// 从上级类型文件导入并重新导出基础类型
import type { Chapter, Novel, Character, Scene, Prop, ParsedData, ShotData, DialogueData } from '../../types';
export type { Chapter, Novel, Character, Scene, Prop, ParsedData, ShotData, DialogueData };

// 转场视频项组件接口
export interface TransitionVideoItemProps {
  fromIndex: number;
  toIndex: number;
  fromVideo?: string;
  toVideo?: string;
  fromImage?: string;
  toImage?: string;
  transitionVideo?: string;
  isGenerating: boolean;
  onGenerate: () => void;
  onRegenerate?: () => void;
  onClick: () => void;
  isActive: boolean;
}

// 下载素材卡片组件接口
export interface DownloadMaterialsCardProps {
  novelId: string;
  chapterId: string;
  chapterTitle: string;
}

// 合并视频卡片组件接口
export interface MergeVideosCardProps {
  novelId: string;
  chapterId: string;
  shotVideos: Record<number, string>;
  transitionVideos: Record<string, string>;
  chapter: Chapter | null;
  aspectRatio?: string;
}

// 章节数据状态
export interface ChapterDataState {
  chapter: Chapter | null;
  novel: Novel | null;
  parsedData: ParsedData | null;
  editableJson: string;
  characters: Character[];
  scenes: Scene[];
  props: Prop[];
  loading: boolean;
}

// 分镜生成状态
export interface ShotGenerationState {
  generatingShots: Set<number>;
  pendingShots: Set<number>;
  shotImages: Record<number, string>;
  isGeneratingAll: boolean;
  uploadingShotIndex: number | null;
}

// 视频生成状态
export interface VideoGenerationState {
  generatingVideos: Set<number>;
  pendingVideos: Set<number>;
  shotVideos: Record<number, string>;
}

// 转场生成状态
export interface TransitionGenerationState {
  transitionVideos: Record<string, string>;
  generatingTransitions: Set<string>;
  currentTransition: string;
  transitionWorkflows: any[];
  selectedTransitionWorkflow: string;
  transitionDuration: number;
  showTransitionConfig: boolean;
}

// Shot 工作流状态
export interface ShotWorkflowState {
  shotWorkflows: any[];
  activeShotWorkflow: any | null;
}

// UI 状态
export interface UIState {
  activeTab: 'json' | 'characters' | 'scenes' | 'script';
  currentShot: number;
  currentVideo: number;
  jsonEditMode: 'text' | 'table';
  showFullTextModal: boolean;
  showMergedImageModal: boolean;
  showImagePreview: boolean;
  previewImageUrl: string | null;
  previewImageIndex: number;
  mergedImage: string | null;
  isMerging: boolean;
  editorKey: number;
  splitConfirmDialog: { isOpen: boolean; hasResources: boolean };
}

// 生成状态
export interface GenerationState {
  isGenerating: boolean;
  isSplitting: boolean;
  isSavingJson: boolean;
}

// 工作流类型（从 Store 类型文件重新导出）
export type { ShotWorkflow, TransitionWorkflow } from './stores/slices/types';
