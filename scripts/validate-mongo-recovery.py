"""Exercise real MongoDB stop/start against an isolated test API/database/container."""

import argparse
import asyncio
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--port", type=int, default=27019)
parser.add_argument("--output", type=Path)
parser.add_argument(
    "--docker-url",
    help="Local Unix daemon endpoint; default is the selected Docker context",
)
args = parser.parse_args()
endpoint = args.docker_url
if not endpoint:
    if os.environ.get("DOCKER_HOST") and not os.environ.get("DOCKER_CONTEXT"):
        endpoint = os.environ["DOCKER_HOST"]
    else:
        endpoint = subprocess.check_output(
            ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"],
            text=True,
        ).strip()
selected = urlsplit(endpoint)
if (
    selected.scheme != "unix"
    or selected.netloc
    or not selected.path.startswith("/")
    or selected.query
    or selected.fragment
    or "\0" in endpoint
):
    parser.error(
        "Recovery validation requires a local Unix Docker endpoint; remote daemons are refused"
    )
if not 1024 <= args.port <= 65535:
    parser.error("Use a non-privileged test database port")
with socket.socket() as probe:
    probe.bind(("127.0.0.1", args.port))

name = "agentshield-recovery-" + uuid.uuid4().hex
uri = f"mongodb://127.0.0.1:{args.port}"
database = "agentshield_test_recovery_" + uuid.uuid4().hex
child_env = dict(
    os.environ,
    CI_MONGODB_CONTAINER=name,
    CI_MONGODB_PORT=str(args.port),
    DOCKER_HOST=endpoint,
)
for selector in (
    "DOCKER_CONTEXT",
    "DOCKER_TLS",
    "DOCKER_TLS_VERIFY",
    "DOCKER_CERT_PATH",
):
    child_env.pop(selector, None)
helper = ["bash", str(ROOT / ".github/scripts/mongodb.sh")]


def docker(*arguments):
    return subprocess.run(
        ["docker", "--host=" + endpoint, *arguments],
        env=child_env,
        check=True,
        capture_output=True,
        text=True,
    )


def lifecycle(command):
    result = subprocess.run(
        [*helper, command], cwd=ROOT, env=child_env, capture_output=True, text=True
    )
    if result.returncode:
        raise RuntimeError(
            f"Isolated MongoDB {command} failed; exit {result.returncode}. No application environment values were logged."
        )


try:
    lifecycle("start")
    os.environ["JWT_SECRET"] = secrets.token_urlsafe(48)
    from app.config import Settings
    from app.main import create_app
    from fastapi.testclient import TestClient
    from pymongo import AsyncMongoClient

    settings = Settings(
        _env_file=None,
        app_env="test",
        jwt_secret=secrets.token_urlsafe(48),
        trusted_hosts="testserver,localhost,127.0.0.1",
        mongodb_uri=uri,
        mongodb_database=database,
        mongodb_timeout_ms=300,
    )
    with TestClient(create_app(settings)) as client:

        def post(path, payload):
            token = client.get("/api/auth/csrf").json()["csrf_token"]
            return client.post(
                path,
                json=payload,
                headers={"Origin": "http://localhost:3000", "X-CSRF-Token": token},
            )

        registered = post(
            "/api/auth/register",
            {
                "full_name": "Recovery Fixture",
                "email": "recovery@example.com",
                "password": "synthetic recovery passphrase",
                "confirm_password": "synthetic recovery passphrase",
            },
        )
        assert registered.status_code == 201
        assert (
            post(
                "/api/auth/login",
                {
                    "email": "recovery@example.com",
                    "password": "synthetic recovery passphrase",
                },
            ).status_code
            == 200
        )
        assert client.get("/ready").status_code == 200
        original_cookie = client.cookies.get(settings.session_cookie)
        docker("stop", "--time", "10", name)
        readiness = client.get("/ready")
        profile = client.get("/api/auth/me")
        assert readiness.status_code == profile.status_code == 503
        assert client.cookies.get(settings.session_cookie) == original_cookie
        assert "recovery@example.com" not in profile.text
        docker("start", name)
        start = time.perf_counter()
        deadline = start + 40
        while time.perf_counter() < deadline:
            if client.get("/ready").status_code == 200:
                break
            time.sleep(0.2)
        else:
            raise RuntimeError("MongoDB recovery exceeded forty seconds")
        restored = client.get("/api/auth/me")
        assert (
            restored.status_code == 200
            and restored.json()["id"] == registered.json()["id"]
        )
        report = {
            "status": "PASS",
            "integration": "Real isolated MongoDB container stop/start with in-process FastAPI and live database authentication",
            "outage_readiness_http": readiness.status_code,
            "outage_profile_http": profile.status_code,
            "restored_profile_http": restored.status_code,
            "session_preserved": True,
            "recovery_seconds": round(time.perf_counter() - start, 3),
            "limitations": "No live provider request or untrusted sandbox execution. Does not stop any existing MongoDB service or use production credentials.",
        }

    async def cleanup_database():
        db = AsyncMongoClient(uri, serverSelectionTimeoutMS=1000)
        try:
            await db.drop_database(database)
        finally:
            await db.close()

    asyncio.run(cleanup_database())
    encoded = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(encoded)
    print(encoded, end="")
finally:
    lifecycle("stop")
