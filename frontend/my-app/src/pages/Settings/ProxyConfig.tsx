// 代理配置组件

import { Network } from 'lucide-react';
import { useTranslation } from '../../stores/i18nStore';
import type { SettingsFormData } from './types';
import type { ProxyConfig } from '../../types';

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
      proxy: { ...(formData.proxy || { enabled: false, httpProxy: '', httpsProxy: '' }), ...updates },
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

      {/* 启用代理开关 */}
      <div className="flex items-center justify-between p-4 border border-gray-200 rounded-lg">
        <div>
          <label className="text-sm font-medium text-gray-700">{t('systemSettings.enableProxy')}</label>
          <p className="text-xs text-gray-500">{t('systemSettings.proxySettings')}</p>
        </div>
        <label className="relative inline-flex items-center cursor-pointer">
          <input
            type="checkbox"
            checked={formData.proxy?.enabled || false}
            onChange={(e) => handleProxyChange({ enabled: e.target.checked })}
            className="sr-only peer"
          />
          <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
        </label>
      </div>

      {formData.proxy?.enabled && (
        <>
          {/* HTTP 代理 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              HTTP Proxy
            </label>
            <input
              type="text"
              value={formData.proxy?.httpProxy || ''}
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
              value={formData.proxy?.httpsProxy || ''}
              onChange={(e) => handleProxyChange({ httpsProxy: e.target.value })}
              className="input-field"
              placeholder="http://127.0.0.1:7890"
            />
          </div>
        </>
      )}
    </div>
  );
}
