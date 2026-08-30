/**
 * 道具相关 API
 */
import { api } from './index';
import type { Prop } from '../types';

export const propApi = {
  /** 获取道具列表 */
  fetchList: (novelId: string) => api.get<Prop[]>(`/props/?novel_id=${novelId}`),

  /** 获取单个道具 */
  fetch: (id: string) => api.get<Prop>(`/props/${id}`),

  /** 创建道具 */
  create: (data: Partial<Prop>) => api.post<Prop>('/props/', data),

  /** 更新道具 */
  update: (id: string, data: Partial<Prop>) => api.put<Prop>(`/props/${id}`, data),

  /** 删除道具 */
  delete: (id: string) => api.delete(`/props/${id}`),

  /** 删除小说下所有道具 */
  deleteAll: (novelId: string) => api.delete(`/props/?novel_id=${novelId}`),

  /** 解析道具 */
  parseProps: (novelId: string, params: { startChapter?: number; endChapter?: number; isIncremental: boolean }) =>
    api.post<Prop[]>(`/novels/${novelId}/parse-props/?sync=true${params.startChapter ? `&start_chapter=${params.startChapter}` : ''}${params.endChapter ? `&end_chapter=${params.endChapter}` : ''}&is_incremental=${params.isIncremental}`),

  /** 解析单章节道具 */
  parseChapterProps: (novelId: string, chapterId: string, isIncremental: boolean = true) =>
    api.post<Prop[]>(`/novels/${novelId}/chapters/${chapterId}/parse-props/?is_incremental=${isIncremental}`),

  /** 获取道具提示词 */
  fetchPrompt: (propId: string) =>
    api.get<{ prompt: string; templateName: string; templateId?: string; isSystem?: boolean }>(`/props/${propId}/prompt`),

  /** 生成道具外观 */
  generateAppearance: (propId: string) =>
    api.post<Prop>(`/props/${propId}/generate-appearance`),

  /** 生成道具图片任务 */
  generateImage: (propId: string) =>
    api.post(`/props/${propId}/generate-image`),

  /** 为未生成或失败的道具生成图片任务 */
  generateMissingImages: (novelId: string) =>
    api.post<{ queuedCount: number; failedCount: number; failedItems: Array<{ id: string; name: string; message: string }> }>(`/props/generate-missing-images?novel_id=${novelId}`),

  /** 上传道具图片 */
  uploadImage: async (propId: string, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.upload<Prop>(`/props/${propId}/upload-image`, formData);
  },

  /** 使用单图编辑工作流编辑道具图片 */
  editImage: (propId: string, prompt: string) =>
    api.post<{ imageUrl: string; taskId?: string }>(`/props/${propId}/edit-image`, { prompt }),

  /** 用编辑结果替换道具图片 */
  replaceImage: (propId: string, imageUrl: string) =>
    api.post<Prop>(`/props/${propId}/replace-image`, { imageUrl }),
};
