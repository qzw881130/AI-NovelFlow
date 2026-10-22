import { useTranslation } from '../../../stores/i18nStore';
import type { GenerationCheck } from '../../../api/config';

const checkStages: Array<{ id: GenerationCheck['stage']; title: string; note: string }> = [
  { id: 'before_queue', title: '启动前', note: '批量生成前立即检查，可看到当前结果。' },
  { id: 'director', title: '导演规划与提示词', note: 'LLM 返回后才检查，启动前无法预判结果。' },
  { id: 'submission', title: '提交视频前', note: '核对实际引用和提交参数，不检查工作流内部流程。' },
  { id: 'assembly', title: '生成后与合并前', note: '拿到视频文件后检查实际输出及来源。' },
];

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
      <p className="mt-1 text-gray-500">这里列出视频生成链路中的检查。启动前检查会立即汇总结果；其余检查会在运行到相应步骤时执行。关闭可选项只是不阻断，仍记录警告。保存后对新任务及重试生效。</p>
      <div className="mt-4 space-y-4">
        {checkStages.map(stage => {
          const stageChecks = checks.filter(check => (check.stage || 'before_queue') === stage.id);
          if (!stageChecks.length) return null;
          return <div key={stage.id}>
            <div className="flex flex-wrap items-baseline gap-x-2 border-b border-gray-100 pb-2">
              <h5 className="font-medium text-gray-800">{stage.title}</h5>
              <span className="text-xs text-gray-500">{stage.note}</span>
            </div>
            <div className="grid gap-x-5 sm:grid-cols-2">
              {stageChecks.map(check => <div key={check.id} className="border-b border-gray-50 py-2.5">
                <label className="flex items-start gap-2">
                  <input type="checkbox" className="mt-0.5" checked={check.configurable ? !!policy[check.id] : true}
                    disabled={!check.configurable}
                    onChange={event => onPolicyChange(check.id, event.target.checked)} />
                  <span className="min-w-0">
                    <span className="font-medium text-gray-800">{check.label}</span>
                    <span className="ml-2 text-xs text-gray-500">{check.configurable ? (policy[check.id] ? '强制通过' : '警告，不阻断') : '始终强制'}</span>
                    <span className="block text-xs leading-5 text-gray-500">{check.description}</span>
                  </span>
                </label>
                {!!check.error_codes?.length && <details className="ml-5 mt-1 text-xs text-gray-600">
                  <summary className="cursor-pointer">可能触发的错误码（{check.error_codes.length}）</summary>
                  <span className="mt-1 block break-all font-mono leading-5">{check.error_codes.join(' · ')}</span>
                </details>}
              </div>)}
            </div>
          </div>;
        })}
      </div>
    </div>
  </section>;
}
