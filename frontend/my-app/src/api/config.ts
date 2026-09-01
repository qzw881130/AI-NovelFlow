/**
 * 系统配置相关 API
 */
import { api } from './index';

export interface SystemConfig {
  parseCharactersPrompt?: string;
  comfyUIHost?: string;
  comfyUITimeout?: number;
  systemStatusSource?: 'comfyui' | 'windows_gpu_monitor';
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
};
