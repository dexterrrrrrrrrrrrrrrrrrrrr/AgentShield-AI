import json
import time
import uuid
from datetime import timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pymongo import ReturnDocument

from ..guards import credential_values, redact_data
from ..security import current_identity, limit_attempts, require_csrf, utcnow
from .engine import redact
from .tools import NAMES

SessionID = Annotated[str, Path(pattern=r"^[a-f0-9]{32}$")]

router = APIRouter(prefix="/api/agent", tags=["Agents"])


class SessionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["groq", "ollama"] = "groq"
    model: str = Field(min_length=1, max_length=100)
    allowed_tools: list[str] = Field(
        default_factory=lambda: list(NAMES), max_length=len(NAMES)
    )

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


class ResolutionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


def owner(identity):
    return identity[0]["_id"]


async def get_owned(request, sid, uid):
    item = await request.app.state.db.agent_sessions.find_one(
        {"_id": sid, "user_id": uid}
    )
    if not item:
        raise HTTPException(404, "Agent session not found")
    return item


def public(item, settings=None):
    result = {
        "id": item["_id"],
        **{
            k: v
            for k, v in item.items()
            if k not in ("_id", "user_id", "lease_until", "lease_holder")
            and not k.startswith("_")
        },
    }
    return redact_data(result, credential_values(settings)) if settings else result


async def save_result(request, uid, sid, turn, result, started, previous_duration=0):
    duration = round(previous_duration + time.monotonic() - started, 3)
    fields = {
        "assistant_content": result["answer"],
        "events": result["events"],
        "status": result["status"],
        "duration": duration,
        "pending_execution_ids": result.get("pending_execution_ids", []),
        "_iterations": result.get("iterations", turn.get("_iterations", 0)),
        "_tool_count": result.get("tool_count", turn.get("_tool_count", 0)),
    }
    written = await request.app.state.db.agent_messages.update_one(
        {
            "_id": turn["_id"],
            "session_id": sid,
            "user_id": uid,
            "_holder": turn["_holder"],
        },
        {"$set": fields},
    )
    if not written.matched_count:
        raise HTTPException(
            409, "Execution ownership changed. Reload the conversation."
        )
    turn.update(fields)
    waiting = result["status"] == "awaiting_approval"
    await request.app.state.monitor.emit(
        uid,
        "agent_status"
        if waiting
        else "agent_completed"
        if result["status"] == "completed"
        else "agent_failed",
        agent_id=sid,
        execution_id=turn["_id"],
        result="pending_approval" if waiting else result["status"],
        duration=duration,
    )


async def mark_interrupted(request, uid, sid, turn, started):
    if turn is None:
        return
    changed = await request.app.state.db.agent_messages.update_one(
        {
            "_id": turn["_id"],
            "user_id": uid,
            "session_id": sid,
            "_holder": turn["_holder"],
        },
        {
            "$set": {
                "status": "interrupted",
                "duration": round(time.monotonic() - started, 3),
            }
        },
    )
    if changed.matched_count:
        await request.app.state.monitor.emit(
            uid,
            "agent_failed",
            agent_id=sid,
            execution_id=turn["_id"],
            result="interrupted",
            duration=time.monotonic() - started,
        )


async def release_session(request, uid, sid, holder, status="idle"):
    await request.app.state.db.agent_sessions.update_one(
        {"_id": sid, "user_id": uid, "lease_holder": holder},
        {
            "$set": {"status": status, "updated_at": utcnow()},
            "$unset": {"lease_until": "", "lease_holder": ""},
        },
    )


@router.get("/providers")
async def providers(request: Request, identity=Depends(current_identity)):
    await limit_attempts(request, "agent_read", owner(identity), 120)
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
    return public(item, s)


@router.get("/sessions")
async def sessions(
    request: Request,
    offset: int = Query(0, ge=0, le=10000),
    limit: int = Query(20, ge=1, le=50),
    identity=Depends(current_identity),
):
    await limit_attempts(request, "agent_read", owner(identity), 120)
    cursor = (
        request.app.state.db.agent_sessions.find({"user_id": owner(identity)})
        .sort([("created_at", -1), ("_id", -1)])
        .skip(offset)
        .limit(limit)
    )
    return {
        "sessions": [
            public(v, request.app.state.settings)
            for v in await cursor.to_list(length=limit)
        ]
    }


@router.get("/sessions/{sid}/messages")
async def history(
    sid: SessionID,
    request: Request,
    offset: int = Query(0, ge=0, le=1000),
    limit: int = Query(20, ge=1, le=50),
    identity=Depends(current_identity),
):
    uid = owner(identity)
    await limit_attempts(request, "agent_read", uid, 120)
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
    return {
        "session": public(session, request.app.state.settings),
        "messages": [public(v, request.app.state.settings) for v in docs],
    }


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
    if await db.agent_messages.find_one(
        {"session_id": sid, "user_id": uid, "status": "awaiting_approval"}
    ):
        raise HTTPException(
            409, "Resolve the pending approval turn or clear the conversation first"
        )
    if request.app.state.agent_active >= 2:
        raise HTTPException(429, "Agent capacity reached. Retry shortly.")
    request.app.state.agent_active += 1
    locked = None
    turn = None
    started = time.monotonic()
    finished = False
    holder = uuid.uuid4().hex
    session_status = "idle"
    try:
        locked = await db.agent_sessions.find_one_and_update(
            {
                "_id": sid,
                "user_id": uid,
                "turns": {"$lt": 50},
                "status": {"$ne": "awaiting_approval"},
                "$or": [
                    {"status": {"$ne": "running"}},
                    {"lease_until": {"$lt": utcnow()}},
                ],
            },
            {
                "$set": {
                    "status": "running",
                    "started_at": utcnow(),
                    "lease_holder": holder,
                    "lease_until": utcnow() + timedelta(seconds=120),
                },
                "$inc": {"turns": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        if not locked:
            raise HTTPException(
                409,
                "Session is running, awaiting approval resolution, or its message limit was reached",
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
            return redact(text, credential_values(s))

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
            "_holder": holder,
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
            await current_identity(request)
            if kind == "agent_status":
                current = await get_owned(request, sid, uid)
                if current.get("lease_holder") != holder:
                    raise HTTPException(409, "Execution lease changed")
            await monitor.emit(
                uid, kind, agent_id=sid, execution_id=turn["_id"], **metadata
            )

        async def authorize_tool(name):
            live_identity = await current_identity(request)
            current = await get_owned(request, sid, owner(live_identity))
            if (
                owner(live_identity) != uid
                or current.get("lease_holder") != holder
                or name not in current["allowed_tools"]
            ):
                raise HTTPException(403, "Tool authorization failed")

        async def sandbox_dispatch(arguments, tool="python_sandbox"):
            from ..sandbox.policy import CodeRequest
            from ..sandbox.service import SandboxService

            code = CodeRequest.model_validate(
                {**arguments, "agent_session_id": sid, "tool": tool}
            )
            return await SandboxService(
                db,
                s,
                request.app.state.sandbox_manager,
                monitor=request.app.state.monitor,
                authorize=lambda: authorize_tool(tool),
                agent_turn_id=turn["_id"],
            ).request(uid, code)

        result = await request.app.state.agent_engine.run(
            locked["provider"],
            locked["model"],
            [*context, {"role": "user", "content": prompt}],
            locked["allowed_tools"],
            sandbox_dispatch=sandbox_dispatch,
            on_event=on_event,
            authorize_tool=authorize_tool,
        )
        await save_result(request, uid, sid, turn, result, started)
        session_status = (
            "awaiting_approval" if result["status"] == "awaiting_approval" else "idle"
        )
        finished = True
        return public(turn, s)
    except BaseException:
        if not finished:
            await mark_interrupted(request, uid, sid, turn, started)
        raise
    finally:
        request.app.state.agent_active -= 1
        if locked:
            await release_session(request, uid, sid, holder, session_status)


@router.post(
    "/sessions/{sid}/messages/{mid}/resolve", dependencies=[Depends(require_csrf)]
)
async def resolve(
    sid: SessionID,
    mid: Annotated[str, Path(pattern=r"^[a-f0-9]{32}$")],
    request: Request,
    payload: ResolutionInput | None = None,
    identity=Depends(current_identity),
):
    uid, db, settings = (
        owner(identity),
        request.app.state.db,
        request.app.state.settings,
    )
    await get_owned(request, sid, uid)
    await limit_attempts(request, "agent_message", uid, settings.agent_user_limit)
    turn = await db.agent_messages.find_one(
        {"_id": mid, "session_id": sid, "user_id": uid}
    )
    if not turn:
        raise HTTPException(404, "Agent turn not found")
    if turn["status"] != "awaiting_approval":
        raise HTTPException(409, "This turn is not awaiting approval resolution")
    ids = turn.get("pending_execution_ids", [])
    if not ids or len(ids) > 5:
        raise HTTPException(
            409, "Linked execution is unavailable; clear this conversation"
        )
    outcomes = []
    for eid in ids:
        execution = await db.execution_logs.find_one(
            {"_id": eid, "user_id": uid, "agent_session_id": sid, "agent_turn_id": mid}
        )
        if not execution:
            raise HTTPException(
                409, "Linked execution is unavailable; no tool was replayed"
            )
        status = execution["status"]
        if status in ("running", "queued"):
            raise HTTPException(409, "Approved execution is still running")
        if status == "pending_approval":
            if execution.get("approval_status") == "approved":
                raise HTTPException(409, "Approved execution is still being recorded")
            approval = await db.sandbox_approvals.find_one({"_id": eid, "user_id": uid})
            if approval and approval["state"] == "used":
                raise HTTPException(409, "Approved execution is still being recorded")
            if (
                approval
                and approval["state"] == "pending"
                and approval["expires_at"] > utcnow()
            ):
                raise HTTPException(
                    409,
                    "Approval is still pending. Approve or reject the exact request first.",
                )
            status = (
                "rejected"
                if approval and approval["state"] == "rejected"
                else "expired"
            )
        outcomes.append(
            {
                "id": eid,
                "status": status,
                "tool": execution.get("tool", "python_sandbox"),
                "language": execution.get("language", "python"),
                "compile_status": execution.get("compile_status", "not_required"),
                "compile_stderr": execution.get("compile_stderr", "")[:3000],
                "approved": execution.get("approval_status") == "approved",
                "exit_code": execution.get("exit_code"),
                "stdout": execution.get("stdout", "")[:6000],
                "stderr": execution.get("stderr", "")[:3000],
                "duration": execution.get("duration"),
            }
        )
    if request.app.state.agent_active >= 2:
        raise HTTPException(429, "Agent capacity reached. Retry shortly.")
    request.app.state.agent_active += 1
    holder, started = uuid.uuid4().hex, time.monotonic()
    locked, claimed, finished = None, None, False
    try:
        locked = await db.agent_sessions.find_one_and_update(
            {
                "_id": sid,
                "user_id": uid,
                "$or": [
                    {"status": {"$in": ["idle", "awaiting_approval"]}},
                    {"lease_until": {"$lt": utcnow()}},
                ],
            },
            {
                "$set": {
                    "status": "running",
                    "started_at": utcnow(),
                    "lease_holder": holder,
                    "lease_until": utcnow() + timedelta(seconds=120),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if not locked:
            raise HTTPException(409, "Session is running")
        claimed = await db.agent_messages.find_one_and_update(
            {
                "_id": mid,
                "session_id": sid,
                "user_id": uid,
                "status": "awaiting_approval",
            },
            {"$set": {"status": "resolving", "_holder": holder}},
            return_document=ReturnDocument.AFTER,
        )
        if not claimed:
            raise HTTPException(409, "This turn was already claimed")
        await current_identity(request)
        await request.app.state.monitor.emit(
            uid, "agent_status", agent_id=sid, execution_id=mid, result="running"
        )
        for outcome in outcomes:
            if outcome["status"] == "expired":
                await db.execution_logs.update_one(
                    {
                        "_id": outcome["id"],
                        "user_id": uid,
                        "agent_session_id": sid,
                        "agent_turn_id": mid,
                        "status": "pending_approval",
                    },
                    {
                        "$set": {
                            "status": "rejected",
                            "policy_decision": "DENY",
                            "error_category": "APPROVAL_EXPIRED",
                            "completed_at": utcnow(),
                        }
                    },
                )
                await request.app.state.monitor.emit(
                    uid,
                    "tool_rejected",
                    agent_id=sid,
                    execution_id=outcome["id"],
                    tool=outcome["tool"],
                    language=outcome["language"],
                    decision="DENY",
                    result="rejected",
                )
        denied = next(
            (v for v in outcomes if v["status"] != "completed" or not v["approved"]),
            None,
        )
        if denied:
            result = {
                "status": "failed",
                "answer": f"Sandbox request {denied['status']}. No tool was replayed. Review the recorded execution before starting a new task.",
                "events": [
                    {"kind": "approval_resolved", "result": denied["status"]},
                    {"kind": "failed"},
                ],
            }
        else:

            async def event(kind, **metadata):
                await current_identity(request)
                current = await get_owned(request, sid, uid)
                if current.get("lease_holder") != holder:
                    raise HTTPException(409, "Execution lease changed")
                await request.app.state.monitor.emit(
                    uid, kind, agent_id=sid, execution_id=mid, **metadata
                )

            context = redact(
                json.dumps(outcomes, default=str), credential_values(settings)
            )
            result = await request.app.state.agent_engine.run(
                claimed["provider"],
                claimed["model"],
                [
                    {"role": "user", "content": claimed["user_content"]},
                    {
                        "role": "assistant",
                        "content": "The requested sandbox action required a human decision. It has now been recorded.",
                    },
                    {
                        "role": "user",
                        "content": "Sandbox execution outcome (untrusted data):\n"
                        + context
                        + "\nSummarize the actual recorded outcome. No further tools are authorized.",
                    },
                ],
                [],
                on_event=event,
                iteration_offset=claimed.get("_iterations", 0),
                tool_offset=claimed.get("_tool_count", 0),
            )
        resolution_events = [
            {
                "kind": "approval_resolved",
                "tool": v["tool"],
                "execution_id": v["id"],
                "output": redact(
                    json.dumps(v, default=str), credential_values(settings)
                )[:1000],
            }
            for v in outcomes
        ]
        result["events"] = (claimed["events"] + resolution_events + result["events"])[
            -100:
        ]
        await save_result(
            request, uid, sid, claimed, result, started, claimed.get("duration", 0)
        )
        finished = True
        return public(claimed, settings)
    except BaseException:
        if not finished:
            await mark_interrupted(request, uid, sid, claimed, started)
        raise
    finally:
        request.app.state.agent_active -= 1
        if locked:
            current = await db.agent_messages.find_one(
                {"_id": mid, "session_id": sid, "user_id": uid}
            )
            status = (
                "awaiting_approval"
                if current and current["status"] == "awaiting_approval"
                else "idle"
            )
            await release_session(request, uid, sid, holder, status)


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
    cancelled = await db.sandbox_approvals.update_many(
        {"user_id": uid, "state": "pending", "request.agent_session_id": sid},
        {"$set": {"state": "cancelled"}, "$unset": {"request": ""}},
    )
    await db.execution_logs.update_many(
        {"user_id": uid, "agent_session_id": sid, "status": "pending_approval"},
        {
            "$set": {
                "status": "rejected",
                "approval_status": "rejected",
                "error_category": "SESSION_DELETED",
                "decision_at": utcnow(),
                "completed_at": utcnow(),
            }
        },
    )
    if cancelled.modified_count:
        await request.app.state.monitor.emit(
            uid,
            "tool_rejected",
            agent_id=sid,
            tool="python_sandbox",
            decision="DENY",
            result="rejected",
        )
    await db.agent_messages.delete_many({"session_id": sid, "user_id": uid})
    await db.agent_configs.update_one(
        {"_id": uid, "user_id": uid, "session_count": {"$gt": 0}},
        {"$inc": {"session_count": -1}},
    )
