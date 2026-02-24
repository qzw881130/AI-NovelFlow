// ComfyUI 配置组件

import { Server } from 'lucide-react';
import { useTranslation } from '../../stores/i18nStore';
import type { SettingsFormData } from './types';

interface ComfyUIConfigProps {
  formData: SettingsFormData;
  onFormDataChange: (data: SettingsFormData) => void;
  onUserModified: () => void;
}

export default function ComfyUIConfig({ formData, onFormDataChange, onUserModified }: ComfyUIConfigProps) {
  const { t } = useTranslation();

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 p-4 bg-green-50 rounded-lg">
        <Server className="h-5 w-5 text-green-600" />
        <div>
          <h3 className="text-sm font-medium text-green-900">{t('systemSettings.comfyUISettings')}</h3>
          <p className="text-xs text-green-700">
            {t('systemSettings.subtitle')}
          </p>
        </div>
      </div>

      {/* ComfyUI Host */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          {t('systemSettings.comfyUIHost')}
        </label>
        <input
          type="text"
          value={formData.comfyUIHost}
          onChange={(e) => { onUserModified(); onFormDataChange({ ...formData, comfyUIHost: e.target.value }); }}
          className="input-field"
          placeholder="http://localhost:8188"
        />
        <p className="mt-1 text-xs text-gray-500">
          ComfyUI 服务的地址和端口
        </p>
      </div>
    </div>
  );
}
