/**
 * 提示词模板相关 API
 */
import { api } from './index';
import type { PromptTemplate } from '../types';

// 提示词模板类型
export type TemplateType = 'style' | 'character_parse' | 'scene_parse' | 'character' | 'scene' | 'chapter_split';

export const promptTemplateApi = {
  /** 获取模板列表 */
  fetchList: (type: TemplateType) => 
    api.get<PromptTemplate[]>(`/prompt-templates/?type=${type}`),

  /** 创建模板 */
  create: (data: { name: string; description: string; template: string; type: TemplateType }) => 
    api.post<PromptTemplate>('/prompt-templates/', data),

  /** 更新模板 */
  update: (id: string, data: { name: string; description: string; template: string; type: TemplateType }) => 
    api.put<PromptTemplate>(`/prompt-templates/${id}/`, data),

  /** 删除模板 */
  delete: (id: string) => api.delete(`/prompt-templates/${id}/`),

  /** 复制模板 */
  copy: (id: string) => api.post<PromptTemplate>(`/prompt-templates/${id}/copy`),
};
