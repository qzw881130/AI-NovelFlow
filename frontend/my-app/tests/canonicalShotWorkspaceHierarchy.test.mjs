import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const componentUrl = new URL('../src/pages/ChapterGenerate/components/VideoGenTab.tsx', import.meta.url);
const source = await readFile(componentUrl, 'utf8');
const semanticPanelStart = source.indexOf('function SemanticClipExecutionPanel(');
const semanticPanelEnd = source.indexOf('\ntype VideoPromptDraft', semanticPanelStart);
const semanticPanelSource = source.slice(semanticPanelStart, semanticPanelEnd);
const directorStart = source.indexOf('function VideoDirectorPanel(');
const directorEnd = source.indexOf('\nexport function VideoGenTab(', directorStart);
const directorSource = source.slice(directorStart, directorEnd);
const advancedStart = directorSource.indexOf('data-testid="advanced-director-details"');
const advancedEnd = directorSource.indexOf('{viewingPromptClip?.prompt_text', advancedStart);
const advancedSource = directorSource.slice(advancedStart, advancedEnd);
const productionStart = directorSource.indexOf('data-testid="canonical-execution-summary"');
const productionSource = directorSource.slice(productionStart, advancedStart);
const debugStart = source.indexOf('function VideoAiCallsPanel(');
const debugEnd = source.indexOf('\nfunction VideoPromptModal(', debugStart);
const debugSource = source.slice(debugStart, debugEnd);

test('canonical workspace exposes Production, Advanced Director, and Debug Inspector levels', () => {
  assert.match(source, /data-testid="canonical-production-header"/);
  assert.match(source, /data-testid="canonical-execution-summary"/);
  assert.ok(advancedStart >= 0);
  assert.match(debugSource, /data-testid="debug-inspector"/);
});

test('Advanced Director is controlled by local presentation state and defaults collapsed', () => {
  assert.match(directorSource, /useState\(false\).*isAdvancedDirectorOpen|\[isAdvancedDirectorOpen, setIsAdvancedDirectorOpen\] = useState\(false\)/s);
  assert.match(advancedSource, /open=\{isAdvancedDirectorOpen\}/);
  assert.match(directorSource, /setIsAdvancedDirectorOpen\(false\)/);
});

test('Debug Inspector defaults collapsed and resets when the Shot changes', () => {
  assert.match(debugSource, /\[panelOpen, setPanelOpen\] = useState\(false\)/);
  assert.match(debugSource, /\[expanded, setExpanded\] = useState\(false\)/);
  assert.match(debugSource, /setPanelOpen\(false\)[\s\S]*setExpanded\(false\)[\s\S]*\}, \[shotId\]\)/);
});

test('current authoritative Final Shot is the default preview target', () => {
  assert.match(source, /hasCurrentAssembly\(currentVideoDirectorPlan, semanticClipTasks\)/);
  assert.match(source, /const previewVideoUrl = selectedPreviewClipUrl \|\| selectedPreviewClip\?\.video_url \|\| currentFinalShotVideoUrl/);
  assert.match(source, /selectedPreviewClip \? `片段预览 · \$\{previewVideoLabel\}` : '最终 Shot 视频'/);
  assert.match(source, /setSelectedPreviewClipKey\(null\)[\s\S]*setSelectedPreviewClipUrl\(null\)[\s\S]*\}, \[currentShotId\]\)/);
});

test('individual Clip preview remains reachable only through Advanced Director controls', () => {
  assert.match(advancedSource, /查看片段预览、恢复与对话分配/);
  assert.match(advancedSource, /onPreviewClip=\{onPreviewClip\}/);
  assert.match(semanticPanelSource, /播放片段 \{clip\.clip_index\}/);
  assert.doesNotMatch(source, />\s*Shot 成片\s*</);
});

test('engineering Clip metadata is absent from default Production and retained under diagnostics', () => {
  assert.doesNotMatch(productionSource, /Revision|AUTO_APPROVE|PASS|generated_by_task_id|CLIP_ONLY/);
  assert.match(semanticPanelSource, /data-testid="semantic-clip-debug-metadata"/);
  assert.match(semanticPanelSource, /Revision \{revision\}/);
  assert.match(semanticPanelSource, /AUTO_APPROVE/);
  assert.match(semanticPanelSource, /'PASS'/);
});

test('optional image-less Visual States remain an explicit non-blocking Production warning', () => {
  assert.match(source, /classifyVisualStateImageStatus\(state, getVideoDirectorKeyframeImageUrl\(currentShotData, state\)\) === 'OPTIONAL_MISSING'/);
  assert.match(source, /个可选图片缺失（不阻塞片段规划）/);
  assert.match(source, /currentCanonicalReadiness\.state === 'REQUIRED_IMAGES_MISSING'/);
});

test('missing Clip Plan maps the primary action to the existing Clip planning handler', () => {
  assert.match(source, /currentCanonicalReadiness\.state === 'CLIP_PLAN_MISSING' \|\| currentCanonicalReadiness\.state === 'CLIP_PLAN_STALE'/);
  assert.match(source, /label: isStale \? '重新规划视频片段' : '规划视频片段'/);
  assert.match(source, /onClick: \(\) => handlePlanSemanticClips\(isStale\)/);
});

test('presentation reuses the frozen readiness and semantic execution authorities', () => {
  assert.match(source, /getCanonicalSemanticReadiness\(/);
  assert.match(source, /getSemanticShotStatusFromPlan\(currentVideoDirectorPlan, semanticClipTasks\)/);
  assert.match(source, /hasCurrentAssembly\(currentVideoDirectorPlan, semanticClipTasks\)/);
  assert.doesNotMatch(source, /function (?:calculate|derive|compute)CanonicalReadiness/);
});

test('actionable failure remains in Production while raw AI diagnostics remain under Debug', () => {
  assert.match(source, /\{currentVideoErrorMessage && \(/);
  assert.match(source, /视频生成失败/);
  assert.match(debugSource, /个失败/);
  assert.match(debugSource, /call\.response/);
  assert.match(debugSource, /call\.parsed_result/);
});

test('historical-plan boundary remains an isolated early-return branch', () => {
  const historicalStart = directorSource.indexOf('if (isHistoricalPlan)');
  const missingStart = directorSource.indexOf('if (!isCanonicalPlan)', historicalStart);
  const historicalSource = directorSource.slice(historicalStart, missingStart);
  assert.match(historicalSource, /data-testid="historical-video-plan-boundary"/);
  assert.match(historicalSource, /使用新版规划重新规划/);
  assert.doesNotMatch(historicalSource, /canonical-production-header|advanced-director-details/);
});

test('H-2 Batch authority and modal remain isolated from the hierarchy projection', () => {
  assert.match(source, /getBatchShotStatusProjection\(/);
  assert.match(source, /buildSemanticBatchRequest\(selectedShotIds, autoAssemble\)/);
  assert.match(source, /showBatchSelectModal && createPortal/);
  assert.match(source, /批量生成视频/);
});
