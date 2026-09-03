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

export interface WorkflowImportPreviewItem {
  index: number;
  id?: string;
  name: string;
  description: string;
  type: string;
  type_label: string;
  is_system: boolean;
  is_active: boolean;
  node_mapping: Record<string, unknown>;
  extension: Record<string, unknown>;
  workflow_file: string;
  valid: boolean;
  errors: string[];
}

export interface WorkflowImportPreview {
  workflows: WorkflowImportPreviewItem[];
  valid_count: number;
  invalid_count: number;
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

  /** 按选择导出工作流 */
  exportSelected: async (workflowIds: string[]) => {
    const response = await fetch(`${API_BASE}/workflows/export`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workflow_ids: workflowIds }),
    });
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
      : filenameMatch?.[1] || 'workflows_export.zip';
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },

  /** 预览导入工作流 ZIP */
  previewImport: async (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    const response = await fetch(`${API_BASE}/workflows/import/preview`, {
      method: 'POST',
      body: formData,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || data.message || '解析工作流 ZIP 失败');
    return data as { success: boolean; data?: WorkflowImportPreview; message?: string };
  },

  /** 执行导入工作流 ZIP */
  executeImport: async (file: File, selectedIndexes: number[]) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('selected_indexes', JSON.stringify(selectedIndexes));
    const response = await fetch(`${API_BASE}/workflows/import/execute`, {
      method: 'POST',
      body: formData,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || data.message || '导入工作流失败');
    return data as { success: boolean; data?: { imported: WorkflowImportPreviewItem[] }; message?: string };
  },

  /** 获取扩展配置 */
  fetchExtensionsConfig: () => api.get('/workflows/extensions/config/'),
};
