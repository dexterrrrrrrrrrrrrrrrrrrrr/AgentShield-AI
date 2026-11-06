from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from ..security import current_identity, limit_attempts, require_csrf, utcnow
from .policy import CodeRequest, limits
from .registry import LANGUAGES
from .service import SandboxService

router = APIRouter(prefix="/api/sandbox", tags=["Sandbox"])
ID = Annotated[str, Path(pattern="^[a-f0-9]{32}$")]


def service(request):
    async def authorize():
        await current_identity(request)

    return SandboxService(
        request.app.state.db,
        request.app.state.settings,
        request.app.state.sandbox_manager,
        monitor=request.app.state.monitor,
        authorize=authorize,
    )


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approve: StrictBool
    request_hash: str = Field(pattern="^[a-f0-9]{64}$")


@router.get("/languages")
async def languages(request: Request, identity=Depends(current_identity)):
    await limit_attempts(request, "sandbox_read", identity[0]["_id"], 60)
    return {
        "languages": [
            {
                "id": entry.id,
                "display_name": entry.display_name,
                "extension": entry.extension,
                "version": entry.version,
                "compilation_required": entry.compilation_required,
                "limits": limits(request.app.state.settings, entry.id),
            }
            for entry in LANGUAGES.values()
        ]
    }


READINESS_MESSAGES = {
    "DISABLED": "Sandbox execution is disabled. Enable it only on a trusted host after local isolation validation.",
    "RECOVERY_REQUIRED": "An interrupted execution requires operator recovery and a new isolation validation before execution can resume.",
    "BUSY": "The sandbox is busy. Wait for the current execution to finish, then check again.",
    "DOCKER_UNAVAILABLE": "The trusted backend cannot reach its configured Docker runtime. Start Colima and verify the native backend Docker endpoint.",
    "CGROUP_V2_UNAVAILABLE": "The runtime does not provide the required cgroup v2 support. Validate Colima CPU, memory and PID controllers with the local validation script.",
    "ORPHANED_CONTAINERS": "A previous sandbox container requires trusted operator inspection and cleanup before execution can resume.",
    "RUNTIME_NOT_PROVISIONED": "Build the selected approved runtime with the provisioning script and configure its resulting image digest on the native backend.",
    "RUNTIME_IMAGE_UNAVAILABLE": "The configured approved runtime image is missing. Provision it locally; the application never downloads runtimes automatically.",
    "RUNTIME_IMAGE_MISMATCH": "The runtime identity does not match its approved configuration. Rebuild it with the supplied provisioning script.",
    "RUNTIME_VERSION_MISMATCH": "The compiler or interpreter version differs from the approved registry. Rebuild the approved runtime before execution.",
    "EFFECTIVE_ISOLATION_MISMATCH": "Effective resource or isolation controls did not match the required policy. Run the local sandbox validator and correct the runtime; execution remains blocked.",
    "UNVERIFIED": "Required sandbox controls could not be verified. Inspect protected backend diagnostics and run the local validation script.",
}


@router.get("/readiness")
async def readiness(
    request: Request,
    language: str = Query("python", max_length=16),
    identity=Depends(current_identity),
):
    if language not in LANGUAGES:
        raise HTTPException(422, "Unsupported language")
    await limit_attempts(request, "sandbox_read", identity[0]["_id"], 60)
    manager = request.app.state.sandbox_manager
    blocked = await request.app.state.db.sandbox_locks.find_one(
        {"_id": "execution", "blocked": True}
    )
    if blocked or getattr(manager, "failed", False):
        reason = "RECOVERY_REQUIRED"
    elif not request.app.state.settings.sandbox_enabled:
        reason = "DISABLED"
    elif getattr(manager, "lock", None) and manager.lock.locked():
        reason = "BUSY"
    else:
        result = await service(request).ready(language)
        if result["ready"]:
            return {"ready": True, "code": "READY", "language": language}
        reason = getattr(
            getattr(manager, "adapter", None), "last_diagnostic", "UNVERIFIED"
        )
        if reason not in READINESS_MESSAGES:
            reason = "UNVERIFIED"
    return {
        "ready": False,
        "code": "SANDBOX_UNAVAILABLE",
        "language": language,
        "reason": reason,
        "message": READINESS_MESSAGES[reason],
    }


@router.post("/execute", dependencies=[Depends(require_csrf)])
async def execute(
    payload: CodeRequest, request: Request, identity=Depends(current_identity)
):
    await limit_attempts(
        request,
        "sandbox_execute",
        identity[0]["_id"],
        request.app.state.settings.sandbox_user_limit,
    )
    return await service(request).request(identity[0]["_id"], payload)


@router.get("/executions")
async def executions(
    request: Request,
    offset: int = Query(0, ge=0, le=10000),
    limit: int = Query(20, ge=1, le=50),
    language: str | None = Query(None, max_length=16),
    identity=Depends(current_identity),
):
    if language is not None and language not in LANGUAGES:
        raise HTTPException(422, "Unsupported language")
    uid = identity[0]["_id"]
    await limit_attempts(request, "sandbox_read", uid, 60)
    query = {"user_id": uid}
    if language == "python":
        query["$or"] = [{"language": "python"}, {"language": {"$exists": False}}]
    elif language:
        query["language"] = language
    items = (
        await request.app.state.db.execution_logs.find(query)
        .sort([("created_at", -1), ("_id", -1)])
        .skip(offset)
        .limit(limit)
        .to_list(length=limit)
    )
    return {
        "executions": [
            SandboxService.public(v, request.app.state.settings) for v in items
        ]
    }


@router.get("/executions/{eid}")
async def execution(eid: ID, request: Request, identity=Depends(current_identity)):
    uid = identity[0]["_id"]
    await limit_attempts(request, "sandbox_read", uid, 60)
    item = await request.app.state.db.execution_logs.find_one(
        {"_id": eid, "user_id": uid}
    )
    if not item:
        raise HTTPException(404, "Execution not found")
    result = SandboxService.public(item, request.app.state.settings)
    pending = await request.app.state.db.sandbox_approvals.find_one(
        {
            "_id": eid,
            "user_id": uid,
            "state": "pending",
            "expires_at": {"$gt": utcnow()},
        }
    )
    if pending:
        result["approval_request"] = (
            service(request).approval_payload(pending).model_dump()
        )
    return result


@router.post("/approvals/{eid}", dependencies=[Depends(require_csrf)])
async def approve(
    eid: ID, payload: Approval, request: Request, identity=Depends(current_identity)
):
    uid = identity[0]["_id"]
    await limit_attempts(
        request, "sandbox_execute", uid, request.app.state.settings.sandbox_user_limit
    )
    if not payload.approve:
        raise HTTPException(422, "Explicit approval is required")
    return await service(request).approve(uid, eid, payload.request_hash)


class Rejection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reject: StrictBool
    request_hash: str = Field(pattern="^[a-f0-9]{64}$")


@router.post("/approvals/{eid}/reject", dependencies=[Depends(require_csrf)])
async def reject(
    eid: ID, payload: Rejection, request: Request, identity=Depends(current_identity)
):
    uid = identity[0]["_id"]
    await limit_attempts(
        request, "sandbox_execute", uid, request.app.state.settings.sandbox_user_limit
    )
    if not payload.reject:
        raise HTTPException(422, "Explicit rejection is required")
    return await service(request).reject(uid, eid, payload.request_hash)
