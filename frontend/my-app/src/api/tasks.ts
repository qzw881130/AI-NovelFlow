/**
 * 任务相关 API
 */
import { api, API_BASE } from './index';

/** Read-only projection of persisted Clip physical metadata. */
export interface ClipPhysicalOutput {
  physical_output_role?: string;
  output_node_id?: string;
  result_url?: string;
  source_video_url?: string;
  fps?: number;
  timebase?: string;
  overlap_frames?: number;
  overlap_duration?: number;
  native_cumulative_duration?: number;
  raw_context_output?: { physical_output_role?: string; output_node_id?: string; result_url?: string; source_video_url?: string };
}

export interface ComfyUIError {
  error_code: string;
  stage: string;
  effective_url?: string | null;
  configured_url?: string | null;
  underlying_error: string;
  http_status?: number | null;
  attempts: number;
  prompt_submitted: boolean;
  proxy?: string | null;
}

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
  referenceImages?: Array<{ label?: string; url: string }>;
  parentTaskId?: string | null;
  errorMessage?: string | null;
  comfyuiError?: ComfyUIError | null;
  completedAt?: string | null;
  currentStep?: string | null;
  shotImageQuality?: { generation_count?: number; max_generations?: number; status?: 'PASS' | 'WARNING' | 'FAIL' | 'ERROR'; attempts?: Array<{ number: number; image_url: string; review_id?: string | null; verdict: string }> } | null;
  canonicalImageProvenance?: import('./shots').CanonicalImageProvenance | null;
  clipExecution?: {
    clip_playback?: { independent_url?: string | null; review_url?: string | null } | null;
    execution_scope?: string;
    clip_id?: string;
    clip_index?: number;
    clip_plan_revision?: number;
    capability?: string;
    artifact_kind?: string;
    physical_output?: ClipPhysicalOutput;
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
    video_reference_manifest?: { references?: Array<{
      slot?: number; kind?: string; source_type?: string; source_keyframe_index?: number;
      image_url?: string; binding?: { uploaded_filename?: string | null; workflow_node_id?: string | null };
    }> };
    execution_contract?: {
      artifact_kind?: string;
      capability?: string;
      previous_clip?: {
        clip_index?: number; clip_plan_revision?: number; generated_by_task_id?: string;
        result_url?: string; physical_output?: ClipPhysicalOutput;
      };
      temporal_anchor_manifest?: { anchors?: Array<{
      anchor_id?: string; slot?: number; time_seconds?: number; frame_position?: number; image_url?: string;
      source?: { type?: string; id?: string; keyframe_index?: number };
    }> } };
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
  ordinaryReferenceCount?: number | null;
}

export interface TaskPage {
  items: Task[];
  total: number;
  total_pages: number;
  stats: { all: number; pending: number; running: number; completed: number; failed: number; cancelled: number };
  types: string[];
}

type TaskReferences = Pick<Task, 'id' | 'status' | 'referenceImages'>;
const referenceTaskRequests = new Map<string, Promise<{ success: boolean; data?: TaskReferences; message?: string }>>();

export const taskApi = {
  fetchPage: (page: number, pageSize: number, status: string, type: string, signal?: AbortSignal) => {
    const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    if (status !== 'all') params.set('status', status);
    if (type !== 'all') params.set('type', type);
    return api.get<TaskPage>(`/tasks/page?${params}`, { signal });
  },
  /** 获取任务列表 */
  fetchList: (limit = 1000) => api.get<Task[]>(`/tasks/?limit=${limit}`),

  /** Get tasks attached to a single Shot, including Clip-scoped metadata. */
  fetchShotTasks: (chapterId: string, shotId: string, signal?: AbortSignal) =>
    api.get<Task[]>(`/tasks/?chapter_id=${encodeURIComponent(chapterId)}&shot_id=${encodeURIComponent(shotId)}&type=shot_video&summary=true&limit=100`, { signal }),

  /** 获取单个任务 */
  fetch: (id: string, signal?: AbortSignal) => api.get<Task>(`/tasks/${id}`, { signal }),

  /** A completed image task's input references are immutable; share the read across mounts. */
  fetchReferences: (id: string) => {
    const pending = referenceTaskRequests.get(id);
    if (pending) return pending;
    const request = api.get<TaskReferences>(`/tasks/${id}?references_only=true`);
    referenceTaskRequests.set(id, request);
    request.then(result => {
      if (!result.success || result.data?.status !== 'completed') referenceTaskRequests.delete(id);
    }).catch(() => referenceTaskRequests.delete(id));
    return request;
  },

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

  /** Let the browser stream the workflow ZIP directly, including large reference videos. */
  downloadWorkflowArchive: (id: string, windowIndex?: number | null) => {
    const path = windowIndex == null
      ? `/tasks/${encodeURIComponent(id)}/workflow/archive`
      : `/tasks/${encodeURIComponent(id)}/clips/${windowIndex}/workflow/archive`;
    const link = document.createElement('a');
    link.href = `${API_BASE}${path}`;
    link.download = `workflow_${id}${windowIndex == null ? '' : `_clip_${windowIndex}`}.zip`;
    document.body.appendChild(link);
    link.click();
    link.remove();
  },

  /** 重试任务 */
  retry: (id: string) => api.post(`/tasks/${id}/retry/`),
};
