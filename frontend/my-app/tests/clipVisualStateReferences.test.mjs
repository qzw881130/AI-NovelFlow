import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import test from 'node:test';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const require = createRequire(import.meta.url);
const moduleUrl = source => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
const compile = source => ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ES2020, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX } }).outputText;
const helper = moduleUrl(compile(await readFile(new URL('../src/pages/ChapterGenerate/clipVisualStateReferences.ts', import.meta.url), 'utf8')));
const { clipVisualStateOptions, visualStatePromptIsCurrent } = await import(helper);
const apiSource = compile(await readFile(new URL('../src/api/shots.ts', import.meta.url), 'utf8'))
  .replace(/from ['"]\.\/index['"]/g, `from ${JSON.stringify(moduleUrl('export const api = {};'))}`)
  .replace(/from ['"]\.\/shotExports['"]/g, `from ${JSON.stringify(moduleUrl('export const downloadQueuedShotExport = () => {};'))}`);
const apiUrl = moduleUrl(apiSource);
const { shotsApi } = await import(apiUrl);
const component = compile(await readFile(new URL('../src/pages/ChapterGenerate/components/ClipVisualStateReferences.tsx', import.meta.url), 'utf8'))
  .replace(/from ['"]react\/jsx-runtime['"]/g, `from ${JSON.stringify(pathToFileURL(require.resolve('react/jsx-runtime')).href)}`)
  .replace(/from ['"]react['"]/g, `from ${JSON.stringify(pathToFileURL(require.resolve('react')).href)}`)
  .replace(/from ['"]\.\.\/\.\.\/\.\.\/api\/shots['"]/g, `from ${JSON.stringify(apiUrl)}`)
  .replace(/from ['"]\.\.\/clipVisualStateReferences['"]/g, `from ${JSON.stringify(helper)}`);
const { ClipVisualStateReferences } = await import(moduleUrl(component));
const base = { clip_index: 6, visual_state_indexes: [9, 10, 11, 12] };

test('legacy defaults to all; explicit [] survives a reload and stays per Clip', () => {
  assert.equal(clipVisualStateOptions(base).filter(s => s.enabled).length, 4);
  const saved = JSON.parse(JSON.stringify({ ...base, visual_state_reference_config: { enabled_state_ids: [] } }));
  assert.equal(clipVisualStateOptions(saved).filter(s => s.enabled).length, 0);
  assert.equal(clipVisualStateOptions(base).filter(s => s.enabled).length, 4);
  assert.deepEqual(clipVisualStateOptions({ ...base, visual_state_reference_config: { enabled_state_ids: ['KF10', 'KF11'] } }).filter(s => s.enabled).map(s => s.id), ['KF10','KF11']);
});

test('row displays individual checkboxes, count and both bulk controls', () => {
  const clip = { ...base, visual_state_reference_config: { enabled_state_ids: ['KF10', 'KF11'] } };
  const html = renderToStaticMarkup(React.createElement(ClipVisualStateReferences, {
    shot: { id: 'shot', videoDirectorPlan: { clip_plan_revision: 2 } }, clip,
    novelId: 'novel', chapterId: 'chapter', onShot() {}, onSaving() {},
  }));
  assert.equal((html.match(/type="checkbox"/g) || []).length, 4);
  assert.equal((html.match(/checked=""/g) || []).length, 2);
  for (const text of ['视觉状态：', '已启用 2/4', '全部启用', '全部禁用']) assert.ok(html.includes(text), text);
});

test('all disabled, no states and busy rows render correctly', () => {
  const render = clip => renderToStaticMarkup(React.createElement(ClipVisualStateReferences, {
    shot: { id: 'shot' }, clip, novelId: 'novel', chapterId: 'chapter', disabled: true, onShot() {}, onSaving() {},
  }));
  const html = render({ ...base, visual_state_reference_config: { enabled_state_ids: [] } });
  assert.ok(html.includes('已启用 0/4'));
  assert.equal((html.match(/checked=""/g) || []).length, 0);
  assert.equal((html.match(/disabled=""/g) || []).length, 6);
  assert.ok(render({ ...base, visual_state_indexes: [] }).includes('已启用 0/0'));
});

test('old prompt cannot be reused after selection changes; restore-all permits legacy cache', () => {
  assert.equal(visualStatePromptIsCurrent(base), true);
  const off = { ...base, visual_state_reference_config: { enabled_state_ids: [] } };
  assert.equal(visualStatePromptIsCurrent(off), false);
  const projection = { disabled_visual_state_ids: ['KF9','KF10','KF11','KF12'] };
  assert.equal(visualStatePromptIsCurrent({ ...off, prompt_projection: projection }), true);
  assert.equal(visualStatePromptIsCurrent({ ...base, prompt_projection: projection }), false);
});

test('save API transmits empty list unchanged and surfaces persistence failures', async () => {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => { calls.push([url, options]); return { ok: true, json: async () => ({ success: true, data: { id: 'shot' } }) }; };
  try {
    await shotsApi.saveClipVisualStateReferences('novel', 'chapter', 'shot', 6, [], 2);
    assert.ok(calls[0][0].endsWith('/clips/6/visual-state-references'));
    assert.equal(calls[0][1].method, 'PATCH');
    assert.deepEqual(JSON.parse(calls[0][1].body), { enabled_state_ids: [], expected_plan_revision: 2 });
    globalThis.fetch = async () => ({ ok: false, json: async () => ({ detail: '视频生成中' }) });
    await assert.rejects(shotsApi.saveClipVisualStateReferences('novel','chapter','shot',6,[],2), /视频生成中/);
  } finally { globalThis.fetch = original; }
});
