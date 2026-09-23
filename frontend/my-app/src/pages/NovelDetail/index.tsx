import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft, Plus, Loader2, FileText, Trash2, Edit3, CheckCircle, AlertCircle, Clock, Wand2, Upload, Play, Download, Video, X, RefreshCw, Combine } from 'lucide-react';
import { useTranslation } from '../../stores/i18nStore';
import type { Chapter, ChapterVideoAsset } from '../../types';
import { useNovelDetailState } from './hooks/useNovelDetailState';
import { CreateChapterModal } from './components/CreateChapterModal';
import { BatchImportModal } from './components/BatchImportModal';
import { MergeChapterVideosModal } from './components/MergeChapterVideosModal';

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

function ChapterRow({ chapter, index, novelId, selected, onToggleSelect, getStatusIcon, getStatusText, onPlayVideo }: {
  chapter: Chapter; index: number; novelId: string; selected: boolean; onToggleSelect: () => void;
  getStatusIcon: (s: Chapter['status']) => { icon: string; color: string; spin?: boolean };
  getStatusText: (s: Chapter['status']) => string;
  onPlayVideo: (chapter: Chapter, asset: ChapterVideoAsset) => void;
}) {
  const { t } = useTranslation();
  const iconInfo = getStatusIcon(chapter.status);
  const contentLength = typeof chapter.contentLength === 'number'
    ? chapter.contentLength
    : (chapter.content || '').replace(/\s/g, '').length;
  const videoAssets = getChapterVideoAssets(chapter);
  return (
    <div className="flex items-center justify-between p-4 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors">
      <div className="flex items-center gap-4">
        <input
          type="checkbox"
          checked={selected}
          onChange={onToggleSelect}
          className="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
          aria-label={`选择章回 ${chapter.title}`}
        />
        <span className="text-sm font-medium text-gray-400 w-8">{String(index + 1).padStart(2, '0')}</span>
        <StatusIcon status={chapter.status} iconInfo={iconInfo} />
        <div>
          <h3 className="font-medium text-gray-900">{chapter.title}</h3>
          <p className="text-xs text-gray-500">{contentLength.toLocaleString()} 字 · {getStatusText(chapter.status)}{chapter.progress > 0 && ` · ${chapter.progress}%`}</p>
          {videoAssets.length > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-gray-500">
              {videoAssets.map(asset => <span key={asset.id} className={`inline-flex items-center gap-1 rounded-full px-2 py-1 ${asset.kind === 'hd' ? 'bg-purple-50 text-purple-700' : 'bg-blue-50 text-blue-700'}`}><Video className="h-3 w-3" />{asset.label} · {formatDuration(asset.duration)} · {formatFileSize(asset.fileSize)}</span>)}
            </div>
          )}
        </div>
      </div>
      <div className="flex gap-2">
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
  const [showMergeModal, setShowMergeModal] = useState(false);
  const [mergeProfile, setMergeProfile] = useState<{ kind: 'draft' | 'hd'; targetMegapixels?: number }>({ kind: 'draft' });
  const hdMergeTargets = Array.from(new Set(state.chapters.flatMap(chapter => getChapterVideoAssets(chapter).filter(asset => asset.kind === 'hd' && asset.targetMegapixels != null).map(asset => Number(asset.targetMegapixels))))).sort((a, b) => a - b);

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
            <p className="text-sm text-gray-500">{state.novel.author} · {state.chapters.length} {t('novelDetail.chapters')}</p>
          </div>
        </div>
        <div className="flex gap-2">
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
                onPlayVideo={(chapter, asset) => setPlayingChapter({ chapter, asset })} />
            ))}
          </div>
        )}
      </div>

      <CreateChapterModal show={state.showCreateModal} newChapter={state.newChapter}
        onClose={() => state.setShowCreateModal(false)} onSubmit={state.handleCreateChapter} setNewChapter={state.setNewChapter} />
      <BatchImportModal show={state.showBatchImportModal} novelId={state.id!}
        onClose={() => state.setShowBatchImportModal(false)} onImportComplete={state.handleBatchImportComplete} />
      {showMergeModal && (
        <MergeChapterVideosModal novelId={state.id!} chapters={state.chapters} initialProfile={mergeProfile} onClose={() => setShowMergeModal(false)} />
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
