/**
 * 统一的图片预览弹窗组件
 *
 * 支持：
 * - 单图预览模式（无导航）
 * - 多图导航模式（可选显示导航按钮）
 * - 图片下载功能
 * - 点击背景或按 ESC 关闭
 */

import { useEffect, useCallback } from 'react';
import { X, Download, ChevronLeft, ChevronRight } from 'lucide-react';

interface ImagePreviewModalProps {
  /** 是否显示 */
  isOpen: boolean;
  /** 图片 URL */
  url: string | null;
  /** 图片名称/标题 */
  name?: string;
  /** 是否显示下载按钮 */
  showDownload?: boolean;
  /** 是否显示导航按钮（多图模式） */
  showNavigation?: boolean;
  /** 总数（多图模式时用于判断是否显示导航） */
  totalCount?: number;
  /** 关闭回调 */
  onClose: () => void;
  /** 上一张回调 */
  onPrev?: () => void;
  /** 下一张回调 */
  onNext?: () => void;
}

export function ImagePreviewModal({
  isOpen,
  url,
  name,
  showDownload = false,
  showNavigation = false,
  totalCount,
  onClose,
  onPrev,
  onNext,
}: ImagePreviewModalProps) {
  // 键盘事件处理
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (!isOpen) return;

    if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
    } else if (showNavigation && e.key === 'ArrowLeft' && onPrev) {
      e.preventDefault();
      onPrev();
    } else if (showNavigation && e.key === 'ArrowRight' && onNext) {
      e.preventDefault();
      onNext();
    }
  }, [isOpen, onClose, showNavigation, onPrev, onNext]);

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  // 下载图片
  const handleDownload = async () => {
    if (!url) return;

    try {
      const response = await fetch(url);
      const blob = await response.blob();
      const downloadUrl = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = downloadUrl;
      // 从 URL 中提取文件名，或使用 name
      const filename = url.split('/').pop() || name || 'image.png';
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(downloadUrl);
    } catch (error) {
      console.error('Download failed:', error);
    }
  };

  if (!isOpen || !url) return null;

  // 是否显示导航按钮
  const shouldShowNavButtons = showNavigation && totalCount && totalCount > 1;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/90"
      onClick={onClose}
    >
      <div className="relative max-w-[90vw] max-h-[90vh] flex flex-col items-center">
        {/* 图片 */}
        <img
          src={url}
          alt={name || 'Preview'}
          className="max-w-full max-h-[80vh] object-contain rounded-lg"
          onClick={(e) => e.stopPropagation()}
        />

        {/* 导航按钮 */}
        {shouldShowNavButtons && (
          <>
            <button
              onClick={(e) => { e.stopPropagation(); onPrev?.(); }}
              className="absolute left-4 top-1/2 -translate-y-1/2 p-2 bg-white/20 hover:bg-white/30 rounded-full text-white transition-colors"
            >
              <ChevronLeft className="h-6 w-6" />
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); onNext?.(); }}
              className="absolute right-4 top-1/2 -translate-y-1/2 p-2 bg-white/20 hover:bg-white/30 rounded-full text-white transition-colors"
            >
              <ChevronRight className="h-6 w-6" />
            </button>
          </>
        )}

        {/* 标题栏 */}
        {name && (
          <div className="mt-3 text-white text-lg font-medium">
            {name}
          </div>
        )}

        {/* 关闭按钮 */}
        <button
          onClick={onClose}
          className="absolute -top-12 right-0 p-2 text-white hover:text-gray-300 transition-colors"
        >
          <X className="h-6 w-6" />
        </button>

        {/* 下载按钮 */}
        {showDownload && (
          <button
            onClick={(e) => { e.stopPropagation(); handleDownload(); }}
            className="absolute -top-12 right-10 p-2 text-white hover:text-blue-400 transition-colors"
            title="下载图片"
          >
            <Download className="h-6 w-6" />
          </button>
        )}
      </div>
    </div>
  );
}

export default ImagePreviewModal;