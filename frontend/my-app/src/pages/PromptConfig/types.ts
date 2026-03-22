import type { PromptTemplate } from '../../types';

// 提示词模板类型（与后端保持一致）
export type TemplateType = 'style' | 'character_parse' | 'scene_parse' | 'prop_parse' | 'character' | 'scene' | 'prop' | 'chapter_split' | 'keyframe_description';

export interface PromptForm {
  name: string;
  description: string;
  template: string;
  wordCount: number;
}
