import {api} from './index';
export interface SourceEvidence {text:string;context_before?:string;context_after?:string}
export interface SourceRange {start:number;end:number;text:string}
export interface ShotSourceContract {version:'chapter-shot-ownership-v2';citation_evidence:SourceEvidence[];citation_ranges:SourceRange[];ownership_evidence:SourceEvidence;ownership_range:SourceRange}
export interface ShotSourceProof {shotId:string;splitRunId:string;sourceStart:number;sourceEnd:number;sourceHash:string;sourceEvidence:SourceEvidence[];sourceRanges:SourceRange[];
  sourceContract?:ShotSourceContract|null;sourceContractVersion?:string|null;sourceCitations?:SourceEvidence[]|null;sourceCitationRanges?:SourceRange[]|null;
  offsetUnit?:'UNICODE_CODE_POINT';assetBindings:Record<string,{assetId:string;name:string;id:string}[]>}
export interface SplitState {canSplit:boolean;splitBlocker:unknown;phase5Ready:boolean;latestRunId:string|null;runStatus:string;issues:unknown[];
  treatmentContractVersion?:string|null;sourceContractVersion?:string|null;
  scope:Record<string,{status:string;emptyConfirmed:boolean;bindings:{id:string;assetId:string;name:string;entityType:string|null}[]}>|null;
  shots:{shotId:string;index:number;status:string;issue:unknown;completionDisposition:'NORMAL'|'DEGRADED_NARRATION_CARD';source:ShotSourceProof|null}[]}
export interface CompletionEntry {shotId:string;shotIndex:number;completionDisposition:'NORMAL'|'DEGRADED_NARRATION_CARD';sourceRange:[number,number]|null;ready:boolean;blocker:unknown}
export interface CompletionReadiness {ready:boolean;manifestHash:string|null;counts:{normal:number;degraded:number;total:number};entries:CompletionEntry[];blocker:unknown}
export interface ChapterCompletion {taskId:string;outcome:'SUCCEEDED'|'SUCCEEDED_WITH_DEGRADATION';manifestHash:string;url:string;normalCount:number;degradedCount:number;degradedRanges:{shotId:string;shotIndex:number;sourceRange:[number,number]}[]}
const root=(n:string,c:string)=>`/novels/${n}/chapters/${c}`;
export const chapterShotSplitsApi={
  state:(n:string,c:string)=>api.get<SplitState>(`${root(n,c)}/split-state`),
  runs:(n:string,c:string)=>api.get<{id:string;status:string;taskId:string}[]>(`${root(n,c)}/split-runs`),
  detail:(n:string,c:string,id:string)=>api.get<unknown>(`${root(n,c)}/split-runs/${id}`),
  admitNarrationCard:(n:string,c:string,id:string)=>api.post<{splitRunId:string;taskId:string;status:string;controlledDegradation:unknown}>(`${root(n,c)}/split-runs/${id}/narration-card`),
  prepareNarrationCardAudio:(n:string,c:string,s:string)=>api.post<{taskId:string;status:string}>(`${root(n,c)}/shots/${s}/narration-card/audio-prepare`),
  renderNarrationCard:(n:string,c:string,s:string)=>api.post<{taskId:string;status:string}>(`${root(n,c)}/shots/${s}/narration-card/render`),
  narrationCard:(n:string,c:string,s:string)=>api.get<unknown>(`${root(n,c)}/shots/${s}/narration-card`),
  completionReadiness:(n:string,c:string)=>api.get<CompletionReadiness>(`${root(n,c)}/completion-readiness`),
  completion:(n:string,c:string)=>api.get<ChapterCompletion|null>(`${root(n,c)}/completion`),
  complete:(n:string,c:string,manifestHash:string)=>api.post<{taskId:string;status:string;manifestHash:string;counts:{normal:number;degraded:number;total:number}}>(`${root(n,c)}/completion?expectedManifestHash=${encodeURIComponent(manifestHash)}`),
  validateTreatments:(n:string,c:string,s:string)=>api.get<{status:string;visual_semantics_verified:false;counts?:Record<string,number>;issues:unknown[]}>(`${root(n,c)}/shots/${s}/treatment-validation`),
};
