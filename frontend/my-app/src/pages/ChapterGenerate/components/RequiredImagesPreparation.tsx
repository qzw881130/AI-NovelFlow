import { useEffect, useState } from 'react';
import { shotsApi, type Shot, type PrepareRequiredImageItem } from '../../../api/shots';
import { canPrepareMaterials, prepareCurrentRequiredImages, requiredImagesForClip, requiredImageStatus } from '../requiredImagePreparation';

export function RequiredImagesPreparation({ shot, novelId, chapterId, clipIndex, onShot, hidePrepare = false }: {
  shot: Shot; novelId?: string; chapterId?: string; clipIndex?: number; onShot: (shot: Shot) => void; hidePrepare?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<PrepareRequiredImageItem[]>([]);
  const [error, setError] = useState('');
  const items = requiredImagesForClip(shot, clipIndex);
  const active = items.some(i => i.active_task);
  const revision = shot.videoDirectorPlan?.clip_plan_revision;
  useEffect(() => { setResults([]); setError(''); }, [shot.id, revision]);
  useEffect(() => {
    if (!active || !novelId || !chapterId) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const response = await shotsApi.getShot(novelId, chapterId, shot.id);
        if (!stopped && response.success && response.data) onShot(response.data);
      } catch { /* Keep polling; a failed GET is not an image failure. */ }
      if (!stopped) timer = setTimeout(poll, 2000);
    };
    timer = setTimeout(poll, 2000);
    return () => { stopped = true; clearTimeout(timer); };
  }, [active, novelId, chapterId, shot.id, revision, onShot]);
  const prepare = async (stateIndex?: number) => {
    if (!novelId || !chapterId) return;
    setBusy(true); setError('');
    try {
      const result = await prepareCurrentRequiredImages(shot, clipIndex == null ? undefined : [clipIndex], stateIndex == null ? undefined : [stateIndex], {
        getShot: async () => { const r = await shotsApi.getShot(novelId, chapterId, shot.id); if (!r.success || !r.data) throw new Error('读取分镜失败'); return r.data; },
        prepare: async (revision, clips, states) => { const r = await shotsApi.prepareRequiredImages(novelId, chapterId, shot.id, revision, clips, states); if (!r.success || !r.data) throw new Error('图片准备失败'); return r.data; },
        onShot,
      });
      setResults(result);
    } catch (e) { setError(e instanceof Error ? e.message : '图片准备失败'); }
    finally { setBusy(false); }
  };
  if (!canPrepareMaterials(shot) || !items.length) return null;
  return <div data-testid="required-images-preparation" className="mt-2 rounded-md border border-amber-100 bg-amber-50/40 px-2.5 py-2 text-xs">
    <div className="mb-1 font-medium text-gray-700">需要{items.length}张执行必需图片 · {items.every(i => i.ready) ? '素材已准备' : '图片准备中'}</div>
    {items.map(item => {
      const status = requiredImageStatus(item);
      const result = results.find(r => r.state_index === item.state_index);
      const failure = !item.ready && !item.active_task ? item.failure?.error_message || (result?.status === 'FAILED' ? result.reason : '') : '';
      const label = item.ready ? '已就绪' : item.active_task ? (item.active_task.current_step || '等待 / 生成中') : failure ? '失败' : '待生成';
      return <div key={`${revision}-${item.state_id}`} className="my-1">
        <div className="flex flex-wrap items-center gap-2">
          <details className="min-w-0"><summary className="cursor-pointer" title="查看视觉状态描述">{item.state_id} · {item.shot_time}s · {label}</summary><p className="mt-1 whitespace-pre-wrap text-gray-600">{item.description || '无状态描述'}</p></details>
          <span className="text-gray-500">→ {item.consumer_clip_indexes.map(c => `C${c}`).join('、')}{item.image_source === 'SHOT_IMAGE' ? ' · 主分镜图' : ''}{item.consumers.some(c => c.kind === 'EARLY_COMPOSITION') ? ' · 已选为早期构图锚点，执行必需' : ''}</span>
          {(status === 'FAILED' || failure) && <button type="button" disabled={busy} onClick={() => prepare(item.state_index)} className="text-red-700 underline disabled:opacity-50">重试{item.state_id}</button>}
        </div>
        {failure && <p role="alert" className="text-red-700">{failure}</p>}
      </div>;
    })}
    {!hidePrepare && items.some(i => !i.ready) && <button type="button" disabled={busy} onClick={() => prepare()} className="mt-1 rounded border border-amber-300 bg-white px-2 py-1 text-amber-800 disabled:opacity-50">{busy ? '正在提交…' : '生成必需视觉状态图'}</button>}
    {results.some(r => r.status !== 'FAILED') && <p className="mt-1 text-gray-500">{results.filter(r => r.status === 'READY').length}张复用 · {results.filter(r => r.status === 'REUSED').length}个任务等待 · {results.filter(r => r.status === 'QUEUED').length}个任务已提交</p>}
    {error && <p role="alert" className="mt-1 text-red-700">{error}</p>}
  </div>;
}
