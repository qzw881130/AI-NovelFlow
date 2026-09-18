import test from 'node:test';
import assert from 'node:assert/strict';
import {revisionStore,pureModule} from './helpers/revision-harness.mjs';
const {receiveShotSnapshots}=pureModule('api/shotRevision.ts');
const clone=x=>JSON.parse(JSON.stringify(x));
const localId='local-created',uuid='2c5bbded-27c5-4271-849d-0f4758967ffb';
const oldEvents=['a','b','c'].map((id,index)=>({id,order:index+1,type:'NARRATION',text:id,treatmentRef:id,voiceOwnerName:'旁白',visibleSpeakerName:null,requiresVisibleLipsync:false,pauseAfter:'NONE',ttsStatus:'READY'}));
const creation={...oldEvents[0],id:localId,order:4,text:'submitted',treatmentRef:'tail',ttsStatus:'NOT_GENERATED'};
const base={id:'s',chapterId:'c',sourceRunId:'source-run',sourceRevision:2,sourceRevisionId:'r2',description:'base',video_description:'motion',sourceTreatments:[],dialogues:[],audioEvents:oldEvents,videoUrl:'/r2.mp4'};
const r3={...base,sourceRevision:3,sourceRevisionId:'r3',audioEvents:[...oldEvents,{...creation,id:uuid}],videoUrl:null};
const r4={...r3,sourceRevision:4,sourceRevisionId:'r4',video_description:'newer motion',audioEvents:[...oldEvents,{...creation,id:uuid,text:'server r4',ttsStatus:'STALE'}],videoUrl:'/r4.mp4'};
const reply=(shot,map={})=>({ok:true,json:async()=>({success:true,data:{shots:[clone(shot)],eventIdMaps:{s:map}}})});
function setup(){
  let release;const requests=[];
  const store=revisionStore({chapter:{id:'c'},shots:[clone(base)],shotServerHeads:{s:clone(base)}},async(_url,options)=>{
    requests.push(JSON.parse(options.body));
    if(requests.length===1)return new Promise(resolve=>{release=resolve;});
    return reply({...r4,sourceRevision:5,sourceRevisionId:'r5',audioEvents:requests.at(-1).shots[0].audio_events});
  });
  store.getState().setShots([{...clone(base),audioEvents:[...clone(oldEvents),clone(creation)]}]);
  const pending=store.getState().saveShotRevisions('n','c',[{id:'s',sourceRevision:2,audio_events:[...clone(oldEvents),clone(creation)]}]);
  return {store,requests,pending,release:map=>release(reply(r3,map ?? {[localId]:uuid}))};
}
function receive(store,shot){store.setState(state=>receiveShotSnapshots(state,[clone(shot)]));}

test('RP02-NEW-004 late creation map coalesces identities without accepting stale content',async()=>{
  const {store,requests,pending,release}=setup();receive(store,r4);release();
  const [returned]=await pending;const actual=store.getState().shots[0];
  assert.equal(actual.sourceRevision,4);assert.equal(returned.sourceRevision,4);assert.equal(actual.audioEvents.length,4);
  assert.equal(new Set(actual.audioEvents.map(e=>e.id)).size,4);assert(!actual.audioEvents.some(e=>e.id===localId));
  assert.equal(actual.audioEvents.at(-1).text,'server r4');assert.equal(actual.audioEvents.at(-1).ttsStatus,'STALE');
  assert.equal(store.getState().shotServerHeads.s.sourceRevision,4);assert.equal(store.getState().shotVideos.s,'/r4.mp4');
  await store.getState().saveShotRevisions('n','c',[{id:'s',sourceRevision:4,audio_events:actual.audioEvents}]);
  assert.equal(requests[1].shots[0].expected_revision,4);assert.equal(requests[1].shots[0].audio_events.length,4);
  assert.equal(requests[1].shots[0].audio_events.at(-1).id,uuid);
});

test('late identity confirmation keeps only genuine post-submission author deltas',async()=>{
  const {store,pending,release}=setup();
  store.getState().setShots([{...store.getState().shots[0],description:'unsubmitted description',audioEvents:[...clone(oldEvents),{...creation,text:'typed while waiting',pauseAfter:'LONG'}]}]);
  receive(store,r4);release();await pending;
  const actual=store.getState().shots[0];assert.equal(actual.audioEvents.length,4);assert.equal(actual.description,'unsubmitted description');
  assert.equal(actual.audioEvents.at(-1).id,uuid);assert.equal(actual.audioEvents.at(-1).text,'typed while waiting');
  assert.equal(actual.audioEvents.at(-1).pauseAfter,'LONG');assert.equal(actual.audioEvents.at(-1).ttsStatus,'STALE');
});

test('deleted local creation is not resurrected by a newer GET and a late acknowledgement',async()=>{
  const {store,pending,release}=setup();store.getState().setShots([{...store.getState().shots[0],audioEvents:clone(oldEvents)}]);
  receive(store,r4);release();await pending;
  assert.deepEqual(Array.from(store.getState().shots[0].audioEvents,e=>e.id),['a','b','c']);
  receive(store,{...r4,sourceRevision:5,sourceRevisionId:'r5'});
  assert.deepEqual(Array.from(store.getState().shots[0].audioEvents,e=>e.id),['a','b','c']);
});

test('acknowledged alias re-entry is canonicalized; same text is never an identity key',async()=>{
  const {store,pending,release}=setup();receive(store,r4);release();await pending;
  const actual=store.getState().shots[0];
  store.getState().setShots([{...actual,audioEvents:[...actual.audioEvents,{...creation,text:'new local edit'}, {...creation,id:'local-unrelated'}]}]);
  const events=store.getState().shots[0].audioEvents;
  assert.equal(events.filter(e=>e.id===uuid).length,1);assert(!events.some(e=>e.id===localId));
  assert(events.some(e=>e.id==='local-unrelated'));
});

for(const bad of [{[localId]:'foreign-id'},{'local-not-submitted':uuid}]){
  test('unverified identity map is rejected without mutating current state '+JSON.stringify(bad),async()=>{
    const {store,pending,release}=setup();receive(store,r4);const before=clone(store.getState().shots);release(bad);
    await assert.rejects(pending,/SHOT_EVENT_IDENTITY/);assert.deepEqual(clone(store.getState().shots),before);
  });
}

test('a late identity map cannot cross a rebuilt source lifecycle',async()=>{
  const {store,pending,release}=setup();store.setState({shots:[{...r4,sourceRunId:'other-run'}],shotServerHeads:{s:{...r4,sourceRunId:'other-run'}}});
  release();await assert.rejects(pending,/SHOT_EVENT_IDENTITY/);
  assert.equal(store.getState().shots[0].sourceRunId,'other-run');
});
