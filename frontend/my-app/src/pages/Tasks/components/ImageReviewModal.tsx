import { useCallback, useEffect, useRef, useState } from 'react';
import { Loader2, RefreshCw, X } from 'lucide-react';
import { imageReviewApi, type ImageReview } from '../../../api/imageReviews';
import type { Task } from '../../../types';

export const DIMENSION_NAMES: Record<string, string> = {
  CHARACTER_IDENTITY: '人物身份', CHARACTER_COUNT: '人物数量', HUMAN_ANATOMY: '人体结构',
  ACTION_ACCURACY: '动作准确性', PROP_ACCURACY: '道具准确性', SCENE_CONSISTENCY: '场景一致性',
};
const STATUS_STYLE: Record<string, string> = {
  PASS: 'bg-green-100 text-green-700', WARNING: 'bg-amber-100 text-amber-800', FAIL: 'bg-red-100 text-red-700',
};
const verdictLabel = (value: string) => value === 'WARNING' ? 'REVIEW' : value;

export function ImageReviewModal({ task, onClose, autoStart = false, initialReviewId }: { task: Pick<Task, 'id' | 'name'>; onClose: () => void; autoStart?: boolean; initialReviewId?: string }) {
  const [reviews, setReviews] = useState<ImageReview[]>([]);
  const [selected, setSelected] = useState<string | null>(initialReviewId || null);
  const [loading, setLoading] = useState(true);
  const [reviewing, setReviewing] = useState(false);
  const [error, setError] = useState('');
  const autoStarted = useRef(false);
  const historyRequest = useRef<{ taskId: string; promise: ReturnType<typeof imageReviewApi.list> } | null>(null);
  const review = reviews.find(item => item.id === selected) || reviews[0];

  const runReview = useCallback(async () => {
    setReviewing(true); setError('');
    try {
      const result = await imageReviewApi.create(task.id);
      if (!result.success || !result.data) throw new Error(result.message || '评审失败');
      setReviews(previous => [result.data!, ...previous.filter(item => item.id !== result.data!.id)]);
      setSelected(result.data.id);
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setReviewing(false); }
  }, [task.id]);

  useEffect(() => {
    let active = true;
    if (historyRequest.current?.taskId !== task.id) {
      historyRequest.current = { taskId: task.id, promise: imageReviewApi.list(task.id) };
    }
    historyRequest.current.promise.then(result => {
      if (active) {
        setReviews(previous => [...previous, ...(result.data || []).filter(item => !previous.some(existing => existing.id === item.id))]);
        setError(result.success ? '' : (result.message || '评审记录加载失败'));
      }
    }).catch(err => { if (active) setError(String(err)); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [task.id]);

  useEffect(() => {
    if (autoStart && !autoStarted.current) {
      autoStarted.current = true;
      void runReview();
    }
  }, [autoStart, runReview]);

  const pending = reviews.some(item => item.status === 'pending' || item.status === 'running');
  useEffect(() => {
    if (!pending) return;
    let active = true;
    const timer = setInterval(() => {
      void imageReviewApi.list(task.id).then(result => {
        if (active && result.success && result.data) setReviews(result.data);
      }).catch(() => { /* Keep history visible; the next poll can recover. */ });
    }, 3000);
    return () => { active = false; clearInterval(timer); };
  }, [pending, task.id]);

  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
    <div className="flex max-h-[90vh] w-full max-w-4xl flex-col rounded-xl bg-white shadow-xl" onClick={event => event.stopPropagation()}>
      <div className="flex items-center justify-between border-b px-5 py-4">
        <div><h2 className="text-lg font-semibold">AI 图片质量评审</h2><p className="text-xs text-gray-500">{task.name || task.id}</p></div>
        <div className="flex items-center gap-2">
          <button disabled={reviewing} onClick={runReview} className="inline-flex items-center gap-1 rounded bg-blue-600 px-3 py-2 text-sm text-white disabled:opacity-50">
            {reviewing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}{review ? '重新评审' : '开始 AI 评审'}
          </button>
          <button onClick={onClose} aria-label="关闭"><X className="h-5 w-5" /></button>
        </div>
      </div>
      <div className="overflow-y-auto p-5 space-y-5">
        {loading && <p className="text-sm text-gray-500">加载评审记录…</p>}
        {error && <p className="rounded bg-red-50 p-3 text-sm text-red-700">{error}</p>}
        {!loading && reviews.length === 0 && <p className="text-sm text-gray-500">尚无评审记录。点击开始 AI 评审。</p>}
        {reviews.length > 1 && <select value={review?.id || ''} onChange={event => setSelected(event.target.value)} className="rounded border p-2 text-sm">
          {reviews.map(item => <option key={item.id} value={item.id}>{item.createdAt || item.id} · {verdictLabel(item.overall || item.status)}</option>)}
        </select>}
        {review && <>
          <div className="flex flex-wrap items-center gap-3">
            {review.overall && <span className={`rounded px-3 py-1 font-semibold ${STATUS_STYLE[review.overall]}`}>{verdictLabel(review.overall)}</span>}
            <span className="text-sm text-gray-700">{review.summary || (review.error ? `ERROR · ${review.error}` : review.status === 'pending' ? 'PENDING · 等待评审' : 'RUNNING · 评审中')}</span>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            {Object.entries(DIMENSION_NAMES).map(([key, label]) => <div key={key} className="rounded border p-3 text-sm">
              <span className="font-medium">{label}</span>
              {review.dimensions[key] && <><span className={`ml-2 rounded px-2 py-0.5 text-xs ${STATUS_STYLE[review.dimensions[key].status]}`}>{verdictLabel(review.dimensions[key].status)}</span>
                <p className="mt-1 text-gray-600">{review.dimensions[key].summary}</p></>}
            </div>)}
          </div>
          <div><h3 className="mb-2 font-medium">问题详情（{review.issues.length}）</h3>
            <div className="space-y-2">{review.issues.map((issue, index) => <div key={index} className="rounded border p-3 text-sm">
              <div className="mb-2 font-medium">{DIMENSION_NAMES[issue.type] || issue.type} · <span className={issue.severity === 'FAIL' ? 'text-red-700' : 'text-amber-700'}>{verdictLabel(issue.severity)}</span></div>
              <p>预期：{issue.expected}</p><p>实际：{issue.observed}</p><p>位置：{issue.location}</p><p>依据：{issue.evidence}</p><p>建议：{issue.suggestion}</p>
            </div>)}</div>
          </div>
          <div className="break-all border-t pt-3 text-xs text-gray-500">模型：{review.model || '—'} · 提示词：{review.templateName || '—'} · 版本：{review.templateVersion || '—'} · LLM 日志：{review.llmLogId || '—'}</div>
          <details className="text-sm"><summary className="cursor-pointer font-medium">评审输入快照</summary>
            <pre className="mt-2 max-h-60 overflow-auto whitespace-pre-wrap rounded bg-gray-50 p-3 text-xs">{JSON.stringify(review.input, null, 2)}</pre>
          </details>
        </>}
      </div>
    </div>
  </div>;
}
