"""Opt-in REAL Docker tests. Never run submitted code before readiness succeeds."""

import os

import pytest

from app.sandbox.manager import DockerAdapter

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_SANDBOX_INTEGRATION") != "1",
    reason="BLOCKED/opt-in: real sandbox requires verified cgroup isolation",
)


@pytest.fixture
def adapter(settings):
    settings.sandbox_enabled = True
    a = DockerAdapter(settings)
    if not a.readiness()["ready"]:
        pytest.fail(
            "SANDBOX_UNAVAILABLE: real Docker security checks are BLOCKED; no user code executed"
        )
    return a


@pytest.mark.parametrize(
    "code,status",
    [
        ('print("hello")', "completed"),
        ("invalid syntax !", "failed"),
        ('raise RuntimeError("test")', "failed"),
        ("while True: pass", "timed_out"),
        ('print("x"*100000)', "output_limit"),
        ("x=bytearray(512*1024*1024)", "failed"),
        ('import os; assert os.getuid()!=0; print("nonroot")', "completed"),
        (
            'import os; assert os.statvfs("/").f_flag & os.ST_RDONLY; open("/tmp/test","w").write("ok")',
            "completed",
        ),
        (
            'import socket; s=socket.socket(); s.settimeout(1); s.connect(("192.0.2.1",80))',
            "failed",
        ),
        ("import os; os.setuid(0)", "failed"),
    ],
)
def test_real_isolation(adapter, code, status):
    result = adapter.execute(code)
    assert result["status"] == status
    assert result["exit_code"] != 125, (
        "Inner-container resource guard refused execution"
    )
    client = adapter.factory()
    try:
        assert not client.containers.list(
            all=True, filters={"label": "agentshield.sandbox=true"}
        )
    finally:
        client.close()
