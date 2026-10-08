import { useEffect, useState } from 'react';
import { useI18nStore } from '../../../stores/i18nStore';
import { useInspectorLabels } from '../labels';
import { CATEGORY_LABELS, seconds } from '../presentation';
import type { Observation, ObservationDraft } from '../types';

export default function ObservationEditor({ time, observations, saving, error, onSave, onDelete, onSelect }: {
  time: number; observations: Observation[]; saving: boolean; error: string;
  onSave: (draft: ObservationDraft, id?: string) => Promise<boolean>; onDelete: (id: string) => void; onSelect: (o: Observation) => void;
}) {
  const l = useInspectorLabels();
  const { language, timezone } = useI18nStore();
  const [editing, setEditing] = useState<string>();
  const [start, setStart] = useState(String(time));
  const [end, setEnd] = useState('');
  const [note, setNote] = useState('');
  const [tags, setTags] = useState<string[]>([]);
  const [validation, setValidation] = useState('');
  // A pending draft stays intact when the user browses another frame or a save fails.
  useEffect(() => { if (!editing && !note && !tags.length) setStart(String(time)); }, [time, editing, note, tags.length]);
  const reset = () => { setEditing(undefined); setStart(String(time)); setEnd(''); setNote(''); setTags([]); setValidation(''); };
  const edit = (o: Observation) => { setEditing(o.observation_id); setStart(String(o.time_seconds)); setEnd(o.end_time_seconds == null ? '' : String(o.end_time_seconds)); setNote(o.note); setTags(o.categories); onSelect(o); };
  const submit = async () => {
    if (start.trim() === '' || !Number.isFinite(Number(start)) || Number(start) < 0 || (end !== '' && (!Number.isFinite(Number(end)) || Number(end) < Number(start))) || !tags.length) { setValidation(`${l.start} / ${l.end} / ${l.tags}`); return; }
    setValidation('');
    if (await onSave({ time_seconds: Number(start), end_time_seconds: end === '' ? null : Number(end), categories: tags, note }, editing)) reset();
  };
  const date = (value: string) => new Date(value).toLocaleString(language, { timeZone: timezone });
  return <section className="cei-card" data-testid="inspector-observations"><h2>{l.observation}</h2><div className="cei-row"><label>{l.start}<input type="number" min="0" step="any" value={start} onChange={e => setStart(e.target.value)} /></label><label>{l.end}<input type="number" min={start} step="any" value={end} onChange={e => setEnd(e.target.value)} /></label></div>
    <fieldset><legend>{l.tags}</legend><div className="cei-tags">{Object.entries(CATEGORY_LABELS).map(([key, label]) => <label key={key}><input type="checkbox" checked={tags.includes(key)} onChange={e => setTags(current => e.target.checked ? [...current, key] : current.filter(t => t !== key))} />{label}</label>)}</div></fieldset>
    <label>{l.note}<textarea value={note} maxLength={10000} onChange={e => setNote(e.target.value)} rows={3} /></label>
    {(error || validation) && <p className="cei-error" role="alert">{error || validation}</p>}
    <div className="cei-row"><button disabled={saving} onClick={() => void submit()}>{saving ? l.saving : l.save}</button><button disabled={saving} onClick={reset}>{l.cancel}</button>{editing && <code>{editing}</code>}</div>
    {!observations.length && <p>{l.noNotes}</p>}
    {observations.map(o => <article className="cei-observation" data-testid="saved-observation" key={o.observation_id}>
      <button onClick={() => onSelect(o)}>{seconds(o.time_seconds)}{o.end_time_seconds != null && `–${seconds(o.end_time_seconds)}`} · {o.categories.map(c => CATEGORY_LABELS[c] || c).join(' / ')}</button><p>{o.note}</p><small>{date(o.updated_at)} · Native index0 {o.frame_evidence.native_frame_index0 ?? '—'} / PTS {seconds(o.frame_evidence.native_pts)}</small>
      <div className="cei-row"><button disabled={saving} onClick={() => edit(o)}>{l.edit}</button><button disabled={saving} onClick={() => onDelete(o.observation_id)}>{l.delete}</button></div>
    </article>)}
  </section>;
}
