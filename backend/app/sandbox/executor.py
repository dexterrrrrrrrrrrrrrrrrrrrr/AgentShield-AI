"""Trusted one-worker executor. No database, identity provider or public routes."""
import asyncio
import hmac
import json
import os
import secrets
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ..config import Settings
from ..guards import strict_json
from .manager import SandboxManager, Unavailable
from .policy import CodeRequest
from .remote import SOCKET, config_hash, read_key, signature


class Envelope(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    epoch: str = Field(pattern='^[a-f0-9]{64}$')
    nonce: str = Field(pattern='^[a-f0-9]{64}$')
    timestamp: int
    configuration: str = Field(pattern='^[a-f0-9]{64}$')
    language: str = Field(max_length=16)
    code: str | None = None
    stdin: str = ''


def create_executor(settings=None, manager=None, key=None):
    settings=settings or Settings(_env_file=None,jwt_secret=secrets.token_urlsafe(48),sandbox_enabled=True)
    manager=manager or SandboxManager(settings)
    key=key or read_key()
    epoch=secrets.token_hex(32)
    used={}

    @asynccontextmanager
    async def lifespan(app):
        # Uvicorn creates its UDS before lifespan starts; directory is private.
        yield

    app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)

    @app.middleware('http')
    async def bounded(request, call_next):
        if request.method=='POST':
            try:
                async with asyncio.timeout(5):
                    data=bytearray()
                    async for chunk in request.stream():
                        if len(data)+len(chunk)>262144: return JSONResponse({'detail':'Invalid request'},413)
                        data.extend(chunk)
                    request.state.body=bytes(data)
            except Exception:
                return JSONResponse({'detail':'Invalid request'},400)
        response=await call_next(request)
        response.headers['Cache-Control']='no-store'
        return response

    @app.get('/health')
    async def health(): return {'status':'alive'}  # NOT sandbox readiness.

    @app.get('/challenge')
    async def challenge(request: Request):
        if not hmac.compare_digest(request.headers.get('authorization',''), 'Bearer '+key.decode()):
            raise HTTPException(401,'Unauthorized')
        return {'epoch':epoch}

    async def admit(request):
        body=request.state.body
        if not hmac.compare_digest(request.headers.get('x-executor-signature',''),signature(key,request.url.path,body)):
            raise HTTPException(401,'Unauthorized')
        try:
            payload=Envelope.model_validate(strict_json(body))
            if payload.epoch!=epoch or abs(time.time()-payload.timestamp)>30: raise ValueError()
            if payload.configuration!=config_hash(settings,payload.language): raise ValueError()
        except (ValueError,TypeError): raise HTTPException(409,'Request or configuration mismatch') from None
        # No await between cleanup, replay check and insertion. One worker only.
        now=time.monotonic()
        for nonce, deadline in list(used.items()):
            if deadline<now: del used[nonce]
        if payload.nonce in used: raise HTTPException(409,'Request already used')
        if len(used)>=128: raise HTTPException(429,'Executor admission full')
        used[payload.nonce]=now+65  # covers ±30s timestamp acceptance window
        return payload

    @app.post('/readiness')
    async def readiness(request: Request):
        p=await admit(request)
        if p.code is not None or p.stdin: raise HTTPException(422,'Unexpected execution data')
        result=await manager.readiness(p.language)
        reason=getattr(manager.adapter,'last_diagnostic','UNVERIFIED')
        if getattr(manager,'failed',False): reason='RECOVERY_REQUIRED'
        elif getattr(manager,'lock',None) and manager.lock.locked(): reason='BUSY'
        return {**result,'reason':reason}

    @app.post('/execute')
    async def execute(request: Request):
        p=await admit(request)
        try:
            code=CodeRequest(language=p.language,code=p.code,stdin=p.stdin,tool='execute_code')
        except ValueError: raise HTTPException(422,'Invalid execution request') from None
        try:
            return await manager.execute(code.code,language=code.language,stdin=code.stdin)
        except Unavailable: raise HTTPException(503,'SANDBOX_UNAVAILABLE') from None

    return app


def main():
    import uvicorn
    os.umask(0o077)
    uvicorn.run(create_executor(),uds=SOCKET,workers=1,access_log=False,
                proxy_headers=False,limit_concurrency=16,timeout_keep_alive=2,
                timeout_graceful_shutdown=100)

if __name__=='__main__': main()
