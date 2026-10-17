/** Chapter merging consumes the persisted Shot videoUrl, never a Clip/task preview. */
export function getChapterMergeReadiness(shot: any): { ready: boolean; label: string; reason: string } {
  if (shot?.id && shot.videoUrl) {
    return { ready: true, label: '可合并', reason: '已保存 Shot 最终视频' };
  }
  const plan = shot?.videoDirectorPlan || {};
  const clips = Array.isArray(plan.clip_plan) && plan.clip_plan.length
    ? plan.clip_plan : Array.isArray(plan.window_plans) ? plan.window_plans : [];
  const complete = clips.length > 0 && clips.every((clip: any) => (
    (clip.video_url || clip.local_path)
    && ['SUCCEEDED', 'COMPLETED', 'APPROVED'].includes(String(clip.status || clip.execution_status || '').toUpperCase())
  ));
  if (complete) return {
    ready: false, label: '片段完成，待合并',
    reason: 'Clip 已生成，但尚无 Shot 最终视频；请先进入该分镜，点击“合并最终视频”。',
  };
  if (shot?.videoStatus === 'failed' || clips.some((clip: any) => String(clip.status || clip.execution_status).toUpperCase() === 'FAILED')) {
    return { ready: false, label: '生成失败', reason: '请先处理失败的片段或 Shot 视频。' };
  }
  if (shot?.videoStatus === 'generating') {
    return { ready: false, label: '生成中', reason: '等待生成并保存 Shot 最终视频后再合并。' };
  }
  return { ready: false, label: clips.length ? '片段未完成' : '缺少最终视频', reason: '尚无 Shot 最终视频，请进入该分镜完成生成与合并。' };
}
