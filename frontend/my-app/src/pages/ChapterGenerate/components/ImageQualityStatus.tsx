import { useEffect, useState } from 'react';
import { AlertCircle, AlertTriangle, CheckCircle, Clock3, HelpCircle, Loader2, XCircle } from 'lucide-react';
import { imageReviewApi, type CurrentImageQuality, type CurrentReviewImage, type ImageQualityStatus } from '../../../api/imageReviews';

export const QUALITY_STATES: ImageQualityStatus[] = ['NOT_REVIEWED', 'PENDING', 'RUNNING', 'PASS', 'WARNING', 'REVIEW', 'FAIL', 'ERROR'];
const labels: Record<ImageQualityStatus, string> = {
  NOT_REVIEWED: '未评审', PENDING: '等待评审', RUNNING: '评审中', PASS: 'PASS', WARNING: 'WARNING', REVIEW: 'REVIEW', FAIL: 'FAIL', ERROR: '评审错误',
};
const styles: Record<ImageQualityStatus, string> = {
  NOT_REVIEWED: 'bg-gray-100 text-gray-600', PENDING: 'bg-blue-50 text-blue-700', RUNNING: 'bg-blue-100 text-blue-700',
  PASS: 'bg-green-100 text-green-700', WARNING: 'bg-amber-100 text-amber-800', REVIEW: 'bg-amber-100 text-amber-800', FAIL: 'bg-red-100 text-red-700', ERROR: 'bg-orange-100 text-orange-800',
};

export function ImageQualityBadge({ status, summary }: { status: ImageQualityStatus; summary?: string | null }) {
  return <span data-quality-status={status} title={summary || `图片质量：${labels[status]}`} className={`inline-flex rounded px-1.5 py-0.5 text-[11px] ${styles[status]}`}>质量 · {labels[status]}</span>;
}

const qualityIcons = {
  NOT_REVIEWED: HelpCircle, PENDING: Clock3, RUNNING: Loader2, PASS: CheckCircle,
  WARNING: AlertTriangle, REVIEW: AlertCircle, FAIL: XCircle, ERROR: AlertCircle,
};

export function ImageQualityIcon({ status, summary }: { status: ImageQualityStatus; summary?: string | null }) {
  const Icon = qualityIcons[status];
  const label = `AI 图片评审：${labels[status]}`;
  return (
    <span
      data-quality-status={status}
      title={summary ? `${label}。${summary}` : label}
      aria-label={label}
      className={`inline-flex rounded border border-current/20 p-0.5 shadow-sm ${styles[status]}`}
    >
      <Icon className={`h-3 w-3 ${status === 'RUNNING' ? 'animate-spin' : ''}`} />
    </span>
  );
}

export function useImageQuality(images: CurrentReviewImage[], refreshKey: unknown) {
  const key = JSON.stringify(images);
  const [rows, setRows] = useState<CurrentImageQuality[]>([]);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const input = JSON.parse(key) as CurrentReviewImage[];
    if (input.length === 0) {
      setRows([]);
      setError('');
      return () => { active = false; };
    }
    const poll = async () => {
      try {
        const batches = await Promise.all(Array.from({ length: Math.ceil(input.length / 200) }, (_, index) =>
          imageReviewApi.statuses(input.slice(index * 200, (index + 1) * 200))));
        if (batches.some(result => !result.success || !result.data)) throw new Error('质量状态暂不可用');
        if (active) { setRows(batches.flatMap(result => result.data || [])); setError(''); }
      } catch { if (active) setError('质量状态暂不可用，图片和视频生成不受影响'); }
      finally { if (active) timer = setTimeout(poll, 5000); }
    };
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [key, refreshKey]);
  // Never use the previous result's quality while a regenerated image is loading.
  const current = images.map(image => rows.find(row => row.taskId === image.taskId && row.imageUrl === image.imageUrl)
    || { ...image, qualityStatus: 'NOT_REVIEWED' as const, reviewId: null, summary: null });
  return { current, error };
}

export function ImageQualitySummary({ rows, error }: { rows: CurrentImageQuality[]; error: string }) {
  return <div data-testid="shot-image-quality-summary" className="mb-2 flex flex-wrap items-center gap-2 text-xs text-gray-600">
    <span>Shot 图片质量 · {rows.length} 张已生成图片</span>
    {QUALITY_STATES.map(status => {
      const count = rows.filter(row => row.qualityStatus === status).length;
      return count ? <span key={status} className={`rounded px-1.5 py-0.5 ${styles[status]}`}>{labels[status]} {count}</span> : null;
    })}
    {error && <span className="text-amber-700">{error}</span>}
    <span className="text-gray-400">质量提醒不阻断视频生成</span>
  </div>;
}
