// An index alone is not identity: audio rebuilds can reuse it at a different time.
export const matchingLegacyKeyframe = (shot: any, frame: any) => {
  if (!frame || !(shot?.videoDirectorPlan?.keyframes || []).some((item: any) => (
    item.index === frame.index && item.role === frame.role && item.time_seconds === frame.time_seconds
  ))) return undefined;
  return (shot.keyframes || []).find((item: any) => (
    Number(item.plan_keyframe_index ?? item.planKeyframeIndex) === Number(frame.index)
    && (!item.role || item.role === frame.role)
    && item.time_seconds != null && frame.time_seconds != null
    && Math.abs(Number(item.time_seconds) - Number(frame.time_seconds)) < 0.001
    && String(item.description || '').trim() === String(frame.description || shot.description || '').trim()
  ));
};

export const videoKeyframeImage = (shot: any, frame: any) => {
  if (!frame) return null;
  if (frame.role === 'START') return shot.imageUrl || null;
  const legacy = matchingLegacyKeyframe(shot, frame);
  return frame.image_url || frame.imageUrl || legacy?.image_url || legacy?.imageUrl || null;
};

export const formalVideoPlanReady = (shot: any) => {
  const plan = shot.videoDirectorPlan || {};
  const mode = plan.selected_mode || plan.recommended_mode || 'SINGLE_FRAME';
  if (mode === 'SINGLE_FRAME') return true;
  const frames = plan.keyframes || [];
  if (mode === 'FIRST_LAST_FRAME') {
    // Successful first/last planning stores audio-bound clips but can retain STALE.
    // Validate the actual ranges against the canonical duration, not that flag.
    const clips = plan.clips?.length ? plan.clips : plan.execution_windows || [];
    const duration = Number(plan.audio_timeline?.resolved_duration ?? shot.duration);
    const matches = (value: unknown, expected: number) => value != null && Math.abs(Number(value) - expected) < 0.001;
    return Number.isFinite(duration) && duration > 0 && clips.length === 1
      && matches(clips[0].start_time, 0) && matches(clips[0].end_time, duration)
      && frames.length === 2
      && frames.some((f: any) => f.role === 'START' && matches(f.time_seconds, 0))
      && frames.some((f: any) => f.role === 'END' && matches(f.time_seconds, duration));
  }
  if (plan.keyframe_planning_status === 'STALE') return false;
  const windows = plan.execution_windows || [];
  if (!frames.length || !windows.length) return false;
  return plan.window_plans?.length === windows.length && plan.window_plans.every((w: any, i: number) => (
    Number(w.start_time) === Number(windows[i].start_time) && Number(w.end_time) === Number(windows[i].end_time)
    && [3, 4].includes(Number(w.selected_frame_count)) && w.keyframe_indexes?.length === Number(w.selected_frame_count)
    && w.keyframe_indexes.every((index: number) => frames.some((f: any) => Number(f.index) === Number(index)))
  ));
};
