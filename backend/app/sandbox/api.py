from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from ..security import current_identity, limit_attempts, require_csrf
from .policy import CodeRequest
from .service import SandboxService

router = APIRouter(prefix="/api/sandbox", tags=["Sandbox"])
ID = Annotated[str, Path(pattern="^[a-f0-9]{32}$")]


def service(request):
    return SandboxService(
        request.app.state.db,
        request.app.state.settings,
        request.app.state.sandbox_manager,
    )


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approve: StrictBool
    request_hash: str = Field(pattern="^[a-f0-9]{64}$")


@router.get("/readiness")
async def readiness(request: Request, identity=Depends(current_identity)):
    await limit_attempts(request, "sandbox_read", identity[0]["_id"], 60)
    if await request.app.state.db.sandbox_locks.find_one(
        {"_id": "execution", "blocked": True}
    ):
        return {"ready": False, "code": "SANDBOX_UNAVAILABLE"}
    return await request.app.state.sandbox_manager.readiness()


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
    identity=Depends(current_identity),
):
    uid = identity[0]["_id"]
    await limit_attempts(request, "sandbox_read", uid, 60)
    items = (
        await request.app.state.db.execution_logs.find({"user_id": uid})
        .sort([("created_at", -1), ("_id", -1)])
        .skip(offset)
        .limit(limit)
        .to_list(length=limit)
    )
    return {"executions": [SandboxService.public(v) for v in items]}


@router.get("/executions/{eid}")
async def execution(eid: ID, request: Request, identity=Depends(current_identity)):
    uid = identity[0]["_id"]
    await limit_attempts(request, "sandbox_read", uid, 60)
    item = await request.app.state.db.execution_logs.find_one(
        {"_id": eid, "user_id": uid}
    )
    if not item:
        raise HTTPException(404, "Execution not found")
    result = SandboxService.public(item)
    pending = await request.app.state.db.sandbox_approvals.find_one(
        {"_id": eid, "user_id": uid, "state": "pending"}
    )
    if pending:
        result["approval_request"] = pending["request"]
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
