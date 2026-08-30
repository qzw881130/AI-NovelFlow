/**
 * 角色相关 API
 */
import { api, API_BASE } from './index';
import type { Character } from '../types';

export const characterApi = {
  /** 获取角色列表 */
  fetchList: async (novelId: string) => {
    const res = await fetch(`${API_BASE}/characters?novel_id=${novelId}`, { cache: 'no-store' });
    return res.json() as Promise<{ success: boolean; data?: Character[]; message?: string }>;
  },

  /** 获取单个角色 */
  fetch: async (id: string) => {
    const res = await fetch(`${API_BASE}/characters/${id}`, { cache: 'no-store' });
    return res.json() as Promise<{ success: boolean; data?: Character; message?: string }>;
  },

  /** 创建角色 */
  create: (data: Partial<Character>) => api.post<Character>('/characters/', data),

  /** 更新角色 */
  update: (id: string, data: Partial<Character>) => api.put<Character>(`/characters/${id}/`, data),

  /** 删除角色 */
  delete: (id: string) => api.delete(`/characters/${id}/`),

  /** 删除小说下所有角色 */
  deleteAll: (novelId: string) => api.delete(`/characters/?novel_id=${novelId}`),

  /** 获取角色提示词 */
  fetchPrompt: (characterId: string) => 
    api.get<{ prompt: string; templateName: string; templateId?: string; isSystem?: boolean }>(`/characters/${characterId}/prompt/`),

  /** 生成外貌描述 */
  generateAppearance: (characterId: string) => 
    api.post<Character>(`/characters/${characterId}/generate-appearance/`),

  /** 生成人设图任务 */
  generatePortrait: (characterId: string) => 
    api.post(`/characters/${characterId}/generate-portrait/`),

  /** 为未生成或失败的角色生成人设图任务 */
  generateMissingPortraits: (novelId: string) =>
    api.post<{
      queuedCount: number;
      failedCount: number;
      failedItems: Array<{ id: string; name: string; message: string }>;
    }>(`/characters/generate-missing-portraits?novel_id=${novelId}`),

  /** 上传角色图片 */
  uploadImage: async (characterId: string, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.upload<Character>(`/characters/${characterId}/upload-image`, formData);
  },

  /** 使用单图编辑工作流编辑角色图片 */
  editImage: (characterId: string, prompt: string) =>
    api.post<{ imageUrl: string }>(`/characters/${characterId}/edit-image`, { prompt }),

  /** 用编辑结果替换角色图片 */
  replaceImage: (characterId: string, imageUrl: string) =>
    api.post<Character>(`/characters/${characterId}/replace-image`, { imageUrl }),

  /** 清空角色图片目录 */
  clearImagesDir: (novelId: string) =>
    api.post(`/characters/clear-characters-dir?novel_id=${novelId}`),

  /** 生成角色音色任务 */
  generateVoice: (characterId: string) =>
    api.post(`/characters/${characterId}/generate-voice`),

  /** 获取音色生成状态 */
  getVoiceStatus: (characterId: string) =>
    api.get<{
      status: 'idle' | 'pending' | 'running' | 'completed' | 'failed';
      taskId?: string;
      progress: number;
      message: string;
      referenceAudioUrl?: string;
    }>(`/characters/${characterId}/voice/status`),

  /** 上传角色音频 */
  uploadAudio: async (characterId: string, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.upload<Character>(`/characters/${characterId}/upload-audio`, formData);
  },
};
