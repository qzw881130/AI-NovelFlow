/**
 * 分镜类型定义
 */

// 分镜台词数据
export interface DialogueData {
  character_name: string;
  text: string;
  emotion_prompt?: string;
  audio_url?: string;
  audio_task_id?: string;
  audio_source?: 'ai_generated' | 'uploaded';
}

// 分镜状态
export type ShotStatus = 'pending' | 'generating' | 'completed' | 'failed';

// 分镜数据
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
  imageStatus: ShotStatus;
  imageTaskId: string | null;
  videoUrl: string | null;
  videoStatus: ShotStatus;
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

// 转场视频数据
export interface TransitionVideo {
  key: string; // "1-2", "2-3" 等
  url: string;
}

// 分镜工作流
export interface ShotWorkflow {
  id: string;
  name: string;
  isActive: boolean;
  nodeMapping?: {
    character_reference_image_node_id?: string;
    scene_reference_image_node_id?: string;
    prop_reference_image_node_id?: string;
    [key: string]: string | undefined;
  };
}

// 音频任务
export interface AudioTask {
  shotIndex: number;
  characterName: string;
  taskId: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
}

// 音频警告
export interface AudioWarning {
  shot_index?: number;
  character_name: string;
  reason: string;
}