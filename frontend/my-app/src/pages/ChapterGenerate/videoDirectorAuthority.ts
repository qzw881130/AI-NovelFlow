import type { CanonicalVisualState, CanonicalVisualTransition, VideoDirectorPlan } from '../../api/shots';

export type CanonicalVisualStateImageStatus = 'REQUIRED_MISSING' | 'OPTIONAL_MISSING' | 'READY';

export function isCanonicalVisualPlan(plan?: VideoDirectorPlan | null): boolean {
  return plan?.canonical_visual_plan === true;
}

export function getCanonicalVisualStates(plan?: VideoDirectorPlan | null): CanonicalVisualState[] {
  const keyframes = plan?.keyframes;
  if (!isCanonicalVisualPlan(plan) || !Array.isArray(keyframes)) return [];
  return keyframes.filter((state): state is CanonicalVisualState => (
    !!state
    && Number.isFinite(Number(state.index))
    && Number.isFinite(Number(state.time_seconds))
  ));
}

export function classifyVisualStateImageStatus(
  state: CanonicalVisualState,
  resolvedImageUrl?: string | null,
): CanonicalVisualStateImageStatus {
  if (resolvedImageUrl || state.image_url) return 'READY';
  return 'OPTIONAL_MISSING';
}

/** Presentation of existing execution data; carry-in never creates an image dependency. */
export function getVisualStateExecutionImageStatus(
  state: CanonicalVisualState,
  plan: VideoDirectorPlan,
  resolvedImageUrl?: string | null,
): CanonicalVisualStateImageStatus | 'NOT_NEEDED' {
  const index = Number(state.index);
  const required = plan.required_execution_images?.find(item => item.state_index === index);
  if (required) return required.ready ? 'READY' : 'REQUIRED_MISSING';
  // Backend can detect a missing physical file even when an old URL remains.
  if (plan.execution_readiness?.blocking_clips?.some((blocker) => Number(blocker.visual_state_index) === index)) {
    return 'REQUIRED_MISSING';
  }
  if (resolvedImageUrl || state.image_url) return 'READY';
  const clips = plan.clip_plan;
  if (!Array.isArray(clips) || clips.length === 0 || Number(plan.clip_plan_revision || 0) <= 0
    || plan.clip_plan_validation?.passed !== true) return classifyVisualStateImageStatus(state, resolvedImageUrl);
  const owners = clips.filter((clip) => clip.visual_state_indexes?.some((owned) => Number(owned) === index));
  if (owners.length === 0) return 'NOT_NEEDED';
  if (plan.clip_plan_validation?.temporal_contract === 'ELIGIBLE_THEN_SELECTED_V1'
    && plan.clip_plan_validation?.composition_contract === 'EARLY_COMPOSITION_V1'
    && owners.some((clip) => clip.selected_temporal_target_ids?.includes(`KF${index}`)
      || clip.early_composition_state_id === `KF${index}`)) return 'REQUIRED_MISSING';
  return 'OPTIONAL_MISSING';
}

export function getRequiredMissingCanonicalVisualStates(
  plan: VideoDirectorPlan,
  resolveImageUrl: (state: CanonicalVisualState) => string | null | undefined = (state) => state.image_url,
): CanonicalVisualState[] {
  return getCanonicalVisualStates(plan).filter((state) => (
    getVisualStateExecutionImageStatus(state, plan, resolveImageUrl(state)) === 'REQUIRED_MISSING'
  ));
}

export function getAdjacentCanonicalTransitions(
  plan: VideoDirectorPlan,
  stateIndex?: number,
): { previous?: CanonicalVisualTransition; next?: CanonicalVisualTransition } {
  if (!isCanonicalVisualPlan(plan) || stateIndex === undefined) return {};
  const transitions = Array.isArray(plan.transitions) ? plan.transitions : [];
  return {
    previous: transitions.find((transition) => Number(transition.to_keyframe_index) === Number(stateIndex)),
    next: transitions.find((transition) => Number(transition.from_keyframe_index) === Number(stateIndex)),
  };
}

export function canUseLegacyShotGeneration(plan?: VideoDirectorPlan | null): boolean {
  return !isCanonicalVisualPlan(plan);
}

export function buildVideoDirectorShotSavePayload(shot: {
  id?: string | number;
  video_description?: string;
  duration?: number;
  videoDirectorPlan?: VideoDirectorPlan;
}): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    id: shot.id,
    video_description: shot.video_description,
    duration: shot.duration,
  };
  if (!isCanonicalVisualPlan(shot.videoDirectorPlan)) {
    payload.video_director_plan = shot.videoDirectorPlan;
  }
  return payload;
}

export function shouldAutoRecommendLegacyVideoMode(
  plan: VideoDirectorPlan,
  currentShotId: string,
  recommendingShotId: string | null,
): boolean {
  return !isCanonicalVisualPlan(plan)
    && !plan.recommended_mode
    && recommendingShotId !== currentShotId;
}
