import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { CheckCircle, Clock, Download, Film, Image as ImageIcon, Loader2, Play, RefreshCw, X, XCircle } from 'lucide-react';
import { novelApi, type CoverTextStyle, type NovelVideoCover, type NovelVideoMergeHistory } from '../../../api/novels';
import { configApi } from '../../../api/config';
import type { Chapter, ChapterVideoAsset } from '../../../types';
import { toast } from '../../../stores/toastStore';
import { youtubeApi } from '../../../api/youtube';
import { YoutubeUploadModal } from './YoutubeUploadModal';


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

const coverRatios: NovelVideoCover['aspectRatio'][] = ['16:9', '9:16', '4:3', '3:4', '1:1'];
const coverTextStyles: { id: CoverTextStyle; name: string; description: string }[] = [
  { id: 'classic', name: '经典居中', description: '暖白标题 · 底部居中' },
  { id: 'cinematic', name: '文学电影', description: '宋体标题 · 柔和留白' },
  { id: 'editorial', name: '左下纪实', description: '醒目大字 · 朱砂短线' },
  { id: 'vintage', name: '朱砂旧书', description: '朱砂标题 · 细线题签' },
];
const coverStyleName = (style?: CoverTextStyle) =>
  coverTextStyles.find(item => item.id === style)?.name || '经典居中';
const playbackPositionKey = (novelId: string, mergeId: string) => `novel-video-cover-position:${novelId}:${mergeId}`;

const readPlaybackPosition = (novelId: string, mergeId: string): number | null => {
  try {
    const saved = window.localStorage.getItem(playbackPositionKey(novelId, mergeId));
    if (saved === null) return null;
    const seconds = Number(saved);
    return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
  } catch {
    return null;
  }
};

const savePlaybackPosition = (novelId: string, mergeId: string, seconds: number) => {
  if (!Number.isFinite(seconds) || seconds < 0) return;
  try {
    window.localStorage.setItem(playbackPositionKey(novelId, mergeId), String(Math.round(seconds * 10) / 10));
  } catch { /* Browser storage may be unavailable. */ }
};

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
  const [playbackItem, setPlaybackItem] = useState<NovelVideoMergeHistory | null>(null);
  const [playingItem, setPlayingItem] = useState<NovelVideoMergeHistory | null>(null);
  const [previewCover, setPreviewCover] = useState<NovelVideoCover | null>(null);
  const [uploadItem, setUploadItem] = useState<NovelVideoMergeHistory | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [videoDuration, setVideoDuration] = useState(0);
  const [frameSeconds, setFrameSeconds] = useState(0);
  const [aspectRatio, setAspectRatio] = useState<NovelVideoCover['aspectRatio']>('16:9');
  const [textStyle, setTextStyle] = useState<CoverTextStyle>('classic');
  const [selectedCoverRatio, setSelectedCoverRatio] = useState<NovelVideoCover['aspectRatio']>('16:9');
  const [coverTitle, setCoverTitle] = useState(novelTitle);
  const [coverAuthor, setCoverAuthor] = useState(novelAuthor);
  const [coverProduction, setCoverProduction] = useState('旺仔有声小说');
  const [generatingCover, setGeneratingCover] = useState(false);
  const currentPlayingItem = playingItem && (history.find(item => item.id === playingItem.id) || playingItem);
  const currentCover = currentPlayingItem?.cover;
  const savedCovers = currentPlayingItem?.covers?.length
    ? currentPlayingItem.covers
    : currentCover?.status === 'completed' && currentCover.imageUrl ? [currentCover] : [];
  const activeCovers = currentPlayingItem?.activeCovers?.length
    ? currentPlayingItem.activeCovers
    : currentCover?.status === 'pending' || currentCover?.status === 'running' ? [currentCover] : [];
  const coverTabs = coverRatios.filter(ratio =>
    savedCovers.some(cover => cover.aspectRatio === ratio)
    || activeCovers.some(cover => cover.aspectRatio === ratio)
    || (currentCover?.status === 'failed' && currentCover.aspectRatio === ratio));
  const visibleCoverRatio = coverTabs.includes(selectedCoverRatio) ? selectedCoverRatio : coverTabs[0];
  const visibleSavedCover = savedCovers.find(cover => cover.aspectRatio === visibleCoverRatio);
  const visibleActiveCover = activeCovers.find(cover => cover.aspectRatio === visibleCoverRatio);
  const visibleFailedCover = currentCover?.status === 'failed' && currentCover.aspectRatio === visibleCoverRatio ? currentCover : null;

  useEffect(() => {
    if (!previewCover) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setPreviewCover(null);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [previewCover]);

  useEffect(() => {
    if (!playbackItem) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setPlaybackItem(null);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [playbackItem]);

  useEffect(() => {
    let cancelled = false;
    void configApi.get().then(response => {
      if (!cancelled && response.success) setCoverProduction(response.data?.coverProduction || '旺仔有声小说');
    }).catch(() => undefined);
    return () => { cancelled = true; };
  }, []);

  const openCoverEditor = (item: NovelVideoMergeHistory) => {
    setPreviewCover(null);
    setPlayingItem(item);
    setVideoDuration(item.duration || 0);
    setFrameSeconds(readPlaybackPosition(novelId, item.id) ?? item.cover?.frameSeconds ?? 0);
    setAspectRatio(item.cover?.aspectRatio || '16:9');
    setTextStyle(item.cover?.textStyle || 'classic');
    setSelectedCoverRatio(item.covers?.some(cover => cover.aspectRatio === '16:9') ? '16:9'
      : item.covers?.[0]?.aspectRatio || item.cover?.aspectRatio || '16:9');
    setCoverTitle(item.cover?.title || novelTitle);
    setCoverAuthor(item.cover?.author || novelAuthor);
    if (item.cover?.production) setCoverProduction(item.cover.production);
  };

  const closeVideo = () => {
    if (currentPlayingItem && videoRef.current) {
      savePlaybackPosition(novelId, currentPlayingItem.id, videoRef.current.currentTime);
    }
    setPreviewCover(null);
    setPlayingItem(null);
  };

  const seekFrame = (seconds: number) => {
    if (!Number.isFinite(seconds)) return;
    const duration = videoRef.current?.duration || videoDuration;
    const next = Math.max(0, duration > 0 ? Math.min(seconds, Math.max(0, duration - 0.05)) : seconds);
    setFrameSeconds(next);
    if (currentPlayingItem) savePlaybackPosition(novelId, currentPlayingItem.id, next);
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
    setSelectedCoverRatio(aspectRatio);
    try {
      const response = await novelApi.generateVideoCover(novelId, currentPlayingItem.id, {
        frameSeconds: Math.round(frameSeconds * 10) / 10, aspectRatio, textStyle,
        title: coverTitle.trim(), author: coverAuthor.trim(), production: coverProduction.trim(),
      });
      if (!response.success || !response.data) {
        const detail = (response as typeof response & { detail?: string }).detail;
        throw new Error(detail || response.message || '提交封面生成失败');
      }
      const newCover = response.data;
      setHistory(previous => previous.map(item => item.id === currentPlayingItem.id
        ? { ...item, cover: newCover, activeCovers: [newCover, ...(item.activeCovers || [])] } : item));
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

  const retryYoutube = async (uploadId: string) => {
    try {
      const response = await youtubeApi.retry(uploadId);
      if (!response.success) throw new Error((response as typeof response & { detail?: string }).detail || response.message || '重试失败');
      toast.success('YouTube 上传已重新排队');
      await refreshHistory(true);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '重试上传失败');
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
                  {item.youtubeUpload && <div className="mt-2 rounded-lg border border-blue-100 bg-blue-50 p-2 text-xs text-blue-900">
                    <div className="flex flex-wrap items-center gap-2">
                      <span>YouTube：{item.youtubeUpload.status === 'completed' ? '上传完成' : item.youtubeUpload.status === 'failed' ? '上传失败' : `${item.youtubeUpload.currentStep || '上传中'} ${item.youtubeUpload.progress}%`}</span>
                      {item.youtubeUpload.youtubeUrl && <a href={item.youtubeUpload.youtubeUrl} target="_blank" rel="noopener noreferrer" className="font-medium underline">查看视频</a>}
                      {item.youtubeUpload.status === 'failed' && <button type="button" onClick={() => void retryYoutube(item.youtubeUpload!.id)} className="font-medium underline">重试</button>}
                      {item.youtubeUpload.status === 'completed' && !!item.youtubeUpload.warnings?.length && <button type="button" onClick={() => void retryYoutube(item.youtubeUpload!.id)} className="font-medium underline">重试封面 / 播放列表</button>}
                    </div>
                    {item.youtubeUpload.errorMessage && <p className="mt-1 break-words text-red-700">{item.youtubeUpload.errorMessage}</p>}
                    {item.youtubeUpload.warnings?.map((warning, index) => <p key={index} className="mt-1 break-words text-amber-700">{warning}</p>)}
                  </div>}
                  {item.status === 'completed' && item.videoUrl && (
                    <div className="mt-3 flex justify-end gap-2 border-t pt-3">
                      <button type="button" onClick={() => setPlaybackItem(item)} className="btn-secondary px-3 py-1.5 text-sm"><Play className="mr-1 h-3.5 w-3.5" />播放</button>
                      <button type="button" onClick={() => openCoverEditor(item)} className="btn-secondary px-3 py-1.5 text-sm"><ImageIcon className="mr-1 h-3.5 w-3.5" />制作封面</button>
                      <button type="button" onClick={() => setUploadItem(item)} className="btn-secondary px-3 py-1.5 text-sm">上传 YouTube</button>
                      <a href={novelApi.videoMergeDownloadUrl(novelId, item.id)} className="btn-secondary px-3 py-1.5 text-sm"><Download className="mr-1 h-3.5 w-3.5" />下载</a>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>
        </div>
      </div>

      {uploadItem && <YoutubeUploadModal novelId={novelId} novelTitle={novelTitle}
        item={history.find(item => item.id === uploadItem.id) || uploadItem}
        onClose={() => setUploadItem(null)} onUploaded={() => void refreshHistory(true)} />}

      {playbackItem?.videoUrl && (
        <div className="fixed inset-0 z-[320] flex items-center justify-center bg-black/80 p-4"
          role="dialog" aria-modal="true" aria-label="播放合并视频"
          onClick={event => { event.stopPropagation(); setPlaybackItem(null); }}>
          <div className="flex max-h-[94vh] w-full max-w-5xl flex-col overflow-hidden rounded-xl bg-white"
            onClick={event => event.stopPropagation()}>
            <div className="flex items-center justify-between border-b px-5 py-3">
              <h3 className="font-medium text-gray-900">播放合并视频 · {playbackItem.chapters.length} 个章回</h3>
              <button type="button" onClick={() => setPlaybackItem(null)} aria-label="关闭播放"
                className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"><X className="h-5 w-5" /></button>
            </div>
            <div className="flex min-h-0 items-center justify-center bg-black">
              <video src={playbackItem.videoUrl} controls autoPlay playsInline
                className="max-h-[80vh] w-full" />
            </div>
          </div>
        </div>
      )}

      {currentPlayingItem?.videoUrl && (
        <div className="fixed inset-0 z-[320] flex items-center justify-center bg-black/80 p-4" onClick={event => { event.stopPropagation(); closeVideo(); }}>
          <div className="flex max-h-[94vh] w-full max-w-7xl flex-col overflow-hidden rounded-xl bg-white" onClick={event => event.stopPropagation()}>
            <div className="flex items-center justify-between border-b px-5 py-3">
              <h3 className="font-medium text-gray-900">章回合并视频 · 制作封面</h3>
              <button type="button" onClick={closeVideo} className="rounded p-1 text-gray-400 hover:bg-gray-100"><X className="h-5 w-5" /></button>
            </div>
            <div className="grid min-h-0 flex-1 overflow-y-auto lg:grid-cols-[minmax(0,1fr)_20rem]">
              <div className="min-w-0 border-r border-gray-200">
                <div className="flex min-h-56 items-center justify-center bg-black">
                  <video
                    ref={videoRef} src={currentPlayingItem.videoUrl} controls
                    className="max-h-[55vh] w-full"
                    onLoadedMetadata={event => {
                      const duration = event.currentTarget.duration;
                      setVideoDuration(Number.isFinite(duration) ? duration : 0);
                      if (frameSeconds > 0 && Number.isFinite(duration)) event.currentTarget.currentTime = Math.min(frameSeconds, Math.max(0, duration - 0.05));
                      event.currentTarget.pause();
                    }}
                    onTimeUpdate={event => {
                      const seconds = event.currentTarget.currentTime;
                      setFrameSeconds(seconds);
                      savePlaybackPosition(novelId, currentPlayingItem.id, seconds);
                    }}
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
                  <fieldset>
                    <legend className="mb-2 text-sm font-medium text-gray-900">文字款式</legend>
                    <div className="grid gap-2 sm:grid-cols-2">
                      {coverTextStyles.map(option => (
                        <button key={option.id} type="button" onClick={() => setTextStyle(option.id)}
                          aria-pressed={textStyle === option.id}
                          className={`flex items-center gap-3 rounded-lg border p-2.5 text-left transition-colors ${textStyle === option.id ? 'border-blue-500 bg-blue-50' : 'border-gray-200 bg-white hover:border-gray-300'}`}>
                          <span className="flex h-12 w-16 shrink-0 items-center justify-center rounded bg-[#222326]">
                            <span className={`text-2xl ${option.id === 'vintage' ? 'font-serif text-[#a95340]' : option.id === 'editorial' ? 'font-sans font-bold text-[#f9f4ea]' : 'font-serif text-[#ebdec8]'}`}>药</span>
                          </span>
                          <span className="min-w-0">
                            <span className={`block text-sm font-medium ${textStyle === option.id ? 'text-blue-800' : 'text-gray-900'}`}>{option.name}</span>
                            <span className="block text-xs text-gray-500">{option.description}</span>
                          </span>
                        </button>
                      ))}
                    </div>
                    <p className="mt-1.5 text-xs text-gray-500">当前 {aspectRatio}：生成时自动采用该比例的文字排版。</p>
                  </fieldset>
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
                    disabled={generatingCover}
                    className="btn-primary w-full justify-center disabled:cursor-not-allowed disabled:opacity-50">
                    {generatingCover
                      ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <ImageIcon className="mr-2 h-4 w-4" />}
                    {generatingCover ? '提交中...' : activeCovers.some(cover => cover.aspectRatio === aspectRatio)
                      ? '再提交该比例封面' : savedCovers.some(cover => cover.aspectRatio === aspectRatio) ? '重新生成该比例封面' : '生成视频封面'}
                  </button>
                </div>
              </div>
              <aside className="flex flex-col border-t bg-gray-50 p-5 lg:border-t-0">
                <div className="mb-3 flex items-center justify-between gap-2">
                  <h4 className="font-medium text-gray-900">视频封面</h4>
                  {savedCovers.length > 0 && <span className="text-xs text-gray-500">已保存 {savedCovers.length} 种比例</span>}
                </div>
                {coverTabs.length > 0 && <div role="tablist" aria-label="视频封面比例" className="mb-3 flex flex-wrap gap-2">
                  {coverTabs.map(ratio => <button key={ratio} type="button" role="tab"
                    aria-selected={visibleCoverRatio === ratio} aria-controls="selected-video-cover" tabIndex={visibleCoverRatio === ratio ? 0 : -1}
                    onClick={() => setSelectedCoverRatio(ratio)}
                    onKeyDown={event => {
                      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
                      event.preventDefault();
                      const index = coverTabs.indexOf(ratio);
                      const next = event.key === 'Home' ? 0 : event.key === 'End' ? coverTabs.length - 1
                        : (index + (event.key === 'ArrowRight' ? 1 : -1) + coverTabs.length) % coverTabs.length;
                      setSelectedCoverRatio(coverTabs[next]);
                      const tabs = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]');
                      tabs?.[next]?.focus();
                    }}
                    className={`rounded-md border px-3 py-1.5 text-sm ${visibleCoverRatio === ratio ? 'border-blue-500 bg-blue-50 font-medium text-blue-700' : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300'}`}>
                    {ratio}{activeCovers.some(cover => cover.aspectRatio === ratio) && <Loader2 className="ml-1 inline h-3 w-3 animate-spin" />}
                  </button>)}
                </div>}
                <div id="selected-video-cover" role="tabpanel" aria-label={visibleCoverRatio ? `${visibleCoverRatio} 视频封面` : '视频封面'}>
                {visibleActiveCover && (
                  <div className="mb-3 flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-700">
                    <Loader2 className="h-4 w-4 shrink-0 animate-spin" />{visibleActiveCover.currentStep || (visibleActiveCover.status === 'pending' ? '等待生成...' : '正在生成封面...')}
                  </div>
                )}
                {visibleFailedCover && (
                  <div className="mb-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                    {visibleFailedCover.errorMessage || '封面生成失败，请重试'}
                  </div>
                )}
                {visibleSavedCover ? (
                  <div className="min-h-0 rounded-lg border border-gray-200 bg-white p-2">
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <span className="text-xs text-gray-500">文字款式：{coverStyleName(visibleSavedCover.textStyle)}</span>
                      <a href={novelApi.videoCoverDownloadUrl(novelId, currentPlayingItem.id, visibleSavedCover.id)}
                        className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-blue-700 hover:bg-blue-50"><Download className="h-3.5 w-3.5" />下载</a>
                    </div>
                    {visibleSavedCover.imageUrl && <button type="button" onClick={() => setPreviewCover(visibleSavedCover)} aria-label={`放大预览 ${visibleSavedCover.aspectRatio} 视频封面`}
                      className="w-full cursor-zoom-in rounded-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500">
                      <img src={visibleSavedCover.imageUrl} alt={`${visibleSavedCover.title} ${visibleSavedCover.aspectRatio} 视频封面`} className="max-h-[55vh] w-full rounded-lg bg-gray-900 object-contain hover:opacity-90" />
                    </button>}
                  </div>
                ) : !visibleActiveCover && !visibleFailedCover ? (
                  <div className="flex min-h-64 flex-col items-center justify-center rounded-lg border border-dashed border-gray-300 text-center text-sm text-gray-500">
                    <ImageIcon className="mb-3 h-8 w-8 text-gray-400" />选好视频帧后生成封面
                  </div>
                ) : null}
                </div>
                <p className="mt-3 text-xs leading-5 text-gray-500">使用当前场景分镜图工作流生成画面，再将标题和署名准确排版在封面上。</p>
              </aside>
            </div>
          </div>
        </div>
      )}
      {previewCover?.imageUrl && currentPlayingItem && (
        <div className="fixed inset-0 z-[340] flex flex-col items-center justify-center gap-4 bg-black/90 p-4"
          role="dialog" aria-modal="true" aria-label="视频封面大图预览"
          onClick={event => { event.stopPropagation(); setPreviewCover(null); }}>
          <div className="flex w-full max-w-7xl items-center justify-between text-white" onClick={event => event.stopPropagation()}>
            <span className="truncate text-sm font-medium">视频封面 · {previewCover.title} · {previewCover.aspectRatio} · {coverStyleName(previewCover.textStyle)}</span>
            <div className="flex items-center gap-2">
              <a href={novelApi.videoCoverDownloadUrl(novelId, currentPlayingItem.id, previewCover.id)}
                className="inline-flex items-center gap-1 rounded-lg px-3 py-2 text-sm hover:bg-white/15"><Download className="h-4 w-4" />下载</a>
              <button type="button" onClick={() => setPreviewCover(null)} aria-label="关闭封面预览"
                className="rounded-lg p-2 hover:bg-white/15"><X className="h-5 w-5" /></button>
            </div>
          </div>
          <img src={previewCover.imageUrl} alt={`${previewCover.title} 视频封面大图`}
            className="max-h-[85vh] max-w-full rounded-lg object-contain shadow-2xl"
            onClick={event => event.stopPropagation()} />
        </div>
      )}
    </div>,
    document.body,
  );
}
