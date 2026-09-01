/**
 * 工作流相关 API
 */
import { api, API_BASE } from './index';

export interface Workflow {
  id: string;
  name: string;
  description: string;
  type: string;
  is_default: boolean;
  is_system: boolean;
  file_path: string;
  created_at: string;
}

export interface WorkflowMapping {
  character_workflow?: string;
  scene_workflow?: string;
  shot_workflow?: string;
  video_workflow?: string;
  transition_workflow?: string;
}

export const workflowApi = {
  /** 获取工作流列表 */
  fetchList: (type?: string) => api.get<Workflow[]>(`/workflows/${type ? `?type=${type}` : ''}`),

  /** 获取单个工作流 */
  fetch: (id: string) => api.get<Workflow>(`/workflows/${id}/`),

  /** 更新工作流 */
  update: (id: string, data: Partial<Workflow>) => api.put<Workflow>(`/workflows/${id}/`, data),

  /** 删除工作流 */
  delete: (id: string) => api.delete(`/workflows/${id}/`),

  /** 设置默认工作流 */
  setDefault: (id: string) => api.post(`/workflows/${id}/set-default/`),

  /** 上传工作流 */
  upload: async (formData: FormData) => {
    const response = await fetch(`${API_BASE}/workflows/upload/`, {
      method: 'POST',
      body: formData
    });
    return response.json();
  },

  /** 打包下载所有类别的当前工作流 */
  exportActive: async () => {
    const response = await fetch(`${API_BASE}/workflows/export-active`);
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || data.message || '导出工作流失败');
    }
    const blob = await response.blob();
    const disposition = response.headers.get('content-disposition') || '';
    const encodedFilenameMatch = disposition.match(/filename\*=UTF-8''([^;]+)/i);
    const filenameMatch = disposition.match(/filename="?([^";]+)"?/i);
    const filename = encodedFilenameMatch
      ? decodeURIComponent(encodedFilenameMatch[1])
      : filenameMatch?.[1] || 'workflows.zip';
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },

  /** 获取扩展配置 */
  fetchExtensionsConfig: () => api.get('/workflows/extensions/config/'),
};
