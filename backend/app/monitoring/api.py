import asyncio
import json
import time
import uuid

import anyio
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.encoders import jsonable_encoder
from pymongo.errors import PyMongoError

from ..guards import allowed_origin
from ..security import current_identity, limit_attempts, utcnow
from .connections import ConnectionLeases

router = APIRouter(prefix="/api/monitor", tags=["Monitoring"])


async def grouped(collection, query, field):
    cursor = await collection.aggregate(
        [{"$match": query}, {"$group": {"_id": "$" + field, "count": {"$sum": 1}}}]
    )
    rows = await cursor.to_list(length=30)
    return {v["_id"]: v["count"] for v in rows}


@router.get("/summary")
async def summary(
    request: Request,
    frontend_origin: str | None = Query(None, max_length=200),
    identity=Depends(current_identity),
):
    uid = identity[0]["_id"]
    db = request.app.state.db
    await limit_attempts(request, "monitor_read", uid, 360)
    agents = await grouped(db.agent_messages, {"user_id": uid}, "status")
    sandbox = await grouped(db.execution_logs, {"user_id": uid}, "status")
    approvals = await grouped(
        db.execution_logs,
        {"user_id": uid, "approval_status": {"$exists": True}},
        "approval_status",
    )
    active = (
        await db.agent_sessions.find(
            {"user_id": uid, "status": "running", "lease_until": {"$gt": utcnow()}},
            {"_id": 1, "provider": 1, "model": 1, "updated_at": 1, "started_at": 1},
        )
        .limit(50)
        .to_list(length=50)
    )
    pending = await db.sandbox_approvals.count_documents(
        {"user_id": uid, "state": "pending", "expires_at": {"$gt": utcnow()}}
    )
    expired = await db.execution_logs.count_documents(
        {
            "user_id": uid,
            "approval_status": "pending",
            "approval_expires_at": {"$lte": utcnow()},
        }
    )
    blocked = await db.security_events.count_documents(
        {"user_id": uid, "kind": "monitor_event", "event.kind": "tool_rejected"}
    )
    return {
        "websocket_origin_allowed": frontend_origin
        in request.app.state.settings.origins
        if frontend_origin is not None
        else None,
        "agent_executions": {
            "total": sum(agents.values()),
            "successful": agents.get("completed", 0),
            "failed": agents.get("failed", 0) + agents.get("interrupted", 0),
            "by_status": agents,
        },
        "sandbox_executions": {"total": sum(sandbox.values()), "by_status": sandbox},
        "approvals": {**approvals, "pending": pending, "expired": expired},
        "blocked_tool_requests": blocked,
        "active_agents": [
            {
                "id": a["_id"],
                "provider": a["provider"],
                "model": a["model"],
                "updated_at": a["updated_at"],
                "started_at": a.get("started_at"),
            }
            for a in active
        ],
        "scope": "Current stored execution records; monitoring security events retained seven days",
    }


@router.get("/events")
async def events(
    request: Request,
    offset: int = Query(0, ge=0, le=10000),
    limit: int = Query(50, ge=1, le=100),
    identity=Depends(current_identity),
):
    uid = identity[0]["_id"]
    await limit_attempts(request, "monitor_read", uid, 360)
    rows = (
        await request.app.state.db.security_events.find(
            {"user_id": uid, "kind": "monitor_event"}
        )
        .sort("event.seq", -1)
        .skip(offset)
        .limit(limit)
        .to_list(length=limit)
    )
    stream = await request.app.state.db.monitor_streams.find_one(
        {"_id": uid, "user_id": uid}
    )
    cutoff = stream.get("signed_from") if stream else None
    return {
        "events": [
            request.app.state.monitor.public_event(v["event"], uid, cutoff)
            for v in rows
        ]
    }


@router.get("/approvals")
async def approvals(
    request: Request,
    offset: int = Query(0, ge=0, le=10000),
    limit: int = Query(20, ge=1, le=50),
    identity=Depends(current_identity),
):
    uid = identity[0]["_id"]
    db = request.app.state.db
    await limit_attempts(request, "monitor_read", uid, 360)
    pending = (
        await db.sandbox_approvals.find(
            {"user_id": uid, "state": "pending", "expires_at": {"$gt": utcnow()}},
            {"request": 0},
        )
        .sort("expires_at", 1)
        .skip(offset)
        .limit(limit)
        .to_list(length=limit)
    )
    history = (
        await db.execution_logs.find(
            {"user_id": uid, "approval_status": {"$in": ["approved", "rejected"]}},
            {"stdout": 0, "stderr": 0},
        )
        .sort("decision_at", -1)
        .skip(offset)
        .limit(limit)
        .to_list(length=limit)
    )
    return {
        "pending": [
            {
                "id": v["_id"],
                "request_hash": v["request_hash"],
                "expires_at": v["expires_at"],
            }
            for v in pending
        ],
        "history": [
            {
                "id": v["_id"],
                "agent_id": v.get("agent_session_id"),
                "decision": v["approval_status"],
                "timestamp": v["decision_at"],
                "status": v["status"],
            }
            for v in history
        ],
    }


@router.websocket("/ws")
async def websocket(ws: WebSocket):
    s = ws.app.state.settings
    monitor = ws.app.state.monitor
    if not allowed_origin(ws):
        await ws.close(code=4403)
        return
    try:
        identity = await current_identity(ws)
        uid = identity[0]["_id"]
        raw = ws.query_params.get("after", "0")
        if (
            set(ws.query_params) - {"after"}
            or (
                hasattr(ws.query_params, "getlist")
                and len(ws.query_params.getlist("after")) > 1
            )
            or not raw.isascii()
            or not raw.isdigit()
            or len(raw) > 16
            or int(raw) > 9007199254740991
        ):
            raise ValueError()
        after = int(raw)
        await limit_attempts(ws, "monitor_connect", uid, 60)
    except HTTPException as exc:
        await ws.close(code=1013 if exc.status_code == 429 else 4401)
        return
    except ValueError:
        await ws.close(code=1008)
        return
    except PyMongoError:
        await ws.close(code=1013)
        return
    if sum(monitor.connections.values()) >= 20 or monitor.connections.get(uid, 0) >= 4:
        await ws.close(code=1013)
        return
    leases = ConnectionLeases(ws.app.state.db)
    cid = uuid.uuid4().hex
    try:
        if not await leases.acquire(uid, cid):
            await ws.close(code=1013)
            return
    except PyMongoError:
        await ws.close(code=1013)
        return
    monitor.connections[uid] = monitor.connections.get(uid, 0) + 1
    last_pong = [time.monotonic()]

    async def send(data):
        await asyncio.wait_for(
            ws.send_json(jsonable_encoder(data)), timeout=s.monitor_send_timeout
        )

    async def receive():
        previous = 0.0
        while True:
            try:
                text = await ws.receive_text()
            except KeyError:
                await ws.close(code=1008)
                return
            try:
                valid = len(text) <= 256 and json.loads(text) == {"type": "pong"}
            except (ValueError, TypeError):
                valid = False
            now = time.monotonic()
            if not valid or now - previous < 1:
                await ws.close(code=1008)
                return
            previous = now
            last_pong[0] = now

    async def transmit():
        nonlocal after
        heartbeat = 0.0
        await send({"type": "connected", "protocol": 1})
        while True:
            try:
                await current_identity(ws)
                if not await leases.renew(uid, cid):
                    await ws.close(code=1013)
                    return
            except HTTPException:
                await ws.close(code=4401)
                return
            if time.monotonic() - last_pong[0] > s.monitor_pong_seconds:
                await ws.close(code=1008)
                return
            batch, gap = await monitor.replay(uid, after)
            if gap:
                await send({"type": "resync_required"})
                # Send retained window, but client must refresh REST snapshots.
                batch, _ = await monitor.replay(uid, 0)
                after = 0
            for event in batch:
                # Revocation or lease loss must stop a slow replay mid-batch.
                try:
                    await current_identity(ws)
                except HTTPException:
                    await ws.close(code=4401)
                    return
                if not await leases.renew(uid, cid):
                    await ws.close(code=1013)
                    return
                await send({"type": "event", "event": event})
                after = event["seq"]
            if time.monotonic() - heartbeat >= s.monitor_heartbeat_seconds:
                await send({"type": "heartbeat", "cursor": after})
                heartbeat = time.monotonic()
            await asyncio.sleep(s.monitor_poll_seconds)

    tasks = []
    try:
        await ws.accept()
        tasks = [asyncio.create_task(receive()), asyncio.create_task(transmit())]
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        for task in tasks:
            task.cancel()
        monitor.connections[uid] -= 1
        if not monitor.connections[uid]:
            del monitor.connections[uid]
        # ASGI shutdown may cancel the handler while it is draining child tasks.
        # Keep cleanup bounded and shielded so no sender outlives its connection.
        with anyio.move_on_after(s.monitor_send_timeout, shield=True):
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            try:
                await leases.release(uid, cid)
            except PyMongoError:
                pass  # Lease expires, never increase capacity on an uncertain write.
            try:
                await ws.close(code=1013)
            except (RuntimeError, WebSocketDisconnect):
                pass
