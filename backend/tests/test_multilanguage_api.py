"""Real MongoDB/auth with explicitly mocked container/compiler/provider behavior."""

import json

import pytest
from conftest import csrf_headers, db_call, login, register
from test_sandbox import approve

from app.agents.providers import Reply
from app.agents.tools import ToolRejected, ToolRequest, execute, validate_request
from app.sandbox.manager import SandboxManager
from app.sandbox.policy import CodeRequest, fingerprint
from app.sandbox.registry import LANGUAGES


class LanguageAdapter:
    def __init__(self):
        self.calls = []
        self.ready = True
        self.compile_fails = False
        self.output = "mock runtime output"

    def readiness(self, language="python"):
        return {
            "ready": self.ready,
            "code": "READY" if self.ready else "SANDBOX_UNAVAILABLE",
        }

    def execute(self, code, language="python", stdin=""):
        self.calls.append((language, code, stdin))
        compiled = LANGUAGES[language].compilation_required
        return {
            "status": "failed" if self.compile_fails else "completed",
            "compile_status": "failed"
            if self.compile_fails
            else "completed"
            if compiled
            else "not_required",
            "compile_stdout": "",
            "compile_stderr": self.output if self.compile_fails else "",
            "stdout": "" if self.compile_fails else self.output,
            "stderr": "",
            "exit_code": 1 if self.compile_fails else 0,
            "duration": 0.02,
            "execution_duration_ms": 0 if self.compile_fails else 10,
        }


def setup(client, mode="approval"):
    register(client)
    login(client)
    s = client.app.state.settings
    s.sandbox_enabled = True
    s.sandbox_policy = mode
    adapter = LanguageAdapter()
    client.app.state.sandbox_manager = SandboxManager(s, adapter)
    return adapter


def submit(client, language="c", code="int main(void) { return 0; }", **kwargs):
    return client.post(
        "/api/sandbox/execute",
        json={
            "language": language,
            "source_code": code,
            "stdin": "input\n",
            "tool": "execute_code",
            **kwargs,
        },
        headers=csrf_headers(client),
    )


@pytest.mark.parametrize("language", list(LANGUAGES))
def test_registered_languages_approval_result_and_signed_audit(client, language):
    adapter = setup(client)
    pending = submit(client, language=language, code="synthetic source fixture").json()
    assert pending["status"] == "pending_approval"
    assert pending["language"] == language and not adapter.calls
    exact = client.get("/api/sandbox/executions/" + pending["id"]).json()[
        "approval_request"
    ]
    assert exact["language"] == language and exact["stdin"] == "input\n"
    assert exact["code"] == "synthetic source fixture"
    done = approve(client, pending)
    assert done.status_code == 200, done.text
    data = done.json()
    assert data["status"] == "completed" and data["execution_id"] == data["id"]
    assert data["execution_duration_ms"] == 10
    assert adapter.calls == [(language, "synthetic source fixture", "input\n")]
    assert approve(client, pending).status_code == 409
    rows = client.get("/api/monitor/events").json()["events"]
    event = next(row for row in rows if row["kind"] == "sandbox_completed")
    assert event["language"] == language and event["tool"] == "execute_code"
    assert event["integrity"] == "verified"
    assert "synthetic source fixture" not in json.dumps(rows)
    assert "input\\n" not in json.dumps(rows)
    assert (
        client.get("/api/sandbox/executions?language=" + language).json()["executions"][
            0
        ]["id"]
        == data["id"]
    )


def test_languages_metadata_and_readiness_require_auth(client):
    assert client.get("/api/sandbox/languages").status_code == 401
    setup(client)
    rows = client.get("/api/sandbox/languages").json()["languages"]
    assert {row["id"] for row in rows} == set(LANGUAGES)
    assert all(row["limits"]["stdin_bytes"] == 8192 for row in rows)
    assert client.get("/api/sandbox/readiness?language=rust").status_code == 422
    assert client.get("/api/sandbox/executions?language=shell").status_code == 422


@pytest.mark.parametrize(
    "changes",
    [
        {"language": "rust"},
        {"language": "Python"},
        {"language": 1},
        {"code": "conflicting source"},
        {"source_code": " "},
        {"source_code": "\x00"},
        {"source_code": "é" * 17000},
        {"stdin": "é" * 4097},
        {"stdin": "\x00"},
        {"image": "arbitrary"},
        {"compiler_flags": ["-O3"]},
        {"tool": "python_sandbox"},
    ],
)
def test_strict_language_source_stdin_and_control_validation(client, changes):
    adapter = setup(client)
    assert client.post("/api/sandbox/execute", json={"language": "c", "source_code": "int main() {}", "tool": "execute_code", **changes}, headers=csrf_headers(client)).status_code == 422
    assert not adapter.calls
    assert db_call(client, "execution_logs", "count_documents", {}) == 0


def test_approval_binds_language_stdin_runtime_and_compile_deadline(client):
    adapter = setup(client)
    client.app.state.settings.sandbox_user_limit = 20
    for field, value in (("stdin", "altered"), ("language", "cpp")):
        pending = submit(client).json()
        db_call(
            client,
            "sandbox_approvals",
            "update_one",
            {"_id": pending["id"]},
            {"$set": {"request." + field: value}},
        )
        assert approve(client, pending).status_code == 409
    pending = submit(client).json()
    client.app.state.settings.sandbox_compile_timeout += 1
    assert approve(client, pending).status_code == 409
    assert not adapter.calls


def test_compile_failure_is_recorded_without_claiming_execution(client):
    adapter = setup(client, mode="allow")
    adapter.compile_fails = True
    adapter.output = "mock compiler error"
    response = submit(client).json()
    assert response["status"] == "failed"
    assert response["compile_status"] == "failed" and response["stdout"] == ""
    assert response["compile_stderr"] == "mock compiler error"
    assert response["execution_duration_ms"] == 0
    event = next(
        v
        for v in client.get("/api/monitor/events").json()["events"]
        if v["kind"] == "sandbox_failed"
    )
    assert event["compile_status"] == "failed"


def test_stdin_and_compiler_outputs_do_not_leak_credentials(client):
    adapter = setup(client, mode="allow")
    key = client.app.state.settings.jwt_secret.get_secret_value()
    assert submit(client, stdin=key).status_code == 422
    adapter.compile_fails = True
    adapter.output = "compiler diagnostics " + key
    response = submit(client).json()
    assert key not in json.dumps(response)
    assert key not in json.dumps(client.get("/api/sandbox/executions").json())


def test_multilanguage_fail_closed_ownership_and_csrf(client):
    adapter = setup(client)
    assert (
        client.post(
            "/api/sandbox/execute", json={"language": "c", "source_code": "fixture"}
        ).status_code
        == 403
    )
    adapter.ready = False
    item = submit(client).json()
    assert (
        item["status"] == "unavailable"
        and item["error_category"] == "SANDBOX_UNAVAILABLE"
    )
    assert not adapter.calls
    adapter.ready = True
    item = submit(client).json()
    register(client, "other@example.com")
    login(client, "other@example.com")
    assert approve(client, item).status_code == 409
    assert client.get("/api/sandbox/executions/" + item["id"]).status_code == 404
    assert client.get("/api/sandbox/executions?language=c").json()["executions"] == []


def session(client, allowed):
    response = client.post(
        "/api/agent/sessions",
        json={
            "provider": "groq",
            "model": client.app.state.settings.groq_model,
            "allowed_tools": allowed,
        },
        headers=csrf_headers(client),
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_session_permission_is_enforced_even_for_direct_sandbox_api(client):
    adapter = setup(client)
    sid = session(client, ["python_sandbox"])
    assert submit(client, agent_session_id=sid).status_code == 404
    assert not adapter.calls


class CodeProvider:
    def __init__(self):
        self.count = 0

    async def complete(self, provider, model, messages, allowed):
        self.count += 1
        if self.count == 1:
            return Reply(
                calls=[
                    ToolRequest(
                        name="execute_code",
                        arguments={
                            "language": "c",
                            "code": "synthetic source",
                            "stdin": "line",
                        },
                    )
                ]
            )
        assert allowed == []
        return Reply(content="Mock summary of stored approved execution")


def test_agent_language_tool_approval_resolution_and_no_code_replay(client):
    adapter = setup(client)
    provider = CodeProvider()
    client.app.state.agent_engine.providers = provider
    sid = session(client, ["execute_code"])
    turn = client.post(
        f"/api/agent/sessions/{sid}/messages",
        json={"content": "Run a C program"},
        headers=csrf_headers(client),
    ).json()
    assert turn["status"] == "awaiting_approval", turn
    item = client.get("/api/sandbox/executions").json()["executions"][0]
    assert item["language"] == "c" and item["tool"] == "execute_code"
    assert approve(client, item).status_code == 200
    response = client.post(
        f"/api/agent/sessions/{sid}/messages/{turn['id']}/resolve",
        headers=csrf_headers(client),
    )
    assert response.status_code == 200 and response.json()["status"] == "completed"
    assert adapter.calls == [("c", "synthetic source", "line")]
    assert provider.count == 2


def test_execute_code_requires_async_authorized_dispatch():
    request = ToolRequest(
        name="execute_code", arguments={"language": "java", "code": "fixture"}
    )
    with pytest.raises(ToolRejected):
        validate_request(request, ["python_sandbox"])
    with pytest.raises(ToolRejected):
        execute(request, ["execute_code"])


def test_alias_canonicalization_and_legacy_python_fingerprint(settings):
    legacy = CodeRequest(code="print(1)")
    modern = CodeRequest(source_code="print(1)", language="python")
    assert legacy.language == "python" and legacy.stdin == ""
    assert fingerprint(legacy, settings) == fingerprint(modern, settings)
