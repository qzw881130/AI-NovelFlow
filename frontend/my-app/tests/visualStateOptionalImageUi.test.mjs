import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const componentUrl = new URL('../src/pages/ChapterGenerate/components/VideoGenTab.tsx', import.meta.url);
const zhCnUrl = new URL('../src/i18n/locales/zh-CN/chapters.ts', import.meta.url);
const source = await readFile(componentUrl, 'utf8');
const zhCnSource = await readFile(zhCnUrl, 'utf8');
const directorStart = source.indexOf('function VideoDirectorPanel(');
const directorEnd = source.indexOf('\nexport function VideoGenTab(', directorStart);
const directorSource = source.slice(directorStart, directorEnd);

test('image-less canonical Visual States use neutral optional-image language', () => {
  assert.match(zhCnSource, /visualStateOptionalMissing: '状态图：可选 · 未生成'/);
  assert.match(zhCnSource, /optionalMissingStates: '状态图：可选 · 未生成 \{count\} 张'/);
  assert.doesNotMatch(zhCnSource, /visualStateOptionalMissing: '可选图片缺失'/);
  assert.doesNotMatch(directorSource, /个可选图片缺失/);
});

test('single-state generation is optional while existing-image regeneration remains intact', () => {
  assert.match(directorSource, /selectedKeyframeImageUrl \? '重新生成状态图片' : '生成可选状态图'/);
  assert.match(directorSource, /selectedKeyframeImageUrl \? '使用当前提示词重新生成状态图片' : '使用当前提示词生成可选状态图'/);
  assert.match(directorSource, /可选视觉锚点；仅在需要加强该时刻的构图、人物、道具或状态控制时生成。/);
  assert.match(directorSource, /onGenerateKeyframe\(selectedKeyframeFrameIndex, 'llm'\)/);
  assert.match(directorSource, /onGenerateKeyframe\(selectedKeyframeFrameIndex, 'image_only'\)/);
});

test('START continues to reuse the Shot main image instead of becoming a missing state image', () => {
  assert.match(directorSource, /if \(kf\.role === 'START'\) return shotImageUrl \|\| null/);
  assert.match(directorSource, /selectedKeyframe\?\.role !== 'START'/);
  assert.match(directorSource, /selectedKeyframeImageUrl[\s\S]*t\('chapterGenerate\.imageReady'\)/);
});

test('batch CTA prepares required images while optional single-state generation stays available', () => {
  assert.match(directorSource, /'批量生成可选状态图'/);
  assert.match(directorSource, /onClick=\{onGenerateMissingKeyframes\}/);
  assert.match(directorSource, /只准备当前 Clip 计划的执行必需图片；已有图片复用，活跃任务等待，其余缺失图片继续提交。/);
  assert.match(directorSource, /isCanonicalPlan \? 'border-gray-300 bg-white text-gray-700 hover:bg-gray-50'/);
});

test('planning help is explicit and readiness authority remains unchanged', () => {
  assert.match(zhCnSource, /visualTimelineHint: '视觉状态是导演规划节点，不要求每个状态都生成图片。状态图用于需要额外视觉控制的时刻。'/);
  assert.match(directorSource, /getCanonicalSemanticReadiness\(plan, getKeyframeImageUrl\)/);
  assert.doesNotMatch(directorSource, /image_requirement|requires_image|image_required|should_generate_image/);
});
