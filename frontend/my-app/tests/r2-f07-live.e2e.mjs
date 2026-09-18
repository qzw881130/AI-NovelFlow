// Real R2-B product evidence: UI split/save, API CAS control, and RSA resolution.
import assert from 'node:assert/strict';
import {readFile, writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import test from 'node:test';
import {chromium} from 'playwright-core';

const directory=process.env.R2_EVIDENCE_DIR;assert(directory);
const fixture=JSON.parse(await readFile(join(directory,'execution-context.json'),'utf8'));
const base=`http://127.0.0.1:${fixture.port}`,f=fixture.f07;
const chapterRoot=`/api/novels/${f.novelId}/chapters/${f.chapterId}`;
const expectedCitations=[{start:0,end:3,text:'🐺刘备'},{start:6,end:9,text:'站定。'}];

async function waitEnabled(page,locator,timeout=60000){
  const until=Date.now()+timeout;await locator.waitFor({state:'visible',timeout});
  while(Date.now()<until){if(await locator.isEnabled())return;await page.waitForTimeout(250);}
  throw new Error('Control did not become enabled');
}

test('R2-B F07 real Director publishes sparse citations through UI, Revision/CAS, and RSA',async()=>{
  const browser=await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context=await browser.newContext({viewport:{width:1500,height:1100},serviceWorkers:'block'});
  const page=await context.newPage();page.setDefaultTimeout(60000);
  const record={scope:'R2-B/F07',at:new Date().toISOString(),upstreamProvider:'test (Binding/Appearance fixture only)',
    realDirector:true,requests:[],splitAttempts:[],revisionIds:[],pageErrors:[],unexpectedHttpFailures:[]};
  page.on('pageerror',error=>record.pageErrors.push(String(error)));
  page.on('response',response=>{
    if(response.status()>=400&&!response.url().endsWith('/shots/batch'))record.unexpectedHttpFailures.push({status:response.status(),url:response.url()});
  });
  page.on('request',request=>{
    if(!['GET','HEAD','OPTIONS'].includes(request.method())&&request.url().includes(`/chapters/${f.chapterId}`)){
      record.requests.push({method:request.method(),url:request.url(),body:request.postData()});
    }
  });
  try{
    await page.goto(base+`/novels/${f.novelId}/chapters/${f.chapterId}/generate`);
    const splitButton=page.getByRole('button',{name:/AI 拆分/}).first();
    let published=null;
    for(let ordinal=1;ordinal<=4;ordinal++){
      await waitEnabled(page,splitButton);
      await splitButton.click();
      const responsePromise=page.waitForResponse(response=>response.request().method()==='POST'&&
        response.url().includes(`${chapterRoot}/split?`),{timeout:650000});
      await page.getByRole('button',{name:'确认拆分',exact:true}).click();
      const response=await responsePromise,body=await response.json();
      const source=body?.data?.shots?.[0]?.source;
      const attempt={ordinal,http:response.status(),success:Boolean(body.success),runId:body?.data?.splitRunId,
        message:body.message,sourceContractVersion:body?.data?.sourceContractVersion,
        citationRanges:source?.sourceCitationRanges,ownershipRange:source?.sourceContract?.ownership_range};
      record.splitAttempts.push(attempt);
      if(body.success&&body.data.shots.length===1&&JSON.stringify(source.sourceCitationRanges)===JSON.stringify(expectedCitations)
          &&source.sourceContract?.ownership_range?.text===f.sourceText){published=body;break;}
    }
    assert(published,'Real Director did not publish the required sparse-citation F07 output');
    assert.equal(published.data.sourceContractVersion,'chapter-shot-ownership-v2');
    record.successfulRunId=published.data.splitRunId;
    record.shotIds=published.data.shots.map(shot=>shot.id);
    assert.equal(record.shotIds.length,1);
    const shotId=record.shotIds[0],shotRoot=`${chapterRoot}/shots/${shotId}`;
    await page.locator(`.generate-layout[data-current-shot-id="${shotId}"]`).waitFor();

    const editor=page.locator('.generate-split-editor');
    const description=editor.locator('.shot-description-textarea');
    const save=editor.getByRole('button',{name:'保存分镜',exact:true});
    let current=(await (await context.request.get(base+shotRoot)).json()).data;
    for(const suffix of [' R2-B UI Revision 1',' R2-B UI Revision 2']){
      await description.fill(current.description+suffix);
      const responsePromise=page.waitForResponse(response=>response.request().method()==='PATCH'&&
        response.url().endsWith(`${chapterRoot}/shots/batch`));
      await save.click();
      const response=await responsePromise,body=await response.json();assert.equal(response.status(),200);assert(body.success);
      current=(await (await context.request.get(base+shotRoot)).json()).data;
      record.revisionIds.push(current.sourceRevisionId);record[`revision${current.sourceRevision}`]=body;
      await page.waitForTimeout(500);await waitEnabled(page,save);
    }
    assert.equal(current.sourceRevision,2);assert.equal(new Set(record.revisionIds).size,2);

    const staleResponse=await context.request.patch(base+`${chapterRoot}/shots/batch`,{data:{shots:[{
      id:shotId,expected_revision:0,description:'stale write must not publish',
    }]}});
    record.staleCas={http:staleResponse.status(),body:await staleResponse.json()};assert.equal(record.staleCas.http,409);
    const afterStale=(await (await context.request.get(base+shotRoot)).json()).data;
    assert.equal(afterStale.sourceRevision,2);assert.equal(afterStale.description,current.description);

    const rsaResponse=await context.request.post(base+shotRoot+'/resolve-assets',{data:{}});
    record.rsa={http:rsaResponse.status(),...(await rsaResponse.json()).data};
    assert.equal(record.rsa.http,200);assert.equal(record.rsa.ready,true);assert.equal(record.rsa.status,'READY');
    const treatment=await context.request.get(base+shotRoot+'/treatment-validation');
    record.treatment=await treatment.json();assert.equal(treatment.status(),200);assert.equal(record.treatment.data.status,'PASS');

    await page.reload();await page.locator(`.generate-layout[data-current-shot-id="${shotId}"]`).waitFor();
    await page.locator('details details > summary').filter({hasText:'Shot 1'}).click();
    await page.getByText('[0, 9) 🐺刘备在桃园站定。',{exact:true}).waitFor();
    await page.getByText('[0, 3) 🐺刘备',{exact:true}).waitFor();
    await page.getByText('[6, 9) 站定。',{exact:true}).waitFor();
    assert(record.requests.some(request=>request.method==='POST'&&request.url.includes('sourceContractVersion=chapter-shot-ownership-v2')));
    const revisionRequests=record.requests.filter(request=>request.method==='PATCH'&&request.url.endsWith('/shots/batch'));
    assert.equal(revisionRequests.length,2);
    for(const request of revisionRequests)assert(!/sourceContract|source_citations|ownership_range/.test(request.body||''));
    assert.deepEqual(record.pageErrors,[]);assert.deepEqual(record.unexpectedHttpFailures,[]);
    record.passed=true;
  }catch(error){record.error=String(error);record.passed=false;throw error;}
  finally{
    await page.screenshot({path:join(directory,'f07-live.png'),fullPage:true});
    await writeFile(join(directory,'f07-live.json'),JSON.stringify(record,null,2));
    await context.close();await browser.close();
  }
});
