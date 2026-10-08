import { useEffect, useState } from 'react';
import { inspectorMediaUrl } from '../../../api/clipExecutionInspector';
import { useInspectorLabels } from '../labels';
import { observationsForFrame, seconds } from '../presentation';
import type { FrameSample, Observation, SamplingManifest } from '../types';
import { VideoSource } from './ExecutionIdentity';

export function ExtractedImage({ url, alt, lazy = false }: { url: string; alt: string; lazy?: boolean }) {
  const l = useInspectorLabels();
  const [failed, setFailed] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => { setFailed(false); setRetry(0); }, [url]);
  return failed ? <div className="cei-image-error" role="alert">{l.unavailable}<button onClick={() => { setFailed(false); setRetry(n => n + 1); }}>{l.retry}</button></div> : <img src={`${inspectorMediaUrl(url)}${retry ? `?retry=${retry}` : ''}`} alt={alt} loading={lazy ? 'lazy' : 'eager'} onError={() => setFailed(true)} />;
}
export default function Filmstrip({ manifest, selected, observations, onSelect, onPage, loading }: {
  manifest: SamplingManifest | null; selected: FrameSample | null; observations: Observation[]; onSelect: (s: FrameSample) => void; onPage: (n: number) => void; loading: boolean;
}) {
  const l = useInspectorLabels();
  return <section className="cei-card" data-testid="inspector-filmstrip"><div className="cei-row"><h2>{l.filmstrip}</h2>{loading && <span>{l.loading}</span>}{manifest && <small>{manifest.unique_frame_count} frames · {manifest.requested_count} requests · dedup {manifest.deduplicated_count}</small>}</div>
    {manifest && <VideoSource taskId={manifest.task_id} videoSha={manifest.video_sha256} surface="filmstrip" />}
    <div className="cei-filmstrip">{manifest?.samples.map(s => <button key={s.sample_id} className={`cei-film-frame ${selected?.native_frame_index0 === s.native_frame_index0 ? 'cei-selected' : ''}`} onClick={() => onSelect(s)} aria-label={`Frame ${s.native_frame_index0} at ${seconds(s.sample_time)}`}>
      <ExtractedImage url={s.image_url} alt={`Native frame ${s.native_frame_index0}`} lazy />
      <b>{manifest.time_domain === 'CLIP_LOCAL' ? 'Clip' : 'Native'} {seconds(s.sample_time)}</b><small>local index0 {s.local_frame_index0 ?? '—'} · Native index0 {s.native_frame_index0}</small><small>Native PTS {seconds(s.native_pts)}</small>
      <span className="cei-event-badges" title={s.reasons.join('\n')}>{s.reasons.filter(r => !r.includes('NEIGHBOR')).slice(0, 3).join(' · ')}</span>
      {observationsForFrame(observations, s).map(o => <span key={o.observation_id} className="cei-note-badge">{l.marker} @{seconds(o.time_seconds)}</span>)}
    </button>)}</div>
    {!loading && !manifest?.samples.length && <p>{l.noFrames}</p>}
    {manifest && <div className="cei-row"><button disabled={manifest.offset === 0 || loading} onClick={() => onPage(Math.max(0, manifest.offset - 48))}>{l.previous}</button><span>{manifest.offset + 1}–{manifest.offset + manifest.samples.length} / {manifest.unique_frame_count}</span><button disabled={manifest.next_offset == null || loading} onClick={() => onPage(manifest.next_offset!)}>{l.next}</button></div>}
    {!!manifest?.unresolved.length && <details><summary>Unresolved / OUT_OF_VIDEO · {manifest.unresolved.length}</summary><pre>{JSON.stringify(manifest.unresolved, null, 2)}</pre></details>}
  </section>;
}
