import type { SemanticClipPlan, VideoDirectorPlan } from '../../api/shots';
import type { Task } from '../../api/tasks';

export type CanonicalSemanticReadinessState =
  | 'NO_VISUAL_PLAN'
  | 'REQUIRED_IMAGES_MISSING'
  | 'CLIP_PLAN_MISSING'
  | 'CLIP_PLAN_STALE'
  | 'GENERATE_VISUAL_START_MISSING'
  | 'READY';

export type SemanticClipStatus = 'NOT_STARTED' | 'RUNNING' | 'WAITING_REVIEW' | 'FAILED' | 'COMPLETED';
export type SemanticShotStatus = 'NOT_STARTED' | 'PARTIAL' | 'WAITING_REVIEW' | 'FAILED' | 'CLIPS_COMPLETE' | 'ASSEMBLED';
export type BatchShotCategory = 'ready' | 'generating' | 'queued' | 'completed' | 'missing_preparation' | 'failed';
export type BatchShotFilter = BatchShotCategory | 'all';

export interface BatchShotStatusProjection {
  category: BatchShotCategory;
  selectable: boolean;
  reason: string;
  retry: boolean;
}

export interface BatchShotStatusProjectionInput {
  eligibility: { selectable: boolean; reason: string };
  isGenerating?: boolean;
  isQueued?: boolean;
  isFailed?: boolean;
  isCompleted?: boolean;
  failureReason?: string | null;
}

export interface BatchShotSelectionItem {
  shotIndex: number;
  category: BatchShotCategory;
  selectable: boolean;
  isLegacy?: boolean;
}

export const CANONICAL_EXECUTION_AUTHORITY = 'SEMANTIC_BATCH' as const;

export function hasValidCurrentClipPlan(plan?: VideoDirectorPlan | null): boolean {
  const clips = plan?.clip_plan;
  return Array.isArray(clips)
    && clips.length > 0
    && Number(plan?.clip_plan_revision || 0) > 0
    && plan?.clip_plan_validation?.passed === true;
}

export function getCanonicalSemanticReadiness(
  plan?: VideoDirectorPlan | null,
  resolveImageUrl: (state: NonNullable<VideoDirectorPlan['keyframes']>[number]) => string | null | undefined = (state) => state.image_url,
): {
  state: CanonicalSemanticReadinessState;
  planningAllowed: boolean;
  executionAllowed: boolean;
  requiredMissingIndexes: number[];
  reason?: string | null;
  missingClipIndex?: number | null;
  missingVisualStateIndex?: number | null;
  missingTimeSeconds?: number | null;
} {
  const candidateKeyframes = plan?.keyframes;
  const keyframes = Array.isArray(candidateKeyframes) ? candidateKeyframes : [];
  if (plan?.canonical_visual_plan !== true || keyframes.length === 0) {
    return { state: 'NO_VISUAL_PLAN', planningAllowed: false, executionAllowed: false, requiredMissingIndexes: [] };
  }
  if (!Array.isArray(plan?.clip_plan) || plan.clip_plan.length === 0) {
    return { state: 'CLIP_PLAN_MISSING', planningAllowed: true, executionAllowed: false, requiredMissingIndexes: [] };
  }
  if (!hasValidCurrentClipPlan(plan)) {
    return { state: 'CLIP_PLAN_STALE', planningAllowed: true, executionAllowed: false, requiredMissingIndexes: [] };
  }
  if (plan.clip_plan_validation?.temporal_contract !== 'ELIGIBLE_THEN_SELECTED_V1') {
    return { state: 'CLIP_PLAN_STALE', planningAllowed: true, executionAllowed: false,
      requiredMissingIndexes: [], reason: '历史片段计划需重新规划，以确认定时目标选择' };
  }
  if (!['EARLY_COMPOSITION_V1', 'EARLY_COMPOSITION_V2'].includes(String(plan.clip_plan_validation?.composition_contract || ''))) {
    return { state: 'CLIP_PLAN_STALE', planningAllowed: true, executionAllowed: false,
      requiredMissingIndexes: [], reason: '历史片段计划需重新规划，以确认早期构图覆盖' };
  }
  const missingImages = (plan.required_execution_images || []).filter(item => !item.ready);
  if (missingImages.length) {
    return { state: 'REQUIRED_IMAGES_MISSING', planningAllowed: true, executionAllowed: false,
      requiredMissingIndexes: missingImages.map(item => item.state_index),
      reason: `缺少执行必需图片：${missingImages.map(item => item.state_id).join('、')}` };
  }
  if (plan.execution_readiness?.ready === false) {
    const blocker = plan.execution_readiness.blocking_clips?.[0];
    return {
      state: blocker?.code === 'TEMPORAL_ANCHOR_UNAVAILABLE' ? 'REQUIRED_IMAGES_MISSING' : 'GENERATE_VISUAL_START_MISSING',
      planningAllowed: true,
      executionAllowed: false,
      requiredMissingIndexes: (plan.execution_readiness.blocking_clips || [])
        .filter((item) => item.visual_state_index != null).map((item) => Number(item.visual_state_index)),
      reason: blocker?.message || plan.execution_readiness.message || '缺少片段起始视觉图',
      missingClipIndex: blocker?.clip_index,
      missingVisualStateIndex: blocker?.visual_state_index,
      missingTimeSeconds: blocker?.time_seconds,
    };
  }
  return { state: 'READY', planningAllowed: true, executionAllowed: true, requiredMissingIndexes: [] };
}

export function getSemanticCapabilityLabel(capability?: string | null): string {
  if (capability === 'GENERATE') return '独立生成';
  if (capability === 'EXTEND') return '连续续生成';
  if (capability === 'TEMPORAL_EXTEND') return '构图 / 定时目标续生成';
  return '未知能力';
}

export function getSemanticContinuityLabel(continuity?: string | null): string {
  if (continuity === 'NONE') return '独立开始';
  if (continuity === 'CUT') return '切换衔接';
  if (continuity === 'CONTINUOUS') return '连续衔接';
  return '衔接未指定';
}

export function getOwnedVisualStateLabel(clip: Pick<SemanticClipPlan, 'visual_state_indexes'>): string {
  const indexes = Array.isArray(clip.visual_state_indexes)
    ? clip.visual_state_indexes.filter((index) => Number.isFinite(Number(index))).map(Number)
    : [];
  return indexes.length > 0 ? indexes.map((index) => `KF${index}`).join('、') : '无';
}

export function getCarryInLabel(clip: Pick<SemanticClipPlan, 'previous_clip_index' | 'carry_in_state_index'>): string | null {
  if (!clip.previous_clip_index && !clip.carry_in_state_index) return null;
  const continuation = clip.previous_clip_index ? `接续 C${clip.previous_clip_index}` : '接续前一片段';
  return clip.carry_in_state_index ? `${continuation} · 承接视觉状态 KF${clip.carry_in_state_index}` : continuation;
}

const isTaskForClipRevision = (task: Task, clip: SemanticClipPlan, revision: number) => (
  task.clipExecution?.execution_scope === 'CLIP'
  && Number(task.clipExecution.clip_plan_revision || 0) === Number(revision)
  && Number(task.clipExecution.clip_index || 0) === Number(clip.clip_index)
);

export function resolveSemanticClipTask(clip: SemanticClipPlan, tasks: Task[], revision: number): Task | undefined {
  if (clip.generated_by_task_id) {
    const exact = tasks.find((task) => String(task.id) === String(clip.generated_by_task_id));
    return exact && isTaskForClipRevision(exact, clip, revision) ? exact : undefined;
  }
  return tasks
    .filter((task) => isTaskForClipRevision(task, clip, revision))
    .sort((a, b) => String(b.completedAt || b.updated_at || b.created_at || '').localeCompare(String(a.completedAt || a.updated_at || a.created_at || '')))[0];
}

export function getCurrentSemanticExecutionState(plan: VideoDirectorPlan, tasks: Task[] = []): {
  isGenerating: boolean;
  isQueued: boolean;
  isFailed: boolean;
  failureReason: string | null;
} {
  const revision = Number(plan.clip_plan_revision || 0);
  const clips = Array.isArray(plan.clip_plan) ? plan.clip_plan : [];
  const currentTasks = clips
    .map((clip) => resolveSemanticClipTask(clip, tasks, revision))
    .filter((task): task is Task => !!task);
  const statuses = currentTasks.map((task) => normalizedTaskStatus(task));
  const failedTask = currentTasks.find((task) => ['failed', 'cancelled'].includes(normalizedTaskStatus(task)));
  return {
    isGenerating: statuses.includes('running'),
    isQueued: statuses.some((status) => ['pending', 'queued'].includes(status)),
    isFailed: !!failedTask,
    failureReason: failedTask?.errorMessage || failedTask?.error_message || null,
  };
}

const normalizedTaskStatus = (task?: Task) => String(task?.status || '').toLowerCase();

export function getSemanticClipStatus(clip: SemanticClipPlan, tasks: Task[], revision: number): SemanticClipStatus {
  const task = resolveSemanticClipTask(clip, tasks, revision);
  const approval = String(task?.clipExecution?.approval_status || clip.approval_status || clip.execution_status || '').toUpperCase();
  const taskStatus = normalizedTaskStatus(task);
  const clipStatus = String(clip.status || clip.execution_status || '').toUpperCase();

  if (approval === 'REVIEW_REQUIRED' || approval === 'PENDING_REVIEW') return 'WAITING_REVIEW';
  if (['pending', 'queued', 'running'].includes(taskStatus) || ['GENERATING', 'RUNNING', 'QUEUED', 'PROMPT_BUILDING'].includes(clipStatus)) return 'RUNNING';
  if (['failed', 'cancelled'].includes(taskStatus) || clipStatus === 'FAILED') return 'FAILED';
  if (taskStatus === 'completed' && !!task?.resultUrl && approval === 'APPROVED') return 'COMPLETED';
  if (
    !!clip.generated_by_task_id
    && !!(clip.video_url || clip.local_path)
    && ['APPROVED', 'SUCCEEDED', 'COMPLETED'].includes(clipStatus)
  ) return 'COMPLETED';
  return 'NOT_STARTED';
}

export function hasCurrentAssembly(plan: VideoDirectorPlan, tasks: Task[] = []): boolean {
  if (plan.canonical_visual_plan === true && !hasValidCurrentClipPlan(plan)) return false;
  const clips = Array.isArray(plan.clip_plan) ? plan.clip_plan : [];
  const revision = Number(plan.clip_plan_revision || 0);
  if (!clips.length || !revision) return false;
  const taskIds = clips.map((clip) => (
    String(clip.generated_by_task_id || resolveSemanticClipTask(clip, tasks, revision)?.id || '')
  ));
  const assemblyIds = (plan.assembly_task_ids || []).map(String);
  return plan.assembly_status === 'COMPLETED'
    && Number(plan.assembly_clip_plan_revision || 0) === revision
    && !!plan.merged_video_url
    && taskIds.every(Boolean)
    && assemblyIds.length === taskIds.length
    && assemblyIds.every((id, index) => id === taskIds[index]);
}

export function getSemanticShotStatusFromPlan(plan: VideoDirectorPlan, tasks: Task[] = []): SemanticShotStatus {
  if (plan.canonical_visual_plan === true && !hasValidCurrentClipPlan(plan)) return 'NOT_STARTED';
  const clips = Array.isArray(plan.clip_plan) ? plan.clip_plan : [];
  if (!clips.length) return 'NOT_STARTED';
  if (hasCurrentAssembly(plan, tasks)) return 'ASSEMBLED';
  const states = clips.map((clip) => getSemanticClipStatus(clip, tasks, Number(plan.clip_plan_revision || 0)));
  if (states.includes('WAITING_REVIEW')) return 'WAITING_REVIEW';
  if (states.includes('FAILED')) return 'FAILED';
  if (states.every((state) => state === 'COMPLETED')) return 'CLIPS_COMPLETE';
  if (states.some((state) => state === 'COMPLETED' || state === 'RUNNING')) return 'PARTIAL';
  return 'NOT_STARTED';
}

export function buildSemanticBatchRequest(shotIds: string[], autoAssemble = true) {
  return {
    shot_ids: shotIds,
    auto_complete_details: false,
    use_reference_audio: true,
    skip_llm_when_prompt_exists: false,
    force_rerun: false,
    auto_assemble: autoAssemble,
  };
}

export function getCanonicalBatchEligibility(
  plan: VideoDirectorPlan,
  tasks: Task[] = [],
  resolveImageUrl?: (state: NonNullable<VideoDirectorPlan['keyframes']>[number]) => string | null | undefined,
  autoAssemble = true,
): { selectable: boolean; reason: string; authority: typeof CANONICAL_EXECUTION_AUTHORITY } {
  const readiness = getCanonicalSemanticReadiness(plan, resolveImageUrl);
  if (readiness.state === 'NO_VISUAL_PLAN') return { selectable: false, reason: '请先规划视觉时间轴', authority: CANONICAL_EXECUTION_AUTHORITY };
  if (readiness.state === 'REQUIRED_IMAGES_MISSING') return { selectable: false, reason: `缺少必需视觉状态图：${readiness.requiredMissingIndexes.map((index) => `KF${index}`).join('、')}`, authority: CANONICAL_EXECUTION_AUTHORITY };
  if (readiness.state === 'CLIP_PLAN_MISSING') return { selectable: false, reason: '请先规划视频片段', authority: CANONICAL_EXECUTION_AUTHORITY };
  if (readiness.state === 'CLIP_PLAN_STALE') return { selectable: false, reason: '需要重新规划视频片段', authority: CANONICAL_EXECUTION_AUTHORITY };
  if (readiness.state === 'GENERATE_VISUAL_START_MISSING') return { selectable: false, reason: readiness.reason || '缺少片段起始视觉图', authority: CANONICAL_EXECUTION_AUTHORITY };
  const status = getSemanticShotStatusFromPlan(plan, tasks);
  if (status === 'ASSEMBLED') return { selectable: false, reason: '当前版本已完成', authority: CANONICAL_EXECUTION_AUTHORITY };
  if (status === 'WAITING_REVIEW') return { selectable: false, reason: '等待审核', authority: CANONICAL_EXECUTION_AUTHORITY };
  if (status === 'CLIPS_COMPLETE' && !autoAssemble) return { selectable: false, reason: '视频片段已完成，待合并', authority: CANONICAL_EXECUTION_AUTHORITY };
  return { selectable: true, reason: status === 'CLIPS_COMPLETE' ? '视频片段已完成，待合并' : '可执行语义视频片段', authority: CANONICAL_EXECUTION_AUTHORITY };
}

/**
 * Projects existing readiness and execution authority into one primary Batch UX
 * category. It deliberately does not decide whether a Shot is executable.
 */
export function getBatchShotStatusProjection({
  eligibility,
  isGenerating = false,
  isQueued = false,
  isFailed = false,
  isCompleted = false,
  failureReason,
}: BatchShotStatusProjectionInput): BatchShotStatusProjection {
  if (isGenerating) return { category: 'generating', selectable: false, reason: '视频生成中', retry: false };
  if (isQueued) return { category: 'queued', selectable: false, reason: '视频队列中', retry: false };
  if (isFailed) {
    return {
      category: 'failed',
      selectable: eligibility.selectable,
      reason: failureReason || '上次执行失败',
      retry: eligibility.selectable,
    };
  }
  if (isCompleted) return { category: 'completed', selectable: false, reason: '当前版本已完成', retry: false };
  if (eligibility.selectable) return { category: 'ready', selectable: true, reason: eligibility.reason, retry: false };
  return { category: 'missing_preparation', selectable: false, reason: eligibility.reason, retry: false };
}

export function getSelectableBatchShotIndexes(
  items: BatchShotSelectionItem[],
  filter: BatchShotFilter,
): number[] {
  return items
    .filter((item) => (filter === 'all' || item.category === filter) && item.selectable)
    .map((item) => item.shotIndex);
}

export function reconcileBatchSelection(
  selectedIndexes: Iterable<number>,
  items: BatchShotSelectionItem[],
): number[] {
  const selectableIndexes = new Set(items.filter((item) => item.selectable).map((item) => item.shotIndex));
  return Array.from(selectedIndexes).filter((index) => selectableIndexes.has(index));
}

export function shouldShowLegacyBatchCompatibility(items: BatchShotSelectionItem[]): boolean {
  return items.some((item) => item.isLegacy === true);
}

export function hasLegacyBatchPlanningState(plan?: VideoDirectorPlan | null): boolean {
  if (!plan || plan.canonical_visual_plan === true) return false;
  return !!plan.selected_mode
    || !!plan.recommended_mode
    || (Array.isArray(plan.keyframes) && plan.keyframes.length > 0)
    || (Array.isArray(plan.window_plans) && plan.window_plans.length > 0)
    || (Array.isArray(plan.clips) && plan.clips.length > 0);
}
