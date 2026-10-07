import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';

const source = await readFile(new URL('../src/pages/Tasks/components/TaskCard.tsx', import.meta.url), 'utf8');
const translations = new Function((await readFile(new URL('../src/i18n/locales/zh-CN/tasks.ts', import.meta.url), 'utf8'))
  .replace('export default', 'return'))().tasks;
const t = (key, params = {}) => Object.entries(params).reduce((value, [name, replacement]) =>
  value.replace(`{${name}}`, String(replacement)), translations[key.replace('tasks.', '')] || key);
const compiled = ts.transpileModule(source.replace(/^import[^;]+;\s*/gm, '').replace('export function', 'function'), {
  compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.None, jsx: ts.JsxEmit.React },
}).outputText;
const icons = ['CheckCircle', 'XCircle', 'Loader2', 'Clock', 'AlertCircle', 'Terminal', 'ChevronUp', 'ChevronDown',
  'Play', 'Code', 'Trash2', 'Film', 'ImageIcon', 'User', 'ListTodo', 'Music', 'Copy'];
const icon = props => React.createElement('svg', props);
const TaskCard = new Function('React', ...icons, 'useTranslation', 'formatUserFacingError', `${compiled};return TaskCard;`)(
  React, ...icons.map(() => icon), () => ({ t }), value => value);
globalThis.fetch = async () => assert.fail('TaskCard must not fetch or mutate product data');

export const baseTask = {
  id: 'task', name: 'Clip', type: 'shot_video', status: 'completed', progress: 100,
  createdAt: '2026-10-06T00:00:00', clipExecution: {},
};
export function renderCard(task, callbacks = {}) {
  const noop = () => {};
  return TaskCard({ task, imageInfo: {}, expandedErrors: new Set(),
    onDelete: noop, onRetry: noop, onViewWorkflow: noop, onViewClipWorkflow: noop, onToggleError: noop,
    onPreviewImage: noop, onPreviewImages: noop, onPreviewVideo: noop, fetchImageInfo: noop,
    getTaskDisplayName: value => value.name, getTaskDisplayDescription: value => value.description || '',
    getTaskTypeName: () => '视频', getWorkflowDisplayName: () => '', getStatusIcon: () => null,
    getStatusText: () => '完成', getStatusColor: () => '', formatDate: value => value, ...callbacks });
}
export function elements(tree, predicate) {
  const found = [];
  const visit = element => {
    if (Array.isArray(element)) return element.forEach(visit);
    if (!React.isValidElement(element)) return;
    if (predicate(element)) found.push(element);
    visit(element.props.children);
  };
  visit(tree); return found;
}

const previous = { clip_index: 1, result_url: '/previous.mp4' };
const anchor = { image_url: '/kf3.png', source: { id: 'KF3', keyframe_index: 3 }, slot: 1, frame_position: 135 };
const taskWithInputs = (anchors = [anchor]) => ({ ...baseTask, clipExecution: {
  previous_approved_video_url: '/previous.mp4',
  execution_contract: { previous_clip: previous, temporal_anchor_manifest: { anchors } },
} });

test('Previous AV and temporal anchor render separately with source, temporal slot and frame', () => {
  const task = taskWithInputs(), before = structuredClone(task);
  const html = renderToStaticMarkup(renderCard(task));
  for (const text of ['生成输入', '参考视频', 'Previous AV · C1', '时间锚点', 'KF3 · 时间槽 1 · 帧 135', '/kf3.png', '/previous.mp4'])
    assert.ok(html.includes(text), text);
  assert.doesNotMatch(html, /普通参考图|Picture|FIRST_FRAME|图片准备/);
  assert.deepEqual(task, before);
});

test('Previous AV-only cards do not manufacture image groups or readiness', () => {
  for (const anchors of [[], undefined]) {
    const task = taskWithInputs([]);
    task.clipExecution.execution_contract.temporal_anchor_manifest.anchors = anchors;
    const html = renderToStaticMarkup(renderCard(task));
    assert.match(html, /Previous AV · C1/);
    assert.doesNotMatch(html, /时间锚点|普通参考图|图片准备|Picture/);
  }
});

test('ordinary Director Visual reference stays Picture1, with its exact original preview list', () => {
  const refs = [{ label: 'Director Visual Ref 1', url: '/bootstrap.png' }];
  const preview = [];
  const tree = renderCard({ ...baseTask, referenceImages: refs }, { onPreviewImages: (...args) => preview.push(args) });
  const html = renderToStaticMarkup(tree);
  assert.match(html, /普通参考图/); assert.match(html, /Director Visual Anchor \/ Picture 1/);
  assert.doesNotMatch(html, /时间锚点|FIRST_FRAME|参考视频/);
  elements(tree, element => element.type === 'button' && element.props.title === 'Director Visual Anchor / Picture 1')[0].props.onClick();
  assert.equal(preview[0][0], refs); assert.equal(preview[0][1], 0);
});

test('temporal previews use only temporal images; ordinary and video callbacks remain distinct', () => {
  const ordinary = [{ label: 'Character', url: '/character.png' }], images = [], videos = [];
  const tree = renderCard({ ...taskWithInputs([anchor, { ...anchor, image_url: '/kf5.png', source: { id: 'KF5' }, slot: 2 }]), referenceImages: ordinary }, {
    onPreviewImages: (...args) => images.push(args), onPreviewVideo: url => videos.push(url),
  });
  const buttons = elements(tree, element => element.type === 'button');
  buttons.find(b => b.props.title === 'Character').props.onClick();
  buttons.find(b => b.props.title === 'KF5 · 时间槽 2 · 帧 135').props.onClick();
  buttons.find(b => b.props.title === 'Previous AV · C1').props.onClick();
  assert.equal(images[0][0], ordinary);
  assert.deepEqual(images[1][0].map(image => image.url), ['/kf3.png', '/kf5.png']);
  assert.equal(images[1][1], 1); assert.deepEqual(videos, ['/previous.mp4']);
});

test('missing fields are safe; contract URL fallback works without guessing source or slots', () => {
  const empty = renderToStaticMarkup(renderCard(baseTask));
  assert.doesNotMatch(empty, /data-generation-inputs/);
  const task = { ...baseTask, clipExecution: { execution_contract: {
    previous_clip: { result_url: '/contract.mp4' },
    temporal_anchor_manifest: { anchors: [{ source: { id: 'missing-image' } }, { image_url: '/source.png', source: { id: 'custom-source' } }] },
  } } };
  const html = renderToStaticMarkup(renderCard(task));
  assert.match(html, /contract.mp4/); assert.match(html, /custom-source/);
  assert.doesNotMatch(html, /missing-image|Picture|时间槽|帧 \d|Cundefined|KFundefined/);
});

test('a URL-less planned temporal ID does not become a physical thumbnail', () => {
  const html = renderToStaticMarkup(renderCard({ ...baseTask, clipExecution: { temporal_anchor_ids: ['planned-KF9'] } }));
  assert.doesNotMatch(html, /data-generation-inputs|planned-KF9/);
});
