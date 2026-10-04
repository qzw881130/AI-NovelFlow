import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const sourceUrl = new URL('../src/pages/ChapterGenerate/semanticClipAuthority.ts', import.meta.url);
const source = await readFile(sourceUrl, 'utf8');
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ES2020, target: ts.ScriptTarget.ES2020 },
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`;
const {
  CANONICAL_EXECUTION_AUTHORITY,
  buildSemanticBatchRequest,
  getCanonicalBatchEligibility,
  getCanonicalSemanticReadiness,
  getCarryInLabel,
  getOwnedVisualStateLabel,
  getSemanticCapabilityLabel,
  getSemanticClipStatus,
  getSemanticContinuityLabel,
  getSemanticShotStatusFromPlan,
  resolveSemanticClipTask,
} = await import(moduleUrl);

const keyframes = [
  { index: 1, time_seconds: 0, role: 'START', timed_visual_target: false },
  { index: 2, time_seconds: 8, role: 'INTERMEDIATE', timed_visual_target: true, image_url: '/kf2.png' },
  { index: 3, time_seconds: 16, role: 'END', timed_visual_target: false },
];

const clips = [
  { clip_index: 1, start_time: 0, end_time: 8, capability: 'GENERATE', continuity_to_previous: 'NONE', visual_state_indexes: [1, 2] },
  { clip_index: 2, start_time: 8, end_time: 16, capability: 'EXTEND', continuity_to_previous: 'CONTINUOUS', previous_clip_index: 1, visual_state_indexes: [3], carry_in_state_index: 2 },
];

const readyPlan = () => ({
  canonical_visual_plan: true,
  keyframes: structuredClone(keyframes),
  clip_plan: structuredClone(clips),
  clip_plan_revision: 2,
  clip_plan_validation: { passed: true, temporal_contract: 'ELIGIBLE_THEN_SELECTED_V1' },
});

const completedClip = (clip, taskId) => ({
  ...clip,
  generated_by_task_id: taskId,
  video_url: `/clips/${taskId}.mp4`,
  execution_status: 'APPROVED',
  status: 'SUCCEEDED',
});

test('A0: no canonical Visual Plan blocks planning and execution', () => {
  const readiness = getCanonicalSemanticReadiness({});
  assert.equal(readiness.state, 'NO_VISUAL_PLAN');
  assert.equal(readiness.planningAllowed, false);
  assert.equal(readiness.executionAllowed, false);
});

test('A: canonical visual plan without clip plan cannot execute', () => {
  const readiness = getCanonicalSemanticReadiness({ canonical_visual_plan: true, keyframes });
  assert.equal(readiness.state, 'CLIP_PLAN_MISSING');
  assert.equal(readiness.planningAllowed, true);
  assert.equal(readiness.executionAllowed, false);
});

test('B: missing eligible images do not block planning', () => {
  const plan = { canonical_visual_plan: true, keyframes: structuredClone(keyframes) };
  delete plan.keyframes[1].image_url;
  const readiness = getCanonicalSemanticReadiness(plan);
  assert.equal(readiness.state, 'CLIP_PLAN_MISSING');
  assert.deepEqual(readiness.requiredMissingIndexes, []);
  assert.equal(readiness.planningAllowed, true);
});

test('unmarked historical plans remain readable but require explicit replan before execution', () => {
  const plan = readyPlan();
  delete plan.clip_plan_validation.temporal_contract;
  const before = structuredClone(plan);
  assert.equal(getCanonicalSemanticReadiness(plan).state, 'CLIP_PLAN_STALE');
  assert.equal(getCanonicalSemanticReadiness(plan).planningAllowed, true);
  assert.equal(getCanonicalBatchEligibility(plan).selectable, false);
  assert.deepEqual(plan, before);
});

test('backend selected missing-image projection blocks only execution', () => {
  const plan = readyPlan();
  plan.execution_readiness = { ready: false, code: 'TEMPORAL_ANCHOR_UNAVAILABLE',
    blocking_clips: [{ready: false, code: 'TEMPORAL_ANCHOR_UNAVAILABLE', clip_index: 2, visual_state_index: 3}] };
  const result = getCanonicalSemanticReadiness(plan);
  assert.equal(result.state, 'REQUIRED_IMAGES_MISSING');
  assert.equal(result.planningAllowed, true);
  assert.equal(result.executionAllowed, false);
  assert.deepEqual(result.requiredMissingIndexes, [3]);
});

test('C: an optional missing ordinary state does not block semantic readiness', () => {
  const readiness = getCanonicalSemanticReadiness(readyPlan());
  assert.equal(readiness.state, 'READY');
  assert.equal(readiness.executionAllowed, true);
});

test('C2: backend visual-start readiness blocks execution and identifies the existing state-image action target', () => {
  const plan = readyPlan();
  plan.execution_readiness = {
    ready: false,
    code: 'GENERATE_VISUAL_START_GROUNDING_MISSING',
    message: '缺少片段起始视觉图：Clip 2 · 视觉状态 4（9.5s）',
    blocking_clips: [{
      ready: false,
      code: 'GENERATE_VISUAL_START_GROUNDING_MISSING',
      message: '缺少片段起始视觉图：Clip 2 · 视觉状态 4（9.5s）',
      clip_index: 2,
      visual_state_index: 4,
      time_seconds: 9.5,
    }],
  };
  const readiness = getCanonicalSemanticReadiness(plan);
  assert.equal(readiness.state, 'GENERATE_VISUAL_START_MISSING');
  assert.equal(readiness.executionAllowed, false);
  assert.equal(readiness.planningAllowed, true);
  assert.equal(readiness.missingClipIndex, 2);
  assert.equal(readiness.missingVisualStateIndex, 4);
  assert.equal(readiness.missingTimeSeconds, 9.5);
  assert.equal(readiness.reason, '缺少片段起始视觉图：Clip 2 · 视觉状态 4（9.5s）');

  const eligibility = getCanonicalBatchEligibility(plan);
  assert.equal(eligibility.selectable, false);
  assert.equal(eligibility.reason, readiness.reason);
});

test('D: arbitrary clip counts derive without a fixed frontend limit', () => {
  const plan = readyPlan();
  plan.clip_plan = Array.from({ length: 8 }, (_, index) => ({
    clip_index: index + 1,
    start_time: index * 2,
    end_time: index * 2 + 2,
    capability: index === 0 ? 'GENERATE' : 'EXTEND',
    continuity_to_previous: index === 0 ? 'NONE' : 'CONTINUOUS',
    visual_state_indexes: [index + 1],
  }));
  assert.equal(getCanonicalSemanticReadiness(plan).state, 'READY');
  assert.equal(plan.clip_plan.length, 8);
  assert.equal(getSemanticShotStatusFromPlan(plan), 'NOT_STARTED');
});

test('E-F: ownership uses visual_state_indexes and keeps carry-in separate', () => {
  const clip = { ...clips[1], keyframe_indexes: [2, 99] };
  assert.equal(getOwnedVisualStateLabel(clip), 'KF3');
  assert.equal(getCarryInLabel(clip), '接续 C1 · 承接视觉状态 KF2');
  assert.equal(getOwnedVisualStateLabel(clip).includes('KF2'), false);
});

test('G: capability and continuity labels are friendly and read-only', () => {
  assert.equal(getSemanticCapabilityLabel('GENERATE'), '独立生成');
  assert.equal(getSemanticCapabilityLabel('EXTEND'), '连续续生成');
  assert.equal(getSemanticCapabilityLabel('TEMPORAL_EXTEND'), '定时目标续生成');
  assert.equal(getSemanticContinuityLabel('NONE'), '独立开始');
  assert.equal(getSemanticContinuityLabel('CONTINUOUS'), '连续衔接');
});

test('H: single-shot canonical execution builds the shared semantic batch request', () => {
  const request = buildSemanticBatchRequest(['shot-1'], true);
  const batchRequest = buildSemanticBatchRequest(['shot-1', 'shot-2'], true);
  assert.equal(CANONICAL_EXECUTION_AUTHORITY, 'SEMANTIC_BATCH');
  assert.deepEqual(request.shot_ids, ['shot-1']);
  assert.deepEqual(
    { ...request, shot_ids: undefined },
    { ...batchRequest, shot_ids: undefined },
  );
  assert.equal(request.force_rerun, false);
  assert.equal(request.auto_assemble, true);
});

test('I-J: canonical batch never downgrades and becomes eligible with a valid clip plan', () => {
  const missing = getCanonicalBatchEligibility({ canonical_visual_plan: true, keyframes });
  assert.equal(missing.selectable, false);
  assert.equal(missing.reason, '请先规划视频片段');
  assert.equal(missing.authority, 'SEMANTIC_BATCH');

  const ready = getCanonicalBatchEligibility(readyPlan());
  assert.equal(ready.selectable, true);
  assert.equal(ready.authority, 'SEMANTIC_BATCH');
});

test('K: task resolution prefers exact generated_by_task_id provenance', () => {
  const clip = { ...clips[0], generated_by_task_id: 'exact' };
  const tasks = [
    { id: 'newer', status: 'completed', created_at: '2026-10-02', clipExecution: { execution_scope: 'CLIP', clip_index: 1, clip_plan_revision: 2 } },
    { id: 'exact', status: 'completed', created_at: '2026-10-01', clipExecution: { execution_scope: 'CLIP', clip_index: 1, clip_plan_revision: 2 } },
  ];
  assert.equal(resolveSemanticClipTask(clip, tasks, 2)?.id, 'exact');
});

test('L: task fallback rejects stale revisions', () => {
  const staleTask = { id: 'stale', status: 'completed', created_at: '2026-10-02', clipExecution: { execution_scope: 'CLIP', clip_index: 1, clip_plan_revision: 1 } };
  const currentTask = { id: 'current', status: 'completed', created_at: '2026-10-01', clipExecution: { execution_scope: 'CLIP', clip_index: 1, clip_plan_revision: 2 } };
  assert.equal(resolveSemanticClipTask(clips[0], [staleTask, currentTask], 2)?.id, 'current');
  assert.equal(resolveSemanticClipTask({ ...clips[0], generated_by_task_id: 'stale' }, [staleTask, currentTask], 2), undefined);
});

test('M: partial and completed clip artifacts derive assembly readiness', () => {
  const partial = readyPlan();
  partial.clip_plan = [completedClip(clips[0], 't1'), clips[1]];
  assert.equal(getSemanticClipStatus(partial.clip_plan[0], [], 2), 'COMPLETED');
  assert.equal(getSemanticShotStatusFromPlan(partial), 'PARTIAL');

  partial.clip_plan = [completedClip(clips[0], 't1'), completedClip(clips[1], 't2')];
  assert.equal(getSemanticShotStatusFromPlan(partial), 'CLIPS_COMPLETE');
});

test('N: current final assembly derives final-complete state', () => {
  const plan = readyPlan();
  plan.clip_plan = [completedClip(clips[0], 't1'), completedClip(clips[1], 't2')];
  plan.assembly_status = 'COMPLETED';
  plan.assembly_clip_plan_revision = 2;
  plan.assembly_task_ids = ['t1', 't2'];
  plan.merged_video_url = '/final.mp4';
  assert.equal(getSemanticShotStatusFromPlan(plan), 'ASSEMBLED');
});

test('N2: completed Clip artifacts are not promoted to final Shot completion', () => {
  const plan = readyPlan();
  plan.clip_plan = [completedClip(clips[0], 't1'), completedClip(clips[1], 't2')];
  plan.merged_video_url = plan.clip_plan[1].video_url;
  assert.equal(getSemanticShotStatusFromPlan(plan), 'CLIPS_COMPLETE');
});

test('O: canonical semantic execution request contains no legacy authority fields', () => {
  const request = buildSemanticBatchRequest(['shot-1']);
  assert.equal('selected_mode' in request, false);
  assert.equal('recommended_mode' in request, false);
  assert.equal('window_plans' in request, false);
  assert.equal('generate_video' in request, false);
});
