import { useState } from 'react';
import { Upload, Plus } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import { toast } from '../../../stores/toastStore';
import { workflowApi } from '../../../api/workflows';
import type { Workflow } from '../types';

interface UploadModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  extensionConfigs: Record<string, any>;
  typeNames: Record<string, string>;
}

export function UploadModal({ isOpen, onClose, onSuccess, extensionConfigs, typeNames }: UploadModalProps) {
  const { t } = useTranslation();
  const [uploadType, setUploadType] = useState<'character' | 'scene' | 'shot' | 'video' | 'transition' | 'prop' | 'voice_design' | 'audio' | 'keyframe_image'>('character');
  const [uploadForm, setUploadForm] = useState({ name: '', description: '', file: null as File | null });
  const [uploadExtension, setUploadExtension] = useState<Record<string, string> | null>(null);
  const [uploading, setUploading] = useState(false);

  // 当上传类型改变时，重置扩展属性
  const handleTypeChange = (type: 'character' | 'scene' | 'shot' | 'video' | 'transition' | 'prop' | 'voice_design' | 'audio' | 'keyframe_image') => {
    setUploadType(type);
    const config = extensionConfigs[type];
    if (config) {
      setUploadExtension({ [config.name]: config.default });
    } else {
      setUploadExtension(null);
    }
  };

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!uploadForm.file) {
      toast.warning(t('systemSettings.workflow.selectFile'));
      return;
    }
    
    setUploading(true);
    const formData = new FormData();
    formData.append('name', uploadForm.name);
    formData.append('type', uploadType);
    formData.append('description', uploadForm.description || '');
    if (uploadExtension) {
      formData.append('extension', JSON.stringify(uploadExtension));
    }
    formData.append('file', uploadForm.file);
    
    try {
      const data = await workflowApi.upload(formData);
      if (data.success) {
        onClose();
        setUploadForm({ name: '', description: '', file: null });
        onSuccess();
      } else {
        let errorMsg = t('systemSettings.workflow.upload') + t('common.failed');
        if (data.detail) {
          if (typeof data.detail === 'string') {
            errorMsg = data.detail;
          } else if (Array.isArray(data.detail)) {
            errorMsg = data.detail.map((e: any) => e.msg || e).join(', ');
          }
        }
        toast.error(errorMsg);
      }
    } catch (error) {
      console.error('上传失败:', error);
      toast.error(t('systemSettings.workflow.upload') + t('common.failed'));
    } finally {
      setUploading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 w-full max-w-md">
        <h3 className="text-lg font-medium mb-4">{t('systemSettings.workflow.upload')}</h3>
        <form onSubmit={handleUpload} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              {t('systemSettings.workflow.type')}
            </label>
            <select
              value={uploadType}
              onChange={(e) => handleTypeChange(e.target.value as any)}
              className="input-field"
            >
              <option value="character">{typeNames.character}</option>
              <option value="scene">{typeNames.scene}</option>
              <option value="shot">{typeNames.shot}</option>
              <option value="keyframe_image">{typeNames.keyframe_image}</option>
              <option value="video">{typeNames.video}</option>
              <option value="transition">{typeNames.transition}</option>
              <option value="prop">{typeNames.prop}</option>
              <option value="voice_design">{typeNames.voice_design}</option>
              <option value="audio">{typeNames.audio}</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              {t('systemSettings.workflow.name')}
            </label>
            <input
              type="text"
              value={uploadForm.name}
              onChange={(e) => setUploadForm({ ...uploadForm, name: e.target.value })}
              className="input-field"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              {t('systemSettings.workflow.description')}
            </label>
            <textarea
              value={uploadForm.description}
              onChange={(e) => setUploadForm({ ...uploadForm, description: e.target.value })}
              className="input-field"
              rows={2}
            />
          </div>
          {/* 扩展属性选择 */}
          {extensionConfigs[uploadType] && uploadExtension && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                {t(extensionConfigs[uploadType].labelKey, { defaultValue: extensionConfigs[uploadType].label })}
              </label>
              <div className="flex gap-2">
                {extensionConfigs[uploadType].options.map((option: any) => (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => {
                      const config = extensionConfigs[uploadType];
                      setUploadExtension({ [config.name]: option.value });
                    }}
                    className={`flex-1 py-2 px-3 rounded-lg text-sm font-medium transition-colors ${
                      uploadExtension[extensionConfigs[uploadType].name] === option.value
                        ? 'bg-primary-500 text-white'
                        : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                    }`}
                  >
                    {t(option.labelKey, { defaultValue: option.label })}
                  </button>
                ))}
              </div>
            </div>
          )}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              {t('systemSettings.workflow.file')}
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                value={uploadForm.file?.name || ''}
                className="input-field flex-1 bg-gray-50"
                placeholder={t('systemSettings.workflow.selectFile')}
                readOnly
              />
              <label className="btn-secondary cursor-pointer flex items-center gap-2 whitespace-nowrap">
                <Upload className="h-4 w-4" />
                {t('systemSettings.workflow.selectFile')}
                <input
                  type="file"
                  accept=".json"
                  onChange={(e) => setUploadForm({ ...uploadForm, file: e.target.files?.[0] || null })}
                  className="hidden"
                  required
                />
              </label>
            </div>
            <p className="mt-1 text-xs text-gray-500">
              {t('systemSettings.workflow.comfyUIJsonTip')}
            </p>
          </div>
          <div className="flex justify-end gap-3">
            <button
              type="button"
              onClick={onClose}
              className="btn-secondary"
            >
              {t('common.cancel')}
            </button>
            <button
              type="submit"
              disabled={uploading}
              className="btn-primary"
            >
              {uploading ? t('common.loading') : t('common.upload')}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
