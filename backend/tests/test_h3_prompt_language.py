"""Language intent uses isolated SQLite and fake execution only."""
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.models.system_config import SystemConfig
from app.models.task import Task
from app.services.h3_prompt_language import new_task_language, task_language
from app.services import h3_single_stage_experiment as compiler, h3_phase_b_pipeline as pipe
from app.services.h3_native_prompt import sections, dialogue_events
from test_h3_phase_b_pipeline import saved, NAMES, FakeDirector, make_case, offline_only
from h3_language_fakes import language_response
from test_persistent_shot_video_retry import setup_retry, install_handler, drained


def test_config_defaults_save_and_validate(client, db_session):
    assert client.get('/api/config/').json()['data']['videoPromptLanguage'] == 'en'
    for language in ['zh', 'en']:
        assert client.post('/api/config/', json={'videoPromptLanguage': language}).status_code == 200
        assert client.get('/api/config/').json()['data']['videoPromptLanguage'] == language
        assert new_task_language(db_session) == language
    assert client.post('/api/config/', json={'videoPromptLanguage': 'auto'}).status_code == 422
    assert new_task_language(db_session) == 'en'


def test_historical_language_is_not_new_default(db_session):
    assert task_language({}) is None
    assert new_task_language(db_session) == 'en'
    config = SystemConfig(id='default', video_prompt_language='zh')
    db_session.add(config); db_session.commit()
    assert new_task_language(db_session) == 'zh'
    assert new_task_language(db_session, 'en') == 'en'
    assert task_language({'video_prompt_language': 'en'}) == 'en'
    assert task_language({}) is None
    with pytest.raises(ValueError, match='H3_PROMPT_LANGUAGE_INVALID'):
        task_language({'video_prompt_language': 'fr'})


@pytest.mark.parametrize('entry', ['batch', 'auto'])
@pytest.mark.parametrize('language', ['en', 'zh'])
def test_batch_creation_freezes_language(client, db_session, monkeypatch, entry, language):
    from app.api import shots as api
    from test_semantic_batch_scheduler import _fixture
    novel, chapter, shot, parent, child = _fixture(db_session, capabilities=('GENERATE',))
    db_session.delete(parent); db_session.delete(child); db_session.commit()
    client.post('/api/config/', json={'videoPromptLanguage': language})
    monkeypatch.setattr(api, 'enqueue_shot_video_batch_task', lambda _: None)
    url = f'/api/novels/{novel.id}/chapters/{chapter.id}/'
    body = {}
    if entry == 'batch':
        url += 'shot-videos/batch'; body['shot_ids'] = [shot.id]
    else:
        url += f'shots/{shot.id}/auto-generation/start'
    response = client.post(url, json=body)
    assert response.status_code == 200, response.text
    tasks = db_session.query(Task).all()
    assert len(tasks) == 2
    assert all(task_language(json.loads(t.metadata_json)) == language for t in tasks)
    client.post('/api/config/', json={'videoPromptLanguage': 'zh' if language == 'en' else 'en'})
    assert all(task_language(json.loads(t.metadata_json)) == language for t in tasks)


@pytest.fixture(scope='module')
def language_cases():
    cases = {}
    for name in NAMES:
        for language in ['en', 'zh']:
            snap = saved(name)
            snap['video_prompt_language'] = language
            snap['source']['hashes']['video_prompt_language'] = compiler._snapshot_digest(language)
            prepared = compiler.prepare_multi_keyframe_phase_b(snap)
            assert prepared['status'] == 'PREPARED', prepared
            cases[name, language] = prepared
    return cases


@pytest.mark.parametrize('name', NAMES)
@pytest.mark.parametrize('language', ['en', 'zh'])
def test_bilingual_prepare_compile_preflight(language_cases, name, language):
    prepared = language_cases[name, language]
    original = saved(name, '_mock_response')
    response = language_response(prepared['llm_input'], original)
    before = deepcopy(prepared)
    result = compiler.compile_multi_keyframe_phase_b(prepared, response)
    assert result['status'] == 'CANDIDATE_FOR_REVIEW', result
    assert pipe.preflight(prepared, result)['passed'], result
    assert prepared == before
    historical = compiler.compile_multi_keyframe_phase_b(compiler.prepare_multi_keyframe_phase_b(saved(name)), original)
    assert result['reference_manifest'] == historical['reference_manifest']
    assert result['temporal_manifest'] == historical['temporal_manifest']
    assert result['execution_decisions'] == historical['execution_decisions']
    assert [(d['speaker'], d['speaker_id'], d['exact_dialogue'], d['speech_lead']) for d in dialogue_events(result['prompt'])] == [
        (d['speaker'], d['speaker_id'], d['exact_dialogue'], d['speech_lead']) for d in dialogue_events(historical['prompt'])]
    assert sections(result['prompt'])['detailed_description'].startswith('<Subject 1>')
    if language == 'en':
        from app.services.h3_prompt_language import validate_english_prose
        text = result['prompt']
        for event in prepared['canonical']:
            text = text.replace(event['exact_dialogue'], '')
        validate_english_prose(text, prepared['subject_names'].values())
    else:
        assert '稳定身份仅绑定到' in result['prompt']
        assert '时长 ' in sections(result['prompt'])['summary']
        assert '仅用于环境外观' in result['prompt']


@pytest.mark.parametrize('damage', ['missing', 'extra', 'binding', 'dialogue', 'wrong_language'])
def test_invalid_localization_rejected(language_cases, damage):
    prepared = language_cases[NAMES[0], 'en']
    response = language_response(prepared['llm_input'], saved(NAMES[0], '_mock_response'))
    key = next(iter(response['localized_descriptions']))
    if damage == 'missing': del response['localized_descriptions'][key]
    elif damage == 'extra': response['localized_descriptions']['invented'] = 'Anything'
    elif damage == 'binding': response['localized_descriptions'][key] = '<Subject 99> is someone'
    elif damage == 'dialogue': response['localized_descriptions'][key] = '<d>[Chinese] 新台词</d>'
    else: response['overall_soundscape'] = '中文环境音'
    result = compiler.compile_multi_keyframe_phase_b(prepared, response)
    assert result['status'] == 'VALIDATION_FAILED', result


def test_language_cache_isolation(language_cases):
    template = SimpleNamespace(id='template', template=compiler.PHASE_B_TEMPLATE.read_text())
    fingerprints = {pipe.input_fingerprint(language_cases[NAMES[0], lang], template) for lang in ['en', 'zh']}
    fingerprints.add(pipe.input_fingerprint(compiler.prepare_multi_keyframe_phase_b(saved(NAMES[0])), template))
    assert len(fingerprints) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize('language', [None, 'en', 'zh'])
async def test_formal_pipeline_uses_frozen_language_and_one_call(db_session, language):
    snap, args, selected = make_case(db_session, NAMES[0])
    task = args['task']
    metadata = json.loads(task.metadata_json)
    if language is not None:
        metadata['video_prompt_language'] = language
    task.metadata_json = json.dumps(metadata); db_session.commit()
    class Director(FakeDirector):
        async def chat_completion(self, **kwargs):
            self.content = saved(NAMES[0], '_mock_response')
            if language is not None:
                self.content = language_response(json.loads(kwargs['user_content']), self.content)
            return await super().chat_completion(**kwargs)
    llm = Director({})
    await pipe.build_phase_b_prompt(**args, llm=llm)
    record = json.loads(task.metadata_json)['h3_phase_b']
    assert len(llm.calls) == 1
    # The selected template is the complete System Prompt, including for a
    # novel's custom template. Language is input data, never a hidden suffix.
    assert llm.calls[0]['system_prompt'] == selected.template
    assert 'H3_PROMPT_LANGUAGE_V1' in llm.calls[0]['system_prompt']
    assert record.get('video_prompt_language') == language
    assert record['status'] == 'COMPILED' and record['preflight']['passed']
    assert record['director_input'].get('video_prompt_language') == language
    wire = json.loads(llm.calls[0]['user_content'])
    assert wire.get('video_prompt_language') == language
    parsed = record['compiler_result']['director_response']
    assert ('localized_descriptions' in parsed) == (language is not None)
    if language is not None:
        assert record['effective_system_prompt'] == selected.template
        assert record['effective_system_prompt_sha256'] == pipe.digest(selected.template)
        assert set(parsed['localized_descriptions']) == set(wire['compiler_description_sources'])
    else:
        assert 'video_prompt_language' not in wire
    metadata = json.loads(task.metadata_json); metadata['skip_llm_when_prompt_exists'] = True
    task.metadata_json = json.dumps(metadata); db_session.commit()
    first = task.prompt_text
    await pipe.build_phase_b_prompt(**args, llm=llm)
    assert len(llm.calls) == 1 and task.prompt_text == first


@pytest.mark.asyncio
@pytest.mark.parametrize('language', [None, 'en', 'zh'])
async def test_isolated_preview_uses_same_template_with_language_as_input(language):
    snapshot = saved(NAMES[0])
    if language is not None:
        snapshot['video_prompt_language'] = language
        snapshot['source']['hashes']['video_prompt_language'] = compiler._snapshot_digest(language)

    class Director(FakeDirector):
        max_retries = 0

        async def chat_completion(self, **kwargs):
            self.content = saved(NAMES[0], '_mock_response')
            if language is not None:
                self.content = language_response(json.loads(kwargs['user_content']), self.content)
            return await super().chat_completion(**kwargs)

    llm = Director({})
    result = await compiler.preview_multi_keyframe_phase_b(snapshot, llm=llm)
    assert result['status'] == 'CANDIDATE_FOR_REVIEW', result
    assert len(llm.calls) == 1
    assert llm.calls[0]['system_prompt'] == compiler.PHASE_B_TEMPLATE.read_text()
    assert json.loads(llm.calls[0]['user_content']).get('video_prompt_language') == language
    assert ('localized_descriptions' in result['director_response']) == (language is not None)


@pytest.mark.parametrize('shot_number', [1, 2, 18])
@pytest.mark.parametrize('silent', [False, True])
@pytest.mark.parametrize('language', ['en', 'zh'])
def test_real_single_and_zero_owned_language(db_session, shot_number, silent, language):
    from test_h3_phase_b_single_owned_state import make_case as single_case, mock_decisions
    from test_h3_phase_b_zero_owned_state import make_case as carry_case, mock_response
    if shot_number == 18:
        _, snapshot, _ = carry_case(db_session, silent=silent)
    else:
        _, snapshot, _ = single_case(db_session, shot_number, silent=silent)
    snapshot['video_prompt_language'] = language
    snapshot['source']['hashes']['video_prompt_language'] = compiler._snapshot_digest(language)
    prepared = compiler.prepare_multi_keyframe_phase_b(snapshot, runtime=True)
    assert prepared['status'] == 'PREPARED', prepared
    response = mock_response(prepared) if shot_number == 18 else mock_decisions(prepared)
    response = language_response(prepared['llm_input'], response)
    result = compiler.compile_multi_keyframe_phase_b(prepared, response)
    assert result['status'] == 'CANDIDATE_FOR_REVIEW', result
    assert pipe.preflight(prepared, result)['passed']
    if silent:
        assert '<d>' not in result['prompt']
        assert ('no speech, narration or additional vocalization' if language == 'en'
                else '不得新增说话、旁白或额外人声') in result['prompt']


@pytest.mark.asyncio
@pytest.mark.parametrize('language', [None, 'en', 'zh'])
@pytest.mark.parametrize('action', ['retry', 'restore'])
async def test_persisted_language_survives_retry_and_restore(setup_retry, db_session, db_engine, monkeypatch, language, action):
    from sqlalchemy.orm import sessionmaker
    from app.models.background_job import BackgroundJob
    from app.services.background_workers import WorkerManager
    from app.services import shot_video_service as video
    from app.services.task_service import TaskService
    manager, create = setup_retry
    task, shot, previous, artifact, args, options = create('EXTEND')
    metadata = json.loads(task.metadata_json)
    if language is not None:
        metadata['video_prompt_language'] = language
    task.metadata_json = json.dumps(metadata)
    options['clip_metadata'] = metadata
    db_session.add(SystemConfig(id='default', video_prompt_language='zh' if language == 'en' else 'en'))
    db_session.commit()
    calls = install_handler(monkeypatch, db_engine)
    try:
        video.enqueue_shot_video_task(*args, **options)
        await drained(manager); db_session.expire_all()
        if action == 'restore':
            monkeypatch.setattr(manager.worker('shot_video'), 'signal', lambda _: None)
        assert TaskService(db_session).retry_task(task.id)['success']
        if action == 'restore':
            restarted = WorkerManager(sessionmaker(bind=db_engine))
            try:
                assert restarted.resume_persisted() == 1
                await drained(restarted)
            finally:
                await restarted.stop()
        else:
            await drained(manager)
        assert len(calls) == 2
        for job in db_session.query(BackgroundJob):
            assert task_language(json.loads(job.payload_json)['clip_metadata']) == language
        assert task_language(json.loads(task.metadata_json)) == language
    finally:
        await manager.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize('language', [None, 'en', 'zh'])
async def test_batch_execution_uses_frozen_intent(db_session, monkeypatch, tmp_path, language):
    from app.api import shots as api
    from test_semantic_batch_scheduler import _fixture, _install_execution_fake
    _, _, shot, parent, child = _fixture(db_session)
    metadata = json.loads(child.metadata_json)
    if language:
        metadata['video_prompt_language'] = language
    child.metadata_json = json.dumps(metadata); db_session.commit()
    calls = []; _install_execution_fake(db_session, monkeypatch, tmp_path, calls)
    execute = api.execute_semantic_clip
    async def check(*args, **kwargs):
        assert kwargs['_frozen_prompt_language'] == language
        return await execute(*args, **kwargs)
    monkeypatch.setattr(api, 'execute_semantic_clip', check)
    assert await api._run_semantic_shot_for_batch(db_session, parent, child, shot) == 'completed'
    assert calls == [1, 2, 3]
