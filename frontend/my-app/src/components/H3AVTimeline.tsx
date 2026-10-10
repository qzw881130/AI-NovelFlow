const seconds = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : '—';
const rows = (value: unknown): any[] => Array.isArray(value) ? value.filter(item => item && typeof item === 'object') : [];

export function H3AVTimeline({ timeline }: { timeline?: any }) {
  if (!timeline || typeof timeline !== 'object') return null;
  const dialogues = rows(timeline.dialogue_events);
  const handoffs = rows(timeline.handoffs);
  const anchors = rows(timeline.anchors);
  const phases = rows(timeline.execution_phases);
  const tableClass = 'w-full text-left text-xs [&_td]:p-2 [&_th]:p-2 [&_tr]:border-b';
  return <div className="space-y-3 rounded border border-blue-200 bg-white p-3" data-testid="h3-av-timeline">
    <p className="font-medium">AV 执行时长：{seconds(timeline.original_duration)}s → {seconds(timeline.optimized_duration)}s · Δ {seconds(timeline.duration_delta)}s</p>
    <p className="text-sm text-gray-600">{timeline.reason}</p>
    <div className="overflow-x-auto"><table className={tableClass}>
      <caption className="text-left font-medium">Dialogue Retiming · 单条发声时长保持</caption>
      <thead><tr><th>事件 / Speaker</th><th>Original → Optimized (s)</th><th>发声时长前 → 后</th></tr></thead>
      <tbody>{dialogues.map((event, i) => {
        const before = event.original_end - event.original_start;
        const after = event.optimized_end - event.optimized_start;
        const unchanged = Number.isFinite(before) && Number.isFinite(after) && Math.abs(before - after) <= 0.000001;
        return <tr key={event.id ?? i}><td>{event.id} · {event.speaker}</td><td>{seconds(event.original_start)}–{seconds(event.original_end)} → {seconds(event.optimized_start)}–{seconds(event.optimized_end)}</td><td>{seconds(before)} → {seconds(after)} {unchanged ? 'PASS' : 'FAIL'}</td></tr>;
      })}</tbody>
    </table></div>
    <details open><summary className="cursor-pointer font-medium">Speaker Handoffs ({handoffs.length})</summary>
      {handoffs.map((handoff, i) => <div key={i} className="mt-2 border-b pb-2 text-xs">
        <p>{handoff.from} → {handoff.to} · {handoff.from_subject} → {handoff.to_subject} · gap {seconds(handoff.original_gap)} → {seconds(handoff.optimized_gap)}s</p>
        {handoff.complexity && <div className="my-1 space-y-1" data-testid="h3-handoff-reasoning">
          <p className="font-medium">复杂度 {handoff.complexity} · Visual Handoff {handoff.visual_handoff_required === true ? '需要' : handoff.visual_handoff_required === false ? '无需' : '—'} · Camera Handoff {handoff.camera_handoff_required === true ? '需要' : handoff.camera_handoff_required === false ? '无需' : '—'}</p>
          <p>空间：{handoff.spatial_relation} · 景深：{handoff.depth_relation}</p>
          <p className="text-gray-600">{handoff.complexity_reasoning}</p>
          <p>Camera：{handoff.camera_strategy}</p>
          <p>Previous Speaker Release：{handoff.previous_speaker_release}</p>
          <p>Next Speaker Readiness：{handoff.next_speaker_readiness}</p>
        </div>}
        <p>{handoff.strategy}</p><p className="text-gray-600">{handoff.reason}</p>
        <details><summary>可见性 / 就绪 / Listener / 注意 / Camera / Anchor</summary><pre className="whitespace-pre-wrap break-words">{JSON.stringify(handoff, null, 2)}</pre></details>
      </div>)}
    </details>
    <div className="overflow-x-auto"><table className={tableClass}>
      <caption className="text-left font-medium">Anchor 使用决策 · 必要剧情视觉要求独立保留</caption>
      <thead><tr><th>Anchor</th><th>Original → Optimized (s)</th><th>理由</th></tr></thead>
      <tbody>{anchors.map((anchor, i) => <tr key={anchor.id ?? i}><td>{anchor.id} · {anchor.decision || (anchor.visual_state_changed === false ? '保持' : '待检查')}</td><td>{seconds(anchor.original_time)} → {anchor.decision === 'DROP' ? '不使用该参考图' : seconds(anchor.optimized_time)}</td><td>{anchor.reason}{anchor.released_constraint && <p>放弃约束：{anchor.released_constraint}</p>}{Array.isArray(anchor.preserved_visual_requirements) && <p>保留视觉要求：{anchor.preserved_visual_requirements.join(', ') || '由全局剧情要求覆盖'}</p>}</td></tr>)}</tbody>
    </table></div>
    <details open><summary className="cursor-pointer font-medium">Attention / Action / Camera / Final Settle ({phases.length})</summary>
      <div className="overflow-x-auto"><table className={tableClass}><thead><tr><th>Phase</th><th>时间 (s)</th><th>执行内容</th></tr></thead>
        <tbody>{phases.map((phase, i) => <tr key={phase.id ?? i}><td>{phase.id} · {phase.type}</td><td className="whitespace-nowrap">{seconds(phase.start)}–{seconds(phase.end)}</td><td>{phase.description}</td></tr>)}</tbody>
      </table></div>
    </details>
  </div>;
}
