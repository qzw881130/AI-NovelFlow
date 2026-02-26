// 支持的 LLM 厂商
export type LLMProvider = 'deepseek' | 'openai' | 'gemini' | 'anthropic' | 'azure' | 'aliyun-bailian' | 'ollama' | 'custom';

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
  
  // 代理配置
  proxy: ProxyConfig;
  
  // 兼容旧配置（保留，但不再使用）
  deepseekApiKey?: string;
  deepseekApiUrl?: string;
  
  // ComfyUI 配置
  comfyUIHost: string;
  
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
  promptTemplateId?: string;  // 角色生成提示词模板
  scenePromptTemplateId?: string;  // 场景生成提示词模板
  chapterSplitPromptTemplateId?: string;  // 分镜拆分提示词模板
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
  status: 'pending' | 'parsing' | 'generating_characters' | 'generating_shots' | 'generating_videos' | 'compositing' | 'completed' | 'failed';
  progress: number;
  parsedData?: ParsedData;
  characterImages?: string[];
  shotImages?: string[];
  shotVideos?: string[];
  transitionVideos?: Record<string, string>;  // {"1-2": url, "2-3": url}
  finalVideo?: string;
}

export interface ParsedData {
  characters: Character[];
  scenes: Scene[];
  shots: Shot[];
}

export interface Character {
  id: string;
  name: string;
  description: string;
  appearance: string;
  imageUrl?: string;
  generatingStatus?: 'pending' | 'running' | 'completed' | 'failed';
  portraitTaskId?: string;
  novelId: string;
  novelName?: string;
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

export interface Shot {
  id: string;
  sceneId: string;
  description: string;
  cameraAngle?: string;
  imageUrl?: string;
  videoUrl?: string;
}

export interface Task {
  id: string;
  type: 'character_portrait' | 'scene_image' | 'shot_image' | 'shot_video' | 'chapter_video' | 'transition_video';
  name: string;
  description?: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress: number;
  currentStep?: string;
  resultUrl?: string;
  errorMessage?: string;
  workflowId?: string;
  workflowName?: string;
  workflowIsSystem?: boolean;
  hasWorkflowJson?: boolean;
  hasPromptText?: boolean;
  novelId?: string;
  novelName?: string;
  chapterId?: string;
  characterId?: string;
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
  system_prompt: string;
  user_prompt: string;
  response: string;
  status: string;
  error_message: string;
  task_type: string;
  novel_id: string;
  chapter_id: string;
  character_id: string;
  used_proxy: boolean;
  duration: number;  // 请求耗时，单位秒
}
