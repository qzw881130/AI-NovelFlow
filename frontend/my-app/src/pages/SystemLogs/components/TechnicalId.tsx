import { Copy } from 'lucide-react';
import { copyToClipboard } from '../../../utils/clipboard';
import { useTranslation } from '../../../stores/i18nStore';
import { shortTechnicalId } from '../displayMetadata';

export function TechnicalId({ value, className = '' }: { value: string | null | undefined; className?: string }) {
  const { t } = useTranslation();
  if (!value) return <span>{t('systemLogs.unknown')}</span>;
  return (
    <span className={`inline-flex max-w-full items-center gap-1 ${className}`} title={value}>
      <code className="truncate font-mono text-xs">{shortTechnicalId(value)}</code>
      <button
        type="button"
        onClick={event => { event.stopPropagation(); void copyToClipboard(value); }}
        aria-label={`${t('common.copy')} ${shortTechnicalId(value)}`}
        title={t('common.copy')}
        className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-gray-400 hover:bg-gray-100 hover:text-primary-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500"
      >
        <Copy aria-hidden="true" className="h-3.5 w-3.5" />
      </button>
    </span>
  );
}
