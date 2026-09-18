import { api } from './index';

export type AssetKind = 'characters' | 'scenes' | 'props';
export interface AssetCandidate {
  id: string;
  assetType: AssetKind;
  name: string;
  entity_type?: 'INDIVIDUAL' | 'GROUP';
  group_size_hint?: number | null;
  description: string;
  appearance?: string;
  setting?: string;
  voice_prompt?: string | null;
  chapter_presence?: { role: string };
  source_evidence: { text: string }[];
  chapter_appearances?: { event_key: string; change_type: string; appearance_description: string | null; source_evidence: { text: string }[] }[];
  validationStatus: string;
  issues: unknown[];
}
export interface AssetParseRun {
  id: string;
  chapterId: string;
  taskId: string;
  parserVersion: string;
  status: string;
  effectiveStatus: string;
  sourceCurrent: boolean;
  sourceHash: string;
  kinds: AssetKind[];
  phase1Ready: boolean;
  publishedToBook: boolean;
  candidateCount: number;
  createdAt: string;
  issues: unknown[];
  candidates?: AssetCandidate[];
  calls?: Record<string, unknown>[];
  source?: { title: string; number: number; content: string };
}
const path = (novelId: string, chapterId: string) => `/novels/${novelId}/chapters/${chapterId}/asset-parses`;
export const chapterAssetsApi = {
  parse: (novelId: string, chapterId: string, kinds: AssetKind[]) => api.post<AssetParseRun>(path(novelId, chapterId), { kinds }),
  list: (novelId: string, chapterId: string) => api.get<AssetParseRun[]>(path(novelId, chapterId)),
  get: (novelId: string, chapterId: string, runId: string) => api.get<AssetParseRun>(`${path(novelId, chapterId)}/${runId}`),
};
