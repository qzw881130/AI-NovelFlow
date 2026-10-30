import type { CurrentImageQuality, CurrentReviewImage } from '../api/imageReviews';
import { useImageQuality } from '../pages/ChapterGenerate/components/ImageQualityStatus';

export function useLibraryImageQuality(images: CurrentReviewImage[]) {
  const { current } = useImageQuality(images, null);
  const getQuality = (imageUrl?: string | null, taskId?: string | null): CurrentImageQuality | undefined => {
    if (!imageUrl) return undefined;
    return current.find(row => row.taskId === (taskId || null) && row.imageUrl === imageUrl);
  };

  return { getQuality };
}
