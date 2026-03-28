/**
 * ChapterGenerate Store 类型定义
 */
import type { Chapter, Novel, Character, DialogueData, KeyframeData } from '../../../../types';
import type { Scene, Prop } from '../../types';
// 从 API 模块导入 Shot 类型，确保类型统一
import type { Shot as ApiShot } from '../../../../api/shots';

// 重新导出 Shot 类型
export type Shot = ApiShot;

// 分镜数据（从 parsed_data 中的 shots 数组）
export interface ShotDataFromParsed {
  id?: string;
  index?: number;
  description: string;
  video_description?: string;
  characters: string[];
  scene: string;
  props: string[];
  duration: number;
  dialogues?: DialogueData[];
  image_url?: string;
  image_path?: string;
  merged_character_image?: string;
  video_url?: string;
  keyframes?: KeyframeData[];
  reference_audio_url?: string;
  reference_audio_type?: string;
}

// 解析后的章节数据（从后端返回的 parsed_data）
// 注意：shots 数据存储在独立的 Shot 表中，通过 store.shots 访问
export interface ParsedData {
  chapter?: string;       // 章节标题
  characters?: string[];  // 角色名称列表
  scenes?: string[];      // 场景名称列表
  props?: string[];       // 道具名称列表
}

// 重新导出基础类型
export type { Character, Scene, Prop, DialogueData };

// 分镜状态
export type ShotStatus = 'pending' | 'generating' | 'completed' | 'failed';

// 音频任务
export interface AudioTask {
  shotId: string;
  characterName: string;
  taskId: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
}

// 音频警告
export interface AudioWarning {
  shot_index?: number;
  character_name: string;
  reason: string;
}

// 关键帧任务
export interface KeyframeTask {
  shotId: string;
  frameIndex: number;
  taskId: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
}

// 参考音频合并任务
export interface ReferenceAudioMergeTask {
  shotId: string;
  taskId: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
}

// 分镜工作流
export interface ShotWorkflow {
  id: string;
  name: string;
  isActive: boolean;
  nodeMapping?: {
    character_reference_image_node_id?: string;
    scene_reference_image_node_id?: string;
    prop_reference_image_node_id?: string;
    [key: string]: string | undefined;
  };
}

// 转场工作流
export interface TransitionWorkflow {
  id: string;
  name: string;
  isActive: boolean;
}

// ========== Slice States ==========

/**
 * 数据 Slice 状态
 */
export interface DataSliceState {
  // 章节数据
  chapter: Chapter | null;
  novel: Novel | null;
  parsedData: ParsedData | null;
  editableJson: string;
  loading: boolean;

  // 资源数据
  characters: Character[];          // 小说级角色列表
  scenes: Scene[];                  // 小说级场景列表
  props: Prop[];                    // 小说级道具列表

  // 章节级资源（本章节使用的资源子集）
  chapterCharacters: string[];      // 本章角色名称列表
  chapterScenes: string[];          // 本章场景名称列表
  chapterProps: string[];           // 本章道具名称列表

  // 分镜数据（从 Shot API 获取）
  shots: Shot[];
}

/**
 * 生成 Slice 状态
 */
export interface GenerationSliceState {
  // 图片生成
  generatingShots: Set<string>;
  pendingShots: Set<string>;
  shotImages: Record<string, string>;
  isGeneratingAll: boolean;
  uploadingShotId: string | null;

  // 视频生成
  generatingVideos: Set<string>;
  pendingVideos: Set<string>;
  shotVideos: Record<string, string>;

  // 转场生成
  transitionVideos: Record<string, string>;
  generatingTransitions: Set<string>;
  currentTransition: string;
  transitionWorkflows: TransitionWorkflow[];
  selectedTransitionWorkflow: string;
  transitionDuration: number;

  // 分镜工作流
  shotWorkflows: ShotWorkflow[];
  activeShotWorkflow: ShotWorkflow | null;

  // 音频生成
  generatingAudios: Set<string>;
  audioWarnings: AudioWarning[];
  audioTasks: AudioTask[];
  audioUrls: Record<string, string>;
  audioSources: Record<string, string>;
  uploadingAudios: Set<string>;

  // 关键帧生成
  generatingKeyframes: Set<string>;  // 格式: "shotId-frameIndex"
  keyframeTasks: KeyframeTask[];
  keyframeImageUrls: Record<string, string>;  // 格式: "shotId-frameIndex": url

  // 参考音频
  mergingReferenceAudios: Set<string>;  // 正在合并台词音频的分镜 ID
  uploadingReferenceAudios: Set<string>;  // 正在上传参考音频的分镜 ID
  referenceAudioMergeTasks: ReferenceAudioMergeTask[];  // 合并任务列表
}

/**
 * UI Slice 状态
 */
export interface UiSliceState {
  // 标签页
  activeTab: 'prepare' | 'resources' | 'shots' | 'compose';

  // 导航
  currentShot: number;
  currentVideo: number;

  // JSON 编辑器
  jsonEditMode: 'text' | 'table';
  editorKey: number;

  // 弹窗
  showFullTextModal: boolean;
  showMergedImageModal: boolean;
  showImagePreview: boolean;
  previewImageUrl: string | null;
  previewImageIndex: number;

  // 合并图片
  mergedImage: string | null;
  isMerging: boolean;

  // 确认对话框
  splitConfirmDialog: { isOpen: boolean; hasResources: boolean };

  // 转场配置
  showTransitionConfig: boolean;

  // 生成状态
  isGenerating: boolean;
  isSplitting: boolean;
  isSavingJson: boolean;
}

/**
 * Chapter Actions 状态
 */
export interface ChapterActionsState {
  // Chapter Actions 方法
  handleSplitChapter: (novelId: string, chapterId: string) => Promise<void>;
  handleSaveJson: (novelId: string, chapterId: string, json: string) => Promise<void>;
  clearChapterResources: (novelId: string, chapterId: string) => Promise<void>;
  splitChapter: (novelId: string, chapterId: string) => Promise<void>;
  // Navigation actions
  navigateToCharacter: (characterName: string) => void;
  navigateToScene: (sceneName: string) => void;
  navigateToProp: (propName: string) => void;
  // Resource regeneration
  handleRegenerateCharacter: (name: string) => void;
  handleRegenerateScene: (name: string) => void;
  handleRegenerateProp: (name: string) => void;
  // Download materials
  downloadChapterMaterials: (novelId: string, chapterId: string) => Promise<void>;
}

// ========== New Slice States (Layout Optimization) ==========

/**
 * Workflow Slice 状态 - 工作流状态管理
 */
export interface WorkflowSliceState {
  /** 当前 Tab 索引 (0-3) */
  currentTab: number;

  /** 各 Tab 的完成状态 */
  tabProgress: Record<number, boolean>;
}

/**
 * SidePanel Slice 状态 - 侧边栏状态管理
 */
export interface SidePanelSliceState {
  /** 左侧栏宽度 (200-400px) */
  leftPanelWidth: number;

  /** 右侧栏宽度 (200-350px) */
  rightPanelWidth: number;

  /** 左侧栏是否收起 */
  leftPanelCollapsed: boolean;

  /** 右侧栏是否收起 */
  rightPanelCollapsed: boolean;
}

/**
 * ShotNavigator Slice 状态 - 分镜导航状态管理
 */
export interface ShotNavigatorSliceState {
  /** 当前分镜 ID */
  currentShotId: string | null;

  /** 当前分镜索引 (从 1 开始) */
  currentShotIndex: number;

  /** 批量选择模式中选中的分镜 ID 列表 */
  selectedShotIds: string[];

  /** 批量模式开关状态 */
  bulkMode: boolean;
}

/**
 * 完整 Store 接口
 */
export interface ChapterGenerateStore
  extends DataSliceState,
    GenerationSliceState,
    UiSliceState,
    ChapterActionsState,
    WorkflowSliceState,
    SidePanelSliceState,
    ShotNavigatorSliceState {
  // ========== Data Actions ==========
  fetchNovel: (novelId: string) => Promise<void>;
  fetchChapter: (novelId: string, chapterId: string) => Promise<void>;
  fetchCharacters: (novelId: string) => Promise<void>;
  fetchScenes: (novelId: string) => Promise<void>;
  fetchProps: (novelId: string) => Promise<void>;
  fetchShots: (novelId: string, chapterId: string) => Promise<void>;
  fetchShotsWithReturn: (novelId: string, chapterId: string) => Promise<Shot[]>;
  setParsedData: (data: ParsedData | null) => void;
  setEditableJson: (json: string) => void;
  setShots: (shots: Shot[]) => void;
  updateShot: (shotId: string, data: Partial<Shot>) => Promise<void>;
  getCharacterImage: (name: string) => string | undefined;
  getSceneImage: (name: string) => string | null;
  getPropImage: (name: string) => string | null;

  // ========== Chapter Resource Actions ==========
  /** 从 parsedData 初始化章节级资源 */
  initChapterResources: () => void;
  /** 添加资源到章节 */
  addResourceToChapter: (type: 'character' | 'scene' | 'prop', name: string) => void;
  /** 从章节移除资源 */
  removeResourceFromChapter: (type: 'character' | 'scene' | 'prop', name: string) => void;
  /** 保存章节资源到 parsedData */
  saveChapterResources: (novelId: string, chapterId: string) => Promise<void>;

  // ========== Image Generation Actions ==========
  generateShotImage: (novelId: string, chapterId: string, shotId: string) => Promise<void>;
  generateAllImages: (novelId: string, chapterId: string) => Promise<void>;
  uploadShotImage: (novelId: string, chapterId: string, shotId: string, file: File) => Promise<void>;
  setShotImages: (images: Record<string, string> | ((prev: Record<string, string>) => Record<string, string>)) => void;

  // ========== Video Generation Actions ==========
  generateShotVideo: (novelId: string, chapterId: string, shotId: string) => Promise<void>;
  generateAllVideos: (novelId: string, chapterId: string) => Promise<void>;
  setShotVideos: (videos: Record<string, string> | ((prev: Record<string, string>) => Record<string, string>)) => void;

  // ========== Transition Actions ==========
  generateTransition: (novelId: string, chapterId: string, fromIndex: number, toIndex: number, useCustomConfig?: boolean) => Promise<void>;
  generateAllTransitions: (novelId: string, chapterId: string) => Promise<void>;
  fetchTransitionWorkflows: () => Promise<void>;
  setSelectedTransitionWorkflow: (workflowId: string) => void;
  setTransitionDuration: (duration: number) => void;

  // ========== Audio Actions ==========
  generateShotAudio: (novelId: string, chapterId: string, shotId: string, dialogues: DialogueData[]) => Promise<void>;
  generateAllAudio: (novelId: string, chapterId: string) => Promise<void>;
  regenerateAudio: (novelId: string, chapterId: string, shotId: string, characterName: string, dialogue: DialogueData) => Promise<void>;
  uploadDialogueAudio: (novelId: string, chapterId: string, shotId: string, characterName: string, file: File) => Promise<void>;
  deleteDialogueAudio: (novelId: string, chapterId: string, shotId: string, characterName: string) => Promise<void>;
  getAudioUrl: (shotId: string, characterName: string) => string | undefined;
  getAudioSource: (shotId: string, characterName: string) => string | undefined;
  isShotAudioGenerating: (shotId: string) => boolean;
  isAudioUploading: (shotId: string, characterName: string) => boolean;
  getShotAudioTasks: (shotId: string) => AudioTask[];
  initAudioFromShots: (shots: Shot[]) => void;

  // ========== Keyframe Actions ==========
  generateKeyframeDescriptions: (novelId: string, chapterId: string, shotId: string, count?: number) => Promise<void>;
  generateKeyframeImage: (novelId: string, chapterId: string, shotId: string, frameIndex: number, workflowId?: string) => Promise<void>;
  uploadKeyframeImage: (novelId: string, chapterId: string, shotId: string, frameIndex: number, file: File) => Promise<void>;
  uploadKeyframeReferenceImage: (novelId: string, chapterId: string, shotId: string, frameIndex: number, file: File) => Promise<void>;
  setKeyframeReferenceImage: (novelId: string, chapterId: string, shotId: string, frameIndex: number, mode: 'auto_select' | 'custom' | 'none', referenceUrl?: string) => Promise<void>;
  isKeyframeGenerating: (shotId: string, frameIndex: number) => boolean;
  getKeyframeImageUrl: (shotId: string, frameIndex: number) => string | undefined;
  getKeyframeTask: (shotId: string, frameIndex: number) => KeyframeTask | undefined;

  // ========== Reference Audio Actions ==========
  mergeDialogueAudio: (novelId: string, chapterId: string, shotId: string) => Promise<void>;
  uploadReferenceAudio: (novelId: string, chapterId: string, shotId: string, file: File) => Promise<void>;
  setReferenceAudio: (novelId: string, chapterId: string, shotId: string, mode: 'none' | 'merged' | 'uploaded' | 'character', characterName?: string) => Promise<void>;
  getReferenceAudioUrl: (shotId: string) => string | undefined;
  inferReferenceAudioSourceType: (shotId: string) => 'none' | 'merged' | 'uploaded' | 'character';
  isReferenceAudioMerging: (shotId: string) => boolean;
  isReferenceAudioUploading: (shotId: string) => boolean;

  // ========== Task Polling Actions ==========
  checkShotTaskStatus: (chapterId: string) => Promise<void>;
  checkVideoTaskStatus: (chapterId: string) => Promise<void>;
  checkTransitionTaskStatus: (chapterId: string) => Promise<void>;
  checkAudioTaskStatus: (chapterId: string) => Promise<void>;
  checkKeyframeTaskStatus: (chapterId: string) => Promise<void>;
  fetchActiveTasks: (chapterId: string) => Promise<void>;

  // ========== UI Actions ==========
  setActiveTab: (tab: UiSliceState['activeTab']) => void;
  setCurrentShot: (shotId: string, index: number) => void;
  setCurrentVideo: (index: number) => void;
  setJsonEditMode: (mode: UiSliceState['jsonEditMode']) => void;
  resetEditorKey: () => void;
  setShowFullTextModal: (show: boolean) => void;
  setShowMergedImageModal: (show: boolean) => void;
  setShowImagePreview: (show: boolean, url?: string | null, index?: number) => void;
  setMergedImage: (image: string | null) => void;
  setIsMerging: (merging: boolean) => void;
  setSplitConfirmDialog: (dialog: UiSliceState['splitConfirmDialog']) => void;
  setShowTransitionConfig: (show: boolean) => void;
  setIsGenerating: (generating: boolean) => void;
  setIsSplitting: (splitting: boolean) => void;
  setIsSavingJson: (saving: boolean) => void;

  // ========== Chapter Actions ==========
  handleSplitChapter: (novelId: string, chapterId: string) => Promise<void>;
  handleSaveJson: (novelId: string, chapterId: string, json: string) => Promise<void>;
  clearChapterResources: (novelId: string, chapterId: string) => Promise<void>;
  handleRegenerateCharacter: (name: string) => void;
  handleRegenerateScene: (name: string) => void;
  handleRegenerateProp: (name: string) => void;

  // ========== Workflow Actions ==========
  setCurrentTab: (index: number) => void;
  markTabComplete: (tabIndex: number) => void;
  resetTabProgress: () => void;
  saveWorkflowState: () => void;

  // ========== SidePanel Actions ==========
  setLeftPanelWidth: (width: number) => void;
  setRightPanelWidth: (width: number) => void;
  toggleLeftPanel: () => void;
  toggleRightPanel: () => void;
  setLeftPanelCollapsed: (collapsed: boolean) => void;
  setRightPanelCollapsed: (collapsed: boolean) => void;
  saveSidePanelState: () => void;

  // ========== ShotNavigator Actions ==========
  setCurrentShotIndex: (index: number) => void;
  previousShot: (totalShots: number) => void;
  nextShot: (totalShots: number) => void;
  toggleShotSelection: (shotId: string) => void;
  selectAll: (shotIds: string[]) => void;
  clearSelection: () => void;
  toggleBulkMode: () => void;
  setBulkMode: (mode: boolean) => void;
}