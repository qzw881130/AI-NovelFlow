import { useEffect, useRef, useState } from 'react';
import { shotsApi, type ContinuationMode } from '../../../api/shots';

export function ShotAutoGeneration({ novelId, chapterId, shotId, disabled = false, continuationMode = 'AUTO', onProgress, mainImageNewerThanVideo = false }: {
  novelId?: string; chapterId?: string; shotId: string; disabled?: boolean; continuationMode?: ContinuationMode; onProgress?: () => void; mainImageNewerThanVideo?: boolean;
}) {
  const [state, setState] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const progressCallback = useRef(onProgress);
  const progressSignature = useRef('');
  progressCallback.current = onProgress;
  useEffect(() => {
    setState(null); setError('');
    progressSignature.current = '';
    if (!novelId || !chapterId) return;
    let stopped = false;
    const load = async () => {
      try {
        const r = await shotsApi.getShotAutoGeneration(novelId, chapterId, shotId);
        if (!stopped && r.success) {
          setState(r.data);
          const next = JSON.stringify([r.data?.status, r.data?.current_step]);
          if (r.data && progressSignature.current !== next) progressCallback.current?.();
          progressSignature.current = next;
        }
      }
      catch { /* Status polling never starts or retries generation. */ }
    };
    void load(); return () => { stopped = true; };
  }, [novelId, chapterId, shotId]);
  useEffect(() => {
    if (!novelId || !chapterId) return;
    const delay = ['pending', 'running'].includes(state?.status) ? 3000 : 30000;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const r = await shotsApi.getShotAutoGeneration(novelId, chapterId, shotId);
        if (!stopped && r.success) {
          setState(r.data);
          const next = JSON.stringify([r.data?.status, r.data?.current_step]);
          if (r.data && progressSignature.current !== next) progressCallback.current?.();
          progressSignature.current = next;
        }
      } catch { /* A later poll may recover. */ }
      if (!stopped) timer = setTimeout(poll, delay);
    };
    timer = setTimeout(poll, delay);
    return () => { stopped = true; clearTimeout(timer); };
  }, [novelId, chapterId, shotId, state?.status]);
  const control = async (action: 'start' | 'pause' | 'resume') => {
    if (!novelId || !chapterId || busy) return;
    setBusy(true); setError('');
    try {
      const r = await shotsApi.controlShotAutoGeneration(novelId, chapterId, shotId, action, continuationMode);
      if (!r.success) throw new Error((r as any).detail || r.message || '自动生成操作失败');
      const latest = await shotsApi.getShotAutoGeneration(novelId, chapterId, shotId);
      if (latest.success) setState(latest.data);
    } catch (e) { setError(e instanceof Error ? e.message : '操作失败'); }
    finally { setBusy(false); }
  };
  const running = ['pending','running'].includes(state?.status);
  const resumable = ['paused','failed','cancelled'].includes(state?.status);
  const completed = state?.status === 'completed';
  const successfulShots = state?.children?.filter((child: any) => child.status === 'completed').length ?? 0;
  return <div data-testid="shot-auto-generation" className="my-2 flex flex-wrap items-center gap-2 rounded border border-blue-100 bg-blue-50/40 p-2 text-xs">
    <button disabled={busy || running || disabled || completed || !novelId || !chapterId}
      onClick={() => control(resumable ? 'resume' : 'start')}
      title={completed ? '当前计划的自动生成已完成；如需重新制作视频，请使用下方 Clip 的重新生成操作' : undefined}
      className="rounded bg-blue-600 px-3 py-1.5 font-medium text-white disabled:opacity-40">
      {busy ? '提交中…' : completed ? '当前 Shot 自动生成已完成' : resumable ? '继续自动生成整个 Shot' : '自动生成整个 Shot'}
    </button>
    {mainImageNewerThanVideo && <span role="status" className="text-amber-800">主分镜图晚于此前生成的 Shot 视频，旧成片可能已失效。请检查并按需重新生成 Clip 和最终视频。</span>}
    {running && <button disabled={busy || state?.pause_requested} onClick={() => control('pause')} className="rounded border px-2 py-1">
      {state?.pause_requested ? '正在停止后续生成…' : '停止后续生成'}
    </button>}
    {state && <span>{completed ? `已完成 · ${successfulShots} 个 Shot 成功 · 进度 ${state.progress ?? 100}%` : `${state.current_step} · 进度 ${state.progress ?? 0}%`}</span>}
    {completed && state.children?.some((child: any) => child.reused_assembly) &&
      <span>已复用现有 Clip 和最终视频。</span>}
    {completed && <span className="text-gray-600">当前计划无需重复运行；要重做，请在下方 Clip 的“操作”中选择“重新生成片段”。</span>}
    {state?.status === 'paused' && <span>已提交片段继续保存，点击继续后复用。</span>}
    {(error || state?.error) && <span role="alert" className="text-red-700">{error || state.error}</span>}
  </div>;
}
