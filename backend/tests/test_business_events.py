"""Committed business results, delivery isolation, event API and real service integration."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, event as sqlalchemy_event
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base, get_db
from app.api.events import router
from app.models.notification import BusinessEvent, NotificationDelivery, NotificationSettings
from app.models.task import Task
from app.models.shot import Shot
from app.models.novel import Novel, Chapter
from app.models.image_quality_review import ImageQualityReview
from app.models.prompt_template import PromptTemplate
from app.services import business_events as be
from app.services.notification_service import NotificationService
from app.services.image_quality_review import review_image_task, execute_image_review
from test_image_quality_review import _response


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    class EventSession(Session):
        pass
    engine = create_engine(f"sqlite:///{tmp_path}/events.db")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=EventSession)
    monkeypatch.setattr(be, "SessionLocal", factory)
    remove = be.install_business_event_hooks(factory)
    with factory() as db:
        db.add_all([Novel(id="novel", title="测试小说"), Chapter(id="chapter", novel_id="novel", title="章", number=1),
                    Shot(id="shot", chapter_id="chapter", index=4, video_director_plan=json.dumps({"keyframes": [{"index": 6}], "clip_plan": [{"clip_index": 2}]})),
                    NotificationSettings(id="default", page_sound_enabled=False),
                    PromptTemplate(id="template", name="#15", type="image_quality_review_prompt", template="registered", is_system=True, is_active=True)])
        db.commit()
        yield db, factory
    remove()
    engine.dispose()


def image_task(db):
    task = Task(type="keyframe_image", name="图片", status="running", novel_id="novel", chapter_id="chapter", shot_id="shot",
                prompt_text="secret full prompt", result_url="/api/files/saved.png", comfyui_prompt_id="comfy-1",
                metadata_json=json.dumps({"reference_selector_input": {"current_anchor": {"index": 6}}}), reference_images="[]")
    db.add(task); db.commit()
    task.status = "completed"; task.completed_at = datetime.now(timezone.utc); db.commit()
    return task


def test_commit_only_no_duplicates_and_recovery_result(ledger):
    db, _ = ledger
    task = image_task(db)
    rows = db.query(BusinessEvent).all()
    assert len(rows) == 1 and rows[0].event_type == 'visual_state.generation.completed'
    assert rows[0].visual_state_id == '6'
    task.current_step = 'refresh'; db.commit()
    task.status = 'failed'; db.flush(); db.rollback()
    assert db.query(BusinessEvent).count() == 1
    task.status = 'completed'; db.commit()
    assert db.query(BusinessEvent).count() == 1
    task.status = 'running'; task.comfyui_prompt_id = 'comfy-2'; db.commit()
    task.status = 'failed'; db.commit()
    assert db.query(BusinessEvent).count() == 2


@pytest.mark.parametrize('trigger', ['manual', 'automatic'])
def test_real_review_service_emits_after_save_without_changing_image(ledger, trigger):
    db, _ = ledger; task = image_task(db)
    llm = AsyncMock(return_value={'success': True, 'content': _response()})
    class LLM:
        provider, model = 'mock', 'mock'
        chat_completion = llm
    with patch('app.services.image_quality_review.LLMService', LLM), patch('app.services.image_quality_review.vision_proxy', side_effect=lambda url, **kw: {**kw, 'url': url}):
        review = asyncio.run(review_image_task(db, task.id, trigger=trigger))
        assert review.overall == 'FAIL'
        event = db.query(BusinessEvent).filter_by(review_id=review.id).one()
        assert event.event_type == 'image.review.failed' and event.status == 'FAIL'
        assert event.trigger == trigger and event.visual_state_id == '6' and event.task_id == task.id
        assert 'CHARACTER_IDENTITY' in json.loads(event.details_json)['failed_dimensions']
        assert 'secret full prompt' not in event.details_json
        asyncio.run(execute_image_review(db, review.id))
        assert llm.await_count == 1
        assert db.query(BusinessEvent).filter_by(review_id=review.id).count() == 1
        second = asyncio.run(review_image_task(db, task.id))
        assert second.id != review.id and db.query(BusinessEvent).filter(BusinessEvent.review_id.isnot(None)).count() == 2
    db.refresh(task)
    assert task.status == 'completed' and task.result_url == '/api/files/saved.png'


@pytest.mark.parametrize('overall,status,code', [('PASS','success','passed'), ('WARNING','success','failed'), (None,'error','error')])
def test_review_verdicts(ledger, overall, status, code):
    db, _ = ledger; task = image_task(db)
    review = ImageQualityReview(task_id=task.id, status=status, overall=overall, trigger='automatic')
    db.add(review); db.commit()
    event = db.query(BusinessEvent).filter_by(review_id=review.id).one()
    assert event.event_type == f'image.review.{code}'
    assert event.raw_status == (overall or 'ERROR')
    assert event.needs_attention == (overall != 'PASS')
    assert task.status == 'completed'


def test_image_review_pass_with_quality_warning_keeps_warning_event_details(ledger):
    db, _ = ledger; task = image_task(db)
    review = ImageQualityReview(task_id=task.id, status='success', overall='PASS', trigger='automatic',
                                dimensions_json=json.dumps({
                                    'CHARACTER_IDENTITY': {'status': 'PASS'},
                                    'ACTION_ACCURACY': {'status': 'WARNING'}}))
    db.add(review); db.commit()
    event = db.query(BusinessEvent).filter_by(review_id=review.id).one()
    details = json.loads(event.details_json)
    assert event.event_type == 'image.review.passed' and event.status == 'SUCCESS'
    assert details['failed_dimensions'] == []
    assert details['warning_dimensions'] == ['ACTION_ACCURACY']


def test_channels_off_and_subscription_off_still_record_and_delivery_dedup(ledger):
    db, _ = ledger
    result = asyncio.run(NotificationService.emit('image.review.failed', {'review_id':'r'}, db=db, dedupe_key='review:r'))
    assert result['channels'] == {'PAGE_SOUND':'disabled','FEISHU':'disabled','TELEGRAM':'disabled'}
    assert db.query(BusinessEvent).count() == 1 and db.query(NotificationDelivery).count() == 0
    config = db.get(NotificationSettings,'default'); config.page_sound_enabled = True; db.commit()
    result = asyncio.run(NotificationService.emit('image.review.failed', db=db, dedupe_key='next'))
    assert result['channels']['PAGE_SOUND'] == 'queued'
    asyncio.run(NotificationService.dispatch_event(db,result['event_id']))
    assert db.query(NotificationDelivery).count() == 1
    assert json.loads(db.query(NotificationDelivery).one().detail)['event_id'] == result['event_id']
    config.event_switches = '{"image.review.failed":false}'; db.commit()
    result = asyncio.run(NotificationService.emit('image.review.failed', db=db))
    assert result['status'] == 'event_disabled' and db.query(BusinessEvent).count() == 3
    assert db.query(NotificationDelivery).count() == 1


def test_notification_failure_and_event_persistence_failure_do_not_touch_task(ledger, monkeypatch):
    db, _ = ledger; task = image_task(db)
    config = db.get(NotificationSettings,'default'); config.feishu_enabled = True; db.commit()
    with patch('app.services.notification_service.send_feishu', new_callable=AsyncMock, side_effect=RuntimeError('offline')):
        result = asyncio.run(NotificationService.emit('image.review.error', {'task_id':task.id}, db=db))
    assert result['channels']['FEISHU'] == 'failed'
    assert db.get(BusinessEvent, result['event_id']) is not None
    with patch.object(be, 'record_event', side_effect=RuntimeError('event table unavailable')):
        task.status = 'failed'; db.commit()
    db.refresh(task); assert task.status == 'failed'


def test_h3_final_and_repair_no_prompt_leak_or_reuse_duplicates(ledger):
    db,_ = ledger; shot = db.get(Shot,'shot')
    call = {'step':'14', 'created_at':'2026-10-11T00:00:00', 'status':'success','clip_index':2,
            'final_prompt':'SHOULD NOT STORE', 'parsed_result':{'llm_log_id':'log1','authority_check':{'passed':True},'preflight_repair':{'l1_invocations':1}}}
    shot.video_director_plan = json.dumps({'ai_calls':[call]}); db.commit()
    assert {r.event_type for r in db.query(BusinessEvent)} == {'clip.prompt.optimize.completed','preflight.repair.completed'}
    shot.description = 'edit'; db.commit()
    call['created_at']='2026-10-11T00:00:01'; call['parsed_result']['reused_result']=True
    shot.video_director_plan=json.dumps({'ai_calls':[call]}); db.commit()
    assert db.query(BusinessEvent).count() == 2
    assert all('SHOULD NOT STORE' not in r.details_json for r in db.query(BusinessEvent))


def test_preflight_failure_without_l1_emits_optimizer_failure_only(ledger):
    db, _ = ledger
    shot = db.get(Shot, 'shot')
    call = {'step': '14', 'created_at': '2026-10-12T00:30:00', 'status': 'failed',
            'clip_index': 1, 'parsed_result': {
                'llm_log_id': 'shot6-log',
                'authority_check': {'passed': False, 'blocking_findings': ['canonical_visual_requirement_trace']},
                'preflight_repair': {'resolution': 'L2_UNSAFE_OR_NONLOCAL', 'l1_invocations': 0, 'attempts': []},
            }}
    shot.video_director_plan = json.dumps({'ai_calls': [call]})
    db.commit()
    rows = db.query(BusinessEvent).all()
    assert [row.event_type for row in rows] == ['clip.prompt.optimize.failed']
    assert 'canonical_visual_requirement_trace' in rows[0].details_json


def test_transport_failure_events_keep_code_log_task_and_clip_without_repair_event(ledger):
    db, _ = ledger
    shot = db.get(Shot, 'shot')
    call = {'step': '14', 'created_at': '2026-10-12T01:00:00', 'status': 'error',
            'clip_index': 2, 'parsed_result': {
                'llm_log_id': 'llm-502', 'error_code': 'LLM_TRANSPORT_ERROR',
                'error': 'API 错误 (502): Upstream service temporarily unavailable',
            }}
    shot.video_director_plan = json.dumps({'ai_calls': [call]})
    db.commit()
    task = Task(id='task-502', type='shot_video', status='failed', name='C2', shot_id='shot',
                chapter_id=shot.chapter_id,
                error_message='#14 LLM_TRANSPORT_ERROR，停止视频生成：API 错误 (502)',
                metadata_json=json.dumps({
                    'execution_scope': 'CLIP', 'clip_id': 'shot:clip:2', 'clip_index': 2,
                    'h3_prompt_optimizer': call['parsed_result'],
                }))
    db.add(task)
    db.commit()
    rows = {row.event_type: row for row in db.query(BusinessEvent).all()}
    assert set(rows) == {'clip.prompt.optimize.failed', 'clip.generation.failed'}
    assert rows['clip.prompt.optimize.failed'].llm_log_id == 'llm-502'
    assert 'LLM_TRANSPORT_ERROR' in rows['clip.prompt.optimize.failed'].details_json
    assert rows['clip.generation.failed'].task_id == 'task-502'
    assert rows['clip.generation.failed'].clip_id == 'shot:clip:2'
    assert rows['clip.generation.failed'].llm_log_id == 'llm-502'
    assert 'LLM_TRANSPORT_ERROR' in rows['clip.generation.failed'].details_json


def test_prior_l1_budget_does_not_emit_new_repair_failure_without_new_call(ledger):
    db, _ = ledger
    shot = db.get(Shot, 'shot')
    shot.video_director_plan = json.dumps({'ai_calls': [{
        'step': '14', 'created_at': '2026-10-12T01:10:00', 'status': 'error',
        'clip_index': 2, 'parsed_result': {
            'llm_log_id': 'current-log', 'error_code': 'PREFLIGHT_FAIL',
            'l1_invocations_this_call': 0,
            'preflight_repair': {'l1_invocations': 1, 'resolution': 'L1_ALREADY_ATTEMPTED'},
            'authority_check': {'passed': False, 'blocking_findings': ['canonical_visual_requirement_trace']},
        },
    }]})
    db.commit()
    assert [row.event_type for row in db.query(BusinessEvent).all()] == ['clip.prompt.optimize.failed']


def test_regeneration_does_not_also_emit_generation(ledger):
    db,_=ledger
    task=Task(type='shot_video',status='completed',name='C2',shot_id='shot',comfyui_prompt_id='p',metadata_json=json.dumps({'execution_scope':'CLIP','clip_index':2,'is_clip_regeneration':True}))
    db.add(task); db.commit()
    assert [r.event_type for r in db.query(BusinessEvent)] == ['clip.regeneration.completed']


def request(db, path):
    app=FastAPI(); app.include_router(router, prefix='/api/events'); app.dependency_overrides[get_db]=lambda: db
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            return await client.get(path)
    return asyncio.run(run())


def test_filters_pagination_details_real_links_and_historical_import(ledger):
    db,_=ledger; task=image_task(db)
    review=ImageQualityReview(task_id=task.id,status='success',overall='FAIL',trigger='manual'); db.add(review); db.commit()
    for i in range(28):
        be.record_event(db,'clip.generation.failed',{'novel_id':'novel','chapter_id':'chapter','shot_id':'shot','clip_id':'shot:clip:2','status':'FAIL','details':{'clip_index':2}}, dedupe_key=f'old:{i}',historical=True,timestamp=datetime(2026,1,1)+timedelta(minutes=i))
    response=request(db,'/api/events?page_size=10&view=attention&novel_id=novel')
    data=response.json()['data']; assert data['total']==29 and len(data['items'])==10
    response=request(db,'/api/events?start_time=2026-01-01T00:00:00Z&end_time=2026-01-01T00:05:00Z&status=FAIL')
    assert response.json()['data']['total']==6
    event=db.query(BusinessEvent).filter_by(review_id=review.id).one()
    detail=request(db,f'/api/events/{event.id}').json()['data']
    assert detail['review_target']['review_id']==review.id
    assert 'visualState=6' in detail['links'][0]['href']
    assert not any('logId' in x['href'] for x in detail['links'])
    assert request(db,'/api/events?page_size=1000').status_code==422
    assert request(db,'/api/events?start_time=2026-10-11&end_time=2026-01-01').status_code==422
    assert request(db,'/api/events/options').json()['data']['shots'][0]['index']==4
    assert all(r.notification_status=='historical' for r in db.query(BusinessEvent).filter_by(historical=True))
    assert db.query(NotificationDelivery).count()==0


def test_event_list_reads_only_related_display_columns(ledger):
    db, _ = ledger
    be.record_event(db, 'image.review.failed', {
        'novel_id': 'novel', 'chapter_id': 'chapter', 'shot_id': 'shot',
    }, dedupe_key='list-projection')
    statements = []

    def capture_sql(connection, cursor, statement, parameters, context, executemany):
        if 'FROM business_events' in statement and 'LEFT OUTER JOIN shots' in statement:
            statements.append(statement)

    engine = db.get_bind()
    sqlalchemy_event.listen(engine, 'before_cursor_execute', capture_sql)
    try:
        response = request(db, '/api/events')
    finally:
        sqlalchemy_event.remove(engine, 'before_cursor_execute', capture_sql)

    assert response.status_code == 200
    item = response.json()['data']['items'][0]
    assert item['novel_title'] == '测试小说' and item['chapter_title'] == '章'
    assert item['shot_index'] == 4
    assert len(statements) == 1
    assert 'shots.video_director_plan' not in statements[0]
    assert 'chapters.content' not in statements[0]
    assert 'novels.story_world_context' not in statements[0]


def test_payload_is_allowlisted(ledger):
    db,_=ledger
    row=be.record_event(db,'image.review.failed',{'details':{'original_prompt':'FULL','api_key':'SECRET','image':'data:abc','failed_dimensions':['CHARACTER_COUNT'],'summary':'Bearer xyz token=secret'}})
    details=json.loads(row.details_json)
    assert set(details)=={'failed_dimensions','summary'}
    assert 'secret' not in details['summary'] and 'xyz' not in details['summary']


def test_expired_shot_write_does_not_replay_existing_calls(ledger):
    db, factory = ledger
    # Saved call predates the event subscription; ordinary updates must not
    # accidentally turn it into a new business event.
    shot = db.get(Shot,'shot')
    saved = {'ai_calls':[{'step':'14','created_at':'2020-01-01T00:00:00','status':'success','parsed_result':{}}]}
    db.connection().execute(Shot.__table__.update().where(Shot.id=='shot').values(video_director_plan=json.dumps(saved)))
    db.commit()
    assert db.query(BusinessEvent).count()==0
    db.expire(shot,['video_director_plan'])
    shot.video_director_plan=json.dumps({**saved,'unrelated':'updated'})
    db.commit()
    assert db.query(BusinessEvent).count()==0


def test_automatic_worker_emits_error_once_and_leaves_completed_image(ledger):
    from app.models.system_config import SystemConfig
    from app.services.image_review_worker import enqueue_automatic_review, process_review_queue
    db,_=ledger; task=image_task(db)
    db.add(SystemConfig(id='default',auto_image_review_enabled=True));db.commit()
    queued=enqueue_automatic_review(db,task.id)
    class LLM:
        provider,model='mock','mock'
        async def chat_completion(self,**kw):raise RuntimeError('provider unavailable')
    with patch('app.services.image_quality_review.LLMService',LLM),patch('app.services.image_quality_review.vision_proxy',side_effect=lambda url,**kw:{**kw,'url':url}):
        review=asyncio.run(process_review_queue(db))
        assert review.id==queued.id and review.status=='error'
        assert asyncio.run(process_review_queue(db)) is None
    event=db.query(BusinessEvent).filter_by(review_id=review.id).one()
    assert event.event_type=='image.review.error' and event.trigger=='automatic'
    db.refresh(task);assert task.status=='completed'


def test_history_import_idempotent_no_delivery(ledger):
    from scripts.backfill_business_events import backfill
    db,_=ledger;task=image_task(db)
    # Simulate saved pre-V1 review without invoking a new LLM.
    db.execute(ImageQualityReview.__table__.insert().values(id='old-review',task_id=task.id,status='success',overall='FAIL',trigger='manual',completed_at=datetime(2026,1,1)))
    db.commit()
    first=backfill(db,'novel',True);second=backfill(db,'novel',True)
    assert first['inserted']==1 and second['inserted']==0
    old=db.query(BusinessEvent).filter_by(review_id='old-review').one()
    assert old.historical and old.notification_status=='historical'
    assert db.query(NotificationDelivery).count()==0


def test_history_import_saved_assembly_preserves_original_record(ledger):
    from scripts.backfill_business_events import backfill
    db,_=ledger;shot=db.get(Shot,'shot')
    saved=json.dumps({'clip_plan':[{'clip_index':1},{'clip_index':2}], 'assembled_result':{
        'status':'COMPLETED','url':'/api/files/existing-shot.mp4',
        'assembled_at':'2026-01-01T12:00:00','clip_plan_revision':3}})
    shot.video_director_plan=saved;db.commit()
    first=backfill(db,'novel',True);second=backfill(db,'novel',True)
    assert first['inserted']==1 and second['inserted']==0
    event=db.query(BusinessEvent).filter_by(event_type='shot.assembly.completed').one()
    assert event.timestamp==datetime(2026,1,1,12)
    assert event.historical and event.notification_status=='historical'
    assert json.loads(event.details_json)['clip_count']==2
    db.refresh(shot);assert shot.video_director_plan==saved
    assert db.query(NotificationDelivery).count()==0


def test_assembly_observation_preserves_result_and_failure(ledger):
    db,_=ledger;shot=db.get(Shot,'shot')
    @be.observed_assembly
    async def merge(db,shot,mode):
        if mode=='raise':raise ValueError('merge failed')
        return {'success':mode=='pass','video_url':'saved.mp4' if mode=='pass' else None,'plan':{'clip_plan_revision':1}}
    with patch.object(be, 'SessionLocal', side_effect=AssertionError('must not use default database')):
        assert asyncio.run(merge(db,shot,'pass'))['success']
        asyncio.run(merge(db,shot,'pass'))
    assert db.query(BusinessEvent).filter_by(event_type='shot.assembly.completed').count()==1
    with pytest.raises(ValueError):asyncio.run(merge(db,shot,'raise'))
    assert db.query(BusinessEvent).filter_by(event_type='shot.assembly.failed').count()==1
