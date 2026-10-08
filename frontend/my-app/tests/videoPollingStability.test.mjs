import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { create } from 'zustand';
import ts from 'typescript';

const read = path => readFile(new URL(`../src/${path}`, import.meta.url), 'utf8');
const compile = source => ts.transpileModule(source.replace(/^export /gm, ''), { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.None } }).outputText;
const strip = source => source.replace(/^import[\s\S]*?;\s*/gm, '');
const deferred = () => { let resolve; const promise = new Promise(yes => { resolve = yes; }); return { promise, resolve }; };
const settle = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };
const projectionJs = compile(strip(await read('pages/ChapterGenerate/shotReferenceProjection.ts')).replace('export function', 'function'));
const project = new Function(`${projectionJs}; return projectShotReferenceImages;`)();
const hookSource = await read('pages/ChapterGenerate/useShotReferenceImages.ts');
const hookFactory = new Function('useEffect', 'useMemo', 'useState', 'taskApi', 'useChapterGenerateStore', 'projectShotReferenceImages',
  `${compile(strip(hookSource).replace('export function', 'function'))}; return useShotReferenceImages;`);

// Execute the real hook with dependency-aware effects and persistent state.
function referencesHarness(fetch) {
  const states = [], effects = []; let stateIndex = 0, effectIndex = 0, queued = [];
  const resources = { characters: [], props: [] };
  const hook = hookFactory((effect, deps) => {
    const index = effectIndex++, old = effects[index];
    if (!old || deps.some((value, i) => !Object.is(value, old.deps[i]))) {
      old?.cleanup?.(); effects[index] = { deps };
      queued.push(() => { effects[index].cleanup = effect(); });
    }
  }, factory => factory(), initial => {
    const index = stateIndex++;
    if (!(index in states)) states[index] = initial;
    return [states[index], value => { states[index] = typeof value === 'function' ? value(states[index]) : value; }];
  }, { fetch }, select => select(resources), project);
  return { resources, render(shot, enabled = true) {
    stateIndex = 0; effectIndex = 0; queued = [];
    const result = hook(shot, enabled); queued.forEach(effect => effect()); return result;
  } };
}

test('video status refreshes do not reload or hide the same task reference images', async () => {
  const calls = [], pending = deferred();
  const harness = referencesHarness(id => { calls.push(id); return pending.promise; });
  let shot = { id: 'shot', imageTaskId: 'image-task', characters: ['Alice'] };
  harness.render(shot);
  pending.resolve({ data: { referenceImages: [{ label: '角色合并图', url: '/merged_characters/alice.png' }] } });
  await settle();
  const first = harness.render(shot); assert.equal(first.referenceImagesLoading, false);
  for (let i = 0; i < 8; i++) {
    shot = { ...shot, videoDirectorPlan: { progress: i } };
    const refreshed = harness.render(shot);
    assert.deepEqual(refreshed.referenceImages, first.referenceImages);
    assert.equal(refreshed.referenceImagesLoading, false);
  }
  assert.deepEqual(calls, ['image-task']);
  harness.resources.characters = [{ name: 'Alice', imageUrl: '/alice-new.png' }];
  assert.ok(harness.render({ ...shot }).referenceImages.some(image => image.url === '/alice-new.png'));
  assert.equal(calls.length, 1);
});

test('a new image task replaces references and ignores late responses from the old task', async () => {
  const old = deferred(), current = deferred(), calls = [];
  const harness = referencesHarness(id => { calls.push(id); return id === 'old' ? old.promise : current.promise; });
  harness.render({ imageTaskId: 'old' }); harness.render({ imageTaskId: 'new' });
  current.resolve({ data: { referenceImages: [{ url: '/new.png' }] } }); await settle();
  old.resolve({ data: { referenceImages: [{ url: '/old.png' }] } }); await settle();
  const result = harness.render({ imageTaskId: 'new', videoStatus: 'generating' });
  assert.deepEqual(result.referenceImages.map(image => image.url), ['/new.png']);
  assert.equal(result.referenceImagesLoading, false); assert.deepEqual(calls, ['old', 'new']);
});

const sliceSource = await read('pages/ChapterGenerate/stores/slices/generationSlice.ts');
const sliceFactory = new Function('shotsApi', 'chapterApi', 'formatUserFacingError', 'fetch', 'localStorage',
  `${compile(strip(sliceSource).replace('export const createGenerationSlice', 'const createGenerationSlice'))}; return createGenerationSlice;`);
const originalShot = () => ({ id: 'shot', index: 3, imageTaskId: 'image-task', imageUrl: '/shot.png', videoStatus: 'generating', videoUrl: null, videoTaskId: 'video-task', videoDirectorPlan: { clip_plan_revision: 1 } });
const activeTask = { id: 'video-task', shotId: 'shot', status: 'running' };
const response = tasks => ({ json: async () => ({ success: true, data: tasks }) });
function makeStore(fetch, getShot) {
  const creator = sliceFactory({ getShot }, {}, value => value || '', fetch, { getItem: () => null });
  return create((...args) => ({ ...creator(...args), chapter: { id: 'chapter', novelId: 'novel' }, shots: [originalShot()], generatingVideos: new Set(['shot']) }));
}

test('overlapping video polls share task and full-shot requests, including during the shot request', async () => {
  const list = deferred(), detail = deferred(); let lists = 0, shots = 0;
  const store = makeStore(() => { lists++; return list.promise; }, async (...args) => {
    shots++; assert.equal(args[3] instanceof AbortSignal, true); return detail.promise;
  });
  const before = store.getState().shots; let updates = 0; store.subscribe(() => updates++);
  const first = store.getState().checkVideoTaskStatus('chapter');
  assert.equal(first, store.getState().checkVideoTaskStatus('chapter'));
  list.resolve(response([activeTask])); await settle();
  assert.equal(first, store.getState().checkVideoTaskStatus('chapter'));
  detail.resolve({ success: true, data: structuredClone(before[0]) }); await first;
  assert.equal(lists, 1); assert.equal(shots, 1); assert.equal(store.getState().shots, before);
  assert.equal(updates, 0, 'identical responses must not publish a new Shot');
});

test('later polls still publish changed director plans and completed video results', async () => {
  let completed = false;
  const store = makeStore(async () => response([{ ...activeTask, status: completed ? 'completed' : 'running', resultUrl: completed ? '/final.mp4' : null }]),
    async () => ({ success: true, data: { ...originalShot(), videoDirectorPlan: { clip_plan_revision: 1, progress: 50 }, ...(completed ? { videoStatus: 'completed', videoUrl: '/final.mp4' } : {}) } }));
  await store.getState().checkVideoTaskStatus('chapter'); assert.equal(store.getState().shots[0].videoDirectorPlan.progress, 50);
  completed = true; await store.getState().checkVideoTaskStatus('chapter');
  assert.equal(store.getState().shots[0].videoUrl, '/final.mp4'); assert.equal(store.getState().shotVideos.shot, '/final.mp4');
  assert.equal(store.getState().generatingVideos.size, 0);
});

test('a failed poll releases the shared request for retry', async () => {
  let calls = 0;
  const store = makeStore(async () => { if (++calls === 1) throw new Error('test network failure'); return response([]); }, async () => assert.fail('No active shot'));
  await store.getState().checkVideoTaskStatus('chapter'); await store.getState().checkVideoTaskStatus('chapter'); assert.equal(calls, 2);
});

test('a response from a previous chapter cannot replace the current chapter state', async () => {
  const pending = deferred();
  const store = makeStore(() => pending.promise, async () => assert.fail('Stale chapter must not refresh shots'));
  const request = store.getState().checkVideoTaskStatus('chapter');
  store.setState({ chapter: { id: 'other', novelId: 'novel' } }); const before = store.getState();
  pending.resolve(response([activeTask])); await request; assert.equal(store.getState(), before);
});

test('only the chapter page owns recurring video status and Shot refreshes', async () => {
  const video = await read('pages/ChapterGenerate/components/VideoGenTab.tsx');
  assert.doesNotMatch(video, /setTimeout\(refreshCurrentShot|setTimeout\(refreshActiveShot/);
  assert.doesNotMatch(sliceSource, /pollVideoTask/);
  assert.match(video, /setHoveredReferenceImage\(null\); \}, \[shot\?\.id,/);
  assert.match(await read('api/tasks.ts'), /fetch: \(id: string\) => api\.get<Task>\(`\/tasks\/\$\{id\}`\)/);
});
