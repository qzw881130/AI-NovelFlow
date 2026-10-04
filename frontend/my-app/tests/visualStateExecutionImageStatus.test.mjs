import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/pages/ChapterGenerate/videoDirectorAuthority.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ES2020 } });
const { getVisualStateExecutionImageStatus: status } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
const state = { index: 2, role: 'INTERMEDIATE', time_seconds: 7.95, timed_visual_target: false };
const plan = () => ({
  canonical_visual_plan: true, clip_plan_revision: 1, clip_plan_validation: { passed: true },
  clip_plan: [{ clip_index: 2, capability: 'EXTEND', continuity_to_previous: 'CONTINUOUS',
    visual_state_indexes: [], carry_in_state_index: 2, requires_temporal_control: false }],
  execution_readiness: { ready: true, blocking_clips: [] },
});

test('C2 carry-in is not a physical dependency and creates no missing-image warning', () => {
  const input = plan();
  const before = structuredClone(input);
  assert.equal(status(state, input), 'NOT_NEEDED');
  assert.equal(status({ ...state, timed_visual_target: true }, input), 'NOT_NEEDED');
  assert.deepEqual(input, before);
});

test('available image is READY, not proof of ownership or physical consumption', () => {
  assert.equal(status(state, plan(), '/state2.png'), 'READY');
  assert.equal(status({ ...state, image_url: '/state2.png' }, plan()), 'READY');
  assert.deepEqual(plan().clip_plan[0].visual_state_indexes, []);
});

test('owned non-timed controls are optional without inventing a new blocker', () => {
  const input = plan();
  input.clip_plan[0].visual_state_indexes = [2];
  assert.equal(status(state, input), 'OPTIONAL_MISSING');
});

test('only backend-projected GENERATE visual-start blocker marks its state required', () => {
  const input = plan();
  input.execution_readiness = { ready: false, blocking_clips: [{ code: 'GENERATE_VISUAL_START_GROUNDING_MISSING',
    clip_index: 3, visual_state_index: 2, ready: false }] };
  assert.equal(status(state, input), 'REQUIRED_MISSING');
  assert.equal(status({ ...state, index: 3 }, input), 'NOT_NEEDED');
  input.execution_readiness = { ready: true, blocking_clips: [] };
  assert.equal(status(state, input), 'NOT_NEEDED');
});

test('owned timed TEMPORAL_EXTEND target needs image; carry-in or ordinary state does not', () => {
  const input = plan();
  Object.assign(input.clip_plan[0], { capability: 'TEMPORAL_EXTEND', requires_temporal_control: true, visual_state_indexes: [2] });
  assert.equal(status({ ...state, timed_visual_target: true }, input), 'REQUIRED_MISSING');
  assert.equal(status(state, input), 'OPTIONAL_MISSING');
  input.clip_plan[0].visual_state_indexes = [3];
  assert.equal(status({ ...state, timed_visual_target: true }, input), 'NOT_NEEDED');
});

test('no current valid Clip Plan retains existing preparation classification', () => {
  for (const input of [{}, { ...plan(), clip_plan_validation: { passed: false } }, { ...plan(), clip_plan_revision: 0 }]) {
    assert.equal(status(state, input), 'OPTIONAL_MISSING');
    assert.equal(status({ ...state, timed_visual_target: true }, input), 'REQUIRED_MISSING');
  }
});

test('Visual State cards and selected actions use execution-aware presentation without handler changes', async () => {
  const ui = await readFile(new URL('../src/pages/ChapterGenerate/components/VideoGenTab.tsx', import.meta.url), 'utf8');
  assert.match(ui, /getVisualStateExecutionImageStatus\(selectedKeyframe, plan, selectedKeyframeImageUrl\)/);
  assert.match(ui, /getVisualStateExecutionImageStatus\(kf, plan, keyframeImageUrl\)/);
  assert.match(ui, /selectedStateImageStatus === 'REQUIRED_MISSING' \? '生成必需状态图片'/);
  assert.match(ui, /status === 'NOT_NEEDED'/);
  assert.match(ui, /onGenerateKeyframe\(selectedKeyframeFrameIndex, 'llm'\)/);
  assert.match(ui, /onGenerateKeyframe\(selectedKeyframeFrameIndex, 'image_only'\)/);
  // The concurrent optional-hint UI may remain unstaged; when present it must not mislabel a required state.
  if (ui.includes('可选视觉锚点；仅在需要加强该时刻的构图')) {
    assert.match(ui, /selectedStateImageStatus !== 'REQUIRED_MISSING' && \(\s*<p[^>]*>\s*可选视觉锚点/);
  }
});
