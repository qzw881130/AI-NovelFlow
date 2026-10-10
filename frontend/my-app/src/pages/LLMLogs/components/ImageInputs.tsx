import { useEffect, useState } from 'react';
import type { LLMImageInput } from '../../../api/llmLogs';

export function ImageInputs({ images }: { images: LLMImageInput[] }) {
  const [index, setIndex] = useState<number | null>(null);
  const [failed, setFailed] = useState<Set<number>>(new Set());
  useEffect(() => { setIndex(null); setFailed(new Set()); }, [images]);
  useEffect(() => {
    if (index === null) return;
    const key = (event: KeyboardEvent) => {
      if (!['Escape', 'ArrowLeft', 'ArrowRight'].includes(event.key)) return;
      event.preventDefault(); event.stopPropagation();
      if (event.key === 'Escape') setIndex(null);
      else setIndex(current => current === null ? null : Math.max(0, Math.min(images.length - 1, current + (event.key === 'ArrowRight' ? 1 : -1))));
    };
    window.addEventListener('keydown', key, true);
    return () => window.removeEventListener('keydown', key, true);
  }, [index, images.length]);
  const unavailable = (i: number) => failed.has(i) || images[i].status === 'unavailable' || !images[i].submitted_url;
  const picture = (i: number, large = false) => unavailable(i)
    ? <div className="flex h-40 items-center justify-center text-sm text-gray-500" role="status">Unavailable · {images[i].unavailable_reason || '图片无法加载'}</div>
    : <img src={images[i].submitted_url!} alt={images[i].logical_id} className={large ? 'max-h-[65vh] max-w-full object-contain mx-auto' : 'h-40 w-full object-contain'} onError={() => setFailed(current => new Set([...current, i]))} />;
  const info = (i: number) => <div className="text-xs space-y-1 break-words">
    <div className="font-medium">{images[i].logical_id} · {images[i].reference_type || 'IMAGE_INPUT'}</div>
    <div>{images[i].role || '-'} · {images[i].binding || '-'}</div>
    <div>提交尺寸 {images[i].submitted_dimensions?.join(' × ') || '未知'} · {images[i].mime_type || '-'} · {images[i].is_proxy ? 'Vision Proxy' : '提交图片'}</div>
    <div>源尺寸 {images[i].source_dimensions?.join(' × ') || '未知'}</div>
  </div>;
  return <>
    <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
      {images.map((item, i) => <button key={`${item.request_order}-${item.logical_id}`} type="button" onClick={() => setIndex(i)} className="rounded border p-2 text-left hover:border-blue-500" aria-label={`查看图片 ${i + 1} ${item.logical_id}`}>
        {picture(i)}{info(i)}
      </button>)}
    </div>
    {index !== null && <div className="fixed inset-0 z-[70] bg-black/80 p-5 flex items-center justify-center" role="dialog" aria-modal="true" aria-label="图片预览" onClick={() => setIndex(null)}>
      <div className="bg-white rounded-lg w-full max-w-5xl p-4" onClick={event => event.stopPropagation()}>
        <div className="flex items-center justify-between mb-3">
          <button type="button" onClick={() => setIndex(i => Math.max(0, (i || 0) - 1))} disabled={index === 0} className="disabled:opacity-40 px-3 py-1">上一张</button>
          <span aria-live="polite">{index + 1} / {images.length}</span>
          <button type="button" onClick={() => setIndex(i => Math.min(images.length - 1, (i || 0) + 1))} disabled={index === images.length - 1} className="disabled:opacity-40 px-3 py-1">下一张</button>
          <button type="button" onClick={() => setIndex(null)} aria-label="关闭图片预览" className="px-3 py-1">关闭 (Esc)</button>
        </div>
        {picture(index, true)}<div className="mt-3">{info(index)}</div>
      </div>
    </div>}
  </>;
}
