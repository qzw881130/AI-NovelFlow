/**
 * LLM 日志相关 API
 */
import { api, API_BASE } from './index';

export interface LLMLog {
  id: string;
  created_at: string;
  provider: string;
  model: string;
  prompt_template_name: string | null;
  system_prompt: string | null;
  user_prompt: string;
  request_info?: string | null;
  response: string | null;
  status: 'pending' | 'success' | 'error';
  error_message: string | null;
  task_type: string | null;
  novel_id: string | null;
  chapter_id: string | null;
  character_id: string | null;
  used_proxy: boolean;
  duration: number | null;
  metrics?: LLMLogMetrics | null;
}

export interface LLMLogMetrics {
  input_tokens?: number | null;
  output_tokens?: number | null;
  total_tokens?: number | null;
  cached_input_tokens?: number | null;
  reasoning_tokens?: number | null;
  finish_reason?: string | null;
  output_tokens_per_second?: number | null;
  raw_usage?: Record<string, unknown> | null;
}

export interface Pagination {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

export interface LLMLogsResponse {
  items: LLMLog[];
  pagination: Pagination;
}

export interface FilterOptions {
  providers: string[];
  models: string[];
  task_types: string[];
}

export interface LLMLogFilters {
  provider: string;
  model: string;
  category: string;
  task_type: string;
  status: string;
}

export type LLMLogStatsGroupBy = 'day' | 'hour' | 'minute';

export interface LLMLogStatsItem {
  key: string;
  label: string;
  count: number;
}

export interface LLMLogStatsResponse {
  group_by: LLMLogStatsGroupBy;
  range_value: number;
  total: number;
  items: LLMLogStatsItem[];
}

export interface LLMLogTokenStatsItem {
  key: string;
  label: string;
  input_tokens: number;
  output_tokens: number;
}

export interface LLMLogTokenStatsResponse {
  group_by: LLMLogStatsGroupBy;
  range_value: number;
  total_input_tokens: number;
  total_output_tokens: number;
  items: LLMLogTokenStatsItem[];
}

export const llmLogsApi = {
  /** 获取日志列表 */
  fetchList: (page: number, pageSize: number, filters: LLMLogFilters) => {
    const params = new URLSearchParams();
    params.append('page', page.toString());
    params.append('page_size', pageSize.toString());
    Object.entries(filters).forEach(([key, value]) => {
      if (value) params.append(key, value);
    });
    return api.get<LLMLogsResponse>(`/llm-logs/?${params}`);
  },

  /** 获取日志详情 */
  fetchDetail: (id: string) => api.get<LLMLog>(`/llm-logs/${id}`),

  /** 获取筛选选项 */
  fetchFilterOptions: () => api.get<FilterOptions>('/llm-logs/filters'),

  /** 获取调用统计 */
  fetchStats: (groupBy: LLMLogStatsGroupBy, rangeValue: number, filters: LLMLogFilters) => {
    const params = new URLSearchParams();
    params.append('group_by', groupBy);
    params.append('range_value', String(rangeValue));
    Object.entries(filters).forEach(([key, value]) => {
      if (value) params.append(key, value);
    });
    return api.get<LLMLogStatsResponse>(`/llm-logs/stats?${params}`);
  },

  /** 获取 Token 消耗统计 */
  fetchTokenStats: (groupBy: LLMLogStatsGroupBy, rangeValue: number, filters: LLMLogFilters) => {
    const params = new URLSearchParams();
    params.append('group_by', groupBy);
    params.append('range_value', String(rangeValue));
    Object.entries(filters).forEach(([key, value]) => {
      if (value) params.append(key, value);
    });
    return api.get<LLMLogTokenStatsResponse>(`/llm-logs/token-stats?${params}`);
  },

  /** 打包下载所选日志的完整 LLM 参数与响应 */
  downloadSelected: async (ids: string[]) => {
    const response = await fetch(`${API_BASE}/llm-logs/export-selected`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids }),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || data.message || '打包下载失败');
    }
    const blob = await response.blob();
    const disposition = response.headers.get('Content-Disposition') || '';
    const filename = disposition.match(/filename="?([^";]+)"?/)?.[1] || 'llm_logs.zip';
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  },
};
