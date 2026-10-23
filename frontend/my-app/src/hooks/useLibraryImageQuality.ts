import { useEffect, useState } from 'react';
import { configApi } from '../api/config';
import type { CurrentImageQuality, CurrentReviewImage } from '../api/imageReviews';
import { useImageQuality } from '../pages/ChapterGenerate/components/ImageQualityStatus';

export function useLibraryImageQuality(images: CurrentReviewImage[]) {
  const [enabled, setEnabled] = useState(false);

  useEffect(() => {
    let active = true;
    void configApi.get().then(result => {
      if (active) setEnabled(Boolean(result.success && result.data?.autoImageReviewEnabled));
    }).catch(() => { if (active) setEnabled(false); });
    return () => { active = false; };
  }, []);

  const { current } = useImageQuality(enabled ? images : [], enabled);
  const getQuality = (imageUrl?: string | null, taskId?: string | null): CurrentImageQuality | undefined => {
    if (!enabled || !imageUrl) return undefined;
    return current.find(row => row.taskId === (taskId || null) && row.imageUrl === imageUrl);
  };

  return { getQuality };
}
