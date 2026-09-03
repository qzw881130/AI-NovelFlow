// ComfyUI 配置组件

import { useState, useEffect, useRef } from 'react';
import { Server, CheckCircle, XCircle, Loader2 } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import type { SettingsFormData } from '../types';
import { healthApi } from '../../../api/health';

interface ComfyUIConfigProps {
  formData: SettingsFormData;
  onFormDataChange: (data: SettingsFormData) => void;
  onUserModified: () => void;
}

export default function ComfyUIConfig({ formData, onFormDataChange, onUserModified }: ComfyUIConfigProps) {
  const { t } = useTranslation();
  const [checking, setChecking] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<'success' | 'failed' | null>(null);
  const initialCheckDone = useRef(false);

  // 组件挂载时检查一次连接状态
  useEffect(() => {
    if (!initialCheckDone.current && formData.comfyUIHost) {
      initialCheckDone.current = true;
      checkConnection();
    }
  }, [formData.comfyUIHost]);

  const checkConnection = async () => {
    setChecking(true);
    setConnectionStatus(null);
    try {
      const data = await healthApi.getComfyUIStatus();
      if (data.status === 'ok') {
        setConnectionStatus('success');
      } else {
        setConnectionStatus('failed');
      }
    } catch (error) {
      setConnectionStatus('failed');
    } finally {
      setChecking(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 p-4 bg-blue-50 rounded-lg">
        <Server className="h-5 w-5 text-blue-600" />
        <div>
          <h3 className="text-sm font-medium text-blue-900">{t('systemSettings.comfyUISettings')}</h3>
          <p className="text-xs text-blue-700">
            {t('systemSettings.subtitle')}
          </p>
        </div>
      </div>

      {/* ComfyUI Host */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          {t('systemSettings.comfyUIHost')}
        </label>
        <div className="flex gap-3">
          <input
            type="text"
            value={formData.comfyUIHost}
            onChange={(e) => { onUserModified(); onFormDataChange({ ...formData, comfyUIHost: e.target.value }); }}
            className="input-field flex-1"
            placeholder="http://127.0.0.1:8188"
          />
          <button
            type="button"
            onClick={checkConnection}
            disabled={checking || !formData.comfyUIHost}
            className="btn-secondary flex items-center gap-2 whitespace-nowrap"
          >
            {checking ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                {t('common.loading')}
              </>
            ) : (
              t('systemSettings.testConnection')
            )}
          </button>
        </div>
        <p className="mt-1 text-xs text-gray-500">
          {t('systemSettings.comfyUIHostHint')}
        </p>

        {/* 连接状态显示 */}
        {connectionStatus && (
          <div className={`mt-3 flex items-center gap-2 p-3 rounded-lg ${
            connectionStatus === 'success' 
              ? 'bg-green-50 text-green-700' 
              : 'bg-red-50 text-red-700'
          }`}>
            {connectionStatus === 'success' ? (
              <>
                <CheckCircle className="h-4 w-4" />
                <span className="text-sm font-medium">{t('systemSettings.connectionSuccess')}</span>
              </>
            ) : (
              <>
                <XCircle className="h-4 w-4" />
                <span className="text-sm font-medium">{t('systemSettings.connectionFailed')}</span>
              </>
            )}
          </div>
        )}
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          ComfyUI 超时时间
        </label>
        <select
          value={formData.comfyUITimeout || 900}
          onChange={(e) => { onUserModified(); onFormDataChange({ ...formData, comfyUITimeout: Number(e.target.value) }); }}
          className="input-field max-w-xs"
        >
          <option value={900}>15 分钟</option>
          <option value={1200}>20 分钟</option>
          <option value={1800}>30 分钟</option>
        </select>
        <p className="mt-1 text-xs text-gray-500">
          用于视频等长任务完成后，等待后端保存结果的超时阈值。
        </p>
      </div>
    </div>
  );
}
