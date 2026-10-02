import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const componentUrl = new URL('../src/pages/ChapterGenerate/components/VideoGenTab.tsx', import.meta.url);
const source = await readFile(componentUrl, 'utf8');
const semanticStart = source.indexOf('function SemanticClipExecutionPanel(');
const semanticEnd = source.indexOf('\ntype VideoPromptDraft', semanticStart);
const semanticSource = source.slice(semanticStart, semanticEnd);
const directorStart = source.indexOf('function VideoDirectorPanel(');
const directorEnd = source.indexOf('\nexport function VideoGenTab(', directorStart);
const directorSource = source.slice(directorStart, directorEnd);
const debugStart = source.indexOf('function VideoAiCallsPanel(');
const debugEnd = source.indexOf('\nfunction VideoPromptModal(', debugStart);
const debugSource = source.slice(debugStart, debugEnd);

test('canonical Visual State actions distinguish first generation from regeneration', () => {
  assert.match(directorSource, /selectedKeyframeImageUrl \? '重新生成状态图片' : '生成状态图片'/);
  assert.match(directorSource, /selectedKeyframeImageUrl \? '使用当前提示词重新生成状态图片' : '使用当前提示词生成状态图片'/);
  assert.match(directorSource, /onGenerateKeyframe\(selectedKeyframeFrameIndex, 'llm'\)/);
  assert.match(directorSource, /onGenerateKeyframe\(selectedKeyframeFrameIndex, 'image_only'\)/);
  assert.match(directorSource, /aria-label=\{isCanonicalPlan \? '选择状态图片生成方式' : '选择关键帧生成模式'\}/);
});

test('canonical Clip actions use current artifact state and preserve both handlers', () => {
  assert.match(semanticSource, /const hasCurrentClipArtifact = clipStatus === 'COMPLETED'/);
  assert.match(semanticSource, /hasCurrentClipArtifact \? '重新生成片段' : '生成片段'/);
  assert.match(semanticSource, /hasCurrentClipArtifact \? '使用当前提示词重新生成' : '使用当前提示词生成'/);
  assert.match(semanticSource, /onRegenerateClip\(\{ \.\.\.clip, clip_index: clip\.clip_index \}, 'llm'\)/);
  assert.match(semanticSource, /onRegenerateClip\(\{ \.\.\.clip, clip_index: clip\.clip_index \}, 'video_only'\)/);
  assert.doesNotMatch(semanticSource, /LLM\+|CLIP_ONLY|#1[123]/);
});

test('canonical assembly language follows current assembly authority', () => {
  assert.match(semanticSource, /shotStatus === 'CLIPS_COMPLETE'/);
  assert.match(semanticSource, /正在合并最终视频\.\.\.[\s\S]*合并最终视频/);
  assert.match(semanticSource, /currentAssembly[\s\S]*播放最终 Shot/);
  assert.match(source, /currentSemanticShotStatus === 'CLIPS_COMPLETE'[\s\S]*label: '合并最终视频'/);
});

test('canonical recovery stays narrow and broad reset remains noncanonical-only', () => {
  assert.match(source, /\{!currentIsCanonicalPlan && \(\s*<button[\s\S]*?重置视频阶段/);
  assert.equal((source.match(/重置视频阶段/g) ?? []).length, 1);
  assert.match(source, /重新生成状态图片/);
  assert.match(source, /重新生成片段/);
});

test('debug export keeps its handler and engineering diagnostics', () => {
  assert.match(debugSource, /onClick=\{handleDownloadLlmData\}/);
  assert.match(debugSource, /导出调试数据/);
  assert.match(debugSource, /call\.response/);
  assert.match(debugSource, /call\.parsed_result/);
  assert.match(semanticSource, /Revision \{revision\}/);
  assert.match(semanticSource, /AUTO_APPROVE/);
  assert.match(semanticSource, /Previous AV/);
});

test('download material actions and shared Batch authority remain untouched', () => {
  assert.match(source, /handleDownloadMaterials\(\)/);
  assert.match(source, /handleDownloadVideoMaterials\(\)/);
  assert.match(source, /导出章节素材包/);
  assert.match(source, /导出 Shot 生产包/);
  assert.match(source, /buildSemanticBatchRequest\(selectedShotIds, autoAssemble\)/);
  assert.match(source, /showBatchSelectModal && createPortal/);
});
