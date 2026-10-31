import { useEffect, useState } from 'react';
import { formatAspectRatio } from '../../utils/aspectRatio';

type ImageInfo = { width: number; height: number; sizeBytes: number | null };

const formatSize = (bytes: number | null) => {
  if (bytes === null) return '—';
  if (bytes > 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
  if (bytes > 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
};

export function GridBoardDraftImage({ imageUrl }: { imageUrl: string }) {
  const [info, setInfo] = useState<ImageInfo>({ width: 0, height: 0, sizeBytes: null });

  useEffect(() => {
    const controller = new AbortController();
    fetch(imageUrl, { method: 'HEAD', signal: controller.signal })
      .then(response => {
        if (!response.ok) return;
        const length = response.headers.get('content-length');
        const sizeBytes = length === null ? null : Number(length);
        if (sizeBytes !== null && Number.isFinite(sizeBytes) && sizeBytes >= 0) {
          setInfo(current => ({ ...current, sizeBytes }));
        }
      })
      .catch(() => { /* Some image hosts do not support HEAD requests. */ });
    return () => controller.abort();
  }, [imageUrl]);

  return (
    <figure className="w-full">
      <img
        src={imageUrl}
        alt="宫格整板初稿"
        className="w-full rounded-lg"
        onLoad={event => {
          const { naturalWidth: width, naturalHeight: height } = event.currentTarget;
          setInfo(current => ({ ...current, width, height }));
        }}
      />
      <figcaption className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm text-gray-600">
        <span>尺寸：{info.width && info.height ? `${info.width} × ${info.height} px` : '—'}</span>
        <span>大小：{formatSize(info.sizeBytes)}</span>
        <span>比例：{info.width && info.height ? formatAspectRatio(info.width, info.height) : '—'}</span>
      </figcaption>
    </figure>
  );
}
