import { useEffect, useState } from 'react';

type ReviewShot = {
  id: string;
  index: number;
  description: string;
  gridData?: { board_image_url?: string; panels: { image_url?: string; review_status: string }[] };
};

export function GridReviewPassModal({ shots, onClose, onSubmit }: {
  shots: ReviewShot[];
  onClose: () => void;
  onSubmit: (shotIds: string[]) => void;
}) {
  const eligible = shots.filter(shot => shot.gridData?.board_image_url
    && shot.gridData.panels.length > 0
    && shot.gridData.panels.every(panel => panel.image_url)
    && shot.gridData.panels.some(panel => panel.review_status !== 'passed'));
  const eligibleIds = eligible.map(shot => shot.id);
  const [selected, setSelected] = useState<string[]>(eligibleIds);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  const toggle = (id: string) => setSelected(rows => rows.includes(id) ? rows.filter(item => item !== id) : [...rows, id]);
  const selectedPanels = eligible.filter(shot => selected.includes(shot.id))
    .reduce((total, shot) => total + shot.gridData!.panels.filter(panel => panel.review_status !== 'passed').length, 0);

  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true" aria-label="批量审核通过">
    <div className="flex max-h-[90vh] w-full max-w-3xl flex-col rounded-xl bg-white shadow-xl">
      <div className="border-b px-5 py-4"><div className="flex items-start justify-between gap-3"><div><h2 className="text-lg font-semibold">批量审核通过</h2><p className="mt-1 text-sm text-gray-600">选择 Shot，将其中尚未通过的子格直接标记为人工审核通过。</p></div><button type="button" className="text-sm text-gray-500" onClick={onClose}>关闭</button></div></div>
      <div className="overflow-y-auto px-5 py-4">
        <div className="mb-3 flex items-center justify-between text-sm"><span>已选 {selected.length}/{eligible.length} 个 Shot · 待通过 {selectedPanels} 格</span><button type="button" className="text-blue-700" onClick={() => setSelected(selected.length === eligible.length ? [] : eligibleIds)}>{selected.length === eligible.length ? '取消全选' : '全选待审核'}</button></div>
        <div className="grid gap-2 sm:grid-cols-2">{shots.map(shot => {
          const canSelect = eligibleIds.includes(shot.id);
          const panels = shot.gridData?.panels || [];
          const passed = panels.filter(panel => panel.review_status === 'passed').length;
          const state = !shot.gridData?.board_image_url ? '尚无宫格整板图' : panels.some(panel => !panel.image_url) ? '子格图片不完整' : passed === panels.length ? '子格全部已通过' : `已通过 ${passed}/${panels.length} 格`;
          return <label key={shot.id} className={`flex gap-3 rounded-lg border p-3 ${!canSelect ? 'bg-gray-50 opacity-60' : selected.includes(shot.id) ? 'border-blue-400 bg-blue-50' : 'border-gray-200'}`}>
            <input type="checkbox" className="mt-1" checked={selected.includes(shot.id)} disabled={!canSelect} onChange={() => toggle(shot.id)} />
            <span><strong className="text-sm">Shot {shot.index} · {shot.description.split('｜')[0]}</strong><small className="mt-1 block text-xs text-gray-600">{state}</small></span>
          </label>;
        })}</div>
        <p className="mt-3 rounded-lg bg-amber-50 p-3 text-xs text-amber-900">此操作跳过 AI 审图，适用于你已亲自核对画面、人物、道具与镜头连续性的 Shot。原先已通过的子格及备注不会被改动。</p>
      </div>
      <div className="flex justify-end gap-2 border-t px-5 py-4"><button type="button" className="rounded-lg border px-4 py-2 text-sm" onClick={onClose}>取消</button><button type="button" disabled={!selected.length} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-40" onClick={() => onSubmit(selected)}>审核通过 {selected.length} 个 Shot · {selectedPanels} 格</button></div>
    </div>
  </div>;
}
