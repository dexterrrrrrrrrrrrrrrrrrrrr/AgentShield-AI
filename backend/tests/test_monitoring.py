import asyncio
import json

import pytest
from conftest import csrf_headers, db_call, login, register
from starlette.websockets import WebSocketDisconnect

ORIGIN = {"origin": "http://localhost:3000"}


def user(client, email="alice@example.com"):
    data = register(client, email).json()
    assert login(client, email).status_code == 200
    client.app.state.settings.monitor_poll_seconds = 0.02
    return data["id"]


def emit(client, uid, kind="agent_status", **fields):
    async def call():
        return await client.app.state.monitor.emit(uid, kind, **fields)

    return client.portal.call(call)


def next_event(ws):
    for _ in range(10):
        data = ws.receive_json()
        if data["type"] == "heartbeat":
            ws.send_json({"type": "pong"})
        if data["type"] == "event":
            return data["event"]
    raise AssertionError("No event received")


def test_websocket_authentication_and_origin(client):
    for headers, expected in [
        (ORIGIN, 4401),
        ({"origin": "https://evil.example"}, 4403),
        ({}, 4403),
    ]:
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/api/monitor/ws", headers=headers):
                pass
        assert exc.value.code == expected
    user(client)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/monitor/ws?after=bad", headers=ORIGIN):
            pass


def test_websocket_order_persistence_reconnect_isolation_and_revocation(client):
    alice = user(client)
    bob = register(client, "bob@example.com").json()["id"]
    emit(client, bob, "agent_started")
    a = emit(client, alice, "agent_started")
    b = emit(client, alice, "agent_status")
    with client.websocket_connect("/api/monitor/ws", headers=ORIGIN) as ws:
        assert ws.receive_json()["type"] == "connected"
        assert next_event(ws)["id"] == a["id"]
        assert next_event(ws)["id"] == b["id"]
        c = emit(client, alice, "agent_completed", result="completed", duration=0.2)
        assert next_event(ws)["id"] == c["id"]
    with client.websocket_connect(
        "/api/monitor/ws?after=" + str(b["seq"]), headers=ORIGIN
    ) as ws:
        ws.receive_json()
        assert next_event(ws)["id"] == c["id"]
        client.post("/api/auth/logout", headers=csrf_headers(client))
        with pytest.raises(WebSocketDisconnect) as exc:
            while True:
                data = ws.receive_json()
                if data["type"] == "heartbeat":
                    ws.send_json({"type": "pong"})
        assert exc.value.code == 4401
    assert client.app.state.monitor.connections == {}
    assert (
        db_call(
            client,
            "security_events",
            "count_documents",
            {"user_id": alice, "kind": "monitor_event"},
        )
        == 3
    )


def test_replay_bounded_gap_and_event_schema(client):
    uid = user(client)
    for _ in range(205):
        emit(client, uid)
    row = db_call(client, "monitor_streams", "find_one", {"_id": uid, "user_id": uid})
    assert len(row["events"]) == 200 and row["seq"] == 205

    async def replay():
        return await client.app.state.monitor.replay(uid, 1)

    batch, gap = client.portal.call(replay)
    assert gap and len(batch) == 50
    assert [v["seq"] for v in batch] == list(range(6, 56))
    with client.websocket_connect("/api/monitor/ws?after=1", headers=ORIGIN) as ws:
        assert ws.receive_json()["type"] == "connected"
        assert ws.receive_json()["type"] == "resync_required"
        assert next_event(ws)["seq"] == 6
    event = emit(client, uid, "tool_requested", tool="gsk_do_not_log_payload")
    text = json.dumps(event, default=str)
    assert "gsk_" not in text and event["tool"] == "unknown"
    assert not any(
        k in event for k in ("code", "prompt", "arguments", "response", "reasoning")
    )


def test_concurrent_event_order(client):
    uid = user(client)

    async def concurrent():
        return await asyncio.gather(
            *(client.app.state.monitor.emit(uid, "agent_status") for _ in range(15))
        )

    data = client.portal.call(concurrent)
    assert sorted(v["seq"] for v in data) == list(range(1, 16))
    row = db_call(client, "monitor_streams", "find_one", {"_id": uid, "user_id": uid})
    assert [v["seq"] for v in row["events"]] == list(range(1, 16))


def test_monitor_rest_auth_and_analytics_accuracy(client):
    assert client.get("/api/monitor/summary").status_code == 401
    uid = user(client)
    for turn, status in enumerate(["completed", "completed", "failed"], 1):
        db_call(
            client,
            "agent_messages",
            "insert_one",
            {
                "user_id": uid,
                "session_id": "a" * 32,
                "turn": turn,
                "status": status,
            },
        )
    db_call(
        client,
        "agent_messages",
        "insert_one",
        {"user_id": "b" * 32, "session_id": "b" * 32, "turn": 1, "status": "completed"},
    )
    emit(client, uid, "tool_rejected", decision="DENY")
    data = client.get("/api/monitor/summary")
    assert data.status_code == 200
    assert data.json()["agent_executions"] == {
        "total": 3,
        "successful": 2,
        "failed": 1,
        "by_status": {"completed": 2, "failed": 1},
    }
    assert data.json()["blocked_tool_requests"] == 1
    assert len(client.get("/api/monitor/events").json()["events"]) == 1
    assert client.get("/api/monitor/events?limit=10000").status_code == 422


def test_approval_reject_authorization_duplicates_and_history(client):
    from test_sandbox import MockAdapter

    from app.sandbox.manager import SandboxManager

    user(client)
    client.app.state.settings.sandbox_enabled = True
    adapter = MockAdapter()
    client.app.state.sandbox_manager = SandboxManager(
        client.app.state.settings, adapter
    )
    item = client.post(
        "/api/sandbox/execute", json={"code": "print(1)"}, headers=csrf_headers(client)
    ).json()
    assert client.get("/api/monitor/approvals").json()["pending"][0]["id"] == item["id"]
    assert all(
        "request" not in p and "code" not in p
        for p in client.get("/api/monitor/approvals").json()["pending"]
    )
    register(client, "bob@example.com")
    login(client, "bob@example.com")
    assert client.get("/api/monitor/approvals").json()["pending"] == []
    url = "/api/sandbox/approvals/" + item["id"] + "/reject"
    body = {"reject": True, "request_hash": item["request_hash"]}
    assert client.post(url, json=body, headers=csrf_headers(client)).status_code == 409
    login(client)
    assert client.post(url, json=body).status_code == 403
    assert client.post(url, json=body, headers=csrf_headers(client)).status_code == 200
    assert client.post(url, json=body, headers=csrf_headers(client)).status_code == 409
    assert not adapter.codes
    data = client.get("/api/monitor/summary").json()
    assert data["approvals"]["rejected"] == 1 and data["approvals"]["pending"] == 0
    assert (
        client.get("/api/monitor/approvals").json()["history"][0]["decision"]
        == "rejected"
    )
    assert (
        client.get("/api/monitor/events").json()["events"][0]["kind"] == "tool_rejected"
    )


def test_websocket_input_and_connection_limits(client):
    uid = user(client)
    with client.websocket_connect("/api/monitor/ws", headers=ORIGIN) as ws:
        ws.receive_json()
        ws.send_json({"type": "approve", "payload": "forbidden"})
        with pytest.raises(WebSocketDisconnect):
            while True:
                ws.receive_json()
    client.app.state.monitor.connections[uid] = 4
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/api/monitor/ws", headers=ORIGIN):
            pass
    assert exc.value.code == 1013
    client.app.state.monitor.connections.clear()


def test_slow_client_and_missing_heartbeat_cleanup(client):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.monitoring.api import websocket

    user(client)
    s = client.app.state.settings
    s.monitor_send_timeout = 0.02

    async def never(*args, **kwargs):
        await asyncio.sleep(10)

    ws = SimpleNamespace(
        app=client.app,
        headers=ORIGIN,
        cookies=dict(client.cookies),
        query_params={},
        accept=AsyncMock(),
        send_json=never,
        receive_text=never,
        close=AsyncMock(),
    )
    client.portal.call(websocket, ws)
    ws.close.assert_awaited_with(code=1013)
    assert client.app.state.monitor.connections == {}
    s.monitor_pong_seconds = 0.03
    s.monitor_poll_seconds = 0.01
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    client.portal.call(websocket, ws)
    assert any(call.kwargs.get("code") == 1008 for call in ws.close.await_args_list)
    assert client.app.state.monitor.connections == {}


def test_approval_and_rejection_race_has_one_winner(client):
    from fastapi import HTTPException
    from test_sandbox import request, setup

    from app.sandbox.api import service

    setup(client)
    uid = client.get("/api/auth/me").json()["id"]
    item = request(client).json()

    async def race():
        from types import SimpleNamespace

        svc = service(SimpleNamespace(app=client.app, cookies=dict(client.cookies)))
        return await asyncio.gather(
            svc.approve(uid, item["id"], item["request_hash"]),
            svc.reject(uid, item["id"], item["request_hash"]),
            return_exceptions=True,
        )

    results = client.portal.call(race)
    assert sum(isinstance(v, dict) for v in results) == 1
    failures = [v for v in results if isinstance(v, HTTPException)]
    assert len(failures) == 1 and failures[0].status_code == 409
    summary = client.get("/api/monitor/summary").json()
    assert (
        summary["approvals"].get("approved", 0)
        + summary["approvals"].get("rejected", 0)
        == 1
    )
    assert summary["approvals"]["pending"] == 0
    decisions = [
        e["kind"]
        for e in client.get("/api/monitor/events").json()["events"]
        if e["kind"] in ("tool_approved", "tool_rejected")
    ]
    assert len(decisions) == 1


def test_monitor_failure_is_safe_and_expired_approvals_not_pending(client):
    from datetime import timedelta
    from unittest.mock import AsyncMock, patch

    from pymongo.errors import ServerSelectionTimeoutError

    from app.security import utcnow

    uid = user(client)
    db_call(
        client,
        "execution_logs",
        "insert_one",
        {
            "user_id": uid,
            "status": "pending_approval",
            "approval_status": "pending",
            "approval_expires_at": utcnow() - timedelta(seconds=1),
        },
    )
    data = client.get("/api/monitor/summary").json()
    assert data["approvals"]["expired"] == 1 and data["approvals"]["pending"] == 0
    with (
        patch.object(
            client.app.state.monitor,
            "replay",
            AsyncMock(side_effect=ServerSelectionTimeoutError("private db detail")),
        ),
        client.websocket_connect("/api/monitor/ws", headers=ORIGIN) as ws,
    ):
        assert ws.receive_json()["type"] == "connected"
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1013
    assert client.app.state.monitor.connections == {}


def test_engine_emits_observable_status_before_provider_response(client):
    from app.agents.engine import Engine
    from app.agents.providers import Reply

    uid = user(client)

    async def run():
        waiting = asyncio.Event()
        release = asyncio.Event()

        class BlockedProvider:
            async def complete(self, *args):
                waiting.set()
                await release.wait()
                return Reply(content="Safe conclusion")

        async def notify(kind, **metadata):
            await client.app.state.monitor.emit(uid, kind, **metadata)

        engine = Engine(client.app.state.settings, BlockedProvider())
        task = asyncio.create_task(engine.run("groq", "test", [], [], on_event=notify))
        try:
            await asyncio.wait_for(waiting.wait(), 2)
            assert not task.done()
            events, _ = await client.app.state.monitor.replay(uid, 0)
            assert events[0]["kind"] == "agent_status"
        finally:
            release.set()
            result = await task
        assert result["status"] == "completed"

    client.portal.call(run)


def test_disconnect_releases_connection_slots_repeatedly(client):
    user(client)
    for _ in range(8):
        with client.websocket_connect("/api/monitor/ws", headers=ORIGIN) as ws:
            assert ws.receive_json()["type"] == "connected"
    assert client.app.state.monitor.connections == {}


def test_monitor_timing_configuration_rejects_inconsistent_settings(settings):
    from pydantic import ValidationError

    from app.config import Settings

    with pytest.raises(ValidationError, match="pong timeout"):
        Settings(
            _env_file=None, jwt_secret=settings.jwt_secret, monitor_pong_seconds=10
        )
