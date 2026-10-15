import type { Task } from '../api/tasks';

const entries = (value: any) => value && typeof value === 'object' ? Object.entries(value) : [];
export function phaseBSummary(record: any) {
  const result = record?.compiler_result;
  const warnings = new Set<string>();
  const errors = new Set<string>();
  if (record?.error) errors.add(String(record.error));
  for (const [name, check] of entries(record?.preflight?.native_diagnostics || result?.review?.native_prompt_diagnostics)) {
    if (check === false) warnings.add(name);
  }
  for (const [scope, diagnostic] of Object.entries({ preflight: record?.preflight, submission: record?.submission_preflight })) {
    if (diagnostic?.passed === false) errors.add(scope);
  }
  for (const finding of [...(result?.picture_audit?.findings || []), ...(record?.preflight?.findings || [])]) {
    if (finding.severity === 'ERROR' || finding.severity === 'BLOCKING') errors.add(finding.code || finding.message);
    else if (finding.severity === 'WARNING') warnings.add(finding.code || finding.message);
  }
  if (record?.status === 'FAILED' && !errors.size) errors.add('规划失败');
  return {
    duration: result?.execution_decisions?.timing?.optimized_duration,
    pictures: result?.reference_manifest?.references?.length,
    temporal: result?.temporal_manifest?.anchors?.length,
    dialogues: result?.execution_decisions?.timing?.dialogue_events?.length,
    warnings: [...warnings], errors: [...errors],
  };
}

export function phaseBActualVideo(task?: Task) {
  if (task?.status !== 'completed' || !task.resultUrl) return undefined;
  const execution = task.clipExecution;
  const independent = execution?.clip_playback?.independent_media?.video_duration;
  if (typeof independent === 'number' && Number.isFinite(independent)) {
    return { seconds: independent, label: '实际视频时长（生成片，含共享前缀）' };
  }
  const duration = execution?.actual_duration;
  if (typeof duration !== 'number' || !Number.isFinite(duration)) return undefined;
  return { seconds: duration, label: execution?.artifact_kind === 'NATIVE_CONTINUITY_OUTPUT' ? '实际视频时长（累计输出）' : '实际视频时长' };
}
