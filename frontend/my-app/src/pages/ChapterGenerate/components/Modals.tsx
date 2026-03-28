import { X } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';

interface FullTextModalProps {
  isOpen: boolean;
  onClose: () => void;
  chapterTitle?: string;
  chapterContent?: string;
}

export function FullTextModal({ isOpen, onClose, chapterTitle, chapterContent }: FullTextModalProps) {
  const { t } = useTranslation();

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg w-full max-w-4xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between p-6 border-b">
          <h3 className="text-lg font-semibold text-gray-900">{t('chapterGenerate.originalContent')}</h3>
          <button
            onClick={onClose}
            className="p-1 text-gray-400 hover:text-gray-600"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="p-6 overflow-y-auto flex-1">
          <h2 className="text-xl font-bold text-gray-900 mb-4">
            {chapterTitle || t('chapterGenerate.unnamedChapter')}
          </h2>
          <div className="prose prose-gray max-w-none">
            <p className="text-gray-700 leading-loose whitespace-pre-wrap text-base">
              {chapterContent || t('chapterGenerate.noContent')}
            </p>
          </div>
        </div>
        <div className="p-6 border-t bg-gray-50 flex justify-end">
          <button
            onClick={onClose}
            className="btn-secondary"
          >
            {t('common.close')}
          </button>
        </div>
      </div>
    </div>
  );
}

interface MergedImageModalProps {
  isOpen: boolean;
  onClose: () => void;
  mergedImage: string | null;
  currentShot: number;
}

export function MergedImageModal({ isOpen, onClose, mergedImage, currentShot }: MergedImageModalProps) {
  const { t } = useTranslation();

  if (!isOpen || !mergedImage) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-80 flex items-center justify-center z-50 p-4">
      <div className="relative max-w-4xl max-h-[90vh] flex flex-col">
        <button
          onClick={onClose}
          className="absolute -top-10 right-0 p-2 text-white hover:text-gray-300"
        >
          <X className="h-6 w-6" />
        </button>
        <img 
          src={mergedImage} 
          alt={t('chapterGenerate.mergedCharacterImage')} 
          className="max-w-full max-h-[80vh] object-contain rounded-lg"
        />
        <div className="mt-4 text-center">
          <button
            onClick={() => {
              const link = document.createElement('a');
              link.download = `${t('chapterGenerate.characterImage')}_${t('chapterGenerate.shot')}${currentShot}.png`;
              link.href = mergedImage;
              link.click();
            }}
            className="btn-primary text-sm"
          >
            <svg className="h-4 w-4 mr-2 inline" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
            </svg>
            {t('chapterGenerate.downloadImage')}
          </button>
        </div>
      </div>
    </div>
  );
}

interface ImagePreviewModalProps {
  isOpen: boolean;
  onClose: () => void;
  previewImageUrl: string | null;
  previewImageIndex: number;
  currentShot: number;
  totalImages: number;
  onNavigate: (direction: 'prev' | 'next') => void;
  parsedDataShots: any[];
  shotImages: Record<number, string>;
}

export function ImagePreviewModal({
  isOpen,
  onClose,
  previewImageUrl,
  previewImageIndex,
  currentShot,
  totalImages,
  onNavigate,
  parsedDataShots,
  shotImages
}: ImagePreviewModalProps) {
  const { t } = useTranslation();

  if (!isOpen || !previewImageUrl) return null;

  // 计算有图片的分镜数量
  const imagesWithShots = parsedDataShots?.filter((_shot: any, idx: number) => shotImages[idx + 1] || parsedDataShots?.[idx]?.image_url).length || 0;

  return (
    <div
      className="fixed inset-0 bg-black bg-opacity-90 flex items-center justify-center z-50 p-4"
      onClick={onClose}
    >
      <div className="relative max-w-5xl max-h-[90vh] w-full flex items-center" onClick={e => e.stopPropagation()}>
        {/* 左导航按钮 */}
        {imagesWithShots > 1 && (
          <button
            onClick={(e) => { e.stopPropagation(); onNavigate('prev'); }}
            className="absolute -left-16 top-1/2 -translate-y-1/2 p-3 text-white hover:text-gray-300 hover:bg-white/10 rounded-full transition-all z-10"
          >
            <svg className="h-10 w-10" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
        )}

        <div className="flex-1 flex flex-col">
          {/* 关闭按钮 */}
          <button
            onClick={onClose}
            className="absolute -top-10 right-0 p-2 text-white hover:text-gray-300 z-10"
          >
            <X className="h-6 w-6" />
          </button>

          {/* 图片 */}
          <img
            src={previewImageUrl}
            alt={t('chapterGenerate.shotPreview')}
            className="max-w-full max-h-[75vh] object-contain rounded-lg mx-auto"
          />

          {/* 下载按钮 */}
          <div className="mt-4 flex justify-center">
            <button
              onClick={() => {
                const link = document.createElement('a');
                link.download = `${t('chapterGenerate.shot')}_${currentShot}.png`;
                link.href = previewImageUrl;
                link.click();
              }}
              className="btn-primary text-sm"
            >
              <svg className="h-4 w-4 mr-2 inline" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              {t('chapterGenerate.downloadImage')}
            </button>
          </div>
        </div>

        {/* 右导航按钮 */}
        {imagesWithShots > 1 && (
          <button
            onClick={(e) => { e.stopPropagation(); onNavigate('next'); }}
            className="absolute -right-16 top-1/2 -translate-y-1/2 p-3 text-white hover:text-gray-300 hover:bg-white/10 rounded-full transition-all z-10"
          >
            <svg className="h-10 w-10" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </button>
        )}
      </div>
    </div>
  );
}

interface SplitConfirmDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
}

export function SplitConfirmDialog({ isOpen, onClose, onConfirm }: SplitConfirmDialogProps) {
  const { t } = useTranslation();

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-gray-800 rounded-xl shadow-2xl border border-gray-700 w-full max-w-md p-6">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-full bg-amber-500/20 flex items-center justify-center">
            <svg className="w-5 h-5 text-amber-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          </div>
          <h3 className="text-lg font-semibold text-white">
            {t('chapterGenerate.confirmResplit')}
          </h3>
        </div>
        
        <p className="text-gray-300 mb-4 leading-relaxed">
          {t('chapterGenerate.resplitWarning')}
        </p>
        
        <div className="bg-gray-900/50 rounded-lg p-4 mb-6 border border-gray-700">
          <ul className="space-y-2 text-sm text-gray-400">
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 bg-red-500 rounded-full"></span>
              {t('chapterGenerate.shotJsonData')}
            </li>
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 bg-red-500 rounded-full"></span>
              {t('chapterGenerate.generatedShotImages')}
            </li>
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 bg-red-500 rounded-full"></span>
              {t('chapterGenerate.generatedShotVideos')}
            </li>
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 bg-red-500 rounded-full"></span>
              {t('chapterGenerate.generatedTransitionVideos')}
            </li>
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 bg-red-500 rounded-full"></span>
              {t('chapterGenerate.mergedCharacterImage')}
            </li>
          </ul>
        </div>
        
        <div className="flex justify-end gap-3">
          <button
            onClick={onClose}
            className="px-4 py-2 text-gray-300 hover:text-white hover:bg-gray-700 rounded-lg transition-colors"
          >
            {t('common.cancel')}
          </button>
          <button
            onClick={onConfirm}
            className="px-4 py-2 bg-amber-600 hover:bg-amber-500 text-white rounded-lg transition-colors flex items-center gap-2"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            {t('chapterGenerate.confirmResplitBtn')}
          </button>
        </div>
      </div>
    </div>
  );
}
