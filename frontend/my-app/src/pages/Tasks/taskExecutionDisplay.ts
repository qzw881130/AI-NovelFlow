/** Display projection only: persisted Clip capability, never legacy video mode. */
export function getCanonicalClipTaskDescription(task: {
  type: string;
  description?: string;
  clipExecution?: {
    execution_scope?: string;
    capability?: string;
    clip_plan_revision?: number;
  } | null;
}): string | null {
  const execution = task.clipExecution;
  if (task.type !== 'shot_video' || execution?.execution_scope !== 'CLIP'
    || Number(execution.clip_plan_revision || 0) <= 0
    || !['GENERATE', 'EXTEND', 'TEMPORAL_EXTEND'].includes(execution.capability || '')) return null;
  const description = (task.description || '')
    .replace(/[；;]?\s*视频模式\s*[:：]\s*(?:SINGLE_FRAME|FIRST_LAST_FRAME|MULTI_KEYFRAME)\b/g, '')
    .trim();
  return [description, execution.capability].filter(Boolean).join(' · ');
}
