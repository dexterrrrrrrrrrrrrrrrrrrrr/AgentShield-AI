"""Real MongoDB/auth journey tests with explicit mocked provider/container I/O."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from conftest import csrf_headers, db_call, login, register
from pymongo.errors import ServerSelectionTimeoutError
from test_sandbox import approve, setup

from app.agents.providers import ProviderError, Reply
from app.agents.tools import ToolRequest
from app.security import encode_token, utcnow


class ApprovalProvider:
    def __init__(self):
        self.calls = []
        self.fail_final = False
        self.forbidden_final = False

    async def complete(self, provider, model, messages, allowed):
        self.calls.append({"messages": messages, "allowed": allowed})
        if len(self.calls) == 1 or self.forbidden_final:
            return Reply(
                calls=[
                    ToolRequest(name="python_sandbox", arguments={"code": "print(1)"})
                ]
            )
        if self.fail_final:
            raise ProviderError("Mock finalization provider unavailable", 503)
        await asyncio.sleep(0.02)
        return Reply(
            content="Final model summary from the actual recorded sandbox outcome."
        )


def create_session(client):
    response = client.post(
        "/api/agent/sessions",
        json={
            "provider": "groq",
            "model": client.app.state.settings.groq_model,
            "allowed_tools": ["python_sandbox"],
        },
        headers=csrf_headers(client),
    )
    assert response.status_code == 201
    return response.json()["id"]


def pause(client, ready=True):
    adapter = setup(client, ready=ready)
    provider = ApprovalProvider()
    client.app.state.agent_engine.providers = provider
    sid = create_session(client)
    response = client.post(
        f"/api/agent/sessions/{sid}/messages",
        json={"content": "Run the approved Python task"},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200
    turn = response.json()
    execution = db_call(client, "execution_logs", "find_one", {"agent_session_id": sid})
    item = {"id": execution["_id"], "request_hash": execution["request_hash"]}
    return sid, turn, item, adapter, provider


def resolve(client, sid, mid, headers=None, **kwargs):
    return client.post(
        f"/api/agent/sessions/{sid}/messages/{mid}/resolve",
        headers=headers or csrf_headers(client),
        **kwargs,
    )


def reject(client, item):
    return client.post(
        f"/api/sandbox/approvals/{item['id']}/reject",
        json={"reject": True, "request_hash": item["request_hash"]},
        headers=csrf_headers(client),
    )


def test_pause_approve_resolve_updates_original_turn_without_code_replay(client):
    sid, turn, item, adapter, provider = pause(client)
    assert turn["status"] == "awaiting_approval" and turn["duration"] >= 0
    assert turn["pending_execution_ids"] == [item["id"]]
    assert len(provider.calls) == 1 and adapter.codes == []
    events = client.get("/api/monitor/events").json()["events"]
    assert not any(e["kind"] == "agent_completed" for e in events)
    assert resolve(client, sid, turn["id"]).status_code == 409
    assert (
        client.post(
            f"/api/agent/sessions/{sid}/messages",
            json={"content": "Start another task"},
            headers=csrf_headers(client),
        ).status_code
        == 409
    )
    assert approve(client, item).status_code == 200
    assert adapter.codes == ["print(1)"] and len(provider.calls) == 1
    result = resolve(client, sid, turn["id"])
    assert result.status_code == 200 and result.json()["status"] == "completed"
    assert (
        result.json()["id"] == turn["id"]
        and result.json()["pending_execution_ids"] == []
    )
    assert result.json()["duration"] >= turn["duration"]
    assert len(provider.calls) == 2 and provider.calls[-1]["allowed"] == []
    assert "mock output" in json.dumps(provider.calls[-1]["messages"])
    assert resolve(client, sid, turn["id"]).status_code == 409
    assert adapter.codes == ["print(1)"] and len(provider.calls) == 2
    rows = client.get(f"/api/agent/sessions/{sid}/messages").json()["messages"]
    assert len(rows) == 1 and rows[0]["status"] == "completed"
    assert (
        client.get("/api/monitor/summary").json()["agent_executions"]["successful"] == 1
    )
    stored = db_call(client, "execution_logs", "find_one", {"_id": item["id"]})
    assert stored["agent_turn_id"] == turn["id"]
    public = json.dumps(
        [
            result.json(),
            client.get(f"/api/agent/sessions/{sid}/messages").json(),
            client.get("/api/sandbox/executions").json(),
        ]
    )
    assert not any(
        k in public
        for k in [
            "_holder",
            "_iterations",
            "_tool_count",
            "agent_turn_id",
            "lease_holder",
        ]
    )


def test_rejected_request_finishes_as_failure_without_calling_model_again(client):
    sid, turn, item, adapter, provider = pause(client)
    assert reject(client, item).status_code == 200
    result = resolve(client, sid, turn["id"])
    assert result.status_code == 200 and result.json()["status"] == "failed"
    assert "rejected" in result.json()["assistant_content"]
    assert len(provider.calls) == 1 and adapter.codes == []
    assert resolve(client, sid, turn["id"]).status_code == 409
    assert (
        client.post(
            f"/api/agent/sessions/{sid}/messages",
            json={"content": "Continue safely"},
            headers=csrf_headers(client),
        ).status_code
        == 200
    )


def test_expiry_can_be_resolved_and_expired_payload_is_not_returned(client):
    sid, turn, item, adapter, provider = pause(client)
    db_call(
        client,
        "sandbox_approvals",
        "update_one",
        {"_id": item["id"]},
        {"$set": {"expires_at": utcnow() - timedelta(seconds=1)}},
    )
    detail = client.get("/api/sandbox/executions/" + item["id"]).json()
    assert "approval_request" not in detail
    result = resolve(client, sid, turn["id"])
    assert result.status_code == 200 and result.json()["status"] == "failed"
    assert "expired" in result.json()["assistant_content"]
    assert adapter.codes == [] and len(provider.calls) == 1
    assert (
        client.post(
            f"/api/agent/sessions/{sid}/messages",
            json={"content": "Continue after expiry"},
            headers=csrf_headers(client),
        ).status_code
        == 200
    )


def test_unavailable_sandbox_does_not_become_fabricated_success(client):
    sid, turn, item, adapter, provider = pause(client, ready=False)
    assert turn["status"] == "failed" and "unavailable" in turn["assistant_content"]
    assert adapter.codes == [] and len(provider.calls) == 1
    assert not any(
        e["kind"] == "agent_completed"
        for e in client.get("/api/monitor/events").json()["events"]
    )


def test_resolution_is_authenticated_csrf_protected_and_owner_bound(client):
    sid, turn, item, adapter, provider = pause(client)
    assert (
        client.post(
            f"/api/agent/sessions/{sid}/messages/{turn['id']}/resolve"
        ).status_code
        == 403
    )
    assert (
        resolve(
            client, sid, turn["id"], json={"approve": True, "execution_id": item["id"]}
        ).status_code
        == 422
    )
    register(client, "bob@example.com")
    login(client, "bob@example.com")
    assert resolve(client, sid, turn["id"]).status_code == 404
    assert client.get("/api/monitor/approvals").json()["pending"] == []
    assert client.get("/api/monitor/events").json()["events"] == []
    assert adapter.codes == [] and len(provider.calls) == 1


def test_owned_but_unrelated_execution_cannot_replace_bound_result(client):
    sid, turn, item, adapter, provider = pause(client)
    unrelated = client.post(
        "/api/sandbox/execute",
        json={"code": "print(2)", "agent_session_id": sid},
        headers=csrf_headers(client),
    ).json()
    db_call(
        client,
        "agent_messages",
        "update_one",
        {"_id": turn["id"]},
        {"$set": {"pending_execution_ids": [unrelated["id"]]}},
    )
    assert resolve(client, sid, turn["id"]).status_code == 409
    assert adapter.codes == [] and len(provider.calls) == 1


def test_resolution_claim_has_one_winner(client):
    sid, turn, item, adapter, provider = pause(client)
    assert approve(client, item).status_code == 200
    headers = csrf_headers(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: resolve(client, sid, turn["id"], headers=headers).status_code,
                range(2),
            )
        )
    assert sorted(results) == [200, 409]
    assert adapter.codes == ["print(1)"] and len(provider.calls) == 2
    assert (
        db_call(client, "agent_sessions", "find_one", {"_id": sid})["status"] == "idle"
    )


def test_resolution_cannot_reset_the_iteration_budget(client):
    client.app.state.settings.agent_max_iterations = 1
    sid, turn, item, adapter, provider = pause(client)
    assert approve(client, item).status_code == 200
    result = resolve(client, sid, turn["id"])
    assert (
        result.json()["status"] == "failed"
        and "iteration limit" in result.json()["assistant_content"]
    )
    assert adapter.codes == ["print(1)"] and len(provider.calls) == 1


def test_resolution_tools_remain_disabled_even_if_provider_requests_them(client):
    sid, turn, item, adapter, provider = pause(client)
    assert approve(client, item).status_code == 200
    provider.forbidden_final = True
    result = resolve(client, sid, turn["id"])
    assert result.json()["status"] == "failed"
    assert any(e["kind"] == "tool_denied" for e in result.json()["events"])
    assert adapter.codes == ["print(1)"]


def test_final_provider_failure_does_not_replay_execution(client):
    sid, turn, item, adapter, provider = pause(client)
    assert approve(client, item).status_code == 200
    provider.fail_final = True
    result = resolve(client, sid, turn["id"])
    assert (
        result.json()["status"] == "failed"
        and "unavailable" in result.json()["assistant_content"]
    )
    assert resolve(client, sid, turn["id"]).status_code == 409
    assert adapter.codes == ["print(1)"]


def test_database_failure_on_resolution_is_safe_and_recoverable(client, monkeypatch):
    sid, turn, item, adapter, provider = pause(client)
    assert approve(client, item).status_code == 200
    collection = type(client.app.state.db.agent_messages)
    original = collection.find_one

    async def fail(self, *args, **kwargs):
        if self.name == "agent_messages":
            raise ServerSelectionTimeoutError("private connection diagnostic")
        return await original(self, *args, **kwargs)

    with monkeypatch.context() as context:
        context.setattr(collection, "find_one", fail)
        response = resolve(client, sid, turn["id"])
        assert response.status_code == 503 and "private connection" not in response.text
    assert resolve(client, sid, turn["id"]).json()["status"] == "completed"
    assert adapter.codes == ["print(1)"]


def test_clearing_waiting_conversation_cancels_pending_code(client):
    sid, turn, item, adapter, provider = pause(client)
    assert (
        client.delete(
            f"/api/agent/sessions/{sid}", headers=csrf_headers(client)
        ).status_code
        == 204
    )
    pending = db_call(client, "sandbox_approvals", "find_one", {"_id": item["id"]})
    assert pending["state"] == "cancelled" and "request" not in pending
    assert approve(client, item).status_code == 409 and adapter.codes == []
    assert client.get(f"/api/agent/sessions/{sid}/messages").status_code == 404
    assert (
        db_call(client, "execution_logs", "find_one", {"_id": item["id"]})[
            "error_category"
        ]
        == "SESSION_DELETED"
    )


def test_stale_finalizer_cannot_release_newer_session_lease(client):
    from test_agents import send, start

    sid = start(client)

    class LeaseProvider:
        async def complete(self, *args):
            await client.app.state.db.agent_sessions.update_one(
                {"_id": sid},
                {
                    "$set": {
                        "lease_holder": "new-holder",
                        "lease_until": utcnow() + timedelta(seconds=120),
                    }
                },
            )
            return Reply(content="The original request completed.")

    client.app.state.agent_engine.providers = LeaseProvider()
    assert send(client, sid).status_code == 200
    saved = db_call(client, "agent_sessions", "find_one", {"_id": sid})
    assert saved["lease_holder"] == "new-holder" and saved["status"] == "running"
    assert send(client, sid).status_code == 409


def test_csrf_cookie_reuse_and_login_boundary(client):
    first = client.get("/api/auth/csrf").json()["csrf_token"]
    again = client.get("/api/auth/csrf")
    assert again.json()["csrf_token"] == first and "set-cookie" not in again.headers
    register(client)
    response = login(client)
    assert response.status_code == 200 and response.json()["session_expires_at"]
    current = client.get("/api/auth/csrf").json()["csrf_token"]
    assert current != first
    assert client.get("/api/auth/csrf").json()["csrf_token"] == current
    assert (
        client.post(
            "/api/auth/logout",
            headers={"Origin": "http://localhost:3000", "X-CSRF-Token": first},
        ).status_code
        == 403
    )
    assert (
        client.get("/api/auth/me").json()["session_expires_at"]
        == response.json()["session_expires_at"]
    )


def test_expired_csrf_is_replaced_without_exposing_access_token(client):
    register(client)
    login(client)
    settings = client.app.state.settings
    expired = encode_token(
        settings,
        subject="",
        token_id="synthetic-csrf-id",
        use="csrf",
        expires=utcnow() - timedelta(seconds=1),
    )
    client.cookies.set(
        settings.csrf_cookie, expired, domain="testserver.local", path="/"
    )
    fresh = client.get("/api/auth/csrf").json()["csrf_token"]
    assert fresh != expired
    assert (
        client.post("/api/auth/logout", headers=csrf_headers(client)).status_code == 204
    )


def test_consumed_marker_survives_original_expiry_without_granting_replay(client):
    from unittest.mock import patch

    from app.sandbox.service import SandboxService

    sid, turn, item, adapter, provider = pause(client)
    deadline = utcnow() + timedelta(seconds=60)
    db_call(
        client,
        "sandbox_approvals",
        "update_one",
        {"_id": item["id"]},
        {"$set": {"expires_at": deadline}},
    )
    headers = csrf_headers(client)
    original = SandboxService.run

    async def during_execution(self, uid, eid, payload):
        marker = await self.db.sandbox_approvals.find_one({"_id": eid, "user_id": uid})
        assert marker["state"] == "used" and "request" not in marker
        assert marker["expires_at"] > deadline + timedelta(seconds=30)
        # Controlled clock + TTL sweep model the old deadline passing before run.
        late = deadline + timedelta(seconds=1)
        await self.db.sandbox_approvals.delete_many(
            {"_id": eid, "expires_at": {"$lte": late}}
        )
        with patch("app.agents.api.utcnow", return_value=late):
            response = await asyncio.to_thread(
                client.post,
                f"/api/agent/sessions/{sid}/messages/{turn['id']}/resolve",
                headers=headers,
            )
        assert response.status_code == 409 and "being recorded" in response.text
        # Even after metadata retention expires, the durable approved field wins.
        await self.db.sandbox_approvals.delete_one({"_id": eid, "user_id": uid})
        response = await asyncio.to_thread(
            client.post,
            f"/api/agent/sessions/{sid}/messages/{turn['id']}/resolve",
            headers=headers,
        )
        assert response.status_code == 409 and "being recorded" in response.text
        return await original(self, uid, eid, payload)

    with patch.object(SandboxService, "run", during_execution):
        assert approve(client, item).status_code == 200
    assert approve(client, item).status_code == 409
    assert resolve(client, sid, turn["id"]).json()["status"] == "completed"
    assert adapter.codes == ["print(1)"]


def test_awaiting_and_replay_attempts_still_count_against_rate_limit(client):
    sid, turn, item, adapter, provider = pause(client)
    client.app.state.settings.agent_user_limit = 1
    assert (
        client.post(
            f"/api/agent/sessions/{sid}/messages",
            json={"content": "Blocked pending retry"},
            headers=csrf_headers(client),
        ).status_code
        == 429
    )
    assert resolve(client, sid, turn["id"]).status_code == 429
    assert adapter.codes == []


def test_lost_lease_prevents_a_tool_dispatch(client):
    from test_agents import send, start

    sid = start(client)

    class LostLeaseProvider:
        async def complete(self, *args):
            await client.app.state.db.agent_sessions.update_one(
                {"_id": sid}, {"$set": {"lease_holder": "recovered-holder"}}
            )
            return Reply(
                calls=[ToolRequest(name="calculator", arguments={"text": "1+1"})]
            )

    client.app.state.agent_engine.providers = LostLeaseProvider()
    result = send(client, sid)
    assert result.status_code == 200 and result.json()["status"] == "failed"
    assert not any(e["kind"] == "tool_response" for e in result.json()["events"])
    assert (
        db_call(client, "agent_sessions", "find_one", {"_id": sid})["lease_holder"]
        == "recovered-holder"
    )
