"""Phase8: real upstream receipts, legacy admission and explicit rebuild ownership."""
import asyncio
from copy import deepcopy
import json
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.novel import Chapter, Character, Scene, Prop
from app.models.shot import Shot
from app.models.task import Task
from app.models.workflow import Workflow
from app.models.llm_log import LLMLog
from app.models.audio_drive import ShotAudioEvent, AudioEventTTSAsset
from app.models.chapter_asset_parse import ChapterAssetCandidate
from app.models.chapter_governance import ChapterLifecycle, ChapterRebuildRun
from app.models.chapter_shot_split import ShotSource
from app.services.chapter_governance import pipeline_state, require_source
from app.services.chapter_rebuild_service import ChapterRebuildService, protection_snapshot
from app.services.chapter_governance_schema import upgrade
from app.services.audio_drive_service import AudioDriveService
from app.services import audio_drive_service as audio
from app.services import runtime_gate as gate
from app.services import shot_video_execution as video
from app.services.chapter_asset_parse_service import digest
from app.services.task_service import TaskService
from app.repositories import TaskRepository
from test_rsa_media import db_session, chapter, fixture, base_setup, setup, enqueue, run
from test_chapter_shot_split import output


def client(db):
    from app.api import shots, audio_drive, chapter_governance
    app = FastAPI()
    app.include_router(shots.router, prefix='/api/novels')
    app.include_router(audio_drive.router, prefix='/api')
    app.include_router(chapter_governance.router, prefix='/api/novels')
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_migration_distinguishes_new_and_legacy_without_backfilling(db_session, chapter):
    old = Shot(chapter_id=chapter.id, index=1, description='旧分镜', image_url='/old.png', dialogues='[{"text":"旧对白"}]')
    fresh = Chapter(novel_id=chapter.novel_id, number=2, title='新章', content='待解析')
    db_session.add_all([old, fresh]); db_session.commit()
    before = protection_snapshot(db_session, chapter.novel_id)
    upgrade(db_session.bind); upgrade(db_session.bind)
    assert pipeline_state(db_session, chapter.novel_id, chapter.id)['origin'] == 'LEGACY'
    assert pipeline_state(db_session, chapter.novel_id, fresh.id)['condition'] == 'NOT_PARSED'
    assert not db_session.query(ShotSource).count()
    assert not db_session.query(ChapterRebuildRun).count()
    result = client(db_session).get(f'/api/shots/{old.id}/audio-events')
    assert result.status_code == 200 and result.json()['data']['events'] == []
    assert not db_session.query(ShotAudioEvent).count()
    assert protection_snapshot(db_session, chapter.novel_id) == before


@pytest.mark.parametrize('endpoint,body,status', [
    ('/generate', {}, 409), ('/generate-video', {}, 409),
    ('/benchmark/generate', {}, 410), ('/keyframes/0/generate-image', {}, 409),
])
def test_legacy_image_video_entries_fail_before_generation(db_session, chapter, endpoint, body, status):
    old = Shot(chapter_id=chapter.id, index=1, description='legacy', image_url='/legacy.png')
    db_session.add(old); db_session.commit()
    root = f'/api/novels/{chapter.novel_id}/chapters/{chapter.id}/shots/{old.id}'
    response = client(db_session).post(root + endpoint, json=body)
    assert response.status_code == status, response.text
    assert not db_session.query(Task).count()


def test_audio_and_index_bypasses_are_closed(db_session, chapter):
    old = Shot(chapter_id=chapter.id, index=1, description='legacy')
    db_session.add(old); db_session.commit()
    c = client(db_session)
    for endpoint in ('audio/prepare', 'audio-timeline/build', 'video/execution-windows/build'):
        assert c.post(f'/api/shots/{old.id}/{endpoint}', json={}).status_code == 409
    response = c.post(f'/api/novels/{chapter.novel_id}/chapters/{chapter.id}/shots/1/generate', json={})
    assert response.status_code == 404


def voice(db, setup, monkeypatch):
    root = setup[4]
    (root / 'voice.wav').write_bytes(b'accepted voice profile')
    monkeypatch.setattr(audio, 'url_to_local_path', lambda url: str(root / url.removeprefix('/api/files/')) if url else None)
    setup[0].reference_audio_url = '/api/files/voice.wav'
    db.add(Workflow(type='audio', name='Existing Qwen3TTS', is_active=True, workflow_json='{}', node_mapping='{}'))
    db.commit()


def test_audio_uses_formal_source_without_requiring_visual_ready(db_session, chapter, setup, monkeypatch):
    voice(db_session, setup, monkeypatch)
    speaking = setup[3][1]  # Appearance has no image: deliberately visually BLOCKED.
    with pytest.raises(HTTPException): gate.require_rsa(db_session, speaking.id)
    event = db_session.query(ShotAudioEvent).one()
    response = AudioDriveService(db_session).create_tts_task(event.id)
    assert response['success']
    task = db_session.get(Task, response['data']['taskId'])
    inputs = json.loads(task.metadata_json)
    assert inputs['source_pin']['shot_id'] == speaking.id
    assert inputs['voice_binding']['character_id'] == setup[0].id
    assert 'rsa_id' not in inputs
    silent = setup[3][0]
    assert AudioDriveService(db_session).build_timeline(silent.id)['success']
    assert AudioDriveService(db_session).build_execution_windows(silent.id)['success']


def test_tts_worker_rechecks_source_before_any_remote_io(db_session, chapter, setup, monkeypatch):
    voice(db_session, setup, monkeypatch)
    event = db_session.query(ShotAudioEvent).one()
    tid = AudioDriveService(db_session).create_tts_task(event.id)['data']['taskId']
    task = TaskRepository(db_session).claim_pending_task('audio_event_tts', 'test-worker')
    token, wid = task.claim_token, task.workflow_id
    chapter.content += '用户修改原文'; db_session.commit()
    import app.core.database as database
    monkeypatch.setattr(database, 'SessionLocal', lambda: Session(db_session.bind, autoflush=False))
    monkeypatch.setattr(audio, 'ComfyUIService', lambda: pytest.fail('Source failure must precede network'))
    asyncio.run(AudioDriveService._run_tts_task(tid, event.id, wid, token))
    db_session.expire_all()
    assert db_session.get(Task, tid).status == 'failed'
    assert not db_session.query(AudioEventTTSAsset).count()


def test_voice_owner_without_stable_id_never_uses_same_name(db_session, setup, monkeypatch):
    voice(db_session, setup, monkeypatch)
    event = db_session.query(ShotAudioEvent).one()
    event.voice_owner_character_id = None; db_session.commit()
    with pytest.raises(HTTPException): AudioDriveService(db_session).create_tts_task(event.id)
    assert not db_session.query(Task).filter_by(type='audio_event_tts').count()


def test_audio_cancel_releases_event_for_explicit_new_attempt(db_session, setup, monkeypatch):
    voice(db_session, setup, monkeypatch)
    event = db_session.query(ShotAudioEvent).one()
    tid = AudioDriveService(db_session).create_tts_task(event.id)['data']['taskId']
    assert asyncio.run(TaskService(db_session).cancel_task(tid))['success']
    db_session.expire_all()
    assert event.tts_status == 'FAILED'
    response = AudioDriveService(db_session).create_batch_tts_tasks(event.shot_id)
    assert response['success'] and len(response['data']['tasks']) == 1
    assert response['data']['tasks'][0]['taskId'] != tid


def test_periodic_audio_recovery_settles_lost_lease_without_resubmission(db_session, setup, monkeypatch):
    voice(db_session, setup, monkeypatch)
    event = db_session.query(ShotAudioEvent).one()
    tid = AudioDriveService(db_session).create_tts_task(event.id)['data']['taskId']
    task = db_session.get(Task, tid)
    task.status, task.comfyui_prompt_id = 'running', 'original-submission'
    task.heartbeat_at = datetime.utcnow() - timedelta(minutes=3)
    db_session.commit()
    from app.core import database
    monkeypatch.setattr(database, 'SessionLocal', lambda: Session(db_session.bind, autoflush=False))
    monkeypatch.setattr(audio, 'ComfyUIService', lambda: pytest.fail('Interrupted task cannot resubmit'))
    assert not asyncio.run(AudioDriveService.run_next_persistent_tts_task())
    db_session.expire_all()
    assert db_session.get(Task, tid).status == 'failed'
    assert db_session.get(Task, tid).comfyui_prompt_id == 'original-submission'
    assert event.tts_status == 'FAILED'


class RebuildLLM:
    provider, model, timeout = 'test', 'rebuild-fixture', 20
    def __init__(self, db, during=None):
        self.db, self.during, self.calls = db, during, []
        self.values = {kind: [deepcopy(c.payload) for c in db.query(ChapterAssetCandidate).filter_by(asset_type=kind)]
                       for kind in ('characters', 'scenes', 'props')}

    async def chat_completion(self, **kwargs):
        self.calls.append(kwargs['task_type'])
        if self.during: self.during()
        kind = kwargs['task_type'].removeprefix('parse_')
        if kwargs['task_type'] == 'split_chapter':
            value=output();value['source_contract_version']='chapter-shot-ownership-v2'
            for planned in value['shots']:
                evidence=planned.pop('source_evidence')
                planned['source_citations']=deepcopy(evidence)
                planned['source_ownership']={'text':evidence[0]['text']}
        else:
            value={kind:self.values[kind]}
        raw, lid = json.dumps(value, ensure_ascii=False), str(uuid4())
        self.db.add(LLMLog(id=lid, provider=self.provider, model=self.model, status='success', task_type=kwargs['task_type'],
                          novel_id=kwargs['novel_id'], chapter_id=kwargs['chapter_id'], system_prompt=kwargs['system_prompt'],
                          user_prompt=kwargs['user_content'], response=raw,
                          prompt_template_name=kwargs.get('prompt_template_name')))
        self.db.commit()
        return {'success': True, 'content': raw, 'llm_log_id': lid}


def rebuild(db, chapter, llm, mode='CONTINUE'):
    service = ChapterRebuildService(db, llm)
    rid = service.enqueue(chapter.novel_id, chapter.id, mode=mode)['data']['id']
    run = db.get(ChapterRebuildRun, rid); task = db.get(Task, run.task_id)
    run.status, task.status = 'RUNNING', 'running'
    run.claim_token = task.claim_token = str(uuid4()); db.commit()
    asyncio.run(service.execute(run.id, run.claim_token)); db.expire_all()
    return db.get(ChapterRebuildRun, rid)


def test_explicit_rebuild_preserves_assets_and_replaces_only_verified_structure(db_session, chapter, fixture):
    old = Shot(chapter_id=chapter.id, index=1, description='old', image_url='/accepted.png', video_url='/accepted.mp4')
    db_session.add(old); db_session.commit(); old_id = old.id
    upgrade(db_session.bind)
    before = protection_snapshot(db_session, chapter.novel_id)
    llm = RebuildLLM(db_session)
    run = rebuild(db_session, chapter, llm, mode='REBUILD')
    assert run.status == 'BLOCKED', (run.error,[(task.type,task.status,task.error_message) for task in db_session.query(Task).filter_by(parent_task_id=run.task_id)])
    assert run.result_hash == digest(run.result)
    assert set(llm.calls) == {'parse_characters', 'parse_scenes', 'parse_props', 'split_chapter'}
    assert db_session.get(Shot, old_id) is None
    assert run.inputs['chapters'][0]['old_shots'][0]['shot']['image_url'] == '/accepted.png'
    assert protection_snapshot(db_session, chapter.novel_id) == before
    assert pipeline_state(db_session, chapter.novel_id, chapter.id)['structuralReady']
    assert db_session.query(Task).filter_by(parent_task_id=run.task_id, type='chapter_shot_split').count() == 1
    for shot in db_session.query(Shot).filter_by(chapter_id=chapter.id): require_source(db_session, shot.id)


def test_rebuild_parent_cancellation_fences_child_publication(db_session, chapter, fixture):
    old = Shot(chapter_id=chapter.id, index=1, description='old'); db_session.add(old); db_session.commit(); old_id = old.id
    def cancel():
        db_session.query(Task).filter_by(type='chapter_asset_rebuild').update({'status': 'cancelled'}); db_session.commit()
    run = rebuild(db_session, chapter, RebuildLLM(db_session, during=cancel))
    assert run.status == 'FAILED' and db_session.get(Shot, old_id)
    assert not db_session.query(ShotSource).count()
    assert not pipeline_state(db_session, chapter.novel_id, chapter.id)['structuralReady']


def test_failed_new_rebuild_never_revives_prior_ready_source(db_session, chapter, setup):
    run = rebuild(db_session, chapter, RebuildLLM(db_session))
    assert run.status == 'BLOCKED', (run.error,[(task.type,task.status,task.error_message) for task in db_session.query(Task).filter_by(parent_task_id=run.task_id)])
    shot = db_session.query(Shot).filter_by(chapter_id=chapter.id).order_by(Shot.index).first()
    require_source(db_session, shot.id)
    result = ChapterRebuildService(db_session).enqueue(chapter.novel_id, chapter.id)
    current = db_session.get(ChapterRebuildRun, result['data']['id'])
    task = db_session.get(Task, current.task_id)
    assert asyncio.run(TaskService(db_session).cancel_task(task.id))['success']
    with pytest.raises(HTTPException): require_source(db_session, shot.id)
    assert TaskService(db_session).retry_task(task.id)['status_code'] in {400, 409}


def admit_video(db, chapter, shot):
    from app.api.shots import _admit_video_execution
    workflow = Workflow(type='video', name='Video', workflow_json='{}', node_mapping='{}', is_active=True)
    db.add(workflow); db.commit()
    options = {'use_keyframes': True, 'use_reference_audio': False, 'selected_mode': 'SINGLE_FRAME',
               'workflow_id': workflow.id, 'only_window_index': None, 'auto_merge_clips': False, 'skip_llm_when_prompt_exists': False}
    return _admit_video_execution(TaskRepository(db), shot, chapter, workflow, 'production', options)


def test_video_claim_and_late_guard_require_exact_rsa_image(db_session, chapter, setup):
    shot = setup[3][0]
    produced, _, _ = run(db_session, enqueue(db_session, shot))
    assert produced.status == 'SUCCEEDED', produced.error
    task = admit_video(db_session, chapter, shot)
    _, _, handle = video.claim_video_execution(db_session, task.id)
    assert video.check_current(db_session, handle)
    shot.description += ' changed'; db_session.commit()
    with pytest.raises(video.ExecutionConflict): video.check_current(db_session, handle)
    assert video.fail_execution(db_session, handle, 'source changed')
    assert db_session.get(Task, task.id).status == 'failed'


def test_video_binding_validation_reports_request_scoped_memoization(db_session, chapter, setup):
    shot = setup[3][0]
    produced, _, _ = run(db_session, enqueue(db_session, shot))
    assert produced.status == 'SUCCEEDED', produced.error
    task = admit_video(db_session, chapter, shot)
    binding = json.loads(task.metadata_json)['rsa_binding']
    metrics = {}

    assert gate.validate_video_binding(db_session, task, binding, validation_metrics=metrics).id == binding['rsa_id']

    for name in ('image_bytes', 'inspect_image', 'compose_sheet', 'validate_manifest',
                 'artifact_proof', 'verify_prompt_record'):
        assert metrics[name]['requests'] == metrics[name]['real_executions'] + metrics[name]['cache_hits']
    assert metrics['image_bytes']['cache_hits'] > 0
    assert metrics['inspect_image']['cache_hits'] > 0
    assert metrics['validate_manifest']['cache_hits'] > 0
    assert metrics['artifact_proof']['cache_hits'] > 0


def test_same_url_and_missing_plan_member_are_not_keyframe_proof(db_session, setup):
    shot = setup[3][0]; run(db_session, enqueue(db_session, shot))
    shot.video_director_plan = json.dumps({'selected_mode': 'FIRST_LAST_FRAME', 'keyframes': [
        {'index': 2, 'role': 'END', 'description': 'end', 'time_seconds': 8, 'image_url': shot.image_url}]})
    db_session.commit()
    with pytest.raises(HTTPException, match='KEYFRAME_LINEAGE_REQUIRED'): gate.video_binding(db_session, shot)
    shot.video_director_plan = json.dumps({'selected_mode': 'MULTI_KEYFRAME', 'window_plans': [{'window_index': 1, 'keyframe_indexes': [1, 2, 3]}],
                                         'keyframes': [{'index': 1, 'role': 'START'}]})
    db_session.commit()
    with pytest.raises(HTTPException, match='MEMBERSHIP_CHANGED'): gate.video_binding(db_session, shot)


def test_single_frame_consumes_no_unused_keyframe_media(db_session, setup):
    from app.services import shot_video_service
    shot=setup[3][0];run(db_session,enqueue(db_session,shot))
    frames=[{'index':2,'role':'END','description':'unused','image_url':'/unverified.png'}]
    assert gate.verified_plan_images(db_session,shot,frames,set())==frames
    with pytest.raises(HTTPException):gate.verified_plan_images(db_session,shot,frames,{2})
    clip={'clip_index':1,'start_time':0,'end_time':4}
    inputs=video._video_reference_inputs(shot_video_service,shot,{},frames,'SINGLE_FRAME',False,clip,{},check_files=False)
    assert inputs['references']==[{'label':'C1 start','url':shot.image_url}]


def test_every_shot_mutation_has_a_runtime_disposition():
    from app.api.shots import router
    known = gate.DEPRECATED | gate.SOURCE_ENTRIES | gate.IMAGE_ENTRIES | gate.VIDEO_ENTRIES | gate.BATCH_ENTRIES | {'delete_shot'}
    assert {r.name for r in router.routes if r.methods & {'POST','PUT','PATCH','DELETE'}} - known == set()


def test_base_prompt_builders_cannot_hide_missing_formal_definitions():
    from app.services.prompt_builder import PromptBuilder
    with pytest.raises(ValueError, match='CHARACTER_APPEARANCE_REQUIRED'):
        PromptBuilder.build_character_prompt('刘备', '', description='角色名字不等于正式外观')
    with pytest.raises(ValueError, match='SCENE_SETTING_REQUIRED'):
        PromptBuilder.build_scene_prompt('桃园', None, template='{setting}')
    with pytest.raises(ValueError, match='PROP_DEFINITION_REQUIRED'):
        PromptBuilder.build_prop_prompt('物件', '', '')


def test_video_batch_pins_only_ready_subset(db_session, chapter, setup):
    first, second = setup[3]
    run(db_session, enqueue(db_session, first))
    result = client(db_session).post(f'/api/novels/{chapter.novel_id}/chapters/{chapter.id}/videos/generate-batch',
                                   json={'shot_ids':[first.id,second.id]}).json()
    assert result['success'], result
    assert result['data']['shotIds'] == [first.id]
    assert result['data']['blocked'][0]['shotId'] == second.id
    task = db_session.get(Task, result['data']['taskId'])
    gate.video_batch_member(db_session, task, first.id)
    assert json.loads(task.metadata_json)['scope'] == 'REQUESTED_READY_SUBSET'
    with pytest.raises(HTTPException): gate.video_batch_member(db_session, task, second.id)


def complete_fixture_video(db, chapter, setup, monkeypatch):
    """Synthetic video transport receipt; real RSA and real publication/merge guards."""
    from app.utils import path_utils
    monkeypatch.setattr(path_utils, 'local_path_to_url', lambda path:'/api/files/'+str(Path(path).relative_to(setup[4])))
    shot = setup[3][0]; run(db, enqueue(db, shot))
    task = admit_video(db, chapter, shot)
    _, _, handle = video.claim_video_execution(db, task.id)
    data = video.check_current(db, handle)[1]
    slot = deepcopy(data['video_run']['clips']['1'])
    graph = {'out': {'class_type':'SaveVideo','inputs':{'source':1}}}
    cid = 'synthetic-video-receipt'
    slot['submission'] = {'state':'acknowledged','prompt_id':cid,'graph':graph,'graph_hash':video.digest(graph),
                          'endpoint':'http://comfy.invalid','output_node':'out'}
    history = {'prompt':[0,cid,graph],'status':{'completed':True,'status_str':'success'},
               'outputs':{'out':{'images':[{'filename':'clip.mp4','subfolder':'','type':'output'}]}}}
    path = Path(handle['directory'])/'clip.mp4'; path.write_bytes(b'synthetic transport artifact')
    slot.update(state='SUCCEEDED', receipt={'run_id':handle['run_id'],'attempt_id':slot['attempt_id'],'clip_index':1,
        'prompt_id':cid,'graph_hash':video.digest(graph),'source_url':video.verify_history(slot,history),'path':str(path),
        'sha256':video.file_digest(path),'bytes':path.stat().st_size,'history':video.capture(handle,'history',history)})
    video._write(db,handle,lambda d:d['video_run']['clips'].update({'1':slot}))
    merge = video.begin_merge(db,handle)
    video.publish_result(db,handle,merge,str(path)); db.expire_all()
    return db.get(Shot,shot.id)


@pytest.mark.parametrize('change_source',[False,True])
def test_chapter_merge_keeps_exact_subset_and_fences_source_changes(db_session, chapter, setup, monkeypatch, change_source):
    from app.services import chapter_video_merge_service as merge
    from app.core import database
    first = complete_fixture_video(db_session,chapter,setup,monkeypatch)
    chapter.final_video='/accepted-final.mp4'; db_session.commit()
    with pytest.raises(HTTPException): merge.capture_merge(db_session,chapter.novel_id,chapter.id)
    captured = merge.capture_merge(db_session,chapter.novel_id,chapter.id,[first.id])
    task = Task(type='chapter_video',name='Synthetic merge fixture',novel_id=chapter.novel_id,chapter_id=chapter.id,status='pending',
                metadata_json=json.dumps({'merge_inputs':captured,'input_hash':digest(captured)}))
    db_session.add(task);db_session.commit();tid=task.id
    async def render(paths, destination, **kwargs):
        Path(destination).write_bytes(b'synthetic merged subset')
        await kwargs['progress_callback'](5, '校验源视频')
        if change_source:
            chapter.content+='changed'; db_session.commit()
        await kwargs['progress_callback'](50, '合并中')
        return {'success':True}
    from app.services.file_storage import file_storage
    monkeypatch.setattr(file_storage,'merge_videos',render)
    monkeypatch.setattr(database,'SessionLocal',lambda:Session(db_session.bind,autoflush=False))
    asyncio.run(merge.run_merge(tid));db_session.expire_all()
    task=db_session.get(Task,tid)
    assert task.status==('failed' if change_source else 'completed'),task.error_message
    if not change_source:assert json.loads(task.metadata_json)['result']['scope']=='REQUESTED_SUBSET'
    assert db_session.get(Chapter,chapter.id).final_video=='/accepted-final.mp4'
