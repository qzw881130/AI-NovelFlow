import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/pages/ChapterGenerate/previousClipFrame.ts', import.meta.url), 'utf8');
const js = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS } }).outputText;
const exports = {};
new Function('exports', js)(exports);
const { previousClipFrameTarget, captureVideoFrame, savePreviousClipFrame } = exports;
const snapshot = JSON.parse(await readFile(new URL('./fixtures/previousClipFrameShot2.json', import.meta.url), 'utf8'));
const fixture = () => structuredClone(snapshot);

test('real Shot2 KF4 belongs to C3; source is C2, never C4 carry-in or selected player', () => {
  const shot = fixture(); const before = JSON.stringify(shot);
  const target = previousClipFrameTarget(shot, 4);
  assert.equal(target.shotId, '2669e7aa-5f92-4261-b602-cae4d81f5c51');
  assert.equal(target.ownerClipIndex, 3); assert.equal(target.previousClipIndex, 2); assert.equal(target.frameIndex, 2);
  assert.equal(JSON.stringify(shot), before);
});

test('all states of C4 use C3; first clip has no previous clip', () => {
  for (const index of [5, 6, 7]) assert.equal(previousClipFrameTarget(fixture(), index).previousClipIndex, 3);
  assert.throws(() => previousClipFrameTarget(fixture(), 2), /第一个 Clip/);
});

test('CUT still exposes the preceding clip as a manual image source without changing its plan', () => {
  const shot = fixture(); shot.videoDirectorPlan.clip_plan[2].previous_clip_index = null;
  shot.videoDirectorPlan.clip_plan[2].continuity_to_previous = 'CUT';
  assert.equal(previousClipFrameTarget(shot, 4).previousClipIndex, 2);
  assert.equal(shot.videoDirectorPlan.clip_plan[2].continuity_to_previous, 'CUT');
});

test('missing/stale plan, invalid ownership and unresolved predecessor are not guessed', () => {
  const shot = fixture(); shot.videoDirectorPlan.clip_plan_validation.passed = false;
  assert.throws(() => previousClipFrameTarget(shot, 4), /Clip 规划/);
  const duplicate = fixture(); duplicate.videoDirectorPlan.clip_plan[3].visual_state_indexes.push(4);
  assert.throws(() => previousClipFrameTarget(duplicate, 4), /所属/);
  const missing = fixture(); missing.videoDirectorPlan.clip_plan[2].visual_state_indexes = [];
  assert.throws(() => previousClipFrameTarget(missing, 4), /所属/);
  const wrongPrevious = fixture(); wrongPrevious.videoDirectorPlan.clip_plan[2].previous_clip_index = 1;
  assert.throws(() => previousClipFrameTarget(wrongPrevious, 4), /关系不一致/);
});

test('failed source, no adopted source, and missing image record cannot be used', () => {
  for (const change of [c => { c.execution_status = 'FAILED'; }, c => { c.generated_by_task_id = null; }, c => { c.video_url = null; c.local_path = null; }]) {
    const shot = fixture(); change(shot.videoDirectorPlan.clip_plan[1]);
    assert.throws(() => previousClipFrameTarget(shot, 4), /正式视频/);
  }
  const shot = fixture(); shot.keyframes = shot.keyframes.filter(f => f.plan_keyframe_index !== 4);
  assert.throws(() => previousClipFrameTarget(shot, 4), /图片记录/);
});

function fakeCanvas(t, { failure = null } = {}) {
  const oldDocument = globalThis.document;
  const calls = [];
  const canvas = { width: 0, height: 0,
    getContext(type) { assert.equal(type, '2d'); return { drawImage(video, ...args) {
      assert.equal(video.paused, true); if (failure) throw failure; calls.push(args);
    } }; },
    toBlob(callback, type) { assert.equal(type, 'image/png'); callback(new Blob(['png'], { type })); },
  };
  globalThis.document = { createElement(type) { assert.equal(type, 'canvas'); return canvas; } };
  t.after(() => { globalThis.document = oldDocument; });
  return { canvas, calls };
}
const video = () => ({ pause() { this.paused = true; }, seeking: false, readyState: 4, videoWidth: 960, videoHeight: 544, currentTime: 11.125 });

test('capture pauses, copies the selected decoded frame at native size and encodes PNG', async t => {
  const { canvas, calls } = fakeCanvas(t);
  const file = await captureVideoFrame(video());
  assert.equal(file.type, 'image/png'); assert.match(file.name, /11\.125\.png$/);
  assert.deepEqual([canvas.width, canvas.height], [960, 544]);
  assert.deepEqual(calls, [[0, 0, 960, 544]]);
});

test('not loaded or still seeking cannot capture a stale frame', async () => {
  for (const patch of [{ seeking: true }, { readyState: 1 }, { videoWidth: 0 }]) {
    await assert.rejects(captureVideoFrame({ ...video(), ...patch }), /尚未就绪/);
  }
});

test('cross-origin canvas restriction is explained', async t => {
  const error = new Error('tainted'); error.name = 'SecurityError'; fakeCanvas(t, { failure: error });
  await assert.rejects(captureVideoFrame(video()), /跨域限制/);
});

test('save uses existing upload endpoint contract and exact zero-based frame index once', async () => {
  const shot = fixture(); const target = previousClipFrameTarget(shot, 4);
  const file = new File(['png'], 'frame.png', { type: 'image/png' }); const calls = [];
  await savePreviousClipFrame(target, file, {
    getShot: async () => ({ success: true, data: shot }),
    upload: async (...args) => { calls.push(args); return { success: true }; },
  });
  assert.deepEqual(calls, [[2, file]]); assert.deepEqual(shot, snapshot);
});

test('state image, description, revision or predecessor changes stop replacement before upload', async () => {
  const target = previousClipFrameTarget(fixture(), 4);
  for (const change of [s => { s.videoDirectorPlan.clip_plan_revision++; }, s => { s.keyframes[2].image_url = '/new.png'; },
    s => { s.videoDirectorPlan.keyframes[3].description += ' changed'; }, s => { s.videoDirectorPlan.clip_plan[1].generated_by_task_id = 'new-task'; }]) {
    const shot = fixture(); change(shot); let uploads = 0;
    await assert.rejects(savePreviousClipFrame(target, new File([], 'x.png'), {
      getShot: async () => ({ success: true, data: shot }), upload: async () => { uploads++; return { success: true }; },
    }), /已变化/);
    assert.equal(uploads, 0);
  }
});

test('backend conflict surfaces without retry or fake success', async () => {
  const shot = fixture(); let uploads = 0;
  await assert.rejects(savePreviousClipFrame(previousClipFrameTarget(shot, 4), new File([], 'x.png'), {
    getShot: async () => ({ success: true, data: shot }),
    upload: async () => { uploads++; return { success: false, detail: 'CANONICAL_ACTIVE_EXECUTION' }; },
  }), /CANONICAL_ACTIVE_EXECUTION/);
  assert.equal(uploads, 1);
});
