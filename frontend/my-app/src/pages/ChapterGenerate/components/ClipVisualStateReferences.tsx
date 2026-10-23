import { useState } from 'react';
import { shotsApi, type SemanticClipPlan, type Shot } from '../../../api/shots';
import { clipVisualStateOptions } from '../clipVisualStateReferences';

export function ClipVisualStateReferences({ shot, clip, novelId, chapterId, disabled, onShot, onSaving }: {
  shot: Shot; clip: SemanticClipPlan; novelId?: string; chapterId?: string; disabled?: boolean;
  onShot: (shot: Shot) => void; onSaving: (saving: boolean) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const options = clipVisualStateOptions(clip);
  const enabled = options.filter(s => s.enabled).map(s => s.id);
  const locked = busy || disabled || !novelId || !chapterId;
  const save = async (ids: string[]) => {
    if (locked || !novelId || !chapterId) return;
    setBusy(true); onSaving(true); setError('');
    try {
      const response = await shotsApi.saveClipVisualStateReferences(novelId, chapterId, shot.id,
        clip.clip_index, ids, Number(shot.videoDirectorPlan?.clip_plan_revision || 0));
      if (!response.success || !response.data) throw new Error(response.message || '保存视觉状态选择失败');
      onShot(response.data);
    } catch (e) { setError(e instanceof Error ? e.message : '保存视觉状态选择失败'); }
    finally { setBusy(false); onSaving(false); }
  };
  return <div data-testid="clip-visual-state-references" className="flex flex-wrap items-center gap-2 text-[11px] text-gray-600">
    <span>视觉状态：</span>
    {options.length === 0 && <span>无</span>}
    {options.map(state => <label key={state.id} className="inline-flex items-center gap-1" title={`视觉状态 ${state.index} 的图片参与此片段生成`}>
      <input type="checkbox" aria-label={`视觉状态 ${state.index}`} checked={state.enabled} disabled={locked}
        onChange={e => save(options.filter(s => s.id === state.id ? e.target.checked : s.enabled).map(s => s.id))} />
      {state.index}
    </label>)}
    <span>已启用 {enabled.length}/{options.length}</span>
    {options.length > 0 && <>
      <button type="button" className="text-blue-600 disabled:opacity-40" disabled={locked || enabled.length === options.length} onClick={() => save(options.map(s => s.id))}>全部启用</button>
      <button type="button" className="text-blue-600 disabled:opacity-40" disabled={locked || enabled.length === 0} onClick={() => save([])}>全部禁用</button>
    </>}
    {busy && <span role="status">保存中…</span>}
    {error && <span role="alert" className="text-red-600">{error}</span>}
  </div>;
}
