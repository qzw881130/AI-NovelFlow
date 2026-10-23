import { useState, useEffect, useRef } from 'react';
import type { VideoAiCall } from '../api/shots';
import type { Task } from '../api/tasks';
import { H3AVTimeline } from './H3AVTimeline';
import { phaseBSummary, phaseBActualVideo } from './h3PhaseBPresentation';

const seconds = (n: unknown) => typeof n === 'number' && Number.isFinite(n) ? `${n.toFixed(2)}s` : '—';
const preClass = 'max-w-full overflow-x-auto whitespace-pre-wrap break-words text-xs';

export function H3PhaseBDetails({ record, actual }: { record: any; actual?: { seconds?: number; label: string } }) {
  const result = record?.compiler_result;
  const decisions = result?.execution_decisions;
  const catalog = decisions?.anchor_catalog || [];
  const stats = phaseBSummary(record);
  const timeline = decisions && { ...decisions.timing,
    original_duration: record.director_input?.execution_budget?.story_duration,
    duration_delta: decisions.duration_delta,
    anchors: (decisions.anchor_decisions || []).map((a: any) => ({ ...a,
      source_picture: catalog.find((c: any) => c.anchor_id === a.id)?.source_picture,
      source_kind: catalog.find((c: any) => c.anchor_id === a.id)?.source_kind,
    })),
  };
  return <div className="min-w-0 space-y-4 text-sm" data-testid="phase-b-planning-details">
    <p>计划生成时长：{seconds(stats.duration)} · 参考图：{stats.pictures ?? '—'}{stats.temporal ? ` + ${stats.temporal} Temporal` : ''} · Dialogue：{stats.dialogues ?? '—'} · Warning：{stats.warnings.length} / Error：{stats.errors.length}</p>
    {actual && typeof actual.seconds === 'number' && <p>{actual.label}：{seconds(actual.seconds)}</p>}
    <p>{record.version} · 模板 {record.template?.name} · {record.template?.id}</p>
    <p>结构与权威事实：{record.preflight?.passed ? '通过' : '未通过或尚未完成'}；实际提交绑定：{record.submission_preflight?.passed ? '通过' : '未确认'}。导演语义与视频质量需审阅。</p>
    {!!stats.errors.length && <p role="alert" className="break-words font-medium text-red-700">执行阻塞：{record.error || stats.errors.join('；')}</p>}
    <details><summary>Warning / Error</summary><pre className={preClass}>{JSON.stringify({ warnings: stats.warnings, errors: stats.errors }, null, 2)}</pre></details>
    {record.reuse && <p>复用匹配输入与模板版本的导演结果，已重新编译。</p>}
    <details open><summary>最终 H3 Prompt</summary><pre className={preClass}>{result?.prompt || '编译尚未成功，未产生最终 Prompt'}</pre></details>
    <details><summary>Reference Manifest / Picture / Temporal 引用（与 Canonical 状态分开）</summary>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3">{[...(result?.reference_manifest?.references || []), ...(result?.temporal_manifest?.anchors || [])].map((r: any, i: number) => <figure className="min-w-0" key={r.picture || r.anchor_id || i}>
        <figcaption className="break-words">{r.picture || r.anchor_id} · {r.kind || 'TEMPORAL_ANCHOR'} · {r.source_name}</figcaption>
        {r.image_url && <a href={r.image_url} target="_blank" rel="noreferrer"><img loading="lazy" className="max-h-36 object-contain" src={r.image_url} alt={r.picture || r.anchor_id || '参考图'} /></a>}
      </figure>)}</div>
      <pre className={preClass}>{JSON.stringify({ ordinary: result?.reference_manifest, temporal: result?.temporal_manifest }, null, 2)}</pre>
    </details>
    <H3AVTimeline timeline={timeline} variant="phase_b" />
    <details><summary>原始 #13 规划</summary><pre className={preClass}>{record.raw_response}</pre></details>
    <details><summary>Compiler diagnostics</summary><pre className={preClass}>{JSON.stringify({ status: result?.status, review: result?.review, picture_audit: result?.picture_audit, continuation_checks: result?.continuation_checks }, null, 2)}</pre></details>
    <details><summary>Preflight 与原始 native diagnostics</summary><pre className={preClass}>{JSON.stringify({ preflight: record.preflight, submission: record.submission_preflight }, null, 2)}</pre></details>
    <details><summary>时间域换算 / Previous AV</summary><pre className={preClass}>{JSON.stringify({ continuation: record.continuation, execution: decisions, execution_budget: record.director_input?.execution_budget }, null, 2)}</pre></details>
  </div>;
}

export function H3PhaseBResult({ record: supplied, call, loadCall, task, actualVideo, compact = false, contextSummary }: {
  record?: any; call?: VideoAiCall; loadCall?: (call: VideoAiCall) => Promise<VideoAiCall>;
  task?: Task; actualVideo?: { seconds?: number; label: string };
  compact?: boolean; contextSummary?: string;
}) {
  const callKey = call ? `${call.task_id}:${call.history_index}:${call.created_at}:${call.status}` : '';
  const [loaded, setLoaded] = useState<{ key: string; value: VideoAiCall }>();
  const [error, setError] = useState<{ key: string; message: string }>();
  const [retry, setRetry] = useState(0);
  const [open, setOpen] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const openerButton = useRef<HTMLButtonElement>(null);
  const record = supplied || call?.parsed_result || (loaded?.key === callKey ? loaded.value.parsed_result : undefined);
  const hasSuppliedRecord = !!supplied;
  useEffect(() => {
    let cancelled = false;
    if (!supplied && !call?.parsed_result && call && loadCall) {
      setError(undefined);
      void loadCall(call).then(value => { if (!cancelled) setLoaded({ key: callKey, value }); })
        .catch(e => { if (!cancelled) setError({ key: callKey, message: String(e) }); });
    }
    return () => { cancelled = true; };
  }, [callKey, hasSuppliedRecord, retry]);
  useEffect(() => { setOpen(false); }, [callKey, supplied?.clip_index]);
  useEffect(() => {
    if (!open || !dialog.current) return;
    const element = dialog.current;
    const opener = openerButton.current;
    // Native top layer escapes ancestors' overflow/transform and traps focus.
    // Restore focus explicitly because React removes the dialog on close.
    element.showModal();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      element.close();
      document.body.style.overflow = previousOverflow;
      if (opener?.isConnected) opener.focus();
    };
  }, [open]);
  if (!record && !call) return null;
  const stats = phaseBSummary(record);
  const title = `Phase B · C${record?.clip_index ?? call?.clip_index ?? '—'} · ${record?.status || call?.status || '读取中'} · ${seconds(stats.duration)}`;
  return <section className={compact ? 'min-w-0 max-w-full text-xs' : 'my-2 text-sm'} data-testid="h3-phase-b-result">
    <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
      <p className="min-w-0 break-words font-medium text-gray-600" data-testid="phase-b-summary">{title}</p>
      {!!stats.errors.length && compact && <span role="status" className="rounded border border-red-200 bg-red-50 px-1.5 py-0.5 font-medium text-red-700">规划失败</span>}
      <button ref={openerButton} type="button" className="shrink-0 text-violet-800 underline" aria-haspopup="dialog" onClick={() => setOpen(true)}>查看规划详情</button>
    </div>
    {!!stats.errors.length && !compact && <p role="alert" className="break-words font-medium text-red-700">执行阻塞：{record?.error || stats.errors.join('；')}</p>}
    {open && <dialog ref={dialog} aria-label={`${title} 规划详情`} aria-modal="true" onCancel={() => setOpen(false)} onClose={() => setOpen(false)}
      onClick={e => { if (e.target === e.currentTarget) setOpen(false); }}
      className="m-auto h-[90dvh] max-h-[90dvh] w-[calc(100%-2rem)] max-w-6xl overflow-hidden rounded-xl border-0 bg-white p-0 shadow-xl backdrop:bg-black/50">
      <div className="flex h-full min-h-0 flex-col">
        <header className="flex shrink-0 items-center justify-between gap-3 border-b px-5 py-4">
          <h3 className="font-semibold">{title} 规划详情</h3>
          <button type="button" autoFocus aria-label="关闭规划详情" onClick={() => setOpen(false)} className="shrink-0 rounded px-3 py-1 hover:bg-gray-100">关闭</button>
        </header>
        <div tabIndex={0} aria-label="规划详情滚动区域" className="min-h-0 min-w-0 flex-1 overflow-y-auto overscroll-contain p-5" data-testid="phase-b-modal-scroll">
          {contextSummary && <p className="mb-3 text-sm text-gray-600">{contextSummary}</p>}
          {record ? <H3PhaseBDetails record={record} actual={actualVideo || phaseBActualVideo(task)} />
            : error?.key === callKey ? <p role="alert">读取失败：{error.message} <button type="button" className="underline" onClick={() => setRetry(n => n + 1)}>重试读取</button></p>
              : <p role="status">正在读取导演记录…</p>}
        </div>
      </div>
    </dialog>}
  </section>;
}
