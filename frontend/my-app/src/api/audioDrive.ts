import { api } from './index';

export type AudioEventType = 'DIALOGUE' | 'NARRATION' | 'INNER_MONOLOGUE';
export type TtsStatus = 'NOT_GENERATED' | 'GENERATING' | 'READY' | 'STALE' | 'FAILED';
export type TimelineStatus = 'NOT_READY' | 'READY' | 'STALE' | 'FAILED';

export interface AudioEventTtsAsset {
  id: string;
  audioEventId: string;
  audioUrl?: string | null;
  durationSeconds?: number | null;
  revision?: number;
  status?: string;
}

export interface AudioDriveEvent {
  id: string;
  shotId: string;
  order: number;
  type: AudioEventType;
  voiceOwnerCharacterId?: string | null;
  voiceOwnerName: string;
  visibleSpeakerCharacterId?: string | null;
  visibleSpeakerName?: string | null;
  requiresVisibleLipsync: boolean;
  text: string;
  emotionPrompt?: string | null;
  pauseAfter: 'NONE' | 'SHORT' | 'MEDIUM' | 'LONG';
  ttsStatus: TtsStatus;
  currentTtsAsset?: AudioEventTtsAsset | null;
}

export interface AudioTimelineEvent {
  audioEventId: string;
  order: number;
  startTime: number;
  endTime: number;
  type: AudioEventType;
  voiceOwnerName: string;
  visibleSpeakerName?: string | null;
  requiresVisibleLipsync: boolean;
  text?: string;
  ttsAssetId?: string | null;
}

export interface AudioTimeline {
  id: string;
  shotId: string;
  revision: number;
  totalDuration: number;
  status: TimelineStatus;
  audioSummary: Record<string, any>;
  events: AudioTimelineEvent[];
}

export interface AudioDriveExecutionWindow {
  window_index?: number;
  windowIndex?: number;
  start_time?: number;
  startTime?: number;
  end_time?: number;
  endTime?: number;
  duration?: number;
  audio_status?: string;
  audioStatus?: string;
  audio_message?: string;
  audioMessage?: string;
  drive_audio_url?: string;
  driveAudioUrl?: string;
  final_audio_url?: string;
  finalAudioUrl?: string;
  clip_audio_duration?: number;
  clipAudioDuration?: number;
  speaker_timeline?: Array<Record<string, any>>;
  speakerTimeline?: Array<Record<string, any>>;
}

export const audioDriveApi = {
  fetchEvents: (shotId: string) => api.get<{ shotId: string; audioStatus: string; events: AudioDriveEvent[] }>(`/shots/${shotId}/audio-events`),
  updateEvent: (eventId: string, data: Partial<AudioDriveEvent>) => api.patch<AudioDriveEvent>(`/audio-events/${eventId}`, data),
  generateEventTts: (eventId: string, force = false) => api.post<{ eventId: string; taskId?: string; status?: string }>(`/audio-events/${eventId}/tts`, { force }),
  generateShotTts: (shotId: string, data: { eventIds?: string[]; onlyStale?: boolean; force?: boolean } = {}) => api.post<{ tasks: Array<{ eventId: string; taskId?: string }> }>(`/shots/${shotId}/audio/tts/generate`, data),
  fetchTimeline: (shotId: string) => api.get<AudioTimeline | null>(`/shots/${shotId}/audio-timeline`),
  buildTimeline: (shotId: string, force = false) => api.post<AudioTimeline>(`/shots/${shotId}/audio-timeline/build`, { force }),
  rebuildTimeline: (shotId: string) => api.post<AudioTimeline>(`/shots/${shotId}/audio-timeline/rebuild`, { force: true }),
  buildExecutionWindows: (shotId: string, maxClipDuration?: number) => api.post<{ shotId: string; executionWindows: AudioDriveExecutionWindow[] }>(`/shots/${shotId}/video/execution-windows/build`, { maxClipDuration }),
  buildClipAudio: (shotId: string, windowIndex: number, force = false) => api.post<{
    shotId: string;
    windowIndex: number;
    audioTimelineId: string;
    speakerTimeline: Array<Record<string, any>>;
    audioStatus: string;
    driveAudioUrl?: string;
    finalAudioUrl?: string;
    message?: string;
  }>(`/shots/${shotId}/video-director/clips/${windowIndex}/audio/build`, { force }),
  prepareShotAudio: (shotId: string, data: { maxClipDuration?: number; forceTts?: boolean; forceClipAudio?: boolean } = {}) => api.post<{
    taskId: string;
    status: string;
    shotIds: string[];
  }>(`/shots/${shotId}/audio/prepare`, data),
  prepareBatchAudio: (data: { shotIds: string[]; maxClipDuration?: number; forceTts?: boolean; forceClipAudio?: boolean }) => api.post<{
    taskId: string;
    status: string;
    shotIds: string[];
  }>('/audio/prepare-batch', data),
};
