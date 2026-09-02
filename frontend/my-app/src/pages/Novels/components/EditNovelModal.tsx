import { useState } from 'react';
import { Download } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import { ASPECT_RATIO_OPTIONS } from '../../../utils';
import { novelApi } from '../../../api/novels';
import { toast } from '../../../stores/toastStore';
import type { Novel, PromptTemplate } from '../../../types';

// 模板类型配置
const TEMPLATE_FIELDS = [
  { key: 'stylePromptTemplateId', labelKey: 'novels.stylePromptLabel', hintKey: 'novels.stylePromptHint', templateType: 'style', category: 'style_design' },
  { key: 'characterParsePromptTemplateId', labelKey: 'novels.characterParsePromptLabel', hintKey: 'novels.characterParsePromptHint', templateType: 'character_parse', category: 'asset_parse' },
  { key: 'sceneParsePromptTemplateId', labelKey: 'novels.sceneParsePromptLabel', hintKey: 'novels.sceneParsePromptHint', templateType: 'scene_parse', category: 'asset_parse' },
  { key: 'propParsePromptTemplateId', labelKey: 'novels.propParsePromptLabel', hintKey: 'novels.propParsePromptHint', templateType: 'prop_parse', category: 'asset_parse' },
  { key: 'promptTemplateId', labelKey: 'novels.characterPromptLabel', hintKey: 'novels.characterPromptHint', templateType: 'character', category: 'asset_generation' },
  { key: 'scenePromptTemplateId', labelKey: 'novels.scenePromptLabel', hintKey: 'novels.scenePromptHint', templateType: 'scene', category: 'asset_generation' },
  { key: 'propPromptTemplateId', labelKey: 'novels.propPromptLabel', hintKey: 'novels.propPromptHint', templateType: 'prop', category: 'asset_generation' },
  { key: 'chapterSplitPromptTemplateId', labelKey: 'novels.splitPromptLabel', hintKey: 'novels.splitPromptHint', templateType: 'chapter_split', category: 'shot_planning' },
  { key: 'keyframeDescriptionPromptTemplateId', labelKey: 'novels.keyframeDescriptionPromptLabel', hintKey: 'novels.keyframeDescriptionPromptHint', templateType: 'keyframe_description', category: 'shot_planning' },
  { key: 'shotImagePromptTemplateId', labelKey: 'novels.shotImagePromptLabel', hintKey: 'novels.shotImagePromptHint', templateType: 'shot_image_prompt', category: 'shot_image' },
  { key: 'videoModeRecommenderPromptTemplateId', labelKey: 'novels.videoModeRecommenderPromptLabel', hintKey: 'novels.videoModeRecommenderPromptHint', templateType: 'video_mode_recommender', category: 'video_director' },
  { key: 'keyframePlannerPromptTemplateId', labelKey: 'novels.keyframePlannerPromptLabel', hintKey: 'novels.keyframePlannerPromptHint', templateType: 'keyframe_planner', category: 'video_director' },
  { key: 'keyframeTransitionPromptTemplateId', labelKey: 'novels.keyframeTransitionPromptLabel', hintKey: 'novels.keyframeTransitionPromptHint', templateType: 'keyframe_transition', category: 'video_director' },
  { key: 'keyframeImagePromptTemplateId', labelKey: 'novels.keyframeImagePromptLabel', hintKey: 'novels.keyframeImagePromptHint', templateType: 'keyframe_image_prompt', category: 'keyframe_image' },
  { key: 'h3SingleFramePromptTemplateId', labelKey: 'novels.h3SingleFramePromptLabel', hintKey: 'novels.h3SingleFramePromptHint', templateType: 'h3_single_frame_prompt', category: 'video_generation' },
  { key: 'h3FirstLastFramePromptTemplateId', labelKey: 'novels.h3FirstLastFramePromptLabel', hintKey: 'novels.h3FirstLastFramePromptHint', templateType: 'h3_first_last_frame_prompt', category: 'video_generation' },
  { key: 'h3MultiKeyframePromptTemplateId', labelKey: 'novels.h3MultiKeyframePromptLabel', hintKey: 'novels.h3MultiKeyframePromptHint', templateType: 'h3_multi_keyframe_prompt', category: 'video_generation' },
] as const;

const TEMPLATE_CATEGORIES = [
  { key: 'style_design', labelKey: 'promptConfig.categories.styleDesign' },
  { key: 'asset_parse', labelKey: 'promptConfig.categories.assetParse' },
  { key: 'asset_generation', labelKey: 'promptConfig.categories.assetGeneration' },
  { key: 'shot_planning', labelKey: 'promptConfig.categories.shotPlanning' },
  { key: 'shot_image', labelKey: 'promptConfig.categories.shotImage' },
  { key: 'video_director', labelKey: 'promptConfig.categories.videoDirector' },
  { key: 'keyframe_image', labelKey: 'promptConfig.categories.keyframeImage' },
  { key: 'video_generation', labelKey: 'promptConfig.categories.videoGeneration' },
] as const;

interface EditNovelModalProps {
  novel: Novel | null;
  onClose: () => void;
  onSubmit: (e: React.FormEvent) => void;
  setNovel: React.Dispatch<React.SetStateAction<Novel | null>>;
  templatesByType: Record<string, PromptTemplate[]>;
  getTemplateDisplayName: (template: PromptTemplate | undefined) => string;
  referenceNovels?: Novel[];
}

export function EditNovelModal({
  novel,
  onClose,
  onSubmit,
  setNovel,
  templatesByType,
  getTemplateDisplayName,
  referenceNovels = [],
}: EditNovelModalProps) {
  const { t } = useTranslation();
  const [isExportingTemplates, setIsExportingTemplates] = useState(false);
  const [showDescription, setShowDescription] = useState(false);

  const aspectRatioOptions = ASPECT_RATIO_OPTIONS.map(opt => ({
    value: opt.value,
    label: `${opt.value} (${t(opt.labelKey)})`,
    description: t(opt.descKey)
  }));

  if (!novel) return null;

  const applyReferenceNovel = (novelId: string) => {
    const referenceNovel = referenceNovels.find((item) => item.id === novelId);
    if (!referenceNovel) return;
    setNovel({
      ...novel,
      ...Object.fromEntries(TEMPLATE_FIELDS.map((field) => [field.key, (referenceNovel as any)[field.key] || ''])),
    });
  };

  const handleExportPromptTemplates = async () => {
    setIsExportingTemplates(true);
    try {
      const templateIds = Object.fromEntries(
        TEMPLATE_FIELDS.map((field) => [field.key, (novel as any)[field.key] || ''])
      );
      await novelApi.exportPromptTemplates(novel.id, templateIds);
      toast.success('提示词模板已打包下载');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '导出提示词模板失败');
    } finally {
      setIsExportingTemplates(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl w-full max-w-6xl max-h-[92vh] overflow-hidden shadow-2xl flex flex-col">
        <div className="border-b border-gray-100 px-6 py-5">
          <h2 className="text-xl font-semibold text-gray-900">{t('novels.editNovel')}</h2>
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
              value={novel.title}
              onChange={(e) => setNovel({ ...novel, title: e.target.value })}
              className="input-field mt-1"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">{t('novels.authorLabel')}</label>
            <input
              type="text"
              value={novel.author}
              onChange={(e) => setNovel({ ...novel, author: e.target.value })}
              className="input-field mt-1"
            />
          </div>
          <div>
            <div className="flex items-baseline gap-2">
              <label className="text-sm font-medium text-gray-700">{t('novels.aspectRatioLabel')}</label>
              <span className="text-xs font-normal text-gray-400">
                {aspectRatioOptions.find(o => o.value === (novel.aspectRatio || '16:9'))?.description}
              </span>
            </div>
            <select
              value={novel.aspectRatio || '16:9'}
              onChange={(e) => setNovel({ ...novel, aspectRatio: e.target.value })}
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
                value={novel.description || ''}
                onChange={(e) => setNovel({ ...novel, description: e.target.value })}
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
              <div className="flex items-center gap-3">
                <label className="flex items-center gap-2 text-sm text-gray-600">
                  <span className="whitespace-nowrap">快速参考</span>
                  <select
                    value=""
                    onChange={(e) => applyReferenceNovel(e.target.value)}
                    className="input-field h-9 min-w-[220px] py-1 text-sm"
                  >
                    <option value="">选择其他小说...</option>
                    {referenceNovels.filter((item) => item.id !== novel.id).map((item) => (
                      <option key={item.id} value={item.id}>{item.title}</option>
                    ))}
                  </select>
                </label>
                <span className="rounded-full bg-blue-50 px-2.5 py-1 text-xs text-blue-700">{TEMPLATE_FIELDS.length} 项</span>
              </div>
            </div>
            <div className="space-y-4">
              {TEMPLATE_CATEGORIES.map(category => {
                const fields = TEMPLATE_FIELDS.filter(field => field.category === category.key);
                if (!fields.length) return null;
                return (
                  <div key={category.key} className="rounded-xl border border-gray-100 bg-gray-50 p-3">
                    <div className="mb-3 flex items-center justify-between gap-2">
                      <h4 className="text-sm font-semibold text-gray-800">{t(category.labelKey)}</h4>
                      <span className="text-xs text-gray-400">{fields.length} 项</span>
                    </div>
                    <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
                      {fields.map(field => (
                        <div key={field.key} className="rounded-lg border border-gray-100 bg-white p-3">
                          <label className="block text-sm font-medium text-gray-800">{t(field.labelKey)}</label>
                          <select
                            value={(novel as any)[field.key] || ''}
                            onChange={(e) => setNovel({ ...novel, [field.key]: e.target.value })}
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
                  </div>
                );
              })}
            </div>
          </section>
          </div>
          <div className="flex items-center justify-between gap-3 border-t border-gray-100 bg-white px-6 py-4">
            <button
              type="button"
              onClick={handleExportPromptTemplates}
              disabled={isExportingTemplates}
              className="inline-flex items-center gap-2 rounded-lg bg-orange-500 px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-orange-600 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Download className="h-4 w-4" />
              {isExportingTemplates ? '打包中...' : '打包所有提示词模板'}
            </button>
            <div className="flex justify-end gap-3">
              <button type="button" onClick={onClose} className="btn-secondary">{t('common.cancel')}</button>
              <button type="submit" className="btn-primary">{t('common.save')}</button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
