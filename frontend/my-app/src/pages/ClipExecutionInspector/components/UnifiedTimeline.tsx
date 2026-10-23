import { useState } from 'react';
import { useInspectorLabels } from '../labels';
import { TRACKS, seconds } from '../presentation';
import type { InspectorEvent, Observation, Projection } from '../types';
import { SourceBadge } from './ClipSummary';

export default function UnifiedTimeline({ projection: p, time, observations, onEvent, onObservation }: {
  projection: Projection; time: number; observations: Observation[]; onEvent: (e: InspectorEvent) => void; onObservation: (o: Observation) => void;
}) {
  const l = useInspectorLabels();
  const [zoom, setZoom] = useState(1);
  const duration = p.time_mapping.axis_duration || p.execution.planned_duration || 1;
  const known = p.time_mapping.time_domain === 'CLIP_LOCAL';
  const percent = (t: number) => `${Math.max(0, Math.min(100, t / duration * 100))}%`;
  const anchors = p.events.filter(e => e.type === 'PHYSICAL_ANCHOR' && e.start != null);
  return <section className="cei-card" data-testid="inspector-timeline"><div className="cei-row"><h2>{l.timeline}</h2><span>{known ? l.clip : l.native} · {seconds(time)}</span><label>{l.zoom} <select value={zoom} onChange={e => setZoom(Number(e.target.value))}><option value={1}>1×</option><option value={2}>2×</option><option value={4}>4×</option></select></label></div>
    <div className="cei-timeline-scroll"><div className="cei-timeline" style={{ minWidth: `${800 * zoom}px` }}>
      <div className="cei-track"><strong>Time</strong><div className="cei-axis">{Array.from({ length: 7 }, (_, i) => <span key={i} style={{ left: percent(duration * i / 6) }}>{seconds(duration * i / 6)}</span>)}</div></div>
      {TRACKS.map(type => <div className={`cei-track cei-track-${type}`} data-testid={`track-${type}`} key={type}><strong>{l[type]}</strong><div className="cei-track-body">
        <div className="cei-cursor" style={{ left: percent(time) }} />
        {known && p.execution.planned_duration != null && <div className="cei-tail" title={l.tail} style={{ left: percent(p.execution.planned_duration), width: percent(duration - p.execution.planned_duration) }} />}
        {type === 'HUMAN' ? observations.map(o => <button key={o.observation_id} className="cei-timeline-event cei-marker" data-testid="observation-marker" style={{ left: percent(o.time_seconds), width: o.end_time_seconds == null ? undefined : percent(o.end_time_seconds - o.time_seconds) }} title={`${seconds(o.time_seconds)} ${o.categories.join(', ')} ${o.note}`} onClick={() => onObservation(o)}>{l.marker} · {seconds(o.time_seconds)}</button>) : known && p.events.filter(e => e.type === type && e.start != null && e.start >= 0).map(e => <button key={e.id} className={`cei-timeline-event ${e.end == null ? 'cei-point' : 'cei-range'}`} style={{ left: percent(e.start!), width: e.end == null ? undefined : percent(e.end - e.start!) }} title={`${e.label} ${seconds(e.start)}–${seconds(e.end)}\n${e.payload.text || e.payload.transition_description || ''}`} onClick={() => onEvent(e)}><span>{e.label}</span></button>)}
        {type !== 'HUMAN' && (!known || !p.events.some(e => e.type === type && e.start != null && e.start >= 0)) && <small className="cei-no-track">{l.unavailable}</small>}
      </div></div>)}
    </div></div>
    {known && anchors.map(e => <p className="cei-anchor-delta" key={e.id}><span className="cei-semantic-key">◆ Semantic KF{e.payload.source?.keyframe_index} {seconds(e.payload.semantic_time)}</span> → <span className="cei-physical-key">◇ position1 {e.payload.frame_position} {seconds(e.start)}</span> · Δ {seconds(e.start! - e.payload.semantic_time)}</p>)}
    <details><summary>{l.untimed}</summary>{p.events.filter(e => e.start == null || e.start < 0).map(e => <p key={e.id}>{e.label} · {e.start == null ? l.unknown : seconds(e.start)} <SourceBadge status={e.source_refs[0]?.status || 'SOURCE_NOT_AVAILABLE'} /></p>)}</details>
    <details><summary>Dialogue / event details</summary>{p.events.filter(e => e.type === 'DIALOGUE').map(e => <p key={e.id}><button onClick={() => onEvent(e)}>{e.label} · {seconds(e.start)}–{seconds(e.end)}</button> {e.payload.text} <SourceBadge status={e.source_refs[0]?.status || 'SOURCE_NOT_AVAILABLE'} /></p>)}</details>
  </section>;
}
