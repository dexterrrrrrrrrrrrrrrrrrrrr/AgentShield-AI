import asyncio
import uuid
from datetime import timedelta

from fastapi import HTTPException
from pymongo import ReturnDocument

from ..guards import CREDENTIAL, credential_values
from ..guards import redact as redact_credentials
from ..security import utcnow
from .manager import Unavailable
from .policy import CodeRequest, Decision, evaluate, fingerprint, limits


class SandboxService:
    def __init__(self, db, settings, manager, monitor=None, authorize=None):
        self.db = db
        self.s = settings
        self.manager = manager
        if monitor is None:
            from ..monitoring.events import Monitor

            monitor = Monitor(db, settings)
        self.monitor = monitor
        self.authorize = authorize

    def validate_code(self, code):
        if any(v in code for v in credential_values(self.s)) or CREDENTIAL.search(code):
            raise HTTPException(422, "Remove credentials from submitted code")

    def approval_payload(self, pending):
        try:
            payload = CodeRequest.model_validate(pending["request"])
        except (ValueError, TypeError, KeyError):
            raise HTTPException(
                409, "Approval is invalid; submit a new request"
            ) from None
        self.validate_code(payload.code)
        return payload

    async def owned(self, uid, payload):
        return not payload.agent_session_id or bool(
            await self.db.agent_sessions.find_one(
                {"_id": payload.agent_session_id, "user_id": uid}
            )
        )

    async def quota(self, uid):
        now = utcnow()
        bucket = int(now.timestamp()) // 300
        event = await self.db.security_events.find_one_and_update(
            {"_id": f"sandbox:{uid}:{bucket}"},
            {
                "$inc": {"attempts": 1},
                "$setOnInsert": {"expires_at": now + timedelta(seconds=600)},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        if event["attempts"] > self.s.sandbox_user_limit:
            raise HTTPException(429, "Sandbox quota exceeded")

    async def request(self, uid, payload):
        await self.quota(uid)
        if not await self.owned(uid, payload):
            raise HTTPException(404, "Agent session not found")
        s = self.s
        # Known credentials must not enter stored approval requests or Docker Cmd.
        self.validate_code(payload.code)
        blocked = await self.db.sandbox_locks.find_one(
            {"_id": "execution", "blocked": True}
        )
        available = (
            {"ready": False, "code": "SANDBOX_UNAVAILABLE"}
            if blocked
            else await self.manager.readiness()
        )
        decision = evaluate(
            authenticated=bool(uid),
            owned=True,
            tool=payload.tool,
            size=len(payload.code.encode()),
            quota=True,
            available=available["ready"],
            enabled=s.sandbox_enabled,
            mode=s.sandbox_policy,
            max_size=s.sandbox_code_bytes,
        )
        eid = uuid.uuid4().hex
        now = utcnow()
        digest = fingerprint(payload, s)
        item = {
            "_id": eid,
            "user_id": uid,
            "agent_session_id": payload.agent_session_id,
            "tool": payload.tool,
            "policy_decision": str(decision),
            "request_hash": digest,
            "status": "pending_approval"
            if decision == Decision.REQUIRE_APPROVAL
            else "denied"
            if decision == Decision.DENY
            else "queued",
            "created_at": now,
            "completed_at": None,
            "duration": None,
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "limits": limits(s),
            "error_category": None,
            "expires_at": now + timedelta(days=s.sandbox_retention_days),
        }
        if not available["ready"]:
            item.update(status="unavailable", error_category="SANDBOX_UNAVAILABLE")
        await self.db.execution_logs.insert_one(item)
        await self.monitor.emit(
            uid,
            "policy_evaluation",
            agent_id=payload.agent_session_id,
            execution_id=eid,
            tool=payload.tool,
            decision=str(decision),
            result=item["status"],
        )
        if decision == Decision.DENY:
            await self.monitor.emit(
                uid,
                "tool_rejected",
                agent_id=payload.agent_session_id,
                execution_id=eid,
                tool=payload.tool,
                decision="DENY",
                result=item["status"],
            )
        if decision == Decision.REQUIRE_APPROVAL:
            await self.db.sandbox_approvals.insert_one(
                {
                    "_id": eid,
                    "user_id": uid,
                    "request": payload.model_dump(),
                    "request_hash": digest,
                    "state": "pending",
                    "expires_at": now + timedelta(seconds=s.sandbox_approval_seconds),
                }
            )
            await self.db.execution_logs.update_one(
                {"_id": eid, "user_id": uid},
                {
                    "$set": {
                        "approval_status": "pending",
                        "approval_expires_at": now
                        + timedelta(seconds=s.sandbox_approval_seconds),
                    }
                },
            )
            await self.monitor.emit(
                uid,
                "approval_required",
                agent_id=payload.agent_session_id,
                execution_id=eid,
                tool=payload.tool,
                decision="REQUIRE_APPROVAL",
                result="pending_approval",
            )
        elif decision == Decision.ALLOW:
            item = await self.run(uid, eid, payload)
        return self.public(item, self.s)

    async def approve(self, uid, eid, digest):
        await self.quota(uid)
        pending = await self.db.sandbox_approvals.find_one(
            {
                "_id": eid,
                "user_id": uid,
                "state": "pending",
                "expires_at": {"$gt": utcnow()},
            }
        )
        if not pending:
            raise HTTPException(409, "Approval is missing, used, or expired")
        payload = self.approval_payload(pending)
        if digest != pending["request_hash"] or fingerprint(payload, self.s) != digest:
            raise HTTPException(
                409, "The request or policy changed; submit a new request"
            )
        if not await self.owned(uid, payload):
            raise HTTPException(404, "Agent session not found")
        if (
            self.s.sandbox_policy == "deny"
            or not (await self.manager.readiness())["ready"]
        ):
            raise HTTPException(503, "SANDBOX_UNAVAILABLE")
        used = await self.db.sandbox_approvals.find_one_and_update(
            {
                "_id": eid,
                "user_id": uid,
                "request_hash": digest,
                "state": "pending",
                "expires_at": {"$gt": utcnow()},
            },
            {"$set": {"state": "used"}, "$unset": {"request": ""}},
            return_document=ReturnDocument.BEFORE,
        )
        if not used:
            raise HTTPException(409, "Approval was already used")
        # Validate the exact document atomically consumed, not an earlier read.
        payload = self.approval_payload(used)
        if fingerprint(payload, self.s) != digest or not await self.owned(uid, payload):
            raise HTTPException(
                409, "The request or policy changed; submit a new request"
            )
        await self.db.execution_logs.update_one(
            {"_id": eid, "user_id": uid},
            {"$set": {"approval_status": "approved", "decision_at": utcnow()}},
        )
        await self.monitor.emit(
            uid,
            "tool_approved",
            agent_id=payload.agent_session_id,
            execution_id=eid,
            tool=payload.tool,
            decision="ALLOW",
            result="queued",
        )
        return self.public(await self.run(uid, eid, payload), self.s)

    async def run(self, uid, eid, payload):
        authorization_failure = None
        # Distributed admission: one live sandbox across backend workers.
        await self.db.sandbox_locks.update_one(
            {"_id": "execution"}, {"$setOnInsert": {"until": utcnow()}}, upsert=True
        )
        lease = await self.db.sandbox_locks.find_one_and_update(
            {"_id": "execution", "until": {"$lte": utcnow()}, "blocked": {"$ne": True}},
            {"$set": {"holder": eid, "until": utcnow() + timedelta(seconds=120)}},
            return_document=ReturnDocument.AFTER,
        )
        if not lease:
            result = {"status": "rejected", "error_category": "SANDBOX_BUSY"}
        else:
            try:
                await self.db.execution_logs.update_one(
                    {"_id": eid, "user_id": uid},
                    {"$set": {"status": "running", "started_at": utcnow()}},
                )
                await self.monitor.emit(
                    uid,
                    "sandbox_started",
                    agent_id=payload.agent_session_id,
                    execution_id=eid,
                    tool=payload.tool,
                    decision="ALLOW",
                    result="running",
                )
                if self.authorize is not None:
                    await self.authorize()
                self.validate_code(payload.code)
                if (
                    not await self.owned(uid, payload)
                    or not self.s.sandbox_enabled
                    or self.s.sandbox_policy == "deny"
                ):
                    raise HTTPException(403, "Sandbox authorization failed")
                result = await self.manager.execute(payload.code)
            except HTTPException as exc:
                authorization_failure = exc
                result = {
                    "status": "rejected",
                    "error_category": "AUTHORIZATION_FAILED",
                }
            except asyncio.CancelledError:
                await self.db.execution_logs.update_one(
                    {"_id": eid, "user_id": uid},
                    {
                        "$set": {
                            "status": "interrupted",
                            "completed_at": utcnow(),
                            "error_category": "CANCELLED",
                        }
                    },
                )
                await self.monitor.emit(
                    uid,
                    "sandbox_failed",
                    agent_id=payload.agent_session_id,
                    execution_id=eid,
                    tool=payload.tool,
                    decision="ALLOW",
                    result="interrupted",
                )
                raise
            except Unavailable:
                await self.db.sandbox_locks.update_one(
                    {"_id": "execution", "holder": eid}, {"$set": {"blocked": True}}
                )
                result = {
                    "status": "unavailable",
                    "error_category": "SANDBOX_UNAVAILABLE",
                }
            finally:
                if self.manager.failed:
                    await self.db.sandbox_locks.update_one(
                        {"_id": "execution", "holder": eid}, {"$set": {"blocked": True}}
                    )
                await self.db.sandbox_locks.update_one(
                    {"_id": "execution", "holder": eid},
                    {"$set": {"until": utcnow()}, "$unset": {"holder": ""}},
                )
        for key in ("stdout", "stderr"):
            if key in result:
                result[key] = redact_credentials(result[key], credential_values(self.s))
        result["completed_at"] = utcnow()
        item = await self.db.execution_logs.find_one_and_update(
            {"_id": eid, "user_id": uid},
            {"$set": result},
            return_document=ReturnDocument.AFTER,
        )
        await self.monitor.emit(
            uid,
            "sandbox_completed" if item["status"] == "completed" else "sandbox_failed",
            agent_id=payload.agent_session_id,
            execution_id=eid,
            tool=payload.tool,
            decision="ALLOW",
            result=item["status"],
            duration=item.get("duration"),
        )
        if authorization_failure is not None:
            raise authorization_failure
        return item

    async def reject(self, uid, eid, digest):
        await self.quota(uid)
        claimed = await self.db.sandbox_approvals.find_one_and_update(
            {
                "_id": eid,
                "user_id": uid,
                "request_hash": digest,
                "state": "pending",
                "expires_at": {"$gt": utcnow()},
            },
            {"$set": {"state": "rejected"}, "$unset": {"request": ""}},
            return_document=ReturnDocument.BEFORE,
        )
        if not claimed:
            raise HTTPException(409, "Approval is missing, used, or expired")
        item = await self.db.execution_logs.find_one_and_update(
            {"_id": eid, "user_id": uid},
            {
                "$set": {
                    "approval_status": "rejected",
                    "status": "rejected",
                    "policy_decision": "DENY",
                    "decision_at": utcnow(),
                    "completed_at": utcnow(),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        await self.monitor.emit(
            uid,
            "tool_rejected",
            agent_id=item.get("agent_session_id"),
            execution_id=eid,
            tool="python_sandbox",
            decision="DENY",
            result="rejected",
        )
        return self.public(item, self.s)

    @staticmethod
    def public(item, settings=None):
        result = {
            "id": item["_id"],
            **{
                k: v
                for k, v in item.items()
                if k not in ("_id", "user_id", "expires_at")
            },
        }
        if settings:
            for key in ("stdout", "stderr"):
                if key in result:
                    result[key] = redact_credentials(
                        result[key], credential_values(settings)
                    )
        return result
