import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import React from 'react';
import ts from 'typescript';
const read = path => readFile(new URL(`../src/${path}`, import.meta.url), 'utf8');
const compile = source => ts.transpileModule(source.replace(/^import[\s\S]*?;\s*/gm, '').replace(/^export /gm, ''), { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.None, jsx: ts.JsxEmit.React } }).outputText;
const source = await read('pages/ChapterGenerate/components/ShotExportModal.tsx');
const factory = new Function('React', 'useRef', 'useState', 'createPortal', 'Download', 'Loader2', 'X', 'document', `${compile(source)};return {ShotExportModal,SHOT_EXPORT_OPTIONS};`);
const flatten = tree => !tree || typeof tree !== 'object' ? [] : [tree,...React.Children.toArray(tree.props?.children).flatMap(flatten)];
const text = tree => typeof tree === 'string' ? tree : typeof tree === 'number' ? String(tree) : Array.isArray(tree) ? tree.map(text).join('') : tree?.props ? text(tree.props.children) : '';
const button = (tree, label) => flatten(tree).find(node => node.type === 'button' && text(node) === label);
const settle = async () => { for(let i=0;i<10;i++) await Promise.resolve(); };
function harness(onExport) {
  let index=0, closed=0; const values=[];
  const useState=initial=>{const i=index++;if(!(i in values)) values[i]=typeof initial==='function'?initial():initial;
    return [values[i], value=>{values[i]=typeof value==='function'?value(values[i]):value;}];};
  const {ShotExportModal,SHOT_EXPORT_OPTIONS}=factory(React,initial=>useState(()=>({current:initial}))[0],useState,tree=>tree,()=>null,()=>null,()=>null,{body:{}});
  return {options:SHOT_EXPORT_OPTIONS,closed:()=>closed,render(){index=0;return ShotExportModal({shotIndex:3,onClose:()=>closed++,onExport});}};
}
test('opening the dialog defaults to all categories and does not start downloading',()=>{
  const h=harness(()=>assert.fail('Only confirm may export')),tree=h.render();
  const checks=flatten(tree).filter(node=>node.type==='input');
  assert.equal(checks.length,11);assert.ok(checks.every(node=>node.props.checked));
  assert.equal(flatten(tree).find(node=>node.props?.role==='dialog').props['aria-modal'],'true');
  button(tree,'取消').props.onClick();assert.equal(h.closed(),1);
});
test('empty selection disables export and a subset sends only checked categories',async()=>{
  const sent=[];const h=harness(async sections=>sent.push(sections));
  let tree=h.render();button(tree,'清空选择').props.onClick();tree=h.render();assert.equal(button(tree,'导出所选内容').props.disabled,true);
  const primary=flatten(tree).find(node=>node.type==='label' && text(node)==='主分镜图');
  flatten(primary).find(node=>node.type==='input').props.onChange({target:{checked:true}});
  tree=h.render();button(tree,'导出所选内容').props.onClick();await settle();
  assert.deepEqual(sent,[['primary_image']]);assert.equal(h.closed(),1);
});
test('packing deduplicates export and failure preserves the window and selection for retry',async()=>{
  let reject;let count=0;const pending=new Promise((_,no)=>{reject=no;});
  const h=harness(()=>{count++;return pending;});let tree=h.render();
  button(tree,'导出所选内容').props.onClick();button(tree,'导出所选内容').props.onClick();assert.equal(count,1);
  assert.equal(button(h.render(),'关闭').props.disabled,undefined);
  reject(new Error('test packing failure'));await settle();tree=h.render();
  assert.equal(h.closed(),0);assert.ok(flatten(tree).filter(node=>node.type==='input').every(node=>node.props.checked));
  assert.equal(text(flatten(tree).find(node=>node.props?.role==='alert')),'test packing failure');
  assert.equal(button(tree,'导出所选内容').props.disabled,false);
});
test('export category keys match the server allowlist and the menu opens the modal',async()=>{
  const backend=await readFile(new URL('../../../backend/app/services/shot_export_selection.py',import.meta.url),'utf8');
  const h=harness(async()=>{});for(const option of h.options) assert.ok(backend.includes(`"${option.key}"`));
  const page=await read('pages/ChapterGenerate/components/VideoGenTab.tsx');
  assert.match(page,/onClick=\{\(\) => setShowShotExportModal\(true\)\}/);
  assert.match(page,/onExport=\{handleDownloadVideoMaterials\}/);
  assert.match(await read('api/shots.ts'),/params\.append\('include', section\)/);
});
