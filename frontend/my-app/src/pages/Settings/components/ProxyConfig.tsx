// 代理配置组件

import { Network } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import type { SettingsFormData } from '../types';
import type { ProxyConfig } from '../../../types';

interface ProxyConfigPanelProps {
  formData: SettingsFormData;
  onFormDataChange: (data: SettingsFormData) => void;
  onUserModified: () => void;
}

export default function ProxyConfigPanel({ formData, onFormDataChange, onUserModified }: ProxyConfigPanelProps) {
  const { t } = useTranslation();

  const handleProxyChange = (updates: Partial<ProxyConfig>) => {
    onUserModified();
    onFormDataChange({
      ...formData,
      proxy: { ...formData.proxy, ...updates },
    });
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 p-4 bg-blue-50 rounded-lg">
        <Network className="h-5 w-5 text-blue-600" />
        <div>
          <h3 className="text-sm font-medium text-blue-900">{t('systemSettings.proxySettings')}</h3>
          <p className="text-xs text-blue-700">
            {t('systemSettings.subtitle')}
          </p>
        </div>
      </div>

      <div className="rounded-lg border border-gray-200 p-4">
        <div className="flex items-center justify-between">
          <div>
            <label htmlFor="llm-proxy-enabled" className="text-sm font-medium text-gray-700">LLM 代理</label>
            <p className="text-xs text-gray-500">控制大模型请求是否使用下方代理地址</p>
          </div>
          <label className="relative inline-flex items-center cursor-pointer">
            <input
              id="llm-proxy-enabled"
              type="checkbox"
              checked={formData.proxy.enabled}
              onChange={(e) => handleProxyChange({ enabled: e.target.checked })}
              className="sr-only peer"
            />
            <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600" />
          </label>
        </div>

      {formData.proxy.enabled && (
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          {/* HTTP 代理 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              HTTP Proxy
            </label>
            <input
              type="text"
              value={formData.proxy.httpProxy}
              onChange={(e) => handleProxyChange({ httpProxy: e.target.value })}
              className="input-field"
              placeholder="http://127.0.0.1:7890"
            />
          </div>

          {/* HTTPS 代理 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              HTTPS Proxy
            </label>
            <input
              type="text"
              value={formData.proxy.httpsProxy}
              onChange={(e) => handleProxyChange({ httpsProxy: e.target.value })}
              className="input-field"
              placeholder="http://127.0.0.1:7890"
            />
          </div>
        </div>
        )}
      </div>

      <div className="rounded-lg border border-gray-200 p-4">
        <div className="flex items-center justify-between">
          <div>
            <label htmlFor="youtube-proxy-enabled" className="text-sm font-medium text-gray-700">YouTube 上传代理</label>
            <p className="text-xs text-gray-500">控制 Google 授权、播放列表和视频上传请求</p>
          </div>
          <label className="relative inline-flex cursor-pointer items-center">
            <input id="youtube-proxy-enabled" type="checkbox" checked={formData.proxy.youtubeEnabled}
              onChange={event => handleProxyChange({ youtubeEnabled: event.target.checked })} className="sr-only peer" />
            <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600" />
          </label>
        </div>
        {formData.proxy.youtubeEnabled && <div className="mt-4">
          <label htmlFor="youtube-proxy-url" className="mb-2 block text-sm font-medium text-gray-700">YouTube 代理地址</label>
          <input id="youtube-proxy-url" type="text" value={formData.proxy.youtubeProxyUrl}
            onChange={event => handleProxyChange({ youtubeProxyUrl: event.target.value })}
            className="input-field" placeholder="http://127.0.0.1:7897" required />
        </div>}
      </div>
    </div>
  );
}
