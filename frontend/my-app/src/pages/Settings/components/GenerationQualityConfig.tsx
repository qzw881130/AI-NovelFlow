import { useTranslation } from '../../../stores/i18nStore';

export default function GenerationQualityConfig({ enabled, onChange }: { enabled: boolean; onChange: (enabled: boolean) => void }) {
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
  </section>;
}
