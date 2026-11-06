"""Real Mongo/cookie/session integration; Google HTTP and signing identity mocked."""

import base64
import hashlib
import json
import logging
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import jwt
import pytest
from conftest import csrf_headers, db_call, login, register
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import SecretStr, ValidationError

from app.config import Settings
from app.guards import credential_values, redact
from app.oauth import JWKS_URL, TOKEN_URL, AccessQueryFilter, digest
from app.security import utcnow

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
WRONG_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
JWK = {
    **json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key())),
    "kid": "google-test",
    "alg": "RS256",
    "use": "sig",
}


@pytest.fixture
def oauth(client):
    settings = client.app.state.settings
    settings.google_client_id = "test-client.apps.googleusercontent.com"
    settings.google_client_secret = SecretStr(secrets.token_urlsafe(32))
    settings.google_redirect_uri = "http://localhost:3000/api/auth/google/callback"
    control = {
        "params": {},
        "claims": {},
        "requests": [],
        "status": 200,
        "omit": (),
        "key": KEY,
    }

    async def handle(request):
        control["requests"].append(request)
        if control.get("timeout"):
            raise httpx.ReadTimeout("private provider diagnostics and credentials")
        if str(request.url) == TOKEN_URL:
            body = parse_qs(request.content.decode())
            assert body["client_id"] == [settings.google_client_id]
            assert body["client_secret"] == [
                settings.google_client_secret.get_secret_value()
            ]
            assert body["redirect_uri"] == [settings.google_redirect_uri]
            verifier = body["code_verifier"][0]
            challenge = (
                base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                .rstrip(b"=")
                .decode()
            )
            assert challenge == control["params"]["code_challenge"][0]
            now = int(utcnow().timestamp())
            claims = {
                "iss": "https://accounts.google.com",
                "aud": settings.google_client_id,
                "iat": now,
                "exp": now + 3600,
                "sub": "google-identity-123",
                "nonce": control["params"]["nonce"][0],
                "email": "google@example.com",
                "email_verified": True,
                "name": "Google Person",
                "picture": "https://lh3.googleusercontent.com/photo",
            }
            claims.update(control["claims"])
            for name in control["omit"]:
                claims.pop(name, None)
            raw = jwt.encode(
                claims,
                control["key"],
                algorithm="RS256",
                headers={"kid": control.get("kid", "google-test")},
            )
            if control.get("raw"):
                raw = control["raw"]
            return httpx.Response(
                control["status"],
                json={
                    "id_token": raw,
                    "access_token": "discarded-provider-token",
                    "refresh_token": "never-store-this",
                },
            )
        assert str(request.url) == JWKS_URL
        return httpx.Response(200, json={"keys": control.get("keys", [JWK])})

    provider = client.app.state.google_provider
    client.portal.call(provider.client.aclose)
    provider.client = httpx.AsyncClient(
        transport=httpx.MockTransport(handle), follow_redirects=False
    )
    return client, control


def begin(oauth, mode="login"):
    client, control = oauth
    response = client.post(
        "/api/auth/google/start", json={"mode": mode}, headers=csrf_headers(client)
    )
    assert response.status_code == 200, response.text
    control["params"] = parse_qs(urlparse(response.json()["authorization_url"]).query)
    return control["params"]["state"][0]


def finish(oauth, state=None, **params):
    client, control = oauth
    state = state or control["params"]["state"][0]
    return client.get(
        "/api/auth/google/callback?"
        + urlencode({"state": state, "code": "test-code", **params}),
        follow_redirects=False,
    )


def test_disabled_provider_and_csrf_start(client):
    assert client.get("/api/auth/providers").json() == {"google": {"enabled": False}}
    assert client.post("/api/auth/google/start", json={}).status_code == 403
    assert (
        client.post(
            "/api/auth/google/start", json={}, headers=csrf_headers(client)
        ).status_code
        == 503
    )
    assert (
        client.get("/api/auth/google/callback", follow_redirects=False)
        .headers["location"]
        .endswith("oauth_error=unavailable")
    )


def test_code_flow_pkce_browser_binding_and_first_login(oauth):
    client, control = oauth
    assert client.get("/api/auth/providers").json()["google"]["enabled"]
    state = begin(oauth)
    params = control["params"]
    assert params["response_type"] == ["code"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["scope"] == ["openid email profile"]
    assert "client_secret" not in params
    flow = db_call(client, "oauth_states", "find_one", {"_id": digest(state)})
    assert state not in str(flow) and params["nonce"][0] not in str(flow)
    cookie = next(
        c
        for c in client.cookies.jar
        if c.name == client.app.state.settings.oauth_cookie
    )
    assert (
        cookie.has_nonstandard_attr("HttpOnly")
        and cookie.get_nonstandard_attr("SameSite") == "lax"
    )
    result = finish(oauth)
    assert (
        result.status_code == 303
        and result.headers["location"] == "http://localhost:3000/"
    )
    assert result.headers["referrer-policy"] == "no-referrer"
    assert result.headers["cache-control"] == "no-store"
    profile = client.get("/api/auth/me").json()
    assert profile["authentication_provider"] == "google" and profile["email_verified"]
    assert profile["google_connected"] and profile["last_login_at"]
    assert profile["profile_picture"] == "https://lh3.googleusercontent.com/photo"
    user = db_call(client, "users", "find_one", {"_id": profile["id"]})
    assert "password_hash" not in user
    assert not any(
        word in str(user)
        for word in ("discarded-provider-token", "never-store-this", "id_token")
    )
    assert "google_sub" not in profile and "token" not in profile
    assert db_call(client, "oauth_states", "count_documents", {}) == 0
    assert login(client, "google@example.com").status_code == 401


def test_returning_subject_preserves_account_id_and_local_email(oauth):
    client, control = oauth
    begin(oauth)
    finish(oauth)
    original = client.get("/api/auth/me").json()
    client.post("/api/auth/logout", headers=csrf_headers(client))
    control["claims"]["email"] = "changed@example.com"
    begin(oauth)
    finish(oauth)
    returned = client.get("/api/auth/me").json()
    assert returned["id"] == original["id"] and returned["email"] == original["email"]
    assert db_call(client, "users", "count_documents", {}) == 1


@pytest.mark.parametrize(
    "case",
    [
        "invalid_state",
        "missing_cookie",
        "foreign_cookie",
        "expired",
        "duplicate_state",
        "missing_code",
        "wrong_iss",
    ],
)
def test_invalid_callback_or_binding_never_authenticates(oauth, case):
    client, control = oauth
    state = begin(oauth)
    if case == "invalid_state":
        state = secrets.token_urlsafe(32)
    if case in ("missing_cookie", "foreign_cookie"):
        client.cookies.clear()
        if case == "foreign_cookie":
            client.cookies.set(
                client.app.state.settings.oauth_cookie, secrets.token_urlsafe(32)
            )
    if case == "expired":
        db_call(
            client,
            "oauth_states",
            "update_many",
            {},
            {"$set": {"expires_at": utcnow() - timedelta(seconds=1)}},
        )
    if case == "duplicate_state":
        result = client.get(
            f"/api/auth/google/callback?state={state}&state={state}&code=anything",
            follow_redirects=False,
        )
    elif case == "missing_code":
        result = finish(oauth, state=state, code="")
    elif case == "wrong_iss":
        result = finish(oauth, state=state, iss="https://evil.example")
    else:
        result = finish(oauth, state=state)
    assert "oauth_error=" in result.headers["location"]
    assert client.get("/api/auth/me").status_code == 401
    assert not control["requests"]


@pytest.mark.parametrize(
    "changes",
    [
        {"iss": "https://evil.example"},
        {"aud": "other-client"},
        {"aud": ["test-client.apps.googleusercontent.com"]},
        {"exp": 1},
        {"iat": 9999999999},
        {"nonce": "wrong"},
        {"email_verified": False},
        {"email_verified": "true"},
        {"email": "invalid"},
        {"sub": ""},
        {"azp": "other"},
        {"exp": int(utcnow().timestamp()) + 99999},
    ],
)
def test_identity_claim_validation(oauth, changes):
    client, control = oauth
    control["claims"] = changes
    begin(oauth)
    response = finish(oauth)
    assert response.headers["location"].endswith("oauth_error=invalid_response")
    assert db_call(client, "users", "count_documents", {}) == 0
    assert client.get("/api/auth/me").status_code == 401


@pytest.mark.parametrize(
    "claim", ["iss", "aud", "exp", "iat", "sub", "nonce", "email", "email_verified"]
)
def test_required_identity_claims(oauth, claim):
    client, control = oauth
    control["omit"] = [claim]
    begin(oauth)
    assert finish(oauth).headers["location"].endswith("oauth_error=invalid_response")
    assert client.get("/api/auth/me").status_code == 401


@pytest.mark.parametrize(
    "variant", ["signature", "unsigned", "unknown_key", "invalid_keys"]
)
def test_identity_signature_and_trusted_keys(oauth, variant):
    client, control = oauth
    if variant == "signature":
        control["key"] = WRONG_KEY
    if variant == "unsigned":
        control["raw"] = jwt.encode({"sub": "attacker"}, key="", algorithm="none")
    if variant == "unknown_key":
        control["kid"] = "attacker-key"
    if variant == "invalid_keys":
        control["keys"] = [{**JWK, "use": "enc"}]
    begin(oauth)
    assert finish(oauth).headers["location"].endswith("oauth_error=invalid_response")
    assert client.get("/api/auth/me").status_code == 401


def test_email_collision_does_not_link_or_authenticate(oauth):
    client, _ = oauth
    registered = register(client, "google@example.com").json()
    begin(oauth)
    assert finish(oauth).headers["location"].endswith("oauth_error=account_conflict")
    user = db_call(client, "users", "find_one", {"_id": registered["id"]})
    assert "google_sub" not in user and user["password_hash"]
    assert client.get("/api/auth/me").status_code == 401
    assert db_call(client, "users", "count_documents", {}) == 1


@pytest.mark.parametrize(
    "email,verified", [("google@example.com", True), ("alice@example.com", False)]
)
def test_authenticated_link_preserves_password_and_email(oauth, email, verified):
    client, _ = oauth
    user = register(client, email).json()
    login(client, email)
    old_hash = db_call(client, "users", "find_one", {"_id": user["id"]})[
        "password_hash"
    ]
    begin(oauth, "link")
    assert (
        finish(oauth).headers["location"]
        == "http://localhost:3000/profile?google=linked"
    )
    profile = client.get("/api/auth/me").json()
    assert profile["id"] == user["id"] and profile["email"] == email
    assert profile["authentication_provider"] == "password+google"
    assert profile["email_verified"] is verified
    assert (
        db_call(client, "users", "find_one", {"_id": user["id"]})["password_hash"]
        == old_hash
    )
    assert login(client, email).status_code == 200


def test_link_requires_authentication_csrf_and_original_session(oauth):
    client, _ = oauth
    assert (
        client.post(
            "/api/auth/google/start",
            json={"mode": "link"},
            headers=csrf_headers(client),
        ).status_code
        == 401
    )
    register(client)
    login(client)
    assert (
        client.post("/api/auth/google/start", json={"mode": "link"}).status_code == 403
    )
    begin(oauth, "link")
    # A fresh password login must not authorize a flow bound to an older session.
    login(client)
    assert finish(oauth).headers["location"].endswith("oauth_error=session_expired")
    assert not client.get("/api/auth/me").json()["google_connected"]


def test_expired_link_session_is_rejected(oauth):
    client, _ = oauth
    register(client)
    login(client)
    begin(oauth, "link")
    db_call(
        client,
        "sessions",
        "update_many",
        {},
        {"$set": {"expires_at": utcnow() - timedelta(seconds=1)}},
    )
    assert finish(oauth).headers["location"].endswith("oauth_error=session_expired")
    assert not db_call(client, "users", "find_one", {}).get("google_sub")


def test_identity_cannot_link_two_users(oauth):
    client, _ = oauth
    begin(oauth)
    finish(oauth)
    client.post("/api/auth/logout", headers=csrf_headers(client))
    register(client)
    login(client)
    begin(oauth, "link")
    assert finish(oauth).headers["location"].endswith("oauth_error=account_conflict")
    assert not client.get("/api/auth/me").json()["google_connected"]


def test_callback_replay_and_concurrent_claim(oauth):
    client, control = oauth
    state = begin(oauth)
    cookie = client.cookies.get(client.app.state.settings.oauth_cookie)
    url = f"/api/auth/google/callback?state={state}&code=test-code"
    headers = {"Cookie": f"{client.app.state.settings.oauth_cookie}={cookie}"}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: client.get(url, headers=headers, follow_redirects=False),
                range(2),
            )
        )
    assert sum(r.headers["location"] == "http://localhost:3000/" for r in results) == 1
    assert sum(str(r.url) == TOKEN_URL for r in control["requests"]) == 1
    assert db_call(client, "sessions", "count_documents", {}) == 1
    assert (
        client.get(url, headers=headers, follow_redirects=False)
        .headers["location"]
        .endswith("oauth_error=expired_request")
    )


def test_google_cancelled_does_not_exchange(oauth):
    client, control = oauth
    state = begin(oauth)
    result = client.get(
        f"/api/auth/google/callback?state={state}&error=access_denied&error_description=private",
        follow_redirects=False,
    )
    assert result.headers["location"].endswith("oauth_error=cancelled")
    assert "private" not in result.text and not control["requests"]


@pytest.mark.parametrize("case", ["timeout", "invalid_code", "rate", "outage"])
def test_provider_failures_are_safe(oauth, case):
    client, control = oauth
    if case == "timeout":
        control["timeout"] = True
    else:
        control["status"] = {"invalid_code": 400, "rate": 429, "outage": 503}[case]
    begin(oauth)
    result = finish(oauth)
    assert "oauth_error=" in result.headers["location"]
    assert "private" not in result.text and "test-code" not in str(result.headers)
    assert client.get("/api/auth/me").status_code == 401


def test_oauth_start_rate_limits_and_strict_input(oauth):
    client, _ = oauth
    client.app.state.settings.oauth_start_limit = 1
    assert (
        client.post(
            "/api/auth/google/start",
            json={"mode": "login", "redirect": "https://evil.example"},
            headers=csrf_headers(client),
        ).status_code
        == 422
    )
    begin(oauth)
    assert (
        client.post(
            "/api/auth/google/start", json={}, headers=csrf_headers(client)
        ).status_code
        == 429
    )


def test_callback_rate_limit(oauth):
    client, _ = oauth
    client.app.state.settings.login_ip_limit = 1
    client.get("/api/auth/google/callback", follow_redirects=False)
    assert (
        client.get("/api/auth/google/callback", follow_redirects=False).status_code
        == 429
    )


def test_oauth_logout_revocation_and_expiry(oauth):
    client, _ = oauth
    begin(oauth)
    finish(oauth)
    token = client.cookies.get(client.app.state.settings.session_cookie)
    assert (
        client.post("/api/auth/logout", headers=csrf_headers(client)).status_code == 204
    )
    client.cookies.set(client.app.state.settings.session_cookie, token)
    assert client.get("/api/auth/me").status_code == 401


def test_google_secret_redaction_and_access_log_queries(oauth):
    client, _ = oauth
    secret = client.app.state.settings.google_client_secret.get_secret_value()
    assert secret not in redact(secret, credential_values(client.app.state.settings))
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        1,
        "%s %s %s %s %s",
        (
            "127.0.0.1",
            "GET",
            "/api/auth/google/callback?code=private&state=hidden",
            "HTTP/1.1",
            303,
        ),
        None,
    )
    assert AccessQueryFilter().filter(record)
    assert "private" not in record.getMessage() and "hidden" not in record.getMessage()


def test_config_requires_exact_frontend_callback_and_complete_credentials():
    base = dict(
        _env_file=None,
        jwt_secret=secrets.token_urlsafe(48),
        google_client_id="client.apps.googleusercontent.com",
        google_client_secret="test-secret",
        google_redirect_uri="http://localhost:3000/api/auth/google/callback",
    )
    assert Settings(**base).google_enabled
    for changes in (
        {"google_client_secret": ""},
        {"google_redirect_uri": "http://evil.example/api/auth/google/callback"},
        {
            "google_redirect_uri": "http://localhost:3000/api/auth/google/callback?redirect=evil"
        },
        {"google_redirect_uri": "http://localhost:3000/other"},
        {"google_client_id": "invalid"},
    ):
        with pytest.raises(ValidationError):
            Settings(**{**base, **changes})
