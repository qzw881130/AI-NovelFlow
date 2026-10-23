import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from '../node_modules/typescript/lib/typescript.js';

globalThis.fetch = async () => assert.fail('Unexpected real frontend network request');

const selectionSource = await readFile(new URL('../src/pages/LLMLogs/selection.ts', import.meta.url), 'utf8');
const selectionJs = ts.transpileModule(selectionSource, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { getTerminableLogIds } = await import(`data:text/javascript;base64,${Buffer.from(selectionJs).toString('base64')}`);
const component = await readFile(new URL('../src/pages/LLMLogs/index.tsx', import.meta.url), 'utf8');
const apiSource = await readFile(new URL('../src/api/llmLogs.ts', import.meta.url), 'utf8');
const hook = await readFile(new URL('../src/pages/LLMLogs/hooks/useLLMLogsState.ts', import.meta.url), 'utf8');
const apiJs = ts.transpileModule(apiSource.replace("import { api, API_BASE } from './index';", "const api = {}; const API_BASE = '/api';"), { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { llmLogsApi } = await import(`data:text/javascript;base64,${Buffer.from(apiJs).toString('base64')}`);

test('empty or completed-only selections cannot terminate', () => {
  assert.deepEqual(getTerminableLogIds(new Set(), [{ id: 'running', status: 'pending' }]), []);
  assert.deepEqual(getTerminableLogIds(new Set(['done', 'failed']), [{ id: 'done', status: 'success' }, { id: 'failed', status: 'error' }]), []);
});

test('only selected pending calls and off-page selections go to backend validation', () => {
  assert.deepEqual(getTerminableLogIds(new Set(['running', 'done', 'off-page']), [
    { id: 'running', status: 'pending' }, { id: 'other', status: 'pending' }, { id: 'done', status: 'success' },
  ]), ['running', 'off-page']);
});

test('confirmation, in-flight guard, scoped clearing, and refresh are wired', () => {
  assert.match(component, /window\.confirm\('确定终止所选日志中的进行中任务吗/);
  assert.match(component, /disabled=\{!terminableIds\.length \|\| isTerminating\}/);
  assert.match(component, /terminationInFlight\.current\) return/);
  assert.match(component, /llmLogsApi\.cancelSelected\(ids\)/);
  assert.match(component, /filter\(id => !cancelled\.has\(id\)\)/);
  assert.match(component, /await state\.fetchLogs\(\{ silent: true \}\)/);
  assert.match(component, /'终止中\.\.\.' : '终止任务'/);
  assert.match(hook, /errorMessage === LLM_CANCELLED_MESSAGE[\s\S]*label: '已终止'/);
});

test('API sends exact selected IDs and returns termination result', async () => {
  const original = globalThis.fetch;
  try {
    let sent;
    globalThis.fetch = async (url, options) => {
      sent = { url, ...options };
      return { ok: true, json: async () => ({ success: true, data: { cancelled_ids: ['running'], skipped_ids: [] } }) };
    };
    assert.deepEqual(await llmLogsApi.cancelSelected(['running']), { cancelled_ids: ['running'], skipped_ids: [] });
    assert.equal(sent.url, '/api/llm-logs/cancel-selected');
    assert.equal(sent.method, 'POST');
    assert.deepEqual(JSON.parse(sent.body), { ids: ['running'] });
  } finally { globalThis.fetch = original; }
});

test('API errors surface rather than report successful termination', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => ({ ok: false, json: async () => ({ detail: '所选日志不存在' }) });
    await assert.rejects(llmLogsApi.cancelSelected(['missing']), /所选日志不存在/);
  } finally { globalThis.fetch = original; }
});

// Execute the actual event handler with mocked API/UI boundaries.
let terminateInitializer;
const componentAst = ts.createSourceFile('index.tsx', component, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
function findHandler(node) {
  if (ts.isVariableDeclaration(node) && node.name.getText(componentAst) === 'terminateSelected') {
    terminateInitializer = node.initializer.getText(componentAst);
  }
  ts.forEachChild(node, findHandler);
}
findHandler(componentAst);
assert.ok(terminateInitializer);
const handlerJs = ts.transpileModule(`const terminateSelected = ${terminateInitializer};`, {
  compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext },
}).outputText;
const handlerFactory = new Function('terminableIds', 'terminationInFlight', 'setIsTerminating', 'window',
  'llmLogsApi', 'setSelectedIds', 'toast', 'state', `${handlerJs}\nreturn terminateSelected;`);
function eventHarness(ids, cancelSelected) {
  let selection = new Set(ids);
  const feedback = [], busy = [], refreshes = [];
  const ref = { current: false };
  const handler = handlerFactory(ids, ref, value => busy.push(value), { confirm: () => true },
    { cancelSelected }, update => { selection = update(selection); },
    { success: message => feedback.push(message), error: message => feedback.push(message) },
    { fetchLogs: async options => refreshes.push(options) });
  return { handler, ref, feedback, busy, refreshes, selection: () => selection,
    select: ids => { selection = new Set(ids); } };
}

test('partial cancellation reports skipped IDs and clears only confirmed cancellations', async () => {
  let sent;
  const harness = eventHarness(['A', 'B'], async ids => {
    sent = ids;
    return { cancelled_ids: ['A'], skipped_ids: ['B'] };
  });
  await harness.handler();
  assert.deepEqual(sent, ['A', 'B']);
  assert.deepEqual([...harness.selection()], ['B']);
  assert.match(harness.feedback[0], /已终止 1/);
  assert.match(harness.feedback[0], /1.*(?:已结束|已终止|跳过)/);
  assert.deepEqual(harness.refreshes, [{ silent: true }]);
  assert.equal(harness.ref.current, false);
  assert.deepEqual(harness.busy, [true, false]);
});

test('in-flight cancellation retains captured IDs and preserves a newer selection', async () => {
  let release, sent;
  const ids = ['A'];
  const harness = eventHarness(ids, async captured => {
    sent = captured;
    return await new Promise(resolve => { release = resolve; });
  });
  const first = harness.handler();
  ids.push('not-originally-selected');
  harness.select(['B']);
  await harness.handler();
  assert.deepEqual(sent, ['A']);
  release({ cancelled_ids: ['A'], skipped_ids: [] });
  await first;
  assert.deepEqual([...harness.selection()], ['B']);
  assert.equal(harness.refreshes.length, 1);
});

test('failed cancellation leaves selection unchanged and refreshes backend authority', async () => {
  const harness = eventHarness(['A'], async () => { throw new Error('cancel failed'); });
  await harness.handler();
  assert.deepEqual([...harness.selection()], ['A']);
  assert.deepEqual(harness.feedback, ['cancel failed']);
  assert.deepEqual(harness.refreshes, [{ silent: true }]);
  assert.equal(harness.ref.current, false);
});

test('no cancellable targets makes no request or local cancelled state', async () => {
  const harness = eventHarness([], async () => assert.fail('unexpected cancellation request'));
  await harness.handler();
  assert.deepEqual(harness.busy, []);
  assert.deepEqual(harness.refreshes, []);
});

// Run the actual state hook with minimal hook storage; effects/network are mocked.
const hookJs = ts.transpileModule(hook.replace(/^import .*;\r?$/gm, '').replace(/^export type .*;\r?$/gm, '').replace('export function useLLMLogsState', 'function useLLMLogsState'), {
  compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext },
}).outputText;
const hookFactory = new Function('useState', 'useEffect', 'useCallback', 'useRef', 'toast', 'useTranslation',
  'llmLogsApi', 'LLM_CANCELLED_MESSAGE', `${hookJs}\nreturn useLLMLogsState;`);
function stateHarness(api) {
  const slots = [];
  let index = 0;
  const useState = initial => {
    const slot = index++;
    if (!(slot in slots)) slots[slot] = typeof initial === 'function' ? initial() : initial;
    return [slots[slot], next => { slots[slot] = typeof next === 'function' ? next(slots[slot]) : next; }];
  };
  const useRef = initial => {
    const slot = index++;
    if (!(slot in slots)) slots[slot] = { current: initial };
    return slots[slot];
  };
  const stateHook = hookFactory(useState, () => {}, callback => callback, useRef,
    { error: () => {} }, () => ({ t: key => key, i18n: { timezone: 'Asia/Shanghai' } }),
    api, '任务被用户取消，LLM 响应已忽略');
  return { render: () => { index = 0; return stateHook(); } };
}

test('refresh renders backend cancelled state distinctly from ordinary error', async () => {
  let items = [{ id: 'A', status: 'pending' }];
  const harness = stateHarness({ fetchList: async () => ({ success: true, data: {
    items, pagination: { page: 1, page_size: 20, total: items.length, total_pages: 1 },
  } }) });
  await harness.render().fetchLogs({ silent: true });
  assert.deepEqual(getTerminableLogIds(new Set(['A']), harness.render().logs), ['A']);
  items = [{ id: 'A', status: 'error', error_message: '任务被用户取消，LLM 响应已忽略' },
    { id: 'B', status: 'error', error_message: 'ordinary network failure' }];
  await harness.render().fetchLogs({ silent: true });
  const state = harness.render();
  assert.deepEqual(state.logs, items);
  assert.deepEqual(getTerminableLogIds(new Set(['A', 'B']), state.logs), []);
  assert.equal(state.getStatusBadgeConfig('error', items[0].error_message).label, '已终止');
  assert.equal(state.getStatusBadgeConfig('error', items[1].error_message).label, 'common.failed');
});

test('a stale refresh response cannot overwrite a newer backend cancellation result', async () => {
  const releases = [];
  const harness = stateHarness({ fetchList: async () => await new Promise(resolve => releases.push(resolve)) });
  const state = harness.render();
  const old = state.fetchLogs({ silent: true });
  const newer = state.fetchLogs({ silent: true });
  const envelope = items => ({ success: true, data: { items, pagination: {
    page: 1, page_size: 20, total: items.length, total_pages: 1,
  } } });
  releases[1](envelope([{ id: 'A', status: 'error', error_message: '任务被用户取消，LLM 响应已忽略' }]));
  await newer;
  releases[0](envelope([{ id: 'A', status: 'pending' }]));
  await old;
  assert.equal(harness.render().logs[0].status, 'error');
});

const listEnvelope = items => ({ success: true, data: { items, pagination: {
  page: 1, page_size: 20, total: items.length, total_pages: 1,
} } });

test('silent polling releases the spinner when it supersedes a slow initial load', async () => {
  const releases = [];
  const harness = stateHarness({ fetchList: () => new Promise(resolve => releases.push(resolve)) });
  const initial = harness.render().fetchLogs();
  const refresh = harness.render().fetchLogs({ silent: true });
  releases[0](listEnvelope([{ id: 'old' }]));
  await initial;
  assert.equal(harness.render().loading, true);
  releases[1](listEnvelope([{ id: 'new' }]));
  await refresh;
  assert.equal(harness.render().loading, false);
  assert.equal(harness.render().logs[0].id, 'new');
});

test('a slow initial response cannot restore stale rows after polling finishes', async () => {
  const releases = [];
  const harness = stateHarness({ fetchList: () => new Promise(resolve => releases.push(resolve)) });
  const initial = harness.render().fetchLogs();
  const refresh = harness.render().fetchLogs({ silent: true });
  releases[1](listEnvelope([{ id: 'new' }]));
  await refresh;
  releases[0](listEnvelope([{ id: 'old' }]));
  await initial;
  assert.equal(harness.render().loading, false);
  assert.equal(harness.render().logs[0].id, 'new');
});

test('failed polling releases a superseded foreground spinner', async () => {
  const requests = [];
  const harness = stateHarness({ fetchList: () => new Promise((resolve, reject) => requests.push({ resolve, reject })) });
  const initial = harness.render().fetchLogs();
  const refresh = harness.render().fetchLogs({ silent: true });
  requests[1].reject(new Error('polling failed'));
  await refresh;
  assert.equal(harness.render().loading, false);
  requests[0].resolve(listEnvelope([{ id: 'old' }]));
  await initial;
  assert.deepEqual(harness.render().logs, []);
});

test('stale polling cannot dismiss a newer foreground spinner', async () => {
  const releases = [];
  const harness = stateHarness({ fetchList: () => new Promise(resolve => releases.push(resolve)) });
  const initial = harness.render().fetchLogs();
  releases[0](listEnvelope([{ id: 'initial' }]));
  await initial;
  const refresh = harness.render().fetchLogs({ silent: true });
  assert.equal(harness.render().loading, false);
  const foreground = harness.render().fetchLogs();
  releases[1](listEnvelope([{ id: 'stale' }]));
  await refresh;
  assert.equal(harness.render().loading, true);
  assert.equal(harness.render().logs[0].id, 'initial');
  releases[2](listEnvelope([{ id: 'foreground' }]));
  await foreground;
  assert.equal(harness.render().loading, false);
  assert.equal(harness.render().logs[0].id, 'foreground');
});
