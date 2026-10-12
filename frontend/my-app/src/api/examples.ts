import { API_BASE } from './index';

export interface ExampleSummary {
  id: string;
  title: string;
  category: string;
  description: string;
  chapterCount: number;
}

export interface ExampleDetail extends ExampleSummary {
  chapters: { number: number; title: string; content: string }[];
}

async function request<T>(path: string, method = 'GET'): Promise<T> {
  const response = await fetch(`${API_BASE}/examples${path}`, { method });
  const body = await response.json().catch(() => ({}));
  if (!response.ok || !body.success || !body.data) {
    throw new Error(body.detail || body.message || `请求失败（HTTP ${response.status}）`);
  }
  return body.data as T;
}

export const examplesApi = {
  list: () => request<ExampleSummary[]>('/'),
  detail: (id: string) => request<ExampleDetail>(`/${encodeURIComponent(id)}/`),
  import: (id: string) => request<{ novel_id: string; chapter_count: number }>(`/${encodeURIComponent(id)}/import/`, 'POST'),
};
