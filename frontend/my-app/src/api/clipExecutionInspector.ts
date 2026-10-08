import { API_BASE } from './index';
import type { Analysis, ArtifactList, Projection, SamplingManifest, ObservationDraft } from '../pages/ClipExecutionInspector/types';

const ROOT = `${API_BASE}/clip-execution-inspector`;
async function request<T>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal, revision?: number): Promise<T> {
  const response = await fetch(`${ROOT}${path}`, { method, signal,
    headers: { ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}), ...(revision !== undefined ? { 'If-Match': `"${revision}"` } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body) });
  const result = await response.json();
  if (!response.ok || !result.success) throw new Error(`${result.detail?.code || 'INSPECTOR_ERROR'}: ${result.detail?.message || result.message || response.statusText}`);
  return result.data as T;
}
const id = encodeURIComponent;
export const inspectorApi = {
  execution: (taskId: string, artifact?: string | null, signal?: AbortSignal) => request<Projection>(`/executions/${id(taskId)}${artifact ? `?artifact_id=${id(artifact)}` : ''}`, 'GET', undefined, signal),
  evidence: (taskId: string, artifact: string, signal?: AbortSignal) => request<Record<string, any>>(`/executions/${id(taskId)}/evidence?artifact_id=${id(artifact)}`, 'GET', undefined, signal),
  artifacts: (shotId: string, clipIndex: number, signal?: AbortSignal) => request<ArtifactList>(`/shots/${id(shotId)}/clips/${clipIndex}/artifacts`, 'GET', undefined, signal),
  sampling: (taskId: string, body: Record<string, any>, offset = 0, signal?: AbortSignal) => request<SamplingManifest>(`/executions/${id(taskId)}/sampling?offset=${offset}`, 'POST', body, signal),
  createAnalysis: (taskId: string, artifact: string) => request<Analysis>('/analyses', 'POST', { task_id: taskId, artifact_id: artifact }),
  analysis: (analysisId: string, signal?: AbortSignal) => request<Analysis>(`/analyses/${id(analysisId)}`, 'GET', undefined, signal),
  createObservation: (analysis: Analysis, draft: ObservationDraft) => request<Analysis>(`/analyses/${id(analysis.analysis_id)}/observations`, 'POST', { ...draft, variant_id: 'A' }, undefined, analysis.revision),
  updateObservation: (analysis: Analysis, observationId: string, draft: ObservationDraft) => request<Analysis>(`/analyses/${id(analysis.analysis_id)}/observations/${id(observationId)}`, 'PATCH', draft, undefined, analysis.revision),
  deleteObservation: (analysis: Analysis, observationId: string) => request<Analysis>(`/analyses/${id(analysis.analysis_id)}/observations/${id(observationId)}`, 'DELETE', undefined, undefined, analysis.revision),
};
export const inspectorMediaUrl = (path: string) => `${API_BASE.replace(/\/api$/, '')}${path}`;
