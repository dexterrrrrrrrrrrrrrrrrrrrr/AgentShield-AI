import asyncio
import json

import groq
import httpx
import pytest
from conftest import csrf_headers, db_call, login, register
from pydantic import SecretStr
from pymongo.errors import ServerSelectionTimeoutError

from app.agents.engine import Engine, redact
from app.agents.providers import ProviderError, Providers, Reply
from app.agents.tools import ToolRejected, ToolRequest, execute


class FakeProvider:
    def __init__(self, calls=False, forever=False):
        self.count = 0
        self.calls, self.forever = calls, forever

    async def complete(self, provider, model, messages, allowed):
        self.count += 1
        if self.forever or (self.calls and self.count == 1):
            return Reply(
                calls=[ToolRequest(name="calculator", arguments={"text": "(12+8)/2"})]
            )
        return Reply(content="The result is 10.")


def start(client, tools=None):
    register(client)
    login(client)
    client.app.state.agent_engine.providers = FakeProvider(calls=True)
    response = client.post(
        "/api/agent/sessions",
        json={
            "provider": "groq",
            "model": client.app.state.settings.groq_model,
            "allowed_tools": tools if tools is not None else ["calculator"],
        },
        headers=csrf_headers(client),
    )
    assert response.status_code == 201
    return response.json()["id"]


def send(client, sid, text="Calculate 12+8 divided by 2"):
    return client.post(
        f"/api/agent/sessions/{sid}/messages",
        json={"content": text},
        headers=csrf_headers(client),
    )


def test_session_workflow_and_real_mongo_persistence(client):
    sid = start(client)
    result = send(client, sid)
    assert result.status_code == 200
    turn = result.json()
    assert turn["status"] == "completed" and "10" in turn["assistant_content"]
    assert [e["kind"] for e in turn["events"]] == [
        "model_request",
        "tool_request",
        "tool_response",
        "model_request",
        "completed",
    ]
    assert "system" not in json.dumps(turn).lower()
    stored = db_call(client, "agent_messages", "find_one", {"session_id": sid})
    assert stored["assistant_content"] == turn["assistant_content"]
    assert stored["user_id"]
    assert (
        client.get(f"/api/agent/sessions/{sid}/messages").json()["messages"][0]["id"]
        == turn["id"]
    )
    assert client.get(f"/api/agent/sessions/{sid}/events").json()["executions"][0][
        "events"
    ]
    assert len(client.get("/api/agent/sessions?limit=1").json()["sessions"]) == 1
    assert send(client, sid, "Continue").json()["status"] == "completed"
    assert (
        client.delete(
            f"/api/agent/sessions/{sid}", headers=csrf_headers(client)
        ).status_code
        == 204
    )
    assert (
        db_call(client, "agent_messages", "count_documents", {"session_id": sid}) == 0
    )
    assert client.get(f"/api/agent/sessions/{sid}/messages").status_code == 404


def test_cross_user_and_missing_authentication(client):
    assert client.get("/api/agent/sessions").status_code == 401
    sid = start(client)
    register(client, "bob@example.com")
    login(client, "bob@example.com")
    assert client.get("/api/agent/sessions").json()["sessions"] == []
    assert client.get(f"/api/agent/sessions/{sid}/messages").status_code == 404
    assert client.get(f"/api/agent/sessions/{sid}/events").status_code == 404
    assert send(client, sid).status_code == 404
    assert (
        client.delete(
            f"/api/agent/sessions/{sid}", headers=csrf_headers(client)
        ).status_code
        == 404
    )


def test_session_input_csrf_and_limits(client):
    sid = start(client)
    assert (
        client.post(
            f"/api/agent/sessions/{sid}/messages", json={"content": "x"}
        ).status_code
        == 403
    )
    assert send(client, sid, " " * 10).status_code == 422
    assert send(client, sid, "x" * 4001).status_code == 422
    assert (
        client.post(
            f"/api/agent/sessions/{sid}/messages", content="x" * 16385
        ).status_code
        == 413
    )
    assert client.get("/api/agent/sessions?limit=5000").status_code == 422
    assert (
        client.post(
            "/api/agent/sessions",
            json={"provider": "groq", "model": "unauthorized-model"},
            headers=csrf_headers(client),
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/agent/sessions",
            json={
                "provider": "groq",
                "model": client.app.state.settings.groq_model,
                "allowed_tools": ["shell"],
            },
            headers=csrf_headers(client),
        ).status_code
        == 422
    )
    client.app.state.settings.agent_user_limit = 1
    assert send(client, sid).status_code == 200
    assert send(client, sid).status_code == 429


def test_busy_and_turn_cap(client):
    sid = start(client)
    client.app.state.agent_active = 2
    assert send(client, sid).status_code == 429
    client.app.state.agent_active = 0
    db_call(
        client, "agent_sessions", "update_one", {"_id": sid}, {"$set": {"turns": 50}}
    )
    assert send(client, sid).status_code == 409


def test_disallowed_tool_is_audited(client):
    sid = start(client, [])
    result = send(client, sid).json()
    assert result["status"] == "failed"
    assert any(e["kind"] == "tool_denied" for e in result["events"])


def test_missing_provider_key_and_database_failure(client, monkeypatch):
    sid = start(client)
    client.app.state.agent_engine.providers = Providers(client.app.state.settings)
    result = send(client, sid).json()
    assert (
        result["status"] == "failed" and "not configured" in result["assistant_content"]
    )

    async def fail(*args, **kwargs):
        raise ServerSelectionTimeoutError("private diagnostics")

    monkeypatch.setattr(type(client.app.state.db.agent_sessions), "find_one", fail)
    response = client.get(f"/api/agent/sessions/{sid}/messages")
    assert response.status_code == 503 and "private" not in response.text


@pytest.mark.parametrize(
    "name,text,expected",
    [
        ("calculator", "(2+3)*4", "20"),
        ("format_json", '{"a":1}', '"a": 1'),
        ("summarize_text", "One. Two. Three. Four.", "One. Two. Three."),
    ],
)
def test_safe_tools(name, text, expected):
    assert expected in execute(ToolRequest(name=name, arguments={"text": text}), [name])


@pytest.mark.parametrize(
    "name,text",
    [
        ("calculator", "__import__('os').system('id')"),
        ("calculator", "2**100000"),
        ("calculator", "1/0"),
        ("calculator", "True"),
        ("calculator", "1e99"),
        ("format_json", "not json"),
        ("format_json", "NaN"),
        ("shell", "pwd"),
    ],
)
def test_tool_rejection(name, text):
    with pytest.raises((ToolRejected, ValueError)):
        execute(
            ToolRequest(name=name, arguments={"text": text}),
            ["calculator", "format_json"],
        )


def test_tool_input_schema():
    with pytest.raises(ValueError):
        execute(
            ToolRequest(name="calculator", arguments={"text": "1+1", "path": "/tmp"}),
            ["calculator"],
        )


@pytest.mark.parametrize("tool_limit,iteration_limit", [(0, 4), (3, 1)])
def test_engine_budgets(settings, tool_limit, iteration_limit):
    settings.agent_max_tool_calls = tool_limit
    settings.agent_max_iterations = iteration_limit
    result = asyncio.run(
        Engine(settings, FakeProvider(forever=True)).run(
            "groq",
            settings.groq_model,
            [{"role": "user", "content": "calculate"}],
            ["calculator"],
        )
    )
    assert result["status"] == "failed" and "limit" in result["answer"]


def test_total_timeout(settings):
    settings.agent_request_timeout = 0.01
    p = FakeProvider()

    async def wait(*args):
        await asyncio.sleep(1)

    p.complete = wait
    result = asyncio.run(Engine(settings, p).run("groq", settings.groq_model, [], []))
    assert result["status"] == "failed" and "timed out" in result["answer"]


def test_redaction(settings):
    assert (
        redact("gsk_very-secret password=hidden Bearer ey.abc.def", [])
        == "[REDACTED] [REDACTED] [REDACTED]"
    )
    assert (
        redact(
            settings.jwt_secret.get_secret_value(),
            [settings.jwt_secret.get_secret_value()],
        )
        == "[REDACTED]"
    )


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, "credentials"),
        (429, "rate limit"),
        (404, "unavailable"),
        (503, "could not complete"),
    ],
)
def test_official_groq_error_mapping(settings, monkeypatch, status, expected):
    settings.groq_api_key = SecretStr("synthetic-test-key")
    real = groq.AsyncGroq

    def handler(request):
        return httpx.Response(
            status,
            json={"error": {"message": "private provider data", "type": "error"}},
            request=request,
        )

    monkeypatch.setattr(
        groq,
        "AsyncGroq",
        lambda **kw: real(
            **{k: v for k, v in kw.items() if k != "http_client"},
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(handler), follow_redirects=False
            ),
        ),
    )
    with pytest.raises(ProviderError, match=expected):
        asyncio.run(Providers(settings).complete("groq", settings.groq_model, [], []))


def test_official_groq_success_and_timeout(settings, monkeypatch):
    settings.groq_api_key = SecretStr("synthetic-test-key")
    real = groq.AsyncGroq

    def handler(request):
        if "/models/" in request.url.path:
            return httpx.Response(
                200, json={"id": settings.groq_model, "object": "model"}
            )
        return httpx.Response(
            200,
            json={
                "id": "test",
                "object": "chat.completion",
                "created": 1,
                "model": settings.groq_model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Mocked response"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    monkeypatch.setattr(
        groq,
        "AsyncGroq",
        lambda **kw: real(
            **{k: v for k, v in kw.items() if k != "http_client"},
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(handler), follow_redirects=False
            ),
        ),
    )
    assert (
        asyncio.run(
            Providers(settings).complete("groq", settings.groq_model, [], [])
        ).content
        == "Mocked response"
    )

    def timeout(request):
        raise httpx.ReadTimeout("private", request=request)

    monkeypatch.setattr(
        groq,
        "AsyncGroq",
        lambda **kw: real(
            **{k: v for k, v in kw.items() if k != "http_client"},
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(timeout), follow_redirects=False
            ),
        ),
    )
    with pytest.raises(ProviderError, match="timed out"):
        asyncio.run(Providers(settings).complete("groq", settings.groq_model, [], []))


def test_ollama_is_opt_in_and_loopback_only(settings):
    with pytest.raises(ProviderError, match="disabled"):
        asyncio.run(
            Providers(settings).complete("ollama", settings.ollama_model, [], [])
        )
    from app.config import Settings

    with pytest.raises(ValueError):
        Settings(
            _env_file=None,
            jwt_secret=settings.jwt_secret,
            ollama_url="http://untrusted.example",
        )


def test_json_numeric_overflow_is_rejected():
    with pytest.raises(ToolRejected):
        execute(
            ToolRequest(name="format_json", arguments={"text": "1e999"}),
            ["format_json"],
        )


def test_ollama_mocked_service_errors_and_response(settings, monkeypatch):
    settings.ollama_enabled = True
    original = httpx.AsyncClient

    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": settings.ollama_model}]}
            )
        return httpx.Response(
            200, json={"message": {"content": "Local mocked response"}}
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(**kw, transport=httpx.MockTransport(handler)),
    )
    assert (
        asyncio.run(
            Providers(settings).complete("ollama", settings.ollama_model, [], [])
        ).content
        == "Local mocked response"
    )
    with pytest.raises(ProviderError, match="not installed"):
        asyncio.run(Providers(settings).complete("ollama", "missing-model", [], []))

    def offline(request):
        raise httpx.ConnectError("private service details", request=request)

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(**kw, transport=httpx.MockTransport(offline)),
    )
    with pytest.raises(ProviderError, match="unreachable"):
        asyncio.run(
            Providers(settings).complete("ollama", settings.ollama_model, [], [])
        )
