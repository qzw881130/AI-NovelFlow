import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
const read = path => readFile(new URL(`../src/${path}`,import.meta.url),'utf8');
const compile = source => ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ES2020,target:ts.ScriptTarget.ES2020,jsx:ts.JsxEmit.React}}).outputText;
const load = async path => import(`data:text/javascript;base64,${Buffer.from(compile(await read(path))).toString('base64')}`);
const authority = await load('pages/ChapterGenerate/semanticClipAuthority.ts');
const native = await load('pages/ChapterGenerate/nativeClipPresentation.ts');
const summary = compile(await read('pages/Tasks/components/CandidateResultSummary.tsx')).replace('export function','function');
const Summary = new Function('React',`${summary}; return CandidateResultSummary;`)(React);
const api = await read('api/shots.ts');
const fragment = api.slice(api.indexOf('  generateVideoDirectorClip: async'),api.indexOf('  generateVideoDirectorClip: async')+4000);
const method = fragment.slice(fragment.indexOf('async'), fragment.indexOf('\n  },')+4);
const request = new Function('fetch','DEFAULT_H3_PROMPT_PIPELINE',`return ${compile(`const send = ${method};`).replace(/^const send = /,'')}`);
const page = await read('pages/ChapterGenerate/components/VideoGenTab.tsx');

test('single Clip API defaults APPLY, independently transmits both strategies', async () => {
  const bodies=[];
  const send=request(async (url,options)=>{bodies.push(JSON.parse(options.body));return {ok:true,json:async()=>({success:true,data:{taskId:'candidate'}})};},'phase_b');
  await send('n','ch','s',6);
  assert.equal(bodies[0].result_mode,'APPLY');
  for(const continuation_mode of ['AUTO','EXTEND_ONLY']) {
    await send('n','ch','s',6,{continuation_mode,result_mode:'CANDIDATE_ONLY',clip_plan_revision:1});
    assert.equal(bodies.at(-1).result_mode,'CANDIDATE_ONLY');assert.equal(bodies.at(-1).continuation_mode,continuation_mode);
  }
});

test('candidate completion/failure/running never replaces official Clip status or playback', () => {
  const clip={clip_index:6,capability:'GENERATE',generated_by_task_id:'official',video_url:'/official.mp4',execution_status:'APPROVED'};
  const official={id:'official',status:'completed',resultUrl:'/official.mp4',clipExecution:{execution_scope:'CLIP',clip_index:6,clip_plan_revision:1,approval_status:'APPROVED'}};
  for (const status of ['completed','failed','running']) {
    const candidate={...official,id:'candidate',status,resultUrl:'/candidate.mp4',clipExecution:{...official.clipExecution,result_mode:'CANDIDATE_ONLY'}};
    assert.equal(authority.resolveSemanticClipTask(clip,[candidate,official],1),official);
    assert.equal(authority.getSemanticClipStatus(clip,[candidate,official],1),'COMPLETED');
    assert.equal(authority.resolveSemanticClipTask({clip_index:6},[candidate],1),undefined);
    assert.equal(native.getClipArtifactPresentation(clip,candidate).playbackUrl,'/official.mp4');
  }
});

test('candidate Task summary preserves frozen modes, path, hash and existing player callback', () => {
  const task={status:'completed',currentStep:'候选已保存',clipExecution:{result_mode:'CANDIDATE_ONLY',clip_index:6,continuation_mode:'EXTEND_ONLY',planned_capability:'TEMPORAL_EXTEND',effective_capability:'EXTEND',candidate_result:{url:'/candidate.mp4',local_path:'/tmp/candidate.mp4',sha256:'abc',actual_duration:59.5}}};
  const calls=[];const element=Summary({task,onPreviewVideo:url=>calls.push(url)});
  const html=renderToStaticMarkup(element);
  for (const text of ['实验候选','未采用','C6','EXTEND_ONLY','TEMPORAL_EXTEND','/tmp/candidate.mp4','abc','59.5','播放实验候选']) assert.ok(html.includes(text),text);
  const walk=e=>{if(!e || typeof e!=='object')return;if(e.type==='button')e.props.onClick();React.Children.forEach(e.props?.children,walk);};walk(element);
  assert.deepEqual(calls,['/candidate.mp4']);
  assert.equal(Summary({task:{...task,clipExecution:{result_mode:'APPLY'}},onPreviewVideo:()=>{}}),null);
});

test('UI labels single Clip scope; candidates do not set official generating/preview state', () => {
  assert.match(page,/useState<VideoResultMode>\('APPLY'\)/);
  assert.match(page,/aria-label="单 Clip 结果保存方式"/);
  assert.match(page,/Shot 自动\/批量生成仍采用正式结果/);
  const handler=page.slice(page.indexOf('const handleRegenerateClip ='),page.indexOf('const handleMergeDirectorClips ='));
  assert.match(handler,/if \(!candidate\) setSelectedPreviewClipKey/);
  assert.match(handler,/if \(candidate\) \{[\s\S]*?return;\s*\}[\s\S]*?generatingVideos/);
  assert.match(page,/href="\/tasks"/);
});

const storeSource=await read('pages/ChapterGenerate/stores/slices/generationSlice.ts');
const ast=ts.createSourceFile('slice.ts',storeSource,ts.ScriptTarget.Latest,true);let poll;
(function visit(node){if(ts.isPropertyAssignment(node)&&node.name.getText(ast)==='checkVideoTaskStatus')poll=node.initializer.getText(ast);ts.forEachChild(node,visit);})(ast);
const pollFactory=new Function('get','set','fetch','shotsApi','videoStatusRequests','mergePolledVideoShot','formatUserFacingError',compile(`return ${poll};`));
test('lightweight video polling cannot publish candidate URL or mark official Shot as generating',async()=>{
  for(const status of ['completed','running','failed']) {
    const state={chapter:{id:'chapter'},shots:[{id:'s',index:1,videoStatus:'completed',videoUrl:'/official.mp4',videoTaskId:'official',videoDirectorPlan:{merged_video_url:'/official.mp4'}}],shotVideos:{s:'/official.mp4'},generatingVideos:new Set(),pendingVideos:new Set()};
    const before=structuredClone(state);let refreshes=0;
    const tick=pollFactory(()=>state,patch=>{const result=typeof patch==='function'?patch(state):patch;Object.assign(state,result)},
      async()=>({json:async()=>({success:true,data:[{id:'candidate',shotId:'s',status,resultUrl:'/candidate.mp4',resultMode:'CANDIDATE_ONLY'}]})}),
      {getShot:async()=>{refreshes++;throw new Error('candidate must not drive production refresh')}},new Map(),(a,b)=>({...a,...b}),x=>x);
    await tick('chapter');assert.deepEqual(state,before);assert.equal(refreshes,0);
  }
});
