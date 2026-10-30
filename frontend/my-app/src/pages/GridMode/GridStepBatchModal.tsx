import { useEffect, useState } from 'react';

export type GridBatchStep = 'panels_plan' | 'board_prepare' | 'board_generate'
  | 'clips_plan' | 'clip_prepare' | 'clip_generate' | 'shot_merge';

export const GRID_BATCH_LABELS: Record<GridBatchStep, string> = {
  panels_plan: '批量规划未规划的 Shot',
  board_prepare: '批量准备整板提示词',
  board_generate: '批量生成已准备整板',
  clips_plan: '批量规划已审核 Shot 的 Clip',
  clip_prepare: '批量编译 H3 提示词',
  clip_generate: '批量生成已编译 Clip',
  shot_merge: '批量合并已完成 Shot',
};

export const isGridBatchStep = (value: string): value is GridBatchStep => value in GRID_BATCH_LABELS;

type BatchShot = {
  id: string;
  index: number;
  description: string;
  videoUrl?: string;
  gridData?: { board_prompt?: string; board_image_url?: string; panels: { image_url?: string; review_status: string }[] };
  gridClipPlan?: { clip_plan: { clip_index: number; prompt?: string; video_url?: string }[] };
};

export type GridBatchItem = { shot_id: string; clip_index?: number };
type Candidate = { key: string; item: GridBatchItem; title: string; detail: string };

export function getGridBatchCandidates(shots: BatchShot[], step: GridBatchStep): Candidate[] {
  return shots.flatMap(shot => {
    const grid = shot.gridData;
    const clips = shot.gridClipPlan?.clip_plan || [];
    const title = `Shot ${shot.index} · ${shot.description.split('｜')[0]}`;
    const wholeShot = (detail: string): Candidate[] => [{ key: shot.id, item: { shot_id: shot.id }, title, detail }];
    if (step === 'panels_plan') return !grid ? wholeShot('规划宫格子格') : [];
    if (step === 'board_prepare') return grid && !grid.board_prompt && !grid.board_image_url ? wholeShot('准备整板提示词') : [];
    if (step === 'board_generate') return grid?.board_prompt && !grid.board_image_url ? wholeShot('生成整板图') : [];
    if (step === 'clips_plan') return grid?.panels.length && grid.panels.every(panel => panel.image_url && panel.review_status === 'passed') && !shot.gridClipPlan
      ? wholeShot('规划 Clip') : [];
    if (step === 'shot_merge') return !shot.videoUrl && clips.length > 0 && clips.every(clip => clip.video_url)
      ? wholeShot(`合并 ${clips.length} 条 Clip`) : [];
    return clips.filter(clip => step === 'clip_prepare' ? !clip.prompt : clip.prompt && !clip.video_url).map(clip => ({
      key: `${shot.id}:${clip.clip_index}`,
      item: { shot_id: shot.id, clip_index: clip.clip_index },
      title: `${title} · C${clip.clip_index}`,
      detail: step === 'clip_prepare' ? '编译 H3 提示词' : '生成 H3 视频',
    }));
  });
}

export function GridStepBatchModal({ shots, step, onClose, onSubmit }: {
  shots: BatchShot[];
  step: GridBatchStep;
  onClose: () => void;
  onSubmit: (items: GridBatchItem[]) => void;
}) {
  const candidates = getGridBatchCandidates(shots, step);
  const [selected, setSelected] = useState<string[]>([]);
  const selectedItems = candidates.filter(candidate => selected.includes(candidate.key));
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  const toggle = (key: string) => setSelected(current => current.includes(key)
    ? current.filter(item => item !== key) : [...current, key]);

  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true" aria-label={GRID_BATCH_LABELS[step]}>
    <div className="flex max-h-[90vh] w-full max-w-3xl flex-col rounded-xl bg-white shadow-xl">
      <div className="border-b px-5 py-4"><div className="flex items-start justify-between gap-3"><div><h2 className="text-lg font-semibold">{GRID_BATCH_LABELS[step]}</h2><p className="mt-1 text-sm text-gray-600">选择要处理的{step === 'clip_prepare' || step === 'clip_generate' ? ' Clip' : ' Shot'}，仅提交勾选项，按画面顺序执行。</p></div><button type="button" className="text-sm text-gray-500" onClick={onClose}>关闭</button></div></div>
      <div className="overflow-y-auto px-5 py-4">
        <div className="mb-3 flex items-center justify-between text-sm"><span>已选 {selectedItems.length}/{candidates.length} 项</span><button type="button" disabled={!candidates.length} className="text-blue-700 disabled:opacity-40" onClick={() => setSelected(selectedItems.length === candidates.length ? [] : candidates.map(item => item.key))}>{selectedItems.length === candidates.length ? '取消全选' : '全选可处理项'}</button></div>
        {candidates.length ? <div className="grid gap-2 sm:grid-cols-2">{candidates.map(candidate => <label key={candidate.key} className={`flex cursor-pointer gap-3 rounded-lg border p-3 ${selected.includes(candidate.key) ? 'border-blue-400 bg-blue-50' : 'border-gray-200'}`}>
          <input type="checkbox" className="mt-1" checked={selected.includes(candidate.key)} onChange={() => toggle(candidate.key)} />
          <span><strong className="text-sm">{candidate.title}</strong><small className="mt-1 block text-xs text-gray-600">{candidate.detail}</small></span>
        </label>)}</div> : <p className="rounded-lg bg-gray-50 p-4 text-sm text-gray-600">当前没有可处理的项目。请刷新页面或先完成前置步骤。</p>}
        {(step === 'board_generate' || step === 'clip_generate') && <p className="mt-3 rounded-lg bg-amber-50 p-3 text-xs text-amber-900">生成任务只会对所选项目调用模型，请确认数量后提交。</p>}
      </div>
      <div className="flex justify-end gap-2 border-t px-5 py-4"><button type="button" className="rounded-lg border px-4 py-2 text-sm" onClick={onClose}>取消</button><button type="button" disabled={!selectedItems.length} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-40" onClick={() => onSubmit(selectedItems.map(candidate => candidate.item))}>提交 {selectedItems.length} 项</button></div>
    </div>
  </div>;
}
