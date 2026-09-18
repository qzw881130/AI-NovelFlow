// Real HTTP/React replays on the authoring-only private snapshot server.
import assert from 'node:assert/strict';
import {before,after,test} from 'node:test';
import {writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {chromium} from 'playwright-core';
const base=process.env.REVIEW_BASE_URL || 'http://127.0.0.1:18001';
assert.equal(new URL(base).port,'18001');
const out=process.env.REVIEW_EVIDENCE_DIR;assert(out);
const root='/api/novels/31295501-a729-4fe7-aa76-a98c06121b98/chapters/49a0e2aa-b633-44de-adb0-f2573f790e97';
let browser;
before(async()=>{browser=await chromium.connectOverCDP('http://127.0.0.1:9222');});
after(async()=>{await browser.close();});
async function scenario(name,index,run){
  const context=await browser.newContext({viewport:{width:1500,height:1100},serviceWorkers:'block'}),page=await context.newPage();
  const record={name,index,at:new Date().toISOString(),patches:[],responses:[],errors:[]};
  page.on('pageerror',error=>record.errors.push(String(error)));
  page.on('request',request=>{if(request.method()==='PATCH')record.patches.push(request.postDataJSON());});
  const open=async()=>{
    const url=base+root.replace('/api','')+`/generate#shot-${index}`;
    if(page.url()===url)await page.reload();else await page.goto(url);
    await page.locator(`.generate-layout[data-current-shot-index="${index}"]:not([data-current-shot-id=""])`).waitFor({timeout:60000});
    await page.getByRole('tab',{name:'分镜拆分',exact:true}).click();
  };
  try{
    await open();const id=await page.locator('.generate-layout').getAttribute('data-current-shot-id');record.shotId=id;
    const get=async()=> (await (await context.request.get(base+root+'/shots/'+id)).json()).data;
    await run({page,context,record,id,get,open});assert.deepEqual(record.errors,[]);record.passed=true;
  }catch(error){record.error=String(error);record.passed=false;throw error;}
  finally{await page.screenshot({path:join(out,name+'.png')});await writeFile(join(out,name+'.json'),JSON.stringify(record,null,2));await context.close();}
}
async function save(page,button,record){
  const waiting=page.waitForResponse(r=>r.request().method()==='PATCH'&&r.url().includes(root+'/shots/batch'));
  await button.click();const response=await waiting,body=await response.json();record.responses.push({http:response.status(),body});return {response,body};
}
async function holdNextSave(page,record){
  let release,started;const wait=new Promise(resolve=>{started=resolve;}),barrier=new Promise(resolve=>{release=resolve;});let used=false;
  await page.route('**'+root+'/shots/batch',async route=>{
    if(used)return route.continue();used=true;
    const response=await route.fetch();const body=await response.json();record.upstream={http:response.status(),body};started();
    await barrier;await route.fulfill({response});
  });
  return {wait,release};
}

test('TG-04 structure JSON preserves aliases until canonical CAS validation',async()=>scenario('tg04-structure',1,async({page,record,get})=>{
  const original=await get();await page.getByRole('button',{name:'编辑结构数据',exact:true}).click();
  const modal=page.locator('div.fixed').filter({has:page.getByRole('heading',{name:'编辑结构数据',exact:true})}).last();
  const input=modal.locator('textarea');const document=JSON.parse(await input.inputValue());const target=document.shots.find(s=>s.id===original.id);
  target.expected_revision=original.sourceRevision;target.sourceRevision=original.sourceRevision-1;
  await input.fill(JSON.stringify(document));await modal.getByRole('button',{name:'保存',exact:true}).click();
  await modal.getByText(/SHOT_REVISION_ALIAS_CONFLICT/).waitFor();assert.equal(record.patches.length,0);
  target.expected_revision=null;target.sourceRevision=original.sourceRevision;
  await input.fill(JSON.stringify(document));await modal.getByRole('button',{name:'保存',exact:true}).click();
  await modal.getByText(/SHOT_REVISION_REQUIRED/).waitFor();assert.equal(record.patches.length,0);
  target.expected_revision=original.sourceRevision;
  await input.fill(JSON.stringify(document));const saved=await save(page,modal.getByRole('button',{name:'保存',exact:true}),record);
  assert.equal(saved.response.status(),200);assert.equal((await get()).sourceRevision,original.sourceRevision);
}));

test('TG-05 partial save retains description draft across tabs',async()=>scenario('tg05-partial',2,async({page,record,get})=>{
  const original=await get(),draft=original.description+'\n尚未提交的草叶细节。';
  await page.locator('.shot-description-textarea').fill(draft);
  await page.getByRole('tab',{name:'视频生成',exact:true}).click();
  const motion=page.getByPlaceholder('请输入视频生成用描述');await motion.fill(original.video_description+'\n镜头稳定移动。');await motion.blur();
  assert.equal((await save(page,page.getByRole('button',{name:'保存视频规划',exact:true}),record)).response.status(),200);
  assert.equal((await get()).description,original.description);
  await page.getByRole('tab',{name:'分镜拆分',exact:true}).click();
  assert.equal(await page.locator('.shot-description-textarea').inputValue(),draft);
  assert.equal((await save(page,page.locator('.shot-form').getByRole('button',{name:'保存分镜',exact:true}),record)).response.status(),200);
  assert.equal((await get()).description,draft);
}));

test('TG-05 image form permits editing while actual response is delayed',async()=>scenario('tg05-inflight',3,async({page,record,get})=>{
  const original=await get();await page.getByRole('tab',{name:'分镜图生成',exact:true}).click();
  const input=page.locator('.shot-description-textarea');await input.fill(original.description+'\n第一次草叶细节。');await input.blur();
  const held=await holdNextSave(page,record);const pending=save(page,page.locator('.shot-form').getByRole('button',{name:'保存分镜',exact:true}),record);
  await held.wait;assert.equal(record.upstream.http,200);
  const later=original.description+'\n请求期间继续编辑的细节。';await input.fill(later);await input.blur();held.release();
  await pending;assert.equal(await input.inputValue(),later);
  assert.equal((await save(page,page.locator('.shot-form').getByRole('button',{name:'保存分镜',exact:true}),record)).response.status(),200);
  assert.equal((await get()).description,later);
}));

test('TG-05 actual new Event UUID is recovered while its text draft remains editable',async()=>scenario('tg05-event-uuid',4,async({page,context,record,get,open,id})=>{
  const original=await get(),last=original.audioEvents.at(-1),key=last.treatmentRef;
  const treatments=structuredClone(original.sourceTreatments),tail=treatments.find(t=>t.key===key);tail.type='VISUAL';delete tail.audio_type;
  const setup=await context.request.patch(base+root+'/shots/batch',{data:{shots:[{id,expected_revision:original.sourceRevision,
    source_treatments:treatments,audio_events:original.audioEvents.slice(0,-1)}]}});
  assert.equal(setup.status(),200);await open();
  await page.locator('.shot-form summary').filter({hasText:'原文处理合同'}).click();
  tail.type='NARRATION';tail.audio_type='NARRATION';
  await page.getByRole('textbox',{name:'原文处理合同 JSON',exact:true}).fill(JSON.stringify(treatments));
  await page.getByRole('button',{name:'+ 旁白',exact:true}).click();
  const event=page.getByText(/^Event 4 ·/).locator('../..');await event.getByRole('combobox',{name:'Event 4 Treatment',exact:true}).selectOption(key);
  const input=event.locator('textarea');await input.fill(last.text);await input.blur();
  const held=await holdNextSave(page,record);const pending=save(page,page.getByRole('button',{name:'保存分镜',exact:true}).first(),record);
  await held.wait;assert.equal(record.upstream.http,200,JSON.stringify(record.upstream.body));
  const later=last.text+'他依旧孤立无援。';await input.fill(later);await input.blur();held.release();await pending;
  const map=record.upstream.body.data.eventIdMaps[id];assert.equal(Object.keys(map).length,1);
  const published=Object.values(map)[0];assert.notEqual(published,last.id);
  assert.equal(await page.getByText(/^Event 4 ·/).locator('../..').locator('textarea').inputValue(),later);
  const next=await save(page,page.locator('.shot-form').getByRole('button',{name:'保存分镜',exact:true}),record);assert.equal(next.response.status(),200,JSON.stringify(next.body));
  const saved=(await get()).audioEvents.at(-1);assert.equal(saved.id,published);assert.equal(saved.text,later);
}));

test('TG-06 structured editor cannot introduce a second unbound Characters block',async()=>scenario('tg06-structure',5,async({page,record,get})=>{
  const original=await get();await page.getByRole('button',{name:'编辑结构数据',exact:true}).click();
  const modal=page.locator('div.fixed').filter({has:page.getByRole('heading',{name:'编辑结构数据',exact:true})}).last();
  const input=modal.locator('textarea'),document=JSON.parse(await input.inputValue());
  document.shots.find(s=>s.id===original.id).video_description+='\nCharacters:\n- 审计外来人物: 站立\nAction: 走入';
  await input.fill(JSON.stringify(document));const result=await save(page,modal.getByRole('button',{name:'保存',exact:true}),record);
  assert.equal(result.response.status(),409);assert.match(JSON.stringify(result.body),/SHOT_VISIBLE_CHARACTER_CLOSURE/);
  assert.equal((await get()).sourceRevision,original.sourceRevision);
}));

test('TG-04 actual file import rejects a conflicting alias before HTTP and accepts equal aliases',async()=>scenario('tg04-import',6,async({page,context,record,get})=>{
  const original=await get();
  const rows=(await (await context.request.get(base+root+'/shots/')).json()).data;
  const target=rows.find(s=>s.id===original.id);target.expected_revision=original.sourceRevision;target.sourceRevision=original.sourceRevision-1;
  async function choose(){
    const waiting=page.waitForEvent('filechooser');await page.getByRole('button',{name:/导入分镜/}).click();
    const chooser=await waiting;await chooser.setFiles({name:'review-import.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify({shots:rows}))});
  }
  await choose();await page.getByRole('button',{name:/确认导入/}).click();
  await page.getByText(/SHOT_REVISION_ALIAS_CONFLICT/).waitFor();assert.equal(record.patches.length,0);
  target.sourceRevision=original.sourceRevision;await choose();
  const saved=await save(page,page.getByRole('button',{name:/确认导入/}),record);
  assert.equal(saved.response.status(),200,JSON.stringify(saved.body));assert.equal((await get()).sourceRevision,original.sourceRevision);
}));

test('TG-05 an actual late r4 response cannot undo a newer r5 accepted by refresh',async()=>scenario('tg05-late-response',1,async({page,record,get,id})=>{
  const original=await get();await page.getByRole('tab',{name:'分镜图生成',exact:true}).click();
  const input=page.locator('.shot-description-textarea');await input.fill(original.description+'\n客户端A已提交。');await input.blur();
  const held=await holdNextSave(page,record);const pending=save(page,page.locator('.shot-form').getByRole('button',{name:'保存分镜',exact:true}),record);
  await held.wait;assert.equal(record.upstream.http,200);
  const r4=record.upstream.body.data.shots[0].sourceRevision;
  const other=await browser.newContext();
  try{
    const remote=await other.request.patch(base+root+'/shots/batch',{data:{shots:[{id,expected_revision:r4,video_description:original.video_description+'\n客户端B的新版本。'}]}});
    const body=await remote.json();assert.equal(remote.status(),200,JSON.stringify(body));record.otherClient={http:remote.status(),body};
    await page.getByRole('tab',{name:'视频生成',exact:true}).click();
    const refreshed=page.waitForResponse(r=>r.request().method()==='GET'&&r.url().endsWith(root+'/shots/'+id));
    await page.getByRole('button',{name:'刷新视频预览',exact:true}).click();await refreshed;
    await page.waitForTimeout(100);held.release();await pending;await page.waitForTimeout(100);
    const motion=page.getByPlaceholder('请输入视频生成用描述');
    assert.equal(await motion.inputValue(),body.data.shots[0].video_description);
    await motion.fill(body.data.shots[0].video_description+'\n客户端A继续编辑。');await motion.blur();
    const next=await save(page,page.getByRole('button',{name:'保存视频规划',exact:true}),record);
    assert.equal(next.response.status(),200,JSON.stringify(next.body));
    assert.equal(record.patches.at(-1).shots[0].expected_revision,r4+1);
    assert.equal((await get()).sourceRevision,r4+2);
  }finally{held.release();await other.close();}
}));
