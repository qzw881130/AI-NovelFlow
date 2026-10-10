import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile, writeFile, mkdir, mkdtemp, rm } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const root = fileURLToPath(new URL('../', import.meta.url));
const sourceDir = path.join(root, 'src/pages/ClipExecutionInspector');
const fixture = JSON.parse(await readFile(new URL('./fixtures/clip-execution-inspector-c2.json', import.meta.url), 'utf8'));
const fixtureB = JSON.parse(await readFile(new URL('./fixtures/clip-execution-inspector-c2-exec-b.json', import.meta.url), 'utf8'));
const completedResults = JSON.parse(await readFile(new URL('./fixtures/clip-execution-inspector-c2-results.json', import.meta.url), 'utf8'));
// Compile actual components with the project's existing TypeScript/React packages.
// Only the global locale/config store is replaced for this isolated SSR test environment.
const temp = await mkdtemp(path.join(root, 'node_modules/.cei-test-'));
async function compile(relative) {
  const source = await readFile(path.join(root, 'src', relative), 'utf8');
  const { outputText } = ts.transpileModule(source.replaceAll('import.meta.env.VITE_API_URL', 'undefined'), {
    fileName: relative,
    compilerOptions: { module: ts.ModuleKind.ES2020, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  });
  const dest = path.join(temp, relative.replace(/\.tsx?$/, '.js'));
  await mkdir(path.dirname(dest), { recursive: true });
  const imports = outputText.replace(/(from\s+['"])(\.[^'"]+)(['"])/g, '$1$2.js$3');
  await writeFile(dest, imports);
}
for (const name of ['presentation.ts', 'labels.ts', 'contactSheet.ts', 'components/ContactSheetModal.tsx', 'components/ExecutionIdentity.tsx', 'components/ClipSummary.tsx', 'components/UnifiedTimeline.tsx', 'components/Filmstrip.tsx', 'components/FrameInspector.tsx', 'components/PromptAuthorityPanel.tsx', 'components/ObservationEditor.tsx']) {
  await compile(`pages/ClipExecutionInspector/${name}`);
}
await compile('api/clipExecutionInspector.ts');
await compile('api/index.ts');
await compile('pages/ClipExecutionInspector/useClipExecutionInspector.ts');
const hookPath = path.join(temp, 'pages/ClipExecutionInspector/useClipExecutionInspector.js');
await writeFile(hookPath, (await readFile(hookPath, 'utf8')).replace("from 'react'", "from './hookReact.js'"));
// Exercise effect replay and durable URL changes against the actual async hook,
// using controlled hook storage without adding a DOM/testing dependency.
await writeFile(path.join(temp, 'pages/ClipExecutionInspector/hookReact.js'), `
let slots = [], cursor = 0, effects = [];
export function begin() { cursor = 0; effects = []; }
export function setups() { return effects; }
export function useState(initial) {
  const index = cursor++;
  if (!(index in slots)) slots[index] = initial;
  return [slots[index], value => { slots[index] = typeof value === 'function' ? value(slots[index]) : value; }];
}
export function useRef(initial) {
  const index = cursor++;
  if (!(index in slots)) slots[index] = { current: initial };
  return slots[index];
}
export function useCallback(callback) { return callback; }
export function useEffect(setup) { effects.push(setup); }
`);
await mkdir(path.join(temp, 'stores'), { recursive: true });
await writeFile(path.join(temp, 'stores/i18nStore.js'), `export const useI18nStore = (selector) => { const state = { language: 'zh-CN', timezone: 'Asia/Shanghai' }; return selector ? selector(state) : state; };`);
async function load(file) { return import(pathToFileURL(path.join(temp, file)).href); }
const { inspectorEntry, expectedAtTime, nativeFrameSample, observationsForFrame, TRACKS } = await load('pages/ClipExecutionInspector/presentation.js');
const { default: ClipSummary } = await load('pages/ClipExecutionInspector/components/ClipSummary.js');
const { default: UnifiedTimeline } = await load('pages/ClipExecutionInspector/components/UnifiedTimeline.js');
const { default: Filmstrip } = await load('pages/ClipExecutionInspector/components/Filmstrip.js');
const { default: FrameInspector, NativeAVPlayback } = await load('pages/ClipExecutionInspector/components/FrameInspector.js');
const { ExecutionResultOptions } = await load('pages/ClipExecutionInspector/components/ExecutionIdentity.js');
const { default: ObservationEditor } = await load('pages/ClipExecutionInspector/components/ObservationEditor.js');
const { loadContactSheet } = await load('pages/ClipExecutionInspector/contactSheet.js');
const { ContactSheetGrid } = await load('pages/ClipExecutionInspector/components/ContactSheetModal.js');
const { inspectorApi } = await load('api/clipExecutionInspector.js');
const render = (component, props) => renderToStaticMarkup(React.createElement(component, props));
test.after(async () => { await rm(temp, { recursive: true, force: true }); });

test('completed Clip entry locks exact task; pending/missing results are not enabled', async () => {
  assert.match(inspectorEntry({ id: 'completed', status: 'completed', resultUrl: '/api/files/c2.mp4' }, {}, '/novels/n'), /^\/clip-execution-inspector\/completed\?returnTo=/);
  assert.equal(inspectorEntry({ id: 'pending', status: 'running' }, {}, '/novels/n'), null);
  assert.equal(inspectorEntry(undefined, {}, '/novels/n'), null);
  assert.match(inspectorEntry(undefined, { generated_by_task_id: 'historical', video_url: '/api/files/history.mp4' }, '/novels/n'), /historical/);
  const wiring = await readFile(path.join(root, 'src/pages/ChapterGenerate/components/VideoGenTab.tsx'), 'utf8');
  assert.match(wiring, /clip-execution-inspector-entry/);
  assert.match(wiring, /inspectorEntry\(task, clip/);
  assert.match(await readFile(path.join(root, 'src/App.tsx'), 'utf8'), /clip-execution-inspector\/:taskId/);
});

test('Summary keeps requested, finalized replacement, and whole Native frame counts distinct', () => {
  const html = render(ClipSummary, { projection: fixture });
  for (const text of ['277', '274', '529', 'TEMPORAL_EXTEND', 'position1 206', '8.541667s', '5.4s', 'CURRENT_PLAN', 'EXECUTION_SNAPSHOT', 'FINAL_PROMPT']) assert.ok(html.includes(text), text);
  assert.ok(html.includes('255'));
  assert.ok(html.includes('22.167s'));
});

test('Timeline renders separate semantic/physical tracks and exact dialogue ranges', () => {
  const html = render(UnifiedTimeline, { projection: fixture, time: 4.5, observations: [], onEvent() {}, onObservation() {} });
  for (const track of TRACKS) assert.ok(html.includes(`track-${track}`));
  assert.match(html, /Semantic KF3/);
  assert.match(html, /position1 206/);
  for (const t of ['0.1s', '5.35s', '5.55s', '8.3s', '8.5s', '11s']) assert.ok(html.includes(t));
  assert.ok(html.includes('侍从2') && html.includes('宫廷总管') && html.includes('皇帝'));
});

test('Filmstrip renders real frame identities, lazy images, missing and paging states', () => {
  const sample = nativeFrameSample(fixture, 340);
  assert.equal(sample.local_frame_index0, 85);
  const manifest = { task_id: fixture.execution.task_id, artifact_id: fixture.artifact.artifact_id, video_sha256: fixture.artifact.video_sha256, samples: [sample], time_domain: 'CLIP_LOCAL', unique_frame_count: 50, requested_count: 70, deduplicated_count: 20, offset: 0, next_offset: 48, unresolved: [] };
  const html = render(Filmstrip, { manifest, selected: sample, observations: [], onSelect() {}, onPage() {}, loading: false });
  assert.match(html, /loading="lazy"/);
  assert.match(html, /14.166667s/);
  assert.ok(html.includes('340') && html.includes('cei-selected'));
  assert.match(render(Filmstrip, { manifest: null, selected: null, observations: [], onSelect() {}, onPage() {}, loading: false }), /没有可用帧/);
});

test('Frame Inspector separates frame-time EXPECTED from exact D5 boundary and authority ABSENT', () => {
  const sample = nativeFrameSample(fixture, 388);
  assert.equal(expectedAtTime(fixture, sample.sample_time).dialogues.length, 0);
  assert.equal(expectedAtTime(fixture, 5.55).dialogues[0].payload.subject_token, '<Subject 5>');
  assert.equal(expectedAtTime(fixture, 4.5).dialogues[0].payload.subject_token, '<Subject 3>');
  const html = render(FrameInspector, { projection: fixture, sample, requested: 5.55, observations: [], onStep() {}, onTime() {} });
  assert.match(html, /expected-frame-time/);
  assert.match(html, /expected-exact-time/);
  assert.match(html, /5.541667s/);
  assert.match(html, /5.55s/);
  for (const name of ['Visual Attention Owner', 'Foreground Speaker', 'Background Entrant', 'Background Motion Subject']) assert.ok(html.includes(name));
  assert.ok((html.match(/cei-source-ABSENT/g) || []).length === 4);
  assert.ok(html.includes('Exactly one body enters'));
  assert.ok(!html.includes('<video')); // No video download on initial open.
  assert.equal(nativeFrameSample(fixture, 254), null);
  assert.equal(nativeFrameSample(fixture, 529), null);
});

test('A/H: five executions of Revision 1 remain distinct selector options keyed by full task ID', () => {
  assert.equal(completedResults.length, 5);
  assert.ok(completedResults.every(e => e.clip_plan_revision === 1));
  const html = render(ExecutionResultOptions, { executions: completedResults, selectedTaskId: fixture.execution.task_id });
  assert.equal((html.match(/<option /g) || []).length, 5);
  for (const e of completedResults) {
    assert.ok(html.includes(`value="${e.task_id}"`));
    assert.ok(html.includes(`Rev 1 · Exec ${e.task_id.slice(0, 8)} · completed`));
  }
});

for (const [label, projection, other] of [['B: A', fixture, fixtureB], ['C: B', fixtureB, fixture]]) {
  test(`${label} summary shows the selected execution and actual video identity`, () => {
    const html = render(ClipSummary, { projection });
    const identity = html.match(/data-testid="execution-identity"([\s\S]*?)<\/dl>/)?.[1];
    assert.ok(identity);
    for (const value of ['Revision', 'Execution', 'Status', 'Operation', 'Video SHA', projection.execution.task_id, projection.artifact.video_sha256,
      `${projection.media.frame_count} frames · ${projection.media.fps} fps`, `${Number(projection.media.video_duration.toFixed(6))}s`]) assert.ok(identity.includes(value), value);
    assert.ok(!identity.includes(other.execution.task_id));
    assert.ok(!identity.includes(other.artifact.video_sha256));
  });
}

test('D: Filmstrip fingerprint belongs to its sampling manifest for both selected executions', () => {
  for (const projection of [fixture, fixtureB]) {
    const sample = nativeFrameSample(projection, 363);
    const manifest = { task_id: projection.execution.task_id, artifact_id: projection.artifact.artifact_id, video_sha256: projection.artifact.video_sha256,
      samples: [sample], time_domain: 'CLIP_LOCAL', unique_frame_count: 1, requested_count: 1, deduplicated_count: 0, offset: 0, next_offset: null, unresolved: [] };
    const html = render(Filmstrip, { manifest, selected: sample, observations: [], onSelect() {}, onPage() {}, loading: false });
    assert.ok(html.includes('data-testid="filmstrip-source"'));
    assert.ok(html.includes(`title="${projection.execution.task_id}"`));
    assert.ok(html.includes(`title="${projection.artifact.video_sha256}"`));
    assert.ok(html.includes(sample.image_url));
  }
});

test('E: Frame Inspector fingerprint follows the selected projection and extracted detail', () => {
  for (const projection of [fixture, fixtureB]) {
    const sample = nativeFrameSample(projection, 363);
    const html = render(FrameInspector, { projection, sample, requested: 4.5, observations: [], onStep() {}, onTime() {} });
    assert.ok(html.includes('data-testid="frame-source"'));
    assert.ok(html.includes(`title="${projection.execution.task_id}"`));
    assert.ok(html.includes(`title="${projection.artifact.video_sha256}"`));
    assert.ok(html.includes(sample.detail_url));
    assert.ok(html.includes('15.125s'));
  }
});

test('F: actual Native playback child uses the selected artifact URL and matching fingerprint', () => {
  for (const [projection, other] of [[fixture, fixtureB], [fixtureB, fixture]]) {
    const html = render(NativeAVPlayback, { projection, sample: nativeFrameSample(projection, 363), video: { current: null }, onTime() {} });
    assert.ok(html.includes(`src="${projection.artifact.result_url}"`));
    assert.ok(html.includes('preload="none"'));
    assert.ok(html.includes('data-testid="player-source"'));
    assert.ok(html.includes(`title="${projection.artifact.video_sha256}"`));
    assert.ok(html.includes(`title="${projection.execution.task_id}"`));
    assert.ok(!html.includes(other.artifact.result_url));
  }
});

test('I: different video SHA isolates both frame cache URLs and displayed source identity', () => {
  const a = nativeFrameSample(fixture, 363);
  const b = nativeFrameSample(fixtureB, 363);
  assert.notEqual(fixture.artifact.video_sha256, fixtureB.artifact.video_sha256);
  assert.notEqual(a.sample_id, b.sample_id);
  assert.notEqual(a.image_url, b.image_url);
  assert.notEqual(a.detail_url, b.detail_url);
  for (const [projection, sample] of [[fixture, a], [fixtureB, b]]) {
    assert.ok(sample.detail_url.includes(`/frames/${projection.artifact.video_sha256}/frame-v1/detail/363`));
  }
});

test('Observation API revision and reload data drive Timeline and frame markers through CRUD', async () => {
  const persistence = path.join(temp, 'saved-analysis.json');
  const initial = { analysis_id: 'analysis', revision: 1, variants: [{ variant_id: 'A', projection: fixture }], observations: [] };
  await writeFile(persistence, JSON.stringify(initial));
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, ...options });
    const data = JSON.parse(await readFile(persistence, 'utf8'));
    if (options.method !== 'GET') {
      assert.equal(options.headers['If-Match'], `"${data.revision}"`);
      const body = options.body ? JSON.parse(options.body) : null;
      if (options.method === 'POST') data.observations.push({ ...body, observation_id: 'note', analysis_id: 'analysis', variant_id: 'A', artifact_id: fixture.artifact.artifact_id, updated_at: '2026-10-07T08:00:00Z', frame_evidence: { native_frame_index0: 340, native_pts: 340 / 24 } });
      if (options.method === 'PATCH') Object.assign(data.observations[0], body);
      if (options.method === 'DELETE') data.observations = [];
      data.revision += 1;
      await writeFile(persistence, JSON.stringify(data));
    }
    return { ok: true, json: async () => ({ success: true, data }) };
  };
  try {
    let saved = await inspectorApi.createObservation(initial, { time_seconds: 3.542, end_time_seconds: null, categories: ['PORTRAIT_DRIFT'], note: 'temporary test' });
    saved = await inspectorApi.analysis('analysis');
    const timeline = render(UnifiedTimeline, { projection: fixture, time: 3.542, observations: saved.observations, onEvent() {}, onObservation() {} });
    assert.ok(timeline.includes('observation-marker') && timeline.includes('3.542s'));
    assert.equal(observationsForFrame(saved.observations, nativeFrameSample(fixture, 340)).length, 1);
    assert.equal(observationsForFrame(saved.observations, nativeFrameSample(fixture, 363)).length, 0);
    assert.ok(render(ObservationEditor, { time: 3.542, observations: saved.observations, saving: false, error: '', onSave() {}, onDelete() {}, onSelect() {} }).includes('temporary test'));
    saved = await inspectorApi.updateObservation(saved, 'note', { time_seconds: 3.542, end_time_seconds: null, categories: ['OTHER'], note: 'updated' });
    saved = await inspectorApi.deleteObservation(saved, 'note');
    saved = await inspectorApi.analysis('analysis');
    assert.ok(!render(UnifiedTimeline, { projection: fixture, time: 3.542, observations: saved.observations, onEvent() {}, onObservation() {} }).includes('data-testid="observation-marker"'));
    assert.deepEqual(calls.map(c => c.method), ['POST', 'GET', 'PATCH', 'DELETE', 'GET']);
    assert.ok(calls.every(c => c.url.includes('/clip-execution-inspector/')));
  } finally { globalThis.fetch = originalFetch; }
});

test('aborted StrictMode load retries and saving the analysis URL preserves the selected frame', async () => {
  const hooks = await load('pages/ClipExecutionInspector/hookReact.js');
  const { useClipExecutionInspector } = await load('pages/ClipExecutionInspector/useClipExecutionInspector.js');
  const originalFetch = globalThis.fetch;
  const calls = [];
  let executions = 0;
  let savedId;
  const saved = { analysis_id: 'durable', revision: 1, variants: [{ variant_id: 'A', projection: fixture }], observations: [] };
  globalThis.fetch = async (url, options) => {
    calls.push({ url, method: options.method });
    if (url.includes('/executions/') && ++executions === 1) {
      await new Promise((resolve, reject) => options.signal.addEventListener('abort', () => reject(new Error('aborted')), { once: true }));
    }
    const data = url.includes('/artifacts') ? { artifacts: [], analyses: [] } : url.endsWith('/analyses') ? saved : fixture;
    return { ok: true, json: async () => ({ success: true, data }) };
  };
  const renderHook = analysisId => {
    hooks.begin();
    return useClipExecutionInspector('task', analysisId, null, id => { savedId = id; });
  };
  try {
    renderHook(null);
    const setup = hooks.setups()[0];
    const firstCleanup = setup();
    firstCleanup();
    const replayCleanup = setup();
    await new Promise(resolve => setImmediate(resolve));
    let state = renderHook(null);
    assert.equal(executions, 2);
    assert.equal(state.loading, false);
    assert.equal(state.error, '');
    assert.equal(state.projection.artifact.artifact_id, fixture.artifact.artifact_id);
    state.selectFrame(nativeFrameSample(fixture, 363), 4.5);
    state = renderHook(null);
    await state.saveAnalysis();
    assert.equal(savedId, 'durable');
    replayCleanup();
    state = renderHook(savedId);
    assert.equal(hooks.setups()[0](), undefined);
    assert.equal(state.selected.native_frame_index0, 363);
    assert.equal(state.requestedTime, 4.5);
    assert.equal(state.analysis.analysis_id, 'durable');
    assert.equal(state.loading, false);
    assert.equal(calls.filter(call => call.method === 'GET' && call.url.includes('/analyses/')).length, 0);
  } finally { globalThis.fetch = originalFetch; }
});


test('Contact sheet reads every page, excludes event-only frames and sorts uniform frame identities', async () => {
  const original = inspectorApi.sampling;
  const calls = [];
  const sample = (index, reasons) => ({ ...nativeFrameSample(fixture, index), reasons });
  const base = { task_id: fixture.execution.task_id, artifact_id: fixture.artifact.artifact_id,
    video_sha256: fixture.artifact.video_sha256, manifest_id: 'uniform-sheet' };
  const controller = new AbortController();
  inspectorApi.sampling = async (taskId, body, offset, signal) => {
    calls.push({ taskId, body, offset, signal });
    return { ...base, samples: offset === 0 ? [sample(340, ['UNIFORM', 'DIALOGUE:START']), sample(341, ['HUMAN_MARKER'])] :
      [sample(364, ['UNIFORM']), sample(340, ['UNIFORM']), sample(255, ['UNIFORM'])], next_offset: offset === 0 ? 48 : null };
  };
  try {
    const frames = await loadContactSheet(fixture, .5, 'analysis-a', controller.signal);
    assert.deepEqual(frames.map(f => f.native_frame_index0), [255, 340, 364]);
    assert.deepEqual(calls.map(c => c.offset), [0, 48]);
    assert.equal(calls[0].body.uniform_interval_seconds, .5);
    assert.equal(calls[0].body.event_enhanced, false);
    assert.equal(calls[0].body.event_neighbors, false);
    assert.equal(calls[0].body.analysis_id, 'analysis-a');
    assert.equal(calls[0].signal, controller.signal);
    const html = render(ContactSheetGrid, { samples: frames, timeDomain: 'CLIP_LOCAL' });
    assert.match(html, /0s · 帧 0/);
    assert.match(html, /3.541667s · 帧 85/);
    assert.match(html, /Native 14.166667s · 帧 340/);
    assert.equal((html.match(/<figure/g) || []).length, 3);
    const native = render(ContactSheetGrid, { samples: [frames[1]], timeDomain: 'NATIVE_ONLY' });
    assert.match(native, /帧 340/);
    assert.doesNotMatch(native, /帧 85/);
  } finally { inspectorApi.sampling = original; }
});

test('Contact sheet rejects changed sources between pages and stops after closing', async () => {
  const original = inspectorApi.sampling;
  const base = { task_id: fixture.execution.task_id, artifact_id: fixture.artifact.artifact_id,
    video_sha256: fixture.artifact.video_sha256, manifest_id: 'same', samples: [] };
  try {
    for (const changed of [{ artifact_id: 'other' }, { video_sha256: 'other' }, { manifest_id: 'other' }]) {
      inspectorApi.sampling = async (_task, _body, offset) => ({ ...base, ...(offset ? changed : {}), next_offset: offset ? null : 48 });
      await assert.rejects(loadContactSheet(fixture, 1), /SOURCE_CHANGED/);
    }
    const controller = new AbortController();
    let calls = 0;
    inspectorApi.sampling = async () => { calls++; controller.abort(); return { ...base, next_offset: 48 }; };
    await assert.rejects(loadContactSheet(fixture, 2, undefined, controller.signal), { name: 'AbortError' });
    assert.equal(calls, 1);
  } finally { inspectorApi.sampling = original; }
});
