/**
 * 任务相关 API
 */

import { get, post, del } from './client';

export interface Task {
  id: number;
  type: 'shot_image' | 'shot_video' | 'transition_video' | 'character_image' | 'scene_image';
  status: 'pending' | 'running' | 'completed' | 'failed';
  novel_id?: number;
  chapter_id?: number;
  shot_id?: number;
  result_url?: string;
  error_message?: string;
  created_at: string;
  updated_at: string;
}

export const taskApi = {
  /**
   * 获取任务列表
   */
  list: (params?: {
    type?: string;
    status?: string;
    novel_id?: number;
    chapter_id?: number;
    limit?: number;
  }) => get<Task[]>('/tasks/', params),
  
  /**
   * 获取任务详情
   */
  get: (id: number) => get<Task>(`/tasks/${id}/`),
  
  /**
   * 删除任务
   */
  delete: (id: number) => del<void>(`/tasks/${id}/`),
  
  /**
   * 重试任务
   */
  retry: (id: number) => post<void>(`/tasks/${id}/retry/`),
  
  /**
   * 批量删除任务
   */
  batchDelete: (ids: number[]) => post<void>('/tasks/batch-delete/', { ids }),
};

export default taskApi;
