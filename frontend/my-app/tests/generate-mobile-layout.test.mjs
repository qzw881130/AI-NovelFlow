import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import postcss from 'postcss';

const require = createRequire(import.meta.url);
const source = name => readFileSync(new URL(`../src/pages/ChapterGenerate/components/${name}.tsx`, import.meta.url), 'utf8');
const css = postcss.parse(readFileSync(new URL('../src/index.css', import.meta.url), 'utf8'));
const element = React.createElement;
const hooks = {
  useState: initial => [typeof initial === 'function' ? initial() : initial, () => {}],
  useEffect() {}, useRef: initial => ({ current: initial }), useMemo: fn => fn(),
};
const shots = Array.from({ length: 13 }, (_, i) => ({ id: `s${i + 1}`, index: i + 1, duration: 10, description: 'Draft', audioEvents: [] }));
const state = {
  shots, currentShotId: 's13', currentShotIndex: 13, currentTab: 0,
  chapter: { title: 'Chapter 18', content: 'Source story' },
  generatingShots: new Set(), pendingShots: new Set(), generatingVideos: new Set(), pendingVideos: new Set(),
  preparingAudioShots: new Set(), pendingAudioPrepareShots: new Set(), shotImages: {}, shotVideos: {},
  leftPanelWidth: 400, rightPanelWidth: 920, leftPanelCollapsed: true, rightPanelCollapsed: true,
  chapterCharacters: [], chapterScenes: [], chapterProps: [], characters: [], scenes: [], props: [],
  selectedShotIds: [], tabProgress: {},
};
function load(name, imports = {}, globals = {}) {
  const exports = {};
  const defaults = {
    react: { ...React, ...hooks },
    '../stores': { useChapterGenerateStore: selector => selector ? selector(state) : state },
    '../../../hooks/useResizable': { useResizable: ({ initialWidth }) => ({ width: initialWidth }) },
    '../../../stores/i18nStore': { useTranslation: () => ({ t: key => key }) },
    '../../../stores/toastStore': { toast: {} },
    '../../../api/shots': { shotsApi: {} },
    '../../../api/novels': { novelApi: {} },
    '../../../contexts/SidebarContext': { useSidebar: () => ({ sidebarWidth: 0 }) },
    'react-router-dom': { useParams: () => ({ id: 'n', cid: 'c' }), useNavigate: () => {}, Link: ({ children }) => element('a', null, children) },
    '../../../utils': {
      getDialogueDurationWarningStats: () => ({ checkedCount: 13, stats: {} }),
      DIALOGUE_WARNING_STYLES: Object.fromEntries(['normal', 'notice', 'warning', 'critical'].map(key => [key, {}])),
      getDialogueDurationWarning: () => ({ style: {} }),
    },
  };
  vm.runInNewContext(ts.transpileModule(source(name), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
  }).outputText, {
    exports, console: { log() {} }, ...globals,
    require: key => imports[key] ?? defaults[key] ?? require(key),
  });
  return exports[name];
}
function nodes(tree) {
  if (!React.isValidElement(tree)) return [];
  return [tree, ...[tree.props.children].flat(Infinity).flatMap(nodes)];
}
function mobileRule(selector, property, value) {
  let found = false;
  css.walkRules(rule => {
    if (!rule.selector.includes(selector) || rule.parent.params !== '(max-width: 1023px)') return;
    rule.walkDecls(property, declaration => { if (declaration.value === value) found = true; });
  });
  assert.ok(found, `${selector}: ${property}: ${value} is mobile-only`);
}

function loadLayout(overrides = {}) {
  const editor = () => element('textarea', { 'data-editor': true, defaultValue: 'Draft' });
  return load('ChapterGenerateLayout', {
    './ThreeColumnLayout': { ThreeColumnLayout: load('ThreeColumnLayout') },
    './TabNavigation': { TabNavigation: load('TabNavigation') },
    './BottomNavigator': { BottomNavigator: () => null },
    './ShotForm': { ShotForm: editor }, './ShotSplitTab': { ShotSplitTab: () => null },
    './ShotImageGenTab': { ShotImageGenTab: ({ children }) => children },
    './AudioGenTab': { AudioGenTab: editor }, './VideoGenTab': { VideoGenTab: editor },
    './ResourcePanel': { ResourcePanel: () => null }, './ShotImageList': { ShotImageList: () => null },
    ...overrides,
  });
}

test('all four stages share one in-flow header and one editor, including the audio branch', () => {
  const Layout = loadLayout();
  for (const tab of [0, 1, 2, 3]) {
    state.currentTab = tab;
    const tree = Layout({});
    const html = renderToStaticMarkup(tree);
    assert.equal((html.match(/<h1 /g) || []).length, 1);
    assert.equal((html.match(/data-editor="true"/g) || []).length, 1);
    assert.equal((html.match(/aria-pressed="true"/g) || []).length, tab === 2 ? 1 : 2);
    assert.ok(nodes(tree).some(node => node.props.className?.includes('generate-stage-navigation')));
  }
  assert.doesNotMatch(source('ChapterGenerateLayout'), /setRightPanelWidth\(|setRightPanelCollapsed\(/);
  assert.doesNotMatch(source('ChapterGenerateLayout'), /z-\[1[23]0\]|absolute left-1\/2 top-1/);
  state.currentTab = 0;
});

test('mobile section switching keeps the same draft tree and never writes desktop preferences', () => {
  let panel = 'editor';
  const Layout = load('ThreeColumnLayout', {
    react: { ...React, ...hooks, useState: () => [panel, next => { panel = next; }] },
  });
  const draft = element('textarea', { defaultValue: 'Unsaved shot 13' });
  const props = { leftPanel: 'Source', centerContent: '13 shots', rightPanel: draft };
  for (const index of [1, 2, 0]) {
    const tree = Layout(props);
    const buttons = nodes(tree).filter(node => node.type === 'button' && node.props['aria-pressed'] !== undefined);
    buttons[index].props.onClick();
    const next = Layout(props);
    assert.equal(next.props['data-mobile-panel'], ['editor', 'list', 'source'][index]);
    assert.equal(nodes(next).filter(node => node === draft).length, 1);
    assert.equal(next.props.children[3].props.style.width, 0, 'desktop collapsed width is not changed');
  }
  mobileRule(".generate-columns[data-mobile-panel='editor']", 'display', 'block');
  mobileRule('.generate-columns > [data-panel]', 'width', '100%');
  mobileRule('.generate-columns > [data-panel]', 'display', 'none');
});

test('split editor exposes its existing save callback for touch and keyboard with busy/read-only guards', () => {
  let saves = 0;
  const effects = [];
  let keydown;
  const Form = load('ShotForm', {
    react: { ...React, ...hooks, useEffect: fn => effects.push(fn) },
  }, { window: { addEventListener: (_name, fn) => { keydown = fn; }, removeEventListener() {} } });
  const props = { shotIndex: 13, shotData: shots[12], onSave: () => { saves += 1; } };
  const tree = Form(props);
  const save = nodes(tree).find(node => node.type === 'button' && node.props.className.includes('bg-green-600'));
  assert.equal(save.props.disabled, false);
  save.props.onClick();
  const cleanup = effects.find(fn => fn.toString().includes('keydown'))();
  keydown({ ctrlKey: true, key: 's', preventDefault() {} });
  cleanup();
  assert.equal(saves, 2);
  for (const guard of [{ isSaving: true }, { readOnly: true }]) {
    const guarded = nodes(Form({ ...props, ...guard })).find(node => node.type === 'button' && node.props.className.includes('bg-green-600'));
    assert.equal(guarded.props.disabled, true);
  }
});

test('split form labels the built timeline rather than claiming the visual estimate is resolved audio', () => {
  const Form = load('ShotForm');
  const props = { shotIndex: 1, showDuration: true, shotData: {
    ...shots[0], duration: 4, estimatedDuration: 4, audioStatus: 'READY',
    videoDirectorPlan: { audio_timeline: { resolved_duration: 9.25 } },
  } };
  const html = renderToStaticMarkup(Form(props));
  assert.match(html, /已构建 Timeline 时长：9.25/);
  assert.doesNotMatch(html, /当前 resolved duration/);
  assert.match(renderToStaticMarkup(Form({ ...props, shotData: { ...props.shotData, audioStatus: 'STALE' } })), /尚未就绪/);
  assert.match(renderToStaticMarkup(Form({ ...props, shotData: { ...props.shotData, videoDirectorPlan: { audio_timeline: { resolved_duration: null } } } })), /尚未就绪/);
});

test('batch options select once on touch/keyboard, allow touch scrolling, and retain mouse drag selection', () => {
  let toggles = 0, starts = 0, enters = 0;
  const Option = load('BatchShotOption');
  const option = Option({ selected: true, disabled: false, 'aria-label': 'Shot 13',
    onToggle: () => { toggles += 1; }, onSelectionStart: () => { starts += 1; }, onSelectionEnter: () => { enters += 1; },
  });
  assert.equal(option.type, 'button');
  assert.equal(option.props['aria-pressed'], true);
  option.props.onPointerDown({ pointerType: 'touch' });
  option.props.onPointerEnter({ pointerType: 'touch' });
  assert.equal(starts + enters + toggles, 0, 'scrolling does not select on pointerdown');
  option.props.onClick({ detail: 1 });
  assert.equal(toggles, 1);
  option.props.onPointerDown({ pointerType: 'mouse' });
  option.props.onPointerEnter({ pointerType: 'mouse' });
  option.props.onClick({ detail: 1 });
  assert.equal(starts, 1);
  assert.equal(enters, 1);
  assert.equal(toggles, 1, 'mouse click does not double-toggle after drag start');
  option.props.onClick({ detail: 0 });
  assert.equal(toggles, 2, 'native Enter/Space click');
  for (const name of ['ShotImageGenTab', 'AudioGenTab', 'VideoGenTab']) {
    assert.match(source(name), /grid-cols-2 (?:gap-3 )?lg:grid-cols-4/);
    assert.match(source(name), /<BatchShotOption/);
    assert.match(source(name), /pointercancel/);
    assert.match(source(name), /<GenerateDialog/);
  }
});

test('dialogs use native modal focus containment, Escape, scroll lock, and focus restoration', () => {
  let setup, shown = 0, closed = 0, focused = 0, dismissed = 0;
  const document = { body: { style: { overflow: 'auto' } }, activeElement: { isConnected: true, focus: () => { focused += 1; } } };
  const Dialog = load('GenerateDialog', {
    react: { ...React, ...hooks, useRef: () => ({ current: { showModal: () => { shown += 1; }, close: () => { closed += 1; } } }), useEffect: fn => { setup = fn; } },
    'react-dom': { createPortal: tree => tree },
  }, { document });
  const dialog = Dialog({ label: 'Resources', onClose: () => { dismissed += 1; }, children: element('div') });
  assert.equal(dialog.type, 'dialog');
  assert.equal(dialog.props['aria-label'], 'Resources');
  const cleanup = setup();
  assert.equal(shown, 1);
  assert.equal(document.body.style.overflow, 'hidden');
  dialog.props.onCancel({ preventDefault() {} });
  assert.equal(dismissed, 1);
  Dialog({ label: 'Busy', busy: true, onClose: assert.fail }).props.onCancel({ preventDefault() {} });
  cleanup();
  assert.equal(document.body.style.overflow, 'auto');
  assert.equal(closed, 1);
  assert.equal(focused, 1);
  assert.match(source('ChapterResourcesModal'), /grid-cols-1 lg:grid-cols-3/);
});

test('footer retains previous/next while collapsed and scrolls to measured thumbnails on resize/reopen', () => {
  const effects = [];
  let resized, observed, disconnected = false, width = 96, viewport = 390;
  const scroller = { scrollLeft: 0, get clientWidth() { return viewport; }, getBoundingClientRect: () => ({ left: 0 }), scrollTo({ left }) { this.scrollLeft = left; } };
  scroller.children = shots.map((_, i) => ({ get offsetWidth() { return width; }, getBoundingClientRect: () => ({ left: 16 + i * (width + 8) - scroller.scrollLeft }) }));
  const Footer = load('BottomNavigator', {
    './ShotThumbnail': { ShotThumbnail: () => null },
    react: { ...React, ...hooks, useRef: () => ({ current: scroller }), useEffect: fn => effects.push(fn) },
  }, { ResizeObserver: class { constructor(fn) { resized = fn; } observe(target) { observed = target; } disconnect() { disconnected = true; } } });
  for (const collapsed of [true, false]) {
    const html = renderToStaticMarkup(Footer({ shots, collapsed }));
    assert.match(html, /aria-label="chapterGenerate.previousShot"/);
    assert.match(html, /aria-label="chapterGenerate.nextShot"/);
    assert.match(html, new RegExp(`aria-expanded="${!collapsed}"`));
  }
  const cleanup = effects.filter(fn => fn.toString().includes('ResizeObserver')).at(-1)();
  assert.equal(observed, scroller);
  assert.equal(scroller.scrollLeft, 16 + 12 * 104 - (390 - 96) / 2);
  width = 128; viewport = 800;
  resized();
  assert.equal(scroller.scrollLeft, 16 + 12 * 136 - (800 - 128) / 2);
  cleanup();
  assert.equal(disconnected, true);
  mobileRule('.generate-nav-space', 'height', 'calc(var(--generate-nav-height) + env(safe-area-inset-bottom, 0px))');
  mobileRule('.generate-bottom-nav', 'padding-bottom', 'env(safe-area-inset-bottom, 0px)');
  mobileRule('.coffee-floating-control', 'display', 'none');
});

test('mobile-only sizing frees all four workflows from clipped/fixed ancestors and keeps controls touch-sized', () => {
  for (const selector of ['.generate-columns', '.generate-split-tab', '.generate-image-content', '.shot-image-form-panel', '.generate-audio-content', '.generate-audio-editor', '.generate-video-content', '.video-main-column']) {
    mobileRule(selector, 'height', 'auto');
    mobileRule(selector, 'overflow', 'visible');
  }
  mobileRule('.shot-image-form-panel', 'width', '100%');
  mobileRule('.generate-director-grid', 'grid-template-columns', 'minmax(0, 1fr)');
  mobileRule('.generate-event-list', 'max-height', '12rem');
  mobileRule('.generate-voices', 'order', '1');
  mobileRule('.generate-audio-timeline', 'order', '-1');
  mobileRule('.generate-dialog) button', 'min-height', '44px');
  mobileRule('.generate-stats', 'width', '100%');
});

test('#shot-1 video statistics stay after all four entrances, collapsed by default, with inline filters when expanded', () => {
  const previous = { ...state };
  Object.assign(state, { currentShotId: 's1', currentShotIndex: 1, currentTab: 3, shots: shots.map(shot => ({ ...shot, videoUrl: 'saved.mp4' })) });
  const values = [];
  let cursor = 0;
  const Layout = loadLayout({ react: { ...React, ...hooks, useState: initial => {
    const index = cursor++;
    if (!(index in values)) values[index] = typeof initial === 'function' ? initial() : initial;
    return [values[index], next => { values[index] = next; }];
  } } });
  const render = () => { cursor = 0; return Layout({}); };
  const statsFrom = tree => nodes(tree).find(node => node.type === 'section' && node.props.className?.includes('generate-statistics'));
  try {
    let tree = render();
    let stats = statsFrom(tree);
    const siblings = React.Children.toArray(tree.props.children);
    const tabIndex = siblings.findIndex(node => node.props.className?.includes('generate-stage-navigation'));
    assert.ok(tabIndex > 0);
    assert.ok(siblings[tabIndex + 1].props.className.includes('generate-statistics'));
    assert.ok(siblings[tabIndex + 2].props.className.includes('generate-workspace'));
    assert.equal(stats.props['data-expanded'], false);
    const summary = nodes(stats).find(node => node.props['aria-controls'] === 'generate-stat-details');
    assert.equal(summary.props['aria-expanded'], false);
    assert.match(renderToStaticMarkup(summary), /13\/13/);
    summary.props.onClick();
    stats = statsFrom(render());
    assert.equal(stats.props['data-expanded'], true);
    const filters = nodes(stats).filter(node => node.props['aria-controls'] === 'generate-filtered-shots');
    assert.equal(filters.length, 6, 'desktop and expanded mobile keep all counts');
    filters[0].props.onClick();
    stats = statsFrom(render());
    const results = nodes(stats).find(node => node.props.id === 'generate-filtered-shots');
    assert.equal(nodes(results).filter(node => node.type === 'button').length, 13);
    for (const node of nodes(stats)) {
      assert.doesNotMatch(node.props.className || '', /\b(?:absolute|fixed|sticky)\b|\bz-/);
      assert.equal(node.props.style?.position, undefined);
    }
    mobileRule(".generate-statistics[data-expanded='false'] .generate-stat-details", 'display', 'none');
    css.walkRules(rule => {
      if (!/generate-stat/.test(rule.selector)) return;
      rule.walkDecls(decl => {
        assert.notEqual(decl.prop, 'z-index');
        if (decl.prop === 'position') assert.equal(decl.value, 'static');
      });
    });
  } finally {
    Object.assign(state, previous);
  }
});

test('four mobile stage buttons use equal grid tracks, short visible labels and full accessible names', () => {
  const Tabs = load('TabNavigation');
  const buttons = nodes(Tabs()).filter(node => node.type === 'button');
  const fullNames = ['tabShotSplit', 'tabShotImage', 'tabAudioGen', 'tabVideoGen'];
  assert.equal(buttons.length, 4);
  for (const [index, button] of buttons.entries()) {
    assert.equal(button.props['aria-label'], `chapterGenerate.${fullNames[index]}`);
    assert.equal(button.props.title, button.props['aria-label']);
    const short = nodes(button).find(node => node.props.className === 'lg:hidden' && node.props['aria-hidden']);
    assert.equal(short.props.children, `chapterGenerate.${fullNames[index]}Short`);
    assert.match(renderToStaticMarkup(button), /<svg/);
  }
  const grid = nodes(Tabs()).find(node => node.props.className?.includes('generate-tabs'));
  assert.match(grid.props.className, /grid grid-cols-4 lg:flex/);
  assert.doesNotMatch(grid.props.className, /overflow|hidden/);
  for (const width of [320, 390, 768, 1023]) {
    const trackWidth = (width - 24 - 16 - 3 * 4) / 4;
    assert.ok(trackWidth >= 44, `${width}px leaves four touch-sized tracks`);
  }
  mobileRule('.generate-tabs > button', 'min-width', '44px');
});

// Render the actual toolbar JSX without invoking component effects or any action handler.
function toolbarButton(file, handler, overrides = {}) {
  const ast = ts.createSourceFile(file, source(file), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let button;
  const normalize = text => text.replace(/\s/g, '');
  function visit(node) {
    if (ts.isJsxElement(node) && node.openingElement.tagName.getText(ast) === 'button') {
      const click = node.openingElement.attributes.properties.find(attr => attr.name?.getText(ast) === 'onClick');
      if (!button && click?.initializer && normalize(click.initializer.expression.getText(ast)) === normalize(handler)) button = node.getText(ast);
    }
    ts.forEachChild(node, visit);
  }
  visit(ast);
  assert.ok(button, `${file}: ${handler}`);
  const exports = {};
  vm.runInNewContext(ts.transpileModule(`export const button = (${button});`, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
  }).outputText, {
    exports, require, ...require('lucide-react'), t: key => key, [handler]: () => {},
    isSaving: false, isExporting: false, isImporting: false, isSplitting: false, isAddingShot: false,
    isDownloading: false, isDownloadingCurrentShotImageData: false, isDownloadingShotImageData: false,
    isRefreshingVideo: false, isGeneratingCurrent: false, isGeneratingAll: false, isCancellingVideo: false,
    isShotVideoGenerating: false, isRecommending: false, saving: false, loading: false,
    preparingAudio: false, batchPreparing: false, readOnly: false, currentShotIndex: 1, collapsed: false,
    chapterId: 'c', effectiveChapterId: 'c', currentShotId: 's1', currentVideoGenerateDisabledReason: '',
    shots, shotsList: shots, shotData: shots[0], onSave() {}, previousChapter: null, nextChapter: null,
    ...overrides,
  });
  return exports.button;
}

test('common secondary actions are icon-only on mobile with full names/titles and unchanged handlers', () => {
  const cases = [
    ['ShotSplitTab', 'handleSave', 'Save'], ['ShotSplitTab', 'handleExport', 'Download'],
    ['ShotSplitTab', 'handleImport', 'Upload'], ['ShotSplitTab', 'openStructureEditor', 'FileJson'],
    ['ShotForm', '() => onSave()', 'Save'], ['ShotImageGenTab', 'handleSaveShot', 'Save'],
    ['ShotImageGenTab', 'handleDownloadCurrentShotImageData', 'Download'],
    ['ShotImageGenTab', 'handleDownloadShotImageData', 'Package'],
    ['ShotImageGenTab', 'handleViewMergedImage', 'Users'], ['ShotImageGenTab', 'handleViewMergedPropImage', 'Box'],
    ['AudioGenTab', 'saveEvent', 'Save'], ['AudioGenTab', 'loadAudioDrive', 'RefreshCw'],
    ['VideoGenTab', 'handleSaveShot', 'Save'], ['VideoGenTab', 'handleDownloadMaterials', 'Download'],
    ['VideoGenTab', 'handleRefreshCurrentVideo', 'RefreshCw'], ['VideoGenTab', 'onOpenPromptModal', 'Copy'],
    ['BottomNavigator', 'goToPreviousShot', 'ChevronLeft'], ['BottomNavigator', 'goToNextShot', 'ChevronRight'],
    ['ChapterGenerateLayout', '() => goToChapter(previousChapter?.id)', 'ChevronLeft'],
    ['ChapterGenerateLayout', '() => goToChapter(nextChapter?.id)', 'ChevronRight'],
    ['ShotImageList', 'handlePrevious', 'ChevronLeft'], ['ShotImageList', 'handleNext', 'ChevronRight'],
  ];
  for (const [file, handler, icon] of cases) {
    const onClick = () => assert.fail('must not invoke actions');
    const button = toolbarButton(file, handler, { [handler]: onClick });
    assert.ok(button.props['aria-label'], `${file}: ${handler} has a full name`);
    assert.ok(button.props.title.includes(button.props['aria-label']), `${file}: title retains full name`);
    if (!handler.includes('=>')) assert.equal(button.props.onClick, onClick);
    assert.ok(nodes(button).some(node => node.type === require('lucide-react')[icon]));
    const text = nodes(button).filter(node => node.type === 'span');
    for (const label of text) assert.equal(label.props.className, 'hidden lg:inline');
    assert.match(renderToStaticMarkup(button), /<svg/);
  }
  mobileRule('.generate-icon-action', 'width', '44px');
  mobileRule('.generate-icon-action', 'height', '44px');
  assert.equal(toolbarButton('ShotSplitTab', 'handleSave', { isSaving: true }).props.disabled, true);
  assert.equal(toolbarButton('BottomNavigator', 'goToPreviousShot').props.disabled, true, '#shot-1 cannot go backwards');
});

test('generation, batch and cancellation actions retain visible mobile context and full desktop labels', () => {
  for (const [file, handler] of [
    ['ShotSplitTab', 'handleSplit'], ['ShotImageGenTab', "() => handleGenerateShot('llm')"],
    ['ShotImageGenTab', 'handleOpenBatchSelect'], ['AudioGenTab', 'prepareCurrentShotAudio'],
    ['AudioGenTab', 'openBatchAudioModal'], ['VideoGenTab', "() => handleGenerateVideo('llm')"],
    ['VideoGenTab', 'handleOpenBatchSelect'], ['VideoGenTab', 'handleCancelCurrentVideo'],
  ]) {
    const button = toolbarButton(file, handler);
    assert.ok(button.props['aria-label'], `${file}: ${handler}`);
    assert.ok(button.props.title.includes(button.props['aria-label']));
    assert.match(button.props.className, /generate-short-action/);
    assert.ok(nodes(button).some(node => node.props.className === 'lg:hidden' && node.props['aria-hidden'] && node.props.children));
    assert.ok(nodes(button).some(node => node.props.className === 'hidden lg:inline' && node.props.children === button.props['aria-label']));
  }
});
