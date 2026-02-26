import { Link } from 'react-router-dom';
import { BookOpen, Trash2, Edit2, Users, MapPin, Play, Sparkles, Loader2 } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import type { Novel, PromptTemplate } from '../../../types';

interface NovelCardProps {
  novel: Novel;
  templatesByType: Record<string, PromptTemplate[]>;
  parsingNovelId: string | null;
  parsingScenesNovelId: string | null;
  onDelete: (id: string) => void;
  onEdit: (novel: Novel) => void;
  onParseConfirm: (novelId: string, type: 'characters' | 'scenes') => void;
  getTemplateDisplayName: (template: PromptTemplate | undefined) => string;
}

// 辅助函数：获取模板
const getTemplate = (templatesByType: Record<string, PromptTemplate[]>, type: string, id: string | undefined): PromptTemplate | undefined => {
  if (!id) return undefined;
  return (templatesByType[type] || []).find(t => t.id === id);
};

export function NovelCard({
  novel,
  templatesByType,
  parsingNovelId,
  parsingScenesNovelId,
  onDelete,
  onEdit,
  onParseConfirm,
  getTemplateDisplayName,
}: NovelCardProps) {
  const { t } = useTranslation();

  // 获取各类型模板
  const styleTemplate = getTemplate(templatesByType, 'style', novel.stylePromptTemplateId);
  const characterTemplate = getTemplate(templatesByType, 'character', novel.promptTemplateId);
  const sceneTemplate = getTemplate(templatesByType, 'scene', novel.scenePromptTemplateId);
  const chapterSplitTemplate = getTemplate(templatesByType, 'chapter_split', novel.chapterSplitPromptTemplateId);

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden hover:shadow-md transition-shadow group">
      <div className="aspect-video bg-gray-100 relative">
        {novel.cover ? (
          <img src={novel.cover} alt={novel.title} className="w-full h-full object-cover" />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center">
            <BookOpen className="h-16 w-16 text-gray-300" />
          </div>
        )}
        <div className="absolute top-2 left-2 px-2 py-1 bg-black/60 text-white text-xs rounded-lg flex items-center gap-1">
          <BookOpen className="h-3 w-3" />
          <span>{novel.chapterCount} {t('novelDetail.chapters')}</span>
        </div>
        <button
          onClick={() => onDelete(novel.id)}
          className="absolute top-2 right-2 p-2 bg-white/90 rounded-lg text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors opacity-0 group-hover:opacity-100"
          title={t('common.delete')}
        >
          <Trash2 className="h-4 w-4" />
        </button>
        <button
          onClick={() => onEdit(novel)}
          className="absolute bottom-2 right-2 p-2 bg-white/90 rounded-lg text-gray-400 hover:text-blue-600 hover:bg-blue-50 transition-colors opacity-0 group-hover:opacity-100"
          title={t('common.edit')}
        >
          <Edit2 className="h-4 w-4" />
        </button>
      </div>
      <div className="p-4">
        <h3 className="text-lg font-semibold text-gray-900 truncate">{novel.title}</h3>
        <p className="text-sm text-gray-500 mt-1">{novel.author}</p>
        <p className="text-sm text-gray-600 mt-2 line-clamp-2 h-10">
          {novel.description || t('novels.noDescription')}
        </p>
        <div className="mt-3 flex flex-wrap gap-1.5 h-16 content-start">
          <span className="inline-flex items-center gap-1 px-2 py-1 bg-pink-50 text-pink-600 text-xs rounded whitespace-nowrap">
            <span className="font-medium">{t('novels.stylePrompt')}</span>
            <span className="truncate max-w-[80px]">{getTemplateDisplayName(styleTemplate)}</span>
          </span>
          <span className="inline-flex items-center gap-1 px-2 py-1 bg-blue-50 text-blue-600 text-xs rounded whitespace-nowrap">
            <span className="font-medium">{t('novels.characterPrompt')}</span>
            <span className="truncate max-w-[80px]">{getTemplateDisplayName(characterTemplate)}</span>
          </span>
          <span className="inline-flex items-center gap-1 px-2 py-1 bg-orange-50 text-orange-600 text-xs rounded whitespace-nowrap">
            <span className="font-medium">{t('novels.scenePrompt')}</span>
            <span className="truncate max-w-[80px]">{getTemplateDisplayName(sceneTemplate)}</span>
          </span>
          <span className="inline-flex items-center gap-1 px-2 py-1 bg-purple-50 text-purple-600 text-xs rounded whitespace-nowrap">
            <span className="font-medium">{t('novels.splitPrompt')}</span>
            <span className="truncate max-w-[80px]">{getTemplateDisplayName(chapterSplitTemplate)}</span>
          </span>
          <span className="inline-flex items-center gap-1 px-2 py-1 bg-green-50 text-green-600 text-xs rounded whitespace-nowrap">
            <span className="font-medium">{t('novels.aspectRatioShort')}</span>
            {novel.aspectRatio || '16:9'}
          </span>
        </div>
        <div className="flex flex-col sm:flex-row sm:items-center justify-end mt-4 pt-4 border-t border-gray-100 gap-3">
          <div className="flex items-center gap-2 flex-wrap">
            <button
              onClick={() => onParseConfirm(novel.id, 'characters')}
              disabled={parsingNovelId === novel.id}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-purple-100 text-purple-600 hover:bg-purple-200 transition-colors disabled:opacity-50 text-sm"
              title={t('novels.aiParseCharacters')}
            >
              {parsingNovelId === novel.id ? (
                <Loader2 className="h-4 w-4 animate-spin flex-shrink-0" />
              ) : (
                <Sparkles className="h-4 w-4 flex-shrink-0" />
              )}
              <span>{t('novels.aiParseCharacters')}</span>
            </button>
            <button
              onClick={() => onParseConfirm(novel.id, 'scenes')}
              disabled={parsingScenesNovelId === novel.id}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-teal-100 text-teal-600 hover:bg-teal-200 transition-colors disabled:opacity-50 text-sm"
              title={t('novels.aiParseScenes')}
            >
              {parsingScenesNovelId === novel.id ? (
                <Loader2 className="h-4 w-4 animate-spin flex-shrink-0" />
              ) : (
                <Sparkles className="h-4 w-4 flex-shrink-0" />
              )}
              <span>{t('novels.aiParseScenes')}</span>
            </button>
            <Link
              to={`/characters?novel=${novel.id}`}
              className="flex items-center justify-center w-9 h-9 rounded-lg text-gray-400 hover:text-primary-600 hover:bg-gray-100 transition-colors flex-shrink-0"
              title={t('novels.viewCharacters')}
            >
              <Users className="h-4 w-4" />
            </Link>
            <Link
              to={`/scenes?novel=${novel.id}`}
              className="flex items-center justify-center w-9 h-9 rounded-lg text-gray-400 hover:text-primary-600 hover:bg-gray-100 transition-colors flex-shrink-0"
              title={t('novels.viewScenes')}
            >
              <MapPin className="h-4 w-4" />
            </Link>
            <Link
              to={`/novels/${novel.id}`}
              className="btn-primary text-sm py-2 px-3 flex-shrink-0"
            >
              <Play className="h-3 w-3 mr-1 flex-shrink-0" />
              {t('novels.manageChapters')}
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
