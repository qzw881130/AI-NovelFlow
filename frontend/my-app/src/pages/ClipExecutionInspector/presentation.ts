import type { FrameSample, InspectorEvent, Observation, Projection } from './types';

export const TRACKS = ['DIALOGUE', 'LIFECYCLE', 'MOTION', 'SEMANTIC_KF', 'PHYSICAL_ANCHOR', 'TRANSITION', 'CAMERA', 'HUMAN'] as const;
export const CATEGORY_LABELS: Record<string, string> = {
  PORTRAIT_DRIFT: 'Portrait / Close-up', WRONG_SPEECH_BODY: 'Wrong visible speaker', WRONG_MOUTH_ARTICULATION: 'Wrong mouth articulation',
  IDENTITY_DRIFT: 'Identity drift', BODY_DUPLICATION: 'Body duplication', SCENE_CONTINUITY_BREAK: 'Scene continuity break',
  PROP_MISMATCH: 'Prop mismatch', CAMERA_MISMATCH: 'Camera mismatch', OTHER: 'Other',
};
export const seconds = (value: number | null | undefined) => value == null ? '—' : `${Number(value.toFixed(6))}s`;
export function inspectorEntry(task: { id: string; status: string; resultUrl?: string | null; result_url?: string | null } | undefined, clip: { generated_by_task_id?: string; video_url?: string }, returnTo: string): string | null {
  const taskId = task?.id || clip.generated_by_task_id;
  const available = task ? task.status === 'completed' && !!(task.resultUrl || task.result_url || clip.video_url) : !!clip.generated_by_task_id && !!clip.video_url;
  return taskId && available ? `/clip-execution-inspector/${encodeURIComponent(taskId)}?returnTo=${encodeURIComponent(returnTo)}` : null;
}
export function expectedAtTime(projection: Projection, time: number) {
  const known = projection.time_mapping.time_domain === 'CLIP_LOCAL';
  const active = (event: InspectorEvent) => event.start != null && event.start <= time && event.end != null && time < event.end;
  const semantic = projection.events.filter(e => e.type === 'SEMANTIC_KF' && e.start != null).sort((a, b) => a.start! - b.start!);
  return {
    status: known ? 'EXPLICIT' : 'DEGRADED',
    dialogues: known ? projection.events.filter(e => e.type === 'DIALOGUE' && active(e)) : [],
    transitions: known ? projection.events.filter(e => e.type === 'TRANSITION' && active(e)) : [],
    rules: projection.events.filter(e => ['LIFECYCLE', 'MOTION', 'CAMERA'].includes(e.type) && (e.start == null || (known && active(e)))),
    previous: known ? [...semantic].reverse().find(e => e.start! <= time) : undefined,
    next: known ? semantic.find(e => e.start! > time) : undefined,
    distances: known ? projection.events.filter(e => ['SEMANTIC_KF', 'PHYSICAL_ANCHOR'].includes(e.type) && e.start != null && e.start >= 0).map(e => ({ ...e, distance: e.start! - time })) : [],
  };
}
export function observationsForFrame(observations: Observation[], frame: FrameSample) {
  return observations.filter(o => o.artifact_id === frame.artifact_id && o.frame_evidence.native_frame_index0 === frame.native_frame_index0);
}
export function nativeFrameSample(projection: Projection, nativeIndex: number): FrameSample | null {
  const media = projection.media;
  if (!media.pts || nativeIndex < 0 || nativeIndex >= media.pts.length) return null;
  const clip = projection.time_mapping.time_domain === 'CLIP_LOCAL';
  const origin = projection.time_mapping.origin_frame_index0 ?? 0;
  if (clip && nativeIndex < origin) return null;
  const time = media.pts[nativeIndex] - (clip ? media.pts[origin] : 0);
  const url = `/api/clip-execution-inspector/frames/${projection.artifact.video_sha256}/frame-v1/thumb/${nativeIndex}`;
  return { sample_id: `${projection.artifact.video_sha256}:${nativeIndex}`, artifact_id: projection.artifact.artifact_id, status: 'EXPLICIT',
    native_frame_index0: nativeIndex, native_pts: media.pts[nativeIndex], local_frame_index0: clip ? nativeIndex - origin : null,
    h3_position1: clip && projection.time_mapping.mode === 'FRAME_INDEX_CFR' ? nativeIndex - origin + 1 : null,
    sample_clip_time: clip ? time : null, sample_time: time, requested_times: [{ time, reason: 'FRAME_STEP', event_id: null }],
    reasons: ['FRAME_STEP'], event_refs: [], image_url: url, detail_url: url.replace('/thumb/', '/detail/') };
}
