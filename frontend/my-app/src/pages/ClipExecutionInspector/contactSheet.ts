import { inspectorApi } from '../../api/clipExecutionInspector';
import type { FrameSample, Projection } from './types';

export async function loadContactSheet(projection: Projection, interval: number, analysisId?: string, signal?: AbortSignal) {
  const samples = new Map<number, FrameSample>();
  const body = { artifact_id: projection.artifact.artifact_id, analysis_id: analysisId, variant_id: 'A',
    uniform_interval_seconds: interval, event_enhanced: false, event_neighbors: false };
  let offset = 0;
  let manifestId: string | undefined;
  do {
    signal?.throwIfAborted();
    const page = await inspectorApi.sampling(projection.execution.task_id, body, offset, signal);
    signal?.throwIfAborted();
    if (page.task_id !== projection.execution.task_id || page.artifact_id !== projection.artifact.artifact_id ||
        page.video_sha256 !== projection.artifact.video_sha256 || (manifestId && page.manifest_id !== manifestId)) {
      throw new Error('SOURCE_CHANGED');
    }
    manifestId = page.manifest_id;
    // Sampling also returns boundary/observation frames; the sheet includes only uniform samples.
    for (const sample of page.samples) {
      if (sample.reasons.includes('UNIFORM')) samples.set(sample.native_frame_index0, sample);
    }
    if (page.next_offset == null) break;
    if (page.next_offset <= offset) throw new Error('INVALID_SAMPLING_PAGE');
    offset = page.next_offset;
  } while (true);
  return [...samples.values()].sort((a, b) => a.native_frame_index0 - b.native_frame_index0);
}
