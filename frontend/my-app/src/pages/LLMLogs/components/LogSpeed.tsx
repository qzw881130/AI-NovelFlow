import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Gauge } from 'lucide-react';
import type { LLMLog } from '../../../api/llmLogs';
import { useTranslation } from '../../../stores/i18nStore';

export function LogSpeed({ log }: { log: LLMLog }) {
  const { t } = useTranslation();
  const id = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const card = useRef<HTMLDivElement>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout>>();
  const pinned = useRef(false);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ top: 0, left: 0 });
  const metrics = log.metrics;
  const speed = metrics?.output_tokens_per_second;
  const speedText = typeof speed === 'number' && Number.isFinite(speed) && speed >= 0
    ? `${speed.toFixed(2)} t/s`
    : '-';

  const show = () => {
    clearTimeout(closeTimer.current);
    setOpen(true);
  };
  const dismiss = () => {
    clearTimeout(closeTimer.current);
    pinned.current = false;
    setOpen(false);
  };
  const scheduleClose = () => {
    clearTimeout(closeTimer.current);
    closeTimer.current = setTimeout(() => {
      if (!pinned.current && document.activeElement !== trigger.current) setOpen(false);
    }, 150);
  };

  useEffect(() => () => clearTimeout(closeTimer.current), []);

  useLayoutEffect(() => {
    if (!open || !trigger.current || !card.current) return;
    const anchor = trigger.current.getBoundingClientRect();
    const bounds = card.current.getBoundingClientRect();
    setPosition({
      left: Math.max(8, Math.min(anchor.left, window.innerWidth - bounds.width - 8)),
      top: Math.max(8, Math.min(
        anchor.bottom + bounds.height + 8 <= window.innerHeight ? anchor.bottom + 4 : anchor.top - bounds.height - 4,
        window.innerHeight - bounds.height - 8,
      )),
    });
  }, [open, log, t]);

  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      if (!trigger.current?.contains(event.target as Node) && !card.current?.contains(event.target as Node)) dismiss();
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') dismiss();
    };
    document.addEventListener('pointerdown', outside);
    document.addEventListener('keydown', escape, true);
    window.addEventListener('resize', dismiss);
    return () => {
      document.removeEventListener('pointerdown', outside);
      document.removeEventListener('keydown', escape, true);
      window.removeEventListener('resize', dismiss);
    };
  }, [open]);

  const details = [
    [t('llmLogs.inputTokens'), metrics?.input_tokens ?? '-'],
    [t('llmLogs.outputTokens'), metrics?.output_tokens ?? '-'],
    [t('llmLogs.totalTokens'), metrics?.total_tokens ?? '-'],
    [t('llmLogs.duration'), log.duration == null ? '-' : `${log.duration.toFixed(2)}s`],
    [t('llmLogs.averageOutputThroughput'), speedText],
    [t('llmLogs.cachedInputTokens'), metrics?.cached_input_tokens ?? '-'],
    [t('llmLogs.reasoningTokens'), metrics?.reasoning_tokens ?? '-'],
    [t('llmLogs.finishReason'), metrics?.finish_reason ?? '-'],
  ];

  return (
    <>
      <button
        ref={trigger}
        type="button"
        aria-label={`${t('llmLogs.tokenDetails')}: ${speedText}`}
        aria-describedby={open ? id : undefined}
        aria-expanded={open}
        onPointerEnter={(event) => { if (event.pointerType !== 'touch') show(); }}
        onPointerLeave={scheduleClose}
        onFocus={show}
        onBlur={() => { if (!pinned.current) scheduleClose(); }}
        onClick={() => {
          if (pinned.current) dismiss();
          else {
            pinned.current = true;
            show();
          }
        }}
        className="inline-flex min-h-9 items-center gap-1.5 whitespace-nowrap rounded px-1 text-left tabular-nums hover:text-primary-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500"
      >
        <Gauge className="h-4 w-4 shrink-0" aria-hidden="true" />
        {speedText}
      </button>
      {open && createPortal(
        <div
          ref={card}
          id={id}
          role="tooltip"
          onPointerEnter={show}
          onPointerLeave={scheduleClose}
          style={position}
          className="fixed z-[300] w-80 max-w-[calc(100vw-16px)] max-h-[calc(100dvh-16px)] overflow-y-auto whitespace-normal rounded-lg border border-gray-200 bg-white p-4 text-sm text-gray-700 shadow-lg"
        >
          <p className="mb-3 font-semibold text-gray-900">{t('llmLogs.tokenDetails')}</p>
          <dl className="space-y-2">
            {details.map(([label, value]) => (
              <div key={label} className="flex justify-between gap-4">
                <dt className="min-w-0 text-gray-500">{label}</dt>
                <dd className="max-w-[55%] break-words text-right font-medium tabular-nums">{value}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-3 border-t border-gray-100 pt-3 text-xs text-gray-500">{t('llmLogs.throughputExplanation')}</p>
        </div>,
        document.body,
      )}
    </>
  );
}
