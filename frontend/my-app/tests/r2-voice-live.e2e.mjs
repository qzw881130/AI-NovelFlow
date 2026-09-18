// Real R2-V UI/API/worker evidence. Requires a private serve_execution fixture.
import assert from 'node:assert/strict';
import {readFile,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
import test from 'node:test';
import {chromium} from 'playwright-core';

const directory=process.env.R2_EVIDENCE_DIR;assert(directory);
const fixture=JSON.parse(await readFile(join(directory,'execution-context.json'),'utf8'));
const base=`http://127.0.0.1:${fixture.port}`;assert.equal(fixture.port,18001);
const sha=buffer=>createHash('sha256').update(buffer).digest('hex');

test('R2-V F17: normal Voice Design, file upload, and two-Chapter narration TTS',async()=>{
  const browser=await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context=await browser.newContext({viewport:{width:1500,height:1100},serviceWorkers:'block'});
  const page=await context.newPage();page.setDefaultTimeout(30000);
  const record={at:new Date().toISOString(),scope:'R2-V/F17',upstreamProvider:'test (source fixture only)',realVoiceAndTts:true,requests:[],httpFailures:[],pageErrors:[],tts:[]};
  page.on('pageerror',error=>record.pageErrors.push(String(error)));
  page.on('response',response=>{if(response.status()>=400)record.httpFailures.push({http:response.status(),url:response.url()});});
  page.on('request',request=>{if(!['GET','HEAD','OPTIONS'].includes(request.method()))record.requests.push({method:request.method(),url:request.url()});});
  async function task(id){
    const until=Date.now()+1100000;
    while(Date.now()<until){
      const response=await context.request.get(base+'/api/tasks/'+id);assert.equal(response.status(),200);
      const envelope=await response.json(),value=envelope.data || envelope;
      if(['completed','failed','cancelled'].includes(value.status)){assert.equal(value.status,'completed',JSON.stringify(value));return value;}
      await page.waitForTimeout(3000);
    }
    throw new Error('Real task did not finish within the configured observation window: '+id);
  }
  try{
    const {novelId,narratorId}=fixture.f17,endpoint='/api/characters/'+narratorId;
    let narratorPromptRequests=0;
    page.on('request',request=>{if(request.url().replace(/\/$/,'')===base+endpoint+'/prompt')narratorPromptRequests++;});
    await page.goto(base+'/characters?novel='+novelId);
    const card=page.locator('#character-'+narratorId);await card.waitFor();
    const voiceButton=card.locator('button').filter({has:page.locator('svg.lucide-mic')});
    const beforeProfile=(await (await context.request.get(base+endpoint)).json()).data;
    assert(!beforeProfile.referenceAudioUrl,'Use a fresh voice fixture for this complete generation run');
    if(!beforeProfile.voicePrompt)assert(await voiceButton.isDisabled());
    await card.getByRole('button',{name:'编辑',exact:true}).last().click();
    const modal=page.locator('form').filter({has:page.locator('textarea[rows="2"]')});
    const prompt='普通话成年女声，温暖清晰的故事旁白，语速适中、自然流畅，不夸张、不唱歌。';
    await modal.locator('textarea[rows="2"]').fill(prompt);
    const configured=page.waitForResponse(r=>r.request().method()==='PUT'&&r.status()!==307&&r.url().replace(/\/$/,'')===base+endpoint);
    await modal.getByRole('button',{name:'保存',exact:true}).click();assert.equal((await configured).status(),200);
    await page.reload();await card.waitFor();await card.getByText(prompt,{exact:true}).waitFor();
    assert(await voiceButton.isEnabled());assert.equal(narratorPromptRequests,0);
    const applicability=await context.request.get(base+endpoint+'/prompt');assert.equal(applicability.status(),200);
    assert.equal((await applicability.json()).data.applicable,false);
    record.promptApplicability={automaticVisualRequests:0,directHttp:200,applicable:false};
    const design=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith(endpoint+'/generate-voice'));
    await card.hover();await voiceButton.click();const designResponse=await design;assert.equal(designResponse.status(),200);
    const designBody=await designResponse.json();assert(designBody.success);record.voiceTaskId=designBody.data.taskId;
    record.voiceTask=await task(record.voiceTaskId);
    const profile=(await (await context.request.get(base+endpoint)).json()).data;assert(profile.referenceAudioUrl.startsWith('/api/files/'));
    const generated=await context.request.get(base+profile.referenceAudioUrl);assert.equal(generated.status(),200);
    const bytes=await generated.body();assert(bytes.length>1000);
    record.voice={profileId:profile.id,prompt:profile.voicePrompt,url:profile.referenceAudioUrl,bytes:bytes.length,sha256:sha(bytes)};
    await page.reload();await card.waitFor();
    const choosing=page.waitForEvent('filechooser');await card.getByRole('button',{name:/上传.*音频/}).click();
    const chooser=await choosing;
    const uploaded=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().includes(endpoint+'/upload-audio'));
    await chooser.setFiles({name:'r2-narrator-reference.flac',mimeType:'audio/flac',buffer:bytes});
    const uploadResponse=await uploaded;assert.equal(uploadResponse.status(),200);record.upload=await uploadResponse.json();
    assert(record.upload.success);
    const after=(await (await context.request.get(base+endpoint)).json()).data;
    assert.equal(after.voicePrompt,prompt);assert.equal(after.id,narratorId);
    const reference=await context.request.get(base+after.referenceAudioUrl);assert.equal(reference.status(),200);
    assert.equal(sha(await reference.body()),record.voice.sha256);
    assert.equal(sha(await (await context.request.get(base+record.voice.url)).body()),record.voice.sha256);
    record.reference={url:after.referenceAudioUrl,sha256:record.voice.sha256,originalVoiceFilePreserved:true};
    for(const chapter of fixture.f17.chapters){
      await page.goto(base+`/novels/${novelId}/chapters/${chapter.id}/generate#shot-1`);
      await page.locator('.generate-layout:not([data-current-shot-id=""])').waitFor();
      await page.getByRole('tab',{name:'音频生成',exact:true}).click();
      await page.getByRole('heading',{name:/编辑 Audio Event/}).waitFor();
      const requested=page.waitForResponse(r=>r.request().method()==='POST'&&/\/audio-events\/[^/]+\/tts$/.test(r.url()));
      await page.getByRole('button',{name:'生成 TTS',exact:true}).click();const response=await requested;assert.equal(response.status(),200);
      const body=await response.json();assert(body.success);const completed=await task(body.data.taskId);
      const built=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/audio-timeline/build'));
      await page.getByRole('button',{name:'构建 Timeline',exact:true}).click();const timelineResponse=await built;assert.equal(timelineResponse.status(),200);
      const timeline=await timelineResponse.json();assert(timeline.success);assert.equal(timeline.data.status,'READY');
      const still=(await (await context.request.get(base+endpoint)).json()).data;
      assert.equal(still.referenceAudioUrl,record.reference.url);assert.equal(still.voicePrompt,prompt);
      record.tts.push({chapterId:chapter.id,shotId:chapter.shotId,task:completed,timeline});
    }
    assert.deepEqual(record.pageErrors,[]);assert(!record.httpFailures.some(f=>f.url.includes(endpoint+'/prompt')));
    record.passed=true;
  }catch(error){record.error=String(error);record.passed=false;throw error;}
  finally{
    await page.screenshot({path:join(directory,'f17-live.png')});
    let attempts=[];try{attempts=JSON.parse(await readFile(join(directory,'f17-live-attempts.json'),'utf8'));}catch{}
    try{const previous=JSON.parse(await readFile(join(directory,'f17-live.json'),'utf8'));if(!attempts.some(a=>a.at===previous.at))attempts.push(previous);}catch{}
    attempts.push(record);await writeFile(join(directory,'f17-live-attempts.json'),JSON.stringify(attempts,null,2));
    await writeFile(join(directory,'f17-live.json'),JSON.stringify(record,null,2));await context.close();await browser.close();
  }
});
