/**
 * 系统配置相关 API
 */

import { get, post } from './client';

export interface LLMConfig {
  provider: string;
  model: string;
  apiKey: string;
  apiUrl: string;
  maxTokens?: number;
  temperature?: number | string;
}

export interface ProxyConfig {
  enabled: boolean;
  httpProxy: string;
  httpsProxy: string;
}

export interface SystemConfig {
  llm?: LLMConfig;
  proxy?: ProxyConfig;
  comfyUIHost?: string;
}

export const configApi = {
  /**
   * 获取系统配置
   */
  get: () => get<SystemConfig>('/config/'),
  
  /**
   * 保存系统配置
   */
  save: (config: SystemConfig) => post<void>('/config/', config),
};

export default configApi;
