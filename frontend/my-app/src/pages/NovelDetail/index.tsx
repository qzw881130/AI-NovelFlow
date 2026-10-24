import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type MouseEvent as ReactMouseEvent } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft, Plus, Loader2, FileText, Trash2, Edit3, CheckCircle, AlertCircle, Clock, Wand2, Upload, Play, Download, Video, X, RefreshCw, Combine, BookOpen } from 'lucide-react';
import { useTranslation } from '../../stores/i18nStore';
import { toast } from '../../stores/toastStore';
import { chapterApi, type ChapterAiSplitBatch } from '../../api/chapters';
import type { Chapter, ChapterVideoAsset } from '../../types';
import { useNovelDetailState } from './hooks/useNovelDetailState';
import { CreateChapterModal } from './components/CreateChapterModal';
import { BatchImportModal } from './components/BatchImportModal';
import { MergeChapterVideosModal } from './components/MergeChapterVideosModal';
import { ChapterReaderModal } from './components/ChapterReaderModal';
import { BatchAiSplitModal } from './components/BatchAiSplitModal';

function StatusIcon({ status, iconInfo }: { status: Chapter['status']; iconInfo: { icon: string; color: string; spin?: boolean } }) {
  if (iconInfo.icon === 'check') return <CheckCircle className={`h-5 w-5 ${iconInfo.color}`} />;
  if (iconInfo.icon === 'alert') return <AlertCircle className={`h-5 w-5 ${iconInfo.color}`} />;
  if (iconInfo.icon === 'clock') return <Clock className={`h-5 w-5 ${iconInfo.color}`} />;
  return <Loader2 className={`h-5 w-5 ${iconInfo.color} ${iconInfo.spin ? 'animate-spin' : ''}`} />;
}

function formatDuration(seconds?: number | null) {
  if (!seconds || seconds <= 0) return '--:--';
  const totalSeconds = Math.round(seconds);
  const minutes = Math.floor(totalSeconds / 60);
  const remainingSeconds = totalSeconds % 60;
  return `${minutes}:${String(remainingSeconds).padStart(2, '0')}`;
}

function formatFileSize(bytes?: number | null) {
  if (!bytes || bytes <= 0) return '--';
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function getChapterVideoAssets(chapter: Chapter): ChapterVideoAsset[] {
  if (chapter.videoAssets?.length) return chapter.videoAssets;
  const draftUrl = chapter.chapterVideoUrl || chapter.finalVideo;
  return draftUrl ? [{ id: chapter.chapterVideoTaskId || 'draft', profileKey: 'draft', kind: 'draft', label: '初稿', videoUrl: draftUrl, duration: chapter.chapterVideoDuration, fileSize: chapter.chapterVideoSize, shotCount: chapter.chapterVideoShotCount }] : [];
}

function getChapterContentLength(chapter: Chapter): number {
  return typeof chapter.contentLength === 'number'
    ? chapter.contentLength
    : (chapter.content || '').replace(/\s/g, '').length;
}

function ChapterRow({ chapter, index, novelId, selected, onToggleSelect, onCheckboxClick, onPointerDown, getStatusIcon, getStatusText, onPlayVideo }: {
  chapter: Chapter; index: number; novelId: string; selected: boolean; onToggleSelect: () => void;
  onCheckboxClick: (event: ReactMouseEvent<HTMLInputElement>) => void;
  onPointerDown: (event: ReactPointerEvent<HTMLDivElement>) => void;
  getStatusIcon: (s: Chapter['status']) => { icon: string; color: string; spin?: boolean };
  getStatusText: (s: Chapter['status']) => string;
  onPlayVideo: (chapter: Chapter, asset: ChapterVideoAsset) => void;
}) {
  const { t } = useTranslation();
  const iconInfo = getStatusIcon(chapter.status);
  const contentLength = getChapterContentLength(chapter);
  const videoAssets = getChapterVideoAssets(chapter);
  const imageStats = chapter.shotImageStats ?? { generated: 0, total: 0, passed: 0, warning: 0, failed: 0 };
  return (
    <div data-chapter-select-index={index} onPointerDown={onPointerDown}
      className={`flex items-center justify-between rounded-lg p-4 transition-colors ${selected ? 'bg-blue-50 ring-1 ring-blue-200' : 'bg-gray-50 hover:bg-gray-100'}`}>
      <div className="mr-4 flex min-w-0 flex-1 items-center gap-4">
        <input
          type="checkbox"
          checked={selected}
          onChange={onToggleSelect}
          onClick={onCheckboxClick}
          className="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
          aria-label={`选择章回 ${chapter.title}`}
        />
        <span className="text-sm font-medium text-gray-400 w-8">{String(index + 1).padStart(2, '0')}</span>
        <StatusIcon status={chapter.status} iconInfo={iconInfo} />
        <div className="min-w-0">
          <h3 className="truncate font-medium text-gray-900">{chapter.title}</h3>
          <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs">
            <span className="text-gray-500">{contentLength.toLocaleString()} 字{chapter.status !== 'pending' && ` · ${getStatusText(chapter.status)}`}{chapter.progress > 0 && ` · ${chapter.progress}%`}</span>
            <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium ${chapter.aiSplitCompleted ? 'bg-green-100 text-green-700' : 'bg-gray-200 text-gray-500'}`}>
              <span className={`h-1.5 w-1.5 rounded-full ${chapter.aiSplitCompleted ? 'bg-green-600' : 'bg-gray-400'}`} aria-hidden="true" />
              {t(chapter.aiSplitCompleted ? 'novelDetail.aiSplitCompleted' : 'novelDetail.aiSplitPending')}
            </span>
            <span className="font-medium text-gray-600">分镜图 {imageStats.generated}/{imageStats.total}</span>
            <span className="text-green-700" title="质量数量只统计当前图片已有明确评审结论的分镜">通过 {imageStats.passed}</span>
            <span className="text-amber-700">警告 {imageStats.warning}</span>
            <span className="text-red-700">失败 {imageStats.failed}</span>
          </div>
          {videoAssets.length > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-gray-500">
              {videoAssets.map(asset => <span key={asset.id} className={`inline-flex items-center gap-1 rounded-full px-2 py-1 ${asset.kind === 'hd' ? 'bg-purple-50 text-purple-700' : 'bg-blue-50 text-blue-700'}`}><Video className="h-3 w-3" />{asset.label} · {formatDuration(asset.duration)} · {formatFileSize(asset.fileSize)}</span>)}
            </div>
          )}
        </div>
      </div>
      <div className="flex shrink-0 gap-2">
        {videoAssets.length > 0 && (
          <>
            <details className="relative">
              <summary className="btn-secondary cursor-pointer list-none text-sm py-1.5 px-3"><Play className="h-3 w-3 mr-1" />播放 ▾</summary>
              <div className="absolute right-0 z-30 mt-1 w-40 rounded-lg border bg-white p-1 shadow-lg">
                {videoAssets.map(asset => <button key={asset.id} onClick={() => onPlayVideo(chapter, asset)} className="w-full rounded px-3 py-2 text-left text-sm hover:bg-gray-50">{asset.label}</button>)}
              </div>
            </details>
            <details className="relative">
              <summary className="btn-secondary cursor-pointer list-none text-sm py-1.5 px-3"><Download className="h-3 w-3 mr-1" />下载 ▾</summary>
              <div className="absolute right-0 z-30 mt-1 w-40 rounded-lg border bg-white p-1 shadow-lg">
                {videoAssets.map(asset => <a key={asset.id} href={asset.videoUrl} download className="block rounded px-3 py-2 text-sm hover:bg-gray-50">{asset.label}</a>)}
              </div>
            </details>
          </>
        )}
        <Link to={`/novels/${novelId}/chapters/${chapter.id}`} className="btn-primary text-sm py-1.5 px-3">
          <Edit3 className="h-3 w-3 mr-1" />{t('common.edit')}
        </Link>
        <Link to={`/novels/${novelId}/chapters/${chapter.id}/generate`}
          className="btn-secondary text-sm py-1.5 px-3 bg-purple-50 text-purple-600 hover:bg-purple-100 border-purple-200">
          <Wand2 className="h-3 w-3 mr-1" />{t('common.generate')}
        </Link>
      </div>
    </div>
  );
}

export default function NovelDetail() {
  const { t } = useTranslation();
  const state = useNovelDetailState();
  const [playingChapter, setPlayingChapter] = useState<{ chapter: Chapter; asset: ChapterVideoAsset } | null>(null);
  const [selectedChapterIds, setSelectedChapterIds] = useState<string[]>([]);
  const [isDownloadingOriginals, setIsDownloadingOriginals] = useState(false);
  const [showMergeModal, setShowMergeModal] = useState(false);
  const [showReaderModal, setShowReaderModal] = useState(false);
  const [splitModalMode, setSplitModalMode] = useState<'create' | 'progress' | null>(null);
  const [latestSplitBatch, setLatestSplitBatch] = useState<ChapterAiSplitBatch | null>(null);
  const latestSplitBatchRef = useRef<ChapterAiSplitBatch | null>(null);
  const dragSelectionRef = useRef<{ pointerId: number; startIndex: number; lastIndex: number; selecting: boolean; initial: Set<string> } | null>(null);
  const suppressCheckboxClickRef = useRef<string | null>(null);
  const [mergeProfile, setMergeProfile] = useState<{ kind: 'draft' | 'hd'; targetMegapixels?: number }>({ kind: 'draft' });
  const totalContentLength = state.chapters.reduce((total, chapter) => total + getChapterContentLength(chapter), 0);
  const hdMergeTargets = Array.from(new Set(state.chapters.flatMap(chapter => getChapterVideoAssets(chapter).filter(asset => asset.kind === 'hd' && asset.targetMegapixels != null).map(asset => Number(asset.targetMegapixels))))).sort((a, b) => a - b);

  const refreshSplitBatches = async () => {
    if (!state.id) return;
    try {
      const response = await chapterApi.listAiSplitBatches(state.id);
      if (!response.success) return;
      const next = response.data?.[0] || null;
      const previous = latestSplitBatchRef.current;
      latestSplitBatchRef.current = next;
      setLatestSplitBatch(next);
      if (previous?.id === next?.id && previous?.status === 'running' && next?.status !== 'running') {
        void state.fetchData(false);
      }
    } catch (error) {
      console.error('读取 AI 拆分任务失败:', error);
    }
  };

  useEffect(() => { void refreshSplitBatches(); }, [state.id]);
  useEffect(() => {
    if (!state.id || latestSplitBatch?.status !== 'running') return;
    const timer = window.setInterval(() => void refreshSplitBatches(), 3000);
    return () => window.clearInterval(timer);
  }, [state.id, latestSplitBatch?.id, latestSplitBatch?.status]);

  const applyDragRange = (index: number) => {
    const drag = dragSelectionRef.current;
    if (!drag || drag.lastIndex === index) return;
    drag.lastIndex = index;
    const next = new Set(drag.initial);
    for (let position = Math.min(drag.startIndex, index); position <= Math.max(drag.startIndex, index); position++) {
      const id = state.chapters[position]?.id;
      if (!id) continue;
      if (drag.selecting) next.add(id);
      else next.delete(id);
    }
    setSelectedChapterIds([...next]);
  };

  useEffect(() => {
    const move = (event: PointerEvent) => {
      if (!dragSelectionRef.current || event.pointerId !== dragSelectionRef.current.pointerId) return;
      const row = document.elementFromPoint(event.clientX, event.clientY)?.closest<HTMLElement>('[data-chapter-select-index]');
      if (row) applyDragRange(Number(row.dataset.chapterSelectIndex));
    };
    const end = () => {
      dragSelectionRef.current = null;
      document.body.classList.remove('select-none');
      window.setTimeout(() => { suppressCheckboxClickRef.current = null; }, 0);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', end);
    window.addEventListener('pointercancel', end);
    window.addEventListener('blur', end);
    return () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', end);
      window.removeEventListener('pointercancel', end);
      window.removeEventListener('blur', end);
      document.body.classList.remove('select-none');
    };
  }, [state.chapters]);

  const beginDragSelection = (event: ReactPointerEvent<HTMLDivElement>, index: number) => {
    if (event.pointerType !== 'mouse' || event.button !== 0) return;
    const target = event.target as HTMLElement;
    if (target.closest('a, button, details, summary')) return;
    event.preventDefault();
    const id = state.chapters[index]?.id;
    if (!id) return;
    if (target.closest('input[type="checkbox"]')) suppressCheckboxClickRef.current = id;
    dragSelectionRef.current = { pointerId: event.pointerId, startIndex: index, lastIndex: -1,
      selecting: !selectedChapterIds.includes(id), initial: new Set(selectedChapterIds) };
    document.body.classList.add('select-none');
    applyDragRange(index);
  };

  const handleDownloadOriginals = async () => {
    if (!state.id || selectedChapterIds.length === 0 || isDownloadingOriginals) return;
    setIsDownloadingOriginals(true);
    try {
      const blob = await chapterApi.downloadOriginals(state.id, selectedChapterIds);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${state.novel?.title || 'novel'}-原文.zip`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      console.error('下载原文失败:', error);
      toast.error(error instanceof Error ? error.message : '下载原文失败');
    } finally {
      setIsDownloadingOriginals(false);
    }
  };

  if (state.isLoading) return <div className="flex justify-center items-center h-64"><Loader2 className="h-8 w-8 animate-spin text-primary-600" /></div>;
  if (!state.novel) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-500">{t('novelDetail.novelNotFound')}</p>
        <Link to="/novels" className="text-primary-600 hover:underline mt-2 inline-block">{t('novelDetail.backToNovels')}</Link>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link to="/novels" className="p-2 text-gray-400 hover:text-gray-600 transition-colors"><ArrowLeft className="h-5 w-5" /></Link>
          <div>
            <h1 className="text-2xl font-bold text-gray-900">{state.novel.title}</h1>
            <p className="text-sm text-gray-500">{state.novel.author} · {state.chapters.length} {t('novelDetail.chapters')} · {t('novelDetail.totalWordCount', { count: totalContentLength.toLocaleString() })}</p>
          </div>
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          <button
            type="button"
            onClick={() => setSplitModalMode(latestSplitBatch?.status === 'running' ? 'progress' : 'create')}
            disabled={selectedChapterIds.length === 0 && latestSplitBatch?.status !== 'running'}
            className="btn-secondary disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Wand2 className="h-4 w-4 mr-2" />{latestSplitBatch?.status === 'running' ? '查看拆分进度' : t('novelDetail.batchAiSplit.button')}{latestSplitBatch?.status !== 'running' && selectedChapterIds.length > 0 ? ` (${selectedChapterIds.length})` : ''}
          </button>
          <details className="relative">
            <summary className="btn-secondary cursor-pointer list-none"><Combine className="h-4 w-4 mr-2" />合并所有章回视频 ▾</summary>
            <div className="absolute right-0 z-30 mt-1 w-40 rounded-lg border bg-white p-1 shadow-lg">
              <button onClick={() => { setMergeProfile({ kind: 'draft' }); setShowMergeModal(true); }} className="w-full rounded px-3 py-2 text-left text-sm hover:bg-gray-50">合并初稿</button>
              {hdMergeTargets.map(mp => <button key={mp} onClick={() => { setMergeProfile({ kind: 'hd', targetMegapixels: mp }); setShowMergeModal(true); }} className="w-full rounded px-3 py-2 text-left text-sm hover:bg-gray-50">合并高清 {mp.toFixed(1)} MP</button>)}
            </div>
          </details>
          <button
            onClick={() => state.setShowCreateModal(true)}
            className="btn-primary"
          >
            <Plus className="h-4 w-4 mr-2" />{t('novelDetail.addChapter')}
          </button>
          <button
            onClick={() => state.setShowBatchImportModal(true)}
            className="btn-secondary"
          >
            <Upload className="h-4 w-4 mr-2" />{t('novelDetail.batchImport.button')}
          </button>
        </div>
      </div>

      {state.novel.description && <div className="card bg-gray-50"><p className="text-gray-600">{state.novel.description}</p></div>}

      {latestSplitBatch && <button type="button" onClick={() => setSplitModalMode('progress')}
        className="flex w-full items-center justify-between rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-left text-sm text-blue-800 hover:bg-blue-100">
        <span>批量 AI 拆分：{latestSplitBatch.status === 'running' ? '后台处理中' : latestSplitBatch.status === 'completed' ? '已完成' : '部分失败'} · 已处理 {latestSplitBatch.completed + latestSplitBatch.failed}/{latestSplitBatch.total}</span>
        <span>查看详情</span>
      </button>}

      <div className="card">
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold text-gray-900">{t('novelDetail.chapterCount', { count: state.chapters.length })}</h2>
            {state.chapters.length > 0 && (
              <label className="flex items-center gap-2 text-sm text-gray-500">
                <input
                  type="checkbox"
                  checked={selectedChapterIds.length > 0 && selectedChapterIds.length === state.chapters.length}
                  onChange={(event) => setSelectedChapterIds(event.target.checked ? state.chapters.map(chapter => chapter.id) : [])}
                  className="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                />
                全选
              </label>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setShowReaderModal(true)}
              disabled={state.chapters.length === 0}
              className="btn-secondary text-sm py-1.5 px-3 disabled:cursor-not-allowed disabled:opacity-50"
              title="阅读小说正文"
            >
              <BookOpen className="h-3 w-3 mr-1" />阅读
            </button>
            <button
              onClick={handleDownloadOriginals}
              disabled={selectedChapterIds.length === 0 || isDownloadingOriginals}
              className="btn-secondary text-sm py-1.5 px-3 disabled:opacity-50 disabled:cursor-not-allowed"
              title="下载选中的章回原文"
            >
              {isDownloadingOriginals ? <Loader2 className="h-3 w-3 mr-1 animate-spin" /> : <Download className="h-3 w-3 mr-1" />}
              下载原文{selectedChapterIds.length > 0 ? ` ${selectedChapterIds.length}` : ''}
            </button>
            <button
              onClick={async () => {
                await state.handleDeleteChapters(selectedChapterIds);
                setSelectedChapterIds([]);
              }}
              disabled={selectedChapterIds.length === 0 || state.isDeleting}
              className="btn-secondary text-sm py-1.5 px-3 text-red-600 hover:bg-red-50 disabled:opacity-50 disabled:cursor-not-allowed"
              title="删除所选章回"
            >
              {state.isDeleting ? <Loader2 className="h-3 w-3 mr-1 animate-spin" /> : <Trash2 className="h-3 w-3 mr-1" />}
              删除{selectedChapterIds.length > 0 ? ` ${selectedChapterIds.length}` : ''}
            </button>
            <button
              onClick={() => state.fetchData(false)}
              disabled={state.isRefreshing}
              className="btn-secondary text-sm py-1.5 px-3 disabled:opacity-50 disabled:cursor-not-allowed"
              title="刷新章回列表"
            >
              <RefreshCw className={`h-3 w-3 mr-1 ${state.isRefreshing ? 'animate-spin' : ''}`} />刷新
            </button>
          </div>
        </div>
        {state.chapters.length === 0 ? (
          <div className="text-center py-12">
            <FileText className="mx-auto h-12 w-12 text-gray-300" />
            <h3 className="mt-4 text-lg font-medium text-gray-900">{t('novelDetail.noChapters')}</h3>
            <p className="mt-1 text-sm text-gray-500">{t('novelDetail.clickAddChapter')}</p>
          </div>
        ) : (
          <div className="space-y-2">
            {state.chapters.map((chapter, index) => (
              <ChapterRow key={chapter.id} chapter={chapter} index={index} novelId={state.id!}
                selected={selectedChapterIds.includes(chapter.id)}
                onPointerDown={event => beginDragSelection(event, index)}
                onCheckboxClick={event => { if (suppressCheckboxClickRef.current === chapter.id) event.preventDefault(); }}
                onToggleSelect={() => {
                  if (suppressCheckboxClickRef.current === chapter.id) return;
                  setSelectedChapterIds(prev => prev.includes(chapter.id) ? prev.filter(id => id !== chapter.id) : [...prev, chapter.id]);
                }}
                getStatusIcon={state.getStatusIcon} getStatusText={state.getStatusText}
                onPlayVideo={(chapter, asset) => setPlayingChapter({ chapter, asset })} />
            ))}
          </div>
        )}
      </div>

      <CreateChapterModal show={state.showCreateModal} newChapter={state.newChapter}
        onClose={() => state.setShowCreateModal(false)} onSubmit={state.handleCreateChapter} setNewChapter={state.setNewChapter} />
      <BatchImportModal show={state.showBatchImportModal} novelId={state.id!}
        onClose={() => state.setShowBatchImportModal(false)} onImportComplete={state.handleBatchImportComplete} />
      {splitModalMode && (
        <BatchAiSplitModal
          novelId={state.id!}
          chapters={state.chapters.filter(chapter => selectedChapterIds.includes(chapter.id))}
          mode={splitModalMode}
          latestBatch={latestSplitBatch}
          onClose={() => setSplitModalMode(null)}
          onBatchCreated={batch => {
            latestSplitBatchRef.current = batch;
            setLatestSplitBatch(batch);
            setSelectedChapterIds([]);
          }}
        />
      )}
      {showMergeModal && (
        <MergeChapterVideosModal novelId={state.id!} novelTitle={state.novel.title} novelAuthor={state.novel.author} chapters={state.chapters} initialProfile={mergeProfile} onClose={() => setShowMergeModal(false)} />
      )}
      {showReaderModal && state.chapters.length > 0 && (
        <ChapterReaderModal novelId={state.id!} novelTitle={state.novel.title} chapters={state.chapters} onClose={() => setShowReaderModal(false)} />
      )}
      {playingChapter?.asset.videoUrl && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/70 p-4">
          <div className="w-full max-w-4xl rounded-xl bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b px-5 py-4">
              <div>
                <h3 className="text-lg font-semibold text-gray-900">{playingChapter.chapter.title} · {playingChapter.asset.label}</h3>
                <p className="text-xs text-gray-500">
                   {formatDuration(playingChapter.asset.duration)} · {formatFileSize(playingChapter.asset.fileSize)} · {playingChapter.asset.shotCount || 0} 镜头
                </p>
              </div>
              <button onClick={() => setPlayingChapter(null)} className="rounded-lg p-2 text-gray-400 hover:bg-gray-100 hover:text-gray-600">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="bg-black">
              <video src={playingChapter.asset.videoUrl} controls autoPlay className="max-h-[70vh] w-full" />
            </div>
            <div className="flex justify-end gap-2 px-5 py-4">
              <a href={playingChapter.asset.videoUrl} download className="btn-secondary text-sm py-1.5 px-3">
                <Download className="h-3 w-3 mr-1" />下载视频
              </a>
              <button onClick={() => setPlayingChapter(null)} className="btn-primary text-sm py-1.5 px-3">关闭</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
