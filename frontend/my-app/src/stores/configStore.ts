/**
 * 配置状态管理 Store
 */

import { create } from 'zustand';
import type { SystemConfig, LLMProvider, LLMProviderPreset, LLMModel, ProxyConfig } from '../types';
import { 
  DEFAULT_CONFIG, 
  LLM_PROVIDER_PRESETS,
  getDefaultApiUrl,
  getDefaultModels,
  getApiKeyPlaceholder,
  getApiKeyHelp 
} from '../constants';

// API 基础 URL
const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';

// Share requests while they are pending, including StrictMode effect replays.
let configLoadRequest: Promise<SystemConfig | null> | null = null;
let connectionCheckRequest: Promise<{ llm: boolean; comfyui: boolean }> | null = null;

// 从后端加载配置
const fetchConfigFromBackend = async () => {
  try {
    const res = await fetch(`${API_BASE}/config/`);
    const data = await res.json();
    console.log('[ConfigStore] API response:', data);
    if (data.success && data.data) {
      const config = {
        llmProvider: data.data.llmProvider || DEFAULT_CONFIG.llmProvider,
        llmModel: data.data.llmModel || DEFAULT_CONFIG.llmModel,
        llmApiKey: '', // API Key 不从前端获取
        llmApiUrl: data.data.llmApiUrl || DEFAULT_CONFIG.llmApiUrl,
        llmMaxTokens: data.data.llmMaxTokens,
        llmTemperature: data.data.llmTemperature,
        proxy: data.data.proxyEnabled !== undefined ? {
          enabled: data.data.proxyEnabled,
          httpProxy: data.data.httpProxy || '',
          httpsProxy: data.data.httpsProxy || '',
        } : DEFAULT_CONFIG.proxy,
        comfyUIHost: data.data.comfyUIHost || DEFAULT_CONFIG.comfyUIHost,
        comfyUITimeout: data.data.comfyUITimeout || DEFAULT_CONFIG.comfyUITimeout,
        systemStatusSource: data.data.systemStatusSource || DEFAULT_CONFIG.systemStatusSource,
      };
      console.log('[ConfigStore] Parsed config:', config);
      return config;
    }
  } catch (error) {
    console.error('Failed to load config from backend:', error);
  }
  return null;
};

interface ConfigState extends SystemConfig {
  isLoading: boolean;
  error: string | null;
  isLoaded: boolean;
  setConfig: (config: Partial<SystemConfig>) => void;
  setLLMConfig: (provider: LLMProvider, model: string, apiKey: string, apiUrl: string, maxTokens?: number, temperature?: string) => void;
  setProxyConfig: (proxy: ProxyConfig) => void;
  getProviderPreset: () => LLMProviderPreset | undefined;
  getCurrentModel: () => LLMModel | undefined;
  checkConnection: () => Promise<{ llm: boolean; comfyui: boolean }>;
  loadConfig: () => Promise<SystemConfig | null>;
}

export const useConfigStore = create<ConfigState>((set, get) => ({
  ...DEFAULT_CONFIG,
  isLoading: false,
  error: null,
  isLoaded: false,
  
  setConfig: (config) => set((state) => {
    // 特殊处理嵌套的 proxy 配置
    if (config.proxy) {
      return {
        ...state,
        ...config,
        proxy: { ...state.proxy, ...config.proxy },
      };
    }
    return { ...state, ...config };
  }),
  
  setLLMConfig: (provider, model, apiKey, apiUrl, maxTokens?, temperature?) => set((state) => ({
    ...state,
    llmProvider: provider,
    llmModel: model,
    llmApiKey: apiKey,
    llmApiUrl: apiUrl,
    llmMaxTokens: maxTokens,
    llmTemperature: temperature,
  })),
  
  setProxyConfig: (proxy) => set((state) => ({ ...state, proxy })),
  
  getProviderPreset: () => {
    const { llmProvider } = get();
    return LLM_PROVIDER_PRESETS.find(p => p.id === llmProvider);
  },
  
  getCurrentModel: () => {
    const { llmModel } = get();
    const preset = get().getProviderPreset();
    return preset?.models.find(m => m.id === llmModel);
  },
  
  checkConnection: () => {
    if (connectionCheckRequest) return connectionCheckRequest;
    set({ isLoading: true, error: null });
    connectionCheckRequest = Promise.allSettled([
      fetch(`${API_BASE}/health/llm`),
      fetch(`${API_BASE}/health/comfyui`),
    ]).then(([llm, comfyui]) => {
      if (llm.status === 'rejected' || comfyui.status === 'rejected') {
        set({ error: '连接检查失败' });
      }
      return {
        llm: llm.status === 'fulfilled' && llm.value.ok,
        comfyui: comfyui.status === 'fulfilled' && comfyui.value.ok,
      };
    }).finally(() => {
      connectionCheckRequest = null;
      set({ isLoading: false });
    });
    return connectionCheckRequest;
  },
  
  loadConfig: async () => {
    // 如果已经加载过，直接返回当前配置（避免重复请求）
    if (get().isLoaded) {
      return {
        llmProvider: get().llmProvider,
        llmModel: get().llmModel,
        llmApiKey: get().llmApiKey,
        llmApiUrl: get().llmApiUrl,
        llmMaxTokens: get().llmMaxTokens,
        llmTemperature: get().llmTemperature,
        proxy: get().proxy,
        comfyUIHost: get().comfyUIHost,
        comfyUITimeout: get().comfyUITimeout,
        systemStatusSource: get().systemStatusSource,
      };
    }
    
    if (configLoadRequest) return configLoadRequest;
    configLoadRequest = fetchConfigFromBackend().then(backendConfig => {
      if (backendConfig) {
        set({ ...backendConfig, isLoaded: true });
      } else {
        set({ isLoaded: true });
      }
      return backendConfig;
    }).finally(() => {
      configLoadRequest = null;
    });
    return configLoadRequest;
  },
}));

// 重新导出辅助函数（从 constants 导出）
export { 
  LLM_PROVIDER_PRESETS,
  getDefaultApiUrl, 
  getDefaultModels, 
  getApiKeyPlaceholder, 
  getApiKeyHelp 
};
