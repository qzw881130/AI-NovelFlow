/**
 * LLM 日志相关 API
 */
import { api } from './index';

export interface LLMLog {
  id: string;
  created_at: string;
  provider: string;
  model: string;
  system_prompt: string;
  user_prompt: string;
  response: string;
  status: string;
  error_message: string;
  task_type: string;
  novel_id: string;
  chapter_id: string;
  character_id: string;
  used_proxy: boolean;
  duration: number;
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

export const llmLogsApi = {
  /** 获取日志列表 */
  fetchList: (page: number, pageSize: number, filters: Record<string, string>) => {
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
};
