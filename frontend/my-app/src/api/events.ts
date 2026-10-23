import { API_BASE } from './index';

export interface BusinessEvent {
  event_id: string; event_type: string; name: string; category: string;
  timestamp: string; recorded_at: string; status: 'SUCCESS' | 'FAIL' | 'ERROR' | 'INFO'; raw_status: string;
  novel_id: string | null; chapter_id: string | null; shot_id: string | null;
  visual_state_id: string | null; clip_id: string | null; task_id: string | null; review_id: string | null; llm_log_id: string | null;
  novel_title: string | null; chapter_title: string | null; shot_index: number | null;
  source: string; trigger: string | null; message: string; details: Record<string, unknown>;
  needs_attention: boolean; historical: boolean; is_test: boolean; notification_status: string;
}
export interface EventDetail extends BusinessEvent {
  links: { label: string; href: string }[];
  review_target: { id: string; name: string; review_id: string } | null;
  notification_result: Record<string, unknown>;
}
export interface EventOptions {
  events: { event_type: string; name: string; category: string }[];
  novels: { id: string; title: string }[];
  chapters: { id: string; title: string; novel_id: string }[];
  shots: { id: string; index: number; chapter_id: string }[];
}
export interface EventPage {
  items: BusinessEvent[]; page: number; page_size: number; total: number;
  counts: { all: number; attention: number; today: number };
}
async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}/events${path}`);
  const data = await response.json();
  if (!response.ok || !data.success) throw new Error(typeof data.detail === 'string' ? data.detail : '事件读取失败');
  return data.data;
}
export const eventsApi = {
  list: (query: URLSearchParams) => get<EventPage>(`?${query}`),
  options: () => get<EventOptions>('/options'),
  detail: (id: string) => get<EventDetail>(`/${encodeURIComponent(id)}`),
};
