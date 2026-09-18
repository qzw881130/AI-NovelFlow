"""R2-A canonical/OpenAI boundary tests. Gemini is intentionally not exercised."""
import asyncio,base64,hashlib,json
from copy import deepcopy
from io import BytesIO
import httpx
import pytest
from PIL import Image
from app.services.llm.base import LLMConfig
from app.services.llm.client import LLMClient
from app.services.llm.providers import openai as provider_module
from app.services.llm.multimodal import MultimodalInputError, verify_logged_request
from types import SimpleNamespace


def image(color):
    stream=BytesIO();Image.new('RGB',(16,12),color).save(stream,format='PNG');return stream.getvalue()
def content():
    return [{'type':'text','text':'Compare in this order.'},
            {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(image('red')).decode()}},
            {'type':'text','text':'Second reference:'},
            {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(image('blue')).decode()}}]
def client(model='deepseek-v4-flash-vision-exp',provider='deepseek'):
    return LLMClient(LLMConfig(provider,model,'https://example.invalid/v1','not-a-real-key'))


def transport(monkeypatch):
    sent=[];logs=[]
    class Http:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def post(self,url,**kwargs):
            sent.append(deepcopy(kwargs['json']))
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"status":"READY"}'}}]},request=httpx.Request('POST',url))
    monkeypatch.setattr(provider_module.httpx,'AsyncClient',Http)
    monkeypatch.setattr(provider_module,'create_llm_log',lambda **kwargs:logs.append(kwargs) or 'log')
    monkeypatch.setattr('app.services.llm.base.update_llm_log',lambda *a,**k:None)
    return sent,logs


def test_ordered_images_reach_openai_wire_and_canonical_log_evidence(monkeypatch):
    sent,logs=transport(monkeypatch);parts=content();before=deepcopy(parts)
    result=asyncio.run(client().chat_completion('system',parts,response_format='json_object'))
    assert result['success'] and parts==before
    assert sent[0]['messages'][1]['content']==parts
    logged=json.loads(logs[0]['user_prompt'])
    assert [p['type'] for p in logged]==['text','image_url','text','image_url']
    for index in (1,3):
        raw=base64.b64decode(parts[index]['image_url']['url'].split(',',1)[1])
        assert logged[index]['image_evidence']['sha256']==hashlib.sha256(raw).hexdigest()
        assert logged[index]['image_evidence']['bytes']==len(raw)
        assert logged[index]['image_evidence']['mime_type']=='image/png'
    assert logs[0]['request_info']['multimodal']['contract']=='inline-images-v1'
    assert 'not-a-real-key' not in json.dumps(logs[0]['request_info'])
    log = SimpleNamespace(**{**logs[0], 'request_info': json.dumps(logs[0]['request_info'])})
    verify_logged_request(log, parts)
    # Redacted native payload alone cannot hide swapping actual image bytes.
    changed = deepcopy(parts)
    changed[1], changed[3] = changed[3], changed[1]
    with pytest.raises(MultimodalInputError):
        verify_logged_request(log, changed)


@pytest.mark.parametrize('bad',[
    [{'type':'image_url','image_url':{'url':'data:image/png;base64,bm90LWFuLWltYWdl'}}],
    [{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(image('red')).decode()}}],
    [{'type':'unsupported','text':'silently dropped?'}],
    [{'type':'image_url','image_url':{'url':'https://example.invalid/ref.png?token=private'}}],
    [{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(image('red')).decode(),'detail':{}}}],
])
def test_bad_image_or_part_fails_before_http_and_success_proof(monkeypatch,bad):
    sent,logs=transport(monkeypatch)
    result=asyncio.run(client().chat_completion('system',bad))
    assert not result['success'] and result['failure_kind']=='INPUT_ERROR'
    assert not sent
    assert not logs and result['llm_log_id'] is None


def test_text_only_model_has_explicit_multimodal_preflight(monkeypatch):
    sent,logs=transport(monkeypatch)
    result=asyncio.run(client(model='deepseek-v4-flash').chat_completion('system',content()))
    assert not result['success'] and 'MULTIMODAL_MODEL' in result['error']
    assert not sent


def test_string_input_remains_unchanged(monkeypatch):
    sent,logs=transport(monkeypatch);result=asyncio.run(client(model='deepseek-v4-flash').chat_completion('system','plain input'))
    assert result['success'];assert sent[0]['messages'][1]['content']=='plain input';assert logs[0]['user_prompt']=='plain input'


@pytest.mark.parametrize('provider', ['openai', 'azure', 'custom', 'aliyun-bailian'])
def test_compatible_deployment_requires_explicit_image_capability(monkeypatch, provider):
    sent, logs = transport(monkeypatch)
    config = LLMConfig(provider, 'private-deployment', 'https://example.invalid/v1', 'not-a-real-key')
    rejected = asyncio.run(LLMClient(config).chat_completion('system', content()))
    assert rejected['failure_kind'] == 'INPUT_ERROR' and not sent
    config.image_input = True
    accepted = asyncio.run(LLMClient(config).chat_completion('system', content()))
    assert accepted['success'] and sent[0]['messages'][1]['content'] == content()
    assert logs[0]['request_info']['multimodal']['model_capability']['declaration'] == 'EXPLICIT_PROCESS_CONFIGURATION'


@pytest.mark.parametrize('provider', ['anthropic', 'ollama'])
def test_unsupported_native_image_adapter_rejects_even_declared_model(monkeypatch, provider):
    sent, logs = transport(monkeypatch)
    config = LLMConfig(provider, 'vision-model', 'https://example.invalid/v1', 'not-a-real-key', image_input=True)
    rejected = asyncio.run(LLMClient(config).chat_completion('system', content()))
    assert rejected['failure_kind'] == 'INPUT_ERROR' and 'MULTIMODAL_PROVIDER' in rejected['error']
    assert not sent and not logs


def test_explicit_disable_and_text_parts(monkeypatch):
    sent, logs = transport(monkeypatch)
    config = LLMConfig('deepseek', 'deepseek-v4-flash-vision-exp', 'https://example.invalid/v1', '', image_input=False)
    assert asyncio.run(LLMClient(config).chat_completion('system', content()))['failure_kind'] == 'INPUT_ERROR'
    parts = [{'type': 'text', 'text': 'one'}, {'type': 'text', 'text': 'two'}]
    assert asyncio.run(LLMClient(config).chat_completion('system', parts))['success']
    assert len(sent) == 1 and sent[0]['messages'][1]['content'] == parts


def test_known_openai_profile_retains_image_wire(monkeypatch):
    sent, logs = transport(monkeypatch)
    result = asyncio.run(client(model='gpt-4o', provider='openai').chat_completion('system', content()))
    assert result['success'] and sent[0]['messages'][1]['content'] == content()
    assert logs[0]['request_info']['multimodal']['model_capability'] == {
        'supported': True, 'declaration': 'KNOWN_MODEL_PROFILE',
    }
