import type { PromptTemplate } from '../../types';

// 提示词模板类型（与后端保持一致）
export type TemplateType =
  | 'story_world_context_recommender'
  | 'style'
  | 'character_parse'
  | 'scene_parse'
  | 'prop_parse'
  | 'character'
  | 'scene'
  | 'prop'
  | 'scene_setting'
  | 'prop_appearance'
  | 'chapter_split'
  | 'shot_image_prompt'
  | 'keyframe_description'
  | 'keyframe_planner'
  | 'keyframe_image_prompt'
  | 'image_quality_review_prompt'
  | 'grid_panel_review_prompt'
  | 'temporal_reference_selector'
  | 'keyframe_transition'
  | 'clip_execution_planner'
  | 'h3_multi_keyframe_director_phase_b'
  | 'grid_shot_plan'
  | 'grid_image_prompt'
  | 'grid_clip_plan'
  | 'grid_h3_phase_b'
  | 'background_music_director'
  | 'background_music_director_full'
  | 'background_music_generation'
  | 'subtitle_correction'
  | 'subtitle_translation';

export type TemplateCategory =
  | 'story_context'
  | 'style_design'
  | 'asset_parse'
  | 'asset_generation'
  | 'shot_planning'
  | 'shot_image'
  | 'video_director'
  | 'keyframe_image'
  | 'video_generation'
  | 'background_music'
  | 'video_subtitles';

export interface PromptForm {
  name: string;
  description: string;
  template: string;
  wordCount: number;
}
