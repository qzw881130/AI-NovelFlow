import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import React from 'react';
import ts from 'typescript';

const source = await readFile(new URL('../src/pages/LLMLogs/components/LogDetailModal.tsx', import.meta.url), 'utf8');
const js = ts.transpileModule(source.replace(/^import[^;]+;\s*/gm, '').replace(/^export /gm, ''), {
  compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.None, jsx: ts.JsxEmit.React },
}).outputText;

const noop = () => null;
function createHarness(log, tab = 'user') {
  let state;
  const copied = [];
  const Modal = new Function(
    'React', 'useState', 'ImageInputs', 'H3AVTimeline', 'Copy', 'Download', 'X', 'ProviderLogo',
    'useTranslation', 'toast', 'chapterLabel', 'navigator', 'window', `${js}; return LogDetailModal;`,
  )(
    React, initial => [state ?? initial, value => { state = value; }], noop, noop, noop, noop, noop, noop,
    () => ({ t: key => ({ 'llmLogs.prettyJson': '美化 JSON', 'llmLogs.showRawJson': '显示原文' })[key] ?? key }),
    { success: noop, error: noop }, noop,
    { clipboard: { writeText: async value => copied.push(value) } }, { isSecureContext: true },
  );
  const render = () => Modal({
    log, activeTab: tab, onTabChange: next => { tab = next; }, onClose: noop,
    formatDate: value => value, getTaskTypeLabel: noop, getDisplayDuration: noop,
    getStatusBadgeConfig: () => ({ bg: '', text: '', label: '' }),
  });
  return { render, copied, setTab: value => { tab = value; }, setLog: value => { log = value; } };
}

function nodes(element, predicate) {
  if (!React.isValidElement(element)) return [];
  return [...(predicate(element) ? [element] : []), ...React.Children.toArray(element.props.children).flatMap(child => nodes(child, predicate))];
}
const button = (tree, label) => nodes(tree, element => element.type === 'button' && element.props.children === label)[0];
const content = tree => nodes(tree, element => element.type === 'pre')[0].props.children;
const log = { id: 'log-1', created_at: '', status: 'success', user_prompt: '{"a":1,"b":[2,3]}', response: '[1,2]', request_info: '{}', image_inputs: [] };

test('valid JSON is formatted on click and original content can be restored', async () => {
  const harness = createHarness(log);
  assert.equal(content(harness.render()), log.user_prompt);
  button(harness.render(), '美化 JSON').props.onClick();
  assert.equal(content(harness.render()), JSON.stringify(JSON.parse(log.user_prompt), null, 2));
  assert.equal(button(harness.render(), '显示原文').props['aria-pressed'], true);
  await nodes(harness.render(), element => element.type === 'button' && element.props['aria-label'] === 'common.copy')[0].props.onClick();
  assert.deepEqual(harness.copied, [log.user_prompt]);
  button(harness.render(), '显示原文').props.onClick();
  assert.equal(content(harness.render()), log.user_prompt);
});

test('invalid JSON has no format button and formatting does not carry to another tab or log', () => {
  const harness = createHarness(log);
  button(harness.render(), '美化 JSON').props.onClick();
  harness.setTab('response');
  assert.equal(content(harness.render()), '[1,2]');
  assert.ok(button(harness.render(), '美化 JSON'));
  harness.setTab('system');
  assert.equal(button(harness.render(), '美化 JSON'), undefined);
  harness.setTab('user');
  harness.setLog({ ...log, id: 'log-2', user_prompt: '{broken json' });
  assert.equal(content(harness.render()), '{broken json');
  assert.equal(button(harness.render(), '美化 JSON'), undefined);
});
