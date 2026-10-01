import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const componentUrl = new URL('../src/pages/ChapterGenerate/components/VideoGenTab.tsx', import.meta.url);
const source = await readFile(componentUrl, 'utf8');
const panelStart = source.indexOf('function VideoDirectorPanel(');
const panelEnd = source.indexOf('\nexport function VideoGenTab(', panelStart);
const panelSource = source.slice(panelStart, panelEnd);
const historicalStart = panelSource.indexOf('if (isHistoricalPlan)');
const missingStart = panelSource.indexOf('if (!isCanonicalPlan)', historicalStart);
const canonicalWorkspaceStart = panelSource.indexOf('return (\n    <>', missingStart);
const historicalSource = panelSource.slice(historicalStart, missingStart);
const missingSource = panelSource.slice(missingStart, canonicalWorkspaceStart);
const canonicalSource = panelSource.slice(canonicalWorkspaceStart);

test('canonical, historical, and missing plans use distinct existing-authority branches', () => {
  assert.match(panelSource, /const isCanonicalPlan = isCanonicalVisualPlan\(plan\)/);
  assert.match(panelSource, /const isHistoricalPlan = !isCanonicalPlan && hasLegacyBatchPlanningState\(plan\)/);
  assert.ok(historicalStart >= 0 && missingStart > historicalStart && canonicalWorkspaceStart > missingStart);
});

test('historical default is a boundary with one explicit canonical replan action', () => {
  assert.match(historicalSource, /data-testid="historical-video-plan-boundary"/);
  assert.match(historicalSource, /使用新版规划重新规划/);
  assert.match(historicalSource, /onClick=\{\(\) => onPlanKeyframes\(true\)\}/);
  assert.doesNotMatch(historicalSource, /onSelectMode|onRecommend\(|onGenerateMissingKeyframes|onMergeClips/);
});

test('historical detail is collapsed read-only inspection without legacy actions', () => {
  assert.match(historicalSource, /<details data-testid="historical-plan-details"/);
  assert.match(historicalSource, /查看旧版规划详情/);
  assert.match(historicalSource, /历史 #07 记录/);
  assert.match(historicalSource, /不能在此选择、保存或执行旧版规划/);
  assert.doesNotMatch(historicalSource, /<details[^>]*\sopen(?:=|\s|>)/);
  assert.match(source, /!currentIsHistoricalPlan && \(\s*<VideoAiCallsPanel/);
});

test('missing plan uses normal initial canonical planning and no historical warning', () => {
  assert.match(missingSource, /data-testid="missing-video-plan-state"/);
  assert.match(missingSource, /onClick=\{\(\) => onPlanKeyframes\(false\)\}/);
  assert.match(missingSource, /规划视觉时间轴/);
  assert.doesNotMatch(missingSource, /旧版视频规划|historical-video-plan-boundary/);
});

test('canonical workspace remains after both boundary returns and refresh has no automatic #07 or #08 call', () => {
  assert.match(canonicalSource, /chapterGenerate\.visualTimeline/);
  assert.match(canonicalSource, /renderModeButton\('SINGLE_FRAME'\)/);
  assert.ok(canonicalWorkspaceStart > missingStart, 'boundary returns prevent legacy selector rendering for historical and missing plans');
  assert.doesNotMatch(source, /shouldAutoRecommendLegacyVideoMode/);
  assert.match(source, /shotsApi\.planVideoKeyframes\(effectiveNovelId, effectiveChapterId, currentShotId, force\)/);
  assert.doesNotMatch(source, /planVideoKeyframes\([^)]*selected_mode|planVideoKeyframes\([^)]*recommended_mode|planVideoKeyframes\([^)]*window_plans/);
});
