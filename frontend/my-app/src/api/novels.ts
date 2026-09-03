/**
 * 小说相关 API
 */
import { api, API_BASE } from './index';
import type { Novel, Chapter } from '../types';

export const novelApi = {
  /** 获取小说列表 */
  fetchList: () => api.get<Novel[]>('/novels/'),

  /** 获取单个小说 */
  fetch: (id: string) => api.get<Novel>(`/novels/${id}/`),

  /** 创建小说 */
  create: (data: Partial<Novel>) => api.post<Novel>('/novels/', data),

  /** 更新小说 */
  update: (id: string, data: Partial<Novel>) => api.put<Novel>(`/novels/${id}/`, data),

  /** 导出当前小说配置的提示词模板 */
  exportPromptTemplates: async (id: string, templateIds: Record<string, string | undefined>) => {
    const response = await fetch(`${API_BASE}/novels/${id}/prompt-templates/export`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ templateIds }),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || data.message || '导出提示词模板失败');
    }
    const blob = await response.blob();
    const disposition = response.headers.get('content-disposition') || '';
    const encodedFilenameMatch = disposition.match(/filename\*=UTF-8''([^;]+)/i);
    const filenameMatch = disposition.match(/filename="?([^";]+)"?/i);
    const filename = encodedFilenameMatch
      ? decodeURIComponent(encodedFilenameMatch[1])
      : filenameMatch?.[1] || 'prompt_templates.zip';
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  },

  /** 删除小说 */
  delete: (id: string) => api.delete(`/novels/${id}/`),

  /** 获取章节列表 */
  fetchChapters: (novelId: string) => api.get<Chapter[]>(`/novels/${novelId}/chapters/`),

  /** 导入小说 */
  import: async (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.upload<Novel>('/novels/import/', formData);
  },

  /** 解析角色 */
  parseCharacters: (novelId: string, params: { sync: boolean; start_chapter?: number; end_chapter?: number; is_incremental: boolean }) => {
    const searchParams = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined) searchParams.append(key, String(value));
    });
    return api.post(`/novels/${novelId}/parse-characters/?${searchParams.toString()}`);
  },
};
