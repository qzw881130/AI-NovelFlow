import { useState } from 'react';
import { createPortal } from 'react-dom';
import { AlertTriangle } from 'lucide-react';
import type { CurrentImageQuality } from '../api/imageReviews';
import { ImageQualityBadge } from '../pages/ChapterGenerate/components/ImageQualityStatus';
import { ImageReviewModal } from '../pages/Tasks/components/ImageReviewModal';

export function LibraryImageReview({ quality, name }: { quality?: CurrentImageQuality; name: string }) {
  const [isOpen, setIsOpen] = useState(false);
  if (!quality) return null;
  const isError = quality.qualityStatus === 'ERROR';

  return <div
    className={isError
      ? 'mt-2 flex w-full flex-wrap items-center gap-2 rounded-lg border-2 border-red-400 bg-red-50 px-3 py-2 text-red-800 shadow-sm'
      : 'mt-2 flex flex-wrap items-center gap-2'}
    role={isError ? 'alert' : undefined}
  >
    {isError ? (
      <span data-quality-status="ERROR" title={quality.summary || '图片质量评审出错'} className="inline-flex items-center gap-1.5 text-xs font-semibold">
        <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />
        图片质量评审出错
      </span>
    ) : <ImageQualityBadge status={quality.qualityStatus} summary={quality.summary} />}
    {quality.reviewId && quality.taskId && <button
      type="button"
      onClick={() => setIsOpen(true)}
      className={isError
        ? 'text-xs font-medium text-red-800 underline underline-offset-2 hover:text-red-950'
        : 'text-xs text-blue-600 hover:text-blue-800 hover:underline'}
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
