import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const require = createRequire(import.meta.url);
const source = file => readFileSync(new URL(`../src/pages/LLMLogs/${file}`, import.meta.url), 'utf8');
const page = source('index.tsx');
const hook = source('hooks/useLLMLogsState.ts');
function extract(text, name) {
  const ast = ts.createSourceFile('source.tsx', text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let result;
  function visit(node) {
    if (ts.isFunctionDeclaration(node) && node.name?.text === name) result = node.getText(ast);
    if (ts.isVariableDeclaration(node) && node.name.getText(ast) === name) result = `const ${name} = ${node.initializer.getText(ast)};`;
    ts.forEachChild(node, visit);
  }
  visit(ast);
  assert.ok(result, `Missing ${name}`);
  return result;
}
function load(text, name, context = {}) {
  const js = ts.transpileModule(text, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  return vm.runInNewContext(`${js}\n${name}`, { exports: {}, require, ...context });
}
const formatDate = timezone => load(extract(hook, 'formatDate'), 'formatDate', { i18n: { timezone } });
const Row = load(extract(page, 'LogTableRow'), 'LogTableRow', {
  useTranslation: () => ({ t: key => key }),
  ProviderLogo: ({ provider, label }) => createElement('span', { 'data-provider': provider, 'aria-label': label }),
  LogSpeed: () => createElement('span', { 'data-speed': true }),
  Eye: () => null,
});
function cells(created_at, timezone = 'Asia/Shanghai') {
  const html = renderToStaticMarkup(createElement(Row, {
    log: { created_at, provider: 'openai', model: 'gpt-test', status: 'success', user_prompt: '' },
    formatDate: formatDate(timezone), onView() {}, truncateText: text => text,
    getTaskTypeLabel: () => '-', getDisplayDuration: () => '1s',
    getStatusBadgeConfig: () => ({ bg: '', text: '', label: 'success' }),
  }));
  return [...html.matchAll(/<td\b[^>]*>(.*?)<\/td>/g)].map(match => match[1]);
}

test('provider logo is in the provider column, model is plain text, speed stays present', () => {
  const row = cells('2026-12-31T20:04:05Z');
  assert.match(row[1], /data-provider="openai"/);
  assert.match(row[1], /aria-label="openai"/);
  assert.equal(row[2], 'gpt-test');
  assert.match(row[8], /data-speed="true"/);
});

test('only table timestamps omit year while retaining configured timezone conversion', () => {
  const timestamp = '2026-12-31T20:04:05Z';
  assert.equal(cells(timestamp)[0], '01/01 04:04:05');
  assert.equal(formatDate('Asia/Shanghai')(timestamp), '2027/01/01 04:04:05');
  assert.equal(cells(timestamp, 'America/New_York')[0], '12/31 15:04:05');
  for (const invalid of ['', 'invalid']) assert.equal(cells(invalid)[0], '-');
});

test('detail modal keeps the full formatter and exports use the original timestamp', () => {
  const modal = source('components/LogDetailModal.tsx');
  assert.match(page, /onClose=\{state.closeModal\} formatDate=\{state.formatDate\}/);
  assert.match(modal, /\{formatDate\(log.created_at\)\}/);
  assert.match(modal, /const safeTime = \(log.created_at \|\| ''\)\.replace/);
  assert.match(modal, /link.download = .*\$\{safeTime \|\| log.id\}/);
});

const Speed = load(extract(source('components/LogSpeed.tsx'), 'LogSpeed'), 'LogSpeed', {
  ...require('react'),
  useLayoutEffect: () => {},
  useTranslation: () => ({ t: key => key }),
  Gauge: require('lucide-react').Gauge,
});

test('speed displays an outline gauge and fixed two-decimal t/s', () => {
  for (const [speed, expected] of [[12.43, '12.43'], [12, '12.00'], [0, '0.00'], [1.236, '1.24']]) {
    const html = renderToStaticMarkup(createElement(Speed, {
      log: { metrics: { output_tokens_per_second: speed } },
    }));
    assert.match(html, /<svg[^>]*fill="none"[^>]*stroke="currentColor"/);
    assert.match(html, /aria-hidden="true"/);
    assert.ok(html.includes(`</svg>${expected} t/s</button>`));
    assert.ok(html.includes(`aria-label="llmLogs.tokenDetails: ${expected} t/s"`));
    assert.match(html, /aria-expanded="false"/);
  }
});

test('speed retains the dash for missing or invalid metrics', () => {
  for (const metrics of [undefined, null, {}, ...[null, -1, NaN, Infinity].map(
    output_tokens_per_second => ({ output_tokens_per_second }),
  )]) {
    const html = renderToStaticMarkup(createElement(Speed, { log: { metrics } }));
    assert.ok(html.includes('</svg>-</button>'));
    assert.match(html, /aria-label="llmLogs.tokenDetails: -"/);
    assert.ok(!html.includes('t/s'));
  }
});
