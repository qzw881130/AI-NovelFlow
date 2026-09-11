import type { AudioTimeline } from '../../../api/audioDrive';

export function AudioTimingReview({ timeline }: { timeline: AudioTimeline }) {
  const timing = timeline.timingSummary;
  if (!timing) return null;
  const seconds = (value: number | null) => value !== null && Number.isFinite(value) ? `${Number(value.toFixed(3))}s` : '--';

  return (
    <section aria-label="时长检查" className="rounded-lg border border-blue-100 bg-blue-50/40 p-3">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-sm font-semibold text-gray-900">时长检查</h4>
        <span className="text-xs text-gray-500">只读建议，不自动裁切</span>
      </div>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
        {[
          ['规划生效时长', timing.resolvedDurationSeconds],
          ['视觉预估下限', timing.visualEstimatedFloorSeconds],
          ['TTS 文件合计', timing.measuredTtsDurationSeconds],
          ['最后 TTS 文件结束', timing.lastTtsFileEndSeconds],
          ['尾事件设定停顿', timing.authoredFinalPauseSeconds],
          ['末段无 TTS 覆盖', timing.remainingNonSpeechHoldSeconds],
        ].map(([label, value]) => (
          <div key={String(label)} className="min-w-0 rounded bg-white p-2">
            <dt className="text-gray-500">{label}</dt>
            <dd className="mt-1 font-medium tabular-nums text-gray-900">{seconds(value as number | null)}</dd>
          </div>
        ))}
      </dl>
      {!timing.ttsCoverageComplete && <p className="mt-3 text-xs text-amber-700">Timeline 或 TTS 尚未全部就绪，不能据此缩短镜头。</p>}
      {timing.ttsCoverageComplete && timing.longTailReviewSuggested && (
        <p className="mt-3 text-xs text-amber-800">
          扣除设定停顿后，末段还有 {seconds(timing.holdAfterAuthoredFinalPauseSeconds)} 无 TTS 覆盖。请先确认动作是否结束，再到分镜拆分调整预估时长。
        </p>
      )}
      <p className="mt-3 text-xs leading-relaxed text-gray-500">
        统计基于完整 TTS 文件，可能包含文件内静音，不代表真实发音或动作结束点。无 TTS 的时段仍可能有动作；保留必要停顿和一镜到底意图，已有视频不会自动改变。
      </p>
    </section>
  );
}
