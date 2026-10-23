import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

const source = await readFile(new URL('../src/pages/Tasks/hooks/useTasksState.ts', import.meta.url), 'utf8');
const js = ts.transpileModule(source.replace(/^import[^;]+;\s*/gm, '').replace(/^export /gm, ''), {
  compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.None },
}).outputText;

function harness(response) {
  const errors = [], successes = [], requests = [], refreshes = [];
  const hook = new Function('useState', 'useCallback', 'useSerialPolling', 'useTranslation', 'taskApi', 'toast', 'console',
    `${js}; return useTasksState;`)(
    initial => [initial, () => {}], f => f, options => () => options.fetch(), () => ({ t: key => key }),
    { retry: async id => { requests.push(id); if (response instanceof Error) throw response; return response; },
      fetchPage: async () => { refreshes.push(true); return { success: false }; } },
    { error: message => errors.push(message), success: message => successes.push(message) }, { error: () => {} },
  );
  return { ...hook(), errors, successes, requests, refreshes };
}

for (const message of ['已有 ComfyUI 回执尚未完成结果确认', '任务状态已变化或仍有后台执行']) {
  test(`retry shows server rejection without success or automatic resubmit: ${message}`, async () => {
    const state = harness({ detail: message });
    await state.handleRetry('same-task');
    assert.deepEqual(state.errors, [message]);
    assert.deepEqual(state.successes, []);
    assert.deepEqual(state.requests, ['same-task']);
    assert.deepEqual(state.refreshes, []);
  });
}
test('successful retry keeps the existing task refresh', async () => {
  const state = harness({ success: true, data: { taskId: 'same-task', status: 'pending' } });
  await state.handleRetry('same-task');
  assert.deepEqual(state.errors, []);
  assert.deepEqual(state.successes, ['tasks.taskRestarted']);
  assert.deepEqual(state.requests, ['same-task']);
  assert.equal(state.refreshes.length, 1);
});
test('transport failure is visible and does not retry automatically', async () => {
  const state = harness(new Error('Network unavailable'));
  await state.handleRetry('same-task');
  assert.deepEqual(state.errors, ['Network unavailable']);
  assert.deepEqual(state.requests, ['same-task']);
});
