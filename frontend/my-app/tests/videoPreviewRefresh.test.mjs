import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const page = await readFile(new URL('../src/pages/ChapterGenerate/components/VideoGenTab.tsx', import.meta.url), 'utf8');
const buttons = await readFile(new URL('../src/pages/ChapterGenerate/components/ClipPlaybackButtons.tsx', import.meta.url), 'utf8');
const compile = source => ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS } }).outputText;
const helpers = compile(buttons.slice(buttons.indexOf('export function clipPlaybackErrorMessage'), buttons.indexOf('export function ClipPlaybackButtons')));
const helperExports = {};
new Function('exports', helpers)(helperExports);
const handler = compile(page.slice(page.indexOf('  const handleRefreshCurrentVideo ='), page.indexOf('  const handlePictureInPicture =')));

function fixture({ kind = 'independent_url', selected = '1', assembled = false, semantic = true } = {}) {
  const state = { shotVideos: { s: '/stale-shot.mp4', other: '/other.mp4' }, shots: [{ id: 's' }, { id: 'other', latest: true }], messages: [], reload: 0, selected: '/old-preview.mp4', clipRequests: [] };
  const target = { current: 's:1' };
  const result = { success: true, data: { id: 's', videoUrl: assembled ? '/final-new.mp4' : null,
    videoDirectorPlan: { canonical_visual_plan: semantic, clip_plan: [{ clip_index: 1, video_url: '/approved-c1.mp4' }], final_assembly: { status: assembled ? 'COMPLETED' : 'READY' } } } };
  const response = { success: true, data: { independent_url: '/raw-new.mp4', cumulative_url: '/cumulative-new.mp4' } };
  const dependencies = {
    effectiveNovelId: 'n', effectiveChapterId: 'c', currentShotId: 's', isRefreshingVideo: false,
    continuationMode: 'EXTEND_ONLY', hasSemanticClipPlan: semantic, selectedPreviewClipKey: selected, selectedPreviewPlaybackKind: kind,
    previewTargetRef: target,
    shotsApi: { async getShot(...args) { state.shotArgs = args; return result; }, async getClipPlayback(...args) { state.clipRequests.push(args); return response; } },
    taskApi: { async fetchShotTasks() { return { success: true, data: [{ id: 'current-task' }] }; } },
    resolveClipPlaybackResponse: helperExports.resolveClipPlaybackResponse,
    isCanonicalVisualPlan: plan => plan.canonical_visual_plan,
    hasCurrentAssembly: plan => plan.final_assembly.status === 'COMPLETED',
    getPlanClipKey: clip => String(clip.clip_index || clip.window_index),
    useChapterGenerateStore: { getState: () => state },
    setShots: value => { state.shots = value; },
    setShotVideos: update => { state.shotVideos = update(state.shotVideos); },
    setSemanticClipTasks: value => { state.tasks = value; },
    setSelectedPreviewClipUrl: value => { state.selected = value; },
    setSelectedPlaybackSource: value => { state.source = value; },
    setPreviewReloadKey: update => { state.reload = update(state.reload); },
    setIsRefreshingVideo: value => { state.busy = value; },
    toast: Object.fromEntries(['success', 'info', 'error'].map(key => [key, text => state.messages.push([key, text])])),
    console: { error() {} },
  };
  const run = new Function(...Object.keys(dependencies), `${handler}; return handleRefreshCurrentVideo;`)(...Object.values(dependencies));
  return { state, target, result, response, dependencies, run };
}

test('unmerged C1 refreshes its clip, clears stale final URL and reloads player', async () => {
  const f = fixture(); await f.run();
  assert.equal(f.state.selected, '/raw-new.mp4'); assert.equal(f.state.reload, 1);
  assert.equal(f.state.shotVideos.s, undefined); assert.equal(f.state.shotVideos.other, '/other.mp4');
  assert.equal(f.state.shots[1].latest, true);
  assert.deepEqual(f.state.clipRequests, [['n', 'c', 's', 1]]);
  assert.equal(f.state.shotArgs.at(-1), 'EXTEND_ONLY');
  assert.deepEqual(f.state.messages, [['success', 'C1 片段预览已刷新']]); assert.equal(f.state.busy, false);
});

test('cumulative selection persists and unchanged URL still reloads', async () => {
  const f = fixture({ kind: 'cumulative_url' }); f.response.data.cumulative_url = '/old-preview.mp4'; await f.run();
  assert.equal(f.state.selected, '/old-preview.mp4'); assert.equal(f.state.reload, 1);
  assert.equal(f.state.source.label, '截至本片段的累计视频');
});

test('old receipt review fallback remains honestly labeled', async () => {
  const f = fixture(); f.response.data.independent_url = null; f.response.data.review_url = '/review.mp4'; await f.run();
  assert.equal(f.state.selected, '/review.mp4'); assert.match(f.state.source.label, /非原始单段/);
});

test('final refresh fetches assembly without invoking clip playback', async () => {
  const f = fixture({ selected: null, assembled: true }); await f.run();
  assert.equal(f.state.shotVideos.s, '/final-new.mp4'); assert.equal(f.state.selected, null);
  assert.equal(f.state.clipRequests.length, 0); assert.equal(f.state.reload, 1);
  assert.deepEqual(f.state.messages, [['success', '最终视频预览已刷新']]);
});

test('unassembled final view reports missing assembly, not missing clip', async () => {
  const f = fixture({ selected: null }); await f.run();
  assert.deepEqual(f.state.messages, [['info', '当前 Shot 尚无已合并的最终视频']]);
  assert.equal(f.state.clipRequests.length, 0);
});

test('read failure preserves current player and shows the actual error', async () => {
  const f = fixture(); f.response.success = false; f.response.message = '读取失败'; await f.run();
  assert.equal(f.state.selected, '/old-preview.mp4'); assert.equal(f.state.reload, 0);
  assert.deepEqual(f.state.messages, [['error', '读取失败']]); assert.equal(f.state.busy, false);
});

test('late response cannot replace newly selected Shot or Clip', async () => {
  const f = fixture();
  f.dependencies.shotsApi.getClipPlayback = async () => { f.target.current = 'new-shot:2'; return f.response; };
  await f.run(); assert.equal(f.state.reload, 0); assert.equal(f.state.selected, '/old-preview.mp4');
  assert.deepEqual(f.state.messages, []); assert.equal(f.state.busy, false);
});

test('legacy window playback remains supported', async () => {
  const f = fixture({ semantic: false });
  f.result.data.videoDirectorPlan = { window_plans: [{ window_index: 1, video_url: '/legacy.mp4' }] };
  await f.run(); assert.equal(f.state.selected, '/legacy.mp4'); assert.equal(f.state.clipRequests.length, 0);
});
