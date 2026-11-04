"""Offline tests of the validation harness; these do not validate real isolation."""

import asyncio
import threading
from unittest.mock import Mock

import pytest

from app.sandbox.manager import SandboxManager
from scripts.validate_sandbox import cases, validate, validation_settings


def test_validator_rejects_remote_sockets_and_ignores_app_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "do-not-use-production-key")
    settings = validation_settings("unix:///tmp/colima.sock")
    assert settings.jwt_secret.get_secret_value() != "do-not-use-production-key"
    assert settings.sandbox_timeout == 10 and settings.sandbox_memory_mb == 128
    with pytest.raises(ValueError):
        validation_settings("tcp://host:2375")


def test_blocked_daemon_never_pulls_or_starts_programs():
    client = Mock()
    client.containers.list.return_value = []
    client.info.return_value = {
        "MemoryLimit": False,
        "SwapLimit": False,
        "PidsLimit": False,
        "CPUCfsQuota": False,
        "CgroupDriver": "none",
        "CgroupVersion": "2",
    }
    factory = Mock()
    report = validate(validation_settings("unix:///tmp/mock.sock"), client, factory)
    assert report["status"] == "BLOCKED" and report["tests"] == []
    factory.assert_not_called()
    client.images.pull.assert_not_called()


def test_probe_refusal_starts_no_programs():
    client = Mock()
    client.containers.list.return_value = []
    client.info.return_value = {
        "MemoryLimit": True,
        "SwapLimit": True,
        "PidsLimit": True,
        "CPUCfsQuota": True,
        "CgroupDriver": "systemd",
        "CgroupVersion": "2",
    }
    adapter = Mock()
    adapter.last_probe = {"memory": "wrong"}
    adapter.readiness.return_value = {"ready": False}
    report = validate(
        validation_settings("unix:///tmp/mock.sock"), client, lambda s: adapter
    )
    assert report["status"] == "BLOCKED"
    adapter.execute.assert_not_called()


def test_harness_contains_actual_resource_enforcement_cases():
    names = {v[0] for v in cases()}
    assert {
        "memory_enforcement",
        "pids_enforcement",
        "cpu_enforcement",
        "wall_timeout",
        "network_denied",
        "root_write_denied",
        "privilege_denied",
        "output_cap",
    } <= names


def test_repeated_cancellation_keeps_capacity_until_cleanup(settings):
    settings.sandbox_enabled = True
    started = threading.Event()
    release = threading.Event()
    finished = []

    class Adapter:
        def execute(self, code):
            started.set()
            release.wait(timeout=1)
            finished.append(True)
            return {"status": "completed"}

    async def run():
        manager = SandboxManager(settings, Adapter())
        task = asyncio.create_task(manager.execute("print(1)"))
        await asyncio.to_thread(started.wait, 0.5)
        task.cancel()
        await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.sleep(0.01)
        assert manager.lock.locked() and not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished and not manager.lock.locked()

    asyncio.run(run())


def test_orphan_container_blocks_probe_and_execution(settings):
    from app.sandbox.manager import DockerAdapter, Unavailable

    client = Mock()
    client.info.return_value = {
        "MemoryLimit": True,
        "SwapLimit": True,
        "PidsLimit": True,
        "CPUCfsQuota": True,
        "CgroupDriver": "systemd",
        "CgroupVersion": "2",
    }
    client.containers.list.return_value = [Mock()]
    adapter = DockerAdapter(settings, lambda: client)
    assert not adapter.readiness()["ready"]
    with pytest.raises(Unavailable):
        adapter.execute("print(1)")
    client.containers.create.assert_not_called()
