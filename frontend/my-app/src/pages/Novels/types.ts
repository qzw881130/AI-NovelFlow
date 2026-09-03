import type { Novel, PromptTemplate } from '../../types';

export interface NovelFormData {
  title: string;
  author: string;
  description: string;
  // 提示词模板关联（每种类型可选择不同模板）
  stylePromptTemplateId: string;
  characterParsePromptTemplateId: string;
  sceneParsePromptTemplateId: string;
  propParsePromptTemplateId: string;
  promptTemplateId: string;  // 角色生成模板
  scenePromptTemplateId: string;
  propPromptTemplateId: string;
  chapterSplitPromptTemplateId: string;
  keyframeDescriptionPromptTemplateId: string;
  shotImagePromptTemplateId: string;
  videoModeRecommenderPromptTemplateId: string;
  keyframePlannerPromptTemplateId: string;
  keyframeImagePromptTemplateId: string;
  keyframeTransitionPromptTemplateId: string;
  h3SingleFramePromptTemplateId: string;
  h3FirstLastFramePromptTemplateId: string;
  h3MultiKeyframePromptTemplateId: string;
  aspectRatio: string;
}

export interface ChapterRange {
  startChapter: number | null;
  endChapter: number | null;
  isIncremental: boolean;
}

export interface ConfirmDialogState {
  isOpen: boolean;
  novelId: string | null;
  type: 'characters' | 'scenes' | 'props';
}

export type ParseType = 'characters' | 'scenes' | 'props';
