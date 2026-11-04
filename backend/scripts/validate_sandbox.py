"""Opt-in local validation. Fixed harmless programs only, all inside verified containers.

No MongoDB, application env file, persistent signing key or user data is used.
Never change the daemon or weaken controls to make validation pass.
"""

import argparse
import json
import platform
import secrets
from datetime import datetime, timezone
from pathlib import Path

import docker

from app.config import Settings
from app.sandbox.manager import DockerAdapter
from app.sandbox.policy import IMAGE, limits
from app.sandbox.readiness import daemon_observations, supports_v2_probe


def validation_settings(url):
    return Settings(
        _env_file=None,
        sandbox_docker_url=url,
        jwt_secret=secrets.token_urlsafe(48),
        sandbox_enabled=True,
        sandbox_memory_mb=128,
        sandbox_cpus=1,
        sandbox_pids=32,
        sandbox_timeout=10,
        sandbox_output_bytes=65536,
        sandbox_code_bytes=32768,
    )


def clean(client):
    if client.containers.list(all=True, filters={"label": "agentshield.sandbox=true"}):
        raise RuntimeError(
            "Sandbox containers remain or another sandbox is active. Stop the backend, inspect labeled containers, and recover explicitly."
        )


def cases():
    return [
        ("stdout", 'print("hello")', "completed"),
        (
            "stderr_runtime",
            'import sys; print("diagnostic",file=sys.stderr); raise RuntimeError("test")',
            "failed",
        ),
        ("syntax", "invalid syntax !", "failed"),
        ("wall_timeout", "import time; time.sleep(30)", "timed_out"),
        ("output_cap", 'print("x"*100000)', "output_limit"),
        ("memory_enforcement", "x=bytearray(512*1024*1024)", "failed"),
        (
            "uid_readonly_tmpfs",
            'import os; assert os.getuid()==65534; assert os.statvfs("/").f_flag & os.ST_RDONLY; open("/tmp/test","w").write("ok"); print("restricted")',
            "completed",
        ),
        ("root_write_denied", 'open("/usr/local/test","w").write("no")', "failed"),
        (
            "network_denied",
            'import socket; s=socket.socket(); s.settimeout(1); s.connect(("192.0.2.1",80))',
            "failed",
        ),
        ("privilege_denied", "import os; os.setuid(0)", "failed"),
        (
            "pids_enforcement",
            """import os,time,json
children=[]; blocked=False
try:
    for i in range(40):
        try:
            pid=os.fork()
        except BlockingIOError:
            blocked=True; break
        if pid==0:
            time.sleep(2); os._exit(0)
        children.append(pid)
finally:
    for child in children: os.waitpid(child,0)
assert blocked and len(children)<32
print(json.dumps({"fork_blocked":blocked,"children":len(children)}))""",
            "completed",
        ),
        (
            "cpu_enforcement",
            """import time,json,pathlib
p=pathlib.Path('/sys/fs/cgroup/cpu.stat')
def throttles(): return int(dict(x.split() for x in p.read_text().splitlines())['nr_throttled'])
before=throttles(); cpu=time.process_time(); wall=time.monotonic()
while time.process_time()-cpu<0.6: pass
print(json.dumps({"cpu_seconds":time.process_time()-cpu,"wall_seconds":time.monotonic()-wall,"throttles":throttles()-before}))""",
            "completed",
        ),
    ]


def validate(settings, client, adapter_factory=DockerAdapter):
    report = {
        "status": "BLOCKED",
        "image": IMAGE,
        "machine": platform.machine(),
        "limits": limits(settings),
        "tests": [],
    }
    clean(client)
    info = client.info()
    report["daemon"] = daemon_observations(info)
    if not supports_v2_probe(info):
        report["reason"] = (
            "SANDBOX_UNAVAILABLE: supported cgroup-v2 namespace unavailable; no test programs started"
        )
        return report
    try:
        client.images.get(IMAGE)
    except docker.errors.ImageNotFound:
        # Explicit operator validation, never an HTTP request or model action.
        client.images.pull(IMAGE)
    adapter = adapter_factory(settings)
    readiness = adapter.readiness()
    report["observed"] = adapter.last_probe
    if not readiness["ready"]:
        report["reason"] = (
            "SANDBOX_UNAVAILABLE: fixed trusted probe could not verify effective limits or isolation; no test programs started"
        )
        return report
    report["status"] = "FAILED"
    for name, code, status in cases():
        active = adapter
        if name == "cpu_enforcement":
            active = adapter_factory(settings.model_copy(update={"sandbox_cpus": 0.5}))
        try:
            result = active.execute(code)  # execute() revalidates each container.
            if result["exit_code"] == 125 or result["status"] != status:
                raise RuntimeError("Unexpected status or inner guard refusal")
            if name == "stdout" and result["stdout"] != "hello\n":
                raise RuntimeError("stdout mismatch")
            if name == "stderr_runtime" and "diagnostic" not in result["stderr"]:
                raise RuntimeError("stderr mismatch")
            if name == "output_cap" and (
                not result["truncated"]
                or len(result["stdout"].encode()) + len(result["stderr"].encode())
                > settings.sandbox_output_bytes
            ):
                raise RuntimeError("output cap failed")
            if name == "memory_enforcement" and not result.get("oom_killed"):
                raise RuntimeError("Memory OOM enforcement was not demonstrated")
            if (
                name == "wall_timeout"
                and result["duration"] > settings.sandbox_timeout + 8
            ):
                raise RuntimeError("Timeout cleanup exceeded tolerance")
            evidence = {
                "oom_killed": bool(result.get("oom_killed")),
                "captured_bytes": len(result["stdout"].encode())
                + len(result["stderr"].encode()),
                "truncated": bool(result.get("truncated")),
            }
            if name in ("cpu_enforcement", "pids_enforcement"):
                evidence.update(json.loads(result["stdout"]))
            if name == "cpu_enforcement" and (
                evidence["throttles"] <= 0
                or evidence["wall_seconds"] < evidence["cpu_seconds"] * 1.4
            ):
                raise RuntimeError("Actual CPU throttling was not demonstrated")
            clean(client)
            report["tests"].append(
                {
                    "name": name,
                    "status": "PASS",
                    "duration": result["duration"],
                    "exit_code": result["exit_code"],
                    "evidence": evidence,
                    "cleanup": "PASS",
                }
            )
        except Exception:
            report["tests"].append(
                {
                    "name": name,
                    "status": "FAIL",
                    "reason": "Validation or cleanup failed; inspect the local runtime. No further programs started.",
                }
            )
            return report
    report["status"] = "PASS"
    report["scope"] = (
        "Real Docker runtime checks only; not proof against container escapes or validation of authentication/MongoDB."
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-url", required=True)
    parser.add_argument("--report-dir", default="..")
    args = parser.parse_args()
    settings = validation_settings(args.docker_url)
    client = None
    try:
        try:
            client = docker.DockerClient(
                base_url=settings.sandbox_docker_url, timeout=3
            )
            report = validate(settings, client)
        except Exception:
            report = {
                "status": "BLOCKED",
                "reason": "Docker unavailable, existing containers, or setup failed. No validation success claimed.",
            }
    finally:
        if client is not None:
            client.close()
    name = (
        "phase4-validation-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        + ".json"
    )
    path = Path(args.report_dir) / name
    with path.open("x") as f:
        json.dump(report, f, indent=2)
    path.chmod(0o600)
    print(json.dumps(report, indent=2))
    print("Report:", path)
    return (
        0 if report["status"] == "PASS" else 2 if report["status"] == "BLOCKED" else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
