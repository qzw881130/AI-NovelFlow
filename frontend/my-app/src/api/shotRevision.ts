/** One authoring request projection. Never substitute a newer server/store revision. */
export interface ShotRevisionDraft {
  id: string;
  sourceRevision?: number;
  expected_revision?: number;
  expectedRevision?: number;
  [key: string]: any;
}

export interface TreatmentDraft {
  json: string;
  error: string;
  sourceRevision?: number;
}

export const protectedSourceFields = new Set([
  'source_contract','sourceContract','source_contract_version','sourceContractVersion',
  'source_citations','sourceCitations','source_citation_ranges','sourceCitationRanges',
  'source_ownership','sourceOwnership','source_evidence','sourceEvidence','source_ranges','sourceRanges',
  'citation_evidence','citationEvidence','citation_ranges','citationRanges',
  'ownership_evidence','ownershipEvidence','ownership_range','ownershipRange',
  'source_start','sourceStart','source_end','sourceEnd','source_hash','sourceHash',
  'source_run_id','sourceRunId','run_id','runId','evidence','ranges','bindings','assetBindings',
  'offset','offset_unit','offsetUnit','source_seal','sourceSeal','base_seal','baseSeal',
]);

export function assertNoProtectedSourceFields(value:Record<string,any>) {
  if (Object.keys(value).some(key=>protectedSourceFields.has(key))) throw new Error('SHOT_REVISION_PROTECTED_FIELD');
}

export function parseTreatmentDraft(json: string) {
  try {
    const value = JSON.parse(json);
    if (!Array.isArray(value)) throw new Error('原文处理合同必须是数组');
    return {value, error: ''};
  } catch (error) {
    return {value: null, error: error instanceof Error ? error.message : 'JSON格式错误'};
  }
}

export function shotRevisionPatch(draft: ShotRevisionDraft) {
  if (Object.keys(draft).some(key=>[
    'source_contract','sourceContract','source_contract_version','sourceContractVersion',
    'source_citations','sourceCitations','source_citation_ranges','sourceCitationRanges',
    'source_ownership','sourceOwnership','source_evidence','sourceEvidence','source_ranges','sourceRanges',
    'citation_evidence','citationEvidence','citation_ranges','citationRanges',
    'ownership_evidence','ownershipEvidence','ownership_range','ownershipRange',
    'source_start','sourceStart','source_end','sourceEnd','source_hash','sourceHash',
    'source_run_id','sourceRunId','run_id','runId','evidence','ranges','bindings','assetBindings',
    'offset','offset_unit','offsetUnit','source_seal','sourceSeal','base_seal','baseSeal',
  ].includes(key))) throw new Error('SHOT_REVISION_PROTECTED_FIELD');
  const versions = ['expected_revision', 'expectedRevision', 'sourceRevision']
    .filter(key => draft[key] !== undefined).map(key => draft[key]);
  if (!versions.length || !Number.isInteger(versions[0]) || versions[0] < 0) throw new Error('SHOT_REVISION_REQUIRED');
  if (versions.some(version => version !== versions[0])) throw new Error('SHOT_REVISION_ALIAS_CONFLICT');
  const patch: Record<string, any> = {id: draft.id, expected_revision: versions[0]};
  for (const field of ['description', 'video_description', 'shot_image_prompt', 'characters', 'scene', 'props', 'continuity_mode', 'dialogues']) {
    if (draft[field] !== undefined) patch[field] = draft[field];
  }
  // Authored duration is separate from the measured runtime duration in the DTO.
  if (draft.estimated_duration !== undefined || draft.estimatedDuration !== undefined) {
    patch.estimated_duration = draft.estimated_duration ?? draft.estimatedDuration;
  } else if (draft.duration !== undefined) patch.duration = draft.duration;
  const events = draft.audio_events ?? draft.audioEvents;
  if (events !== undefined) patch.audio_events = Array.isArray(events) ? events.map((event, index) => ({...event, order: index + 1})) : events;
  const treatments = draft.source_treatments ?? draft.sourceTreatments;
  if (treatments !== undefined) patch.source_treatments = treatments;
  return patch;
}

export function sameDraftValue(a: any, b: any): boolean {
  if (a === b) return true;
  if (!a || !b || typeof a !== 'object' || typeof b !== 'object' || Array.isArray(a) !== Array.isArray(b)) return false;
  const keys = Object.keys(a);
  return keys.length === Object.keys(b).length && keys.every(key => Object.prototype.hasOwnProperty.call(b,key) && sameDraftValue(a[key],b[key]));
}

const eventFields = ['type','treatmentRef','voiceOwnerName','voiceOwnerCharacterId','visibleSpeakerName','visibleSpeakerCharacterId','requiresVisibleLipsync','text','emotionPrompt','pauseAfter','order'];
const bindingFields = ['type','voiceOwnerName','voiceOwnerCharacterId','visibleSpeakerName','visibleSpeakerCharacterId','requiresVisibleLipsync'];
const authorFields: Record<string,string> = {description:'description',video_description:'video_description',characters:'characters',scene:'scene',props:'props',
  estimatedDuration:'estimated_duration',continuity_mode:'continuity_mode',dialogues:'dialogues',audioEvents:'audio_events',sourceTreatments:'source_treatments',shotImagePrompt:'shot_image_prompt'};

function copy<T>(value: T): T { return value === undefined ? value : JSON.parse(JSON.stringify(value)); }
function eventView(events: any[]) {return (events || []).map(event => Object.fromEntries(['id',...eventFields].map(key => [key,event[key]])));}

function mergeEventDrafts(local: any[], reference: any[], incoming: any[], idMap: Record<string,string>) {
  const mapped = (events: any[]) => (events || []).map(event => ({...event,id:idMap[event.id] || event.id}));
  const current=mapped(local), before=mapped(reference), old=new Map(before.map(event => [event.id,event]));
  const received=new Map((incoming || []).map(event => [event.id,event]));
  const result=current.map(event => {
    const saved=received.get(event.id), prior=old.get(event.id);
    if (!saved) return event;
    if (!prior) return {...saved,...event,id:saved.id};
    const merged={...saved};
    for (const key of eventFields) if (!sameDraftValue(event[key],prior[key])) merged[key]=event[key];
    // Names, IDs and visibility are one draft unit (including deliberate nulls).
    if (bindingFields.some(key => !sameDraftValue(event[key],prior[key]))) {
      for (const key of bindingFields) merged[key]=event[key];
    }
    return merged;
  });
  // Preserve local removals/order. Include genuinely new server Events without
  // guessing that matching text/order identifies a local creation.
  for (const event of incoming || []) if (!old.has(event.id) && !result.some(item => item.id===event.id)) result.push(event);
  return result;
}

export interface ShotSaveContext { start: any; head?: any; patch: Record<string,any>; }

interface CreatedEventIdentity { id: string; submitted: any; trackedInDraft: boolean; applied: boolean; }
export interface ShotEventIdentities { sourceRunId?: string | null; entries: Record<string,CreatedEventIdentity>; }

function identityError(reason: string): never {throw new Error('SHOT_EVENT_IDENTITY_'+reason);}

function acknowledgeEventIdentities(cache: ShotEventIdentities | undefined, incoming: any, local: any, head: any, context: ShotSaveContext | undefined, map: Record<string,string>) {
  const run=incoming.sourceRunId;
  if (!context || context.patch.id!==incoming.id || incoming.sourceRevision<=context.patch.expected_revision
      || (context.start && (context.start.id!==incoming.id || context.start.sourceRunId!==run))
      || (context.head && context.head.sourceRunId!==run) || (local && local.sourceRunId!==run) || (head && head.sourceRunId!==run)) identityError('SCOPE_MISMATCH');
  const entries={...(cache && cache.sourceRunId===run ? cache.entries : {})};
  const submitted=context.patch.audio_events || [];
  const ids=new Set<string>();
  for (const [clientId,id] of Object.entries(map)) {
    const sent=submitted.find((event:any)=>event.id===clientId);
    if (!clientId.startsWith('local-') || !sent || typeof id!=='string' || !id || id.startsWith('local-') || ids.has(id)
        || !(incoming.audioEvents || []).some((event:any)=>event.id===id)
        || Object.entries(entries).some(([other,value])=>other!==clientId && value.id===id)
        || (entries[clientId] && entries[clientId].id!==id)) identityError('MAP_INVALID');
    ids.add(id);
    entries[clientId] ||= {id,submitted:copy(sent),trackedInDraft:(context.start?.audioEvents || []).some((event:any)=>event.id===clientId),applied:false};
  }
  return {sourceRunId:run,entries};
}

/** Apply verified identity knowledge without accepting any stale DTO content. */
function repairEventIdentities(local: any, server: any, identity: ShotEventIdentities) {
  if (!local || local.sourceRunId!==identity.sourceRunId || server?.sourceRunId!==identity.sourceRunId) return {shot:local,identity};
  let events=copy(local.audioEvents || []);
  const entries={...identity.entries};
  for (const [clientId,entry] of Object.entries(entries)) {
    const alias=events.find((event:any)=>event.id===clientId), canonical=events.find((event:any)=>event.id===entry.id);
    const latest=(server.audioEvents || []).find((event:any)=>event.id===entry.id);
    if (!alias) {
      // A tracked creation removed before its first acknowledgement stays removed,
      // even if an intervening GET had appended the as-yet unrelated server UUID.
      if (!entry.applied && entry.trackedInDraft) events=events.filter((event:any)=>event.id!==entry.id);
      entries[clientId]={...entry,applied:true};continue;
    }
    if (!latest) identityError('TARGET_NOT_CURRENT');
    const delta=(value:any,base:any) => {
      const changed:Record<string,any>={};
      for (const key of eventFields) if (!sameDraftValue(value[key],base[key])) changed[key]=value[key];
      if (bindingFields.some(key=>!sameDraftValue(value[key],base[key]))) for (const key of bindingFields) changed[key]=value[key];
      return changed;
    };
    const fromAlias=delta(alias,entry.submitted), fromCanonical=canonical ? delta(canonical,latest) : {};
    for (const key of Object.keys(fromAlias)) {
      if (Object.prototype.hasOwnProperty.call(fromCanonical,key) && !sameDraftValue(fromAlias[key],fromCanonical[key])) identityError('DRAFT_CONFLICT');
    }
    const merged={...latest,...fromCanonical,...fromAlias,id:entry.id};
    // Keep the author's creation position; never infer identity from text/order.
    events=events.flatMap((event:any)=>event.id===clientId ? [merged] : event.id===entry.id ? [] : [event]);
    entries[clientId]={...entry,applied:true};
  }
  return {shot:{...local,audioEvents:events},identity:{...identity,entries}};
}

export function normalizeKnownEventIdentities(state: any, draft: any) {
  const identity=state.shotEventIdentities?.[draft.id];
  if (!identity) return draft;
  const current=state.shots.find((shot:any)=>shot.id===draft.id), head=state.shotServerHeads?.[draft.id];
  if (!current || current.sourceRunId!==identity.sourceRunId || (draft.sourceRunId!==undefined && draft.sourceRunId!==identity.sourceRunId)) return draft;
  const events=draft.audio_events ?? draft.audioEvents;
  if (!events) return draft;
  const repaired=repairEventIdentities({...current,...draft,audioEvents:events},head || current,identity).shot;
  return {...draft,...(draft.audio_events!==undefined ? {audio_events:repaired.audioEvents} : {audioEvents:repaired.audioEvents})};
}

/** Reconcile a verified DTO with the draft that existed before/during this request. */
export function reconcileShotDraft(local: any, head: any, incoming: any, context?: ShotSaveContext, idMap: Record<string,string> = {}) {
  if (!local) return copy(incoming);
  if (incoming.sourceRevision < Math.max(local.sourceRevision ?? -1,head?.sourceRevision ?? -1)) return local;
  const result=copy(incoming), start=context?.start || head, patch=context?.patch || {};
  for (const [field,wire] of Object.entries(authorFields)) {
    const submitted=Object.prototype.hasOwnProperty.call(patch,wire) || (field==='estimatedDuration' && Object.prototype.hasOwnProperty.call(patch,'duration'));
    const reference=submitted ? start : (context?.head || head);
    let dirty=reference ? !sameDraftValue(field==='audioEvents'?eventView(local[field]):local[field],field==='audioEvents'?eventView(reference[field]):reference[field]) : local[field] !== undefined;
    if (context && !submitted && !reference && field==='dialogues' && patch.audio_events) {
      // Compatibility dialogue projection is server-owned unless edited locally.
      const projected=(start?.audioEvents || []).filter((event:any)=>event.type==='DIALOGUE').map((event:any,index:number)=>({order:index+1,character_name:event.voiceOwnerName,text:event.text,emotion_prompt:event.emotionPrompt || '自然'}));
      dirty=!sameDraftValue(local.dialogues,projected);
    }
    if (!dirty) continue;
    result[field]=field==='audioEvents' ? mergeEventDrafts(local[field],reference?.[field] || start?.[field],incoming[field],idMap) : copy(local[field]);
  }
  return result;
}

export function captureShotSaves(state: any, patches: Record<string,any>[]) {
  return Object.fromEntries(patches.map(patch => [patch.id,{patch:copy(patch),start:copy(state.shots.find((shot:any)=>shot.id===patch.id)),head:copy(state.shotServerHeads?.[patch.id])}]));
}

/** Shared GET/save DTO receiver. Accepted heads and local authoring drafts stay separate. */
export function receiveShotSnapshots(state: any, received: any[], contexts: Record<string,ShotSaveContext> = {}, eventIdMaps: Record<string,Record<string,string>> = {}, replace=false) {
  const heads={...state.shotServerHeads}, byId=new Map(state.shots.map((shot:any)=>[shot.id,shot]));
  const shotImages={...state.shotImages},shotVideos={...state.shotVideos};
  const shotEventIdentities={...state.shotEventIdentities};
  for (const incoming of received) {
    let local:any=byId.get(incoming.id);const head=heads[incoming.id];
    const map=eventIdMaps[incoming.id] || {};
    if (Object.keys(map).length) shotEventIdentities[incoming.id]=acknowledgeEventIdentities(shotEventIdentities[incoming.id],incoming,local,head,contexts[incoming.id],map);
    const identity=shotEventIdentities[incoming.id];
    if (identity && local && identity.sourceRunId===local.sourceRunId) {
      const newest=head && head.sourceRevision>=incoming.sourceRevision ? head : local.sourceRevision>incoming.sourceRevision ? local : incoming;
      const repaired=repairEventIdentities(local,newest,identity);
      local=repaired.shot;shotEventIdentities[incoming.id]=repaired.identity;byId.set(incoming.id,local);
    }
    if (incoming.sourceRevision < Math.max(local?.sourceRevision ?? -1,head?.sourceRevision ?? -1)) continue;
    const next=reconcileShotDraft(local,head,incoming,contexts[incoming.id],eventIdMaps[incoming.id]);
    byId.set(incoming.id,next);heads[incoming.id]=copy(incoming);
    if (incoming.imageUrl) shotImages[incoming.id]=incoming.imageUrl;else delete shotImages[incoming.id];
    if (incoming.videoUrl) shotVideos[incoming.id]=incoming.videoUrl;else delete shotVideos[incoming.id];
  }
  return {shots:(replace?received:state.shots).map((shot:any)=>byId.get(shot.id) || shot),shotServerHeads:heads,shotEventIdentities,shotImages,shotVideos};
}
