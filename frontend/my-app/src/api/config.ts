/**
 * 系统配置相关 API
 */
import { api } from './index';

export type CustomVariableKey = 'KEY1' | 'KEY2' | 'KEY3' | 'KEY4' | 'KEY5' | 'KEY6' | 'KEY7' | 'KEY8' | 'KEY9';
export type CustomVariables = Record<CustomVariableKey, { value: string; note: string }>;

export interface SystemConfig {
  autoImageReviewEnabled?: boolean;
  videoPromptLanguage?: 'en' | 'zh';
  nameplatePreviewMode?: 'protagonist_first' | 'chapter_first';
  autoApproveFirstAppearanceNames?: boolean;
  generationQualityPolicy?: Record<string, boolean>;
  coverProduction?: string;
  parseCharactersPrompt?: string;
  comfyUIHost?: string;
  comfyUITimeout?: number;
  systemStatusSource?: 'comfyui' | 'windows_gpu_monitor';
  proxyEnabled?: boolean;
  httpProxy?: string;
  httpsProxy?: string;
  youtubeProxyEnabled?: boolean;
  youtubeProxyUrl?: string;
  customVariables?: CustomVariables;
}

export interface GenerationCheck {
  id: string;
  label: string;
  description: string;
  configurable: boolean;
  blocking: boolean;
  stage: 'before_queue' | 'director' | 'submission' | 'assembly';
  error_codes?: string[];
}

export const configApi = {
  /**
   * 获取系统配置
   */
  get: async () => {
    return api.get<SystemConfig>('/config/');
  },

  /**
   * 更新系统配置
   */
  update: async (config: Partial<SystemConfig>) => {
    return api.post<SystemConfig>('/config/', config);
  },
  customVariables: async () => api.get<CustomVariables>('/config/custom-variables'),
  customVariableOptions: async () => api.get<Array<{ key: CustomVariableKey; note: string }>>('/config/custom-variables/options'),
  generationChecks: async () => api.get<{ checks: GenerationCheck[]; policy: Record<string, boolean> }>('/config/generation-checks'),
};
