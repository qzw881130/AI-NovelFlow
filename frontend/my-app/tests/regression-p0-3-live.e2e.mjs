// Real publisher/GET/late-ack/subsequent-save sequence on a private snapshot DB.
import assert from 'node:assert/strict';
import {before,after,test} from 'node:test';
import {writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {chromium} from 'playwright-core';
const base=process.env.REVIEW_BASE_URL || 'http://127.0.0.1:18001';assert.equal(new URL(base).port,'18001');
const out=process.env.REVIEW_EVIDENCE_DIR;assert(out);
const root='/api/novels/31295501-a729-4fe7-aa76-a98c06121b98/chapters/49a0e2aa-b633-44de-adb0-f2573f790e97';
const id='edebac68-4f2a-4213-b42d-55425a968bbf';
let browser;
before(async()=>{browser=await chromium.connectOverCDP('http://127.0.0.1:9222');});
after(async()=>{await browser.close();});

for(const editWhileWaiting of [false,true])test('RP02-NEW-004 real creation acknowledgement after GET, local edit='+editWhileWaiting,async()=>{
  const context=await browser.newContext({viewport:{width:1500,height:1100},serviceWorkers:'block'}),page=await context.newPage();
  const record={at:new Date().toISOString(),editWhileWaiting,requests:[],errors:[]};let release;
  page.on('pageerror',error=>record.errors.push(String(error)));
  page.on('request',request=>{if(request.method()==='PATCH')record.requests.push(request.postDataJSON());});
  const get=async()=> (await (await context.request.get(base+root+'/shots/'+id)).json()).data;
  try{
    const original=await get(),last=original.audioEvents.at(-1);assert.equal(last.type,'NARRATION');
    const treatments=structuredClone(original.sourceTreatments),tail=treatments.find(t=>t.key===last.treatmentRef);
    tail.type='VISUAL';delete tail.audio_type;
    const setup=await context.request.patch(base+root+'/shots/batch',{data:{shots:[{id,expected_revision:original.sourceRevision,source_treatments:treatments,audio_events:original.audioEvents.slice(0,-1)}]}});
    assert.equal(setup.status(),200);record.setup=await setup.json();
    await page.goto(base+root.replace('/api','')+'/generate#shot-4');
    await page.locator('.generate-layout[data-current-shot-index="4"]:not([data-current-shot-id=""])').waitFor({timeout:60000});
    await page.getByRole('tab',{name:'分镜拆分',exact:true}).click();
    await page.locator('.shot-form summary').filter({hasText:'原文处理合同'}).click();
    tail.type='NARRATION';tail.audio_type='NARRATION';
    await page.getByRole('textbox',{name:'原文处理合同 JSON',exact:true}).fill(JSON.stringify(treatments));
    await page.getByRole('button',{name:'+ 旁白',exact:true}).click();
    const editor=page.getByText(/^Event 4 ·/).locator('../..');
    await editor.getByRole('combobox',{name:'Event 4 Treatment',exact:true}).selectOption(last.treatmentRef);
    await editor.locator('textarea').fill(last.text);await editor.locator('textarea').blur();
    let started;const queued=new Promise(resolve=>{started=resolve;}),barrier=new Promise(resolve=>{release=resolve;});let used=false;
    await page.route('**'+root+'/shots/batch',async route=>{
      if(used)return route.continue();used=true;
      const response=await route.fetch();record.creation={http:response.status(),body:await response.json()};started();
      await barrier;await route.fulfill({response});
    });
    const acknowledgement=page.waitForResponse(r=>r.request().method()==='PATCH'&&r.url().endsWith('/shots/batch'));
    await page.getByRole('button',{name:'保存分镜',exact:true}).first().click();await queued;
    assert.equal(record.creation.http,200,JSON.stringify(record.creation.body));
    const createdShot=record.creation.body.data.shots.find(s=>s.id===id),map=record.creation.body.data.eventIdMaps[id];
    assert.equal(Object.keys(map).length,1);const [localId,uuid]=Object.entries(map)[0];record.identity={localId,uuid};
    const edited=last.text+'这是仍未提交的编辑。';
    if(editWhileWaiting){await editor.locator('textarea').fill(edited);await editor.locator('textarea').blur();}
    const newerEvents=structuredClone(createdShot.audioEvents);newerEvents.at(-1).text=last.text+'这是服务端新版本。';
    const newer=await context.request.patch(base+root+'/shots/batch',{data:{shots:[{id,expected_revision:createdShot.sourceRevision,audio_events:newerEvents}]}});
    assert.equal(newer.status(),200);record.newer=await newer.json();
    const newest=record.newer.data.shots[0];
    await page.getByRole('tab',{name:'视频生成',exact:true}).click();
    const refreshed=page.waitForResponse(r=>r.request().method()==='GET'&&r.url().endsWith(root+'/shots/'+id));
    await page.getByRole('button',{name:'刷新视频预览',exact:true}).click();await refreshed;await page.waitForTimeout(100);
    release();await acknowledgement;await page.waitForTimeout(100);
    await page.getByRole('tab',{name:'分镜拆分',exact:true}).click();
    assert.equal(await page.getByText(/^Event \d+ ·/).count(),4,'There must not be both local ID and publisher UUID');
    const currentText=await page.getByText(/^Event 4 ·/).locator('../..').locator('textarea').inputValue();
    assert.equal(currentText,editWhileWaiting?edited:newest.audioEvents.at(-1).text);
    const nextResponse=page.waitForResponse(r=>r.request().method()==='PATCH'&&r.url().endsWith('/shots/batch'));
    await page.locator('.shot-form').getByRole('button',{name:'保存分镜',exact:true}).click();
    const next=await nextResponse;record.next={http:next.status(),body:await next.json()};
    assert.equal(next.status(),200,JSON.stringify(record.next.body));
    const request=record.requests.at(-1).shots.find(s=>s.id===id);
    assert.equal(request.expected_revision,newest.sourceRevision);assert.equal(request.audio_events.length,4);
    assert(request.audio_events.some(e=>e.id===uuid));assert(!request.audio_events.some(e=>e.id===localId));
    const actual=await get();assert.equal(actual.audioEvents.length,4);assert.equal(actual.audioEvents.at(-1).id,uuid);
    assert.equal(actual.audioEvents.at(-1).text,currentText);
    const source=await (await context.request.get(base+root+'/shots/'+id+'/treatment-validation')).json();assert.equal(source.data.status,'PASS');
    record.final={revision:actual.sourceRevision,eventIds:actual.audioEvents.map(e=>e.id),source:source.data.status};
    assert.deepEqual(record.errors,[]);record.passed=true;
  }catch(error){record.error=String(error);record.passed=false;throw error;}
  finally{
    release?.();await page.screenshot({path:join(out,`identity-live-${editWhileWaiting}.png`)});
    await writeFile(join(out,`identity-live-${editWhileWaiting}.json`),JSON.stringify(record,null,2));await context.close();
  }
});
