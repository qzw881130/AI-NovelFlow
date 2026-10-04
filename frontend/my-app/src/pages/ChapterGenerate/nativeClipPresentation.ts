import type { Task } from '../../api/tasks';
import type { SemanticClipPlan } from '../../api/shots';

const NATIVE_ROLE = 'NATIVE_CONTINUITY_OUTPUT';

export function getClipArtifactPresentation(clip: SemanticClipPlan, task?: Task) {
  const continuous = clip.capability === 'EXTEND' || clip.capability === 'TEMPORAL_EXTEND';
  const metadata = task?.clipExecution;
  const physical = metadata?.physical_output;
  const contract = metadata?.execution_contract;
  const approved = task?.status === 'completed' && metadata?.approval_status === 'APPROVED';
  const nativeReady = continuous && approved && clip.generated_by_task_id === task?.id
    && contract?.capability === clip.capability && contract?.artifact_kind === NATIVE_ROLE
    && physical?.physical_output_role === NATIVE_ROLE && physical?.output_node_id === '65'
    && !!task?.resultUrl && physical?.result_url === task.resultUrl && clip.video_url === task.resultUrl;
  const hasResult = !!(clip.video_url || task?.resultUrl);
  const outputStatus = nativeReady ? 'READY' : hasResult
    ? 'Legacy / native continuity unavailable' : '尚无 native continuity output';
  // There is no independent contribution preview artifact. Neither raw context
  // nor the full native cumulative result is an independent Clip playback source.
  const playbackUrl = continuous ? null : metadata?.assembled_result?.url || clip.video_url || task?.resultUrl || null;
  const overlapFrames = nativeReady ? physical?.overlap_frames : undefined;
  const duration = nativeReady ? physical?.overlap_duration
    ?? (physical?.overlap_frames != null && physical?.fps ? physical.overlap_frames / physical.fps : undefined) : undefined;
  const overlapLabel = overlapFrames != null && duration != null
    ? `${overlapFrames} frames / ${duration}s` : '未提供';
  return {
    continuous, nativeReady, outputStatus, playbackUrl, overlapLabel,
    nativeDuration: nativeReady ? physical?.native_cumulative_duration : undefined,
    resultLabel: continuous ? nativeReady ? 'Native continuity output' : '历史/未验证 continuity output' : '片段视频',
    playbackUnavailableReason: '连续 Clip 暂无独立片段预览，请在组装后播放最终 Shot 视频',
  };
}

export function getPreviousAvPresentation(
  clip: SemanticClipPlan, task?: Task, previousClip?: SemanticClipPlan, previousTask?: Task,
) {
  const current = getClipArtifactPresentation(clip, task);
  if (!current.continuous) return { label: '无', debugUrl: null };
  const previous = task?.clipExecution?.execution_contract?.previous_clip;
  const debugUrl = previous?.result_url || task?.clipExecution?.previous_approved_video_url || null;
  const identity = clip.previous_clip_index != null ? `C${clip.previous_clip_index}` : 'Previous Clip 未提供';
  const exact = !!previousClip && previousClip.clip_index === clip.previous_clip_index
    && previousClip.generated_by_task_id === previousTask?.id
    && (!task || previousTask?.clipExecution?.clip_plan_revision === task.clipExecution?.clip_plan_revision)
    && previousTask?.status === 'completed' && previousTask.clipExecution?.approval_status === 'APPROVED'
    && !!previousTask.resultUrl && previousTask.resultUrl === previousClip.video_url
    && (!previous || (previous.generated_by_task_id === previousTask.id && previous.result_url === previousTask.resultUrl));
  if (exact && previousClip.capability === 'GENERATE') {
    return { label: `${identity} · 首段生成 AV · READY`, debugUrl };
  }
  if (exact && getClipArtifactPresentation(previousClip, previousTask).nativeReady) {
    return { label: `${identity} · Native continuity · READY`, debugUrl };
  }
  return { label: `${identity} · native continuity unavailable`, debugUrl };
}
