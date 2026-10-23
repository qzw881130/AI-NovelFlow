import copy
import json
import re
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from app.services import h3_preflight_repair as repair
from app.services.h3_execution_optimizer import check_authority
from app.models.novel import Novel
from app.models.prompt_template import PromptTemplate
F=Path(__file__).parent/'fixtures'
C2=Path(__file__).resolve().parents[2]/'docs/performance/h3_11_14_validation'
def fixture(name='approved_c1'):return json.loads((F/f'h3_v5_{name}.json').read_text())
def check(f,o):return check_authority(f['raw_prompt'],o,f['authority'],f['initial'],f['limits'])


@pytest.mark.asyncio
async def test_c2_verified_floor_position_wording_l0_passes_full_preflight_without_llm(monkeypatch):
 runtime=json.loads((C2/'14_RUNTIME_INPUT.json').read_text())
 from app.utils.json_parser import safe_parse_llm_json
 original=safe_parse_llm_json((C2/'14_LLM_RESPONSE.txt').read_text(),default=None)
 raw=(C2/'11_RAW_PROMPT.txt').read_text()
 assert original['optimized_prompt']==(C2/'14_CANDIDATE_PROMPT.txt').read_text()
 assert runtime['raw_h3_prompt']==raw
 assert runtime['execution_context']['canonical_transitions'][0]['canonical_source_id']=='transition_2'
 assert runtime['immutable_authority']['dialogue_events']==[]
 before_runtime=copy.deepcopy(runtime)
 recheck=lambda candidate:check_authority(raw,candidate,runtime['immutable_authority'],
                                           runtime['initial_execution_timing'],runtime['duration_limits'])
 initial=recheck(original)
 assert initial['blocking_findings']==['blocking_preservation_wording']
 chat=AsyncMock()
 monkeypatch.setattr(repair,'LLMService',lambda:NS(chat_completion=chat))
 revised,audit,state=await repair.repair_output(None,None,None,original,runtime,initial,recheck)
 assert state['resolution']=='L0_PASS' and state.get('l1_invocations',0)==0
 assert audit['passed'] and not audit['blocking_findings'] and all(audit['checks'].values())
 assert state['attempts'][0]['changes'][0]['code']=='VERIFIED_FLOOR_POSITION_WORDING'
 addition=' Preserve these established floor positions.'
 assert revised['optimized_prompt'].count(addition)==1
 assert revised['optimized_prompt'].replace(addition,'',1)==original['optimized_prompt']
 assert {k:v for k,v in revised.items() if k!='optimized_prompt'}=={k:v for k,v in original.items() if k!='optimized_prompt'}
 assert runtime==before_runtime
 assert revised['av_timeline']['optimized_duration']==8.2
 assert set(re.findall(r'<Picture \d+>',revised['optimized_prompt']))=={'<Picture 1>','<Picture 2>','<Picture 3>'}
 assert '<d>' not in revised['optimized_prompt']
 chat.assert_not_called()


def test_l0_only_restates_explicit_verified_floor_positions():
 prompt=('subject_definitions:\n<Subject 1> is 甲.\n\nsummary:\nCurrent scene.\n\n'
         'retention_analysis:\nContinue the current floor positions established by the incoming video.\n\n'
         'detailed_description:\n<Subject 1> remains visible.\n\noverall_soundscape:\nQuiet.\n\nnon_diegetic_music:\nNone.')
 output={'optimized_prompt':prompt}
 authority={'subject_bindings':{'<Subject 1>':'甲'},'dialogue_events':[],
            'continuation':{'binding_verified':True}}
 fixed,changes=repair.deterministic_candidate(output,authority,['blocking_preservation_wording'])
 assert changes[0]['code']=='VERIFIED_FLOOR_POSITION_WORDING'
 assert fixed['optimized_prompt'].replace(' Preserve these established floor positions.','',1)==prompt
 assert repair.deterministic_candidate(output,authority,[])[0]==output
 unverified=copy.deepcopy(authority);unverified['continuation']['binding_verified']=False
 assert repair.deterministic_candidate(output,unverified,['blocking_preservation_wording'])==(output,[])
 vague={'optimized_prompt':prompt.replace('Continue the current floor positions established by the incoming video.',
                                            'Continue the current scene.')}
 assert repair.deterministic_candidate(vague,authority,['blocking_preservation_wording'])==(vague,[])


@pytest.mark.asyncio
async def test_l1_blocking_wording_only_local_insertion_and_full_recheck(monkeypatch):
 f=fixture();output=copy.deepcopy(f['output'])
 marker='unique blocking marker'
 output['optimized_prompt']=output['optimized_prompt'].replace('retention_analysis:\n','retention_analysis:\n'+marker+'\n')
 text=' Preserve established floor positions.'
 chat=AsyncMock(return_value={'success':True,'content':json.dumps({'insertions':[{'after':marker,'text':text}]})})
 monkeypatch.setattr(repair,'LLMService',lambda:NS(chat_completion=chat))
 monkeypatch.setattr(repair,'resolve_prompt_template',lambda *a:NS(type=repair.TEMPLATE_TYPE,id='registered-id',name='repair',template='registered-v1'))
 initial={'passed':False,'blocking_findings':['blocking_preservation_wording']}
 def recheck(candidate):
  return {'passed':True,'blocking_findings':[]} if text in candidate['optimized_prompt'] else initial
 repaired,audit,state=await repair.repair_output(None,NS(id='n'),NS(chapter_id='c'),output,
                                                  {'immutable_authority':f['authority']},initial,recheck)
 assert state['resolution']=='L1_PASS' and audit['passed'] and state['l1_invocations']==1
 assert chat.await_count==1
 request=json.loads(chat.await_args.kwargs['user_content'])
 assert request['failed_checks']==['blocking_preservation_wording']
 assert request['original_optimized_output']==output
 assert 'images' not in chat.await_args.kwargs
 assert repaired['optimized_prompt'].replace(text,'',1)==output['optimized_prompt']
 assert {k:v for k,v in repaired.items() if k!='optimized_prompt'}=={k:v for k,v in output.items() if k!='optimized_prompt'}


@pytest.mark.asyncio
@pytest.mark.parametrize('failed,section,text',[
 ('reference_authority_scope','retention_analysis',' Identity references preserve permanent identity only.'),
 ('speaker_switch_listener_settle','detailed_description',' All other visible characters listen naturally with relaxed closed lips and no speech-like articulation.'),
 ('speaker_switch_listener_scope','detailed_description',' Every other visible character listens naturally with relaxed closed lips and no speech-like articulation.'),
])
async def test_existing_l1_repair_categories_remain_eligible(monkeypatch,failed,section,text):
 f=fixture();output=copy.deepcopy(f['output']);marker='unique legacy repair marker'
 output['optimized_prompt']=output['optimized_prompt'].replace(section+':\n',section+':\n'+marker+'\n')
 chat=AsyncMock(return_value={'success':True,'content':json.dumps({'insertions':[{'after':marker,'text':text}]})})
 monkeypatch.setattr(repair,'LLMService',lambda:NS(chat_completion=chat))
 monkeypatch.setattr(repair,'resolve_prompt_template',lambda *a:NS(type=repair.TEMPLATE_TYPE,id='registered-id',name='repair',template='registered-v1'))
 initial={'passed':False,'blocking_findings':[failed]}
 recheck=lambda candidate:{'passed':True,'blocking_findings':[]} if text in candidate['optimized_prompt'] else initial
 revised,audit,state=await repair.repair_output(None,NS(id='n'),NS(chapter_id='c'),output,
                                                  {'immutable_authority':f['authority']},initial,recheck)
 assert state['resolution']=='L1_PASS' and audit['passed'] and state['l1_invocations']==1
 assert text in revised['optimized_prompt'] and chat.await_count==1


@pytest.mark.asyncio
async def test_l1_new_authority_conflict_still_fails(monkeypatch):
 f=fixture();output=copy.deepcopy(f['output']);marker='unique blocking marker'
 output['optimized_prompt']=output['optimized_prompt'].replace('retention_analysis:\n','retention_analysis:\n'+marker+'\n')
 text=' Preserve established floor positions. PHASE'
 chat=AsyncMock(return_value={'success':True,'content':json.dumps({'insertions':[{'after':marker,'text':text}]})})
 monkeypatch.setattr(repair,'LLMService',lambda:NS(chat_completion=chat))
 monkeypatch.setattr(repair,'resolve_prompt_template',lambda *a:NS(type=repair.TEMPLATE_TYPE,id='registered-id',name='repair',template='registered-v1'))
 initial={'passed':False,'blocking_findings':['blocking_preservation_wording']}
 def recheck(candidate):
  return {'passed':False,'blocking_findings':['no_internal_execution_dsl']} if text in candidate['optimized_prompt'] else initial
 repaired,audit,state=await repair.repair_output(None,NS(id='n'),NS(chapter_id='c'),output,
                                                  {'immutable_authority':f['authority']},initial,recheck)
 assert state['resolution']=='L1_FAILED_PREFLIGHT' and not audit['passed']
 assert audit['blocking_findings']==initial['blocking_findings'] and repaired==output
 assert state['attempts'][-1]['preflight']['blocking_findings']==['no_internal_execution_dsl']
 assert chat.await_count==1


@pytest.mark.asyncio
async def test_preflight_passed_output_is_never_repaired(monkeypatch):
 f=fixture();output=copy.deepcopy(f['output']);audit=check(f,output)
 chat=AsyncMock();monkeypatch.setattr(repair,'LLMService',lambda:NS(chat_completion=chat))
 revised,final,state=await repair.repair_output(None,None,None,output,{'immutable_authority':f['authority']},audit,lambda _:audit)
 assert state['resolution']=='ALREADY_PASS' and revised==output and final==audit
 chat.assert_not_called()

@pytest.mark.parametrize('name',['approved_c1','c2_repeated_provenance','c3_fragment_provenance','c6_opening_authority'])
def test_saved_approved_outputs_unchanged(name):
 f=fixture(name);original=copy.deepcopy(f['output'])
 candidate,changes=repair.deterministic_candidate(original,f['authority'])
 assert not changes
 assert candidate==original
 assert check(f,candidate)['passed']

def test_l0_only_unique_canonical_name_and_anchor_id():
 a={'subject_bindings':{'<Subject 1>':'宫廷总管','<Subject 2>':'皇帝'},'dialogue_events':[],
    'anchor_policy':{'catalog':[{'source_picture':'<Picture 1>','anchor_id':'KF7'}]}}
 o={'optimized_prompt':'<Subject 1> is 宫延总管, identity.','anchor_decisions':[{'id':'<Picture 1>','decision':'KEEP'}]}
 c,changes=repair.deterministic_candidate(o,a)
 assert c['optimized_prompt']=='<Subject 1> is 宫廷总管, identity.'
 assert c['anchor_decisions'][0]['id']=='KF7'
 assert o['anchor_decisions'][0]['id']=='<Picture 1>'
 wrong={**o,'optimized_prompt':'<Subject 1> is 皇帝, identity.'}
 assert repair.deterministic_candidate(wrong,a)[0]['optimized_prompt']==wrong['optimized_prompt']

def test_l0_missing_stable_id_but_never_changed_dialogue():
 f=fixture();o=copy.deepcopy(f['output']);o['optimized_prompt']=o['optimized_prompt'].replace('(S1)','',1)
 c,changes=repair.deterministic_candidate(o,f['authority'])
 assert any(x['code']=='MISSING_STABLE_SPEAKER_ID' for x in changes)
 assert check(f,c)['passed']
 wrong=copy.deepcopy(o);d=f['authority']['dialogue_events'][0]
 wrong['optimized_prompt']=wrong['optimized_prompt'].replace(d['exact_dialogue'],'篡改对白')
 c,changes=repair.deterministic_candidate(wrong,f['authority'])
 assert not check(f,c)['passed']
 assert not any(x['code']=='MISSING_STABLE_SPEAKER_ID' for x in changes)

def test_l0_reference_range_requires_every_real_projected_slot():
 authority={'subject_bindings':{},'reference_bindings':[{'picture':f'<Picture {i}>'} for i in range(1,6)]}
 original={'optimized_prompt':'subject_definitions:\nN/A\n\nsummary:\nA room.\n\nretention_analysis:\n<Picture 2> through <Picture 5> guide established props.\n\ndetailed_description:\nAn unchanged action.\n\noverall_soundscape:\nQuiet.\n\nnon_diegetic_music:\nN/A'}
 out,changes=repair.deterministic_candidate(original,authority)
 assert '<Picture 2>, <Picture 3>, <Picture 4> and <Picture 5>' in out['optimized_prompt']
 assert changes[0]['code']=='EXPLICIT_PICTURE_RANGE'
 assert 'through' in original['optimized_prompt']
 for invalid in ['<Picture 2> through <Picture 6>','<Picture 5> through <Picture 2>']:
  bad={'optimized_prompt':original['optimized_prompt'].replace('<Picture 2> through <Picture 5>',invalid)}
  assert repair.deterministic_candidate(bad,authority)==(bad,[])
 authority['anchor_policy']={'catalog':[{'anchor_id':'KF1','source_picture':'<Picture 1>'}]}
 original['av_timeline']={'anchors':[{'id':'KF1','decision':'DROP'}]}
 assert repair.deterministic_candidate(original,authority)==(original,[])

def test_l0_normalizes_only_complete_known_section_headings():
 f=fixture();original=copy.deepcopy(f['output'])
 original['optimized_prompt']=original['optimized_prompt'].replace('\ndetailed_description:', '\n detailed_description:')
 result,changes=repair.deterministic_candidate(original,f['authority'])
 assert result['optimized_prompt']==f['output']['optimized_prompt'] and check(f,result)['passed']
 assert any(c['code']=='H3_SECTION_HEADER_INDENTATION' for c in changes)
 assert '\n detailed_description:' in original['optimized_prompt']
 original['optimized_prompt']=original['optimized_prompt'].replace('non_diegetic_music:', 'unknown_section:')
 assert not any(c['code']=='H3_SECTION_HEADER_INDENTATION' for c in repair.deterministic_candidate(original,f['authority'])[1])

@pytest.mark.asyncio
async def test_l1_local_insertions_recheck_and_single_call(monkeypatch):
 f=fixture();o=copy.deepcopy(f['output']);marker='anchors do not dictate story.'
 addition=' All other visible characters listen naturally with relaxed closed lips and no speech-like articulation.'
 o['optimized_prompt']=o['optimized_prompt'].replace('retention_analysis:\n','retention_analysis:\n'+marker+'\n')
 chat=AsyncMock(return_value={'success':True,'content':json.dumps({'insertions':[{'after':marker,'text':addition}]}),'log_id':'repair-log'})
 monkeypatch.setattr(repair,'LLMService',lambda:NS(chat_completion=chat))
 monkeypatch.setattr(repair,'resolve_prompt_template',lambda *a:NS(type=repair.TEMPLATE_TYPE,id='registered-id',name='repair',template='registered-v1'))
 a={'blocking_findings':['reference_authority_scope'],'passed':False}
 def recheck(c):return {'blocking_findings':[],'passed':True} if addition in c['optimized_prompt'] else a
 writes=[]
 out,audit,state=await repair.repair_output(None,NS(id='n'),NS(chapter_id='c'),o,{'immutable_authority':f['authority']},a,recheck,persist=lambda s:writes.append(copy.deepcopy(s)))
 assert audit['passed'] and state['resolution']=='L1_PASS'
 assert state['l1_invocations']==1 and state['template_id']=='registered-id'
 assert out['av_timeline']==o['av_timeline'] and addition not in o['optimized_prompt']
 assert any(s.get('resolution')=='L1_IN_FLIGHT' for s in writes)
 await repair.repair_output(None,NS(id='n'),NS(chapter_id='c'),o,{'immutable_authority':f['authority']},a,recheck,state=state)
 assert chat.await_count==1


@pytest.mark.asyncio
async def test_l1_call_uses_selected_edited_prompt_from_management(client, db_session, monkeypatch):
 system = db_session.query(PromptTemplate).filter_by(type=repair.TEMPLATE_TYPE, is_system=True).one()
 custom = client.post(f'/api/prompt-templates/{system.id}/copy').json()['data']
 edited = 'Edited #14A prompt selected from prompt management.'
 response = client.put(f"/api/prompt-templates/{custom['id']}", json={
  'name':'自定义 #14A', 'description':'供小说选择', 'template':edited, 'type':repair.TEMPLATE_TYPE,
 })
 assert response.status_code == 200
 novel_id = client.post('/api/novels/', json={'title':'#14A 模板测试'}).json()['data']['id']
 response = client.put(f'/api/novels/{novel_id}/', json={'h3PreflightRepairPromptTemplateId':custom['id']})
 assert response.status_code == 200
 novel = db_session.get(Novel, novel_id)
 assert novel.h3_preflight_repair_prompt_template_id == custom['id']

 f=fixture();output=copy.deepcopy(f['output']);marker='unique managed template marker'
 output['optimized_prompt']=output['optimized_prompt'].replace('retention_analysis:\n','retention_analysis:\n'+marker+'\n')
 fail={'passed':False,'blocking_findings':['reference_authority_scope']}
 chat=AsyncMock(return_value={'success':False,'error':'expected test stop','log_id':'repair-log'})
 monkeypatch.setattr(repair,'LLMService',lambda:NS(chat_completion=chat))
 await repair.repair_output(db_session,novel,NS(chapter_id='chapter'),output,
  {'immutable_authority':f['authority']},fail,lambda _:fail)
 assert chat.await_count == 1
 assert chat.await_args.kwargs['system_prompt'] == edited
 assert chat.await_args.kwargs['task_type'] == repair.TEMPLATE_TYPE
 assert chat.await_args.kwargs['prompt_template_name'].startswith('自定义 #14A [')

@pytest.mark.parametrize('text',[' Cut to emperor.',' He walks forward.',' Wait 1 second.',' <d>新对白</d>',' (S9) speaks.',' <Picture 99> supplies identity.'])
def test_l1_rejects_nonlocal_or_canonical_changes(text):
 o=fixture()['output'];o['optimized_prompt']=o['optimized_prompt'].replace('retention_analysis:\n','retention_analysis:\nunique marker\n')
 with pytest.raises(ValueError):repair.apply_insertions(o,{'insertions':[{'after':'unique marker','text':text}]},{'reference_authority_scope'})

@pytest.mark.asyncio
async def test_canonical_fail_never_calls_llm(monkeypatch):
 f=fixture();chat=AsyncMock();monkeypatch.setattr(repair,'LLMService',lambda:NS(chat_completion=chat))
 a={'passed':False,'blocking_findings':['dialogue_ids_speakers_text_order']}
 _,audit,state=await repair.repair_output(None,None,None,f['output'],{'immutable_authority':f['authority']},a,lambda x:a)
 assert state['resolution']=='L2_UNSAFE_OR_NONLOCAL' and not audit['passed']
 chat.assert_not_called()

@pytest.mark.asyncio
async def test_saved_patch_revalidated_without_new_llm_or_changed_input(monkeypatch):
 f=fixture();o=copy.deepcopy(f['output']);marker='unique reference marker'
 o['optimized_prompt']=o['optimized_prompt'].replace('retention_analysis:\n','retention_analysis:\n'+marker+'\n')
 addition=' Identity references preserve permanent identity, while anchors supply current staging.'
 response={'success':True,'content':json.dumps({'insertions':[{'after':marker,'text':addition}]})}
 state={'original_output':copy.deepcopy(o),'l1_invocations':1,'attempts':[
  {'level':'L1','failed_checks':['reference_authority_scope'],'llm_log_id':'saved-log','raw_response':response,'accepted':False}]}
 original_state=copy.deepcopy(state)
 fail={'passed':False,'blocking_findings':['reference_authority_scope']}
 def recheck(c):return {'passed':True,'blocking_findings':[]} if addition in c['optimized_prompt'] else fail
 chat=AsyncMock();monkeypatch.setattr(repair,'LLMService',lambda:NS(chat_completion=chat))
 out,audit,saved=await repair.repair_output(None,None,None,o,{'immutable_authority':f['authority']},fail,recheck,state=state)
 assert audit['passed'] and saved['resolution']=='L1_REPLAY_PASS'
 assert saved['l1_invocations']==1 and saved['attempts'][-1]['llm_called'] is False
 assert state==original_state and saved['attempts'][0]==state['attempts'][0]
 assert out['av_timeline']==o['av_timeline']
 changed=copy.deepcopy(o);changed['optimized_prompt']+='\nChanged input.'
 out,audit,saved=await repair.repair_output(None,None,None,changed,{'immutable_authority':f['authority']},fail,recheck,state=state)
 assert not audit['passed'] and out==changed and saved['resolution']=='L1_ALREADY_ATTEMPTED'
 chat.assert_not_called()

def test_canonical_name_digits_are_not_timing_but_new_numbers_still_fail():
 f=fixture();o=f['output'];o['optimized_prompt']=o['optimized_prompt'].replace('retention_analysis:\n','retention_analysis:\nunique marker\n')
 patch={'insertions':[{'after':'unique marker','text':' 骗子1 retains identity from the supplied reference.'}]}
 assert repair.apply_insertions(o,patch,{'reference_authority_scope'},f['authority'])
 patch['insertions'][0]['text']=' 骗子1 waits 2 seconds.'
 with pytest.raises(ValueError):repair.apply_insertions(o,patch,{'reference_authority_scope'},f['authority'])


def test_listener_mouth_movement_is_not_a_body_move():
 f=fixture();o=f['output'];o['optimized_prompt']=o['optimized_prompt'].replace('detailed_description:\n','detailed_description:\nunique marker\n')
 patch={'insertions':[{'after':'unique marker','text':' All other visible characters listen naturally with relaxed closed lips and no speech-like mouth movement.'}]}
 assert repair.apply_insertions(o,patch,{'speaker_switch_listener_scope'},f['authority'])
 patch['insertions'][0]['text']=' The listeners move behind the speaker.'
 with pytest.raises(ValueError):repair.apply_insertions(o,patch,{'speaker_switch_listener_scope'},f['authority'])


def test_every_other_visible_listener_has_same_strict_state_requirements():
 from app.services.h3_native_prompt import _explicit_listener_scope
 a={'subject_bindings':{'<Subject 1>':'甲','<Subject 2>':'乙'}}
 text='Every other visible character listens naturally with relaxed closed lips and no speech-like articulation.'
 assert _explicit_listener_scope(text,'<Subject 1>',a,r'closed lips')
 for bad in [text.replace('Every other','Some other'),text.replace('closed lips','open lips'),text.replace('no speech-like articulation','')]:
  assert not _explicit_listener_scope(bad,'<Subject 1>',a,r'closed lips')
