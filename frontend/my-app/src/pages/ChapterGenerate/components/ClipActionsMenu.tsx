import { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ChevronDown } from 'lucide-react';

/** Keep the existing actions mounted; the portal escapes the Clip strip's overflow. */
export function ClipActionsMenu({ clipIndex, children }: { clipIndex: number; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ left: 0, top: 0, maxHeight: 300 });
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const id = useId();
  useEffect(() => {
    if (!open) return;
    const place = () => {
      const rect = trigger.current?.getBoundingClientRect();
      if (!rect) return;
      const height = Math.min(panel.current?.scrollHeight || 240, window.innerHeight - 16);
      const below = window.innerHeight - rect.bottom - 12;
      const above = rect.top - 12;
      const useAbove = below < height && above > below;
      setPosition({ left: Math.max(8, Math.min(rect.left, window.innerWidth - 272)),
        top: useAbove ? Math.max(8, rect.top - height - 4) : rect.bottom + 4,
        maxHeight: Math.max(80, useAbove ? above : below) });
    };
    const outside = (event: PointerEvent) => {
      if (!trigger.current?.contains(event.target as Node) && !panel.current?.contains(event.target as Node)) setOpen(false);
    };
    place();
    panel.current?.querySelector<HTMLElement>('button:not(:disabled), a[href]')?.focus();
    document.addEventListener('pointerdown', outside);
    window.addEventListener('resize', place);
    window.addEventListener('scroll', place, true);
    return () => {
      document.removeEventListener('pointerdown', outside);
      window.removeEventListener('resize', place);
      window.removeEventListener('scroll', place, true);
    };
  }, [open]);
  return <>
    <button ref={trigger} type="button" aria-label={`C${clipIndex} 操作`} aria-expanded={open} aria-controls={id}
      onClick={() => setOpen(value => !value)}
      className="inline-flex items-center gap-1 rounded border border-blue-200 px-2.5 py-1 text-[11px] font-medium text-blue-700 hover:bg-blue-50">
      操作 <ChevronDown className="h-3 w-3" />
    </button>
    {typeof document !== 'undefined' && createPortal(<div id={id} ref={panel} role="group" aria-label={`C${clipIndex} 操作列表`}
      style={{ ...position, display: open ? undefined : 'none' }}
      onKeyDown={event => { if (event.key === 'Escape') { event.preventDefault(); setOpen(false); trigger.current?.focus(); } }}
      onClick={event => {
        const target = event.target as HTMLElement;
        // Playback can fail asynchronously; leave its existing error feedback visible.
        if (!target.closest('[data-testid="clip-dual-playback"]') && target.closest('button:not(:disabled), a[href]')) setOpen(false);
      }}
      className="fixed z-[200] w-64 max-w-[calc(100vw-1rem)] overflow-y-auto rounded-lg border border-gray-200 bg-white p-1.5 shadow-lg [&_a]:block [&_a]:w-full [&_a]:rounded [&_a]:border-0 [&_a]:px-3 [&_a]:py-2 [&_button]:w-full [&_button]:rounded [&_button]:border-0 [&_button]:px-3 [&_button]:py-2 [&_button]:text-left [&_button]:hover:bg-gray-50 [&_[data-testid=clip-dual-playback]]:flex-col [&_[data-testid=clip-dual-playback]]:items-stretch [&_[data-testid=clip-dual-playback]]:gap-0">
      {children}
    </div>, document.body)}
  </>;
}
