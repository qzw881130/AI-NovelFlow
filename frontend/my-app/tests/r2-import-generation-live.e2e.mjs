// Continue the independently imported F44 Revision through actual #06/#09 workers.
import assert from 'node:assert/strict';
import {readFile,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import test from 'node:test';
import {chromium} from 'playwright-core';
const directory=process.env.R2_EVIDENCE_DIR;assert(directory);
const fixture=JSON.parse(await readFile(join(directory,'execution-context.json'),'utf8'));
const base=`http://127.0.0.1:${fixture.port}`;assert.equal(fixture.port,18001);
const f=fixture.f44,root=`/api/novels/${f.novelId}/chapters/${f.chapterId}/shots/${f.shotId}`;

test('R2-V F44 imported Revision completes new primary and keyframe media',async()=>{
  const browser=await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context=await browser.newContext({viewport:{width:1500,height:1100},serviceWorkers:'block'}),page=await context.newPage();
  const record={scope:'R2-V/F44',at:new Date().toISOString(),requests:[],errors:[]};
  page.on('pageerror',error=>record.errors.push(String(error)));
  page.on('request',request=>{if(request.method()==='POST')record.requests.push({url:request.url(),body:request.postData()});});
  async function waitTask(id){
    const until=Date.now()+1100000;
    while(Date.now()<until){
      const response=await context.request.get(base+'/api/tasks/'+id);assert.equal(response.status(),200);
      const body=await response.json(),value=body.data || body;
      if(['completed','failed','cancelled'].includes(value.status)){record.lastTask=value;assert.equal(value.status,'completed',JSON.stringify(value));return value;}
      await page.waitForTimeout(3000);
    }
    throw new Error('Real RSA media task did not settle: '+id);
  }
  try{
    const before=(await (await context.request.get(base+root)).json()).data;
    assert.equal(before.sourceRevision,3);assert.match(before.description,/R2 F44 导入后再次编辑/);
    record.before={revision:before.sourceRevision,description:before.description,eventIds:before.audioEvents.map(e=>e.id)};
    const resolved=await context.request.post(base+root+'/resolve-assets');assert.equal(resolved.status(),200);
    record.rsa=await resolved.json();assert(record.rsa.success&&record.rsa.data.ready);
    await page.goto(base+`/novels/${f.novelId}/chapters/${f.chapterId}/generate#shot-4`);
    await page.locator('.generate-layout[data-current-shot-index="4"]:not([data-current-shot-id=""])').waitFor({timeout:60000});
    await page.getByRole('tab',{name:'分镜图生成',exact:true}).click();
    const responsePromise=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith(root+'/generate'));
    await page.getByRole('button',{name:'LLM+生成分镜',exact:true}).click();
    const response=await responsePromise;assert.equal(response.status(),200);record.primaryRequest=await response.json();assert(record.primaryRequest.success);
    record.primaryTask=await waitTask(record.primaryRequest.data.taskId);
    const frame=await context.request.post(base+root+'/keyframes/0/generate-image',{data:{skip_llm_when_prompt_exists:false}});
    assert.equal(frame.status(),200);record.keyframeRequest=await frame.json();assert(record.keyframeRequest.success);
    record.keyframeTask=await waitTask(record.keyframeRequest.data.taskId);
    const after=(await (await context.request.get(base+root)).json()).data;
    assert.equal(after.sourceRevision,3);assert.equal(after.description,before.description);
    assert.deepEqual(after.audioEvents.map(e=>e.id),record.before.eventIds);
    const coverage=await (await context.request.get(base+root+'/treatment-validation')).json();assert.equal(coverage.data.status,'PASS');
    record.after={revision:after.sourceRevision,imageTaskId:after.imageTaskId,keyframeTaskId:after.keyframes[0].image_task_id,source:coverage.data.status};
    assert.deepEqual(record.errors,[]);record.passed=true;
  }catch(error){record.error=String(error);record.passed=false;throw error;}
  finally{await page.screenshot({path:join(directory,'f44-generation.png')});await writeFile(join(directory,'f44-generation.json'),JSON.stringify(record,null,2));await context.close();await browser.close();}
});
