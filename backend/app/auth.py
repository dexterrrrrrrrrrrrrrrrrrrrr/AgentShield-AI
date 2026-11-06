import secrets
import uuid
from datetime import timedelta

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pymongo.errors import DuplicateKeyError

from .schemas import LoginInput, RegisterInput, UserResponse, public_user
from .security import (
    cookie_options,
    current_identity,
    decode_token,
    encode_token,
    limit_attempts,
    require_csrf,
    session_id_from_cookie,
    utcnow,
)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.get("/csrf")
async def csrf(request: Request, response: Response):
    settings = request.app.state.settings
    subject = session_id_from_cookie(request)
    existing = request.cookies.get(settings.csrf_cookie, "")
    try:
        if decode_token(settings, existing, "csrf")["sub"] == subject:
            return {"csrf_token": existing}
    except jwt.InvalidTokenError:
        pass
    token = encode_token(
        settings,
        subject=subject,
        token_id=secrets.token_urlsafe(32),
        use="csrf",
        expires=utcnow() + timedelta(minutes=30),
    )
    response.set_cookie(settings.csrf_cookie, token, **cookie_options(settings, 1800))
    return {"csrf_token": token}


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=201,
    dependencies=[Depends(require_csrf)],
)
async def register(payload: RegisterInput, request: Request):
    settings = request.app.state.settings
    ip = request.client.host if request.client else "unknown"
    await limit_attempts(request, "register_ip", ip, settings.register_ip_limit)
    user = {
        "_id": uuid.uuid4().hex,
        "full_name": payload.full_name,
        "email": str(payload.email),
        "password_hash": await request.app.state.passwords.hash(
            payload.password.get_secret_value()
        ),
        "created_at": utcnow(),
    }
    try:
        await request.app.state.db.users.insert_one(user)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409, detail="Unable to register with these details"
        ) from None
    return public_user(user, authenticated=False)


@router.post(
    "/login", response_model=UserResponse, dependencies=[Depends(require_csrf)]
)
async def login(payload: LoginInput, request: Request, response: Response):
    settings = request.app.state.settings
    ip = request.client.host if request.client else "unknown"
    await limit_attempts(request, "login_ip", ip, settings.login_ip_limit)
    await limit_attempts(
        request, "login_email", str(payload.email), settings.login_email_limit
    )
    db = request.app.state.db
    passwords = request.app.state.passwords
    user = await db.users.find_one({"email": str(payload.email)})
    valid = await passwords.verify(
        user.get("password_hash") or passwords.dummy if user else passwords.dummy,
        payload.password.get_secret_value(),
    )
    if not user or not user.get("password_hash") or not valid:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if passwords.hasher.check_needs_rehash(user["password_hash"]):
        await db.users.update_one(
            {"_id": user["_id"]},
            {
                "$set": {
                    "password_hash": await passwords.hash(
                        payload.password.get_secret_value()
                    )
                }
            },
        )
    return await create_session(request, response, user)


async def create_session(request: Request, response: Response, user: dict):
    """Shared local session infrastructure; provider tokens never become sessions."""
    settings = request.app.state.settings
    db = request.app.state.db
    # JWT NumericDate is whole seconds; expose the same real expiration in JSON.
    now = utcnow().replace(microsecond=0)
    expires = now + timedelta(minutes=settings.access_token_minutes)
    sid = secrets.token_urlsafe(32)
    await db.sessions.insert_one(
        {"_id": sid, "user_id": user["_id"], "created_at": now, "expires_at": expires}
    )
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"last_login_at": now}})
    user = {**user, "last_login_at": now}
    token = encode_token(
        settings, subject=user["_id"], token_id=sid, use="access", expires=expires
    )
    response.set_cookie(
        settings.session_cookie,
        token,
        **cookie_options(settings, settings.access_token_minutes * 60),
    )
    # Pre-login CSRF credentials cannot be reused for the new session.
    response.delete_cookie(
        settings.csrf_cookie,
        path="/",
        secure=settings.secure_cookies,
        httponly=True,
        samesite="lax",
    )
    return public_user(user, session_expires_at=expires)


@router.get("/me", response_model=UserResponse)
async def me(identity=Depends(current_identity)):
    return public_user(identity[0], session_expires_at=identity[1]["expires_at"])


@router.post("/logout", status_code=204, dependencies=[Depends(require_csrf)])
async def logout(request: Request, identity=Depends(current_identity)):
    _, session = identity
    await request.app.state.db.sessions.delete_one(
        {"_id": session["_id"], "user_id": session["user_id"]}
    )
    settings = request.app.state.settings
    response = Response(status_code=204)
    for name in (settings.session_cookie, settings.csrf_cookie, settings.oauth_cookie):
        response.delete_cookie(
            name,
            path="/",
            secure=settings.secure_cookies,
            httponly=True,
            samesite="lax",
        )
    response.headers["Cache-Control"] = "no-store"
    return response
