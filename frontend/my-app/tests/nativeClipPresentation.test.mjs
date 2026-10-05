import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const source = await readFile(new URL('../src/pages/ChapterGenerate/nativeClipPresentation.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ES2020, target: ts.ScriptTarget.ES2020 } }).outputText;
const { getClipArtifactPresentation: artifact, getPreviousAvPresentation: previous } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
const page = await readFile(new URL('../src/pages/ChapterGenerate/components/VideoGenTab.tsx', import.meta.url), 'utf8');
const detailsSource = page.slice(page.indexOf('function ClipExecutionDetails('), page.indexOf('function SemanticClipExecutionPanel('));
const detailsJs = ts.transpileModule(detailsSource, { compilerOptions: { jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2020 } }).outputText;
const Details = new Function('React', 'getClipArtifactPresentation', 'getPreviousAvPresentation', `${detailsJs}; return ClipExecutionDetails;`)(React, artifact, previous);

const generate = { clip_index: 1, capability: 'GENERATE', continuity_to_previous: 'NONE', generated_by_task_id: 'c1', video_url: '/c1.mp4' };
const first = { id: 'c1', status: 'completed', resultUrl: '/c1.mp4', clipExecution: { approval_status: 'APPROVED', clip_plan_revision: 2, capability: 'GENERATE' } };
function native(capability = 'EXTEND', index = 2) {
  const clip = { clip_index: index, capability, continuity_to_previous: 'CONTINUOUS', previous_clip_index: index-1,
    generated_by_task_id: `c${index}`, video_url: `/c${index}.mp4`, selected_temporal_target_ids: ['KF4'] };
  const task = { id: `c${index}`, status: 'completed', resultUrl: clip.video_url, clipExecution: {
    approval_status: 'APPROVED', clip_plan_revision: 2,
    physical_output: { physical_output_role: 'NATIVE_CONTINUITY_OUTPUT', output_node_id: '65', result_url: clip.video_url,
      overlap_frames: 17, overlap_duration: 0.75, fps: 24, native_cumulative_duration: 18.625 },
    execution_contract: { capability, artifact_kind: 'NATIVE_CONTINUITY_OUTPUT', previous_clip: {
      clip_index: index-1, generated_by_task_id: `c${index-1}`, result_url: `/c${index-1}.mp4`,
    }, temporal_anchor_manifest: { anchors: [{ anchor_id: 'KF4', time_seconds: 2 }] } },
  } };
  return { clip, task };
}
function render(clip, task, previousClip = generate, previousTask = first) {
  return renderToStaticMarkup(React.createElement(Details, { clip, task, previousTask,
    plan: { clip_plan_revision: 2, clip_plan: [previousClip, clip] } }));
}

test('GENERATE and CUT preserve playback and omit native overlap', () => {
  for (const continuity of ['NONE', 'CUT']) {
    const clip = { ...generate, continuity_to_previous: continuity };
    assert.equal(artifact(clip, first).playbackUrl, '/c1.mp4');
    assert.equal(previous(clip, first).label, '无');
    assert.doesNotMatch(render(clip, first), /Native overlap|Native continuity output/);
  }
});

test('EXTEND reports exact Previous identity and honest GENERATE bootstrap role', () => {
  const { clip, task } = native();
  assert.equal(artifact(clip, task).nativeReady, true);
  assert.match(render(clip, task), /Previous AV dependency：C1 · 首段生成 AV · READY/);
  assert.match(render(clip, task), /Native continuity output：READY/);
  assert.match(render(clip, task), /生成结果：Native continuity output/);
});

test('TEMPORAL_EXTEND retains selected targets and materialized anchors alongside native Previous', () => {
  const predecessor = native();
  const { clip, task } = native('TEMPORAL_EXTEND', 3);
  const html = render(clip, task, predecessor.clip, predecessor.task);
  assert.match(html, /C2 · Native continuity · READY/);
  assert.match(html, /Selected temporal targets：KF4/);
  assert.match(html, /Temporal Anchors：KF4 @ 2s/);
});

test('overlap comes from backend metadata, preferring its duration and deriving only when absent', () => {
  const { clip, task } = native();
  assert.equal(artifact(clip, task).overlapLabel, '17 frames / 0.75s');
  delete task.clipExecution.physical_output.overlap_duration;
  assert.equal(artifact(clip, task).overlapLabel, `17 frames / ${17/24}s`);
  assert.doesNotMatch(source, /\b39\b|1\.625/);
});

test('legacy raw, assembled_result and plan-only metadata cannot fake native READY or playback', () => {
  const { clip, task } = native();
  delete task.clipExecution.physical_output;
  task.clipExecution.execution_contract.artifact_kind = 'CLIP_ONLY';
  task.clipExecution.assembled_result = { url: '/raw39.mp4' };
  clip.physical_output = { physical_output_role: 'NATIVE_CONTINUITY_OUTPUT' };
  const view = artifact(clip, task);
  assert.equal(view.nativeReady, false);
  assert.equal(view.playbackUrl, null);
  assert.equal(view.outputStatus, 'Legacy / native continuity unavailable');
  assert.doesNotMatch(render(clip, task), /Native continuity output：READY/);
  const successor = native('TEMPORAL_EXTEND', 3);
  assert.doesNotMatch(previous(successor.clip, successor.task, clip, task).label, /READY/);
});

test('stale, failed, mismatched or unapproved native results are not READY', () => {
  for (const mutate of [t => t.status='failed', t => t.clipExecution.approval_status='FAILED',
    t => t.id='wrong', t => t.clipExecution.physical_output.result_url='/raw.mp4',
    t => t.clipExecution.execution_contract.capability='GENERATE']) {
    const { clip, task } = native(); mutate(task);
    assert.equal(artifact(clip, task).nativeReady, false);
    assert.equal(artifact(clip, task).playbackUrl, null);
  }
});

test('continuous native playback remains disabled; planned state is not mislabeled legacy', () => {
  const { clip, task } = native();
  assert.equal(artifact(clip, task).playbackUrl, null);
  assert.equal(artifact({ ...clip, video_url: null, generated_by_task_id: undefined }).outputStatus, '尚无 native continuity output');
  assert.match(page, /video_url: getClipArtifactPresentation\(clip, task\)\.playbackUrl/);
  assert.match(page, /selectedPreviewClipKey \? selectedPreviewClip\?\.video_url \|\| undefined/);
  assert.match(page, /isContinuation && <button type="button" disabled/);
});
