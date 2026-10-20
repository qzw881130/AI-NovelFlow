import { useTranslation } from '../../../stores/i18nStore';
import type { GenerationCheck } from '../../../api/config';

export default function GenerationQualityConfig({ enabled, onChange, language, onLanguageChange, nameplateAvailable, autoApproveNameplateAvailable, showFirstAppearanceNames, onShowFirstAppearanceNamesChange, autoApproveFirstAppearanceNames, onAutoApproveFirstAppearanceNamesChange, checks, policy, onPolicyChange }: {
  enabled: boolean;
  onChange: (enabled: boolean) => void;
  language: 'en' | 'zh';
  onLanguageChange: (language: 'en' | 'zh') => void;
  nameplateAvailable: boolean;
  autoApproveNameplateAvailable: boolean;
  showFirstAppearanceNames: boolean;
  onShowFirstAppearanceNamesChange: (enabled: boolean) => void;
  autoApproveFirstAppearanceNames: boolean;
  onAutoApproveFirstAppearanceNamesChange: (enabled: boolean) => void;
  checks: GenerationCheck[];
  policy: Record<string, boolean>;
  onPolicyChange: (id: string, blocking: boolean) => void;
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
    {nameplateAvailable && <div className="rounded-lg border border-gray-200 p-4 text-sm">
      <label className="flex items-start gap-3">
        <input type="checkbox" checked={showFirstAppearanceNames}
          onChange={event => onShowFirstAppearanceNamesChange(event.target.checked)} className="mt-1" />
        <span>
          <span className="block font-medium text-gray-800">{t('systemSettings.showFirstAppearanceNames')}</span>
          <span className="mt-1 block max-w-3xl text-sm leading-6 text-gray-500">{t('systemSettings.showFirstAppearanceNamesDesc')}</span>
        </span>
      </label>
      {autoApproveNameplateAvailable && <label className={`mt-4 flex items-start gap-3 border-t border-gray-100 pt-4 ${showFirstAppearanceNames ? '' : 'opacity-50'}`}>
        <input type="checkbox" checked={autoApproveFirstAppearanceNames}
          disabled={!showFirstAppearanceNames}
          onChange={event => onAutoApproveFirstAppearanceNamesChange(event.target.checked)} className="mt-1" />
        <span>
          <span className="block font-medium text-gray-800">{t('systemSettings.autoApproveFirstAppearanceNames')}</span>
          <span className="mt-1 block max-w-3xl text-sm leading-6 text-gray-500">{t('systemSettings.autoApproveFirstAppearanceNamesDesc')}</span>
        </span>
      </label>}
    </div>}
    <div className="rounded-lg border border-gray-200 p-4 text-sm">
      <h4 className="font-medium text-gray-800">视频生成预检</h4>
      <p className="mt-1 text-gray-500">批量生成前会汇总所有分镜的检查结果。执行完整性检查始终强制；以下质量检查可选择是否阻断生成。</p>
      <div className="mt-3 divide-y divide-gray-100">
        {checks.map(check => <label key={check.id} className="flex items-start gap-3 py-3">
          <input type="checkbox" className="mt-1" checked={check.configurable ? !!policy[check.id] : true}
            disabled={!check.configurable}
            onChange={event => onPolicyChange(check.id, event.target.checked)} />
          <span>
            <span className="font-medium text-gray-800">{check.label}</span>
            <span className="ml-2 text-xs text-gray-500">{check.configurable ? (policy[check.id] ? '强制通过后生成' : '仅提示，不阻断') : '始终强制'}</span>
            <span className="block text-gray-500">{check.description}</span>
          </span>
        </label>)}
      </div>
    </div>
  </section>;
}
