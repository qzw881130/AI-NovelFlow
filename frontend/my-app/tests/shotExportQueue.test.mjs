import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';
const source = await readFile(new URL('../src/api/shotExports.ts', import.meta.url), 'utf8');
const code = ts.transpileModule(source.replace(/^export /gm, ''), { compilerOptions: { module: ts.ModuleKind.None, target: ts.ScriptTarget.ES2020 } }).outputText;
const base = '/api/novels/n/chapters/c/shots/s';
const params = new URLSearchParams('include=primary_image');
function harness(fetch) {
  const saved = new Map(), downloads = [], timers = [];
  const storage = { getItem: k=>saved.get(k)||null, setItem:(k,v)=>saved.set(k,v), removeItem:k=>saved.delete(k) };
  const document = { body:{appendChild(){}},createElement(){return {style:{},click(){downloads.push(this.href);},remove(){}};} };
  const window = { setTimeout(done, ms){timers.push(ms);queueMicrotask(done);} };
  const run = new Function('fetch','AbortSignal','window','localStorage','document',`${code};return downloadQueuedShotExport;`)(fetch,{timeout:ms=>({ms})},window,storage,document);
  return {run,saved,downloads,timers};
}
const response = data=>({ok:true,json:async()=>({success:true,data})});
test('queued export can run beyond 120 seconds with short polling requests then browser download',async()=>{
  const calls=[],progress=[];let polls=0;
  const h=harness(async(url, options)=>{calls.push({url,options});
    if(options.method==='POST')return response({task_id:'job',status:'pending',progress:0});
    return response({task_id:'job',status:++polls>90?'completed':'running',progress:5,current_step:'打包 Clip'});
  });
  await h.run(base,params,message=>progress.push(message));
  assert.equal(calls[0].url,`${base}/export-video-materials?${params}`);
  assert.equal(calls.filter(c=>c.options.method==='POST').length,1);
  assert.ok(h.timers.reduce((a,b)=>a+b,0)>120_000);
  assert.ok(calls.every(c=>c.options.signal.ms===20_000));
  assert.deepEqual(h.downloads,[`${base}/exports/job/download`]);
  assert.equal(h.saved.size,0);
  assert.ok(progress.some(p=>p.includes('打包 Clip')));
});
test('temporary polling disconnect retries; a longer disconnect preserves receipt for resume without resubmission',async()=>{
  let mode='disconnect', posts=0, reads=0;
  const h=harness(async(_url,options)=>{
    if(options.method==='POST'){posts++;return response({task_id:'saved-job',status:'pending'});}
    reads++;
    if(mode==='disconnect')throw new Error('network');
    return response({task_id:'saved-job',status:'completed',progress:100});
  });
  await assert.rejects(h.run(base,params),/后台任务会继续/);
  assert.equal(posts,1);assert.equal(reads,5);assert.equal(h.saved.size,1);
  mode='ready';await h.run(base,params);
  assert.equal(posts,1);assert.equal(h.saved.size,0);
  assert.deepEqual(h.downloads,[`${base}/exports/saved-job/download`]);
});
test('failed packing surfaces its error instead of downloading and forgets failed receipt',async()=>{
  const h=harness(async(_url,options)=>response(options.method==='POST'?{task_id:'job',status:'pending'}:{task_id:'job',status:'failed',error_message:'磁盘空间不足'}));
  await assert.rejects(h.run(base,params),/磁盘空间不足/);
  assert.equal(h.saved.size,0);assert.equal(h.downloads.length,0);
});
