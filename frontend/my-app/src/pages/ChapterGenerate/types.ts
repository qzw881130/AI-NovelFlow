// 从上级类型文件导入并重新导出
import type { Chapter as ChapterType, Novel as NovelType } from '../../types';
export type { ChapterType as Chapter, NovelType as Novel };

// 重新声明类型供本地使用
type Chapter = ChapterType;
type Novel = NovelType;

// 角色数据类型
export interface Character {
  id: string;
  name: string;
  imageUrl: string | null;
  novelId: string;
}

// 场景数据类型
export interface Scene {
  id: string;
  novelId: string;
  name: string;
  description: string;
  setting: string;
  imageUrl?: string;
  generatingStatus?: string;
  sceneTaskId?: string;
}

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

// JSON表格编辑器组件接口
export interface JsonTableEditorProps {
  value: string;
  onChange: (value: string) => void;
  availableScenes?: string[]; // 场景库中的场景名列表
  availableCharacters?: string[]; // 角色库中的角色名列表
  activeShotWorkflow?: any; // 当前激活的分镜工作流
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

// 分镜数据类型
export interface ShotData {
  id: number;
  description: string;
  video_description?: string;
  characters: string[];
  scene: string;
  duration: number;
  image_url?: string;
  image_path?: string;
  merged_character_image?: string;
}

// 解析后的章节数据类型
export interface ParsedData {
  characters?: string[];
  scenes?: string[];
  shots?: ShotData[];
}

// 章节数据状态
export interface ChapterDataState {
  chapter: Chapter | null;
  novel: Novel | null;
  parsedData: ParsedData | null;
  editableJson: string;
  characters: Character[];
  scenes: Scene[];
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
