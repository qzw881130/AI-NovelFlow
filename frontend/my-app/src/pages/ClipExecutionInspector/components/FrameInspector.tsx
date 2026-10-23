import { useEffect, useRef, useState } from 'react';
import type { RefObject } from 'react';
import { inspectorMediaUrl } from '../../../api/clipExecutionInspector';
import { useInspectorLabels } from '../labels';
import { expectedAtTime, observationsForFrame, seconds } from '../presentation';
import type { FrameSample, Observation, Projection } from '../types';
import { ExtractedImage } from './Filmstrip';
import { SourceBadge, SourceDetails } from './ClipSummary';
import PromptAuthorityPanel from './PromptAuthorityPanel';
import { VideoSource } from './ExecutionIdentity';

export function NativeAVPlayback({ projection: p, sample, video, onTime }: {
  projection: Projection; sample: FrameSample | null; video: RefObject<HTMLVideoElement>; onTime: (t: number) => void;
}) {
  const l = useInspectorLabels();
  return <><VideoSource taskId={p.execution.task_id} videoSha={p.artifact.video_sha256} surface="player" />
    <video controls preload="none" ref={video} src={inspectorMediaUrl(p.artifact.result_url)} onLoadedMetadata={() => { if (sample && video.current) video.current.currentTime = sample.native_pts; }} onPause={() => {
      if (!video.current) return;
      const t = video.current.currentTime - (p.time_mapping.time_domain === 'CLIP_LOCAL' ? p.time_mapping.origin_native_pts || 0 : 0);
      if (t >= 0) onTime(t);
    }} /><p>{l.browserSeek}</p></>;
}

function Expected({ projection, time, exact = false }: { projection: Projection; time: number; exact?: boolean }) {
  const l = useInspectorLabels();
  const state = expectedAtTime(projection, time);
  return <div data-testid={exact ? 'expected-exact-time' : 'expected-frame-time'}><h3>{exact ? l.exact : l.expected} · {seconds(time)}</h3>
    {state.status === 'DEGRADED' && <p className="cei-warning">DEGRADED · {l.unavailable}</p>}
    {state.dialogues.length ? state.dialogues.map(e => <div key={e.id}><b>{e.label}</b> <SourceBadge status={e.source_refs[0]?.status || 'SOURCE_NOT_AVAILABLE'} /><p>{e.payload.text}</p><p>{seconds(e.start)}–{seconds(e.end)}</p><SourceDetails sources={e.source_refs} /></div>) : <p>{l.gap}</p>}
    <p>{l.previousState}: {state.previous?.label || '—'} @{seconds(state.previous?.start)} / {l.nextState}: {state.next?.label || '—'} @{seconds(state.next?.start)}</p>
    <details open><summary>{l.distance}</summary>{state.distances.map(e => <p key={e.id}>{e.label}: {e.distance >= 0 ? '+' : ''}{seconds(e.distance)}</p>)}</details>
    {state.transitions.map(e => <details key={e.id}><summary>{e.label} · {seconds(e.start)}–{seconds(e.end)} <SourceBadge status={e.source_refs[0]?.status || 'SOURCE_NOT_AVAILABLE'} /></summary><p>{e.payload.transition_description}</p><SourceDetails sources={e.source_refs} /></details>)}
    {state.rules.map(e => <details key={e.id}><summary>{e.label} · {e.timing_kind === 'CLIP_SCOPE' ? 'CLIP_SCOPE' : `${seconds(e.start)}–${seconds(e.end)}`}</summary><p>{e.payload.message}</p><pre>{e.payload.text}</pre><SourceDetails sources={e.source_refs} /></details>)}
  </div>;
}
export default function FrameInspector({ projection: p, sample, requested, observations, onStep, onTime }: {
  projection: Projection; sample: FrameSample | null; requested: number; observations: Observation[]; onStep: (delta: number) => void; onTime: (t: number) => void;
}) {
  const l = useInspectorLabels();
  const video = useRef<HTMLVideoElement>(null);
  const [playback, setPlayback] = useState(false);
  useEffect(() => {
    if (sample && video.current && video.current.paused) video.current.currentTime = sample.native_pts;
  }, [sample]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.closest('input, textarea, select, button, [contenteditable="true"]')) return;
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); onStep(e.key === 'ArrowLeft' ? -1 : 1); }
      if (e.code === 'Space' && video.current) { e.preventDefault(); if (video.current.paused) void video.current.play(); else video.current.pause(); }
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [onStep]);
  return <section className="cei-card" data-testid="inspector-frame"><h2>{l.frame}</h2><div className="cei-inspect-grid"><div>
    <VideoSource taskId={p.execution.task_id} videoSha={p.artifact.video_sha256} surface="frame" />
    <h3>{l.actual}</h3>{sample ? <><ExtractedImage url={sample.detail_url} alt={`Actual Native frame ${sample.native_frame_index0}`} />
      <p>{l.time} {seconds(requested)} · actual {p.time_mapping.time_domain === 'CLIP_LOCAL' ? 'Clip' : 'Native'} {seconds(sample.sample_time)} · Δ {seconds(sample.sample_time - requested)}</p>
      <p>Clip index0 <b>{sample.local_frame_index0 ?? '—'}</b> / H3 position1 <b>{sample.h3_position1 ?? '—'}</b> / Native index0 <b>{sample.native_frame_index0}</b> / Native PTS <b>{seconds(sample.native_pts)}</b></p>
      <div className="cei-row"><button disabled={sample.native_frame_index0 <= (p.time_mapping.origin_frame_index0 ?? 0)} onClick={() => onStep(-1)}>← frame</button><button disabled={sample.native_frame_index0 + 1 >= (p.media.frame_count || 0)} onClick={() => onStep(1)}>frame →</button></div>
      <details><summary>Sampling provenance</summary><pre>{JSON.stringify(sample.requested_times, null, 2)}</pre></details>
      {observationsForFrame(observations, sample).map(o => <p className="cei-note-badge" key={o.observation_id}>{l.marker} {seconds(o.time_seconds)} · {o.categories.join(', ')} · {o.note}</p>)}
    </> : <p>{l.noFrames}</p>}
    {p.media.status === 'EXPLICIT' && <details onToggle={e => setPlayback(e.currentTarget.open)}><summary>Native AV playback</summary>{playback && <NativeAVPlayback projection={p} sample={sample} video={video} onTime={onTime} />}</details>}
  </div><div>{sample && <><Expected projection={p} time={sample.sample_time} />{Math.abs(sample.sample_time - requested) > 1e-7 && <Expected projection={p} time={requested} exact />}</>}<PromptAuthorityPanel projection={p} /></div></div></section>;
}
