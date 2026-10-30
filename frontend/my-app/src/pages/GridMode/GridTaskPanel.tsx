import { useState } from 'react';
import { API_BASE } from '../../api';
import { toast } from '../../stores/toastStore';

export type GridTask = {
  id: string; type: string; status: string; name: string; currentStep?: string;
  resultUrl?: string;
  createdAt?: string | null; startedAt?: string | null; completedAt?: string | null;
  errorMessage?: string; progress?: number; shotId?: string; clipIndex?: number;
  panelIndex?: number; parentTaskId?: string; batchOrder?: number; gridStep?: string;
  autoShotResults?: Record<string, { status: string; message?: string; step?: string; warnings?: string[] }>;
  nameplatePreview?: { url?: string; status?: string; warnings?: string[]; autoApproved?: boolean };
};

type TaskDetail = GridTask & {
  promptText?: string; referenceImages?: { picture_index?: number; role?: string; name?: string; url: string }[];
  metadata?: Record<string, unknown>; comfyuiPromptId?: string; resultUrl?: string;
};

const statusLabel: Record<string, string> = {
  pending: '排队中', running: '执行中', completed: '已完成', failed: '失败', cancelled: '已取消',
};

function formatTaskTime(value?: string | null) {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).format(date);
}

function taskEventTime(task: GridTask) {
  const time = task.completedAt || task.startedAt || task.createdAt;
  if (!time) return null;
  const label = task.completedAt ? task.status === 'failed' ? '失败时间' : task.status === 'cancelled' ? '取消时间' : '完成时间'
    : task.startedAt ? '开始时间' : '创建时间';
  return `${label}：${formatTaskTime(time)}`;
}

export function GridTaskPanel({ tasks, shots, onRefresh, onAction, onResumeBatch }: {
  tasks: GridTask[];
  shots: { id: string; index: number }[];
  onRefresh: () => void;
  onAction: (label: string, action: () => Promise<unknown>) => void;
  onResumeBatch: (step: string) => void;
}) {
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [loadingId, setLoadingId] = useState('');
  const batch = tasks.find(item => item.type === 'grid_batch');
  const otherBatches = tasks.filter(item => item.type === 'grid_batch' && item.id !== batch?.id);
  const autoTasks = tasks.filter(item => ['grid_auto_batch', 'grid_board_batch', 'grid_review_batch'].includes(item.type));
  const autoParentIds = new Set(autoTasks.map(item => item.id));
  const children = batch ? tasks.filter(item => item.parentTaskId === batch.id).sort((a, b) => (a.batchOrder || 0) - (b.batchOrder || 0)) : [];
  const autoChildren = tasks.filter(item => autoParentIds.has(item.parentTaskId || ''));
  const recent = tasks.filter(item => !['grid_batch', 'grid_auto_batch', 'grid_board_batch', 'grid_review_batch'].includes(item.type) && item.parentTaskId !== batch?.id && !autoParentIds.has(item.parentTaskId || ''));
  const visible = [...recent.filter(item => ['failed', 'running', 'pending'].includes(item.status)),
    ...recent.filter(item => item.status === 'completed').slice(0, 6)];
  const done = children.filter(item => item.status === 'completed').length;
  const runningChild = children.find(item => item.status === 'running');
  const batchProgress = children.length
    ? children.reduce((total, item) => total + (item.status === 'completed' ? 100 : item.status === 'running' ? item.progress || 0 : 0), 0) / children.length
    : batch?.progress || 0;
  const shotName = (item: GridTask) => shots.find(shot => shot.id === item.shotId)?.index;
  const superseded = (item: GridTask) => {
    const position = tasks.indexOf(item);
    return position > 0 && tasks.slice(0, position).some(newer =>
      newer.shotId === item.shotId && newer.gridStep === item.gridStep
      && newer.clipIndex === item.clipIndex && newer.panelIndex === item.panelIndex
      && ['pending', 'running', 'completed'].includes(newer.status));
  };

  const openDetail = async (item: GridTask) => {
    setLoadingId(item.id);
    try {
      const response = await fetch(`${API_BASE}/tasks/${item.id}`);
      const payload = await response.json();
      if (!response.ok || !payload.success) throw new Error(payload.detail || payload.message || '读取任务详情失败');
      setDetail(payload.data);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    } finally { setLoadingId(''); }
  };

  const itemView = (item: GridTask) => <div key={item.id} className={`rounded-lg border p-3 text-xs ${item.status === 'failed' ? 'border-red-200 bg-red-50' : 'border-gray-200 bg-white'}`}>
    <div className="flex items-start justify-between gap-2"><div className="min-w-0 font-medium text-gray-900">{item.batchOrder ? `${item.batchOrder}. ` : ''}{shotName(item) ? `Shot ${shotName(item)} · ` : ''}{item.clipIndex ? `C${item.clipIndex} · ` : ''}{item.panelIndex ? `格 ${item.panelIndex} · ` : ''}{item.name.split(' · ')[0]}</div><span className={`shrink-0 ${item.status === 'failed' && !superseded(item) ? 'text-red-700' : item.status === 'completed' ? 'text-green-700' : 'text-blue-700'}`}>{superseded(item) ? '历史任务' : statusLabel[item.status] || item.status}</span></div>
    {item.currentStep && <p className="mt-1 text-gray-600">{item.currentStep}</p>}
    {item.errorMessage && <p className="mt-1 break-words text-red-700">{item.errorMessage}</p>}
    {taskEventTime(item) && <p className="mt-1 text-gray-500">{taskEventTime(item)}</p>}
    {['pending', 'running'].includes(item.status) && <div className="mt-2 h-1.5 overflow-hidden rounded bg-gray-200"><div className="h-full rounded bg-blue-500" style={{ width: `${Math.max(4, item.progress || 0)}%` }} /></div>}
    <div className="mt-2 flex flex-wrap gap-3 text-blue-700"><button type="button" onClick={() => openDetail(item)} disabled={loadingId === item.id}>查看输入与任务详情</button>
      {['pending', 'running'].includes(item.status) && <button type="button" className="text-red-700" onClick={() => onAction('取消任务', () => fetch(`${API_BASE}/tasks/${item.id}/cancel`, { method: 'POST' }).then(async response => { const body = await response.json(); if (!response.ok || !body.success) throw new Error(body.detail || body.message || '取消失败'); }))}>取消</button>}
      {['failed', 'cancelled'].includes(item.status) && !superseded(item) && !autoParentIds.has(item.parentTaskId || '') && <button type="button" onClick={() => onAction('从此步续做', () => fetch(`${API_BASE}/tasks/${item.id}/retry`, { method: 'POST' }).then(async response => { const body = await response.json(); if (!response.ok || !body.success) throw new Error(body.detail || body.message || '重试失败'); }))}>从此步续做</button>}
    </div>
  </div>;

  return <section className="rounded-xl border bg-white p-4">
    <div className="flex items-center justify-between"><h2 className="font-semibold">本章生成任务</h2><button type="button" onClick={onRefresh} className="text-xs text-blue-700">刷新</button></div>
    <p className="mt-1 text-xs text-gray-500">任务在后台执行；关闭页面后仍可回来查看。</p>
    {autoTasks.map(auto => { const autoReviewCount = Object.values(auto.autoShotResults || {}).filter(result => result.status === 'needs_review').length;
      const autoWarningCount = Object.values(auto.autoShotResults || {}).filter(result => result.warnings?.length).length;
      return <div key={auto.id} className={`mt-3 rounded-lg border p-3 text-sm ${auto.status === 'failed' ? 'border-red-200 bg-red-50' : autoReviewCount || autoWarningCount ? 'border-amber-200 bg-amber-50' : 'border-green-200 bg-green-50'}`}>
      <div className="flex justify-between gap-2"><strong>{auto.name.split(' · ')[0]}</strong><span>{statusLabel[auto.status] || auto.status}{autoReviewCount ? ` · ${autoReviewCount} 个 Shot 待人工复核` : ''}{autoWarningCount ? ` · ${autoWarningCount} 个 Shot 带警告` : ''}</span></div>
      <div className="mt-2 h-2 overflow-hidden rounded bg-green-100"><div className="h-full bg-green-600" style={{ width: `${auto.progress || 0}%` }} /></div>
      <p className="mt-1 text-xs text-gray-700">{auto.currentStep}</p>
      {taskEventTime(auto) && <p className="mt-1 text-xs text-gray-500">{taskEventTime(auto)}</p>}
      <div className="mt-2 max-h-40 space-y-1 overflow-y-auto">{Object.entries(auto.autoShotResults || {}).map(([id, result]) => <p key={id} className={`text-xs ${result.status === 'failed' ? 'text-red-700' : result.status === 'needs_review' || result.warnings?.length ? 'text-amber-800' : 'text-gray-700'}`}>
        Shot {shots.find(shot => shot.id === id)?.index || '?'} · {{ pending: '排队中', running: '执行中', completed: '已完成', failed: '失败', needs_review: '待人工复核' }[result.status] || result.status}{result.message ? ` · ${result.message}` : ''}{result.warnings?.length ? ` · ${result.warnings.join('；')}` : ''}
      </p>)}</div>
      {auto.errorMessage && <p className="mt-2 text-xs text-red-700">{auto.errorMessage}</p>}
      {['failed', 'cancelled'].includes(auto.status) && <button type="button" className="mt-2 text-xs font-medium text-blue-700" onClick={() => onAction('重试未完成 Shot', () => fetch(`${API_BASE}/tasks/${auto.id}/retry`, { method: 'POST' }).then(async response => { const body = await response.json(); if (!response.ok || !body.success) throw new Error(body.detail || body.message || '重试失败'); }))}>重试未完成 Shot</button>}
      {['pending', 'running'].includes(auto.status) && <button type="button" className="mt-2 text-xs text-red-700" onClick={() => onAction('取消自动批量任务', () => fetch(`${API_BASE}/tasks/${auto.id}/cancel`, { method: 'POST' }).then(async response => { const body = await response.json(); if (!response.ok || !body.success) throw new Error(body.detail || body.message || '取消失败'); }))}>取消整批</button>}
    </div>; })}
    {autoChildren.length > 0 && <details className="mt-3"><summary className="cursor-pointer text-sm text-gray-700">自动批量步骤 · {autoChildren.length} 项</summary><div className="mt-2 max-h-72 space-y-2 overflow-y-auto">{autoChildren.slice(0, 20).map(itemView)}</div></details>}
    {batch && <div className="mt-3 rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm"><div className="flex justify-between gap-2"><strong>最近一批 · {batch.name.split(' · ')[0]}</strong><span>{runningChild ? '执行中' : statusLabel[batch.status] || batch.status}</span></div>
      <div className="mt-2 h-2 overflow-hidden rounded bg-blue-100"><div className="h-full bg-blue-600" style={{ width: `${batchProgress}%` }} /></div>
      <p className="mt-1 text-xs text-gray-700">完成 {done}/{children.length || '?'} 项{runningChild ? ` · 第 ${runningChild.batchOrder} 项 ${runningChild.progress || 0}%` : ''}</p>
      {taskEventTime(batch) && <p className="mt-1 text-xs text-gray-500">{taskEventTime(batch)}</p>}
      {runningChild?.currentStep && <p className="mt-1 text-xs text-blue-800">{runningChild.name.split(' · ').slice(-2).join(' · ')}：{runningChild.currentStep}</p>}
      {batch.errorMessage && <p className="mt-1 text-xs text-red-700">{batch.currentStep}：{batch.errorMessage}</p>}
      {batch.status === 'failed' && batch.gridStep && <button type="button" className="mt-2 text-xs font-medium text-blue-700" onClick={() => onResumeBatch(batch.gridStep!)}>继续生成未完成项</button>}
      {['pending', 'running'].includes(batch.status) && <button type="button" className="mt-2 text-xs text-red-700" onClick={() => onAction('取消整批任务', () => fetch(`${API_BASE}/tasks/${batch.id}/cancel`, { method: 'POST' }).then(async response => { const body = await response.json(); if (!response.ok || !body.success) throw new Error(body.detail || body.message || '取消失败'); }))}>取消整批</button>}
    </div>}
    {children.length > 0 && <details className="mt-3" open={batch?.status === 'failed'}><summary className="cursor-pointer text-sm text-gray-700">本批明细 · {children.length} 项</summary><div className="mt-2 max-h-72 space-y-2 overflow-y-auto">{children.map(itemView)}</div></details>}
    {otherBatches.length > 0 && <details className="mt-3"><summary className="cursor-pointer text-sm text-gray-700">其他步骤批次 · {otherBatches.length} 批</summary><div className="mt-2 space-y-2">{otherBatches.map(itemView)}</div></details>}
    <div className="mt-3 max-h-80 space-y-2 overflow-y-auto">{visible.length ? visible.map(itemView) : !batch && !autoTasks.length && <p className="text-xs text-gray-500">暂无宫格任务</p>}</div>
    {detail && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true" aria-label="任务详情"><div className="max-h-[85vh] w-full max-w-3xl overflow-y-auto rounded-xl bg-white p-5 shadow-xl"><div className="flex justify-between gap-3"><div><h3 className="font-semibold">{detail.name}</h3><p className="mt-1 text-xs text-gray-500">{statusLabel[detail.status] || detail.status} · Task {detail.id}</p><p className="mt-1 text-xs text-gray-500">{[detail.createdAt && `创建：${formatTaskTime(detail.createdAt)}`, detail.startedAt && `开始：${formatTaskTime(detail.startedAt)}`, detail.completedAt && `结束：${formatTaskTime(detail.completedAt)}`].filter(Boolean).join(' · ')}</p></div><button type="button" onClick={() => setDetail(null)} className="text-sm text-gray-600">关闭</button></div>
      {detail.errorMessage && <p className="mt-3 rounded bg-red-50 p-2 text-sm text-red-700">{detail.errorMessage}</p>}
      {detail.referenceImages?.length ? <div className="mt-4"><h4 className="text-sm font-medium">实际参考图</h4><div className="mt-2 flex flex-wrap gap-2">{detail.referenceImages.map((ref, index) => <div key={index} className="w-32"><img src={ref.url} alt={`Picture ${index + 1}`} className="aspect-video w-full rounded object-cover" /><p className="mt-1 text-xs">Picture {ref.picture_index || index + 1} · {ref.role || ref.name}</p></div>)}</div></div> : null}
      {detail.promptText && <div className="mt-4"><h4 className="text-sm font-medium">实际提交提示词</h4><pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap rounded bg-slate-900 p-3 text-xs text-white">{detail.promptText}</pre></div>}
      {detail.metadata && <details className="mt-4 text-xs"><summary className="cursor-pointer">版式、修订与来源</summary><pre className="mt-2 overflow-auto whitespace-pre-wrap rounded bg-gray-50 p-3">{JSON.stringify(detail.metadata, null, 2)}</pre></details>}
      {detail.comfyuiPromptId && <p className="mt-3 text-xs text-gray-500">ComfyUI prompt ID：{detail.comfyuiPromptId}</p>}
    </div></div>}
  </section>;
}
