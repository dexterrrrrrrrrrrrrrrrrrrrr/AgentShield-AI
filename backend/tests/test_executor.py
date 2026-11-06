"""Internal transport/security tests. Actual Docker remains a separate gate."""
import asyncio
import json
import secrets
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.sandbox.executor import create_executor
from app.sandbox.remote import RemoteManager, config_hash, signature
from app.sandbox.manager import Unavailable
from app.sandbox.registry import LANGUAGES

KEY=secrets.token_urlsafe(48).encode()

class Manager:
    def __init__(self):
        self.adapter=SimpleNamespace(last_diagnostic='EFFECTIVE_ISOLATION_MISMATCH')
        self.calls=[]
        self.ready=True
    async def readiness(self, language): return {'ready':self.ready,'code':'READY' if self.ready else 'SANDBOX_UNAVAILABLE'}
    async def execute(self, code, language, stdin):
        self.calls.append((code,language,stdin))
        if not self.ready: raise Unavailable()
        return dict(status='completed',stdout='hello\n',stderr='',exit_code=0,duration=0.1,
                    language=language,compile_status='not_required',execution_duration_ms=100)


def payload(client,settings,**changes):
    epoch=client.get('/challenge',headers={'Authorization':'Bearer '+KEY.decode()}).json()['epoch']
    return dict(epoch=epoch,nonce=secrets.token_hex(32),timestamp=int(time.time()),
                language='python',configuration=config_hash(settings,'python'),code='print(1)',stdin='',**changes)

def send(client,path,data,key=KEY):
    body=json.dumps(data).encode()
    return client.post(path,content=body,headers={'X-Executor-Signature':signature(key,path,body)})

@pytest.mark.parametrize('language',LANGUAGES)
def test_remote_path_all_languages(settings, language):
    settings.sandbox_enabled=True
    manager=Manager()
    remote=RemoteManager(settings,transport=httpx.ASGITransport(app=create_executor(settings,manager,KEY)),key=KEY)
    async def run():
        assert (await remote.readiness(language))['ready']
        assert (await remote.execute('source',language,'input'))['stdout']=='hello\n'
    asyncio.run(run())
    assert manager.calls==[('source',language,'input')]

@pytest.mark.parametrize('change',[{'epoch':'a'*64},{'timestamp':0},{'configuration':'b'*64},{'mounts':['/']},{'language':'bash'}])
def test_reject_configuration_protocol_and_unknown_language(settings,change):
    manager=Manager()
    with TestClient(create_executor(settings,manager,KEY)) as c:
        data=payload(c,settings);data.update(change)
        assert send(c,'/execute',data).status_code==409
    assert not manager.calls


def test_authentication_replay_and_restart_epoch(settings):
    manager=Manager()
    with TestClient(create_executor(settings,manager,KEY)) as c:
        assert c.get('/challenge').status_code==401
        data=payload(c,settings)
        assert send(c,'/execute',data,b'wrong').status_code==401
        assert send(c,'/execute',data).status_code==200
        assert send(c,'/execute',data).status_code==409
    with TestClient(create_executor(settings,manager,KEY)) as c:
        assert send(c,'/execute',data).status_code==409
    assert len(manager.calls)==1


def test_liveness_is_not_readiness_and_transport_error_never_retries(settings):
    settings.sandbox_enabled=True
    manager=Manager();manager.ready=False
    app=create_executor(settings,manager,KEY)
    with TestClient(app) as c: assert c.get('/health').status_code==200
    remote=RemoteManager(settings,transport=httpx.ASGITransport(app=app),key=KEY)
    async def run():
        assert not (await remote.readiness())['ready']
        with pytest.raises(Unavailable): await remote.execute('x')
        with pytest.raises(Unavailable): await remote.execute('x')
        assert remote.failed
    asyncio.run(run())
    assert len(manager.calls)==1


def test_request_size_and_code_validation(settings):
    manager=Manager()
    with TestClient(create_executor(settings,manager,KEY)) as c:
        assert c.post('/execute',content=b'x'*262145).status_code==413
        data=payload(c,settings);data['code']='x'*32769
        assert send(c,'/execute',data).status_code==422
    assert not manager.calls


def test_executor_cannot_inject_owner_fields(settings):
    settings.sandbox_enabled=True
    remote=RemoteManager(settings,key=KEY)
    async def forged(*args,**kwargs): return dict(user_id='foreign')
    remote.request=forged
    with pytest.raises(Unavailable): asyncio.run(remote.execute('x'))
    assert remote.failed


def test_public_api_approval_through_remote_adapter(client):
    from conftest import register, login, csrf_headers, db_call
    register(client);login(client)
    settings=client.app.state.settings
    settings.sandbox_enabled=True
    manager=Manager()
    client.app.state.sandbox_manager=RemoteManager(settings,key=KEY,
        transport=httpx.ASGITransport(app=create_executor(settings,manager,KEY)))
    assert client.post('/api/sandbox/execute',json={'code':KEY.decode()},headers=csrf_headers(client)).status_code==422
    pending=client.post('/api/sandbox/execute',json={'language':'python','source_code':'print(1)','tool':'execute_code'},headers=csrf_headers(client))
    assert pending.status_code==200
    data=pending.json()
    assert data['status']=='pending_approval'
    assert manager.calls==[]
    path='/api/sandbox/approvals/'+data['id']
    body={'approve':True,'request_hash':data['request_hash']}
    done=client.post(path,json=body,headers=csrf_headers(client))
    assert done.status_code==200,done.text
    assert done.json()['status']=='completed'
    assert client.post(path,json=body,headers=csrf_headers(client)).status_code==409
    assert len(manager.calls)==1
    history=client.get('/api/sandbox/executions').json()['executions']
    assert history[0]['stdout']=='hello\n'
    assert db_call(client,'execution_logs','find_one',{'_id':data['id']})['status']=='completed'
