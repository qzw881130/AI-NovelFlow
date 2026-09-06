import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import ts from 'typescript';

const source = readFileSync(new URL('../src/utils/errorUtils.ts', import.meta.url), 'utf8');
const exports = {};
vm.runInNewContext(ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText, { exports });
const { formatUserFacingError: format } = exports;

const fixture = () => ({
  source: 'AudioDrive',
  subject_manifest: { subjects: Array.from({ length: 100 }, (_, i) => ({
    subject_ref: `<Subject ${i}>`, character_name: 'PRIVATE_CHARACTER',
    reference_image: `/private/401/${i}.png`, description: 'quoted "text" and braces { }',
  })) },
  speaker_timeline_segments: 4,
  issues: [{ code: 'NONE_SEGMENT_LIPSYNC_CONTRADICTION', blocking: true }],
  blocking_issues: [{ code: 'NONE_SEGMENT_LIPSYNC_CONTRADICTION', blocking: true }],
  passed: false,
  audio_drive_context: { drive_audio: 'clip_002_drive_audio.wav', final_audio: 'clip_002_final_audio.wav' },
});

test('large AudioDrive audit is concise, heuristic-aware and leaves raw data intact', () => {
  const audit = fixture();
  const raw = JSON.stringify(audit);
  const result = format(raw);
  assert.match(result, /^Clip 2 AudioDrive/);
  assert.match(result, /提示词口型约束检查未通过/);
  assert.match(result, /可能.*并不代表生成视频中人物实际开口/);
  assert.match(result, /请检查/);
  assert.ok(result.length < 220);
  assert.doesNotMatch(result, /PRIVATE_CHARACTER|subject_manifest|\.wav|认证失败|NONE_SEGMENT_LIPSYNC/);
  assert.equal(JSON.stringify(audit), raw);
  assert.equal(format(audit), result);
});

test('prefixed JSON, nested detail/error objects and encoded strings use the real helper', () => {
  const audit = fixture();
  const expected = format(audit);
  for (const input of [
    `视频失败: ${JSON.stringify(audit)} (request failed)`,
    { detail: { error: audit } },
    JSON.stringify({ detail: JSON.stringify({ error: `RuntimeError: ${JSON.stringify(audit)}` }) }),
    { error: { message: JSON.stringify(audit) } },
  ]) assert.equal(format(input), expected);
});

test('known issue codes get actionable labels and repeated issues are deduplicated', () => {
  const codes = {
    MISSING_AUDIO_TEXT_RENDERING_CONSTRAINT: '音频文字约束不完整',
    UNKNOWN_SUBJECT_REFERENCE: '人物引用无法识别',
    MISSING_SUBJECT_REFERENCE_IN_PROMPT: '提示词缺少说话人物引用',
    INVALID_SPEAKER_TIMELINE: '说话者时间轴格式或时间范围无效',
    INVALID_AUDIO_SPEAKER_SEMANTICS: '音频说话者标记不符合要求',
    UNRESOLVED_VISIBLE_SPEAKER: '可见说话者无法匹配参考图人物',
    DIALOGUE_TEXT_LEAKAGE: '提示词含有可能触发朗读的台词文本',
  };
  for (const [code, label] of Object.entries(codes)) {
    const issue = { code, blocking: true, text: 'PRIVATE_DIALOGUE' };
    const result = format({ ...fixture(), issues: [issue, issue], blocking_issues: [issue] });
    assert.equal(result.split(label).length - 1, 1);
    assert.match(result, /请/);
    assert.ok(!result.includes(code));
    assert.ok(!result.includes('PRIVATE_DIALOGUE'));
  }
});

test('unknown and malformed issues never spill the manifest or arbitrary issue details', () => {
  const result = format({ ...fixture(), issues: [null, 4, {}, 'FUTURE_CODE', { code: '__proto__' }], blocking_issues: [] });
  assert.match(result, /未识别的问题/);
  assert.equal(result.split('未识别的问题').length - 1, 1);
  assert.doesNotMatch(result, /PRIVATE_CHARACTER|FUTURE_CODE|__proto__/);
  assert.match(format({ source: 'AudioDrive', issues: [] }), /请检查/);
});

test('invalid JSON, unrelated structured errors and existing error formatting are preserved', () => {
  for (const raw of ['普通错误', '{"source":"AudioDrive","issues":[',
    'prefix {invalid} suffix', JSON.stringify({ source: 'Other', issues: ['UNKNOWN_SUBJECT_REFERENCE'] }),
    JSON.stringify({ detail: 'ordinary error' }), 'NONE_SEGMENT_LIPSYNC_CONTRADICTION']) {
    assert.equal(format(` ${raw} `), raw);
  }
  assert.equal(format(undefined), '');
  assert.match(format('401 unauthorized'), /^LLM 认证失败/);
  assert.match(format('DIALOGUE_DURATION_INSUFFICIENT'), /^Clip 台词时长不足/);
  assert.match(format('Invalid NAL unit size'), /^合并视频解码失败/);
  const circular = {}; circular.detail = circular;
  assert.equal(format(circular), '[object Object]');
});

test('VideoGenTab and Tasks retain shared formatting for task and clip displays', () => {
  const video = readFileSync(new URL('../src/pages/ChapterGenerate/components/VideoGenTab.tsx', import.meta.url), 'utf8');
  const tasks = readFileSync(new URL('../src/pages/Tasks/components/TaskCard.tsx', import.meta.url), 'utf8');
  assert.match(video, /formatUserFacingError\(clip\.error_message\)/);
  assert.match(video, /formatUserFacingError\(\(currentVideoDirectorPlan as any\)\.task_error_message/);
  assert.match(tasks, /formatUserFacingError\(task\.errorMessage\)/);
  assert.match(tasks, /formatUserFacingError\(clip\.errorMessage\)/);
});
