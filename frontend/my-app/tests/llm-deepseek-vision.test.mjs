import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import ts from 'typescript';

const source = readFileSync(new URL('../src/constants/llm.ts', import.meta.url), 'utf8');
const js = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const exports = {};
vm.runInNewContext(js, { exports });

test('DeepSeek model selector presets include vision without changing defaults', () => {
  const models = exports.getDefaultModels('deepseek');
  const model = models.find(item => item.id === 'deepseek-v4-flash-vision-exp');
  assert.ok(model);
  assert.equal(model.name, 'DeepSeek V4 Flash Vision Exp');
  assert.equal(model.contextLength, 1048576);
  assert.equal(model.maxTokens, 393216);
  assert.equal(model.capabilities.vision, true);
  assert.equal(exports.getDefaultApiUrl('deepseek'), 'https://api.deepseek.com');
  assert.equal(models[0].id, 'deepseek-v4-flash');
  assert.equal(exports.DEFAULT_CONFIG.llmModel, 'deepseek-v4-flash');
  for (const id of ['deepseek-v4-flash', 'deepseek-v4-pro']) {
    assert.equal(models.find(item => item.id === id).maxTokens, 393216);
    assert.equal(models.find(item => item.id === id).capabilities, undefined);
  }
});
