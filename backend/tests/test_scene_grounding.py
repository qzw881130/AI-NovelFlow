"""Read-only Scene grounding audit without a SceneOccurrence model."""
from copy import deepcopy
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.chapter_shot_splits import router
from app.core.database import get_db
from app.models.chapter_shot_split import ChapterShotSplitRun, ShotSource
from app.models.llm_log import LLMLog
from app.models.shot import Shot
from app.models.task import Task
from app.services.scene_grounding import (CONTEXT_INFERRED, DIRECT_LOCAL, SCENE_TRANSITION,
    SCENE_UNRESOLVED, classify_plan, classify_run)
from app.services.chapter_asset_parse_service import digest
from test_chapter_shot_split import LLM, chapter, db_session, execute, fixture, output


def shot(index,text,scene):
    return {'id':index,'source_citations':[{'text':text}],'source_ownership':{'text':text},'scene':scene}


def test_scene_grounding_four_states_are_diagnostic_and_only_direct_is_authorized():
    parts=[('进入甲地。','甲地'),('众人继续商议。','甲地'),('前往乙地。进入乙地。','甲地'),
        ('众人继续整军。','乙地'),('地点没有交代。','丙地'),('来见某人。','丙地')]
    text=''.join(value for value,_ in parts)
    basis={'source':{'content':text},'scope':{'scenes':{'bindings':[
        {'name':'甲地','assetId':'a','membershipEvidence':[{'text':'进入甲地。'}]},
        {'name':'乙地','assetId':'b','membershipEvidence':[{'text':'进入乙地。'}]},
        {'name':'丙地','assetId':'c','membershipEvidence':[]},
    ]}}}
    plan={'shots':[shot(index,value,scene) for index,(value,scene) in enumerate(parts,1)]}
    frozen=deepcopy((plan,basis));report=classify_plan(plan,basis)
    assert [item['classification'] for item in report['shots']]==[
        DIRECT_LOCAL,CONTEXT_INFERRED,SCENE_TRANSITION,CONTEXT_INFERRED,SCENE_UNRESOLVED,SCENE_TRANSITION]
    assert report['counts']=={DIRECT_LOCAL:1,CONTEXT_INFERRED:2,SCENE_TRANSITION:2,
        SCENE_UNRESOLVED:1,'HUMAN_REQUIRED':5,'total':6}
    assert [item['autoAuthorized'] for item in report['shots']]==[True,False,False,False,False,False]
    assert (plan,basis)==frozen

    empty_authority=deepcopy(basis);empty_authority['scope']['scenes']['bindings'][0].update(
        membershipEvidence=[],sourceEvidence=[{'text':'进入甲地。'}])
    assert classify_plan(plan,empty_authority)['counts'][DIRECT_LOCAL]==0


def rejected_scene_run(db,chapter):
    value=output();value['shots'][0]['scene']='不存在';value['scenes']=['不存在','桃园']
    result=execute(db,chapter,LLM(db,value));assert not result['success']
    return result['data']['splitRunId']


def test_saved_run_scene_grounding_api_is_read_only(db_session,chapter,fixture):
    run_id=rejected_scene_run(db_session,chapter)
    before={'runs':db_session.query(ChapterShotSplitRun).count(),'shots':db_session.query(Shot).count(),
        'sources':db_session.query(ShotSource).count(),'chapter':{key:getattr(chapter,key) for key in ('status','progress','parsed_data')}}
    report=classify_run(db_session,chapter.novel_id,chapter.id,run_id)
    assert report['counts']['total']==2 and report['counts']['HUMAN_REQUIRED']==2
    assert report['bindingEvidenceIsOccurrenceProof'] is False and report['auditEligibleForAuthorization'] is True
    app=FastAPI();app.include_router(router,prefix='/api/novels');app.dependency_overrides[get_db]=lambda:db_session
    with TestClient(app) as client:
        data=client.get(f'/api/novels/{chapter.novel_id}/chapters/{chapter.id}/split-runs/{run_id}/scene-grounding').json()['data']
    assert data==report
    after={'runs':db_session.query(ChapterShotSplitRun).count(),'shots':db_session.query(Shot).count(),
        'sources':db_session.query(ShotSource).count(),'chapter':{key:getattr(chapter,key) for key in ('status','progress','parsed_data')}}
    assert after==before


def test_scene_grounding_rejected_run_provenance_and_stale_source_fail_closed(db_session,chapter,fixture):
    run_id=rejected_scene_run(db_session,chapter);run=db_session.get(ChapterShotSplitRun,run_id)
    chapter.content+='变化';db_session.commit()
    report=classify_run(db_session,chapter.novel_id,chapter.id,run_id)
    assert not report['sourceCurrent'] and not any(item['autoAuthorized'] for item in report['shots'])
    chapter.content=run.inputs['basis']['source']['content'];db_session.commit()
    task=db_session.get(Task,run.task_id);task.status='completed';db_session.commit()
    with pytest.raises(Exception,match='SCENE_GROUNDING_REJECTED_RUN_REQUIRED'):
        classify_run(db_session,chapter.novel_id,chapter.id,run_id)
    task.status='failed';log=db_session.get(LLMLog,run.call['llm_log_id']);log.response='tampered';db_session.commit()
    with pytest.raises(Exception,match='SHOT_SPLIT_PROVENANCE_INVALID'):
        classify_run(db_session,chapter.novel_id,chapter.id,run_id)


def test_scene_grounding_rejects_impossible_run_profile_tuple(db_session,chapter,fixture):
    run_id=rejected_scene_run(db_session,chapter);run=db_session.get(ChapterShotSplitRun,run_id)
    run.inputs={**run.inputs,'source_window_version':'appearance-source-windows-v1'}
    run.input_hash=digest(run.inputs)
    task=db_session.get(Task,run.task_id);meta=json.loads(task.metadata_json);meta['input_hash']=run.input_hash
    task.metadata_json=json.dumps(meta);db_session.commit()
    with pytest.raises(Exception,match='SCENE_GROUNDING_RUN_VERSION_UNSUPPORTED'):
        classify_run(db_session,chapter.novel_id,chapter.id,run_id)


def test_overlapping_ranges_never_infer_scene_continuity():
    text='进入甲地。继续商议。';basis={'source':{'content':text},'scope':{'scenes':{'bindings':[
        {'name':'甲地','assetId':'a','membershipEvidence':[]}]}}}
    plan={'shots':[{'id':1,'source_citations':[{'text':'进入甲地。继续'}],
        'source_ownership':{'text':'进入甲地。继续'},'scene':'甲地'},
        {'id':2,'source_citations':[{'text':'继续商议。'}],'source_ownership':{'text':'继续商议。'},'scene':'甲地'}]}
    report=classify_plan(plan,basis)
    assert report['shots'][1]['classification']==SCENE_UNRESOLVED
