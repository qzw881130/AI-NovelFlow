import assert from 'node:assert/strict';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || '/Users/qianzhiwei/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const base = process.env.NOVELFLOW_TEST_URL || 'http://127.0.0.1:5173';
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, permissions: ['clipboard-read', 'clipboard-write'] });
const errors = [];
const mutations = [];
context.on('request', request => {
  if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) mutations.push(`${request.method()} ${request.url()}`);
});

try {
  const settings = await context.newPage();
  settings.on('pageerror', error => errors.push(error.message));
  await settings.goto(`${base}/settings#notifications`);
  await settings.getByRole('heading', { name: '消息通知', exact: true }).waitFor();
  for (const [name, route] of [['飞书通知', 'feishu-notifications'], ['Telegram 通知', 'telegram-notifications']]) {
    const card = settings.locator('section').filter({ has: settings.getByRole('heading', { name, exact: true }) }).first();
    const link = card.getByRole('link', { name: '配置教程' });
    assert.equal(await link.getAttribute('href'), `/help/${route}`);
    assert.equal(await link.getAttribute('target'), '_blank');
    assert.match(await link.getAttribute('rel'), /noopener/);
    assert.equal(await card.getByRole('checkbox', { name: '开启' }).count(), 1);
    const [popup] = await Promise.all([settings.waitForEvent('popup'), link.click()]);
    popup.on('pageerror', error => errors.push(error.message));
    await popup.getByRole('heading', { name: `${name}配置教程` }).waitFor();
    assert.equal(new URL(popup.url()).pathname, `/help/${route}`);
    assert.equal(new URL(settings.url()).pathname, '/settings');
    await popup.close();
  }

  for (const [route, title, steps, copyLabel, copyValue] of [
    ['telegram-notifications', 'Telegram 通知配置教程', 6, '复制创建机器人命令', '/newbot'],
    ['feishu-notifications', '飞书通知配置教程', 7, '复制Webhook 格式示例（不可用于配置）', 'https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx'],
  ]) {
    const page = await context.newPage();
    const notificationRequests = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => {
      if (request.url().includes('/api/notifications/')) notificationRequests.push(request.url());
    });
    await page.goto(`${base}/help/${route}`);
    await page.getByRole('heading', { name: title }).waitFor();
    assert.equal(await page.getByRole('heading', { name: /^步骤 \d+：/ }).count(), steps);
    assert.equal(await page.locator('section[aria-labelledby$="-faq"] details').count(), route === 'feishu-notifications' ? 7 : 6);
    assert.equal(await page.locator('input').count(), 0);
    const external = page.getByRole('link', { name: route === 'feishu-notifications' ? '打开飞书官网' : '打开 BotFather' });
    assert.equal(await external.getAttribute('target'), '_blank');
    assert.match(await external.getAttribute('rel'), /noopener/);
    await page.getByRole('button', { name: copyLabel }).click();
    assert.equal(await page.evaluate(() => navigator.clipboard.readText()), copyValue);
    assert.deepEqual(notificationRequests, []);
    await page.reload();
    await page.getByRole('heading', { name: title }).waitFor();
    assert.deepEqual(notificationRequests, []);
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    await page.getByRole('link', { name: '返回消息通知设置' }).last().click();
    await page.waitForURL(`${base}/settings#notifications`);
    await page.close();
  }

  assert.deepEqual(errors, []);
  assert.deepEqual(mutations, []);
  console.log('notification help browser checks passed: links, routes, refresh, copy, FAQ, mobile width, return, no help credential requests');
} finally {
  await browser.close();
}
