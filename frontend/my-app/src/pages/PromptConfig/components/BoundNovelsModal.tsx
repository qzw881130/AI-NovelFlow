import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Loader2, X } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import { promptTemplateApi } from '../../../api/promptTemplates';
import type { BoundNovel } from '../../../api/promptTemplates';
import type { PromptTemplate } from '../../../types';

interface BoundNovelsModalProps {
  template: PromptTemplate;
  onClose: () => void;
  getDisplayName: (template: PromptTemplate) => string;
}

export function BoundNovelsModal({ template, onClose, getDisplayName }: BoundNovelsModalProps) {
  const { t } = useTranslation();
  const [novels, setNovels] = useState<BoundNovel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setNovels([]);
    setLoading(true);
    setError(false);
    promptTemplateApi.fetchBoundNovels(template.id, controller.signal)
      .then(data => { if (!controller.signal.aborted) setNovels(data); })
      .catch(() => { if (!controller.signal.aborted) setError(true); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [template.id]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50 p-4" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
      <div role="dialog" aria-modal="true" aria-label={`${t('promptConfig.boundNovels')} — ${getDisplayName(template)}`} className="w-full max-w-xl rounded-lg bg-white p-6 shadow-xl">
        <div className="flex items-start justify-between gap-4">
          <h3 className="text-lg font-semibold text-gray-900">{t('promptConfig.boundNovels')} — {getDisplayName(template)}</h3>
          <button type="button" onClick={onClose} aria-label={t('common.close')} className="rounded p-1 text-gray-500 hover:bg-gray-100"><X className="h-5 w-5" /></button>
        </div>
        <div className="mt-4 max-h-[60vh] min-h-[5rem] overflow-y-auto">
          {loading ? <div role="status" className="flex items-center gap-2 text-sm text-gray-500"><Loader2 className="h-4 w-4 animate-spin" />{t('promptConfig.loadingBindings')}</div>
            : error ? <p role="alert" className="text-sm text-red-600">{t('promptConfig.loadBindingsFailed')}</p>
              : novels.length === 0 ? <p className="py-5 text-sm text-gray-500">{t('promptConfig.noBoundNovels')}</p>
                : <ul className="divide-y divide-gray-100">
                  {novels.map(novel => <li key={novel.novel_id} className="py-3">
                    <Link to={`/novels/${encodeURIComponent(novel.novel_id)}`} onClick={onClose} className="font-medium text-blue-600 hover:underline">{novel.novel_title}</Link>
                    {novel.author && <p className="mt-1 text-sm text-gray-500">{t('promptConfig.author')}: {novel.author}</p>}
                    <p className="mt-1 text-xs text-gray-500">{t('promptConfig.bindingType')}: {t('promptConfig.explicitBinding')}</p>
                  </li>)}
                </ul>}
        </div>
        <div className="mt-4 flex items-center justify-between border-t border-gray-200 pt-4 text-sm text-gray-500">
          <span>{t('promptConfig.boundNovelCount', { count: !loading && !error ? novels.length : 0 })}</span>
          <button type="button" onClick={onClose} className="btn-secondary">{t('common.close')}</button>
        </div>
      </div>
    </div>
  );
}
