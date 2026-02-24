/**
 * 场景相关 API
 */

import { get, post, put, del } from './client';

export interface Scene {
  id: number;
  novel_id: number;
  name: string;
  setting: string;
  description: string;
  prompt?: string;
  image_url?: string;
  created_at: string;
  updated_at: string;
}

export const sceneApi = {
  /**
   * 获取场景列表
   */
  list: (novelId?: number) => get<Scene[]>('/scenes/', { novel_id: novelId }),
  
  /**
   * 获取场景详情
   */
  get: (id: number) => get<Scene>(`/scenes/${id}/`),
  
  /**
   * 创建场景
   */
  create: (data: Partial<Scene>) => post<Scene>('/scenes/', data),
  
  /**
   * 更新场景
   */
  update: (id: number, data: Partial<Scene>) => put<Scene>(`/scenes/${id}/`, data),
  
  /**
   * 删除场景
   */
  delete: (id: number) => del<void>(`/scenes/${id}/`),
  
  /**
   * 生成场景提示词
   */
  generatePrompt: (id: number) => get<{ prompt: string }>(`/scenes/${id}/prompt/`),
  
  /**
   * 生成场景图片
   */
  generateImage: (id: number) => post<void>(`/scenes/${id}/generate-image/`),
};

export default sceneApi;
