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
  const header = source.slice(source.lastIndexOf('data-testid="chapter-header"'), source.lastIndexOf('{/* TabNavigation */}'));
  assert.match(header,/\{renderVideoGenerationStats\(\)\}/);
  assert.match(header,/\{renderChapterSwitch\(\)\}/);
  assert.match(header,/\{chapterSummary\}/);
  assert.match(header,/onClick=\{onResourcesManageClick\}/);
  assert.match(source,/if \(currentTab !== 3 \|\| shots.length === 0\) return null/);
  const mainHeader = source.slice(source.lastIndexOf('{\/\* TabNavigation \*\/}'));
  assert.doesNotMatch(mainHeader,/renderVideoGenerationStats\(\)/);
  assert.ok(mainHeader.indexOf('<TabNavigation />') < mainHeader.indexOf('{headerContextStats}'));
  assert.match(mainHeader, /\{headerContextStats && \(/);
  assert.doesNotMatch(mainHeader, /renderQueueStats|headerQueueStats/);
});

test('every chapter layout places queues in header actions, regardless of the selected tab', () => {
  const headers = source.split('data-testid="chapter-header"').slice(1);
  assert.equal(headers.length, 2, 'main and historical audio layouts');
  for (const section of headers) {
    const header = section.slice(0, section.indexOf('{/* TabNavigation */}'));
    assert.match(header, /\{renderQueueStats\(\)\}/);
    assert.ok(header.indexOf('renderQueueStats()') < header.indexOf('renderChapterSwitch()'));
    assert.ok(header.indexOf('renderChapterSwitch()') < header.indexOf('onClick={onResourcesManageClick}'));
    assert.doesNotMatch(section.slice(section.indexOf('{/* TabNavigation */}')), /renderQueueStats|headerQueueStats/);
  }
  assert.doesNotMatch(source, /headerQueueStats|currentTab === 1 && renderQueueStats/);
  assert.match(source, /aria-label="任务队列统计" className="flex min-w-0 max-w-full flex-wrap items-center justify-end/);
  assert.match(source, /if \(!hasQueueStats\) return null/);
  assert.match(source, /生成分镜图：队列中 \{pendingShots.size\} 个/);
  assert.match(source, /生成视频：队列中 \{pendingVideos.size\} 个/);
});
