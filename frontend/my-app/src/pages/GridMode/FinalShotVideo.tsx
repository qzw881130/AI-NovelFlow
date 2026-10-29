import { useEffect, useState } from 'react';

type VideoMetadata = {
  duration: number | null;
  width: number | null;
  height: number | null;
  sizeBytes: number | null;
};

const formatDuration = (seconds: number | null) => {
  if (!seconds || !Number.isFinite(seconds)) return '-';
  const minutes = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60).toString().padStart(2, '0');
  return `${minutes}:${secs}`;
};

const formatFileSize = (bytes: number | null) => {
  if (!bytes || !Number.isFinite(bytes)) return '-';
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
};

const formatBitrate = (bytes: number | null, duration: number | null) => {
  if (!bytes || !duration || !Number.isFinite(duration)) return '-';
  const kbps = (bytes * 8) / duration / 1000;
  return kbps >= 1000 ? `${(kbps / 1000).toFixed(2)} Mbps` : `${Math.round(kbps)} kbps`;
};

export function FinalShotVideo({ videoUrl }: { videoUrl: string }) {
  const [metadata, setMetadata] = useState<VideoMetadata>({
    duration: null, width: null, height: null, sizeBytes: null,
  });

  useEffect(() => {
    let cancelled = false;
    fetch(videoUrl, { method: 'HEAD' })
      .then(async response => {
        if (cancelled || !response.ok) return;
        const contentLength = response.headers.get('content-length');
        let fallbackSize: number | null = null;
        if (!contentLength && response.headers.get('content-type')?.includes('application/json')) {
          try {
            const payload = await response.json();
            fallbackSize = Number(payload?.size) || null;
          } catch {
            fallbackSize = null;
          }
        }
        if (!cancelled) setMetadata(previous => ({
          ...previous,
          sizeBytes: contentLength ? Number(contentLength) : fallbackSize,
        }));
      })
      .catch(() => {
        // 部分视频源不支持 HEAD；播放器仍可提供时长和分辨率。
      });
    return () => { cancelled = true; };
  }, [videoUrl]);

  return <>
    <video
      controls
      src={videoUrl}
      className="mt-3 w-full rounded"
      onLoadedMetadata={event => {
        const video = event.currentTarget;
        setMetadata(previous => ({
          ...previous,
          duration: Number.isFinite(video.duration) ? video.duration : null,
          width: video.videoWidth || null,
          height: video.videoHeight || null,
        }));
      }}
    />
    <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-600">
      <span>时长：{formatDuration(metadata.duration)}</span>
      <span>分辨率：{metadata.width && metadata.height ? `${metadata.width} x ${metadata.height}` : '-'}</span>
      <span>大小：{formatFileSize(metadata.sizeBytes)}</span>
      <span>码率：{formatBitrate(metadata.sizeBytes, metadata.duration)}</span>
    </div>
  </>;
}
