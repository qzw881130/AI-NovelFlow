import test from 'node:test';
import assert from 'node:assert/strict';
import {revisionStore,symbol} from './helpers/revision-harness.mjs';

const base={id:'s',chapterId:'c',sourceRevision:3,sourceRevisionId:'r3',description:'server description',video_description:'server motion',
  estimatedDuration:8,duration:10,characters:['阿青'],scene:'门厅',props:[],continuity_mode:'NORMAL',dialogues:[],
  audioEvents:[],sourceTreatments:[],imageUrl:'/image.png',videoUrl:'/video.mp4'};
const clone=value=>JSON.parse(JSON.stringify(value));
const response=(shots,eventIdMaps={})=>({ok:true,json:async()=>({success:true,data:{shots,eventIdMaps}})});
function fixture(fetch,shot=base){return revisionStore({chapter:{id:'c',novelId:'n'},shots:[clone(shot)]},fetch);}

for(const aliases of [{expected_revision:3,sourceRevision:2},{expected_revision:null,sourceRevision:3},{expectedRevision:3,sourceRevision:2}]){
  test('TG-04 structured/import preserves conflicting or null aliases '+JSON.stringify(aliases),async()=>{
    let calls=0;const store=fixture(async()=>{calls++;return response([base]);});
    const apply=symbol('pages/ChapterGenerate/components/ShotSplitTab.tsx','applyStructuredShotData',{
      novelId:'n',chapterId:'c',useChapterGenerateStore:store,t:x=>x,initChapterResources(){},markTabComplete(){},
    });
    await assert.rejects(apply({shots:[{...base,...aliases}]}),/SHOT_REVISION/);
    assert.equal(calls,0);assert.equal(store.getState().shots[0].sourceRevision,3);
  });
}

test('TG-04 equal duplicate aliases and actual no-op version are accepted',async()=>{
  const store=fixture(async()=>response([clone(base)]));
  const apply=symbol('pages/ChapterGenerate/components/ShotSplitTab.tsx','applyStructuredShotData',{
    novelId:'n',chapterId:'c',useChapterGenerateStore:store,t:x=>x,initChapterResources(){},markTabComplete(){},
  });
  await apply({shots:[{...base,expected_revision:3,expectedRevision:3}]});
  assert.equal(store.getState().shots[0].sourceRevision,3);
});

test('TG-05 RA-NEW-003 partial video save retains an unsubmitted description',async()=>{
  let sent;const store=fixture(async(_url,options)=>{sent=JSON.parse(options.body).shots[0];return response([{...base,sourceRevision:4,sourceRevisionId:'r4',video_description:'saved motion'}]);});
  store.getState().setShots([{...base,description:'unsaved description',video_description:'saved motion'}]);
  const save=symbol('pages/ChapterGenerate/components/VideoGenTab.tsx','handleSaveShot',{
    effectiveNovelId:'n',effectiveChapterId:'c',currentShotData:store.getState().shots[0],useChapterGenerateStore:store,
    setIsSaving(){},t:x=>x,toast:{success(){},error:assert.fail},console,
  });
  await save();assert.equal(sent.description,undefined);
  assert.equal(store.getState().shots[0].description,'unsaved description');
  assert.equal(store.getState().shots[0].sourceRevision,4);
});

test('TG-05 edits made while a save is pending survive the full response',async()=>{
  let release;const store=fixture(()=>new Promise(resolve=>{release=resolve;}));
  store.getState().setShots([{...base,description:'submitted'}]);
  const pending=store.getState().saveShotRevisions('n','c',[{id:'s',sourceRevision:3,description:'submitted'}]);
  store.getState().setShots([{...store.getState().shots[0],description:'typed during request'}]);
  release(response([{...base,sourceRevision:4,sourceRevisionId:'r4',description:'submitted'}]));
  await pending;assert.equal(store.getState().shots[0].description,'typed during request');assert.equal(store.getState().shots[0].sourceRevision,4);
});

test('TG-05 old response cannot regress store, media, or returned revision 5 to 4',async()=>{
  let release;const store=fixture(()=>new Promise(resolve=>{release=resolve;}));
  const pending=store.getState().saveShotRevisions('n','c',[{id:'s',sourceRevision:3,description:'r4 text'}]);
  store.setState({shots:[{...base,sourceRevision:5,sourceRevisionId:'r5',description:'r5 text',videoUrl:'/r5.mp4'}],shotVideos:{s:'/r5.mp4'}});
  release(response([{...base,sourceRevision:4,sourceRevisionId:'r4',description:'r4 text',videoUrl:null}]));
  const returned=await pending;
  assert.equal(store.getState().shots[0].sourceRevision,5);assert.equal(store.getState().shotVideos.s,'/r5.mp4');
  assert.equal(returned[0].sourceRevision,5);
});

test('TG-05 explicit published Event ID mapping preserves edits during creation',async()=>{
  const event={id:'local-created',order:1,type:'NARRATION',treatmentRef:'n',voiceOwnerName:'旁白',visibleSpeakerName:null,requiresVisibleLipsync:false,text:'submitted',pauseAfter:'NONE',ttsStatus:'NOT_GENERATED'};
  let release;const store=fixture(()=>new Promise(resolve=>{release=resolve;}));
  store.getState().setShots([{...base,audioEvents:[event]}]);
  const pending=store.getState().saveShotRevisions('n','c',[{id:'s',sourceRevision:3,audio_events:[event]}]);
  store.getState().setShots([{...store.getState().shots[0],audioEvents:[{...event,text:'edited during request'}]}]);
  release(response([{...base,sourceRevision:4,sourceRevisionId:'r4',audioEvents:[{...event,id:'published-uuid'}]}],{s:{'local-created':'published-uuid'}}));
  await pending;const actual=store.getState().shots[0].audioEvents[0];
  assert.equal(actual.id,'published-uuid');assert.equal(actual.text,'edited during request');
});

test('TG-05 complete response recovers canonical Event metadata; invalid receipt preserves draft',async()=>{
  const initial={...base,audioEvents:[{id:'e',text:'old',ttsStatus:'READY'}]};
  const store=fixture(async()=>response([{...initial,sourceRevision:4,audioEvents:[{id:'e',text:'new',ttsStatus:'STALE'}]}]),initial);
  await store.getState().saveShotRevisions('n','c',[{id:'s',sourceRevision:3,audio_events:[{id:'e',text:'new'}]}]);
  assert.equal(store.getState().shots[0].audioEvents[0].ttsStatus,'STALE');
  const bad=fixture(async()=>response([]));
  await assert.rejects(bad.getState().saveShotRevisions('n','c',[{id:'s',sourceRevision:3}]),/SHOT_REVISION_RESPONSE_INVALID/);
  assert.equal(bad.getState().shots[0].sourceRevision,3);
});

test('TG-05 newer server DTOs received outside save update the baseline without erasing a draft',()=>{
  const store=fixture(async()=>response([]));
  store.setState({shotServerHeads:{s:clone(base)}});
  store.getState().setShots([{...base,description:'local draft'}]);
  store.getState().setShots([{...base,sourceRevision:4,sourceRevisionId:'r4',video_description:'remote 4'}]);
  assert.equal(store.getState().shots[0].description,'local draft');
  assert.equal(store.getState().shotServerHeads.s.sourceRevision,4);
  store.getState().setShots([{...base,sourceRevision:5,sourceRevisionId:'r5',video_description:'remote 5'}]);
  assert.equal(store.getState().shots[0].video_description,'remote 5');
  assert.equal(store.getState().shots[0].description,'local draft');
});

test('TG-05 a response older than its own submitted CAS is not a successful receipt',async()=>{
  const store=fixture(async()=>response([{...base,sourceRevision:2}]));
  await assert.rejects(store.getState().saveShotRevisions('n','c',[{id:'s',sourceRevision:3,description:'edit'}]),/SHOT_REVISION_RESPONSE_INVALID/);
  assert.equal(store.getState().shots[0].sourceRevision,3);
});
