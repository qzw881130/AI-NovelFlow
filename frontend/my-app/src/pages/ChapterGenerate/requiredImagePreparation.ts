import type { RequiredExecutionImage, Shot, PrepareRequiredImagesResult } from '../../api/shots';

export type RequiredImageStatus = 'NOT_REQUIRED' | 'REQUIRED_MISSING' | 'GENERATING' | 'READY' | 'FAILED';
export function requiredImageStatus(item?: RequiredExecutionImage): RequiredImageStatus {
  if (!item) return 'NOT_REQUIRED';
  if (item.ready) return 'READY';
  if (item.active_task) return 'GENERATING';
  if (item.failure) return 'FAILED';
  return 'REQUIRED_MISSING';
}
export function requiredImagesForClip(shot: Pick<Shot, 'videoDirectorPlan'>, clipIndex?: number): RequiredExecutionImage[] {
  return (shot.videoDirectorPlan?.required_execution_images || [])
    .filter(item => clipIndex == null || item.consumer_clip_indexes.includes(clipIndex))
    .map(item => {
      if (clipIndex == null) return item;
      const ready = item.consumers.filter(c => c.consumer_clip_index === clipIndex).every(c => c.ready);
      return { ...item, ready, missing: !ready, failure: ready ? null : item.failure };
    });
}
export function clipPreparationPresentation(shot: Pick<Shot, 'videoDirectorPlan'>, clipIndex: number) {
  const images = requiredImagesForClip(shot, clipIndex);
  const imagesReady = images.every(item => item.consumers.filter(c => c.consumer_clip_index === clipIndex).every(c => c.ready));
  const execution = shot.videoDirectorPlan?.clip_execution_readiness?.find(c => c.clip_index === clipIndex);
  return { imagesReady, executionReady: imagesReady && execution?.ready === true,
    label: !imagesReady ? '等待必需图片' : execution?.code === 'WAITING_PREVIOUS_AV' ? `等待C${execution.previous_clip_index}前序视频` : execution?.ready ? '可生成片段' : '等待执行校验' };
}
export function canPrepareMaterials(shot: Pick<Shot, 'videoDirectorPlan'>): boolean {
  const plan = shot.videoDirectorPlan;
  return plan?.canonical_visual_plan === true && plan.clip_plan_validation?.passed === true
    && plan.clip_plan_validation.temporal_contract === 'ELIGIBLE_THEN_SELECTED_V1'
    && Number(plan.clip_plan_revision) > 0 && !!plan.required_execution_images?.length;
}
export async function prepareCurrentRequiredImages(
  shot: Shot, clipIndexes: number[] | undefined, stateIndexes: number[] | undefined,
  ports: { getShot: () => Promise<Shot>; prepare: (revision: number, clips?: number[], states?: number[]) => Promise<PrepareRequiredImagesResult>; onShot: (shot: Shot) => void },
) {
  const fresh = await ports.getShot();
  ports.onShot(fresh);
  if (!canPrepareMaterials(fresh)) throw new Error('当前片段计划不可准备，请刷新或重新规划');
  if (fresh.videoDirectorPlan?.clip_plan_revision !== shot.videoDirectorPlan?.clip_plan_revision) throw new Error('Clip revision 已变化，请重新检查准备范围');
  const result = await ports.prepare(Number(fresh.videoDirectorPlan?.clip_plan_revision), clipIndexes, stateIndexes);
  ports.onShot(result.shot);
  // Only authoritative fresh Shot/anchor/readiness decides READY, never Task.completed.
  ports.onShot(await ports.getShot());
  return result.items;
}
