import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const sourceUrl = new URL('../src/pages/ChapterGenerate/components/ChapterGenerateLayout.tsx', import.meta.url);
const source = await readFile(sourceUrl, 'utf8');

test('Chapter Generate status content participates in responsive document layout', () => {
  assert.equal(source.includes('absolute left-1/2 top-1 -translate-x-1/2'), false);
  assert.equal(source.includes('absolute right-0 top-1'), false);
  assert.match(source, /const headerContextStats = renderDialogueWarningStats\(\);/);
  assert.match(source, /mt-1 flex flex-wrap items-center justify-between gap-2/);
});

test('video statistics live in chapter header; tabs retain other status sources', () => {
  const header = source.slice(source.indexOf('data-testid="chapter-header"'), source.lastIndexOf('{/* TabNavigation */}'));
  assert.match(header,/\{renderVideoGenerationStats\(\)\}/);
  assert.match(header,/\{renderChapterSwitch\(\)\}/);
  assert.match(header,/\{chapterSummary\}/);
  assert.match(header,/onClick=\{onResourcesManageClick\}/);
  assert.match(source,/if \(currentTab !== 3 \|\| shots.length === 0\) return null/);
  const mainHeader = source.slice(source.lastIndexOf('{\/\* TabNavigation \*\/}'));
  assert.doesNotMatch(mainHeader,/renderVideoGenerationStats\(\)/);
  assert.ok(mainHeader.indexOf('<TabNavigation />') < mainHeader.indexOf('{headerContextStats}'));
  assert.match(mainHeader, /\{\(headerContextStats \|\| headerQueueStats\) && \(/);
  assert.match(mainHeader, /\{headerQueueStats\}/);
});
