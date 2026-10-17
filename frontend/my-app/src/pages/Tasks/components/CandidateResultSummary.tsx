import type { Task } from '../../../types';

export function CandidateResultSummary({ task, onPreviewVideo }: { task: Task; onPreviewVideo: (url: string) => void }) {
  const execution = task.clipExecution;
  if (execution?.result_mode !== 'CANDIDATE_ONLY') return null;
  const result = execution.candidate_result;
  return <section className="my-2 min-w-0 rounded border border-amber-200 bg-amber-50 p-3 text-sm" aria-label="实验候选结果">
    <div className="font-medium text-amber-900">实验候选 · C{execution.clip_index} · 未采用</div>
    <div className="break-words">执行策略：{execution.continuation_mode || 'AUTO'} · 规划模式：{execution.planned_capability || execution.capability} · 实际模式：{execution.effective_capability || execution.capability}</div>
    <div>执行结果：{task.status} · {task.currentStep || task.errorMessage || '等待执行'}</div>
    {result && <>
      <div className="break-all text-xs">{result.local_path}</div>
      <div className="break-all text-xs">SHA256：{result.sha256}</div>
      {result.actual_duration != null && <div>实际视频时长：{result.actual_duration}s</div>}
      <button type="button" className="mt-1 text-blue-700 underline" onClick={() => onPreviewVideo(result.url)}>播放实验候选</button>
    </>}
  </section>;
}
