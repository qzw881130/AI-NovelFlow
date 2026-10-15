import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';
const root=new URL('../src/pages/ChapterGenerate/components/',import.meta.url);
const page=await readFile(new URL('VideoGenTab.tsx',root),'utf8');
const ast=ts.createSourceFile('page.tsx',page,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
function declaration(name){let found;function walk(n){if(ts.isFunctionDeclaration(n)&&n.name?.text===name)found=n.getText(ast);if(ts.isVariableDeclaration(n)&&n.name.getText(ast)===name)found=`const ${n.getText(ast)};`;ts.forEachChild(n,walk);}walk(ast);assert.ok(found,name);return found;}
const compile=s=>ts.transpileModule(s,{compilerOptions:{jsx:ts.JsxEmit.React,target:ts.ScriptTarget.ES2020,module:ts.ModuleKind.CommonJS}}).outputText;
function load(s,name,deps={}){return new Function('React',...Object.keys(deps),`${compile(s)};return ${name};`)(React,...Object.values(deps));}
const strip=s=>s.replace(/^import[^;]+;\s*/gm,'').replace(/^export default.*$/gm,'').replace(/^export /gm,'');
const layout=await readFile(new URL('ThreeColumnLayout.tsx',root),'utf8');

test('collapsed resource sidebar has zero layout width and keeps the same store toggle; expanded width is restored',()=>{
 for(const collapsed of [false,true]){
  let toggled=0;const resize=[];
  const C=load(strip(layout),'ThreeColumnLayout',{useChapterGenerateStore:()=>({leftPanelWidth:280,rightPanelWidth:320,leftPanelCollapsed:collapsed,rightPanelCollapsed:false,toggleLeftPanel:()=>toggled++}),useResizable:opts=>{resize.push(opts);return {width:opts.initialWidth,handleMouseDown:()=>{}};}});
  const tree=C({leftPanel:'资源内容',centerContent:'视频主体',rightPanel:null});
  const sidebar=tree.props.children[0];const html=renderToStaticMarkup(tree);
  assert.equal(sidebar.props.style.width,collapsed?0:280);
  assert.equal(resize[0].collapsedWidth,0);
  assert.equal(html.includes('资源内容'),!collapsed);
  assert.ok(html.includes('视频主体'));
  const toggle=sidebar.props.children.find(x=>x?.type==='button');toggle.props.onClick();assert.equal(toggled,1);
  assert.equal(toggle.props['aria-expanded'],!collapsed);
 }
});

test('review row orders existing actions before unchanged quality state, including historical no-task images',()=>{
 const Badge=({status})=>React.createElement('span',{'data-quality-status':status},status);
 for(const status of ['PASS','WARNING','FAIL','NOT_REVIEWED']){
  const actions=load(declaration('renderImageReviewActions'),'renderImageReviewActions',{getKeyframeImageTaskId:k=>k.task,loadingImageReviewTask:null,isKeyframeGenerating:()=>false,openImageReview:()=>{throw Error('not clicked');},renderImageQuality:()=>React.createElement(Badge,{status})});
  const html=renderToStaticMarkup(actions({task:'t'},'/image.png'));
  assert.ok(html.indexOf('AI 评审')<html.indexOf('查看评审历史'));
  assert.ok(html.indexOf('查看评审历史')<html.indexOf('data-quality-status'));
  assert.match(html,/flex flex-wrap items-center/);
  assert.equal(actions({task:'t'},null),null);
  const legacy=renderToStaticMarkup(actions({},'/historical.png'));assert.match(legacy,new RegExp(status));assert.doesNotMatch(legacy,/AI 评审/);
 }
});

test('Clip card preserves all Dialogue identifiers, original speakers, text and order; silent Clip is explicit',()=>{
 const Details=load(declaration('ClipDialogueList'),'ClipDialogueList');
 const rows=[['D1','老大臣妻子','今天怎么这么早？'],['D2','老大臣','陛下派我去办一件事。'],['D3','老大臣妻子','什么事？'],['D4','老大臣','去看一块布。'],['D5','老大臣妻子','一块布也值得你这样紧张？'],['D6','老大臣','那不是普通的布。']].map(([dialogue_id,speaker,text])=>({dialogue_id,speaker,text}));
 const props={dialogueAssignment:rows};const before=structuredClone(props);
 const html=renderToStaticMarkup(React.createElement(Details,props));let end=-1;
 for(const r of rows){const text=`${r.dialogue_id} · ${r.speaker}：${r.text}`;const at=html.indexOf(text);assert.ok(at>end,text);end=at;}
 assert.deepEqual(props,before);
 const silent=renderToStaticMarkup(React.createElement(Details,{dialogueAssignment:[]}));assert.match(silent,/此片段无对白/);assert.doesNotMatch(silent,/role="alert"/);
});

test('Clip detail Modal is top-layer, scrollable and keeps task hydration identity/revision guards',()=>{
 const code=declaration('ClipMetadataDetails');
 let state=0;const C=load(code,'ClipMetadataDetails',{useRef:()=>({current:null}),useState:initial=>[++state===1?true:initial,()=>{}],useEffect:()=>{},taskApi:{}});
 const html=renderToStaticMarkup(React.createElement(C,{task:{id:'task'},children:t=>React.createElement('div',{},t.id)}));
 assert.match(html,/<dialog[^>]*aria-label="Clip 执行详情"/);assert.match(html,/min-h-0 min-w-0 flex-1 overflow-auto/);
 assert.match(html,/>task<\/div>/);assert.match(code,/data\?\.id === task\.id/);assert.match(code,/data\.clipExecution\?\.clip_plan_revision === task\.clipExecution\?\.clip_plan_revision/);
});


test('card keeps state controls, Phase B and Dialogue outside the generic detail Modal',()=>{
 const panel=declaration('SemanticClipExecutionPanel');
 const modal=panel.slice(panel.indexOf('<ClipMetadataDetails'),panel.indexOf('</ClipMetadataDetails>'));
 assert.doesNotMatch(modal,/<ClipVisualStateReferences|<H3PhaseBResult|<ClipDialogueList/);
 for(const component of ['ClipVisualStateReferences','H3PhaseBResult','ClipDialogueList']) assert.ok(panel.indexOf(`<${component}`)>panel.indexOf('</ClipMetadataDetails>'));
 assert.doesNotMatch(declaration('ClipExecutionDetails'),/<H3PhaseBResult|Dialogue 原文/);
 assert.match(panel,/call.task_type === 'h3_multi_keyframe_director_phase_b' && Number\(call.clip_index\) === Number\(clip.clip_index\)/);
});

test('narrow layout scrolls the stacked editor and preview without squeezing Clip cards to zero height',()=>{
 assert.match(page,/flex-col lg:flex-row gap-4 overflow-y-auto lg:overflow-hidden/);
 assert.match(page,/video-main-column flex-none lg:flex-1 min-w-0/);
 assert.match(page,/event.key === 'ArrowLeft' \|\| event.key === 'ArrowRight'\) event.stopPropagation\(\)/);
});
