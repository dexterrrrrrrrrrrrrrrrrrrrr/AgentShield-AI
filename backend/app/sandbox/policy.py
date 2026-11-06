import hashlib
import json
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .registry import LANGUAGES, configuration

IMAGE = "python@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30"


class Decision(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


class CodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    code: str = Field(min_length=1, max_length=32768)
    language: str = "python"
    stdin: str = Field(default="", max_length=8192)
    agent_session_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    tool: str = Field(
        default="python_sandbox", pattern="^(python_sandbox|execute_code)$"
    )

    @model_validator(mode="before")
    @classmethod
    def source_alias(cls, value):
        if not isinstance(value, dict):
            return value
        value = dict(value)
        if "source_code" in value:
            if "code" in value:
                raise ValueError("Supply code or source_code, not both")
            value["code"] = value.pop("source_code")
        if "tool" not in value and value.get("language", "python") != "python":
            value["tool"] = "execute_code"
        return value

    @field_validator("language")
    @classmethod
    def registered_language(cls, value):
        if value not in LANGUAGES:
            raise ValueError("Unsupported language")
        return value

    @field_validator("code")
    @classmethod
    def code_bytes(cls, value):
        if len(value.encode()) > 32768 or not value.strip() or "\0" in value:
            raise ValueError("Invalid code size or content")
        return value

    @field_validator("stdin")
    @classmethod
    def stdin_bytes(cls, value):
        if len(value.encode()) > 8192 or "\0" in value:
            raise ValueError("Invalid stdin size or content")
        return value

    @model_validator(mode="after")
    def tool_language(self):
        if self.tool == "python_sandbox" and self.language != "python":
            raise ValueError("python_sandbox only accepts Python")
        return self


def limits(s, language="python"):
    runtime = configuration(s, language)
    return {
        "memory_mb": s.sandbox_memory_mb,
        "cpus": s.sandbox_cpus,
        "pids": s.sandbox_pids,
        "timeout": s.sandbox_timeout,
        "output_bytes": s.sandbox_output_bytes,
        "code_bytes": s.sandbox_code_bytes,
        "stdin_bytes": 8192,
        "compile_timeout": runtime["compile_timeout"],
        "workspace_bytes": runtime["workspace_bytes"],
    }


def fingerprint(payload, s):
    value = {
        **payload.model_dump(),
        "limits": limits(s, payload.language),
        "runtime": configuration(s, payload.language),
        "policy": s.sandbox_policy,
        "revision": 2,
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def evaluate(
    *, authenticated, owned, tool, size, quota, available, enabled, mode, max_size
):
    if (
        not authenticated
        or not owned
        or tool not in ("python_sandbox", "execute_code")
        or size > max_size
        or not quota
        or mode not in ("approval", "allow")
    ):
        return Decision.DENY
    if not enabled or not available:
        return Decision.DENY
    return Decision.REQUIRE_APPROVAL if mode == "approval" else Decision.ALLOW


def policy_mode(settings, *, agent_request=False):
    """Only direct Code Sandbox requests opt in to trusted-local automation."""
    if settings.sandbox_policy != "auto":
        return settings.sandbox_policy
    # Recheck at execution time too; never rely on frontend metadata or startup alone.
    if not settings.sandbox_auto_allowed:
        return "deny"
    return "approval" if agent_request else "allow"


def policy_name(settings, *, agent_request=False):
    mode = policy_mode(settings, agent_request=agent_request)
    if mode == "allow":
        return "AUTO_EXECUTE" if settings.sandbox_policy == "auto" else "ALLOW"
    return "REQUIRE_APPROVAL" if mode == "approval" else "DENY"
