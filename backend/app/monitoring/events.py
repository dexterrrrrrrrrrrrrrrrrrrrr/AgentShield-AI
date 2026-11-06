import asyncio
import hashlib
import hmac
import json
import math
import uuid
from datetime import timedelta

from pymongo.errors import DuplicateKeyError

from ..security import utcnow

KINDS = {
    "agent_started",
    "agent_status",
    "tool_requested",
    "tool_completed",
    "policy_evaluation",
    "approval_required",
    "tool_approved",
    "tool_rejected",
    "sandbox_started",
    "sandbox_completed",
    "sandbox_failed",
    "agent_completed",
    "agent_failed",
}
TOOLS = {
    "calculator",
    "summarize_text",
    "format_json",
    "python_sandbox",
    "execute_code",
}
DECISIONS = {"ALLOW", "DENY", "REQUIRE_APPROVAL"}
RESULTS = {
    "running",
    "completed",
    "failed",
    "rejected",
    "denied",
    "pending_approval",
    "unavailable",
    "interrupted",
    "timed_out",
    "output_limit",
    "queued",
}


class AuditIntegrityError(RuntimeError):
    pass


class Monitor:
    def __init__(self, db, settings):
        self.db = db
        key = (
            settings.audit_signing_key.get_secret_value()
            or settings.jwt_secret.get_secret_value()
        )
        self.key = hmac.digest(key.encode(), b"AgentShield/audit/v1", "sha256")
        self.connections = {}  # Admission only; event delivery uses MongoDB.

    async def emit(
        self,
        uid,
        kind,
        *,
        agent_id=None,
        execution_id=None,
        tool=None,
        decision=None,
        result=None,
        duration=None,
        language=None,
        compile_status=None,
    ):
        if kind not in KINDS:
            raise ValueError("Unknown monitoring event")
        # Only identifiers and fixed vocabulary. Never accept arbitrary payloads.
        for value in (uid, agent_id, execution_id):
            if value is not None and (
                not isinstance(value, str)
                or len(value) != 32
                or any(c not in "0123456789abcdef" for c in value)
            ):
                raise ValueError("Invalid event identifier")
        now = utcnow()
        # BSON dates have millisecond precision; sign exactly what MongoDB stores.
        now = now.replace(microsecond=now.microsecond // 1000 * 1000)
        if duration is not None and not math.isfinite(float(duration)):
            raise ValueError("Invalid duration")
        event = {
            "id": uuid.uuid4().hex,
            "user_id": uid,
            "agent_id": agent_id,
            "execution_id": execution_id,
            "timestamp": now,
            "kind": kind,
            "category": "security"
            if kind
            in {
                "policy_evaluation",
                "approval_required",
                "tool_approved",
                "tool_rejected",
                "sandbox_failed",
            }
            else "execution",
            "severity": "warning"
            if kind in {"tool_rejected", "sandbox_failed", "agent_failed"}
            else "info",
            "action": kind,
            "tool": tool if tool in TOOLS else "unknown" if tool else None,
            "policy_decision": decision if decision in DECISIONS else None,
            "execution_result": result if result in RESULTS else None,
            "duration": round(max(0, min(float(duration), 3600)), 3)
            if duration is not None
            else None,
        }
        if language is not None:
            from ..sandbox.registry import LANGUAGES

            if language not in LANGUAGES:
                raise ValueError("Invalid event language")
            event["language"] = language
        if compile_status is not None:
            if compile_status not in {
                "not_required",
                "pending",
                "completed",
                "failed",
                "timed_out",
                "output_limit",
            }:
                raise ValueError("Invalid compilation status")
            event["compile_status"] = compile_status
        # CAS binds the signed sequence to the atomic bounded append. No transaction
        # or replica-set requirement; concurrent writers retry without skipping IDs.
        for _ in range(32):
            stream = await self.db.monitor_streams.find_one(
                {"_id": uid, "user_id": uid}
            )
            if stream is None:
                try:
                    await self.db.monitor_streams.insert_one(
                        {
                            "_id": uid,
                            "user_id": uid,
                            "seq": 0,
                            "events": [],
                            "signed_from": 1,
                        }
                    )
                except DuplicateKeyError:
                    pass
                continue
            seq = stream["seq"]
            if stream["events"]:
                if stream["events"][-1]["seq"] != seq:
                    raise AuditIntegrityError()
                for prior in stream["events"]:
                    self.public_event(prior, uid, stream.get("signed_from"))
            event["seq"] = seq + 1
            event["signature"] = self.seal(event)
            claimed = await self.db.monitor_streams.update_one(
                {"_id": uid, "user_id": uid, "seq": seq},
                {
                    "$set": {
                        "seq": seq + 1,
                        "updated_at": now,
                        "signed_from": stream.get("signed_from", seq + 1),
                    },
                    "$push": {"events": {"$each": [event], "$slice": -200}},
                },
            )
            if claimed.modified_count:
                break
            await asyncio.sleep(0)
        else:
            raise AuditIntegrityError()
        published = dict(event)
        await self.db.security_events.insert_one(
            {
                "_id": event["id"],
                "kind": "monitor_event",
                "user_id": uid,
                "event": published,
                "expires_at": now + timedelta(days=7),
            }
        )
        return self.public_event(published, uid, event["seq"])

    def seal(self, event):
        value = {k: v for k, v in event.items() if k != "signature"}
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=lambda v: v.isoformat(timespec="milliseconds"),
        ).encode()
        return hmac.new(self.key, encoded, hashlib.sha256).hexdigest()

    def public_event(self, event, uid, signed_from=None):
        try:
            return self._public_event(event, uid, signed_from)
        except (TypeError, ValueError, AttributeError, KeyError):
            raise AuditIntegrityError() from None

    def _public_event(self, event, uid, signed_from):
        # Legacy Phase 5 metadata is readable but explicitly cannot be authenticated.
        if event.get("user_id") != uid or event.get("kind") not in KINDS:
            raise AuditIntegrityError()
        signed = event.get("signature")
        if signed or (signed_from is not None and event.get("seq", 0) >= signed_from):
            if not isinstance(signed, str) or not hmac.compare_digest(
                signed, self.seal(event)
            ):
                raise AuditIntegrityError()
        allowed = {
            "id",
            "user_id",
            "agent_id",
            "execution_id",
            "timestamp",
            "kind",
            "category",
            "severity",
            "action",
            "tool",
            "policy_decision",
            "execution_result",
            "duration",
            "language",
            "compile_status",
            "seq",
        }
        return {
            **{k: v for k, v in event.items() if k in allowed},
            "integrity": "verified" if signed else "legacy_unverified",
        }

    async def replay(self, uid, after):
        stream = await self.db.monitor_streams.find_one({"_id": uid, "user_id": uid})
        if not stream:
            return [], False
        events = stream.get("events", [])
        gap = bool(
            events and after and (after < events[0]["seq"] - 1 or after > stream["seq"])
        )
        if events and (
            events[-1]["seq"] != stream["seq"]
            or any(b["seq"] != a["seq"] + 1 for a, b in zip(events, events[1:]))
        ):
            raise AuditIntegrityError()
        batch = [
            self.public_event(v, uid, stream.get("signed_from"))
            for v in events
            if v["seq"] > after
        ][:50]
        return batch, gap
