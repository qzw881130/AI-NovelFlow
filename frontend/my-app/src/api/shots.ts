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
  characters: string[];
  scene: string;
  props: string[];
  duration: number;
  imageUrl: string | null;
  imagePath: string | null;
  imageStatus: 'pending' | 'generating' | 'completed' | 'failed';
  imageTaskId: string | null;
  videoUrl: string | null;
  videoStatus: 'pending' | 'generating' | 'completed' | 'failed';
  videoTaskId: string | null;
  mergedCharacterImage: string | null;
  dialogues: DialogueData[];
  keyframes?: KeyframeData[];
  referenceAudioUrl?: string | null;
  referenceAudioType?: string;
  createdAt: string | null;
  updatedAt: string | null;
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
  characters?: string[];
  scene?: string;
  props?: string[];
  duration?: number;
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
    shotId: string
  ): Promise<{ success: boolean; data?: { taskId: string; status: string }; message?: string }> => {
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/generate/`,
      { method: 'POST' }
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
    }
  ): Promise<{ success: boolean; data?: { taskId: string; status: string }; message?: string }> => {
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/generate-video`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          use_keyframes: options?.use_keyframes ?? true,
          use_reference_audio: options?.use_reference_audio ?? true,
          workflow_id: options?.workflow_id,
        }),
      }
    );
    return response.json();
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