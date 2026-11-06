"""Explicit fixed harmless program through real browser-facing auth/approval APIs.

Creates one synthetic account and retained audit/history rows. No provider mocks.
Run against an isolated local deployment, one language per invocation to respect quotas.
"""
import argparse
import json
import secrets
import sys
import uuid
from pathlib import Path

import httpx

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from scripts.validate_multilanguage import PROGRAMS


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://localhost:3000')
    parser.add_argument('--language',choices=list(PROGRAMS),default='python')
    args=parser.parse_args()
    base=httpx.URL(args.base_url)
    if base.scheme not in ('http','https') or base.host not in ('localhost','127.0.0.1','::1') or base.username or base.password or base.path not in ('','/') or base.query or base.fragment:
        parser.error('Use a credential-free loopback origin')
    with httpx.Client(base_url=str(base).rstrip('/'),timeout=100,follow_redirects=False,trust_env=False) as client:
        def request(path,data=None):
            if data is None: r=client.get(path)
            else:
                csrf=client.get('/api/auth/csrf');csrf.raise_for_status()
                r=client.post(path,json=data,headers={'Origin':str(base).rstrip('/'),'X-CSRF-Token':csrf.json()['csrf_token']})
            if r.is_error: raise RuntimeError('Validation API returned HTTP '+str(r.status_code))
            return r.json() if r.content else {}
        password=secrets.token_urlsafe(32)
        email='executor-validation-'+uuid.uuid4().hex+'@example.com'
        request('/api/auth/register',dict(full_name='Executor Validation',email=email,password=password,confirm_password=password))
        request('/api/auth/login',dict(email=email,password=password))
        try:
            ready=request('/api/sandbox/readiness?language='+args.language)
            if not ready.get('ready'):
                print(json.dumps({'status':'BLOCKED','language':args.language,'readiness':ready,'programs_executed':0},indent=2));return 2
            pending=request('/api/sandbox/execute',dict(language=args.language,source_code=PROGRAMS[args.language],stdin='validation\n',tool='execute_code'))
            if pending['status']!='pending_approval': raise RuntimeError('Expected human approval policy')
            # Invocation explicitly authorizes only the fixed hello-world request.
            result=request('/api/sandbox/approvals/'+pending['id'],dict(approve=True,request_hash=pending['request_hash']))
            passed=result['status']=='completed' and result['stdout']=='hello\n' and result['exit_code']==0
            print(json.dumps({'status':'PASS' if passed else 'FAIL','language':args.language,'execution_id':result['id'],'execution_status':result['status'],'compile_status':result.get('compile_status')},indent=2))
            return 0 if passed else 1
        finally: request('/api/auth/logout',{})

if __name__=='__main__':
    try: raise SystemExit(main())
    except Exception as error:
        # No raw HTTP/provider exceptions, credentials, request bodies or cookies.
        print('FAIL: deployed sandbox validation failed ('+type(error).__name__+')',file=sys.stderr)
        raise SystemExit(1)
