import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { create } from 'zustand';
import ts from 'typescript';

const source = await readFile(new URL('../src/stores/configStore.ts', import.meta.url), 'utf8');
const js = ts.transpileModule(source
  .replace(/^import[\s\S]*?;\s*/gm, '')
  .replace(/^const API_BASE = .*;$/m, "const API_BASE = '/api';")
  .replace('export const useConfigStore', 'const useConfigStore')
  .replace(/^export \{[\s\S]*?\};\s*$/m, ''), {
  compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.None },
}).outputText;
const factory = new Function('create', 'DEFAULT_CONFIG', 'LLM_PROVIDER_PRESETS', 'fetch', 'console', `${js}; return useConfigStore;`);
const defaults = { llmProvider: 'custom', llmModel: 'test-model', comfyUIHost: 'http://comfyui', proxy: { enabled: false } };
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const makeStore = fetch => factory(create, defaults, [], fetch, { log() {}, error() {} });

test('StrictMode-style overlapping config loads issue one request and reuse loaded data', async () => {
  const pending = deferred(), urls = [];
  const store = makeStore(url => { urls.push(url); return pending.promise; });
  const first = store.getState().loadConfig();
  const repeated = store.getState().loadConfig();
  assert.deepEqual(urls, ['/api/config/']);
  pending.resolve({ json: async () => ({ success: true, data: { llmProvider: 'custom', llmModel: 'loaded-model' } }) });
  assert.deepEqual(await first, await repeated);
  assert.equal(store.getState().isLoaded, true);
  assert.equal((await store.getState().loadConfig()).llmModel, 'loaded-model');
  assert.equal(urls.length, 1);
});

test('overlapping automatic and manual checks share one LLM and one ComfyUI request without redirects', async () => {
  const llm = deferred(), comfyui = deferred(), urls = [];
  const store = makeStore(url => { urls.push(url); return url.endsWith('/llm') ? llm.promise : comfyui.promise; });
  const first = store.getState().checkConnection();
  const repeated = store.getState().checkConnection();
  assert.equal(first, repeated);
  assert.deepEqual(urls, ['/api/health/llm', '/api/health/comfyui']);
  assert.equal(store.getState().isLoading, true);
  comfyui.resolve({ ok: true });
  await Promise.resolve();
  assert.equal(store.getState().isLoading, true);
  llm.resolve({ ok: true });
  assert.deepEqual(await first, { llm: true, comfyui: true });
  assert.equal(store.getState().isLoading, false);
});

test('a later refresh performs new checks instead of caching old connection status', async () => {
  const urls = [];
  const store = makeStore(async url => { urls.push(url); return { ok: true }; });
  await store.getState().checkConnection();
  await store.getState().checkConnection();
  assert.deepEqual(urls, ['/api/health/llm', '/api/health/comfyui', '/api/health/llm', '/api/health/comfyui']);
});

test('one failed service does not suppress the other result, and subsequent checks can retry', async () => {
  let failing = true;
  const store = makeStore(async url => {
    if (url.endsWith('/llm') && failing) throw new Error('network failed');
    return { ok: true };
  });
  assert.deepEqual(await store.getState().checkConnection(), { llm: false, comfyui: true });
  assert.equal(store.getState().isLoading, false);
  assert.equal(store.getState().error, '连接检查失败');
  failing = false;
  assert.deepEqual(await store.getState().checkConnection(), { llm: true, comfyui: true });
  assert.equal(store.getState().error, null);
});

test('HTTP failure is shown as disconnected without affecting the healthy service', async () => {
  const store = makeStore(async url => ({ ok: !url.endsWith('/comfyui') }));
  assert.deepEqual(await store.getState().checkConnection(), { llm: true, comfyui: false });
  assert.equal(store.getState().isLoading, false);
});
