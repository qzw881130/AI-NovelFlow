import type { Shot, VideoDirectorPlan } from '../api/shots';
import type { Task } from '../api/tasks';
import {
  getSemanticClipStatus,
  getSemanticShotStatusFromPlan,
  hasCurrentAssembly,
  type SemanticClipStatus,
  type SemanticShotStatus,
} from '../pages/ChapterGenerate/semanticClipAuthority';

export { getSemanticClipStatus, hasCurrentAssembly };
export type { SemanticClipStatus, SemanticShotStatus };

export const isSemanticShot = (shot: Pick<Shot, 'videoDirectorPlan'> | any) => (
  Array.isArray(shot?.videoDirectorPlan?.clip_plan) && shot.videoDirectorPlan.clip_plan.length > 0
);

export function getSemanticShotStatus(shot: Pick<Shot, 'videoDirectorPlan'>, tasks: Task[] = []): SemanticShotStatus {
  return getSemanticShotStatusFromPlan(shot.videoDirectorPlan || {}, tasks);
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
