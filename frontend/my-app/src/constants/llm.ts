/**
 * LLM 提供商常量配置
 */

import type { LLMProvider, LLMProviderPreset, LLMModel, ProxyConfig, SystemConfig } from '../types';

/**
 * 默认代理配置
 */
export const DEFAULT_PROXY: ProxyConfig = {
  enabled: false,
  httpProxy: '',
  httpsProxy: '',
};

/**
 * 默认系统配置
 */
export const DEFAULT_CONFIG: SystemConfig = {
  llmProvider: 'deepseek',
  llmModel: 'deepseek-v4-flash',
  llmApiKey: '',
  llmApiUrl: 'https://api.deepseek.com',
  llmMaxTokens: 393216,
  llmTemperature: undefined,
  llmTimeout: 1800,
  proxy: DEFAULT_PROXY,
  comfyUIHost: 'http://127.0.0.1:8188',
  comfyUITimeout: 900,
  systemStatusSource: 'comfyui',
  outputResolution: '1920x1080',
  outputFrameRate: 24,
};

/**
 * LLM 厂商预设配置
 */
export const LLM_PROVIDER_PRESETS: LLMProviderPreset[] = [
  {
    id: 'deepseek',
    name: 'DeepSeek',
    defaultApiUrl: 'https://api.deepseek.com',
    models: [
      { id: 'deepseek-v4-flash', name: 'DeepSeek V4 Flash', description: '新一代快速模型', maxTokens: 393216 },
      { id: 'deepseek-v4-pro', name: 'DeepSeek V4 Pro', description: '新一代高性能模型', maxTokens: 393216 },
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
      { id: 'gpt-5.6-luna', name: 'GPT-5.6 Luna' },
      { id: 'gpt-5.6-sol', name: 'GPT-5.6 Sol' },
      { id: 'gpt-5.6-terra', name: 'GPT-5.6 Terra' },
      { id: 'gpt-5.5', name: 'GPT-5.5', description: '旗舰推理与编码模型', maxTokens: 1000000 },
      { id: 'gpt-5.4', name: 'GPT-5.4', description: '高性价比专业模型', maxTokens: 1000000 },
      { id: 'gpt-5.4-mini', name: 'GPT-5.4 Mini', description: '轻量高性能模型', maxTokens: 400000 },
      { id: 'gpt-5.4-nano', name: 'GPT-5.4 Nano', description: '超低延迟模型', maxTokens: 400000 },
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
      { id: 'gemini-2.5-pro', name: 'Gemini 2.5 Pro', description: '稳定专业版', maxTokens: 1000000 },
      { id: 'gemini-2.5-flash', name: 'Gemini 2.5 Flash', description: '稳定快速版', maxTokens: 1000000 },
      { id: 'gemini-2.5-flash-lite', name: 'Gemini 2.5 Flash Lite', description: '稳定轻量版', maxTokens: 1000000 },
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
      { id: 'qwen3.6-max-preview', name: '通义千问 3.6 Max Preview', description: '最新旗舰预览模型' },
      { id: 'qwen3.6-plus', name: '通义千问 3.6 Plus', description: '新一代均衡模型' },
      { id: 'qwen3.6-flash', name: '通义千问 3.6 Flash', description: '新一代高速模型' },
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
    defaultApiUrl: 'http://127.0.0.1:11434/v1',
    models: [
      { id: 'ollama-default', name: '自动获取模型', description: '点击"自动获取"按钮获取模型列表' },
    ],
    apiKeyPlaceholder: '可选',
    apiKeyHelp: 'Ollama 通常不需要 API Key',
  },
  {
    id: 'custom',
    name: '自定义 API',
    defaultApiUrl: 'http://127.0.0.1:11434/v1',
    models: [
      { id: 'custom-model', name: '自定义模型', description: '兼容 OpenAI 格式的自定义 API' },
    ],
    apiKeyPlaceholder: '...',
    apiKeyHelp: '支持任何兼容 OpenAI API 格式的服务',
  },
];

/**
 * 获取厂商默认 API URL
 */
export const getDefaultApiUrl = (provider: LLMProvider): string => {
  const preset = LLM_PROVIDER_PRESETS.find(p => p.id === provider);
  return preset?.defaultApiUrl || '';
};

/**
 * 获取厂商默认模型列表
 */
export const getDefaultModels = (provider: LLMProvider): LLMModel[] => {
  const preset = LLM_PROVIDER_PRESETS.find(p => p.id === provider);
  return preset?.models || [];
};

/**
 * 获取 API Key 占位符
 */
export const getApiKeyPlaceholder = (provider: LLMProvider): string => {
  const preset = LLM_PROVIDER_PRESETS.find(p => p.id === provider);
  return preset?.apiKeyPlaceholder || '...';
};

/**
 * 获取 API Key 帮助文本
 */
export const getApiKeyHelp = (provider: LLMProvider): string | undefined => {
  const preset = LLM_PROVIDER_PRESETS.find(p => p.id === provider);
  return preset?.apiKeyHelp;
};
