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

// JSON 表格编辑器组件接口
export interface JsonTableEditorProps {
  value: string;
  onChange: (value: string) => void;
  availableScenes?: string[]; // 场景库中的场景名列表
  availableCharacters?: string[]; // 角色库中的角色名列表
  availableProps?: string[]; // 道具库中的道具名列表
  activeShotWorkflow?: any; // 当前激活的分镜工作流
  // 音频相关
  audioUrls?: Record<string, string>; // 音频 URL，key: "shotIndex_characterName"
  audioSources?: Record<string, string>; // 音频来源，key: "shotIndex_characterName"
  isShotAudioGenerating?: (shotIndex: number) => boolean;
  getShotAudioTasks?: (shotIndex: number) => Array<{ characterName: string; status: string; taskId: string }>;
  onRegenerateAudio?: (shotIndex: number, characterName: string, dialogue: DialogueData) => void;
  onGenerateDialogueAudio?: (shotIndex: number, dialogue: DialogueData) => void; // 单个角色台词生成音频
  // 音频上传相关
  onUploadDialogueAudio?: (shotIndex: number, characterName: string, file: File) => void;
  onDeleteDialogueAudio?: (shotIndex: number, characterName: string) => void;
  isAudioUploading?: (shotIndex: number, characterName: string) => boolean;
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
