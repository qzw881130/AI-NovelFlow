import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const code = await readFile(new URL('../src/pages/ChapterGenerate/chapterMergeReadiness.ts', import.meta.url), 'utf8');
const exports = {};
new Function('exports', ts.transpileModule(code, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText)(exports);
const ready = exports.getChapterMergeReadiness;

test('Shot24: successful C1 does not make the chapter merge ready without final Shot URL', () => {
  const result = ready({ id: '87bef940-93a8-4e84-9e7f-a1d5dc399979', videoUrl: null, videoStatus: 'pending',
    videoDirectorPlan: { canonical_visual_plan: true, clip_plan: [{ clip_index: 1, status: 'SUCCEEDED', video_url: '/shot_024_clip_1.mp4' }] } });
  assert.equal(result.ready, false);
  assert.equal(result.label, '片段完成，待合并');
  assert.match(result.reason, /合并最终视频/);
});

test('orphaned plan URL and task preview cannot make a missing persisted video mergeable', () => {
  assert.equal(ready({ id: 's', videoStatus: 'completed', videoUrl: null,
    resultUrl: '/task.mp4', videoDirectorPlan: { merged_video_url: '/stale.mp4' } }).ready, false);
});

test('formal canonical and legacy Shot video bindings are accepted, including duration warnings', () => {
  for (const plan of [undefined, { canonical_visual_plan: true, duration_acceptance: 'FAIL' }]) {
    assert.equal(ready({ id: 's', videoUrl: '/final.mp4', videoDirectorPlan: plan }).ready, true);
  }
});

test('incomplete and failed Clips are explained separately from missing assembly', () => {
  const shot = { id: 's', videoDirectorPlan: { clip_plan: [{ status: 'SUCCEEDED', video_url: '/c1.mp4' }, { status: 'PLANNED' }] } };
  assert.equal(ready(shot).label, '片段未完成');
  shot.videoDirectorPlan.clip_plan[1].status = 'FAILED';
  assert.equal(ready(shot).label, '生成失败');
});

test('generation and missing media states are not selectable', () => {
  assert.equal(ready({ id: 's', videoStatus: 'generating' }).label, '生成中');
  assert.equal(ready({ id: 's', videoStatus: 'completed' }).label, '缺少最终视频');
  assert.equal(ready(undefined).ready, false);
});

// Exercise the actual picker loading effect: no fallback to cached task results.
const page = await readFile(new URL('../src/pages/ChapterGenerate/components/VideoGenTab.tsx', import.meta.url), 'utf8');
const start = page.indexOf('  // Read persisted Shot bindings when opening the picker.');
const source = page.slice(start, page.indexOf('  const mergeReadyShotIds', start));
const js = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2020 } }).outputText;
function picker(fetch) {
  const state = { shots: [{ id: 'stale', videoUrl: '/preview.mp4' }], selection: new Set(['stale']) };
  const deps = {
    showMergeSelectModal: true, effectiveNovelId: 'n', effectiveChapterId: 'c', mergeReadinessReload: 0,
    useEffect: fn => { state.cleanup = fn(); }, shotsApi: { getShots: fetch }, getChapterMergeReadiness: ready,
    setMergeReadinessLoading: value => { state.loading = value; },
    setMergeReadinessError: value => { state.error = value; },
    setMergeShots: value => { state.shots = value; },
    setSelectedMergeShotIds: value => { state.selection = value; },
  };
  new Function(...Object.keys(deps), js)(...Object.values(deps));
  return state;
}
const settle = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };

test('opening picker clears stale selection and selects only fresh persisted final videos', async () => {
  let resolve;
  const state = picker((_n, _c, signal) => { assert.ok(signal instanceof AbortSignal); return new Promise(done => { resolve = done; }); });
  assert.equal(state.loading, true); assert.deepEqual([...state.selection], []); assert.deepEqual(state.shots, []);
  resolve({ success: true, data: [{ id: 'ready', videoUrl: '/final.mp4' }, { id: 's24', videoUrl: null }] });
  await settle(); assert.deepEqual([...state.selection], ['ready']); assert.equal(state.loading, false);
});

test('failed readiness read leaves no selectable cached items', async () => {
  const state = picker(async () => { throw new Error('network down'); });
  await settle(); assert.deepEqual(state.shots, []); assert.equal(state.error, 'network down'); assert.equal(state.loading, false);
});

test('closed picker discards late responses from an older chapter or request', async () => {
  let resolve;
  const state = picker(() => new Promise(done => { resolve = done; }));
  state.cleanup(); resolve({ success: true, data: [{ id: 'late', videoUrl: '/old.mp4' }] });
  await settle(); assert.deepEqual(state.shots, []); assert.deepEqual([...state.selection], []);
});
