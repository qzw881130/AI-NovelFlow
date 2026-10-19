import { useState, useEffect } from 'react';
import { ChevronLeft, ChevronRight, X, Download } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';

interface ImagePreviewModalProps {
  imageUrl: string;
  images?: Array<{ label?: string; url: string }>;
  currentIndex?: number;
  onNavigate?: (direction: 'prev' | 'next') => void;
  onClose: () => void;
}

export function ImagePreviewModal({ imageUrl, images = [], currentIndex = 0, onNavigate, onClose }: ImagePreviewModalProps) {
  const { t } = useTranslation();
  const [info, setInfo] = useState<{ width: number; height: number; size?: string } | null>(null);
  const canNavigate = images.length > 1 && !!onNavigate;
  const currentImage = images[currentIndex];

  useEffect(() => {
    const img = new Image();
    img.onload = () => {
      setInfo(prev => ({ ...prev, width: img.naturalWidth, height: img.naturalHeight }));
    };
    img.src = imageUrl;

    fetch(imageUrl, { method: 'HEAD' })
      .then(res => {
        const contentLength = res.headers.get('content-length');
        if (contentLength) {
          const size = parseInt(contentLength);
          const sizeStr = size > 1024 * 1024
            ? `${(size / 1024 / 1024).toFixed(2)} MB`
            : size > 1024 ? `${(size / 1024).toFixed(1)} KB` : `${size} B`;
          setInfo(prev => ({ ...prev, size: sizeStr } as any));
        }
      })
      .catch(() => {});
  }, [imageUrl]);

  useEffect(() => {
    if (!canNavigate) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'ArrowLeft') {
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();
        onNavigate?.('prev');
      } else if (event.key === 'ArrowRight') {
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();
        onNavigate?.('next');
      }
    };

    window.addEventListener('keydown', handleKeyDown, true);
    return () => window.removeEventListener('keydown', handleKeyDown, true);
  }, [canNavigate, onNavigate]);

  const handleDownload = async () => {
    try {
      const response = await fetch(imageUrl);
      const blob = await response.blob();
      const downloadUrl = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = downloadUrl;
      link.download = imageUrl.split('/').pop() || 'image.png';
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
      {canNavigate && (
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onNavigate?.('prev'); }}
          className="fixed left-6 top-1/2 -translate-y-1/2 p-3 text-white bg-black/30 hover:bg-white/15 rounded-full transition-all z-10"
          title="上一个参考图 (←)"
          aria-label="上一个参考图"
        >
          <ChevronLeft className="h-10 w-10" />
        </button>
      )}
      <div className="relative max-w-[90vw] max-h-[90vh] flex flex-col items-center">
        {currentImage?.label && (
          <div className="mb-3 rounded bg-black/45 px-3 py-1 text-sm text-white">
            {currentImage.label} · {currentIndex + 1}/{images.length}
          </div>
        )}
        <img
          src={imageUrl}
          alt={t('tasks.preview')}
          className="max-w-full max-h-[80vh] object-contain rounded-lg"
          onClick={(e) => e.stopPropagation()}
        />
        {info && (
          <div className="mt-3 text-white text-sm opacity-80 flex items-center gap-4">
            <span>{t('tasks.dimensions')}: {info.width} × {info.height} px</span>
            {info.size && <span>{t('tasks.size')}: {info.size}</span>}
          </div>
        )}
        {/* 关闭按钮 */}
        <button onClick={onClose} className="absolute -top-10 right-0 p-2 text-white hover:text-gray-300 transition-colors">
          <X className="h-6 w-6" />
        </button>
        {/* 下载按钮 */}
        <button
          onClick={(e) => { e.stopPropagation(); handleDownload(); }}
          className="absolute -top-10 right-10 p-2 text-white hover:text-blue-400 transition-colors"
          title={t('common.download') || '下载'}
        >
          <Download className="h-6 w-6" />
        </button>
      </div>
      {canNavigate && (
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onNavigate?.('next'); }}
          className="fixed right-6 top-1/2 -translate-y-1/2 p-3 text-white bg-black/30 hover:bg-white/15 rounded-full transition-all z-10"
          title="下一个参考图 (→)"
          aria-label="下一个参考图"
        >
          <ChevronRight className="h-10 w-10" />
        </button>
      )}
    </div>
  );
}

interface VideoPreviewModalProps {
  videoUrl: string;
  onClose: () => void;
}

interface VideoMetadata {
  duration: number | null;
  width: number | null;
  height: number | null;
  sizeBytes: number | null;
}

const emptyVideoMetadata = (): VideoMetadata => ({ duration: null, width: null, height: null, sizeBytes: null });

const formatVideoDuration = (seconds: number | null) => {
  if (seconds === null || !Number.isFinite(seconds) || seconds < 0) return '-';
  const totalSeconds = Math.round(seconds);
  return `${Math.floor(totalSeconds / 60)}:${String(totalSeconds % 60).padStart(2, '0')}`;
};

const formatVideoSize = (bytes: number | null) => {
  if (bytes === null || !Number.isFinite(bytes) || bytes <= 0) return '-';
  return bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
};

const formatVideoBitrate = (bytes: number | null, duration: number | null) => {
  if (bytes === null || duration === null || !Number.isFinite(bytes) || !Number.isFinite(duration) || bytes <= 0 || duration <= 0) return '-';
  const kbps = (bytes * 8) / duration / 1000;
  return kbps >= 1000 ? `${(kbps / 1000).toFixed(2)} Mbps` : `${Math.round(kbps)} kbps`;
};

export function VideoPreviewModal({ videoUrl, onClose }: VideoPreviewModalProps) {
  const { t } = useTranslation();
  const [metadata, setMetadata] = useState<VideoMetadata>(emptyVideoMetadata);

  useEffect(() => {
    setMetadata(emptyVideoMetadata());
    const controller = new AbortController();
    fetch(videoUrl, { method: 'HEAD', signal: controller.signal })
      .then(response => {
        if (controller.signal.aborted || !response.ok) return;
        const contentLength = Number(response.headers.get('content-length'));
        if (Number.isFinite(contentLength) && contentLength > 0) {
          setMetadata(current => ({ ...current, sizeBytes: contentLength }));
        }
      })
      .catch(() => {
        // Remote videos may not expose Content-Length or permit HEAD requests.
      });
    return () => controller.abort();
  }, [videoUrl]);

  const handleLoadedMetadata = (event: React.SyntheticEvent<HTMLVideoElement>) => {
    const video = event.currentTarget;
    setMetadata(current => ({
      ...current,
      duration: Number.isFinite(video.duration) ? video.duration : null,
      width: video.videoWidth || null,
      height: video.videoHeight || null,
    }));
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-90 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="relative flex w-fit max-w-[90vw] max-h-[90vh] flex-col overflow-visible">
        <video key={videoUrl} src={videoUrl} controls autoPlay className="max-w-full max-h-[calc(90vh-4rem)] rounded-t-lg" onLoadedMetadata={handleLoadedMetadata} onDurationChange={handleLoadedMetadata} onClick={(e) => e.stopPropagation()} />
        <div className="flex w-full flex-wrap items-center gap-x-5 gap-y-1 rounded-b-lg bg-white px-4 py-2 text-sm text-gray-700" onClick={(e) => e.stopPropagation()}>
          <span>{t('tasks.videoDuration')}：{formatVideoDuration(metadata.duration)}</span>
          <span>{t('tasks.videoResolution')}：{metadata.width && metadata.height ? `${metadata.width} x ${metadata.height}` : '-'}</span>
          <span>{t('tasks.size')}：{formatVideoSize(metadata.sizeBytes)}</span>
          <span>{t('tasks.videoBitrate')}：{formatVideoBitrate(metadata.sizeBytes, metadata.duration)}</span>
        </div>
        <button onClick={onClose} className="absolute -top-10 right-0 p-2 text-white hover:text-gray-300 transition-colors">
          <X className="h-6 w-6" />
        </button>
      </div>
    </div>
  );
}
