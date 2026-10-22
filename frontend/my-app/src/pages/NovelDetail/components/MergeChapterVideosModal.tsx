import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { CheckCircle, Clock, Download, Film, Image as ImageIcon, Loader2, Play, RefreshCw, X, XCircle } from 'lucide-react';
import { novelApi, type NovelVideoCover, type NovelVideoMergeHistory } from '../../../api/novels';
import { configApi } from '../../../api/config';
import type { Chapter, ChapterVideoAsset } from '../../../types';
import { toast } from '../../../stores/toastStore';


const chapterAssets = (chapter: Chapter): ChapterVideoAsset[] => chapter.videoAssets || [];

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

const coverRatios: NovelVideoCover['aspectRatio'][] = ['16:9', '9:16', '4:3', '1:1'];

export function MergeChapterVideosModal({ novelId, novelTitle, novelAuthor, chapters, initialProfile = { kind: 'draft' }, onClose }: {
  novelId: string;
  novelTitle: string;
  novelAuthor: string;
  chapters: Chapter[];
  initialProfile?: { kind: 'draft' | 'hd'; targetMegapixels?: number };
  onClose: () => void;
}) {
  const profileKey = initialProfile.kind === 'hd' ? `hd:${initialProfile.targetMegapixels}` : 'draft';
  const findAsset = (chapter: Chapter) => chapterAssets(chapter).find(asset => asset.profileKey === profileKey);
  const eligibleIds = chapters.filter(findAsset).map(chapter => chapter.id);
  const [selectedIds, setSelectedIds] = useState<string[]>(eligibleIds);
  const [history, setHistory] = useState<NovelVideoMergeHistory[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [playingItem, setPlayingItem] = useState<NovelVideoMergeHistory | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [videoDuration, setVideoDuration] = useState(0);
  const [frameSeconds, setFrameSeconds] = useState(0);
  const [aspectRatio, setAspectRatio] = useState<NovelVideoCover['aspectRatio']>('16:9');
  const [coverTitle, setCoverTitle] = useState(novelTitle);
  const [coverAuthor, setCoverAuthor] = useState(novelAuthor);
  const [coverProduction, setCoverProduction] = useState('旺仔有声小说');
  const [generatingCover, setGeneratingCover] = useState(false);
  const currentPlayingItem = playingItem && (history.find(item => item.id === playingItem.id) || playingItem);
  const currentCover = currentPlayingItem?.cover;

  useEffect(() => {
    let cancelled = false;
    void configApi.get().then(response => {
      if (!cancelled && response.success) setCoverProduction(response.data?.coverProduction || '旺仔有声小说');
    }).catch(() => undefined);
    return () => { cancelled = true; };
  }, []);

  const openVideo = (item: NovelVideoMergeHistory) => {
    setPlayingItem(item);
    setVideoDuration(item.duration || 0);
    setFrameSeconds(item.cover?.frameSeconds || 0);
    setAspectRatio(item.cover?.aspectRatio || '16:9');
    setCoverTitle(item.cover?.title || novelTitle);
    setCoverAuthor(item.cover?.author || novelAuthor);
    if (item.cover?.production) setCoverProduction(item.cover.production);
  };

  const seekFrame = (seconds: number) => {
    if (!Number.isFinite(seconds)) return;
    const duration = videoRef.current?.duration || videoDuration;
    const next = Math.max(0, duration > 0 ? Math.min(seconds, Math.max(0, duration - 0.05)) : seconds);
    setFrameSeconds(next);
    if (videoRef.current && Number.isFinite(videoRef.current.duration)) {
      videoRef.current.pause();
      videoRef.current.currentTime = next;
    }
  };

  const submitCover = async () => {
    if (!currentPlayingItem) return;
    if (!coverTitle.trim() || !coverAuthor.trim() || !coverProduction.trim()) {
      toast.error('请填写封面标题、原作者和制作');
      return;
    }
    setGeneratingCover(true);
    try {
      const response = await novelApi.generateVideoCover(novelId, currentPlayingItem.id, {
        frameSeconds: Math.round(frameSeconds * 10) / 10, aspectRatio,
        title: coverTitle.trim(), author: coverAuthor.trim(), production: coverProduction.trim(),
      });
      if (!response.success || !response.data) {
        const detail = (response as typeof response & { detail?: string }).detail;
        throw new Error(detail || response.message || '提交封面生成失败');
      }
      setHistory(previous => previous.map(item => item.id === currentPlayingItem.id ? { ...item, cover: response.data } : item));
      toast.success('封面已加入生成队列');
      await refreshHistory(true);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '提交封面生成失败');
    } finally {
      setGeneratingCover(false);
    }
  };

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
      const response = await novelApi.mergeChapterVideos(novelId, selectedIds, initialProfile.kind, initialProfile.targetMegapixels);
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
              <span className="rounded-md bg-purple-50 px-2 py-1 text-sm font-medium text-purple-700">{initialProfile.kind === 'hd' ? `高清 ${initialProfile.targetMegapixels?.toFixed(1)} MP` : '初稿'}</span>
              <label className="flex items-center gap-2 text-sm text-gray-600">
                <input type="checkbox" checked={allSelected} onChange={event => setSelectedIds(event.target.checked ? eligibleIds : [])} className="h-4 w-4 rounded border-gray-300 text-primary-600" />
                全选可用章回
              </label>
            </div>
            <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-4">
              {chapters.map(chapter => {
                const asset = findAsset(chapter);
                const videoUrl = asset?.videoUrl;
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
                        {videoUrl ? `${formatDuration(asset?.duration)} · ${formatFileSize(asset?.fileSize)}` : `缺少${initialProfile.kind === 'hd' ? ` ${initialProfile.targetMegapixels?.toFixed(1)} MP 高清` : '初稿'}章回视频`}
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
                        <span className={`rounded px-1.5 py-0.5 text-[10px] ${item.videoVariant === 'hd' ? 'bg-purple-50 text-purple-700' : 'bg-gray-100 text-gray-600'}`}>{item.videoVariant === 'hd' ? `高清 ${item.targetMegapixels?.toFixed(1)} MP` : '初稿'}</span>
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
                      <button type="button" onClick={() => openVideo(item)} className="btn-secondary px-3 py-1.5 text-sm"><Play className="mr-1 h-3.5 w-3.5" />播放 / 封面</button>
                      <a href={novelApi.videoMergeDownloadUrl(novelId, item.id)} className="btn-secondary px-3 py-1.5 text-sm"><Download className="mr-1 h-3.5 w-3.5" />下载</a>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>
        </div>
      </div>

      {currentPlayingItem?.videoUrl && (
        <div className="fixed inset-0 z-[320] flex items-center justify-center bg-black/80 p-4" onClick={event => { event.stopPropagation(); setPlayingItem(null); }}>
          <div className="flex max-h-[94vh] w-full max-w-7xl flex-col overflow-hidden rounded-xl bg-white" onClick={event => event.stopPropagation()}>
            <div className="flex items-center justify-between border-b px-5 py-3">
              <h3 className="font-medium text-gray-900">章回合并视频 · 制作封面</h3>
              <button type="button" onClick={() => setPlayingItem(null)} className="rounded p-1 text-gray-400 hover:bg-gray-100"><X className="h-5 w-5" /></button>
            </div>
            <div className="grid min-h-0 flex-1 overflow-y-auto lg:grid-cols-[minmax(0,1fr)_20rem]">
              <div className="min-w-0 border-r border-gray-200">
                <div className="flex min-h-56 items-center justify-center bg-black">
                  <video
                    ref={videoRef} src={currentPlayingItem.videoUrl} controls autoPlay
                    className="max-h-[55vh] w-full"
                    onLoadedMetadata={event => {
                      const duration = event.currentTarget.duration;
                      setVideoDuration(Number.isFinite(duration) ? duration : 0);
                      if (frameSeconds > 0 && Number.isFinite(duration)) event.currentTarget.currentTime = Math.min(frameSeconds, Math.max(0, duration - 0.05));
                    }}
                    onTimeUpdate={event => setFrameSeconds(event.currentTarget.currentTime)}
                  />
                </div>
                <div className="space-y-4 p-5">
                  <div>
                    <div className="mb-2 flex items-center justify-between gap-4 text-sm">
                      <label htmlFor="cover-frame-seconds" className="font-medium text-gray-900">选取封面画面</label>
                      <div className="flex items-center gap-2 text-gray-500">
                        <input id="cover-frame-seconds" type="number" min="0" max={videoDuration || undefined} step="0.1"
                          value={Number(frameSeconds.toFixed(1))} onChange={event => seekFrame(Number(event.target.value))}
                          className="w-20 rounded-md border border-gray-300 px-2 py-1 text-right text-gray-900" />
                        秒 / {formatDuration(videoDuration)}
                      </div>
                    </div>
                    <input aria-label="选择封面视频帧" type="range" min="0" max={Math.max(0, videoDuration - 0.05)} step="0.1"
                      value={Math.min(frameSeconds, Math.max(0, videoDuration - 0.05))} onChange={event => seekFrame(Number(event.target.value))}
                      className="w-full accent-blue-600" />
                    <p className="mt-1 text-xs text-gray-500">播放或拖动视频后，使用当前时间的画面作为生成参考。</p>
                  </div>
                  <div>
                    <span className="mb-2 block text-sm font-medium text-gray-900">封面比例</span>
                    <div className="flex flex-wrap gap-2">
                      {coverRatios.map(ratio => <button key={ratio} type="button" onClick={() => setAspectRatio(ratio)}
                        aria-pressed={aspectRatio === ratio}
                        className={`rounded-md border px-3 py-1.5 text-sm ${aspectRatio === ratio ? 'border-blue-500 bg-blue-50 text-blue-700' : 'border-gray-200 text-gray-600 hover:border-gray-300'}`}>{ratio}</button>)}
                    </div>
                  </div>
                  <div className="grid gap-3 sm:grid-cols-3">
                    <label className="block text-sm font-medium text-gray-800">标题
                      <input value={coverTitle} maxLength={100} onChange={event => setCoverTitle(event.target.value)} className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 font-normal" placeholder="小说名" />
                    </label>
                    <label className="block text-sm font-medium text-gray-800">原作者
                      <input value={coverAuthor} maxLength={100} onChange={event => setCoverAuthor(event.target.value)} className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 font-normal" placeholder="原作者" />
                    </label>
                    <label className="block text-sm font-medium text-gray-800">制作
                      <input value={coverProduction} maxLength={80} onChange={event => setCoverProduction(event.target.value)} className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 font-normal" placeholder="制作单位" />
                    </label>
                  </div>
                  <button type="button" onClick={submitCover}
                    disabled={generatingCover || currentCover?.status === 'pending' || currentCover?.status === 'running'}
                    className="btn-primary w-full justify-center disabled:cursor-not-allowed disabled:opacity-50">
                    {generatingCover || currentCover?.status === 'pending' || currentCover?.status === 'running'
                      ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <ImageIcon className="mr-2 h-4 w-4" />}
                    {currentCover?.status === 'pending' || currentCover?.status === 'running' ? '封面生成中...' : currentCover?.status === 'completed' ? '重新生成封面' : '生成视频封面'}
                  </button>
                </div>
              </div>
              <aside className="flex flex-col border-t bg-gray-50 p-5 lg:border-t-0">
                <div className="mb-3 flex items-center justify-between gap-2">
                  <h4 className="font-medium text-gray-900">视频封面</h4>
                  {currentCover?.status === 'completed' && <a href={novelApi.videoCoverDownloadUrl(novelId, currentPlayingItem.id)}
                    className="btn-secondary px-3 py-1.5 text-sm"><Download className="mr-1 h-4 w-4" />下载</a>}
                </div>
                {currentCover?.status === 'completed' && currentCover.imageUrl ? (
                  <img src={currentCover.imageUrl} alt={`${currentCover.title} 视频封面`} className="max-h-[66vh] w-full rounded-lg border border-gray-200 bg-gray-900 object-contain" />
                ) : currentCover?.status === 'failed' ? (
                  <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">{currentCover.errorMessage || '封面生成失败，请重试'}</div>
                ) : currentCover?.status === 'pending' || currentCover?.status === 'running' ? (
                  <div className="flex min-h-64 flex-col items-center justify-center rounded-lg border border-dashed border-blue-200 bg-blue-50 text-center text-sm text-blue-700">
                    <Loader2 className="mb-3 h-7 w-7 animate-spin" />
                    <span>{currentCover.currentStep || '正在生成封面...'}</span>
                  </div>
                ) : (
                  <div className="flex min-h-64 flex-col items-center justify-center rounded-lg border border-dashed border-gray-300 text-center text-sm text-gray-500">
                    <ImageIcon className="mb-3 h-8 w-8 text-gray-400" />选好视频帧后生成封面
                  </div>
                )}
                <p className="mt-3 text-xs leading-5 text-gray-500">使用当前场景分镜图工作流生成画面，再将标题和署名准确排版在封面上。</p>
              </aside>
            </div>
          </div>
        </div>
      )}
    </div>,
    document.body,
  );
}
