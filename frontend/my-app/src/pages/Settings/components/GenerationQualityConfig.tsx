import { useTranslation } from '../../../stores/i18nStore';

export default function GenerationQualityConfig({ enabled, onChange, language, onLanguageChange, showFirstAppearanceNames, onShowFirstAppearanceNamesChange }: {
  enabled: boolean;
  onChange: (enabled: boolean) => void;
  language: 'en' | 'zh';
  onLanguageChange: (language: 'en' | 'zh') => void;
  showFirstAppearanceNames: boolean;
  onShowFirstAppearanceNamesChange: (enabled: boolean) => void;
}) {
  const { t } = useTranslation();
  return <section className="space-y-4" aria-labelledby="image-quality-review-heading">
    <h3 id="image-quality-review-heading" className="font-semibold text-gray-900">{t('systemSettings.imageQualityReview')}</h3>
    <label className="flex items-start gap-3 rounded-lg border border-gray-200 p-4 text-sm">
      <input type="checkbox" checked={enabled} onChange={event => onChange(event.target.checked)} className="mt-1" />
      <span>
        <span className="block font-medium text-gray-800">{t('systemSettings.autoImageReview')}</span>
        <span className="mt-1 block max-w-3xl text-sm leading-6 text-gray-500">{t('systemSettings.autoImageReviewDesc')}</span>
      </span>
    </label>
    <div className="rounded-lg border border-gray-200 p-4">
      <label htmlFor="video-prompt-language" className="block text-sm font-medium text-gray-800">
        {t('systemSettings.videoPromptLanguage')}
      </label>
      <select id="video-prompt-language" value={language}
        onChange={event => onLanguageChange(event.target.value as 'en' | 'zh')}
        className="mt-3 w-full max-w-xs rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm">
        <option value="en">{t('systemSettings.videoPromptEnglish')}</option>
        <option value="zh">{t('systemSettings.videoPromptChinese')}</option>
      </select>
      <p className="mt-2 max-w-3xl text-sm leading-6 text-gray-500">{t('systemSettings.videoPromptLanguageDesc')}</p>
    </div>
    <label className="flex items-start gap-3 rounded-lg border border-gray-200 p-4 text-sm">
      <input type="checkbox" checked={showFirstAppearanceNames}
        onChange={event => onShowFirstAppearanceNamesChange(event.target.checked)} className="mt-1" />
      <span>
        <span className="block font-medium text-gray-800">{t('systemSettings.showFirstAppearanceNames')}</span>
        <span className="mt-1 block max-w-3xl text-sm leading-6 text-gray-500">{t('systemSettings.showFirstAppearanceNamesDesc')}</span>
      </span>
    </label>
  </section>;
}
