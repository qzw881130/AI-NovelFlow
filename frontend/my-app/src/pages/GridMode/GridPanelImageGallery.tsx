import { useState } from 'react';
import { createPortal } from 'react-dom';
import { ImageQualityBadge, useImageQuality } from '../ChapterGenerate/components/ImageQualityStatus';
import { ImageReviewModal } from '../Tasks/components/ImageReviewModal';
import type { GridTask } from './GridTaskPanel';

type PanelImage = {
  index: number;
  image_url?: string;
  review_status: string;
  review_note?: string;
};

const reviewLabels: Record<string, string> = {
  passed: '已通过', warning: '待复核', failed: '需重做', pending: '待审核',
};
const reviewStyles: Record<string, string> = {
  passed: 'bg-green-100 text-green-700',
  warning: 'bg-amber-100 text-amber-800',
  failed: 'bg-red-100 text-red-700',
  pending: 'bg-gray-100 text-gray-600',
};

function imageKey(url?: string) {
  if (!url) return '';
  try { return new URL(url, window.location.origin).pathname; }
  catch { return url; }
}

export function GridPanelImageGallery({ panels, layout, tasks, shotIndex, selectedIndex, onSelect }: {
  panels: PanelImage[];
  layout: string;
  tasks: GridTask[];
  shotIndex: number;
  selectedIndex: number;
  onSelect: (index: number) => void;
}) {
  const [reviewTarget, setReviewTarget] = useState<{ task: GridTask; imageUrl: string; reviewId: string } | null>(null);
  const reviewTasks = panels.map(panel => tasks.find(task => task.type === 'grid_panel_review'
    && task.panelIndex === panel.index && imageKey(task.resultUrl) === imageKey(panel.image_url)));
  const images = panels.map((panel, index) => ({ taskId: reviewTasks[index]?.id || null, imageUrl: panel.image_url || '' }));
  const { current: qualities, error } = useImageQuality(images, shotIndex);

  return <>
    {error && <p className="text-xs text-amber-700">{error}；下方仍显示已保存的子格审核状态。</p>}
    <div className={`grid gap-2 ${layout.endsWith('3') ? 'grid-cols-1 sm:grid-cols-2 xl:grid-cols-3' : 'grid-cols-1 sm:grid-cols-2'}`}>
      {panels.map((panel, index) => {
        const quality = qualities[index];
        const reviewTask = reviewTasks[index];
        const reviewLabel = reviewLabels[panel.review_status] || panel.review_status;
        return <div key={panel.index} className={`min-w-0 overflow-hidden rounded-lg border-2 bg-white ${index === selectedIndex ? 'border-blue-500' : 'border-gray-200'}`}>
          <button type="button" onClick={() => onSelect(index)} aria-label={`选择格 ${panel.index}`} aria-current={index === selectedIndex ? 'true' : undefined} className="block w-full text-left focus-visible:outline-2 focus-visible:outline-blue-600">
            {panel.image_url ? <img src={panel.image_url} alt={`格 ${panel.index}`} className="aspect-video w-full object-cover" /> : <div className="flex aspect-video items-center justify-center bg-gray-100 text-xs text-gray-500">尚无子格图片</div>}
            <span className="block p-2">
              <span className="flex flex-wrap items-center gap-1.5 text-xs"><strong className="mr-1">格 {panel.index}</strong>
                {reviewTask && quality && <ImageQualityBadge status={quality.qualityStatus} summary={quality.summary} />}
                <span className={`rounded px-1.5 py-0.5 text-[11px] ${reviewStyles[panel.review_status] || reviewStyles.pending}`}>审核 · {reviewLabel}</span>
              </span>
            </span>
          </button>
          {reviewTask && quality?.reviewId && panel.image_url && <div className="border-t border-gray-100 px-2 py-1.5">
            <button type="button" className="text-xs text-blue-700 hover:underline focus-visible:outline-2 focus-visible:outline-blue-600" onClick={() => setReviewTarget({ task: reviewTask, imageUrl: panel.image_url!, reviewId: quality.reviewId! })}>查看评审详情</button>
          </div>}
        </div>;
      })}
    </div>
    {reviewTarget && createPortal(<ImageReviewModal key={`${reviewTarget.task.id}:${reviewTarget.imageUrl}`}
      task={{ id: reviewTarget.task.id, name: `Shot ${shotIndex} · 格 ${reviewTarget.task.panelIndex} · AI 图片质量评审` }}
      imageUrl={reviewTarget.imageUrl} initialReviewId={reviewTarget.reviewId} readOnly onClose={() => setReviewTarget(null)} />,
    document.body)}
  </>;
}
