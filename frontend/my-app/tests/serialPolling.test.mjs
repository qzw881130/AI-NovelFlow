import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from '../node_modules/typescript/lib/typescript.js';

const source = await readFile(new URL('../src/hooks/useSerialPolling.ts', import.meta.url), 'utf8');
const js = ts.transpileModule(source.split('export function useSerialPolling')[0].replace(/^import .*;$/m, ''), {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
}).outputText;
const { createSerialPoller } = await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };

function harness() {
  const original = { document: globalThis.document, setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout };
  const document = new EventTarget();
  document.hidden = false;
  globalThis.document = document;
  const timers = new Map();
  let now = 0, id = 0;
  globalThis.setTimeout = (fn, ms) => { timers.set(++id, { fn, due: now + ms }); return id; };
  globalThis.clearTimeout = key => timers.delete(key);
  const requests = [], values = [], errors = [];
  let settled = 0;
  const poller = createSerialPoller({
    intervalMs: 3000, timeoutMs: 15000,
    fetch: signal => new Promise((resolve, reject) => {
      requests.push({ signal, resolve, reject });
      signal.addEventListener('abort', () => reject(new Error('aborted')), { once: true });
    }),
    onSuccess: value => values.push(value), onError: error => errors.push(error), onSettled: () => settled++,
  });
  return {
    poller, requests, values, errors, settled: () => settled,
    advance: async ms => {
      now += ms;
      for (const [key, timer] of [...timers]) if (timer.due <= now && timers.has(key)) {
        timers.delete(key); timer.fn();
      }
      await flush();
    },
    visibility: async hidden => { document.hidden = hidden; document.dispatchEvent(new Event('visibilitychange')); await flush(); },
    restore: () => { poller.stop(); Object.assign(globalThis, original); },
  };
}

test('slow API and manual refreshes share one request, then wait a full interval', async () => {
  const h = harness();
  try {
    await flush();
    await h.advance(10000);
    const manual = h.poller.refresh();
    const repeated = h.poller.refresh();
    assert.equal(manual, repeated);
    assert.equal(h.requests.length, 1);
    h.requests[0].resolve('first');
    await manual;
    await h.advance(2999);
    assert.equal(h.requests.length, 1);
    await h.advance(1);
    assert.equal(h.requests.length, 2);
    assert.deepEqual(h.values, ['first']);
  } finally { h.restore(); }
});

test('timeout aborts the request, settles loading and permits the next poll', async () => {
  const h = harness();
  try {
    await flush();
    await h.advance(15000);
    assert.equal(h.requests[0].signal.aborted, true);
    assert.equal(h.errors.length, 1);
    assert.equal(h.settled(), 1);
    await h.advance(3000);
    assert.equal(h.requests.length, 2);
  } finally { h.restore(); }
});

test('hidden pages stop requests and resume when visible', async () => {
  const h = harness();
  try {
    await flush();
    await h.visibility(true);
    assert.equal(h.requests[0].signal.aborted, true);
    assert.equal(h.errors.length, 0);
    await h.advance(30000);
    assert.equal(h.requests.length, 1);
    await h.visibility(false);
    assert.equal(h.requests.length, 2);
  } finally { h.restore(); }
});

test('unmount aborts in-flight requests without stale updates or new timers', async () => {
  const h = harness();
  try {
    await flush();
    h.poller.stop();
    h.requests[0].resolve('stale');
    await flush();
    await h.advance(30000);
    assert.equal(h.requests[0].signal.aborted, true);
    assert.equal(h.requests.length, 1);
    assert.deepEqual(h.values, []);
    assert.equal(h.settled(), 0);
  } finally { h.restore(); }
});

test('API failures settle and retry rather than killing polling', async () => {
  const h = harness();
  try {
    await flush();
    h.requests[0].reject(new Error('network failed'));
    await flush();
    assert.equal(h.errors.length, 1);
    await h.advance(3000);
    h.requests[1].resolve('recovered');
    await flush();
    assert.deepEqual(h.values, ['recovered']);
    assert.equal(h.settled(), 2);
  } finally { h.restore(); }
});
