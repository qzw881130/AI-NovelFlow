/**
 * 道具卡片组件
 */
import { Loader2, Package, Trash2, Edit2, Upload, Wand2, Sparkles, ImagePlus } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import type { Prop } from '../../../types';
import type { PropPrompt } from '../types';
import { ASPECT_RATIO_CLASSES } from '../constants';

interface PropCardProps {
  prop: Prop;
  aspectRatio: string;
  highlightedId: string | null;
  generatingId: string | null;
  generatingAppearanceId: string | null;
  uploadingId: string | null;
  propPrompt?: PropPrompt;
  templateDisplayName: string;
  onDelete: (id: string) => void;
  onEdit: (prop: Prop) => void;
  onGenerateImage: (prop: Prop) => void;
  onGenerateAppearance: (prop: Prop) => void;
  onUploadImage: (propId: string) => void;
  onEditImage: (prop: Prop) => void;
  onImageClick: (url: string, name: string, propId: string) => void;
}

export function PropCard({
  prop,
  aspectRatio,
  highlightedId,
  generatingId,
  generatingAppearanceId,
  uploadingId,
  propPrompt,
  templateDisplayName,
  onDelete,
  onEdit,
  onGenerateImage,
  onGenerateAppearance,
  onUploadImage,
  onEditImage,
  onImageClick,
}: PropCardProps) {
  const { t } = useTranslation();
  const aspectClass = ASPECT_RATIO_CLASSES[aspectRatio] || 'aspect-square';

  return (
    <div
      id={`prop-${prop.id}`}
      className={`bg-white rounded-lg shadow-sm border overflow-hidden hover:shadow-md transition-all group ${
        highlightedId === prop.id
          ? 'ring-4 ring-blue-500 ring-opacity-50 border-blue-500 animate-pulse'
          : 'border-gray-200'
      }`}
    >
      {/* Prop Image */}
      <div className={`${aspectClass} bg-gray-100 relative w-full`}>
        {prop.imageUrl ? (
          <img
            src={prop.imageUrl}
            alt={prop.name}
            className="w-full h-full object-cover cursor-pointer"
            onClick={() => onImageClick(prop.imageUrl!, prop.name, prop.id)}
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center">
            <Package className="h-20 w-20 text-gray-300" />
          </div>
        )}

        {prop.imageUrl && (
          <button
            onClick={() => onEditImage(prop)}
            className="absolute top-2 left-2 p-2 bg-white/90 rounded-lg text-gray-500 hover:text-primary-600 hover:bg-primary-50 transition-colors opacity-0 group-hover:opacity-100"
            title={t('props.editImage')}
          >
            <ImagePlus className="h-4 w-4" />
          </button>
        )}

        {/* Status Badge */}
        {prop.generatingStatus === 'running' && (
          <div className="absolute top-2 left-2 px-2 py-1 bg-blue-500 text-white text-xs rounded-full flex items-center gap-1">
            <Loader2 className="h-3 w-3 animate-spin" />
            {t('props.generating')}
          </div>
        )}
        {prop.generatingStatus === 'failed' && (
          <div className="absolute top-2 left-2 px-2 py-1 bg-red-500 text-white text-xs rounded-full">
            {t('props.generateFailed')}
          </div>
        )}

        {/* Delete Button - 右上角 */}
        <button
          onClick={() => onDelete(prop.id)}
          className="absolute top-2 right-2 p-2 bg-white/90 rounded-lg text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors opacity-0 group-hover:opacity-100"
          title={t('common.delete')}
        >
          <Trash2 className="h-4 w-4" />
        </button>

        {/* Edit Button - 左下角 */}
        <button
          onClick={() => onEdit(prop)}
          className="absolute bottom-2 left-2 p-2 bg-white/90 rounded-lg text-gray-400 hover:text-blue-600 hover:bg-blue-50 transition-colors opacity-0 group-hover:opacity-100"
          title={t('common.edit')}
        >
          <Edit2 className="h-4 w-4" />
        </button>

        {/* 上传按钮 */}
        <button
          onClick={() => onUploadImage(prop.id)}
          disabled={uploadingId === prop.id}
          className="absolute bottom-2 left-12 p-2 bg-white/90 rounded-lg text-gray-400 hover:text-green-600 hover:bg-green-50 transition-colors disabled:opacity-70 opacity-0 group-hover:opacity-100"
          title={t('props.uploadImage')}
        >
          {uploadingId === prop.id ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Upload className="h-4 w-4" />
          )}
        </button>

        {/* AI生成道具图 Button */}
        <button
          onClick={() => onGenerateImage(prop)}
          disabled={generatingId === prop.id || prop.generatingStatus === 'pending' || prop.generatingStatus === 'running'}
          className="absolute bottom-2 right-2 flex items-center gap-1 px-3 py-1.5 bg-amber-600/90 hover:bg-amber-700 text-white rounded-lg transition-colors disabled:opacity-70 opacity-0 group-hover:opacity-100 text-xs"
          title={prop.generatingStatus === 'pending' || prop.generatingStatus === 'running' ? t('props.generatingStatus') : (prop.imageUrl ? t('props.regenerate') : t('props.generateImage'))}
        >
          {prop.generatingStatus === 'pending' || prop.generatingStatus === 'running' || generatingId === prop.id ? (
            <>
              <Loader2 className="h-3 w-3 animate-spin" />
              <span>{prop.generatingStatus === 'pending' ? t('props.pendingGeneration') : t('props.generatingStatus')}</span>
            </>
          ) : (
            <>
              <Wand2 className="h-3 w-3" />
              <span>AI{t('props.generateImage')}</span>
            </>
          )}
        </button>

        {/* Loading Overlay */}
        {generatingId === prop.id && (
          <div className="absolute inset-0 bg-black bg-opacity-50 flex items-center justify-center">
            <div className="text-center">
              <Loader2 className="h-8 w-8 animate-spin text-white mx-auto" />
              <p className="text-white text-sm mt-2">{t('props.generating')}</p>
            </div>
          </div>
        )}
      </div>

      {/* Prop Info */}
      <div className="p-4">
        <h3 className="text-lg font-semibold text-gray-900 truncate">
          {prop.name}
        </h3>

        {/* 道具描述 */}
        {prop.description && (
          <div className="mt-3">
            <p className="text-xs text-gray-400 mb-1">{t('props.descriptionLabel')}</p>
            <div className="text-sm text-gray-600 max-h-20 overflow-y-auto pr-1 scrollbar-thin">
              {prop.description}
            </div>
          </div>
        )}

        {/* 外观描述 */}
        {prop.appearance ? (
          <div className="mt-3">
            <p className="text-xs text-gray-400 mb-1">{t('props.appearance')}</p>
            <div className="text-xs text-gray-500 bg-gray-50 rounded p-2 max-h-24 overflow-y-auto scrollbar-thin">
              {prop.appearance}
            </div>
          </div>
        ) : (
          <div className="mt-3">
            <button
              onClick={() => onGenerateAppearance(prop)}
              disabled={generatingAppearanceId === prop.id || !prop.description}
              className="text-xs inline-flex items-center text-primary-600 hover:text-primary-700 disabled:opacity-50"
            >
              {generatingAppearanceId === prop.id ? (
                <>
                  <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                  {t('props.generatingStatus')}
                </>
              ) : (
                <>
                  <Sparkles className="h-3 w-3 mr-1" />
                  {t('props.generateAppearance')}
                </>
              )}
            </button>
          </div>
        )}

        {/* 生成提示词 */}
        {propPrompt && (
          <div className="mt-3 pt-3 border-t border-gray-100">
            <div className="flex items-center justify-between mb-1">
              <p className="text-xs text-gray-400">{t('props.promptLabel')}</p>
              <span className="text-xs text-gray-400">{templateDisplayName}</span>
            </div>
            <div className="text-xs text-gray-500 bg-gray-50 rounded p-2 max-h-20 overflow-y-auto scrollbar-thin font-mono">
              {propPrompt.prompt}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
