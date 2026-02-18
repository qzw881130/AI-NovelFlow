import { useState, useEffect } from 'react';
import { 
  Globe,
  Clock,
  Loader2,
  Save
} from 'lucide-react';
import { toast } from '../stores/toastStore';
import { useTranslation, languageOptions, timezoneOptions, type Language } from '../stores/i18nStore';

const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';

export default function UIConfig() {
  const { t, i18n } = useTranslation();
  
  // 界面配置
  const [language, setLanguage] = useState<Language>(i18n.language as Language);
  const [timezone, setTimezone] = useState(i18n.timezone);
  const [savingUIConfig, setSavingUIConfig] = useState(false);
  const [loading, setLoading] = useState(true);

  // 从后端加载界面配置（只在组件挂载时执行一次）
  useEffect(() => {
    const fetchConfig = async () => {
      try {
        const res = await fetch(`${API_BASE}/config/`);
        const data = await res.json();
        if (data.success && data.data) {
          // 加载界面配置
          if (data.data.language) {
            setLanguage(data.data.language);
            // 同步更新全局语言
            i18n.changeLanguage(data.data.language);
          }
          if (data.data.timezone) {
            setTimezone(data.data.timezone);
            i18n.changeTimezone(data.data.timezone);
          }
        }
      } catch (error) {
        console.error('加载配置失败:', error);
      } finally {
        setLoading(false);
      }
    };
    fetchConfig();
    // 注意：i18n 不从依赖数组中移除，只在组件挂载时执行一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 处理语言变更
  const handleLanguageChange = (newLanguage: Language) => {
    setLanguage(newLanguage);
    // 立即更新全局语言
    i18n.changeLanguage(newLanguage);
  };

  // 保存界面配置
  const handleSaveUIConfig = async () => {
    setSavingUIConfig(true);
    try {
      const res = await fetch(`${API_BASE}/config/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          language,
          timezone
        })
      });
      
      if (res.ok) {
        toast.success(t('uiConfig.configSaved') || '界面配置已保存');
      } else {
        toast.error(t('common.saveFailed') || '保存失败');
      }
    } catch (error) {
      console.error('保存界面配置失败:', error);
      toast.error(t('common.saveFailed') || '保存失败');
    } finally {
      setSavingUIConfig(false);
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <Loader2 className="h-8 w-8 animate-spin text-gray-400" />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">{t('uiConfig.title')}</h1>
        <p className="mt-1 text-sm text-gray-500">
          {t('uiConfig.subtitle')}
        </p>
      </div>

      {/* 界面配置 */}
      <div className="card">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-2">
            <Globe className="h-5 w-5 text-teal-600" />
            <h2 className="text-lg font-semibold text-gray-900">{t('uiConfig.title')}</h2>
          </div>
          <button
            type="button"
            onClick={handleSaveUIConfig}
            disabled={savingUIConfig}
            className="inline-flex items-center gap-1 px-3 py-1.5 text-sm text-primary-600 hover:text-primary-700 hover:bg-primary-50 rounded-md transition-colors disabled:opacity-50"
          >
            <Save className="h-4 w-4" />
            {savingUIConfig ? t('common.saving') : t('common.save')}
          </button>
        </div>
        
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* 语言选择 */}
          <div>
            <label className="flex items-center gap-2 text-sm font-medium text-gray-700 mb-2">
              <Globe className="h-4 w-4 text-gray-400" />
              {t('uiConfig.languageSettings')}
            </label>
            <select
              value={language}
              onChange={(e) => handleLanguageChange(e.target.value as Language)}
              className="input-field w-full"
            >
              {languageOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <p className="text-xs text-gray-500 mt-1">
              {t('uiConfig.selectLanguage')}
            </p>
          </div>
          
          {/* 时区选择 */}
          <div>
            <label className="flex items-center gap-2 text-sm font-medium text-gray-700 mb-2">
              <Clock className="h-4 w-4 text-gray-400" />
              {t('uiConfig.timezoneSettings')}
            </label>
            <select
              value={timezone}
              onChange={(e) => {
                const newTimezone = e.target.value;
                setTimezone(newTimezone);
                i18n.changeTimezone(newTimezone);
              }}
              className="input-field w-full"
            >
              {timezoneOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {t(option.labelKey)}
                </option>
              ))}
            </select>
            <p className="text-xs text-gray-500 mt-1">
              {t('uiConfig.selectTimezone')}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
