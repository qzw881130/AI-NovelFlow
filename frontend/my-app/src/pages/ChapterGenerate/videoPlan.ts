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
  // Legacy successful replans retained STALE. Trust only a complete canonical structure.
  const windows = plan.execution_windows || [];
  const duration = Number(plan.audio_timeline?.resolved_duration ?? shot.duration);
  const finite = (value: unknown) => value != null && value !== '' && Number.isFinite(Number(value));
  const matches = (value: unknown, expected: number) => finite(value) && Math.abs(Number(value) - expected) < 0.001;
  if (!Number.isFinite(duration) || duration <= 0 || !Array.isArray(frames) || !frames.length
    || !Array.isArray(windows) || !windows.length || !Array.isArray(plan.window_plans)
    || plan.window_plans.length !== windows.length) return false;
  const byIndex = new Map<number, any>();
  if (!frames.every((f: any, i: number) => {
    if (!f || !Number.isInteger(Number(f.index)) || Number(f.index) <= 0 || byIndex.has(Number(f.index))
      || !finite(f.time_seconds) || Number(f.time_seconds) < 0 || Number(f.time_seconds) > duration
      || (i > 0 && (Number(f.index) <= Number(frames[i - 1].index)
        || Number(f.time_seconds) <= Number(frames[i - 1].time_seconds)))) return false;
    byIndex.set(Number(f.index), f);
    return f.role === (i === 0 ? 'START' : i === frames.length - 1 ? 'END' : 'INTERMEDIATE');
  }) || !matches(frames[0].time_seconds, 0) || !matches(frames[frames.length - 1].time_seconds, duration)) return false;
  const referenced = new Set<number>();
  const ready = windows.every((window: any, i: number) => {
    const w = plan.window_plans[i];
    if (!window || !w || Number(window.window_index) !== i + 1 || Number(w.window_index) !== i + 1
      || !finite(window.start_time) || !finite(window.end_time)
      || Number(window.start_time) < 0 || Number(window.end_time) > duration
      || Number(window.end_time) <= Number(window.start_time)
      || !matches(window.start_time, i === 0 ? 0 : Number(windows[i - 1].end_time))
      || (i === windows.length - 1 && !matches(window.end_time, duration))
      || !matches(w.start_time, Number(window.start_time)) || !matches(w.end_time, Number(window.end_time))
      || ![3, 4].includes(Number(w.selected_frame_count)) || !Array.isArray(w.keyframe_indexes)
      || w.keyframe_indexes.length !== Number(w.selected_frame_count)
      || new Set(w.keyframe_indexes.map(Number)).size !== w.keyframe_indexes.length) return false;
    const selected = w.keyframe_indexes.map((index: any) => byIndex.get(Number(index)));
    return selected.every((f: any, j: number) => {
      if (!f || Number(f.time_seconds) < Number(window.start_time) || Number(f.time_seconds) > Number(window.end_time)
        || (j > 0 && Number(f.time_seconds) <= Number(selected[j - 1].time_seconds))) return false;
      referenced.add(Number(f.index));
      return true;
    }) && matches(selected[0].time_seconds, Number(window.start_time))
      && matches(selected[selected.length - 1].time_seconds, Number(window.end_time));
  });
  return ready && referenced.size === frames.length;
};
