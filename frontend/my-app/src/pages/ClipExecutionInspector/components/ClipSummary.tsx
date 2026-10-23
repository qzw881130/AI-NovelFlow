import { useInspectorLabels } from '../labels';
import { seconds } from '../presentation';
import type { Projection, SourceStatus } from '../types';
import ExecutionIdentity from './ExecutionIdentity';

export function SourceBadge({ status }: { status: SourceStatus | string }) { return <span className={`cei-source cei-source-${status}`}>{status}</span>; }
export function SourceDetails({ sources }: { sources: Projection['events'][number]['source_refs'] }) {
  return <details className="cei-provenance"><summary>Source / provenance</summary>{sources.map((source, i) => <div key={i}><SourceBadge status={source.status} /><code>{source.kind} · {source.entity_id} · {source.path}</code><p>revision {source.source_revision ?? '—'} · {source.relation_to_execution}</p><code>SHA256 {source.content_hash}</code>{source.text_start != null && <p>text [{source.text_start}, {source.text_end})</p>}</div>)}</details>;
}
export default function ClipSummary({ projection: p }: { projection: Projection }) {
  const l = useInspectorLabels();
  const anchors = p.events.filter(e => e.type === 'PHYSICAL_ANCHOR');
  const semantic = p.events.filter(e => e.type === 'SEMANTIC_KF');
  return <section className="cei-card" data-testid="inspector-summary">
    <h2>{l.summary} · Shot {p.clip_ref.shot_index ?? '—'} / C{p.clip_ref.clip_index ?? '—'} · Revision {p.clip_ref.clip_plan_revision ?? '—'}</h2>
    <ExecutionIdentity projection={p} />
    <div className="cei-summary-grid">
      <div><strong>Shot Time</strong><p>{seconds(p.execution.shot_start)} – {seconds(p.execution.shot_end)}</p><SourceBadge status={p.execution.timing_source_status} /></div>
      <div><strong>{l.planned}</strong><p>{seconds(p.execution.planned_duration)}</p><small>{l.clip}</small></div>
      <div><strong>Operation</strong><p>{p.artifact.capability}</p><small>{p.artifact.artifact_kind}</small></div>
      <div><strong>FPS</strong><p>{p.media.fps ?? '—'} · {p.media.is_cfr == null ? '—' : p.media.is_cfr ? 'CFR' : 'VFR'}</p><small>stream timebase {p.media.stream_time_base ?? '—'}</small></div>
      <div><strong>{l.nativeFrames}</strong><p>{p.media.frame_count ?? '—'}</p><small>{l.native}: {seconds(p.media.video_duration)}</small></div>
      <div><strong>{l.replacement}</strong><p>{p.time_mapping.replacement_frames ?? '—'}</p><small>window {seconds(p.time_mapping.window_duration)} · origin n{p.time_mapping.origin_frame_index0 ?? '—'}</small></div>
      <div><strong>{l.latent}</strong><p>{p.execution.requested_latent_frame_count ?? '—'}</p><small>requested {seconds(p.execution.requested_duration)}</small></div>
      <div><strong>Previous AV</strong><p>{p.execution.previous_av ? `C${p.execution.previous_av.clip_index}` : '—'}</p><small>overlap {p.time_mapping.overlap_frames ?? '—'} · net-new {p.time_mapping.net_new_frames ?? '—'}</small></div>
    </div>
    <div className="cei-targets"><p><b>Semantic Target</b> {semantic.map(e => `${e.label} @${seconds(e.start)}`).join(' · ') || '—'}</p>
      <p><b>Physical Anchor</b> {anchors.map(e => `position1 ${e.payload.frame_position} / local index0 ${e.payload.local_frame_index0} @${seconds(e.start)} → Native index0 ${e.payload.native_frame_index0 ?? '—'} / PTS ${seconds(e.payload.native_pts)}`).join(' · ') || '—'}</p>
      {anchors.map(e => <details key={e.id}><summary>{e.label} · reachability evidence</summary><pre>{JSON.stringify(e.payload.reachability, null, 2)}</pre><p>Semantic {seconds(e.payload.semantic_time)} / physical {seconds(e.start)} · delta {seconds(e.start != null && e.payload.semantic_time != null ? e.start - e.payload.semantic_time : null)}</p><SourceDetails sources={e.source_refs} /></details>)}
      <p>Owned KF: {p.plan_context.owned_visual_state_indexes.join(', ') || '—'} · carry-in KF{p.plan_context.carry_in_state_index ?? '—'} <SourceBadge status={p.plan_context.status} /></p>
    </div>
    <div className="cei-availability">{p.availability.map(item => <span key={item.name}>{item.name} <SourceBadge status={item.status} /></span>)}</div>
    {[...p.warnings, ...p.media.warnings, ...p.time_mapping.warnings].map((warning, i) => <p className="cei-warning" key={i}>{warning}</p>)}
    {p.conflicts.length > 0 && <details className="cei-warning" open><summary>Evidence conflicts · {p.conflicts.length}</summary>{p.conflicts.map((c, i) => <pre key={i}>{JSON.stringify(c, null, 2)}</pre>)}</details>}
    <details><summary>Task / artifact / media / reference details</summary><p>Task: <code>{p.execution.task_id}</code> · status {p.execution.status}</p><p>Artifact: <code>{p.artifact.artifact_id}</code></p><p>Prompt ID: <code>{p.execution.comfyui_prompt_id ?? '—'}</code> · seed {p.execution.seed ?? '—'}</p>
      <p>Video stream {seconds(p.media.video_stream_duration)} · audio {seconds(p.media.audio_duration)} · container {seconds(p.media.container_duration)}</p>
      <p>Video SHA256: <code>{p.artifact.video_sha256 ?? '—'}</code></p>
      <h3>Ordinary Picture references</h3>{p.references.ordinary.map((r, i) => <details key={i}><summary>Picture {r.slot} · {r.kind} · {r.source_name}</summary><pre>{JSON.stringify(r, null, 2)}</pre></details>)}
      <h3>Temporal Anchors / Previous AV</h3><pre>{JSON.stringify({ temporal: p.references.temporal_anchors, previous_av: p.references.previous_av, submitted: p.submitted }, null, 2)}</pre>
      <SourceDetails sources={[p.references.source, p.plan_context.source]} />
    </details>
  </section>;
}
