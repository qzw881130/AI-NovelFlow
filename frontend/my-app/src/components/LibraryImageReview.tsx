import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { AlertTriangle, Loader2 } from 'lucide-react';
import { imageReviewApi, type CurrentImageQuality, type ImageReview } from '../api/imageReviews';
import { ImageQualityBadge } from '../pages/ChapterGenerate/components/ImageQualityStatus';
import { ImageReviewModal } from '../pages/Tasks/components/ImageReviewModal';

type LibraryKind = 'character' | 'scene' | 'prop';

function reviewStatus(review: ImageReview): CurrentImageQuality['qualityStatus'] {
  if (review.status === 'success') return review.overall || 'ERROR';
  return ({ pending: 'PENDING', running: 'RUNNING', error: 'ERROR' } as const)[review.status];
}

export function LibraryImageReview({ quality, name, kind, entityId, imageUrl }: {
  quality?: CurrentImageQuality; name: string; kind: LibraryKind; entityId: string; imageUrl: string;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [error, setError] = useState('');
  const [localQuality, setLocalQuality] = useState<CurrentImageQuality | null>(null);
  const current = localQuality?.imageUrl === imageUrl ? localQuality : quality;
  const isError = current?.qualityStatus === 'ERROR';
  useEffect(() => {
    if (!localQuality?.taskId || !['PENDING', 'RUNNING'].includes(localQuality.qualityStatus)) return;
    let active = true;
    const timer = window.setInterval(() => {
      void imageReviewApi.statuses([{ taskId: localQuality.taskId, imageUrl: localQuality.imageUrl }])
        .then(result => {
          if (active && result.success && result.data?.[0]) setLocalQuality(result.data[0]);
        }).catch(() => { /* The next poll can recover. */ });
    }, 3000);
    return () => { active = false; window.clearInterval(timer); };
  }, [localQuality?.taskId, localQuality?.imageUrl, localQuality?.qualityStatus]);
  const startReview = async () => {
    setReviewing(true);
    setError('');
    try {
      const result = await imageReviewApi.createLibrary(kind, entityId);
      if (!result.success || !result.data) {
        throw new Error((result as { detail?: string }).detail || result.message || 'AI 评审失败');
      }
      const { taskId, review } = result.data;
      setLocalQuality({ taskId, imageUrl, qualityStatus: reviewStatus(review),
        reviewId: review.id, summary: review.summary || review.error });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setReviewing(false);
    }
  };

  return <div
    className={isError
      ? 'mt-2 flex w-full flex-wrap items-center gap-2 rounded-lg border-2 border-red-400 bg-red-50 px-3 py-2 text-red-800 shadow-sm'
      : 'mt-2 flex flex-wrap items-center gap-2'}
    role={isError ? 'alert' : undefined}
  >
    {isError ? (
      <span data-quality-status="ERROR" title={current?.summary || '图片质量评审出错'} className="inline-flex items-center gap-1.5 text-xs font-semibold">
        <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />
        图片质量评审出错
      </span>
    ) : <ImageQualityBadge status={current?.qualityStatus || 'NOT_REVIEWED'} summary={current?.summary} />}
    <button type="button" disabled={reviewing} onClick={() => void startReview()}
      className="inline-flex items-center gap-1 text-xs font-medium text-blue-700 hover:underline disabled:opacity-50"
      aria-label={`${name}：${current?.reviewId ? '重新 AI 评审' : '开始 AI 评审'}`}>
      {reviewing && <Loader2 className="h-3 w-3 animate-spin" />}
      {reviewing ? 'AI 评审中' : current?.reviewId ? '重新 AI 评审' : '开始 AI 评审'}
    </button>
    {current?.reviewId && current.taskId && <button
      type="button"
      onClick={() => setIsOpen(true)}
      className={isError
        ? 'text-xs font-medium text-red-800 underline underline-offset-2 hover:text-red-950'
        : 'text-xs text-blue-600 hover:text-blue-800 hover:underline'}
      aria-label={`查看${name}的AI图片评审详情`}
    >查看评审详情</button>}
    {error && <span role="alert" className="w-full text-xs text-red-700">{error}</span>}
    {isOpen && current?.taskId && createPortal(
      <ImageReviewModal
        key={`${current.taskId}:${current.imageUrl}`}
        task={{ id: current.taskId, name }}
        imageUrl={current.imageUrl}
        initialReviewId={current.reviewId || undefined}
        readOnly
        onClose={() => setIsOpen(false)}
      />,
      document.body,
    )}
  </div>;
}
