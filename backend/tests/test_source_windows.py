"""R-SW1: per-visible-character Appearance-aware source windows."""
from copy import deepcopy
import json

import pytest

from app.schemas.chapter_shot_split import parse_output
from app.services.chapter_scope import (OWNERSHIP_VERSION, SCENE_BOUNDARY_RUN_VERSION,
    SOURCE_WINDOW_RUN_VERSION, SOURCE_WINDOW_VERSION, SplitReview, build_source_windows,
    collect_appearance_crossing_findings, deterministic_scene_crossing,
    direct_local_scene_evidence, validate_plan)
from app.services.shot_contract_auto_repair import (CREATIVE_COMPLETION,SCENE_POLICY_VERSION,
    apply_response as apply_auto_repair_response,build_plan as build_auto_repair_plan)


def selection(kind,appearance_id=None,event_id=None):
    return {'kind':kind,'appearanceId':appearance_id,'sourceEventIds':[event_id] if event_id else [],
        'sourceChapterId':'chapter' if event_id else None,
        'reason':'NEW_EVENT' if event_id else 'NO_PRIOR_CHANGE_VERIFIED'}


def character(name,segments):
    return {'characterId':'id-'+name,'name':name,'segments':[
        {'start':start,'end':end,'selection':state} for start,end,state in segments]}


def scene(name,evidence=None):
    return {'name':name,'assetId':'scene-'+name,'sourceEvidence':[{'text':evidence}] if evidence else []}


def scope(text,characters,scenes=None,version=SCENE_BOUNDARY_RUN_VERSION):
    target={'characters':characters}
    windows=build_source_windows(target,text,'timeline-run') or {
        'version':SOURCE_WINDOW_VERSION,'offset_unit':'UNICODE_CODE_POINT','end_exclusive':True,
        'timeline_run_id':'timeline-run','hard_boundaries':[],'characters':[],'unresolved_characters':[]}
    boundaries=[{'character_id':item['characterId'],'name':item['name'],'segments':[
        {'start':segment['start'],'end':segment['end'],'logical_status':segment['selection']['kind'],
         'opening_text':text[segment['start']:min(segment['end'],segment['start']+48)],
         'closing_text':text[max(segment['start'],segment['end']-48):segment['end']]}
        for segment in item['segments']]} for item in characters]
    bindings=[{'name':item['name'],'assetId':item['characterId']} for item in characters]
    return {'version':version,'source':{'title':'章','content':text,'hash':'source'},'source_contract_version':OWNERSHIP_VERSION,
        'scope':{'characters':{'bindings':bindings},'scenes':{'bindings':scenes or [scene('场景')]},
                  'props':{'bindings':[]}},'appearance_boundaries':boundaries,'source_windows':windows}


def planned(index,text,characters,scene_name='场景'):
    return {'id':index,'source_citations':[{'text':text}],'source_ownership':{'text':text},
        'description':f'Scene: {scene_name}\nCharacters:\n'+''.join(f'- {name}: 静止\n' for name in characters)+'Action: 静止',
        'video_description':'保持静止，全程不产生说话口型。','characters':characters,'scene':scene_name,'props':[],
        'duration':1,'continuity_mode':'NORMAL','dialogues':[],'audio_events':[],
        'source_treatments':[{'key':'visual','type':'VISUAL','source_evidence':[{'text':text}],
            'visual_targets':['description']}]}


def plan(text,basis,parts):
    shots=[];cursor=0
    for index,part in enumerate(parts,1):
        value,names,*selected_scene=part
        start=text.index(value,cursor);end=start+len(value);cursor=end
        shots.append(planned(index,value,names,selected_scene[0] if selected_scene else '场景'))
    used=[];used_scenes=[]
    for shot in shots:
        for name in shot['characters']:
            if name not in used:used.append(name)
        if shot['scene'] not in used_scenes:used_scenes.append(shot['scene'])
    return {'source_contract_version':OWNERSHIP_VERSION,'chapter':'章','characters':used,
        'scenes':used_scenes,'props':[],'unresolved_assets':[],'shots':shots}


def validate(data,basis):
    return validate_plan(data,basis,historical_structure=True)


def test_r_sc1_rejects_only_ordered_distinct_direct_local_scene_evidence():
    text='甲地议事。乙地集结。';scenes=[scene('甲地','甲地议事。'),scene('乙地','乙地集结。')]
    basis=scope(text,[],scenes);data=plan(text,basis,[(text,[],'甲地')])
    with pytest.raises(SplitReview,match='SHOT_CROSSES_SCENE_BOUNDARY') as raised:validate(data,basis)
    detail=json.loads(str(raised.value).split(': ',1)[1])
    assert detail=={'shot_index':1,'evidence_range':[0,len(text)],
        'proof':'ORDERED_DISTINCT_DIRECT_LOCAL_SCENE_EVIDENCE','scene_evidence':[
            {'scene':'甲地','sceneAssetId':'scene-甲地','text':'甲地议事。','range':[0,5]},
            {'scene':'乙地','sceneAssetId':'scene-乙地','text':'乙地集结。','range':[5,10]}]}
    reversed_basis=scope(text,[],list(reversed(scenes)))
    with pytest.raises(SplitReview) as reversed_error:validate(data,reversed_basis)
    assert str(reversed_error.value)==str(raised.value)
    historical=deepcopy(basis);historical['version']=SOURCE_WINDOW_RUN_VERSION
    assert len(validate(data,historical))==1


def test_r_sc1_abstains_without_two_ordered_distinct_direct_local_witnesses():
    cases=[]
    cases.append(('甲地整军，随后投乙地而去。',[scene('甲地','甲地整军'),scene('乙地','前文乙地证据')]))
    cases.append(('甲地。重复。重复。',[scene('甲地','甲地。'),scene('乙地','重复。')]))
    cases.append(('甲乙场景。',[scene('甲地','甲乙场景。'),scene('乙地','乙场景。')]))
    empty=scene('乙地','乙地。');empty['membershipEvidence']=[]
    cases.append(('甲地。乙地。',[scene('甲地','甲地。'),empty]))
    aliases=[scene('甲地','甲地。'),scene('乙地','乙地。')]
    aliases[0]['assetId']=aliases[1]['assetId']='shared-scene'
    cases.append(('甲地。乙地。',aliases))
    missing_ids=[scene('甲地','甲地。'),scene('乙地','乙地。')]
    for item in missing_ids:item.pop('assetId')
    cases.append(('甲地。乙地。',missing_ids))
    for text,scenes in cases:
        basis=scope(text,[],scenes);data=plan(text,basis,[(text,[],'甲地')])
        assert deterministic_scene_crossing(basis,0,len(text)) is None
        assert len(validate(data,basis))==1


def test_no_appearance_boundary_keeps_empty_window_assertions():
    text='甲平静站立。';basis=scope(text,[character('甲',[(0,len(text),selection('BASE'))])])
    assert basis['source_windows']['characters']==[] and basis['source_windows']['hard_boundaries']==[]
    assert validate(plan(text,basis,[(text,['甲'])]),basis)[0]['start']==0


def test_single_boundary_and_exact_endpoints_are_valid():
    text='甲锻造。甲披甲。';boundary=text.index('甲披甲')
    basis=scope(text,[character('甲',[(0,boundary,selection('BASE')),
        (boundary,len(text),selection('APPEARANCE','armor','event'))])])
    data=plan(text,basis,[(text[:boundary],['甲']),(text[boundary:],['甲'])])
    prepared=validate(data,basis)
    assert [(item['start'],item['end']) for item in prepared]==[(0,boundary),(boundary,len(text))]
    assert all(len(item['source_window_bindings'])==1 for item in prepared)


def test_three_characters_share_one_boundary_and_bind_independently():
    text='三人备战。三人披甲。';boundary=text.index('三人披甲')
    chars=[character(name,[(0,boundary,selection('BASE')),
        (boundary,len(text),selection('APPEARANCE','armor-'+name,'event-'+name))]) for name in ('刘备','关羽','张飞')]
    basis=scope(text,chars);data=plan(text,basis,[(text[:boundary],['刘备','关羽','张飞']),
        (text[boundary:],['刘备','关羽','张飞'])])
    assert len(basis['source_windows']['hard_boundaries'])==1
    assert basis['source_windows']['hard_boundaries'][0]=={'offset':boundary,'characters':['刘备','关羽','张飞']}
    assert all(len(item['source_window_bindings'])==3 for item in validate(data,basis))


def test_multiple_boundaries_create_non_overlapping_half_open_windows():
    text='甲便服。甲披甲。甲卸甲。';first=text.index('甲披甲');second=text.index('甲卸甲')
    basis=scope(text,[character('甲',[(0,first,selection('BASE')),
        (first,second,selection('APPEARANCE','armor','event-1')),
        (second,len(text),selection('APPEARANCE','plain','event-2'))])])
    windows=basis['source_windows']['characters'][0]['windows']
    assert [(item['start'],item['end']) for item in windows]==[(0,first),(first,second),(second,len(text))]
    assert len({item['window_id'] for item in windows})==3
    assert len(validate(plan(text,basis,[(text[:first],['甲']),(text[first:second],['甲']),
        (text[second:],['甲'])]),basis))==3


def test_true_crossing_remains_rejected_by_existing_validator():
    text='甲锻造。甲披甲。';boundary=text.index('甲披甲')
    basis=scope(text,[character('甲',[(0,boundary,selection('BASE')),
        (boundary,len(text),selection('APPEARANCE','armor','event'))])])
    data=plan(text,basis,[(text,['甲'])])
    with pytest.raises(SplitReview,match='SHOT_CROSSES_APPEARANCE_BOUNDARY'):validate(data,basis)


def test_program_derives_window_binding_without_model_assertion():
    text='甲锻造。甲披甲。';boundary=text.index('甲披甲')
    basis=scope(text,[character('甲',[(0,boundary,selection('BASE')),
        (boundary,len(text),selection('APPEARANCE','armor','event'))])])
    data=plan(text,basis,[(text[:boundary],['甲']),(text[boundary:],['甲'])])
    prepared=validate(data,basis)
    assert 'source_window_bindings' not in data['shots'][0]
    assert prepared[0]['source_window_bindings'][0]['name']=='甲'
    assert prepared[0]['bindings']['source_windows']==prepared[0]['source_window_bindings']


def test_unrelated_visible_character_can_cross_another_characters_boundary():
    text='甲锻造，乙旁观。甲披甲，乙仍旁观。';boundary=text.index('甲披甲')
    basis=scope(text,[character('甲',[(0,boundary,selection('BASE')),
        (boundary,len(text),selection('APPEARANCE','armor','event'))]),
        character('乙',[(0,len(text),selection('BASE'))])])
    data=plan(text,basis,[(text,['乙'])])
    assert 'source_window_bindings' not in data['shots'][0]
    assert validate(data,basis)[0]['source_window_bindings']==[]


def test_unicode_code_point_offsets_include_astral_character_once():
    text='🐺甲站定。甲披甲。';boundary=text.index('甲披甲')
    assert boundary==5
    basis=scope(text,[character('甲',[(0,boundary,selection('BASE')),
        (boundary,len(text),selection('APPEARANCE','armor','event'))])])
    assert basis['source_windows']['offset_unit']=='UNICODE_CODE_POINT'
    assert basis['source_windows']['characters'][0]['windows'][1]['start']==5
    assert len(validate(plan(text,basis,[(text[:boundary],['甲']),(text[boundary:],['甲'])]),basis))==2


def test_unresolved_timeline_never_fabricates_a_hard_window():
    text='甲状态不明。';windows=build_source_windows({'characters':[character('甲',[
        (0,len(text),selection('UNRESOLVED'))])]},text,'timeline-run')
    assert windows['characters']==[]
    assert windows['unresolved_characters']==[{'character_id':'id-甲','name':'甲'}]


def test_windowed_wire_schema_keeps_program_derived_field_out_of_llm_output():
    text='甲站立。';basis=scope(text,[character('甲',[(0,len(text),selection('BASE'))])])
    data=plan(text,basis,[(text,['甲'])]);raw=json.dumps(data,ensure_ascii=False)
    parsed=parse_output(raw,OWNERSHIP_VERSION,SOURCE_WINDOW_VERSION)
    assert 'source_window_bindings' not in parsed['shots'][0]
    injected=deepcopy(data);injected['shots'][0]['source_window_bindings']=[]
    with pytest.raises(Exception):parse_output(json.dumps(injected,ensure_ascii=False),OWNERSHIP_VERSION,SOURCE_WINDOW_VERSION)


def test_audio_whitespace_is_restored_from_exact_owned_source_with_receipt():
    text='甲行。\n乙停。';basis=scope(text,[]);data=plan(text,basis,[(text,[])])
    data['shots'][0]['audio_events']=[{'order':1,'type':'NARRATION','voice_owner':'旁白',
        'visible_speaker':None,'requires_visible_lipsync':False,'text':'甲行。乙停。',
        'emotion_prompt':'平静','pause_after':'NONE','treatment_ref':'narration'}]
    prepared=validate(data,basis);item=prepared[0]
    assert item['audio'][0]['text']==text
    assert item['source_contract']['deterministic_normalizations']==[{
        'kind':'SOURCE_WHITESPACE_RESTORED','field':'audio_events','order':1,
        'input_hash':__import__('app.services.chapter_asset_parse_service',fromlist=['digest']).digest('甲行。乙停。'),
        'output_hash':__import__('app.services.chapter_asset_parse_service',fromlist=['digest']).digest(text),
        'source_start':0,'source_end':len(text)}]


def test_shot13_weapon_forging_and_armoring_fixture_must_split_at_event():
    before='玄德谢别二客，便命良匠打造双股剑。云长造青龙偃月刀，又名“冷艳锯”，重八十二斤。张飞造丈八点钢矛。'
    after='各置全身铠甲。共聚乡勇五百余人，来见邹靖。邹靖引见太守刘焉。'
    text=before+after;boundary=len(before)
    chars=[character(name,[(0,boundary,selection('BASE')),
        (boundary,len(text),selection('APPEARANCE','armor-'+name,'event-'+name))]) for name in ('刘备','关羽','张飞')]
    basis=scope(text,chars)
    crossing=plan(text,basis,[(text,['刘备','关羽','张飞'])]);crossing['shots'][0]['duration']=2
    with pytest.raises(SplitReview,match='SHOT_CROSSES_APPEARANCE_BOUNDARY'):validate(crossing,basis)
    findings=collect_appearance_crossing_findings(crossing,basis)
    repair=build_auto_repair_plan(findings,crossing,basis)
    assert len(findings)==3 and len(repair['targets'])==1
    assert repair['targets'][0]['hard_boundaries'][0]['affected_characters']==['刘备','关羽','张飞']
    assert [(item['start'],item['end']) for item in repair['targets'][0]['required_windows']]==[(0,boundary),(boundary,len(text))]
    repaired=plan(text,basis,[(before,['刘备','关羽','张飞']),(after,['刘备','关羽','张飞'])])
    patch={'repair_type':'SHOT_CROSSES_APPEARANCE_BOUNDARY','repairs':[{
        'shot_index':1,'replacements':repaired['shots']}]}
    composed=apply_auto_repair_response(crossing,repair,json.dumps(patch,ensure_ascii=False),basis)
    assert [item['source_ownership']['text'] for item in composed['shots']]==[before,after]
    assert [item['id'] for item in composed['shots']]==[1,2]
    prepared=validate(composed,basis)
    assert [(item['start'],item['end']) for item in prepared]==[(0,boundary),(boundary,len(text))]
    assert all(item['end']<=boundary or item['start']>=boundary for item in prepared)


def test_scene_aware_boundary_resplit_accepts_unique_child_local_scene_evidence():
    before='张飞庄中锻造兵器。';after='众人抵达涿县拜见刘焉。';text=before+after;boundary=len(before)
    chars=[character('甲',[(0,boundary,selection('BASE')),
        (boundary,len(text),selection('APPEARANCE','armor','event'))])]
    basis=scope(text,chars,[scene('张飞庄','张飞庄中锻造兵器'),scene('涿县','抵达涿县拜见刘焉')])
    crossing=plan(text,basis,[(text,['甲'],'张飞庄')]);crossing['shots'][0]['duration']=2
    with pytest.raises(SplitReview,match='SHOT_CROSSES_APPEARANCE_BOUNDARY'):validate(crossing,basis)
    findings=collect_appearance_crossing_findings(crossing,basis);repair=build_auto_repair_plan(findings,crossing,basis)
    replacements=[planned(1,before,['甲'],'张飞庄'),planned(2,after,['甲'],'涿县')]
    patch={'repair_type':'SHOT_CROSSES_APPEARANCE_BOUNDARY','repairs':[{'shot_index':1,'replacements':replacements}]}
    decisions=[];composed=apply_auto_repair_response(crossing,repair,json.dumps(patch,ensure_ascii=False),basis,decisions)
    assert [item['state'] for item in decisions]==['SAME_SCENE','SOURCE_SPAN_AWARE_SCENE_CHANGE']
    assert decisions[1]['supportedScenes']==[{'name':'涿县','evidence':[{'text':'抵达涿县拜见刘焉','start':boundary+2,'end':len(text)-1}]}]
    assert composed['scenes']==['张飞庄','涿县']
    assert [(item['start'],item['end']) for item in validate(composed,basis)]==[(0,boundary),(boundary,len(text))]
    strict_empty=deepcopy(basis);alternate=strict_empty['scope']['scenes']['bindings'][1]
    alternate['membershipEvidence']=[]
    strict_repair=build_auto_repair_plan(findings,crossing,strict_empty,
        scene_policy_version=SCENE_POLICY_VERSION)
    with pytest.raises(ValueError,match='SHOT_CONTRACT_REPAIR_SCENE_UNRESOLVED'):
        apply_auto_repair_response(crossing,strict_repair,json.dumps(patch,ensure_ascii=False),strict_empty,[])


def test_scene_aware_boundary_resplit_rejects_unbound_or_unsupported_change():
    before='张飞庄中锻造。';after='众人前去会合。';text=before+after;boundary=len(before)
    chars=[character('甲',[(0,boundary,selection('BASE')),
        (boundary,len(text),selection('APPEARANCE','armor','event'))])]
    basis=scope(text,chars,[scene('张飞庄','张飞庄中锻造'),scene('涿县','前文涿县证据')])
    crossing=plan(text,basis,[(text,['甲'],'张飞庄')]);crossing['shots'][0]['duration']=2
    repair=build_auto_repair_plan(collect_appearance_crossing_findings(crossing,basis),crossing,basis,
        scene_policy_version=SCENE_POLICY_VERSION)
    replacements=[planned(1,before,['甲'],'张飞庄'),planned(2,after,['甲'],'未绑定场景')]
    patch={'repair_type':'SHOT_CROSSES_APPEARANCE_BOUNDARY','repairs':[{'shot_index':1,'replacements':replacements}]}
    decisions=[]
    with pytest.raises(ValueError,match='SHOT_CONTRACT_REPAIR_SCENE_UNRESOLVED'):
        apply_auto_repair_response(crossing,repair,json.dumps(patch,ensure_ascii=False),basis,decisions)
    assert decisions[-1]['state']=='SCENE_UNRESOLVED' and decisions[-1]['reason']=='SCENE_OUTSIDE_CHAPTER_SCOPE'


def test_current_scene_policy_records_source_silent_creative_completion():
    before='张飞庄中锻造。';after='众人前去会合。';text=before+after;boundary=len(before)
    chars=[character('甲',[(0,boundary,selection('BASE')),
        (boundary,len(text),selection('APPEARANCE','armor','event'))])]
    basis=scope(text,chars,[scene('张飞庄','张飞庄中锻造'),scene('幽州太守府议事厅','前文其他证据')])
    crossing=plan(text,basis,[(text,['甲'],'张飞庄')]);crossing['shots'][0]['duration']=2
    repair=build_auto_repair_plan(collect_appearance_crossing_findings(crossing,basis),crossing,basis)
    replacements=[planned(1,before,['甲'],'张飞庄'),planned(2,after,['甲'],'幽州太守府议事厅')]
    patch={'repair_type':'SHOT_CROSSES_APPEARANCE_BOUNDARY','repairs':[{'shot_index':1,'replacements':replacements}]}
    decisions=[];composed=apply_auto_repair_response(crossing,repair,json.dumps(patch,ensure_ascii=False),basis,decisions)
    assert decisions[-1]['state']==CREATIVE_COMPLETION
    assert decisions[-1]['grounding']=='CREATIVE_COMPLETION'
    assert decisions[-1]['reason']=='SOURCE_SILENT_CREATIVE_COMPLETION'
    assert decisions[-1]['sceneAssetId']=='scene-幽州太守府议事厅' and decisions[-1]['supportedScenes']==[]
    assert composed['shots'][1]['scene']=='幽州太守府议事厅'


def test_current_creative_policy_never_overrides_explicit_conflicting_scene():
    before='父场景准备。';after='甲地明确会合。';text=before+after;boundary=len(before)
    chars=[character('甲',[(0,boundary,selection('BASE')),
        (boundary,len(text),selection('APPEARANCE','armor','event'))])]
    basis=scope(text,chars,[scene('父场景','父场景准备'),scene('甲地','甲地明确会合'),scene('乙地','前文乙地')])
    crossing=plan(text,basis,[(text,['甲'],'父场景')]);crossing['shots'][0]['duration']=2
    repair=build_auto_repair_plan(collect_appearance_crossing_findings(crossing,basis),crossing,basis)
    replacements=[planned(1,before,['甲'],'父场景'),planned(2,after,['甲'],'乙地')]
    patch={'repair_type':'SHOT_CROSSES_APPEARANCE_BOUNDARY','repairs':[{'shot_index':1,'replacements':replacements}]}
    decisions=[]
    with pytest.raises(ValueError,match='SHOT_CONTRACT_REPAIR_SCENE_UNRESOLVED'):
        apply_auto_repair_response(crossing,repair,json.dumps(patch,ensure_ascii=False),basis,decisions)
    assert decisions[-1]['state']=='SCENE_UNRESOLVED'
    assert decisions[-1]['supportedScenes'][0]['name']=='甲地'


@pytest.mark.parametrize('after',['众人并未到甲地，继续赶路。','众人商议明日去甲地。'])
def test_scene_name_mention_vetoes_creative_but_is_not_affirmative_grounding(after):
    before='父场景准备。';text=before+after;boundary=len(before)
    chars=[character('甲',[(0,boundary,selection('BASE')),
        (boundary,len(text),selection('APPEARANCE','armor','event'))])]
    basis=scope(text,chars,[scene('父场景','父场景准备'),scene('甲地','前文甲地证据')])
    crossing=plan(text,basis,[(text,['甲'],'父场景')]);crossing['shots'][0]['duration']=2
    repair=build_auto_repair_plan(collect_appearance_crossing_findings(crossing,basis),crossing,basis)
    replacements=[planned(1,before,['甲'],'父场景'),planned(2,after,['甲'],'甲地')]
    patch={'repair_type':'SHOT_CROSSES_APPEARANCE_BOUNDARY','repairs':[{'shot_index':1,'replacements':replacements}]}
    decisions=[]
    with pytest.raises(ValueError,match='SHOT_CONTRACT_REPAIR_SCENE_UNRESOLVED'):
        apply_auto_repair_response(crossing,repair,json.dumps(patch,ensure_ascii=False),basis,decisions)
    assert decisions[-1]['reason']=='SCENE_SIGNAL_REQUIRES_DIRECT_GROUNDING'
    assert decisions[-1]['sceneNameMentions']==['甲地'] and decisions[-1]['supportedScenes']==[]


def test_scene_aware_policy_rejects_ambiguous_support_and_parent_fallback():
    before='父场景内准备。';after='甲地证据与乙地证据并列。';text=before+after;boundary=len(before)
    chars=[character('甲',[(0,boundary,selection('BASE')),
        (boundary,len(text),selection('APPEARANCE','armor','event'))])]
    basis=scope(text,chars,[scene('父场景','父场景内准备'),scene('甲地','甲地证据'),scene('乙地','乙地证据')])
    crossing=plan(text,basis,[(text,['甲'],'父场景')]);crossing['shots'][0]['duration']=2
    repair=build_auto_repair_plan(collect_appearance_crossing_findings(crossing,basis),crossing,basis,
        scene_policy_version=SCENE_POLICY_VERSION)
    for proposed,reason in [('父场景','PARENT_SCENE_CONTRADICTED_BY_CHILD_SPAN'),
                            ('甲地','NO_UNIQUE_CHILD_SPAN_SCENE_SUPPORT')]:
        replacements=[planned(1,before,['甲'],'父场景'),planned(2,after,['甲'],proposed)]
        patch={'repair_type':'SHOT_CROSSES_APPEARANCE_BOUNDARY','repairs':[{'shot_index':1,'replacements':replacements}]}
        decisions=[]
        with pytest.raises(ValueError,match='SHOT_CONTRACT_REPAIR_SCENE_UNRESOLVED'):
            apply_auto_repair_response(crossing,repair,json.dumps(patch,ensure_ascii=False),basis,decisions)
        assert decisions[-1]['state']=='SCENE_UNRESOLVED'
        assert decisions[-1]['reason']==reason


def test_scene_aware_policy_ignores_repeated_evidence_and_rejects_model_proof_fields():
    before='父场景准备。';after='重复证据。重复证据。';text=before+after;boundary=len(before)
    chars=[character('甲',[(0,boundary,selection('BASE')),
        (boundary,len(text),selection('APPEARANCE','armor','event'))])]
    basis=scope(text,chars,[scene('父场景','父场景准备'),scene('新场景','重复证据')])
    crossing=plan(text,basis,[(text,['甲'],'父场景')]);crossing['shots'][0]['duration']=2
    repair=build_auto_repair_plan(collect_appearance_crossing_findings(crossing,basis),crossing,basis,
        scene_policy_version=SCENE_POLICY_VERSION)
    replacements=[planned(1,before,['甲'],'父场景'),planned(2,after,['甲'],'新场景')]
    patch={'repair_type':'SHOT_CROSSES_APPEARANCE_BOUNDARY','repairs':[{'shot_index':1,'replacements':replacements}]}
    decisions=[]
    with pytest.raises(ValueError,match='SHOT_CONTRACT_REPAIR_SCENE_UNRESOLVED'):
        apply_auto_repair_response(crossing,repair,json.dumps(patch,ensure_ascii=False),basis,decisions)
    assert decisions[-1]['supportedScenes']==[]
    patch['repairs'][0]['replacements'][1]['scene_binding_id']='model-invented-proof'
    with pytest.raises(ValueError,match='SHOT_CONTRACT_REPAIR_OUTPUT_INVALID'):
        apply_auto_repair_response(crossing,repair,json.dumps(patch,ensure_ascii=False),basis,[])


def test_legacy_boundary_repair_plan_replays_strict_parent_scene_policy():
    text='甲准备。甲披甲。';boundary=text.index('甲披甲')
    basis=scope(text,[character('甲',[(0,boundary,selection('BASE')),
        (boundary,len(text),selection('APPEARANCE','armor','event'))])])
    crossing=plan(text,basis,[(text,['甲'])]);crossing['shots'][0]['duration']=2
    findings=collect_appearance_crossing_findings(crossing,basis)
    repair=build_auto_repair_plan(findings,crossing,basis,scene_aware=False)
    assert 'scene_policy' not in repair['targets'][0] and 'scene' in repair['preserve'] and 'change_scene' in repair['forbidden']
    replacements=[planned(1,text[:boundary],['甲']),planned(2,text[boundary:],['甲'])]
    patch={'repair_type':'SHOT_CROSSES_APPEARANCE_BOUNDARY','repairs':[{'shot_index':1,'replacements':replacements}]}
    assert len(apply_auto_repair_response(crossing,repair,json.dumps(patch,ensure_ascii=False),basis)['shots'])==2
    patch['repairs'][0]['replacements'][1]['scene']='其他场景'
    with pytest.raises(ValueError,match='SHOT_CONTRACT_REPAIR_SCENE_CHANGED'):
        apply_auto_repair_response(crossing,repair,json.dumps(patch,ensure_ascii=False),basis)


def test_real_shot18_replays_v1_and_current_policy_records_creative_completion():
    fixture=json.loads((__import__('pathlib').Path(__file__).parent/'fixtures'/'scene_aware_shot18.json').read_text())
    assert fixture['sourceHash']=='09f14b27943324fc8da0e4848a6886dd3e96e987b6973326360874231107452e'
    assert fixture['sceneBindingCount']==len(fixture['sceneBindings'])==13
    frozen=['前']*fixture['chapterLength']
    for item in fixture['sceneBindings']:
        start,end=item['range'];assert end-start==len(item['evidence'])
        for offset,value in enumerate(item['evidence'],start):
            assert frozen[offset] in ('前',value);frozen[offset]=value
    target=fixture['before']+fixture['after'];start=fixture['targetStart'];frozen[start:start+len(target)]=target
    text=''.join(frozen);boundary=start+len(fixture['before'])
    chars=[character(name,[(0,boundary,selection('BASE')),
        (boundary,len(text),selection('APPEARANCE','armor-'+name,'event-'+name))]) for name in fixture['characters']]
    scenes=[scene(item['name'],item['evidence']) for item in fixture['sceneBindings']]
    basis=scope(text,chars,scenes,version=SOURCE_WINDOW_RUN_VERSION);prefix=text[:start];suffix=text[start+len(target):]
    assert direct_local_scene_evidence(basis,start,start+len(target))==[]
    assert deterministic_scene_crossing(basis,start,start+len(target)) is None
    crossing=plan(text,basis,[(prefix,[],fixture['prefixScene']),
        (target,fixture['characters'],fixture['parentScene']),(suffix,[],'高冈')])
    crossing['shots'][1]['duration']=24
    repair=build_auto_repair_plan(collect_appearance_crossing_findings(crossing,basis),crossing,basis)
    replacements=[planned(1,fixture['before'],fixture['characters'],fixture['replacementScenes'][0]),
        planned(2,fixture['after'],fixture['characters'],fixture['replacementScenes'][1])]
    for item in replacements:item['duration']=12
    patch={'repair_type':'SHOT_CROSSES_APPEARANCE_BOUNDARY','repairs':[{'shot_index':2,'replacements':replacements}]}
    decisions=[]
    with pytest.raises(ValueError,match='SHOT_CONTRACT_REPAIR_SCENE_UNRESOLVED'):
        apply_auto_repair_response(crossing,repair,json.dumps(patch,ensure_ascii=False),basis,decisions)
    assert decisions==fixture['expectedSceneDecisions']
    current=deepcopy(basis);current['version']=SCENE_BOUNDARY_RUN_VERSION
    creative_repair=build_auto_repair_plan(
        collect_appearance_crossing_findings(crossing,current),crossing,current)
    creative=[];composed=apply_auto_repair_response(
        crossing,creative_repair,json.dumps(patch,ensure_ascii=False),current,creative)
    assert creative[1]['state']==CREATIVE_COMPLETION
    assert creative[1]['grounding']=='CREATIVE_COMPLETION'
    assert creative[1]['reason']=='SOURCE_SILENT_CREATIVE_COMPLETION'
    assert creative[1]['proposedScene']==fixture['replacementScenes'][1]
    assert composed['shots'][2]['scene']==fixture['replacementScenes'][1]
