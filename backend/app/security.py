"""JWT verification, bounded password work, and signed session-bound CSRF."""

import asyncio
import hashlib
import hmac
import secrets
from datetime import datetime, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import HTTPException, Request
from pymongo import ReturnDocument
from starlette.concurrency import run_in_threadpool

from .config import Settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Passwords:
    def __init__(self):
        # OWASP Argon2id minimum: 19 MiB, 2 iterations, parallelism 1.
        self.hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
        self.slots = asyncio.Semaphore(2)
        self.dummy = self.hasher.hash(secrets.token_urlsafe(32))

    async def hash(self, password: str) -> str:
        async with self.slots:
            return await run_in_threadpool(self.hasher.hash, password)

    async def verify(self, hashed: str, password: str) -> bool:
        async with self.slots:
            try:
                return await run_in_threadpool(self.hasher.verify, hashed, password)
            except (VerificationError, InvalidHashError):
                return False


def encode_token(
    settings: Settings, *, subject: str, token_id: str, use: str, expires: datetime
) -> str:
    now = utcnow()
    return jwt.encode(
        {
            "sub": subject,
            "jti": token_id,
            "token_use": use,
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience + (":csrf" if use == "csrf" else ""),
            "iat": now,
            "nbf": now,
            "exp": expires,
        },
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )


def decode_token(settings: Settings, token: str, use: str) -> dict:
    claims = jwt.decode(
        token,
        settings.jwt_secret.get_secret_value(),
        algorithms=["HS256"],
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience + (":csrf" if use == "csrf" else ""),
        options={
            "require": ["sub", "jti", "exp", "iat", "nbf", "iss", "aud", "token_use"]
        },
    )
    if (
        claims["token_use"] != use
        or not isinstance(claims["sub"], str)
        or not isinstance(claims["jti"], str)
    ):
        raise jwt.InvalidTokenError("Invalid token claims")
    return claims


def unauthorized() -> HTTPException:
    return HTTPException(status_code=401, detail="Authentication required")


async def current_identity(request: Request) -> tuple[dict, dict]:
    settings = request.app.state.settings
    token = request.cookies.get(settings.session_cookie)
    if not token:
        raise unauthorized()
    try:
        claims = decode_token(settings, token, "access")
    except jwt.InvalidTokenError:
        raise unauthorized() from None
    session = await request.app.state.db.sessions.find_one(
        {
            "_id": claims["jti"],
            "user_id": claims["sub"],
            "expires_at": {"$gt": utcnow()},
        }
    )
    if not session:
        raise unauthorized()
    user = await request.app.state.db.users.find_one({"_id": session["user_id"]})
    if not user:
        raise unauthorized()
    return user, session


def cookie_options(settings: Settings, max_age: int) -> dict:
    return {
        "httponly": True,
        "secure": settings.secure_cookies,
        "samesite": "lax",
        "path": "/",
        "max_age": max_age,
    }


def session_id_from_cookie(request: Request) -> str:
    settings = request.app.state.settings
    try:
        return decode_token(
            settings, request.cookies.get(settings.session_cookie, ""), "access"
        )["jti"]
    except jwt.InvalidTokenError:
        return ""


def require_csrf(request: Request) -> None:
    settings = request.app.state.settings
    if request.headers.get("origin") not in settings.origins:
        raise HTTPException(status_code=403, detail="Request origin is not allowed")
    cookie = request.cookies.get(settings.csrf_cookie, "")
    header = request.headers.get("x-csrf-token", "")
    if (
        not cookie
        or not header
        or not hmac.compare_digest(cookie.encode(), header.encode())
    ):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    try:
        claims = decode_token(settings, header, "csrf")
        if claims["sub"] != session_id_from_cookie(request):
            raise jwt.InvalidTokenError("CSRF session mismatch")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=403, detail="CSRF validation failed") from None


async def limit_attempts(
    request: Request, category: str, identifier: str, limit: int
) -> None:
    """Atomic, shared fixed-window counters, including across backend workers."""
    settings = request.app.state.settings
    now = utcnow()
    window = settings.rate_window_seconds
    bucket = int(now.timestamp()) // window
    digest = hmac.new(
        settings.jwt_secret.get_secret_value().encode(),
        identifier.encode(),
        hashlib.sha256,
    ).hexdigest()
    key = f"{category}:{digest}:{bucket}"
    event = await request.app.state.db.security_events.find_one_and_update(
        {"_id": key},
        {
            "$inc": {"attempts": 1},
            "$setOnInsert": {
                "kind": "auth_rate_limit",
                "category": category,
                "expires_at": datetime.fromtimestamp(
                    (bucket + 2) * window, timezone.utc
                ),
            },
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    if event["attempts"] > limit:
        retry = (bucket + 1) * window - int(now.timestamp())
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Try again later.",
            headers={"Retry-After": str(retry)},
        )
