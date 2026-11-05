"""Mocked Docker contract tests + real MongoDB/auth tests. No untrusted host execution."""

import asyncio
import json
import struct
import time
from datetime import timedelta
from unittest.mock import Mock

import pytest
from conftest import csrf_headers, db_call, login, register

from app.sandbox.manager import DockerAdapter, SandboxManager, Unavailable
from app.sandbox.policy import Decision, evaluate
from app.security import utcnow


class MockAdapter:
    def __init__(self, ready=True):
        self.ready = ready
        self.codes = []

    def readiness(self):
        return {
            "ready": self.ready,
            "code": "READY" if self.ready else "SANDBOX_UNAVAILABLE",
        }

    def execute(self, code):
        self.codes.append(code)
        return {
            "status": "completed",
            "stdout": "mock output\n",
            "stderr": "",
            "exit_code": 0,
            "duration": 0.01,
            "truncated": False,
        }


def setup(client, ready=True, mode="approval"):
    register(client)
    login(client)
    s = client.app.state.settings
    s.sandbox_enabled = True
    s.sandbox_policy = mode
    adapter = MockAdapter(ready)
    client.app.state.sandbox_manager = SandboxManager(s, adapter)
    return adapter


def request(client, code="print(1)", **extra):
    return client.post(
        "/api/sandbox/execute",
        json={"code": code, **extra},
        headers=csrf_headers(client),
    )


def approve(client, item, **changes):
    return client.post(
        "/api/sandbox/approvals/" + item["id"],
        json={"approve": True, "request_hash": item["request_hash"], **changes},
        headers=csrf_headers(client),
    )


def test_approval_exact_request_single_use_and_logs(client):
    adapter = setup(client)
    item = request(client).json()
    assert (
        item["policy_decision"] == "REQUIRE_APPROVAL"
        and item["status"] == "pending_approval"
    )
    assert adapter.codes == []
    detail = client.get("/api/sandbox/executions/" + item["id"]).json()
    assert detail["approval_request"]["code"] == "print(1)"
    assert approve(client, item, approve=False).status_code == 422
    assert approve(client, item, request_hash="a" * 64).status_code == 409
    result = approve(client, item)
    assert result.status_code == 200 and result.json()["stdout"] == "mock output\n"
    assert adapter.codes == ["print(1)"]
    assert approve(client, item).status_code == 409
    stored = db_call(client, "execution_logs", "find_one", {"_id": item["id"]})
    assert stored["user_id"] and stored["completed_at"] and "code" not in stored
    assert (
        db_call(client, "sandbox_approvals", "find_one", {"_id": item["id"]}).get(
            "request"
        )
        is None
    )
    assert len(client.get("/api/sandbox/executions?limit=1").json()["executions"]) == 1


def test_approval_expiry_policy_change_and_ownership(client):
    adapter = setup(client)
    item = request(client).json()
    client.app.state.settings.sandbox_memory_mb = 256
    assert approve(client, item).status_code == 409
    client.app.state.settings.sandbox_memory_mb = 128
    db_call(
        client,
        "sandbox_approvals",
        "update_one",
        {"_id": item["id"]},
        {"$set": {"expires_at": utcnow() - timedelta(seconds=1)}},
    )
    assert approve(client, item).status_code == 409
    foreign = request(client).json()
    register(client, "bob@example.com")
    login(client, "bob@example.com")
    assert client.get("/api/sandbox/executions/" + foreign["id"]).status_code == 404
    assert client.get("/api/sandbox/executions").json()["executions"] == []
    assert approve(client, foreign).status_code == 409
    assert not adapter.codes


def test_auth_csrf_input_quotas(client):
    assert client.get("/api/sandbox/readiness").status_code == 401
    assert client.get("/api/sandbox/executions").status_code == 401
    setup(client)
    assert (
        client.post("/api/sandbox/execute", json={"code": "print(1)"}).status_code
        == 403
    )
    assert request(client, image="evil").status_code == 422
    assert request(client, "é" * 20000).status_code == 422
    assert request(client, "a" * 32769).status_code == 422
    assert request(client, " ", tool="shell").status_code == 422
    assert request(client, agent_session_id="a" * 32).status_code == 404
    db_call(client, "security_events", "delete_many", {})
    client.app.state.settings.sandbox_user_limit = 1
    assert request(client).status_code == 200
    assert request(client).status_code == 429


def test_fail_closed_and_deny(client):
    adapter = setup(client, False)
    item = request(client).json()
    assert (
        item["status"] == "unavailable"
        and item["error_category"] == "SANDBOX_UNAVAILABLE"
    )
    assert not adapter.codes
    adapter.ready = True
    client.app.state.settings.sandbox_policy = "deny"
    assert request(client).json()["policy_decision"] == "DENY"
    assert not adapter.codes
    client.app.state.settings.sandbox_policy = "allow"
    assert request(client).json()["status"] == "completed"
    assert adapter.codes == ["print(1)"]


def fake_client(settings, output=b"hello\n", bad=False):
    created = []

    def create(**kw):
        sock = Mock()
        sock._sock = Mock()
        sock._sock.recv.side_effect = [
            b"\x01\0\0\0" + struct.pack(">I", len(output)) + output,
            b"",
        ]
        c = Mock()
        c.attrs = {
            "Config": {
                "User": kw["user"],
                "Env": ["PATH=/usr/local/bin:/usr/bin:/bin"],
            },
            "HostConfig": {
                "ReadonlyRootfs": kw["read_only"],
                "Privileged": bad,
                "NetworkMode": kw["network_mode"],
                "PidMode": "",
                "CgroupnsMode": "private",
                "MemorySwap": kw["memswap_limit"],
                "CapAdd": None,
                "IpcMode": "private",
                "Binds": None,
                "CapDrop": kw["cap_drop"],
                "SecurityOpt": kw["security_opt"],
                "Memory": kw["mem_limit"],
                "PidsLimit": kw["pids_limit"],
                "NanoCpus": kw["nano_cpus"],
            },
            "Mounts": [],
            "State": {"Running": True},
        }
        c.attach_socket.return_value = sock
        c.wait.return_value = {"StatusCode": 0}
        created.append((kw, c, sock))
        return c

    client = Mock()
    client.containers.list.return_value = []
    client.containers.create.side_effect = create
    client.info.return_value = {
        "MemoryLimit": True,
        "SwapLimit": True,
        "PidsLimit": True,
        "CPUCfsQuota": True,
        "CgroupDriver": "systemd",
        "CgroupVersion": "2",
    }
    return client, created


def test_mock_container_restrictions_and_cleanup(settings):
    client, created = fake_client(settings)
    adapter = DockerAdapter(settings, lambda: client)
    result = adapter._run(client, "print(1)")
    assert result["stdout"] == "hello\n" and result["exit_code"] == 0
    kw, c, sock = created[0]
    assert kw["image"].startswith("python@sha256:") and kw["user"] == "65534:65534"
    assert kw["environment"] == {} and kw["volumes"] == {} and kw["mounts"] == []
    assert kw["use_config_proxy"] is False
    assert kw["read_only"] and not kw["privileged"] and kw["network_disabled"]
    assert kw["network_mode"] == "none" and kw["cap_drop"] == ["ALL"]
    assert kw["pids_limit"] == 32 and kw["nano_cpus"] == 1000000000
    assert kw["mem_limit"] == 134217728 and kw["memswap_limit"] == 134217728
    assert kw["ipc_mode"] == "private" and kw["cgroupns"] == "private"
    assert kw["log_config"]["Type"] == "none" and "noexec" in kw["tmpfs"]["/tmp"]
    c.remove.assert_called_once_with(force=True, v=True)
    sock.close.assert_called_once()


def test_mock_readiness_checks_effective_limits_and_daemon(settings):
    values = {
        "uid": 65534,
        "cgroup_path": "/",
        "memory": "134217728",
        "swap": "0",
        "pids": "32",
        "cpu": "100000 100000",
        "ro": True,
        "workspace": True,
        "network": True,
        "nnp": True,
        "caps": True,
        "seccomp": True,
    }
    client, created = fake_client(settings, json.dumps(values).encode())
    assert DockerAdapter(settings, lambda: client).readiness()["ready"]
    values["memory"] = "34359738368"
    client, _ = fake_client(settings, json.dumps(values).encode())
    adapter = DockerAdapter(settings, lambda: client)
    assert not adapter.readiness()["ready"]
    with pytest.raises(Unavailable):
        adapter.execute("print(1)")
    assert all(v[0]["command"][-1] != "print(1)" for v in created)
    client = Mock()
    client.info.side_effect = RuntimeError("private diagnostic")
    assert DockerAdapter(settings, lambda: client).readiness() == {
        "ready": False,
        "code": "SANDBOX_UNAVAILABLE",
    }
    client, _ = fake_client(settings)
    client.info.return_value["CgroupDriver"] = "none"
    assert not DockerAdapter(settings, lambda: client).readiness()["ready"]
    client.containers.create.assert_not_called()


def test_mock_timeout_output_limit_and_cleanup_on_error(settings, monkeypatch):
    client, created = fake_client(settings, b"x" * 2048)
    settings.sandbox_output_bytes = 1024
    adapter = DockerAdapter(settings, lambda: client)
    result = adapter._run(client, "print(1)")
    assert result["status"] == "output_limit" and len(result["stdout"]) == 1024
    created[-1][1].kill.assert_called_once()
    created[-1][1].remove.assert_called_once()
    monkeypatch.setattr(
        adapter, "_frames", lambda *args: ([bytearray(), bytearray()], False, True)
    )
    assert adapter._run(client, "while True: pass")["status"] == "timed_out"
    created[-1][1].kill.assert_called_once()
    created[-1][1].remove.assert_called_once()
    client, created = fake_client(settings, bad=True)
    with pytest.raises(Unavailable):
        DockerAdapter(settings, lambda: client)._run(client, "print(1)")
    created[-1][1].start.assert_not_called()
    created[-1][1].remove.assert_called_once()


def test_mock_cancellation_waits_for_worker_cleanup(settings):
    adapter = MockAdapter()
    settings.sandbox_enabled = True
    done = []

    def work(code):
        time.sleep(0.05)
        done.append("cleaned")
        return {"status": "completed"}

    adapter.execute = work

    async def run():
        m = SandboxManager(settings, adapter)
        task = asyncio.create_task(m.execute("print(1)"))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert done == ["cleaned"] and not m.lock.locked()

    asyncio.run(run())


def test_policy_matrix():
    base = dict(
        authenticated=True,
        owned=True,
        tool="python_sandbox",
        size=10,
        quota=True,
        available=True,
        enabled=True,
        mode="approval",
        max_size=32768,
    )
    assert evaluate(**base) == Decision.REQUIRE_APPROVAL
    assert evaluate(**{**base, "mode": "allow"}) == Decision.ALLOW
    for key, value in [
        ("authenticated", False),
        ("owned", False),
        ("tool", "shell"),
        ("size", 40000),
        ("quota", False),
        ("available", False),
        ("enabled", False),
        ("mode", "deny"),
    ]:
        assert evaluate(**{**base, key: value}) == Decision.DENY


def test_langgraph_sandbox_dispatch_requires_session_allowlist(client):
    from app.agents.providers import Reply
    from app.agents.tools import ToolRejected, ToolRequest, execute

    adapter = setup(client)
    model = client.app.state.settings.groq_model
    session = client.post(
        "/api/agent/sessions",
        json={"provider": "groq", "model": model, "allowed_tools": ["python_sandbox"]},
        headers=csrf_headers(client),
    ).json()

    class Provider:
        async def complete(self, provider, model, messages, allowed):
            if messages[-1]["role"] == "tool":
                return Reply(content="Approval is required; code has not run.")
            return Reply(
                calls=[
                    ToolRequest(name="python_sandbox", arguments={"code": "print(1)"})
                ]
            )

    client.app.state.agent_engine.providers = Provider()
    result = client.post(
        "/api/agent/sessions/" + session["id"] + "/messages",
        json={"content": "Request Python execution"},
        headers=csrf_headers(client),
    )
    assert result.status_code == 200 and result.json()["status"] == "awaiting_approval"
    assert adapter.codes == []
    execution = db_call(
        client, "execution_logs", "find_one", {"agent_session_id": session["id"]}
    )
    assert execution["policy_decision"] == "REQUIRE_APPROVAL"
    assert "print(1)" not in json.dumps(result.json()["events"])
    with pytest.raises(ToolRejected):
        execute(
            ToolRequest(name="python_sandbox", arguments={"code": "print(1)"}),
            ["python_sandbox"],
        )
    # Resolve the paused request through a real authenticated rejection first.
    assert (
        client.post(
            "/api/sandbox/approvals/" + execution["_id"] + "/reject",
            json={"reject": True, "request_hash": execution["request_hash"]},
            headers=csrf_headers(client),
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/agent/sessions/{session['id']}/messages/{result.json()['id']}/resolve",
            headers=csrf_headers(client),
        ).json()["status"]
        == "failed"
    )
    # Removing the tool from the immutable session's allowlist denies model requests.
    db_call(
        client,
        "agent_sessions",
        "update_one",
        {"_id": session["id"]},
        {"$set": {"allowed_tools": []}},
    )
    assert (
        client.post(
            "/api/agent/sessions/" + session["id"] + "/messages",
            json={"content": "Try again"},
            headers=csrf_headers(client),
        ).json()["status"]
        == "failed"
    )


def test_cleanup_failure_latches_manager_unavailable(settings):
    adapter = MockAdapter()

    def fail(code):
        raise RuntimeError("private Docker error")

    adapter.execute = fail
    settings.sandbox_enabled = True

    async def run():
        manager = SandboxManager(settings, adapter)
        with pytest.raises(Unavailable, match="SANDBOX_UNAVAILABLE"):
            await manager.execute("print(1)")
        assert not (await manager.readiness())["ready"]

    asyncio.run(run())


def test_cleanup_failure_disables_other_workers_via_mongo(client):
    adapter = setup(client, mode="allow")

    def fail(code):
        raise RuntimeError("cleanup could not be confirmed")

    adapter.execute = fail
    assert request(client).json()["error_category"] == "SANDBOX_UNAVAILABLE"
    assert (
        db_call(client, "sandbox_locks", "find_one", {"_id": "execution"})["blocked"]
        is True
    )
    replacement = MockAdapter()
    client.app.state.sandbox_manager = SandboxManager(
        client.app.state.settings, replacement
    )
    assert client.get("/api/sandbox/readiness").json()["ready"] is False
    assert request(client).json()["error_category"] == "SANDBOX_UNAVAILABLE"
    assert not replacement.codes


def test_mock_transient_socket_timeout_does_not_poison_output(settings):
    client, created = fake_client(settings)
    original = client.containers.create.side_effect

    def create(**kw):
        c = original(**kw)
        sock = created[-1][2]
        data = b"\x02\0\0\0" + struct.pack(">I", 5) + b"error"
        sock._sock.recv.side_effect = [TimeoutError(), data, b""]
        c.wait.return_value = {"StatusCode": 1}
        return c

    client.containers.create.side_effect = create
    result = DockerAdapter(settings, lambda: client)._run(client, "raise Exception()")
    assert (
        result["status"] == "failed"
        and result["stderr"] == "error"
        and result["exit_code"] == 1
    )
    created[-1][1].remove.assert_called_once()


def test_trusted_launcher_syntax_and_probe_literals():
    import ast

    from app.sandbox.manager import PROBE, RUNNER

    ast.parse(RUNNER)
    tree = ast.parse(PROBE)
    values = [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]
    assert "NoNewPrivs:\t1" in values
    assert "CapEff:\t0000000000000000" in values
