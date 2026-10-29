import base64
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock
import pytest
from PIL import Image
from app.models.prompt_template import PromptTemplate
from app.services import h3_execution_optimizer as opt
from app.services.llm.multimodal import attach_image_inputs, capture_image_inputs
from app.services.llm.base import build_llm_request_info
from app.services.prompt_template_service import SYSTEM_H3_VIDEO_PROMPT_TEMPLATES
from app.services.vision_inputs import vision_proxy, previous_video_frames

RAW='''duration: 4s
<Subject 1> is 皇帝, stable identity.
<Subject 2> is 骗子2, stable identity.
Apply <Picture 2> identity to <Subject 1> only.
KF1 — START — Clip-local 0.00s — <Picture 1>
CONTINUOUS_TAKE: all remain visible; palms visibly empty.
D1:
  speaker: <Subject 1>
  start_time: 1.00s
  end_time: 3.00s
  exact_dialogue: 它有多漂亮？
During D1 ONLY <Subject 1> produces human vocalization and lip synchronization. <Subject 2> is non-vocal; no speech-like mouth articulation.
PHASE P1 — CAMERA — 0s–4s: Keep the continuous ensemble camera steady.
'''
NATIVE = """subject_definitions:
<Subject 1> is 皇帝, with physical identity from <Picture 2>.
<Subject 2> is 骗子2, with a distinct stable face.
<Picture 1> is the opening visual anchor.
summary:
A 4-second continuous ensemble view.
retention_analysis:
Visual anchors preserve clothing, pose, blocking and floor positions; identity references supply face and permanent identity only, without overriding anchor staging.
detailed_description:
Maintain established floor positions. Begin from <Picture 1>. The camera reveals a readable face and mouth; the other man listens with relaxed closed lips.
<Subject 1> (S1) asks, <d>[Chinese] 它有多漂亮？</d> He closes his lips; both retain empty hands and settle naturally.
overall_soundscape:
Quiet room tone.
non_diegetic_music:
N/A
"""

@pytest.fixture
def runtime(monkeypatch,tmp_path):
 from app.services.file_storage import file_storage
 monkeypatch.setattr(file_storage,'base_dir',tmp_path)
 source=tmp_path/'source.png';Image.new('RGB',(2048,1200),'red').save(source)
 refs={'references':[{'slot':1,'kind':'DIRECTOR_VISUAL_ANCHOR','local_path':str(source),'source_time_seconds':0},{'slot':2,'kind':'CHARACTER_IDENTITY','local_path':str(source),'source_name':'皇帝'}]}
 return opt.build_runtime_input(RAW,'MULTI_KEYFRAME',{'clip_index':1,'planned_duration':4},refs)

def test_registry_custom_lookup(db_session):
 item=next(i for i in SYSTEM_H3_VIDEO_PROMPT_TEMPLATES if i['type']==opt.TEMPLATE_TYPE)
 assert item['template']==(Path(__file__).resolve().parent/'fixtures/retired_h3/14_MiniMax_H3_Execution_Prompt_Optimizer_V1.txt').read_text()
 system=PromptTemplate(**item,is_system=True,is_active=True)
 custom=PromptTemplate(name='custom14',type=opt.TEMPLATE_TYPE,template='edited',is_system=False,is_active=True)
 db_session.add_all([system,custom]);db_session.commit()
 novel=NS(h3_execution_optimizer_prompt_template_id=None)
 assert opt.resolve_prompt_template(db_session,novel,'h3_execution_optimizer_prompt_template_id',opt.TEMPLATE_TYPE).id==system.id
 novel.h3_execution_optimizer_prompt_template_id=custom.id
 assert opt.resolve_prompt_template(db_session,novel,'h3_execution_optimizer_prompt_template_id',opt.TEMPLATE_TYPE).template=='edited'

def test_actual_wire_images_and_text_compatibility(runtime):
 _,images=runtime
 body={'messages':[{'role':'system','content':'s'},{'role':'user','content':'u'}]}
 info=build_llm_request_info('custom','http://localhost','http://localhost','configured',{'Authorization':'Bearer secret'},body)
 assert info['payload']==body and info['imageInputs']==[] and info['headers']['Authorization']=='Bearer ***'
 final=attach_image_inputs(body,'custom',images);original=json.dumps(final)
 info=build_llm_request_info('custom','http://localhost','http://localhost','configured',{},final,image_metadata=[{k:v for k,v in i.items() if k!='url'} for i in images])
 assert json.dumps(final)==original and 'base64,' not in json.dumps(info)
 submitted=base64.b64decode(images[0]['url'].split(',',1)[1]);item=info['imageInputs'][0]
 assert item['sha256']==hashlib.sha256(submitted).hexdigest() and item['size_bytes']==len(submitted)
 assert item['submitted_dimensions']==[1024,600] and item['source_dimensions']==[2048,1200]
 assert len(capture_image_inputs(final,[{}]*9)[1])==2

@pytest.mark.parametrize('provider',['custom','anthropic','gemini','ollama'])
def test_provider_image_shapes(provider,runtime):
 body={'messages':[{'role':'system','content':'s'},{'role':'user','content':'u'}]} if provider!='gemini' else {'contents':[{'parts':[{'text':'u'}]}]}
 logged,items=capture_image_inputs(attach_image_inputs(body,provider,runtime[1]))
 assert len(items)==2 and all(i['status']=='available' for i in items)
 assert runtime[1][0]['url'] not in json.dumps(logged)

def test_vision_capability_explicit(runtime):
 # Provider names are not a capability database; always submit the configured model's images.
 body={'messages':[{'role':'user','content':'u'}]}
 assert len(capture_image_inputs(attach_image_inputs(body,'deepseek',runtime[1]))[1])==2

@pytest.mark.asyncio
async def test_llm_input_omits_only_duplicate_sources_and_keeps_saved_runtime(monkeypatch, runtime):
 import copy
 sample=copy.deepcopy(runtime[0]);images=runtime[1]
 sources=[{'id':'opening_state','text':RAW},
          {'id':'transition_2','text':'<Subject 1> and <Subject 2> continue the assigned action.'}]
 built,_=opt.build_runtime_input(
  'duration: 4s\n<Subject 1> is 皇帝.','SINGLE_FRAME',{'planned_duration':4},
  execution_context={'anchor_policy_version':1,'canonical_visual_sources':copy.deepcopy(sources)})
 assert built['immutable_authority']['anchor_policy']['canonical_visual_sources']==built['execution_context']['canonical_visual_sources']==sources
 sample['immutable_authority']['anchor_policy']={'canonical_visual_sources':copy.deepcopy(sources)}
 sample['execution_context']={'canonical_visual_sources':copy.deepcopy(sources),
                              'canonical_transitions':[{'canonical_source_id':'transition_2',
                                                        'transition_description':sources[1]['text']}],
                              'continuation':{'context_frames':39}}
 before=copy.deepcopy(sample)
 template='unchanged #14 system prompt'
 monkeypatch.setattr(opt,'resolve_prompt_template',lambda *a:NS(type=opt.TEMPLATE_TYPE,id='14',name='registered',template=template))
 monkeypatch.setattr(opt,'build_runtime_input',lambda *a:(sample,images))
 monkeypatch.setattr(opt,'append_video_ai_call',lambda *a:None)
 chat=AsyncMock(return_value={'success':False,'error':'offline fixture','log_id':'offline-log'})
 monkeypatch.setattr(opt,'LLMService',lambda:NS(chat_completion=chat))
 _,record=await opt.optimize_h3_execution_prompt(
  Mock(),NS(id='novel'),NS(index=6,chapter_id='chapter'),RAW,'MULTI_KEYFRAME',
  {'clip_index':2,'planned_duration':4})
 sent=chat.call_args.kwargs
 expected=copy.deepcopy(before);expected['execution_context'].pop('canonical_visual_sources')
 assert sent['system_prompt']==template and json.loads(sent['user_content'])==expected
 assert sent['images'] is images and record['image_count']==len(images)
 assert record['runtime_input']==before and sample==before
 assert record['runtime_input']['immutable_authority']['anchor_policy']['canonical_visual_sources']==sources
 assert record['runtime_input']['execution_context']['canonical_transitions']==before['execution_context']['canonical_transitions']
 mismatch=copy.deepcopy(before)
 mismatch['execution_context']['canonical_visual_sources'][0]['text']='different source'
 assert opt.llm_input_view(mismatch) is mismatch

def valid_output(runtime, prompt=NATIVE):
 initial=runtime[0]['initial_execution_timing'];duration=initial['duration']
 phases=[{'id':a,'type':b,'start':float(c),'end':float(d),'description':e} for a,b,c,d,e in opt.re.findall(r'(?m)^PHASE ([\w-]+) — ([A-Z_]+) — ([\d.]+)s–([\d.]+)s: (.+)$',RAW)]
 timeline={'original_duration':duration,'optimized_duration':duration,'duration_delta':0,'duration_changed':False,'reason':'现有预算足够',
  'dialogue_events':[{'id':e['id'],'speaker':e['speaker'],'original_start':e['start_time'],'original_end':e['end_time'],'duration':e['end_time']-e['start_time'],'optimized_start':e['start_time'],'optimized_end':e['end_time']} for e in initial['dialogue_events']],
  'handoffs':[], 'anchors':[{'id':e['id'],'original_time':e['time'],'optimized_time':e['time'],'delta':0,'visual_state_changed':False,'reason':'保留起点','prompt_excerpt':'Begin from <Picture 1>.'} for e in initial['visual_anchors']], 'execution_phases':phases}
 return {'optimized_prompt':prompt,'av_timeline':timeline,'authority_echo':runtime[0]['immutable_authority'],'risks':[],'changes':[],'timing_recommendations':[]}


def audit(runtime,output,raw=RAW):
 return opt.check_authority(raw,output,runtime[0]['immutable_authority'],runtime[0]['initial_execution_timing'],runtime[0]['duration_limits'])

@pytest.mark.parametrize('before,after',[
 ('<Subject 1> (S1)', '<Subject 2> (S1)'), ('它有多漂亮？', '改词'),
 ('<Subject 1> is 皇帝', '<Subject 1> is 骗子2'),
 ('identity from <Picture 2>', 'identity from <Picture 1>'), ('<Picture 1>', '<Picture 9>')])
def test_canonical_mutations_block(runtime,before,after):
 output=valid_output(runtime);output['optimized_prompt']=NATIVE.replace(before,after)
 assert not audit(runtime,output)['passed']

def test_natural_rewording_does_not_require_internal_phase_echo(runtime):
 output=valid_output(runtime,NATIVE.replace('The camera reveals', 'The camera gently reveals'))
 assert audit(runtime,output)['passed']
 assert 'PHASE' not in output['optimized_prompt'] and output['av_timeline']['execution_phases']


@pytest.mark.parametrize('prefix', ['- ', '* ', '+ ', '  - '])
def test_list_form_subject_definitions_preserve_strict_identity_contract(runtime, prefix):
 # Saved canonical Clip prompts may use Markdown list items. Their identity
 # authority must be identical to plain definitions, not an empty mapping.
 raw = opt.re.sub(r'(?m)^(<Subject \d+> is)', prefix + r'\1', RAW)
 assert opt.subject_bindings(raw) == runtime[0]['immutable_authority']['subject_bindings']
 output = valid_output(runtime)
 output['optimized_prompt'] = opt.re.sub(r'(?m)^(<Subject \d+> is)', prefix + r'\1', NATIVE)
 assert audit(runtime, output, raw)['passed']
 output['optimized_prompt'] = output['optimized_prompt'].replace('<Subject 1> is 皇帝', '<Subject 1> is 骗子2')
 assert 'subject_binding' in audit(runtime, output, raw)['blocking_findings']

def test_missing_authority_trace_is_blocked(runtime):
 output=valid_output(runtime);output.pop('authority_echo')
 assert 'authority_echo_preserved' in audit(runtime,output)['blocking_findings']

@pytest.mark.asyncio
@pytest.mark.parametrize('response,expected',[
 ({'success':False,'error':'vision unsupported'},'FALLBACK'),
 ({'success':True,'content':'bad JSON'},'FALLBACK'),
 ({'success':True,'content':json.dumps({'optimized_prompt':RAW.replace('它有多漂亮？','改词')})},'FALLBACK'),
 ({'success':True,'content':'valid','invalid_risks':True},'FALLBACK'),
 ({'success':True,'content':'valid'},'OPTIMIZED')])
async def test_parser_fallback_and_execution_duration(monkeypatch,runtime,response,expected):
 monkeypatch.setattr(opt,'resolve_prompt_template',lambda *a:NS(type=opt.TEMPLATE_TYPE,id='14',name='registered',template='registry edited prompt'))
 monkeypatch.setattr(opt,'build_runtime_input',lambda *a:runtime)
 response=dict(response)
 if response.get('content')=='valid':
  output=valid_output(runtime)
  if response.get('invalid_risks'):output['risks']='malformed array'
  response['content']=json.dumps(output)
 chat=AsyncMock(return_value={**response,'log_id':'log14'});monkeypatch.setattr(opt,'LLMService',lambda:NS(chat_completion=chat))
 calls=[];monkeypatch.setattr(opt,'append_video_ai_call',lambda shot,call:calls.append(call))
 selected,record=await opt.optimize_h3_execution_prompt(Mock(),NS(id='novel'),NS(index=3,chapter_id='chapter'),RAW,'MULTI_KEYFRAME',{'clip_index':1,'planned_duration':4})
 expected_prompt=(opt.compile_dialogue_time_cues(
  NATIVE, runtime[0]['immutable_authority']['dialogue_events'], valid_output(runtime)['av_timeline'])
  if expected=='OPTIMIZED' else RAW)
 assert record['status']==expected and selected==expected_prompt and record['clip_index']==1
 assert record['duration_applied'] is (expected=='OPTIMIZED') and record['timing_applied'] is (expected=='OPTIMIZED')
 assert chat.call_args.kwargs['system_prompt']=='registry edited prompt' and len(chat.call_args.kwargs['images'])==2 and calls[0]['step']=='14'
 if response.get('error')=='vision unsupported':assert record['capability_error']=='VISION_CAPABILITY_UNAVAILABLE'
 if expected=='OPTIMIZED':assert record['output']['duration']['recommended']==4 and record['output']['duration']['original']==4 and record['effective_duration']==4

@pytest.mark.asyncio
async def test_disabled_hook_preserves_h3(monkeypatch):
 from app.services.shot_video_service import _apply_h3_execution_optimizer
 forbidden=AsyncMock(side_effect=AssertionError('must not call'));monkeypatch.setattr(opt,'optimize_h3_execution_prompt',forbidden)
 assert await _apply_h3_execution_optimizer(Mock(),NS(metadata_json='{}'),None,None,RAW,'SINGLE_FRAME',{})==RAW
 forbidden.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('model_reports_insufficient', [False, True])
async def test_infeasible_budget_is_reported_without_rewriting_or_retry(monkeypatch, runtime, model_reports_insufficient):
 import copy
 sample=copy.deepcopy(runtime)
 output=valid_output(sample)
 if model_reports_insufficient:
  output['risks']=['INSUFFICIENT_AV_EXECUTION_BUDGET']
 else:
  sample[0]['immutable_authority']['dialogue_events'][0]['duration']=21
 original=copy.deepcopy(sample)
 monkeypatch.setattr(opt,'resolve_prompt_template',lambda *a:NS(type=opt.TEMPLATE_TYPE,id='14',name='registered',template='unchanged'))
 monkeypatch.setattr(opt,'build_runtime_input',lambda *a:sample)
 chat=AsyncMock(return_value={'success':True,'content':json.dumps(output)})
 monkeypatch.setattr(opt,'LLMService',lambda:NS(chat_completion=chat))
 monkeypatch.setattr(opt,'append_video_ai_call',lambda *a:None)
 selected,record=await opt.optimize_h3_execution_prompt(Mock(),NS(id='novel'),NS(index=3,chapter_id='chapter'),RAW,'SINGLE_FRAME',{'planned_duration':4})
 assert record['error_code']=='DURATION_INFEASIBLE' and record['requires_clip_replan']
 assert record['status']=='FALLBACK' and not record['duration_applied'] and selected==RAW
 assert chat.await_count==int(model_reports_insufficient) and sample==original
 if model_reports_insufficient:
  assert record['raw_response_content']==json.dumps(output) and record['optimized_prompt']==output['optimized_prompt']

def test_proxy_cache_no_upscale(monkeypatch,tmp_path):
 from app.services.file_storage import file_storage
 monkeypatch.setattr(file_storage,'base_dir',tmp_path)
 path=tmp_path/'small.png';Image.new('RGB',(400,200)).save(path)
 first=vision_proxy(path);second=vision_proxy(path)
 assert first['submitted_dimensions']==[400,200] and first['sha256']==second['sha256'] and path.read_bytes().startswith(b'\x89PNG')

def test_previous_context_frames(monkeypatch,tmp_path):
 import subprocess
 from app.services.file_storage import file_storage
 monkeypatch.setattr(file_storage,'base_dir',tmp_path)
 video=tmp_path/'previous.mp4';subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=80x40:r=24:d=6','-c:v','libx264','-threads','1',str(video)],check=True)
 frames=previous_video_frames(video,39)
 assert len(frames)==5 and len({f['time'] for f in frames})==5
 assert frames[0]['source_frame_index']==144-39 and frames[-1]['source_frame_index']==143
 assert frames[0]['time']==105/24 and frames[-1]['time']==143/24
 assert all(f['context_frames']==39 and f['context_start_frame']==105 and f['context_end_frame']==143 for f in frames)
 assert all(f['logical_id'].startswith('PreviousFrame') and f['reference_type']=='PREVIOUS_VIDEO_FRAME' for f in frames)
 assert previous_video_frames(None)==[]

@pytest.mark.asyncio
@pytest.mark.parametrize('capability',['EXTEND','TEMPORAL_EXTEND'])
async def test_shared_hook_preserves_continuation_mode_without_owned_kf(monkeypatch,capability):
 from app.services.shot_video_service import _apply_h3_execution_optimizer
 from app.services import h3_continuation
 monkeypatch.setattr(h3_continuation,'continuation_contract',lambda *a: {'context_frames':39,'binding_verified':True})
 shot=NS(video_director_plan='{}',duration=4)
 task=NS(metadata_json=json.dumps({'optimize_h3_prompt':True,'capability':capability}))
 invoke=AsyncMock(return_value=('optimized',{'status':'OPTIMIZED'}));monkeypatch.setattr(opt,'optimize_h3_execution_prompt',invoke)
 await _apply_h3_execution_optimizer(Mock(),task,None,shot,RAW,'SINGLE_FRAME',{'visual_state_indexes':[],'planned_duration':4},previous_video_path='/previous.mp4')
 assert invoke.call_args.args[4]==capability
 assert invoke.call_args.kwargs['previous_video_path']=='/previous.mp4'

def test_previous_context_is_not_an_anchor_or_numbered_picture(monkeypatch):
 preview={'logical_id':'PreviousFrame1','context_frames':39,'source_frame_index':323,'context_start_frame':323,'context_end_frame':361,'source_fps':24,'llm_preview_only':True}
 monkeypatch.setattr(opt,'previous_video_frames',lambda *a: [preview])
 runtime,images=opt.build_runtime_input('duration: 4s','EXTEND',{'planned_duration':4},previous_video_path='/previous.mp4',execution_context={'anchor_policy_version':1,'continuation':{'context_frames':39,'binding_verified':True}})
 assert runtime['previous_video_context']['context_frames']==39 and images==[preview]
 assert runtime['immutable_authority']['reference_bindings']==[]
 assert runtime['immutable_authority']['anchor_policy']['catalog']==[]
 assert runtime['previous_video_context']['frames'][0]['source_frame_index']==323

def test_log_detail_images():
 from app.api.llm_logs import get_llm_log_detail
 log=NS(**{k:None for k in ['created_at','provider','model','prompt_template_name','system_prompt','user_prompt','response','status','error_message','task_type','novel_id','chapter_id','character_id','used_proxy','duration','usage_metrics']},id='log',request_info=json.dumps({'imageInputs':[{'logical_id':'PreviousFrame1','request_order':1}]}))
 repo=NS(get_by_id=lambda _:log)
 assert get_llm_log_detail('log',repo)['data']['image_inputs'][0]['logical_id']=='PreviousFrame1'
 log.request_info='{}';assert get_llm_log_detail('log',repo)['data']['image_inputs']==[]


def test_identical_canonical_lines_are_valid(runtime):
 repeated=RAW+RAW[RAW.index('D1:'):RAW.index('PHASE')].replace('D1:', 'D2:').replace('During D1', 'During D2')
 data=dict(runtime[0]);initial={**data['initial_execution_timing'],'dialogue_events':opt.dialogue_events(repeated)}
 canonical=[{'id':e['id'],'speaker':e['speaker'],'exact_dialogue':e['exact_dialogue'],'order':i,'duration':e['end_time']-e['start_time']} for i,e in enumerate(initial['dialogue_events'],1)]
 data.update(initial_execution_timing=initial,immutable_authority={**data['immutable_authority'],'dialogue_events':canonical,'allowed_dialogue_overlaps':[['D1','D2']]})
 changed=(data,runtime[1]);output=valid_output(changed,NATIVE.replace('He closes his lips;', '<Subject 1> (S1) repeats, <d>[Chinese] 它有多漂亮？</d> He closes his lips;'))
 assert audit(changed,output,repeated)['passed']

def test_explicit_scene_prop_reference_swap_is_blocked(runtime):
 data=dict(runtime[0]);data['immutable_authority']={**data['immutable_authority'], 'reference_bindings':[{**data['immutable_authority']['reference_bindings'][0], 'type':'SCENE'},data['immutable_authority']['reference_bindings'][1]]}
 changed=(data,runtime[1])
 assert not audit(changed,valid_output(changed,NATIVE+'\n<Picture 1> — PROP / invented object'))['passed']


def test_pose_prose_does_not_override_identity_definitions():
 assert opt.subject_bindings(RAW+'\nAt KF2, <Subject 1> is upright in the center, facing the visitors.') == {'<Subject 1>':'皇帝','<Subject 2>':'骗子2'}

@pytest.mark.asyncio
@pytest.mark.parametrize('roles,expected',[(['START'],'SINGLE_FRAME'),(['START','END'],'FIRST_LAST_FRAME'),(['START','INTERMEDIATE','END'],'MULTI_KEYFRAME')])
async def test_shared_hook_uses_the_canonical_builder_shape(monkeypatch,roles,expected):
 from app.services.shot_video_service import _apply_h3_execution_optimizer
 states=[{'index':i,'role':role} for i,role in enumerate(roles,1)]
 shot=NS(video_director_plan=json.dumps({'keyframes':states,'transitions':[]}),duration=4)
 task=NS(metadata_json='{"optimize_h3_prompt":true}')
 invoke=AsyncMock(return_value=('optimized',{'status':'OPTIMIZED'}));monkeypatch.setattr(opt,'optimize_h3_execution_prompt',invoke)
 assert await _apply_h3_execution_optimizer(Mock(),task,None,shot,RAW,'SINGLE_FRAME',{'visual_state_indexes':list(range(1,len(roles)+1)),'planned_duration':4})=='optimized'
 assert invoke.call_args.args[4]==expected and task.prompt_text=='optimized'
 assert invoke.call_args.kwargs['execution_context']['anchor_policy_version']==1
 assert invoke.call_args.kwargs['execution_context']['canonical_visual_sources']
 assert json.loads(task.metadata_json)['h3_prompt_optimizer']['status']=='OPTIMIZED'

@pytest.mark.asyncio
async def test_auto_repair_reuses_failed_raw_response_only_under_same_fingerprints(monkeypatch,runtime):
 template='registered';output=valid_output(runtime)
 monkeypatch.setattr(opt,'resolve_prompt_template',lambda *a:NS(type=opt.TEMPLATE_TYPE,id='14',name='registered',template=template))
 monkeypatch.setattr(opt,'build_runtime_input',lambda *a:runtime)
 monkeypatch.setattr(opt,'append_video_ai_call',lambda *a:None)
 chat=AsyncMock(return_value={'success':False,'error':'must not call'})
 monkeypatch.setattr(opt,'LLMService',lambda:NS(chat_completion=chat))
 record={'version':opt.VERSION,'status':'FALLBACK','original_output':output,'output':output,
  'raw_response_content':json.dumps(output,ensure_ascii=False),'llm_log_id':'saved-log',
  'authority_check':{'passed':False},'runtime_input':runtime[0],
  'raw_prompt_sha256':hashlib.sha256(RAW.encode()).hexdigest(),
  'system_prompt_sha256':hashlib.sha256(template.encode()).hexdigest()}
 _,result=await opt.optimize_h3_execution_prompt(Mock(),NS(id='novel'),NS(index=3,chapter_id='chapter'),RAW,'MULTI_KEYFRAME',{'clip_index':1,'planned_duration':4},reuse_record=record,execution_context={'preflight_auto_repair':True})
 assert result['status']=='OPTIMIZED' and result['reused_result']
 assert result['llm_log_id']=='saved-log';chat.assert_not_called()
 changed={**record,'system_prompt_sha256':'different'}
 _,result=await opt.optimize_h3_execution_prompt(Mock(),NS(id='novel'),NS(index=3,chapter_id='chapter'),RAW,'MULTI_KEYFRAME',{'clip_index':1,'planned_duration':4},reuse_record=changed,execution_context={'preflight_auto_repair':True})
 assert not result.get('reused_result') and chat.await_count==1


@pytest.mark.asyncio
async def test_http_502_is_transport_failure_with_original_log_id(monkeypatch, runtime):
 monkeypatch.setattr(opt, 'resolve_prompt_template', lambda *a: NS(
  type=opt.TEMPLATE_TYPE, id='14', name='registered', template='unchanged'))
 monkeypatch.setattr(opt, 'build_runtime_input', lambda *a: runtime)
 monkeypatch.setattr(opt, 'append_video_ai_call', lambda *a: None)
 error='API 错误 (502): {"error":{"message":"Upstream service temporarily unavailable"}}'
 chat=AsyncMock(return_value={'success':False,'error':error,'log_id':'c2-llm-log'})
 monkeypatch.setattr(opt, 'LLMService', lambda: NS(chat_completion=chat))
 selected,record=await opt.optimize_h3_execution_prompt(
  Mock(),NS(id='novel'),NS(index=6,chapter_id='chapter'),RAW,'EXTEND',
  {'clip_index':2,'planned_duration':4})
 assert selected==RAW and record['status']=='FALLBACK'
 assert record['error_code']=='LLM_TRANSPORT_ERROR'
 assert record['failure_stage']=='LLM_REQUEST' and record['llm_log_id']=='c2-llm-log'
 assert error in record['error'] and 'authority_check' not in record


@pytest.mark.asyncio
async def test_actual_preflight_failure_is_not_transport_or_repair_failure(monkeypatch, runtime):
 monkeypatch.setattr(opt, 'resolve_prompt_template', lambda *a: NS(
  type=opt.TEMPLATE_TYPE, id='14', name='registered', template='unchanged'))
 monkeypatch.setattr(opt, 'build_runtime_input', lambda *a: runtime)
 monkeypatch.setattr(opt, 'append_video_ai_call', lambda *a: None)
 output=valid_output(runtime,NATIVE.replace('它有多漂亮？','篡改台词'))
 chat=AsyncMock(return_value={'success':True,'content':json.dumps(output,ensure_ascii=False),'log_id':'preflight-log'})
 monkeypatch.setattr(opt, 'LLMService', lambda: NS(chat_completion=chat))
 _,record=await opt.optimize_h3_execution_prompt(
  Mock(),NS(id='novel'),NS(index=6,chapter_id='chapter'),RAW,'GENERATE',
  {'clip_index':1,'planned_duration':4})
 assert record['status']=='FALLBACK' and record['error_code']=='PREFLIGHT_FAIL'
 assert record['failure_stage']=='PREFLIGHT' and record['llm_log_id']=='preflight-log'
 assert record['authority_check']['passed'] is False
 assert not record.get('preflight_repair') and record['l1_invocations_this_call']==0


@pytest.mark.asyncio
async def test_failed_l1_is_classified_separately_from_preflight_only(monkeypatch, runtime):
 from app.services import h3_preflight_repair
 monkeypatch.setattr(opt, 'resolve_prompt_template', lambda *a: NS(
  type=opt.TEMPLATE_TYPE, id='14', name='registered', template='unchanged'))
 monkeypatch.setattr(opt, 'build_runtime_input', lambda *a: runtime)
 monkeypatch.setattr(opt, 'append_video_ai_call', lambda *a: None)
 output=valid_output(runtime,NATIVE.replace('它有多漂亮？','篡改台词'))
 monkeypatch.setattr(opt, 'LLMService', lambda: NS(chat_completion=AsyncMock(return_value={
  'success':True,'content':json.dumps(output,ensure_ascii=False),'log_id':'initial-log'})))
 async def failed_repair(*args, **kwargs):
  return args[3],args[5],{'l1_invocations':1,'resolution':'L1_FAILED','attempts':[{'level':'L1','llm_log_id':'repair-log'}]}
 monkeypatch.setattr(h3_preflight_repair, 'repair_output', failed_repair)
 _,record=await opt.optimize_h3_execution_prompt(
  Mock(),NS(id='novel'),NS(index=6,chapter_id='chapter'),RAW,'GENERATE',
  {'clip_index':1,'planned_duration':4},execution_context={'preflight_auto_repair':True})
 assert record['error_code']=='REPAIR_FAIL' and record['status']=='FALLBACK'
 assert record['l1_invocations_this_call']==1
 assert record['preflight_repair']['attempts'][0]['llm_log_id']=='repair-log'


@pytest.mark.asyncio
async def test_repair_execution_exception_is_distinct_without_fake_l1_event(monkeypatch, runtime):
 from app.services import h3_preflight_repair
 monkeypatch.setattr(opt, 'resolve_prompt_template', lambda *a: NS(
  type=opt.TEMPLATE_TYPE, id='14', name='registered', template='unchanged'))
 monkeypatch.setattr(opt, 'build_runtime_input', lambda *a: runtime)
 monkeypatch.setattr(opt, 'append_video_ai_call', lambda *a: None)
 output=valid_output(runtime,NATIVE.replace('它有多漂亮？','篡改台词'))
 monkeypatch.setattr(opt, 'LLMService', lambda: NS(chat_completion=AsyncMock(return_value={
  'success':True,'content':json.dumps(output,ensure_ascii=False),'log_id':'initial-log'})))
 monkeypatch.setattr(h3_preflight_repair, 'repair_output', AsyncMock(side_effect=ValueError('REPAIR_TEMPLATE_TYPE_MISMATCH')))
 _,record=await opt.optimize_h3_execution_prompt(
  Mock(),NS(id='novel'),NS(index=6,chapter_id='chapter'),RAW,'GENERATE',
  {'clip_index':1,'planned_duration':4},execution_context={'preflight_auto_repair':True})
 assert record['error_code']=='REPAIR_FAIL' and record['failure_stage']=='REPAIR'
 assert record['l1_invocations_this_call']==0 and record['llm_log_id']=='initial-log'


@pytest.mark.asyncio
async def test_worker_failure_message_retains_code_and_task_evidence(monkeypatch):
 from app.services.shot_video_service import _apply_h3_execution_optimizer
 task=NS(id='task-c2',metadata_json=json.dumps({'optimize_h3_prompt':True,'clip_id':'shot:clip:2',
                                                 'clip_index':2,'clip_plan_revision':1}))
 shot=NS(video_director_plan='{}',duration=8.2)
 record={'status':'FALLBACK','error_code':'LLM_TRANSPORT_ERROR','llm_log_id':'c2-llm-log',
         'error':'API 错误 (502): Upstream service temporarily unavailable'}
 monkeypatch.setattr(opt,'optimize_h3_execution_prompt',AsyncMock(return_value=(RAW,record)))
 with pytest.raises(ValueError,match='LLM_TRANSPORT_ERROR.*502'):
  await _apply_h3_execution_optimizer(Mock(),task,None,shot,RAW,'SINGLE_FRAME',
                                     {'clip_index':2,'planned_duration':8.2})
 saved=json.loads(task.metadata_json)
 assert saved['h3_prompt_optimizer']['llm_log_id']=='c2-llm-log'
 assert saved['h3_prompt_optimizer']['generation_blocked'] is True
 assert saved['clip_id']=='shot:clip:2' and saved['clip_plan_revision']==1


@pytest.mark.asyncio
async def test_worker_preserves_original_canonical_transition_id_and_local_scope(monkeypatch):
 from app.services.shot_video_service import _apply_h3_execution_optimizer
 from app.services import h3_continuation
 source={'segment_index':2,'from_keyframe_index':2,'to_keyframe_index':3,
         'start_time':12.0,'end_time':22.0,'transition_description':'原始双人手势与正面推进。'}
 task=NS(metadata_json=json.dumps({'optimize_h3_prompt':True,'capability':'EXTEND'}))
 shot=NS(video_director_plan=json.dumps({'keyframes':[],'transitions':[source]}),duration=38)
 monkeypatch.setattr(h3_continuation,'continuation_contract',lambda *a:{'binding_verified':True})
 invoke=AsyncMock(return_value=('optimized',{'status':'OPTIMIZED'}))
 monkeypatch.setattr(opt,'optimize_h3_execution_prompt',invoke)
 clip={'clip_index':2,'start_time':13.7,'end_time':21.9,'planned_duration':8.2,
       'visual_state_indexes':[],'carry_in_state_index':2,'continuity_to_previous':'CONTINUOUS'}
 assert await _apply_h3_execution_optimizer(
  Mock(),task,None,shot,RAW,'SINGLE_FRAME',clip,previous_video_path='/previous.mp4',
  execution_context={'previous_clip':{'generated_by_task_id':'c1'}})=='optimized'
 context=invoke.call_args.kwargs['execution_context']
 visual_source=context['canonical_visual_sources'][-1]
 assert (visual_source['id'],visual_source['text'])==('transition_2',source['transition_description'])
 assert visual_source['clip_scope']['clip_local_end_time']==8.2
 projected=context['canonical_transitions'][0]
 assert (projected['clip_local_start_time'],projected['clip_local_end_time'])==(0.0,8.2)
 assert projected['target_state_owned'] is False
 assert projected['action_progress']=='UNVERIFIED_FROM_PREVIOUS_VIDEO'
 assert source=={'segment_index':2,'from_keyframe_index':2,'to_keyframe_index':3,
                 'start_time':12.0,'end_time':22.0,'transition_description':'原始双人手势与正面推进。'}
