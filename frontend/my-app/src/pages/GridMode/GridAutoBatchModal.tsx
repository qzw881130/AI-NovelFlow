import { useEffect, useState } from 'react';

type BatchShot = {
  id: string;
  index: number;
  description: string;
  videoUrl?: string;
  gridData?: { layout: string; board_prompt?: string; board_image_url?: string; panels: { review_status: string }[] };
  gridClipPlan?: { clip_plan: { video_url?: string }[] };
};

export function GridAutoBatchModal({ shots, mode, onClose, onSubmit }: {
  shots: BatchShot[];
  mode: 'board' | 'video';
  onClose: () => void;
  onSubmit: (shotIds: string[], mergeChapter: boolean) => void;
}) {
  const isBoard = mode === 'board';
  const eligible = shots.filter(shot => isBoard ? !shot.gridData?.board_image_url : !shot.videoUrl);
  const [selected, setSelected] = useState<string[]>(() => eligible.map(shot => shot.id));
  const [mergeChapter, setMergeChapter] = useState(false);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  const toggle = (id: string) => setSelected(rows => rows.includes(id) ? rows.filter(item => item !== id) : [...rows, id]);
  const state = (shot: BatchShot) => {
    if (isBoard) {
      if (shot.gridData?.board_image_url) return '宫格图已生成';
      if (shot.gridData?.board_prompt) return '整板提示词已准备，将继续生图';
      if (shot.gridData) return `已规划 ${shot.gridData.layout}，将准备整板提示词`;
      return '将从规划子格开始';
    }
    if (shot.videoUrl) return '当前 Shot 已完成';
    if (!shot.gridData) return '将从规划子格开始';
    if (!shot.gridData.board_image_url) return `已规划 ${shot.gridData.layout}，将继续生图`;
    const passed = shot.gridData.panels.filter(panel => panel.review_status === 'passed').length;
    if (passed < shot.gridData.panels.length) return `子格已通过 ${passed}/${shot.gridData.panels.length}，其余将由 AI 初审`;
    const clips = shot.gridClipPlan?.clip_plan || [];
    return clips.length ? `Clip 已生成 ${clips.filter(clip => clip.video_url).length}/${clips.length}，从未完成处继续` : '图片已审核，将规划 Clip';
  };

  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true" aria-label={isBoard ? '批量生成分镜宫格图' : '批量自动生成 Shot'}>
    <div className="flex max-h-[90vh] w-full max-w-3xl flex-col rounded-xl bg-white shadow-xl">
      <div className="border-b px-5 py-4"><div className="flex items-start justify-between gap-3"><div><h2 className="text-lg font-semibold">{isBoard ? '批量生成分镜宫格图' : '批量自动生成 Shot'}</h2><p className="mt-1 text-sm text-gray-600">{isBoard ? '按 Shot 顺序后台执行：规划子格 → 准备整板提示词 → 生成分镜宫格图。完成后可逐格检查，再进入视频生成。' : '按 Shot 顺序后台执行：规划子格 → 整板生图 → 逐格 AI 初审 → Clip 规划与六段式提示词 → H3 视频 → 合并 Shot。'}</p></div><button type="button" className="text-sm text-gray-500" onClick={onClose}>关闭</button></div></div>
      <div className="overflow-y-auto px-5 py-4">
        <div className="mb-3 flex items-center justify-between text-sm"><span>已选 {selected.length}/{eligible.length} 个待完成 Shot</span><button type="button" className="text-blue-700" onClick={() => setSelected(selected.length === eligible.length ? [] : eligible.map(shot => shot.id))}>{selected.length === eligible.length ? '取消全选' : '全选待完成'}</button></div>
        <div className="grid gap-2 sm:grid-cols-2">{shots.map(shot => <label key={shot.id} className={`flex gap-3 rounded-lg border p-3 ${!eligible.some(item => item.id === shot.id) ? 'bg-gray-50 opacity-60' : selected.includes(shot.id) ? 'border-blue-400 bg-blue-50' : 'border-gray-200'}`}>
          <input type="checkbox" className="mt-1" checked={selected.includes(shot.id)} disabled={!eligible.some(item => item.id === shot.id)} onChange={() => toggle(shot.id)} />
          <span><strong className="text-sm">Shot {shot.index} · {shot.description.split('｜')[0]}</strong><small className="mt-1 block text-xs text-gray-600">{state(shot)}</small></span>
        </label>)}</div>
        {!isBoard && <label className="mt-5 flex gap-3 rounded-lg border border-gray-200 p-3 text-sm"><input type="checkbox" checked={mergeChapter} onChange={event => setMergeChapter(event.target.checked)} /><span><strong>全部 Shot 完成后合并章回</strong><small className="mt-1 block text-gray-500">本章所有 Shot 都完成时执行；姓名牌沿用现有章回合并设置。</small></span></label>}
        <p className="mt-3 rounded-lg bg-amber-50 p-3 text-xs text-amber-900">{isBoard ? '已有宫格图的 Shot 不会重做。单个 Shot 生图失败时，其余 Shot 继续生成；完成后请逐格检查人物、道具和镜头质量。' : '只有 AI 初审明确 PASS 的子格才会自动通过。有疑点先自动重做一次；仍不通过则暂停该 Shot，继续处理其他 Shot。可在本页查看原因并重试。'}</p>
      </div>
      <div className="flex justify-end gap-2 border-t px-5 py-4"><button type="button" className="rounded-lg border px-4 py-2 text-sm" onClick={onClose}>取消</button><button type="button" disabled={!selected.length} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-40" onClick={() => onSubmit(selected, isBoard ? false : mergeChapter)}>{isBoard ? `生成 ${selected.length} 张宫格图` : `生成 ${selected.length} 个 Shot`}</button></div>
    </div>
  </div>;
}
