import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';

const source = await readFile(new URL('../src/pages/LLMLogs/components/ImageInputs.tsx', import.meta.url), 'utf8');
const js = ts.transpileModule(source.replace(/^import[^;]+;\s*/gm, '').replace(/^export /gm, ''), {
  compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.None, jsx: ts.JsxEmit.React },
}).outputText;
function harness(images, secure = true) {
  const state = [], copied = [], notices = [];
  let cursor = 0, removed = false;
  const textarea = { value: '', style: {}, select() {}, remove() { removed = true; } };
  const useState = initial => {
    const i = cursor++;
    if (!(i in state)) state[i] = initial;
    return [state[i], next => { state[i] = typeof next === 'function' ? next(state[i]) : next; }];
  };
  const module = new Function('React', 'useState', 'useEffect', 'toast', 'navigator', 'window', 'document', `${js}; return {ImageInputs, imageInputSummary};`)(
    React, useState, () => {}, { success: s => notices.push(s), error: s => notices.push(s) },
    { clipboard: { writeText: async value => copied.push(value) } }, { isSecureContext: secure },
    { createElement: () => textarea, body: { appendChild() {} }, execCommand: () => { copied.push(textarea.value); return true; } },
  );
  return { ...module, copied, notices, removed: () => removed, render: () => { cursor = 0; return module.ImageInputs({ images }); } };
}
function nodes(element, predicate) {
  if (!React.isValidElement(element)) return [];
  return [...(predicate(element) ? [element] : []), ...React.Children.toArray(element.props.children).flatMap(child => nodes(child, predicate))];
}
function button(tree, label, index = 0) {
  return nodes(tree, e => e.type === 'button' && e.props.children === label)[index];
}
const records = [
  { request_order: 1, logical_id: 'GENERATED_OUTPUT', name: '实际生成图', submitted_url: '/result.jpg', source_dimensions: [1088, 704], size_bytes: 1536 },
  { request_order: 2, logical_id: 'Picture1', reference_type: 'TEMPORAL_ANCHOR', binding: { picture: 1, sources: ['KF4'], node_id: '470' }, submitted_url: '/anchor.jpg' },
  { request_order: 3, logical_id: 'Picture2', reference_type: 'CHARACTER_IDENTITY', binding: { sources: ['CHAR:18d390dc-ae72-43d2-ad1d-aa5ba5721a56'], character_ids: ['id'], sha256: 'a'.repeat(64) }, source_dimensions: [1118, 2274], submitted_url: '/portrait.jpg', size_bytes: 2 * 1024 * 1024, extra_debug: { unknown_field: 'retained' } },
  { request_order: 4, logical_id: 'Picture3', reference: JSON.stringify({ reference_type: 'SCENE', sources: ['SCENE:王宫宫门'] }), submitted_url: '/scene.jpg' },
  { request_order: 5, logical_id: 'Picture4', reference_type: 'PROP', sources: ['PROP:宽边礼帽'], submitted_url: '/hat.jpg' },
  { request_order: 6, logical_id: 'Picture5', reference: 'invalid JSON: { source', status: 'unavailable', unavailable_reason: 'missing asset' },
];

test('six cards retain input order and show concise metadata without raw JSON', () => {
  const before = structuredClone(records), h = harness(records), tree = h.render();
  const cards = nodes(tree, e => e.type === 'article');
  assert.equal(cards.length, 6);
  assert.deepEqual(cards.map(c => nodes(c, e => e.type === 'h4')[0].props.children), ['GENERATED_OUTPUT', 'Picture 1', 'Picture 2', 'Picture 3', 'Picture 4', 'Picture 5']);
  const html = renderToStaticMarkup(tree);
  for (const name of ['实际生成图', 'KF4', '角色身份参考 · 1 个来源', '王宫宫门', '宽边礼帽', '1118 × 2274', '文件大小：1.5 KB', '文件大小：2 MB', '文件大小：未知']) assert.ok(html.includes(name), name);
  assert.doesNotMatch(html, /node_id|sha256|character_ids|extra_debug|invalid JSON/);
  assert.deepEqual(records, before);
});

test('object and JSON string references are read-only views with identical summaries', () => {
  const h = harness([]), reference = { picture: 4, reference_type: 'SCENE', sources: ['SCENE:书房'] };
  const object = { reference, source_dimensions: [800, 400] };
  assert.deepEqual(h.imageInputSummary(object, 0), h.imageInputSummary({ ...object, reference: JSON.stringify(reference) }, 0));
  assert.deepEqual(h.imageInputSummary(object, 0), { label: 'Picture 4', referenceType: 'SCENE', source: '书房', sourceSize: '800 × 400', fileSize: '未知' });
});

test('legacy no-reference records and malformed strings remain usable without invented dimensions', () => {
  const h = harness([]);
  for (const reference of [undefined, null, '', 'not JSON', 'null', '[]']) {
    const summary = h.imageInputSummary({ reference, submitted_dimensions: [400, 200] }, 0);
    assert.equal(summary.label, '图片输入 1');
    assert.equal(summary.source, '未提供来源名称');
    assert.equal(summary.sourceSize, '未知');
    assert.equal(summary.fileSize, '未知');
  }
  assert.equal(h.imageInputSummary({ binding: '{"picture":8,"filename":"/full/path/scene.png"}' }, 0).source, 'scene.png');
  assert.equal(h.imageInputSummary({ size_bytes: 0 }, 0).fileSize, '0 B');
  assert.equal(h.imageInputSummary({ size_bytes: 1024 }, 0).fileSize, '1 KB');
  assert.equal(h.imageInputSummary({ size_bytes: -1 }, 0).fileSize, '未知');
});

test('raw view and copy retain every original field, including JSON and invalid string values', async () => {
  for (const [i, record] of records.entries()) {
    const h = harness(records);
    button(h.render(), '查看原始信息', i).props.onClick();
    const tree = h.render(), pre = nodes(tree, e => e.type === 'pre')[0];
    assert.equal(pre.props.children, JSON.stringify(record, null, 2));
    assert.deepEqual(JSON.parse(pre.props.children), record);
    await button(tree, '复制完整 JSON').props.onClick();
    assert.deepEqual(h.copied, [JSON.stringify(record, null, 2)]);
    assert.deepEqual(h.notices, ['已复制完整 JSON']);
  }
});

test('LAN insecure-context copy fallback preserves full JSON and removes temporary textarea', async () => {
  const h = harness(records, false);
  button(h.render(), '查看原始信息', 2).props.onClick();
  await button(h.render(), '复制完整 JSON').props.onClick();
  assert.equal(h.copied[0], JSON.stringify(records[2], null, 2));
  assert.equal(h.removed(), true);
});

test('gallery navigation preserves order and exposes unavailable and failed previews', () => {
  const h = harness(records);
  button(h.render(), '查看大图', 2).props.onClick();
  let tree = h.render();
  assert.match(renderToStaticMarkup(tree), /aria-label="图片预览"/);
  button(tree, '下一张').props.onClick();
  tree = h.render();
  const dialog = nodes(tree, e => e.props['aria-label'] === '图片预览')[0];
  assert.equal(nodes(dialog, e => e.type === 'img')[0].props.alt, 'Picture 3');
  nodes(dialog, e => e.type === 'img')[0].props.onError();
  assert.match(renderToStaticMarkup(h.render()), /图片不可用或链接已失效/);
  button(h.render(), '查看大图', 5).props.onClick();
  assert.match(renderToStaticMarkup(h.render()), /图片无法加载.*missing asset/);
  const close = nodes(h.render(), e => e.props['aria-label'] === '关闭图片预览')[0];
  close.props.onClick();
  assert.equal(nodes(h.render(), e => e.props.role === 'dialog').length, 0);
});

test('image-only single records and empty image arrays render safely', () => {
  assert.equal(nodes(harness([]).render(), e => e.type === 'article').length, 0);
  const tree = harness([{ submitted_url: '/square.png' }]).render();
  assert.equal(nodes(tree, e => e.type === 'article').length, 1);
  assert.match(renderToStaticMarkup(tree), /图片输入 1/);
});
