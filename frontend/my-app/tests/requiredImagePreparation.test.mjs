import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import test from 'node:test';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const require = createRequire(import.meta.url);
const toModule = source => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
const compile = source => ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ES2020, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX } }).outputText;
const helperSource = await readFile(new URL('../src/pages/ChapterGenerate/requiredImagePreparation.ts', import.meta.url), 'utf8');
const helperUrl = toModule(compile(helperSource));
const { requiredImageStatus, requiredImagesForClip, clipPreparationPresentation, canPrepareMaterials, prepareCurrentRequiredImages } = await import(helperUrl);
const componentSource = await readFile(new URL('../src/pages/ChapterGenerate/components/RequiredImagesPreparation.tsx', import.meta.url), 'utf8');
const componentModule = compile(componentSource)
  .replace(/from "react\/jsx-runtime"/g, `from ${JSON.stringify(pathToFileURL(require.resolve('react/jsx-runtime')).href)}`)
  .replace(/from ['"]react['"]/g, `from ${JSON.stringify(pathToFileURL(require.resolve('react')).href)}`)
  .replace(/from ['"]\.\.\/\.\.\/\.\.\/api\/shots['"]/g, `from ${JSON.stringify(toModule('export const shotsApi = {};'))}`)
  .replace(/from ['"]\.\.\/requiredImagePreparation['"]/g, `from ${JSON.stringify(helperUrl)}`);
const { RequiredImagesPreparation } = await import(toModule(componentModule));
const sid='f4c64af1-8c5d-4ce0-8443-50970c34b85d';
const provenance = { shot_id: sid, clip_plan_revision: 2, state_index: 4, state_id: 'KF4', state_fingerprint: 'current' };
function item(index, clip, ready=false) {
  return { kind:index===1?'GENERATE_VISUAL_START':'SELECTED_TEMPORAL_TARGET', state_index:index, state_id:`KF${index}`,
    shot_time:index===4?28.8:index===7?52.5:0, consumer_clip_indexes:[clip],consumer_clip_index:clip,
    image_source:index===1?'SHOT_IMAGE':'KEYFRAME_IMAGE',ready,missing:!ready,provenance:{...provenance,state_index:index,state_id:`KF${index}`},
    description:`description KF${index}`,consumers:[{consumer_clip_index:clip,ready}],active_task:null,failure:null };
}
function shot() { return { id:sid, chapterId:'chapter',index:1, keyframes:[{frame_index:2,plan_keyframe_index:4,image_task_id:'new-task'}],
  videoDirectorPlan:{canonical_visual_plan:true,clip_plan_revision:2,clip_plan_validation:{passed:true,temporal_contract:'ELIGIBLE_THEN_SELECTED_V1',composition_contract:'EARLY_COMPOSITION_V1'},
    keyframes:[{index:4,time_seconds:28.8}],required_execution_images:[item(1,1,true),item(4,3),item(7,5)],
    clip_execution_readiness:[{clip_index:3,images_ready:false,ready:false,code:'REQUIRED_IMAGES_MISSING',previous_clip_index:2}] } }; }

test('required projection C3 contains only KF4; batch includes existing KF1 plus KF4/KF7', () => {
  assert.deepEqual(requiredImagesForClip(shot(),3).map(i=>i.state_id),['KF4']);
  assert.deepEqual(requiredImagesForClip(shot()).map(i=>i.state_id),['KF1','KF4','KF7']);
  assert.equal(canPrepareMaterials(shot()),true);
  assert.equal(requiredImageStatus(), 'NOT_REQUIRED');
});

test('current V2 marker permits existing required-image controls', () => {
  const input=shot();
  input.videoDirectorPlan.clip_plan_validation.composition_contract='EARLY_COMPOSITION_V2';
  assert.equal(canPrepareMaterials(input),true);
});

test('READY wins over historical failure; active shows current step; failure remains retryable', () => {
  assert.equal(requiredImageStatus({...item(4,3,true),failure:{error_message:'old'}}),'READY');
  assert.equal(requiredImageStatus({...item(4,3),active_task:{current_step:'sampling'},failure:{error_message:'old'}}),'GENERATING');
  assert.equal(requiredImageStatus({...item(4,3),failure:{error_message:'failed'}}),'FAILED');
  assert.equal(requiredImageStatus(item(4,3)),'REQUIRED_MISSING');
});

test('image-ready C3 still waits C2; current guard alone enables execution', () => {
  const s=shot();s.videoDirectorPlan.required_execution_images[1]=item(4,3,true);
  s.videoDirectorPlan.clip_execution_readiness[0]={clip_index:3,images_ready:true,ready:false,code:'WAITING_PREVIOUS_AV',previous_clip_index:2};
  assert.deepEqual(clipPreparationPresentation(s,3),{imagesReady:true,executionReady:false,label:'等待C2前序视频'});
  s.videoDirectorPlan.clip_execution_readiness[0].ready=true;s.videoDirectorPlan.clip_execution_readiness[0].code='READY';
  assert.equal(clipPreparationPresentation(s,3).executionReady,true);
});

test('rendered Clip area shows KF4/time/currentStep and failure reason/retry just KF4', () => {
  const s=shot();s.videoDirectorPlan.required_execution_images[1].failure={error_message:'mock image failure'};
  const html=renderToStaticMarkup(React.createElement(RequiredImagesPreparation,{shot:s,novelId:'novel',chapterId:'chapter',clipIndex:3,onShot(){}}));
  assert.match(html,/KF4/);assert.match(html,/28\.8s/);assert.match(html,/mock image failure/);assert.match(html,/重试KF4/);
  assert.doesNotMatch(html,/KF7/);assert.match(html,/description KF4/);
  s.videoDirectorPlan.required_execution_images[1].active_task={task_id:'active',current_step:'mock sampling'};
  const running=renderToStaticMarkup(React.createElement(RequiredImagesPreparation,{shot:s,clipIndex:3,onShot(){}}));
  assert.match(running,/mock sampling/);assert.doesNotMatch(running,/重试KF4/);
});

test('batch material render lists ready main image and missing targets', () => {
  const html=renderToStaticMarkup(React.createElement(RequiredImagesPreparation,{shot:shot(),hidePrepare:true,onShot(){}}));
  for(const label of ['KF1','KF4','KF7','主分镜图','已就绪','待生成'])assert.ok(html.includes(label),label);
  assert.doesNotMatch(html,/批量生成视频/);
});

test('Clip prepare sends current revision/Clip scope; retry sends only KF4; always fresh preflight', async () => {
  const s=shot();const calls=[];let reads=0;const fresh=[];
  const ports={getShot:async()=>{reads++;return structuredClone(s)},onShot:x=>fresh.push(x),prepare:async(...args)=>{calls.push(args);return {shot:s,items:[{state_id:'KF4',status:'QUEUED',task_id:'new-task'}]}}};
  await prepareCurrentRequiredImages(s,[3],[4],ports);
  assert.deepEqual(calls,[[2,[3],[4]]]);assert.equal(reads,2);assert.equal(fresh.length,3);
});

test('bulk active KF4 does not stop missing KF7; adapter returns per-item results without video phase', async () => {
  const s=shot();s.videoDirectorPlan.required_execution_images[1].active_task={task_id:'active'};
  let prepared=0;const results=[{state_id:'KF1',status:'READY'},{state_id:'KF4',status:'REUSED'},{state_id:'KF7',status:'QUEUED'}];
  const output=await prepareCurrentRequiredImages(s,undefined,undefined,{getShot:async()=>s,onShot(){},prepare:async(rev,clips,states)=>{
    prepared++;assert.equal(rev,2);assert.equal(clips,undefined);assert.equal(states,undefined);return{shot:s,items:results};
  }});
  assert.deepEqual(output,results);assert.equal(prepared,1);
});

test('stale revision stops prepare before submission', async () => {
  const s=shot();const changed=structuredClone(s);changed.videoDirectorPlan.clip_plan_revision=3;let submits=0;
  await assert.rejects(prepareCurrentRequiredImages(s,[3],undefined,{getShot:async()=>changed,onShot(){},prepare:async()=>{submits++}}),/revision/);
  assert.equal(submits,0);
});

// Exercise the actual store polling function in isolation with fake fetch/Shot APIs.
const storeSource=await readFile(new URL('../src/pages/ChapterGenerate/stores/slices/generationSlice.ts',import.meta.url),'utf8');
const ast=ts.createSourceFile('slice.ts',storeSource,ts.ScriptTarget.Latest,true);let polling;
function visit(node){if(ts.isPropertyAssignment(node)&&node.name.getText(ast)==='checkKeyframeTaskStatus')polling=node.initializer.getText(ast);ts.forEachChild(node,visit)}visit(ast);
const pollingFactory = new Function('get','set','fetch','shotsApi', compile(`return ${polling};`));
function pollingHarness(taskRows,freshShot=shot()) {
  let state={shots:[shot()],keyframeTasks:[{shotId:sid,frameIndex:2,taskId:'new-task',status:'running'}],generatingKeyframes:new Set([`${sid}-2`]),keyframeImageUrls:{}};
  const calls=[];const callback=pollingFactory(()=>state,patch=>{state={...state,...patch}},async()=>({json:async()=>({success:true,data:taskRows})}),{getShot:async(...args)=>{calls.push(args);return{success:true,data:freshShot}}});
  return{callback,calls,state:()=>state};
}
const currentTask=(status)=>({id:'new-task',name:`生成关键帧图片: ${sid}-2`,shotId:sid,status,currentStep:'mock current step',errorMessage:status==='failed'?'mock error':null,canonicalImageProvenance:provenance,resultUrl:'/completed-only.png'});

test('terminal polling passes novelId and fresh Shot controls readiness, not completed Task URL', async () => {
  const harness=pollingHarness([currentTask('completed')]);await harness.callback('chapter','novel');
  assert.deepEqual(harness.calls,[['novel','chapter',sid]]);
  assert.equal(harness.state().shots[0].videoDirectorPlan.required_execution_images[1].ready,false);
  assert.equal(harness.state().keyframeImageUrls[`${sid}-2`],undefined);
  assert.equal(harness.state().keyframeTasks[0].currentStep,'mock current step');
});

test('FAILED polling preserves reason and refreshes; old failed Task cannot clear new running attempt', async () => {
  const harness=pollingHarness([currentTask('failed')]);await harness.callback('chapter','novel');
  assert.equal(harness.calls.length,1);assert.equal(harness.state().keyframeTasks[0].errorMessage,'mock error');
  const old={...currentTask('failed'),id:'old-task'};
  const active=pollingHarness([currentTask('running'),old]);await active.callback('chapter','novel');
  assert.ok(active.state().generatingKeyframes.has(`${sid}-2`));assert.equal(active.calls.length,0);
});

test('replan old frame-name Task never impersonates current State failure', async () => {
  const stale={...currentTask('failed'),canonicalImageProvenance:{...provenance,clip_plan_revision:1}};
  const harness=pollingHarness([stale]);await harness.callback('chapter','novel');
  assert.equal(harness.calls.length,0);assert.equal(harness.state().keyframeTasks.length,0);assert.equal(harness.state().generatingKeyframes.size,0);
});

test('UI wiring keeps separate material selection, Clip scopes and existing manual video Batch', async()=>{
  const ui=await readFile(new URL('../src/pages/ChapterGenerate/components/VideoGenTab.tsx',import.meta.url),'utf8');
  const entry=await readFile(new URL('../src/pages/ChapterGenerate/index.tsx',import.meta.url),'utf8');
  assert.match(entry,/checkKeyframeTaskStatus\(cid, id\)/);
  assert.match(ui,/clipIndex=\{Number\(clip.clip_index\)\}/);assert.match(ui,/!preparation.executionReady/);
  assert.match(ui,/data-testid="batch-material-preparation"/);assert.match(ui,/materialShotIds/);
  assert.match(ui,/生成全部必需视觉状态图/);assert.match(ui,/手动选择并点击原有/);
  assert.match(ui,/\(!isCanonicalPlan && hasGeneratingMissingKeyframes\)/);
});

test('composition reason stays visible in existing material controls and legacy marker cannot prepare', async () => {
  const input = shot();
  const required = input.videoDirectorPlan.required_execution_images[1];
  required.kind = 'EARLY_COMPOSITION';
  required.consumers[0].kind = 'EARLY_COMPOSITION';
  const html = renderToStaticMarkup(React.createElement(RequiredImagesPreparation, { shot: input, clipIndex: 3, onShot() {} }));
  assert.match(html, /已选为早期构图锚点，执行必需/);
  assert.match(html, /生成必需视觉状态图/);
  delete input.videoDirectorPlan.clip_plan_validation.composition_contract;
  assert.equal(canPrepareMaterials(input), false);
  let submitted = false;
  await assert.rejects(prepareCurrentRequiredImages(input, [3], [4], {
    getShot: async () => input,
    prepare: async () => { submitted = true; },
    onShot() {},
  }), /重新规划/);
  assert.equal(submitted, false);
});
