import { useEffect, useId, useRef, useState } from 'react';
import { ChevronDown, Download, Loader2 } from 'lucide-react';
import { chapterApi } from '../../../api/chapters';
import { toast } from '../../../stores/toastStore';

export function SubtitleExportMenu({ novelId, chapterId, chapterTitle }: {
  novelId: string;
  chapterId: string;
  chapterTitle: string;
}) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const pending = useRef(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const items = useRef<Array<HTMLButtonElement | null>>([]);
  const initialFocus = useRef(0);
  const id = useId();

  useEffect(() => {
    if (!open) return;
    items.current[initialFocus.current]?.focus();
    const dismiss = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', dismiss);
    return () => document.removeEventListener('pointerdown', dismiss);
  }, [open]);

  const download = async (format: 'srt' | 'ass') => {
    if (pending.current) return;
    pending.current = true;
    setLoading(true);
    setOpen(false);
    trigger.current?.focus();
    try {
      const { blob, filename } = await chapterApi.downloadSubtitles(novelId, chapterId, format);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      try {
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
      } finally {
        link.remove();
        // Allow the browser to start consuming the blob before releasing it.
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
      toast.success(`「${chapterTitle}」${format.toUpperCase()} 成片字幕已开始下载`);
    } catch (error) {
      toast.error(error instanceof TypeError ? '字幕下载失败，请检查网络连接后重试' : error instanceof Error ? error.message : '字幕导出失败，请稍后重试');
    } finally {
      pending.current = false;
      setLoading(false);
    }
  };

  return (
    <div ref={root} className="relative min-w-0" onBlur={(event) => {
      if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
    }} onKeyDown={(event) => {
      if (event.key === 'Escape' && open) {
        event.preventDefault();
        event.stopPropagation();
        setOpen(false);
        trigger.current?.focus();
      }
    }}>
      <button ref={trigger} id={`${id}-trigger`} type="button"
        aria-haspopup="menu" aria-expanded={open} aria-controls={open ? `${id}-menu` : undefined}
        aria-label={`导出成片字幕：${chapterTitle}`} aria-disabled={loading} aria-busy={loading}
        title="按章节合并成片的实际时间轴导出字幕；仅支持 AudioDrive，需成片与渲染时间轴及音频快照元数据匹配"
        className="btn-secondary min-h-[44px] w-full text-sm py-1.5 px-3 xl:min-h-0 focus-visible:ring-2 focus-visible:ring-primary-500 aria-disabled:opacity-50 aria-disabled:cursor-wait"
        onClick={() => {
          if (pending.current) return;
          initialFocus.current = 0;
          setOpen(!open);
        }}
        onKeyDown={(event) => {
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            if (pending.current) return;
            initialFocus.current = event.key === 'ArrowUp' ? 1 : 0;
            setOpen(true);
          }
        }}>
        {loading ? <Loader2 aria-hidden="true" className="h-3 w-3 mr-1 animate-spin" /> : <Download aria-hidden="true" className="h-3 w-3 mr-1" />}
        <span role="status">{loading ? '正在导出...' : '导出成片字幕'}</span>
        <ChevronDown aria-hidden="true" className="ml-1 h-3 w-3" />
      </button>
      {open && (
        <div id={`${id}-menu`} role="menu" aria-labelledby={`${id}-trigger`} aria-describedby={`${id}-hint`}
          className="absolute right-0 z-30 mt-1 w-44 max-w-[calc(100vw-2rem)] rounded-lg border border-gray-200 bg-white p-1 shadow-lg"
          onKeyDown={(event) => {
            const index = items.current.indexOf(document.activeElement as HTMLButtonElement);
            let next: number;
            if (event.key === 'ArrowDown') next = (index + 1) % 2;
            else if (event.key === 'ArrowUp') next = (index + 1) % 2;
            else if (event.key === 'Home') next = 0;
            else if (event.key === 'End') next = 1;
            else return;
            event.preventDefault();
            items.current[next]?.focus();
          }}>
          <p id={`${id}-hint`} role="presentation" className="px-3 py-2 text-xs text-gray-500">仅支持 AudioDrive，按章节合并成片的实际时间轴导出。需已有成片及匹配的渲染时间轴、音频快照元数据；缺失或不匹配时，请按错误提示重新生成或合并，不会回退到逻辑音频时间轴。</p>
          {(['srt', 'ass'] as const).map((format, index) => (
            <button key={format} ref={(element) => { items.current[index] = element; }}
              type="button" role="menuitem" tabIndex={-1} onClick={() => download(format)}
              className="flex min-h-[44px] w-full items-center rounded-md px-3 py-2 text-left text-sm text-gray-700 hover:bg-gray-100 focus:bg-primary-50 focus:text-primary-700 focus:outline-none">
              {format.toUpperCase()}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
