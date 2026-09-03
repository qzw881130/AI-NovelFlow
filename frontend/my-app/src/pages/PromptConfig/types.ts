import type { PromptTemplate } from '../../types';

// 提示词模板类型（与后端保持一致）
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

export type TemplateCategory =
  | 'style_design'
  | 'asset_parse'
  | 'asset_generation'
  | 'shot_planning'
  | 'shot_image'
  | 'video_director'
  | 'keyframe_image'
  | 'video_generation';

export interface PromptForm {
  name: string;
  description: string;
  template: string;
  wordCount: number;
}
