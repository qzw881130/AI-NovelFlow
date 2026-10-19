import { useState } from 'react';
import { createPortal } from 'react-dom';
import type { CurrentImageQuality } from '../api/imageReviews';
import { ImageQualityBadge } from '../pages/ChapterGenerate/components/ImageQualityStatus';
import { ImageReviewModal } from '../pages/Tasks/components/ImageReviewModal';

export function LibraryImageReview({ quality, name }: { quality?: CurrentImageQuality; name: string }) {
  const [isOpen, setIsOpen] = useState(false);
  if (!quality) return null;

  return <div className="mt-2 flex flex-wrap items-center gap-2">
    <ImageQualityBadge status={quality.qualityStatus} summary={quality.summary} />
    {quality.reviewId && quality.taskId && <button
      type="button"
      onClick={() => setIsOpen(true)}
      className="text-xs text-blue-600 hover:text-blue-800 hover:underline"
      aria-label={`查看${name}的AI图片评审详情`}
    >查看评审详情</button>}
    {isOpen && quality.taskId && createPortal(
      <ImageReviewModal
        key={`${quality.taskId}:${quality.imageUrl}`}
        task={{ id: quality.taskId, name }}
        imageUrl={quality.imageUrl}
        initialReviewId={quality.reviewId || undefined}
        readOnly
        onClose={() => setIsOpen(false)}
      />,
      document.body,
    )}
  </div>;
}
