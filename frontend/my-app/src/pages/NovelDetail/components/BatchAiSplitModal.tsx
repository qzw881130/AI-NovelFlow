import { useState } from 'react';
import { AlertTriangle, Loader2, X } from 'lucide-react';
import { chapterApi, type ChapterAiSplitBatch } from '../../../api/chapters';
import { useTranslation } from '../../../stores/i18nStore';
import type { Chapter } from '../../../types';

interface BatchAiSplitModalProps {
  novelId: string;
  chapters: Chapter[];
  mode: 'create' | 'progress';
  latestBatch: ChapterAiSplitBatch | null;
  onClose: () => void;
  onBatchCreated: (batch: ChapterAiSplitBatch) => void;
}

const statusLabel = { pending: '排队中', running: '拆分中', completed: '已完成', failed: '失败', cancelled: '已取消' };

export function BatchAiSplitModal({ novelId, chapters, mode, latestBatch, onClose, onBatchCreated }: BatchAiSplitModalProps) {
  const { t } = useTranslation();
  const [submittedBatch, setSubmittedBatch] = useState<ChapterAiSplitBatch | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const batch = submittedBatch && latestBatch?.id === submittedBatch.id ? latestBatch
    : submittedBatch || (mode === 'progress' ? latestBatch : null);
  const resplitCount = chapters.filter(chapter => chapter.aiSplitCompleted).length;

  const start = async () => {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      const response = await chapterApi.createAiSplitBatch(novelId, chapters.map(chapter => chapter.id));
      if (!response.success || !response.data) {
        const detail = 'detail' in response && typeof response.detail === 'string' ? response.detail : undefined;
        throw new Error(detail || response.message || '提交批量拆分失败');
      }
      setSubmittedBatch(response.data);
      onBatchCreated(response.data);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '提交批量拆分失败');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true" aria-labelledby="batch-ai-split-title">
      <div className="w-full max-w-lg rounded-xl bg-white p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 id="batch-ai-split-title" className="text-lg font-semibold text-gray-900">{t('novelDetail.batchAiSplit.title')}</h2>
          <button type="button" onClick={onClose} className="rounded p-1 text-gray-400 hover:text-gray-600" aria-label={t('common.close')}><X className="h-5 w-5" /></button>
        </div>

        {batch ? <>
          <p className="text-sm text-gray-700">已完成 {batch.completed + batch.failed} / {batch.total} 个章回 · 成功 {batch.completed} · 失败 {batch.failed}</p>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-gray-100"><div className="h-full bg-primary-600 transition-all" style={{ width: `${batch.total ? ((batch.completed + batch.failed) / batch.total) * 100 : 0}%` }} /></div>
          <div className="mt-4 max-h-64 overflow-y-auto rounded-lg border border-gray-200 p-3 text-sm">
            {batch.chapters.map(chapter => <div key={chapter.taskId} className="flex justify-between gap-3 py-1.5">
              <span className="min-w-0 truncate" title={chapter.title}>{chapter.title}{chapter.errorMessage ? `：${chapter.errorMessage}` : ''}</span>
              <span className={`shrink-0 ${chapter.status === 'failed' ? 'text-red-600' : chapter.status === 'completed' ? 'text-green-600' : 'text-gray-500'}`}>{statusLabel[chapter.status]}</span>
            </div>)}
          </div>
          {batch.status === 'running' && <p className="mt-3 text-xs text-gray-500">任务在后台并行处理，关闭此窗口或离开页面后仍会继续。</p>}
          <div className="mt-6 flex justify-end"><button type="button" onClick={onClose} className="btn-primary">{t('common.close')}</button></div>
        </> : <>
          <p className="text-sm text-gray-600">已选择 {chapters.length} 个章回，提交后将在后台并行拆分。</p>
          {resplitCount > 0 && <div className="mt-4 flex gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{t('novelDetail.batchAiSplit.resplitWarning', { count: resplitCount })}</span>
          </div>}
          <div className="mt-4 max-h-48 overflow-y-auto rounded-lg border border-gray-200 p-3 text-sm text-gray-700">
            {chapters.map(chapter => <div key={chapter.id} className="py-1">{chapter.title}</div>)}
          </div>
          {error && <p role="alert" className="mt-3 text-sm text-red-600">{error}</p>}
          <div className="mt-6 flex justify-end gap-2">
            <button type="button" onClick={onClose} className="btn-secondary">{t('common.cancel')}</button>
            <button type="button" onClick={() => void start()} disabled={busy || chapters.length === 0} className="btn-primary disabled:opacity-50">
              {busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}{t('novelDetail.batchAiSplit.start')}
            </button>
          </div>
        </>}
      </div>
    </div>
  );
}
