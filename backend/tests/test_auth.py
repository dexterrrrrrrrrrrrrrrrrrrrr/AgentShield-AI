from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import jwt
import pytest
from argon2 import PasswordHasher
from conftest import csrf_headers, db_call, login, register
from fastapi.testclient import TestClient
from pymongo.errors import ServerSelectionTimeoutError

from app.config import Settings
from app.main import create_app
from app.security import utcnow


def token(client):
    return client.cookies.get(client.app.state.settings.session_cookie)


def set_token(client, value):
    client.cookies.clear()
    client.cookies.set(
        client.app.state.settings.session_cookie,
        value,
        domain="testserver.local",
        path="/",
    )


def resign(client, **changes):
    settings = client.app.state.settings
    claims = jwt.decode(
        token(client),
        settings.jwt_secret.get_secret_value(),
        algorithms=["HS256"],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
    )
    claims.update(changes)
    return jwt.encode(claims, settings.jwt_secret.get_secret_value(), algorithm="HS256")


def test_registration_hashes_password_and_normalizes_email(client):
    response = register(client, "  ALICE@Example.COM  ", full_name="  Alice   Example ")
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "alice@example.com"
    assert data["full_name"] == "Alice Example"
    assert data["authenticated"] is False
    assert "password" not in response.text
    user = db_call(client, "users", "find_one", {"_id": data["id"]})
    assert user["password_hash"].startswith("$argon2id$")
    assert PasswordHasher().verify(user["password_hash"], "a long test passphrase")
    assert "password" not in user and "confirm_password" not in user
    assert client.get("/api/auth/me").status_code == 401


def test_duplicate_registration_uses_unique_normalized_email(client):
    assert register(client).status_code == 201
    response = register(client, "ALICE@EXAMPLE.COM")
    assert response.status_code == 409
    assert response.json() == {"detail": "Unable to register with these details"}
    assert db_call(client, "users", "count_documents", {}) == 1


def test_concurrent_duplicate_registration(client):
    headers = csrf_headers(client)
    body = {
        "email": "same@example.com",
        "full_name": "Same User",
        "password": "a long test passphrase",
        "confirm_password": "a long test passphrase",
    }
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(
            pool.map(
                lambda _: (
                    client.post(
                        "/api/auth/register", headers=headers, json=body
                    ).status_code
                ),
                range(3),
            )
        )
    assert sorted(results) == [201, 409, 409]


@pytest.mark.parametrize(
    "changes",
    [
        {"email": "invalid"},
        {"email": {"$ne": ""}},
        {"password": "short", "confirm_password": "short"},
        {"password": " " * 12, "confirm_password": " " * 12},
        {"confirm_password": "a different passphrase"},
        {"full_name": " "},
        {"password": "p" * 129, "confirm_password": "p" * 129},
        {"extra": True},
    ],
)
def test_registration_validation_never_echoes_passwords(client, changes):
    response = register(client, **changes)
    assert response.status_code == 422
    assert "a long test passphrase" not in response.text
    assert "password_hash" not in response.text
    assert db_call(client, "users", "count_documents", {}) == 0


def test_login_and_profile_have_secure_cookie_no_token_body(client):
    register(client)
    response = login(client, " ALICE@EXAMPLE.COM ")
    assert response.status_code == 200
    assert "password" not in response.text and "token" not in response.json()
    cookie = next(
        c
        for c in client.cookies.jar
        if c.name == client.app.state.settings.session_cookie
    )
    assert cookie.has_nonstandard_attr("HttpOnly")
    assert cookie.get_nonstandard_attr("SameSite") == "lax"
    assert not cookie.secure  # explicit HTTP development mode
    profile = client.get("/api/auth/me")
    assert profile.json()["email"] == "alice@example.com"
    assert profile.json()["authenticated"] is True
    assert profile.json()["created_at"]
    assert profile.headers["cache-control"] == "no-store"
    assert db_call(client, "sessions", "count_documents", {}) == 1
    session = db_call(client, "sessions", "find_one", {})
    assert "token" not in session


@pytest.mark.parametrize(
    "email,password",
    [
        ("alice@example.com", "wrong password"),
        ("unknown@example.com", "a long test passphrase"),
    ],
)
def test_generic_login_failure(client, email, password):
    register(client)
    response = login(client, email, password)
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid email or password"}
    assert db_call(client, "sessions", "count_documents", {}) == 0


def test_missing_authentication(client):
    assert client.get("/api/auth/me").status_code == 401
    assert (
        client.post("/api/auth/logout", headers=csrf_headers(client)).status_code == 401
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"exp": utcnow() - timedelta(minutes=1)},
        {"iss": "other"},
        {"aud": "other"},
        {"nbf": utcnow() + timedelta(minutes=1)},
        {"token_use": "csrf"},
    ],
)
def test_invalid_access_claims(client, changes):
    register(client)
    login(client)
    set_token(client, resign(client, **changes))
    assert client.get("/api/auth/me").status_code == 401


def test_invalid_signature_and_malformed_jwt(client):
    register(client)
    login(client)
    original = token(client)
    claims = jwt.decode(original, options={"verify_signature": False})
    tampered = jwt.encode(
        claims, "this-is-a-different-test-signing-key-123", algorithm="HS256"
    )
    for value in (
        tampered,
        "not.a.jwt",
        "",
        jwt.encode(claims, key="", algorithm="none"),
    ):
        set_token(client, value)
        assert client.get("/api/auth/me").status_code == 401


def test_required_jwt_claims_cannot_be_omitted(client):
    register(client)
    login(client)
    settings = client.app.state.settings
    claims = jwt.decode(token(client), options={"verify_signature": False})
    del claims["exp"]
    set_token(
        client,
        jwt.encode(claims, settings.jwt_secret.get_secret_value(), algorithm="HS256"),
    )
    assert client.get("/api/auth/me").status_code == 401


def test_expired_database_session_rejected_before_ttl_cleanup(client):
    register(client)
    login(client)
    db_call(
        client,
        "sessions",
        "update_many",
        {},
        {"$set": {"expires_at": utcnow() - timedelta(seconds=1)}},
    )
    assert client.get("/api/auth/me").status_code == 401


def test_logout_revokes_captured_token(client):
    register(client)
    login(client)
    captured = token(client)
    response = client.post("/api/auth/logout", headers=csrf_headers(client))
    assert response.status_code == 204
    assert db_call(client, "sessions", "count_documents", {}) == 0
    assert not client.cookies.get(client.app.state.settings.session_cookie)
    set_token(client, captured)
    assert client.get("/api/auth/me").status_code == 401


def test_session_ownership_and_cross_user_isolation(client):
    alice = register(client).json()
    bob = register(client, "bob@example.com", full_name="Bob Example").json()
    login(client)
    alice_token = token(client)
    assert (
        client.get("/api/auth/me", params={"user_id": bob["id"]}).json()["id"]
        == alice["id"]
    )
    # Even a correctly signed test token cannot borrow another user's session.
    set_token(client, resign(client, sub=bob["id"]))
    assert client.get("/api/auth/me").status_code == 401
    set_token(client, alice_token)
    login(client, "bob@example.com")
    bob_token = token(client)
    assert client.get("/api/auth/me").json()["id"] == bob["id"]
    client.post("/api/auth/logout", headers=csrf_headers(client))
    set_token(client, alice_token)
    assert client.get("/api/auth/me").json()["id"] == alice["id"]
    set_token(client, bob_token)
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/agent_configs").status_code == 404


def test_login_email_rate_limit(client, monkeypatch):
    now = utcnow()
    monkeypatch.setattr("app.security.utcnow", lambda: now)
    register(client)
    for _ in range(client.app.state.settings.login_email_limit):
        assert login(client, password="wrong").status_code == 401
    response = login(client)
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0


def test_ip_rate_limit_does_not_trust_forwarded_headers(client, monkeypatch):
    now = utcnow()
    monkeypatch.setattr("app.security.utcnow", lambda: now)
    client.app.state.settings.login_ip_limit = 2
    assert login(client, "one@example.com").status_code == 401
    assert login(client, "two@example.com").status_code == 401
    response = client.post(
        "/api/auth/login",
        json={"email": "three@example.com", "password": "wrong"},
        headers={**csrf_headers(client), "X-Forwarded-For": "198.51.100.99"},
    )
    assert response.status_code == 429


def test_registration_rate_limit(client, monkeypatch):
    now = utcnow()
    monkeypatch.setattr("app.security.utcnow", lambda: now)
    client.app.state.settings.register_ip_limit = 1
    assert register(client).status_code == 201
    assert register(client, "bob@example.com").status_code == 429


@pytest.mark.parametrize("endpoint", ["register", "login", "logout"])
def test_state_changes_require_csrf_and_origin(client, endpoint):
    register(client)
    login(client)
    url = "/api/auth/" + endpoint
    payload = {"email": "bob@example.com", "password": "a long test passphrase"}
    assert client.post(url, json=payload).status_code == 403
    headers = csrf_headers(client)
    for altered in (
        {"Origin": "http://localhost:3000"},
        {**headers, "Origin": "https://evil.example"},
        {**headers, "X-CSRF-Token": "invalid"},
    ):
        assert client.post(url, json=payload, headers=altered).status_code == 403


def test_csrf_is_bound_to_session(client):
    register(client)
    before_login = client.get("/api/auth/csrf").json()["csrf_token"]
    login(client)
    client.cookies.set(
        client.app.state.settings.csrf_cookie,
        before_login,
        domain="testserver.local",
        path="/",
    )
    assert (
        client.post(
            "/api/auth/logout",
            headers={"Origin": "http://localhost:3000", "X-CSRF-Token": before_login},
        ).status_code
        == 403
    )


def test_signed_csrf_cannot_be_forged(client):
    forged = "attacker-controlled-value"
    client.cookies.set(client.app.state.settings.csrf_cookie, forged)
    assert (
        client.post(
            "/api/auth/login",
            json={"email": "alice@example.com", "password": "wrong"},
            headers={"Origin": "http://localhost:3000", "X-CSRF-Token": forged},
        ).status_code
        == 403
    )


def test_large_request_rejected(client):
    assert client.post("/api/auth/login", content="x" * 16385).status_code == 413


def test_indexes_and_future_collections(client):
    users = db_call(client, "users", "index_information")
    sessions = db_call(client, "sessions", "index_information")
    counters = db_call(client, "security_events", "index_information")
    assert users["unique_email"]["unique"] is True
    assert sessions["session_expiry"]["expireAfterSeconds"] == 0
    assert counters["rate_expiry"]["expireAfterSeconds"] == 0
    collections = client.portal.call(client.app.state.db.list_collection_names)
    assert set(collections) == {
        "users",
        "sessions",
        "security_events",
        "agent_sessions",
        "agent_messages",
        "agent_configs",
        "execution_logs",
        "sandbox_approvals",
        "sandbox_locks",
        "monitor_streams",
        "monitor_connections",
    }


def test_database_startup_failure_is_safe(settings):
    bad = settings.model_copy(
        update={
            "mongodb_uri": __import__("pydantic").SecretStr("mongodb://127.0.0.1:1"),
            "mongodb_timeout_ms": 100,
        }
    )
    with pytest.raises(RuntimeError, match="MongoDB startup verification failed"):
        with TestClient(create_app(bad)):
            pass


def test_database_runtime_failure_is_safe(client, monkeypatch):
    async def fail(*args, **kwargs):
        raise ServerSelectionTimeoutError("sensitive database information")

    monkeypatch.setattr(type(client.app.state.db), "command", fail)
    response = client.get("/ready")
    assert response.status_code == 503
    assert "sensitive" not in response.text
    assert response.json() == {"detail": "Database temporarily unavailable"}


def test_secure_production_cookies(settings):
    production = settings.model_copy(
        update={"app_env": "production", "cors_origins": "https://localhost:3000"}
    )
    with TestClient(create_app(production), base_url="https://testserver") as secure:
        headers = csrf_headers(secure, "https://localhost:3000")
        response = secure.post(
            "/api/auth/register",
            json={
                "email": "secure@example.com",
                "full_name": "Secure User",
                "password": "a long test passphrase",
                "confirm_password": "a long test passphrase",
            },
            headers=headers,
        )
        assert response.status_code == 201
        response = secure.post(
            "/api/auth/login",
            json={"email": "secure@example.com", "password": "a long test passphrase"},
            headers=csrf_headers(secure, "https://localhost:3000"),
        )
        assert response.status_code == 200
        session = next(
            c for c in secure.cookies.jar if c.name == "__Host-agentshield_session"
        )
        assert session.secure and session.path == "/" and not session.domain_specified
        assert session.has_nonstandard_attr("HttpOnly")
        assert secure.get("/api/auth/me").status_code == 200
        secure.portal.call(
            secure.app.state.db.client.drop_database, settings.mongodb_database
        )


def test_configuration_rejects_weak_secrets_and_unsafe_origins():
    import secrets

    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_secret="weak")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_secret=secrets.token_urlsafe(48), cors_origins="*")
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            jwt_secret=secrets.token_urlsafe(48),
            app_env="production",
            cors_origins="http://localhost:3000",
        )


def test_database_failure_does_not_authenticate_or_pretend_to_logout(
    client, monkeypatch
):
    register(client)
    login(client)
    headers = csrf_headers(client)

    async def fail(*args, **kwargs):
        raise ServerSelectionTimeoutError("private database diagnostics")

    monkeypatch.setattr(type(client.app.state.db.sessions), "find_one", fail)
    assert client.get("/api/auth/me").status_code == 503
    response = client.post("/api/auth/logout", headers=headers)
    assert response.status_code == 503
    assert "private" not in response.text
    assert token(client)


def test_deleted_user_cannot_keep_using_session(client):
    register(client)
    login(client)
    db_call(client, "users", "delete_many", {})
    assert client.get("/api/auth/me").status_code == 401


@pytest.mark.parametrize(
    "changes",
    [
        {"exp": utcnow() - timedelta(seconds=1)},
        {"aud": "agentshield-web"},
        {"token_use": "access"},
        {"sub": "another-session"},
    ],
)
def test_expired_or_wrong_purpose_csrf_rejected(client, changes):
    settings = client.app.state.settings
    original = client.get("/api/auth/csrf").json()["csrf_token"]
    claims = jwt.decode(original, options={"verify_signature": False})
    claims.update(changes)
    forged = jwt.encode(
        claims, settings.jwt_secret.get_secret_value(), algorithm="HS256"
    )
    client.cookies.set(
        settings.csrf_cookie, forged, domain="testserver.local", path="/"
    )
    response = client.post(
        "/api/auth/login",
        json={"email": "alice@example.com", "password": "wrong"},
        headers={"Origin": "http://localhost:3000", "X-CSRF-Token": forged},
    )
    assert response.status_code == 403


def test_chunked_body_limit(client):
    response = client.post("/api/auth/login", content=iter([b"x" * 8192, b"x" * 8193]))
    assert response.status_code == 413


def test_application_shutdown_closes_database(settings):
    app = create_app(settings)
    with TestClient(app) as c:
        mongo = app.state.db.client
        c.portal.call(mongo.drop_database, settings.mongodb_database)
        assert not mongo._topology._closed
    assert mongo._topology._closed
