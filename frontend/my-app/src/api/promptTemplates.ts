/**
 * 提示词模板相关 API
 */
import { api, API_BASE } from './index';
import type { PromptTemplate } from '../types';

// 提示词模板类型
export type TemplateType =
  | 'style'
  | 'character_parse'
  | 'scene_parse'
  | 'prop_parse'
  | 'character'
  | 'scene'
  | 'prop'
  | 'chapter_split'
  | 'shot_image_prompt'
  | 'video_mode_recommender'
  | 'keyframe_description'
  | 'keyframe_planner'
  | 'keyframe_image_prompt'
  | 'keyframe_transition'
  | 'h3_single_frame_prompt'
  | 'h3_first_last_frame_prompt'
  | 'h3_multi_keyframe_prompt';

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

  /** 打包下载所有提示词模板 */
  downloadAll: async (): Promise<void> => {
    const response = await fetch(`${API_BASE}/prompt-templates/export-all`);
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || '下载失败');
    }

    const blob = await response.blob();
    const disposition = response.headers.get('Content-Disposition') || '';
    const encodedFilename = disposition.match(/filename\*=UTF-8''([^;]+)/)?.[1];
    const fallbackFilename = disposition.match(/filename="?([^";]+)"?/)?.[1];
    const filename = encodedFilename
      ? decodeURIComponent(encodedFilename)
      : fallbackFilename || 'prompt_templates.zip';

    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  },
};
