import { api } from './index';
import type { AssetKind, AssetCandidate } from './chapterAssets';

export interface IdentityAsset {
  asset_id: string;
  canonical_name: string;
  entity_type: 'INDIVIDUAL' | 'GROUP' | null;
  description: string;
  strong_aliases: string[];
  contextual_aliases: string[];
  retrieval_score?: number;
  is_narrator?: boolean;
}
export interface IdentityDecision {
  id: string;
  candidateId: string;
  assetType: AssetKind;
  candidate: AssetCandidate;
  resolution: string;
  matchType: string;
  confidence: number;
  reason: string;
  status: string;
  assetId: string | null;
  canonicalName: string;
  llmUsed: boolean;
  shortlist: IdentityAsset[];
  candidateMatches: {asset_id: string; confidence: number}[];
  call: unknown;
}
export interface ResolutionRun {
  id: string; taskId: string; status: string; effectiveStatus: string; phase2Ready: boolean;
  kinds: AssetKind[]; decisions: IdentityDecision[]; reviews: IdentityDecision[]; issues: unknown[];
}
export interface BindingState {
  phase2Ready: boolean;
  assets: Record<AssetKind, {status: string; runId: string|null; emptyConfirmed: boolean; bindings: {
    id: string; assetId: string; name: string; entityType: string | null; method: string; chapterRole: string | null;
    membershipEvidence?: {text:string}[]; sourceEvidence?: {text:string}[];
  }[]}>;
}

export type SceneGroundingClassification = 'DIRECT_LOCAL'|'CONTEXT_INFERRED'|'SCENE_TRANSITION'|'SCENE_UNRESOLVED';
export interface SceneGroundingReport {
  version:string; splitRunId:string; splitRunStatus:string; sourceHash:string; sourceCurrent:boolean;
  bindingEvidenceSemantic:'CHAPTER_MEMBERSHIP_REPRESENTATIVE'; bindingEvidenceIsOccurrenceProof:false;
  autoAuthorization:'DIRECT_LOCAL'[]; auditEligibleForAuthorization:boolean;
  diagnosticOnly:'CONTEXT_INFERRED'[]; failClosed:('SCENE_TRANSITION'|'SCENE_UNRESOLVED')[];
  transitionCueSemantic:'HEURISTIC_DIAGNOSTIC_NOT_OCCURRENCE_PROOF';
  counts:Record<SceneGroundingClassification|'HUMAN_REQUIRED'|'total',number>;
  shots:{shotIndex:number;range:[number,number];scene:string;classification:SceneGroundingClassification;
    reason:string;autoAuthorized:boolean;membershipEvidence:{scene:string;text:string;range:[number,number]}[];
    sceneNameMentions:string[];otherSceneSignals:string[];transitionCues:string[];possibleNextScenes:string[]}[];
}
export interface IdentityCatalog { assets: Record<AssetKind, IdentityAsset[]>; hash: string; genericGroups: string[] }
const root = (n: string, c: string) => `/novels/${n}/chapters/${c}`;
export const assetResolutionsApi = {
  resolve: (n: string, c: string, kinds: AssetKind[], force = false) => api.post<ResolutionRun>(`${root(n,c)}/asset-resolutions`, { kinds, force }),
  list: (n: string, c: string) => api.get<ResolutionRun[]>(`${root(n,c)}/asset-resolutions`),
  bindings: (n: string, c: string) => api.get<BindingState>(`${root(n,c)}/asset-bindings`),
  sceneGrounding: (n:string,c:string,runId:string) => api.get<SceneGroundingReport>(`${root(n,c)}/split-runs/${runId}/scene-grounding`),
  catalog: (n: string) => api.get<IdentityCatalog>(`/novels/${n}/identity-catalog`),
  review: (n: string, c: string, id: string, action: { action: 'MATCH'|'CREATE'|'IGNORE'; asset_id?: string; canonical_name?: string; confirm_legacy_type?: boolean; expected_catalog_hash: string }) =>
    api.post<ResolutionRun>(`${root(n,c)}/asset-reviews/${id}`, action),
};
