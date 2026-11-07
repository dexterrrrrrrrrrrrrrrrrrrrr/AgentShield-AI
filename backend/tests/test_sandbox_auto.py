"""Real auth/MongoDB and signed executor protocol; Docker execution is mocked."""
import secrets

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.sandbox.executor import create_executor
from app.sandbox.remote import RemoteManager
from app.sandbox.registry import LANGUAGES
from conftest import csrf_headers, db_call, login, register
from test_executor import KEY, Manager


def auto_setup(client):
    register(client)
    login(client)
    s = client.app.state.settings
    s.app_env = "development"
    s.sandbox_enabled = True
    s.sandbox_policy = "auto"
    s.sandbox_trusted_local = True
    s.sandbox_transport = "executor"
    manager = Manager()
    client.app.state.sandbox_manager = RemoteManager(
        s, key=KEY, transport=httpx.ASGITransport(app=create_executor(s, manager, KEY))
    )
    return manager


def submit(client, **changes):
    return client.post('/api/sandbox/execute', headers=csrf_headers(client),
                       json={'source_code': 'fixed test source', 'tool': 'execute_code', **changes})


@pytest.mark.parametrize('changes', [
    {'sandbox_trusted_local': False},
    {'app_env': 'production', 'cors_origins': 'https://localhost:3000'},
    {'app_env': 'test'},
    {'cors_origins': 'https://public.example'},
    {'cors_origins': 'http://localhost:3000,https://public.example'},
])
def test_auto_configuration_requires_explicit_local_development(changes):
    config = dict(_env_file=None, jwt_secret=secrets.token_urlsafe(48),
                  sandbox_policy='auto', sandbox_trusted_local=True, app_env='development')
    with pytest.raises(ValidationError, match='SANDBOX_POLICY=auto requires'):
        Settings(**{**config, **changes})


def test_auto_configuration_is_opt_in_and_approval_stays_production_default():
    key = secrets.token_urlsafe(48)
    assert Settings(_env_file=None, jwt_secret=key).sandbox_policy == 'approval'
    assert Settings(_env_file=None, jwt_secret=key, app_env='production',
                    cors_origins='https://example.com').sandbox_policy == 'approval'
    assert Settings(_env_file=None, jwt_secret=key, sandbox_policy='auto',
                    sandbox_trusted_local=True).sandbox_auto_allowed


@pytest.mark.parametrize('language', LANGUAGES)
def test_auto_executes_once_through_executor_and_persists_without_approval(client, language):
    manager = auto_setup(client)
    assert client.get('/api/sandbox/languages').json()['execution_policy'] == 'AUTO_EXECUTE'
    response = submit(client, language=language, stdin='input data')
    assert response.status_code == 200
    result = response.json()
    assert result['status'] == 'completed'
    assert result['policy_decision'] == 'ALLOW'
    assert result['execution_policy'] == 'AUTO_EXECUTE'
    assert result['stdout'] == 'hello\n' and result['stderr'] == '' and result['exit_code'] == 0
    assert manager.calls == [('fixed test source', language, 'input data')]
    assert db_call(client, 'sandbox_approvals', 'count_documents', {}) == 0
    assert client.get('/api/sandbox/executions/' + result['id']).json()['status'] == 'completed'
    events = client.get('/api/monitor/events').json()['events']
    assert {'policy_evaluation', 'sandbox_started', 'sandbox_completed'} <= {v['kind'] for v in events}
    assert all(v['integrity'] == 'verified' for v in events)
    assert 'approval_required' not in {v['kind'] for v in events}
    assert client.post('/api/sandbox/approvals/' + result['id'], headers=csrf_headers(client),
                       json={'approve': True, 'request_hash': result['request_hash']}).status_code == 409
    assert len(manager.calls) == 1
    register(client, 'other@example.com'); login(client, 'other@example.com')
    assert client.get('/api/sandbox/executions/' + result['id']).status_code == 404
    assert client.get('/api/sandbox/executions').json()['executions'] == []


@pytest.mark.parametrize('failure', ['readiness', 'disabled', 'recovery', 'trust', 'production'])
def test_auto_fail_closed(client, failure):
    manager = auto_setup(client)
    s = client.app.state.settings
    if failure == 'readiness': manager.ready = False
    elif failure == 'disabled': s.sandbox_enabled = False
    elif failure == 'trust': s.sandbox_trusted_local = False
    elif failure == 'production': s.app_env = 'production'
    else: db_call(client, 'sandbox_locks', 'update_one', {'_id': 'execution'}, {'$set': {'blocked': True}}, upsert=True)
    response = submit(client)
    if failure == 'production':
        assert response.status_code == 403  # Secure CSRF cookies cannot be sent over test HTTP.
        from app.sandbox.policy import policy_mode
        assert policy_mode(s) == 'deny'
    else:
        assert response.json()['status'] in ('unavailable', 'denied')
    assert not manager.calls


def test_auto_keeps_auth_csrf_validation_quota_and_ownership(client):
    assert submit(client).status_code == 401
    manager = auto_setup(client)
    assert client.post('/api/sandbox/execute', json={'code': 'x'}).status_code == 403
    assert submit(client, language='shell').status_code == 422
    assert submit(client, image='arbitrary').status_code == 422
    assert submit(client, source_code='x' * 32769).status_code == 422
    assert submit(client, agent_session_id='a' * 32).status_code == 404
    assert not manager.calls
    # Independently exercise the persistent service quota as well as HTTP admission.
    client.app.state.settings.sandbox_user_limit = 1
    db_call(client, 'security_events', 'delete_many', {})
    assert submit(client).json()['status'] == 'completed'
    assert submit(client).status_code == 429
    assert len(manager.calls) == 1


@pytest.mark.parametrize("mode", ["auto", "allow", "approval"])
def test_auto_does_not_automatically_execute_agent_requests(client, mode):
    manager = auto_setup(client)
    client.app.state.settings.sandbox_policy = mode
    uid = db_call(client, 'users', 'find_one', {'email': 'alice@example.com'})['_id']
    sid = 'b' * 32
    db_call(client, 'agent_sessions', 'insert_one', {'_id': sid, 'user_id': uid, 'allowed_tools': ['execute_code']})
    result = submit(client, agent_session_id=sid).json()
    assert result['status'] == 'pending_approval'
    assert result['execution_policy'] == 'REQUIRE_APPROVAL'
    assert not manager.calls
    approved = client.post('/api/sandbox/approvals/' + result['id'], headers=csrf_headers(client),
                           json={'approve': True, 'request_hash': result['request_hash']})
    assert approved.status_code == 200 and approved.json()['status'] == 'completed'
    assert len(manager.calls) == 1


def test_switching_policy_does_not_auto_approve_existing_requests(client):
    manager = auto_setup(client)
    s = client.app.state.settings
    s.sandbox_policy = 'approval'
    result = submit(client).json()
    assert result['status'] == 'pending_approval'
    s.sandbox_policy = 'auto'
    assert client.post('/api/sandbox/approvals/' + result['id'], headers=csrf_headers(client),
                       json={'approve': True, 'request_hash': result['request_hash']}).status_code == 409
    assert not manager.calls


@pytest.mark.parametrize('change', ['trust', 'policy', 'logout'])
def test_auto_revalidates_after_admission_before_dispatch(client, monkeypatch, change):
    from app.sandbox.service import SandboxService
    manager = auto_setup(client)
    original = SandboxService.run

    async def changed(self, uid, eid, payload, **kwargs):
        if change == 'trust': self.s.sandbox_trusted_local = False
        elif change == 'policy': self.s.sandbox_policy = 'approval'
        else: await self.db.sessions.delete_many({'user_id': uid})
        return await original(self, uid, eid, payload, **kwargs)

    monkeypatch.setattr(SandboxService, 'run', changed)
    assert submit(client).status_code in (401, 403)
    assert not manager.calls
