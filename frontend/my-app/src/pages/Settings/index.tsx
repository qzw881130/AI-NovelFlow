// Settings 页面主组件

import { useState, useEffect, useRef } from 'react';
import { Save, Loader2, Bot, Network, Server, CheckCircle, Activity } from 'lucide-react';
import { useTranslation } from '../../stores/i18nStore';
import { toast } from '../../stores/toastStore';
import LLMConfig from './components/LLMConfig';
import ProxyConfigPanel from './components/ProxyConfig';
import ComfyUIConfig from './components/ComfyUIConfig';
import WorkflowManager from './components/WorkflowManager';
import SystemStatusConfig from './components/SystemStatusConfig';
import type { SettingsFormData } from './types';
import { configApi } from '../../api/config';
import { DEFAULT_CONFIG } from '../../constants';

export default function Settings() {
  const { t } = useTranslation();
  
  // 表单数据
  const [formData, setFormData] = useState<SettingsFormData>(DEFAULT_CONFIG);
  
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [activeTab, setActiveTab] = useState<'llm' | 'proxy' | 'comfyui' | 'systemStatus' | 'workflows'>('llm');
  const isUserModifiedRef = useRef(false);

  // 从后端加载配置
  useEffect(() => {
    const loadConfig = async () => {
      try {
        const result = await configApi.get();
        console.log('[Settings/index] API response:', result);
        if (result.success && result.data) {
          const config = result.data as any;
          setFormData({
            llmProvider: config.llmProvider || 'deepseek',
            llmModel: config.llmModel || 'deepseek-v4-flash',
            llmApiKey: '', // API Key 不从前端获取
            llmApiUrl: config.llmApiUrl || 'https://api.deepseek.com',
            llmMaxTokens: config.llmMaxTokens || DEFAULT_CONFIG.llmMaxTokens,
            llmTemperature: config.llmTemperature,
            llmTimeout: config.llmTimeout || DEFAULT_CONFIG.llmTimeout,
            proxy: config.proxyEnabled !== undefined ? {
              enabled: config.proxyEnabled,
              httpProxy: config.httpProxy || '',
              httpsProxy: config.httpsProxy || '',
            } : DEFAULT_CONFIG.proxy,
            comfyUIHost: config.comfyUIHost || DEFAULT_CONFIG.comfyUIHost,
            systemStatusSource: config.systemStatusSource || DEFAULT_CONFIG.systemStatusSource,
          });
        }
      } catch (error) {
        console.error('加载配置失败:', error);
      }
    };
    loadConfig();
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    
    try {
      let payload: any = {};

      if (activeTab === 'llm') {
        payload = {
          llm: {
            provider: formData.llmProvider,
            model: formData.llmModel,
            apiKey: formData.llmApiKey,
            apiUrl: formData.llmApiUrl,
            maxTokens: formData.llmMaxTokens,
            temperature: formData.llmTemperature,
            timeout: formData.llmTimeout,
          },
        };
      } else if (activeTab === 'proxy') {
        payload = { proxy: formData.proxy };
      } else if (activeTab === 'comfyui') {
        payload = { comfyUIHost: formData.comfyUIHost };
      } else if (activeTab === 'systemStatus') {
        payload = { systemStatusSource: formData.systemStatusSource };
      }

      const result = await configApi.update(payload);
      
      if (result.success) {
        isUserModifiedRef.current = false;
        setSaved(true);
        setTimeout(() => setSaved(false), 3000);
        toast.success(t('systemSettings.configSaved'));
      } else {
        console.error('保存配置失败:', result.message);
        toast.error(t('systemSettings.configSaveFailed'));
      }
    } catch (error) {
      console.error('保存配置失败:', error);
      toast.error(t('systemSettings.configSaveFailed'));
    } finally {
      setSaving(false);
    }
  };

  const handleUserModified = () => {
    isUserModifiedRef.current = true;
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">{t('systemSettings.title')}</h1>
        <p className="mt-1 text-sm text-gray-500">
          {t('systemSettings.subtitle')}
        </p>
      </div>

      {/* AI 服务配置 - 标签页 */}
      <div className="card">
        <div className="flex items-center gap-3 mb-6">
          <div className="p-2 bg-blue-100 rounded-lg">
            <Bot className="h-5 w-5 text-blue-600" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-gray-900">{t('systemSettings.llmConfig')}</h2>
            <p className="text-sm text-gray-500">{t('systemSettings.subtitle')}</p>
          </div>
        </div>
        
        {/* 标签页导航 */}
        <div className="flex border-b border-gray-200 mb-6">
          <button
            type="button"
            onClick={() => setActiveTab('llm')}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'llm'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            <div className="flex items-center gap-2">
              <Bot className="h-4 w-4" />
              {t('systemSettings.llmConfig')}
            </div>
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('proxy')}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'proxy'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            <div className="flex items-center gap-2">
              <Network className="h-4 w-4" />
              {t('systemSettings.proxySettings')}
            </div>
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('comfyui')}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'comfyui'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            <div className="flex items-center gap-2">
              <Server className="h-4 w-4" />
              {t('systemSettings.comfyUISettings')}
            </div>
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('workflows')}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'workflows'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            <div className="flex items-center gap-2">
              <Server className="h-4 w-4" />
              {t('systemSettings.workflow.title')}
            </div>
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('systemStatus')}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'systemStatus'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            <div className="flex items-center gap-2">
              <Activity className="h-4 w-4" />
              {t('systemSettings.systemStatusSettings')}
            </div>
          </button>
        </div>

        {/* 工作流管理面板 - 独立于表单之外，避免嵌套表单问题 */}
        {activeTab === 'workflows' && (
          <WorkflowManager />
        )}

        {/* LLM/Proxy/ComfyUI 配置需要表单提交 */}
        {activeTab !== 'workflows' && (
          <form onSubmit={handleSubmit} className="space-y-6">
            {/* LLM 配置面板 */}
            {activeTab === 'llm' && (
              <LLMConfig 
                formData={formData}
                onFormDataChange={setFormData}
                onUserModified={handleUserModified}
              />
            )}

            {/* 代理配置面板 */}
            {activeTab === 'proxy' && (
              <ProxyConfigPanel 
                formData={formData}
                onFormDataChange={setFormData}
                onUserModified={handleUserModified}
              />
            )}

            {/* ComfyUI 配置面板 */}
            {activeTab === 'comfyui' && (
              <ComfyUIConfig 
                formData={formData}
                onFormDataChange={setFormData}
                onUserModified={handleUserModified}
              />
            )}

            {activeTab === 'systemStatus' && (
              <SystemStatusConfig
                formData={formData}
                onFormDataChange={setFormData}
                onUserModified={handleUserModified}
              />
            )}

            {/* 保存按钮 */}
            <div className="flex justify-end pt-6 border-t border-gray-200 mt-6">
              <button
                type="submit"
                disabled={saving}
                className="btn-primary flex items-center gap-2"
              >
                {saving ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    {t('common.saving')}
                  </>
                ) : saved ? (
                  <>
                    <CheckCircle className="h-4 w-4 text-green-500" />
                    {t('common.saved')}
                  </>
                ) : (
                  <>
                    <Save className="h-4 w-4" />
                    {t('common.save')}
                  </>
                )}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
