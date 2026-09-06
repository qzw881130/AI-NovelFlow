import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import test from 'node:test';
import ts from 'typescript';

const require = createRequire(import.meta.url);
const root = '../src/pages/ChapterGenerate/';
const source = file => readFileSync(new URL(root + file, import.meta.url), 'utf8');
function load(text, imports = {}) {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(text, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText,
    { exports, require: name => imports[name] ?? require(name), console, localStorage: { getItem: () => null }, fetch: (...args) => imports.fetch(...args) });
  return exports;
}
const helpers = load(source('videoPlan.ts'));
const { formatUserFacingError } = load(readFileSync(new URL('../src/utils/errorUtils.ts', import.meta.url), 'utf8'));
const end = { index: 2, role: 'END', time_seconds: 9.051, description: 'End pose' };
const legacy = { frame_index: 0, plan_keyframe_index: 2, time_seconds: 9.051, description: 'End pose', image_url: 'end.png' };
const audioClip = () => ({ clip_index: 1, start_time: 0, end_time: 9.051, audio_status: 'READY', drive_audio_url: 'drive.wav', final_audio_url: 'final.wav' });
const shot = () => ({ id: '46', chapterId: 'c', imageUrl: 'start.png', videoStatus: 'pending', audioStatus: 'READY', keyframes: [{ ...legacy }], videoDirectorPlan: {
  selected_mode: 'FIRST_LAST_FRAME', audio_timeline: { resolved_duration: 9.051 }, execution_windows: [audioClip()],
  keyframes: [{ index: 1, role: 'START', time_seconds: 0 }, { ...end }],
} });

test('rebuilt Shot46 requires formal plan; matching legacy image only', () => {
  const s = shot();
  assert.equal(helpers.formalVideoPlanReady(s), true);
  assert.equal(helpers.videoKeyframeImage(s, end), 'end.png');
  s.keyframes[0].time_seconds = 15;
  assert.equal(helpers.videoKeyframeImage(s, end), null);
  s.keyframes[0] = { ...legacy, description: 'Different pose' };
  assert.equal(helpers.videoKeyframeImage(s, end), null);
  s.videoDirectorPlan.keyframes = [];
  assert.equal(helpers.formalVideoPlanReady(s), false);
  assert.equal(helpers.videoKeyframeImage(s, end), null);
});

// Execute the actual component handler with mocked dependencies, without mounting or network I/O.
const component = source('components/VideoGenTab.tsx');
const ast = ts.createSourceFile('VideoGenTab.tsx', component, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
let handler;
let readinessSelector;
let clipSelector;
function visit(node) {
  if (ts.isVariableDeclaration(node) && node.name.getText(ast) === 'handleGenerateVideo') handler = node.initializer.getText(ast);
  if (ts.isVariableDeclaration(node) && node.name.getText(ast) === 'getAudioDriveReadiness') readinessSelector = node.initializer.getText(ast);
  if (ts.isVariableDeclaration(node) && node.name.getText(ast) === 'mergeClipAudioWindows') clipSelector = node.initializer.getText(ast);
  ts.forEachChild(node, visit);
}
visit(ast);
const { getAudioDriveReadiness, mergeClipAudioWindows } = load(`export const getAudioDriveReadiness = ${readinessSelector}; export const mergeClipAudioWindows = ${clipSelector};`);
async function runHandler(initial, refreshed, mode = 'llm') {
  const calls = [], errors = [];
  let latest = initial;
  const context = {
    ...helpers, effectiveNovelId: 'n', effectiveChapterId: 'c', currentShotId: initial.id, hasVideo: false,
    preparingVideoRef: { current: false }, setPreparingVideoShotId() {}, setShowGenerateVideoMenu() {},
    refreshCurrentShotData: async () => { calls.push('refresh'); return latest; },
    getAudioDriveReadiness, formatUserFacingError,
    getShotImageUrl: s => s.imageUrl, buildVideoPromptDrafts: () => [],
    handlePlanVideoKeyframes: async () => { calls.push('plan'); latest = refreshed; return true; },
    generateKeyframeImage: async () => calls.push('image'), generateShotVideo: async () => calls.push('video'),
    useChapterGenerateStore: { getState: () => ({ generatingKeyframes: new Set() }) },
    toast: { info() {}, error: message => errors.push(message) }, markTabComplete() {}, t: x => x, console: { error() {} },
  };
  const js = ts.transpileModule(`const run = ${handler};`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  const run = vm.runInNewContext(js + '\nrun', context);
  await run(mode);
  assert.equal(context.preparingVideoRef.current, false);
  return { calls, errors };
}
test('LLM rebuilds empty formal plan, refreshes and reuses matching END', async () => {
  const initial = shot(); initial.videoDirectorPlan.keyframes = [];
  assert.deepEqual(await runHandler(initial, shot()), { calls: ['refresh', 'plan', 'refresh', 'video'], errors: [] });
});
test('missing END is submitted through existing image handler; retry can generate video', async () => {
  const s = shot(); delete s.keyframes[0].image_url;
  assert.deepEqual((await runHandler(s, s)).calls, ['refresh', 'image']);
  assert.deepEqual((await runHandler(shot(), shot())).calls, ['refresh', 'video']);
});
test('incompatible END is actionable, never submitted as video', async () => {
  const s = shot(); s.keyframes[0].time_seconds = 15;
  const result = await runHandler(s, s);
  assert.deepEqual(result.calls, ['refresh']); assert.equal(result.errors.length, 1);
});
test('video-only does not plan; audio readiness revalidated after planning', async () => {
  const initial = shot(); initial.videoDirectorPlan.keyframes = [];
  assert.deepEqual((await runHandler(initial, shot(), 'video_only')).calls, ['refresh']);
  const updated = shot(); updated.audioStatus = 'STALE';
  assert.deepEqual((await runHandler(initial, updated)).calls, ['refresh', 'plan', 'refresh']);
});

// Shape written by shots.py plan_video_keyframes for FIRST_LAST_FRAME success.
const firstLastPlanningSuccess = executionWindows => {
  const s = shot();
  s.duration = 15; // The canonical audio duration must win over an old Shot value.
  Object.assign(s.videoDirectorPlan, {
    keyframe_planning_status: 'STALE',
    transitions: [], window_plans: [], clips: [audioClip()],
    execution_windows: executionWindows,
    validation: { valid: true },
  });
  return s;
};

test('actual FIRST_LAST_FRAME success accepts clips with absent, empty, or bare execution windows and retained STALE', async () => {
  for (const windows of [undefined, [], [{ window_index: 1, start_time: 0, end_time: 9.051 }]]) {
    const updated = firstLastPlanningSuccess(windows);
    assert.equal(helpers.formalVideoPlanReady(updated), true);
    assert.equal(getAudioDriveReadiness(updated).ready, true);
    assert.equal(mergeClipAudioWindows(updated.videoDirectorPlan, 'FIRST_LAST_FRAME'), updated.videoDirectorPlan.clips);
    const initial = shot(); initial.videoDirectorPlan.keyframes = [];
    assert.deepEqual(await runHandler(initial, updated), { calls: ['refresh', 'plan', 'refresh', 'video'], errors: [] });
    assert.deepEqual(await runHandler(updated, updated), { calls: ['refresh', 'video'], errors: [] });
  }
});

test('FIRST_LAST_FRAME selectors prefer actual clips over obsolete window metadata', () => {
  const s = firstLastPlanningSuccess([{ window_index: 1, start_time: 0, end_time: 15, audio_status: 'STALE' }]);
  assert.equal(getAudioDriveReadiness(s).ready, true);
  assert.equal(helpers.formalVideoPlanReady(s), true);
  assert.equal(mergeClipAudioWindows(s.videoDirectorPlan, 'FIRST_LAST_FRAME')[0].end_time, 9.051);
  s.videoDirectorPlan.clips[0].audio_status = 'STALE';
  s.videoDirectorPlan.execution_windows = [audioClip()];
  assert.equal(getAudioDriveReadiness(s).ready, false); // Do not fall back to old READY audio.
});

test('obsolete STALE flag does not bypass actual frame, clip, or canonical duration mismatches', () => {
  for (const mutate of [
    s => { s.videoDirectorPlan.keyframes = []; },
    s => { s.videoDirectorPlan.keyframes[0].time_seconds = 1; },
    s => { s.videoDirectorPlan.keyframes[1].time_seconds = 15; },
    s => { s.videoDirectorPlan.clips[0].start_time = 1; },
    s => { s.videoDirectorPlan.clips[0].end_time = 15; },
    s => { s.videoDirectorPlan.audio_timeline.resolved_duration = 10; },
    s => { s.videoDirectorPlan.clips[0].end_time = 15; s.videoDirectorPlan.keyframes[1].time_seconds = 15; },
    s => { s.videoDirectorPlan.clips = []; },
  ]) {
    const s = firstLastPlanningSuccess([]);
    mutate(s);
    assert.equal(helpers.formalVideoPlanReady(s), false);
  }
});

test('real selector blocks missing final audio after successful planning', async () => {
  const initial = shot(); initial.videoDirectorPlan.keyframes = [];
  const updated = firstLastPlanningSuccess([]);
  delete updated.videoDirectorPlan.clips[0].final_audio_url;
  const result = await runHandler(initial, updated);
  assert.deepEqual(result.calls, ['refresh', 'plan', 'refresh']);
  assert.equal(result.errors.length, 1);
});

test('MULTI_KEYFRAME still selects window_plans rather than legacy clips', () => {
  const s = firstLastPlanningSuccess([]);
  s.videoDirectorPlan.selected_mode = 'MULTI_KEYFRAME';
  s.videoDirectorPlan.window_plans = [{ ...audioClip(), audio_status: 'STALE' }];
  assert.equal(getAudioDriveReadiness(s).ready, false);
  assert.equal(mergeClipAudioWindows(s.videoDirectorPlan, 'MULTI_KEYFRAME'), s.videoDirectorPlan.window_plans);
});

const shot91 = () => {
  const windows = [[0, 11.091], [11.091, 17.088]].map(([start_time, end_time], i) => ({
    ...audioClip(), window_index: i + 1, start_time, end_time,
  }));
  return { ...shot(), id: '9d523806-8ae9-49af-ac60-573b10408545', duration: 20, videoTaskId: null,
    videoDirectorPlan: {
      selected_mode: 'MULTI_KEYFRAME', keyframe_planning_status: 'STALE', keyframe_planning_message: 'Old audio build',
      audio_timeline: { resolved_duration: 17.088 }, execution_windows: windows,
      window_plans: windows.map((w, i) => ({ ...w, selected_frame_count: 3, keyframe_indexes: i ? [3, 4, 5] : [1, 2, 3] })),
      keyframes: [0, 5, 11.091, 14, 17.088].map((time_seconds, i) => ({
        index: i + 1, time_seconds, role: i === 0 ? 'START' : i === 4 ? 'END' : 'INTERMEDIATE', image_url: `frame${i + 1}.png`,
      })),
    },
  };
};

test('Shot91 manual LLM+ submits video for canonical legacy STALE multi plan without replanning', async () => {
  const s = shot91();
  assert.equal(helpers.formalVideoPlanReady(s), true);
  assert.deepEqual(await runHandler(s, s), { calls: ['refresh', 'video'], errors: [] });
});

test('Shot91 replan reaches video and subsequent attempts never repeat planning', async () => {
  for (const status of ['STALE', 'READY']) {
    const initial = shot91(); initial.videoDirectorPlan.keyframes = [];
    const updated = shot91(); updated.videoDirectorPlan.keyframe_planning_status = status;
    assert.deepEqual(await runHandler(initial, updated), { calls: ['refresh', 'plan', 'refresh', 'video'], errors: [] });
    assert.deepEqual(await runHandler(updated, updated), { calls: ['refresh', 'video'], errors: [] });
  }
});

test('multi readiness rejects noncanonical bounds, counts, references and ordering even with READY', async () => {
  const defects = [
    p => { p.audio_timeline.resolved_duration = 18; },
    p => { p.execution_windows[0].start_time = -1; },
    p => { p.execution_windows[1].start_time = 12; },
    p => { p.execution_windows[1].end_time = 20; },
    p => { p.execution_windows[0].end_time = 0; },
    p => { p.window_plans[0].start_time = null; },
    p => { p.window_plans[1].end_time = 18; },
    p => { p.window_plans.pop(); },
    p => { p.window_plans[1].window_index = 1; },
    p => { p.window_plans[0].selected_frame_count = 2; },
    p => { p.window_plans[0].selected_frame_count = 4; },
    p => { p.window_plans[0].keyframe_indexes = [1, 2, 2]; },
    p => { p.window_plans[0].keyframe_indexes = [1, 2, 99]; },
    p => { p.window_plans[0].keyframe_indexes = [1, 3, 2]; },
    p => { p.window_plans[0].keyframe_indexes = [1, 2, 4]; },
    p => { p.keyframes[0].time_seconds = 1; },
    p => { p.keyframes[4].time_seconds = 17; },
    p => { p.keyframes[1].time_seconds = 12; },
    p => { p.keyframes[1].time_seconds = NaN; },
    p => { p.keyframes[1].index = 1; },
    p => { p.keyframes[0].role = 'INTERMEDIATE'; },
    p => { p.keyframes.reverse(); },
  ];
  for (const status of ['STALE', 'READY']) {
    for (const mutate of defects) {
      const s = shot91(); s.videoDirectorPlan.keyframe_planning_status = status;
      mutate(s.videoDirectorPlan);
      assert.equal(helpers.formalVideoPlanReady(s), false, `${status}: ${mutate}`);
      const result = await runHandler(s, s);
      assert.equal(result.calls.includes('video'), false);
      assert.equal(result.errors.length, 1);
    }
  }
});

function storeHarness(s, tasks, batchTasks = []) {
  let state = { chapter: { id: 'c' }, shots: [s] }, writes = 0;
  const api = {};
  const { createGenerationSlice } = load(source('stores/slices/generationSlice.ts'), {
    '../../../../api/shots': { shotsApi: api }, '../../../../api/chapters': { chapterApi: {} },
    '../../../../utils': { formatUserFacingError: value => value }, '../../videoPlan': helpers,
    fetch: async url => ({ json: async () => ({ success: true, data: url.includes('shot_video_batch') ? batchTasks : tasks }) }),
  });
  const set = patch => { const next = typeof patch === 'function' ? patch(state) : patch; if (next !== state) { state = { ...state, ...next }; writes++; } };
  state = { ...state, ...createGenerationSlice(set, () => state) };
  return { get: () => state, set, writes: () => writes, api };
}
test('keyframe polling tracks current task, includes queued and cancelled, and no-ops unchanged results', async () => {
  const s = shot(); s.keyframes[0].image_task_id = 'new';
  const tasks = [
    { id: 'old', shotId: '46', name: '关键帧 aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa-0', status: 'completed', resultUrl: 'old.png' },
    { id: 'new', shotId: '46', name: '关键帧 aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa-0', status: 'queued' },
  ];
  const h = storeHarness(s, tasks);
  await h.get().checkKeyframeTaskStatus('c');
  assert.equal(h.get().generatingKeyframes.has('46-0'), true);
  const writes = h.writes();
  await h.get().checkKeyframeTaskStatus('c'); assert.equal(h.writes(), writes);
  tasks[1].status = 'cancelled';
  await h.get().checkKeyframeTaskStatus('c'); assert.equal(h.get().generatingKeyframes.size, 0);
  assert.equal(h.get().shots[0].keyframes[0].image_url, 'end.png');
  tasks[1].status = 'completed'; tasks[1].resultUrl = 'new.png';
  await h.get().checkKeyframeTaskStatus('c');
  const completedWrites = h.writes();
  await h.get().checkKeyframeTaskStatus('c'); assert.equal(h.writes(), completedWrites);
  assert.equal(h.get().shots[0].videoDirectorPlan.keyframes[1].image_url, 'new.png');
});
test('failed regeneration stays failed even when previous video exists', async () => {
  const s = shot(); s.videoTaskId = 'task'; s.videoUrl = 'previous.mp4';
  const h = storeHarness(s, [{ id: 'task', shotId: '46', status: 'failed', errorMessage: 'Failed' }]);
  await h.get().checkVideoTaskStatus('c');
  assert.equal(h.get().shots[0].videoStatus, 'failed');
  assert.equal(h.get().shots[0].videoUrl, 'previous.mp4');
});

test('video polling restores all normal task statuses from empty local sets on reload', async () => {
  for (const [status, expected] of Object.entries({ pending: 'pending', queued: 'generating', running: 'generating', completed: 'completed', failed: 'failed', cancelled: 'failed' })) {
    const s = shot(); s.videoTaskId = 'task';
    const h = storeHarness(s, [{ id: 'task', shotId: '46', status, resultUrl: status === 'completed' ? 'video.mp4' : undefined }]);
    await h.get().checkVideoTaskStatus('c');
    assert.equal(h.get().shots[0].videoStatus, expected, status);
    assert.equal(h.get().pendingVideos.has('46'), status === 'pending', status);
    assert.equal(h.get().generatingVideos.has('46'), ['queued', 'running'].includes(status), status);
    const writes = h.writes();
    await h.get().checkVideoTaskStatus('c'); assert.equal(h.writes(), writes, status);
  }
});

test('late video details cannot overwrite a newer shot or another task type', async () => {
  const s = shot(); s.videoTaskId = 'task';
  const h = storeHarness(s, [{ id: 'task', shotId: '46', status: 'running' }]);
  h.get().chapter.novelId = 'n';
  let resolveDetails;
  const started = new Promise(resolve => {
    h.api.getShot = () => { resolve(); return new Promise(done => { resolveDetails = done; }); };
  });
  const polling = h.get().checkVideoTaskStatus('c');
  await started;
  const updated = { ...h.get().shots[0], videoTaskId: 'new-task', imageStatus: 'generating' };
  h.set({ shots: [updated] });
  resolveDetails({ success: true, data: { ...s, videoStatus: 'completed', imageStatus: 'completed' } });
  await polling;
  assert.equal(h.get().shots[0], updated);
});

test('video detail hydration does not fight task status or image polling', async () => {
  const s = shot(); s.videoTaskId = 'task'; s.imageStatus = 'generating';
  const h = storeHarness(s, [{ id: 'task', shotId: '46', status: 'running' }]);
  h.get().chapter.novelId = 'n';
  h.api.getShot = async () => ({ success: true, data: { ...s, videoStatus: 'pending', imageStatus: 'completed' } });
  await h.get().checkVideoTaskStatus('c');
  assert.equal(h.get().shots[0].videoStatus, 'generating');
  assert.equal(h.get().shots[0].imageStatus, 'generating');
  const writes = h.writes();
  await h.get().checkVideoTaskStatus('c'); assert.equal(h.writes(), writes);
});

test('unrelated batch cannot reclaim a tracked individual task; cancelled parent clears queue', async () => {
  const s = shot(); s.videoTaskId = 'individual';
  const h = storeHarness(s, [{ id: 'individual', shotId: '46', status: 'completed', resultUrl: 'video.mp4' }], [
    { id: 'batch', status: 'running', metadata: { shot_ids: ['46'] } },
  ]);
  await h.get().checkVideoTaskStatus('c');
  assert.equal(h.get().shots[0].videoStatus, 'completed');
  assert.equal(h.get().shots[0].videoTaskId, 'individual');
  const queued = shot(); queued.videoTaskId = 'batch';
  const cancelled = storeHarness(queued, [], [{ id: 'batch', status: 'cancelled', metadata: { shot_ids: ['46'] } }]);
  cancelled.get().pendingVideos.add('46');
  await cancelled.get().checkVideoTaskStatus('c');
  assert.equal(cancelled.get().shots[0].videoStatus, 'failed');
  assert.equal(cancelled.get().pendingVideos.size, 0);
});
