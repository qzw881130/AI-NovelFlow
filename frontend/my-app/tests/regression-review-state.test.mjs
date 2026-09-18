import assert from 'node:assert/strict';
import test from 'node:test';
import {symbol,revisionStore,savedResponse} from './helpers/revision-harness.mjs';

const patch=symbol('api/shotRevision.ts','shotRevisionPatch');
const edit=symbol('pages/ChapterGenerate/audioEventDraft.ts','editAudioEvent');
const actor={id:'e',type:'DIALOGUE',voiceOwnerName:'阿乐',voiceOwnerCharacterId:'a',visibleSpeakerName:'阿乐',visibleSpeakerCharacterId:'a',requiresVisibleLipsync:true,text:'快来！'};

test('RIR-004 aliases agree and absent/null/contradictory versions never become the current head',()=>{
  for(const key of ['sourceRevision','expectedRevision','expected_revision'])assert.equal(patch({id:'s',[key]:0}).expected_revision,0);
  for(const value of [{},{expected_revision:null},{expected_revision:true},{expected_revision:0,sourceRevision:1}])assert.throws(()=>patch({id:'s',...value}),/SHOT_REVISION/);
});

test('RIR-006 binding edits replace stale IDs, keep Event identity, and distinguish internal voice',()=>{
  const changed=edit(actor,'voiceOwnerName','村民');
  assert.equal(changed.id,actor.id);assert.equal(changed.voiceOwnerCharacterId,null);assert.equal(changed.visibleSpeakerCharacterId,null);
  assert.equal(changed.visibleSpeakerName,'村民');assert.equal(actor.voiceOwnerCharacterId,'a');
  const internal=edit(changed,'type','INNER_MONOLOGUE');
  assert.equal(internal.voiceOwnerName,'村民');assert.equal(internal.visibleSpeakerName,null);assert.equal(internal.requiresVisibleLipsync,false);
  const narration=edit(internal,'type','NARRATION');assert.equal(narration.voiceOwnerName,'旁白');assert.equal(narration.voiceOwnerCharacterId,null);
});

test('RIR-009 shared save refuses invalid or omitted contract drafts, preserving their text',async()=>{
  let requests=0;const store=revisionStore({chapter:{id:'c'},shots:[{id:'s',sourceRevision:2}]},async(_url,options)=>{requests++;return savedResponse(JSON.parse(options.body).shots);});
  store.getState().setShotTreatmentDraft('s',{json:'[',error:'Invalid JSON',sourceRevision:2});
  await assert.rejects(store.getState().saveShotRevisions('n','c',[{id:'s',sourceRevision:2,description:'edit'}]),/TREATMENT_DRAFT_INVALID/);
  assert.equal(requests,0);assert.equal(store.getState().shotTreatmentDrafts.s.json,'[');
  store.getState().setShotTreatmentDraft('s',{json:'[]',error:'',sourceRevision:2});
  await assert.rejects(store.getState().saveShotRevisions('n','c',[{id:'s',sourceRevision:2}]),/TREATMENT_DRAFT_NOT_INCLUDED/);
  await store.getState().saveShotRevisions('n','c',[{id:'s',sourceRevision:2,sourceTreatments:[]}]);
  assert.equal(requests,1);assert.equal(store.getState().shots[0].sourceRevision,3);
  assert.equal(store.getState().shotTreatmentDrafts.s,undefined);
});
