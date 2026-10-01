import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const sourceUrl = new URL('../src/pages/ChapterGenerate/videoDirectorAuthority.ts', import.meta.url);
const source = await readFile(sourceUrl, 'utf8');
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ES2020, target: ts.ScriptTarget.ES2020 },
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`;
const {
  buildVideoDirectorShotSavePayload,
  canUseLegacyShotGeneration,
  classifyVisualStateImageStatus,
  getAdjacentCanonicalTransitions,
  getCanonicalVisualStates,
  getRequiredMissingCanonicalVisualStates,
  isCanonicalVisualPlan,
  shouldAutoRecommendLegacyVideoMode,
} = await import(moduleUrl);

const makeCanonicalPlan = (count) => ({
  canonical_visual_plan: true,
  keyframes: Array.from({ length: count }, (_, offset) => ({
    index: offset + 1,
    time_seconds: offset * 5,
    role: offset === 0 ? 'START' : offset === count - 1 ? 'END' : 'INTERMEDIATE',
    description: `State ${offset + 1}`,
    timed_visual_target: offset === 1,
  })),
  transitions: Array.from({ length: Math.max(0, count - 1) }, (_, offset) => ({
    segment_index: offset + 1,
    from_keyframe_index: offset + 1,
    to_keyframe_index: offset + 2,
    transition_description: `Transition ${offset + 1}`,
  })),
});

test('A: canonical N=1 derives one visual state without mode', () => {
  const plan = makeCanonicalPlan(1);
  assert.equal(isCanonicalVisualPlan(plan), true);
  assert.equal('selected_mode' in plan, false);
  assert.deepEqual(getCanonicalVisualStates(plan).map((state) => state.index), [1]);
});

test('B: canonical N=2 and N=3 derive directly from keyframes without mode', () => {
  for (const count of [2, 3]) {
    const plan = makeCanonicalPlan(count);
    assert.equal('recommended_mode' in plan, false);
    assert.equal(getCanonicalVisualStates(plan).length, count);
  }
});

test('C: canonical N=5 and N=8 are not truncated by legacy frame counts', () => {
  for (const count of [5, 8]) {
    const plan = {
      ...makeCanonicalPlan(count),
      selected_mode: 'FIRST_LAST_FRAME',
      window_plans: [{ selected_frame_count: 3 }],
    };
    assert.deepEqual(
      getCanonicalVisualStates(plan).map((state) => state.index),
      Array.from({ length: count }, (_, index) => index + 1),
    );
  }
});

test('D-F: canonical image status distinguishes required, optional, and ready', () => {
  assert.equal(classifyVisualStateImageStatus({ index: 2, time_seconds: 5, role: 'INTERMEDIATE', timed_visual_target: true }), 'REQUIRED_MISSING');
  assert.equal(classifyVisualStateImageStatus({ index: 3, time_seconds: 10, role: 'INTERMEDIATE', timed_visual_target: false }), 'OPTIONAL_MISSING');
  assert.equal(classifyVisualStateImageStatus({ index: 1, time_seconds: 0, role: 'START', timed_visual_target: true }), 'OPTIONAL_MISSING');
  assert.equal(classifyVisualStateImageStatus({ index: 4, time_seconds: 15, role: 'END', timed_visual_target: true }, '/ready.png'), 'READY');
});

test('canonical plan without recommended_mode suppresses automatic legacy #07', () => {
  const canonicalPlan = {
    canonical_visual_plan: true,
    keyframes: [
      { index: 1, time_seconds: 0, role: 'START', timed_visual_target: false },
      { index: 2, time_seconds: 6, role: 'INTERMEDIATE', timed_visual_target: false },
      { index: 3, time_seconds: 12, role: 'INTERMEDIATE', timed_visual_target: true },
      { index: 4, time_seconds: 18, role: 'INTERMEDIATE', timed_visual_target: true },
      { index: 5, time_seconds: 24, role: 'END', timed_visual_target: false },
    ],
  };

  assert.equal(shouldAutoRecommendLegacyVideoMode(canonicalPlan, 'shot-1', null), false);
});

test('H: canonical planning ignores selected_frame_count and window plans', () => {
  const plan = {
    ...makeCanonicalPlan(5),
    selected_frame_count: 4,
    window_plans: [{ selected_frame_count: 3 }, { selected_frame_count: 4 }],
  };
  assert.equal(getCanonicalVisualStates(plan).length, 5);
});

test('I: canonical missing-image batch includes required timed targets only', () => {
  const plan = makeCanonicalPlan(5);
  plan.keyframes[2].timed_visual_target = false;
  plan.keyframes[3].timed_visual_target = true;
  plan.keyframes[4].timed_visual_target = true;
  plan.keyframes[4].image_url = '/end-ready.png';
  assert.deepEqual(
    getRequiredMissingCanonicalVisualStates(plan).map((state) => state.index),
    [2, 4],
  );
});

test('J: canonical adjacent transitions come from plan.transitions', () => {
  const plan = {
    ...makeCanonicalPlan(3),
    window_plans: [{
      from_keyframe_index: 99,
      to_keyframe_index: 100,
      transition_description: 'Legacy window transition',
    }],
  };
  const adjacent = getAdjacentCanonicalTransitions(plan, 2);
  assert.equal(adjacent.previous?.transition_description, 'Transition 1');
  assert.equal(adjacent.next?.transition_description, 'Transition 2');
});

test('K: canonical path cannot use legacy shot generation fallback', () => {
  assert.equal(canUseLegacyShotGeneration(makeCanonicalPlan(3)), false);
  assert.equal(canUseLegacyShotGeneration({}), true);
});

test('historical noncanonical plan can retain automatic legacy #07 behavior', () => {
  assert.equal(shouldAutoRecommendLegacyVideoMode({}, 'shot-1', null), true);
  assert.equal(shouldAutoRecommendLegacyVideoMode({ recommended_mode: 'MULTI_KEYFRAME' }, 'shot-1', null), false);
  assert.equal(shouldAutoRecommendLegacyVideoMode({}, 'shot-1', 'shot-1'), false);
});

test('canonical ordinary Shot save never sends a browser-held full plan snapshot', () => {
  const canonical = buildVideoDirectorShotSavePayload({
    id: 'shot-1',
    video_description: 'motion',
    duration: 24,
    videoDirectorPlan: makeCanonicalPlan(5),
  });
  assert.deepEqual(canonical, { id: 'shot-1', video_description: 'motion', duration: 24 });
  assert.equal('video_director_plan' in canonical, false);

  const historicalPlan = { selected_mode: 'SINGLE_FRAME' };
  const historical = buildVideoDirectorShotSavePayload({ id: 'shot-2', videoDirectorPlan: historicalPlan });
  assert.equal(historical.video_director_plan, historicalPlan);
});
