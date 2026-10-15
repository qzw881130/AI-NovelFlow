import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';
const source=await readFile(new URL('../src/pages/ChapterGenerate/components/ClipActionsMenu.tsx',import.meta.url),'utf8');
const code=ts.transpileModule(source.replace(/^import[^;]+;\s*/gm,'').replace('export function','function'),{compilerOptions:{jsx:ts.JsxEmit.React,target:ts.ScriptTarget.ES2020}}).outputText;

test('dropdown keeps all existing actions mounted and preserves disabled states and callbacks',()=>{
 let called=0;
 const actions=[React.createElement('a',{key:0,href:'/inspect'},'执行分析'),...['播放本片段','播放累计视频','重新生成片段','使用当前提示词重新生成'].map((label,i)=>React.createElement('button',{key:i+1,disabled:i===3,onClick:()=>called++},label))];
 for(const open of [false,true]){
  let state=0;let next;
  const deps={React,useState:initial=>[state++===0?open:initial,value=>{next=value;}],useRef:()=>({current:null}),useId:()=>':actions:',useEffect:()=>{},createPortal:child=>child,document:{body:{}},ChevronDown:()=>null};
  const Menu=new Function(...Object.keys(deps),`${code};return ClipActionsMenu;`)(...Object.values(deps));
  const tree=Menu({clipIndex:2,children:actions});
  const [trigger,panel]=tree.props.children;
  assert.equal(trigger.props['aria-expanded'],open);
  assert.equal(panel.props.children,actions);
  assert.equal(panel.props.style.display,open?undefined:'none');
  assert.equal(panel.props.children[4].props.disabled,true);
  panel.props.children[3].props.onClick();
  trigger.props.onClick();assert.equal(next(open),!open);
  const html=renderToStaticMarkup(tree);
  for(const label of ['执行分析','播放本片段','播放累计视频','重新生成片段','使用当前提示词重新生成'])assert.ok(html.includes(label));
  assert.match(html,/fixed z-\[200\]/);
 }
 assert.equal(called,2);
});
