import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import React from 'react';
import ts from 'typescript';
const read = path => readFile(new URL(`../src/${path}`, import.meta.url), 'utf8');
const compile = source => ts.transpileModule(source.replace(/^import[\s\S]*?;\s*/gm, '').replace(/^export /gm, ''),
  { compilerOptions: { module: ts.ModuleKind.None, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.React } }).outputText;
const source = await read('pages/ChapterGenerate/components/VisualStateDescriptionEditor.tsx');
const factory = new Function('React', 'useState', 'useRef', 'Loader2', 'Save', `${compile(source)};return VisualStateDescriptionEditor;`);
const flatten = node => !node || typeof node !== 'object' ? [] : [node, ...React.Children.toArray(node.props?.children).flatMap(flatten)];
const text = node => typeof node === 'string' ? node : Array.isArray(node) ? node.map(text).join('') : node?.props ? text(node.props.children) : '';
const button = (tree, label) => flatten(tree).find(node => node.type === 'button' && text(node) === label);
const textarea = tree => flatten(tree).find(node => node.type === 'textarea');
const deferred = () => { let resolve; const promise = new Promise(yes => { resolve = yes; }); return { promise, resolve }; };
const settle = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };
function harness(onSave) {
  const states = []; let index = 0;
  const useState = initial => { const key = index++; if (!(key in states)) states[key] = typeof initial === 'function' ? initial() : initial;
    return [states[key], value => { states[key] = typeof value === 'function' ? value(states[key]) : value; }]; };
  const Editor = factory(React, useState, initial => useState(() => ({ current: initial }))[0], () => null, () => null);
  return (props = {}) => { index = 0; return Editor({ label: '视觉状态描述', description: 'original', revision: 1, onSave, ...props }); };
}

test('edit/cancel switch modes, while poll refreshes preserve unsaved text', () => {
  const render = harness(async () => assert.fail('Cancel must not save'));
  let tree = render(); assert.equal(textarea(tree).props.readOnly, true);
  button(tree, '编辑').props.onClick(); tree = render(); assert.equal(textarea(tree).props.readOnly, false);
  textarea(tree).props.onChange({ target: { value: 'draft' } });
  tree = render({ description: 'worker update' }); assert.equal(textarea(tree).props.value, 'draft');
  button(tree, '取消').props.onClick(); tree = render({ description: 'worker update' });
  assert.equal(textarea(tree).props.value, 'worker update'); assert.equal(textarea(tree).props.readOnly, true);
});

test('save uses the original description/revision and deduplicates clicks until success', async () => {
  const pending = deferred(), calls = [];
  const render = harness((...args) => { calls.push(args); return pending.promise; });
  let tree = render(); button(tree, '编辑').props.onClick(); tree = render();
  textarea(tree).props.onChange({ target: { value: '  edited  ' } }); tree = render({ description: 'new poll data', revision: 2 });
  button(tree, '保存').props.onClick(); button(tree, '保存').props.onClick(); assert.deepEqual(calls, [['edited', 'original', 1]]);
  tree = render(); assert.equal(textarea(tree).props.disabled, true); assert.equal(button(tree, '取消').props.disabled, true);
  pending.resolve(); await settle(); tree = render({ description: 'edited' });
  assert.equal(textarea(tree).props.readOnly, true); assert.equal(textarea(tree).props.value, 'edited');
});

test('failed saves retain the draft, show an error, and allow retry', async () => {
  let fail = true;
  const render = harness(async () => { if (fail) throw new Error('视觉状态已更新'); });
  let tree = render(); button(tree, '编辑').props.onClick(); tree = render();
  textarea(tree).props.onChange({ target: { value: 'draft' } }); tree = render(); button(tree, '保存').props.onClick();
  await settle(); tree = render(); assert.equal(textarea(tree).props.value, 'draft');
  assert.equal(text(flatten(tree).find(node => node.props?.role === 'alert')), '视觉状态已更新');
  fail = false; button(tree, '保存').props.onClick(); await settle(); assert.equal(textarea(render()).props.readOnly, true);
});

test('empty/unchanged drafts and active generation cannot save', () => {
  const render = harness(async () => assert.fail('Invalid draft must not save'));
  assert.equal(button(render({ disabled: true }), '编辑').props.disabled, true);
  let tree = render(); button(tree, '编辑').props.onClick(); tree = render(); assert.equal(button(tree, '保存').props.disabled, true);
  textarea(tree).props.onChange({ target: { value: '  ' } }); tree = render(); assert.equal(button(tree, '保存').props.disabled, true);
  textarea(tree).props.onChange({ target: { value: 'draft' } }); tree = render({ disabled: true });
  assert.equal(button(tree, '保存').props.disabled, true); button(tree, '保存').props.onClick();
});

const apiFactory = new Function('fetch', 'api', `${compile(await read('api/shots.ts'))}; return shotsApi;`);
test('description API sends a narrow PATCH with conflict fields', async () => {
  let sent;
  const api = apiFactory(async (url, options) => { sent = { url, ...options }; return { ok: true, json: async () => ({ success: true, data: { description: 'edited' } }) }; }, {});
  await api.saveVisualStateDescription('novel', 'chapter', 'shot', 10, 'edited', 'original', 2);
  assert.equal(sent.url, '/api/novels/novel/chapters/chapter/shots/shot/video-director/states/10/description');
  assert.equal(sent.method, 'PATCH'); assert.deepEqual(JSON.parse(sent.body), { description: 'edited', expected_description: 'original', expected_plan_revision: 2 });
});
test('description API surfaces server conflicts', async () => {
  const api = apiFactory(async () => ({ ok: false, json: async () => ({ detail: '视觉状态已更新' }) }), {});
  await assert.rejects(api.saveVisualStateDescription('n', 'c', 's', 10, 'new', 'old', 2), /视觉状态已更新/);
});
