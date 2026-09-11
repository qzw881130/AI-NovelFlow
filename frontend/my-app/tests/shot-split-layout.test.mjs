import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const require = createRequire(import.meta.url);
let state;
const imports = {
  react: { ...require('react'), useState: initial => [initial, () => {}], useEffect: () => {} },
  '../stores': {
    useChapterGenerateStore: selector => selector ? selector(state) : state,
    useDataSlice: () => ({}),
  },
  '../../../hooks/useResizable': {
    useResizable: ({ initialWidth }) => ({ width: initialWidth }),
  },
  '../../../api/shots': { shotsApi: {} },
  '../../../stores/toastStore': { toast: {} },
  '../../../stores/i18nStore': { useTranslation: () => ({ t: key => key }) },
  '../../../utils': { getDialogueDurationWarningStats: () => ({ stats: { critical: 0 } }) },
};
function load(file) {
  const source = readFileSync(new URL(`../src/pages/ChapterGenerate/components/${file}.tsx`, import.meta.url), 'utf8');
  const exports = {};
  vm.runInNewContext(ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText, { exports, require: name => imports[name] ?? require(name) });
  return exports[file];
}
const ThreeColumnLayout = load('ThreeColumnLayout');
const ShotSplitTab = load('ShotSplitTab');

test('wide side panels wrap instead of collapsing the split column, including saved and collapsed widths', () => {
  for (const [leftPanelWidth, rightPanelWidth] of [[200, 760], [400, 920]]) {
    for (const leftPanelCollapsed of [false, true]) {
      for (const rightPanelCollapsed of [false, true]) {
        state = { leftPanelWidth, rightPanelWidth, leftPanelCollapsed, rightPanelCollapsed };
        const layout = ThreeColumnLayout({ leftPanel: 'original', centerContent: 'split', rightPanel: 'editor' });
        const [, left, center, right] = layout.props.children;
        assert.match(layout.props.className, /\bflex-wrap\b/);
        assert.match(layout.props.className, /\boverflow-auto\b/);
        assert.ok(center.props.className.includes('min-w-[min(20rem,100%)]'));
        assert.equal(layout.props['data-mobile-panel'], 'editor');
        assert.equal(center.props['data-panel'], 'list');
        assert.equal(right.props['data-panel'], 'editor');
        for (const panel of [left, center, right]) assert.match(panel.props.className, /\bh-full\b/);
        for (const panel of [left, right]) assert.match(panel.props.className, /\bmax-w-full\b/);
        assert.equal(left.props.style.width, leftPanelCollapsed ? 48 : leftPanelWidth);
        assert.equal(right.props.style.width, rightPanelCollapsed ? 0 : rightPanelWidth);
        assert.equal(left.props['data-desktop-collapsed'], leftPanelCollapsed);
        assert.equal(right.props['data-desktop-collapsed'], rightPanelCollapsed);
        const html = renderToStaticMarkup(layout);
        for (const content of ['original', 'split', 'editor']) {
          assert.equal(html.split(`>${content}<`).length - 1, 1, 'content stays mounted exactly once');
        }
      }
    }
  }
});

test('zero-shot toolbar wraps whole buttons and leaves AI split enabled', () => {
  state = { shots: [], currentShotIndex: 1 };
  const html = renderToStaticMarkup(createElement(ShotSplitTab, { novelId: 'n', chapterId: 'c' }));
  const toolbar = html.match(/^<div[^>]*><div class="([^"]*)"><div class="([^"]*)">/);
  assert.ok(toolbar);
  assert.match(toolbar[1], /\bflex-wrap\b/);
  assert.match(toolbar[2], /\bflex-wrap\b/);
  assert.ok(toolbar[2].includes('[&amp;&gt;button]:shrink-0'));
  assert.ok(toolbar[2].includes('[&amp;&gt;button]:whitespace-nowrap'));
  const splitButton = html.match(/<button([^>]*aria-label="chapterGenerate.aiSplit"[^>]*)>/);
  assert.ok(splitButton);
  assert.doesNotMatch(splitButton[1], /\bdisabled="/);
  assert.match(html, /<span class="hidden lg:inline">chapterGenerate.aiSplit<\/span>/);
  assert.match(html, /chapterGenerate.clickAiSplitHint/);
});
