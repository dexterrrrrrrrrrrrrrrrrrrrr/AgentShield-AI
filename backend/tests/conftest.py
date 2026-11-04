"""All integration tests require real, local MongoDB and disposable databases."""

import os
import secrets
import uuid

import pytest
from fastapi.testclient import TestClient
from pymongo.uri_parser import parse_uri

# Allows module import in CI without any production configuration or credentials.
os.environ["JWT_SECRET"] = secrets.token_urlsafe(48)

from app.config import Settings  # noqa: E402 - set the ephemeral test key first
from app.main import create_app  # noqa: E402 - no production key is loaded in tests


def local_test_uri():
    uri = os.environ.get("TEST_MONGODB_URI", "mongodb://127.0.0.1:27017")
    parsed = parse_uri(uri)
    if parsed.get("username") or any(
        host not in ("localhost", "127.0.0.1", "::1") for host, _ in parsed["nodelist"]
    ):
        raise RuntimeError(
            "Tests require credential-free local MongoDB; never use a production URI"
        )
    return uri


@pytest.fixture(scope="session")
def database_name():
    # Reuse collection files within a run: repeated database drops can exhaust
    # MongoDB descriptors while WiredTiger defers physical file cleanup.
    uri = local_test_uri()
    name = "agentshield_test_" + uuid.uuid4().hex
    yield name
    import asyncio

    from pymongo import AsyncMongoClient

    async def cleanup():
        client = AsyncMongoClient(uri)
        try:
            await client.drop_database(name)
        finally:
            await client.close()

    asyncio.run(cleanup())


@pytest.fixture
def settings(database_name):
    uri = local_test_uri()
    return Settings(
        _env_file=None,
        app_env="test",
        mongodb_uri=uri,
        mongodb_database=database_name,
        jwt_secret=secrets.token_urlsafe(48),
        cors_origins="http://localhost:3000",
    )


@pytest.fixture
def client(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        yield client
        for collection in (
            "users",
            "sessions",
            "security_events",
            "agent_sessions",
            "agent_messages",
            "agent_configs",
            "execution_logs",
            "sandbox_approvals",
            "sandbox_locks",
        ):
            client.portal.call(app.state.db[collection].delete_many, {})


def csrf_headers(client, origin="http://localhost:3000"):
    token = client.get("/api/auth/csrf").json()["csrf_token"]
    return {"Origin": origin, "X-CSRF-Token": token}


def register(client, email="alice@example.com", **changes):
    payload = {
        "full_name": "Alice Example",
        "email": email,
        "password": "a long test passphrase",
        "confirm_password": "a long test passphrase",
    }
    payload.update(changes)
    return client.post("/api/auth/register", json=payload, headers=csrf_headers(client))


def login(client, email="alice@example.com", password="a long test passphrase"):
    return client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
        headers=csrf_headers(client),
    )


def db_call(client, collection, operation, *args, **kwargs):
    method = getattr(client.app.state.db[collection], operation)

    async def call():
        return await method(*args, **kwargs)

    return client.portal.call(call)
