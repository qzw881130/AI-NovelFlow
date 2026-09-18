import { Sparkles, Loader2 } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import type { ChapterRange, ConfirmDialogState } from '../types';

interface ParseConfirmDialogProps {
  isOpen: boolean;
  confirmDialog: ConfirmDialogState;
  chapterRange: ChapterRange;
  parsingNovelId: string | null;
  parsingScenesNovelId: string | null;
  parsingPropsNovelId: string | null;
  onClose: () => void;
  onConfirmCharacters: () => void;
  onConfirmScenes: () => void;
  onConfirmProps: () => void;
  onChapterRangeChange: (range: ChapterRange) => void;
}

const TYPE_CONFIG = {
  characters: { bgColor: 'bg-purple-100', textColor: 'text-purple-600' },
  scenes: { bgColor: 'bg-teal-100', textColor: 'text-teal-600' },
  props: { bgColor: 'bg-amber-100', textColor: 'text-amber-600' },
};

export function ParseConfirmDialog({
  isOpen,
  confirmDialog,
  chapterRange,
  parsingNovelId,
  parsingScenesNovelId,
  parsingPropsNovelId,
  onClose,
  onConfirmCharacters,
  onConfirmScenes,
  onConfirmProps,
  onChapterRangeChange,
}: ParseConfirmDialogProps) {
  const { t } = useTranslation();

  if (!isOpen) return null;

  const type = confirmDialog.type;
  const config = TYPE_CONFIG[type];
  const isCharacters = type === 'characters';
  const isScenes = type === 'scenes';
  const isProps = type === 'props';

  const isParsing = isCharacters
    ? parsingNovelId === confirmDialog.novelId
    : isScenes
    ? parsingScenesNovelId === confirmDialog.novelId
    : parsingPropsNovelId === confirmDialog.novelId;

  const getTitle = () => {
    if (isCharacters) return t('novels.aiParseCharactersTitle');
    if (isScenes) return t('novels.aiParseScenesTitle');
    return t('novels.aiParsePropsTitle');
  };

  const getMessage = () => {
    if (isCharacters) return t('novels.parseConfirmMessage');
    if (isScenes) return t('novels.parseScenesConfirmMessage');
    return t('novels.parsePropsConfirmMessage');
  };

  const onConfirm = () => {
    if (isCharacters) onConfirmCharacters();
    else if (isScenes) onConfirmScenes();
    else onConfirmProps();
  };

  const getButtonColor = () => {
    if (isCharacters) return 'bg-purple-600 hover:bg-purple-700';
    if (isScenes) return 'bg-teal-600 hover:bg-teal-700';
    return 'bg-amber-600 hover:bg-amber-700';
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg p-6 w-full max-w-md shadow-xl">
        <div className="flex items-center gap-3 mb-4">
          <div className={`p-2 rounded-full ${config.bgColor}`}>
            <Sparkles className={`h-6 w-6 ${config.textColor}`} />
          </div>
          <h3 className="text-lg font-semibold text-gray-900">
            {getTitle()}
          </h3>
        </div>

        <p className="text-gray-600 mb-4">
          {getMessage()}
        </p>

        <div className="mb-4 space-y-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">{t('novels.chapterRange')}</label>
            <div className="flex gap-2">
              <div className="flex-1">
                <input
                  type="number"
                  min="1"
                  placeholder={t('novels.startChapter')}
                  value={chapterRange.startChapter || ''}
                  onChange={(e) => onChapterRangeChange({
                    ...chapterRange,
                    startChapter: e.target.value ? parseInt(e.target.value) : null
                  })}
                  className="input-field w-full text-sm"
                />
              </div>
              <div className="flex items-center text-gray-400">-</div>
              <div className="flex-1">
                <input
                  type="number"
                  min="1"
                  placeholder={t('novels.endChapter')}
                  value={chapterRange.endChapter || ''}
                  onChange={(e) => onChapterRangeChange({
                    ...chapterRange,
                    endChapter: e.target.value ? parseInt(e.target.value) : null
                  })}
                  className="input-field w-full text-sm"
                />
              </div>
            </div>
            <p className="text-xs text-gray-500 mt-1">{t('novels.parseEntireNovel')}</p>
          </div>

          <p className="rounded bg-blue-50 p-3 text-sm text-blue-800">按章回保存独立候选和来源证据，等待身份归并。此次解析不会覆盖、补写或删除全局角色/场景/道具。</p>
        </div>

        <p className="text-sm text-gray-500 mb-6">{t('novels.parseConfirmHint')}</p>

        <div className="flex justify-end gap-3">
          <button
            onClick={onClose}
            className="px-4 py-2 text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
          >
            {t('common.cancel')}
          </button>
          <button
            onClick={onConfirm}
            className={`px-4 py-2 text-white rounded-lg transition-colors flex items-center gap-2 ${getButtonColor()}`}
          >
            {isParsing ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                {t('novels.parseInProgress')}
              </>
            ) : (
              <>
                <Sparkles className="h-4 w-4" />
                {t('common.confirm')}
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
