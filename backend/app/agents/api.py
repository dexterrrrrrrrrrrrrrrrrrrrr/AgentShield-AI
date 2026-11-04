import time
import uuid
from datetime import timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pymongo import ReturnDocument

from ..security import current_identity, limit_attempts, require_csrf, utcnow
from .engine import redact
from .tools import NAMES

SessionID = Annotated[str, Path(pattern=r"^[a-f0-9]{32}$")]

router = APIRouter(prefix="/api/agent", tags=["Agents"])


class SessionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["groq", "ollama"] = "groq"
    model: str = Field(min_length=1, max_length=100)
    allowed_tools: list[str] = Field(default_factory=lambda: list(NAMES), max_length=4)

    @field_validator("allowed_tools")
    @classmethod
    def allowlist(cls, value):
        if len(value) != len(set(value)) or any(v not in NAMES for v in value):
            raise ValueError("Invalid tool allowlist")
        return value


class MessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=4000)

    @field_validator("content")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Message is empty")
        return value


def owner(identity):
    return identity[0]["_id"]


async def get_owned(request, sid, uid):
    item = await request.app.state.db.agent_sessions.find_one(
        {"_id": sid, "user_id": uid}
    )
    if not item:
        raise HTTPException(404, "Agent session not found")
    return item


def public(item):
    return {
        "id": item["_id"],
        **{k: v for k, v in item.items() if k not in ("_id", "user_id", "lease_until")},
    }


@router.get("/providers")
async def providers(request: Request, identity=Depends(current_identity)):
    s = request.app.state.settings
    return {
        "providers": [
            {
                "id": "groq",
                "model": s.groq_model,
                "enabled": True,
                "configured": bool(s.groq_api_key.get_secret_value()),
            },
            {
                "id": "ollama",
                "model": s.ollama_model,
                "enabled": s.ollama_enabled,
                "configured": s.ollama_enabled,
            },
        ],
        "tools": NAMES,
    }


@router.post("/sessions", status_code=201, dependencies=[Depends(require_csrf)])
async def create(
    payload: SessionInput, request: Request, identity=Depends(current_identity)
):
    uid, db, s = owner(identity), request.app.state.db, request.app.state.settings
    await limit_attempts(request, "agent_create", uid, 10)
    expected = s.groq_model if payload.provider == "groq" else s.ollama_model
    if payload.model != expected or (
        payload.provider == "ollama" and not s.ollama_enabled
    ):
        raise HTTPException(422, "Provider or model is not enabled by the server")
    # Fixed owner config, used as an atomic session quota; no credentials stored.
    await db.agent_configs.update_one(
        {"_id": uid, "user_id": uid},
        {"$setOnInsert": {"session_count": 0}},
        upsert=True,
    )
    quota = await db.agent_configs.find_one_and_update(
        {"_id": uid, "user_id": uid, "session_count": {"$lt": 50}},
        {"$inc": {"session_count": 1}},
        return_document=ReturnDocument.AFTER,
    )
    if not quota:
        raise HTTPException(429, "Session limit reached. Delete an old conversation.")
    item = {
        "_id": uuid.uuid4().hex,
        "user_id": uid,
        **payload.model_dump(),
        "created_at": utcnow(),
        "updated_at": utcnow(),
        "status": "idle",
        "turns": 0,
    }
    try:
        await db.agent_sessions.insert_one(item)
    except Exception:
        await db.agent_configs.update_one(
            {"_id": uid, "user_id": uid}, {"$inc": {"session_count": -1}}
        )
        raise
    return public(item)


@router.get("/sessions")
async def sessions(
    request: Request,
    offset: int = Query(0, ge=0, le=10000),
    limit: int = Query(20, ge=1, le=50),
    identity=Depends(current_identity),
):
    cursor = (
        request.app.state.db.agent_sessions.find({"user_id": owner(identity)})
        .sort([("created_at", -1), ("_id", -1)])
        .skip(offset)
        .limit(limit)
    )
    return {"sessions": [public(v) for v in await cursor.to_list(length=limit)]}


@router.get("/sessions/{sid}/messages")
async def history(
    sid: SessionID,
    request: Request,
    offset: int = Query(0, ge=0, le=1000),
    limit: int = Query(20, ge=1, le=50),
    identity=Depends(current_identity),
):
    uid = owner(identity)
    session = await get_owned(request, sid, uid)
    docs = (
        await request.app.state.db.agent_messages.find(
            {"user_id": uid, "session_id": sid}
        )
        .sort("turn", 1)
        .skip(offset)
        .limit(limit)
        .to_list(length=limit)
    )
    return {"session": public(session), "messages": [public(v) for v in docs]}


@router.get("/sessions/{sid}/events")
async def events(
    sid: SessionID,
    request: Request,
    offset: int = Query(0, ge=0, le=1000),
    limit: int = Query(20, ge=1, le=50),
    identity=Depends(current_identity),
):
    data = await history(sid, request, offset, limit, identity)
    return {
        "executions": [
            {
                "id": v["id"],
                "status": v["status"],
                "events": v["events"],
                "created_at": v["created_at"],
            }
            for v in data["messages"]
        ]
    }


@router.post("/sessions/{sid}/messages", dependencies=[Depends(require_csrf)])
async def send(
    sid: SessionID,
    payload: MessageInput,
    request: Request,
    identity=Depends(current_identity),
):
    uid, db, s = owner(identity), request.app.state.db, request.app.state.settings
    await get_owned(request, sid, uid)
    await limit_attempts(request, "agent_message", uid, s.agent_user_limit)
    if request.app.state.agent_active >= 2:
        raise HTTPException(429, "Agent capacity reached. Retry shortly.")
    request.app.state.agent_active += 1
    locked = None
    turn = None
    started = time.monotonic()
    finished = False
    try:
        locked = await db.agent_sessions.find_one_and_update(
            {
                "_id": sid,
                "user_id": uid,
                "turns": {"$lt": 50},
                "$or": [
                    {"status": {"$ne": "running"}},
                    {"lease_until": {"$lt": utcnow()}},
                ],
            },
            {
                "$set": {
                    "status": "running",
                    "started_at": utcnow(),
                    "lease_until": utcnow() + timedelta(seconds=120),
                },
                "$inc": {"turns": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        if not locked:
            raise HTTPException(
                409, "Session is running or its message limit was reached"
            )
        old = (
            await db.agent_messages.find(
                {"session_id": sid, "user_id": uid, "status": "completed"}
            )
            .sort("turn", -1)
            .limit(6)
            .to_list(length=6)
        )
        context = []
        for v in reversed(old):
            context.extend(
                [
                    {"role": "user", "content": v["user_content"][:2000]},
                    {"role": "assistant", "content": v["assistant_content"][:2000]},
                ]
            )

        def clean(text):
            return redact(
                text,
                [s.groq_api_key.get_secret_value(), s.jwt_secret.get_secret_value()],
            )

        prompt = clean(payload.content)
        # Persist the user turn before external I/O. No partial tool effects exist.
        turn = {
            "_id": uuid.uuid4().hex,
            "user_id": uid,
            "session_id": sid,
            "turn": locked["turns"],
            "provider": locked["provider"],
            "model": locked["model"],
            "user_content": prompt,
            "assistant_content": "",
            "events": [{"kind": "started"}],
            "status": "running",
            "created_at": utcnow(),
        }
        await db.agent_messages.insert_one(turn)
        monitor = request.app.state.monitor
        await monitor.emit(
            uid,
            "agent_started",
            agent_id=sid,
            execution_id=turn["_id"],
            result="running",
        )

        async def on_event(kind, **metadata):
            await monitor.emit(
                uid, kind, agent_id=sid, execution_id=turn["_id"], **metadata
            )

        async def sandbox_dispatch(arguments):
            from ..sandbox.policy import CodeRequest
            from ..sandbox.service import SandboxService

            code = CodeRequest.model_validate({**arguments, "agent_session_id": sid})
            return await SandboxService(
                db,
                s,
                request.app.state.sandbox_manager,
                monitor=request.app.state.monitor,
            ).request(uid, code)

        result = await request.app.state.agent_engine.run(
            locked["provider"],
            locked["model"],
            [*context, {"role": "user", "content": prompt}],
            locked["allowed_tools"],
            sandbox_dispatch=sandbox_dispatch,
            on_event=on_event,
        )
        await db.agent_messages.update_one(
            {"_id": turn["_id"], "session_id": sid, "user_id": uid},
            {
                "$set": {
                    "assistant_content": result["answer"],
                    "events": result["events"],
                    "status": result["status"],
                    "duration": round(time.monotonic() - started, 3),
                }
            },
        )
        turn.update(
            assistant_content=result["answer"],
            events=result["events"],
            status=result["status"],
        )
        await monitor.emit(
            uid,
            "agent_completed" if result["status"] == "completed" else "agent_failed",
            agent_id=sid,
            execution_id=turn["_id"],
            result=result["status"],
            duration=time.monotonic() - started,
        )
        finished = True
        return public(turn)
    except BaseException:
        if turn is not None and not finished:
            await db.agent_messages.update_one(
                {"_id": turn["_id"], "user_id": uid, "session_id": sid},
                {
                    "$set": {
                        "status": "interrupted",
                        "duration": round(time.monotonic() - started, 3),
                    }
                },
            )
            await request.app.state.monitor.emit(
                uid,
                "agent_failed",
                agent_id=sid,
                execution_id=turn["_id"],
                result="interrupted",
                duration=time.monotonic() - started,
            )
        raise
    finally:
        request.app.state.agent_active -= 1
        if locked:
            await db.agent_sessions.update_one(
                {"_id": sid, "user_id": uid},
                {
                    "$set": {"status": "idle", "updated_at": utcnow()},
                    "$unset": {"lease_until": ""},
                },
            )


@router.delete("/sessions/{sid}", status_code=204, dependencies=[Depends(require_csrf)])
async def delete(sid: SessionID, request: Request, identity=Depends(current_identity)):
    uid, db = owner(identity), request.app.state.db
    await get_owned(request, sid, uid)
    result = await db.agent_sessions.delete_one(
        {
            "_id": sid,
            "user_id": uid,
            "$or": [{"status": {"$ne": "running"}}, {"lease_until": {"$lt": utcnow()}}],
        }
    )
    if not result.deleted_count:
        raise HTTPException(409, "Cannot delete a running session")
    await db.agent_messages.delete_many({"session_id": sid, "user_id": uid})
    await db.agent_configs.update_one(
        {"_id": uid, "user_id": uid, "session_count": {"$gt": 0}},
        {"$inc": {"session_count": -1}},
    )
