import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Check, Film, Loader2, RefreshCw, Sparkles, X } from 'lucide-react';

import { shotsApi, type HdVideoVariant, type Shot } from '../../../api/shots';
import { toast } from '../../../stores/toastStore';
import { useChapterGenerateStore } from '../stores';

const MP_OPTIONS = [0.5, 0.8, 1.0, 1.2, 1.5, 1.8, 2.0];

interface HdRepaintTabProps {
  novelId: string;
  chapterId: string;
  shots: Shot[];
}

interface VideoMetadata {
  width: number;
  height: number;
  duration: number;
}

type HdDisplayStatus = 'pending' | 'queued' | 'generating' | 'completed' | 'failed';
const getHdVariant = (shot: Shot, targetMp: number): HdVideoVariant | undefined =>
  (shot.hdVideoVariants || []).find((variant) => Number(variant.targetMegapixels) === Number(targetMp));
const getHdDisplayStatus = (shot: Shot, targetMp: number): HdDisplayStatus => {
  const variant = getHdVariant(shot, targetMp);
  if (variant?.status === 'running') return 'generating';
  if (variant?.status === 'pending') return 'queued';
  if (variant?.videoUrl) return 'completed';
  if (variant?.status === 'failed') return 'failed';
  return 'pending';
};
const hasAnyActiveHd = (shot: Shot) => (shot.hdVideoVariants || []).some((variant) => ['pending', 'running'].includes(variant.status));
const isHdActive = (shot: Shot, targetMp: number) => ['queued', 'generating'].includes(getHdDisplayStatus(shot, targetMp));
const statusLabel = (shot: Shot, targetMp: number) => ({
  pending: '待生成',
  queued: '队列中',
  generating: '生成中',
  completed: '已完成',
  failed: '失败',
})[getHdDisplayStatus(shot, targetMp)];
const statusClassName = (shot: Shot, targetMp: number) => ({
  pending: 'text-gray-500',
  queued: 'text-blue-600',
  generating: 'text-indigo-600',
  completed: 'text-green-600',
  failed: 'text-red-600',
})[getHdDisplayStatus(shot, targetMp)];

export function HdRepaintTab({ novelId, chapterId, shots }: HdRepaintTabProps) {
  const currentShotId = useChapterGenerateStore((state) => state.currentShotId);
  const currentShotIndex = useChapterGenerateStore((state) => state.currentShotIndex);
  const setShots = useChapterGenerateStore((state) => state.setShots);
  const targetMp = useChapterGenerateStore((state) => state.hdTargetMegapixels);
  const setTargetMp = useChapterGenerateStore((state) => state.setHdTargetMegapixels);
  const currentShot = shots.find((shot) => shot.id === currentShotId) || shots[currentShotIndex - 1];
  const currentHdVariant = currentShot ? getHdVariant(currentShot, targetMp) : undefined;
  const [source, setSource] = useState<any>(null);
  const [sourceError, setSourceError] = useState('');
  const [loadingSource, setLoadingSource] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [showBatchModal, setShowBatchModal] = useState(false);
  const [batchSubmitting, setBatchSubmitting] = useState(false);
  const [selectedBatchShotIds, setSelectedBatchShotIds] = useState<Set<string>>(new Set());
  const [showMergeModal, setShowMergeModal] = useState(false);
  const [selectedMergeShotIds, setSelectedMergeShotIds] = useState<Set<string>>(new Set());
  const [mergeTargetMp, setMergeTargetMp] = useState(1.0);
  const [mergeSubmitting, setMergeSubmitting] = useState(false);
  const [draftMetadata, setDraftMetadata] = useState<VideoMetadata | null>(null);
  const [hdMetadata, setHdMetadata] = useState<VideoMetadata | null>(null);
  const [batchStatus, setBatchStatus] = useState<any>(null);

  const replaceShot = (updated: Shot) => {
    setShots(useChapterGenerateStore.getState().shots.map((shot) => shot.id === updated.id ? { ...shot, ...updated } : shot));
  };

  const refreshShot = async (shotId: string) => {
    const result = await shotsApi.getShot(novelId, chapterId, shotId);
    if (result.success && result.data) replaceShot(result.data);
    return result.data;
  };

  const loadSource = async () => {
    if (!currentShot?.id) return;
    setLoadingSource(true);
    setSourceError('');
    const result = await shotsApi.getHdRepaintSource(novelId, chapterId, currentShot.id);
    if (result.success) setSource(result.data);
    else {
      setSource(null);
      setSourceError(result.message || '没有可 Replay 的成功视频 Execution');
    }
    setLoadingSource(false);
  };

  const loadBatchStatus = async () => {
    const result = await shotsApi.getLatestHdRepaintBatch(novelId, chapterId, targetMp);
    if (result.success) setBatchStatus(result.data || null);
  };

  useEffect(() => {
    setDraftMetadata(null);
    setHdMetadata(null);
    loadSource();
    loadBatchStatus();
  }, [currentShot?.id, targetMp]);

  useEffect(() => {
    const active = shots.filter(hasAnyActiveHd);
    if (!active.length) return;
    const timer = window.setInterval(async () => {
      await Promise.all(active.map((shot) => refreshShot(shot.id)));
      if (currentShot?.id) loadSource();
      loadBatchStatus();
    }, 3000);
    return () => window.clearInterval(timer);
  }, [shots.map((shot) => `${shot.id}:${shot.hdVideoStatus}:${shot.hdVideoTaskId || ''}`).join('|'), currentShot?.id]);

  const startCurrent = async () => {
    if (!currentShot) return;
    setSubmitting(true);
    try {
      const result = await shotsApi.createHdRepaint(novelId, chapterId, currentShot.id, targetMp);
      if (!result.success) throw new Error(result.message || '高清重绘任务创建失败');
      await refreshShot(currentShot.id);
      toast.success('高清重绘任务已进入持久化队列');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '高清重绘任务创建失败');
    } finally {
      setSubmitting(false);
    }
  };

  const eligibleShots = shots.filter((shot) => !!shot.videoUrl && !isHdActive(shot, targetMp));
  const openBatchModal = () => {
    setSelectedBatchShotIds(new Set(eligibleShots.map((shot) => shot.id)));
    setShowBatchModal(true);
    loadBatchStatus();
  };

  const toggleBatchShot = (shot: Shot) => {
    if (!shot.videoUrl || isHdActive(shot, targetMp)) return;
    setSelectedBatchShotIds((current) => {
      const next = new Set(current);
      if (next.has(shot.id)) next.delete(shot.id);
      else next.add(shot.id);
      return next;
    });
  };

  const startBatch = async () => {
    const selectedIds = eligibleShots.filter((shot) => selectedBatchShotIds.has(shot.id)).map((shot) => shot.id);
    if (!selectedIds.length) return;
    setBatchSubmitting(true);
    try {
      const result = await shotsApi.createHdRepaintBatch(novelId, chapterId, selectedIds, targetMp);
      if (!result.success) throw new Error(result.message || '批量高清重绘创建失败');
      const taskByShotId = new Map<string, string>((result.data?.tasks || []).map((task: any) => [String(task.shotId), String(task.taskId)]));
      setShots(useChapterGenerateStore.getState().shots.map((shot) => taskByShotId.has(shot.id) ? {
        ...shot,
        hdVideoStatus: 'pending' as const,
        hdVideoTaskId: taskByShotId.get(shot.id) || null,
      } : shot));
      setShowBatchModal(false);
      toast.success(result.message || '批量高清重绘已进入持久化队列');
      loadBatchStatus();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '批量高清重绘创建失败');
    } finally {
      setBatchSubmitting(false);
    }
  };

  const openMergeModal = () => {
    setMergeTargetMp(targetMp);
    setSelectedMergeShotIds(new Set(shots.filter((shot) => !!getHdVariant(shot, targetMp)?.videoUrl).map((shot) => shot.id)));
    setShowMergeModal(true);
  };
  const changeMergeTarget = (megapixels: number) => {
    setMergeTargetMp(megapixels);
    setSelectedMergeShotIds(new Set(shots.filter((shot) => !!getHdVariant(shot, megapixels)?.videoUrl).map((shot) => shot.id)));
  };
  const availableHdMergeShotIds = shots.filter((shot) => !!getHdVariant(shot, mergeTargetMp)?.videoUrl).map((shot) => shot.id);
  const hdMergeComplete = shots.length > 0 && availableHdMergeShotIds.length === shots.length;

  const mergeHdChapter = async () => {
    const selectedIds = shots.filter((shot) => getHdVariant(shot, mergeTargetMp)?.videoUrl && selectedMergeShotIds.has(shot.id)).map((shot) => shot.id);
    if (!selectedIds.length) return;
    setMergeSubmitting(true);
    try {
      const result = await shotsApi.mergeChapterVideos(novelId, chapterId, selectedIds, 'hd', mergeTargetMp);
      if (!result.success) throw new Error(result.message || '高清章节视频合并失败');
      setShowMergeModal(false);
      toast.success('高清章节视频合并任务已提交，可在任务列表查看');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '高清章节视频合并失败');
    } finally {
      setMergeSubmitting(false);
    }
  };

  const retryFailedBatch = async () => {
    if (!batchStatus?.id) return;
    const result = await shotsApi.retryFailedHdRepaints(novelId, chapterId, batchStatus.id);
    if (!result.success) return toast.error(result.message || '重试失败项失败');
    await Promise.all(shots.filter((shot) => shot.hdVideoStatus === 'failed').map((shot) => refreshShot(shot.id)));
    toast.success(result.message || '失败项已重新进入队列');
    loadBatchStatus();
  };

  const estimatedDimensions = draftMetadata ? (() => {
    const scale = Math.sqrt((targetMp * 1_000_000) / Math.max(1, draftMetadata.width * draftMetadata.height));
    return `${Math.round(draftMetadata.width * scale / 16) * 16}×${Math.round(draftMetadata.height * scale / 16) * 16}`;
  })() : '-';

  const renderVideo = (label: string, url: string | null, metadata: VideoMetadata | null, setMetadata: (value: VideoMetadata) => void, badge?: string) => (
    <div className="rounded-xl border border-gray-200 bg-white p-3 shadow-sm">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-sm font-semibold text-gray-800">{label}</span>
        {badge && <span className="rounded-full bg-blue-50 px-2 py-0.5 text-xs text-blue-700">{badge}</span>}
      </div>
      {url ? (
        <video
          key={url}
          src={url}
          controls
          preload="metadata"
          className="aspect-video w-full rounded-lg bg-black object-contain"
          onLoadedMetadata={(event) => setMetadata({
            width: event.currentTarget.videoWidth,
            height: event.currentTarget.videoHeight,
            duration: event.currentTarget.duration,
          })}
        />
      ) : (
        <div className="flex aspect-video items-center justify-center rounded-lg bg-gray-950 text-sm text-gray-400">暂无视频</div>
      )}
      <div className="mt-2 text-xs text-gray-500">
        {metadata ? `${metadata.width}×${metadata.height} · ${metadata.duration.toFixed(1)}秒` : '等待视频元数据'}
      </div>
    </div>
  );

  if (!currentShot) return <div className="p-6 text-gray-500">请选择 Shot</div>;

  return (
    <div className="h-full overflow-y-auto p-4">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">高清重绘 · Shot #{currentShot.index}</h2>
          <p className="text-xs text-gray-500">Replay 原 successful H3 Execution，仅覆盖 Megapixels</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button onClick={startCurrent} disabled={submitting || !source || isHdActive(currentShot, targetMp)} className="btn-primary inline-flex items-center gap-2 disabled:opacity-50">
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}高清重绘当前 Shot
          </button>
          <button onClick={openBatchModal} className="btn-secondary">批量高清重绘</button>
          <button onClick={openMergeModal} className="btn-secondary inline-flex items-center gap-1"><Film className="h-4 w-4" />合并高清视频</button>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
        <div className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-2">
            {renderVideo('初稿视频', currentShot.videoUrl, draftMetadata, setDraftMetadata, '初稿')}
            {renderVideo(`高清 ${targetMp.toFixed(1)} MP`, currentHdVariant?.videoUrl || null, hdMetadata, setHdMetadata, statusLabel(currentShot, targetMp))}
          </div>

          <div className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="mb-3 text-sm font-semibold text-gray-800">高清目标</div>
            <div className="mb-3 flex flex-wrap gap-2">
              {MP_OPTIONS.map((mp) => <button key={mp} onClick={() => setTargetMp(mp)} className={`rounded-lg border px-3 py-2 text-sm ${targetMp === mp ? 'border-blue-500 bg-blue-50 text-blue-700' : 'border-gray-200 text-gray-600 hover:border-blue-300'}`}>{mp.toFixed(1)}{mp === 1 ? ' 推荐' : ''}</button>)}
            </div>
            <div className="rounded-lg bg-gray-50 px-3 py-2 text-sm text-gray-700">{targetMp.toFixed(1)} MP → {estimatedDimensions}</div>
          </div>

          <div className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="mb-3 text-sm font-semibold text-gray-800">重绘策略</div>
            <div className="grid gap-2 text-sm text-gray-700 sm:grid-cols-2">
              {['使用原视频实际 Prompt', '使用原 Seed', '使用原参考图及原始顺序', '使用原 Workflow', '使用原时长/帧数', '使用原模型与生成参数'].map((item) => <div key={item} className="flex items-center gap-2"><Check className="h-4 w-4 text-green-600" />{item}</div>)}
            </div>
          </div>
        </div>

        <aside className="space-y-3 rounded-xl border border-gray-200 bg-white p-4 text-sm">
          <div className="flex items-center justify-between"><span className="font-semibold text-gray-800">Execution 信息</span><button onClick={loadSource} title="刷新"><RefreshCw className={`h-4 w-4 ${loadingSource ? 'animate-spin' : ''}`} /></button></div>
          {source ? <>
            <div><span className="text-gray-500">来源任务</span><div className="break-all font-mono text-xs">{source.sourceTaskId}</div></div>
            <div className="flex justify-between"><span className="text-gray-500">原 MP</span><span>{source.sourceMegapixels ?? '-'}</span></div>
            <div className="flex justify-between"><span className="text-gray-500">Seed</span><span className="font-mono">{source.seed ?? (source.isMultiClip ? '按 Clip' : '-')}</span></div>
            <div className="flex justify-between"><span className="text-gray-500">时长</span><span>{source.duration || '-'}秒</span></div>
            <div className="flex justify-between"><span className="text-gray-500">执行结构</span><span>{source.isMultiClip ? `${source.clipCount} Clips` : '单 Execution'}</span></div>
            {source.clips?.map((clip: any) => <div key={clip.windowIndex} className="rounded bg-gray-50 px-2 py-1 text-xs">C{clip.windowIndex} · Seed {clip.seed ?? '-'} · {clip.sourceMegapixels ?? '-'} MP</div>)}
          </> : <div className="rounded-lg bg-amber-50 p-3 text-amber-700">{sourceError || '读取 Replay Source...'}</div>}
          <div className="border-t border-gray-100 pt-3"><span className="text-gray-500">{targetMp.toFixed(1)} MP 状态</span><div className="mt-1 font-medium">{statusLabel(currentShot, targetMp)}</div></div>
        </aside>
      </div>

      {showBatchModal && createPortal(<div className="fixed inset-0 z-[300] flex items-center justify-center bg-black/50 p-4">
        <div className="flex max-h-[90vh] w-full max-w-4xl flex-col rounded-xl bg-white shadow-2xl">
          <div className="flex items-center justify-between border-b p-4"><div><h3 className="font-semibold">高清重绘整章</h3><p className="text-xs text-gray-500">所有任务将持久化，关闭页面后继续执行</p></div><button onClick={() => setShowBatchModal(false)}><X className="h-5 w-5" /></button></div>
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
            <div className="flex flex-wrap gap-2">{MP_OPTIONS.map((mp) => <button key={mp} onClick={() => setTargetMp(mp)} className={`rounded border px-3 py-1.5 ${targetMp === mp ? 'border-blue-500 bg-blue-50 text-blue-700' : 'border-gray-200'}`}>{mp.toFixed(1)} MP</button>)}</div>
            <div className="grid grid-cols-3 gap-3 text-center text-sm md:grid-cols-6">
              <div className="rounded bg-gray-50 p-3">已选择<br/><b>{selectedBatchShotIds.size}</b></div>
              <div className="rounded bg-gray-50 p-3">可提交<br/><b>{eligibleShots.length}</b></div>
              <div className="rounded bg-gray-100 p-3 text-gray-700">待生成<br/><b>{shots.filter((shot) => getHdDisplayStatus(shot, targetMp) === 'pending').length}</b></div>
              <div className="rounded bg-blue-50 p-3 text-blue-700">队列中<br/><b>{shots.filter((shot) => getHdDisplayStatus(shot, targetMp) === 'queued').length}</b></div>
              <div className="rounded bg-indigo-50 p-3 text-indigo-700">生成中<br/><b>{shots.filter((shot) => getHdDisplayStatus(shot, targetMp) === 'generating').length}</b></div>
              <div className="rounded bg-green-50 p-3 text-green-700">已完成<br/><b>{shots.filter((shot) => getHdDisplayStatus(shot, targetMp) === 'completed').length}</b></div>
            </div>
            <div className="flex items-center justify-between border-b border-gray-100 pb-2">
              <span className="text-sm font-medium text-gray-700">选择分镜视频</span>
              <button
                type="button"
                onClick={() => setSelectedBatchShotIds(selectedBatchShotIds.size === eligibleShots.length ? new Set() : new Set(eligibleShots.map((shot) => shot.id)))}
                className="text-sm text-blue-600 hover:text-blue-800"
              >
                {selectedBatchShotIds.size === eligibleShots.length && eligibleShots.length > 0 ? '取消全选' : '全选可用'}
              </button>
            </div>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-4">
              {shots.map((shot) => {
                const disabled = !shot.videoUrl || isHdActive(shot, targetMp);
                const selected = selectedBatchShotIds.has(shot.id);
                return (
                  <button
                    key={shot.id}
                    type="button"
                    disabled={disabled}
                    onClick={() => toggleBatchShot(shot)}
                    className={`relative overflow-hidden rounded-lg border-2 text-left transition ${disabled ? 'cursor-not-allowed border-gray-100 opacity-55' : selected ? 'border-blue-500 ring-2 ring-blue-100' : 'border-gray-200 hover:border-blue-300'}`}
                  >
                    <div className="relative aspect-video bg-gray-950">
                      {shot.videoUrl ? <video src={shot.videoUrl} preload="metadata" muted className="h-full w-full object-cover" /> : <div className="flex h-full items-center justify-center text-xs text-gray-400">无初稿视频</div>}
                      <span className="absolute left-1 top-1 rounded bg-black/65 px-1.5 py-0.5 text-xs text-white">#{shot.index}</span>
                      {!disabled && <span className={`absolute right-1 top-1 flex h-5 w-5 items-center justify-center rounded-full ${selected ? 'bg-blue-500 text-white' : 'bg-white/80 text-transparent'}`}><Check className="h-3.5 w-3.5" /></span>}
                    </div>
                    <div className="flex items-center justify-between gap-2 px-2 py-1.5 text-xs">
                      <span className="truncate">初稿可用</span>
                      <span className={statusClassName(shot, targetMp)}>{statusLabel(shot, targetMp)}</span>
                    </div>
                  </button>
                );
              })}
            </div>
            {batchStatus && <div className="rounded-lg border border-gray-200 p-3 text-sm"><div className="flex justify-between"><span>最近批次 · {batchStatus.targetMegapixels} MP</span><b>{batchStatus.progress}%</b></div><div className="mt-2 text-xs text-gray-500">完成 {batchStatus.completed} / 队列 {batchStatus.pending} / 生成中 {batchStatus.running} / 失败 {batchStatus.failed}</div>{batchStatus.failed > 0 && <button onClick={retryFailedBatch} className="mt-2 text-sm text-red-600 underline">重试失败项</button>}</div>}
          </div>
          <div className="flex justify-end gap-2 border-t p-4"><button onClick={() => setShowBatchModal(false)} className="btn-secondary">取消</button><button onClick={startBatch} disabled={!selectedBatchShotIds.size || batchSubmitting} className="btn-primary disabled:opacity-50">{batchSubmitting ? '提交中...' : `开始批量高清重绘 (${selectedBatchShotIds.size})`}</button></div>
        </div>
      </div>, document.body)}

      {showMergeModal && createPortal(<div className="fixed inset-0 z-[300] flex items-center justify-center bg-black/50 p-4">
        <div className="flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl">
          <div className="flex items-center justify-between border-b px-5 py-4">
            <div><h3 className="font-semibold text-gray-900">选择要合并的 {mergeTargetMp.toFixed(1)} MP 视频</h3><p className="mt-1 text-xs text-gray-500">按 Shot 顺序合并；缺少该目标结果的 Shot 不可选择</p></div>
            <button onClick={() => setShowMergeModal(false)}><X className="h-5 w-5" /></button>
          </div>
          <div className="flex flex-wrap gap-2 border-b bg-gray-50 px-5 py-3">
            {MP_OPTIONS.map((mp) => (
              <button
                key={mp}
                type="button"
                onClick={() => changeMergeTarget(mp)}
                className={`rounded-lg border px-3 py-1.5 text-sm ${mergeTargetMp === mp ? 'border-purple-500 bg-purple-50 text-purple-700' : 'border-gray-200 bg-white text-gray-600 hover:border-purple-300'}`}
              >
                {mp.toFixed(1)} MP
              </button>
            ))}
          </div>
          <div className="flex items-center justify-between border-b bg-gray-50 px-5 py-3 text-sm">
            <span>已选择 {selectedMergeShotIds.size} / 可合并 {availableHdMergeShotIds.length} / 共 {shots.length}{!hdMergeComplete ? ` · 缺 ${shots.length - availableHdMergeShotIds.length} 个 Shot` : ''}</span>
            <button
              type="button"
              onClick={() => {
                const available = shots.filter((shot) => !!getHdVariant(shot, mergeTargetMp)?.videoUrl).map((shot) => shot.id);
                setSelectedMergeShotIds(selectedMergeShotIds.size === available.length ? new Set() : new Set(available));
              }}
              className="text-blue-600 hover:text-blue-800"
            >
              {selectedMergeShotIds.size === shots.filter((shot) => !!getHdVariant(shot, mergeTargetMp)?.videoUrl).length && selectedMergeShotIds.size > 0 ? '取消全选' : '全选可用'}
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-4">
              {shots.map((shot) => {
                const variant = getHdVariant(shot, mergeTargetMp);
                const available = !!variant?.videoUrl;
                const selected = selectedMergeShotIds.has(shot.id);
                return <button
                  key={shot.id}
                  type="button"
                  disabled={!available}
                  onClick={() => setSelectedMergeShotIds((current) => {
                    const next = new Set(current);
                    if (next.has(shot.id)) next.delete(shot.id); else next.add(shot.id);
                    return next;
                  })}
                  className={`relative overflow-hidden rounded-lg border-2 text-left transition ${!available ? 'cursor-not-allowed border-gray-100 opacity-50' : selected ? 'border-purple-500 ring-2 ring-purple-100' : 'border-gray-200 hover:border-purple-300'}`}
                >
                  <div className="relative aspect-video bg-gray-950">
                    {variant?.videoUrl ? <video src={variant.videoUrl} preload="metadata" muted className="h-full w-full object-cover" /> : <div className="flex h-full items-center justify-center text-xs text-gray-400">缺少 {mergeTargetMp.toFixed(1)} MP</div>}
                    <span className="absolute left-1 top-1 rounded bg-black/65 px-1.5 py-0.5 text-xs text-white">#{shot.index}</span>
                    {available && <span className={`absolute right-1 top-1 flex h-5 w-5 items-center justify-center rounded-full ${selected ? 'bg-purple-500 text-white' : 'bg-white/80 text-transparent'}`}><Check className="h-3.5 w-3.5" /></span>}
                  </div>
                  <div className="flex items-center justify-between px-2 py-1.5 text-xs"><span>{mergeTargetMp.toFixed(1)} MP</span><span className={available ? 'text-green-600' : 'text-gray-400'}>{available ? '可合并' : `缺少 ${mergeTargetMp.toFixed(1)} MP`}</span></div>
                </button>;
              })}
            </div>
          </div>
          <div className="flex justify-end gap-2 border-t px-5 py-4">
            <button onClick={() => setShowMergeModal(false)} className="btn-secondary">取消</button>
            <button onClick={mergeHdChapter} disabled={!hdMergeComplete || selectedMergeShotIds.size !== shots.length || mergeSubmitting} className="btn-primary disabled:opacity-50">{mergeSubmitting ? '提交中...' : hdMergeComplete ? `合并完整 ${mergeTargetMp.toFixed(1)} MP 章回视频` : `缺少 ${shots.length - availableHdMergeShotIds.length} 个 ${mergeTargetMp.toFixed(1)} MP Shot`}</button>
          </div>
        </div>
      </div>, document.body)}
    </div>
  );
}
