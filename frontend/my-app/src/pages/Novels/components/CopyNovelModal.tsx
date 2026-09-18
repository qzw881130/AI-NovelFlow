import { useEffect, useRef, useState } from 'react';
import { Copy, Loader2, X } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import type { Novel } from '../../../types';

interface CopyNovelModalProps {
  novels: Novel[];
  onClose: () => void;
  onCopy: (sourceId: string, title: string) => Promise<void>;
}

export function CopyNovelModal({ novels, onClose, onCopy }: CopyNovelModalProps) {
  const { t } = useTranslation();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const sourceRef = useRef<HTMLSelectElement>(null);
  const submittingRef = useRef(false);
  const [sourceId, setSourceId] = useState('');
  const [title, setTitle] = useState('');
  const [isCopying, setIsCopying] = useState(false);
  const [error, setError] = useState('');
  const source = novels.find((novel) => novel.id === sourceId);

  useEffect(() => {
    const dialog = dialogRef.current;
    dialog?.showModal();
    sourceRef.current?.focus();
    return () => dialog?.close();
  }, []);

  const handleSourceChange = (id: string) => {
    setSourceId(id);
    const selected = novels.find((novel) => novel.id === id);
    setTitle(selected ? `${selected.title}copy` : '');
    setError('');
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!source || !title.trim() || submittingRef.current) return;
    submittingRef.current = true;
    setIsCopying(true);
    setError('');
    try {
      await onCopy(source.id, title.trim());
      onClose();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('novels.copyFailed'));
    } finally {
      submittingRef.current = false;
      setIsCopying(false);
    }
  };

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby="copy-novel-heading"
      aria-describedby="copy-novel-scope"
      onCancel={(event) => {
        event.preventDefault();
        if (!submittingRef.current) onClose();
      }}
      className="m-auto max-h-[90vh] w-11/12 max-w-lg overflow-y-auto rounded-xl bg-white p-0 shadow-2xl backdrop:bg-black/50"
    >
      <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4">
        <h2 id="copy-novel-heading" className="text-lg font-semibold text-gray-900">
          {t('novels.copyNovel')}
        </h2>
        <button
          type="button"
          onClick={onClose}
          disabled={isCopying}
          aria-label={t('common.close')}
          className="rounded-lg p-2 text-gray-400 hover:bg-gray-100 hover:text-gray-600 disabled:opacity-50"
        >
          <X className="h-5 w-5" aria-hidden="true" />
        </button>
      </div>
      <form onSubmit={handleSubmit} aria-busy={isCopying}>
        <div className="space-y-4 px-5 py-5">
          <p id="copy-novel-scope" className="rounded-lg bg-blue-50 p-3 text-sm text-blue-800">
            {t('novels.copyScopeHint')}
          </p>
          <div>
            <label htmlFor="copy-novel-source" className="block text-sm font-medium text-gray-700">
              {t('novels.copySource')}
            </label>
            <select
              id="copy-novel-source"
              ref={sourceRef}
              required
              value={sourceId}
              onChange={(event) => handleSourceChange(event.target.value)}
              disabled={isCopying}
              className="input-field mt-1 min-w-0"
            >
              <option value="">{t('novels.copySourcePlaceholder')}</option>
              {novels.map((novel) => (
                <option key={novel.id} value={novel.id}>{novel.title} · {novel.id}</option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="copy-novel-title" className="block text-sm font-medium text-gray-700">
              {t('novels.copyTitle')}
            </label>
            <input
              id="copy-novel-title"
              type="text"
              required
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              disabled={!source || isCopying}
              className="input-field mt-1"
            />
          </div>
          {error && <p role="alert" className="break-words text-sm text-red-600">{error}</p>}
        </div>
        <div className="flex flex-wrap justify-end gap-3 border-t border-gray-100 px-5 py-4">
          <button type="button" onClick={onClose} disabled={isCopying} className="btn-secondary">
            {t('common.cancel')}
          </button>
          <button type="submit" disabled={!source || !title.trim() || isCopying} className="btn-primary">
            {isCopying ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Copy className="mr-2 h-4 w-4" />}
            {t(isCopying ? 'novels.copying' : 'novels.copyConfirm')}
          </button>
        </div>
      </form>
    </dialog>
  );
}
