/**
 * 角色相关 API
 */

import { get, post, put, del, ApiResponse } from './client';

export interface Character {
  id: number;
  novel_id: number;
  name: string;
  appearance: string;
  description: string;
  prompt?: string;
  image_url?: string;
  created_at: string;
  updated_at: string;
}

export const characterApi = {
  /**
   * 获取角色列表
   */
  list: (novelId?: number) => get<Character[]>('/characters/', { novel_id: novelId }),
  
  /**
   * 获取角色详情
   */
  get: (id: number) => get<Character>(`/characters/${id}/`),
  
  /**
   * 创建角色
   */
  create: (data: Partial<Character>) => post<Character>('/characters/', data),
  
  /**
   * 更新角色
   */
  update: (id: number, data: Partial<Character>) => put<Character>(`/characters/${id}/`, data),
  
  /**
   * 删除角色
   */
  delete: (id: number) => del<void>(`/characters/${id}/`),
  
  /**
   * 生成角色提示词
   */
  generatePrompt: (id: number) => get<{ prompt: string }>(`/characters/${id}/prompt/`),
  
  /**
   * 生成角色图片
   */
  generateImage: (id: number) => post<void>(`/characters/${id}/generate-image/`),
};

export default characterApi;
