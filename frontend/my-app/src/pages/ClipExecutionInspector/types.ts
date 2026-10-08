export type SourceStatus = 'EXPLICIT' | 'CURRENT_PLAN' | 'EXECUTION_SNAPSHOT' | 'FINAL_PROMPT' | 'ABSENT' | 'SOURCE_NOT_AVAILABLE' | 'DEGRADED';
export interface SourceRef { kind: string; status: SourceStatus; entity_id: string; path: string; content_hash: string; source_revision: number | null; observed_at: string; relation_to_execution: string; text_start?: number; text_end?: number }
export interface InspectorEvent { id: string; type: string; label: string; start: number | null; end: number | null; timing_kind: string; payload: Record<string, any>; source_refs: SourceRef[]; native_frame_index0?: number }
export interface FrameSample {
  sample_id: string; artifact_id: string; status: string; requested_time?: number; native_frame_index0: number;
  local_frame_index0: number | null; h3_position1: number | null; native_pts: number; sample_clip_time: number | null; sample_time: number;
  requested_times: Array<{ time: number; reason: string; event_id: string | null; quantization_error?: number; boundary_behavior?: string }>;
  reasons: string[]; event_refs: string[]; image_url: string; detail_url: string;
}
export interface Projection {
  projection_version: number;
  clip_ref: { novel_id: string; chapter_id: string; shot_id: string; shot_index: number; clip_index: number; clip_plan_revision: number | null; legacy: boolean };
  artifact: { task_id: string; artifact_id: string; video_sha256: string | null; result_url: string; capability: string; artifact_kind: string; identity_status: string; comfyui_prompt_id: string | null; workflow_sha256: string; prompt_sha256: string };
  execution: { task_id: string; status: string; seed: number | null; comfyui_prompt_id: string | null; shot_start: number | null; shot_end: number | null; planned_duration: number | null; timing_source_status: SourceStatus; requested_duration: number | null; requested_latent_frame_count: number | null; previous_av: Record<string, any> | null; created_at: string | null; completed_at: string | null };
  plan_context: { status: SourceStatus; revision: number | null; plan_hash: string; carry_in_state_index: number | null; owned_visual_state_indexes: number[]; source: SourceRef };
  media: { status: SourceStatus; reason?: string; frame_count?: number; fps?: string; fps_numerator?: number; fps_denominator?: number; is_cfr?: boolean; pts_monotonic?: boolean; pts?: number[]; pts_exact?: string[]; video_duration?: number; video_stream_duration?: number; audio_duration?: number | null; container_duration?: number; stream_time_base?: string; width?: number; height?: number; warnings: string[] };
  time_mapping: { status: SourceStatus; mode: string; time_domain: string; planned_duration: number | null; axis_duration: number | null; window_duration?: number; origin_frame_index0: number | null; origin_native_pts: number | null; overlap_frames?: number; replacement_frames?: number; net_new_frames?: number; warnings: string[] };
  events: InspectorEvent[];
  authority_items: Array<{ title: string; status: SourceStatus; presence: string; submitted_verified: boolean; message?: string; sections: Array<{ text: string; text_start: number; text_end: number; source: SourceRef }> }>;
  availability: Array<{ name: string; status: SourceStatus; reasons?: string[] }>;
  conflicts: Array<Record<string, any>>; warnings: string[];
  references: { ordinary: Array<Record<string, any>>; temporal_anchors: Array<Record<string, any>>; previous_av: Record<string, any> | null; source: SourceRef };
  submitted: Record<string, any>; historical_auxiliary: Array<Record<string, any>>;
}
export interface SamplingManifest {
  task_id: string; artifact_id: string; video_sha256: string;
  manifest_id: string; sampling_version: number; render_version: string; mapping_version: number; time_domain: string;
  samples: FrameSample[]; offset: number; next_offset: number | null; unique_frame_count: number; requested_count: number; deduplicated_count: number;
  unresolved: Array<{ time: number; reason: string; status: string }>; spec: Record<string, any>;
}
export interface Observation {
  observation_id: string; analysis_id: string; variant_id: string; artifact_id: string; time_domain: string;
  time_seconds: number; end_time_seconds: number | null; categories: string[]; note: string; created_at: string; updated_at: string;
  frame_evidence: { native_frame_index0: number | null; local_frame_index0: number | null; native_pts: number | null; sample_clip_time: number | null; video_sha256: string; mapping_version: number };
}
export type ObservationDraft = Pick<Observation, 'time_seconds' | 'end_time_seconds' | 'categories' | 'note'>;
export interface Analysis {
  analysis_id: string; revision: number; created_at: string; updated_at: string; observations: Observation[];
  variants: Array<{ variant_id: string; label: string; role: string; artifact_id: string; projection: Projection; source_snapshot: Record<string, any>; source_media_status?: string }>;
}
export interface ArtifactList {
  artifacts: Array<{ task_id: string; status: string; clip_plan_revision: number | null; created_at: string }>;
  analyses: Array<{ analysis_id: string; created_at: string; variants: Array<{ variant_id: string; label: string; artifact_id: string; task_id: string }> }>;
}
