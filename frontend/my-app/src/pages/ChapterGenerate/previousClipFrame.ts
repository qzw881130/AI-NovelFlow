import type { VideoDirectorPlan } from '../../api/shots';

export interface PreviousClipFrameTarget {
  shotId: string;
  stateIndex: number;
  frameIndex: number;
  ownerClipIndex: number;
  previousClipIndex: number;
  identity: string;
}

// Use owned state membership, never carry-in membership or the selected player.
export function previousClipFrameTarget(shot: {
  id: string;
  videoDirectorPlan?: VideoDirectorPlan;
  keyframes?: Array<{ frame_index?: number; plan_keyframe_index?: number; image_url?: string | null }>;
}, stateIndex: number): PreviousClipFrameTarget {
  const plan = shot.videoDirectorPlan;
  if (!plan?.canonical_visual_plan || !plan.clip_plan_validation?.passed || !plan.clip_plan_revision) {
    throw new Error('请先完成当前视觉状态的 Clip 规划');
  }
  const state = plan.keyframes?.find(item => Number(item.index) === stateIndex);
  const owners = (plan.clip_plan || []).filter(clip => clip.visual_state_indexes?.includes(stateIndex));
  if (!state || owners.length !== 1) throw new Error('无法确认当前视觉状态所属的 Clip');
  const owner = owners[0];
  const clips = [...(plan.clip_plan || [])].sort((a, b) => a.clip_index - b.clip_index);
  const previous = clips[clips.findIndex(clip => clip.clip_index === owner.clip_index) - 1];
  if (!previous) throw new Error('当前视觉状态属于第一个 Clip，没有上一个 Clip');
  if (owner.previous_clip_index != null && owner.previous_clip_index !== previous.clip_index) {
    throw new Error('前序 Clip 关系不一致，请刷新规划后重试');
  }
  if (!previous.generated_by_task_id || !(previous.video_url || previous.local_path)
    || !['APPROVED', 'COMPLETED', 'SUCCEEDED'].includes(String(previous.execution_status).toUpperCase())) {
    throw new Error(`上一个 Clip C${previous.clip_index} 尚无已完成的正式视频`);
  }
  const frame = shot.keyframes?.find(item => Number(item.plan_keyframe_index) === stateIndex);
  if (!frame || !Number.isInteger(frame.frame_index) || Number(frame.frame_index) < 0) {
    throw new Error('当前视觉状态没有可替换的图片记录');
  }
  return {
    shotId: shot.id, stateIndex, frameIndex: Number(frame.frame_index),
    ownerClipIndex: owner.clip_index, previousClipIndex: previous.clip_index,
    identity: JSON.stringify({
      shotId: shot.id, revision: plan.clip_plan_revision,
      state: [state.index, state.role, state.time_seconds, state.description, state.image_url, frame.image_url, frame.frame_index],
      owner: [owner.clip_index, owner.start_time, owner.end_time, owner.visual_state_indexes, owner.previous_clip_index],
      previous: [previous.clip_index, previous.generated_by_task_id, previous.video_url, previous.local_path],
    }),
  };
}

export async function captureVideoFrame(video: HTMLVideoElement): Promise<File> {
  video.pause();
  if (video.seeking || video.readyState < 2 || !video.videoWidth || !video.videoHeight) {
    throw new Error('视频画面尚未就绪，请等待定位完成后截取');
  }
  const canvas = document.createElement('canvas');
  const captureTime = video.currentTime;
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  const context = canvas.getContext('2d');
  if (!context) throw new Error('浏览器无法截取视频画面');
  try {
    // Copy synchronously after pausing: async encoding cannot advance the frame.
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob>((resolve, reject) => canvas.toBlob(
      value => value ? resolve(value) : reject(new Error('视频帧编码失败')), 'image/png',
    ));
    return new File([blob], `clip-frame-${captureTime.toFixed(3)}.png`, { type: 'image/png' });
  } catch (error) {
    if (error instanceof Error && error.name === 'SecurityError') {
      throw new Error('视频跨域限制导致无法截帧，请使用系统内保存的视频');
    }
    throw error;
  }
}

export async function savePreviousClipFrame(
  target: PreviousClipFrameTarget, file: File,
  api: {
    getShot: () => Promise<{ success: boolean; data?: Parameters<typeof previousClipFrameTarget>[0]; message?: string }>;
    upload: (frameIndex: number, file: File) => Promise<{ success: boolean; message?: string; detail?: string }>;
  },
) {
  const fresh = await api.getShot();
  if (!fresh.success || !fresh.data) throw new Error(fresh.message || '读取当前视觉状态失败');
  if (previousClipFrameTarget(fresh.data, target.stateIndex).identity !== target.identity) {
    throw new Error('视觉状态、Clip 规划或前序视频已变化，请关闭弹窗后重新选择');
  }
  const result = await api.upload(target.frameIndex, file);
  if (!result.success) throw new Error(result.detail || result.message || '截帧保存失败');
}
