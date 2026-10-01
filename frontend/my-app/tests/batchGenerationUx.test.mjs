import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const authorityUrl = new URL('../src/pages/ChapterGenerate/semanticClipAuthority.ts', import.meta.url);
const authoritySource = await readFile(authorityUrl, 'utf8');
const { outputText } = ts.transpileModule(authoritySource, {
  compilerOptions: { module: ts.ModuleKind.ES2020, target: ts.ScriptTarget.ES2020 },
});
const authorityModuleUrl = `data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`;
const {
  getBatchShotStatusProjection,
  getCurrentSemanticExecutionState,
  getSelectableBatchShotIndexes,
  hasLegacyBatchPlanningState,
  reconcileBatchSelection,
  shouldShowLegacyBatchCompatibility,
} = await import(authorityModuleUrl);

const readyEligibility = { selectable: true, reason: '可执行语义视频片段' };
const blockedEligibility = (reason) => ({ selectable: false, reason });

test('status classification projects authoritative ready, completed, and missing-preparation states', () => {
  assert.deepEqual(getBatchShotStatusProjection({ eligibility: readyEligibility }), {
    category: 'ready', selectable: true, reason: '可执行语义视频片段', retry: false,
  });
  assert.equal(getBatchShotStatusProjection({ eligibility: blockedEligibility('当前版本已完成'), isCompleted: true }).category, 'completed');
  assert.deepEqual(
    getBatchShotStatusProjection({ eligibility: blockedEligibility('缺少主分镜图') }),
    { category: 'missing_preparation', selectable: false, reason: '缺少主分镜图', retry: false },
  );
  assert.equal(
    getBatchShotStatusProjection({ eligibility: blockedEligibility('请先规划视频片段') }).category,
    'missing_preparation',
  );
});

test('execution classifications distinguish running, queued, and retryable failure', () => {
  assert.equal(getBatchShotStatusProjection({ eligibility: readyEligibility, isGenerating: true }).category, 'generating');
  assert.equal(getBatchShotStatusProjection({ eligibility: readyEligibility, isQueued: true }).category, 'queued');
  assert.deepEqual(
    getBatchShotStatusProjection({ eligibility: readyEligibility, isFailed: true, failureReason: 'workflow failed' }),
    { category: 'failed', selectable: true, reason: 'workflow failed', retry: true },
  );
  assert.equal(
    getBatchShotStatusProjection({ eligibility: blockedEligibility('缺少主分镜图'), isFailed: true }).selectable,
    false,
  );
});

test('category precedence is generating, queued, failed, completed, ready, then missing preparation', () => {
  assert.equal(getBatchShotStatusProjection({ eligibility: readyEligibility, isGenerating: true, isQueued: true, isFailed: true, isCompleted: true }).category, 'generating');
  assert.equal(getBatchShotStatusProjection({ eligibility: readyEligibility, isQueued: true, isFailed: true, isCompleted: true }).category, 'queued');
  assert.equal(getBatchShotStatusProjection({ eligibility: readyEligibility, isFailed: true, isCompleted: true }).category, 'failed');
  assert.equal(getBatchShotStatusProjection({ eligibility: readyEligibility, isCompleted: true }).category, 'completed');
});

test('current semantic execution flags use only exact current-revision Clip tasks', () => {
  const plan = {
    clip_plan_revision: 4,
    clip_plan: [
      { clip_index: 1 },
      { clip_index: 2 },
      { clip_index: 3 },
    ],
  };
  const tasks = [
    { id: 'running', status: 'running', clipExecution: { execution_scope: 'CLIP', clip_plan_revision: 4, clip_index: 1 } },
    { id: 'queued', status: 'queued', clipExecution: { execution_scope: 'CLIP', clip_plan_revision: 4, clip_index: 2 } },
    { id: 'failed', status: 'failed', error_message: 'bad input', clipExecution: { execution_scope: 'CLIP', clip_plan_revision: 4, clip_index: 3 } },
    { id: 'stale', status: 'failed', error_message: 'stale error', clipExecution: { execution_scope: 'CLIP', clip_plan_revision: 3, clip_index: 1 } },
  ];
  assert.deepEqual(getCurrentSemanticExecutionState(plan, tasks), {
    isGenerating: true,
    isQueued: true,
    isFailed: true,
    failureReason: 'bad input',
  });
});

test('selection never includes blocked, running, queued, or completed Shots', () => {
  const items = [
    { shotIndex: 1, category: 'ready', selectable: true },
    { shotIndex: 2, category: 'missing_preparation', selectable: false },
    { shotIndex: 3, category: 'generating', selectable: false },
    { shotIndex: 4, category: 'queued', selectable: false },
    { shotIndex: 5, category: 'completed', selectable: false },
    { shotIndex: 6, category: 'failed', selectable: true },
  ];
  assert.deepEqual(reconcileBatchSelection([1, 2, 3, 4, 5, 6], items), [1, 6]);
  assert.deepEqual(getSelectableBatchShotIndexes(items, 'ready'), [1]);
  assert.deepEqual(getSelectableBatchShotIndexes(items, 'failed'), [6]);
  assert.deepEqual(getSelectableBatchShotIndexes(items, 'missing_preparation'), []);
});

test('select-all is scoped to the current filter and filter changes do not select blocked Shots', () => {
  const items = [
    { shotIndex: 1, category: 'ready', selectable: true },
    { shotIndex: 2, category: 'ready', selectable: true },
    { shotIndex: 3, category: 'missing_preparation', selectable: false },
    { shotIndex: 4, category: 'failed', selectable: true },
  ];
  assert.deepEqual(getSelectableBatchShotIndexes(items, 'ready'), [1, 2]);
  assert.deepEqual(getSelectableBatchShotIndexes(items, 'all'), [1, 2, 4]);
  assert.deepEqual(getSelectableBatchShotIndexes(items, 'missing_preparation'), []);
  assert.equal(reconcileBatchSelection([1, 2, 3], items).length, 2, 'CTA count follows executable selection only');
});

test('legacy compatibility is hidden for canonical-only context and detected for legacy/mixed context', () => {
  const canonical = [{ shotIndex: 1, category: 'ready', selectable: true, isLegacy: false }];
  const mixed = [...canonical, { shotIndex: 2, category: 'ready', selectable: true, isLegacy: true }];
  assert.equal(shouldShowLegacyBatchCompatibility(canonical), false);
  assert.equal(shouldShowLegacyBatchCompatibility(mixed), true);
  assert.equal(hasLegacyBatchPlanningState({}), false, 'an unprepared empty plan is not historical legacy context');
  assert.equal(hasLegacyBatchPlanningState({ canonical_visual_plan: true, selected_mode: 'SINGLE_FRAME' }), false);
  assert.equal(hasLegacyBatchPlanningState({ selected_mode: 'MULTI_KEYFRAME', window_plans: [{ window_index: 1 }] }), true);
});

test('legacy auto-detail control is nested under the advanced compatibility section', async () => {
  const componentUrl = new URL('../src/pages/ChapterGenerate/components/VideoGenTab.tsx', import.meta.url);
  const componentSource = await readFile(componentUrl, 'utf8');
  const advancedStart = componentSource.indexOf('<details className="mb-3');
  const advancedEnd = componentSource.indexOf('</details>', advancedStart);
  const controlIndex = componentSource.indexOf('自动完成细节（仅 legacy Shot）');
  assert.ok(advancedStart >= 0 && advancedEnd > advancedStart);
  assert.ok(controlIndex > advancedStart && controlIndex < advancedEnd);
  assert.match(componentSource, /legacyCompatibilityVisible && \(/);
});
