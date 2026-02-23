import { create } from 'zustand';
import type { SystemConfig, LLMProvider, LLMProviderPreset, LLMModel, ProxyConfig } from '../types';

// API 基础 URL
const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';

// 默认代理配置
const defaultProxy: ProxyConfig = {
  enabled: false,
  httpProxy: '',
  httpsProxy: '',
};

// 默认配置
const defaultConfig: SystemConfig = {
  llmProvider: 'deepseek',
  llmModel: 'deepseek-chat',
  llmApiKey: '',
  llmApiUrl: 'https://api.deepseek.com',
  llmMaxTokens: undefined,
  llmTemperature: undefined,
  proxy: defaultProxy,
  comfyUIHost: 'http://192.168.50.1:8288',
  outputResolution: '1920x1080',
  outputFrameRate: 24,
};

// 从后端加载配置
const fetchConfigFromBackend = async () => {
  try {
    const res = await fetch(`${API_BASE}/config/`);
    const data = await res.json();
    if (data.success && data.data) {
      return {
        llmProvider: data.data.llmProvider || defaultConfig.llmProvider,
        llmModel: data.data.llmModel || defaultConfig.llmModel,
        llmApiKey: '', // API Key 不从前端获取
        llmApiUrl: data.data.llmApiUrl || defaultConfig.llmApiUrl,
        llmMaxTokens: data.data.llmMaxTokens,
        llmTemperature: data.data.llmTemperature,
        proxy: data.data.proxyEnabled !== undefined ? {
          enabled: data.data.proxyEnabled,
          httpProxy: data.data.httpProxy || '',
          httpsProxy: data.data.httpsProxy || '',
        } : defaultConfig.proxy,
        comfyUIHost: data.data.comfyUIHost || defaultConfig.comfyUIHost,
      };
    }
  } catch (error) {
    console.error('Failed to load config from backend:', error);
  }
  return null;
};

// LLM 厂商预设配置
export const LLM_PROVIDER_PRESETS: LLMProviderPreset[] = [
  {
    id: 'deepseek',
    name: 'DeepSeek',
    defaultApiUrl: 'https://api.deepseek.com',
    models: [
      { id: 'deepseek-chat', name: 'DeepSeek Chat', description: '通用对话模型', maxTokens: 8192 },
      { id: 'deepseek-coder', name: 'DeepSeek Coder', description: '代码专用模型', maxTokens: 8192 },
      { id: 'deepseek-reasoner', name: 'DeepSeek Reasoner', description: '推理模型', maxTokens: 8192 },
    ],
    apiKeyPlaceholder: 'sk-...',
    apiKeyHelp: '在 DeepSeek 控制台获取 API Key',
  },
  {
    id: 'openai',
    name: 'OpenAI',
    defaultApiUrl: 'https://api.openai.com/v1',
    models: [
      { id: 'gpt-4o', name: 'GPT-4o', description: '多模态旗舰模型', maxTokens: 128000 },
      { id: 'gpt-4o-mini', name: 'GPT-4o Mini', description: '轻量快速模型', maxTokens: 128000 },
      { id: 'gpt-4-turbo', name: 'GPT-4 Turbo', description: '高性能模型', maxTokens: 128000 },
      { id: 'gpt-3.5-turbo', name: 'GPT-3.5 Turbo', description: '经济实用模型', maxTokens: 16385 },
    ],
    apiKeyPlaceholder: 'sk-...',
    apiKeyHelp: '在 OpenAI 控制台获取 API Key',
  },
  {
    id: 'gemini',
    name: 'Google Gemini',
    defaultApiUrl: 'https://generativelanguage.googleapis.com/v1beta',
    models: [
      { id: 'gemini-2.5-flash-preview-05-20', name: 'Gemini 2.5 Flash Preview', description: '快速预览版', maxTokens: 1000000 },
      { id: 'gemini-2.5-pro-preview-05-20', name: 'Gemini 2.5 Pro Preview', description: '专业预览版', maxTokens: 1000000 },
      { id: 'gemini-2.0-flash', name: 'Gemini 2.0 Flash', description: '快速模型', maxTokens: 1000000 },
      { id: 'gemini-2.0-flash-lite', name: 'Gemini 2.0 Flash Lite', description: '轻量快速模型', maxTokens: 1000000 },
      { id: 'gemini-2.0-pro-exp-02-05', name: 'Gemini 2.0 Pro Exp', description: '实验性专业版', maxTokens: 2000000 },
    ],
    apiKeyPlaceholder: 'AI...',
    apiKeyHelp: '在 Google AI Studio 获取 API Key',
  },
  {
    id: 'anthropic',
    name: 'Anthropic Claude',
    defaultApiUrl: 'https://api.anthropic.com/v1',
    models: [
      { id: 'claude-3-5-sonnet-20241022', name: 'Claude 3.5 Sonnet', description: '平衡性能与速度', maxTokens: 200000 },
      { id: 'claude-3-opus-20240229', name: 'Claude 3 Opus', description: '最强性能模型', maxTokens: 200000 },
      { id: 'claude-3-sonnet-20240229', name: 'Claude 3 Sonnet', description: '平衡模型', maxTokens: 200000 },
      { id: 'claude-3-haiku-20240307', name: 'Claude 3 Haiku', description: '快速轻量模型', maxTokens: 200000 },
    ],
    apiKeyPlaceholder: 'sk-ant-...',
    apiKeyHelp: '在 Anthropic 控制台获取 API Key',
  },
  {
    id: 'azure',
    name: 'Azure OpenAI',
    defaultApiUrl: 'https://{your-resource}.openai.azure.com/openai/deployments/{deployment-id}',
    models: [
      { id: 'gpt-4o', name: 'GPT-4o', description: '多模态旗舰模型' },
      { id: 'gpt-4', name: 'GPT-4', description: '高性能模型' },
      { id: 'gpt-35-turbo', name: 'GPT-3.5 Turbo', description: '经济实用模型' },
    ],
    apiKeyPlaceholder: '...',
    apiKeyHelp: '在 Azure Portal 获取 API Key 和 Endpoint',
  },
  {
    id: 'aliyun-bailian',
    name: '阿里云百炼',
    defaultApiUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    models: [
      { id: 'qwen-max', name: '通义千问 Max', description: '通义千问超大规模语言模型，支持复杂任务', maxTokens: 32000 },
      { id: 'qwen-plus', name: '通义千问 Plus', description: '通义千问大规模语言模型，均衡性能与速度', maxTokens: 32000 },
      { id: 'qwen-turbo', name: '通义千问 Turbo', description: '通义千问轻量模型，快速响应', maxTokens: 32000 },
      { id: 'qwen-coder-plus', name: '通义千问 Coder Plus', description: '代码专用模型', maxTokens: 32000 },
      { id: 'qwen-2.5-72b-instruct', name: 'Qwen2.5-72B-Instruct', description: '72B 参数指令模型', maxTokens: 128000 },
      { id: 'deepseek-v3', name: 'DeepSeek-V3', description: 'DeepSeek V3 模型（通过百炼）', maxTokens: 64000 },
      { id: 'deepseek-r1', name: 'DeepSeek-R1', description: 'DeepSeek R1 推理模型（通过百炼）', maxTokens: 64000 },
    ],
    apiKeyPlaceholder: 'sk-...',
    apiKeyHelp: '在阿里云百炼控制台获取 API Key',
  },
  {
    id: 'ollama',
    name: 'Ollama',
    defaultApiUrl: 'http://192.168.50.1:11434/v1',
    models: [
      { id: 'ollama-default', name: '自动获取模型', description: '点击"自动获取"按钮获取模型列表' },
    ],
    apiKeyPlaceholder: '可选',
    apiKeyHelp: 'Ollama 通常不需要 API Key',
  },
  {
    id: 'custom',
    name: '自定义 API',
    defaultApiUrl: 'http://192.168.50.1:11434/v1',
    models: [
      { id: 'custom-model', name: '自定义模型', description: '兼容 OpenAI 格式的自定义 API' },
    ],
    apiKeyPlaceholder: '...',
    apiKeyHelp: '支持任何兼容 OpenAI API 格式的服务',
  },
];

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
  ...defaultConfig,
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
  
  checkConnection: async () => {
    set({ isLoading: true, error: null });
    try {
      // 检查 LLM API
      const llmRes = await fetch(`${API_BASE}/health/llm/`);
      const llm = llmRes.ok;
      
      // 检查 ComfyUI
      const comfyRes = await fetch(`${API_BASE}/health/comfyui/`);
      const comfyui = comfyRes.ok;
      
      set({ isLoading: false });
      return { llm, comfyui };
    } catch (error) {
      set({ isLoading: false, error: '连接检查失败' });
      return { llm: false, comfyui: false };
    }
  },
  
  loadConfig: async () => {
    const backendConfig = await fetchConfigFromBackend();
    if (backendConfig) {
      set({ ...backendConfig, isLoaded: true });
      return backendConfig;
    } else {
      set({ isLoaded: true });
      return null;
    }
  },
}));

// 导出辅助函数
export const getDefaultApiUrl = (provider: LLMProvider): string => {
  const preset = LLM_PROVIDER_PRESETS.find(p => p.id === provider);
  return preset?.defaultApiUrl || '';
};

export const getDefaultModels = (provider: LLMProvider): LLMModel[] => {
  const preset = LLM_PROVIDER_PRESETS.find(p => p.id === provider);
  return preset?.models || [];
};

export const getApiKeyPlaceholder = (provider: LLMProvider): string => {
  const preset = LLM_PROVIDER_PRESETS.find(p => p.id === provider);
  return preset?.apiKeyPlaceholder || '...';
};

export const getApiKeyHelp = (provider: LLMProvider): string | undefined => {
  const preset = LLM_PROVIDER_PRESETS.find(p => p.id === provider);
  return preset?.apiKeyHelp;
};
