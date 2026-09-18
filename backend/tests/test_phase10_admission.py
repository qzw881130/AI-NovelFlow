import json
import asyncio
from pathlib import Path
import pytest
from fastapi import HTTPException
from app.models.workflow import Workflow
from app.models.rsa_media import RsaImageAttempt
from app.services.rsa_image_service import RsaImageService
from app.services.rsa_media_graph import inspect_graph, prepare_graph
from app.services.chapter_scope import (collect_visible_character_findings, validate_plan, SplitReview,
    collect_scope, direct_speech_quotes)
from app.services.shot_contract_auto_repair import (apply_response as apply_auto_repair_response,
    build_plan as build_auto_repair_plan, classify as classify_auto_repair)
from app.constants.workflow import EXTRA_SYSTEM_WORKFLOWS
from app.services.prompt_template_service import PromptTemplateService, SYSTEM_PROMPT_TEMPLATES
from test_rsa_media import db_session, chapter, fixture, base_setup, setup
from test_chapter_shot_split import output, LLM, execute


def test_required_reference_mapping_is_explicit_before_attempt_creation(db_session,setup):
    workflow=db_session.query(Workflow).filter_by(type='shot_character_scene').one()
    mapping=json.loads(workflow.node_mapping);mapping.pop('scene_reference_image_node_id');workflow.node_mapping=json.dumps(mapping);db_session.commit()
    with pytest.raises(HTTPException) as raised:RsaImageService(db_session).enqueue(setup[3][0].id)
    assert raised.value.status_code==409
    assert raised.value.detail['field']=='scene_reference_image_node_id'
    assert db_session.query(RsaImageAttempt).count()==0


def test_default_three_reference_workflow_binds_real_prop_slot():
    definition=next(w for w in EXTRA_SYSTEM_WORKFLOWS if w['filename']=='shot_flux2_klein_three_ref_edit.json')
    graph=json.loads((Path(__file__).parents[1]/'workflows'/definition['filename']).read_text())
    mapping=definition['node_mapping'];nodes=[mapping[key] for key in ('character_reference_image_node_id','scene_reference_image_node_id','prop_reference_image_node_id')]
    prepared=prepare_graph(graph,mapping,nodes,'16:9',7)
    assert inspect_graph(prepared,mapping,nodes)
    assert len(set(nodes))==3 and all(prepared[node]['class_type']=='LoadImage' for node in nodes)


def test_split_closure_failure_identifies_the_exact_shot(db_session,chapter,fixture):
    plan=output();plan['shots'][0]['description']=plan['shots'][0]['description'].replace('Action:','- 关羽: 站立\nAction:')
    with pytest.raises(SplitReview) as raised:validate_plan(plan,collect_scope(db_session,chapter.novel_id,chapter.id))
    detail=json.loads(str(raised.value).split(': ',1)[1])
    assert detail=={'shot_index':1,'declared_characters':['刘备'],'description_characters':['刘备','关羽']}


def test_real_746c_closure_fixture_builds_one_complete_structured_repair_plan():
    fixture_path=Path(__file__).parent/'fixtures/shot_contract_closure_746c011b.json'
    source=json.loads(fixture_path.read_text())
    shots=[]
    expected={}
    for item in source['violations']:
        shots.append({'description':'Scene: 真实冻结场景\nCharacters:\n'+'\n'.join(item['characters_block'])+'\nAction: 静止',
            'video_description':'保持静止。','characters':item['declared_characters']})
        expected[item['shot_index']]=item['missing_characters']
    # Preserve the original sparse shot indexes from the immutable production response.
    plan={'shots':[]}
    by_index={item['shot_index']:shot for item,shot in zip(source['violations'],shots)}
    for index in range(1,max(by_index)+1):
        plan['shots'].append(by_index.get(index,{'description':'Scene: 空镜\nCharacters:\nAction: 静止',
            'video_description':'保持静止。','characters':[]}))
    findings=collect_visible_character_findings(plan)
    assert len(findings)==6 and classify_auto_repair(findings,findings[0]['message'])=='AUTO_REPAIRABLE'
    assert {item['shot_index']:item['missing_characters'] for item in findings}==expected
    repair=build_auto_repair_plan(findings)
    assert repair['attempt']==repair['budget']==1 and len(repair['targets'])==6
    patch={'repair_type':'SHOT_VISIBLE_CHARACTER_CLOSURE','repairs':[
        {'shot_index':target['shot_index'],'field':'description','characters':[
            {'name':name,'visual_description':f'{name}位于当前画面中，面向主要行动区域，保持静态可见姿态'}
            for name in target['missing_characters']]}
        for target in repair['targets']]}
    repaired=apply_auto_repair_response(plan,repair,json.dumps(patch,ensure_ascii=False))
    assert collect_visible_character_findings(repaired)==[]
    targets={item['shot_index'] for item in repair['targets']}
    for index,(before,after) in enumerate(zip(plan['shots'],repaired['shots']),1):
        if index not in targets:assert before==after
        else:
            assert before['description'].split('Characters:',1)[0]==after['description'].split('Characters:',1)[0]
            assert before['description'].split('Action:',1)[1]==after['description'].split('Action:',1)[1]
            assert {key:value for key,value in before.items() if key!='description'}=={
                key:value for key,value in after.items() if key!='description'}


def test_auto_repair_has_one_registry_prompt_while_policy_stays_in_code():
    templates=[item for item in SYSTEM_PROMPT_TEMPLATES if item['type']=='shot_contract_repair']
    assert len(templates)==1 and templates[0]['name']=='分镜契约自动修复 V1'
    assert '[version: shot-contract-auto-repair-v1]' in templates[0]['template']
    assert 'SHOT_VISIBLE_CHARACTER_CLOSURE' in templates[0]['template']
    assert 'SHOT_CROSSES_APPEARANCE_BOUNDARY' in templates[0]['template']
    assert 'SOURCE_SPAN_AWARE' in templates[0]['template'] and 'SCENE_UNRESOLVED' in templates[0]['template']
    assert 'Scene ID' in templates[0]['template'] and 'offset' in templates[0]['template']
    assert '黄巾军' not in templates[0]['template'] and 'repair_budget = 1' not in templates[0]['template']
    assert classify_auto_repair([{'code':'SHOT_CROSSES_SCENE_BOUNDARY'}],
        'SHOT_CROSSES_SCENE_BOUNDARY: {}')=='HUMAN_REQUIRED'


def test_auto_repair_registry_supports_system_default_and_user_copy(db_session):
    service=PromptTemplateService(db_session);service.init_system_templates()
    system=service.get_default_system_template('shot_contract_repair')
    assert system and system.is_system and system.is_active
    copied=service.copy_template(system.id)
    assert not copied.is_system and copied.type=='shot_contract_repair' and copied.template==system.template


def test_quoted_titles_are_not_invented_spoken_lines():
    text='皆号“十常侍”。帝呼让为“阿父”。旗上书“甲子”。刀名“冷艳锯”。玄德曰：“愿闻其志。”阿乐大喊：“狼来了！”'
    assert direct_speech_quotes(text)==['愿闻其志。','狼来了！']


def test_action_colon_quotes_remain_authorable_outside_automatic_attribution_grammar():
    text='阿乐哈哈大笑："我骗你们的！"村民摆摆手："他又在骗人。"他回村认错："我不该说谎。"旗上书：“甲子”。'
    # source-attribution-v1 does not infer speech from an arbitrary action + colon.
    # The product still accepts explicitly authored/director DIALOGUE for it.
    assert direct_speech_quotes(text)==[]
    from regression_review.cases import story,full_validate
    candidate,basis=story([('阿青哈哈大笑：','VISUAL'),('“我骗你们的！”','DIALOGUE')])
    assert full_validate(candidate,basis)['counts']['dialogue']==1
    candidate['shots'][0]['audio_events']=[];candidate['shots'][0]['dialogues']=[]
    with pytest.raises(SplitReview,match='DIALOGUE_EVENT_MISSING'):full_validate(candidate,basis)


@pytest.mark.parametrize('occurrences',[0,2])
def test_quote_review_distinguishes_missing_from_repeated_speech(db_session,chapter,fixture,occurrences):
    from copy import deepcopy
    from app.models.chapter_shot_split import ChapterShotSplitRun, ShotSource
    plan=output();spoken=plan['shots'][1]
    for key in ('dialogues','audio_events'):
        event=spoken[key][0]
        spoken[key]=[{**deepcopy(event),'order':index+1} for index in range(occurrences)]
    result=execute(db_session,chapter,LLM(db_session,plan))
    assert not result['success']
    detail=json.loads(result['message'].split(': ',1)[1])
    expected='DIALOGUE_EVENT_MISSING' if occurrences==0 else 'TREATMENT_CONFLICT'
    issue=next(item for item in detail if item['code']==expected)
    assert issue['actual_count']==occurrences
    assert issue['treatment_key']=='speech'
    assert db_session.query(ShotSource).count()==0
    assert db_session.query(ChapterShotSplitRun).one().status=='NEEDS_REVIEW'


def test_explicit_fresh_split_preserves_failure_without_reusing_rejected_draft(db_session,chapter,fixture):
    from app.services.chapter_shot_split_service import ChapterShotSplitService
    from app.models.chapter_shot_split import ChapterShotSplitRun
    bad=output();bad['shots'][0]['description']=bad['shots'][0]['description'].replace('Action:','- 关羽: 站立\nAction:')
    assert not execute(db_session,chapter,LLM(db_session,bad))['success']
    llm=LLM(db_session)
    result=asyncio.run(ChapterShotSplitService(db_session,llm).split(chapter.novel_id,chapter.id,repair_previous=False))
    assert result['success'],result
    latest=db_session.get(ChapterShotSplitRun,result['data']['splitRunId'])
    assert latest.inputs['repair'] is None and latest.inputs['repair_previous'] is False
    assert 'previous_rejected_attempt' not in llm.calls[0]['user_content']
    assert db_session.query(ChapterShotSplitRun).filter_by(status='NEEDS_REVIEW').count()==1
