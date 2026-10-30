import { useEffect, useState } from 'react';
import type { LLMImageInput } from '../../../api/llmLogs';
import { toast } from '../../../stores/toastStore';

function text(value: unknown) {
  return typeof value === 'string' ? value.trim() : '';
}

function formatImageSize(bytes: number | undefined): string {
  if (typeof bytes !== 'number' || !Number.isSafeInteger(bytes) || bytes < 0) return '未知';
  if (bytes < 1024) return `${bytes} B`;
  const unit = bytes < 1024 * 1024 ? 'KB' : 'MB';
  const value = bytes / (unit === 'KB' ? 1024 : 1024 * 1024);
  return `${Number(value.toFixed(2))} ${unit}`;
}

// Parse only a display view. Original records, including JSON strings, stay intact.
function referenceObject(value: unknown): Record<string, unknown> {
  if (typeof value === 'string') {
    try { value = JSON.parse(value); } catch { return {}; }
  }
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : {};
}

export function imageInputSummary(item: LLMImageInput, index: number) {
  const data = item as LLMImageInput & Record<string, unknown>;
  const reference = referenceObject(data.reference);
  const binding = referenceObject(item.binding ?? reference.binding);
  const logicalId = text(item.logical_id);
  const picture = logicalId.match(/^<?Picture\s*(\d+)>?$/i);
  const number = binding.picture ?? reference.picture;
  const label = picture ? `Picture ${picture[1]}` : logicalId ||
    (number !== undefined && /^\d+$/.test(String(number)) ? `Picture ${number}` : `图片输入 ${index + 1}`);
  const referenceType = text(item.reference_type) || text(reference.reference_type) || 'IMAGE_INPUT';
  const sources = data.sources ?? binding.sources ?? reference.sources;
  const sourceList = Array.isArray(sources) ? sources.filter((value): value is string => typeof value === 'string') : [];
  const namedSources = sourceList
    .map(value => value.replace(/^(SCENE|PROP|CHAR):/, ''))
    .filter(value => !/^[0-9a-f]{8}-[0-9a-f-]{27,}$/i.test(value));
  const source = text(data.source_name) || text(reference.name) ||
    (sourceList.length > 0 && namedSources.length === sourceList.length ? namedSources.join('、') : '') ||
    (referenceType === 'CHARACTER_IDENTITY' && sourceList.length ? `角色身份参考 · ${sourceList.length} 个来源` : '') ||
    text(data.name) || (text(binding.filename) || text(item.source_path)).split(/[\\/]/).pop() || '未提供来源名称';
  const dimensions = item.source_dimensions;
  const sourceSize = Array.isArray(dimensions) && dimensions.length >= 2 && dimensions.slice(0, 2).every(value => Number.isFinite(value) && value > 0)
    ? `${dimensions[0]} × ${dimensions[1]}` : '未知';
  return { label, referenceType, source: source.length > 72 ? `${source.slice(0, 71)}…` : source, sourceSize,
    fileSize: formatImageSize(item.size_bytes) };
}

export function ImageInputs({ images }: { images: LLMImageInput[] }) {
  const [index, setIndex] = useState<number | null>(null);
  const [view, setView] = useState<'image' | 'metadata'>('image');
  const [failed, setFailed] = useState<Set<number>>(new Set());
  useEffect(() => { setIndex(null); setFailed(new Set()); }, [images]);
  useEffect(() => {
    if (index === null) return;
    const key = (event: KeyboardEvent) => {
      if (!['Escape', 'ArrowLeft', 'ArrowRight'].includes(event.key)) return;
      // Keep log-level Escape from closing the underlying log at the same time.
      event.stopPropagation();
      if (view === 'metadata' && event.key !== 'Escape') return;
      event.preventDefault();
      if (event.key === 'Escape') setIndex(null);
      else setIndex(current => current === null ? null : Math.max(0, Math.min(images.length - 1, current + (event.key === 'ArrowRight' ? 1 : -1))));
    };
    window.addEventListener('keydown', key, true);
    return () => window.removeEventListener('keydown', key, true);
  }, [index, images.length, view]);

  const open = (i: number, nextView: typeof view) => { setView(nextView); setIndex(i); };
  const unavailable = (i: number) => failed.has(i) || images[i].status === 'unavailable' || !images[i].submitted_url;
  const picture = (i: number, large = false) => unavailable(i)
    ? <div className="flex h-full min-h-[11rem] items-center justify-center p-4 text-center text-sm text-gray-500" role="status">
        <div><p>图片无法加载</p><p className="mt-1 max-h-20 overflow-auto break-all text-xs">{text(images[i].unavailable_reason) || '图片不可用或链接已失效'}</p></div>
      </div>
    : <img src={images[i].submitted_url!} alt={imageInputSummary(images[i], i).label}
        className={large ? 'max-h-[60vh] max-w-full object-contain mx-auto' : 'h-full w-full object-contain'}
        onError={() => setFailed(current => new Set([...current, i]))} />;

  const copyMetadata = async () => {
    if (index === null) return;
    const content = JSON.stringify(images[index], null, 2);
    try {
      if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(content);
      else {
        const textarea = document.createElement('textarea');
        textarea.value = content;
        textarea.style.position = 'fixed';
        textarea.style.left = '-9999px';
        document.body.appendChild(textarea);
        try {
          textarea.select();
          if (!document.execCommand('copy')) throw new Error('Clipboard unavailable');
        } finally { textarea.remove(); }
      }
      toast.success('已复制完整 JSON');
    } catch { toast.error('复制失败，请选中原始信息手动复制'); }
  };
  const selected = index !== null && images[index] ? imageInputSummary(images[index], index) : null;

  return <>
    <div data-testid="image-input-grid" className="grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {images.map((item, i) => {
        const summary = imageInputSummary(item, i);
        return <article key={`${i}-${item.request_order}-${item.logical_id}`} data-testid="image-input-card" className="flex min-w-0 flex-col overflow-hidden rounded-lg border border-gray-200 bg-white">
          <div className="flex min-h-[76px] flex-col items-start gap-1 px-3 py-2.5">
            <h4 className="max-w-full truncate text-sm font-semibold text-gray-900">{summary.label}</h4>
            <span className="max-w-full truncate rounded bg-blue-50 px-2 py-0.5 text-xs text-blue-700" title={summary.referenceType}>{summary.referenceType}</span>
          </div>
          <button type="button" onClick={() => open(i, 'image')} className="mx-3 h-44 shrink-0 overflow-hidden rounded bg-gray-50 focus-visible:outline-blue-500" aria-label={`查看图片 ${i + 1} ${text(item.logical_id)}`}>
            {picture(i)}
          </button>
          <div className="min-w-0 flex-1 px-3 py-3 text-xs text-gray-600">
            <p className="line-clamp-2 min-h-[2rem] break-words leading-4" title={summary.source}>{summary.source}</p>
            <p className="mt-1">原图尺寸：{summary.sourceSize}</p>
            <p className="mt-1">文件大小：{summary.fileSize}</p>
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-gray-100 px-3 py-2.5 text-xs">
            <button type="button" onClick={() => open(i, 'image')} className="text-blue-600 hover:underline">查看大图</button>
            <button type="button" onClick={() => open(i, 'metadata')} className="text-gray-600 hover:text-blue-600 hover:underline">查看原始信息</button>
          </div>
        </article>;
      })}
    </div>
    {index !== null && selected && <div className="fixed inset-0 z-[70] bg-black/80 p-3 sm:p-5 flex items-center justify-center" role="dialog" aria-modal="true" aria-label={view === 'image' ? '图片预览' : '图片原始信息'} onClick={() => setIndex(null)}>
      <div className="flex max-h-[90vh] w-full min-w-0 max-w-5xl flex-col overflow-hidden rounded-lg bg-white" onClick={event => event.stopPropagation()}>
        <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b p-3 text-sm">
          <span className="min-w-0 break-words font-medium">{selected.label} · {view === 'image' ? '图片预览' : '原始信息'}</span>
          <div className="flex items-center gap-2">
            <button type="button" onClick={() => setIndex(i => Math.max(0, (i || 0) - 1))} disabled={index === 0} className="disabled:opacity-40 px-2 py-1">上一张</button>
            <span aria-live="polite">{index + 1} / {images.length}</span>
            <button type="button" onClick={() => setIndex(i => Math.min(images.length - 1, (i || 0) + 1))} disabled={index === images.length - 1} className="disabled:opacity-40 px-2 py-1">下一张</button>
            <button type="button" onClick={() => setIndex(null)} aria-label={view === 'image' ? '关闭图片预览' : '关闭原始信息'} className="px-2 py-1">关闭 (Esc)</button>
          </div>
        </div>
        {view === 'metadata' ? <>
          <div className="flex shrink-0 items-center justify-between gap-2 px-4 py-3 text-xs text-gray-500">
            <span>完整原始记录（保留原字段与字符串）</span>
            <button type="button" onClick={copyMetadata} className="shrink-0 rounded border border-gray-200 px-3 py-1.5 text-blue-600 hover:bg-blue-50">复制完整 JSON</button>
          </div>
          <pre tabIndex={0} className="min-h-0 min-w-0 flex-1 overflow-auto whitespace-pre-wrap break-all bg-gray-50 p-4 text-xs leading-relaxed text-gray-700">{JSON.stringify(images[index], null, 2)}</pre>
        </> : <div className="min-h-0 overflow-auto p-4">
          {picture(index, true)}
          <div className="mt-3 space-y-1 break-words text-xs text-gray-600"><p>{selected.referenceType} · {selected.source}</p><p>原图尺寸：{selected.sourceSize}</p><p>文件大小：{selected.fileSize}</p></div>
        </div>}
      </div>
    </div>}
  </>;
}
