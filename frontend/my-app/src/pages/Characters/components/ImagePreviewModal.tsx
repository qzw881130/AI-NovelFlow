/**
 * 图片预览弹窗组件
 */
import { useEffect, useState } from 'react';
import { X, ChevronLeft, ChevronRight, Download } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import type { Character } from '../../../types';

interface ImagePreviewModalProps {
  isOpen: boolean;
  url: string | null;
  name: string;
  characterId: string | null;
  charactersWithImages: Character[];
  onClose: () => void;
  onNavigate: (direction: 'prev' | 'next') => void;
}

export function ImagePreviewModal({
  isOpen,
  url,
  name,
  characterId,
  charactersWithImages,
  onClose,
  onNavigate,
}: ImagePreviewModalProps) {
  const { t } = useTranslation();
  const [imageSize, setImageSize] = useState<{ width: number; height: number } | null>(null);

  useEffect(() => {
    setImageSize(null);
  }, [url]);

  const downloadName = `${name || 'character'}.png`;

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!isOpen) return;
      
      if (e.key === 'ArrowLeft') {
        e.preventDefault();
        onNavigate('prev');
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        onNavigate('next');
      } else if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, characterId, onNavigate, onClose]);

  if (!isOpen || !url) return null;

  return (
    <div 
      className="fixed inset-0 bg-black bg-opacity-90 flex items-center justify-center z-50 p-4"
      onClick={onClose}
    >
      <div className="relative max-w-[90vw] max-h-[90vh] flex flex-col items-center">
        <img 
          src={url} 
          alt={name}
          className="max-w-full max-h-[80vh] object-contain rounded-lg"
          onLoad={(event) => {
            setImageSize({
              width: event.currentTarget.naturalWidth,
              height: event.currentTarget.naturalHeight,
            });
          }}
          onClick={(e) => e.stopPropagation()}
        />
        
        {/* 导航按钮 */}
        {charactersWithImages.length > 1 && (
          <>
            <button
              onClick={(e) => { e.stopPropagation(); onNavigate('prev'); }}
              className="absolute left-4 top-1/2 -translate-y-1/2 p-2 bg-white/20 hover:bg-white/30 rounded-full text-white transition-colors"
            >
              <ChevronLeft className="h-6 w-6" />
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); onNavigate('next'); }}
              className="absolute right-4 top-1/2 -translate-y-1/2 p-2 bg-white/20 hover:bg-white/30 rounded-full text-white transition-colors"
            >
              <ChevronRight className="h-6 w-6" />
            </button>
          </>
        )}
        
        <div className="mt-3 flex flex-col items-center gap-2 text-white">
          <div className="text-lg font-medium">{name}</div>
          <div className="flex items-center gap-3 text-sm text-white/70">
            {imageSize && (
              <span>{imageSize.width} x {imageSize.height} px</span>
            )}
            <a
              href={url}
              download={downloadName}
              onClick={(e) => e.stopPropagation()}
              className="inline-flex items-center gap-1 rounded-full bg-white/15 px-3 py-1 text-white transition-colors hover:bg-white/25"
            >
              <Download className="h-4 w-4" />
              {t('common.download')}
            </a>
          </div>
        </div>

        <button
          onClick={onClose}
          className="absolute -top-10 right-0 p-2 text-white hover:text-gray-300 transition-colors"
        >
          <X className="h-6 w-6" />
        </button>
        
        <div className="mt-4 text-white text-sm opacity-60">
          {t('characters.keyboardNavigate')}
        </div>
      </div>
    </div>
  );
}
