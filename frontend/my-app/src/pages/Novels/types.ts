import type { Novel, PromptTemplate } from '../../types';

export interface NovelFormData {
  title: string;
  author: string;
  description: string;
  // 提示词模板关联（每种类型可选择不同模板）
  stylePromptTemplateId: string;
  characterParsePromptTemplateId: string;
  sceneParsePromptTemplateId: string;
  promptTemplateId: string;  // 角色生成模板
  scenePromptTemplateId: string;
  chapterSplitPromptTemplateId: string;
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
  type: 'characters' | 'scenes';
}

export type ParseType = 'characters' | 'scenes';
