import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { ChevronDown, ChevronUp } from 'lucide-react';

async function loadTypeScript(relativePath) {
  const source = await readFile(new URL(relativePath, import.meta.url), 'utf8');
  const javascript = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ES2020, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  return import(`data:text/javascript;base64,${Buffer.from(javascript).toString('base64')}`);
}

const presentation = await loadTypeScript('../src/pages/ChapterGenerate/videoExecutionPresentation.ts');
const native = await loadTypeScript('../src/pages/ChapterGenerate/nativeClipPresentation.ts');
const authority = await loadTypeScript('../src/pages/ChapterGenerate/semanticClipAuthority.ts');
const page = await readFile(new URL('../src/pages/ChapterGenerate/components/VideoGenTab.tsx', import.meta.url), 'utf8');
const panelSource = page.slice(page.indexOf('const executionToneClass'), page.indexOf('interface VideoDirectorPanelProps'));
const panelJs = ts.transpileModule(panelSource, {
  compilerOptions: { jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2020 },
}).outputText;
// Existing presentation checks inspect the chain with the global preference expanded.
const components = new Function('React', 'useState', 'useId', 'ChevronDown', 'ChevronUp', 'localStorage', ...Object.keys({ ...presentation, ...native, ...authority }),
  `${panelJs}; return { ExecutionChainOverview, FinalAssemblyStatusPanel };`)(
  React, React.useState, React.useId, ChevronDown, ChevronUp, { getItem: () => 'true' }, ...Object.values({ ...presentation, ...native, ...authority }),
);

const clips = [
  { clip_index: 1, start_time: 0, end_time: 8, capability: 'GENERATE', generated_by_task_id: 'c1', video_url: '/c1.mp4', approval_status: 'APPROVED', execution_status: 'APPROVED' },
  { clip_index: 2, start_time: 8, end_time: 19.4, capability: 'EXTEND', previous_clip_index: 1, generated_by_task_id: 'c2', video_url: '/c2.mp4', approval_status: 'APPROVED', execution_status: 'APPROVED' },
  { clip_index: 3, start_time: 19.4, end_time: 33.95, capability: 'TEMPORAL_EXTEND', previous_clip_index: 2, generated_by_task_id: 'c3', video_url: '/c3.mp4', approval_status: 'APPROVED', execution_status: 'APPROVED' },
];
function task(index) {
  const clip = clips[index - 1];
  const previous = clips[index - 2];
  return { id: `c${index}`, status: 'completed', resultUrl: clip.video_url, clipExecution: {
    execution_scope: 'CLIP', clip_index: index, clip_plan_revision: 4,
    approval_status: 'APPROVED', approval_mode: 'AUTO_APPROVE',
    video_reference_manifest: { references: [] },
    physical_output: index === 1 ? undefined : { physical_output_role: 'NATIVE_CONTINUITY_OUTPUT', output_node_id: '65', result_url: clip.video_url, overlap_frames: 39, overlap_duration: 1.625, fps: 24 },
    execution_contract: index === 1 ? undefined : {
      capability: clip.capability, artifact_kind: 'NATIVE_CONTINUITY_OUTPUT',
      previous_clip: { generated_by_task_id: previous.generated_by_task_id, result_url: previous.video_url },
      temporal_anchor_manifest: { anchors: index === 3 ? [{ anchor_id: 'temporal-1', source: { id: 'KF4' }, time_seconds: 9.4, image_url: '/kf4.png' }] : [] },
    },
  } };
}
const tasks = [task(1), task(2), task(3)];
const plan = {
  canonical_visual_plan: true, clip_plan_revision: 4, clip_plan_validation: { passed: true },
  clip_plan: clips, assembly_status: 'COMPLETED', assembly_clip_plan_revision: 4,
  assembly_task_ids: tasks.map(item => item.id), merged_video_url: '/final.mp4',
  assembly_mode: 'NATIVE_OVERLAP_REPLACEMENT',
  assembled_result: { assembled_media_duration: 61.667 },
};

test('Clip rows separate generation, review and three physical input classes', () => {
  const html = renderToStaticMarkup(React.createElement(components.ExecutionChainOverview, { plan, tasks }));
  assert.match(html, /C1 · 0–8s/);
  assert.match(html, /C1[\s\S]*?GENERATE[\s\S]*?生成：完成[\s\S]*?审核：AUTO_APPROVED/);
  assert.doesNotMatch(html.match(/data-testid="execution-chain-clip-1"[\s\S]*?<\/article>/)?.[0] || '', /Previous AV：/);
  assert.match(html, /C2[\s\S]*?EXTEND[\s\S]*?Previous AV：[\s\S]*?C1 · 首段生成 AV · READY/);
  assert.match(html, /C3[\s\S]*?TEMPORAL_EXTEND[\s\S]*?C2 · Native continuity · READY/);
  assert.match(html, /Temporal Anchors：KF4 @ 9\.4s/);
  assert.match(html, /Native AV：[\s\S]*?READY[\s\S]*?Overlap 39 frames \/ 1\.625s/);
  assert.match(html, /普通图片参考：0 张/);
  assert.doesNotMatch(html, /图片准备：已就绪|manifest.*未提供或为空/);
  assert.equal(presentation.getOrdinaryImageReferenceCount(tasks[2]), 0);
  assert.equal(presentation.getMaterializedTemporalAnchors(clips[2], tasks[2])[0].label, 'KF4');
});

test('zero ordinary images and zero temporal anchors never imply image conditioning', () => {
  const html = renderToStaticMarkup(React.createElement(components.ExecutionChainOverview, { plan, tasks }));
  const c2 = html.match(/data-testid="execution-chain-clip-2"[\s\S]*?<\/article>/)?.[0] || '';
  assert.match(c2, /Previous AV：[\s\S]*?READY/);
  assert.match(c2, /普通图片参考：0 张/);
  assert.match(c2, /Temporal Anchors：0 个/);
  assert.doesNotMatch(c2, /图片准备|图片.*已就绪/);
});

test('completed assembly and failed duration acceptance coexist without hiding playback', () => {
  const html = renderToStaticMarkup(React.createElement(components.FinalAssemblyStatusPanel, { plan, tasks, targetDuration: 68 }));
  assert.match(html, /Final Assembly<\/span><strong[^>]*>COMPLETED/);
  assert.match(html, /NATIVE_OVERLAP_REPLACEMENT/);
  assert.match(html, /68\.000s/);
  assert.match(html, /61\.667s/);
  assert.match(html, /-6\.333s/);
  assert.match(html, /Duration acceptance<\/span><strong[^>]*>FAIL/);
  assert.match(page, /src=\{previewVideoUrl\}/);
  assert.match(page, /hasCurrentAssembly\(currentVideoDirectorPlan, semanticClipTasks\).*currentVideoDirectorPlan\.merged_video_url/s);
  assert.equal(presentation.getDurationPresentation(68, 61.667).acceptance, 'FAIL');
});

test('missing historical task metadata stays neutral and existing Clip actions remain', () => {
  const html = renderToStaticMarkup(React.createElement(components.ExecutionChainOverview, { plan: { clip_plan_revision: 4, clip_plan: [clips[0]] }, tasks: [] }));
  assert.match(html, /普通图片参考：未提供/);
  assert.match(html, /Temporal Anchors：0 个/);
  assert.match(page, /onRegenerateClip\(\{ \.\.\.clip, clip_index: clip\.clip_index \}, 'llm'\)/);
  assert.match(page, /onRegenerateClip\(\{ \.\.\.clip, clip_index: clip\.clip_index \}, 'video_only'\)/);
  assert.match(page, /onAssemble=\{onMergeClips\}/);
});
