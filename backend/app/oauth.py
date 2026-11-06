"""Google Authorization Code + PKCE/OIDC. Fixed endpoints, no provider token storage."""

import asyncio
import base64
import hashlib
import hmac
import logging
import re
import secrets
import time
import uuid
from datetime import timedelta
from typing import Literal
from urllib.parse import urlencode, urlparse

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, EmailStr, TypeAdapter
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

from .auth import create_session
from .guards import strict_json
from .security import (
    cookie_options,
    current_identity,
    limit_attempts,
    require_csrf,
    utcnow,
)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])
AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")
STATE_SECONDS = 300
log = logging.getLogger(__name__)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class OAuthFailure(Exception):
    def __init__(self, category="invalid_response"):
        self.category = category
        super().__init__(category)


class AccessQueryFilter(logging.Filter):
    """Uvicorn's formatted request target otherwise includes OAuth code/state."""

    def filter(self, record):
        if isinstance(record.args, tuple) and len(record.args) == 5:
            args = list(record.args)
            if isinstance(args[2], str):
                args[2] = args[2].split("?", 1)[0]
                record.args = tuple(args)
        return True


def install_access_filter():
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, AccessQueryFilter) for f in logger.filters):
        logger.addFilter(AccessQueryFilter())


class GoogleProvider:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(5, connect=2),
            follow_redirects=False,
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
            transport=transport,
        )
        self.keys = {}
        self.keys_at = 0.0
        self.key_lock = asyncio.Lock()
        self.slots = asyncio.Semaphore(4)

    async def close(self):
        await self.client.aclose()

    async def _json(self, method, url, **kwargs):
        try:
            async with self.client.stream(
                method, url, headers={"Accept-Encoding": "identity"}, **kwargs
            ) as response:
                if response.status_code != 200:
                    raise OAuthFailure(
                        "unavailable"
                        if response.status_code >= 429
                        else "invalid_response"
                    )
                if response.headers.get("content-encoding", "identity") != "identity":
                    raise OAuthFailure()
                if (
                    not response.headers.get("content-type", "")
                    .lower()
                    .startswith("application/json")
                ):
                    raise OAuthFailure()
                data = bytearray()
                async for chunk in response.aiter_bytes(4096):
                    data.extend(chunk)
                    if len(data) > 65536:
                        raise OAuthFailure()
                result = strict_json(bytes(data))
                if not isinstance(result, dict):
                    raise OAuthFailure()
                return result
        except (httpx.HTTPError, TimeoutError):
            raise OAuthFailure("unavailable") from None
        except (ValueError, RecursionError, UnicodeError):
            raise OAuthFailure() from None

    async def _key(self, kid):
        async with self.key_lock:
            now = time.monotonic()
            if now - self.keys_at > 300 or kid not in self.keys:
                # Avoid a JWKS fetch storm for attacker-controlled unknown kids.
                if self.keys_at and now - self.keys_at < 60:
                    raise OAuthFailure()
                payload = await self._json("GET", JWKS_URL)
                keys = payload.get("keys")
                if not isinstance(keys, list) or not 1 <= len(keys) <= 16:
                    raise OAuthFailure()
                parsed = {}
                for item in keys:
                    if (
                        not isinstance(item, dict)
                        or item.get("kty") != "RSA"
                        or item.get("use") != "sig"
                        or item.get("alg", "RS256") != "RS256"
                    ):
                        raise OAuthFailure()
                    key_id = item.get("kid")
                    if (
                        not isinstance(key_id, str)
                        or not 1 <= len(key_id) <= 128
                        or key_id in parsed
                    ):
                        raise OAuthFailure()
                    try:
                        key = jwt.PyJWK.from_dict(item, algorithm="RS256").key
                        if key.key_size < 2048:
                            raise OAuthFailure()
                    except (ValueError, TypeError, jwt.PyJWTError):
                        raise OAuthFailure() from None
                    parsed[key_id] = key
                self.keys, self.keys_at = parsed, now
            if kid not in self.keys:
                raise OAuthFailure()
            return self.keys[kid]

    async def exchange(self, code: str, state: dict):
        if self.slots.locked():
            raise OAuthFailure("unavailable")
        async with self.slots:
            try:
                async with asyncio.timeout(12):
                    tokens = await self._json(
                        "POST",
                        TOKEN_URL,
                        data={
                            "grant_type": "authorization_code",
                            "code": code,
                            "client_id": self.settings.google_client_id,
                            "client_secret": self.settings.google_client_secret.get_secret_value(),
                            "redirect_uri": self.settings.google_redirect_uri,
                            "code_verifier": state["verifier"],
                        },
                    )
                    raw = tokens.get("id_token")
                    if not isinstance(raw, str) or len(raw) > 16384:
                        raise OAuthFailure()
                    header = jwt.get_unverified_header(raw)
                    if header.get("alg") != "RS256" or any(
                        k in header for k in ("jku", "jwk", "x5u", "crit")
                    ):
                        raise OAuthFailure()
                    kid = header.get("kid")
                    if not isinstance(kid, str) or not 1 <= len(kid) <= 128:
                        raise OAuthFailure()
                    key = await self._key(kid)
                    claims = jwt.decode(
                        raw,
                        key,
                        algorithms=["RS256"],
                        audience=self.settings.google_client_id,
                        issuer=ISSUERS,
                        options={
                            "require": [
                                "iss",
                                "aud",
                                "exp",
                                "iat",
                                "sub",
                                "nonce",
                                "email",
                                "email_verified",
                            ],
                            "strict_aud": True,
                        },
                    )
                    if (
                        not isinstance(claims["sub"], str)
                        or not re.fullmatch(r"[A-Za-z0-9_-]{1,255}", claims["sub"])
                        or not isinstance(claims["nonce"], str)
                        or not hmac.compare_digest(
                            digest(claims["nonce"]), state["nonce_hash"]
                        )
                        or claims["email_verified"] is not True
                        or claims.get("azp", self.settings.google_client_id)
                        != self.settings.google_client_id
                        or type(claims["iat"]) is not int
                        or type(claims["exp"]) is not int
                        or claims["exp"] - claims["iat"] > 7200
                        or not isinstance(claims["email"], str)
                        or len(claims["email"]) > 254
                    ):
                        raise OAuthFailure()
                    email = str(
                        TypeAdapter(EmailStr).validate_python(
                            claims["email"].strip().casefold()
                        )
                    ).casefold()
                    name = claims.get("name", "Google User")
                    if not isinstance(name, str):
                        raise OAuthFailure()
                    name = " ".join(name.split())[:100]
                    if len(name) < 2:
                        name = "Google User"
                    picture = claims.get("picture")
                    if isinstance(picture, str) and len(picture) <= 2048:
                        p = urlparse(picture)
                        picture = (
                            picture
                            if (
                                p.scheme == "https"
                                and p.hostname
                                and p.hostname.endswith(".googleusercontent.com")
                                and p.port in (None, 443)
                                and not p.username
                                and not p.password
                                and not p.fragment
                                and not p.query
                            )
                            else None
                        )
                    else:
                        picture = None
                    return {
                        "sub": claims["sub"],
                        "email": email,
                        "name": name,
                        "picture": picture,
                    }
            except TimeoutError:
                raise OAuthFailure("unavailable") from None
            except (ValueError, KeyError, TypeError, jwt.PyJWTError):
                raise OAuthFailure() from None


class StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["login", "link"] = "login"


@router.get("/providers")
async def providers(request: Request):
    return {"google": {"enabled": request.app.state.settings.google_enabled}}


@router.post("/google/start", dependencies=[Depends(require_csrf)])
async def start(payload: StartRequest, request: Request):
    settings = request.app.state.settings
    if not settings.google_enabled:
        raise HTTPException(503, "Google sign-in is not configured")
    origin = request.headers["origin"]
    callback = urlparse(settings.google_redirect_uri)
    if origin != f"{callback.scheme}://{callback.netloc}":
        raise HTTPException(
            503, "Google sign-in is unavailable for this application origin"
        )
    ip = request.client.host if request.client else "unknown"
    await limit_attempts(request, "oauth_start_ip", ip, settings.oauth_start_limit)
    identity = None
    if payload.mode == "link":
        identity = await current_identity(request)
        if not identity[0].get("password_hash") or identity[0].get("google_sub"):
            raise HTTPException(
                409, "Google account linking is not available for this account"
            )
        await limit_attempts(
            request, "oauth_link_user", identity[0]["_id"], settings.oauth_start_limit
        )
    state, binding, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(4))
    record = {
        "_id": digest(state),
        "binding_hash": digest(binding),
        "nonce_hash": digest(nonce),
        "verifier": verifier,
        "mode": payload.mode,
        "origin": origin,
        "expires_at": utcnow() + timedelta(seconds=STATE_SECONDS),
        "user_id": identity[0]["_id"] if identity else None,
        "session_id": identity[1]["_id"] if identity else None,
    }
    await request.app.state.db.oauth_states.insert_one(record)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    from fastapi.responses import JSONResponse

    response = JSONResponse(
        {"authorization_url": AUTHORIZATION_URL + "?" + urlencode(params)}
    )
    response.set_cookie(
        settings.oauth_cookie, binding, **cookie_options(settings, STATE_SECONDS)
    )
    return response


def redirect(request, path, *, origin=None):
    settings = request.app.state.settings
    response = RedirectResponse((origin or settings.origins[0]) + path, status_code=303)
    response.delete_cookie(
        settings.oauth_cookie,
        path="/",
        secure=settings.secure_cookies,
        httponly=True,
        samesite="lax",
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


async def resolve_user(request, identity, flow):
    users = request.app.state.db.users
    sub = identity["sub"]
    if flow["mode"] == "link":
        try:
            user, session = await current_identity(request)
        except HTTPException:
            raise OAuthFailure("session_expired") from None
        if user["_id"] != flow["user_id"] or session["_id"] != flow["session_id"]:
            raise OAuthFailure("session_expired")
        if user.get("google_sub"):
            raise OAuthFailure("already_linked")
        update = {
            "google_sub": sub,
            "google_linked_at": utcnow(),
            "profile_picture": identity["picture"],
        }
        # Verification refers to the retained local email, not any other Google email.
        if user["email"] == identity["email"]:
            update["email_verified"] = True
        try:
            linked = await users.find_one_and_update(
                {
                    "_id": user["_id"],
                    "google_sub": {"$exists": False},
                    "password_hash": {"$type": "string"},
                },
                {"$set": update},
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            raise OAuthFailure("account_conflict") from None
        if not linked:
            raise OAuthFailure("already_linked")
        return linked
    # The stable subject is authoritative. Email is only a uniqueness/conflict check.
    existing = await users.find_one({"google_sub": sub})
    if existing:
        return existing
    user = {
        "_id": uuid.uuid4().hex,
        "full_name": identity["name"],
        "email": identity["email"],
        "email_verified": True,
        "google_sub": sub,
        "google_linked_at": utcnow(),
        "profile_picture": identity["picture"],
        "created_at": utcnow(),
    }
    try:
        await users.insert_one(user)
    except DuplicateKeyError:
        # Concurrent first sign-ins may race; only the same subject may authenticate.
        existing = await users.find_one({"google_sub": sub})
        if not existing:
            raise OAuthFailure("account_conflict") from None
        return existing
    return user


@router.get("/google/callback")
async def callback(request: Request):
    settings = request.app.state.settings
    flow = None
    try:
        if not settings.google_enabled:
            raise OAuthFailure("unavailable")
        ip = request.client.host if request.client else "unknown"
        await limit_attempts(request, "oauth_callback_ip", ip, settings.login_ip_limit)
        query = request.query_params
        if len(request.scope.get("query_string", b"")) > 8192:
            raise OAuthFailure()
        if any(len(query.getlist(key)) != 1 for key in query):
            raise OAuthFailure()
        state = query.get("state", "")
        binding = request.cookies.get(settings.oauth_cookie, "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", state) or not re.fullmatch(
            r"[A-Za-z0-9_-]{43}", binding
        ):
            raise OAuthFailure("expired_request")
        # Consume only a matching browser's unexpired flow. Failed/replayed
        # callbacks cannot resurrect it; TTL deletion timing is never trusted.
        flow = await request.app.state.db.oauth_states.find_one_and_delete(
            {
                "_id": digest(state),
                "binding_hash": digest(binding),
                "expires_at": {"$gt": utcnow()},
            }
        )
        if not flow:
            raise OAuthFailure("expired_request")
        if "error" in query:
            raise OAuthFailure(
                "cancelled" if query["error"] == "access_denied" else "invalid_response"
            )
        code = query.get("code", "")
        if (
            not code
            or len(code) > 2048
            or any(ord(c) < 33 or ord(c) > 126 for c in code)
        ):
            raise OAuthFailure()
        if "iss" in query and query["iss"] not in ISSUERS:
            raise OAuthFailure()
        identity = await request.app.state.google_provider.exchange(code, flow)
        user = await resolve_user(request, identity, flow)
        response = redirect(
            request,
            "/profile?google=linked" if flow["mode"] == "link" else "/",
            origin=flow["origin"],
        )
        if flow["mode"] == "login":
            await create_session(request, response, user)
        return response
    except OAuthFailure as exc:
        category = exc.category
    except PyMongoError:
        category = "temporarily_unavailable"
    # Fixed categories only: no exception bodies, identifiers or callback values.
    log.info("Google authentication result: %s", category)
    path = "/profile" if flow and flow["mode"] == "link" else "/login"
    return redirect(
        request,
        path + "?oauth_error=" + category,
        origin=flow["origin"] if flow else None,
    )
