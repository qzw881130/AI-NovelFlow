import type { SemanticClipPlan } from '../../api/shots';
import type { Task } from '../../api/tasks';

export function formatExecutionSeconds(value: number): string {
  return value.toFixed(3);
}

export function getClipGenerationPresentation(clip: SemanticClipPlan, task?: Task) {
  const status = String(task?.status || '').toLowerCase();
  if (status === 'completed' || (!task && clip.generated_by_task_id && clip.video_url)) {
    return { label: '完成', tone: 'blue' as const };
  }
  if (status === 'failed' || status === 'cancelled' || clip.execution_status === 'FAILED') {
    return { label: '失败', tone: 'red' as const };
  }
  if (['pending', 'queued', 'running'].includes(status)
    || ['GENERATING', 'RUNNING', 'QUEUED', 'PROMPT_BUILDING'].includes(String(clip.execution_status || ''))) {
    return { label: '生成中', tone: 'blue' as const };
  }
  return { label: '未生成', tone: 'gray' as const };
}

export function getClipReviewPresentation(clip: SemanticClipPlan, task?: Task) {
  const status = String(task?.clipExecution?.approval_status || clip.approval_status || clip.execution_status || '').toUpperCase();
  const mode = String(task?.clipExecution?.approval_mode || clip.approval_mode || '').toUpperCase();
  if (status === 'APPROVED') {
    return { label: mode === 'AUTO_APPROVE' ? 'AUTO_APPROVED' : 'APPROVED', tone: 'green' as const };
  }
  if (status === 'REJECTED' || status === 'FAILED') return { label: status, tone: 'red' as const };
  if (status === 'REVIEW_REQUIRED' || status === 'PENDING_REVIEW') return { label: '待审核', tone: 'amber' as const };
  return { label: '未审核', tone: 'gray' as const };
}

export function getMaterializedTemporalAnchors(clip: SemanticClipPlan, task?: Task) {
  if (clip.capability !== 'TEMPORAL_EXTEND') return [];
  const anchors = task?.clipExecution?.execution_contract?.temporal_anchor_manifest?.anchors;
  if (!Array.isArray(anchors)) return [];
  return anchors.map((anchor) => ({
    label: anchor.source?.id || anchor.anchor_id || '未知锚点',
    timeSeconds: anchor.time_seconds,
    imageUrl: anchor.image_url || null,
  }));
}

export function getOrdinaryImageReferenceCount(task?: Task): number | null {
  const references = task?.clipExecution?.video_reference_manifest?.references;
  return Array.isArray(references) ? references.length : null;
}

export function getDurationPresentation(target?: number | null, actual?: number | null) {
  if (target == null || actual == null || !Number.isFinite(target) || !Number.isFinite(actual)) {
    return { delta: null, acceptance: 'UNKNOWN' as const };
  }
  const delta = actual - target;
  // A half-second allowance covers ordinary frame/codec rounding; it does not
  // turn a materially shortened assembled video into an accepted 68-second Shot.
  return { delta, acceptance: Math.abs(delta) <= 0.5 ? 'PASS' as const : 'FAIL' as const };
}
