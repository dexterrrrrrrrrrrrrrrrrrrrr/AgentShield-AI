"""Disposable, bounded local API measurements; never sends model or sandbox requests."""

import argparse
import asyncio
import json
import os
import platform
import secrets
import statistics
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mongodb-uri", default="mongodb://127.0.0.1:27017")
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    uri = urlsplit(args.mongodb_uri)
    if (
        uri.scheme != "mongodb"
        or uri.hostname not in ("127.0.0.1", "localhost", "::1")
        or uri.username
        or uri.password
        or uri.query
        or uri.path not in ("", "/")
    ):
        parser.error("Use a credential-free loopback MongoDB, never a production URI")
    if not 5 <= args.samples <= 50:
        parser.error("Samples must be between 5 and 50")
    # Safe import-time app configuration; the measured app uses explicit settings.
    os.environ["JWT_SECRET"] = secrets.token_urlsafe(48)
    from app.config import Settings
    from app.main import create_app
    from app.security import utcnow
    from fastapi.testclient import TestClient
    from pymongo import AsyncMongoClient

    database = "agentshield_test_measure_" + uuid.uuid4().hex
    settings = Settings(
        _env_file=None,
        app_env="test",
        jwt_secret=secrets.token_urlsafe(48),
        mongodb_uri=args.mongodb_uri,
        mongodb_database=database,
        trusted_hosts="testserver,localhost,127.0.0.1",
    )
    measurements = {}
    try:
        with TestClient(create_app(settings)) as client:

            def post(path, data):
                csrf = client.get("/api/auth/csrf").json()["csrf_token"]
                return client.post(
                    path,
                    json=data,
                    headers={"Origin": "http://localhost:3000", "X-CSRF-Token": csrf},
                )

            registered = post(
                "/api/auth/register",
                {
                    "full_name": "Measurement User",
                    "email": "measure@example.com",
                    "password": "synthetic measurement passphrase",
                    "confirm_password": "synthetic measurement passphrase",
                },
            )
            assert registered.status_code == 201
            assert (
                post(
                    "/api/auth/login",
                    {
                        "email": "measure@example.com",
                        "password": "synthetic measurement passphrase",
                    },
                ).status_code
                == 200
            )
            uid = registered.json()["id"]
            sid = uuid.uuid4().hex

            async def seed():
                db = client.app.state.db
                now = utcnow()
                await db.agent_sessions.insert_one(
                    {
                        "_id": sid,
                        "user_id": uid,
                        "provider": "groq",
                        "model": settings.groq_model,
                        "allowed_tools": ["calculator"],
                        "status": "idle",
                        "turns": 50,
                        "created_at": now,
                        "updated_at": now,
                    }
                )
                await db.agent_messages.insert_many(
                    [
                        {
                            "_id": uuid.uuid4().hex,
                            "user_id": uid,
                            "session_id": sid,
                            "turn": i,
                            "user_content": "Synthetic arithmetic task",
                            "assistant_content": "Synthetic persisted measurement fixture",
                            "events": [],
                            "status": "completed",
                            "created_at": now,
                        }
                        for i in range(1, 51)
                    ]
                )
                for _ in range(200):
                    await client.app.state.monitor.emit(
                        uid, "agent_status", agent_id=sid
                    )

            client.portal.call(seed)
            for label, path in (
                ("session_page_20", "/api/agent/sessions?limit=20"),
                ("history_page_20", f"/api/agent/sessions/{sid}/messages?limit=20"),
                ("audit_page_50", "/api/monitor/events?limit=50"),
                ("analytics_summary", "/api/monitor/summary"),
            ):
                for _ in range(3):
                    assert client.get(path).status_code == 200
                elapsed = []
                for _ in range(args.samples):
                    start = time.perf_counter()
                    response = client.get(path)
                    elapsed.append((time.perf_counter() - start) * 1000)
                    assert response.status_code == 200
                ordered = sorted(elapsed)
                measurements[label] = {
                    "samples": len(elapsed),
                    "median_ms": round(statistics.median(elapsed), 3),
                    "p95_ms": round(
                        ordered[max(0, int(len(ordered) * 0.95 + 0.999) - 1)], 3
                    ),
                    "max_ms": round(max(elapsed), 3),
                }
        report = {
            "method": "In-process FastAPI TestClient request roundtrips with real local MongoDB; 3 warmups then sequential samples per endpoint. Includes authentication, DB and serialization; excludes TCP/TLS/browser/network/model/container latency.",
            "hardware": {
                "system": platform.system(),
                "machine": platform.machine(),
                "logical_cpus": os.cpu_count(),
                "python": platform.python_version(),
                "memory_bytes_visible_to_os": os.sysconf("SC_PHYS_PAGES")
                * os.sysconf("SC_PAGE_SIZE")
                if hasattr(os, "sysconf")
                else None,
            },
            "workload": {
                "users": 1,
                "agent_sessions": 1,
                "persisted_turns": 50,
                "signed_audit_events": 200,
                "concurrent_requests": 1,
            },
            "commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "working_tree_dirty": bool(
                subprocess.check_output(
                    ["git", "status", "--porcelain", "--untracked-files=no"],
                    cwd=ROOT,
                    text=True,
                ).strip()
            ),
            "results": measurements,
            "limitations": "Cloud Linux measurements do not predict M2/8GB performance. Synthetic fixture records are isolated measurement data, never production analytics. No before/after speedup claimed.",
        }
        text = json.dumps(report, indent=2) + "\n"
        if args.output:
            args.output.write_text(text)
        print(text, end="")
    finally:

        async def cleanup():
            db_client = AsyncMongoClient(args.mongodb_uri)
            try:
                await db_client.drop_database(database)
            finally:
                await db_client.close()

        asyncio.run(cleanup())


if __name__ == "__main__":
    main()
