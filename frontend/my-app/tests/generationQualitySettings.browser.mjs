import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || '/Users/qianzhiwei/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const appUrl=process.env.NOVELFLOW_TEST_URL || 'http://127.0.0.1:5173';
const out=new URL('../../../docs/image-quality-review-v2/',import.meta.url);
const browser=await chromium.launch({channel:'chrome',headless:true});
const page=await browser.newPage({viewport:{width:1600,height:1100}});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
const fetchConfig=async()=> (await (await page.request.get(appUrl+'/api/config/')).json()).data;
const original=await fetchConfig();const savedBodies=[];
const control=page.getByRole('checkbox',{name:/生成图片后自动 AI 评审/});
const waitValue=async value=>{
 await page.waitForFunction(value=>[...document.querySelectorAll('label')].some(e=>e.textContent.includes('生成图片后自动 AI 评审')&&e.querySelector('input')?.checked===value),value);
};
const save=async value=>{
 await control.setChecked(value);
 const result=page.waitForResponse(r=>r.url().endsWith('/api/config/')&&r.request().method()==='POST');
 await page.locator('form button[type=submit]').click();
 const response=await result;
 savedBodies.push(response.request().postDataJSON());
 assert.deepEqual(savedBodies.at(-1),{autoImageReviewEnabled:value});
 assert.equal((await response.json()).success,true);
 assert.equal((await fetchConfig()).autoImageReviewEnabled,value);
};
try {
 await page.goto(appUrl+'/settings#llm');
 await page.getByRole('button',{name:'生成质量控制',exact:true}).waitFor();
 const labels=await page.locator('.card > div').filter({has:page.getByRole('button',{name:'消息通知',exact:true})}).first().getByRole('button').allTextContents();
 assert.equal(labels.at(-2)?.trim(),'消息通知');assert.equal(labels.at(-1)?.trim(),'生成质量控制');
 assert.equal(await control.count(),0);
 await page.getByRole('button',{name:'生成质量控制',exact:true}).click();
 assert.ok(page.url().endsWith('#generation-quality'));
 await waitValue(original.autoImageReviewEnabled);
 assert.equal(await control.count(),1);
 await save(!original.autoImageReviewEnabled);
 const loaded=page.waitForResponse(r=>r.url().endsWith('/api/config/')&&r.request().method()==='GET');
 await page.reload();await loaded;await waitValue(!original.autoImageReviewEnabled);
 await page.screenshot({path:new URL('generation-quality-enabled.png',out).pathname});
 await save(original.autoImageReviewEnabled);
 const reloaded=page.waitForResponse(r=>r.url().endsWith('/api/config/')&&r.request().method()==='GET');
 await page.reload();await reloaded;await waitValue(original.autoImageReviewEnabled);
 await page.screenshot({path:new URL('generation-quality-settings.png',out).pathname});
 await page.getByRole('button',{name:'LLM 配置',exact:true}).click();
 assert.equal(await control.count(),0);
 assert.equal((await fetchConfig()).llmProvider,original.llmProvider);
 const final=await fetchConfig();assert.deepEqual(final,original);
 assert.deepEqual(errors,[]);
 await fs.writeFile(new URL('generation-quality-browser.json',out),JSON.stringify({success:true,initialEnabled:original.autoImageReviewEnabled,finalEnabled:final.autoImageReviewEnabled,tabAfterNotifications:true,oldLocationRemoved:true,singleSwitch:true,onOffSaved:true,refreshPreserved:true,saveBodies:savedBodies,otherConfigUnchanged:true,pageErrors:errors},null,2));
 console.log('PASS: tab placement, single switch, isolated save payload, ON/OFF persistence, refresh, unchanged LLM/config');
} finally {
 // If a browser assertion fails, still restore the user's original switch via its existing API.
 if ((await fetchConfig()).autoImageReviewEnabled!==original.autoImageReviewEnabled)
   await page.request.post(appUrl+'/api/config/',{data:{autoImageReviewEnabled:original.autoImageReviewEnabled}});
 await browser.close();
}
