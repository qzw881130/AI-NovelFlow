import { ChevronLeft, ChevronRight, X, Download } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import type { PreviewImageState } from '../types';

interface ImagePreviewModalProps {
  previewImage: PreviewImageState;
  onClose: () => void;
  onNavigate: (direction: 'prev' | 'next') => void;
}

export function ImagePreviewModal({ previewImage, onClose, onNavigate }: ImagePreviewModalProps) {
  const { t } = useTranslation();
  if (!previewImage.isOpen || !previewImage.url) return null;

  const hasMultipleImages = previewImage.images && previewImage.images.length > 1;

  // 下载图片
  const handleDownload = async () => {
    if (!previewImage.url) return;
    try {
      const response = await fetch(previewImage.url);
      const blob = await response.blob();
      const downloadUrl = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = downloadUrl;
      link.download = previewImage.url.split('/').pop() || 'image.png';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(downloadUrl);
    } catch (error) {
      console.error('Download failed:', error);
    }
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-90 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="relative max-w-5xl max-h-[90vh] w-full flex items-center">
        {/* 左导航按钮 */}
        {hasMultipleImages && (
          <button onClick={(e) => { e.stopPropagation(); onNavigate('prev'); }}
            className="absolute -left-16 top-1/2 -translate-y-1/2 p-3 text-white hover:text-gray-300 hover:bg-white/10 rounded-full transition-all">
            <ChevronLeft className="h-10 w-10" />
          </button>
        )}
        <div className="flex-1">
          {/* 关闭按钮 */}
          <button onClick={onClose} className="absolute -top-12 right-0 p-2 text-white hover:text-gray-300 transition-colors">
            <X className="h-8 w-8" />
          </button>
          {/* 下载按钮 */}
          <button
            onClick={(e) => { e.stopPropagation(); handleDownload(); }}
            className="absolute -top-12 right-12 p-2 text-white hover:text-blue-400 transition-colors"
            title={t('common.download') || '下载'}
          >
            <Download className="h-6 w-6" />
          </button>
          <img src={previewImage.url} alt={t('chapterDetail.imagePreview')}
            className="w-full h-full object-contain max-h-[80vh] rounded-lg" onClick={(e) => e.stopPropagation()} />
        </div>
        {/* 右导航按钮 */}
        {hasMultipleImages && (
          <button onClick={(e) => { e.stopPropagation(); onNavigate('next'); }}
            className="absolute -right-16 top-1/2 -translate-y-1/2 p-3 text-white hover:text-gray-300 hover:bg-white/10 rounded-full transition-all">
            <ChevronRight className="h-10 w-10" />
          </button>
        )}
      </div>
    </div>
  );
}
