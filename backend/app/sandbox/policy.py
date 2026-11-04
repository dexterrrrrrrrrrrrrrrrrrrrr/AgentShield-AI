import hashlib
import json
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

IMAGE = "python@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30"


class Decision(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


class CodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=32768)
    agent_session_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    tool: str = Field(default="python_sandbox", pattern="^python_sandbox$")

    @field_validator("code")
    @classmethod
    def code_bytes(cls, value):
        if len(value.encode()) > 32768 or not value.strip() or "\0" in value:
            raise ValueError("Invalid code size or content")
        return value


def limits(s):
    return {
        "memory_mb": s.sandbox_memory_mb,
        "cpus": s.sandbox_cpus,
        "pids": s.sandbox_pids,
        "timeout": s.sandbox_timeout,
        "output_bytes": s.sandbox_output_bytes,
        "code_bytes": s.sandbox_code_bytes,
    }


def fingerprint(payload, s):
    value = {
        **payload.model_dump(),
        "limits": limits(s),
        "image": IMAGE,
        "policy": s.sandbox_policy,
        "revision": 1,
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def evaluate(
    *, authenticated, owned, tool, size, quota, available, enabled, mode, max_size
):
    if (
        not authenticated
        or not owned
        or tool != "python_sandbox"
        or size > max_size
        or not quota
        or mode not in ("approval", "allow")
    ):
        return Decision.DENY
    if not enabled or not available:
        return Decision.DENY
    return Decision.REQUIRE_APPROVAL if mode == "approval" else Decision.ALLOW
