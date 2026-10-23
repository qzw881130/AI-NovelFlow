import assert from 'node:assert/strict';
import test from 'node:test';
import { build } from 'esbuild';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || '/Users/qianzhiwei/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');

const mocks = {
  i18nStore: `export const useTranslation = () => ({ t: (key, params) => {
    const labels = {
      'promptConfig.systemDefault': '系统默认', 'promptConfig.userCustom': '用户自定义',
      'promptConfig.lastModified': '最后修改', 'promptConfig.unknown': '未知',
      'promptConfig.boundNovels': '绑定小说', 'promptConfig.loadingBindings': '正在加载绑定小说…',
      'promptConfig.loadBindingsFailed': '绑定小说查询失败', 'promptConfig.noBoundNovels': '暂无小说显式绑定此模板',
      'promptConfig.author': '作者', 'promptConfig.bindingType': '绑定方式',
      'promptConfig.explicitBinding': '显式指定', 'promptConfig.boundNovelCount': '共 {count} 本小说',
      'common.close': '关闭', 'common.view': '查看', 'common.download': '下载',
      'common.edit': '编辑', 'common.delete': '删除', 'promptConfig.copyAsUser': '复制为用户模板',
    };
    return (labels[key] || key).replace('{count}', String(params?.count ?? ''));
  } });`,
  usePromptConfigState: `export const TEMPLATE_TYPE_CONFIG = { keyframe_planner: { fileNumber: '08' } };`,
  promptTemplates: `export const promptTemplateApi = { fetchBoundNovels: (id, signal) => window.__fetchBoundNovels(id, signal) };`,
  router: `import React from 'react'; export const Link = ({to, onClick, children, ...props}) =>
    React.createElement('a', { href: to, ...props, onClick: event => { event.preventDefault(); history.pushState({}, '', to); onClick?.(event); } }, children);`,
};

const entry = `
  import React, { useState } from 'react';
  import { createRoot } from 'react-dom/client';
  import { TemplateCard } from './src/pages/PromptConfig/components/TemplateCard';
  import { BoundNovelsModal } from './src/pages/PromptConfig/components/BoundNovelsModal';
  const templates = [
    { id: 'system', name: '系统模板', description: '系统', template: 'body', type: 'keyframe_planner', isSystem: true, lastModifiedAt: '2026-10-15T02:03:00+00:00' },
    { id: 'custom', name: '自定义模板', description: '用户', template: 'body', type: 'keyframe_planner', isSystem: false, lastModifiedAt: '2026-10-14T01:02:00+00:00' },
    { id: 'inline', name: '无文件模板', description: '内置', template: 'body', type: 'keyframe_planner', isSystem: true, lastModifiedAt: null },
  ];
  function App() {
    const [selected, setSelected] = useState(null);
    window.selectTemplate = id => setSelected(templates.find(item => item.id === id));
    return <div>{templates.map(template => <TemplateCard key={template.id} template={template} type="keyframe_planner"
      onView={() => {}} onEdit={() => {}} onCopy={() => {}} onDelete={() => {}} onBindings={setSelected}
      getDisplayName={item => item.name} getDisplayDescription={item => item.description} />)}
      {selected && <BoundNovelsModal key={selected.id} template={selected} onClose={() => setSelected(null)} getDisplayName={item => item.name} />}
    </div>;
  }
  createRoot(document.getElementById('root')).render(<App />);
`;

const bundle = await build({
  stdin: { contents: entry, resolveDir: new URL('..', import.meta.url).pathname, sourcefile: 'prompt-test.tsx', loader: 'tsx' },
  bundle: true, write: false, platform: 'browser', format: 'iife', jsx: 'automatic',
  plugins: [{ name: 'mock-dependencies', setup(builder) {
    builder.onResolve({ filter: /i18nStore|usePromptConfigState|api\/promptTemplates|react-router-dom/ }, args => {
      const key = args.path.includes('i18nStore') ? 'i18nStore'
        : args.path.includes('usePromptConfigState') ? 'usePromptConfigState'
          : args.path.includes('promptTemplates') ? 'promptTemplates' : 'router';
      return { path: key, namespace: 'mock' };
    });
    builder.onLoad({ filter: /.*/, namespace: 'mock' }, args => ({ contents: mocks[args.path], loader: 'tsx', resolveDir: new URL('..', import.meta.url).pathname }));
  }}],
});

test('cards and bound novels modal handle time, loading, empty, failure, navigation, and switching', async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const context = await browser.newContext({ timezoneId: 'Asia/Shanghai' });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('http://novelflow.test/**', route => route.fulfill({ status: 200, contentType: 'text/html', body: '<div id="root"></div>' }));
    await page.goto('http://novelflow.test/');
    await page.evaluate(() => {
      window.__requests = [];
      window.__fetchBoundNovels = (id, signal) => new Promise((resolve, reject) => window.__requests.push({ id, signal, resolve, reject }));
    });
    await page.addScriptTag({ content: bundle.outputFiles[0].text });
    const cards = page.locator('div.rounded-lg.border');
    await cards.first().waitFor();
    assert.match(await cards.nth(0).innerText(), /最后修改: 2026-10-15 10:03/);
    assert.match(await cards.nth(1).innerText(), /最后修改: 2026-10-14 09:02/);
    assert.match(await cards.nth(2).innerText(), /最后修改: 未知/);
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    await page.setViewportSize({ width: 1280, height: 900 });

    await cards.nth(0).getByRole('button', { name: '绑定小说' }).click();
    await page.getByRole('dialog', { name: '绑定小说 — 系统模板' }).waitFor();
    await page.getByText('正在加载绑定小说…').waitFor();
    await page.waitForFunction(() => window.__requests.length === 1);
    await page.evaluate(() => window.__requests[0].resolve([{ novel_id: 'n-1', novel_title: '甲小说', author: '作者甲', binding_type: 'explicit' }]));
    const dialog = page.getByRole('dialog');
    await dialog.getByRole('link', { name: '甲小说' }).waitFor();
    assert.match(await dialog.innerText(), /作者: 作者甲[\s\S]*绑定方式: 显式指定/);
    assert.match(await dialog.innerText(), /共 1 本小说/);
    assert.equal(await dialog.getByRole('link', { name: '甲小说' }).getAttribute('href'), '/novels/n-1');
    await dialog.getByRole('link', { name: '甲小说' }).click();
    assert.equal(new URL(page.url()).pathname, '/novels/n-1');
    assert.equal(await page.getByRole('dialog').count(), 0);

    await cards.nth(1).getByRole('button', { name: '绑定小说' }).click();
    await page.waitForFunction(() => window.__requests.length === 2);
    await page.evaluate(() => window.__requests[1].resolve([]));
    await page.getByText('暂无小说显式绑定此模板').waitFor();
    assert.match(await page.getByRole('dialog').innerText(), /共 0 本小说/);
    await page.getByRole('dialog').getByRole('button', { name: '关闭' }).first().click();
    assert.equal(await page.getByRole('dialog').count(), 0);

    await cards.nth(0).getByRole('button', { name: '绑定小说' }).click();
    await page.waitForFunction(() => window.__requests.length === 3);
    await page.evaluate(() => window.__requests[2].reject(new Error('failed')));
    await page.getByText('绑定小说查询失败').waitFor();
    await page.getByRole('dialog').getByRole('button', { name: '关闭' }).first().click();

    await page.evaluate(() => window.selectTemplate('system'));
    await page.waitForFunction(() => window.__requests.length === 4);
    await page.evaluate(() => window.selectTemplate('custom'));
    await page.waitForFunction(() => window.__requests.length === 5);
    assert.equal(await page.evaluate(() => window.__requests[3].signal.aborted), true);
    await page.evaluate(() => window.__requests[3].resolve([{ novel_id: 'old', novel_title: '旧小说', author: '', binding_type: 'explicit' }]));
    await page.getByRole('dialog', { name: '绑定小说 — 自定义模板' }).waitFor();
    assert.equal(await page.getByText('旧小说').count(), 0);
    await page.evaluate(() => window.__requests[4].resolve([{ novel_id: 'new', novel_title: '新小说', author: '', binding_type: 'explicit' }]));
    await page.getByRole('link', { name: '新小说' }).waitFor();
    assert.equal(await page.getByText('旧小说').count(), 0);
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
  }
});
