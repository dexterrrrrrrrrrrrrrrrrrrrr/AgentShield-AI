"""Real SDK/request-path and authenticated LangGraph/Mongo tests; Groq HTTP mocked."""
import asyncio
import json
import groq
import httpx
import pytest
from pydantic import SecretStr
from conftest import register, login, csrf_headers
from app.agents.providers import Providers, ProviderError

MODEL = 'openai/gpt-oss-20b'


def install(monkeypatch, handler):
    real = groq.AsyncGroq
    def factory(**kw):
        kw['http_client'] = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
        return real(**kw)
    monkeypatch.setattr(groq, 'AsyncGroq', factory)


def response(content='Mocked Groq reply', calls=None):
    return httpx.Response(200, json={'choices':[{'message':{'role':'assistant', 'content':content,
                  'reasoning':'hidden reasoning must not be returned', 'tool_calls':calls}}]})


@pytest.mark.parametrize('status,code,expected', [
    (401,None,'credentials'), (403,None,'denied access'), (404,None,'API endpoint'),
    (404,'model_not_found','saved conversation model'), (400,'model_decommissioned','saved conversation model'),
    (400,'invalid_request_error','format or parameters'), (422,None,'format or parameters'),
    (400,'tool_use_failed','valid tool call'), (429,None,'rate limit'), (500,None,'service error'),
])
def test_safe_error_classification(settings, monkeypatch, status, code, expected):
    settings.groq_api_key = SecretStr('synthetic-sdk-test-key')
    install(monkeypatch, lambda req: httpx.Response(status, json={'error':{'code':code,'message':'PRIVATE CODE AND SECRET'}}))
    with pytest.raises(ProviderError, match=expected) as error:
        asyncio.run(Providers(settings).complete('groq', MODEL, [{'role':'user','content':'hello'}], ['calculator']))
    assert 'PRIVATE' not in str(error.value)


@pytest.mark.parametrize('failure', ['network','timeout','malformed'])
def test_provider_transport_and_response_errors(settings,monkeypatch,failure):
    settings.groq_api_key = SecretStr('synthetic-sdk-test-key')
    def handler(request):
        if failure == 'network': raise httpx.ConnectError('private',request=request)
        if failure == 'timeout': raise httpx.ReadTimeout('private',request=request)
        return httpx.Response(200,json={'choices': []})
    install(monkeypatch,handler)
    with pytest.raises(ProviderError,match={'network':'unreachable','timeout':'timed out','malformed':'invalid'}[failure]):
        asyncio.run(Providers(settings).complete('groq',MODEL,[],[]))


def test_sdk_uses_official_path_namespaced_model_and_scoped_tools(settings,monkeypatch):
    settings.groq_api_key = SecretStr('synthetic-sdk-test-key')
    monkeypatch.setenv('GROQ_BASE_URL','https://untrusted.invalid')
    seen=[]
    def handler(request):
        assert str(request.url) == 'https://api.groq.com/openai/v1/chat/completions'
        assert request.method == 'POST'
        data=json.loads(request.content)
        assert data['model'] == MODEL
        assert [t['function']['name'] for t in data['tools']] == ['calculator']
        seen.append(data)
        return response()
    install(monkeypatch,handler)
    reply=asyncio.run(Providers(settings).complete('groq',MODEL,[{'role':'user','content':'Hello'}],['calculator']))
    assert reply.content == 'Mocked Groq reply' and len(seen)==1
    assert 'reasoning' not in reply.model_dump()


def test_authenticated_agent_path_persistence_tool_roundtrip_and_failure_recovery(client,monkeypatch):
    register(client);login(client)
    s=client.app.state.settings
    s.groq_model=MODEL;s.groq_api_key=SecretStr('synthetic-sdk-test-key')
    seen=[]
    def handler(request):
        assert request.url.path == '/openai/v1/chat/completions'
        data=json.loads(request.content);seen.append(data)
        assert data['model']==MODEL
        latest=data['messages'][-1]
        if latest['content']=='provider error fixture':
            return httpx.Response(400,json={'error':{'code':'invalid_request_error','message':'PRIVATE'}})
        if latest['role']=='user' and latest['content'].startswith('Calculate'):
            return response('',[{'id':'call_fixture','type':'function','function':{'name':'calculator','arguments':'{"text":"(12+8)/2"}'}}])
        if latest['role']=='tool': return response('Mocked result: 10.')
        return response('Mocked response for '+latest['content'])
    install(monkeypatch,handler)
    sid=client.post('/api/agent/sessions',headers=csrf_headers(client),json={'provider':'groq','model':MODEL,'allowed_tools':['calculator']}).json()['id']
    for prompt in ('Hello! Reply with one sentence.', 'What is 12 + 8?', 'Calculate (12 + 8) / 2 using the calculator.', 'Why should tools have least privilege?'):
        result=client.post(f'/api/agent/sessions/{sid}/messages',headers=csrf_headers(client),json={'content':prompt})
        assert result.status_code==200 and result.json()['status']=='completed'
    assert any(m['role']=='tool' for call in seen for m in call['messages'])
    # Saved sessions retain their model; changing deployment defaults never rewrites them.
    s.groq_model = 'new-deployment-default'
    failed=client.post(f'/api/agent/sessions/{sid}/messages',headers=csrf_headers(client),json={'content':'provider error fixture'}).json()
    assert failed['status']=='failed' and 'format or parameters' in failed['assistant_content']
    assert 'PRIVATE' not in str(failed)
    # A failed turn releases the session lease and doesn't erase earlier messages.
    again=client.post(f'/api/agent/sessions/{sid}/messages',headers=csrf_headers(client),json={'content':'hello again'}).json()
    assert again['status']=='completed'
    history=client.get(f'/api/agent/sessions/{sid}/messages').json()
    assert len(history['messages'])==6
    assert history['session']['model']==MODEL


def test_failed_retrieve_does_not_block_working_chat(settings, monkeypatch):
    settings.groq_api_key = SecretStr('synthetic-sdk-test-key')
    real = groq.AsyncGroq
    calls = []
    def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == 'GET':
            return httpx.Response(404, json={'error':{'message':'not found'}})
        assert request.url.path == '/openai/v1/chat/completions'
        return response('Working chat endpoint')
    async def reproduce_legacy_lookup():
        async with real(api_key='synthetic-sdk-test-key', base_url='https://api.groq.com',
                        max_retries=0, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))) as sdk:
            with pytest.raises(groq.NotFoundError):
                await sdk.models.retrieve(MODEL)
    asyncio.run(reproduce_legacy_lookup())
    install(monkeypatch, handler)
    result = asyncio.run(Providers(settings).complete('groq', MODEL, [{'role':'user','content':'hello'}], ['calculator']))
    assert result.content == 'Working chat endpoint'
    assert [method for method, _ in calls] == ['GET', 'POST']
