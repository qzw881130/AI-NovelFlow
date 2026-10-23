import { useCallback, useEffect, useRef, useState } from 'react';
import { inspectorApi } from '../../api/clipExecutionInspector';
import { nativeFrameSample } from './presentation';
import type { Analysis, ArtifactList, FrameSample, InspectorEvent, ObservationDraft, Projection, SamplingManifest } from './types';

const message = (error: unknown) => error instanceof Error ? error.message : String(error);
export function useClipExecutionInspector(taskId: string, analysisId: string | null, artifactId: string | null, onSaved: (id: string) => void) {
  const [projection, setProjection] = useState<Projection | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [artifacts, setArtifacts] = useState<ArtifactList | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [writeError, setWriteError] = useState('');
  const [sampleError, setSampleError] = useState('');
  const [saving, setSaving] = useState(false);
  const [interval, setInterval] = useState(1);
  const [events, setEvents] = useState(true);
  const [neighbors, setNeighbors] = useState(true);
  const [offset, setOffset] = useState(0);
  const [manifest, setManifest] = useState<SamplingManifest | null>(null);
  const [sampling, setSampling] = useState(false);
  const [selected, setSelected] = useState<FrameSample | null>(null);
  const [requestedTime, setRequestedTime] = useState(0);
  const [selectedEvent, setSelectedEvent] = useState<InspectorEvent | null>(null);
  const [raw, setRaw] = useState<Record<string, any> | null>(null);
  const loadedKey = useRef('');
  const selectionRequest = useRef(0);
  const generation = useRef(0);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const key = `${taskId}|${analysisId || ''}|${artifactId || ''}|${reloadKey}`;
    if (loadedKey.current === key) return;
    loadedKey.current = key;
    const controller = new AbortController();
    generation.current += 1;
    selectionRequest.current += 1;
    setLoading(true); setError(''); setProjection(null); setAnalysis(null); setManifest(null); setSelected(null); setRaw(null); setArtifacts(null); setOffset(0); setSelectedEvent(null); setRequestedTime(0);
    const load = async () => {
      try {
        let p: Projection;
        if (analysisId) {
          const saved = await inspectorApi.analysis(analysisId, controller.signal);
          const variant = saved.variants.find(v => v.variant_id === 'A');
          if (!variant || variant.projection.execution.task_id !== taskId) throw new Error('SOURCE_IDENTITY_MISMATCH');
          p = variant.projection;
          if (controller.signal.aborted) return;
          setAnalysis(saved);
        } else p = await inspectorApi.execution(taskId, artifactId, controller.signal);
        if (controller.signal.aborted) return;
        setProjection(p);
        if (p.clip_ref.shot_id && p.clip_ref.clip_index != null) {
          inspectorApi.artifacts(p.clip_ref.shot_id, p.clip_ref.clip_index, controller.signal).then(data => {
            if (!controller.signal.aborted) setArtifacts(data);
          }).catch(() => { /* Saved analyses can remain readable after business records disappear. */ });
        }
      } catch (err) { if (!controller.signal.aborted) setError(message(err)); }
      finally { if (!controller.signal.aborted) setLoading(false); }
    };
    void load();
    return () => {
      controller.abort();
      // StrictMode replays setup after cleanup; an aborted load is not loaded.
      // Keep the new key published by ensureAnalysis so saving preserves the view.
      if (loadedKey.current === key) loadedKey.current = '';
    };
  }, [taskId, analysisId, artifactId, reloadKey]);

  const samplingBody = useCallback((extra: Record<string, any> = {}) => ({ artifact_id: projection?.artifact.artifact_id,
    analysis_id: analysis?.analysis_id, variant_id: 'A', uniform_interval_seconds: interval,
    event_enhanced: events, event_neighbors: neighbors, ...extra }), [projection?.artifact.artifact_id, analysis?.analysis_id, interval, events, neighbors]);

  useEffect(() => {
    if (!projection) return;
    const controller = new AbortController();
    setSampling(true); setSampleError('');
    inspectorApi.sampling(taskId, samplingBody(), offset, controller.signal).then(data => {
      if (controller.signal.aborted) return;
      setManifest(data);
      setSelected(current => current && current.artifact_id === projection.artifact.artifact_id ? current : data.samples[0] || null);
    }).catch(err => { if (!controller.signal.aborted) setSampleError(message(err)); }).finally(() => { if (!controller.signal.aborted) setSampling(false); });
    return () => controller.abort();
  }, [projection?.artifact.artifact_id, taskId, samplingBody, offset, analysis?.revision, reloadKey]);

  const selectFrame = useCallback((sample: FrameSample, requested = sample.sample_time) => {
    selectionRequest.current += 1;
    setSelected(sample); setRequestedTime(requested); setSelectedEvent(null);
  }, []);
  const selectTime = useCallback(async (time: number, event: InspectorEvent | null = null) => {
    if (!projection || !Number.isFinite(time) || time < 0) return;
    const requestId = ++selectionRequest.current;
    const currentGeneration = generation.current;
    setSampleError('');
    try {
      const data = await inspectorApi.sampling(taskId, samplingBody({ include_uniform: false, event_enhanced: false, requested_times: [time] }));
      if (requestId !== selectionRequest.current || currentGeneration !== generation.current) return;
      const sample = data.samples.find(s => s.requested_times.some(r => r.reason === 'MANUAL_REQUEST' && r.time === time));
      if (!sample) throw new Error(data.unresolved.find(r => r.reason === 'MANUAL_REQUEST')?.status || 'OUT_OF_VIDEO');
      setSelected(sample); setRequestedTime(time); setSelectedEvent(event);
    } catch (err) { if (requestId === selectionRequest.current && currentGeneration === generation.current) setSampleError(message(err)); }
  }, [projection, taskId, samplingBody]);
  const stepFrame = useCallback((delta: number) => {
    if (!projection || !selected) return;
    const sample = nativeFrameSample(projection, selected.native_frame_index0 + delta);
    if (sample) selectFrame(sample);
  }, [projection, selected, selectFrame]);

  const ensureAnalysis = async () => {
    if (analysis) return analysis;
    if (!projection) throw new Error('SOURCE_NOT_AVAILABLE');
    const data = await inspectorApi.createAnalysis(taskId, projection.artifact.artifact_id);
    setAnalysis(data); setProjection(data.variants[0].projection);
    // Publishing the durable URL does not reset the currently selected frame or draft.
    loadedKey.current = `${taskId}|${data.analysis_id}|${artifactId || ''}|${reloadKey}`;
    onSaved(data.analysis_id);
    return data;
  };
  const saveAnalysis = async () => {
    setSaving(true); setWriteError('');
    try { await ensureAnalysis(); } catch (err) { setWriteError(message(err)); } finally { setSaving(false); }
  };
  const saveObservation = async (draft: ObservationDraft, observationId?: string): Promise<boolean> => {
    setSaving(true); setWriteError('');
    try {
      const saved = await ensureAnalysis();
      setAnalysis(observationId ? await inspectorApi.updateObservation(saved, observationId, draft) : await inspectorApi.createObservation(saved, draft));
      return true;
    } catch (err) { setWriteError(message(err)); return false; } finally { setSaving(false); }
  };
  const deleteObservation = async (observationId: string) => {
    if (!analysis) return;
    setSaving(true); setWriteError('');
    try { setAnalysis(await inspectorApi.deleteObservation(analysis, observationId)); }
    catch (err) { setWriteError(message(err)); } finally { setSaving(false); }
  };
  const loadRaw = async () => {
    if (!projection || raw) return;
    const g = generation.current;
    try {
      const data = analysis ? analysis.variants[0].source_snapshot : await inspectorApi.evidence(taskId, projection.artifact.artifact_id);
      if (g === generation.current) setRaw(data);
    } catch (err) { if (g === generation.current) setWriteError(message(err)); }
  };
  const changeSampling = (value: number) => { setInterval(value); setOffset(0); };
  return { projection, analysis, artifacts, loading, error, writeError, sampleError, saving, interval, events, neighbors,
    manifest, sampling, selected, requestedTime, selectedEvent, raw, offset, setOffset,
    changeSampling, setEvents: (value: boolean) => { setEvents(value); setOffset(0); }, setNeighbors: (value: boolean) => { setNeighbors(value); setOffset(0); },
    selectFrame, selectTime, stepFrame, saveAnalysis, saveObservation, deleteObservation, loadRaw,
    reload: () => setReloadKey(k => k + 1) };
}
