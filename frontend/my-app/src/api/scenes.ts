/**
 * 场景相关 API
 */
import { api, API_BASE } from './index';
import type { Scene } from '../types';

export const sceneApi = {
  /** 获取场景列表 */
  fetchList: (novelId: string) => api.get<Scene[]>(`/scenes?novel_id=${novelId}`),

  /** 获取单个场景 */
  fetch: (id: string) => api.get<Scene>(`/scenes/${id}`),

  /** 创建场景 */
  create: (data: Partial<Scene>) => api.post<Scene>('/scenes/', data),

  /** 更新场景 */
  update: (id: string, data: Partial<Scene>) => api.put<Scene>(`/scenes/${id}/`, data),

  /** 删除场景 */
  delete: (id: string) => api.delete(`/scenes/${id}/`),

  /** 删除小说下所有场景 */
  deleteAll: (novelId: string) => api.delete(`/scenes/?novel_id=${novelId}`),

  /** 获取场景提示词 */
  fetchPrompt: (sceneId: string) => 
    api.get<{ prompt: string; templateName: string; templateId?: string; isSystem?: boolean }>(`/scenes/${sceneId}/prompt`),

  /** 生成场景设定 */
  generateSetting: (sceneId: string) => 
    api.post<Scene>(`/scenes/${sceneId}/generate-setting`),

  /** 生成场景图任务 */
  generateImage: (sceneId: string) => 
    api.post(`/scenes/${sceneId}/generate-image`),

  /** 为未生成或失败的场景生成图片任务 */
  generateMissingImages: (novelId: string) =>
    api.post<{ queuedCount: number; failedCount: number; failedItems: Array<{ id: string; name: string; message: string }> }>(`/scenes/generate-missing-images?novel_id=${novelId}`),

  /** 上传场景图片 */
  uploadImage: async (sceneId: string, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.upload<Scene>(`/scenes/${sceneId}/upload-image`, formData);
  },

  /** 使用单图编辑工作流编辑场景图片 */
  editImage: (sceneId: string, prompt: string) =>
    api.post<{ imageUrl: string; taskId?: string }>(`/scenes/${sceneId}/edit-image`, { prompt }),

  /** 用编辑结果替换场景图片 */
  replaceImage: (sceneId: string, imageUrl: string) =>
    api.post<Scene>(`/scenes/${sceneId}/replace-image`, { imageUrl }),

  /** 清空场景图片目录 */
  clearImagesDir: (novelId: string) => 
    api.post(`/scenes/clear-scenes-dir?novel_id=${novelId}`),

  /** 解析场景 */
  parseScenes: (novelId: string, mode: 'incremental' | 'full') => 
    api.post('/scenes/parse-scenes', { novel_id: novelId, chapter_ids: [], mode }),
};
