"""Phase5: authoritative chapter memberships, source proof and atomic replacement."""
import asyncio
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from uuid import uuid4
import pytest
from fastapi import HTTPException, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, create_engine, inspect
from app.models.novel import Character, Scene, Prop
from app.models.task import Task
from app.models.llm_log import LLMLog
from app.models.shot import Shot
from app.models.prompt_template import PromptTemplate
from app.models.audio_drive import ShotAudioEvent
from app.models.chapter_shot_split import ChapterShotSplitRun as Run, ShotSource
from app.services.chapter_scope import (OWNERSHIP_VERSION,SOURCE_WINDOW_VERSION,collect_scope,request_prompts,locate_ranges,
    validate_plan,SplitReview)
from app.schemas.chapter_shot_split import parse_output
from app.services.chapter_shot_split_service import (MAX_REPAIR_ROUNDS_PER_ROOT_PLAN,ChapterShotSplitService,
    HUMAN_CORRECTION_VERSION,checked_run,checked_source,collect_repairable_inventory,split_state)
from app.repositories.task import TaskRepository
from app.services.task_service import TaskService
from app.services.appearance_timeline_service import AppearanceTimelineService
from app.services.chapter_asset_parse_service import digest
from app.core.database import get_db
from test_appearance_timeline import db_session, chapter, prepare, change
from test_asset_resolution import extract, resolve, row_snapshot

TEXT = '🐺刘备在桃园站定。刘备披甲，说：“出发！”'


@pytest.fixture
def fixture(db_session, chapter):
    actor = prepare(db_session, chapter, TEXT, [change('刘备披甲')])
    extract(db_session,chapter,[{"name":"桃园","description":"园林","setting":"桃树","source_evidence":[{"text":"桃园"}]}],"scenes")
    assert resolve(db_session,chapter,kinds=["scenes"])["success"]
    extract(db_session,chapter,[],"props");assert resolve(db_session,chapter,kinds=["props"])["success"]
    assert AppearanceTimelineService(db_session).build(chapter.novel_id,chapter.id)["success"]
    db_session.add(PromptTemplate(name="Shot Director",type="chapter_split",is_system=True,is_active=True,
        template=(Path(__file__).parents[1]/"prompt_templates/05_NovelFlow_VideoDirector_ShotDirector_V1.txt").read_text()))
    db_session.commit()
    return actor


def shot(index, text, speaking=False):
    dialogues=[{"order":1,"character_name":"刘备","text":"出发！","emotion_prompt":"坚定"}] if speaking else []
    audio=[{"order":1,"type":"DIALOGUE","voice_owner":"刘备","visible_speaker":"刘备","requires_visible_lipsync":True,
        "text":"出发！","emotion_prompt":"坚定","pause_after":"NONE","treatment_ref":"speech"}] if speaking else []
    treatments=[{'key':'action','type':'VISUAL','source_evidence':[{'text':text.removesuffix('“出发！”')}],
                 'visual_targets':['video_description']}]
    if speaking:treatments.append({'key':'speech','type':'DIALOGUE','source_evidence':[{'text':'“出发！”'}]})
    return {"id":index,"source_evidence":[{"text":text}],"description":"Scene: 桃园\nCharacters:\n- 刘备: 画面中央站立\nAction: 静立",
        "video_description":"从静态首帧继续，刘备开口说话。" if speaking else "从静态首帧继续，刘备注视前方，全程不产生说话口型。",
        "characters":["刘备"],"scene":"桃园","props":[],"duration":8,"continuity_mode":"NORMAL","dialogues":dialogues,"audio_events":audio,
        "source_treatments":treatments}


def output():
    return {"chapter":"第一回","characters":["刘备"],"scenes":["桃园"],"props":[],"unresolved_assets":[],
        "shots":[shot(1,TEXT[:TEXT.index('刘备披甲')]),shot(2,TEXT[TEXT.index('刘备披甲'):],True)]}


class LLM:
    provider, model = "test", "shot-director-test"
    def __init__(self, db, value=None, during=None, log=True, fail=False):
        self.db,self.value,self.during,self.log,self.fail = db,value if value is not None else output(),during,log,fail
        self.calls=[]
    async def chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        if self.during:
            result=self.during()
            if asyncio.iscoroutine(result):await result
        if self.fail:return {"success":False,"error":"MODEL_ERROR"}
        raw = self.value if isinstance(self.value,str) else json.dumps(self.value,ensure_ascii=False)
        log_id=str(uuid4())
        if self.log:
            self.db.add(LLMLog(id=log_id,provider=self.provider,model=self.model,status="success",task_type="split_chapter",
                novel_id=kwargs['novel_id'],chapter_id=kwargs['chapter_id'],system_prompt=kwargs['system_prompt'],user_prompt=kwargs['user_content'],response=raw,
                prompt_template_name=kwargs.get('prompt_template_name')))
            self.db.commit()
        return {"success":True,"content":raw,"llm_log_id":log_id if self.log else None}


class SequenceLLM(LLM):
    def __init__(self,db,values):
        super().__init__(db);self.values=values
    async def chat_completion(self,**kwargs):
        if len(self.calls)>=len(self.values):raise AssertionError('repair budget exceeded')
        self.value=self.values[len(self.calls)]
        result=await super().chat_completion(**kwargs)
        if self.log:
            log=self.db.get(LLMLog,result['llm_log_id']);log.task_type=kwargs['task_type'];self.db.commit()
        return result


def execute(db, chapter, llm=None):
    return asyncio.run(ChapterShotSplitService(db,llm or LLM(db)).split(chapter.novel_id,chapter.id))


def add_repair_template(db):
    row=PromptTemplate(name='分镜契约自动修复 V1',type='shot_contract_repair',is_system=True,is_active=True,
        template=(Path(__file__).parents[1]/'prompt_templates/shot_contract_auto_repair_v1.txt').read_text())
    db.add(row);db.commit();return row


def closure_failure():
    value=output();value['shots'][0]['description']='Scene: 桃园\nCharacters:\nAction: 静立'
    return value


def closure_patch(visual_description='画面中央站立，面向前方，保持静态警戒姿态'):
    return {'repair_type':'SHOT_VISIBLE_CHARACTER_CLOSURE','repairs':[{
        'shot_index':1,'field':'description','characters':[{'name':'刘备','visual_description':visual_description}],
    }]}


def governed_crossing_plan():
    value=shot(1,TEXT,True);value['duration']=16
    value['description']='Scene: 桃园\nCharacters:\nAction: 静立'
    evidence=value.pop('source_evidence');value['source_citations']=evidence
    value['source_ownership']={'text':TEXT}
    return {'source_contract_version':OWNERSHIP_VERSION,'chapter':'第一回','characters':['刘备'],
        'scenes':['桃园'],'props':[],'unresolved_assets':[],'shots':[value]}


def governed_boundary_patch(*,valid_scene=True):
    replacements=deepcopy(output()['shots'])
    for item in replacements:
        evidence=item.pop('source_evidence');item['source_citations']=evidence
        item['source_ownership']={'text':evidence[0]['text']}
    replacements[1]['description']='Scene: 桃园\nCharacters:\nAction: 说话'
    if not valid_scene:replacements[1]['scene']='未绑定场景'
    return {'repair_type':'SHOT_CROSSES_APPEARANCE_BOUNDARY','repairs':[
        {'shot_index':1,'replacements':replacements}]}


def governed_closure_patch(shot_index):
    return {'repair_type':'SHOT_VISIBLE_CHARACTER_CLOSURE','repairs':[
        {'shot_index':shot_index,'field':'description','characters':[
            {'name':'刘备','visual_description':'画面中央站立，面向行动区域，保持静态可见姿态'}]}]}


def execute_governed(db,chapter,llm):
    return asyncio.run(ChapterShotSplitService(db,llm).split(
        chapter.novel_id,chapter.id,source_contract_version=OWNERSHIP_VERSION))


def test_auto_repair_closure_once_then_full_validation_publishes(db_session,chapter,fixture):
    template=add_repair_template(db_session);llm=SequenceLLM(db_session,[closure_failure(),closure_patch()])
    result=execute(db_session,chapter,llm);assert result['success'],result
    assert len(llm.calls)==2 and llm.calls[1]['task_type']=='shot_contract_auto_repair'
    assert llm.calls[1]['prompt_template_name']==template.name
    runs=db_session.query(Run).order_by(Run.created_at,Run.id).all()
    assert [run.status for run in runs]==['NEEDS_REVIEW','SUCCEEDED']
    assert runs[0].issues[0]['repairClassification']=='AUTO_REPAIRABLE'
    assert len(runs[0].issues[0]['violationInventory'])==1
    repair=runs[1];assert repair.inputs['auto_repair']['parent_run_id']==runs[0].id
    assert repair.inputs['auto_repair']['template']['id']==template.id
    assert repair.result['auto_repair']['outcome']=='REPAIRED'
    assert repair.result['auto_repair']['violationsBefore']==1 and repair.result['auto_repair']['violationsAfter']==0
    assert db_session.query(ShotSource).count()==2 and split_state(db_session,chapter.novel_id,chapter.id)['phase5Ready']
    log=db_session.get(LLMLog,repair.call['llm_log_id'])
    assert log.execution_metadata['outcome']=='REPAIRED' and log.execution_metadata['attempt']==log.execution_metadata['budget']==1


def test_multi_family_governance_replays_boundary_then_closure_and_publishes(db_session,chapter,fixture):
    add_repair_template(db_session)
    llm=SequenceLLM(db_session,[governed_crossing_plan(),governed_boundary_patch(),governed_closure_patch(2)])
    result=execute_governed(db_session,chapter,llm)
    assert result['success'],result
    runs=db_session.query(Run).order_by(Run.created_at,Run.id).all()
    assert [run.status for run in runs]==['NEEDS_REVIEW','NEEDS_REVIEW','SUCCEEDED']
    assert len(runs[0].issues[0]['repairInventory']['SHOT_CROSSES_APPEARANCE_BOUNDARY'])==1
    assert len(runs[0].issues[0]['repairInventory']['SHOT_VISIBLE_CHARACTER_CLOSURE'])==1
    assert [call['task_type'] for call in llm.calls]==[
        'split_chapter','shot_contract_auto_repair','shot_contract_auto_repair']
    first,second=runs[1:];first_auto=first.inputs['auto_repair'];second_auto=second.inputs['auto_repair']
    assert first_auto['repair_plan']['repair_type']=='SHOT_CROSSES_APPEARANCE_BOUNDARY'
    assert second_auto['repair_plan']['repair_type']=='SHOT_VISIBLE_CHARACTER_CLOSURE'
    assert first_auto['governance']['round']==1 and second_auto['governance']['round']==2
    assert first_auto['governance']['root_run_id']==second_auto['governance']['root_run_id']==runs[0].id
    assert second_auto['governance']['predecessor_run_id']==first.id
    assert first.issues[0]['repair']['outcome']=='REPAIRED_WITH_REMAINING_FINDINGS'
    assert second.result['auto_repair']['outcome']=='REPAIRED'
    assert second.result['auto_repair']['governance']['attemptedKeys']==[
        {'root_shot_index':1,'violation_family':'SHOT_CROSSES_APPEARANCE_BOUNDARY'},
        {'root_shot_index':1,'violation_family':'SHOT_VISIBLE_CHARACTER_CLOSURE'}]
    assert second_auto['governance']['max_rounds']==MAX_REPAIR_ROUNDS_PER_ROOT_PLAN==3
    assert checked_run(db_session,second)==second.inputs['basis']
    assert split_state(db_session,chapter.novel_id,chapter.id)['phase5Ready']
    from app.api.tasks import delete_task
    for protected in runs:
        with pytest.raises(HTTPException,match='SHOT_SPLIT_LINEAGE_TASK_REQUIRED'):
            asyncio.run(delete_task(protected.task_id,TaskService(db_session),TaskRepository(db_session)))


def test_failed_family_key_does_not_consume_independent_closure_or_repeat(db_session,chapter,fixture):
    add_repair_template(db_session)
    llm=SequenceLLM(db_session,[governed_crossing_plan(),governed_boundary_patch(valid_scene=False),
        governed_closure_patch(1)])
    result=execute_governed(db_session,chapter,llm)
    assert not result['success'] and len(llm.calls)==3
    runs=db_session.query(Run).order_by(Run.created_at,Run.id).all()
    assert [run.status for run in runs]==['NEEDS_REVIEW']*3
    assert [run.inputs.get('auto_repair',{}).get('repair_plan',{}).get('repair_type') for run in runs]==[
        None,'SHOT_CROSSES_APPEARANCE_BOUNDARY','SHOT_VISIBLE_CHARACTER_CLOSURE']
    assert runs[1].issues[0]['repair']['outcome']=='STILL_INVALID'
    assert runs[2].issues[0]['repair']['outcome']=='REPAIRED_WITH_REMAINING_FINDINGS'
    blocked=SequenceLLM(db_session,[]);again=execute_governed(db_session,chapter,blocked)
    assert not again['success'] and again['message']=='SHOT_CONTRACT_REPAIR_BUDGET_EXHAUSTED'
    assert blocked.calls==[] and db_session.query(Run).count()==3


def test_governance_resumes_from_replayed_candidate_after_process_boundary(db_session,chapter,fixture):
    add_repair_template(db_session);first_llm=SequenceLLM(
        db_session,[governed_crossing_plan(),governed_boundary_patch()])
    service=ChapterShotSplitService(db_session,first_llm)
    first=asyncio.run(service._split_once(chapter.novel_id,chapter.id,
        source_contract_version=OWNERSHIP_VERSION));context=first.pop('_auto_repair_context')
    second=asyncio.run(service._split_once(chapter.novel_id,chapter.id,repair_previous=False,
        preserve_structure=False,source_contract_version=OWNERSHIP_VERSION,_auto_repair=context))
    assert not second['success'] and second['_auto_repair_context']['governance']['round']==2
    resumed=SequenceLLM(db_session,[governed_closure_patch(2)])
    result=execute_governed(db_session,chapter,resumed)
    assert result['success'] and len(resumed.calls)==1
    final=db_session.get(Run,result['data']['splitRunId'])
    assert final.inputs['auto_repair']['governance']['round']==2
    assert checked_run(db_session,final)==final.inputs['basis']


def test_explicit_fresh_request_cannot_reset_identical_root_target_ledger(db_session,chapter,fixture):
    add_repair_template(db_session);initial=SequenceLLM(db_session,[governed_crossing_plan(),
        governed_boundary_patch(valid_scene=False),governed_closure_patch(1)])
    assert not execute_governed(db_session,chapter,initial)['success']
    count=db_session.query(Run).count();fresh=SequenceLLM(db_session,[governed_crossing_plan()])
    result=asyncio.run(ChapterShotSplitService(db_session,fresh).split(
        chapter.novel_id,chapter.id,repair_previous=False,source_contract_version=OWNERSHIP_VERSION))
    assert not result['success'] and len(fresh.calls)==1
    assert db_session.query(Run).count()==count+1
    latest=db_session.query(Run).order_by(Run.created_at.desc(),Run.id.desc()).first()
    assert latest.issues[0]['repairClassification']=='HUMAN_REQUIRED'
    assert not latest.inputs.get('auto_repair')


def test_interrupted_round_consumes_only_its_reserved_target_key(db_session,chapter,fixture):
    add_repair_template(db_session);root_llm=SequenceLLM(db_session,[governed_crossing_plan()])
    service=ChapterShotSplitService(db_session,root_llm)
    root=asyncio.run(service._split_once(chapter.novel_id,chapter.id,
        source_contract_version=OWNERSHIP_VERSION));context=root.pop('_auto_repair_context')
    interrupted=asyncio.run(ChapterShotSplitService(db_session,LLM(db_session,fail=True))._split_once(
        chapter.novel_id,chapter.id,repair_previous=False,preserve_structure=False,
        source_contract_version=OWNERSHIP_VERSION,_auto_repair=context))
    assert not interrupted['success']
    failed=db_session.query(Run).order_by(Run.created_at.desc(),Run.id.desc()).first()
    assert failed.status=='NEEDS_REVIEW' and failed.issues[0]['code']=='REPAIR_INTERRUPTED'
    closure=SequenceLLM(db_session,[governed_closure_patch(1)])
    result=execute_governed(db_session,chapter,closure)
    assert not result['success'] and len(closure.calls)==1
    latest=db_session.query(Run).order_by(Run.created_at.desc(),Run.id.desc()).first()
    assert latest.inputs['auto_repair']['repair_plan']['repair_type']=='SHOT_VISIBLE_CHARACTER_CLOSURE'
    attempted=latest.issues[0]['repair']['governance']['attemptedKeys']
    assert attempted==[
        {'root_shot_index':1,'violation_family':'SHOT_CROSSES_APPEARANCE_BOUNDARY'},
        {'root_shot_index':1,'violation_family':'SHOT_VISIBLE_CHARACTER_CLOSURE'}]


def test_cancelled_round_is_replayable_and_does_not_strand_other_family(db_session,chapter,fixture):
    add_repair_template(db_session);service=ChapterShotSplitService(
        db_session,SequenceLLM(db_session,[governed_crossing_plan()]))
    root=asyncio.run(service._split_once(chapter.novel_id,chapter.id,
        source_contract_version=OWNERSHIP_VERSION));context=root.pop('_auto_repair_context')

    async def cancel_current():
        task=db_session.query(Task).filter_by(type='chapter_shot_split',status='running').one()
        cancelled=await TaskService(db_session).cancel_task(task.id)
        assert cancelled['success']

    cancelled_llm=SequenceLLM(db_session,[governed_boundary_patch()]);cancelled_llm.during=cancel_current
    cancelled=asyncio.run(ChapterShotSplitService(db_session,cancelled_llm)._split_once(
        chapter.novel_id,chapter.id,repair_previous=False,preserve_structure=False,
        source_contract_version=OWNERSHIP_VERSION,_auto_repair=context))
    assert not cancelled['success']
    interrupted=db_session.query(Run).order_by(Run.created_at.desc(),Run.id.desc()).first()
    assert interrupted.status=='NEEDS_REVIEW' and interrupted.issues[0]['code']=='REPAIR_INTERRUPTED'
    interrupted_task=db_session.get(Task,interrupted.task_id);marker=json.loads(interrupted_task.metadata_json)['auto_repair_interruption']
    governance=interrupted.inputs['auto_repair']['governance']
    assert marker=={'version':'root-lineage-auto-repair-v1','rootRunId':governance['root_run_id'],
        'predecessorRunId':governance['predecessor_run_id'],'round':governance['round'],
        'targetKeys':governance['target_keys'],'message':interrupted.issues[0]['message']}
    closure=SequenceLLM(db_session,[governed_closure_patch(1)])
    result=execute_governed(db_session,chapter,closure)
    assert not result['success'] and len(closure.calls)==1
    latest=db_session.query(Run).order_by(Run.created_at.desc(),Run.id.desc()).first()
    assert latest.inputs['auto_repair']['repair_plan']['repair_type']=='SHOT_VISIBLE_CHARACTER_CLOSURE'


def test_provider_error_log_reserves_target_and_allows_next_family(db_session,chapter,fixture):
    add_repair_template(db_session);service=ChapterShotSplitService(
        db_session,SequenceLLM(db_session,[governed_crossing_plan()]))
    root=asyncio.run(service._split_once(chapter.novel_id,chapter.id,
        source_contract_version=OWNERSHIP_VERSION));context=root.pop('_auto_repair_context')

    class ProviderErrorLLM:
        provider,model='test','shot-director-test'
        async def chat_completion(self,**kwargs):
            log=LLMLog(id=str(uuid4()),provider=self.provider,model=self.model,status='error',
                task_type=kwargs['task_type'],novel_id=kwargs['novel_id'],chapter_id=kwargs['chapter_id'],
                system_prompt=kwargs['system_prompt'],user_prompt=kwargs['user_content'],response=None,
                prompt_template_name=kwargs.get('prompt_template_name'))
            db_session.add(log);db_session.commit()
            return {'success':False,'content':'','error':'PROVIDER_TIMEOUT','llm_log_id':log.id}

    interrupted=asyncio.run(ChapterShotSplitService(db_session,ProviderErrorLLM())._split_once(
        chapter.novel_id,chapter.id,repair_previous=False,preserve_structure=False,
        source_contract_version=OWNERSHIP_VERSION,_auto_repair=context))
    assert not interrupted['success']
    failed=db_session.query(Run).order_by(Run.created_at.desc(),Run.id.desc()).first()
    assert failed.status=='NEEDS_REVIEW' and failed.issues[0]['code']=='REPAIR_INTERRUPTED'
    closure=SequenceLLM(db_session,[governed_closure_patch(1)])
    result=execute_governed(db_session,chapter,closure)
    assert not result['success'] and len(closure.calls)==1
    latest=db_session.query(Run).order_by(Run.created_at.desc(),Run.id.desc()).first()
    assert latest.inputs['auto_repair']['repair_plan']['repair_type']=='SHOT_VISIBLE_CHARACTER_CLOSURE'


def test_interruption_receipt_cannot_replace_completed_repair_delta(db_session,chapter,fixture):
    add_repair_template(db_session);llm=SequenceLLM(db_session,[governed_crossing_plan(),
        governed_boundary_patch(valid_scene=False),governed_closure_patch(1)])
    assert not execute_governed(db_session,chapter,llm)['success']
    latest=db_session.query(Run).order_by(Run.created_at.desc(),Run.id.desc()).first()
    from app.services.chapter_shot_split_service import _interrupted_repair_issue
    latest.issues=[_interrupted_repair_issue(latest,'forged')];db_session.commit()
    with pytest.raises(HTTPException,match='AUTO_REPAIR_GOVERNANCE'):
        asyncio.run(ChapterShotSplitService(db_session,SequenceLLM(db_session,[])).split(
            chapter.novel_id,chapter.id,source_contract_version=OWNERSHIP_VERSION))


def test_direct_split_replay_binds_frozen_provider_and_model(db_session,chapter,fixture):
    result=execute(db_session,chapter);assert result['success']
    run=db_session.get(Run,result['data']['splitRunId']);log=db_session.get(LLMLog,run.call['llm_log_id'])
    log.provider='changed-provider';db_session.commit()
    assert not split_state(db_session,chapter.novel_id,chapter.id)['phase5Ready']


def test_repair_inventory_excludes_degraded_card_visual_contract():
    card={'completion_disposition':'DEGRADED_NARRATION_CARD','description':'neutral card',
        'video_description':'neutral card','characters':[]}
    normal={'description':'Scene: 桃园\nCharacters:\nAction: 静立','video_description':'保持静止。',
        'characters':['刘备']}
    inventory=collect_repairable_inventory({'shots':[card,normal]},{})
    assert inventory['SHOT_CROSSES_APPEARANCE_BOUNDARY']==[]
    assert [(item['shot_index'],item['missing_characters']) for item in
        inventory['SHOT_VISIBLE_CHARACTER_CLOSURE']]==[(2,['刘备'])]


def test_human_authored_root_can_enter_existing_governance_without_fake_llm_log(db_session,chapter,fixture):
    add_repair_template(db_session);root_llm=SequenceLLM(db_session,[governed_crossing_plan()])
    first=asyncio.run(ChapterShotSplitService(db_session,root_llm)._split_once(
        chapter.novel_id,chapter.id,source_contract_version=OWNERSHIP_VERSION))
    parent=db_session.get(Run,first['data']['splitRunId']);candidate=parse_output(
        json.dumps(governed_crossing_plan(),ensure_ascii=False),OWNERSHIP_VERSION,SOURCE_WINDOW_VERSION);now=datetime.utcnow()
    proof={'version':HUMAN_CORRECTION_VERSION,'parent_run_id':parent.id,'parent_input_hash':parent.input_hash,
        'parent_response_hash':digest(parent.call['response']),'after_plan_hash':digest(candidate),
        'authorization':'TEST_HUMAN_DECISION'}
    inputs={**deepcopy(parent.inputs),'repair':None,'repair_previous':False,
        'human_authored_correction':proof}
    run=Run(id=str(uuid4()),novel_id=parent.novel_id,chapter_id=parent.chapter_id,task_id=str(uuid4()),version=parent.version,
        status='NEEDS_REVIEW',inputs=inputs,input_hash=digest(inputs),call={'kind':'HUMAN_AUTHORED_PLAN_CORRECTION',
            'success':True,'response':json.dumps(candidate,ensure_ascii=False,separators=(',',':'))},
        issues=[{'code':'NEEDS_REVIEW','message':'HUMAN_CORRECTION_REQUIRES_EXISTING_REPAIR'}],
        expires_at=now,completed_at=now)
    task=Task(id=run.task_id,type='chapter_shot_split',status='failed',novel_id=parent.novel_id,
        chapter_id=parent.chapter_id,name='human correction',error_message='NEEDS_REVIEW',completed_at=now,
        metadata_json=json.dumps({'execution_purpose':'production','delivery_mode':'HUMAN_AUTHORED_PLAN_CORRECTION',
            'split_run_id':run.id,'input_hash':run.input_hash}))
    db_session.add_all([task,run]);db_session.commit()
    result=execute_governed(db_session,chapter,SequenceLLM(
        db_session,[governed_boundary_patch(),governed_closure_patch(2)]))
    assert result['success'],json.dumps(result,ensure_ascii=False)
    final=db_session.get(Run,result['data']['splitRunId'])
    assert final.inputs['auto_repair']['governance']['root_run_id']==run.id
    assert checked_run(db_session,final)==final.inputs['basis']


def test_auto_repair_identical_response_is_no_effect_and_never_loops(db_session,chapter,fixture):
    add_repair_template(db_session);bad=json.dumps(closure_failure(),ensure_ascii=False,separators=(',',':'))
    llm=SequenceLLM(db_session,[bad,bad]);result=execute(db_session,chapter,llm)
    assert not result['success'] and result['data']['autoRepair']['outcome']=='REPAIR_NO_EFFECT'
    assert len(llm.calls)==2 and db_session.query(Run).count()==2
    assert [run.status for run in db_session.query(Run).order_by(Run.created_at,Run.id)]==['NEEDS_REVIEW','NEEDS_REVIEW']
    assert db_session.query(ShotSource).count()==0 and db_session.query(Shot).count()==0
    repair=db_session.query(Run).order_by(Run.created_at.desc(),Run.id.desc()).first()
    log=db_session.get(LLMLog,repair.call['llm_log_id'])
    assert log.execution_metadata['beforeHash']==log.execution_metadata['afterHash']
    assert log.execution_metadata['violationsBefore']==log.execution_metadata['violationsAfter']==1
    blocked=SequenceLLM(db_session,[]);again=execute(db_session,chapter,blocked)
    assert not again['success'] and again['message']=='SHOT_CONTRACT_REPAIR_BUDGET_EXHAUSTED'
    assert again['data']['autoRepair']['budgetExhausted'] is True and blocked.calls==[]
    assert db_session.query(Run).count()==2


def test_auto_repair_new_format_violation_stops_without_publication(db_session,chapter,fixture):
    add_repair_template(db_session)
    llm=SequenceLLM(db_session,[closure_failure(),closure_patch('静立\n未标明归属的游离说明')])
    result=execute(db_session,chapter,llm)
    assert not result['success'] and result['data']['autoRepair']['outcome']=='NEW_VIOLATIONS'
    assert 'SHOT_CHARACTER_DESCRIPTION_FORMAT' in result['data']['autoRepair']['validatorError']
    assert len(llm.calls)==2 and db_session.query(ShotSource).count()==db_session.query(Shot).count()==0
    assert db_session.query(Run).order_by(Run.created_at.desc(),Run.id.desc()).first().status=='NEEDS_REVIEW'


def test_auto_repair_uses_configured_registry_prompt_and_dynamic_context(db_session,chapter,fixture):
    custom=PromptTemplate(name='Book Repair Prompt',type='shot_contract_repair',is_system=False,is_active=True,
        template='Fixed registry-managed repair system prompt. Return the required strict JSON patch only.')
    db_session.add(custom);db_session.flush();chapter.novel.shot_contract_repair_prompt_template_id=custom.id;db_session.commit()
    llm=SequenceLLM(db_session,[closure_failure(),closure_patch()]);result=execute(db_session,chapter,llm)
    assert result['success'],result
    repair=db_session.get(Run,result['data']['splitRunId']);frozen=repair.inputs['auto_repair']['template']
    assert frozen['id']==custom.id and frozen['name']==custom.name and frozen['configured'] is True
    assert frozen['hash']==digest(custom.template) and llm.calls[1]['system_prompt']==custom.template
    context=json.loads(llm.calls[1]['user_content'])
    assert set(context)=={'contract_version','original_shot_plan','repair_plan'}
    assert context['repair_plan']['targets'][0]['missing_characters']==['刘备']
    assert '刘备' not in llm.calls[1]['system_prompt']


def test_configured_missing_auto_repair_template_never_falls_back(db_session,chapter,fixture):
    chapter.novel.shot_contract_repair_prompt_template_id='missing-repair-template';db_session.commit()
    llm=SequenceLLM(db_session,[closure_failure()]);result=execute(db_session,chapter,llm)
    assert not result['success'] and result['data']['autoRepair']['outcome']=='UNAVAILABLE'
    assert result['data']['autoRepair']['detail']=='SHOT_CONTRACT_REPAIR_TEMPLATE_INVALID'
    assert len(llm.calls)==1 and db_session.query(Run).count()==1 and db_session.query(Shot).count()==0


def test_pre_ar1_rejected_run_enters_one_targeted_repair_without_regeneration(db_session,chapter,fixture):
    first_llm=SequenceLLM(db_session,[closure_failure()]);first=execute(db_session,chapter,first_llm)
    assert not first['success'] and first['data']['autoRepair']['outcome']=='UNAVAILABLE'
    rejected=db_session.query(Run).one();assert len(first_llm.calls)==1
    add_repair_template(db_session)
    repair_llm=SequenceLLM(db_session,[closure_patch()]);result=execute(db_session,chapter,repair_llm)
    assert result['success'],result
    assert len(repair_llm.calls)==1 and repair_llm.calls[0]['task_type']=='shot_contract_auto_repair'
    accepted=db_session.get(Run,result['data']['splitRunId'])
    assert accepted.inputs['auto_repair']['parent_run_id']==rejected.id
    assert db_session.query(Run).count()==2 and accepted.result['auto_repair']['outcome']=='REPAIRED'


@pytest.mark.parametrize('kind',['format','evidence'])
def test_auto_repair_policy_keeps_non_closure_failures_human_required(db_session,chapter,fixture,kind):
    add_repair_template(db_session);bad=output()
    if kind=='format':bad['shots'][0]['description']='Scene: 桃园\nCharacters:\n游离说明\nAction: 静立'
    else:bad['shots'][0]['source_evidence']=[{'text':'不存在的原文'}]
    llm=SequenceLLM(db_session,[bad]);result=execute(db_session,chapter,llm)
    assert not result['success'] and len(llm.calls)==1 and db_session.query(Run).count()==1
    run=db_session.query(Run).one()
    assert run.issues[0].get('repairClassification')!='AUTO_REPAIRABLE'


@pytest.mark.parametrize('target',['parent_log','repair_metadata','task_receipt','composed_hash'])
def test_auto_repair_replay_proof_rejects_tampering(db_session,chapter,fixture,target):
    add_repair_template(db_session);result=execute(db_session,chapter,SequenceLLM(db_session,[closure_failure(),closure_patch()]))
    assert result['success'],result
    repair=db_session.get(Run,result['data']['splitRunId']);parent=db_session.get(Run,repair.inputs['auto_repair']['parent_run_id'])
    if target=='parent_log':db_session.get(LLMLog,parent.call['llm_log_id']).response='changed'
    elif target=='repair_metadata':
        log=db_session.get(LLMLog,repair.call['llm_log_id']);metadata=deepcopy(log.execution_metadata);metadata['outcome']='REPAIR_NO_EFFECT';log.execution_metadata=metadata
    elif target=='task_receipt':
        task=db_session.get(Task,repair.task_id);metadata=json.loads(task.metadata_json);metadata['auto_repair']['resolved']=0;task.metadata_json=json.dumps(metadata)
    else:repair.call={**repair.call,'composed_response_hash':'changed'}
    db_session.commit()
    assert not split_state(db_session,chapter.novel_id,chapter.id)['phase5Ready']


def test_only_chapter_bindings_unicode_sources_audio_ids_and_no_book_updates(db_session,chapter,fixture):
    before={m.__tablename__:[row_snapshot(r) for r in db_session.query(m).order_by(m.id)] for m in (Character,Scene,Prop)}
    llm=LLM(db_session);result=execute(db_session,chapter,llm)
    assert result['success'],result
    user=json.loads(llm.calls[0]['user_content'].split('\n',1)[1])
    assert user['allowed_characters']==['刘备'] and user['allowed_scenes']==['桃园'] and user['allowed_props']==[]
    assert '应保留的旧角色' not in llm.calls[0]['user_content'] and '木杖' not in llm.calls[0]['user_content']
    segments=user['appearance_boundaries'][0]['segments']
    assert segments[1]['opening_text']==TEXT[9:]
    assert segments[0]['closing_text']==TEXT[:9]
    rows=db_session.query(Shot).order_by(Shot.index).all()
    sources=[checked_source(db_session,s) for s in rows]
    assert [(s.source_start,s.source_end) for s in sources]==[(0,9),(9,len(TEXT))]
    assert all(TEXT[r['start']:r['end']]==r['text'] for s in sources for r in s.ranges)
    event=db_session.query(ShotAudioEvent).one()
    assert event.voice_owner_character_id==event.visible_speaker_character_id==fixture.id
    assert sources[1].bindings['characters'][0]['assetId']==fixture.id
    assert split_state(db_session,chapter.novel_id,chapter.id)['phase5Ready']
    assert before=={m.__tablename__:[row_snapshot(r) for r in db_session.query(m).order_by(m.id)] for m in (Character,Scene,Prop)}


def test_unparsed_or_stale_bindings_never_fall_back_to_book(db_session,chapter):
    llm=LLM(db_session)
    with pytest.raises(HTTPException): execute(db_session,chapter,llm)
    assert llm.calls==[] and db_session.query(Run).count()==0


@pytest.mark.parametrize('mutation',['costume','unbound_prop','empty','offset','missing_evidence','overlap','cross_change','quote','voice','speaker','duplicate_json','malformed','summary'])
def test_invalid_plan_keeps_old_shot_and_resources(db_session,chapter,fixture,mutation):
    old=Shot(chapter_id=chapter.id,index=1,description='old accepted',image_url='/old.png',video_url='/old.mp4')
    db_session.add(old);chapter.final_video='/accepted-final.mp4';db_session.commit();before=row_snapshot(old)
    data=output()
    if mutation=='costume': data['shots'][1]['characters']=['刘备战甲版']
    elif mutation=='unbound_prop': data['shots'][0]['props']=['木杖']
    elif mutation=='empty': data['shots']=[]
    elif mutation=='offset': data['shots'][0]['source_start']=0
    elif mutation=='missing_evidence': data['shots'][0]['source_evidence']=[{'text':'刘备身穿白衣'}]
    elif mutation=='overlap': data['shots'][1]['source_evidence']=data['shots'][0]['source_evidence']
    elif mutation=='cross_change': data['shots']=[shot(1,TEXT,True)]
    elif mutation=='quote': data['shots'][1]['dialogues']=[];data['shots'][1]['audio_events']=[]
    elif mutation=='voice': data['shots'][1]['audio_events'][0]['voice_owner']='应保留的旧角色'
    elif mutation=='speaker': data['shots'][1]['audio_events'][0]['visible_speaker']='旁白'
    elif mutation=='duplicate_json': data='{"shots":[],"shots":[]}'
    elif mutation=='malformed': data='```json\n{}\n```'
    elif mutation=='summary': data['characters'].append('应保留的旧角色')
    result=execute(db_session,chapter,LLM(db_session,data))
    assert not result['success'],result
    db_session.refresh(old);db_session.refresh(chapter)
    assert row_snapshot(old)==before and chapter.final_video=='/accepted-final.mp4'
    assert db_session.query(ShotSource).count()==0 and db_session.query(Run).one().status=='NEEDS_REVIEW'


@pytest.mark.parametrize('mutation',['source','binding','task','shot'])
def test_concurrent_changes_block_publication_and_preserve_call(db_session,chapter,fixture,mutation):
    old=Shot(chapter_id=chapter.id,index=1,description='old');db_session.add(old);db_session.commit()
    def modify():
        if mutation=='source': chapter.content+='新增正文'
        elif mutation=='binding':
            from app.models.asset_resolution import ChapterSceneBinding
            db_session.query(ChapterSceneBinding).one().status='STALE'
        elif mutation=='task': db_session.query(Task).filter_by(type='chapter_shot_split').one().status='cancelled'
        else: old.description='user edit'
        db_session.commit()
    result=execute(db_session,chapter,LLM(db_session,during=modify))
    assert not result['success'] and db_session.get(Shot,old.id)
    assert db_session.query(Run).one().call['llm_log_id']


def test_later_failed_attempt_and_manual_shot_edit_invalidate_source(db_session,chapter,fixture):
    assert execute(db_session,chapter)['success']
    first=db_session.query(Shot).order_by(Shot.index).first()
    first.description+='manual edit';db_session.commit()
    with pytest.raises(HTTPException): checked_source(db_session,first)
    assert not split_state(db_session,chapter.novel_id,chapter.id)['phase5Ready']
    assert not execute(db_session,chapter,LLM(db_session,fail=True))['success']
    assert db_session.query(Shot).count()==2
    assert not split_state(db_session,chapter.novel_id,chapter.id)['phase5Ready']


def test_unresolved_upstream_asset_is_review_not_empty_success(db_session,chapter,fixture):
    data=output();data['shots']=[];data['unresolved_assets']=[{'asset_type':'props','name':'铠甲道具','source_evidence':[{'text':'刘备披甲'}],'reason':'未绑定'}]
    result=execute(db_session,chapter,LLM(db_session,data))
    assert not result['success'] and 'UPSTREAM_ASSET_MISSING' in result['message']
    assert db_session.query(Run).one().status=='NEEDS_REVIEW'


def test_explicit_retry_freezes_rejected_draft_feedback_and_revalidates_all(db_session,chapter,fixture):
    bad=output();bad['shots']=[shot(1,TEXT,True)]
    first=execute(db_session,chapter,LLM(db_session,bad));assert not first['success']
    llm=LLM(db_session);second=execute(db_session,chapter,llm);assert second['success'],second
    run=db_session.get(Run,second['data']['splitRunId'])
    assert run.inputs['repair']['run_id']==first['data']['splitRunId']
    assert 'evidence_range' in run.inputs['repair']['validation_error']
    assert run.inputs['basis']['policy']['definition']['repair_instruction'] in llm.calls[0]['system_prompt']
    assert len(llm.calls)==1


def test_repeated_and_disjoint_evidence_are_not_guessed():
    with pytest.raises(SplitReview): locate_ranges('披甲。披甲。',[{'text':'披甲'}])
    with pytest.raises(SplitReview): locate_ranges('甲。中间剧情。乙。',[{'text':'甲。'},{'text':'乙。'}])
    assert locate_ranges('🐺\r\n甲。',[{'text':'甲。'}])[0]['start']==3


def test_database_failure_rolls_back_all_replacement_rows(db_session,chapter,fixture):
    old=Shot(chapter_id=chapter.id,index=1,description='accepted',image_url='/accepted.png')
    db_session.add(old);db_session.commit();old_id=old.id
    def fail(*args): raise RuntimeError('INSERT_FAILURE')
    event.listen(ShotAudioEvent,'before_insert',fail)
    try:
        result=execute(db_session,chapter)
    finally:
        event.remove(ShotAudioEvent,'before_insert',fail)
    assert not result['success'] and 'INSERT_FAILURE' in result['message']
    assert db_session.query(Shot).one().id==old_id and db_session.query(ShotSource).count()==0


def test_second_request_cannot_create_parallel_split_or_orphan_task(db_session,chapter,fixture):
    blocked=[]
    async def duplicate():
        with pytest.raises(HTTPException) as error:
            await ChapterShotSplitService(db_session,LLM(db_session)).split(chapter.novel_id,chapter.id)
        blocked.append(error.value.status_code)
    result=execute(db_session,chapter,LLM(db_session,during=duplicate))
    assert result['success'],result
    assert blocked==[409] and db_session.query(Run).count()==1
    assert db_session.query(Task).filter_by(type='chapter_shot_split').count()==1


def test_narration_is_nonvisual_and_unbound_book_roles_not_needed(db_session,chapter,fixture):
    data=output();data['shots'][0]['audio_events']=[{'order':1,'type':'NARRATION','voice_owner':'旁白','visible_speaker':None,
        'requires_visible_lipsync':False,'text':TEXT[:9],'emotion_prompt':'平静','pause_after':'SHORT','treatment_ref':'action'}]
    data['shots'][0]['source_treatments'][0]['type']='NARRATION'
    result=execute(db_session,chapter,LLM(db_session,data));assert result['success'],result
    narration=db_session.query(ShotAudioEvent).filter_by(event_type='NARRATION').one()
    assert narration.voice_owner_character_id is None and narration.visible_speaker_character_id is None
    assert '旁白' not in db_session.query(Shot).order_by(Shot.index).first().characters


def test_missing_log_never_publishes(db_session,chapter,fixture):
    result=execute(db_session,chapter,LLM(db_session,log=False))
    assert not result['success'] and 'LLM_LOG_UNVERIFIED' in result['message']
    assert db_session.query(Shot).count()==0


def test_configured_missing_template_does_not_fall_back(db_session,chapter,fixture):
    chapter.novel.chapter_split_prompt_template_id='missing-configured-template';db_session.commit()
    llm=LLM(db_session)
    with pytest.raises(HTTPException):execute(db_session,chapter,llm)
    assert not llm.calls


def test_active_shot_execution_blocks_rebuild(db_session,chapter,fixture):
    shot_row=Shot(chapter_id=chapter.id,index=1);db_session.add(shot_row);db_session.flush()
    db_session.add(Task(name='active shot image',type='shot_image',status='running',novel_id=chapter.novel_id,chapter_id=chapter.id,shot_id=shot_row.id));db_session.commit()
    llm=LLM(db_session)
    with pytest.raises(HTTPException):execute(db_session,chapter,llm)
    assert not llm.calls and not split_state(db_session,chapter.novel_id,chapter.id)['canSplit']


@pytest.mark.parametrize('target',['source','log','task','membership'])
def test_provenance_tampering_or_extra_legacy_shot_blocks_ready(db_session,chapter,fixture,target):
    assert execute(db_session,chapter)['success']
    run=db_session.query(Run).one()
    if target=='source':db_session.query(ShotSource).first().source_start=1
    elif target=='log':db_session.get(LLMLog,run.call['llm_log_id']).response='{}'
    elif target=='task':db_session.get(Task,run.task_id).metadata_json='{}'
    else:db_session.add(Shot(chapter_id=chapter.id,index=3,description='legacy import'))
    db_session.commit()
    assert not split_state(db_session,chapter.novel_id,chapter.id)['phase5Ready']


@pytest.mark.parametrize('field',['range','audio'])
def test_consistent_rehashed_receipts_still_must_match_original_llm_output(db_session,chapter,fixture,field):
    from app.services.chapter_shot_split_service import source_payload
    assert execute(db_session,chapter)['success']
    source=db_session.query(ShotSource).filter(ShotSource.source_start==9).one();run=db_session.get(Run,source.run_id)
    if field=='range':source.source_start=10
    else:
        db_session.query(ShotAudioEvent).filter_by(shot_id=source.shot_id).one().emotion_prompt='tampered'
        audio=deepcopy(source.audio_snapshot);audio[0]['emotion_prompt']='tampered';source.audio_snapshot=audio
    payload=source_payload(source);source.seal=digest(payload)
    result=deepcopy(run.result);result['sources'][source.shot_id]=payload;run.result=result;run.result_hash=digest(result)
    task=db_session.get(Task,run.task_id);meta=json.loads(task.metadata_json);meta['result_hash']=run.result_hash;task.metadata_json=json.dumps(meta)
    db_session.commit()
    assert not split_state(db_session,chapter.novel_id,chapter.id)['phase5Ready']


def test_llm_log_change_at_final_publication_fence_rolls_back(db_session,chapter,fixture,monkeypatch):
    service=ChapterShotSplitService(db_session,LLM(db_session));original=service.guard;calls=[]
    def guarded(rid,token):
        calls.append(rid)
        if len(calls)==2:
            run=db_session.get(Run,rid);db_session.get(LLMLog,run.call['llm_log_id']).response='changed';db_session.commit()
        return original(rid,token)
    monkeypatch.setattr(service,'guard',guarded)
    result=asyncio.run(service.split(chapter.novel_id,chapter.id))
    assert not result['success'] and 'LOG_CHANGED_BEFORE_PUBLICATION' in result['message']
    assert db_session.query(Shot).count()==0


def test_existing_split_api_and_raw_name_helper_cannot_bypass_scope(db_session,chapter,fixture,monkeypatch):
    from app.api.chapters import router
    from app.api.chapter_shot_splits import router as state_router
    from app.services.novel_service import NovelService
    from app.services.llm_service import LLMService
    from app.repositories.character_repository import CharacterRepository
    value=output();value['source_contract_version']='chapter-shot-ownership-v2'
    for planned in value['shots']:
        evidence=planned.pop('source_evidence')
        planned['source_citations']=deepcopy(evidence)
        planned['source_ownership']={'text':evidence[0]['text']}
    llm=LLM(db_session,value)
    monkeypatch.setattr(NovelService,'get_llm_service',lambda self:llm)
    def forbidden(*args,**kwargs):raise AssertionError('Book-wide names must not be queried')
    monkeypatch.setattr(CharacterRepository,'get_names_by_novel',forbidden)
    app=FastAPI();app.include_router(router,prefix='/api/novels');app.include_router(state_router,prefix='/api/novels')
    app.dependency_overrides[get_db]=lambda:db_session
    client=TestClient(app);root=f'/api/novels/{chapter.novel_id}/chapters/{chapter.id}'
    result=client.post(root+'/split').json();assert result['success'],result
    before=[row_snapshot(r) for r in db_session.query(Shot)]
    assert client.get(root+'/split-state').json()['data']['phase5Ready']
    assert client.get(root+'/split-runs/'+result['data']['splitRunId']).json()['data']['call']['llm_log_id']
    assert before==[row_snapshot(r) for r in db_session.query(Shot)]
    with pytest.raises(RuntimeError,match='CHAPTER_SCOPE_REQUIRED'):
        asyncio.run(LLMService().split_chapter_with_prompt('title','content','prompt',character_names=['any Book role']))


def test_schema_is_additive_and_legacy_shot_gets_no_source(db_session,chapter,fixture):
    from app.services.chapter_shot_split_schema import upgrade
    old=Shot(chapter_id=chapter.id,index=1,description='legacy');db_session.add(old);db_session.commit()
    upgrade(db_session.bind);upgrade(db_session.bind)
    assert old.source_start is None and old.source_end is None
    assert db_session.query(ShotSource).count()==0
    assert split_state(db_session,chapter.novel_id,chapter.id)['shots'][0]['status']=='LEGACY'


def test_group_binding_stays_one_asset_with_explicit_size(db_session,chapter):
    from test_chapter_asset_parse import character
    chapter.content='三名村民在桃园站定。';db_session.commit()
    candidate={**character('村民群'),'entity_type':'GROUP','group_size_hint':3,'source_evidence':[{'text':chapter.content}]}
    extract(db_session,chapter,[candidate]);assert resolve(db_session,chapter)['success']
    extract(db_session,chapter,[{'name':'桃园','description':'园林','setting':'桃树','source_evidence':[{'text':'桃园'}]}],'scenes')
    assert resolve(db_session,chapter,kinds=['scenes'])['success']
    extract(db_session,chapter,[],'props');assert resolve(db_session,chapter,kinds=['props'])['success']
    assert AppearanceTimelineService(db_session).build(chapter.novel_id,chapter.id)['success']
    db_session.add(PromptTemplate(name='split',type='chapter_split',template='Test fixture director template',is_system=True,is_active=True));db_session.commit()
    data={'chapter':chapter.title,'characters':['村民群'],'scenes':['桃园'],'props':[],'shots':[shot(1,chapter.content)]}
    data['shots'][0]['characters']=['村民群'];data['shots'][0]['description']='Scene: 桃园\nCharacters:\n- 村民群: 三名村民自然站立\nAction: 静立'
    result=execute(db_session,chapter,LLM(db_session,data));assert result['success'],result
    binding=db_session.query(ShotSource).one().bindings['characters'][0]
    assert binding['entityType']=='GROUP' and binding['groupSizeHint']==3
    assert db_session.query(Character).filter_by(novel_id=chapter.novel_id,name='村民群').count()==1
