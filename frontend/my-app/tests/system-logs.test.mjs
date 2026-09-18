import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const require = createRequire(import.meta.url);
const root = new URL('../src/', import.meta.url);
const read = path => readFileSync(new URL(path, root), 'utf8');

function load(path, mocks = {}) {
  const output = ts.transpileModule(read(path), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      jsx: ts.JsxEmit.ReactJSX,
      target: ts.ScriptTarget.ES2022,
      esModuleInterop: true,
    },
  }).outputText;
  const module = { exports: {} };
  const localRequire = specifier => {
    if (Object.prototype.hasOwnProperty.call(mocks, specifier)) return mocks[specifier];
    return require(specifier);
  };
  vm.runInNewContext(output, {
    module,
    exports: module.exports,
    require: localRequire,
    URLSearchParams,
    AbortController,
    DOMException,
    console,
    setTimeout,
    clearTimeout,
  }, { filename: path });
  return module.exports;
}

const translate = (key, params = {}) => {
  if (params.defaultValue) return params.defaultValue;
  if (key === 'systemLogs.unknown') return 'Unknown';
  if (key === 'systemLogs.unavailable') return 'Unavailable';
  if (key === 'systemLogs.responseExcerptUnavailable') return 'Response excerpt unavailable';
  return key;
};
const i18nMock = { useTranslation: () => ({ t: translate, i18n: { language: 'en-US', timezone: 'UTC' } }) };
const displayMetadata = {
  novels: { 'novel-1': { id: 'novel-1', title: 'Readable Novel' } },
  chapters: { 'chapter-1': { id: 'chapter-1', novelId: 'novel-1', number: 7, title: 'Readable Chapter' } },
  shots: { 'shot-1': { id: 'shot-1', chapterId: 'chapter-1', index: 9 } },
};
const TechnicalId = ({ value }) => createElement('code', { 'data-technical-id': value || '' }, value || 'Unknown');

const sample = {
  eventId: 'task:task-legacy:terminal',
  source: 'task_terminal',
  occurredAt: '2026-09-16T09:30:00Z',
  level: 'ERROR',
  service: 'task',
  provider: null,
  stage: 'TASK',
  operation: 'SHOT_VIDEO',
  errorCode: 'HISTORIC_UPLOAD_FAILED',
  failureClass: 'UNKNOWN',
  summary: 'Historic upload failed safely',
  scope: {
    novelId: 'novel-1', chapterId: 'chapter-1', shotId: 'shot-1', shotIndex: 1,
    clipIndex: 2, frameIndex: 3, referenceIndex: null, taskId: 'task-legacy',
    attemptKind: 'SHOT_VIDEO', attemptId: 'attempt-1', attemptNo: 2, retryNo: 1,
  },
  submission: { state: 'UNKNOWN', cid: null },
  diagnosticQuality: 'LEGACY_SUMMARY_ONLY',
  diagnosticQualityFlags: ['LEGACY_SUMMARY_ONLY', 'UNKNOWN_SUBMISSION_STATE'],
};

test('route, sidebar and API client expose the approved GET-only surface', async () => {
  const app = read('App.tsx');
  const sidebar = read('components/Sidebar.tsx');
  assert.match(app, /lazy\(\(\) => import\('\.\/pages\/SystemLogs'\)\)/);
  assert.equal((app.match(/path="system-logs"/g) || []).length, 1);
  assert.match(sidebar, /t\('nav\.systemLogs'\).*href: '\/system-logs'/s);

  const calls = [];
  const api = load('api/systemLogs.ts', {
    './index': { api: { get: async (...args) => { calls.push(args); return { success: true, data: {} }; } } },
  }).systemLogsApi;
  await api.list({
    view: 'errors', level: 'ERROR', service: 'comfyui', provider: 'comfyui',
    novel_id: 'novel', chapter_id: 'chapter', shot_id: 'shot', task_id: 'task',
    error_code: 'CODE', failure_class: 'TIMEOUT', cursor: 'opaque', limit: 50,
  });
  await api.filters();
  await api.detail('task-diagnostic:task/1:efd1_hash');
  assert.equal(calls.length, 3);
  const listUrl = calls[0][0];
  for (const pair of [
    'view=errors', 'level=ERROR', 'service=comfyui', 'provider=comfyui', 'novel_id=novel',
    'chapter_id=chapter', 'shot_id=shot', 'task_id=task', 'error_code=CODE',
    'failure_class=TIMEOUT', 'cursor=opaque', 'limit=50',
  ]) assert.ok(listUrl.includes(pair), pair);
  assert.equal(calls[1][0], '/system-logs/filters');
  assert.equal(calls[2][0], '/system-logs/task-diagnostic%3Atask%2F1%3Aefd1_hash');
  const apiSource = read('api/systemLogs.ts');
  assert.doesNotMatch(apiSource, /api\.(post|put|patch|delete)\s*</);
});

test('URL state defaults to attention, round-trips approved filters and clears dependent state', () => {
  const state = load('pages/SystemLogs/urlState.ts');
  const empty = state.parseSystemLogUrlState(new URLSearchParams('unapproved=value'));
  assert.equal(empty.view, 'attention');
  assert.equal(state.serializeSystemLogUrlState(empty).toString(), 'view=attention');

  const restored = state.parseSystemLogUrlState(new URLSearchParams(
    'view=needs_review&level=REVIEW_REQUIRED&service=review&provider=p&novel_id=n&chapter_id=c&shot_id=s&task_id=t&error_code=E&failure_class=UNKNOWN&cursor=opaque&event=review%3A1',
  ));
  assert.deepEqual(JSON.parse(JSON.stringify(restored)), {
    view: 'needs_review', level: 'REVIEW_REQUIRED', service: 'review', provider: 'p',
    novelId: 'n', chapterId: 'c', shotId: 's', taskId: 't', errorCode: 'E',
    failureClass: 'UNKNOWN', cursor: 'opaque', eventId: 'review:1',
  });
  const changedBook = state.updateSystemLogUrlState(restored, { novelId: 'n2' });
  assert.equal(changedBook.chapterId, '');
  assert.equal(changedBook.shotId, '');
  assert.equal(changedBook.cursor, '');
  assert.equal(changedBook.eventId, '');
  const changedChapter = state.updateSystemLogUrlState(restored, { chapterId: 'c2' });
  assert.equal(changedChapter.shotId, '');
  const atomicCascade = state.updateSystemLogUrlState(empty, {
    novelId: 'n1', chapterId: 'c1', shotId: 's1',
  });
  assert.equal(atomicCascade.novelId, 'n1');
  assert.equal(atomicCascade.chapterId, 'c1');
  assert.equal(atomicCascade.shotId, 's1');
  const query = state.systemLogQueryFromState(restored);
  assert.equal(query.view, 'needs_review');
  assert.equal(query.task_id, 't');
  assert.equal(query.cursor, 'opaque');
});

test('read-only domain metadata hydrates human labels while preserving authoritative IDs', async () => {
  const calls = [];
  const metadataModule = load('pages/SystemLogs/displayMetadata.ts', {
    '../../api/novels': { novelApi: { fetchList: async () => {
      calls.push('novels');
      return { success: true, data: [{ id: 'novel-uuid', title: 'The Readable Novel' }] };
    } } },
    '../../api/chapters': { chapterApi: { fetchByNovel: async novelId => {
      calls.push(`chapters:${novelId}`);
      return { success: true, data: [{ id: 'chapter-uuid', novelId, number: 4, title: 'A Named Chapter' }] };
    } } },
    '../../api/shots': { shotsApi: { getShots: async (novelId, chapterId) => {
      calls.push(`shots:${novelId}:${chapterId}`);
      return { success: true, data: [{ id: 'shot-uuid', index: 12 }] };
    } } },
  });
  const metadata = await metadataModule.loadSystemLogDisplayMetadata();
  assert.deepEqual(calls, ['novels', 'chapters:novel-uuid', 'shots:novel-uuid:chapter-uuid']);
  assert.equal(metadata.novels['novel-uuid'].title, 'The Readable Novel');
  assert.equal(metadata.chapters['chapter-uuid'].title, 'A Named Chapter');
  assert.equal(metadata.shots['shot-uuid'].index, 12);
  assert.equal(metadataModule.shortTechnicalId('12345678-1234-1234-1234-123456789abc'), '12345678...9abc');

  const filters = read('pages/SystemLogs/components/SystemLogFilters.tsx');
  assert.match(filters, /<option key=\{value\} value=\{value\}>\{label\(value\)\}<\/option>/);
  assert.match(filters, /metadata\.novels\[value\]\?\.title/);
  assert.match(filters, /`#\$\{chapter\.number\} \$\{chapter\.title\}`/);
  assert.match(filters, /`Shot \$\{shot\.index\}`/);
  const technicalId = read('pages/SystemLogs/components/TechnicalId.tsx');
  assert.match(technicalId, /shortTechnicalId\(value\)/);
  assert.match(technicalId, /copyToClipboard\(value\)/);
  assert.match(technicalId, /title=\{value\}/);
});

test('desktop table and mobile cards show real terminal and legacy UNKNOWN values', () => {
  const page = load('pages/SystemLogs/index.tsx', {
    react: require('react'),
    'lucide-react': require('lucide-react'),
    '../../stores/i18nStore': i18nMock,
    './components/TechnicalId': { TechnicalId },
    './components/SystemLogDetailDrawer': { SystemLogDetailDrawer: () => null },
    './components/SystemLogFilters': { SystemLogFilters: () => null },
    './hooks/useSystemLogsState': { useSystemLogsState: () => ({}) },
  });
  const props = { item: sample, metadata: displayMetadata, formatDate: value => value, onView() {} };
  const row = renderToStaticMarkup(createElement(page.SystemLogTableRow, props));
  const card = renderToStaticMarkup(createElement(page.SystemLogCard, props));
  for (const value of ['HISTORIC_UPLOAD_FAILED', 'UNKNOWN', 'task-legacy', 'Historic upload failed safely']) {
    assert.ok(row.includes(value), value);
    assert.ok(card.includes(value), value);
  }
  for (const value of ['Readable Novel', 'Readable Chapter', 'Shot 1']) assert.ok(row.includes(value), value);
  assert.match(card, /line-clamp-2/);

  const source = read('pages/SystemLogs/index.tsx');
  for (const column of ['time', 'level', 'service', 'stage', 'bookChapter', 'shotClipFrame', 'task', 'errorCode', 'failureClass', 'summary', 'details']) {
    assert.ok(source.includes(`'${column}'`), column);
  }
  for (const view of ['attention', 'errors', 'needs_review', 'all']) assert.ok(source.includes(`'${view}'`));
  assert.match(source, /hidden overflow-x-auto lg:block/);
  assert.match(source, /lg:hidden/);
});

test('mobile filters and detail are full-screen native dialogs with 44px controls', () => {
  const filters = read('pages/SystemLogs/components/SystemLogFilters.tsx');
  const detail = read('pages/SystemLogs/components/SystemLogDetailDrawer.tsx');
  for (const source of [filters, detail]) {
    assert.match(source, /<dialog/);
    assert.match(source, /h-\[100dvh\]/);
    assert.match(source, /min-h-\[44px\]|h-11/);
    assert.match(source, /onCancel=/);
  }
  assert.match(filters, /select\('chapterId', chapterOptions, !draft\.novelId,/);
  assert.match(filters, /select\('shotId', shotOptions, !draft\.chapterId,/);
  const lifecycle = read('pages/SystemLogs/components/useSystemLogDialog.ts');
  assert.match(lifecycle, /showModal\(\)/);
  assert.match(lifecycle, /document\.body\.style\.overflow = 'hidden'/);
  assert.match(lifecycle, /previousFocus.*focus\(\)/s);
});

test('detail drawer renders the approved safe projection and links only where entries exist', () => {
  const Link = ({ to, children, ...props }) => createElement('a', { ...props, href: typeof to === 'string' ? to : '#' }, children);
  const drawer = load('pages/SystemLogs/components/SystemLogDetailDrawer.tsx', {
    react: require('react'),
    'lucide-react': require('lucide-react'),
    'react-router-dom': { Link },
    '../../../stores/i18nStore': i18nMock,
    './useSystemLogDialog': { useSystemLogDialog() {} },
    './TechnicalId': { TechnicalId },
  }).SystemLogDetailDrawer;
  const diagnostic = {
    ...sample,
    eventId: 'observation:efd1-safe',
    source: 'external_failure_observation',
    stage: 'VIDEO_REFERENCE_UPLOAD',
    operation: 'UPLOAD_IMAGE',
    service: 'comfyui',
    provider: 'comfyui',
    errorCode: 'UPLOAD_FAILED',
    failureClass: 'HTTP_ERROR',
    detail: {
      diagnostic: {
        version: 1, diagnosticId: 'efd1-safe', errorCode: 'UPLOAD_FAILED', failureClass: 'HTTP_ERROR',
        level: 'ERROR', stage: 'VIDEO_REFERENCE_UPLOAD', operation: 'UPLOAD_IMAGE', service: 'comfyui', provider: 'comfyui',
        scope: sample.scope,
        timing: { startedAt: 'start', finishedAt: 'finish', elapsedMs: 321 },
        reference: { referenceIndex: 0, filename: 'safe.png', bytes: 42, sha256: 'ref-sha', sourceId: 'source-1', revision: 7 },
        upstream: { rsaId: 'rsa-1', rsaHash: 'rsa-sha', manifestHash: 'manifest-sha' },
        externalCall: {
          endpoint: 'https://safe.invalid/upload', method: 'POST', timeoutMs: 9000,
          exceptionType: 'HTTPStatusError', exceptionMessage: 'safe bounded message', httpStatus: 503,
          responseContentType: 'application/json', responseBodySha256: 'body-sha', responseBodyBytes: 88,
          responseExcerptTruncated: true, receiptStatus: null, receiptViolation: null,
        },
        submission: { queueCalled: false, submitted: false, state: 'NOT_SUBMITTED', cid: null, queueSeen: false, remoteUploadEffect: 'UNKNOWN' },
        evidence: { evidenceId: 'ev1-safe', path: 'safe.json', sha256: 'evidence-sha', bytes: 99, truncated: false, redactionVersion: 1 },
        redacted: true, truncated: false,
      },
      evidence: { evidenceId: 'ev1-safe', path: 'safe.json', sha256: 'evidence-sha', bytes: 99, truncated: false, redactionVersion: 1 },
      domainState: { taskId: 'task-legacy', taskStatus: 'failed' },
      llm: { logId: 'llm-1', provider: 'openai', model: 'gpt-test', status: 'error', taskType: 'video', durationSeconds: 1.5 },
      reviewFinding: {
        findingId: 'review-1', code: 'UNBOUND_ASSET_REFERENCE', message: 'review message', status: 'OPEN',
        fallbackAction: 'SAME_INPUT', fallbackOutcome: 'PENDING',
        evidence: { firstFailedLlmLogId: 'llm-review' },
      },
    },
  };
  const html = renderToStaticMarkup(createElement(drawer, {
    eventId: diagnostic.eventId, preview: null, detail: diagnostic, loading: false, error: '',
    metadata: displayMetadata, formatDate: value => String(value), onClose() {},
  }));
  for (const value of [
    'task-legacy', 'attempt-1', 'novel-1', 'chapter-1', 'shot-1', 'VIDEO_REFERENCE_UPLOAD',
    'UPLOAD_IMAGE', 'UPLOAD_FAILED', 'HTTP_ERROR', 'https://safe.invalid/upload', '321', '9000',
    'HTTPStatusError', 'safe bounded message', '503', 'body-sha', 'safe.png', 'ref-sha',
    'source-1', 'rsa-1', 'rsa-sha', 'manifest-sha', 'NOT_SUBMITTED', 'review message',
    'ev1-safe', 'safe.json', 'evidence-sha', 'llm-1', 'Response excerpt unavailable',
    'Readable Novel', 'Readable Chapter', 'Shot 1',
  ]) assert.ok(html.includes(value), value);
  assert.match(html, /href="\/tasks"/);
  assert.match(html, /href="\/asset-debug\?task_id=task-legacy"/);
  assert.match(html, /href="\/llm-logs"/);
  assert.doesNotMatch(html, />\s*(Retry|Resolve|Acknowledge|Adopt|Cancel|Repair)\s*</i);
});

function flatten(value, prefix = '', result = {}) {
  for (const [key, item] of Object.entries(value)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (item && typeof item === 'object') flatten(item, path, result);
    else result[path] = item;
  }
  return result;
}

test('all five locales provide the complete System Logs key set', () => {
  const zhCN = load('i18n/locales/zh-CN/logs.ts').default;
  const enUS = load('i18n/locales/en-US/logs.ts').default;
  const locales = {
    'zh-CN': { logs: zhCN, nav: load('i18n/locales/zh-CN/nav.ts').default },
    'en-US': { logs: enUS, nav: load('i18n/locales/en-US/nav.ts').default },
    'zh-TW': {
      logs: load('i18n/locales/zh-TW/logs.ts', { '../zh-CN/logs': { __esModule: true, default: zhCN } }).default,
      nav: load('i18n/locales/zh-TW/nav.ts').default,
    },
    'ja-JP': {
      logs: load('i18n/locales/ja-JP/logs.ts', { '../en-US/logs': { __esModule: true, default: enUS } }).default,
      nav: load('i18n/locales/ja-JP/nav.ts').default,
    },
    'ko-KR': {
      logs: load('i18n/locales/ko-KR/logs.ts', { '../en-US/logs': { __esModule: true, default: enUS } }).default,
      nav: load('i18n/locales/ko-KR/nav.ts').default,
    },
  };
  const expected = Object.keys(flatten(zhCN.systemLogs)).sort();
  const requiredDetails = [
    'fields.diagnosticQuality', 'fields.taskId', 'fields.attemptId', 'fields.novelId',
    'fields.stage', 'fields.errorCode', 'fields.endpoint', 'fields.exceptionType',
    'fields.httpStatus', 'fields.referenceFilename', 'fields.rsaId', 'fields.queueCalled',
    'fields.reviewStatus', 'fields.evidenceId',
  ];
  for (const [name, locale] of Object.entries(locales)) {
    assert.ok(locale.nav.nav.systemLogs, `${name} nav.systemLogs`);
    const flattened = flatten(locale.logs.systemLogs);
    assert.deepEqual(Object.keys(flattened).sort(), expected, `${name} key parity`);
    for (const key of requiredDetails) assert.ok(flattened[key], `${name} ${key}`);
  }
});
