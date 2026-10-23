import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/pages/Tasks/taskExecutionDisplay.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ES2020 } });
const { getCanonicalClipTaskDescription } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);

const task = (capability = 'EXTEND') => ({
  type: 'shot_video', description: "为章节 'test 2' 的分镜 1 生成 Clip 2；视频模式：SINGLE_FRAME",
  clipExecution: { execution_scope: 'CLIP', clip_plan_revision: 1, capability },
});

for (const capability of ['GENERATE', 'EXTEND', 'TEMPORAL_EXTEND']) {
  test(`canonical Task displays ${capability} rather than legacy mode`, () => {
    const input = task(capability);
    const before = structuredClone(input);
    assert.equal(getCanonicalClipTaskDescription(input), `为章节 'test 2' 的分镜 1 生成 Clip 2 · ${capability}`);
    assert.deepEqual(input, before);
  });
}

test('historical / non-Clip / HD / unknown authority keeps existing display path', () => {
  for (const input of [
    { ...task(), clipExecution: undefined },
    { ...task(), type: 'shot_video_hd' },
    { ...task(), clipExecution: { ...task().clipExecution, execution_scope: 'SHOT' } },
    { ...task(), clipExecution: { ...task().clipExecution, clip_plan_revision: 0 } },
    task('SINGLE_FRAME'), task('UNKNOWN'),
  ]) assert.equal(getCanonicalClipTaskDescription(input), null);
});

test('only the legacy mode suffix is removed; description is preserved', () => {
  for (const mode of ['SINGLE_FRAME', 'FIRST_LAST_FRAME', 'MULTI_KEYFRAME']) {
    assert.equal(getCanonicalClipTaskDescription({ ...task(), description: `Clip 2；视频模式：${mode}；其他信息` }),
      'Clip 2；其他信息 · EXTEND');
  }
  assert.equal(getCanonicalClipTaskDescription({ ...task(), description: undefined }), 'EXTEND');
});

test('Task page uses the semantic display projection before its legacy fallback', async () => {
  const page = await readFile(new URL('../src/pages/Tasks/index.tsx', import.meta.url), 'utf8');
  assert.ok(page.indexOf('getCanonicalClipTaskDescription(task)') < page.indexOf("if (!task.description) return ''"));
});
