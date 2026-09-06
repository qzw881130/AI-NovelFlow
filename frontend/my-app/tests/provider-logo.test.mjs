import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import { renderToStaticMarkup } from 'react-dom/server';

const require = createRequire(import.meta.url);
const source = readFileSync(new URL('../src/components/ProviderLogo.tsx', import.meta.url), 'utf8');
const exports = {};
vm.runInNewContext(ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
}).outputText, {
  exports,
  require: name => name.endsWith('.svg') ? { default: name } : require(name),
});
const { ProviderLogo } = exports;

test('all branded providers render their local SVG with exact model identity', () => {
  for (const provider of ['deepseek', 'openai', 'gemini', 'anthropic', 'azure', 'aliyun-bailian', 'ollama']) {
    const label = `${provider}: actual-model-id`;
    const html = renderToStaticMarkup(ProviderLogo({ provider, label }));
    assert.ok(html.includes(`src="../assets/providers/${provider}.svg"`));
    assert.ok(html.includes(`aria-label="${label}"`));
    assert.ok(html.includes(`title="${label}"`));
    const svg = readFileSync(new URL(`../src/assets/providers/${provider}.svg`, import.meta.url), 'utf8');
    assert.match(svg, /viewBox="0 0 24 24"/);
    assert.doesNotMatch(svg, /<script|<foreignObject|\bon\w+=|(?:href|src)=/i);
  }
});

test('custom and unknown providers have accessible non-brand fallbacks', () => {
  for (const provider of ['custom', 'unknown', '', 'constructor', '__proto__']) {
    const label = `${provider}: model<&>`;
    const html = renderToStaticMarkup(ProviderLogo({ provider, label }));
    assert.doesNotMatch(html, /<img/);
    assert.ok(html.includes('role="img"'));
    assert.ok(html.includes('model&lt;&amp;&gt;'));
    assert.ok(html.includes(provider === 'custom' ? '&lt;/&gt;' : '?'));
  }
});
