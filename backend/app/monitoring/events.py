import uuid
from datetime import timedelta

from pymongo import ReturnDocument

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
TOOLS = {"calculator", "summarize_text", "format_json", "python_sandbox"}
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


class Monitor:
    def __init__(self, db):
        self.db = db
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
        # One atomic append allocates sequence and persists a bounded replay feed.
        # No allocate-then-insert race can make a client skip a later commit.
        stream = await self.db.monitor_streams.find_one_and_update(
            {"_id": uid, "user_id": uid},
            [
                {"$set": {"seq": {"$add": [{"$ifNull": ["$seq", 0]}, 1]}}},
                {
                    "$set": {
                        "user_id": uid,
                        "events": {
                            "$slice": [
                                {
                                    "$concatArrays": [
                                        {"$ifNull": ["$events", []]},
                                        [
                                            {
                                                "$mergeObjects": [
                                                    {"$literal": event},
                                                    {"seq": "$seq"},
                                                ]
                                            }
                                        ],
                                    ]
                                },
                                -200,
                            ]
                        },
                        "updated_at": now,
                    }
                },
            ],
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        published = stream["events"][-1]
        await self.db.security_events.insert_one(
            {
                "_id": event["id"],
                "kind": "monitor_event",
                "user_id": uid,
                "event": published,
                "expires_at": now + timedelta(days=7),
            }
        )
        return published

    async def replay(self, uid, after):
        stream = await self.db.monitor_streams.find_one({"_id": uid, "user_id": uid})
        if not stream:
            return [], False
        events = stream.get("events", [])
        gap = bool(
            events and after and (after < events[0]["seq"] - 1 or after > stream["seq"])
        )
        return [v for v in events if v["seq"] > after][:50], gap
