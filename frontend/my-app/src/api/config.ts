/**
 * 系统配置相关 API
 */
import { api } from './index';

export interface SystemConfig {
  autoImageReviewEnabled?: boolean;
  videoPromptLanguage?: 'en' | 'zh';
  showFirstAppearanceNames?: boolean;
  autoApproveFirstAppearanceNames?: boolean;
  generationQualityPolicy?: Record<string, boolean>;
  parseCharactersPrompt?: string;
  comfyUIHost?: string;
  comfyUITimeout?: number;
  systemStatusSource?: 'comfyui' | 'windows_gpu_monitor';
}

export interface GenerationCheck {
  id: string;
  label: string;
  description: string;
  configurable: boolean;
  blocking: boolean;
  stage: 'before_queue' | 'director' | 'submission' | 'assembly';
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
  generationChecks: async () => api.get<{ checks: GenerationCheck[]; policy: Record<string, boolean> }>('/config/generation-checks'),
};
