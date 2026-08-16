import { Link } from 'react-router-dom';
import { ArrowLeft, Save, Loader2, Play, Trash2, Sparkles, MapPin, Film, Package } from 'lucide-react';
import { useTranslation } from '../../stores/i18nStore';
import type { Chapter, Novel } from '../../types';
import type { ParseResultData } from './types';
import { useChapterDetailState } from './hooks/useChapterDetailState';
import { ImagePreviewModal } from './components/ImagePreviewModal';
import { getStatusInfo } from './utils/getStatusInfo';

function ParseResultCard({ result, type, onViewClick }: { result: ParseResultData; type: 'characters' | 'scenes' | 'props'; onViewClick: () => void }) {
  const { t } = useTranslation();
  const isCharacter = type === 'characters';
  const isScene = type === 'scenes';
  const isProp = type === 'props';

  let bgClass = 'bg-purple-50 border-purple-200';
  let iconBgClass = 'bg-purple-100';
  let iconClass = 'text-purple-600';
  let textClass = 'text-purple-800';
  let subTextClass = 'text-purple-600';
  let btnClass = 'bg-purple-600 hover:bg-purple-700';
  let Icon = Sparkles;
  let labelKey = 'chapterDetail.parseComplete';
  let btnKey = 'chapterDetail.viewCharacters';

  if (isScene) {
    bgClass = 'bg-teal-50 border-teal-200';
    iconBgClass = 'bg-teal-100';
    iconClass = 'text-teal-600';
    textClass = 'text-teal-800';
    subTextClass = 'text-teal-600';
    btnClass = 'bg-teal-600 hover:bg-teal-700';
    Icon = MapPin;
    labelKey = 'chapterDetail.parseScenesComplete';
    btnKey = 'chapterDetail.viewScenes';
  } else if (isProp) {
    bgClass = 'bg-amber-50 border-amber-200';
    iconBgClass = 'bg-amber-100';
    iconClass = 'text-amber-600';
    textClass = 'text-amber-800';
    subTextClass = 'text-amber-600';
    btnClass = 'bg-amber-600 hover:bg-amber-700';
    Icon = Package;
    labelKey = 'chapterDetail.parsePropsComplete';
    btnKey = 'chapterDetail.viewProps';
  }

  return (
    <div className={`card ${bgClass}`}>
      <div className="flex items-center gap-3">
        <div className={`p-2 ${iconBgClass} rounded-full`}><Icon className={`h-5 w-5 ${iconClass}`} /></div>
        <div>
          <p className={`font-medium ${textClass}`}>{t(labelKey)}</p>
          <p className={`text-sm ${subTextClass}`}>{t('chapterDetail.parseResult', { created: result.created, updated: result.updated })}</p>
        </div>
        <button onClick={onViewClick} className={`ml-auto btn-primary ${btnClass} text-sm`}>
          {t(btnKey)}
        </button>
      </div>
    </div>
  );
}

function GeneratedAssets({ chapter, onImageClick }: { chapter: Chapter; onImageClick: (url: string, idx: number, imgs: string[]) => void }) {
  const { t } = useTranslation();
  const hasAssets = chapter.characterImages?.length || chapter.shotImages?.length || chapter.shotVideos?.length;
  if (!hasAssets) return null;

  return (
    <div className="card">
      <h3 className="text-lg font-semibold text-gray-900 mb-4">{t('chapterDetail.generatedResources')}</h3>
      {chapter.characterImages?.length ? (
        <div className="mb-6">
          <h4 className="text-sm font-medium text-gray-700 mb-2">{t('chapterDetail.characterImages')}</h4>
          <div className="grid grid-cols-4 gap-4">
            {chapter.characterImages.map((img, idx) => (
              <img key={idx} src={img} alt={t('chapterDetail.characterImageAlt', { index: idx + 1 })}
                className="rounded-lg cursor-pointer hover:opacity-90 transition-opacity" onClick={() => onImageClick(img, idx, chapter.characterImages || [])} />
            ))}
          </div>
        </div>
      ) : null}
      {chapter.shotImages?.length ? (
        <div className="mb-6">
          <h4 className="text-sm font-medium text-gray-700 mb-2">{t('chapterDetail.shotImages')}</h4>
          <div className="grid grid-cols-4 gap-4">
            {chapter.shotImages.map((img, idx) => (
              <img key={idx} src={img} alt={t('chapterDetail.shotImageAlt', { index: idx + 1 })}
                className="rounded-lg cursor-pointer hover:opacity-90 transition-opacity" onClick={() => onImageClick(img, idx, chapter.shotImages || [])} />
            ))}
          </div>
        </div>
      ) : null}
      {chapter.shotVideos?.length ? (
        <div>
          <h4 className="text-sm font-medium text-gray-700 mb-2">{t('chapterDetail.shotVideos')}</h4>
          <div className="grid grid-cols-2 gap-4">
            {chapter.shotVideos.map((video, idx) => <video key={idx} src={video} controls className="rounded-lg" />)}
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default function ChapterDetail() {
  const { t } = useTranslation();
  const state = useChapterDetailState();

  if (state.isLoading) return <div className="flex justify-center items-center h-64"><Loader2 className="h-8 w-8 animate-spin text-primary-600" /></div>;
  if (!state.chapter || !state.novel) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-500">{t('chapterDetail.chapterNotExist')}</p>
        <Link to={`/novels/${state.id}`} className="text-primary-600 hover:underline mt-2 inline-block">{t('chapterDetail.backToNovel')}</Link>
      </div>
    );
  }

  const statusInfo = getStatusInfo(state.chapter.status, t);
  const StatusIcon = statusInfo.icon;
  const shouldSpin = !['completed', 'failed', 'pending'].includes(state.chapter.status);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-4 min-w-0">
          <Link to={`/novels/${state.id}`} className="p-2 text-gray-400 hover:text-gray-600 transition-colors flex-shrink-0"><ArrowLeft className="h-5 w-5" /></Link>
          <div className="min-w-0">
            <h1 className="text-2xl font-bold text-gray-900 truncate">{t('chapterDetail.chapterTitle', { number: state.chapter.number, title: state.chapter.title })}</h1>
            <p className="text-sm text-gray-500 truncate">{state.novel.title}</p>
          </div>
        </div>
        <div className="flex gap-3 overflow-x-auto pb-1 flex-shrink-0 max-w-[70vw]">
          <button onClick={state.handleDelete} className="btn-secondary text-red-600 hover:text-red-700 border-red-200 hover:border-red-300 whitespace-nowrap flex-shrink-0">
            <Trash2 className="h-4 w-4 mr-2 flex-shrink-0" />{t('common.delete')}
          </button>
          <button onClick={state.handleSave} disabled={state.isSaving} className="btn-primary whitespace-nowrap flex-shrink-0">
            {state.isSaving ? <Loader2 className="h-4 w-4 mr-2 animate-spin flex-shrink-0" /> : <Save className="h-4 w-4 mr-2 flex-shrink-0" />}{t('common.save')}
          </button>
          <button onClick={state.handleParseCharacters} className="btn-secondary text-purple-600 border-purple-200 hover:bg-purple-50 disabled:opacity-50 whitespace-nowrap flex-shrink-0">
            {state.parsingChapter ? <Loader2 className="h-4 w-4 mr-2 animate-spin flex-shrink-0" /> : <Sparkles className="h-4 w-4 mr-2 flex-shrink-0" />}{t('chapterDetail.parseCharacters')}
          </button>
          <button onClick={state.handleParseScenes} className="btn-secondary text-teal-600 border-teal-200 hover:bg-teal-50 disabled:opacity-50 whitespace-nowrap flex-shrink-0" disabled={state.parsingScenes}>
            {state.parsingScenes ? <Loader2 className="h-4 w-4 mr-2 animate-spin flex-shrink-0" /> : <MapPin className="h-4 w-4 mr-2 flex-shrink-0" />}{t('chapterDetail.parseScenes')}
          </button>
          <button onClick={state.handleParseProps} className="btn-secondary text-amber-600 border-amber-200 hover:bg-amber-50 disabled:opacity-50 whitespace-nowrap flex-shrink-0" disabled={state.parsingProps}>
            {state.parsingProps ? <Loader2 className="h-4 w-4 mr-2 animate-spin flex-shrink-0" /> : <Package className="h-4 w-4 mr-2 flex-shrink-0" />}{t('chapterDetail.parseProps')}
          </button>
          <button onClick={state.handleGenerate} className="btn-primary bg-green-600 hover:bg-green-700 whitespace-nowrap flex-shrink-0" disabled={state.chapter.status !== 'pending' && state.chapter.status !== 'failed'}>
            <Play className="h-4 w-4 mr-2 flex-shrink-0" />{t('chapterDetail.generateVideo')}
          </button>
        </div>
      </div>

      {/* Status Bar */}
      <div className={`card ${statusInfo.bg}`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <StatusIcon className={`h-6 w-6 ${statusInfo.color} ${shouldSpin ? 'animate-spin' : ''}`} />
            <div>
              <p className={`font-medium ${statusInfo.color}`}>{statusInfo.text}</p>
              {state.chapter.progress > 0 && <p className="text-sm text-gray-500">{t('chapterDetail.progress', { progress: state.chapter.progress })}</p>}
            </div>
          </div>
          {state.chapter.status === 'completed' && state.chapter.finalVideo && (
            <a href={state.chapter.finalVideo} target="_blank" rel="noopener noreferrer" className="btn-primary">
              <Film className="h-4 w-4 mr-2" />{t('chapterDetail.viewVideo')}
            </a>
          )}
        </div>
      </div>

      {/* Parse Results */}
      {state.parseResult && <ParseResultCard result={state.parseResult} type="characters" onViewClick={() => window.location.href = `/characters?novel=${state.id}&highlight=new`} />}
      {state.parseScenesResult && <ParseResultCard result={state.parseScenesResult} type="scenes" onViewClick={() => window.location.href = `/scenes?novel=${state.id}&highlight=new`} />}
      {state.parsePropsResult && <ParseResultCard result={state.parsePropsResult} type="props" onViewClick={() => window.location.href = `/props?novel=${state.id}&highlight=new`} />}

      {/* Content Editor */}
      <div className="card">
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">{t('chapterDetail.chapterTitleLabel')}</label>
            <input type="text" value={state.title} onChange={(e) => state.setTitle(e.target.value)} className="input-field" placeholder={t('chapterDetail.chapterTitlePlaceholder')} />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">{t('chapterDetail.chapterContentLabel')}</label>
            <textarea value={state.content} onChange={(e) => state.setContent(e.target.value)} rows={20} className="input-field font-mono text-sm" placeholder={t('chapterDetail.chapterContentPlaceholder')} />
            <p className="text-xs text-gray-500 mt-2">{t('chapterDetail.wordCount', { count: state.content.length })}</p>
          </div>
        </div>
      </div>

      <GeneratedAssets chapter={state.chapter} onImageClick={state.openImagePreview} />
      <ImagePreviewModal previewImage={state.previewImage} onClose={state.closeImagePreview} onNavigate={state.navigatePreview} />
    </div>
  );
}
