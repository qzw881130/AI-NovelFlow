import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/utils/errorUtils.ts', import.meta.url), 'utf8');
const categorySource = await readFile(new URL('../src/utils/preflightErrorCategory.ts', import.meta.url), 'utf8');
const categoryExports = {};
new Function('exports', ts.transpileModule(categorySource, {
  compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS },
}).outputText)(categoryExports);
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS },
}).outputText;
const exports = {};
new Function('exports', 'require', compiled)(exports, () => categoryExports);
const { formatUserFacingError } = exports;

test('known validation failures carry the exact catalog label', () => {
  assert.match(formatUserFacingError('PHASE_B_INPUT_NOT_COVERED: missing previous video'), /^\[Phase B 输入与续接来源\]/);
  assert.equal(categoryExports.preflightErrorCategory('CLIP_RECOVERY_PLAN_CHANGED'), 'Clip 结果恢复与回写');
  assert.equal(categoryExports.preflightErrorCategory('成片视觉验收未通过：多余人物'), 'Clip 成片人物验收');
});

test('continuation binding failure explains the Phase B stop without hiding the raw cause', () => {
  const raw = 'PHASE_B_INPUT_NOT_COVERED: ValueError: PREVIOUS_AV_BINDING_UNVERIFIED: native masked-context path changed';
  const formatted = formatUserFacingError(raw);
  assert.match(formatted, /续接绑定未通过验证/);
  assert.match(formatted, /Phase B 输入校验/);
  assert.match(formatted, /尚未提交 ComfyUI/);
  assert.doesNotMatch(formatted, /PHASE_B_INPUT_NOT_COVERED/);
});
