import type { Shot, VideoDirectorPlan } from '../api/shots';
import type { Task } from '../api/tasks';

export type SemanticClipStatus = 'NOT_STARTED' | 'RUNNING' | 'WAITING_REVIEW' | 'FAILED' | 'COMPLETED';
export type SemanticShotStatus = 'NOT_STARTED' | 'PARTIAL' | 'WAITING_REVIEW' | 'FAILED' | 'CLIPS_COMPLETE' | 'ASSEMBLED';

const taskStatus = (task?: Task | null) => String(task?.status || '').toLowerCase();

export const isSemanticShot = (shot: Pick<Shot, 'videoDirectorPlan'> | any) => (
  Array.isArray(shot?.videoDirectorPlan?.clip_plan) && shot.videoDirectorPlan.clip_plan.length > 0
);

export function getSemanticClipStatus(
  clip: NonNullable<VideoDirectorPlan['clip_plan']>[number],
  tasks: Task[],
  revision: number,
): SemanticClipStatus {
  const matching = tasks.filter((task) => (
    task.clipExecution?.execution_scope === 'CLIP'
    && Number(task.clipExecution.clip_plan_revision || 0) === revision
    && Number(task.clipExecution.clip_index || 0) === Number(clip.clip_index)
  ));
  const task = matching.sort((a, b) => String(b.completedAt || b.created_at || '').localeCompare(String(a.completedAt || a.created_at || '')))[0];
  const approval = String(task?.clipExecution?.approval_status || clip.approval_status || '').toUpperCase();
  const status = taskStatus(task);

  if (approval === 'REVIEW_REQUIRED' || approval === 'PENDING_REVIEW') return 'WAITING_REVIEW';
  if (['pending', 'queued', 'running'].includes(status)) return 'RUNNING';
  if (['GENERATING', 'RUNNING', 'QUEUED', 'PROMPT_BUILDING'].includes(String(clip.status || clip.execution_status || '').toUpperCase())) return 'RUNNING';
  if (['failed', 'cancelled'].includes(status) || String(clip.execution_status || '').toUpperCase() === 'FAILED') return 'FAILED';
  if (status === 'completed' && !!task?.resultUrl && approval === 'APPROVED') return 'COMPLETED';
  return 'NOT_STARTED';
}

export function hasCurrentAssembly(plan: VideoDirectorPlan, clips: NonNullable<VideoDirectorPlan['clip_plan']>, tasks: Task[]) {
  const revision = Number(plan.clip_plan_revision || 0);
  const taskIds = clips.map((clip) => {
    const task = tasks.find((item) => (
      item.clipExecution?.execution_scope === 'CLIP'
      && Number(item.clipExecution.clip_plan_revision || 0) === revision
      && Number(item.clipExecution.clip_index || 0) === Number(clip.clip_index)
    ));
    return String(task?.id || clip.generated_by_task_id || '');
  });
  const assemblyIds = (plan.assembly_task_ids || []).map(String);
  return plan.assembly_status === 'COMPLETED'
    && Number(plan.assembly_clip_plan_revision || 0) === revision
    && !!plan.merged_video_url
    && taskIds.every(Boolean)
    && assemblyIds.length === taskIds.length
    && assemblyIds.every((id, index) => id === taskIds[index]);
}

export function getSemanticShotStatus(shot: Pick<Shot, 'videoDirectorPlan'>, tasks: Task[] = []): SemanticShotStatus {
  const plan = shot.videoDirectorPlan || {};
  const clips = Array.isArray(plan.clip_plan) ? plan.clip_plan : [];
  if (!clips.length) return 'NOT_STARTED';
  if (hasCurrentAssembly(plan, clips, tasks)) return 'ASSEMBLED';
  const states = clips.map((clip) => getSemanticClipStatus(clip, tasks, Number(plan.clip_plan_revision || 0)));
  if (states.includes('WAITING_REVIEW')) return 'WAITING_REVIEW';
  if (states.includes('FAILED')) return 'FAILED';
  if (states.every((state) => state === 'COMPLETED')) return 'CLIPS_COMPLETE';
  if (states.some((state) => state === 'COMPLETED' || state === 'RUNNING')) return 'PARTIAL';
  return 'NOT_STARTED';
}

export function getTemporalTargetLabel(plan: VideoDirectorPlan, clip: NonNullable<VideoDirectorPlan['clip_plan']>[number]) {
  const anchors = (clip.temporal_anchor_ids || []).map((id) => (plan.temporal_anchors || []).find((anchor) => anchor.anchor_id === id)).filter(Boolean);
  const labels = anchors.map((anchor) => {
    const index = anchor?.source?.keyframe_index;
    const keyframe = (plan.keyframes || []).find((item) => Number(item.index) === Number(index));
    return `KF${index ?? '?'} · ${Number(keyframe?.time_seconds ?? anchor?.time_seconds ?? 0)}s`;
  });
  if (!labels.length) return null;
  return labels.length > 1 ? `${labels[0]} +${labels.length - 1}` : labels[0];
}

export function getSemanticClipCounts(shot: Shot, tasks: Task[]) {
  const plan = shot.videoDirectorPlan || {};
  const clips = Array.isArray(plan.clip_plan) ? plan.clip_plan : [];
  const states = clips.map((clip) => getSemanticClipStatus(clip, tasks, Number(plan.clip_plan_revision || 0)));
  return {
    pending: states.filter((state) => state !== 'COMPLETED').length,
    reusable: states.filter((state) => state === 'COMPLETED').length,
  };
}
