"""Phase9 read-only, explicitly linked provenance; corrupt evidence is never empty success."""
import asyncio
from copy import deepcopy
import json
from uuid import uuid4
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from app.core.database import get_db
from app.models.novel import Novel, Chapter
from app.models.shot import Shot
from app.models.task import Task
from app.models.llm_log import LLMLog
from app.models.rsa_media import RsaMediaArtifact
from app.models.resolved_shot_assets import ResolvedShotAssets
from app.models.asset_resolution import AssetResolutionDecision
from app.services.asset_debug_service import AssetDebugService
from app.services.task_service import TaskService
from test_rsa_media import db_session, chapter, fixture, base_setup, setup, enqueue, run


def client(db):
    from app.api.asset_debug import router
    from app.api.tasks import router as tasks
    app=FastAPI();app.include_router(router,prefix='/api');app.include_router(tasks,prefix='/api/tasks')
    app.dependency_overrides[get_db]=lambda:db
    return TestClient(app)


def trace(db, chapter, **options):
    return AssetDebugService(db,chapter.novel_id).chapter(chapter.id,**options)


def test_primary_keyframe_trace_uses_explicit_rsa_source_and_log_ids(db_session,chapter,setup):
    shot=setup[3][0]
    first,_,_=run(db_session,enqueue(db_session,shot))
    second,_,_=run(db_session,enqueue(db_session,shot,stage='KEYFRAME',frame_index=0))
    log=db_session.get(LLMLog,second.execution['prompt']['llm_log_id'])
    log.duration=1.25;log.usage_metrics={'input_tokens':90,'output_tokens':30};db_session.commit()
    graph=trace(db_session,chapter,shot_id=shot.id)
    nodes={n['key']:n for n in graph['nodes']}
    assert not graph['coverage']['truncated']
    for key in (f'rsa:{setup[5]["id"]}',f'media_artifact:{first.artifact_id}',f'media_artifact:{second.artifact_id}',
                f'llm_log:{log.id}',f'source:{shot.id}'):
        assert key in nodes
    assert {'from':f'media_artifact:{second.artifact_id}','to':f'media_artifact:{first.artifact_id}',
            'path':'data.parents[0].id'} in graph['edges']
    assert nodes[f'llm_log:{log.id}']['facts']['durationSeconds']==1.25
    assert nodes[f'llm_log:{log.id}']['facts']['tokenUsage']=={'input_tokens':90,'output_tokens':30}
    assert graph['current']['shot']['checks']['assets']['ready']
    detail=AssetDebugService(db_session,chapter.novel_id).record('media_attempt',second.id)
    assert detail['record']['execution']['uploads'][0]['remote_sha256']==db_session.get(RsaMediaArtifact,first.artifact_id).data['image']['sha256']
    assert detail['record']['inputs']['rsa_id']==setup[5]['id']


def test_debug_queries_do_not_write_or_resolve(db_session,chapter,setup,monkeypatch):
    from app.services.resolved_shot_assets_service import ResolvedShotAssetsService
    from app.services.chapter_rebuild_service import ChapterRebuildService
    from app.services.comfyui import ComfyUIService
    def forbidden(*args,**kwargs):pytest.fail('Debug must not execute, repair, resolve or contact a provider')
    monkeypatch.setattr(ResolvedShotAssetsService,'resolveShotAssets',forbidden)
    monkeypatch.setattr(ChapterRebuildService,'enqueue',forbidden)
    monkeypatch.setattr(ComfyUIService,'__init__',forbidden)
    def statements(conn,cursor,statement,parameters,context,many):
        assert statement.lstrip().split()[0].upper() not in {'INSERT','UPDATE','DELETE','CREATE','ALTER','REPLACE'}
    event.listen(db_session.bind,'before_cursor_execute',statements)
    try:
        api=client(db_session)
        root=f'/api/novels/{chapter.novel_id}/chapters/{chapter.id}/asset-debug'
        assert api.get(root,params={'shot_id':setup[3][0].id}).status_code==200
        assert api.get(f'/api/novels/{chapter.novel_id}/asset-debug/records/rsa/{setup[5]["id"]}').status_code==200
    finally:event.remove(db_session.bind,'before_cursor_execute',statements)
    assert not db_session.new and not db_session.dirty and not db_session.deleted


def test_legacy_debug_reports_missing_chain_without_inventing_bindings(db_session,chapter):
    old=Shot(chapter_id=chapter.id,index=1,characters='["刘备"]',scene='桃园',description='旧分镜',image_url='/old.png')
    db_session.add(old);db_session.commit()
    graph=trace(db_session,chapter,shot_id=old.id)
    assert not graph['current']['shot']['checks']['source']['ready']
    assert not any(n['kind'] in {'character_binding','rsa','appearance_event'} for n in graph['nodes'])
    source=next(n for n in graph['nodes'] if n['key']==f'source:{old.id}')
    assert source['availability']=='MISSING'


@pytest.mark.parametrize('raw,state',[('{broken','INVALID_JSON'),('[]','WRONG_TYPE'),(None,'MISSING'),('{}','VALID')])
def test_task_detail_distinguishes_corrupt_missing_and_valid_empty(db_session,chapter,raw,state):
    task=Task(name='diagnostic fixture',type='shot_video',novel_id=chapter.novel_id,chapter_id=chapter.id,status='failed',metadata_json=raw,reference_images='broken')
    db_session.add(task);db_session.commit()
    response=TaskService.format_task_detail(task)
    assert response['evidence']['metadata_json']['state']==state
    assert response['metadata']==({} if state=='VALID' else None)
    assert response['referenceImages'] is None
    assert response['evidence']['reference_images']['state']=='INVALID_JSON'


def test_malformed_json_column_keeps_other_trace_nodes_available(db_session,chapter,setup):
    rid=setup[5]['id']
    db_session.execute(text('UPDATE resolved_shot_assets SET inputs=:raw WHERE id=:id'),{'raw':'{"logical":','id':rid});db_session.commit();db_session.expire_all()
    graph=trace(db_session,chapter,rsa_id=rid)
    node=next(n for n in graph['nodes'] if n['key']==f'rsa:{rid}')
    assert node['availability']=='CORRUPT'
    assert any(i['field']=='inputs' and i['code']=='INVALID_JSON' for i in node['issues'])
    detail=AssetDebugService(db_session,chapter.novel_id).record('rsa',rid)
    assert detail['jsonFields']['inputs']['state']=='INVALID_JSON'
    assert detail['record']['inputs'] is None
    assert any(n['kind']=='task' for n in graph['nodes'])


def test_foreign_book_pointer_is_diagnostic_not_a_data_leak(db_session,chapter,setup):
    other=Novel(title='private other book');db_session.add(other);db_session.flush()
    foreign=Task(name='foreign sensitive title',type='shot_image',novel_id=other.id,status='failed',prompt_text='foreign-only-prompt')
    db_session.add(foreign);db_session.commit()
    row=db_session.get(ResolvedShotAssets,setup[5]['id']);row.task_id=foreign.id;db_session.commit()
    graph=trace(db_session,chapter,rsa_id=row.id)
    target=next(n for n in graph['nodes'] if n['key']==f'task:{foreign.id}')
    assert target['availability']=='OUT_OF_SCOPE'
    assert 'foreign-only-prompt' not in json.dumps(graph) and 'foreign sensitive title' not in json.dumps(graph)
    with pytest.raises(HTTPException):AssetDebugService(db_session,chapter.novel_id).record('task',foreign.id)


def test_deleted_task_remains_missing_while_ledger_is_traceable(db_session,chapter,setup):
    row,_,_=run(db_session,enqueue(db_session,setup[3][0]))
    db_session.delete(db_session.get(Task,row.id));db_session.commit()
    graph=trace(db_session,chapter,shot_id=setup[3][0].id)
    assert next(n for n in graph['nodes'] if n['key']==f'task:{row.id}')['availability']=='MISSING'
    assert any(n['key']==f'media_attempt:{row.id}' for n in graph['nodes'])


def test_saved_ready_status_is_separate_from_current_failed_gate(db_session,chapter,setup):
    rid=setup[5]['id'];setup[1].setting+=' changed';db_session.commit()
    graph=trace(db_session,chapter,rsa_id=rid)
    assert next(n for n in graph['nodes'] if n['key']==f'rsa:{rid}')['recordStatus']=='READY'
    detail=AssetDebugService(db_session,chapter.novel_id).record('rsa',rid)
    assert detail['currentGate']['state']=='FAIL'
    assert not graph['current']['shot']['checks']['assets']['ready']


def test_raw_evidence_redacts_credentials_without_hiding_metrics(db_session,chapter):
    task=Task(name='redaction',type='shot_video',novel_id=chapter.novel_id,chapter_id=chapter.id,status='failed',
              metadata_json=json.dumps({'api_key':'do-not-display','headers':{'Authorization':'Bearer hidden-value'},
                                        'token_usage':{'total_tokens':123},'workflow_json':json.dumps({'token':'nested-secret'})}))
    db_session.add(task);db_session.commit()
    detail=AssetDebugService(db_session,chapter.novel_id).record('task',task.id)
    encoded=json.dumps(detail)
    for secret in ('do-not-display','hidden-value','nested-secret'):assert secret not in encoded
    assert detail['record']['metadata_json']['token_usage']['total_tokens']==123
    assert detail['jsonFields']['metadata_json']['redacted']


def test_graph_limit_is_explicit_and_cycles_are_bounded(db_session,chapter,setup):
    graph=AssetDebugService(db_session,chapter.novel_id,max_nodes=4).chapter(chapter.id,shot_id=setup[3][0].id)
    assert len(graph['nodes'])<=4 and graph['coverage']['truncated']
    tid=setup[5]['taskId'];task=db_session.get(Task,tid);task.parent_task_id=tid;db_session.commit()
    graph=AssetDebugService(db_session,chapter.novel_id).task(tid)
    assert len({n['key'] for n in graph['nodes']})==len(graph['nodes'])
    assert any(i['code']=='SELF_REFERENCE' for i in graph['diagnostics'])


def test_clip_workflow_debug_never_reads_current_plan_or_remote(db_session,chapter,monkeypatch):
    shot=Shot(chapter_id=chapter.id,index=1,description='legacy',video_director_plan=json.dumps({'window_plans':[{'window_index':1,'workflow_json':{'guessed':True},'generated_by_task_id':'old'}]}))
    db_session.add(shot);db_session.commit()
    task=Task(id='old',name='old video',type='shot_video',status='failed',novel_id=chapter.novel_id,chapter_id=chapter.id,shot_id=shot.id)
    db_session.add(task);db_session.commit()
    from app.services.comfyui import ComfyUIService
    monkeypatch.setattr(ComfyUIService,'__init__',lambda *a,**k:pytest.fail('read-only debug'))
    response=client(db_session).get('/api/tasks/old/clips/1/workflow')
    assert response.status_code==200 and response.json()['data']['workflow'] is None
    assert 'guessed' not in response.text


def test_new_resolution_records_metrics_and_deterministic_no_llm(db_session,chapter,fixture):
    decisions=db_session.query(AssetResolutionDecision).all()
    assert decisions
    for decision in decisions:
        assert decision.plan['metrics']['latency_ms']>=0
        if not decision.llm_used:
            assert decision.plan['metrics']['token_usage'] is None


def test_log_reverse_trace_requires_saved_id_not_equal_text(db_session,chapter,setup):
    attempt,_,_=run(db_session,enqueue(db_session,setup[3][0]))
    lid=attempt.execution['prompt']['llm_log_id']
    graph=AssetDebugService(db_session,chapter.novel_id).anchor('llm_log',lid)
    assert any(n['key']==f'media_attempt:{attempt.id}' for n in graph['nodes'])
    original=db_session.get(LLMLog,lid)
    unrelated=LLMLog(provider=original.provider,model=original.model,task_type=original.task_type,status='success',
                     novel_id=original.novel_id,chapter_id=original.chapter_id,system_prompt=original.system_prompt,
                     user_prompt=original.user_prompt,response=original.response)
    db_session.add(unrelated);db_session.commit()
    graph=AssetDebugService(db_session,chapter.novel_id).anchor('llm_log',unrelated.id)
    assert not any(n['kind']=='media_attempt' for n in graph['nodes'])


def test_video_ai_call_preserves_explicit_log_pointer(db_session,chapter,setup):
    from app.services.video_director_ai import append_video_ai_call
    shot=setup[3][0]
    log=LLMLog(provider='test',model='planner',status='success',task_type='video_mode_recommender',
               novel_id=chapter.novel_id,chapter_id=chapter.id,user_prompt='saved planner input',response='saved output')
    db_session.add(log);db_session.commit()
    plan=append_video_ai_call(shot,{'step':'07','task_type':'video_mode_recommender','llm_log_id':log.id,'status':'success'})
    db_session.commit()
    assert plan['ai_calls'][-1]['llm_log_id']==log.id
    graph=AssetDebugService(db_session,chapter.novel_id).anchor('llm_log',log.id)
    assert {'from':f'shot:{shot.id}','to':f'llm_log:{log.id}','path':'video_director_plan.ai_calls[0].llm_log_id'} in graph['edges']


@pytest.mark.parametrize('raw',['[null]','["wrong"]','[{"label":"missing url"}]'])
def test_invalid_reference_members_do_not_crash_or_look_empty(db_session,chapter,raw):
    task=Task(name='bad members',type='shot_image',status='failed',novel_id=chapter.novel_id,reference_images=raw)
    db_session.add(task);db_session.commit()
    data=TaskService.format_task_detail(task)
    assert data['referenceImages'] is None and data['evidence']['reference_images']['state']=='WRONG_TYPE'
