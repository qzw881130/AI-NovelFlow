// LLM 配置组件

import { useState } from 'react';
import { Eye, EyeOff, Bot } from 'lucide-react';
import { useTranslation } from '../../stores/i18nStore';
import { useConfigStore, LLM_PROVIDER_PRESETS } from '../../stores/configStore';
import { getProviderDisplayName, getModelName, getModelDescription } from './utils';
import type { SettingsFormData } from './types';
import type { LLMProvider, LLMModel } from '../../types';

interface LLMConfigProps {
  formData: SettingsFormData;
  onFormDataChange: (data: SettingsFormData) => void;
  onUserModified: () => void;
}

export default function LLMConfig({ formData, onFormDataChange, onUserModified }: LLMConfigProps) {
  const { t } = useTranslation();
  const [showApiKey, setShowApiKey] = useState(false);
  const [customModels, setCustomModels] = useState<LLMModel[]>([]);
  const [loadingCustomModels, setLoadingCustomModels] = useState(false);
  const [customModelsError, setCustomModelsError] = useState<string | null>(null);

  // 获取当前厂商预设
  const currentPreset = LLM_PROVIDER_PRESETS.find(p => p.id === formData.llmProvider);
  
  // 获取当前厂商的模型列表
  const availableModels = (formData.llmProvider === 'custom' || formData.llmProvider === 'ollama') && customModels.length > 0
    ? customModels
    : currentPreset?.models || [];

  // 自动获取自定义 API 的模型列表
  const fetchCustomModels = async () => {
    if (!formData.llmApiUrl) {
      setCustomModelsError('请先填写 API URL');
      return;
    }
    
    setLoadingCustomModels(true);
    setCustomModelsError(null);
    
    try {
      // 尝试 Ollama API 格式
      const ollamaUrl = formData.llmApiUrl.replace(/\/v1$/, '').replace(/\/$/, '') + '/api/tags';
      const res = await fetch(ollamaUrl, { 
        method: 'GET',
        headers: formData.llmApiKey ? { 'Authorization': `Bearer ${formData.llmApiKey}` } : {}
      });
      
      if (res.ok) {
        const data = await res.json();
        if (data.models && Array.isArray(data.models)) {
          const models: LLMModel[] = data.models.map((m: any) => ({
            id: m.name || m.model,
            name: m.name || m.model,
            description: `${m.details?.family || ''} ${m.details?.parameter_size || ''}`.trim() || '本地模型',
          }));
          setCustomModels(models);
          
          if (models.length > 0 && !models.find(m => m.id === formData.llmModel)) {
            onFormDataChange({ ...formData, llmModel: models[0].id });
          }
          
          return;
        }
      }
      
      // 尝试 OpenAI 兼容格式
      const openaiUrl = formData.llmApiUrl.replace(/\/$/, '') + '/models';
      const openaiRes = await fetch(openaiUrl, {
        headers: formData.llmApiKey ? { 'Authorization': `Bearer ${formData.llmApiKey}` } : {}
      });
      
      if (openaiRes.ok) {
        const data = await openaiRes.json();
        if (data.data && Array.isArray(data.data)) {
          const models: LLMModel[] = data.data.map((m: any) => ({
            id: m.id,
            name: m.id,
            description: m.object || 'API 模型',
          }));
          setCustomModels(models);
          
          if (models.length > 0 && !models.find(m => m.id === formData.llmModel)) {
            onFormDataChange({ ...formData, llmModel: models[0].id });
          }
          return;
        }
      }
      
      setCustomModelsError('无法自动获取模型列表，请检查 API URL 是否正确');
    } catch (error) {
      console.error('获取模型列表失败:', error);
      setCustomModelsError('获取模型列表失败：' + (error instanceof Error ? error.message : '网络错误'));
    } finally {
      setLoadingCustomModels(false);
    }
  };

  // 处理厂商切换
  const handleProviderChange = (provider: LLMProvider) => {
    onUserModified();
    const preset = LLM_PROVIDER_PRESETS.find(p => p.id === provider);
    onFormDataChange({
      ...formData,
      llmProvider: provider,
      llmModel: preset?.models[0]?.id || '',
      llmApiUrl: preset?.defaultApiUrl || '',
    });
    if (provider !== 'custom' && provider !== 'ollama') {
      setCustomModels([]);
    }
  };

  return (
    <div className="space-y-6">
      {/* 厂商选择 */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-3">
          {t('systemSettings.selectProvider')}
        </label>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          {LLM_PROVIDER_PRESETS.map((preset) => (
            <button
              key={preset.id}
              type="button"
              onClick={() => handleProviderChange(preset.id)}
              className={`flex items-center gap-3 p-3 rounded-lg border-2 transition-all ${
                formData.llmProvider === preset.id
                  ? 'border-blue-500 bg-blue-50 text-blue-700'
                  : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
              }`}
            >
              <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold ${
                formData.llmProvider === preset.id
                  ? 'bg-blue-500 text-white'
                  : 'bg-gray-200 text-gray-600'
              }`}>
                {getProviderDisplayName(preset.id, t).charAt(0)}
              </div>
              <div className="text-left">
                <div className="text-sm font-medium">{getProviderDisplayName(preset.id, t)}</div>
                <div className="text-xs text-gray-500">
                  {preset.models.length} {t('systemSettings.selectModel')}
                </div>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* API 地址 */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          {t('systemSettings.apiUrl')}
        </label>
        <input
          type="url"
          value={formData.llmApiUrl}
          onChange={(e) => { onUserModified(); onFormDataChange({ ...formData, llmApiUrl: e.target.value }); }}
          className="input-field"
          placeholder={currentPreset?.defaultApiUrl || ''}
        />
      </div>

      {/* API Key */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          {t('systemSettings.apiKey')}
        </label>
        <div className="relative">
          <input
            type={showApiKey ? 'text' : 'password'}
            value={formData.llmApiKey}
            onChange={(e) => { onUserModified(); onFormDataChange({ ...formData, llmApiKey: e.target.value }); }}
            className="input-field pr-10"
            placeholder={t('systemSettings.enterApiKey')}
          />
          <button
            type="button"
            onClick={() => setShowApiKey(!showApiKey)}
            className="absolute inset-y-0 right-0 pr-3 flex items-center text-gray-400 hover:text-gray-500"
          >
            {showApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        </div>
      </div>

      {/* 模型选择 */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          {t('systemSettings.selectModel')}
          {formData.llmProvider === 'ollama' && (
            <button
              type="button"
              onClick={fetchCustomModels}
              disabled={loadingCustomModels}
              className="ml-2 text-xs text-blue-600 hover:text-blue-700 disabled:opacity-50"
            >
              {loadingCustomModels ? '获取中...' : '自动获取'}
            </button>
          )}
        </label>
        
        {formData.llmProvider === 'custom' ? (
          <input
            type="text"
            value={formData.llmModel}
            onChange={(e) => {
              onUserModified();
              onFormDataChange({ ...formData, llmModel: e.target.value });
            }}
            placeholder="输入模型名称，例如：glm-5:cloud"
            className="input-field"
          />
        ) : (
          <select
            value={formData.llmModel}
            onChange={(e) => { onUserModified(); onFormDataChange({ ...formData, llmModel: e.target.value }); }}
            className="input-field"
          >
            {availableModels.map((model) => {
              const name = getModelName(model.id, t) || model.name;
              const desc = getModelDescription(model.id, t);
              return (
                <option key={model.id} value={model.id}>
                  {name} {desc ? `- ${desc}` : ''}
                  {model.maxTokens ? ` (${(model.maxTokens / 1000).toFixed(0)}k tokens)` : ''}
                </option>
              );
            })}
          </select>
        )}
        {customModelsError && (
          <p className="mt-1 text-xs text-red-600">{customModelsError}</p>
        )}
      </div>

      {/* 最大Token数配置 */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          {t('systemSettings.maxTokens')}
        </label>
        <input
          type="number"
          value={formData.llmMaxTokens || ''}
          onChange={(e) => {
            onUserModified();
            const value = e.target.value ? parseInt(e.target.value) : undefined;
            onFormDataChange({ ...formData, llmMaxTokens: value });
          }}
          className="input-field"
          placeholder="4000"
          min="1"
          max="128000"
        />
        <p className="mt-1 text-xs text-gray-500">
          {t('systemSettings.maxTokensDesc')}
        </p>
      </div>

      {/* Temperature配置 */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          {t('systemSettings.temperature')}
        </label>
        <input
          type="number"
          step="0.1"
          value={formData.llmTemperature || ''}
          onChange={(e) => {
            onUserModified();
            onFormDataChange({ ...formData, llmTemperature: e.target.value });
          }}
          className="input-field"
          placeholder="0.7"
          min="0"
          max="2"
        />
        <p className="mt-1 text-xs text-gray-500">
          {t('systemSettings.temperatureDesc')}
        </p>
      </div>
    </div>
  );
}
