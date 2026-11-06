"""Validator control-flow checks using HTTP fixtures, not real Docker results."""
import importlib.util
from pathlib import Path
import sys

import httpx
import pytest

path = Path(__file__).resolve().parents[2] / 'scripts/validate-deployed-sandbox.py'
spec = importlib.util.spec_from_file_location('deployed_validator', path)
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


@pytest.mark.parametrize('policy', ['auto', 'approval'])
@pytest.mark.parametrize('fault', [None, 'policy', 'readiness', 'stderr', 'history', 'audit'])
def test_deployed_validator_checks_policy_execution_history_and_audit(monkeypatch, capsys, policy, fault):
    eid = 'a' * 32
    calls = []
    result = dict(id=eid, language='c', status='completed', execution_policy='AUTO_EXECUTE',
                  stdout='hello\n', stderr='unexpected' if fault == 'stderr' else '',
                  exit_code=0, compile_status='completed')

    def handle(request):
        path = request.url.path
        calls.append(path)
        if path == '/api/auth/csrf': data = {'csrf_token': 'fixture'}
        elif path.startswith('/api/auth/'): data = {}
        elif path == '/api/sandbox/languages':
            data = {'execution_policy': 'DENY' if fault == 'policy' else 'AUTO_EXECUTE' if policy == 'auto' else 'REQUIRE_APPROVAL'}
        elif path == '/api/sandbox/readiness': data = {'ready': fault != 'readiness'}
        elif path == '/api/sandbox/execute':
            data = result if policy == 'auto' else dict(id=eid, status='pending_approval', request_hash='b' * 64)
        elif path == '/api/sandbox/approvals/' + eid: data = result
        elif path == '/api/sandbox/executions/' + eid:
            data = {**result, 'status': 'failed'} if fault == 'history' else result
        elif path == '/api/monitor/events':
            data = {'events': [dict(execution_id=eid, kind=kind, integrity='legacy_unverified' if fault == 'audit' else 'verified')
                               for kind in ['policy_evaluation', 'sandbox_started', 'sandbox_completed', 'tool_approved']]}
        else: raise AssertionError(path)
        return httpx.Response(200, json=data)

    original = httpx.Client
    monkeypatch.setattr(validator.httpx, 'Client', lambda **kw: original(**kw, transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(sys, 'argv', ['validator', '--language', 'c', '--policy', policy])
    if fault == 'policy':
        with pytest.raises(RuntimeError): validator.main()
        assert '/api/sandbox/execute' not in calls
    else:
        assert validator.main() == (0 if fault is None else 2 if fault == 'readiness' else 1)
        if fault == 'readiness': assert '/api/sandbox/execute' not in calls
    if policy == 'auto': assert not any('/approvals/' in call for call in calls)
    assert calls[-1] == '/api/auth/logout'
    capsys.readouterr()
