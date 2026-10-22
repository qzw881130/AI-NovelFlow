// Settings 页面主组件

import { useState, useEffect, useRef } from 'react';
import { Save, Loader2, Bot, Network, Server, CheckCircle, Activity, Bell, ShieldCheck, Clapperboard } from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from '../../stores/i18nStore';
import { toast } from '../../stores/toastStore';
import LLMConfig from './components/LLMConfig';
import ProxyConfigPanel from './components/ProxyConfig';
import ComfyUIConfig from './components/ComfyUIConfig';
import WorkflowManager from './components/WorkflowManager';
import SystemStatusConfig from './components/SystemStatusConfig';
import NotificationConfig from './components/NotificationConfig';
import GenerationQualityConfig from './components/GenerationQualityConfig';
import type { SettingsFormData } from './types';
import { configApi } from '../../api/config';
import type { GenerationCheck } from '../../api/config';
import { DEFAULT_CONFIG } from '../../constants';

type SettingsTab = 'llm' | 'proxy' | 'comfyui' | 'systemStatus' | 'workflows' | 'notifications' | 'generationQuality' | 'content';

const TAB_HASHES: Record<SettingsTab, string> = {
  llm: 'llm',
  proxy: 'proxy',
  comfyui: 'comfyui',
  workflows: 'workflows',
  systemStatus: 'system-status',
  notifications: 'notifications',
  generationQuality: 'generation-quality',
  content: 'content',
};

const getTabFromHash = (hash: string): SettingsTab => {
  const normalized = hash.replace(/^#/, '').toLowerCase();
  const match = (Object.entries(TAB_HASHES) as Array<[SettingsTab, string]>)
    .find(([, value]) => value === normalized);
  return match?.[0] || 'llm';
};

export default function Settings() {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  
  // 表单数据
  const [formData, setFormData] = useState<SettingsFormData>(DEFAULT_CONFIG);
  
  const [saving, setSaving] = useState(false);
  const [nameplateAvailable, setNameplateAvailable] = useState(false);
  const [autoApproveNameplateAvailable, setAutoApproveNameplateAvailable] = useState(false);
  const [generationChecks, setGenerationChecks] = useState<GenerationCheck[]>([]);
  const [saved, setSaved] = useState(false);
  const [activeTab, setActiveTab] = useState<SettingsTab>(() => getTabFromHash(window.location.hash));
  const isUserModifiedRef = useRef(false);

  useEffect(() => {
    setActiveTab(getTabFromHash(location.hash));
  }, [location.hash]);

  const selectTab = (tab: SettingsTab) => {
    setActiveTab(tab);
    navigate({
      pathname: location.pathname,
      search: location.search,
      hash: TAB_HASHES[tab],
    });
  };

  // 从后端加载配置
  useEffect(() => {
    const loadConfig = async () => {
      try {
        const result = await configApi.get();
        console.log('[Settings/index] API response:', result);
        if (result.success && result.data) {
          const config = result.data as any;
          setNameplateAvailable(typeof config.showFirstAppearanceNames === 'boolean');
          setAutoApproveNameplateAvailable(typeof config.autoApproveFirstAppearanceNames === 'boolean');
          setFormData({
            llmProvider: config.llmProvider || 'deepseek',
            llmModel: config.llmModel || 'deepseek-v4-flash',
            llmApiKey: '', // API Key 不从前端获取
            llmApiUrl: config.llmApiUrl || 'https://api.deepseek.com',
            llmMaxTokens: config.llmMaxTokens || DEFAULT_CONFIG.llmMaxTokens,
            llmTemperature: config.llmTemperature,
            llmTimeout: config.llmTimeout || DEFAULT_CONFIG.llmTimeout,
            autoImageReviewEnabled: config.autoImageReviewEnabled ?? false,
            videoPromptLanguage: config.videoPromptLanguage ?? 'en',
            showFirstAppearanceNames: config.showFirstAppearanceNames ?? false,
            autoApproveFirstAppearanceNames: config.autoApproveFirstAppearanceNames ?? false,
            generationQualityPolicy: config.generationQualityPolicy ?? {},
            coverProduction: config.coverProduction ?? '旺仔有声小说',
            proxy: config.proxyEnabled !== undefined ? {
              enabled: config.proxyEnabled,
              httpProxy: config.httpProxy || '',
              httpsProxy: config.httpsProxy || '',
              youtubeEnabled: config.youtubeProxyEnabled ?? false,
              youtubeProxyUrl: config.youtubeProxyUrl || '',
            } : DEFAULT_CONFIG.proxy,
            comfyUIHost: config.comfyUIHost || DEFAULT_CONFIG.comfyUIHost,
            comfyUITimeout: config.comfyUITimeout || DEFAULT_CONFIG.comfyUITimeout,
            systemStatusSource: config.systemStatusSource || DEFAULT_CONFIG.systemStatusSource,
          });
        }
      } catch (error) {
        console.error('加载配置失败:', error);
      }
    };
    loadConfig();
    configApi.generationChecks().then(result => {
      if (result.success && result.data) setGenerationChecks(result.data.checks);
    }).catch(error => console.error('加载生成检查项失败:', error));
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
      } else if (activeTab === 'generationQuality') {
        payload = {
          autoImageReviewEnabled: formData.autoImageReviewEnabled ?? false,
          videoPromptLanguage: formData.videoPromptLanguage ?? 'en',
          showFirstAppearanceNames: formData.showFirstAppearanceNames ?? false,
          generationQualityPolicy: formData.generationQualityPolicy ?? {},
          ...(autoApproveNameplateAvailable ? {
            autoApproveFirstAppearanceNames: formData.autoApproveFirstAppearanceNames ?? false,
          } : {}),
        };
      } else if (activeTab === 'content') {
        payload = { coverProduction: formData.coverProduction?.trim() || '旺仔有声小说' };
      } else if (activeTab === 'proxy') {
        payload = { proxy: formData.proxy };
      } else if (activeTab === 'comfyui') {
        payload = { comfyUIHost: formData.comfyUIHost, comfyUITimeout: formData.comfyUITimeout };
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
          {activeTab === 'notifications' ? '设置通知通道、提示音和事件开关' : activeTab === 'generationQuality' ? t('systemSettings.imageQualityReview') : activeTab === 'content' ? '设置视频封面等内容的默认署名' : t('systemSettings.subtitle')}
        </p>
      </div>

      {/* AI 服务配置 - 标签页 */}
      <div className="card">
        <div className="flex items-center gap-3 mb-6">
          <div className="p-2 bg-blue-100 rounded-lg">
            {activeTab === 'generationQuality' ? <ShieldCheck className="h-5 w-5 text-blue-600" /> : activeTab === 'notifications' ? <Bell className="h-5 w-5 text-blue-600" /> : activeTab === 'content' ? <Clapperboard className="h-5 w-5 text-blue-600" /> : <Bot className="h-5 w-5 text-blue-600" />}
          </div>
          <div>
            <h2 className="text-lg font-semibold text-gray-900">{activeTab === 'notifications' ? '消息通知' : activeTab === 'generationQuality' ? t('systemSettings.generationQualityControl') : activeTab === 'content' ? '内容设置' : t('systemSettings.llmConfig')}</h2>
            <p className="text-sm text-gray-500">{activeTab === 'notifications' ? '配置页面声音、外部推送与事件开关' : activeTab === 'generationQuality' ? t('systemSettings.imageQualityReview') : activeTab === 'content' ? '设置封面制作署名' : t('systemSettings.subtitle')}</p>
          </div>
        </div>
        
        {/* 标签页导航 */}
        <div className="flex border-b border-gray-200 mb-6 overflow-x-auto">
          <button
            type="button"
            onClick={() => selectTab('llm')}
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
            onClick={() => selectTab('proxy')}
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
            onClick={() => selectTab('comfyui')}
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
            onClick={() => selectTab('workflows')}
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
            onClick={() => selectTab('systemStatus')}
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
          <button type="button" onClick={() => selectTab('notifications')}
            className={`shrink-0 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${activeTab === 'notifications' ? 'border-blue-500 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`}>
            <span className="flex items-center gap-2"><Bell className="h-4 w-4" />消息通知</span>
          </button>
          <button type="button" onClick={() => selectTab('generationQuality')}
            className={`shrink-0 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${activeTab === 'generationQuality' ? 'border-blue-500 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`}>
            <span className="flex items-center gap-2"><ShieldCheck className="h-4 w-4" />{t('systemSettings.generationQualityControl')}</span>
          </button>
          <button type="button" onClick={() => selectTab('content')}
            className={`shrink-0 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${activeTab === 'content' ? 'border-blue-500 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`}>
            <span className="flex items-center gap-2"><Clapperboard className="h-4 w-4" />内容设置</span>
          </button>
        </div>

        {/* 工作流管理面板 - 独立于表单之外，避免嵌套表单问题 */}
        {activeTab === 'workflows' && (
          <WorkflowManager />
        )}
        {activeTab === 'notifications' && <NotificationConfig />}

        {/* LLM/Proxy/ComfyUI 配置需要表单提交 */}
        {activeTab !== 'workflows' && activeTab !== 'notifications' && (
          <form onSubmit={handleSubmit} className="space-y-6">
            {activeTab === 'content' && (
              <div className="rounded-lg border border-gray-200 p-5">
                <label htmlFor="cover-production" className="block text-sm font-medium text-gray-900">视频封面制作署名</label>
                <p className="mt-1 text-sm text-gray-500">生成章回合并视频封面时默认填写，可在每次生成前修改。</p>
                <input id="cover-production" type="text" maxLength={80} required
                  value={formData.coverProduction ?? ''}
                  onChange={event => setFormData(previous => ({ ...previous, coverProduction: event.target.value }))}
                  className="input mt-3 w-full max-w-md" placeholder="旺仔有声小说" />
              </div>
            )}
            {/* LLM 配置面板 */}
            {activeTab === 'llm' && (
              <LLMConfig 
                formData={formData}
                onFormDataChange={setFormData}
                onUserModified={handleUserModified}
              />
            )}

            {activeTab === 'generationQuality' && (
              <GenerationQualityConfig
                checks={generationChecks}
                policy={formData.generationQualityPolicy ?? {}}
                onPolicyChange={(id, blocking) => {
                  handleUserModified();
                  setFormData(previous => ({...previous,
                    generationQualityPolicy: {...(previous.generationQualityPolicy ?? {}), [id]: blocking}}));
                }}
                nameplateAvailable={nameplateAvailable}
                autoApproveNameplateAvailable={autoApproveNameplateAvailable}
                language={formData.videoPromptLanguage ?? 'en'}
                onLanguageChange={videoPromptLanguage => {
                  handleUserModified();
                  setFormData(previous => ({ ...previous, videoPromptLanguage }));
                }}
                enabled={formData.autoImageReviewEnabled ?? false}
                onChange={(enabled) => {
                  handleUserModified();
                  setFormData(previous => ({ ...previous, autoImageReviewEnabled: enabled }));
                }}
                showFirstAppearanceNames={formData.showFirstAppearanceNames ?? false}
                onShowFirstAppearanceNamesChange={(enabled) => {
                  handleUserModified();
                  setFormData(previous => ({ ...previous, showFirstAppearanceNames: enabled }));
                }}
                autoApproveFirstAppearanceNames={formData.autoApproveFirstAppearanceNames ?? false}
                onAutoApproveFirstAppearanceNamesChange={(enabled) => {
                  handleUserModified();
                  setFormData(previous => ({ ...previous, autoApproveFirstAppearanceNames: enabled }));
                }}
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
