/**
 * 场景卡片组件
 */
import { Loader2, MapPin, Trash2, Edit2, Upload, Wand2, Sparkles, ImagePlus } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import type { Scene, PromptTemplate } from '../../../types';
import type { ScenePrompt } from '../types';

interface SceneCardProps {
  scene: Scene;
  highlightedId: string | null;
  generatingId: string | null;
  generatingSettingId: string | null;
  uploadingId: string | null;
  scenePrompt?: ScenePrompt;
  templateDisplayName: string;
  onDelete: (id: string) => void;
  onEdit: (scene: Scene) => void;
  onGenerateImage: (scene: Scene) => void;
  onGenerateSetting: (scene: Scene) => void;
  onUploadImage: (sceneId: string) => void;
  onEditImage: (scene: Scene) => void;
  onImageClick: (url: string, name: string, sceneId: string) => void;
}

export function SceneCard({
  scene,
  highlightedId,
  generatingId,
  generatingSettingId,
  uploadingId,
  scenePrompt,
  templateDisplayName,
  onDelete,
  onEdit,
  onGenerateImage,
  onGenerateSetting,
  onUploadImage,
  onEditImage,
  onImageClick,
}: SceneCardProps) {
  const { t } = useTranslation();

  return (
    <div
      id={`scene-${scene.id}`}
      className={`bg-white rounded-lg shadow-sm border overflow-hidden hover:shadow-md transition-all group ${
        highlightedId === scene.id 
          ? 'ring-4 ring-blue-500 ring-opacity-50 border-blue-500 animate-pulse' 
          : 'border-gray-200'
      }`}
    >
      {/* Scene Image */}
      <div className="relative aspect-video bg-gray-100 w-full">
        {scene.imageUrl ? (
          <img
            src={scene.imageUrl}
            alt={scene.name}
            className="w-full h-full object-cover cursor-pointer"
            onClick={() => onImageClick(scene.imageUrl!, scene.name, scene.id)}
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center">
            <MapPin className="h-20 w-20 text-gray-300" />
          </div>
        )}

        {scene.imageUrl && (
          <button
            onClick={() => onEditImage(scene)}
            className="absolute top-2 left-2 p-2 bg-white/90 rounded-lg text-gray-500 hover:text-primary-600 hover:bg-primary-50 transition-colors opacity-0 group-hover:opacity-100"
            title={t('scenes.editImage')}
          >
            <ImagePlus className="h-4 w-4" />
          </button>
        )}
        
        {/* Status Badge */}
        {scene.generatingStatus === 'running' && (
          <div className="absolute top-2 left-2 px-2 py-1 bg-blue-500 text-white text-xs rounded-full flex items-center gap-1">
            <Loader2 className="h-3 w-3 animate-spin" />
            {t('scenes.generating')}
          </div>
        )}
        {scene.generatingStatus === 'failed' && (
          <div className="absolute top-2 left-2 px-2 py-1 bg-red-500 text-white text-xs rounded-full">
            {t('scenes.generateFailed')}
          </div>
        )}
        
        {/* Delete Button - 右上角 */}
        <button
          onClick={() => onDelete(scene.id)}
          className="absolute top-2 right-2 p-2 bg-white/90 rounded-lg text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors opacity-0 group-hover:opacity-100"
          title={t('common.delete')}
        >
          <Trash2 className="h-4 w-4" />
        </button>
        
        {/* Edit Button - 左下角 */}
        <button
          onClick={() => onEdit(scene)}
          className="absolute bottom-2 left-2 p-2 bg-white/90 rounded-lg text-gray-400 hover:text-blue-600 hover:bg-blue-50 transition-colors opacity-0 group-hover:opacity-100"
          title={t('common.edit')}
        >
          <Edit2 className="h-4 w-4" />
        </button>
        
        {/* 上传按钮 */}
        <button
          onClick={() => onUploadImage(scene.id)}
          disabled={uploadingId === scene.id}
          className="absolute bottom-2 left-12 p-2 bg-white/90 rounded-lg text-gray-400 hover:text-green-600 hover:bg-green-50 transition-colors disabled:opacity-70 opacity-0 group-hover:opacity-100"
          title={t('scenes.uploadImage')}
        >
          {uploadingId === scene.id ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Upload className="h-4 w-4" />
          )}
        </button>
        
        {/* AI生成场景图 Button */}
        <button
          onClick={() => onGenerateImage(scene)}
          disabled={generatingId === scene.id || scene.generatingStatus === 'pending' || scene.generatingStatus === 'running'}
          className="absolute bottom-2 right-2 flex items-center gap-1 px-3 py-1.5 bg-green-600/90 hover:bg-green-700 text-white rounded-lg transition-colors disabled:opacity-70 opacity-0 group-hover:opacity-100 text-xs"
          title={scene.generatingStatus === 'pending' || scene.generatingStatus === 'running' ? t('scenes.generatingStatus') : (scene.imageUrl ? t('scenes.regenerate') : t('scenes.generateImage'))}
        >
          {scene.generatingStatus === 'pending' || scene.generatingStatus === 'running' || generatingId === scene.id ? (
            <>
              <Loader2 className="h-3 w-3 animate-spin" />
              <span>{scene.generatingStatus === 'pending' ? t('scenes.pendingGeneration') : t('scenes.generatingStatus')}</span>
            </>
          ) : (
            <>
              <Wand2 className="h-3 w-3" />
              <span>AI{t('scenes.generateImage')}</span>
            </>
          )}
        </button>
        
        {/* Loading Overlay */}
        {generatingId === scene.id && (
          <div className="absolute inset-0 bg-black bg-opacity-50 flex items-center justify-center">
            <div className="text-center">
              <Loader2 className="h-8 w-8 animate-spin text-white mx-auto" />
              <p className="text-white text-sm mt-2">{t('scenes.generating')}</p>
            </div>
          </div>
        )}
      </div>

      {/* Scene Info */}
      <div className="p-4">
        <h3 className="text-lg font-semibold text-gray-900 truncate">
          {scene.name}
        </h3>
        
        {/* 场景描述 */}
        {scene.description && (
          <div className="mt-3">
            <p className="text-xs text-gray-400 mb-1">{t('scenes.descriptionLabel')}</p>
            <div className="text-sm text-gray-600 max-h-20 overflow-y-auto pr-1 scrollbar-thin">
              {scene.description}
            </div>
          </div>
        )}
        
        {/* 环境设定 */}
        {scene.setting ? (
          <div className="mt-3">
            <p className="text-xs text-gray-400 mb-1">{t('scenes.setting')}</p>
            <div className="text-xs text-gray-500 bg-gray-50 rounded p-2 max-h-24 overflow-y-auto scrollbar-thin">
              {scene.setting}
            </div>
          </div>
        ) : (
          <div className="mt-3">
            <button
              onClick={() => onGenerateSetting(scene)}
              disabled={generatingSettingId === scene.id || !scene.description}
              className="text-xs inline-flex items-center text-primary-600 hover:text-primary-700 disabled:opacity-50"
            >
              {generatingSettingId === scene.id ? (
                <>
                  <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                  {t('scenes.generatingStatus')}
                </>
              ) : (
                <>
                  <Sparkles className="h-3 w-3 mr-1" />
                  {t('scenes.generateSetting')}
                </>
              )}
            </button>
          </div>
        )}

        {/* 生成提示词 */}
        {scenePrompt && (
          <div className="mt-3 pt-3 border-t border-gray-100">
            <div className="flex items-center justify-between mb-1">
              <p className="text-xs text-gray-400">{t('scenes.promptLabel')}</p>
              <span className="text-xs text-gray-400">{templateDisplayName}</span>
            </div>
            <div className="text-xs text-gray-500 bg-gray-50 rounded p-2 max-h-20 overflow-y-auto scrollbar-thin font-mono">
              {scenePrompt.prompt}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
