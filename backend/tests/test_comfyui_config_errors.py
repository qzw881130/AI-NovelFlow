"""Canonical product endpoint, no fallback transport, structured task errors."""
import asyncio
import errno
import json
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock
import httpx
import pytest
from app.core import config
from app.models.system_config import SystemConfig
from app.models.task import Task
from app.services.comfyui.client import ComfyUIClient
from app.services.comfyui.service import ComfyUIService
from app.services.comfyui.errors import persist_task_comfyui_error, task_comfyui_error
from app.services.task_service import TaskService
from test_video_reference_phase1 import assets, fixture as clip_fixture

@pytest.fixture(autouse=True)
def isolated_runtime(monkeypatch):
    monkeypatch.setattr(config, '_settings_instance', config.Settings())
    monkeypatch.setattr(config, '_comfyui_configured_url', None)
    monkeypatch.setattr(httpx.AsyncClient, 'post', AsyncMock(side_effect=AssertionError('REAL HTTP FORBIDDEN')))
    monkeypatch.setattr(httpx.AsyncClient, 'get', AsyncMock(side_effect=AssertionError('REAL HTTP FORBIDDEN')))

def configure(db, endpoint='http://192.168.50.1:8288'):
    db.add(SystemConfig(id='default', comfyui_host=endpoint, comfyui_timeout=321))
    db.commit()

class HTTP:
    def __init__(self, outcomes):
        self.outcomes, self.requests = list(outcomes), []
    async def __aenter__(self): return self
    async def __aexit__(self, *_): pass
    async def post(self, url, **kwargs):
        file = kwargs.get('files', {}).get('image')
        self.requests.append((url, (file[0], file[1].read(), file[2]) if file else kwargs.get('json'), kwargs.get('data'), kwargs['timeout']))
        result = self.outcomes.pop(0)
        if isinstance(result, Exception): raise result
        return result
    async def get(self, *_args, **_kwargs): return self.outcomes.pop(0)

def test_backend_worker_and_evidence_share_canonical_loader(db_session):
    configure(db_session)
    config.reload_settings_from_db({'comfyui_host': 'http://192.168.50.1:8288'})
    backend = ComfyUIClient()
    assert backend.base_url == 'http://192.168.50.1:8288'
    config._comfyui_configured_url = None
    config.get_settings().COMFYUI_HOST = 'http://127.0.0.1:8188'
    worker = ComfyUIService(db=db_session)
    assert worker.base_url == backend.base_url == 'http://192.168.50.1:8288'
    config._comfyui_configured_url = None
    config.get_settings().COMFYUI_HOST = 'http://127.0.0.1:8188'
    evidence = ComfyUIClient.for_product_runtime(db_session)
    assert evidence.base_url == 'http://192.168.50.1:8288'
    assert config.comfyui_runtime_configuration() == {'configured_url': evidence.base_url, 'effective_url': evidence.base_url, 'initialized': True}
    assert config.get_settings().COMFYUI_TIMEOUT == 321
    assert db_session.query(SystemConfig).count() == 1
    assert not db_session.dirty

@pytest.mark.parametrize('endpoint', ['http://127.0.0.1:8188', 'http://localhost:8188'])
def test_explicit_product_localhost_is_valid(db_session, endpoint):
    configure(db_session, endpoint)
    client = ComfyUIClient.for_product_runtime(db_session)
    assert client.base_url == endpoint
    assert client._configuration_failure('ASSET_UPLOAD') is None

def test_explicit_standalone_default_and_override():
    config.reload_settings_from_db({'comfyui_host': 'http://product.test:8288'})
    for endpoint in [None, 'http://localhost:8188']:
        client = ComfyUIClient(runtime_mode='standalone', base_url=endpoint)
        assert client.base_url == (endpoint or 'http://127.0.0.1:8188')
        assert client._configuration_failure('ASSET_UPLOAD') is None
    with pytest.raises(ValueError): ComfyUIClient(base_url='http://wrong.test')
    with pytest.raises(ValueError): ComfyUIClient(runtime_mode='implicit')

@pytest.mark.parametrize('initialized', [True, False])
def test_independent_executor_initializes_before_script(monkeypatch, initialized):
    spec = importlib.util.spec_from_file_location('product_bootstrap', Path(__file__).parents[1] / 'scripts/run_with_product_config.py')
    bootstrap = importlib.util.module_from_spec(spec); spec.loader.exec_module(bootstrap)
    calls = []
    def initialize():
        calls.append('initialize')
        if not initialized:
            raise RuntimeError('COMFYUI_CONFIG_NOT_INITIALIZED')
    monkeypatch.setattr(config, 'initialize_product_comfyui_config', initialize)
    monkeypatch.setattr(bootstrap.sys, 'argv', ['bootstrap', '/evidence.py', 'argument'])
    monkeypatch.setattr(bootstrap.runpy, 'run_path', lambda script, **kwargs: calls.append((script, kwargs, list(bootstrap.sys.argv))))
    if initialized:
        bootstrap.main()
        assert calls == ['initialize', ('/evidence.py', {'run_name': '__main__'}, ['/evidence.py', 'argument'])]
    else:
        with pytest.raises(RuntimeError, match='COMFYUI_CONFIG_NOT_INITIALIZED'): bootstrap.main()
        assert calls == ['initialize']

@pytest.mark.asyncio
async def test_uninitialized_product_never_uploads_submits_or_retries(tmp_path, monkeypatch):
    asset = tmp_path / 'previous.mp4'; asset.write_bytes(b'unchanged input')
    client = ComfyUIClient(); transport = HTTP([httpx.Response(502)])
    monkeypatch.setattr(client, '_client', lambda: transport)
    sleep = AsyncMock(); monkeypatch.setattr(asyncio, 'sleep', sleep)
    for result in [await client.upload_video(str(asset)), await client.upload_image(str(asset)), await client.queue_prompt({})]:
        error = result['comfyui_error']
        assert error['error_code'] == 'COMFYUI_CONFIG_NOT_INITIALIZED'
        assert error['attempts'] == 0 and error['prompt_submitted'] is False
        assert error['effective_url'] == 'http://127.0.0.1:8188'
        assert 'configured_url' not in error
    assert not transport.requests; sleep.assert_not_awaited()

@pytest.mark.asyncio
async def test_missing_row_fails_without_creating_config_or_http(db_session, tmp_path):
    service = ComfyUIService(db=db_session)
    path = tmp_path / 'asset.mp4'; path.write_bytes(b'asset')
    result = await service.client.upload_video(str(path))
    assert result['comfyui_error']['error_code'] == 'COMFYUI_CONFIG_NOT_INITIALIZED'
    assert result['comfyui_error']['attempts'] == 0
    assert db_session.query(SystemConfig).count() == 0
    httpx.AsyncClient.post.assert_not_awaited()
    configure(db_session); config.initialize_product_comfyui_config(db_session)
    assert service.client._configuration_failure('ASSET_UPLOAD') is None

@pytest.mark.asyncio
async def test_mismatch_is_observable_without_http(tmp_path):
    config.reload_settings_from_db({'comfyui_host': 'http://canonical.test:8288'})
    config.get_settings().COMFYUI_HOST = 'http://127.0.0.1:8188'
    path = tmp_path / 'asset.mp4'; path.write_bytes(b'asset')
    error = (await ComfyUIClient().upload_video(str(path)))['comfyui_error']
    assert error['error_code'] == 'COMFYUI_CONFIG_MISMATCH'
    assert error['configured_url'] == 'http://canonical.test:8288'
    assert error['effective_url'] == 'http://127.0.0.1:8188'
    assert error['attempts'] == 0
    httpx.AsyncClient.post.assert_not_awaited()

@pytest.mark.asyncio
@pytest.mark.parametrize('kind,code,cause', [
    ('refused', 'COMFYUI_CONNECTION_FAILED', 'Connection refused'),
    ('proxy_502_with_cause', 'COMFYUI_CONNECTION_FAILED', 'Connection refused'),
    ('remote_502', 'COMFYUI_HTTP_ERROR', 'Upstream service temporarily unavailable'),
    ('empty_502', 'COMFYUI_HTTP_ERROR', 'HTTP 502 (empty response body)'),
])
async def test_upload_error_classification_and_attempts(kind, code, cause, tmp_path, monkeypatch):
    asset = tmp_path / 'previous.mp4'; asset.write_bytes(b'identical payload')
    client = ComfyUIClient(runtime_mode='standalone', base_url='http://comfy.test:8288')
    if kind == 'refused':
        failure = httpx.ConnectError('All connection attempts failed')
        failure.__cause__ = ConnectionRefusedError(errno.ECONNREFUSED, 'Connection refused')
    elif kind == 'proxy_502_with_cause': failure = httpx.Response(502, json={'error': {'message': cause}})
    elif kind == 'remote_502': failure = httpx.Response(502, json={'error': {'message': cause}})
    else: failure = httpx.Response(502, content=b'')
    transport = HTTP([failure] * 4); monkeypatch.setattr(client, '_client', lambda: transport)
    sleep = AsyncMock(); monkeypatch.setattr(asyncio, 'sleep', sleep)
    result = await client.upload_video(str(asset)); error = result['comfyui_error']
    assert error['error_code'] == code and cause in error['underlying_error']
    assert error['http_status'] == (None if kind == 'refused' else 502)
    assert error['attempts'] == 4 and error['prompt_submitted'] is False
    assert [c.args[0] for c in sleep.await_args_list] == [2, 4, 8]
    assert all(request == transport.requests[0] for request in transport.requests)

@pytest.mark.asyncio
async def test_502_recovers_same_upload_then_single_submission(tmp_path, monkeypatch):
    asset = tmp_path / 'asset.mp4'; asset.write_bytes(b'payload')
    client = ComfyUIClient(runtime_mode='standalone')
    transport = HTTP([httpx.Response(502), httpx.Response(200, json={'name': 'asset.mp4'}), httpx.Response(200, json={'prompt_id': 'once'})])
    monkeypatch.setattr(client, '_client', lambda: transport); monkeypatch.setattr(asyncio, 'sleep', AsyncMock())
    result = await client.upload_video(str(asset))
    assert result['success'] and result['upload_attempts'] == 2 and 'comfyui_error' not in result
    assert (await client.queue_prompt({'node': 'unchanged'}))['prompt_id'] == 'once'
    assert [x[0].rsplit('/', 1)[-1] for x in transport.requests] == ['image', 'image', 'prompt']

@pytest.mark.asyncio
async def test_upload_stage_task_persistence_and_list_detail(db_session, tmp_path, monkeypatch):
    configure(db_session); service = ComfyUIService(db=db_session)
    asset = tmp_path / 'previous.mp4'; asset.write_bytes(b'video')
    transport = HTTP([httpx.Response(502, json={'error': 'Connection refused'})] * 4)
    monkeypatch.setattr(service.client, '_client', lambda: transport); monkeypatch.setattr(asyncio, 'sleep', AsyncMock())
    queue = AsyncMock(); monkeypatch.setattr(service.client, 'queue_prompt', queue)
    result = await service.generate_video_continuation_with_workflow('fixed H3', '{}', {}, str(asset), 11.1, 'unchanged', capability='TEMPORAL_EXTEND')
    assert result['comfyui_error']['stage'] == 'PREVIOUS_AV_UPLOAD'
    assert result['comfyui_error']['prompt_submitted'] is False; queue.assert_not_awaited()
    task = Task(id='test-task', name='C2', type='shot_video', status='failed', progress=30,
                metadata_json=json.dumps({'execution_scope': 'CLIP', 'clip_index': 2, 'physical_output': {'sha256': 'preserve'}}))
    persist_task_comfyui_error(task, result); db_session.add(task); db_session.commit(); db_session.expire_all()
    saved = db_session.query(Task).filter_by(id='test-task').one()
    assert json.loads(saved.metadata_json)['physical_output'] == {'sha256': 'preserve'}
    listed = TaskService.format_task_list([saved], {}, {}, {})[0]
    assert listed['comfyuiError'] == TaskService.format_task_detail(saved)['comfyuiError'] == result['comfyui_error']

def test_formal_clip_worker_persists_structured_failure(db_session, assets, monkeypatch):
    from app.api import shots as api
    from app.models.workflow import Workflow
    from app.repositories import NovelRepository, ChapterRepository, TaskRepository, ShotRepository
    from app.services import shot_video_service as worker
    shot, plan, clip = clip_fixture(assets)
    db_session.add_all([shot, Workflow(id='g', name='Mock', type='multi_reference_video', workflow_json='{}', node_mapping='{}', is_active=True)])
    db_session.commit()
    captured = {}
    monkeypatch.setattr(api.TaskService, 'validate_workflow_node_mapping', lambda *_: (True, ''))
    monkeypatch.setattr(api, 'enqueue_shot_video_task', lambda *args, **kwargs: captured.update(args=args, kwargs=kwargs))
    response = asyncio.run(api._execute_phase_b_semantic_clip(
        'n', 'ch', 's', clip['clip_index'], api.SemanticClipGenerateRequest(clip_plan_revision=1, auto_merge=False),
        db_session, NovelRepository(db_session), ChapterRepository(db_session), TaskRepository(db_session), ShotRepository(db_session)))
    assert response['success']
    diagnostic = {'error_code': 'COMFYUI_CONNECTION_FAILED', 'stage': 'ORDINARY_REFERENCE_UPLOAD',
                  'effective_url': 'http://comfy.test:8288', 'underlying_error': 'Connection refused',
                  'http_status': None, 'attempts': 4, 'prompt_submitted': False}
    class MockComfy:
        async def generate_shot_video_with_workflow(self, **kwargs):
            return {'success': False, 'message': 'transport failure', 'comfyui_error': diagnostic}
    monkeypatch.setattr(worker, 'ComfyUIService', MockComfy)
    monkeypatch.setattr(worker, 'build_h3_video_prompt', AsyncMock(return_value='mock H3'))
    monkeypatch.setattr(worker, 'SessionLocal', lambda: db_session)
    monkeypatch.setattr(db_session, 'close', lambda: None)
    asyncio.run(worker.generate_shot_video_task(*captured['args'], **captured['kwargs']))
    db_session.expire_all()
    task = db_session.query(Task).filter_by(id=captured['args'][0]).one()
    assert task.status == 'failed' and task.comfyui_prompt_id is None
    assert TaskService.format_task_detail(task)['comfyuiError'] == diagnostic
    assert TaskService.format_task_list([task], {}, {}, {})[0]['comfyuiError'] == diagnostic
    assert json.loads(task.metadata_json)['clip_plan_revision'] == plan['clip_plan_revision']

def test_retry_clears_previous_attempt_diagnostic_without_losing_metadata(db_session, assets, monkeypatch):
    from app.services import scene_service
    task = Task(id='retry-scene', name='Scene', type='scene_image', status='failed', scene_id='room-id',
                metadata_json=json.dumps({'preserved': 'authority', 'comfyui_error': {'error_code': 'COMFYUI_UPLOAD_FAILED'}}))
    db_session.add(task); db_session.commit()
    enqueue = []
    monkeypatch.setattr(scene_service, 'enqueue_scene_image_task', lambda *args: enqueue.append(args))
    assert TaskService(db_session).retry_task(task.id)['success']
    assert len(enqueue) == 1
    assert json.loads(task.metadata_json) == {'preserved': 'authority'}
    assert TaskService.format_task_detail(task)['comfyuiError'] is None

def test_config_loader_does_not_flush_other_pending_product_changes(db_session):
    configure(db_session)
    from app.models.novel import Novel
    pending = Novel(id='not-persisted', title='Pending unrelated write')
    db_session.add(pending)
    config.initialize_product_comfyui_config(db_session)
    assert pending in db_session.new
    with db_session.no_autoflush:
        assert db_session.query(Novel).filter_by(id='not-persisted').first() is None

@pytest.mark.asyncio
async def test_submission_failure_without_repeated_submission(monkeypatch):
    client = ComfyUIClient(runtime_mode='standalone'); transport = HTTP([httpx.Response(400, json={'error': 'invalid workflow'})])
    monkeypatch.setattr(client, '_client', lambda: transport)
    error = (await client.queue_prompt({}))['comfyui_error']
    assert error['error_code'] == 'COMFYUI_PROMPT_SUBMIT_FAILED' and error['stage'] == 'PROMPT_SUBMIT'
    assert error['attempts'] == 1 and error['prompt_submitted'] is False and len(transport.requests) == 1

@pytest.mark.asyncio
async def test_execution_failure_retains_submitted_true(monkeypatch):
    client = ComfyUIClient(runtime_mode='standalone')
    transport = HTTP([httpx.Response(200, json={'submitted': {'status': {'status_str': 'error', 'messages': [['execution_error', {'exception_message': 'node execution failed'}]]}}})])
    monkeypatch.setattr(client, '_client', lambda: transport)
    error = (await client.wait_for_result('submitted', {}))['comfyui_error']
    assert error['error_code'] == 'COMFYUI_EXECUTION_FAILED' and error['prompt_submitted'] is True and error['attempts'] == 1

def test_diagnostics_do_not_expose_credentials():
    task = Task(metadata_json=json.dumps({'comfyui_error': {'error_code': 'COMFYUI_CONNECTION_FAILED', 'stage': 'PREVIOUS_AV_UPLOAD',
        'effective_url': 'http://user:secret@comfy.test:8188/upload/image?token=secret', 'configured_url': 'http://user:secret@comfy.test:8188',
        'underlying_error': 'token=secret', 'http_status': 502, 'attempts': 4, 'prompt_submitted': False, 'proxy': 'http://user:secret@proxy.test:7897'}}))
    result = task_comfyui_error(task)
    assert 'secret' not in json.dumps(result)
    assert result['effective_url'] == 'http://comfy.test:8188/upload/image'
