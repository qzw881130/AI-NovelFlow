import { useState } from 'react';
import { useTranslation } from '../../../stores/i18nStore';
import { ASPECT_RATIO_OPTIONS } from '../../../utils';
import type { PromptTemplate } from '../../../types';
import type { NovelFormData } from '../types';

// 模板类型配置
const TEMPLATE_FIELDS = [
  { key: 'stylePromptTemplateId', labelKey: 'novels.stylePromptLabel', hintKey: 'novels.stylePromptHint', templateType: 'style' },
  { key: 'characterParsePromptTemplateId', labelKey: 'novels.characterParsePromptLabel', hintKey: 'novels.characterParsePromptHint', templateType: 'character_parse' },
  { key: 'sceneParsePromptTemplateId', labelKey: 'novels.sceneParsePromptLabel', hintKey: 'novels.sceneParsePromptHint', templateType: 'scene_parse' },
  { key: 'propParsePromptTemplateId', labelKey: 'novels.propParsePromptLabel', hintKey: 'novels.propParsePromptHint', templateType: 'prop_parse' },
  { key: 'promptTemplateId', labelKey: 'novels.characterPromptLabel', hintKey: 'novels.characterPromptHint', templateType: 'character' },
  { key: 'scenePromptTemplateId', labelKey: 'novels.scenePromptLabel', hintKey: 'novels.scenePromptHint', templateType: 'scene' },
  { key: 'propPromptTemplateId', labelKey: 'novels.propPromptLabel', hintKey: 'novels.propPromptHint', templateType: 'prop' },
  { key: 'chapterSplitPromptTemplateId', labelKey: 'novels.splitPromptLabel', hintKey: 'novels.splitPromptHint', templateType: 'chapter_split' },
  { key: 'keyframeDescriptionPromptTemplateId', labelKey: 'novels.keyframeDescriptionPromptLabel', hintKey: 'novels.keyframeDescriptionPromptHint', templateType: 'keyframe_description' },
  { key: 'shotImagePromptTemplateId', labelKey: 'novels.shotImagePromptLabel', hintKey: 'novels.shotImagePromptHint', templateType: 'shot_image_prompt' },
  { key: 'videoModeRecommenderPromptTemplateId', labelKey: 'novels.videoModeRecommenderPromptLabel', hintKey: 'novels.videoModeRecommenderPromptHint', templateType: 'video_mode_recommender' },
  { key: 'keyframePlannerPromptTemplateId', labelKey: 'novels.keyframePlannerPromptLabel', hintKey: 'novels.keyframePlannerPromptHint', templateType: 'keyframe_planner' },
  { key: 'keyframeImagePromptTemplateId', labelKey: 'novels.keyframeImagePromptLabel', hintKey: 'novels.keyframeImagePromptHint', templateType: 'keyframe_image_prompt' },
  { key: 'keyframeTransitionPromptTemplateId', labelKey: 'novels.keyframeTransitionPromptLabel', hintKey: 'novels.keyframeTransitionPromptHint', templateType: 'keyframe_transition' },
  { key: 'h3SingleFramePromptTemplateId', labelKey: 'novels.h3SingleFramePromptLabel', hintKey: 'novels.h3SingleFramePromptHint', templateType: 'h3_single_frame_prompt' },
  { key: 'h3FirstLastFramePromptTemplateId', labelKey: 'novels.h3FirstLastFramePromptLabel', hintKey: 'novels.h3FirstLastFramePromptHint', templateType: 'h3_first_last_frame_prompt' },
  { key: 'h3MultiKeyframePromptTemplateId', labelKey: 'novels.h3MultiKeyframePromptLabel', hintKey: 'novels.h3MultiKeyframePromptHint', templateType: 'h3_multi_keyframe_prompt' },
] as const;

interface CreateNovelModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (e: React.FormEvent) => void;
  formData: NovelFormData;
  setFormData: React.Dispatch<React.SetStateAction<NovelFormData>>;
  templatesByType: Record<string, PromptTemplate[]>;
  getTemplateDisplayName: (template: PromptTemplate | undefined) => string;
}

export function CreateNovelModal({
  isOpen,
  onClose,
  onSubmit,
  formData,
  setFormData,
  templatesByType,
  getTemplateDisplayName,
}: CreateNovelModalProps) {
  const { t } = useTranslation();
  const [showDescription, setShowDescription] = useState(false);

  const aspectRatioOptions = ASPECT_RATIO_OPTIONS.map(opt => ({
    value: opt.value,
    label: `${opt.value} (${t(opt.labelKey)})`,
    description: t(opt.descKey)
  }));

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl w-full max-w-6xl max-h-[92vh] overflow-hidden shadow-2xl flex flex-col">
        <div className="border-b border-gray-100 px-6 py-5">
          <h2 className="text-xl font-semibold text-gray-900">{t('novels.createNovelTitle')}</h2>
          <p className="mt-1 text-sm text-gray-500">基础信息与提示词模板配置</p>
        </div>
        <form onSubmit={onSubmit} className="flex min-h-0 flex-1 flex-col">
          <div className="flex-1 overflow-y-auto px-6 py-5 space-y-6">
            <section className="rounded-xl border border-gray-200 bg-gray-50 p-4">
              <h3 className="text-sm font-semibold text-gray-800 mb-4">基础信息</h3>
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <div>
            <label className="block text-sm font-medium text-gray-700">{t('novels.titleLabel')}</label>
            <input
              type="text"
              required
              value={formData.title}
              onChange={(e) => setFormData({ ...formData, title: e.target.value })}
              className="input-field mt-1"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">{t('novels.authorLabel')}</label>
            <input
              type="text"
              value={formData.author}
              onChange={(e) => setFormData({ ...formData, author: e.target.value })}
              className="input-field mt-1"
            />
          </div>
          <div>
            <div className="flex items-baseline gap-2">
              <label className="text-sm font-medium text-gray-700">{t('novels.aspectRatioLabel')}</label>
              <span className="text-xs font-normal text-gray-400">
                {aspectRatioOptions.find(o => o.value === formData.aspectRatio)?.description}
              </span>
            </div>
            <select
              value={formData.aspectRatio}
              onChange={(e) => setFormData({ ...formData, aspectRatio: e.target.value })}
              className="input-field mt-1"
            >
              {aspectRatioOptions.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </div>
          <div className="lg:col-span-3">
            <div className="flex items-center gap-2">
              <label className="text-sm font-medium text-gray-700">{t('novels.descriptionLabel')}</label>
              <button
                type="button"
                onClick={() => setShowDescription(!showDescription)}
                className="rounded-md px-2 py-0.5 text-xs font-normal text-blue-600 hover:bg-blue-50 hover:text-blue-700"
              >
                {showDescription ? '隐藏' : '显示'}
              </button>
            </div>
            {showDescription && (
              <textarea
                rows={4}
                value={formData.description}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                className="input-field mt-1"
              />
            )}
          </div>
              </div>
            </section>
          
          {/* 提示词模板选择 */}
          <section className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="mb-4 flex items-center justify-between gap-3">
              <h3 className="text-sm font-semibold text-gray-800">{t('novels.promptTemplatesSection')}</h3>
              <span className="rounded-full bg-blue-50 px-2.5 py-1 text-xs text-blue-700">{TEMPLATE_FIELDS.length} 项</span>
            </div>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {TEMPLATE_FIELDS.map(field => (
                <div key={field.key} className="rounded-lg border border-gray-100 bg-gray-50 p-3">
                  <label className="block text-sm font-medium text-gray-800">{t(field.labelKey)}</label>
                  <select
                    value={formData[field.key]}
                    onChange={(e) => setFormData({ ...formData, [field.key]: e.target.value })}
                    className="input-field mt-1"
                  >
                    <option value="">{t('novels.defaultTemplate')}</option>
                    {(templatesByType[field.templateType] || []).map((template) => (
                      <option key={template.id} value={template.id}>
                        {getTemplateDisplayName(template)} {template.isSystem ? t('novels.systemTemplate') : t('novels.customTemplate')}
                      </option>
                    ))}
                  </select>
                  <p className="text-xs text-gray-500 mt-1">{t(field.hintKey)}</p>
                </div>
              ))}
            </div>
          </section>
          </div>
          <div className="flex justify-end gap-3 border-t border-gray-100 bg-white px-6 py-4">
            <button type="button" onClick={onClose} className="btn-secondary">{t('common.cancel')}</button>
            <button type="submit" className="btn-primary">{t('common.create')}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
