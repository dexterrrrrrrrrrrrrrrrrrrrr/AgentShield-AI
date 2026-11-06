"""Narrow authenticated Unix-socket adapter; no remote Docker management API."""
import asyncio
import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from ..guards import strict_json

import httpx

from .manager import Unavailable
from .registry import configuration

SOCKET = '/run/agentshield-executor/control.sock'
TOKEN_FILE = '/run/secrets/executor_token'


def read_key():
    key = Path(TOKEN_FILE).read_bytes().strip()
    if len(key) < 48 or len(key) > 128 or len(set(key)) < 16:
        raise RuntimeError('Executor credential configuration is invalid')
    return key


def config_hash(settings, language):
    return hashlib.sha256(json.dumps(configuration(settings, language), sort_keys=True).encode()).hexdigest()


def signature(key, path, body):
    return hmac.new(key, path.encode()+b'\n'+body, hashlib.sha256).hexdigest()


class ExecutionResult(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,allow_inf_nan=False)
    status: Literal['completed','failed','timed_out','output_limit']
    stdout: str = Field(max_length=65536)
    stderr: str = Field(max_length=65536)
    exit_code: int
    duration: float = Field(ge=0,le=120)
    language: str = Field(max_length=16)
    compile_status: Literal['completed','failed','timed_out','output_limit','not_required']
    compile_stdout: str = Field(default='',max_length=65536)
    compile_stderr: str = Field(default='',max_length=65536)
    execution_duration_ms: int = Field(ge=0,le=120000)
    compile_duration_ms: int = Field(default=0,ge=0,le=120000)
    truncated: bool = False
    oom_killed: bool = False
    output_bytes: int = Field(default=0,ge=0,le=65536)
    error_category: str | None = Field(default=None,max_length=64)


class RemoteManager:
    def __init__(self, settings, transport=None, key=None):
        self.s = settings
        self.key = key or read_key()
        self.failed = False
        self.lock = asyncio.Lock()
        self.adapter = self
        self.last_diagnostic = 'EXECUTOR_UNAVAILABLE'
        self.transport = transport

    async def request(self, path, language, **values):
        transport = self.transport or httpx.AsyncHTTPTransport(uds=SOCKET, retries=0)
        async with httpx.AsyncClient(transport=transport, base_url='http://executor', timeout=90, follow_redirects=False) as client:
            async with client.stream('GET','/challenge',headers={'Authorization':'Bearer '+self.key.decode()}) as response:
                response.raise_for_status()
                data=bytearray()
                async for chunk in response.aiter_bytes(256):
                    if len(data)+len(chunk)>1024: raise Unavailable('SANDBOX_UNAVAILABLE')
                    data.extend(chunk)
                epoch = strict_json(bytes(data))['epoch']
            payload = dict(epoch=epoch, nonce=secrets.token_hex(32), timestamp=int(time.time()),
                           language=language, configuration=config_hash(self.s, language), **values)
            body = json.dumps(payload, ensure_ascii=True, separators=(',', ':')).encode()
            async with client.stream('POST', path, content=body,
                headers={'X-Executor-Signature':signature(self.key,path,body),'Content-Type':'application/json'}) as response:
                response.raise_for_status()
                data=bytearray()
                async for chunk in response.aiter_bytes(4096):
                    data.extend(chunk)
                    if len(data)>400000: raise Unavailable('SANDBOX_UNAVAILABLE')
                return strict_json(bytes(data))

    async def readiness(self, language='python'):
        if not self.s.sandbox_enabled or self.failed or self.lock.locked():
            return {'ready':False,'code':'SANDBOX_UNAVAILABLE'}
        try:
            result = await self.request('/readiness',language)
            self.last_diagnostic = result.get('reason','UNVERIFIED')
            if type(result.get('ready')) is not bool: raise ValueError()
            return result
        except Exception:
            self.last_diagnostic='EXECUTOR_UNAVAILABLE'
            return {'ready':False,'code':'SANDBOX_UNAVAILABLE'}

    async def execute(self, code, language='python', stdin=''):
        if not self.s.sandbox_enabled or self.failed or self.lock.locked():
            raise Unavailable('SANDBOX_UNAVAILABLE')
        async with self.lock:
            try:
                result=await self.request('/execute',language,code=code,stdin=stdin)
                result=ExecutionResult.model_validate(result).model_dump()
                if result['language']!=language: raise ValueError()
                if sum(len(result[k].encode()) for k in ('stdout','stderr','compile_stdout','compile_stderr')) > self.s.sandbox_output_bytes: raise ValueError()
                return result
            except BaseException as exc:
                # Never retry uncertain execution. Existing Mongo latch blocks later jobs.
                self.failed=True
                if isinstance(exc,asyncio.CancelledError): raise
                raise Unavailable('SANDBOX_UNAVAILABLE') from None
