/**
 * 分镜相关 API
 */
import { api } from './index';

// 分镜台词数据
export interface DialogueData {
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
  createdAt: string | null;
  updatedAt: string | null;
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
    shotIndex: number
  ): Promise<{ success: boolean; data?: { taskId: string; status: string }; message?: string }> => {
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotIndex}/generate/`,
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
    shotIndex: number
  ): Promise<{ success: boolean; data?: { taskId: string; status: string }; message?: string }> => {
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotIndex}/generate-video/`,
      { method: 'POST' }
    );
    return response.json();
  },

  /**
   * 上传分镜图片
   */
  uploadImage: async (
    novelId: string,
    chapterId: string,
    shotIndex: number,
    file: File
  ): Promise<{ success: boolean; data?: { imageUrl: string }; message?: string }> => {
    const formData = new FormData();
    formData.append('file', file);
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotIndex}/upload-image`,
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
    shotIndex: number,
    dialogues: DialogueData[]
  ): Promise<{ success: boolean; data?: any; message?: string }> => {
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotIndex}/audio`,
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
    shotIndex: number,
    characterName: string,
    file: File
  ): Promise<{ success: boolean; data?: any; message?: string }> => {
    const formData = new FormData();
    formData.append('file', file);
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotIndex}/dialogues/${encodeURIComponent(characterName)}/audio/upload`,
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
    shotIndex: number,
    characterName: string
  ): Promise<{ success: boolean; data?: any; message?: string }> => {
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotIndex}/dialogues/${encodeURIComponent(characterName)}/audio`,
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
};