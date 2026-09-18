// Real mounted React pages + real API. Use backend/tests/regression_review/serve_snapshot.py.
import assert from 'node:assert/strict';
import {before,after,test} from 'node:test';
import {writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {chromium} from 'playwright-core';

const base=process.env.REVIEW_BASE_URL || 'http://127.0.0.1:18001';
assert.equal(new URL(base).port,'18001','Use the isolated review server, never production');
const evidence=process.env.REVIEW_EVIDENCE_DIR;
assert(evidence,'REVIEW_EVIDENCE_DIR is required');
const label=process.env.REVIEW_RUN_LABEL || 'live';
const book='31295501-a729-4fe7-aa76-a98c06121b98',chapter='49a0e2aa-b633-44de-adb0-f2573f790e97';
const root=`/api/novels/${book}/chapters/${chapter}`;
let browser;
before(async()=>{browser=await chromium.connectOverCDP(process.env.REVIEW_CDP_URL || 'http://127.0.0.1:9222');});
after(async()=>{await browser?.close();});

async function scenario(name,index,stage,run){
  const context=await browser.newContext({viewport:{width:1500,height:1100},serviceWorkers:'block'});
  const page=await context.newPage();page.setDefaultTimeout(30000);
  const record={name,base,at:new Date().toISOString(),requests:[],pageErrors:[]};
  page.on('pageerror',e=>record.pageErrors.push(e.message));
  page.on('request',r=>{if(r.method()==='PATCH')record.requests.push({url:r.url(),body:r.postDataJSON()});});
  try{
    await page.goto(`${base}/novels/${book}/chapters/${chapter}/generate#shot-${index}`);
    await page.locator(`.generate-layout[data-current-shot-index="${index}"]:not([data-current-shot-id=""])`).waitFor({timeout:60000});
    if(stage)await page.getByRole('tab',{name:stage,exact:true}).click();
    const shotId=await page.locator('.generate-layout').getAttribute('data-current-shot-id');
    record.shotId=shotId;
    const before=await (await context.request.get(base+root+'/shots/'+shotId)).json();record.beforeRevision=before.data.sourceRevision;
    await run({page,context,record,shotId,before:before.data});
    assert.deepEqual(record.pageErrors,[]);record.passed=true;
  }catch(error){record.passed=false;record.error=String(error);throw error;}
  finally{
    await page.screenshot({path:join(evidence,`${label}-${name}.png`)});
    await writeFile(join(evidence,`${label}-${name}.json`),JSON.stringify(record,null,2));
    await context.close();
  }
}

async function save(page,button,record){
  const waiting=page.waitForResponse(r=>r.request().method()==='PATCH' && (r.url().includes('/shots/batch') || r.url().includes('/audio-events/')));
  await button.click();const response=await waiting;const body=await response.json();
  record.responses ||= [];record.responses.push({http:response.status(),body});
  return {response,body,request:response.request().postDataJSON()};
}

test('RIR-005 image page saves two different edits and recovers revision without refresh',async()=>scenario('rir005-image',1,'分镜图生成',async({page,record,before})=>{
  const input=page.locator('.shot-description-textarea');const original=await input.inputValue();
  for(let i=1;i<=2;i++){
    await input.fill(original+`\n第${i}次编辑：微风吹动草叶。`);await input.blur();
    const {response,body,request}=await save(page,page.locator('.shot-form').getByRole('button',{name:'保存分镜',exact:true}),record);
    assert.equal(response.status(),200,JSON.stringify(body));
    assert.equal(request.shots[0].expected_revision,before.sourceRevision+i-1);
    assert.equal(body.data.shots[0].sourceRevision,before.sourceRevision+i);
  }
}));

test('RIR-004 video page sends CAS and recovers it for a second distinct edit',async()=>scenario('rir004-video',3,'视频生成',async({page,record,before})=>{
  const input=page.getByPlaceholder('请输入视频生成用描述');const original=await input.inputValue();
  for(let i=1;i<=2;i++){
    await input.fill(original+`\n第${i}次编辑：镜头平稳。`);await input.blur();
    const {response,body,request}=await save(page,page.getByRole('button',{name:'保存视频规划',exact:true}),record);
    assert.equal(request.shots[0].expected_revision,before.sourceRevision+i-1);
    assert.equal(response.status(),200,JSON.stringify(body));
    assert.equal(body.data.shots[0].sourceRevision,before.sourceRevision+i);
  }
}));

test('RIR-006 persisted speaker selectors update IDs and remain consumable',async()=>scenario('rir006-speaker',2,null,async({page,context,record,shotId})=>{
  const event=page.getByText(/^Event 1 ·/).locator('../..');
  await event.getByText('Voice Owner',{exact:true}).locator('..').locator('select').selectOption({label:'村民'});
  await event.getByText('Visible Speaker',{exact:true}).locator('..').locator('select').selectOption({label:'村民'});
  const {response,body}=await save(page,page.locator('.shot-form').getByRole('button',{name:'保存分镜',exact:true}),record);
  assert.equal(response.status(),200,JSON.stringify(body));
  const current=body.data.shots.find(s=>s.id===shotId),spoken=current.audioEvents[0];
  assert.equal(spoken.voiceOwnerName,'村民');assert.equal(spoken.voiceOwnerCharacterId,'939585a1-dd2a-4c4e-8091-40d45e95c0a2');
  assert.equal(spoken.visibleSpeakerCharacterId,spoken.voiceOwnerCharacterId);
  const coverage=await (await context.request.get(base+root+'/shots/'+shotId+'/treatment-validation')).json();
  assert.equal(coverage.data.status,'PASS');record.coverage=coverage.data.status;
}));

test('RIR-003 audio page publishes one authority and permits successive pause edits',async()=>scenario('rir003-audio',4,'音频生成',async({page,context,record,shotId,before})=>{
  await page.getByRole('heading',{name:/编辑 Audio Event/}).waitFor();
  for(const [i,pause] of ['LONG','SHORT'].entries()){
    await page.locator('.generate-audio-editor label').filter({has:page.getByText('停顿',{exact:true})}).locator('select').selectOption(pause);
    const {response,body}=await save(page,page.getByRole('button',{name:'保存事件',exact:true}),record);
    assert.equal(response.status(),200,JSON.stringify(body));
    const coverage=await (await context.request.get(base+root+'/shots/'+shotId+'/treatment-validation')).json();
    record.coverage=coverage;
    assert.equal(coverage.data.status,'PASS');
    const current=await (await context.request.get(base+root+'/shots/'+shotId)).json();
    assert.equal(current.data.sourceRevision,before.sourceRevision+i+1);
    assert.equal(current.data.audioEvents[0].pauseAfter,pause);
  }
}));

test('RIR-009 invalid Treatment draft blocks top save and survives tab changes until repaired',async()=>scenario('rir009-draft',5,null,async({page,record,before})=>{
  const contract=page.getByRole('textbox',{name:'原文处理合同 JSON',exact:true});
  await page.locator('.shot-form summary').filter({hasText:'原文处理合同'}).click();
  const original=await contract.inputValue();await contract.fill('[');await contract.blur();
  await page.locator('.shot-form [role=alert]').waitFor();
  const description=page.locator('.shot-description-textarea');await description.fill(before.description+'\n微风吹动草叶。');await description.blur();
  const count=record.requests.length,top=page.getByRole('button',{name:'保存分镜',exact:true}).first();
  if(!await top.isDisabled())await top.click();
  await page.waitForTimeout(300);
  assert.equal(record.requests.length,count,'Invalid draft must not send a partial save');
  await page.getByRole('tab',{name:'分镜图生成',exact:true}).click();
  const imageSave=page.locator('.shot-form').getByRole('button',{name:'保存分镜',exact:true});
  if(!await imageSave.isDisabled())await imageSave.click();
  await page.waitForTimeout(200);assert.equal(record.requests.length,count);
  await page.getByRole('tab',{name:'分镜拆分',exact:true}).click();
  await page.locator('.shot-form summary').filter({hasText:'原文处理合同'}).click();
  assert.equal(await contract.inputValue(),'[','The invalid draft must not silently disappear on remount');
  await contract.fill(original);await contract.blur();
  const {response,body}=await save(page,page.getByRole('button',{name:'保存分镜',exact:true}).first(),record);
  assert.equal(response.status(),200,JSON.stringify(body));
  assert.equal(body.data.shots.find(s=>s.id===before.id).sourceRevision,before.sourceRevision+1);
}));

test('RIR-004 two actual browser clients reject a stale writer while the current client can continue',async()=>scenario('rir004-two-clients',6,'视频生成',async({page,record,before})=>{
  const other=await browser.newContext({viewport:{width:1500,height:1100},serviceWorkers:'block'});
  const second=await other.newPage();record.otherClientRequests=[];
  second.on('request',r=>{if(r.method()==='PATCH')record.otherClientRequests.push(r.postDataJSON());});
  try{
    await second.goto(`${base}/novels/${book}/chapters/${chapter}/generate#shot-6`);
    await second.locator('.generate-layout[data-current-shot-index="6"]:not([data-current-shot-id=""])').waitFor({timeout:60000});
    await second.getByRole('tab',{name:'视频生成',exact:true}).click();
    const input=page.getByPlaceholder('请输入视频生成用描述');
    await input.fill(before.video_description+'\n客户端A第一次编辑。');await input.blur();
    const first=await save(page,page.getByRole('button',{name:'保存视频规划',exact:true}),record);
    assert.equal(first.response.status(),200);
    const otherInput=second.getByPlaceholder('请输入视频生成用描述');
    await otherInput.fill(before.video_description+'\n客户端B的过期草稿。');await otherInput.blur();
    const stale=await save(second,second.getByRole('button',{name:'保存视频规划',exact:true}),record);
    assert.equal(stale.request.shots[0].expected_revision,before.sourceRevision);
    assert.equal(stale.response.status(),409);assert.equal(stale.body.detail.code,'SHOT_REVISION_CONFLICT');
    await input.fill(before.video_description+'\n客户端A第二次编辑。');await input.blur();
    const next=await save(page,page.getByRole('button',{name:'保存视频规划',exact:true}),record);
    assert.equal(next.response.status(),200);assert.equal(next.body.data.shots[0].sourceRevision,before.sourceRevision+2);
  }finally{await other.close();}
}));
