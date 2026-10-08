import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useInspectorLabels } from './labels';
import { useClipExecutionInspector } from './useClipExecutionInspector';
import ClipSummary from './components/ClipSummary';
import UnifiedTimeline from './components/UnifiedTimeline';
import Filmstrip from './components/Filmstrip';
import FrameInspector from './components/FrameInspector';
import ObservationEditor from './components/ObservationEditor';
import { ExecutionResultOptions } from './components/ExecutionIdentity';
import './inspector.css';

export default function ClipExecutionInspector() {
  const { taskId = '' } = useParams();
  const [query, setQuery] = useSearchParams();
  const navigate = useNavigate();
  const l = useInspectorLabels();
  const state = useClipExecutionInspector(taskId, query.get('analysis'), query.get('artifact'), id => {
    const next = new URLSearchParams(query); next.set('analysis', id); setQuery(next, { replace: true });
  });
  const [timeInput, setTimeInput] = useState('0');
  useEffect(() => setTimeInput(String(state.requestedTime)), [state.requestedTime]);
  const p = state.projection;
  const observations = state.analysis?.observations.filter(o => o.variant_id === 'A') || [];
  const returnTo = query.get('returnTo');
  const back = returnTo?.startsWith('/novels/') ? returnTo : p ? `/novels/${p.clip_ref.novel_id}/chapters/${p.clip_ref.chapter_id}/generate` : '/novels';
  const openTask = (nextTaskId: string, analysis?: string) => {
    const next = new URLSearchParams(); next.set('returnTo', back); if (analysis) next.set('analysis', analysis);
    navigate(`/clip-execution-inspector/${encodeURIComponent(nextTaskId)}?${next}`);
  };
  return <main className="cei-page" data-testid="clip-execution-inspector"><div className="cei-row cei-heading"><h1>{l.title}</h1><Link to={back}>{l.back}</Link></div>
    {state.loading && <p>{l.loading}</p>}
    {state.error && <div className="cei-error" role="alert">{state.error} <button onClick={state.reload}>{l.retry}</button></div>}
    {p && <>
      <div className="cei-card cei-row">
        {state.artifacts && <label>{l.artifact}<select disabled={state.saving} value={taskId} onChange={e => openTask(e.target.value)}><ExecutionResultOptions executions={state.artifacts.artifacts} selectedTaskId={taskId} /></select></label>}
        <button disabled={state.saving || p.artifact.identity_status !== 'STABLE' || !!state.analysis} onClick={() => void state.saveAnalysis()}>{state.analysis ? l.saved : l.saveAnalysis}</button>
        {state.analysis && <><code>{state.analysis.analysis_id}</code><button disabled={state.saving} onClick={() => openTask(taskId)}>{l.newAnalysis}</button></>}
        {!!state.artifacts?.analyses.length && <label>{l.saved}<select disabled={state.saving} value={state.analysis?.analysis_id || ''} onChange={e => { if (e.target.value) {
          const a = state.artifacts?.analyses.find(a => a.analysis_id === e.target.value);
          // Saved execution identity is validated by the API/hook, including a deleted Task.
          if (a) navigate(`/clip-execution-inspector/${encodeURIComponent(a.variants[0].task_id || taskId)}?analysis=${a.analysis_id}&returnTo=${encodeURIComponent(back)}`);
        } }}><option value="">—</option>{state.artifacts.analyses.map(a => <option value={a.analysis_id} key={a.analysis_id}>{a.created_at} · {a.analysis_id.slice(0, 8)}</option>)}</select></label>}
      </div>
      {state.analysis?.variants[0].source_media_status === 'SOURCE_NOT_AVAILABLE' && <p className="cei-warning">{l.missingMedia}</p>}
      {state.analysis?.variants[0].source_media_status === 'SOURCE_CHANGED' && <p className="cei-warning">{l.sourceChanged}</p>}
      <ClipSummary projection={p} />
      <UnifiedTimeline projection={p} time={state.selected?.sample_time || 0} observations={observations} onEvent={e => { if (e.start != null && e.start >= 0) void state.selectTime(e.start, e); }} onObservation={o => void state.selectTime(o.time_seconds)} />
      <div className="cei-card cei-row cei-sampling-controls"><label>{l.sampling}<select value={state.interval} onChange={e => state.changeSampling(Number(e.target.value))}>{[.5, 1, 2].map(t => <option value={t} key={t}>{t}s</option>)}</select></label>
        <label><input type="checkbox" checked={state.events} onChange={e => state.setEvents(e.target.checked)} />{l.events}</label><label><input type="checkbox" checked={state.neighbors} disabled={!state.events} onChange={e => state.setNeighbors(e.target.checked)} />{l.neighbors}</label>
        <form className="cei-row" onSubmit={e => { e.preventDefault(); if (timeInput.trim()) void state.selectTime(Number(timeInput)); }}><label>{p.time_mapping.time_domain === 'CLIP_LOCAL' ? l.clip : l.native}<input type="number" min="0" max={p.time_mapping.axis_duration ?? undefined} step="any" value={timeInput} onChange={e => setTimeInput(e.target.value)} /></label><button type="submit">{l.view}</button></form>
      </div>
      {state.sampleError && <p className="cei-error" role="alert">{state.sampleError} <button onClick={() => void state.selectTime(state.requestedTime)}>{l.retry}</button></p>}
      <Filmstrip manifest={state.manifest} selected={state.selected} observations={observations} onSelect={state.selectFrame} onPage={state.setOffset} loading={state.sampling} />
      <FrameInspector projection={p} sample={state.selected} requested={state.requestedTime} observations={observations} onStep={state.stepFrame} onTime={t => void state.selectTime(t)} />
      <ObservationEditor key={`${taskId}:${p.artifact.artifact_id}`} time={state.requestedTime} observations={observations} saving={state.saving} error={state.writeError} onSave={state.saveObservation} onDelete={id => void state.deleteObservation(id)} onSelect={o => void state.selectTime(o.time_seconds)} />
      <details className="cei-card" onToggle={e => { if (e.currentTarget.open) void state.loadRaw(); }}><summary>{l.raw}</summary>{state.raw ? <><button onClick={() => void navigator.clipboard.writeText(JSON.stringify(state.raw, null, 2))}>{l.copy}</button><pre>{JSON.stringify(state.raw, null, 2)}</pre></> : <p>{l.loading}</p>}</details>
    </>}
  </main>;
}
