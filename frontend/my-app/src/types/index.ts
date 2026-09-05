// 支持的 LLM 厂商
export type LLMProvider = 'deepseek' | 'openai' | 'gemini' | 'anthropic' | 'azure' | 'aliyun-bailian' | 'ollama' | 'custom';
export type SystemStatusSource = 'comfyui' | 'windows_gpu_monitor';

// LLM 模型配置
export interface LLMModelConfig {
  provider: LLMProvider;
  model: string;
  apiKey: string;
  apiUrl: string;
}

// 代理配置
export interface ProxyConfig {
  enabled: boolean;
  httpProxy: string;
  httpsProxy: string;
}

export interface SystemConfig {
  // LLM 配置（多厂商支持）
  llmProvider: LLMProvider;
  llmModel: string;
  llmApiKey: string;
  llmApiUrl: string;
  llmMaxTokens?: number;  // 最大token数
  llmTemperature?: string;  // 温度参数
  llmTimeout?: number;  // 请求超时（秒）
  
  // 代理配置
  proxy: ProxyConfig;
  
  // 兼容旧配置（保留，但不再使用）
  deepseekApiKey?: string;
  deepseekApiUrl?: string;
  
  // ComfyUI 配置
  comfyUIHost: string;
  comfyUITimeout: number;
  systemStatusSource: SystemStatusSource;
  
  // 输出配置（已废弃，保留兼容）
  outputResolution?: string;
  outputFrameRate?: number;
}

// LLM 厂商预设配置
export interface LLMProviderPreset {
  id: LLMProvider;
  name: string;
  defaultApiUrl: string;
  models: LLMModel[];
  apiKeyPlaceholder: string;
  apiKeyHelp?: string;
}

// LLM 模型
export interface LLMModel {
  id: string;
  name: string;
  description?: string;
  maxTokens?: number;
}

export interface Novel {
  id: string;
  title: string;
  author: string;
  description: string;
  cover?: string;
  chapterCount: number;
  status: 'pending' | 'processing' | 'completed';
  // 提示词模板关联（每种类型可选择不同模板）
  stylePromptTemplateId?: string;  // 风格提示词模板
  characterParsePromptTemplateId?: string;  // 角色解析提示词模板
  sceneParsePromptTemplateId?: string;  // 场景解析提示词模板
  propParsePromptTemplateId?: string;  // 道具解析提示词模板
  promptTemplateId?: string;  // 角色生成提示词模板
  scenePromptTemplateId?: string;  // 场景生成提示词模板
  propPromptTemplateId?: string;  // 道具生成提示词模板
  chapterSplitPromptTemplateId?: string;  // 分镜拆分提示词模板
  keyframeDescriptionPromptTemplateId?: string;  // 关键帧描述提示词模板
  shotImagePromptTemplateId?: string;  // 主分镜图提示词模板
  videoModeRecommenderPromptTemplateId?: string;  // 视频模式推荐提示词模板
  keyframePlannerPromptTemplateId?: string;  // 关键帧规划提示词模板
  keyframeImagePromptTemplateId?: string;  // 关键帧生图提示词模板
  keyframeTransitionPromptTemplateId?: string;  // 关键帧过渡规划提示词模板
  h3SingleFramePromptTemplateId?: string;  // H3 单帧视频提示词模板
  h3FirstLastFramePromptTemplateId?: string;  // H3 首尾帧视频提示词模板
  h3MultiKeyframePromptTemplateId?: string;  // H3 多关键帧视频提示词模板
  aspectRatio?: string;  // 画面比例: 16:9, 9:16, 4:3, 3:4, 1:1
  createdAt: string;
  updatedAt: string;
}

export interface Chapter {
  id: string;
  novelId: string;
  number: number;
  title: string;
  content?: string;
  contentLength?: number;
  status: 'pending' | 'parsing' | 'generating_characters' | 'generating_shots' | 'generating_videos' | 'compositing' | 'completed' | 'failed';
  progress: number;
  parsedData?: ParsedData;
  characterImages?: string[];
  shotImages?: string[];
  shotVideos?: string[];
  transitionVideos?: Record<string, string>;  // {"1-2": url, "2-3": url}
  finalVideo?: string;
  chapterVideoUrl?: string;
  chapterVideoDuration?: number | null;
  chapterVideoSize?: number | null;
  chapterVideoShotCount?: number | null;
  chapterVideoTaskId?: string;
  chapterVideoCompletedAt?: string | null;
}

export interface ParsedData {
  characters?: string[];  // 章节角色名称列表
  scenes?: string[];      // 章节场景名称列表
  props?: string[];       // 章节道具名称列表
  shots?: ShotData[];     // 分镜数据列表
}

export interface ShotData {
  id?: number | string;
  description: string;
  video_description?: string;
  characters: string[];
  scene: string;
  props: string[];
  duration: number;
  videoDirectorPlan?: VideoDirectorPlan;
  videoDirectorPlanRevision?: number;
  dialogues?: DialogueData[];
  image_url?: string;
  image_path?: string;
  merged_character_image?: string;
  video_url?: string;
  keyframes?: KeyframeData[];
  reference_audio_url?: string;
  reference_audio_type?: 'none' | 'merged' | 'uploaded' | 'character';
}

export type VideoMode = 'SINGLE_FRAME' | 'FIRST_LAST_FRAME' | 'MULTI_KEYFRAME';

export interface VideoDirectorPlan {
  selected_mode?: VideoMode;
  recommended_mode?: VideoMode;
  recommended_label?: string;
  recommendation_reason?: string;
  first_last_available?: boolean;
  notice?: string;
  workflow_capability?: Record<string, any>;
  keyframes?: any[];
  transitions?: any[];
  clips?: any[];
  execution_windows?: any[];
  window_plans?: any[];
  ai_calls?: any[];
  validation?: Record<string, any>;
}

export interface DialogueData {
  type?: 'character' | 'narration';
  order?: number;
  character_name: string;
  text: string;
  emotion_prompt?: string;
  audio_url?: string;
  audio_task_id?: string;
  audio_source?: 'ai_generated' | 'uploaded';
}

export interface KeyframeData {
  frame_index: number;
  description: string;
  image_url?: string;
  image_task_id?: string;
  reference_image_url?: string | null;
  reference_mode?: 'auto_select' | 'custom' | 'none';
}

export interface Character {
  id: string;
  name: string;
  description: string;
  appearance: string;
  voicePrompt?: string;
  referenceAudioUrl?: string;
  voiceTaskId?: string | null;
  voiceTaskStatus?: 'idle' | 'pending' | 'running' | 'completed' | 'failed';
  voiceTaskProgress?: number;
  voiceTaskMessage?: string;
  imageUrl?: string;
  generatingStatus?: 'pending' | 'running' | 'completed' | 'failed';
  portraitTaskId?: string;
  novelId: string;
  novelName?: string;
  isNarrator?: boolean;
  updatedAt?: string;
}

export interface Scene {
  id: string;
  novelId: string;
  name: string;
  description: string;
  setting: string;
  imageUrl?: string;
  generatingStatus?: string;
  sceneTaskId?: string;
  novelName?: string;
  startChapter?: number;
  endChapter?: number;
  isIncremental?: boolean;
  sourceRange?: string;
  lastParsedAt?: string;
  createdAt?: string;
  updatedAt?: string;
}

export interface Prop {
  id: string;
  novelId: string;
  name: string;
  description: string;
  appearance: string;
  imageUrl?: string;
  generatingStatus?: 'pending' | 'running' | 'completed' | 'failed';
  propTaskId?: string;
  novelName?: string;
  startChapter?: number;
  endChapter?: number;
  isIncremental?: boolean;
  sourceRange?: string;
  lastParsedAt?: string;
  createdAt?: string;
  updatedAt?: string;
}

export interface Shot {
  id: string;
  sceneId: string;
  description: string;
  cameraAngle?: string;
  imageUrl?: string;
  videoUrl?: string;
}

export interface VideoDirectorTaskClip {
  windowIndex?: number;
  status?: string;
  startTime?: number;
  endTime?: number;
  workflowType?: string;
  workflowName?: string;
  promptId?: string;
  promptText?: string;
  hasWorkflowJson?: boolean;
  referenceImages?: Array<{ label?: string; url: string }>;
  videoUrl?: string;
  sourceVideoUrl?: string;
  audioStatus?: string;
  audioMessage?: string;
  driveAudioUrl?: string;
  finalAudioUrl?: string;
  clipAudioDuration?: number;
  errorMessage?: string;
  generatedAt?: string;
  dialogueCount?: number | null;
}

export interface Task {
  id: string;
  type: 'character_portrait' | 'character_voice' | 'audio_event_tts' | 'audio_prepare' | 'character_audio' | 'narrator_audio' | 'scene_image' | 'shot_image' | 'shot_image_batch' | 'keyframe_image' | 'single_image_edit' | 'shot_video' | 'shot_video_batch' | 'chapter_video' | 'transition_video' | 'prop_image';
  name: string;
  description?: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  progress: number;
  currentStep?: string;
  resultUrl?: string;
  errorMessage?: string;
  workflowId?: string;
  workflowName?: string;
  workflowIsSystem?: boolean;
  hasWorkflowJson?: boolean;
  hasPromptText?: boolean;
  referenceImages?: Array<{ label?: string; url: string }>;
  videoDirectorClips?: VideoDirectorTaskClip[];
  novelId?: string;
  novelName?: string;
  chapterId?: string;
  characterId?: string;
  shotId?: string;
  createdAt: string;
  startedAt?: string;
  completedAt?: string;
}

export interface ApiResponse<T> {
  success: boolean;
  data?: T;
  message?: string;
}

// 提示词模板
export interface PromptTemplate {
  id: string;
  name: string;
  nameKey?: string;
  description: string;
  descriptionKey?: string;
  template: string;
  type: string;
  isSystem: boolean;
  isActive: boolean;
  createdAt: string;
}

export interface TestCase {
  id: string;
  name: string;
  nameKey?: string;
  description?: string;
  descriptionKey?: string;
  type: 'full' | 'character' | 'shot' | 'video';
  isActive: boolean;
  isPreset: boolean;
  novelId: string;
  novelTitle: string;
  chapterCount: number;
  characterCount: number;
  expectedCharacterCount?: number;
  expectedShotCount?: number;
  notes?: string;
  notesKey?: string;
  createdAt: string;
}

// LLM 日志接口
export interface LLMLog {
  id: string;
  created_at: string;
  provider: string;
  model: string;
  prompt_template_name: string | null;
  system_prompt: string | null;
  user_prompt: string;
  request_info?: string | null;
  response: string | null;
  status: 'pending' | 'success' | 'error';
  error_message: string | null;
  task_type: string | null;
  novel_id: string | null;
  chapter_id: string | null;
  character_id: string | null;
  used_proxy: boolean;
  duration: number | null;  // 请求耗时，单位秒
}
