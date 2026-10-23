import { useEffect, useId, useRef, useState } from 'react';
import { loadContactSheet } from '../contactSheet';
import { useInspectorLabels } from '../labels';
import { seconds } from '../presentation';
import type { FrameSample, Projection } from '../types';
import { ExtractedImage } from './Filmstrip';
import { VideoSource } from './ExecutionIdentity';

export function ContactSheetGrid({ samples, timeDomain }: { samples: FrameSample[]; timeDomain: string }) {
  const l = useInspectorLabels();
  const local = timeDomain === 'CLIP_LOCAL';
  return <div className="cei-contact-sheet-grid" data-testid="contact-sheet-grid">{samples.map(sample =>
    <figure key={sample.sample_id}>
      <ExtractedImage url={sample.image_url} alt={`${local ? 'Clip' : 'Native'} ${seconds(sample.sample_time)} · ${l.frameNumber} ${local ? sample.local_frame_index0 : sample.native_frame_index0}`} lazy />
      <figcaption><b>{seconds(sample.sample_time)} · {l.frameNumber} {local ? sample.local_frame_index0 : sample.native_frame_index0}</b>
        {local && (sample.local_frame_index0 !== sample.native_frame_index0 || sample.sample_time !== sample.native_pts) &&
          <span>Native {seconds(sample.native_pts)} · {l.frameNumber} {sample.native_frame_index0}</span>}
      </figcaption>
    </figure>)}</div>;
}

export default function ContactSheetModal({ projection, interval, analysisId, onClose }: {
  projection: Projection; interval: number; analysisId?: string; onClose: () => void;
}) {
  const l = useInspectorLabels();
  const titleId = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  const [samples, setSamples] = useState<FrameSample[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const element = dialog.current!;
    const previousOverflow = document.body.style.overflow;
    element.showModal();
    document.body.style.overflow = 'hidden';
    return () => { element.close(); document.body.style.overflow = previousOverflow; };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(''); setSamples([]);
    loadContactSheet(projection, interval, analysisId, controller.signal).then(frames => {
      if (!controller.signal.aborted) setSamples(frames);
    }).catch(reason => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : String(reason));
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [projection, interval, analysisId, retry]);
  return <dialog ref={dialog} className="cei-contact-sheet-modal" aria-labelledby={titleId}
    onCancel={e => { e.preventDefault(); onClose(); }} onClick={e => {
      if (e.target !== e.currentTarget) return;
      const rect = e.currentTarget.getBoundingClientRect();
      if (e.clientX < rect.left || e.clientX > rect.right || e.clientY < rect.top || e.clientY > rect.bottom) onClose();
    }}>
    <header className="cei-contact-sheet-header"><div><h2 id={titleId}>{l.contactSheet}</h2>
      <p>{l.sampling} {interval}s · {l.uniformOnly} · {l.zeroBasedFrames}{!loading && !error && ` · ${samples.length} ${l.frameNumber}`}</p>
    </div><button onClick={onClose} autoFocus>{l.close}</button></header>
    <div className="cei-contact-sheet-content" aria-busy={loading}>
      <VideoSource taskId={projection.execution.task_id} videoSha={projection.artifact.video_sha256} surface="contact-sheet" />
      {loading ? <p role="status">{l.loading}</p> : error ? <div className="cei-error" role="alert">{error === 'SOURCE_CHANGED' ? l.sourceChanged : error} <button onClick={() => setRetry(n => n + 1)}>{l.retry}</button></div> :
        samples.length ? <ContactSheetGrid samples={samples} timeDomain={projection.time_mapping.time_domain} /> : <p>{l.noFrames}</p>}
    </div>
  </dialog>;
}
