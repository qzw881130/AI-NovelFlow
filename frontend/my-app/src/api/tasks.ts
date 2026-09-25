/**
 * 任务相关 API
 */
import { api } from './index';

export interface Task {
  id: string;
  type: string;
  status: string;
  progress: number;
  novel_id: string;
  chapter_id: string;
  character_id: string;
  scene_id: string;
  shot_id: string;
  error_message: string;
  created_at: string;
  updated_at: string;
  workflow_id?: string;
  name?: string;
  workflowName?: string;
  resultUrl?: string | null;
  completedAt?: string | null;
  clipExecution?: {
    execution_scope?: string;
    clip_id?: string;
    clip_index?: number;
    clip_plan_revision?: number;
    capability?: string;
    planned_duration?: number;
    requested_duration?: number;
    actual_duration?: number | null;
    assembled_media_duration?: number | null;
    assembled_result?: { status?: string; url?: string; assembled_media_duration?: number | null; clip_index?: number; task_id?: string } | null;
    approval_status?: string;
    approval_mode?: string;
    previous_approved_task_id?: string | null;
    previous_approved_video_url?: string | null;
    previous_approved_video_source?: string | null;
    temporal_anchor_ids?: string[];
    dialogue_assignment?: Array<{
      dialogue_id: string;
      segment_index: number;
      speaker: string;
      text: string;
      estimated_duration: number;
      is_continuation: boolean;
      continues_in_next_clip: boolean;
    }>;
  } | null;
}

export const taskApi = {
  /** 获取任务列表 */
  fetchList: (limit = 1000) => api.get<Task[]>(`/tasks/?limit=${limit}`),

  /** Get tasks attached to a single Shot, including Clip-scoped metadata. */
  fetchShotTasks: (chapterId: string, shotId: string) =>
    api.get<Task[]>(`/tasks/?chapter_id=${encodeURIComponent(chapterId)}&shot_id=${encodeURIComponent(shotId)}&type=shot_video&limit=100`),

  /** 获取单个任务 */
  fetch: (id: string) => api.get<Task>(`/tasks/${id}/`),

  /** 删除任务 */
  delete: (id: string) => api.delete(`/tasks/${id}/`),

  /** 取消任务 */
  cancel: (id: string) => api.post(`/tasks/${id}/cancel`),

  /** 取消所有任务 */
  cancelAll: () => api.post('/tasks/cancel-all/'),

  /** 获取任务工作流 */
  fetchWorkflow: (id: string) => api.get(`/tasks/${id}/workflow/`),

  /** 获取多 Clip 任务中单个 Clip 的实际工作流 */
  fetchClipWorkflow: (id: string, windowIndex: number) => api.get(`/tasks/${id}/clips/${windowIndex}/workflow/`),

  /** 重试任务 */
  retry: (id: string) => api.post(`/tasks/${id}/retry/`),
};
