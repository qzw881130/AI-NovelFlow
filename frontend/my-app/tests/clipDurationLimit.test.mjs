import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../src/pages/ChapterGenerate/components/VideoGenTab.tsx', import.meta.url), 'utf8');
for (const [i, match] of [...source.matchAll(/const maxClipDuration = (.+);/g)].entries()) {
  test(`duration UI path ${i} respects product ceiling and lower workflow capability`, () => {
    const limit = new Function('plan', 'currentVideoDirectorPlan', `return ${match[1]}`);
    for (const [max, expected] of [[undefined, 20], [12, 12], [15, 15], [18.5, 18.5], [20, 20], [30, 20]]) {
      const plan = { workflow_capability: { max_clip_duration: max } };
      assert.equal(limit(plan, plan), expected);
    }
  });
}
