/**
 * 分镜相关 API
 */
import { api } from './index';
import { downloadQueuedShotExport } from './shotExports';

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
  hdVideoUrl: string | null;
  hdVideoStatus: 'pending' | 'generating' | 'completed' | 'failed';
  hdVideoTaskId: string | null;
  hdVideoSourceTaskId: string | null;
  hdVideoMegapixels: number | null;
  hdVideoVariants: HdVideoVariant[];
  mergedCharacterImage: string | null;
  mergedPropImage: string | null;
  dialogues: DialogueData[];
  keyframes?: KeyframeData[];
  referenceAudioUrl?: string | null;
  referenceAudioType?: string;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface HdVideoExecution {
  id: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  videoUrl?: string | null;
  targetMegapixels: number;
  sourceTaskId?: string | null;
  parentTaskId?: string | null;
  progress: number;
  currentStep?: string | null;
  errorMessage?: string | null;
  createdAt?: string | null;
  startedAt?: string | null;
  completedAt?: string | null;
}

export interface HdVideoVariant {
  targetMegapixels: number;
  status: HdVideoExecution['status'];
  videoUrl?: string | null;
  taskId?: string | null;
  latestCompletedTaskId?: string | null;
  sourceTaskId?: string | null;
  errorMessage?: string | null;
  executions: HdVideoExecution[];
}

/** @deprecated Historical noncanonical Video Director plans only. */
export type VideoMode = 'SINGLE_FRAME' | 'FIRST_LAST_FRAME' | 'MULTI_KEYFRAME';

export type CanonicalVisualStateRole = 'START' | 'INTERMEDIATE' | 'END';

export interface CanonicalVisualState {
  index: number;
  time_seconds: number;
  role: CanonicalVisualStateRole;
  description?: string | null;
  /** #08 eligible timed-image candidate, not execution-required or selected. */
  timed_visual_target?: boolean;
  image_url?: string | null;
  image_task_id?: string | null;
  prompt_text?: string | null;
}

export interface CanonicalVisualTransition {
  segment_index?: number;
  from_keyframe_index?: number;
  to_keyframe_index?: number;
  start_time?: number;
  end_time?: number;
  transition_description?: string | null;
  [key: string]: any;
}

export type SemanticClipCapability = 'GENERATE' | 'EXTEND' | 'TEMPORAL_EXTEND';

export interface SemanticClipPlan {
  visual_state_reference_config?: { enabled_state_ids: string[] } | null;
  clip_index: number;
  start_time: number;
  end_time: number;
  planned_duration?: number;
  planning_mode?: string;
  capability: SemanticClipCapability;
  continuity_to_previous?: 'NONE' | 'CUT' | 'CONTINUOUS';
  previous_clip_index?: number | null;
  visual_state_indexes?: number[];
  carry_in_state_index?: number | null;
  requires_temporal_control?: boolean;
  temporal_anchor_ids?: string[];
  selected_temporal_target_ids?: string[];
  early_composition_state_id?: string | null;
  clip_id?: string;
  generated_by_task_id?: string;
  video_url?: string | null;
  local_path?: string | null;
  source_video_url?: string | null;
  execution_status?: string;
  approval_mode?: string;
  approval_status?: string;
  status?: string;
  error_message?: string | null;
  prompt_text?: string;
  dialogue_assignment?: Array<Record<string, any>>;
  [key: string]: any;
}

export interface PlanSemanticClipsRequest {
  temporal_anchors?: Array<Record<string, any>>;
  approval_mode?: 'AUTO_APPROVE' | 'REVIEW_REQUIRED';
  force?: boolean;
}

export interface PlanSemanticClipsResult {
  clips: SemanticClipPlan[];
  validation: {
    passed?: boolean;
    findings?: Array<{ code?: string; severity?: string; message?: string }>;
    [key: string]: any;
  };
  revision?: number;
  temporal_anchors?: VideoDirectorPlan['temporal_anchors'];
  execution_readiness?: VideoDirectorPlan['execution_readiness'];
}

export interface VideoAiCall {
  step?: string;
  title?: string;
  task_type?: string;
  prompt_template_name?: string;
  status?: string;
  error_message?: string;
  input_summary?: string;
  response?: string;
  parsed_result?: any;
  final_prompt?: string | null;
  clip_index?: number | null;
  workflow_type?: string | null;
  workflow_name?: string | null;
  reference_images?: Array<{ label?: string; url?: string }> | null;
  submitted_reference_bindings?: Array<{ picture?: number; sources?: string[]; node_id?: string; filename?: string }> | null;
  task_id?: string;
  created_at?: string;
}

export interface CanonicalImageProvenance {
  shot_id: string;
  clip_plan_revision: number;
  state_index: number;
  state_id: string;
  state_fingerprint: string;
}
export interface RequiredExecutionImage {
  kind: 'SELECTED_TEMPORAL_TARGET' | 'EARLY_COMPOSITION' | 'GENERATE_VISUAL_START';
  state_index: number;
  state_id: string;
  shot_time: number;
  description?: string;
  consumer_clip_index: number;
  consumer_clip_indexes: number[];
  clip_local_time?: number | null;
  image_source: string;
  image_url?: string | null;
  ready: boolean;
  missing: boolean;
  provenance: CanonicalImageProvenance;
  active_task?: { task_id: string; status: string; current_step?: string | null; error_message?: string | null } | null;
  failure?: { task_id: string; status: string; error_message?: string | null } | null;
  consumers: Array<{ consumer_clip_index: number; kind: string; clip_local_time?: number | null; image_url?: string | null; ready: boolean }>;
}
export interface PrepareRequiredImageItem {
  state_index: number;
  state_id: string;
  consumer_clip_indexes: number[];
  status: 'READY' | 'REUSED' | 'QUEUED' | 'FAILED';
  task_id?: string | null;
  reason?: string;
}
export interface PrepareRequiredImagesResult { items: PrepareRequiredImageItem[]; shot: Shot }

export interface VideoDirectorPlan {
  required_execution_images?: RequiredExecutionImage[];
  clip_execution_readiness?: Array<{ clip_index: number; images_ready: boolean; ready: boolean; code: string; previous_clip_index?: number | null }>;
  canonical_visual_plan?: boolean;
  /** @deprecated Historical noncanonical plans only; never canonical authority. */
  selected_mode?: VideoMode;
  /** @deprecated Historical noncanonical plans only; never canonical authority. */
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
  keyframes?: CanonicalVisualState[];
  transitions?: CanonicalVisualTransition[];
  clips?: Array<{
    clip_index: number;
    start_time: number;
    end_time: number;
    frame_count?: number;
    /** @deprecated Historical fixed-frame clip metadata only. */
    selected_frame_count?: number;
    workflow_key?: string;
    workflow_type?: string;
    /** @deprecated Use semantic clip visual_state_indexes for canonical ownership. */
    keyframe_indexes?: number[];
    status?: string;
    prompt_text?: string;
  }>;
  execution_windows?: Array<{
    window_index: number;
    start_time: number;
    end_time: number;
  }>;
  /** @deprecated Historical MULTI_KEYFRAME planning only. */
  window_plans?: Array<{
    window_index: number;
    start_time: number;
    end_time: number;
    /** @deprecated Historical fixed-frame window metadata only. */
    selected_frame_count: 3 | 4;
    workflow_key?: string;
    workflow_type?: string;
    workflow_name?: string;
    /** @deprecated Historical window membership only. */
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
  clip_plan_revision?: number;
  temporal_anchors?: Array<{
    anchor_id: string;
    time_seconds: number;
    image_url?: string;
    source?: { type?: string; id?: string; keyframe_index?: number; image_task_id?: string; [key: string]: any };
    description?: string;
  }>;
  assembly_status?: string;
  assembly_mode?: string;
  assembly_clip_plan_revision?: number;
  assembly_task_ids?: string[];
  assembled_result?: { status?: string; url?: string; assembled_media_duration?: number | null; clip_plan_revision?: number } | null;
  clip_plan_approval_mode?: string;
  clip_plan_validation?: {
    passed?: boolean;
    findings?: Array<{ code?: string; severity?: string; message?: string }>;
    dialogue_ownership?: { passed?: boolean; [key: string]: any };
    [key: string]: any;
  };
  clip_plan_findings?: Array<{ code?: string; severity?: string; message?: string }>;
  clip_plan?: SemanticClipPlan[];
  execution_readiness?: {
    ready: boolean;
    code?: string;
    message?: string | null;
    blocking_clips?: Array<{
      ready: boolean;
      applicable?: boolean;
      code?: string;
      message?: string | null;
      clip_index?: number | null;
      visual_state_index?: number | null;
      time_seconds?: number | null;
      grounding_source?: 'KEYFRAME_IMAGE' | 'SHOT_IMAGE' | null;
      image_url?: string | null;
    }>;
  };
  ai_calls?: VideoAiCall[];
  validation?: Record<string, any>;
}

// 关键帧数据
export interface KeyframeData {
  frame_index: number;
  description: string;
  image_url?: string;
  image_task_id?: string;
  prompt_text?: string;
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
  getShot: async (novelId: string, chapterId: string, shotId: string, signal?: AbortSignal): Promise<{ success: boolean; data: Shot; message?: string }> => {
    const response = await fetch(`/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}`, { signal });
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

  downloadShotVideoMaterialsPackage: async (novelId: string, chapterId: string, shotId: string, sections?: string[], onProgress?: (message: string) => void): Promise<void> => {
    if (sections && sections.length === 0) throw new Error('请至少选择一个导出项');
    const params = new URLSearchParams();
    sections?.forEach(section => params.append('include', section));
    await downloadQueuedShotExport(`/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}`, params, onProgress);
  },

  resetShotVideoData: async (novelId: string, chapterId: string, shotId: string): Promise<{ success: boolean; message?: string; detail?: string }> => {
    const response = await fetch(`/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/reset-video-data`, { method: 'POST' });
    const text = await response.text();
    let data: any = {};
    try { data = text ? JSON.parse(text) : {}; } catch { data = { message: text }; }
    if (!response.ok) throw new Error(data.detail || data.message || '重置当前 Shot 视频数据失败');
    return data;
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
  ): Promise<{
    success: boolean;
    data?: { taskId: string; status: string; promptText?: string | null };
    message?: string;
    detail?: string | { code?: string; message?: string; available_reference_count?: number; missing?: Record<string, string[]> };
  }> => {
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/generate/`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt_text: options?.prompt_text || null, workflow_type: options?.workflow_type || null }),
      }
    );
    const result = await response.json();
    if (!response.ok) {
      const detailMessage = typeof result.detail === 'object' ? result.detail?.message : result.detail;
      return { success: false, message: detailMessage || result.message || '生成失败', detail: result.detail };
    }
    return result;
  },

  generateImagesBatch: async (
    novelId: string,
    chapterId: string,
    options: { shot_ids: string[]; skip_llm_when_prompt_exists?: boolean }
  ): Promise<{
    success: boolean;
    data?: { batchTaskId: string; tasks: Array<{ taskId: string; shotId: string; status: string }> };
    message?: string;
    detail?: string | { code?: string; message?: string; shot_id?: string; available_reference_count?: number; missing?: Record<string, string[]> };
  }> => {
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shot-images/batch`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          shot_ids: options.shot_ids,
          skip_llm_when_prompt_exists: options.skip_llm_when_prompt_exists ?? true,
        }),
      }
    );
    const result = await response.json();
    if (!response.ok) {
      const detailMessage = typeof result.detail === 'object' ? result.detail?.message : result.detail;
      return { success: false, message: detailMessage || result.message || '批量生成分镜图失败', detail: result.detail };
    }
    return result;
  },

  generateVideosBatch: async (
    novelId: string,
    chapterId: string,
    options: {
      shot_ids: string[];
      auto_complete_details?: boolean;
      use_reference_audio?: boolean;
      optimize_h3_prompt?: boolean; skip_llm_when_prompt_exists?: boolean;
      force_rerun?: boolean;
      auto_assemble?: boolean;
    }
  ): Promise<{ success: boolean; data?: { batchTaskId: string; tasks: Array<{ taskId: string; shotId: string; status: string }> }; message?: string; detail?: string }> => {
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shot-videos/batch`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          shot_ids: options.shot_ids,
          auto_complete_details: options.auto_complete_details ?? true,
          use_reference_audio: options.use_reference_audio ?? true,
          skip_llm_when_prompt_exists: options.skip_llm_when_prompt_exists ?? false,
          optimize_h3_prompt: options.optimize_h3_prompt ?? false,
          force_rerun: options.force_rerun ?? true,
          auto_assemble: options.auto_assemble ?? true,
        }),
      }
    );
    const responseText = await response.text();
    let data: any;
    try {
      data = responseText ? JSON.parse(responseText) : {};
    } catch {
      data = { message: responseText || `HTTP ${response.status}` };
    }
    if (!response.ok) {
      return { success: false, message: data?.message || data?.detail || '批量生成视频失败', detail: data?.detail };
    }
    return data;
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
      optimize_h3_prompt?: boolean; skip_llm_when_prompt_exists?: boolean;
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
          skip_llm_when_prompt_exists: options?.skip_llm_when_prompt_exists ?? false,
          optimize_h3_prompt: options?.optimize_h3_prompt ?? false,
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

  saveClipVisualStateReferences: async (
    novelId: string, chapterId: string, shotId: string, clipIndex: number,
    enabledStateIds: string[], expectedPlanRevision: number,
  ): Promise<{ success: boolean; data?: Shot; message?: string }> => {
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/video-director/clips/${clipIndex}/visual-state-references`,
      { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
        enabled_state_ids: enabledStateIds, expected_plan_revision: expectedPlanRevision,
      }) },
    );
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : result.detail?.message || '保存视觉状态选择失败');
    return result;
  },

  saveVisualStateDescription: async (
    novelId: string, chapterId: string, shotId: string, stateIndex: number,
    description: string, expectedDescription: string, expectedPlanRevision: number,
  ): Promise<{ success: boolean; data?: { description: string; shotDescription: string; videoDirectorPlan: VideoDirectorPlan; keyframes: any[] }; message?: string }> => {
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/video-director/states/${stateIndex}/description`,
      { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
        description, expected_description: expectedDescription, expected_plan_revision: expectedPlanRevision,
      }) },
    );
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : result.detail?.message || '保存视觉状态描述失败');
    return result;
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

  planVideoClips: async (
    novelId: string,
    chapterId: string,
    shotId: string,
    options: PlanSemanticClipsRequest = {},
  ): Promise<{ success: boolean; data?: PlanSemanticClipsResult; message?: string; detail?: string }> => {
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/video-director/plan-clips`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          temporal_anchors: options.temporal_anchors ?? [],
          approval_mode: options.approval_mode ?? 'AUTO_APPROVE',
          force: options.force ?? false,
        }),
      },
    );
    const data = await response.json();
    if (!response.ok) {
      return { success: false, message: data?.message || data?.detail || '视频片段规划失败', detail: data?.detail };
    }
    return data;
  },

  generateVideoDirectorClip: async (
    novelId: string,
    chapterId: string,
    shotId: string,
    windowIndex: number,
    options?: { use_reference_audio?: boolean; auto_merge?: boolean; optimize_h3_prompt?: boolean; skip_llm_when_prompt_exists?: boolean; clip_plan_revision?: number }
  ): Promise<{ success: boolean; data?: { taskId: string; status: string }; message?: string; detail?: string }> => {
    const response = await fetch(
      `/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/video-director/clips/${windowIndex}/generate`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          use_reference_audio: options?.use_reference_audio ?? true,
          auto_merge: options?.auto_merge ?? true,
          skip_llm_when_prompt_exists: options?.skip_llm_when_prompt_exists ?? false,
          optimize_h3_prompt: options?.optimize_h3_prompt ?? false,
          clip_plan_revision: options?.clip_plan_revision,
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
  prepareRequiredImages: async (novelId: string, chapterId: string, shotId: string, revision: number, clipIndexes?: number[], stateIndexes?: number[]) =>
    api.post<PrepareRequiredImagesResult>(`/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/video-director/prepare-required-images`, {
      clip_plan_revision: revision, clip_indexes: clipIndexes, state_indexes: stateIndexes,
    }),

  generateKeyframeImage: async (
    novelId: string,
    chapterId: string,
    shotId: string,
    frameIndex: number,
    workflowId?: string,
    options?: { skip_llm_when_prompt_exists?: boolean }
  ): Promise<{ success: boolean; data?: { task_id: string }; message?: string; detail?: string }> => {
    const body: any = {};
    if (workflowId) body.workflow_id = workflowId;
    if (options?.skip_llm_when_prompt_exists !== undefined) {
      body.skip_llm_when_prompt_exists = options.skip_llm_when_prompt_exists;
    }
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

  getHdRepaintSource: async (novelId: string, chapterId: string, shotId: string) => {
    const response = await fetch(`/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/hd-repaint/source`);
    const data = await response.json();
    if (!response.ok) return { success: false, message: data?.detail || '无法读取 Replay Source' };
    return data;
  },

  createHdRepaint: async (novelId: string, chapterId: string, shotId: string, targetMegapixels: number) => {
    const response = await fetch(`/api/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/hd-repaint`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target_megapixels: targetMegapixels }),
    });
    const data = await response.json();
    if (!response.ok) return { success: false, message: data?.detail || '高清重绘任务创建失败' };
    return data;
  },

  createHdRepaintBatch: async (novelId: string, chapterId: string, shotIds: string[], targetMegapixels: number) => {
    const response = await fetch(`/api/novels/${novelId}/chapters/${chapterId}/hd-repaints/batch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ shot_ids: shotIds, target_megapixels: targetMegapixels }),
    });
    const data = await response.json();
    if (!response.ok) return { success: false, message: data?.detail || '批量高清重绘任务创建失败' };
    return data;
  },

  getLatestHdRepaintBatch: async (novelId: string, chapterId: string, targetMegapixels?: number) =>
    api.get<any>(`/novels/${novelId}/chapters/${chapterId}/hd-repaints/latest${targetMegapixels == null ? '' : `?target_megapixels=${targetMegapixels}`}`),

  retryFailedHdRepaints: async (novelId: string, chapterId: string, batchId: string) =>
    api.post(`/novels/${novelId}/chapters/${chapterId}/hd-repaints/${batchId}/retry-failed`),

  mergeChapterVideos: async (novelId: string, chapterId: string, shotIds: string[], videoVariant: 'draft' | 'hd', targetMegapixels?: number) => {
    const response = await fetch(`/api/novels/${novelId}/chapters/${chapterId}/merge-videos`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: 'shots_only', shot_ids: shotIds, video_variant: videoVariant, target_megapixels: targetMegapixels }),
    });
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
