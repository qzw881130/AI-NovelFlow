import { useTranslation } from '../../../stores/i18nStore';
import { ASPECT_RATIO_OPTIONS } from '../../../utils';
import type { Novel, PromptTemplate } from '../../../types';

// 模板类型配置
const TEMPLATE_FIELDS = [
  { key: 'stylePromptTemplateId', labelKey: 'novels.stylePromptLabel', hintKey: 'novels.stylePromptHint', templateType: 'style' },
  { key: 'characterParsePromptTemplateId', labelKey: 'novels.characterParsePromptLabel', hintKey: 'novels.characterParsePromptHint', templateType: 'character_parse' },
  { key: 'sceneParsePromptTemplateId', labelKey: 'novels.sceneParsePromptLabel', hintKey: 'novels.sceneParsePromptHint', templateType: 'scene_parse' },
  { key: 'promptTemplateId', labelKey: 'novels.characterPromptLabel', hintKey: 'novels.characterPromptHint', templateType: 'character' },
  { key: 'scenePromptTemplateId', labelKey: 'novels.scenePromptLabel', hintKey: 'novels.scenePromptHint', templateType: 'scene' },
  { key: 'chapterSplitPromptTemplateId', labelKey: 'novels.splitPromptLabel', hintKey: 'novels.splitPromptHint', templateType: 'chapter_split' },
] as const;

interface EditNovelModalProps {
  novel: Novel | null;
  onClose: () => void;
  onSubmit: (e: React.FormEvent) => void;
  setNovel: React.Dispatch<React.SetStateAction<Novel | null>>;
  templatesByType: Record<string, PromptTemplate[]>;
  getTemplateDisplayName: (template: PromptTemplate | undefined) => string;
}

export function EditNovelModal({
  novel,
  onClose,
  onSubmit,
  setNovel,
  templatesByType,
  getTemplateDisplayName,
}: EditNovelModalProps) {
  const { t } = useTranslation();

  const aspectRatioOptions = ASPECT_RATIO_OPTIONS.map(opt => ({
    value: opt.value,
    label: `${opt.value} (${t(opt.labelKey)})`,
    description: t(opt.descKey)
  }));

  if (!novel) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">{t('novels.editNovel')}</h2>
        <form onSubmit={onSubmit} className="space-y-4">
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
            <label className="block text-sm font-medium text-gray-700">{t('novels.descriptionLabel')}</label>
            <textarea
              rows={3}
              value={novel.description || ''}
              onChange={(e) => setNovel({ ...novel, description: e.target.value })}
              className="input-field mt-1"
            />
          </div>
          
          {/* 提示词模板选择 */}
          <div className="border-t pt-4 mt-4">
            <h3 className="text-sm font-medium text-gray-700 mb-3">{t('novels.promptTemplatesSection')}</h3>
            <div className="space-y-3">
              {TEMPLATE_FIELDS.map(field => (
                <div key={field.key}>
                  <label className="block text-sm font-medium text-gray-700">{t(field.labelKey)}</label>
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
          
          <div>
            <label className="block text-sm font-medium text-gray-700">{t('novels.aspectRatioLabel')}</label>
            <select
              value={novel.aspectRatio || '16:9'}
              onChange={(e) => setNovel({ ...novel, aspectRatio: e.target.value })}
              className="input-field mt-1"
            >
              {aspectRatioOptions.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
            <p className="text-xs text-gray-500 mt-1">
              {aspectRatioOptions.find(o => o.value === (novel.aspectRatio || '16:9'))?.description}
            </p>
          </div>
          <div className="flex justify-end gap-3 mt-6">
            <button type="button" onClick={onClose} className="btn-secondary">{t('common.cancel')}</button>
            <button type="submit" className="btn-primary">{t('common.save')}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
