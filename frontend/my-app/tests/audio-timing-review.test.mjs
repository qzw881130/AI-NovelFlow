import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const require = createRequire(import.meta.url);
const componentPath = '../src/pages/ChapterGenerate/components/';
const reviewSource = readFileSync(new URL(`${componentPath}AudioTimingReview.tsx`, import.meta.url), 'utf8');
const exports = {};
vm.runInNewContext(ts.transpileModule(reviewSource, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
}).outputText, { exports, require });
const Review = exports.AudioTimingReview;
const summary = {
  ttsCoverageComplete: true, measuredTtsDurationSeconds: 1.097,
  visualEstimatedFloorSeconds: 7, resolvedDurationSeconds: 7,
  lastTtsFileEndSeconds: 1.097, authoredFinalPauseSeconds: 1.2,
  remainingNonSpeechHoldSeconds: 5.903, holdAfterAuthoredFinalPauseSeconds: 4.703,
  longTailReviewSuggested: true,
};

test('timing review distinguishes file coverage, authored pause and action hold without editing media', () => {
  const timeline = { status: 'READY', timingSummary: structuredClone(summary) };
  const before = structuredClone(timeline);
  const html = renderToStaticMarkup(React.createElement(Review, { timeline }));
  for (const value of ['1.097s', '1.2s', '5.903s', '4.703s', '最后 TTS 文件结束', '不代表真实发音或动作结束点', '不自动裁切']) {
    assert.ok(html.includes(value), value);
  }
  assert.doesNotMatch(html, /<(button|input|audio|video)\b/);
  assert.deepEqual(timeline, before);
});

test('unready timing keeps unknown values unknown and never suggests a cut', () => {
  const html = renderToStaticMarkup(React.createElement(Review, { timeline: {
    status: 'STALE', timingSummary: { ...summary, ttsCoverageComplete: false,
      lastTtsFileEndSeconds: null, authoredFinalPauseSeconds: null,
      remainingNonSpeechHoldSeconds: null, holdAfterAuthoredFinalPauseSeconds: null },
  } }));
  assert.match(html, /尚未全部就绪/);
  assert.match(html, /--/);
  assert.doesNotMatch(html, /扣除设定停顿后/);
  assert.equal(renderToStaticMarkup(React.createElement(Review, { timeline: {} })), '');
});

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

test('late AudioDrive responses cannot replace the currently selected shot data', async () => {
  const source = readFileSync(new URL(`${componentPath}AudioGenTab.tsx`, import.meta.url), 'utf8');
  const ast = ts.createSourceFile('AudioGenTab.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let declaration;
  function visit(node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(ast) === 'loadAudioDrive') declaration = node.getText(ast);
    ts.forEachChild(node, visit);
  }
  visit(ast);
  assert.ok(declaration);
  for (const rejectOld of [false, true]) {
    const oldEvents = deferred(), oldTimeline = deferred();
    const state = {};
    const context = {
      exports: {}, console: { error() {} }, currentShot: { id: 's1' }, loadRequestRef: { current: 0 },
      setLoading: value => { state.loading = value; },
      setEvents: value => { state.events = value; }, setTimeline: value => { state.timeline = value; },
      setAudioStatus: value => { state.status = value; }, setMessage: value => { state.message = value; },
      setSelectedEventId: update => { state.selected = update(state.selected); },
      loadClipWindowsFromShot: () => { state.windowLoads = (state.windowLoads || 0) + 1; },
      audioDriveApi: {
        fetchEvents: id => id === 's1' ? oldEvents.promise : Promise.resolve({ data: { events: [{ id: 'event-13', shotId: id }], audioStatus: 'READY' } }),
        fetchTimeline: id => id === 's1' ? oldTimeline.promise : Promise.resolve({ data: { shotId: id } }),
      },
    };
    vm.runInNewContext(ts.transpileModule(`export const ${declaration};`, {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    }).outputText, context);
    const oldLoad = context.exports.loadAudioDrive();
    context.currentShot = { id: 's13' };
    await context.exports.loadAudioDrive();
    if (rejectOld) oldEvents.reject(new Error('old request failed'));
    else oldEvents.resolve({ data: { events: [{ id: 'event-1' }], audioStatus: 'STALE' } });
    oldTimeline.resolve({ data: { shotId: 's1' } });
    await oldLoad;
    assert.equal(state.timeline.shotId, 's13');
    assert.equal(state.events[0].id, 'event-13');
    assert.equal(state.selected, 'event-13');
    assert.equal(state.status, 'READY');
    assert.equal(state.windowLoads, undefined, 'window updates belong to the current-plan effect');
    assert.equal(state.loading, false);
    assert.equal(state.message, undefined);
  }
});
