/**
 * ChapterGenerate Store 类型定义
 */
import type { Chapter, Novel, Character, DialogueData } from '../../../../types';
import type { Scene, Prop } from '../../types';

// 分镜数据（从 parsed_data 中的 shots 数组）
export interface ShotDataFromParsed {
  id?: number | string;
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
}

// 解析后的章节数据（从后端返回的 parsed_data）
export interface ParsedData {
  characters?: string[];  // 角色名称列表
  scenes?: string[];      // 场景名称列表
  props?: string[];       // 道具名称列表
  shots?: ShotDataFromParsed[];  // 分镜数据列表
}

// 重新导出基础类型
export type { Character, Scene, Prop, DialogueData };

// 分镜状态
export type ShotStatus = 'pending' | 'generating' | 'completed' | 'failed';

// 分镜数据
export interface Shot {
  id: string;
  chapterId: string;
  index: number;
  description: string;
  characters: string[];
  scene: string;
  props: string[];
  duration: number;
  imageUrl: string | null;
  imagePath: string | null;
  imageStatus: ShotStatus;
  imageTaskId: string | null;
  videoUrl: string | null;
  videoStatus: ShotStatus;
  videoTaskId: string | null;
  mergedCharacterImage: string | null;
  dialogues: DialogueData[];
  createdAt: string | null;
  updatedAt: string | null;
}

// 音频任务
export interface AudioTask {
  shotIndex: number;
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
  generatingShots: Set<number>;
  pendingShots: Set<number>;
  shotImages: Record<number, string>;
  isGeneratingAll: boolean;
  uploadingShotIndex: number | null;

  // 视频生成
  generatingVideos: Set<number>;
  pendingVideos: Set<number>;
  shotVideos: Record<number, string>;

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
  handleMergeCharacterImages: () => Promise<void>;
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
  generateShotImage: (novelId: string, chapterId: string, shotIndex: number) => Promise<void>;
  generateAllImages: (novelId: string, chapterId: string) => Promise<void>;
  uploadShotImage: (novelId: string, chapterId: string, shotIndex: number, file: File) => Promise<void>;
  setShotImages: (images: Record<number, string> | ((prev: Record<number, string>) => Record<number, string>)) => void;

  // ========== Video Generation Actions ==========
  generateShotVideo: (novelId: string, chapterId: string, shotIndex: number) => Promise<void>;
  generateAllVideos: (novelId: string, chapterId: string) => Promise<void>;
  setShotVideos: (videos: Record<number, string> | ((prev: Record<number, string>) => Record<number, string>)) => void;

  // ========== Transition Actions ==========
  generateTransition: (novelId: string, chapterId: string, fromIndex: number, toIndex: number, useCustomConfig?: boolean) => Promise<void>;
  generateAllTransitions: (novelId: string, chapterId: string) => Promise<void>;
  fetchTransitionWorkflows: () => Promise<void>;
  setSelectedTransitionWorkflow: (workflowId: string) => void;
  setTransitionDuration: (duration: number) => void;

  // ========== Audio Actions ==========
  generateShotAudio: (novelId: string, chapterId: string, shotIndex: number, dialogues: DialogueData[]) => Promise<void>;
  generateAllAudio: (novelId: string, chapterId: string) => Promise<void>;
  regenerateAudio: (novelId: string, chapterId: string, shotIndex: number, characterName: string, dialogue: DialogueData) => Promise<void>;
  uploadDialogueAudio: (novelId: string, chapterId: string, shotIndex: number, characterName: string, file: File) => Promise<void>;
  deleteDialogueAudio: (novelId: string, chapterId: string, shotIndex: number, characterName: string) => Promise<void>;
  getAudioUrl: (shotIndex: number, characterName: string) => string | undefined;
  getAudioSource: (shotIndex: number, characterName: string) => string | undefined;
  isShotAudioGenerating: (shotIndex: number) => boolean;
  isAudioUploading: (shotIndex: number, characterName: string) => boolean;
  getShotAudioTasks: (shotIndex: number) => AudioTask[];
  initAudioFromShots: (shots: Shot[]) => void;

  // ========== Task Polling Actions ==========
  checkShotTaskStatus: (chapterId: string) => Promise<void>;
  checkVideoTaskStatus: (chapterId: string) => Promise<void>;
  checkTransitionTaskStatus: (chapterId: string) => Promise<void>;
  checkAudioTaskStatus: (chapterId: string) => Promise<void>;
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
  handleMergeCharacterImages: () => Promise<void>;
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