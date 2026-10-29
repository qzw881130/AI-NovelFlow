import type { NovelTemplateFieldKey } from './promptTemplateFields';
import type { NovelVideoMode } from './components/NovelVideoModeSelector';

export type NovelFormData = Record<NovelTemplateFieldKey, string> & {
  title: string;
  author: string;
  description: string;
  aspectRatio: string;
  videoMode: NovelVideoMode;
};

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
