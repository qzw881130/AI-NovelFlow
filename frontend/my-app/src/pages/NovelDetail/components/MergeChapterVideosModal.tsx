import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { CheckCircle, Clock, Download, Film, Loader2, Play, RefreshCw, X, XCircle } from 'lucide-react';
import { novelApi, type NovelVideoMergeHistory } from '../../../api/novels';
import type { Chapter } from '../../../types';
import { toast } from '../../../stores/toastStore';


const getChapterVideoUrl = (chapter: Chapter) => chapter.chapterVideoUrl || chapter.finalVideo;

const formatDuration = (seconds?: number | null) => {
  if (!seconds || seconds <= 0) return '--:--';
  const rounded = Math.round(seconds);
  return `${Math.floor(rounded / 60)}:${String(rounded % 60).padStart(2, '0')}`;
};

const formatFileSize = (bytes?: number | null) => {
  if (!bytes || bytes <= 0) return '--';
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
};

const formatDate = (value?: string | null) => value
  ? new Date(value).toLocaleString('zh-CN', { hour12: false })
  : '-';

export function MergeChapterVideosModal({ novelId, chapters, onClose }: {
  novelId: string;
  chapters: Chapter[];
  onClose: () => void;
}) {
  const eligibleIds = chapters.filter(getChapterVideoUrl).map(chapter => chapter.id);
  const [selectedIds, setSelectedIds] = useState<string[]>(eligibleIds);
  const [history, setHistory] = useState<NovelVideoMergeHistory[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [playingItem, setPlayingItem] = useState<NovelVideoMergeHistory | null>(null);

  const refreshHistory = async (silent = false) => {
    if (!silent) setHistoryLoading(true);
    try {
      const response = await novelApi.fetchVideoMergeHistory(novelId);
      if (response.success && response.data) setHistory(response.data);
    } catch (error) {
      console.error('加载章回视频合并历史失败:', error);
      if (!silent) toast.error('加载合并历史失败');
    } finally {
      if (!silent) setHistoryLoading(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let firstLoad = true;
    const poll = async () => {
      if (cancelled) return;
      await refreshHistory(!firstLoad);
      firstLoad = false;
      if (!cancelled) timer = setTimeout(poll, 3000);
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [novelId]);

  const submitMerge = async () => {
    if (selectedIds.length < 2) return;
    setSubmitting(true);
    try {
      const response = await novelApi.mergeChapterVideos(novelId, selectedIds);
      if (!response.success) {
        const detail = (response as typeof response & { detail?: string }).detail;
        throw new Error(response.message || detail || '提交合并任务失败');
      }
      toast.success(`已提交 ${selectedIds.length} 个章回视频的合并任务`);
      await refreshHistory(true);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '提交合并任务失败');
    } finally {
      setSubmitting(false);
    }
  };

  const allSelected = eligibleIds.length > 0 && eligibleIds.every(id => selectedIds.includes(id));

  return createPortal(
    <div className="fixed inset-0 z-[300] flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="flex max-h-[92vh] w-full max-w-6xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl" onClick={event => event.stopPropagation()}>
        <div className="flex items-center justify-between border-b px-5 py-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">合并所有章回视频</h2>
            <p className="mt-1 text-sm text-gray-500">选择至少两个已有最终视频的章回，按章回顺序合并</p>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-2 text-gray-400 hover:bg-gray-100 hover:text-gray-600"><X className="h-5 w-5" /></button>
        </div>

        <div className="grid min-h-0 flex-1 gap-0 overflow-hidden lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
          <section className="flex min-h-0 flex-col border-b lg:border-b-0 lg:border-r">
            <div className="flex items-center justify-between border-b bg-gray-50 px-5 py-3">
              <h3 className="font-medium text-gray-900">选择章回视频</h3>
              <label className="flex items-center gap-2 text-sm text-gray-600">
                <input type="checkbox" checked={allSelected} onChange={event => setSelectedIds(event.target.checked ? eligibleIds : [])} className="h-4 w-4 rounded border-gray-300 text-primary-600" />
                全选可用章回
              </label>
            </div>
            <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-4">
              {chapters.map(chapter => {
                const videoUrl = getChapterVideoUrl(chapter);
                const selected = selectedIds.includes(chapter.id);
                return (
                  <label key={chapter.id} className={`flex items-center gap-3 rounded-lg border p-3 ${videoUrl ? 'cursor-pointer border-gray-200 hover:bg-blue-50/50' : 'cursor-not-allowed border-gray-100 bg-gray-50 opacity-60'}`}>
                    <input
                      type="checkbox"
                      checked={selected}
                      disabled={!videoUrl}
                      onChange={() => setSelectedIds(current => selected ? current.filter(id => id !== chapter.id) : [...current, chapter.id])}
                      className="h-4 w-4 rounded border-gray-300 text-primary-600"
                    />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium text-gray-900">第 {chapter.number} 章 · {chapter.title}</div>
                      <div className="mt-1 text-xs text-gray-500">
                        {videoUrl ? `${formatDuration(chapter.chapterVideoDuration)} · ${formatFileSize(chapter.chapterVideoSize)}` : '暂无最终章回视频'}
                      </div>
                    </div>
                    {videoUrl && <Film className="h-4 w-4 text-blue-500" />}
                  </label>
                );
              })}
            </div>
            <div className="border-t bg-white px-5 py-4">
              <button type="button" onClick={submitMerge} disabled={selectedIds.length < 2 || submitting} className="btn-primary w-full justify-center disabled:cursor-not-allowed disabled:opacity-50">
                {submitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Film className="mr-2 h-4 w-4" />}
                {submitting ? '提交中...' : `合并 ${selectedIds.length} 个章回视频`}
              </button>
            </div>
          </section>

          <section className="flex min-h-0 flex-col">
            <div className="flex items-center justify-between border-b bg-gray-50 px-5 py-3">
              <h3 className="font-medium text-gray-900">历史合并记录</h3>
              <button type="button" onClick={() => refreshHistory()} className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-primary-600"><RefreshCw className="h-4 w-4" />刷新</button>
            </div>
            <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
              {historyLoading ? (
                <div className="flex h-48 items-center justify-center text-gray-500"><Loader2 className="mr-2 h-5 w-5 animate-spin" />加载历史记录...</div>
              ) : history.length === 0 ? (
                <div className="flex h-48 items-center justify-center text-gray-500">暂无合并记录</div>
              ) : history.map(item => (
                <div key={item.id} className="rounded-lg border border-gray-200 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 text-sm font-medium text-gray-900">
                        {item.status === 'completed' ? <CheckCircle className="h-4 w-4 text-green-600" /> : item.status === 'failed' ? <XCircle className="h-4 w-4 text-red-600" /> : <Loader2 className="h-4 w-4 animate-spin text-blue-600" />}
                        合并 {item.chapters.length} 个章回
                      </div>
                      <p className="mt-1 truncate text-xs text-gray-500" title={item.chapters.map(chapter => `第${chapter.number}章 ${chapter.title}`).join('、')}>
                        {item.chapters.map(chapter => `第${chapter.number}章`).join('、') || '章回信息不可用'}
                      </p>
                    </div>
                    <span className={`rounded-full px-2 py-1 text-xs ${item.status === 'completed' ? 'bg-green-50 text-green-700' : item.status === 'failed' ? 'bg-red-50 text-red-700' : 'bg-blue-50 text-blue-700'}`}>
                      {item.status === 'completed' ? '已完成' : item.status === 'failed' ? '失败' : item.status === 'running' ? `${item.progress}%` : '等待中'}
                    </span>
                  </div>
                  <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-500">
                    <span className="inline-flex items-center gap-1"><Clock className="h-3.5 w-3.5" />{formatDate(item.completedAt || item.createdAt)}</span>
                    {item.status === 'completed' && <span>{formatDuration(item.duration)} · {formatFileSize(item.fileSize)}</span>}
                    {item.cacheHit && <span>缓存结果</span>}
                  </div>
                  {item.errorMessage && <p className="mt-2 rounded bg-red-50 px-2 py-1.5 text-xs text-red-700">{item.errorMessage}</p>}
                  {item.status !== 'completed' && item.currentStep && <p className="mt-2 text-xs text-gray-500">{item.currentStep}</p>}
                  {item.status === 'completed' && item.videoUrl && (
                    <div className="mt-3 flex justify-end gap-2 border-t pt-3">
                      <button type="button" onClick={() => setPlayingItem(item)} className="btn-secondary px-3 py-1.5 text-sm"><Play className="mr-1 h-3.5 w-3.5" />播放</button>
                      <a href={item.videoUrl} download className="btn-secondary px-3 py-1.5 text-sm"><Download className="mr-1 h-3.5 w-3.5" />下载</a>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>
        </div>
      </div>

      {playingItem?.videoUrl && (
        <div className="fixed inset-0 z-[320] flex items-center justify-center bg-black/80 p-4" onClick={() => setPlayingItem(null)}>
          <div className="w-full max-w-5xl overflow-hidden rounded-xl bg-white" onClick={event => event.stopPropagation()}>
            <div className="flex items-center justify-between border-b px-5 py-3">
              <h3 className="font-medium text-gray-900">章回合并视频</h3>
              <button type="button" onClick={() => setPlayingItem(null)} className="rounded p-1 text-gray-400 hover:bg-gray-100"><X className="h-5 w-5" /></button>
            </div>
            <div className="bg-black"><video src={playingItem.videoUrl} controls autoPlay className="max-h-[75vh] w-full" /></div>
          </div>
        </div>
      )}
    </div>,
    document.body,
  );
}
