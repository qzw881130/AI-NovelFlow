import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';
async function load(file, exported, deps={}) {
 const source=await readFile(new URL(`../src/${file}`,import.meta.url),'utf8');
 const js=ts.transpileModule(source.replace(/^import[^;]+;\s*/gm,'').replace(/^export /gm,''),{
  compilerOptions:{target:ts.ScriptTarget.ES2020,module:ts.ModuleKind.None,jsx:ts.JsxEmit.React}}).outputText;
 return new Function('React',...Object.keys(deps),`${js};return ${exported};`)(React,...Object.values(deps));
}
const H3AVTimeline=await load('components/H3AVTimeline.tsx','H3AVTimeline');
const presentation=await load('components/h3PhaseBPresentation.ts','({phaseBSummary,phaseBActualVideo})');
const deps={H3AVTimeline,useState:React.useState,useEffect:React.useEffect,useRef:React.useRef,...presentation};
const Result=await load('components/H3PhaseBResult.tsx','H3PhaseBResult',deps);
const Details=await load('components/H3PhaseBResult.tsx','H3PhaseBDetails',deps);
const renderDetails=record=>renderToStaticMarkup(React.createElement(Details,{record}));
const render=record=>renderToStaticMarkup(React.createElement(Result,{record}));
const record={version:'H3_PHASE_B_LIMITED_V1',status:'COMPILED',clip_index:2,template:{id:'user',name:'User selection'},
 preflight:{passed:true,native_diagnostics:{camera:false}},director_input:{execution_budget:{story_duration:9}},raw_response:'original Director',
 compiler_result:{prompt:'final H3 Prompt',reference_manifest:{references:[{slot:1,kind:'CHARACTER_IDENTITY'}]},
 temporal_manifest:{anchors:[]},execution_decisions:{duration_delta:1.8,timing:{optimized_duration:10.8,
 dialogue_events:[{id:'D27',speaker:'<Subject 2>',original_start:0,original_end:2.75,optimized_start:2.05,optimized_end:4.8}]},
 anchor_catalog:[{anchor_id:'KF9',source_picture:'<Picture 1>',source_kind:'DIRECTOR_VISUAL_ANCHOR'},{anchor_id:'KF10',source_kind:'CANONICAL_VISUAL_STATE'}],
 anchor_decisions:[{id:'KF9',decision:'RETIME',original_time:1.2,optimized_time:4.8},{id:'KF10',decision:'DROP',original_time:3,optimized_time:null}]}}};
test('Phase B shows decisions, references and diagnostics without claiming #14 approval',()=>{
 const html=renderDetails(record);
 for(const text of ['User selection','2.05–4.80','KF9 · RETIME','KF10 · DROP','Canonical 文本状态，无独立图片','final H3 Prompt','original Director','camera','false'])assert.ok(html.includes(text),text);
 assert.match(html,/实际提交绑定：未确认/);
 assert.match(html,/计划到达不等于实测到达/);
 assert.doesNotMatch(html,/#14优化|已采用优化|Speaker Handoffs|Final Settle/);
});
test('failed result remains visible and legacy records do not acquire Phase B labels',()=>{
 assert.match(render({status:'FAILED',error:'DIALOGUE_ORDER_CHANGED'}),/DIALOGUE_ORDER_CHANGED/);
 assert.match(renderDetails({status:'FAILED'}),/未产生最终 Prompt/);
 assert.equal(render(undefined),'');
});
test('Clip and batch requests preserve explicit route; legacy remains default',async()=>{
 const requests=[];const fetch=async(url,opt)=>{requests.push(JSON.parse(opt.body));return {ok:true,json:async()=>({success:true}),text:async()=>'{"success":true}'};};
 const api=await load('api/shots.ts','shotsApi',{api:{},fetch,downloadQueuedShotExport:()=>{throw Error('not used')}});
 await api.generateVideoDirectorClip('n','c','s',1,{h3_prompt_pipeline:'phase_b',clip_plan_revision:3});
 await api.generateVideosBatch('n','c',{shot_ids:['s'],h3_prompt_pipeline:'phase_b'});
 await api.generateVideoDirectorClip('n','c','s',1);
 assert.deepEqual(requests.map(r=>r.h3_prompt_pipeline),['phase_b','phase_b','legacy']);
 assert.equal(requests[0].clip_plan_revision,3);
});
test('novel template field has a distinct managed type in existing video category',async()=>{
 const fields=await load('pages/Novels/promptTemplateFields.ts','TEMPLATE_FIELDS');
 const phase=fields.find(f=>f.templateType==='h3_multi_keyframe_director_phase_b');
 assert.equal(phase.category,'video_generation');assert.equal(phase.key,'h3MultiKeyframeDirectorPhaseBTemplateId');
 for(const kind of ['h3_multi_keyframe_prompt','h3_execution_optimizer_prompt','h3_preflight_repair_prompt'])assert.ok(fields.some(f=>f.templateType===kind));
});

test('main page is compact; details live in a scrollable modal, blocking errors stay visible',()=>{
 const html=render(record);
 assert.ok(html.includes('Phase B · C2 · COMPILED · 10.80s'));
 assert.ok(html.includes('查看规划详情'));
 assert.doesNotMatch(html,/<details|final H3 Prompt|Compiler diagnostics|Dialogue Retiming/);
 assert.doesNotMatch(html,/<dialog/);
 const details=renderDetails(record);
 for(const text of ['计划生成时长：10.80s','参考图：1','Dialogue：1','Warning：1 / Error：0','最终 H3 Prompt','Reference Manifest','时间域换算']) assert.ok(details.includes(text),text);
 const failed=render({...record,status:'FAILED',error:'PICTURE_BINDING_MISMATCH',preflight:{passed:false}});
 assert.match(failed,/<p role="alert"[^>]*>执行阻塞：PICTURE_BINDING_MISMATCH/);
});
test('Shot toolbar suppresses duplicate error text while retaining failure badge and modal evidence',async()=>{
 const failed={...record,status:'FAILED',error:'PICTURE_BINDING_MISMATCH',preflight:{passed:false}};
 const html=renderToStaticMarkup(React.createElement(Result,{record:failed,compact:true,contextSummary:'6 个视觉状态'}));
 assert.match(html,/规划失败/);assert.match(html,/查看规划详情/);
 assert.doesNotMatch(html,/PICTURE_BINDING_MISMATCH|bg-violet-50|6 个视觉状态/);
 let hook=0;
 const Open=await load('components/H3PhaseBResult.tsx','H3PhaseBResult',{...deps,useState:initial=>[++hook===4?true:initial,()=>{}]});
 const modal=renderToStaticMarkup(React.createElement(Open,{record:failed,compact:true,contextSummary:'6 个视觉状态'}));
 assert.equal(modal.split('执行阻塞：PICTURE_BINDING_MISMATCH').length-1,1);
 assert.match(modal,/6 个视觉状态/);
 assert.match(modal,/Compiler diagnostics/);assert.match(modal,/Preflight 与原始 native diagnostics/);
});
test('open modal uses top layer and bounded vertical and horizontal scroll areas',async()=>{
 let hook=0;
 const Open=await load('components/H3PhaseBResult.tsx','H3PhaseBResult',{...deps,useState:initial=>{hook++;return [hook===4?true:initial,()=>{}]}});
 const html=renderToStaticMarkup(React.createElement(Open,{record}));
 assert.match(html,/<dialog/);assert.match(html,/aria-modal="true"/);
 assert.match(html,/phase-b-modal-scroll/);assert.match(html,/min-h-0 min-w-0 flex-1 overflow-y-auto/);
 assert.match(html,/max-w-full overflow-x-auto/);assert.match(html,/min-w-\[36rem\]/);
 assert.ok(html.includes('原始 #13 规划') && html.includes('Compiler diagnostics'));
});
test('actual duration requires completed media and distinguishes cumulative continuation output',()=>{
 const {phaseBActualVideo}=presentation;
 const execution={actual_duration:31.375,artifact_kind:'NATIVE_CONTINUITY_OUTPUT',clip_playback:{independent_media:{video_duration:17.916667}}};
 assert.equal(phaseBActualVideo({status:'running',resultUrl:'/old.mp4',clipExecution:execution}),undefined);
 assert.equal(phaseBActualVideo({status:'completed',clipExecution:execution}),undefined);
 assert.deepEqual(phaseBActualVideo({status:'completed',resultUrl:'/video.mp4',clipExecution:execution}),{seconds:17.916667,label:'实际视频时长（生成片，含共享前缀）'});
 assert.deepEqual(phaseBActualVideo({status:'completed',resultUrl:'/video.mp4',clipExecution:{actual_duration:31.375,artifact_kind:'NATIVE_CONTINUITY_OUTPUT'}}),{seconds:31.375,label:'实际视频时长（累计输出）'});
 assert.equal(phaseBActualVideo({status:'completed',resultUrl:'/video.mp4',clipExecution:{requested_duration:17.5}}),undefined);
});
test('missing records do not claim zero warnings or failed compilation',()=>{
 const html=renderToStaticMarkup(React.createElement(Result,{call:{task_type:'h3_multi_keyframe_director_phase_b',clip_index:1,status:'success'}}));
 assert.match(html,/Phase B · C1 · success · —/);assert.match(html,/查看规划详情/);assert.doesNotMatch(html,/执行阻塞|Warning：0/);
});
test('legacy false diagnostics remain warnings and temporal images stay separate',()=>{
 const s=presentation.phaseBSummary({...record,compiler_result:{...record.compiler_result,temporal_manifest:{anchors:[{anchor_id:'KF6'}]}}});
 assert.equal(s.pictures,1);assert.equal(s.temporal,1);assert.deepEqual(s.warnings,['camera']);assert.deepEqual(s.errors,[]);
});
test('historical Phase B log uses managed category and existing filter request',async()=>{
 const config=await load('pages/PromptConfig/hooks/usePromptConfigState.ts','TEMPLATE_TYPE_CONFIG',{DEFAULT_CHARACTER_TEMPLATE:'',DEFAULT_CHAPTER_SPLIT_TEMPLATE:'',DEFAULT_STYLE_TEMPLATE:''});
 const requests=[];let n=0;const phase='h3_multi_keyframe_director_phase_b';
 const hook=await load('pages/LLMLogs/hooks/useLLMLogsState.ts','useLLMLogsState',{
  useState:initial=>{n++;return [n===4?{category:'video_generation',task_type:phase}:n===5?{task_types:[phase,'h3_execution_optimizer_prompt','keyframe_planner']}:typeof initial==='function'?initial():initial,()=>{}]},
  useEffect:()=>{},useCallback:f=>f,useRef:()=>({current:0}),useTranslation:()=>({t:k=>k,i18n:{}}),
  TEMPLATE_TYPE_CONFIG:config,llmLogsApi:{fetchList:async(...args)=>{requests.push(args);return {success:false}}},toast:{error:()=>{}},LLM_CANCELLED_MESSAGE:'cancelled'
 });
 const state=hook();
 assert.equal(state.getTaskTypeCategoryLabel(phase),'promptConfig.categories.videoGeneration');
 assert.equal(state.getTaskTypeNameLabel(phase),'#13 '+config[phase].nameKey);
 assert.deepEqual(state.taskTypeOptions,[phase,'h3_execution_optimizer_prompt']);
 assert.equal(state.getTaskTypeNameLabel('unknown_raw_task'),'unknown_raw_task');
 await state.applyFilters();assert.equal(requests[0][2].task_type,phase);assert.equal(requests[0][2].category,'video_generation');
});

test('log detail keeps raw task type visible even when request_info already exists',async()=>{
 const noop=()=>null;
 const Modal=await load('pages/LLMLogs/components/LogDetailModal.tsx','LogDetailModal',{
  ImageInputs:noop,H3AVTimeline,Copy:noop,Download:noop,X:noop,ProviderLogo:noop,
  useTranslation:()=>({t:k=>k}),toast:{}
 });
 const html=renderToStaticMarkup(React.createElement(Modal,{log:{id:'historical',created_at:'2026-10-15',task_type:'h3_multi_keyframe_director_phase_b',status:'success',request_info:'{"model":"gpt-5.6-sol"}'},activeTab:'params',onTabChange:()=>{},onClose:()=>{},formatDate:x=>x,getTaskTypeLabel:()=> '视频生成 / #13 单阶段导演',getDisplayDuration:()=> '47s',getStatusBadgeConfig:()=>({bg:'',text:'',label:'成功'})}));
 assert.match(html,/<code[^>]*>h3_multi_keyframe_director_phase_b<\/code>/);
 assert.ok(html.includes('视频生成 / #13 单阶段导演'));
});
