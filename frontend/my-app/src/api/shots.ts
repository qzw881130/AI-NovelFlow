/**
 * 分镜相关 API
 */
import { api } from './index';

// 分镜台词数据
export interface DialogueData {
  type?: 'character' | 'narration';  // 台词类型：角色台词或旁白
  character_name: string;
  text: string;
  emotion_prompt?: string;
  audio_url?: string;
  audio_task_id?: string;
  audio_source?: 'ai_generated' | 'uploaded';
}

// 分镜数据（从后端 Shot 模型映射）
export interface Shot {
  id: string;
  chapterId: string;
  index: number;
  description: string;
  video_description?: string;
  shotImagePrompt?: string | null;
  characters: string[];
  scene: string;
  props: string[];
  duration: number;
  continuity_mode?: string;
  videoDirectorPlan?: VideoDirectorPlan;
  imageUrl: string | null;
  imagePath: string | null;
  imageStatus: 'pending' | 'generating' | 'completed' | 'failed';
  imageTaskId: string | null;
  videoUrl: string | null;
  videoStatus: 'pending' | 'generating' | 'completed' | 'failed';
  videoTaskId: string | null;
  mergedCharacterImage: string | null;
  mergedPropImage: string | null;
  dialogues: DialogueData[];
  keyframes?: KeyframeData[];
  referenceAudioUrl?: string | null;
  referenceAudioType?: string;
  createdAt: string | null;
  updatedAt: string | null;
}

export type VideoMode = 'SINGLE_FRAME' | 'FIRST_LAST_FRAME' | 'MULTI_KEYFRAME';

export interface VideoAiCall {
  step?: string;
  title?: string;
  task_type?: string;
  prompt_template_name?: string;
  status?: string;
  input_summary?: string;
  response?: string;
  parsed_result?: any;
  final_prompt?: string | null;
  clip_index?: number | null;
  workflow_type?: string | null;
  workflow_name?: string | null;
  reference_images?: Array<{ label?: string; url?: string }> | null;
  created_at?: string;
}

export interface VideoDirectorPlan {
  selected_mode?: VideoMode;
  recommended_mode?: VideoMode;
  recommended_label?: string;
  recommendation_reason?: string;
  task_error_message?: string;
  error_message?: string;
  first_last_available?: boolean;
  notice?: string;
  workflow_capability?: {
    max_clip_duration?: number;
    workflow_name?: string;
    [key: string]: any;
  };
  keyframes?: Array<{
    index: number;
    time_seconds: number;
    role: 'START' | 'INTERMEDIATE' | 'END';
    description?: string | null;
    image_url?: string;
  }>;
  transitions?: Array<{
    segment_index?: number;
    from_keyframe_index?: number;
    to_keyframe_index?: number;
    transition_description?: string;
    [key: string]: any;
  }>;
  clips?: Array<{
    clip_index: number;
    start_time: number;
    end_time: number;
    frame_count?: number;
    selected_frame_count?: number;
    workflow_key?: string;
    workflow_type?: string;
    keyframe_indexes?: number[];
    status?: string;
  }>;
  execution_windows?: Array<{
    window_index: number;
    start_time: number;
    end_time: number;
  }>;
  window_plans?: Array<{
    window_index: number;
    start_time: number;
    end_time: number;
    selected_frame_count: 3 | 4;
    workflow_key?: string;
    workflow_type?: string;
    workflow_name?: string;
    keyframe_indexes: number[];
    status?: string;
    video_url?: string;
    local_path?: string;
    source_video_url?: string;
    prompt_text?: string;
    prompt_id?: string;
    reference_images?: Array<{ label?: string; url?: string }>;
    error_message?: string | null;
    generated_at?: string;
  }>;
  merged_video_url?: string;
  merged_at?: string;
  ai_calls?: VideoAiCall[];
  validation?: Record<string, any>;
}

// 关键帧数据
export interface KeyframeData {
  frame_index: number;
  description: string;
  image_url?: string;
  image_task_id?: string;
  reference_image_url?: string;
  reference_mode?: string;
}

// 分镜更新请求
export interface ShotUpdateRequest {
  description?: string;
  video_description?: string;
  shot_image_prompt?: string;
  characters?: string[];
  scene?: string;
  props?: string[];
  duration?: number;
  continuity_mode?: string;
  dialogues?: DialogueData[];
}

export const shotsApi = {
  /**
   * 获取章节的所有分镜列表
   */
  getShots: async (novelId: string, chapterId: string): Promise<{ success: boolean; data: Shot[]; message?: string }> => {
    const response = await fetch(`/api/novels/${novelId}/chapters/${chapterId}/shots/`);
    return response.json();
  },

  /**
   * 获取单个分镜详情
   */
  getShot: async (novelId: string, chapterId: string, shotId: string): Promise<{ success: boolean; data: Shot; message?: string }> => {
    const response = await fetch(`/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}`);
    return response.json();
  },

  downloadShotLlmData: async (novelId: string, chapterId: string, shotId: string): Promise<void> => {
    const response = await fetch(`/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/download-llm-data`);
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || data.message || '下载 LLM 数据失败');
    }
    const blob = await response.blob();
    const disposition = response.headers.get('content-disposition') || '';
    const filenameMatch = disposition.match(/filename="?([^";]+)"?/i);
    const filename = filenameMatch?.[1] || 'shot_llm_data.zip';
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  },

  downloadShotImageDataPackage: async (novelId: string, chapterId: string): Promise<void> => {
    const response = await fetch(`/api/novels/${novelId}/chapters/${chapterId}/download-shot-image-data`);
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || data.message || '打包分镜图数据失败');
    }
    const blob = await response.blob();
    const disposition = response.headers.get('content-disposition') || '';
    const filenameMatch = disposition.match(/filename="?([^";]+)"?/i);
    const filename = filenameMatch?.[1] || 'shot_image_data.zip';
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  },

  downloadCurrentShotImageDataPackage: async (novelId: string, chapterId: string, shotId: string): Promise<void> => {
    const response = await fetch(`/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/download-shot-image-data`);
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || data.message || '打包当前分镜图数据失败');
    }
    const blob = await response.blob();
    const disposition = response.headers.get('content-disposition') || '';
    const filenameMatch = disposition.match(/filename="?([^";]+)"?/i);
    const filename = filenameMatch?.[1] || 'current_shot_image_data.zip';
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  },

  /**
   * 更新分镜信息
   */
  updateShot: async (
    novelId: string,
    chapterId: string,
    shotId: string,
    data: ShotUpdateRequest
  ): Promise<{ success: boolean; data: Shot; message?: string }> => {
    const response = await fetch(`/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    return response.json();
  },

  /**
   * 生成分镜图片
   */
  generateImage: async (
    novelId: string,
    chapterId: string,
    shotId: string,
    options?: { prompt_text?: string; workflow_type?: 'shot' | 'shot_scene' | 'shot_character_scene' | 'shot_scene_prop' }
  ): Promise<{ success: boolean; data?: { taskId: string; status: string; promptText?: string | null }; message?: string }> => {
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/generate/`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt_text: options?.prompt_text || null, workflow_type: options?.workflow_type || null }),
      }
    );
    return response.json();
  },

  /**
   * 生成分镜视频
   */
  generateVideo: async (
    novelId: string,
    chapterId: string,
    shotId: string,
    options?: {
      use_keyframes?: boolean;
      use_reference_audio?: boolean;
      workflow_id?: string;
      selected_mode?: VideoMode;
    }
  ): Promise<{ success: boolean; data?: { taskId: string; status: string }; message?: string; detail?: string }> => {
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/generate-video`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          use_keyframes: options?.use_keyframes ?? true,
          use_reference_audio: options?.use_reference_audio ?? true,
          workflow_id: options?.workflow_id,
          selected_mode: options?.selected_mode,
        }),
      }
    );
    const data = await response.json();
    if (!response.ok) {
      return { success: false, message: data?.message || data?.detail || '生成失败', detail: data?.detail };
    }
    return data;
  },

  recommendVideoMode: async (
    novelId: string,
    chapterId: string,
    shotId: string,
    force = false
  ): Promise<{ success: boolean; data?: VideoDirectorPlan; message?: string }> => {
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/video-director/recommend`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ force }),
      }
    );
    return response.json();
  },

  saveVideoDirectorPlan: async (
    novelId: string,
    chapterId: string,
    shotId: string,
    plan: Partial<VideoDirectorPlan>
  ): Promise<{ success: boolean; data?: VideoDirectorPlan; message?: string }> => {
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/video-director`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(plan),
      }
    );
    return response.json();
  },

  planVideoKeyframes: async (
    novelId: string,
    chapterId: string,
    shotId: string,
    force = false
  ): Promise<{ success: boolean; data?: VideoDirectorPlan; message?: string; detail?: string }> => {
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/video-director/plan-keyframes`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ force }),
      }
    );
    const data = await response.json();
    if (!response.ok) {
      return { success: false, message: data?.message || data?.detail || '关键帧规划失败', detail: data?.detail };
    }
    return data;
  },

  generateVideoDirectorClip: async (
    novelId: string,
    chapterId: string,
    shotId: string,
    windowIndex: number,
    options?: { use_reference_audio?: boolean; auto_merge?: boolean }
  ): Promise<{ success: boolean; data?: { taskId: string; status: string }; message?: string; detail?: string }> => {
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/video-director/clips/${windowIndex}/generate`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          use_reference_audio: options?.use_reference_audio ?? true,
          auto_merge: options?.auto_merge ?? true,
        }),
      }
    );
    const data = await response.json();
    if (!response.ok) {
      return { success: false, message: data?.message || data?.detail || 'Clip 重新生成失败', detail: data?.detail };
    }
    return data;
  },

  mergeVideoDirectorClips: async (
    novelId: string,
    chapterId: string,
    shotId: string
  ): Promise<{ success: boolean; data?: { videoUrl?: string; videoDirectorPlan?: VideoDirectorPlan; skipped?: boolean }; message?: string; detail?: string }> => {
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/video-director/clips/merge`,
      { method: 'POST' }
    );
    const data = await response.json();
    if (!response.ok) {
      return { success: false, message: data?.message || data?.detail || '重新合并失败', detail: data?.detail };
    }
    return data;
  },

  /**
   * 上传分镜图片
   */
  uploadImage: async (
    novelId: string,
    chapterId: string,
    shotId: string,
    file: File
  ): Promise<{ success: boolean; data?: { imageUrl: string }; message?: string }> => {
    const formData = new FormData();
    formData.append('file', file);
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/upload-image`,
      { method: 'POST', body: formData }
    );
    return response.json();
  },

  editImage: async (
    novelId: string,
    chapterId: string,
    shotId: string,
    prompt: string
  ): Promise<{ success: boolean; data?: { imageUrl: string; taskId?: string }; message?: string; detail?: string }> => {
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/edit-image`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt }),
      }
    );
    const data = await response.json();
    if (!response.ok) {
      return { success: false, message: data?.message || data?.detail || '编辑分镜图片失败', detail: data?.detail };
    }
    return data;
  },

  replaceImage: async (
    novelId: string,
    chapterId: string,
    shotId: string,
    imageUrl: string
  ): Promise<{ success: boolean; data?: Shot; message?: string; detail?: string }> => {
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/replace-image`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image_url: imageUrl }),
      }
    );
    const data = await response.json();
    if (!response.ok) {
      return { success: false, message: data?.message || data?.detail || '替换分镜图片失败', detail: data?.detail };
    }
    return data;
  },

  editKeyframeImage: async (
    novelId: string,
    chapterId: string,
    shotId: string,
    frameIndex: number,
    prompt: string
  ): Promise<{ success: boolean; data?: { imageUrl: string; taskId?: string }; message?: string; detail?: string }> => {
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/keyframes/${frameIndex}/edit-image`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt }),
      }
    );
    const data = await response.json();
    if (!response.ok) {
      return { success: false, message: data?.message || data?.detail || '编辑关键帧图片失败', detail: data?.detail };
    }
    return data;
  },

  replaceKeyframeImage: async (
    novelId: string,
    chapterId: string,
    shotId: string,
    frameIndex: number,
    imageUrl: string
  ): Promise<{ success: boolean; data?: Shot; message?: string; detail?: string }> => {
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/keyframes/${frameIndex}/replace-image`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image_url: imageUrl }),
      }
    );
    const data = await response.json();
    if (!response.ok) {
      return { success: false, message: data?.message || data?.detail || '替换关键帧图片失败', detail: data?.detail };
    }
    return data;
  },

  /**
   * 生成分镜台词音频
   */
  generateAudio: async (
    novelId: string,
    chapterId: string,
    shotId: string,
    dialogues: DialogueData[]
  ): Promise<{ success: boolean; data?: any; message?: string }> => {
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/audio`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dialogues }),
      }
    );
    return response.json();
  },

  /**
   * 批量生成章节所有分镜音频
   */
  generateAllAudio: async (
    novelId: string,
    chapterId: string
  ): Promise<{ success: boolean; data?: any; message?: string }> => {
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/audio/generate-all`,
      { method: 'POST' }
    );
    return response.json();
  },

  /**
   * 上传台词音频
   */
  uploadDialogueAudio: async (
    novelId: string,
    chapterId: string,
    shotId: string,
    characterName: string,
    file: File
  ): Promise<{ success: boolean; data?: any; message?: string }> => {
    const formData = new FormData();
    formData.append('file', file);
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/dialogues/${encodeURIComponent(characterName)}/audio/upload`,
      { method: 'POST', body: formData }
    );
    return response.json();
  },

  /**
   * 删除台词音频
   */
  deleteDialogueAudio: async (
    novelId: string,
    chapterId: string,
    shotId: string,
    characterName: string
  ): Promise<{ success: boolean; data?: any; message?: string }> => {
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/dialogues/${encodeURIComponent(characterName)}/audio`,
      { method: 'DELETE' }
    );
    return response.json();
  },

  /**
   * 批量更新分镜
   */
  batchUpdateShots: async (
    novelId: string,
    chapterId: string,
    shots: any[]
  ): Promise<{ success: boolean; data?: { updated_count: number; shots: any[] }; message?: string }> => {
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/batch`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shots }),
      }
    );
    return response.json();
  },

  /**
   * 创建新分镜
   */
  createShot: async (
    novelId: string,
    chapterId: string,
    data: {
      description?: string;
      characters?: string[];
      scene?: string;
      props?: string[];
      duration?: number;
      continuity_mode?: string;
      dialogues?: DialogueData[];
      insert_index?: number;
    }
  ): Promise<{ success: boolean; data?: Shot; message?: string }> => {
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      }
    );
    return response.json();
  },

  /**
   * 删除分镜
   */
  deleteShot: async (
    novelId: string,
    chapterId: string,
    shotId: string
  ): Promise<{ success: boolean; data?: { deleted_shot_id: string; deleted_index: number }; message?: string }> => {
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}`,
      { method: 'DELETE' }
    );
    return response.json();
  },

  // ==================== 关键帧 API ====================

  /**
   * 生成关键帧描述
   */
  generateKeyframeDescriptions: async (
    novelId: string,
    chapterId: string,
    shotId: string,
    count: number = 3
  ): Promise<{ success: boolean; data?: { keyframes: any[] }; message?: string }> => {
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/keyframes/generate-descriptions`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ count }),
      }
    );
    return response.json();
  },

  /**
   * 生成关键帧图片
   */
  generateKeyframeImage: async (
    novelId: string,
    chapterId: string,
    shotId: string,
    frameIndex: number,
    workflowId?: string
  ): Promise<{ success: boolean; data?: { task_id: string }; message?: string }> => {
    const body: any = {};
    if (workflowId) body.workflow_id = workflowId;
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/keyframes/${frameIndex}/generate-image`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }
    );
    return response.json();
  },

  /**
   * 上传关键帧图片
   */
  uploadKeyframeImage: async (
    novelId: string,
    chapterId: string,
    shotId: string,
    frameIndex: number,
    file: File
  ): Promise<{ success: boolean; data?: { image_url: string }; message?: string }> => {
    const formData = new FormData();
    formData.append('file', file);
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/keyframes/${frameIndex}/upload-image`,
      { method: 'POST', body: formData }
    );
    return response.json();
  },

  /**
   * 上传关键帧参考图
   */
  uploadKeyframeReferenceImage: async (
    novelId: string,
    chapterId: string,
    shotId: string,
    frameIndex: number,
    file: File
  ): Promise<{ success: boolean; data?: { reference_image_url?: string; reference_url?: string }; message?: string }> => {
    const formData = new FormData();
    formData.append('file', file);
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/keyframes/${frameIndex}/upload-reference-image`,
      { method: 'POST', body: formData }
    );
    return response.json();
  },

  /**
   * 设置关键帧参考图
   */
  setKeyframeReferenceImage: async (
    novelId: string,
    chapterId: string,
    shotId: string,
    frameIndex: number,
    mode: 'auto_select' | 'custom' | 'none',
    referenceUrl?: string
  ): Promise<{ success: boolean; data?: { reference_image_url?: string | null; reference_url?: string | null }; message?: string }> => {
    const body: any = { mode };
    if (mode === 'custom' && referenceUrl) body.reference_url = referenceUrl;
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/keyframes/${frameIndex}/reference-image`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }
    );
    return response.json();
  },

  /**
   * 更新关键帧数据
   */
  updateKeyframes: async (
    novelId: string,
    chapterId: string,
    shotId: string,
    keyframes: any[]
  ): Promise<{ success: boolean; data?: { keyframes: any[] }; message?: string }> => {
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/keyframes`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ keyframes }),
      }
    );
    return response.json();
  },

  // ==================== 音频参考 API ====================

  /**
   * 合并台词音频作为参考音频
   */
  mergeDialogueAudio: async (
    novelId: string,
    chapterId: string,
    shotId: string
  ): Promise<{ success: boolean; audio_url?: string; duration?: number; message?: string }> => {
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/merge-audio`,
      { method: 'POST' }
    );
    return response.json();
  },

  /**
   * 上传参考音频
   */
  uploadReferenceAudio: async (
    novelId: string,
    chapterId: string,
    shotId: string,
    file: File
  ): Promise<{ success: boolean; audio_url?: string; message?: string }> => {
    const formData = new FormData();
    formData.append('file', file);
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/upload-reference-audio`,
      { method: 'POST', body: formData }
    );
    return response.json();
  },

  /**
   * 设置参考音频来源
   */
  setReferenceAudio: async (
    novelId: string,
    chapterId: string,
    shotId: string,
    mode: 'none' | 'merged' | 'uploaded' | 'character',
    characterName?: string
  ): Promise<{ success: boolean; audio_url?: string; message?: string }> => {
    const body: any = { mode };
    if (mode === 'character' && characterName) body.character_name = characterName;
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/set-reference-audio`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }
    );
    return response.json();
  },
};
