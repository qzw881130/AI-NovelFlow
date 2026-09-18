import { api } from './index';

export interface AppearanceSelection {
  kind: 'BASE'|'APPEARANCE'|'UNRESOLVED'; appearanceId: string|null; sourceEventIds: string[];
  sourceChapterId: string|null; reason: string; imageStatus?: string;
}
export interface CharacterTimeline {
  characterId: string; name: string; bindingId: string; logicalReady: boolean; issues: unknown[];
  entry: AppearanceSelection; exit: AppearanceSelection;
  segments: {start:number; end:number; selection:AppearanceSelection}[];
}
export interface TimelineRun {
  id: string; taskId: string; effectiveStatus: string; phase3Ready: boolean; inputHash: string|null;
  issues: unknown[]; createdAt: string;
  result?: {targetChapterId:string; chapters:{chapterId:string; number:number; characters:CharacterTimeline[]}[]};
}
export interface LocatedEvent {
  proposal: {id:string; character_id:string; event_key:string; change_type:string; appearance_description:string|null; source_evidence:{text:string}[]};
  proposal_hash:string; status:string; source_start:number|null; source_end:number|null; resolvedAppearanceId:string|null;
  review:unknown; locationProof?:{code?:string; candidate_spans?:[number,number][]};
}
export interface EventSource {sourceHash:string; content:string; events:LocatedEvent[]}
const root=(n:string,c:string)=>`/novels/${n}/chapters/${c}`;
export const appearanceTimelinesApi={
  build:(n:string,c:string)=>api.post<TimelineRun>(`${root(n,c)}/appearance-timelines`,{}),
  rebuildThrough:(n:string,c:string)=>api.post<TimelineRun[]>(`${root(n,c)}/appearance-timelines/rebuild-through`),
  list:(n:string,c:string)=>api.get<TimelineRun[]>(`${root(n,c)}/appearance-timelines`),
  get:(n:string,c:string,id:string)=>api.get<TimelineRun>(`${root(n,c)}/appearance-timelines/${id}`),
  events:(n:string,c:string)=>api.get<EventSource>(`${root(n,c)}/appearance-events`),
  review:(n:string,c:string,id:string,data:{action:'LOCATE'|'CONFIRM_NEW'|'IGNORE';expected_source_hash:string;expected_proposal_hash:string;
    source_start?:number;source_end?:number;evidence_text?:string;appearance_description?:string;reason:string})=>
    api.post(`${root(n,c)}/appearance-events/${id}/review`,data),
};
