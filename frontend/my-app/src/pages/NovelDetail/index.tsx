import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft, Plus, Loader2, FileText, Trash2, Edit3, CheckCircle, AlertCircle, Clock, Wand2, Upload, Play, Download, Video, X, RefreshCw } from 'lucide-react';
import { useTranslation } from '../../stores/i18nStore';
import type { Chapter } from '../../types';
import { useNovelDetailState } from './hooks/useNovelDetailState';
import { CreateChapterModal } from './components/CreateChapterModal';
import { BatchImportModal } from './components/BatchImportModal';

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

function getChapterVideoUrl(chapter: Chapter) {
  return chapter.chapterVideoUrl || chapter.finalVideo;
}

function ChapterRow({ chapter, index, novelId, selected, onToggleSelect, getStatusIcon, getStatusText, onPlayVideo }: {
  chapter: Chapter; index: number; novelId: string; selected: boolean; onToggleSelect: () => void;
  getStatusIcon: (s: Chapter['status']) => { icon: string; color: string; spin?: boolean };
  getStatusText: (s: Chapter['status']) => string;
  onPlayVideo: (chapter: Chapter) => void;
}) {
  const { t } = useTranslation();
  const iconInfo = getStatusIcon(chapter.status);
  const contentLength = typeof chapter.contentLength === 'number'
    ? chapter.contentLength
    : (chapter.content || '').replace(/\s/g, '').length;
  const videoUrl = getChapterVideoUrl(chapter);
  return (
    <div className="flex min-w-0 flex-col gap-3 p-3 sm:p-4 xl:flex-row xl:items-center xl:justify-between bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors">
      <div className="flex min-w-0 items-start gap-2 sm:gap-4 xl:items-center">
        <input
          type="checkbox"
          checked={selected}
          onChange={onToggleSelect}
          className="mt-1 h-5 w-5 shrink-0 rounded border-gray-300 text-primary-600 focus:ring-primary-500 xl:mt-0 xl:h-4 xl:w-4"
          aria-label={`选择章回 ${chapter.title}`}
        />
        <span className="min-w-[2ch] shrink-0 text-sm font-medium text-gray-400 sm:min-w-[2rem]">{String(index + 1).padStart(2, '0')}</span>
        <span className="shrink-0"><StatusIcon status={chapter.status} iconInfo={iconInfo} /></span>
        <div className="min-w-0 [overflow-wrap:anywhere]">
          <h3 className="font-medium text-gray-900">{chapter.title}</h3>
          <p className="text-xs text-gray-500">{contentLength.toLocaleString()} 字 · {getStatusText(chapter.status)}{chapter.progress > 0 && ` · ${chapter.progress}%`}</p>
          {videoUrl && (
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-gray-500">
              <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2 py-1 text-blue-700">
                <Video className="h-3 w-3" />合并视频
              </span>
              <span>{formatDuration(chapter.chapterVideoDuration)}</span>
              <span>{formatFileSize(chapter.chapterVideoSize)}</span>
              <span>{chapter.chapterVideoShotCount || 0} 镜头</span>
            </div>
          )}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap sm:justify-end xl:shrink-0 [&>a]:min-h-[44px] [&>button]:min-h-[44px] xl:[&>a]:min-h-0 xl:[&>button]:min-h-0">
        {videoUrl && (
          <>
            <button onClick={() => onPlayVideo(chapter)} className="btn-secondary text-sm py-1.5 px-3" title="播放章回视频">
              <Play className="h-3 w-3 mr-1" />播放
            </button>
            <a href={videoUrl} download className="btn-secondary text-sm py-1.5 px-3" title="下载章回视频">
              <Download className="h-3 w-3 mr-1" />下载
            </a>
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
  const [playingChapter, setPlayingChapter] = useState<Chapter | null>(null);
  const [selectedChapterIds, setSelectedChapterIds] = useState<string[]>([]);

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
    <div className="min-w-0 space-y-4 sm:space-y-6">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div className="flex min-w-0 items-start gap-2 sm:gap-4">
          <Link to="/novels" aria-label={t('novelDetail.backToNovels')} className="shrink-0 p-3 sm:p-2 text-gray-400 hover:text-gray-600 transition-colors"><ArrowLeft className="h-5 w-5" /></Link>
          <div className="min-w-0 [overflow-wrap:anywhere]">
            <h1 className="text-xl sm:text-2xl font-bold text-gray-900">{state.novel.title}</h1>
            <p className="text-sm text-gray-500">{state.novel.author} · {state.chapters.length} {t('novelDetail.chapters')}</p>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap sm:justify-end xl:shrink-0 [&>button]:min-h-[44px] xl:[&>button]:min-h-0">
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

      {state.novel.description && <div className="card bg-gray-50 p-4 sm:p-6"><p className="text-gray-600 [overflow-wrap:anywhere]">{state.novel.description}</p></div>}

      <div className="card min-w-0 p-3 sm:p-6">
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <h2 className="text-lg font-semibold text-gray-900">{t('novelDetail.chapterCount', { count: state.chapters.length })}</h2>
            {state.chapters.length > 0 && (
              <label className="flex min-h-[44px] items-center gap-2 text-sm text-gray-500 sm:min-h-0">
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
          <div className="grid grid-cols-2 gap-2 sm:flex sm:items-center [&>button]:min-h-[44px] xl:[&>button]:min-h-0">
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
                onToggleSelect={() => setSelectedChapterIds(prev => prev.includes(chapter.id) ? prev.filter(id => id !== chapter.id) : [...prev, chapter.id])}
                getStatusIcon={state.getStatusIcon} getStatusText={state.getStatusText}
                onPlayVideo={setPlayingChapter} />
            ))}
          </div>
        )}
      </div>

      <CreateChapterModal show={state.showCreateModal} newChapter={state.newChapter}
        onClose={() => state.setShowCreateModal(false)} onSubmit={state.handleCreateChapter} setNewChapter={state.setNewChapter} />
      <BatchImportModal show={state.showBatchImportModal} novelId={state.id!}
        onClose={() => state.setShowBatchImportModal(false)} onImportComplete={state.handleBatchImportComplete} />
      {playingChapter && getChapterVideoUrl(playingChapter) && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/70 p-3 sm:p-4">
          <div className="flex max-h-[calc(100dvh-2rem)] min-w-0 w-full max-w-4xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl">
            <div className="flex shrink-0 items-center justify-between gap-3 border-b px-4 sm:px-5 py-3 sm:py-4">
              <div className="min-w-0 max-h-[20dvh] overflow-y-auto [overflow-wrap:anywhere]">
                <h3 className="text-lg font-semibold text-gray-900">{playingChapter.title}</h3>
                <p className="text-xs text-gray-500">
                  {formatDuration(playingChapter.chapterVideoDuration)} · {formatFileSize(playingChapter.chapterVideoSize)} · {playingChapter.chapterVideoShotCount || 0} 镜头
                </p>
              </div>
              <button onClick={() => setPlayingChapter(null)} aria-label={t('common.close')} className="shrink-0 rounded-lg p-3 text-gray-400 hover:bg-gray-100 hover:text-gray-600">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="min-h-0 overflow-y-auto bg-black">
              <video src={getChapterVideoUrl(playingChapter)} controls autoPlay className="max-h-[60dvh] w-full" />
            </div>
            <div className="flex shrink-0 flex-wrap justify-end gap-2 px-4 sm:px-5 py-3 sm:py-4 [&>*]:min-h-[44px] sm:[&>*]:min-h-0">
              <a href={getChapterVideoUrl(playingChapter)} download className="btn-secondary text-sm py-1.5 px-3">
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
