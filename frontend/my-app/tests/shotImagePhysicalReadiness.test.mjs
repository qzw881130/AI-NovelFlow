import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const componentUrl = new URL('../src/pages/ChapterGenerate/components/ShotImageGenTab.tsx', import.meta.url);
const generationSliceUrl = new URL('../src/pages/ChapterGenerate/stores/slices/generationSlice.ts', import.meta.url);
const shotsApiUrl = new URL('../src/api/shots.ts', import.meta.url);
const componentSource = await readFile(componentUrl, 'utf8');
const generationSource = await readFile(generationSliceUrl, 'utf8');
const apiSource = await readFile(shotsApiUrl, 'utf8');

test('zero-reference Shot exposes preparation guidance and blocks generation actions', () => {
  assert.match(componentSource, /availableReferenceCount === 0/);
  assert.match(componentSource, /data-testid="shot-image-reference-blocker"/);
  assert.match(componentSource, /主分镜参考素材未准备/);
  assert.match(componentSource, /请先准备至少一个角色、场景或道具参考图片/);
  assert.match(componentSource, /disabled=\{isGeneratingCurrent \|\| physicalReferencesBlocked/);
  assert.match(componentSource, /if \(physicalReferencesBlocked\) return/);
});

test('missing resource details are dynamic and partial references stay executable', () => {
  assert.match(componentSource, /missingCharacters\.join\('、'\)/);
  assert.match(componentSource, /missingScenes\.join\('、'\)/);
  assert.match(componentSource, /missingProps\.join\('、'\)/);
  assert.match(componentSource, /availableReferenceCount = Number\(boundCharacters\.length > missingCharacters\.length\)/);
  assert.match(componentSource, /\+ Number\(Boolean\(shot\?\.scene\) && missingScenes\.length === 0\)/);
  assert.match(componentSource, /\+ Number\(boundRealProps\.length > missingProps\.length\)/);
  assert.match(componentSource, /data-testid="shot-image-reference-warning"/);
  assert.match(componentSource, /仍可生成/);
});

test('batch selection cannot make zero-reference work look runnable', () => {
  assert.match(componentSource, /selectableShotIds = shots[\s\S]*!getShotImagePhysicalReadiness\(shot, characters, scenes, props\)\.hardBlocked/);
  assert.match(componentSource, /isReferenceBlocked \? '缺少参考'/);
});

test('backend rejection preserves the previous image and structured error message', () => {
  assert.match(generationSource, /const previousShot = \{ \.\.\.shot \}/);
  assert.match(generationSource, /后端确认任务创建前保留当前主分镜图/);
  assert.match(generationSource, /s\.id === shotId \? previousShot : s/);
  assert.match(apiSource, /typeof result\.detail === 'object' \? result\.detail\?\.message : result\.detail/);
});

test('refreshed failed Shot has a retryable failure state instead of a spinner', () => {
  assert.match(componentSource, /currentShotObj\?\.imageStatus === 'failed'/);
  assert.match(componentSource, /data-testid="shot-image-failed-state"/);
  assert.match(componentSource, /准备好参考素材后可重新生成/);
});
