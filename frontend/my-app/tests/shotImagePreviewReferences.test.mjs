import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

globalThis.fetch = async () => assert.fail('Unexpected real network request');

const modalUrl = new URL('../src/pages/ChapterGenerate/components/Modals.tsx', import.meta.url);
const videoUrl = new URL('../src/pages/ChapterGenerate/components/VideoGenTab.tsx', import.meta.url);
const hookUrl = new URL('../src/pages/ChapterGenerate/useShotReferenceImages.ts', import.meta.url);
const taskApiUrl = new URL('../src/api/tasks.ts', import.meta.url);
const modalSource = await readFile(modalUrl, 'utf8');
const videoSource = await readFile(videoUrl, 'utf8');
const hookSource = await readFile(hookUrl, 'utf8');
const taskApiSource = await readFile(taskApiUrl, 'utf8');

test('shot preview loads the exact generation task reference snapshot', () => {
  assert.match(modalSource, /useShotReferenceImages\(previewShot, isOpen\)/);
  assert.match(hookSource, /shot\?\.imageTaskId \|\| shot\?\.image_task_id/);
  assert.match(hookSource, /taskApi\.fetch\(taskId\)/);
  assert.match(taskApiSource, /referenceImages\?: Array<\{ label\?: string; url: string \}>/);
});

test('shot preview renders references in a height-bounded scrollable right column', () => {
  assert.match(modalSource, /aria-label="分镜参考图"/);
  assert.match(modalSource, /style=\{\{ height: `\$\{previewImageRenderedHeight\}px`, maxHeight: '60vh' \}\}/);
  assert.match(modalSource, /min-h-0 flex-1 space-y-2 overflow-y-auto/);
  assert.match(modalSource, /referenceImages\.map\(\(image, index\)/);
});

test('shot preview shows a large reference preview to the right on hover', () => {
  assert.match(modalSource, /onMouseEnter=\{\(\) => setHoveredReferenceImage\(image\)\}/);
  assert.match(modalSource, /onMouseLeave=\{\(\) => setHoveredReferenceImage\(null\)\}/);
  assert.match(modalSource, /aria-label="参考图大图预览"/);
  assert.match(modalSource, /absolute left-full top-0/);
  assert.match(modalSource, /max-h-\[52vh\].*object-contain/);
});

test('video START state uses the same shot references beside the main image', () => {
  assert.match(videoSource, /useShotReferenceImages\(shot, !!shotImageUrl\)/);
  assert.match(videoSource, /selectedKeyframe\?\.role === 'START'\s*\? shotReferenceImages/);
  assert.match(videoSource, /aria-label="分镜参考图"/);
  assert.match(videoSource, /absolute inset-0 space-y-1 overflow-y-auto/);
});


const videoAst=ts.createSourceFile('VideoGenTab.tsx',videoSource,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
function declaration(name) {
  let result;
  function find(node) {
    if(ts.isFunctionDeclaration(node) && node.name?.text===name) result=node.getText(videoAst);
    if(ts.isVariableDeclaration(node) && node.name.getText(videoAst)===name) result=`const ${node.getText(videoAst)};`;
    ts.forEachChild(node,find);
  }
  find(videoAst);assert.ok(result,name);return result;
}
const compile=source=>ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2020,module:ts.ModuleKind.None,jsx:ts.JsxEmit.React}}).outputText;
const nativeSource=await readFile(new URL('../src/pages/ChapterGenerate/nativeClipPresentation.ts',import.meta.url),'utf8');
const nativeModule=await import(`data:text/javascript;base64,${Buffer.from(ts.transpileModule(nativeSource,{compilerOptions:{target:ts.ScriptTarget.ES2020,module:ts.ModuleKind.ES2020}}).outputText).toString('base64')}`);
const ClipExecutionDetails=new Function('React','getClipArtifactPresentation','getPreviousAvPresentation',`${compile(declaration('ClipExecutionDetails'))};return ClipExecutionDetails;`)(React,nativeModule.getClipArtifactPresentation,nativeModule.getPreviousAvPresentation);
const displayName=new Function(`${compile(declaration('getReferenceDisplayName'))};return getReferenceDisplayName;`)();
const clip={clip_index:2,start_time:8,end_time:16,capability:'EXTEND',continuity_to_previous:'CONTINUOUS',
  previous_clip_index:1,visual_state_indexes:[4],carry_in_state_index:3,selected_temporal_target_ids:[]};
const plan={clip_plan_revision:2,required_execution_images:[],clip_execution_readiness:[{clip_index:2,code:'WAITING_PREVIOUS_AV'}]};
const renderDetails=(c=clip,p=plan,task)=>renderToStaticMarkup(React.createElement(ClipExecutionDetails,{clip:c,plan:p,task}));

test('Clip details project backend capability, ownership, carry-in and Previous AV readiness',()=>{
  const c=structuredClone(clip),p=structuredClone(plan),before=structuredClone({c,p});
  const html=renderDetails(c,p,{id:'task',clipExecution:{capability:'GENERATE'}});
  assert.match(html,/Capability：EXTEND/);assert.doesNotMatch(html,/Capability：GENERATE/);
  assert.match(html,/Owned states：KF4/);assert.match(html,/Carry-in：KF3（仅承接，非 owned\/reference）/);
  assert.match(html,/Previous AV dependency：C1/);assert.match(html,/WAITING_PREVIOUS_AV/);
  assert.match(html,/Selected temporal targets：无/);assert.doesNotMatch(html,/Picture 3|Picture 4/);
  assert.deepEqual({c,p},before);
});

test('Physical Picture index comes only from the final backend manifest, not State index',()=>{
  const task={id:'current',clipExecution:{video_reference_manifest:{references:[
    {slot:1,kind:'DIRECTOR_VISUAL_ANCHOR',source_keyframe_index:8,image_url:'/eight.png'},
    {slot:2,kind:'SCENE',image_url:'/scene.png'},
    {slot:7,kind:'PROP',image_url:'/prop.png'}]}}};
  const html=renderDetails(clip,plan,task);
  assert.match(html,/Picture 1.*State KF8/);assert.match(html,/Picture 2.*SCENE/);assert.match(html,/Picture 7.*PROP/);
  assert.doesNotMatch(html,/Picture 8|Picture 3/);
});

test('eligible but unselected state and label KF never imply a materialized temporal anchor',()=>{
  const html=renderDetails({...clip,visual_state_indexes:[4]}, {...plan,keyframes:[{index:4,timed_visual_target:true,image_url:'/eligible.png'}]});
  assert.match(html,/Selected temporal targets：无/);assert.match(html,/Temporal Anchors：0 个/);
  assert.equal(displayName({label:'KF4',sources:['KF4']}),'KF4');
  assert.equal(displayName({kind:'DIRECTOR_VISUAL_ANCHOR',sources:['KF4']}),'视觉锚点：KF4');
  assert.doesNotMatch(html,/TEMPORAL_ANCHOR|Picture 4/);
});

test('selected targets and materialized temporal anchors remain separate backend projections',()=>{
  const html=renderDetails({...clip,capability:'TEMPORAL_EXTEND',selected_temporal_target_ids:['KF4']},plan,
    {id:'current',clipExecution:{execution_contract:{temporal_anchor_manifest:{anchors:[{anchor_id:'KF4',time_seconds:2}]}}}});
  assert.match(html,/Selected temporal targets：KF4/);assert.match(html,/Temporal Anchors：KF4 @ 2s/);
  assert.doesNotMatch(html,/Picture 4/);
  assert.equal(displayName({kind:'TEMPORAL_ANCHOR',sources:['KF4']}),'时间锚点：KF4');
});

test('reference category labels use backend kinds rather than guessing from KF numbering',()=>{
  for(const [kind,sources,expected] of [
    ['CHARACTER_IDENTITY',['CHAR:Alice'],'角色：Alice'],['SCENE',['SCENE:Gate'],'场景：Gate'],
    ['PROP',['PROP:Hat'],'道具：Hat'],['DIRECTOR_VISUAL_ANCHOR',['SHOT_IMAGE'],'主分镜图'],
    ['TEMPORAL_ANCHOR',['KF8'],'时间锚点：KF8']]) assert.equal(displayName({kind,sources}),expected);
  assert.equal(displayName({label:'角色：Alice',source:'current_resource'}),'角色：Alice（当前资源补充预览）');
});

test('missing optional state stays optional and only backend required images appear as missing',()=>{
  const p={...plan,keyframes:[{index:8,timed_visual_target:true,image_url:null}],required_execution_images:[
    {state_id:'KF4',state_index:4,consumer_clip_indexes:[2],ready:false,missing:true},
    {state_id:'KF7',state_index:7,consumer_clip_indexes:[3],ready:false,missing:true},
    {state_id:'KF1',state_index:1,consumer_clip_indexes:[2],ready:true,missing:false}]};
  const html=renderDetails(clip,p);
  assert.match(html,/Required images：KF4 缺失，请准备图片、KF1 已就绪/);assert.doesNotMatch(html,/KF7|KF8/);
  const unknown=renderDetails(clip,{...plan,required_execution_images:[{state_id:'KF4',consumer_clip_indexes:[2]}]});
  assert.match(unknown,/KF4 状态未提供/);assert.doesNotMatch(unknown,/KF4 缺失/);
});

test('zero refs, no Previous AV, absent legacy fields and null array entries do not crash',()=>{
  for(const [c,p] of [[{},{}],[{clip_index:1,visual_state_indexes:null,selected_temporal_target_ids:null},
    {required_execution_images:[null],clip_execution_readiness:[null]}]]) {
    const html=renderDetails(c,p,{clipExecution:{video_reference_manifest:{references:[null]},execution_contract:{temporal_anchor_manifest:{anchors:[null]}}}});
    assert.match(html,/Capability：未提供/);assert.match(html,/Previous AV dependency：无/);
    assert.match(html,/历史数据仅供查看/);assert.doesNotMatch(html,/Picture 1|TEMPORAL_ANCHOR/);
  }
});

// Execute production hooks with mock React state/effects and mock read-only API.
// Rendering and effect flushing are separate so stale data before effects is checked too.
function hookHarness(factory,ports={}) {
  const values=[],effects=[];let cursor=0,effectCursor=0,pending=[];
  const hooks={
    useState(initial){const i=cursor++;if(!(i in values))values[i]=typeof initial==='function'?initial():initial;
      return [values[i],v=>{values[i]=typeof v==='function'?v(values[i]):v;}];},
    useRef(initial){return hooks.useState(()=>({current:initial}))[0];},
    useMemo(fn){return fn();},useCallback(fn){return fn;},
    useEffect(fn,deps){const i=effectCursor++;const old=effects[i];
      if(!old || deps.some((v,j)=>!Object.is(v,old.deps[j])))pending.push(()=>{
        old?.cleanup?.();effects[i]={deps,cleanup:fn()};});}
  };
  const run=factory(hooks,ports);
  return {render(...args){cursor=0;effectCursor=0;pending=[];return run(...args);},
    flush(){const jobs=pending;pending=[];jobs.forEach(fn=>fn());},unmount(){effects.forEach(x=>x.cleanup?.());}};
}
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const settle=async()=>{await new Promise(resolve=>setImmediate(resolve));};
const hookCode=compile(hookSource.replace(/^import[^;]+;\s*/gm,'').replace('export function','function'));
const hookFactory=(hooks,ports)=>new Function('useEffect','useMemo','useState','taskApi','useChapterGenerateStore','projectShotReferenceImages',
  `${hookCode};return useShotReferenceImages;`)(hooks.useEffect,hooks.useMemo,hooks.useState,ports.taskApi,
    selector=>selector({characters:[],props:[]}),refs=>refs.map(x=>({...x,source:'task'})));

function referenceHarness(){const requests=[];const harness=hookHarness(hookFactory,{taskApi:{fetch(id){const d=deferred();requests.push({id,...d});return d.promise;}}});return {harness,requests};}

test('reference refresh with the same task ID uses the fresh Shot and hides old snapshot immediately',async()=>{
  const {harness:h,requests:r}=referenceHarness();const old={imageTaskId:'same'};
  h.render(old);h.flush();r[0].resolve({data:{referenceImages:[{label:'old',url:'/old.png'}]}});await settle();
  assert.equal(h.render(old).referenceImages[0].url,'/old.png');
  const fresh={imageTaskId:'same'};
  assert.deepEqual(h.render(fresh).referenceImages,[]);h.flush();assert.equal(r.length,2);
  r[1].resolve({data:{referenceImages:[{label:'new',url:'/new.png'}]}});await settle();
  assert.equal(h.render(fresh).referenceImages[0].url,'/new.png');h.unmount();
});

test('old Shot/task response cannot overwrite a new current reference request',async()=>{
  const {harness:h,requests:r}=referenceHarness();const a={imageTaskId:'A'},b={imageTaskId:'B'};
  h.render(a);h.flush();h.render(b);h.flush();
  r[1].resolve({data:{referenceImages:[{url:'/B.png'}]}});await settle();
  r[0].resolve({data:{referenceImages:[{url:'/A.png'}]}});await settle();
  assert.equal(h.render(b).referenceImages[0].url,'/B.png');h.unmount();
});

test('missing historical task fields, errors, disabled and zero-task references degrade to empty',async()=>{
  for(const response of [{data:{}},{data:{referenceImages:[null,{url:3},{url:''}]}}]){
    const {harness:h,requests:r}=referenceHarness();const shot={imageTaskId:'A'};
    h.render(shot);h.flush();r[0].resolve(response);await settle();assert.deepEqual(h.render(shot).referenceImages,[]);
    assert.deepEqual(h.render(shot,false).referenceImages,[]);h.flush();h.unmount();
  }
  const {harness:h,requests:r}=referenceHarness();h.render({});h.flush();assert.equal(r.length,0);
  const shot={imageTaskId:'bad'};h.render(shot);h.flush();r[0].reject(new Error('mock'));await settle();
  assert.deepEqual(h.render(shot).referenceImages,[]);assert.equal(h.render(shot).referenceImagesLoading,false);h.unmount();
});

const popoverFactory=(hooks,ports)=>new Function('React','useRef','useState','useCallback','useEffect','createPortal','taskApi','document',
  `${compile(declaration('ClipMetadataDetails'))};return ClipMetadataDetails;`)(React,hooks.useRef,hooks.useState,hooks.useCallback,hooks.useEffect,
    children=>children,ports.taskApi,{body:{},addEventListener(){},removeEventListener(){}});
const originalWindow=globalThis.window;
globalThis.window={addEventListener(){},removeEventListener(){},innerHeight:800,innerWidth:1200};
function popoverHarness(){const requests=[];const h=hookHarness(popoverFactory,{taskApi:{fetch(id){const d=deferred();requests.push({id,...d});return d.promise;}}});return {h,requests};}
const shownTask=tree=>tree.props.children[1].props.children;
const open=tree=>tree.props.onToggle({currentTarget:{open:true}});

test('Clip detail refresh/replan drops old execution metadata and late old responses',async()=>{
  const {h,requests:r}=popoverHarness();const a={id:'A',clipExecution:{clip_plan_revision:1}},b={id:'B',clipExecution:{clip_plan_revision:2}};
  let tree=h.render({task:a,children:x=>x});h.flush();open(tree);
  tree=h.render({task:a,children:x=>x});h.flush();assert.equal(r[0].id,'A');
  tree=h.render({task:b,children:x=>x});assert.equal(shownTask(tree),b);h.flush();
  r[1].resolve({data:{...b,referenceImages:[{url:'/new.png'}]}});await settle();
  r[0].resolve({data:{...a,referenceImages:[{url:'/old.png'}]}});await settle();
  assert.equal(shownTask(h.render({task:b,children:x=>x})).referenceImages[0].url,'/new.png');h.unmount();
});

test('Clip detail rejects mismatched backend task identity or revision',async()=>{
  for(const data of [{id:'other',clipExecution:{clip_plan_revision:2}},{id:'A',clipExecution:{clip_plan_revision:1}}]){
    const {h,requests:r}=popoverHarness();const a={id:'A',clipExecution:{clip_plan_revision:2}};
    const props={task:a,children:x=>x};let tree=h.render(props);h.flush();open(tree);h.render(props);h.flush();
    r[0].resolve({data});await settle();assert.equal(shownTask(h.render(props)),a);h.unmount();
  }
});

test('Clip polling hydrates current task details before its next read and ignores unmounted results',async()=>{
  const panel=declaration('SemanticClipExecutionPanel');
  const ast=ts.createSourceFile('panel.tsx',panel,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
  let effect;
  function find(node){if(ts.isCallExpression(node)&&node.expression.getText(ast)==='useEffect')effect=node.arguments[0].getText(ast);ts.forEachChild(node,find);}
  find(ast);assert.ok(effect);
  const requests=[],details=[],applied=[],timers=[];
  const invoke=new Function('chapterId','shot','clips','revision','taskApi','resolveSemanticClipTask','setTasks','onTasksChange','setLoading','window',
    `${compile(`const effect=${effect};`)};return effect();`);
  const task={id:'current',clipExecution:{execution_scope:'CLIP',clip_index:2,clip_plan_revision:2}};
  const cleanup=invoke('chapter',{id:'shot'},[clip],2,{fetchShotTasks(){const d=deferred();requests.push(d);return d.promise;},fetch(){const d=deferred();details.push(d);return d.promise;}},
    (_clip,rows)=>rows.find(row=>row.id==='current'),x=>applied.push(x),()=>{},()=>{},
    {setTimeout(fn){timers.push(fn);return timers.length;},clearTimeout(){}});
  assert.equal(requests.length,1);assert.equal(timers.length,0);
  requests[0].resolve({data:[task]});await settle();
  assert.equal(details.length,1);assert.equal(timers.length,0);
  details[0].resolve({data:{...task,clipExecution:{...task.clipExecution,video_reference_manifest:{references:[]}}}});await settle();
  assert.equal(applied.length,1);assert.deepEqual(applied[0][0].clipExecution.video_reference_manifest.references,[]);
  assert.equal(timers.length,1);timers[0]();assert.equal(requests.length,2);
  requests[1].resolve({data:[{...task,status:'running'}]});await settle();
  assert.equal(applied.length,2);assert.equal(applied[1][0].status,'running');
  assert.deepEqual(applied[1][0].clipExecution.video_reference_manifest.references,[]);
  assert.equal(details.length,1);
  timers[1]();cleanup();requests[2].resolve({data:[{id:'late'}]});await settle();
  assert.equal(applied.length,2);
});
