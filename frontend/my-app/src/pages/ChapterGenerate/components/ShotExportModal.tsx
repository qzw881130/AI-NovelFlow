import { useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Download, Loader2, X } from 'lucide-react';

export const SHOT_EXPORT_OPTIONS = [
  { key: 'primary_image', label: '主分镜图', group: '图像' },
  { key: 'visual_states', label: '视觉状态图片', group: '图像' },
  { key: 'characters', label: '角色图片', group: '图像' },
  { key: 'scenes', label: '场景图片', group: '图像' },
  { key: 'props', label: '道具图片', group: '图像' },
  { key: 'clip_videos', label: 'Clip 视频片段', group: '视频' },
  { key: 'final_video', label: '最终 Shot 视频', group: '视频' },
  { key: 'reference_images', label: '生成时使用的参考图片', group: '生成资料' },
  { key: 'prompts', label: '实际生成提示词', group: '生成资料' },
  { key: 'workflows', label: 'ComfyUI 工作流', group: '生成资料' },
  { key: 'plan', label: '视觉状态描述与视频规划', group: '生成资料' },
] as const;

export function ShotExportModal({ shotIndex, onClose, onExport }: {
  shotIndex: number;
  onClose: () => void;
  onExport: (sections: string[]) => Promise<void>;
}) {
  const [selected, setSelected] = useState<Set<string>>(() => new Set(SHOT_EXPORT_OPTIONS.map(option => option.key)));
  const [packing, setPacking] = useState(false);
  const [error, setError] = useState('');
  const inFlight = useRef(false);
  const exportSelected = async () => {
    if (inFlight.current || selected.size === 0) return;
    inFlight.current = true;
    setPacking(true);
    setError('');
    try {
      await onExport(SHOT_EXPORT_OPTIONS.filter(option => selected.has(option.key)).map(option => option.key));
      onClose();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '导出失败，请重试');
    } finally {
      inFlight.current = false;
      setPacking(false);
    }
  };
  return createPortal(
    <div className="fixed inset-0 z-[150] flex items-center justify-center bg-black/50 p-4" onClick={event => { if (event.target === event.currentTarget && !packing) onClose(); }}>
      <section role="dialog" aria-modal="true" aria-label="导出 Shot 生产包" className="flex max-h-[85vh] w-full max-w-xl flex-col rounded-xl bg-white shadow-xl">
        <header className="flex items-center justify-between border-b p-4">
          <h2 className="text-lg font-semibold">导出 Shot {shotIndex} 生产包</h2>
          <button type="button" onClick={onClose} disabled={packing} aria-label="关闭导出窗口" className="rounded p-1 text-gray-500 hover:bg-gray-100 disabled:opacity-50"><X className="h-5 w-5" /></button>
        </header>
        <div className="space-y-4 overflow-y-auto p-4">
          <p className="text-sm text-gray-500">选择需要打包的内容。未生成或不可用的文件会跳过，ZIP 内会附带导出清单。</p>
          <div className="flex gap-4 text-sm">
            <button type="button" disabled={packing} onClick={() => setSelected(new Set(SHOT_EXPORT_OPTIONS.map(option => option.key)))} className="text-blue-600 disabled:opacity-50">全选</button>
            <button type="button" disabled={packing} onClick={() => setSelected(new Set())} className="text-gray-500 disabled:opacity-50">清空选择</button>
            <span className="ml-auto text-gray-500">已选择 {selected.size} 项</span>
          </div>
          {['图像', '视频', '生成资料'].map(group => <fieldset key={group} disabled={packing}>
            <legend className="mb-2 text-sm font-semibold text-gray-700">{group}</legend>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {SHOT_EXPORT_OPTIONS.filter(option => option.group === group).map(option => <label key={option.key} className="flex cursor-pointer items-center gap-2 rounded-lg border border-gray-200 px-3 py-2 text-sm hover:bg-gray-50">
                <input type="checkbox" checked={selected.has(option.key)} onChange={event => {
                  const checked = event.target.checked;
                  setSelected(previous => { const next = new Set(previous); if (checked) next.add(option.key); else next.delete(option.key); return next; });
                }} className="h-4 w-4 rounded border-gray-300 text-blue-600" />{option.label}
              </label>)}
            </div>
          </fieldset>)}
          {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
        </div>
        <footer className="flex justify-end gap-3 border-t p-4">
          <button type="button" disabled={packing} onClick={onClose} className="rounded-lg bg-gray-100 px-4 py-2 text-sm disabled:opacity-50">取消</button>
          <button type="button" disabled={packing || selected.size === 0} onClick={() => void exportSelected()} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white disabled:opacity-50">
            {packing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}{packing ? '打包中...' : '导出所选内容'}
          </button>
        </footer>
      </section>
    </div>, document.body,
  );
}
