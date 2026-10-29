import { useEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';
import { chapterApi } from '../../api/chapters';

interface Props {
  novelId: string;
  chapterId: string;
  chapterTitle: string;
  onClose: () => void;
}

export function ChapterOriginalDrawer({ novelId, chapterId, chapterTitle, onClose }: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const dialog = dialogRef.current;
    dialog?.showModal();
    return () => { if (dialog?.open) dialog.close(); };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');
    chapterApi.fetchForReading(novelId, chapterId).then(result => {
      if (cancelled) return;
      if (!result.success || !result.data) throw new Error(result.message || '原文加载失败');
      setContent(result.data.content || '');
    }).catch(reason => {
      if (!cancelled) setError(reason instanceof Error ? reason.message : '原文加载失败');
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, [novelId, chapterId, retry]);

  return <dialog ref={dialogRef} onClose={onClose} aria-label="章节原文" className="fixed inset-y-0 left-0 right-auto m-0 flex h-dvh max-h-dvh w-full max-w-xl flex-col rounded-none bg-white p-0 text-gray-900 shadow-xl backdrop:bg-black/40">
    <div className="flex items-start justify-between gap-4 border-b border-gray-200 px-5 py-4">
      <div className="min-w-0"><h2 className="text-base font-semibold">原文内容</h2><p className="mt-1 truncate text-sm text-gray-500">{chapterTitle}{!loading && !error ? ` · ${content.replace(/\s/g, '').length} 字` : ''}</p></div>
      <button type="button" onClick={() => dialogRef.current?.close()} aria-label="关闭原文" className="rounded p-1 text-gray-500 hover:bg-gray-100"><X className="h-5 w-5" /></button>
    </div>
    <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
      {loading ? <p className="text-sm text-gray-500">正在加载原文…</p> : error ? <div role="alert" className="text-sm text-red-700"><p>{error}</p><button type="button" onClick={() => setRetry(value => value + 1)} className="mt-3 rounded border border-red-200 px-3 py-1.5 hover:bg-red-50">重试</button></div> : content ? <div className="whitespace-pre-wrap break-words text-sm leading-7">{content}</div> : <p className="text-sm text-gray-500">本章暂无原文。</p>}
    </div>
  </dialog>;
}
