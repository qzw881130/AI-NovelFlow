export function H3OptimizerResult({ record }: { record?: any }) {
  if (!record) return null;
  const output = record.output || {};
  return <details className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm max-h-80 overflow-y-auto" data-testid="h3-optimizer-result">
    <summary className="cursor-pointer font-medium">#14 H3 提示词优化 · 最近片段 {record.clip_index ?? record.runtime_input?.clip?.id ?? '-'} · {record.status === 'OPTIMIZED' ? '已采用优化提示词' : record.generation_blocked ? '校验未通过，生成已停止' : '已回退 Raw Prompt'}</summary>
    {record.error && <p className="mt-2 text-amber-800">{record.error}</p>}
    <div className="mt-2">原始时长 {record.original_duration ?? output.av_timeline?.original_duration ?? output.duration?.original ?? record.runtime_input?.clip?.duration ?? '-'}s · #14 优化时长 {record.optimized_duration ?? output.av_timeline?.optimized_duration ?? '-'}s · 执行参数时长 {record.effective_duration ?? '-'}s · 来源 {record.duration_source ?? 'ORIGINAL'}</div>
    {!output.av_timeline && <p>历史 V1 记录：建议时长 {output.duration?.recommended ?? '-'}s（未应用）</p>}
    {record.reused_result && <p>复用已校验的提示词、AV 时间线和执行时长。</p>}
    <p>{output.duration?.reason}</p>
    <H3AVTimeline timeline={output.av_timeline} />
    {Array.isArray(output.canonical_visual_requirements) && <details className="mt-2"><summary>必要剧情视觉要求 / Reference 编号映射</summary><pre className="whitespace-pre-wrap break-words">{JSON.stringify({ requirements: output.canonical_visual_requirements, references: output.reference_projection, execution: record.execution_reference_manifest }, null, 2)}</pre></details>}
    <div className="mt-2">复杂度 {output.complexity?.level || '-'} · 角色 {output.complexity?.subjects ?? '-'} · 对话 {output.complexity?.dialogue_events ?? '-'} · 切换 {output.complexity?.speaker_switches ?? '-'}</div>
    {!!output.risks?.length && <div className="mt-2"><span className="font-medium">风险提示</span><ul className="mt-1 list-disc pl-5 space-y-1 max-h-32 overflow-y-auto">
      {Array.isArray(output.risks) && output.risks.map((risk: any, index: number) => <li key={index}>{typeof risk === 'string' ? risk : `${risk?.code || ''}: ${risk?.detail || risk?.description || String(risk)}`}</li>)}
    </ul></div>}
    {record.llm_log_id && <a className="text-blue-700 underline" href={`/llm-logs?logId=${encodeURIComponent(record.llm_log_id)}`} target="_blank" rel="noreferrer">查看 LLM 日志及图片输入 ({record.image_count || 0})</a>}
    {record.authority_check && <details className="mt-2"><summary>Authority Check · {record.authority_check.status}</summary><pre className="whitespace-pre-wrap break-words">{JSON.stringify(record.authority_check, null, 2)}</pre></details>}
    <details className="mt-2"><summary>Raw Prompt</summary><pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words bg-white p-2">{record.raw_prompt}</pre></details>
    <details className="mt-2"><summary>Optimized Prompt</summary><pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words bg-white p-2">{record.optimized_prompt || (record.generation_blocked ? '优化未通过校验，未提交视频生成。' : '优化失败，使用 Raw Prompt 继续生成。')}</pre></details>
  </details>;
}
import { H3AVTimeline } from '../../../components/H3AVTimeline';
