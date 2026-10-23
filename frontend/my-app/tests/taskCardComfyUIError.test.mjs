import assert from 'node:assert/strict';
import test from 'node:test';
import { renderToStaticMarkup } from 'react-dom/server';
import { baseTask, renderCard, elements } from './taskCardGenerationInputs.test.mjs';
const error = { error_code: 'COMFYUI_CONNECTION_FAILED', stage: 'PREVIOUS_AV_UPLOAD', configured_url: 'http://192.168.50.1:8288',
  effective_url: 'http://127.0.0.1:8188', underlying_error: 'Connection refused', http_status: 502, attempts: 4, prompt_submitted: false };
const failed = value => ({ ...baseTask, status: 'failed', errorMessage: '视频上传失败 (HTTP 502:)', comfyuiError: value });
test('structured connection error takes priority over legacy empty 502 message', () => {
  const html = renderToStaticMarkup(renderCard(failed(error)));
  for (const text of ['ComfyUI 连接失败 · Previous AV 上传', '127.0.0.1:8188 · Connection refused · 已尝试 4 次']) assert.ok(html.includes(text), text);
  assert.doesNotMatch(html, /视频上传失败 \(HTTP 502:\)|data-comfyui-error-details|traceback/i);
});
test('config failure has a clear configuration message without invented cause', () => {
  const html = renderToStaticMarkup(renderCard(failed({ ...error, error_code: 'COMFYUI_CONFIG_NOT_INITIALIZED', underlying_error: 'Product task did not load ComfyUI runtime configuration', http_status: null, attempts: 0 })));
  assert.match(html, /ComfyUI 配置未初始化/); assert.match(html, /产品任务未加载 ComfyUI runtime configuration/);
  assert.doesNotMatch(html, /Connection refused|HTTP 502|已尝试 4 次/);
});
test('expanded details preserve cause, endpoints, status, attempts and submission independently', () => {
  const html = renderToStaticMarkup(renderCard(failed({ ...error, proxy: 'http://127.0.0.1:7897' }), { expandedErrors: new Set(['task']) }));
  for (const text of ['Error Code','COMFYUI_CONNECTION_FAILED','Stage','PREVIOUS_AV_UPLOAD','Configured Endpoint','http://192.168.50.1:8288',
    'Effective Endpoint','http://127.0.0.1:8188','Underlying Error','Connection refused','HTTP Status','502','Attempts','Prompt Submitted','否','Proxy','http://127.0.0.1:7897']) assert.ok(html.includes(text), text);
});
test('even short errors expand without HTTP or task retry', () => {
  const toggled = []; const tree = renderCard(failed(error), { onToggleError: id => toggled.push(id), onRetry: () => assert.fail('must not retry') });
  const toggle = elements(tree, e => e.type === 'button' && e.props['aria-expanded'] === false)[0];
  assert.ok(toggle); toggle.props.onClick(); assert.deepEqual(toggled, ['task']);
});
test('missing configured endpoint and proxy are omitted without fabrication', () => {
  const html = renderToStaticMarkup(renderCard(failed({ ...error, configured_url: undefined, http_status: null }), { expandedErrors: new Set(['task']) }));
  assert.doesNotMatch(html, /Configured Endpoint|Proxy|undefined/); assert.match(html, /HTTP Status/); assert.match(html, /—/);
});
test('legacy errors remain a compatibility fallback', () => {
  const html = renderToStaticMarkup(renderCard(failed(undefined)));
  assert.match(html, /视频上传失败 \(HTTP 502:\)/); assert.doesNotMatch(html, /data-comfyui-error/);
});
test('completed cards do not show stale persisted errors', () => {
  assert.doesNotMatch(renderToStaticMarkup(renderCard({ ...baseTask, comfyuiError: error })), /data-comfyui-error/);
});
