"""R2-B/F07: citations are evidence; one continuous ownership drives all gates."""
import asyncio
from copy import deepcopy
import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from app.models.chapter_shot_split import ChapterShotSplitRun as Run, ShotSource
from app.models.appearance_timeline import AppearanceTimelineRun
from app.models.llm_log import LLMLog
from app.models.novel import Scene
from app.models.shot import Shot
from app.models.task import Task
from app.core.database import get_db
from app.services.chapter_asset_parse_service import digest
from app.services.asset_resolution_service import AssetResolutionService
from app.services.chapter_scope import (OWNERSHIP_RUN_VERSION, SCENE_BOUNDARY_RUN_VERSION,
    SOURCE_WINDOW_RUN_VERSION, collect_scope, load_policy, ownership_source, validate_plan, SplitReview)
from app.services.chapter_shot_split_schema import upgrade
from app.services.chapter_shot_split_service import ChapterShotSplitService, checked_source, source_payload
import app.services.chapter_shot_split_service as split_module
from app.services.resolved_shot_assets_service import ResolvedShotAssetsService
from app.services.shot_revision_service import ShotRevisionService
from app.schemas.chapter_shot_split import parse_output
from test_chapter_shot_split import (SequenceLLM, add_repair_template, chapter, closure_patch, db_session,
    execute, fixture, LLM, output, shot, TEXT)
from test_chapter_asset_parse import FakeLLM as ParseLLM, execute as parse_execute
from test_resolved_shot_assets import setup as rsa_setup

OWNERSHIP = 'chapter-shot-ownership-v2'
RUN_VERSION = SCENE_BOUNDARY_RUN_VERSION


def v2_shot(index, text, *, citations=None, speaking=False):
    value = shot(index, text, speaking)
    value.pop('source_evidence')
    value['source_citations'] = [{'text': item} for item in (citations or [text])]
    value['source_ownership'] = {'text': text}
    return value


def v2_output():
    first = TEXT[:TEXT.index('刘备披甲')]
    second = TEXT[TEXT.index('刘备披甲'):]
    return {
        'source_contract_version': OWNERSHIP,
        'chapter': '第一回', 'characters': ['刘备'], 'scenes': ['桃园'], 'props': [],
        'unresolved_assets': [],
        'shots': [
            v2_shot(1, first, citations=['🐺刘备', '站定。']),
            v2_shot(2, second, speaking=True),
        ],
    }


def test_optional_source_context_empty_string_normalizes_to_absent():
    data=v2_output();data['shots'][0]['source_citations'][0]['context_after']=''
    data['shots'][0]['source_ownership']['context_before']=' '
    data['shots'][0]['source_treatments'][0]['source_evidence'][0]['context_after']=''
    parsed=parse_output(json.dumps(data,ensure_ascii=False),OWNERSHIP)
    assert parsed['shots'][0]['source_citations'][0]['context_after'] is None
    assert parsed['shots'][0]['source_ownership']['context_before'] is None
    assert parsed['shots'][0]['source_treatments'][0]['source_evidence'][0]['context_after'] is None


def boundary_crossing_output():
    value=v2_output();crossing=v2_shot(1,TEXT,speaking=True);crossing['duration']=16
    value['shots']=[crossing]
    return value


def boundary_repair_output(replacements=None):
    return {'repair_type':'SHOT_CROSSES_APPEARANCE_BOUNDARY','repairs':[
        {'shot_index':1,'replacements':deepcopy(replacements or v2_output()['shots'])}]}


def attach_source_windows(db,chapter,value):
    return deepcopy(value)


def execute_v2(db, chapter, value=None, **options):
    value=attach_source_windows(db,chapter,deepcopy(value or v2_output()))
    return asyncio.run(ChapterShotSplitService(db, LLM(db, value)).split(
        chapter.novel_id, chapter.id, source_contract_version=OWNERSHIP, **options))


def test_sparse_citations_publish_one_signed_continuous_source(db_session, chapter, fixture):
    result = execute_v2(db_session, chapter)
    assert result['success'], result
    source = db_session.query(ShotSource).filter_by(source_start=0).one()
    assert (source.source_start, source.source_end) == (0, 9)
    assert source.ranges == [{'start': 0, 'end': 9, 'text': '🐺刘备在桃园站定。'}]
    assert source.source_contract == {
        'version': OWNERSHIP,
        'citation_evidence': [{'text': '🐺刘备'}, {'text': '站定。'}],
        'citation_ranges': [
            {'start': 0, 'end': 3, 'text': '🐺刘备'},
            {'start': 6, 'end': 9, 'text': '站定。'},
        ],
        'ownership_evidence': {'text': '🐺刘备在桃园站定。'},
        'ownership_range': {'start': 0, 'end': 9, 'text': '🐺刘备在桃园站定。'},
    }
    assert source_payload(source)['source_contract'] == source.source_contract
    assert digest(source_payload(source)) == source.seal
    assert source.bindings['source_windows'][0]['name']=='刘备'
    assert source.bindings['source_windows'][0]['source_start']==0
    assert db_session.get(Run, source.run_id).version == RUN_VERSION
    checked_source(db_session, db_session.get(Shot, source.shot_id))
    projected=result['data']['shots'][0]['source']
    assert projected['sourceContract']==source.source_contract
    assert projected['sourceCitationRanges']==source.source_contract['citation_ranges']
    assert projected['offsetUnit']=='UNICODE_CODE_POINT'


def test_v2_closure_auto_repair_preserves_ownership_contract(db_session,chapter,fixture):
    add_repair_template(db_session);bad=attach_source_windows(db_session,chapter,v2_output())
    bad['shots'][0]['description']='Scene: 桃园\nCharacters:\nAction: 静止'
    llm=SequenceLLM(db_session,[bad,closure_patch()])
    result=asyncio.run(ChapterShotSplitService(db_session,llm).split(
        chapter.novel_id,chapter.id,source_contract_version=OWNERSHIP))
    assert result['success'],result
    assert result['data']['autoRepair']['outcome']=='REPAIRED' and len(llm.calls)==2
    sources=db_session.query(ShotSource).order_by(ShotSource.source_start).all()
    assert all(source.source_contract['version']==OWNERSHIP for source in sources)
    assert checked_source(db_session,db_session.get(Shot,sources[0].shot_id)).source_contract==sources[0].source_contract


def test_v2_boundary_targeted_resplit_once_then_publishes(db_session,chapter,fixture):
    add_repair_template(db_session);llm=SequenceLLM(db_session,[boundary_crossing_output(),boundary_repair_output()])
    result=asyncio.run(ChapterShotSplitService(db_session,llm).split(
        chapter.novel_id,chapter.id,source_contract_version=OWNERSHIP))
    assert result['success'],result
    assert len(llm.calls)==2 and result['data']['autoRepair']['repairType']=='SHOT_CROSSES_APPEARANCE_BOUNDARY'
    assert result['data']['autoRepair']['violationsBefore']==1 and result['data']['autoRepair']['violationsAfter']==0
    assert [item['state'] for item in result['data']['autoRepair']['sceneDecisions']]==['SAME_SCENE','SAME_SCENE']
    request=json.loads(llm.calls[1]['user_content'])['repair_plan']['targets'][0]['scene_policy']
    assert request['mode']=='SOURCE_SPAN_AWARE' and request['parent_scene']=='桃园'
    assert request['allowed_scenes']==['桃园'] and request['states']==[
        'SAME_SCENE','SOURCE_SPAN_AWARE_SCENE_CHANGE','CREATIVE_COMPLETION','SCENE_UNRESOLVED']
    shots=db_session.query(Shot).order_by(Shot.index).all();assert len(shots)==2
    sources=[checked_source(db_session,item) for item in shots]
    assert [(item.source_start,item.source_end) for item in sources]==[(0,9),(9,len(TEXT))]
    assert all(item.bindings['source_windows'][0]['name']=='刘备' for item in sources)


def test_v2_boundary_scene_aware_change_publishes_and_replays_bound_scene(db_session,chapter,fixture):
    add_repair_template(db_session)
    db_session.add(Scene(novel_id=chapter.novel_id,name='军营',description='披甲军营',setting='军营'))
    db_session.commit()
    scenes=[{'name':'桃园','description':'桃园','setting':'桃园','source_evidence':[{'text':TEXT[:9]}]},
        {'name':'军营','description':'披甲军营','setting':'军营','source_evidence':[{'text':TEXT[9:]}]}]
    parsed=parse_execute(db_session,chapter,ParseLLM(db_session,{'scenes':{'scenes':scenes}}),['scenes'])
    assert parsed['success']
    assert asyncio.run(AssetResolutionService(db_session).resolve(chapter.novel_id,chapter.id,['scenes']))['success']
    repair=boundary_repair_output();repair['repairs'][0]['replacements'][1]['scene']='军营'
    llm=SequenceLLM(db_session,[boundary_crossing_output(),repair])
    result=asyncio.run(ChapterShotSplitService(db_session,llm).split(
        chapter.novel_id,chapter.id,source_contract_version=OWNERSHIP))
    assert result['success'],result
    assert result['data']['scenes']==['桃园','军营']
    assert [item['state'] for item in result['data']['autoRepair']['sceneDecisions']]==[
        'SAME_SCENE','SOURCE_SPAN_AWARE_SCENE_CHANGE']
    shots=db_session.query(Shot).order_by(Shot.index).all();sources=[checked_source(db_session,item) for item in shots]
    assert [source.bindings['scenes'][0]['name'] for source in sources]==['桃园','军营']
    run=db_session.get(Run,sources[0].run_id);log=db_session.get(LLMLog,run.call['llm_log_id'])
    assert log.execution_metadata['sceneDecisions']==result['data']['autoRepair']['sceneDecisions']
    log.execution_metadata={**log.execution_metadata,'sceneDecisions':[]};db_session.commit()
    with pytest.raises(HTTPException,match='AUTO_REPAIR_GOVERNANCE_DELTA_CHANGED'):
        checked_source(db_session,shots[0])


def test_v2_source_silent_scene_creative_completion_publishes_truthful_receipt(db_session,chapter,fixture):
    add_repair_template(db_session)
    db_session.add(Scene(novel_id=chapter.novel_id,name='军营',description='披甲军营',setting='军营'))
    db_session.commit()
    scenes=[{'name':'桃园','description':'桃园','setting':'桃园','source_evidence':[{'text':'桃园'}]},
        {'name':'军营','description':'披甲军营','setting':'军营','source_evidence':[{'text':'刘备'}]}]
    assert parse_execute(db_session,chapter,ParseLLM(db_session,{'scenes':{'scenes':scenes}}),['scenes'])['success']
    assert asyncio.run(AssetResolutionService(db_session).resolve(chapter.novel_id,chapter.id,['scenes']))['success']
    repair=boundary_repair_output();repair['repairs'][0]['replacements'][1]['scene']='军营'
    llm=SequenceLLM(db_session,[boundary_crossing_output(),repair])
    result=asyncio.run(ChapterShotSplitService(db_session,llm).split(
            chapter.novel_id,chapter.id,source_contract_version=OWNERSHIP))
    assert result['success'],result
    decision=result['data']['autoRepair']['sceneDecisions'][1]
    assert decision['state']==decision['grounding']=='CREATIVE_COMPLETION'
    assert decision['reason']=='SOURCE_SILENT_CREATIVE_COMPLETION'
    assert decision['supportedScenes']==decision['sceneNameMentions']==[]
    plan=json.loads(llm.calls[1]['user_content'])['repair_plan']
    assert 'scene_policy_provenance' in plan['preserve']
    assert 'scene_contradicts_explicit_source' in plan['forbidden']
    assert 'ungrounded_scene_change' not in plan['forbidden']
    shots=db_session.query(Shot).order_by(Shot.index).all()
    assert shots[1].scene=='军营' and checked_source(db_session,shots[1]).bindings['scenes'][0]['name']=='军营'


def test_v2_historical_strict_scene_repair_receipt_replays_after_policy_upgrade(db_session,chapter,fixture,monkeypatch):
    add_repair_template(db_session);original=split_module.build_auto_repair_plan
    frozen=json.loads((__import__('pathlib').Path(__file__).parents[1]/'fixtures'/'scene_aware_shot18.json').read_text())['legacyStrictV1']
    monkeypatch.setattr(split_module,'build_auto_repair_plan',lambda findings,plan=None,basis=None,**kwargs:
        original(findings,plan,basis,scene_aware=False))
    llm=SequenceLLM(db_session,[boundary_crossing_output(),boundary_repair_output()])
    result=asyncio.run(ChapterShotSplitService(db_session,llm).split(
        chapter.novel_id,chapter.id,source_contract_version=OWNERSHIP))
    assert result['success'] and 'sceneDecisions' not in result['data']['autoRepair']
    run=db_session.get(Run,result['data']['splitRunId']);stored=run.inputs['auto_repair']['repair_plan']
    assert stored['preserve']==frozen['preserve'] and stored['forbidden']==frozen['forbidden']
    assert all('scene_policy' not in target for target in stored['targets'])
    assert {key:run.result['auto_repair'].get(key) for key in frozen['delta']}==frozen['delta']
    monkeypatch.setattr(split_module,'build_auto_repair_plan',original)
    for item in db_session.query(Shot).order_by(Shot.index):checked_source(db_session,item)


def test_v2_boundary_resplit_identical_response_is_no_effect_and_budget_exhausted(db_session,chapter,fixture):
    add_repair_template(db_session);bad=json.dumps(boundary_crossing_output(),ensure_ascii=False,separators=(',',':'))
    llm=SequenceLLM(db_session,[bad,bad]);result=asyncio.run(ChapterShotSplitService(db_session,llm).split(
        chapter.novel_id,chapter.id,source_contract_version=OWNERSHIP))
    assert not result['success'] and result['data']['autoRepair']['outcome']=='REPAIR_NO_EFFECT'
    assert len(llm.calls)==2 and db_session.query(Shot).count()==0
    blocked=SequenceLLM(db_session,[]);again=asyncio.run(ChapterShotSplitService(db_session,blocked).split(
        chapter.novel_id,chapter.id,source_contract_version=OWNERSHIP))
    assert again['message']=='SHOT_CONTRACT_REPAIR_BUDGET_EXHAUSTED' and blocked.calls==[]


def test_v2_boundary_resplit_new_contract_violation_stops(db_session,chapter,fixture):
    add_repair_template(db_session);replacements=v2_output()['shots']
    replacements[1]['description']='Scene: 桃园\nCharacters:\n游离说明\nAction: 静止'
    llm=SequenceLLM(db_session,[boundary_crossing_output(),boundary_repair_output(replacements)])
    result=asyncio.run(ChapterShotSplitService(db_session,llm).split(
        chapter.novel_id,chapter.id,source_contract_version=OWNERSHIP))
    assert not result['success'] and result['data']['autoRepair']['outcome']=='NEW_VIOLATIONS'
    assert 'SHOT_CHARACTER_DESCRIPTION_FORMAT' in result['data']['autoRepair']['validatorError']
    assert len(llm.calls)==2 and db_session.query(Shot).count()==0


def test_v2_ownership_not_found_remains_human_required(db_session,chapter,fixture):
    bad=v2_output();bad['shots'][0]['source_ownership']={'text':'不存在的原文'}
    llm=SequenceLLM(db_session,[bad]);result=asyncio.run(ChapterShotSplitService(db_session,llm).split(
        chapter.novel_id,chapter.id,source_contract_version=OWNERSHIP))
    assert not result['success'] and 'SHOT_OWNERSHIP_NOT_FOUND' in result['message']
    assert len(llm.calls)==1 and db_session.query(Run).count()==1
    assert db_session.query(Run).one().issues[0].get('repairClassification')!='AUTO_REPAIRABLE'


def test_same_sparse_evidence_remains_invalid_under_v1(db_session,chapter,fixture):
    data=output()
    data['shots'][0]['source_evidence']=[{'text':'🐺刘备'},{'text':'站定。'}]
    result=execute(db_session,chapter,LLM(db_session,data))
    assert not result['success'] and 'SHOT_EVIDENCE_NOT_CONTIGUOUS' in result['message']
    assert db_session.query(ShotSource).count()==0


@pytest.mark.parametrize('mutation,code', [
    ('middle_treatment_gap', 'SOURCE_TREATMENT_MISSING'),
    ('citation_outside', 'SHOT_CITATION_OUTSIDE_OWNERSHIP'),
    ('citation_reordered', 'SHOT_CITATION_ORDER_INVALID'),
    ('ambiguous_ownership', 'SHOT_OWNERSHIP_AMBIGUOUS'),
    ('bad_context', 'SHOT_CITATION_NOT_FOUND'),
    ('model_offset', 'extra_forbidden'),
    ('mixed_v1', 'extra_forbidden'),
    ('unknown_version', 'SOURCE_CONTRACT_VERSION'),
])
def test_v2_invalid_input_never_falls_back_or_replaces_existing(db_session, chapter, fixture, mutation, code):
    old = Shot(chapter_id=chapter.id, index=1, description='accepted', image_url='/accepted.png')
    db_session.add(old); db_session.commit()
    data = v2_output()
    if mutation == 'middle_treatment_gap':
        data['shots'][0]['source_treatments'][0]['source_evidence'] = [{'text': '🐺刘备'}]
    elif mutation == 'citation_outside':
        data['shots'][0]['source_citations'] = [{'text': '刘备披甲'}]
    elif mutation == 'citation_reordered':
        data['shots'][0]['source_citations'].reverse()
    elif mutation == 'ambiguous_ownership':
        data['shots'][0]['source_ownership'] = {'text':'刘备'}
        data['shots'][0]['source_citations'] = [{'text':'刘备'}]
    elif mutation == 'bad_context':
        data['shots'][0]['source_citations'][0]['context_before'] = '不存在'
    elif mutation == 'model_offset':
        data['shots'][0]['source_ownership']['start'] = 0
    elif mutation == 'mixed_v1':
        data['shots'][0]['source_evidence'] = [{'text': TEXT[:9]}]
    else:
        data['source_contract_version'] = 'chapter-shot-ownership-v3'
    result = execute_v2(db_session, chapter, data)
    assert not result['success'] and code in (result.get('message') or '')
    assert db_session.get(Shot, old.id).description == 'accepted'
    assert db_session.query(ShotSource).count() == 0
    assert db_session.query(Run).one().status == 'NEEDS_REVIEW'


def test_context_disambiguates_but_does_not_expand_citation():
    text = '甲重复。乙重复。'
    basis = {
        'source': {'title':'章', 'content':text, 'hash':'h'},
        'source_contract_version': OWNERSHIP,
        'scope': {'characters':{'bindings':[]}, 'scenes':{'bindings':[{'name':'场景'}]}, 'props':{'bindings':[]}},
        'appearance_boundaries': [],
    }
    candidate = {
        'source_contract_version': OWNERSHIP, 'chapter':'章', 'characters':[], 'scenes':['场景'], 'props':[], 'unresolved_assets':[],
        'shots':[{
            'id':1, 'source_citations':[{'text':'重复。','context_before':'乙'}],
            'source_ownership':{'text':text}, 'description':'Scene: 场景\nCharacters:\nAction: 静止',
            'video_description':'静止，无说话口型。', 'characters':[], 'scene':'场景', 'props':[], 'duration':1,
            'continuity_mode':'NORMAL', 'dialogues':[], 'audio_events':[],
            'source_treatments':[{'key':'v','type':'VISUAL','source_evidence':[{'text':'乙重复。'}],
                                  'visual_targets':['description']}],
        }],
    }
    prepared = validate_plan(parse_output(json.dumps(candidate), OWNERSHIP), basis, historical_structure=True)
    assert prepared[0]['source_contract']['citation_ranges'] == [{'start':5,'end':8,'text':'重复。'}]
    assert prepared[0]['start'] == 0 and prepared[0]['end'] == 8


def test_empty_character_prompt_matches_flat_block_contract():
    prompt = load_policy()['definition']['system_suffix']
    assert 'characters为空数组时' in prompt
    assert '不得输出任何项目、占位语或“无可见人物”' in prompt


def test_full_ownership_rejects_intermediate_appearance_change_even_when_endpoints_match():
    data = v2_output(); data['shots'] = [v2_shot(1, TEXT[:9], citations=['🐺刘备','站定。'])]
    basis = {
        'source': {'title':'第一回','content':TEXT[:9],'hash':'h'}, 'source_contract_version':OWNERSHIP,
        'scope': {'characters':{'bindings':[{'name':'刘备','assetId':'actor'}]},
                  'scenes':{'bindings':[{'name':'桃园','assetId':'scene'}]}, 'props':{'bindings':[]}},
        'appearance_boundaries':[{'name':'刘备','segments':[
            {'start':0,'end':3,'logical_status':'BASE'}, {'start':3,'end':6,'logical_status':'APPEARANCE'},
            {'start':6,'end':9,'logical_status':'BASE'},
        ]}],
    }
    with pytest.raises(SplitReview, match='SHOT_CROSSES_APPEARANCE_BOUNDARY'):
        validate_plan(parse_output(json.dumps(data), OWNERSHIP), basis)


@pytest.mark.parametrize('mutation,code',[
    ('gap','SHOT_OWNERSHIP_GAP'),('overlap','SHOT_SOURCE_OVERLAP_OR_REORDERED'),
    ('reordered','SHOT_SOURCE_OVERLAP_OR_REORDERED'),('ambiguous_citation','SHOT_CITATION_AMBIGUOUS'),
])
def test_chapter_ownership_partition_and_citation_ambiguity_are_strict(db_session,chapter,fixture,mutation,code):
    old=Shot(chapter_id=chapter.id,index=1,description='accepted');db_session.add(old);db_session.commit()
    data=v2_output()
    if mutation=='gap':
        data['shots'][0]['source_ownership']={'text':TEXT[:8]}
        data['shots'][0]['source_citations']=[{'text':TEXT[:8]}]
    elif mutation=='overlap':
        data['shots'][1]['source_ownership']={'text':TEXT[8:]}
        data['shots'][1]['source_citations']=[{'text':TEXT[8:]}]
    elif mutation=='reordered':
        left,right=data['shots'][0],data['shots'][1]
        left['source_ownership'],right['source_ownership']=right['source_ownership'],left['source_ownership']
        left['source_citations'],right['source_citations']=right['source_citations'],left['source_citations']
    else:
        data['shots']=[v2_shot(1,TEXT,citations=['刘备'],speaking=True)]
    result=execute_v2(db_session,chapter,data)
    assert not result['success'] and code in result['message']
    assert db_session.get(Shot,old.id).description=='accepted'


def test_selected_v2_rejects_well_formed_v1_output_without_fallback(db_session,chapter,fixture):
    result=execute_v2(db_session,chapter,output())
    assert not result['success'] and 'SOURCE_CONTRACT_VERSION' in result['message']
    assert db_session.query(ShotSource).count()==0


def test_additive_migration_is_idempotent_and_does_not_backfill_v1():
    engine=create_engine('sqlite:///:memory:')
    with engine.begin() as connection:
        connection.execute(text('''CREATE TABLE shot_sources (
            shot_id VARCHAR PRIMARY KEY, run_id VARCHAR NOT NULL, source_start INTEGER NOT NULL,
            source_end INTEGER NOT NULL, source_hash VARCHAR NOT NULL, evidence JSON NOT NULL,
            ranges JSON NOT NULL, bindings JSON NOT NULL, snapshot JSON NOT NULL,
            audio_snapshot JSON NOT NULL, treatment_contract JSON, seal VARCHAR NOT NULL)'''))
        connection.execute(text("""INSERT INTO shot_sources VALUES
            ('legacy-shot','legacy-run',0,1,'hash','[]','[]','{}','{}','[]',NULL,'legacy-seal')"""))
    assert 'source_contract' not in {column['name'] for column in inspect(engine).get_columns('shot_sources')}
    upgrade(engine); upgrade(engine)
    assert 'source_contract' in {column['name'] for column in inspect(engine).get_columns('shot_sources')}
    with engine.connect() as connection:
        row=connection.execute(text('SELECT seal, source_contract FROM shot_sources')).one()
    assert row == ('legacy-seal',None)
    engine.dispose()


def test_deploying_v2_preserves_v1_payload_seal_and_reader(db_session,chapter,fixture):
    result=execute(db_session,chapter);assert result['success'],result
    rows=db_session.query(ShotSource).order_by(ShotSource.source_start).all()
    before=[(source_payload(row),row.seal) for row in rows]
    upgrade(db_session.bind);upgrade(db_session.bind)
    db_session.expire_all()
    rows=db_session.query(ShotSource).order_by(ShotSource.source_start).all()
    assert all(row.source_contract is None and 'source_contract' not in source_payload(row) for row in rows)
    assert before==[(source_payload(row),row.seal) for row in rows]
    assert all(checked_source(db_session,db_session.get(Shot,row.shot_id)) for row in rows)


def test_v2_prompt_version_and_policy_are_pinned_in_run(db_session,chapter,fixture):
    llm=LLM(db_session,attach_source_windows(db_session,chapter,v2_output()))
    result=asyncio.run(ChapterShotSplitService(db_session,llm).split(
        chapter.novel_id,chapter.id,source_contract_version=OWNERSHIP))
    assert result['success'],result
    run=db_session.get(Run,result['data']['splitRunId'])
    assert run.version==RUN_VERSION and run.inputs['source_contract_version']==OWNERSHIP
    assert run.inputs['source_window_version']=='appearance-source-windows-v1'
    assert run.inputs['basis']['source_contract_policy']['definition']['version']==OWNERSHIP
    assert run.inputs['basis']['source_windows']['offset_unit']=='UNICODE_CODE_POINT'
    assert run.inputs['basis']['source_window_contract']['version']=='appearance-source-windows-v1'
    assert run.inputs['basis']['source_contract_policy']['hash']
    assert run.inputs['basis']['template']['hash']=='cb2267dd938c15b4b3f6e000e5a433319711ddfd449e894ca7e084e71923869d'
    compatible=run.inputs['basis']['source_contract_policy']['definition']['compatible_template_hashes']
    scene_compatible=run.inputs['basis']['source_contract_policy']['definition']['scene_boundary_template_hashes']
    assert '270063b5fff8a55c298a673974c7c01ad9bfd036f89e234b1cd439a60fc7ddf5' in compatible
    assert run.inputs['basis']['template']['hash'] in compatible
    assert scene_compatible==[run.inputs['basis']['template']['hash']]
    assert 'Shot来源归属合同 chapter-shot-ownership-v2' in run.inputs['system_prompt']
    payload=json.loads(llm.calls[0]['user_content'].split('\n',1)[1])
    assert payload['source_contract_version']==OWNERSHIP
    assert payload['source_windows']==run.inputs['basis']['source_windows']
    assert payload['source_windows']['contract']==run.inputs['basis']['source_window_contract']['definition']
    assert '【Appearance-aware Source Window 硬约束】' in run.inputs['system_prompt']
    assert '仅作为 voice_owner、画外对白或旁白存在的角色也不产生视觉 window constraint' in run.inputs['system_prompt']
    assert 'Boundary 恰好等于 Shot start 或 Shot end 合法' in run.inputs['system_prompt']
    assert '不得通过删除可见角色、把角色改成画外、篡改剧情' in run.inputs['system_prompt']
    assert '不要输出 source_window_bindings' in run.inputs['system_prompt']
    assert '【R-SC1 / Single-Scene Shot 硬约束】' in run.inputs['system_prompt']
    assert 'tracking shot、CONTINUOUS_TAKE、montage、match cut' in run.inputs['system_prompt']
    assert set(payload['source_windows']['contract'])=={'version','scope','offset_unit','end_exclusive'}
    assert 'rules' not in payload['source_windows']['contract']
    assert all('source_window_bindings' not in planned for planned in json.loads(run.call['response'])['shots'])
    assert all('source_windows' in source['bindings'] for source in run.result['sources'].values())


def test_current_profile_requires_single_scene_compatible_director(db_session,chapter,fixture,monkeypatch):
    import app.services.chapter_scope as scope_module
    policy=scope_module.load_ownership_policy()
    policy['definition']['scene_boundary_template_hashes']=['not-current-template']
    monkeypatch.setattr(scope_module,'load_ownership_policy',lambda:deepcopy(policy))
    with pytest.raises(HTTPException,match='SHOT_SCENE_TEMPLATE_INCOMPATIBLE'):
        collect_scope(db_session,chapter.novel_id,chapter.id,OWNERSHIP)
    historical=collect_scope(db_session,chapter.novel_id,chapter.id,OWNERSHIP,
        run_profile=SOURCE_WINDOW_RUN_VERSION)
    assert historical['version']==SOURCE_WINDOW_RUN_VERSION


def test_stale_timeline_cannot_fabricate_source_windows(db_session,chapter,fixture):
    timeline=db_session.query(AppearanceTimelineRun).order_by(AppearanceTimelineRun.created_at.desc()).first()
    timeline.status='FAILED';db_session.commit()
    with pytest.raises(HTTPException,match='APPEARANCE_TIMELINE_NOT_CURRENT'):
        collect_scope(db_session,chapter.novel_id,chapter.id,OWNERSHIP,run_profile=SOURCE_WINDOW_RUN_VERSION)


def test_pre_sw1_v2_run_keeps_its_frozen_profile_and_ready_proof(db_session,chapter,fixture):
    result=asyncio.run(ChapterShotSplitService(db_session,LLM(db_session,v2_output()))._split_once(
        chapter.novel_id,chapter.id,source_contract_version=OWNERSHIP,_run_profile=OWNERSHIP_RUN_VERSION))
    assert result['success'],result
    run=db_session.get(Run,result['data']['splitRunId'])
    assert run.version==OWNERSHIP_RUN_VERSION and 'source_window_version' not in run.inputs
    assert 'source_windows' not in run.inputs['basis']
    assert __import__('app.services.chapter_shot_split_service',fromlist=['split_state']).split_state(
        db_session,chapter.novel_id,chapter.id)['phase5Ready']


def test_pre_sw1_rar1_repair_replays_original_hash_profile(db_session,chapter,fixture):
    add_repair_template(db_session);bad=v2_output();bad['shots'][0]['description']='Scene: 桃园\nCharacters:\nAction: 静止'
    llm=SequenceLLM(db_session,[bad,closure_patch()]);service=ChapterShotSplitService(db_session,llm)
    rejected=asyncio.run(service._split_once(chapter.novel_id,chapter.id,source_contract_version=OWNERSHIP,
        _run_profile=OWNERSHIP_RUN_VERSION));context=rejected.pop('_auto_repair_context')
    accepted=asyncio.run(service._split_once(chapter.novel_id,chapter.id,source_contract_version=OWNERSHIP,
        repair_previous=False,_auto_repair=context,_run_profile=OWNERSHIP_RUN_VERSION))
    assert accepted['success'],accepted
    run=db_session.get(Run,accepted['data']['splitRunId'])
    assert run.version==OWNERSHIP_RUN_VERSION and 'source_window_version' not in run.inputs
    assert run.result['auto_repair']['outcome']=='REPAIRED'
    assert __import__('app.services.chapter_shot_split_service',fromlist=['split_state']).split_state(
        db_session,chapter.novel_id,chapter.id)['phase5Ready']


def test_pre_sw1_rejected_plan_is_not_reused_by_sw1_profile(db_session,chapter,fixture):
    bad=v2_output();bad['shots'][0]['description']='Scene: 桃园\nCharacters:\nAction: 静止'
    rejected=asyncio.run(ChapterShotSplitService(db_session,LLM(db_session,bad))._split_once(
        chapter.novel_id,chapter.id,source_contract_version=OWNERSHIP,_run_profile=OWNERSHIP_RUN_VERSION))
    assert not rejected['success']
    current=attach_source_windows(db_session,chapter,v2_output());llm=LLM(db_session,current)
    accepted=asyncio.run(ChapterShotSplitService(db_session,llm).split(
        chapter.novel_id,chapter.id,source_contract_version=OWNERSHIP))
    assert accepted['success'],accepted
    run=db_session.get(Run,accepted['data']['splitRunId'])
    assert run.version==SCENE_BOUNDARY_RUN_VERSION and run.inputs['repair'] is None
    assert len(llm.calls)==1 and 'previous_rejected_attempt' not in llm.calls[0]['user_content']


def test_unadapted_selected_template_is_rejected_before_director_call(db_session,chapter,fixture):
    template=chapter.novel.chapter_split_prompt_template_id
    from app.models.prompt_template import PromptTemplate
    row=db_session.get(PromptTemplate,template) if template else db_session.query(PromptTemplate).filter_by(type='chapter_split').first()
    row.template+='\ncustom unversioned instruction';chapter.novel.chapter_split_prompt_template_id=row.id;db_session.commit()
    llm=LLM(db_session,v2_output())
    with pytest.raises(HTTPException,match='SHOT_OWNERSHIP_TEMPLATE_INCOMPATIBLE'):
        asyncio.run(ChapterShotSplitService(db_session,llm).split(
            chapter.novel_id,chapter.id,source_contract_version=OWNERSHIP))
    assert llm.calls==[] and db_session.query(Run).count()==0


def test_product_api_defaults_to_v2_and_rejects_unknown_version(db_session,chapter,fixture,monkeypatch):
    from app.api.chapters import router
    from app.services.novel_service import NovelService
    llm=LLM(db_session,attach_source_windows(db_session,chapter,v2_output()));monkeypatch.setattr(NovelService,'get_llm_service',lambda self:llm)
    app=FastAPI();app.include_router(router,prefix='/api/novels');app.dependency_overrides[get_db]=lambda:db_session
    client=TestClient(app);root=f'/api/novels/{chapter.novel_id}/chapters/{chapter.id}'
    response=client.post(root+'/split')
    assert response.status_code==200 and response.json()['success'],response.text
    assert db_session.query(Run).one().version==RUN_VERSION
    count=db_session.query(Run).count()
    rejected=client.post(root+'/split?sourceContractVersion=chapter-shot-ownership-v3')
    assert rejected.status_code==422 and 'SOURCE_CONTRACT_VERSION' in rejected.text
    assert db_session.query(Run).count()==count


def test_rehashed_v2_contract_tampering_still_fails_original_log_replay(db_session,chapter,fixture):
    assert execute_v2(db_session,chapter)['success']
    source=db_session.query(ShotSource).filter_by(source_start=0).one();run=db_session.get(Run,source.run_id)
    changed=deepcopy(source.source_contract);changed['citation_ranges'][0]['start']=1;source.source_contract=changed
    payload=source_payload(source);source.seal=digest(payload)
    result=deepcopy(run.result);result['sources'][source.shot_id]=payload;run.result=result;run.result_hash=digest(result)
    task=db_session.get(Task,run.task_id);meta=json.loads(task.metadata_json);meta['result_hash']=run.result_hash;task.metadata_json=json.dumps(meta)
    db_session.commit()
    assert not __import__('app.services.chapter_shot_split_service',fromlist=['split_state']).split_state(
        db_session,chapter.novel_id,chapter.id)['phase5Ready']


def test_cross_version_repair_is_not_reused_and_structure_lock_records_conversion(db_session,chapter,fixture):
    bad=output();bad['shots']=[shot(1,TEXT,True)]
    rejected=execute(db_session,chapter,LLM(db_session,bad));assert not rejected['success']
    accepted=execute_v2(db_session,chapter);assert accepted['success'],accepted
    assert db_session.get(Run,accepted['data']['splitRunId']).inputs['repair'] is None

    # Start a separate v1 source, then explicitly convert its complete signed envelope.
    second=execute(db_session,chapter,LLM(db_session,output()));assert second['success'],second
    converted=attach_source_windows(db_session,chapter,v2_output())
    for planned in converted['shots']:
        planned['source_citations']=[deepcopy(planned['source_ownership'])]
    result=asyncio.run(ChapterShotSplitService(db_session,LLM(db_session,converted)).split(
        chapter.novel_id,chapter.id,preserve_structure=True,source_contract_version=OWNERSHIP))
    assert result['success'],result
    run=db_session.get(Run,result['data']['splitRunId']);conversion=run.inputs['structure_lock_conversion']
    assert conversion['from'] is None and conversion['to']==OWNERSHIP
    assert conversion['to_run_version']==SCENE_BOUNDARY_RUN_VERSION
    assert conversion['source_window_version']=='appearance-source-windows-v1'
    assert all('source_window_bindings' not in planned for planned in conversion['shots'])
    assert conversion['source_run_id']==second['data']['splitRunId']
    with pytest.raises(HTTPException,match='DOWNGRADE_FORBIDDEN'):
        asyncio.run(ChapterShotSplitService(db_session,LLM(db_session,output())).split(
            chapter.novel_id,chapter.id,preserve_structure=True))


def test_revision_and_import_cannot_change_source_contract(db_session, chapter, fixture):
    assert execute_v2(db_session, chapter)['success']
    target = db_session.query(Shot).order_by(Shot.index).first()
    current = checked_source(db_session, target)
    before = deepcopy(db_session.get(ShotSource, target.id).source_contract)
    for field in ('source_contract', 'sourceContract', 'source_citations', 'sourceCitationRanges',
                  'source_ownership', 'source_evidence', 'sourceEvidence', 'source_ranges', 'sourceRanges',
                  'citation_evidence', 'citation_ranges', 'ownership_evidence', 'ownership_range',
                  'source_run_id', 'runId', 'evidence', 'ranges', 'bindings', 'offsetUnit', 'sourceSeal'):
        with pytest.raises(HTTPException, match='SHOT_REVISION_PROTECTED_FIELD'):
            ShotRevisionService(db_session).save_batch(chapter.novel_id, chapter.id, [{
                'id':target.id, 'expected_revision':current.revision, field:{'tampered':True},
            }], origin='IMPORT')
        db_session.rollback()
    assert db_session.get(ShotSource, target.id).source_contract == before


def test_revision_request_rejects_source_fields_before_extra_projection():
    from app.schemas.shot import BatchShotsUpdateRequest,ShotUpdate
    with pytest.raises(ValueError,match='SHOT_REVISION_PROTECTED_FIELD'):
        ShotUpdate.model_validate({'expectedRevision':0,'sourceContract':{'tampered':True}})
    with pytest.raises(ValueError,match='SHOT_REVISION_PROTECTED_FIELD'):
        BatchShotsUpdateRequest.model_validate({'shots':[
            {'id':'shot','expectedRevision':0,'sourceCitationRanges':[{'start':0,'end':1}]}
        ]})


def test_citation_with_multiple_matches_only_outside_owner_is_classified_as_outside():
    with pytest.raises(ValueError,match='SHOT_CITATION_OUTSIDE_OWNERSHIP'):
        ownership_source('重复。乙所有。重复。', {
            'source_ownership':{'text':'乙所有。'},'source_citations':[{'text':'重复。'}],
        })


def test_v2_revision_and_rsa_consume_same_continuous_source(db_session, chapter, rsa_setup):
    actor, scene, appearance, _, root = rsa_setup
    result=execute_v2(db_session,chapter,repair_previous=False)
    assert result['success'],result
    shots=db_session.query(Shot).filter_by(chapter_id=chapter.id).order_by(Shot.index).all()
    target = shots[0]
    source = checked_source(db_session, target)
    assert source.source_contract['ownership_range'] == {'start':0,'end':9,'text':TEXT[:9]}
    saved = ShotRevisionService(db_session).save_batch(chapter.novel_id, chapter.id, [{
        'id':target.id, 'expected_revision':0, 'video_description':target.video_description+' 保持连续。',
    }])
    assert saved['success']
    current = checked_source(db_session, target)
    assert current.source_contract == source.source_contract and current.revision == 1
    stale = ResolvedShotAssetsService(db_session).resolveShotAssets(target.id)
    assert stale['success'] and stale['data']['ready']
    logic = stale['data']['assets']['logical_hash']
    assert logic
    with pytest.raises(HTTPException):
        ShotRevisionService(db_session).save_batch(chapter.novel_id, chapter.id, [{
            'id':target.id, 'expected_revision':0, 'description':target.description,
        }])
