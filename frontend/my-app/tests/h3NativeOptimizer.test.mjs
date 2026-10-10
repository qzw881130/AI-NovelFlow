import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';

async function compile(file, exported, dependencies = {}) {
  const source = await readFile(new URL(`../src/${file}`, import.meta.url), 'utf8');
  const code = ts.transpileModule(source.replace(/^import[^;]+;\s*/gm, '').replace(/^export /gm, ''), {
    compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.None, jsx: ts.JsxEmit.React },
  }).outputText;
  return new Function('React', ...Object.keys(dependencies), `${code}; return ${exported};`)(React, ...Object.values(dependencies));
}
const H3AVTimeline = await compile('components/H3AVTimeline.tsx', 'H3AVTimeline');
const H3OptimizerResult = await compile('pages/ChapterGenerate/components/H3OptimizerResult.tsx', 'H3OptimizerResult', { H3AVTimeline });
const render = record => renderToStaticMarkup(React.createElement(H3OptimizerResult, { record }));

test('native prompt and internal AV timing render independently', () => {
  const html = render({ status: 'OPTIMIZED', original_duration: 13.1, optimized_duration: 15, effective_duration: 15,
    duration_source: 'H3_PROMPT_OPTIMIZER', optimized_prompt: 'subject_definitions:\nsummary:\ndetailed_description:\n<Subject 1> (S1) asks, <d>[Chinese] 问？</d>',
    output: { av_timeline: { original_duration: 13.1, optimized_duration: 15, duration_delta: 1.9,
      dialogue_events: [{ id: 'D3', speaker: '<Subject 1>', original_start: 5.15, original_end: 8.15, optimized_start: 5.35, optimized_end: 8.35 }],
      anchors: [{ id: 'KF2', original_time: 4.95, optimized_time: 4.75, visual_state_changed: false, prompt_excerpt: 'Develop toward the upright arrangement.' }],
      execution_phases: [{ id: 'P00', type: 'CAMERA', start: 0, end: 15, description: 'Internal camera planning' }] } } });
  assert.match(html, /已采用优化提示词/);
  assert.match(html, /H3_PROMPT_OPTIMIZER/);
  assert.match(html, /5\.35–8\.35/);
  assert.match(html, /P00 · CAMERA/);
  assert.match(html, /&lt;d&gt;\[Chinese\] 问？&lt;\/d&gt;/);
});

test('failed preflight clearly reports stopped generation, with no Raw continuation claim', () => {
  const html = render({ status: 'FALLBACK', generation_blocked: true, error: 'bad native dialogue' });
  assert.match(html, /校验未通过，生成已停止/);
  assert.match(html, /未提交视频生成/);
  assert.doesNotMatch(html, /使用 Raw Prompt 继续生成/);
});

test('historical fallback records retain their original meaning', () => {
  assert.match(render({ status: 'FALLBACK' }), /已回退 Raw Prompt/);
});

test('anchor point events remain inspectable next to positive-duration phases', () => {
  const html = render({ status: 'OPTIMIZED', output: { av_timeline: {
    original_duration: 13.1, optimized_duration: 15, duration_delta: 1.9,
    execution_phases: [
      { id: 'P09', type: 'ANCHOR_ARRIVAL', start: 5.1, end: 5.1, description: 'Point arrival.' },
      { id: 'P18', type: 'FINAL_SETTLE', start: 14.35, end: 15, description: 'Duration-bearing settle.' },
    ],
  } } });
  assert.match(html, /P09 · ANCHOR_ARRIVAL/);
  assert.match(html, /5\.10–5\.10/);
  assert.match(html, /14\.35–15\.00/);
  assert.doesNotMatch(html, /NaN|Infinity|FAIL/);
});

test('anchor choices show dropped references without inventing an arrival time', () => {
  const html = render({ status: 'OPTIMIZED', output: {
    canonical_visual_requirements: [{ id: 'V1', requirement: 'Keep both hands empty.' }],
    reference_projection: [{ source_picture: '<Picture 4>', picture: '<Picture 3>' }],
    av_timeline: { original_duration: 13.1, optimized_duration: 15,
      anchors: [
        { id: 'KF1', decision: 'KEEP', original_time: 0, optimized_time: 0, reason: 'Opening continuity.' },
        { id: 'KF2', decision: 'RETIME', original_time: 4.95, optimized_time: 5.2, reason: 'Later acquisition.' },
        { id: 'KF3', decision: 'DROP', original_time: 13, optimized_time: null,
          reason: 'Distant composition competes with speaking face.', released_constraint: 'Exact frame distance.', preserved_visual_requirements: ['V1'] },
      ] },
  } });
  assert.match(html, /KF1 · KEEP/);
  assert.match(html, /KF2 · RETIME/);
  assert.match(html, /KF3 · DROP/);
  assert.match(html, /不使用该参考图/);
  assert.match(html, /保留视觉要求：V1/);
  assert.match(html, /Keep both hands empty/);
  assert.match(html, /&lt;Picture 4&gt;/);
  assert.doesNotMatch(html, /NaN|Infinity/);
});
