/**
 * VideoGenTab - 视频生成 Tab（阶段 4）
 *
 * 布局参考分镜图生成页面：
 * - 中间：视频生成提示词编辑 + 视频预览
 * - 右侧：关键帧设置 + 转场生成
 *
 * 注意：分镜资源列表在左侧可折叠区域显示（由 ChapterGenerateLayout 的左侧栏渲染）
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import { useChapterGenerateStore } from '../stores';
import { Film, Loader2, Download, Save, Square, Check, X, Image, ChevronDown, Eye, Combine, Layers, ChevronUp, Volume2, Play, Copy, Info, ChevronLeft, ChevronRight, RefreshCw, Sparkles, PictureInPicture } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import { shotsApi } from '../../../api/shots';
import { taskApi } from '../../../api/tasks';
import { toast } from '../../../stores/toastStore';
import KeyframesManager from '../../../components/KeyframesManager';
import AudioReferenceSelector from '../../../components/AudioReferenceSelector';
import { ImagePreviewModal } from '../../../components/ImagePreviewModal';
import { ImageEditModal } from '../../../components/ImageEditModal';
import type { KeyframeData } from '../../../types';
import type { VideoAiCall, VideoDirectorPlan, VideoMode } from '../../../api/shots';
import { dialogueEmotion, dialogueSpeaker, dialogueText, estimateDialogueSeconds, formatUserFacingError, getClipDialoguesForDisplay, numberOrNull } from '../../../utils';

const VIDEO_TAB_UI_STORAGE_KEY = 'chapterGenerate_videoTab_ui';
type MergeVideoMode = 'shots_only' | 'shots_with_transitions';
type BatchSelectionMode = 'all' | 'pending' | null;
type VideoImageEditTarget = {
  type: 'shot' | 'keyframe';
  imageUrl: string;
  itemName: string;
  frameIndex?: number;
};

type VideoPromptDraft = {
  key: string;
  label: string;
  prompt: string;
  source: 'window_plan' | 'clip' | 'ai_call';
  index?: number;
};

interface VideoMetadata {
  duration: number | null;
  width: number | null;
  height: number | null;
  sizeBytes: number | null;
}

const VIDEO_MODE_LABELS: Record<VideoMode, string> = {
  SINGLE_FRAME: '单帧',
  FIRST_LAST_FRAME: '首尾帧',
  MULTI_KEYFRAME: '多关键帧',
};

const getVideoModeLabel = (mode?: VideoMode) => mode ? VIDEO_MODE_LABELS[mode] : '-';
const sleep = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));

const formatAiCallValue = (value: any) => {
  if (value === null || value === undefined || value === '') return '-';
  if (typeof value === 'string') return value;
  return JSON.stringify(value, null, 2);
};

const videoPlanWindowsMatchDuration = (plan: VideoDirectorPlan, duration: number, maxClipDuration: number) => {
  const windows = Array.isArray(plan.execution_windows) ? plan.execution_windows : [];
  const expectedWindows: { window_index: number; start_time: number; end_time: number }[] = [];
  let start = 0;
  let index = 1;
  while (start < duration) {
    const end = Math.min(duration, start + maxClipDuration);
    expectedWindows.push({ window_index: index, start_time: start, end_time: end });
    start = end;
    index += 1;
  }
  if (windows.length !== expectedWindows.length) return false;
  return windows.every((window: any, idx: number) => {
    const expected = expectedWindows[idx];
    return Number(window?.window_index || 0) === expected.window_index
      && Number(window?.start_time || 0) === expected.start_time
      && Number(window?.end_time || 0) === expected.end_time;
  });
};

const getAudioDriveReadiness = (shot: any) => {
  const plan: any = shot?.videoDirectorPlan || {};
  const windows = Array.isArray(plan.window_plans) && plan.window_plans.length > 0
    ? plan.window_plans
    : Array.isArray(plan.execution_windows)
      ? plan.execution_windows
      : Array.isArray(plan.clips)
        ? plan.clips
        : [];
  const timelineReady = String(shot?.audioStatus || '').toUpperCase() === 'READY';
  const clipCount = windows.length;
  const readyClipCount = windows.filter((window: any) => (
    String(window?.audio_status || window?.audioStatus || '').toUpperCase() === 'READY'
    && Boolean(window?.drive_audio_url || window?.driveAudioUrl)
    && Boolean(window?.final_audio_url || window?.finalAudioUrl)
  )).length;
  const clipAudioReady = clipCount > 0 && readyClipCount === clipCount;
  const missingClips = windows
    .filter((window: any) => !(String(window?.audio_status || window?.audioStatus || '').toUpperCase() === 'READY' && (window?.drive_audio_url || window?.driveAudioUrl) && (window?.final_audio_url || window?.finalAudioUrl)))
    .map((window: any, index: number) => `C${window?.window_index || window?.windowIndex || index + 1}`);
  let reason = '';
  if (!timelineReady) reason = 'Audio Timeline 未 READY，请先到音频生成页生成 TTS 并构建 Timeline。';
  else if (!clipCount) reason = '尚未构建 Clip Audio 执行窗口，请先到音频生成页构建窗口和 Clip Audio。';
  else if (!clipAudioReady) reason = `Clip Audio 未 READY：${missingClips.join(' / ')}，请先到音频生成页构建 drive/final 音频。`;
  return { timelineReady, clipAudioReady, clipCount, readyClipCount, missingClips, ready: timelineReady && clipAudioReady, reason };
};

const mergeClipAudioWindows = (plan: any, selectedMode: string) => {
  const windowPlans = Array.isArray(plan?.window_plans) ? plan.window_plans : [];
  const executionWindows = Array.isArray(plan?.execution_windows) ? plan.execution_windows : [];
  if (selectedMode === 'MULTI_KEYFRAME') return windowPlans.length > 0 ? windowPlans : executionWindows;
  const baseClips = Array.isArray(plan?.clips) ? plan.clips : [];
  const audioWindows = windowPlans.length > 0 ? windowPlans : executionWindows;
  if (baseClips.length === 0) return audioWindows;
  return baseClips.map((clip: any, index: number) => {
    const clipIndex = Number(clip?.window_index || clip?.windowIndex || clip?.clip_index || clip?.clipIndex || index + 1);
    const audioWindow = audioWindows.find((window: any, windowIndex: number) => (
      Number(window?.window_index || window?.windowIndex || window?.clip_index || window?.clipIndex || windowIndex + 1) === clipIndex
    ));
    return audioWindow ? { ...clip, ...audioWindow } : clip;
  });
};

const pauseSecondsByType: Record<string, number> = {
  NONE: 0,
  SHORT: 0.3,
  MEDIUM: 0.6,
  LONG: 1.2,
};

const countTextChars = (text?: string) => String(text || '').replace(/\s/g, '').length;

const getClipAudioEventTexts = (shot: any, clip: any, driveOnly = false) => {
  const plan = shot?.videoDirectorPlan || shot?.video_director_plan || {};
  const audioEvents = Array.isArray(shot?.audioEvents)
    ? shot.audioEvents
    : Array.isArray(shot?.audio_events)
      ? shot.audio_events
      : [];
  const audioEventsById = new Map(audioEvents.map((event: any) => [String(event.id || event.audioEventId || event.audio_event_id), event]));
  const audioEventsByOrder = new Map(audioEvents.map((event: any) => [Number(event.order ?? event.event_order ?? 0), event]));

  const clipStart = numberOrNull(clip?.start_time ?? clip?.startTime) ?? 0;
  const clipEnd = numberOrNull(clip?.end_time ?? clip?.endTime) ?? numberOrNull(shot?.duration) ?? clipStart;
  const timeline = plan.audio_timeline || plan.audioTimeline || {};
  const timelineEvents = Array.isArray(timeline.events) ? timeline.events : [];

  if (timelineEvents.length > 0) {
    return timelineEvents
      .map((event: any) => {
        const order = Number(event.order ?? event.event_order ?? 0);
        const sourceEvent: any = audioEventsById.get(String(event.audioEventId || event.audio_event_id || event.id)) || audioEventsByOrder.get(order) || {};
        return {
          key: event.audioEventId || event.audio_event_id || event.id || order,
          start: Number(event.startTime ?? event.start_time ?? 0),
          end: Number(event.endTime ?? event.end_time ?? 0),
          type: event.type || event.event_type,
          voiceOwnerName: event.voiceOwnerName || event.voice_owner_name || sourceEvent?.voiceOwnerName || sourceEvent?.voice_owner_name,
          visibleSpeakerName: event.visibleSpeakerName || event.visible_speaker_name || sourceEvent?.visibleSpeakerName || sourceEvent?.visible_speaker_name,
          requiresVisibleLipsync: Boolean(event.requiresVisibleLipsync ?? event.requires_visible_lipsync ?? sourceEvent?.requiresVisibleLipsync ?? sourceEvent?.requires_visible_lipsync),
          text: String(event.text || sourceEvent?.text || '').trim(),
        };
      })
      .filter((event: any) => {
        if (driveOnly && !event.requiresVisibleLipsync) return false;
        return event.end > clipStart && event.start < clipEnd;
      })
      .map((event: any) => ({
        key: event.key,
        start: Math.max(event.start, clipStart) - clipStart,
        end: Math.min(event.end, clipEnd) - clipStart,
        speaker: driveOnly
          ? (event.visibleSpeakerName || event.voiceOwnerName || '可见角色')
          : (event.voiceOwnerName || event.visibleSpeakerName || '声音'),
        text: event.text,
        charCount: countTextChars(event.text),
      }))
      .filter((item: any) => item.text);
  }

  if (!audioEvents.length) return [];

  const speakerTimeline = Array.isArray(clip?.speaker_timeline) ? clip.speaker_timeline : Array.isArray(clip?.speakerTimeline) ? clip.speakerTimeline : [];
  const visibleSegments = speakerTimeline.filter((segment: any) => String(segment.visible_speaker || segment.visibleSpeaker || 'NONE') !== 'NONE');
  const orderedEvents = [...audioEvents].sort((a: any, b: any) => Number(a.order ?? a.event_order ?? 0) - Number(b.order ?? b.event_order ?? 0));
  const hasEventDurations = orderedEvents.some((event: any) => Number(event.currentTtsAsset?.durationSeconds ?? event.current_tts_asset?.duration_seconds ?? event.durationSeconds ?? 0) > 0);

  if (!hasEventDurations) {
    return orderedEvents
      .filter((event: any) => !driveOnly || Boolean(event.requiresVisibleLipsync ?? event.requires_visible_lipsync))
      .map((event: any, index: number) => {
        const segment = visibleSegments[index] || speakerTimeline[index];
        const start = Number(segment?.start_time ?? segment?.startTime ?? clipStart) - clipStart;
        const end = Number(segment?.end_time ?? segment?.endTime ?? clipEnd) - clipStart;
        const text = String(event.text || '').trim();
        return {
          key: event.id || `${index}-${text}`,
          start: Math.max(0, start),
          end: Math.max(Math.max(0, start), Math.min(clipEnd - clipStart, end || clipEnd - clipStart)),
          speaker: driveOnly
            ? (event.visibleSpeakerName || event.visible_speaker_name || event.voiceOwnerName || event.voice_owner_name || '可见角色')
            : (event.voiceOwnerName || event.voice_owner_name || event.visibleSpeakerName || event.visible_speaker_name || '声音'),
          text,
          charCount: countTextChars(text),
        };
      })
      .filter((item: any) => item.text);
  }

  let cursor = 0;
  return orderedEvents
    .map((event: any) => {
      const duration = Number(event.currentTtsAsset?.durationSeconds ?? event.current_tts_asset?.duration_seconds ?? event.durationSeconds ?? 0) || 0;
      const start = cursor;
      const end = start + duration;
      cursor = end + (pauseSecondsByType[String(event.pauseAfter || event.pause_after || 'NONE').toUpperCase()] ?? 0);
      return { event, start, end };
    })
    .filter(({ event, start, end }: any) => {
      if (driveOnly && !Boolean(event.requiresVisibleLipsync ?? event.requires_visible_lipsync)) return false;
      return end > clipStart && start < clipEnd;
    })
    .map(({ event, start, end }: any) => {
      const text = String(event.text || '').trim();
      return {
        key: event.id || `${start}-${end}-${text}`,
        start: Math.max(start, clipStart) - clipStart,
        end: Math.min(end, clipEnd) - clipStart,
        speaker: driveOnly
          ? (event.visibleSpeakerName || event.visible_speaker_name || event.voiceOwnerName || event.voice_owner_name || '可见角色')
          : (event.voiceOwnerName || event.voice_owner_name || event.visibleSpeakerName || event.visible_speaker_name || '声音'),
        text,
        charCount: countTextChars(text),
      };
    })
    .filter((item: any) => item.text);
};

const pct = (value: number, total: number) => `${Math.max(0, Math.min(100, total > 0 ? (value / total) * 100 : 0))}%`;

function ClipAudioTimeline({
  clipDuration,
  speakerTimeline,
  driveTextEvents,
  finalTextEvents,
}: {
  clipDuration: number;
  speakerTimeline: any[];
  driveTextEvents: any[];
  finalTextEvents: any[];
}) {
  const duration = Math.max(clipDuration, 0.001);
  const driveBlocks = driveTextEvents.length > 0
    ? driveTextEvents
    : speakerTimeline
      .filter((segment: any) => String(segment.visible_speaker || segment.visibleSpeaker || 'NONE') !== 'NONE')
      .map((segment: any, index: number) => ({
        key: `speaker-${index}`,
        start: Number(segment.start_time ?? segment.startTime ?? 0),
        end: Number(segment.end_time ?? segment.endTime ?? 0),
        speaker: segment.visible_speaker || segment.visibleSpeaker || '可见角色',
        text: '',
        charCount: 0,
      }));
  const finalBlocks = finalTextEvents.length > 0 ? finalTextEvents : driveBlocks;
  const ticks = [0, duration / 2, duration];

  const renderTrack = (label: string, blocks: any[], className: string) => (
    <div className="grid grid-cols-[72px_minmax(0,1fr)] items-center gap-2">
      <div className="text-[11px] font-medium text-gray-600">{label}</div>
      <div className="relative h-9 rounded border border-gray-200 bg-white">
        {blocks.map((block: any) => {
          const start = Number(block.start || 0);
          const end = Math.max(start, Number(block.end || start));
          return (
            <div
              key={`${label}-${block.key}-${start}-${end}`}
              className={`absolute top-1 h-7 overflow-hidden rounded px-2 text-[11px] leading-7 ${className}`}
              style={{ left: pct(start, duration), width: pct(end - start, duration) }}
              title={`${start.toFixed(3)}s-${end.toFixed(3)}s · ${block.speaker}${block.charCount ? ` · ${block.charCount}字` : ''}${block.text ? ` · ${block.text}` : ''}`}
            >
              <span className="truncate">{start.toFixed(2)}-{end.toFixed(2)}s · {block.speaker}{block.charCount ? ` · ${block.charCount}字` : ''}</span>
            </div>
          );
        })}
      </div>
    </div>
  );

  return (
    <div className="rounded border border-white/70 bg-white/70 px-2 py-2">
      <div className="mb-2 flex items-center justify-between text-[11px] text-gray-500">
        <span className="font-medium text-gray-700">Audio Timeline</span>
        <span>总时长 {clipDuration.toFixed(3)}s</span>
      </div>
      <div className="mb-1 grid grid-cols-[72px_minmax(0,1fr)] gap-2 text-[10px] text-gray-400">
        <div />
        <div className="relative h-4 border-t border-gray-200">
          {ticks.map((tick) => (
            <span key={tick} className="absolute top-0 -translate-x-1/2 border-l border-gray-200 pl-1" style={{ left: pct(tick, duration) }}>{tick.toFixed(tick === 0 ? 0 : 1)}s</span>
          ))}
        </div>
      </div>
      <div className="space-y-2">
        {renderTrack('Drive', driveBlocks, 'bg-cyan-100 text-cyan-800')}
        {renderTrack('Final', finalBlocks, 'bg-purple-100 text-purple-800')}
      </div>
    </div>
  );
}

const copyText = async (text?: string | null) => {
  if (!text) return;
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
    } else {
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.style.position = 'fixed';
      textarea.style.left = '-9999px';
      textarea.style.top = '-9999px';
      document.body.appendChild(textarea);
      textarea.focus();
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
    }
    toast.success('已复制');
  } catch {
    toast.error('复制失败');
  }
};

function VideoAiCallsPanel({
  calls = [],
  novelId,
  chapterId,
  shotId,
  onRefresh,
  isRefreshing = false,
}: {
  calls?: VideoAiCall[];
  novelId?: string;
  chapterId?: string;
  shotId?: string;
  onRefresh?: () => void;
  isRefreshing?: boolean;
}) {
  const { t } = useTranslation();
  const [panelOpen, setPanelOpen] = useState(true);
  const [expanded, setExpanded] = useState(true);
  const [openIndex, setOpenIndex] = useState(Math.max(0, calls.length - 1));
  const [viewingData, setViewingData] = useState<{ title: string; content: string } | null>(null);
  const [isDownloading, setIsDownloading] = useState(false);
  const sortedCalls = [...calls].sort((a, b) => {
    const aTime = a.created_at ? new Date(a.created_at).getTime() : 0;
    const bTime = b.created_at ? new Date(b.created_at).getTime() : 0;
    return aTime - bTime;
  });
  const latest = sortedCalls[sortedCalls.length - 1];
  const getAudioDebugSummary = (call: VideoAiCall) => {
    const parsed: any = call.parsed_result || {};
    const audioTimeline = parsed.audio_timeline || parsed.audioTimeline;
    const audioDrive = parsed.audio_drive_context || parsed.audioDriveContext;
    if (audioTimeline?.resolved_duration !== undefined) {
      return `Audio Timeline rev ${audioTimeline.revision ?? '-'} · resolved ${audioTimeline.resolved_duration}s`;
    }
    if (audioDrive?.audio_mode) {
      return `AudioDrive ${audioDrive.audio_mode} · duration ${audioDrive.duration ?? '-'}s`;
    }
    if (parsed.source === 'AudioDrive') {
      return `AudioDrive · speaker_timeline ${parsed.speaker_timeline_segments ?? 0} segments`;
    }
    return '';
  };

  const handleDownloadLlmData = async () => {
    if (!novelId || !chapterId || !shotId) {
      toast.error(t('chapterGenerate.missingShotInfoForLlmDownload'));
      return;
    }
    setIsDownloading(true);
    try {
      await shotsApi.downloadShotLlmData(novelId, chapterId, shotId);
      toast.success(t('chapterGenerate.llmDataDownloaded'));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t('chapterGenerate.downloadLlmDataFailed'));
    } finally {
      setIsDownloading(false);
    }
  };

  useEffect(() => {
    if (calls.length > 0) setOpenIndex(calls.length - 1);
  }, [calls.length]);

  if (!calls.length) {
    return (
      <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50">
        <div className="flex items-center justify-between px-3 py-2">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-gray-800">
              {t('chapterGenerate.aiCallResults')}
              <button
                type="button"
                onClick={handleDownloadLlmData}
                disabled={isDownloading}
                className="inline-flex items-center gap-1 rounded border border-gray-200 bg-white px-2 py-0.5 text-xs font-normal text-gray-700 hover:bg-gray-100 disabled:opacity-50"
              >
                <Download className="h-3 w-3" />{isDownloading ? t('chapterGenerate.downloading') : t('chapterGenerate.downloadLlmData')}
              </button>
            </div>
            <div className="text-xs text-gray-500">{t('chapterGenerate.noAiCallResults')}</div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onRefresh}
              disabled={isRefreshing || !onRefresh}
              className="p-1.5 text-gray-500 hover:text-blue-700 disabled:opacity-50"
              title={t('common.refresh')}
            >
              <RefreshCw className={`h-4 w-4 ${isRefreshing ? 'animate-spin' : ''}`} />
            </button>
            <button
              type="button"
              onClick={() => setPanelOpen(!panelOpen)}
              className="px-2 py-1 text-xs rounded border border-gray-200 bg-white text-gray-700 hover:bg-gray-100"
            >
              {panelOpen ? t('common.collapse') : t('common.expand')}
            </button>
          </div>
        </div>
        {panelOpen && (
          <div className="border-t border-gray-200 px-3 py-3 text-sm text-gray-500">
            {t('chapterGenerate.noAiCallResultsHint')}
          </div>
        )}
      </div>
    );
  }

  const visibleCalls = expanded ? sortedCalls : [latest];

  return (
    <>
    <div className="flex min-h-0 flex-1 flex-col rounded-lg border border-gray-200 bg-gray-50">
      <div className={`flex items-center justify-between px-3 py-2 ${panelOpen ? 'border-b border-gray-200' : ''}`}>
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-gray-800">
            {t('chapterGenerate.aiCallResults')}
            <button
              type="button"
              onClick={handleDownloadLlmData}
              disabled={isDownloading}
              className="inline-flex items-center gap-1 rounded border border-gray-200 bg-white px-2 py-0.5 text-xs font-normal text-gray-700 hover:bg-gray-100 disabled:opacity-50"
            >
              <Download className="h-3 w-3" />{isDownloading ? t('chapterGenerate.downloading') : t('chapterGenerate.downloadLlmData')}
            </button>
          </div>
          <div className="text-xs text-gray-500">{t('chapterGenerate.aiCallCountHint', { count: calls.length })}</div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onRefresh}
            disabled={isRefreshing || !onRefresh}
            className="p-1.5 text-gray-500 hover:text-blue-700 disabled:opacity-50"
            title={t('common.refresh')}
          >
            <RefreshCw className={`h-4 w-4 ${isRefreshing ? 'animate-spin' : ''}`} />
          </button>
          {panelOpen && (
            <button
              type="button"
              onClick={() => setExpanded(!expanded)}
              className="px-2 py-1 text-xs rounded border border-gray-200 bg-white text-gray-700 hover:bg-gray-100"
            >
              {expanded ? t('chapterGenerate.showLatestOnly') : t('chapterGenerate.expandAllAiCalls')}
            </button>
          )}
          <button
            type="button"
            onClick={() => setPanelOpen(!panelOpen)}
            className="px-2 py-1 text-xs rounded border border-gray-200 bg-white text-gray-700 hover:bg-gray-100"
          >
            {panelOpen ? t('common.collapse') : t('common.expand')}
          </button>
        </div>
      </div>
      {panelOpen && <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
        {visibleCalls.map((call, idx) => {
          const actualIndex = expanded ? idx : sortedCalls.length - 1;
          const isOpen = openIndex === actualIndex;
          const responseText = formatAiCallValue(call.response);
          const promptText = formatAiCallValue(call.final_prompt);
          const audioDebugSummary = getAudioDebugSummary(call);
          return (
            <div key={`${call.step}-${call.created_at}-${actualIndex}`} className="rounded-lg border border-gray-200 bg-white overflow-hidden">
              <button
                type="button"
                onClick={() => setOpenIndex(isOpen ? -1 : actualIndex)}
                className="w-full px-3 py-2 flex items-center justify-between gap-3 text-left hover:bg-gray-50"
              >
                <div>
                  <div className="text-sm font-medium text-gray-800">#{call.step || '--'} {call.title || call.task_type || t('chapterGenerate.aiCall')}</div>
                  <div className="text-xs text-gray-500">
                    {call.prompt_template_name || '-'} · {call.status || '-'} · {call.created_at ? new Date(call.created_at).toLocaleString() : '-'}
                    {call.clip_index ? ` · Clip ${call.clip_index}` : ''}
                  </div>
                  {audioDebugSummary && <div className="mt-0.5 text-xs text-cyan-700">{audioDebugSummary}</div>}
                </div>
                <ChevronDown className={`w-4 h-4 text-gray-400 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
              </button>
              {isOpen && (
                <div className="px-3 pb-3">
                  {call.input_summary && <div className="text-xs text-gray-500">{call.input_summary}</div>}
                  {audioDebugSummary && <div className="mt-1 rounded border border-cyan-100 bg-cyan-50 px-2 py-1 text-xs text-cyan-700">{audioDebugSummary}</div>}
                  <div className="mt-3 grid grid-cols-1 gap-3 xl:grid-cols-2">
                  <div className="min-w-0">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs font-medium text-gray-600">{t('chapterGenerate.returnResult')}</span>
                      <div className="flex items-center gap-2">
                        <button type="button" onClick={() => setViewingData({ title: t('chapterGenerate.returnResult'), content: responseText })} className="text-blue-600 hover:text-blue-800" title={t('common.view')}><Eye className="w-3 h-3" /></button>
                        <button type="button" onClick={() => copyText(responseText)} className="text-blue-600 hover:text-blue-800" title={t('common.copy')}><Copy className="w-3 h-3" /></button>
                      </div>
                    </div>
                    <pre className="max-h-40 overflow-auto rounded bg-gray-900 p-2 text-xs text-gray-100 whitespace-pre-wrap">{responseText}</pre>
                  </div>
                  <div className="min-w-0">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs font-medium text-gray-600">{t('chapterGenerate.finalPrompt')}</span>
                        <div className="flex items-center gap-2">
                          <button type="button" onClick={() => setViewingData({ title: t('chapterGenerate.finalPrompt'), content: promptText })} className="text-blue-600 hover:text-blue-800" title={t('common.view')}><Eye className="w-3 h-3" /></button>
                          <button type="button" onClick={() => copyText(promptText)} className="text-blue-600 hover:text-blue-800" title={t('common.copy')}><Copy className="w-3 h-3" /></button>
                        </div>
                      </div>
                      <pre className="max-h-40 overflow-auto rounded bg-gray-900 p-2 text-xs text-gray-100 whitespace-pre-wrap">{promptText}</pre>
                    </div>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>}
    </div>
    {viewingData && (
      <div className="fixed inset-0 isolate z-[300] flex items-center justify-center bg-black/60 p-4 backdrop-blur-[1px]" onClick={() => setViewingData(null)}>
        <div className="w-full max-w-5xl max-h-[86vh] overflow-hidden rounded-xl bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
          <div className="flex items-center justify-between gap-3 border-b border-gray-200 px-4 py-3">
            <div className="min-w-0">
              <div className="text-base font-semibold text-gray-900 truncate">{viewingData.title}</div>
              <div className="text-xs text-gray-500">{t('chapterGenerate.fullDataPreview')}</div>
            </div>
            <div className="flex items-center gap-2 flex-shrink-0">
              <button type="button" onClick={() => copyText(viewingData.content)} className="inline-flex items-center gap-1 rounded-md border border-gray-200 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50">
                <Copy className="h-4 w-4" />{t('common.copy')}
              </button>
              <button type="button" onClick={() => setViewingData(null)} className="rounded-md p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-700">
                <X className="h-5 w-5" />
              </button>
            </div>
          </div>
          <div className="max-h-[72vh] overflow-auto bg-gray-950 p-4">
            <pre className="text-sm leading-6 text-gray-100 whitespace-pre-wrap break-words">{viewingData.content}</pre>
          </div>
        </div>
      </div>
    )}
    </>
  );
}

function VideoPromptModal({
  isOpen,
  drafts,
  selectedMode,
  isSaving,
  onChange,
  onClose,
  onSave,
}: {
  isOpen: boolean;
  drafts: VideoPromptDraft[];
  selectedMode: VideoMode;
  isSaving: boolean;
  onChange: (key: string, prompt: string) => void;
  onClose: () => void;
  onSave: () => void;
}) {
  if (!isOpen) return null;

  const hasDrafts = drafts.length > 0;

  return (
    <div className="fixed inset-0 isolate z-[300] flex items-center justify-center bg-black/60 px-4 backdrop-blur-[1px]">
      <div className="flex max-h-[86vh] w-full max-w-5xl flex-col rounded-xl bg-white shadow-2xl">
        <div className="flex items-start justify-between border-b border-gray-200 px-5 py-4">
          <div>
            <h3 className="text-lg font-semibold text-gray-900">AI提示词</h3>
            <p className="mt-1 text-sm text-gray-500">
              {hasDrafts ? `当前模式：${getVideoModeLabel(selectedMode)}，共 ${drafts.length} 条可编辑 Prompt。` : '当前 Shot 暂无可编辑的视频生成 AI 提示词。'}
            </p>
          </div>
          <button type="button" onClick={onClose} className="rounded-full p-2 text-gray-400 hover:bg-gray-100 hover:text-gray-600">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {!hasDrafts ? (
            <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50 px-4 py-8 text-center text-sm text-gray-600">
              <div className="font-medium text-gray-800">还没有可编辑的 Clip Prompt</div>
              <div className="mt-2">请先执行视频模式推荐、关键帧/Clip 规划，或使用“LLM+生成当前Shot视频”生成一次 H3 视频提示词。</div>
            </div>
          ) : (
            <div className="space-y-4">
              {drafts.map((draft) => (
                <div key={draft.key} className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <div>
                      <div className="text-sm font-semibold text-gray-800">{draft.label}</div>
                      <div className="text-xs text-gray-500">
                        {draft.source === 'ai_call' ? '未规划 Clip：保存后会写入 C1 Prompt' : draft.source === 'window_plan' ? '来源：window_plan.prompt_text' : '来源：clip.prompt_text'}
                      </div>
                    </div>
                    <button type="button" onClick={() => copyText(draft.prompt)} className="inline-flex items-center gap-1 rounded border border-gray-200 bg-white px-2 py-1 text-xs text-gray-600 hover:bg-gray-100">
                      <Copy className="h-3.5 w-3.5" />复制
                    </button>
                  </div>
                  <textarea
                    value={draft.prompt}
                    onChange={(event) => onChange(draft.key, event.target.value)}
                    className="min-h-[220px] w-full rounded-lg border border-gray-300 bg-white px-3 py-2 font-mono text-xs leading-5 text-gray-800 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100"
                    placeholder="这里填写当前 Clip 的最终视频生成 AI 提示词"
                  />
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-3 border-t border-gray-200 px-5 py-4">
          <button type="button" onClick={onClose} className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50">
            取消
          </button>
          <button
            type="button"
            onClick={onSave}
            disabled={!hasDrafts || isSaving}
            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            保存
          </button>
        </div>
      </div>
    </div>
  );
}

interface VideoDirectorPanelProps {
  shot: any;
  shotImageUrl?: string | null;
  plan: VideoDirectorPlan;
  isRecommending: boolean;
  isPlanningKeyframes: boolean;
  onRecommend: (force?: boolean) => void;
  onPlanKeyframes: (force?: boolean) => void;
  onGenerateMissingKeyframes: () => void;
  onGenerateEndKeyframe: (mode?: 'llm' | 'image_only') => void;
  isGeneratingEndKeyframe?: boolean;
  isGeneratingMissingKeyframes?: boolean;
  generatingKeyframes?: Set<string>;
  keyframeTasks?: any[];
  onSelectMode: (mode: VideoMode) => void;
  onPreviewClip: (clip: any) => void;
  onRegenerateClip: (clip: any, mode?: 'llm' | 'video_only') => void;
  onMergeClips: () => void;
  onPreviewImage: (url: string) => void;
  onEditImage: (target: VideoImageEditTarget) => void;
  onOpenPromptModal: () => void;
  selectedPreviewClipKey?: string | null;
  regeneratingClipKey?: string | null;
  isMergingClips?: boolean;
  isShotVideoGenerating?: boolean;
}

function VideoDirectorPanel({
  shot,
  shotImageUrl,
  plan,
  isRecommending,
  isPlanningKeyframes,
  onRecommend,
  onPlanKeyframes,
  onGenerateMissingKeyframes,
  onGenerateEndKeyframe,
  isGeneratingEndKeyframe,
  isGeneratingMissingKeyframes,
  generatingKeyframes = new Set(),
  keyframeTasks = [],
  onSelectMode,
  onPreviewClip,
  onRegenerateClip,
  onMergeClips,
  onPreviewImage,
  onEditImage,
  onOpenPromptModal,
  selectedPreviewClipKey,
  regeneratingClipKey,
  isMergingClips,
  isShotVideoGenerating,
}: VideoDirectorPanelProps) {
  const { t } = useTranslation();
  const [showEndKeyframeMenu, setShowEndKeyframeMenu] = useState(false);
  const [openClipGenerateMenuKey, setOpenClipGenerateMenuKey] = useState<string | null>(null);

  useEffect(() => {
    if (regeneratingClipKey && openClipGenerateMenuKey === regeneratingClipKey) {
      setOpenClipGenerateMenuKey(null);
    }
  }, [openClipGenerateMenuKey, regeneratingClipKey]);

  useEffect(() => {
    if (isShotVideoGenerating) {
      setOpenClipGenerateMenuKey(null);
      setShowEndKeyframeMenu(false);
    }
  }, [isShotVideoGenerating]);
  const selectedMode = plan.selected_mode || plan.recommended_mode || 'SINGLE_FRAME';
  const maxClipDuration = plan.workflow_capability?.max_clip_duration || 15;
  const firstLastAvailable = plan.first_last_available ?? ((shot?.duration || 0) <= maxClipDuration);
  const keyframes = plan.keyframes || [];
  const clips = mergeClipAudioWindows(plan, selectedMode);
  const hasWindowPlans = selectedMode === 'MULTI_KEYFRAME' && clips.length > 0;
  const legacyKeyframes = shot?.keyframes || [];
  const getKeyframeImageUrl = (kf: any) => {
    if (!kf) return null;
    if (kf.role === 'START') return shotImageUrl || null;
    if (kf.image_url || kf.imageUrl) return kf.image_url || kf.imageUrl;
    const legacyKeyframe = legacyKeyframes.find((item: any) => Number(item.plan_keyframe_index ?? item.planKeyframeIndex) === Number(kf.index));
    return legacyKeyframe?.image_url || legacyKeyframe?.imageUrl || null;
  };
  const getKeyframeFrameIndex = (kf: any) => {
    if (!kf || kf.role === 'START') return undefined;
    const legacyKeyframe = legacyKeyframes.find((item: any) => Number(item.plan_keyframe_index ?? item.planKeyframeIndex) === Number(kf.index));
    if (legacyKeyframe?.frame_index !== undefined) return Number(legacyKeyframe.frame_index);
    const nonStartIndex = keyframes.filter((item: any) => item.role !== 'START').findIndex((item: any) => Number(item.index) === Number(kf.index));
    return nonStartIndex >= 0 ? nonStartIndex : undefined;
  };
  const isKeyframeGenerating = (kf: any) => {
    const shotId = shot?.id ? String(shot.id) : '';
    const frameIndex = getKeyframeFrameIndex(kf);
    if (!shotId || frameIndex === undefined) return false;
    if (generatingKeyframes.has(`${shotId}-${frameIndex}`)) return true;
    return keyframeTasks.some((task: any) => (
      task.shotId === shotId
      && Number(task.frameIndex) === Number(frameIndex)
      && ['pending', 'running'].includes(String(task.status))
    ));
  };
  const activeMissingKeyframes = selectedMode === 'MULTI_KEYFRAME'
    ? keyframes.filter((kf: any) => kf.role !== 'START' && !getKeyframeImageUrl(kf) && isKeyframeGenerating(kf))
    : [];
  const missingKeyframes = selectedMode === 'MULTI_KEYFRAME'
    ? keyframes.filter((kf: any) => kf.role !== 'START' && !getKeyframeImageUrl(kf))
    : [];
  const hasGeneratingMissingKeyframes = missingKeyframes.some((kf: any) => isKeyframeGenerating(kf));
  const missingKeyframeButtonLabel = hasGeneratingMissingKeyframes
    ? `关键帧任务中 ${activeMissingKeyframes.length}/${missingKeyframes.length}`
    : `生成缺失关键帧${missingKeyframes.length > 0 ? ` ${missingKeyframes.length}` : ''}`;
  const threeFrameClipCount = clips.filter((clip: any) => Number(clip.selected_frame_count || clip.frame_count) === 3).length;
  const fourFrameClipCount = clips.filter((clip: any) => Number(clip.selected_frame_count || clip.frame_count) === 4).length;
  const [selectedKeyframeIndex, setSelectedKeyframeIndex] = useState(0);
  const [selectedClipKey, setSelectedClipKey] = useState<string | null>(null);
  const [isEndDescriptionExpanded, setIsEndDescriptionExpanded] = useState(false);
  const [viewingPromptClip, setViewingPromptClip] = useState<any | null>(null);
  const selectedKeyframe = keyframes[selectedKeyframeIndex] || keyframes[0];
  const hasNextKeyframe = selectedKeyframeIndex < keyframes.length - 1;
  const transitions = plan.transitions || [];
  const previousTransition = transitions.find((transition) => (
    Number(transition.to_keyframe_index) === Number(selectedKeyframe?.index)
  ));
  const nextTransition = transitions.find((transition) => (
    Number(transition.from_keyframe_index) === Number(selectedKeyframe?.index)
  ));
  const getClipKey = (clip: any) => String(clip.clip_index || clip.window_index || `${clip.start_time}-${clip.end_time}`);
  const clipContainsKeyframe = (clip: any, keyframeIndex: number) => (
    Array.isArray(clip.keyframe_indexes) && clip.keyframe_indexes.some((item: number) => Number(item) === Number(keyframeIndex))
  );
  const defaultSelectedClip = clips.find((clip: any) => clipContainsKeyframe(clip, Number(selectedKeyframe?.index))) || clips[0];
  const selectedClip = clips.find((clip: any) => getClipKey(clip) === selectedClipKey) || defaultSelectedClip;
  const selectedClipKeyframes = new Set((selectedClip?.keyframe_indexes || []).map((item: number) => Number(item)));
  const selectedKeyframeClipCount = clips.filter((clip: any) => clipContainsKeyframe(clip, Number(selectedKeyframe?.index))).length;
  const startKeyframe = keyframes.find((kf: any) => kf.role === 'START') || { index: 1, time_seconds: 0, role: 'START' };
  const endKeyframe: any = keyframes.find((kf: any) => kf.role === 'END') || { index: 2, time_seconds: shot?.duration || 0, role: 'END', description: shot?.video_description || shot?.description || '' };
  const endKeyframeImageUrl = getKeyframeImageUrl(endKeyframe);
  const hasReusableEndKeyframePrompt = !!String(endKeyframe?.prompt_text || '').trim();
  const firstLastTransition = transitions.find((transition) => Number(transition.from_keyframe_index) === 1 && Number(transition.to_keyframe_index) === 2) || transitions[0];

  useEffect(() => {
    if (!showEndKeyframeMenu) return;
    const handleClick = () => setShowEndKeyframeMenu(false);
    window.addEventListener('click', handleClick);
    return () => window.removeEventListener('click', handleClick);
  }, [showEndKeyframeMenu]);

  useEffect(() => {
    setSelectedKeyframeIndex(0);
    setSelectedClipKey(null);
    setIsEndDescriptionExpanded(false);
  }, [shot?.id, selectedMode]);

  const renderModeButton = (mode: VideoMode, disabled = false, title = '') => {
    const effectiveDisabled = disabled || !!isShotVideoGenerating;
    const effectiveTitle = isShotVideoGenerating ? '当前 Shot 视频生成中，请等待完成后再切换生成模式' : title;
    return (
    <button
      type="button"
      onClick={() => !effectiveDisabled && onSelectMode(mode)}
      disabled={effectiveDisabled}
      title={effectiveTitle}
      className={`flex-1 rounded-lg border px-3 py-2 text-sm font-medium transition-colors ${
        selectedMode === mode
          ? 'border-blue-500 bg-blue-50 text-blue-700'
          : 'border-gray-200 bg-white text-gray-700 hover:border-blue-300 hover:bg-blue-50'
      } ${effectiveDisabled ? 'cursor-not-allowed bg-gray-50 text-gray-400 hover:border-gray-200 hover:bg-gray-50' : ''}`}
    >
      {getVideoModeLabel(mode)}{plan.recommended_mode === mode ? ' ★' : ''}{disabled ? '（当前不可用）' : ''}
    </button>
    );
  };

  const getClipStatusClass = (status?: string) => {
    switch ((status || 'NOT_STARTED').toUpperCase()) {
      case 'PROMPT_BUILDING':
        return 'bg-blue-50 text-blue-700 border-blue-200';
      case 'QUEUED':
        return 'bg-indigo-50 text-indigo-700 border-indigo-200';
      case 'RUNNING':
        return 'bg-amber-50 text-amber-700 border-amber-200';
      case 'SUCCEEDED':
        return 'bg-green-50 text-green-700 border-green-200';
      case 'FAILED':
        return 'bg-red-50 text-red-700 border-red-200';
      default:
        return 'bg-gray-100 text-gray-700 border-gray-200';
    }
  };
  const getClipStatusLabel = (status?: string) => {
    switch ((status || 'PENDING').toUpperCase()) {
      case 'PROMPT_BUILDING': return t('tasks.clipStatuses.promptBuilding');
      case 'QUEUED': return t('tasks.clipStatuses.queued');
      case 'RUNNING': return t('tasks.clipStatuses.running');
      case 'SUCCEEDED': return t('tasks.clipStatuses.succeeded');
      case 'FAILED': return t('tasks.clipStatuses.failed');
      case 'CANCELLED': return t('tasks.clipStatuses.cancelled');
      case 'NOT_STARTED': return '未生成';
      default: return t('tasks.clipStatuses.pending');
    }
  };
  const clipHasMergeArtifact = (clip: any) => !!(clip.video_url || clip.local_path);
  const missingClipArtifacts = selectedMode === 'MULTI_KEYFRAME'
    ? clips.filter((clip: any) => !clipHasMergeArtifact(clip)).map((clip: any) => `C${clip.window_index || clip.clip_index}`)
    : [];
  const allClipsReady = selectedMode === 'MULTI_KEYFRAME' && clips.length > 0 && missingClipArtifacts.length === 0;
  const parseTime = (value?: string) => {
    if (!value) return 0;
    const timestamp = new Date(value).getTime();
    return Number.isFinite(timestamp) ? timestamp : 0;
  };
  const mergedAt = parseTime(plan.merged_at);
  const latestClipGeneratedAt = Math.max(0, ...clips.map((clip: any) => parseTime(clip.generated_at)));
  const hasClipChangesToMerge = !allClipsReady || !mergedAt || latestClipGeneratedAt > mergedAt;
  const downloadClipPrompt = () => {
    const promptText = viewingPromptClip?.prompt_text;
    if (!promptText) return;
    const clipIndex = viewingPromptClip.clip_index || viewingPromptClip.window_index || 'clip';
    const blob = new Blob([promptText], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `shot_${shot?.index || shot?.id || 'unknown'}_clip_${clipIndex}_prompt_13.txt`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <>
    <div className="flex-shrink-0 border border-gray-200 rounded-lg p-4 space-y-4 bg-white">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-gray-800 flex items-center gap-2 min-w-0">
            <Sparkles className="w-4 h-4 text-blue-600" />
            视频导演
            <span className="truncate text-xs font-normal text-gray-500">
              AI推荐：{isRecommending ? '推荐中...' : getVideoModeLabel(plan.recommended_mode)}
              {plan.recommendation_reason ? ` · ${plan.recommendation_reason}` : ''}
            </span>
          </h3>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onOpenPromptModal}
            className="px-3 py-1.5 rounded-lg border border-blue-200 bg-blue-50 text-sm text-blue-700 hover:bg-blue-100 transition-colors flex items-center gap-1.5 whitespace-nowrap"
          >
            <Copy className="w-4 h-4" />
            AI提示词
          </button>
          <button
            type="button"
            onClick={() => onRecommend(true)}
            disabled={isRecommending || !!isShotVideoGenerating}
            title={isShotVideoGenerating ? '当前 Shot 视频生成中，请等待完成后再重新推荐' : undefined}
            className="px-3 py-1.5 rounded-lg border border-gray-200 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50 transition-colors flex items-center gap-1.5 whitespace-nowrap"
          >
            <RefreshCw className={`w-4 h-4 ${isRecommending ? 'animate-spin' : ''}`} />
            重新推荐视频生成模式
          </button>
        </div>
      </div>

      {plan.notice && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {plan.notice}
        </div>
      )}

      <div className="flex gap-2">
        {renderModeButton('SINGLE_FRAME')}
        {renderModeButton('FIRST_LAST_FRAME', !firstLastAvailable, `当前 Workflow 单次最大 ${maxClipDuration}s，本 Shot ${shot?.duration || 0}s`)}
        {renderModeButton('MULTI_KEYFRAME')}
      </div>

      {selectedMode === 'MULTI_KEYFRAME' && (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-blue-100 bg-blue-50 px-3 py-2">
          <div className="text-xs text-blue-700">
            #08 只规划关键帧时间轴和 3/4 帧 window_plans；关键帧图片需在规划后单独生成。
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => onPlanKeyframes(true)}
              disabled={isPlanningKeyframes || !!isShotVideoGenerating}
              title={isShotVideoGenerating ? '当前 Shot 视频生成中，请等待完成后再重新规划关键帧' : undefined}
              className="px-3 py-1.5 rounded-lg border border-blue-200 bg-white text-sm text-blue-700 hover:bg-blue-50 disabled:opacity-50 transition-colors whitespace-nowrap"
            >
              {isPlanningKeyframes ? '规划中...' : hasWindowPlans ? '重新规划关键帧' : 'AI规划关键帧'}
            </button>
              <button
                type="button"
                onClick={onGenerateMissingKeyframes}
              disabled={isPlanningKeyframes || isGeneratingMissingKeyframes || hasGeneratingMissingKeyframes || !hasWindowPlans || missingKeyframes.length === 0 || !!isShotVideoGenerating}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-600 text-sm text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors whitespace-nowrap"
                title={isShotVideoGenerating ? '当前 Shot 视频生成中，请等待完成后再生成关键帧' : !hasWindowPlans ? '请先完成 #08 关键帧规划' : ''}
              >
              {(isGeneratingMissingKeyframes || hasGeneratingMissingKeyframes) && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              {isGeneratingMissingKeyframes ? '正在提交关键帧任务...' : missingKeyframeButtonLabel}
              </button>
          </div>
        </div>
      )}

      {selectedMode === 'SINGLE_FRAME' && (
        <div className="grid grid-cols-[minmax(260px,45%)_1fr] gap-4">
          <div>
            <div className="text-xs font-medium text-gray-600 mb-2">起始帧</div>
            <div className="relative aspect-video rounded-lg bg-gray-100 overflow-hidden border border-gray-200">
              {shotImageUrl ? (
                <>
                  <img src={shotImageUrl} alt="当前主分镜图" className="w-full h-full object-cover" />
                  <div className="absolute top-2 right-2 z-10 flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => onPreviewImage(shotImageUrl)}
                      className="p-2 rounded-full bg-black/70 text-white shadow-lg ring-1 ring-white/30 transition-all hover:bg-black/85 hover:text-blue-300"
                      title="查看大图"
                    >
                      <Eye className="h-4 w-4" />
                    </button>
                    <button
                      type="button"
                      onClick={() => onEditImage({ type: 'shot', imageUrl: shotImageUrl, itemName: `镜${shot?.index || ''} 起始帧` })}
                      className="p-2 rounded-full bg-black/70 text-white shadow-lg ring-1 ring-white/30 transition-all hover:bg-black/85 hover:text-blue-300"
                      title="编辑图片"
                    >
                      <Image className="h-4 w-4" />
                    </button>
                  </div>
                </>
              ) : (
                <div className="w-full h-full flex items-center justify-center text-gray-400">
                  <Image className="w-8 h-8" />
                </div>
              )}
            </div>
          </div>
          <div className="space-y-3">
            <div>
              <div className="text-xs font-medium text-gray-600 mb-1">动态描述</div>
              <div className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-700 min-h-20 whitespace-pre-wrap">
                {shot?.video_description || '暂无 video_description'}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2 text-sm">
              <div className="rounded-lg border border-gray-200 px-3 py-2 flex items-center justify-between">主分镜图 <Check className={`w-4 h-4 ${shotImageUrl ? 'text-green-600' : 'text-gray-300'}`} /></div>
              <div className="rounded-lg border border-gray-200 px-3 py-2 flex items-center justify-between">Video Prompt <Check className={`w-4 h-4 ${shot?.video_description ? 'text-green-600' : 'text-gray-300'}`} /></div>
              <div className="rounded-lg border border-gray-200 px-3 py-2 flex items-center justify-between">Workflow <Check className="w-4 h-4 text-green-600" /></div>
              <div className="rounded-lg border border-gray-200 px-3 py-2 flex items-center justify-between">duration {shot?.duration || 0}s {'<='} {maxClipDuration}s <Check className={`w-4 h-4 ${(shot?.duration || 0) <= maxClipDuration ? 'text-green-600' : 'text-amber-500'}`} /></div>
            </div>
          </div>
        </div>
      )}

      {selectedMode === 'FIRST_LAST_FRAME' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between gap-3 rounded-lg border border-blue-100 bg-blue-50 px-3 py-2">
            <div className="text-xs text-blue-700">
              {t('chapterGenerate.firstLastPlanNotice')}
            </div>
            <button
              type="button"
              onClick={() => onPlanKeyframes(true)}
              disabled={isPlanningKeyframes}
              className="px-3 py-1.5 rounded-lg border border-blue-200 bg-white text-sm text-blue-700 hover:bg-blue-50 disabled:opacity-50 transition-colors whitespace-nowrap"
            >
              {isPlanningKeyframes ? t('chapterGenerate.planning') : firstLastTransition ? t('chapterGenerate.replanFirstLastFrame') : t('chapterGenerate.aiPlanFirstLastFrame')}
            </button>
          </div>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div className="rounded-lg border border-gray-200 bg-white p-3">
              <div className="mb-2 flex items-center justify-between">
                <div>
                  <div className="text-xs font-semibold text-gray-600">START · 0s</div>
                  <div className="text-[11px] text-gray-500">KF{startKeyframe.index} · {t('chapterGenerate.primaryStoryboard')}</div>
                </div>
                <span className={`text-xs ${shotImageUrl ? 'text-green-600' : 'text-amber-600'}`}>{shotImageUrl ? t('chapterGenerate.imageReady') : t('chapterGenerate.missingPrimaryStoryboard')}</span>
              </div>
              <div className="relative aspect-video rounded-lg bg-gray-100 overflow-hidden border border-gray-200 flex items-center justify-center">
                {shotImageUrl ? (
                  <>
                    <img src={shotImageUrl} alt="START" className="w-full h-full object-cover" />
                    <div className="absolute top-2 right-2 z-10 flex items-center gap-2">
                      <button type="button" onClick={() => onPreviewImage(shotImageUrl)} className="p-2 rounded-full bg-black/70 text-white shadow-lg ring-1 ring-white/30 hover:bg-black/85 hover:text-blue-300" title={t('chapterGenerate.viewLargeImage')}><Eye className="h-4 w-4" /></button>
                      <button type="button" onClick={() => onEditImage({ type: 'shot', imageUrl: shotImageUrl, itemName: `${t('chapterGenerate.shot')}${shot?.index || ''} START` })} className="p-2 rounded-full bg-black/70 text-white shadow-lg ring-1 ring-white/30 hover:bg-black/85 hover:text-blue-300" title={t('chapterGenerate.editImage')}><Image className="h-4 w-4" /></button>
                    </div>
                  </>
                ) : <Image className="w-10 h-10 text-gray-300" />}
              </div>
            </div>
            <div className="rounded-lg border border-gray-200 bg-white p-3">
              <div className="mb-2 flex items-center justify-between">
                <div>
                  <div className="text-xs font-semibold text-gray-600">END · {endKeyframe.time_seconds || shot?.duration || 0}s</div>
                  <div className="text-[11px] text-gray-500">KF{endKeyframe.index} · {t('chapterGenerate.generatedKeyframe')}</div>
                </div>
                <span className={`text-xs ${endKeyframeImageUrl ? 'text-green-600' : isGeneratingEndKeyframe ? 'text-blue-600' : 'text-amber-600'}`}>
                  {endKeyframeImageUrl ? t('chapterGenerate.imageReady') : isGeneratingEndKeyframe ? t('chapterGenerate.generatingShort') : t('chapterGenerate.pending')}
                </span>
              </div>
              <div className="relative aspect-video rounded-lg bg-gray-100 overflow-hidden border border-gray-200 flex items-center justify-center">
                {endKeyframeImageUrl ? (
                  <>
                    <img src={endKeyframeImageUrl} alt="END" className="w-full h-full object-cover" />
                    <div className="absolute top-2 right-2 z-10 flex items-center gap-2">
                      <button type="button" onClick={() => onPreviewImage(endKeyframeImageUrl)} className="p-2 rounded-full bg-black/70 text-white shadow-lg ring-1 ring-white/30 hover:bg-black/85 hover:text-blue-300" title={t('chapterGenerate.viewLargeImage')}><Eye className="h-4 w-4" /></button>
                      <button type="button" onClick={() => onEditImage({ type: 'keyframe', imageUrl: endKeyframeImageUrl, itemName: `${t('chapterGenerate.shot')}${shot?.index || ''} END`, frameIndex: getKeyframeFrameIndex(endKeyframe) })} className="p-2 rounded-full bg-black/70 text-white shadow-lg ring-1 ring-white/30 hover:bg-black/85 hover:text-blue-300" title={t('chapterGenerate.editImage')}><Image className="h-4 w-4" /></button>
                    </div>
                  </>
                ) : isGeneratingEndKeyframe ? (
                  <div className="flex flex-col items-center gap-2 text-blue-600">
                    <Loader2 className="h-8 w-8 animate-spin" />
                    <div className="text-sm">{t('chapterGenerate.endKeyframeGenerating')}</div>
                  </div>
                ) : (
                  <Image className="w-10 h-10 text-gray-300" />
                )}
              </div>
              <div className="mt-2">
                <div className="mb-1 flex items-center justify-between gap-2">
                  <div className="text-xs font-semibold text-gray-600">{t('chapterGenerate.keyframeDescription')}</div>
                  <button
                    type="button"
                    onClick={() => setIsEndDescriptionExpanded((expanded) => !expanded)}
                    className="text-xs text-blue-600 hover:text-blue-700"
                  >
                    {isEndDescriptionExpanded ? t('chapterGenerate.hide') : t('chapterGenerate.show')}
                  </button>
                </div>
                {isEndDescriptionExpanded && (
                  <textarea
                    readOnly
                    value={endKeyframe.description || t('chapterGenerate.waitingAiEndFramePlan')}
                    className="w-full h-40 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm resize-none"
                  />
                )}
              </div>
              <div className="relative mt-2 inline-flex">
                <button
                  type="button"
                  onClick={() => onGenerateEndKeyframe('llm')}
                  disabled={isPlanningKeyframes || isGeneratingEndKeyframe || !endKeyframe.description || !!isShotVideoGenerating}
                  title={isShotVideoGenerating ? '当前 Shot 视频生成中，请等待完成后再生成 END 关键帧' : undefined}
                  className="inline-flex items-center gap-1.5 rounded-l-md border border-blue-200 px-3 py-1.5 text-xs text-blue-700 hover:bg-blue-50 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isGeneratingEndKeyframe && <Loader2 className="h-3 w-3 animate-spin" />}
                  {isGeneratingEndKeyframe ? t('chapterGenerate.endKeyframeGenerating') : endKeyframeImageUrl ? t('chapterGenerate.llmRegenerateEndKeyframe') : t('chapterGenerate.llmGenerateEndKeyframe')}
                </button>
                <button
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation();
                    setShowEndKeyframeMenu(prev => !prev);
                  }}
                  disabled={isPlanningKeyframes || isGeneratingEndKeyframe || !endKeyframe.description || !!isShotVideoGenerating}
                  title={isShotVideoGenerating ? '当前 Shot 视频生成中，请等待完成后再选择 END 关键帧生成模式' : undefined}
                  className="inline-flex items-center rounded-r-md border border-l-0 border-blue-200 px-2 py-1.5 text-xs text-blue-700 hover:bg-blue-50 disabled:opacity-50 disabled:cursor-not-allowed"
                  aria-label={t('chapterGenerate.selectEndKeyframeGenerateMode')}
                >
                  <ChevronDown className="h-3.5 w-3.5" />
                </button>
                {showEndKeyframeMenu && (
                    <div className="absolute left-0 top-full z-[80] mt-1 w-52 rounded-lg border border-gray-200 bg-white py-1 shadow-lg">
                    <button
                      type="button"
                      onClick={() => {
                        setShowEndKeyframeMenu(false);
                        onGenerateEndKeyframe('llm');
                      }}
                      className="w-full px-3 py-2 text-left text-xs text-gray-700 hover:bg-blue-50"
                    >
                      {t('chapterGenerate.llmRegenerateEndKeyframe')}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setShowEndKeyframeMenu(false);
                        onGenerateEndKeyframe('image_only');
                      }}
                      disabled={!hasReusableEndKeyframePrompt || !!isShotVideoGenerating}
                      title={isShotVideoGenerating ? '当前 Shot 视频生成中，请等待完成后再生成 END 关键帧' : !hasReusableEndKeyframePrompt ? t('chapterGenerate.noReusableEndKeyframePrompt') : undefined}
                      className="w-full px-3 py-2 text-left text-xs text-gray-700 hover:bg-blue-50 disabled:cursor-not-allowed disabled:text-gray-400 disabled:hover:bg-white"
                    >
                      {t('chapterGenerate.regenerateEndKeyframeOnly')}
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
          <div>
            <div className="mb-1 flex items-center justify-between">
              <div className="text-xs font-semibold text-gray-600">{t('chapterGenerate.transitionLabel')} · KF1 → KF2 · 0-{shot?.duration || 0}s</div>
              <span className={`text-xs ${firstLastTransition?.transition_description ? 'text-green-600' : endKeyframe.description ? 'text-amber-600' : 'text-gray-500'}`}>
                {firstLastTransition?.transition_description ? t('chapterGenerate.planned') : endKeyframe.description ? t('chapterGenerate.notPlanned') : t('chapterGenerate.waitingFirstLastPlan')}
              </span>
            </div>
            <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm text-gray-700 min-h-20 whitespace-pre-wrap">
              {firstLastTransition?.transition_description || (endKeyframe.description ? t('chapterGenerate.waitingStartEndTransitionPlan') : t('chapterGenerate.waitingFirstLastPlanStep'))}
            </div>
          </div>
        </div>
      )}

      {selectedMode === 'MULTI_KEYFRAME' && (
        <div className="space-y-4">
          <div>
            <div className="flex items-center justify-between mb-2">
              <div>
                <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                  <span className="text-sm font-semibold text-gray-700">{t('chapterGenerate.keyframeTimeline')}</span>
                  <span className="text-xs font-normal text-gray-500">{t('chapterGenerate.keyframeTimelineSummary', { keyframes: keyframes.length, transitions: Math.max(0, keyframes.length - 1), clips: clips.length, maxClipDuration })}</span>
                </div>
              </div>
            </div>
            <div className="rounded-lg border border-gray-200 bg-white px-3 py-2">
              {clips.length > 0 && (
                <div className="mb-2 flex gap-2 overflow-x-auto pb-1">
                  {clips.map((clip: any) => {
                    const clipIndex = clip.clip_index || clip.window_index;
                    const frameCount = clip.selected_frame_count || clip.frame_count;
                    const isClipSelected = selectedClip && getClipKey(selectedClip) === getClipKey(clip);
                    return (
                      <button
                        key={`range-${getClipKey(clip)}`}
                        type="button"
                        onClick={() => {
                          setSelectedClipKey(getClipKey(clip));
                          const firstKeyframeIndex = Array.isArray(clip.keyframe_indexes) ? Number(clip.keyframe_indexes[0]) : NaN;
                          const targetIndex = keyframes.findIndex((kf: any) => Number(kf.index) === firstKeyframeIndex);
                          if (targetIndex >= 0) setSelectedKeyframeIndex(targetIndex);
                        }}
                        className={`h-8 min-w-40 rounded-md border px-2 text-left text-xs transition-all ${isClipSelected
                          ? 'border-blue-300 bg-blue-50 text-blue-700 ring-1 ring-blue-100'
                          : 'border-gray-200 bg-gray-50 text-gray-600 hover:border-blue-200 hover:bg-blue-50/60'
                        }`}
                      >
                        C{clipIndex} · {clip.start_time}-{clip.end_time}s · {frameCount || '?'}KF
                      </button>
                    );
                  })}
                </div>
              )}
              <div className="flex items-start gap-2 overflow-x-auto pb-1">
                {keyframes.map((kf, idx) => {
                  const isCurrentKeyframe = selectedKeyframeIndex === idx;
                  const isInSelectedClip = selectedClipKeyframes.has(Number(kf.index));
                  const keyframeClipCount = clips.filter((clip: any) => clipContainsKeyframe(clip, Number(kf.index))).length;
                  const hasImage = !!getKeyframeImageUrl(kf);
                  const isGenerating = isKeyframeGenerating(kf);
                  const marker = keyframeClipCount > 1 ? '⇄' : kf.role === 'START' || kf.role === 'END' ? '★' : '◇';
                  return (
                    <button
                      key={`${kf.index}-${kf.time_seconds}`}
                      type="button"
                      onClick={() => {
                        setSelectedKeyframeIndex(idx);
                        setSelectedClipKey(null);
                      }}
                      title={`${kf.role}${keyframeClipCount > 1 ? ` · ${t('chapterGenerate.sharedBoundary')}` : ''}${isGenerating ? ` · ${t('chapterGenerate.generatingShort')}` : hasImage ? ` · ${t('chapterGenerate.generated')}` : ` · ${t('chapterGenerate.missingImage')}`}`}
                      className={`relative h-14 min-w-24 rounded-lg px-2 py-1 text-center transition-all ${isCurrentKeyframe
                        ? 'border border-blue-300 bg-blue-50 text-blue-700 shadow-sm ring-2 ring-blue-100'
                        : isInSelectedClip
                          ? 'border border-blue-100 bg-blue-50/50 text-blue-700'
                          : 'border border-transparent text-gray-700 hover:bg-gray-50 hover:text-blue-600'
                      }`}
                    >
                      <div className="flex items-center justify-center gap-1 text-[11px] text-gray-500">
                        {isGenerating ? <Loader2 className="h-3 w-3 animate-spin text-blue-500" /> : <span className={`h-2.5 w-2.5 rounded-full border ${hasImage ? 'border-green-500 bg-green-100' : 'border-gray-400 bg-gray-100'}`} />}
                        <span>{marker}</span>
                      </div>
                      <div className="mt-0.5 text-xs font-semibold">KF{kf.index} · {kf.time_seconds}s</div>
                      <div className={`text-[11px] ${isGenerating ? 'text-blue-600' : hasImage ? 'text-green-600' : 'text-amber-600'}`}>{isGenerating ? t('chapterGenerate.generatingShort') : hasImage ? t('chapterGenerate.generated') : t('chapterGenerate.missingImage')}</div>
                      {isCurrentKeyframe && <div className="absolute -bottom-1 left-2 right-2 h-1 rounded-full bg-blue-500" />}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-[minmax(260px,45%)_1fr] gap-4">
            <div>
              <div className="relative aspect-video rounded-lg bg-gray-100 overflow-hidden border border-gray-200 flex items-center justify-center">
                {isKeyframeGenerating(selectedKeyframe) ? (
                  <div className="flex flex-col items-center gap-2 text-blue-500">
                    <Loader2 className="w-10 h-10 animate-spin" />
                    <div className="text-sm">{t('chapterGenerate.keyframeImageGenerating')}</div>
                  </div>
                ) : getKeyframeImageUrl(selectedKeyframe) ? (
                  <>
                    <img src={getKeyframeImageUrl(selectedKeyframe)!} alt={`KF${selectedKeyframe.index}`} className="w-full h-full object-cover" />
                    <div className="absolute top-2 right-2 z-10 flex items-center gap-2">
                      <button type="button" onClick={() => onPreviewImage(getKeyframeImageUrl(selectedKeyframe)!)} className="p-2 rounded-full bg-black/70 text-white shadow-lg ring-1 ring-white/30 transition-all hover:bg-black/85 hover:text-blue-300" title={t('chapterGenerate.viewLargeImage')}><Eye className="h-4 w-4" /></button>
                      <button type="button" onClick={() => onEditImage({ type: selectedKeyframe?.role === 'START' ? 'shot' : 'keyframe', imageUrl: getKeyframeImageUrl(selectedKeyframe)!, itemName: `${t('chapterGenerate.shot')}${shot?.index || ''} KF${selectedKeyframe?.index || ''}`, frameIndex: getKeyframeFrameIndex(selectedKeyframe) })} className="p-2 rounded-full bg-black/70 text-white shadow-lg ring-1 ring-white/30 transition-all hover:bg-black/85 hover:text-blue-300" title={t('chapterGenerate.editImage')}><Image className="h-4 w-4" /></button>
                    </div>
                  </>
                ) : shotImageUrl && selectedKeyframe?.role === 'START' ? (
                  <>
                    <img src={shotImageUrl} alt="START" className="w-full h-full object-cover" />
                    <div className="absolute top-2 right-2 z-10 flex items-center gap-2">
                      <button type="button" onClick={() => onPreviewImage(shotImageUrl)} className="p-2 rounded-full bg-black/70 text-white shadow-lg ring-1 ring-white/30 transition-all hover:bg-black/85 hover:text-blue-300" title={t('chapterGenerate.viewLargeImage')}><Eye className="h-4 w-4" /></button>
                      <button type="button" onClick={() => onEditImage({ type: 'shot', imageUrl: shotImageUrl, itemName: `${t('chapterGenerate.shot')}${shot?.index || ''} START` })} className="p-2 rounded-full bg-black/70 text-white shadow-lg ring-1 ring-white/30 transition-all hover:bg-black/85 hover:text-blue-300" title={t('chapterGenerate.editImage')}><Image className="h-4 w-4" /></button>
                    </div>
                  </>
                ) : (
                  <Image className="w-12 h-12 text-gray-300" />
                )}
              </div>
              <div className="mt-2 flex items-center justify-between">
                <span className="text-sm font-medium text-gray-700">KF{selectedKeyframe?.index || 1} · {selectedKeyframe?.time_seconds || 0}s</span>
                <span className={`text-xs ${getKeyframeImageUrl(selectedKeyframe) ? 'text-green-600' : 'text-amber-600'}`}>
                  {isKeyframeGenerating(selectedKeyframe) ? t('chapterGenerate.imageGenerating') : getKeyframeImageUrl(selectedKeyframe) ? t('chapterGenerate.imageReady') : t('chapterGenerate.waitingImageGeneration')}
                </span>
              </div>
            </div>
            <div className="space-y-3">
              <div>
                <div className="text-xs font-semibold text-gray-600 mb-1">{t('chapterGenerate.keyframeDescription')}</div>
                <textarea
                  readOnly
                  value={selectedKeyframe?.role === 'START' ? (shot?.description || '') : (selectedKeyframe?.description || '')}
                  className="w-full h-28 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm resize-none"
                />
              </div>
              <div>
                <div className="text-xs font-semibold text-gray-600 mb-1">
                  {t('chapterGenerate.previousTransition')}{previousTransition ? ` · KF${previousTransition.from_keyframe_index} → KF${previousTransition.to_keyframe_index} · ${previousTransition.start_time ?? ''}-${previousTransition.end_time ?? ''}s` : ''}
                </div>
                <textarea
                  readOnly
                  value={previousTransition?.transition_description || ''}
                  placeholder={selectedKeyframeIndex === 0 ? t('chapterGenerate.noPreviousTransition') : t('chapterGenerate.waitingPreviousTransitionPlan')}
                  className="w-full h-20 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm resize-none"
                />
              </div>
              <div>
                <div className="text-xs font-semibold text-gray-600 mb-1">
                  {t('chapterGenerate.nextTransition')}{nextTransition ? ` · KF${nextTransition.from_keyframe_index} → KF${nextTransition.to_keyframe_index} · ${nextTransition.start_time ?? ''}-${nextTransition.end_time ?? ''}s` : ''}
                </div>
                <textarea
                  readOnly
                  value={nextTransition?.transition_description || ''}
                  placeholder={hasNextKeyframe ? t('chapterGenerate.waitingNextTransitionPlan') : t('chapterGenerate.noNextTransition')}
                  className="w-full h-20 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm resize-none"
                />
              </div>
            </div>
          </div>

        </div>
      )}

      <div className="rounded-lg border border-gray-200 bg-white p-3">
        <div className="flex items-center justify-between gap-3 mb-2">
          <div className="text-sm font-semibold text-gray-700">{t('chapterGenerate.executionPlan')} · {clips.length} {t('chapterGenerate.clips')}</div>
          <div className="text-xs text-gray-500">{t('chapterGenerate.estimatedH3Tasks', { count: clips.length })}</div>
        </div>
        {selectedMode === 'MULTI_KEYFRAME' && (
          <div className="grid grid-cols-2 gap-2 text-sm mb-3">
            <div className="rounded-lg border border-gray-200 px-3 py-2 flex items-center justify-between">{t('chapterGenerate.threeFrameClips')} <span className="font-semibold text-gray-800">{threeFrameClipCount}</span></div>
            <div className="rounded-lg border border-gray-200 px-3 py-2 flex items-center justify-between">{t('chapterGenerate.fourFrameClips')} <span className="font-semibold text-gray-800">{fourFrameClipCount}</span></div>
          </div>
        )}
        {clips.length > 0 ? (
          <div className="grid grid-cols-[repeat(auto-fit,minmax(320px,1fr))] gap-3">
            {clips.map((clip: any) => {
              const clipIndex = clip.clip_index || clip.window_index;
              const frameCount = clip.selected_frame_count || clip.frame_count;
              const clipHasVideo = !!(clip.video_url || clip.local_path || (selectedMode !== 'MULTI_KEYFRAME' && shot?.videoUrl));
              const clipStatus = clip.status || (clipHasVideo ? 'SUCCEEDED' : 'NOT_STARTED');
              const clipKey = getClipKey(clip);
              const isPreviewing = selectedPreviewClipKey === clipKey;
              const isRegenerating = regeneratingClipKey === clipKey;
              const clipAudioStatus = String(clip.audio_status || clip.audioStatus || '').toUpperCase() || 'NOT_READY';
              const clipDriveAudioUrl = clip.drive_audio_url || clip.driveAudioUrl;
              const clipFinalAudioUrl = clip.final_audio_url || clip.finalAudioUrl;
              const clipSpeakerTimeline = Array.isArray(clip.speaker_timeline) ? clip.speaker_timeline : Array.isArray(clip.speakerTimeline) ? clip.speakerTimeline : [];
              const clipAudioReady = clipAudioStatus === 'READY' && !!clipDriveAudioUrl && !!clipFinalAudioUrl;
              const driveTextEvents = getClipAudioEventTexts(shot, clip, true);
              const finalTextEvents = getClipAudioEventTexts(shot, clip, false);
              const clipGenerationDisabled = isRegenerating || !!isShotVideoGenerating || !clipAudioReady;
              const clipFrameLabel = selectedMode === 'SINGLE_FRAME'
                ? t('chapterGenerate.primaryStoryboard')
                : selectedMode === 'FIRST_LAST_FRAME'
                  ? t('chapterGenerate.firstLastFrame')
                  : Array.isArray(clip.keyframe_indexes) && clip.keyframe_indexes.length > 0
                    ? clip.keyframe_indexes.map((item: number) => `KF${item}`).join(' / ')
                    : t('chapterGenerate.waitingKeyframes');
              const clipTitleFrameLabel = selectedMode === 'SINGLE_FRAME'
                ? t('chapterGenerate.singleFrame')
                : selectedMode === 'FIRST_LAST_FRAME'
                  ? t('chapterGenerate.firstLastFrame')
                  : `${frameCount || '?'}KF`;
              const clipReferenceImages = Array.isArray(clip.reference_images) && clip.reference_images.length > 0
                ? clip.reference_images
                : (Array.isArray(clip.keyframe_indexes) ? clip.keyframe_indexes : [])
                  .map((keyframeIndex: number) => {
                    const keyframe = keyframes.find((item: any) => Number(item.index) === Number(keyframeIndex));
                    const url = getKeyframeImageUrl(keyframe);
                    return url ? { url, label: `C${clipIndex} · KF${keyframeIndex}` } : null;
                  })
                  .filter(Boolean);
              const clipDialogues = getClipDialoguesForDisplay(shot, clip)
                .map((dialogue: any, dialogueIndex: number) => {
                  const text = dialogueText(dialogue);
                  const emotion = dialogueEmotion(dialogue);
                  return {
                    key: `${clipKey}-dialogue-${dialogueIndex}`,
                    speaker: dialogueSpeaker(dialogue) || '旁白',
                    text,
                    emotion,
                    minRequiredSeconds: estimateDialogueSeconds(text, emotion),
                  };
                })
                .filter((dialogue: any) => dialogue.text);
              const clipDuration = Math.max(0, (numberOrNull(clip.end_time) ?? numberOrNull(shot?.duration) ?? 0) - (numberOrNull(clip.start_time) ?? 0));
              const totalMinDialogueSeconds = clipDialogues.reduce((sum: number, dialogue: any) => sum + dialogue.minRequiredSeconds, 0);
              const dialogueDurationInsufficient = clipDialogues.length > 0 && clipDuration > 0 && totalMinDialogueSeconds > clipDuration + 0.05;
              return (
                <div key={`${clipIndex}-${clip.start_time}-${clip.end_time}`} className={`rounded-lg border p-3 ${isPreviewing ? 'border-blue-300 bg-blue-50 ring-2 ring-blue-100' : 'border-gray-200 bg-white'}`}>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-semibold text-gray-800">C{clipIndex} · {clip.start_time}-{clip.end_time}s · {clipTitleFrameLabel}</div>
                      <div className="mt-1 text-xs text-gray-500">
                        {clipFrameLabel}
                        {clip.workflow_key ? ` · ${clip.workflow_key}` : ''}
                      </div>
                    </div>
                    <span className={`rounded-md border px-2 py-1 text-xs ${getClipStatusClass(clipStatus)}`}>{getClipStatusLabel(clipStatus)}</span>
                  </div>
                  {clipReferenceImages.length > 0 && (
                    <div className="mt-3 flex gap-2 overflow-x-auto pb-1">
                      {clipReferenceImages.map((image: any, imageIndex: number) => (
                        <div key={`${clipKey}-ref-${imageIndex}`} className="w-24 flex-shrink-0">
                          <div className="aspect-video overflow-hidden rounded border border-gray-200 bg-gray-100">
                            {image.url ? <img src={image.url} alt={image.label || `C${clipIndex}参考图`} className="h-full w-full object-cover" /> : <Image className="m-auto mt-4 h-5 w-5 text-gray-300" />}
                          </div>
                          <div className="mt-1 truncate text-[10px] text-gray-500">{image.label || `参考图 ${imageIndex + 1}`}</div>
                        </div>
                      ))}
                    </div>
                  )}
                  <div className={`mt-3 rounded-lg border px-3 py-2 text-xs ${dialogueDurationInsufficient ? 'border-red-200 bg-red-50 text-red-700' : 'border-gray-200 bg-gray-50 text-gray-700'}`}>
                    <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
                      <span className="font-medium">AudioDrive Clip 音频</span>
                      <span className={dialogueDurationInsufficient ? 'text-red-700' : 'text-gray-500'}>
                        {clipAudioReady ? 'READY' : clipAudioStatus} · Clip {clipDuration ? `${clipDuration.toFixed(2)}s` : '-'}
                      </span>
                    </div>
                    <div className="space-y-2">
                      {(clipDriveAudioUrl || clipFinalAudioUrl) ? (
                        <div className="grid grid-cols-1 gap-2 xl:grid-cols-2">
                          {clipDriveAudioUrl && (
                            <div className="rounded border border-cyan-100 bg-white px-2 py-1.5">
                              <div className="mb-1 font-medium text-cyan-700">Drive 音频 · 可见口型</div>
                              <audio src={clipDriveAudioUrl} controls preload="metadata" className="h-8 w-full" />
                              <div className="mt-2 space-y-1 rounded bg-cyan-50/70 px-2 py-1 text-[11px] text-cyan-800">
                                <div className="font-medium">Drive 台词 · {driveTextEvents.reduce((sum: number, item: any) => sum + item.charCount, 0)} 字</div>
                                {driveTextEvents.length > 0 ? driveTextEvents.map((item: any) => (
                                  <div key={`${clipKey}-drive-text-${item.key}`} className="leading-5">
                                    <span className="font-mono text-cyan-600">{item.start.toFixed(3)}s-{item.end.toFixed(3)}s</span>
                                    <span> · {item.speaker} · {item.charCount}字 · {item.text}</span>
                                  </div>
                                )) : <div className="text-cyan-600">无可见口型台词。</div>}
                              </div>
                            </div>
                          )}
                          {clipFinalAudioUrl && (
                            <div className="rounded border border-purple-100 bg-white px-2 py-1.5">
                              <div className="mb-1 font-medium text-purple-700">Final 音频 · 最终听感</div>
                              <audio src={clipFinalAudioUrl} controls preload="metadata" className="h-8 w-full" />
                              <div className="mt-2 space-y-1 rounded bg-purple-50/70 px-2 py-1 text-[11px] text-purple-800">
                                <div className="font-medium">Final 文本 · {finalTextEvents.reduce((sum: number, item: any) => sum + item.charCount, 0)} 字</div>
                                {finalTextEvents.length > 0 ? finalTextEvents.map((item: any) => (
                                  <div key={`${clipKey}-final-text-${item.key}`} className="leading-5">
                                    <span className="font-mono text-purple-600">{item.start.toFixed(3)}s-{item.end.toFixed(3)}s</span>
                                    <span> · {item.speaker} · {item.charCount}字 · {item.text}</span>
                                  </div>
                                )) : <div className="text-purple-600">无最终听感文本。</div>}
                              </div>
                            </div>
                          )}
                        </div>
                      ) : (
                        <div className="rounded border border-dashed border-amber-200 bg-amber-50 px-2 py-1 text-amber-700">尚未构建 drive/final 音频，请到音频生成页构建 Clip Audio。</div>
                      )}
                      <ClipAudioTimeline
                        clipDuration={clipDuration}
                        speakerTimeline={clipSpeakerTimeline}
                        driveTextEvents={driveTextEvents}
                        finalTextEvents={finalTextEvents}
                      />
                      {clipDialogues.length > 0 && (
                        <div className="rounded border border-amber-100 bg-amber-50 px-2 py-1 text-amber-700">
                          <div className="font-medium">兼容旧台词参考 · 非 H3 控制源</div>
                          <div className="mt-0.5">最低所需 {totalMinDialogueSeconds.toFixed(2)}s，AudioDrive 以 drive/final 音频和 speaker_timeline 为准。</div>
                        </div>
                      )}
                    </div>
                  </div>
                  {clip.error_message && <div className="mt-2 text-xs text-red-600">{formatUserFacingError(clip.error_message)}</div>}
                  {selectedMode === 'MULTI_KEYFRAME' && (
                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        onClick={() => onPreviewClip(clip)}
                        disabled={!clip.video_url}
                        title={!clip.video_url ? `C${clipIndex} 缺少可预览的视频记录，请重新生成该 Clip` : `预览 C${clipIndex}`}
                        className="rounded-md border border-gray-200 px-2 py-1 text-xs text-gray-700 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {clip.video_url ? '预览 Clip' : '缺少视频记录'}
                      </button>
                      <div className="relative inline-flex">
                        <button
                          type="button"
                          onClick={() => {
                            setOpenClipGenerateMenuKey(null);
                            onRegenerateClip(clip, 'llm');
                          }}
                          disabled={clipGenerationDisabled}
                          title={isShotVideoGenerating ? '当前 Shot 视频生成中，请等待完成后再操作 Clip' : !clipAudioReady ? 'Clip Audio 未 READY，请先到音频生成页构建 drive/final 音频' : undefined}
                          className="inline-flex items-center gap-1 rounded-l-md border border-blue-200 px-2 py-1 text-xs text-blue-700 hover:bg-blue-50 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          {isRegenerating && <Loader2 className="h-3 w-3 animate-spin" />}
                          {isRegenerating ? '生成中...' : 'LLM+生成Clip视频'}
                        </button>
                        <button
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation();
                            setOpenClipGenerateMenuKey(openClipGenerateMenuKey === clipKey ? null : clipKey);
                          }}
                          disabled={clipGenerationDisabled}
                          title={isShotVideoGenerating ? '当前 Shot 视频生成中，请等待完成后再选择生成模式' : !clipAudioReady ? 'Clip Audio 未 READY，请先到音频生成页构建 drive/final 音频' : undefined}
                          className="inline-flex items-center rounded-r-md border border-l-0 border-blue-200 px-2 py-1 text-xs text-blue-700 hover:bg-blue-50 disabled:opacity-50 disabled:cursor-not-allowed"
                          aria-label="选择 Clip 视频生成模式"
                        >
                          <ChevronDown className="h-3.5 w-3.5" />
                        </button>
                        {openClipGenerateMenuKey === clipKey && (
                          <div className="absolute bottom-full left-0 z-[80] mb-1 w-44 rounded-lg border border-gray-200 bg-white py-1 shadow-lg">
                            <button
                              type="button"
                              onClick={() => {
                                setOpenClipGenerateMenuKey(null);
                                onRegenerateClip(clip, 'llm');
                              }}
                              className="w-full px-3 py-2 text-left text-xs text-gray-700 hover:bg-blue-50"
                            >
                              LLM+生成Clip视频
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                setOpenClipGenerateMenuKey(null);
                                onRegenerateClip(clip, 'video_only');
                              }}
                              disabled={!clip.prompt_text || !!isShotVideoGenerating || !clipAudioReady}
                              title={isShotVideoGenerating ? '当前 Shot 视频生成中，请等待完成后再操作 Clip' : !clipAudioReady ? 'Clip Audio 未 READY，请先到音频生成页构建 drive/final 音频' : !clip.prompt_text ? '缺少可复用的 Clip 视频最终 Prompt，请先使用 LLM+生成Clip视频' : undefined}
                              className="w-full px-3 py-2 text-left text-xs text-gray-700 hover:bg-blue-50 disabled:cursor-not-allowed disabled:text-gray-400 disabled:hover:bg-white"
                            >
                              仅生成Clip视频
                            </button>
                          </div>
                        )}
                      </div>
                      {clip.prompt_text && (
                        <button type="button" onClick={() => setViewingPromptClip(clip)} className="rounded-md border border-gray-200 px-2 py-1 text-xs text-gray-700 hover:bg-gray-50">
                          查看Prompt
                        </button>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
            {selectedMode === 'MULTI_KEYFRAME' && (
              <button
                type="button"
                onClick={onMergeClips}
                disabled={!allClipsReady || !hasClipChangesToMerge || isMergingClips || !!isShotVideoGenerating}
                title={isShotVideoGenerating ? '当前 Shot 视频生成中，请等待完成后再重新合并' : !allClipsReady ? `缺少可合并的 Clip 视频：${missingClipArtifacts.join(' / ')}` : !hasClipChangesToMerge ? '没有 Clip 被重新生成，整体视频已是最新' : '使用所有 Clip 视频重新合并整体视频'}
                className="rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-sm font-medium text-green-700 hover:bg-green-100 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isMergingClips ? '重新合并中...' : missingClipArtifacts.length > 0 ? `缺少 ${missingClipArtifacts.join(' / ')} 视频记录` : !hasClipChangesToMerge ? '整体视频已是最新' : '重新合并整体视频'}
              </button>
            )}
          </div>
        ) : (
          <div className="rounded-md border border-dashed border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
            {selectedMode === 'MULTI_KEYFRAME' ? '等待 #08 生成 window_plans 后才能执行多关键帧视频。' : '暂无执行 Clip，请重新推荐或保存视频规划。'}
          </div>
        )}
      </div>
    </div>
    {viewingPromptClip?.prompt_text && (
      <div className="fixed inset-0 isolate z-[300] flex items-center justify-center bg-black/60 p-4 backdrop-blur-[1px]" onClick={() => setViewingPromptClip(null)}>
        <div className="flex max-h-[86vh] w-full max-w-5xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl" onClick={(event) => event.stopPropagation()}>
          <div className="flex items-center justify-between gap-3 border-b border-gray-200 px-5 py-4">
            <div className="min-w-0">
              <div className="text-base font-semibold text-gray-900">#13 Prompt</div>
              <div className="text-xs text-gray-500">
                C{viewingPromptClip.clip_index || viewingPromptClip.window_index || '-'} · {viewingPromptClip.start_time ?? '-'}-{viewingPromptClip.end_time ?? '-'}s
              </div>
            </div>
            <div className="flex flex-shrink-0 items-center gap-2">
              <button type="button" onClick={() => copyText(viewingPromptClip.prompt_text)} className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50">
                <Copy className="h-4 w-4" />复制
              </button>
              <button type="button" onClick={downloadClipPrompt} className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50">
                <Download className="h-4 w-4" />下载
              </button>
              <button type="button" onClick={() => setViewingPromptClip(null)} className="rounded-md p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-700">
                <X className="h-5 w-5" />
              </button>
            </div>
          </div>
          <div className="flex-1 overflow-auto bg-gray-950 p-4">
            <pre className="whitespace-pre-wrap break-words text-sm leading-6 text-gray-100">{viewingPromptClip.prompt_text}</pre>
          </div>
        </div>
      </div>
    )}
    </>
  );
}

const formatDuration = (seconds: number | null) => {
  if (!seconds || !Number.isFinite(seconds)) return '-';
  const minutes = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60).toString().padStart(2, '0');
  return `${minutes}:${secs}`;
};

const formatFileSize = (bytes: number | null) => {
  if (!bytes || !Number.isFinite(bytes)) return '-';
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
};

const formatBitrate = (bytes: number | null, duration: number | null) => {
  if (!bytes || !duration || !Number.isFinite(duration)) return '-';
  const kbps = (bytes * 8) / duration / 1000;
  return kbps >= 1000 ? `${(kbps / 1000).toFixed(2)} Mbps` : `${Math.round(kbps)} kbps`;
};

const getSavedVideoTabUiState = () => {
  try {
    const saved = localStorage.getItem(VIDEO_TAB_UI_STORAGE_KEY);
    if (!saved) {
      return { showKeyframes: true, showAudioRef: true, isSidePanelCollapsed: false };
    }

    const parsed = JSON.parse(saved) as {
      showKeyframes?: boolean;
      showAudioRef?: boolean;
      isSidePanelCollapsed?: boolean;
    };

    return {
      showKeyframes: typeof parsed.showKeyframes === 'boolean' ? parsed.showKeyframes : true,
      showAudioRef: typeof parsed.showAudioRef === 'boolean' ? parsed.showAudioRef : true,
      isSidePanelCollapsed: typeof parsed.isSidePanelCollapsed === 'boolean' ? parsed.isSidePanelCollapsed : false,
    };
  } catch {
    return { showKeyframes: true, showAudioRef: true, isSidePanelCollapsed: false };
  }
};

const saveVideoTabUiState = (state: { showKeyframes: boolean; showAudioRef: boolean; isSidePanelCollapsed: boolean }) => {
  try {
    localStorage.setItem(VIDEO_TAB_UI_STORAGE_KEY, JSON.stringify(state));
  } catch {
    // ignore localStorage errors
  }
};

interface VideoGenTabProps {
  chapter?: any;
  shotVideos?: Record<string, string>;
  shotImages?: Record<string, string>;
  transitionVideos?: Record<string, string>;
  generatingVideos?: Set<string>;
  generatingTransitions?: Set<string>;
  currentShot?: number;
  novelId?: string;
  chapterId?: string;
  shots?: any[];
}

export function VideoGenTab({
  chapter,
  shotVideos: propShotVideos = {},
  shotImages: propShotImages = {},
  transitionVideos: propTransitionVideos = {},
  generatingVideos: propGeneratingVideos,
  generatingTransitions: propGeneratingTransitions,
  currentShot,
  novelId,
  chapterId,
  shots: propShots = [],
}: VideoGenTabProps) {
  const { t } = useTranslation();
  const store = useChapterGenerateStore();
  const { markTabComplete, setCurrentShot, downloadChapterMaterials, generateShotVideo, generateKeyframeImage, setShots, setShotVideos, setShotImages, checkVideoTaskStatus, generateTransition, transitionWorkflows, selectedTransitionWorkflow, setSelectedTransitionWorkflow, fetchTransitionWorkflows, transitionDuration, setTransitionDuration } = store;

  // 直接订阅 store 状态（确保状态更新时组件重新渲染）
  const storeShots = useChapterGenerateStore((state) => state.shots);
  const storeShotVideos = useChapterGenerateStore((state) => state.shotVideos);
  const storeShotImages = useChapterGenerateStore((state) => state.shotImages);
  const storeTransitionVideos = useChapterGenerateStore((state) => state.transitionVideos);
  const storeGeneratingVideos = useChapterGenerateStore((state) => state.generatingVideos);
  const storePendingVideos = useChapterGenerateStore((state) => state.pendingVideos);
  const storeGeneratingTransitions = useChapterGenerateStore((state) => state.generatingTransitions);
  const storeGeneratingKeyframes = useChapterGenerateStore((state) => state.generatingKeyframes);
  const storeKeyframeTasks = useChapterGenerateStore((state) => state.keyframeTasks);

  // 优先使用 store 状态，props 作为备用
  const shotVideos = storeShotVideos;
  const shotImages = storeShotImages;
  const transitionVideos = storeTransitionVideos;
  const generatingVideos = propGeneratingVideos ?? storeGeneratingVideos;
  const generatingTransitions = propGeneratingTransitions ?? storeGeneratingTransitions;
  const generatingKeyframes = storeGeneratingKeyframes;

  const selectedTransitionWorkflowData = transitionWorkflows.find((workflow: any) => (
    selectedTransitionWorkflow ? workflow.id === selectedTransitionWorkflow : workflow.isActive
  ));
  const selectedTransitionDescription = selectedTransitionWorkflowData
    ? t(selectedTransitionWorkflowData.descriptionKey || '', { defaultValue: selectedTransitionWorkflowData.description || '' })
    : '';

  // 优先使用 props 传入的 novelId，否则从 chapter 对象获取
  const effectiveNovelId = novelId || chapter?.novelId;
  const effectiveChapterId = chapterId || chapter?.id;

  const [selectedVideo, setSelectedVideo] = useState<number>(1);
  const [isGeneratingAll, setIsGeneratingAll] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);
  const [showBatchSelectModal, setShowBatchSelectModal] = useState(false);
  const [selectedShotIds, setSelectedShotIds] = useState<Set<string>>(new Set());
  const [batchSelectionMode, setBatchSelectionMode] = useState<BatchSelectionMode>(null);
  const [dragSelectionMode, setDragSelectionMode] = useState<'select' | 'deselect' | null>(null);
  const [autoCompleteDetails, setAutoCompleteDetails] = useState(true);
  const [previewImage, setPreviewImage] = useState<string | null>(null);
  const [previewTransitionVideo, setPreviewTransitionVideo] = useState<string | null>(null);

  const initialVideoTabUiState = getSavedVideoTabUiState();

  // 关键帧展开状态
  const [showKeyframes, setShowKeyframes] = useState(initialVideoTabUiState.showKeyframes);

  // 音频参考展开状态
  const [showAudioRef, setShowAudioRef] = useState(initialVideoTabUiState.showAudioRef);

  const [isSidePanelCollapsed, setIsSidePanelCollapsed] = useState(initialVideoTabUiState.isSidePanelCollapsed);

  // 合并视频相关状态
  const [mergingMode, setMergingMode] = useState<MergeVideoMode | null>(null);
  const [showMergeSelectModal, setShowMergeSelectModal] = useState(false);
  const [selectedMergeShotIds, setSelectedMergeShotIds] = useState<Set<string>>(new Set());
  const [mergeSelectionMode, setMergeSelectionMode] = useState<'select' | 'deselect' | null>(null);
  const [mergeIncludeTransitions, setMergeIncludeTransitions] = useState(false);
  const [showMergeModal, setShowMergeModal] = useState(false);
  const [mergedVideoUrl, setMergedVideoUrl] = useState<string | null>(null);
  const [isRefreshingVideo, setIsRefreshingVideo] = useState(false);
  const [selectedPreviewClipKey, setSelectedPreviewClipKey] = useState<string | null>(null);
  const [regeneratingClipKey, setRegeneratingClipKey] = useState<string | null>(null);
  const [isMergingClips, setIsMergingClips] = useState(false);
  const [isCancellingVideo, setIsCancellingVideo] = useState(false);
  const [isRefreshingAiCalls, setIsRefreshingAiCalls] = useState(false);
  const [showGenerateVideoMenu, setShowGenerateVideoMenu] = useState(false);
  const [isVideoPromptModalOpen, setIsVideoPromptModalOpen] = useState(false);
  const [videoPromptDrafts, setVideoPromptDrafts] = useState<VideoPromptDraft[]>([]);
  const [isSavingVideoPrompts, setIsSavingVideoPrompts] = useState(false);
  const [imageEditTarget, setImageEditTarget] = useState<VideoImageEditTarget | null>(null);
  const [imageEditResultUrl, setImageEditResultUrl] = useState<string | null>(null);
  const [imageEditResultSize, setImageEditResultSize] = useState<{ width: number; height: number } | null>(null);
  const [isEditingImage, setIsEditingImage] = useState(false);
  const [isReplacingImage, setIsReplacingImage] = useState(false);
  const [videoMetadata, setVideoMetadata] = useState<VideoMetadata>({
    duration: null,
    width: null,
    height: null,
    sizeBytes: null,
  });
  const previewVideoRef = useRef<HTMLVideoElement | null>(null);

  // 统一使用 store.shots 作为分镜数据源
  const shotsList = storeShots.length > 0 ? storeShots : propShots;
  const currentShotData = shotsList[selectedVideo - 1];

  // 获取当前分镜的关键帧数据
  const currentKeyframes: KeyframeData[] = currentShotData?.keyframes || [];
  const currentShotId = currentShotData?.id ? String(currentShotData.id) : String(selectedVideo);
  // 优先从 shot.imageUrl 获取，其次从 shotImages 映射获取
  const currentShotImageUrl = currentShotData?.imageUrl || shotImages[currentShotId];

  // 获取当前分镜的视频 URL（shotVideos 使用 shot.id 作为 key）
  const currentShotVideoUrl = currentShotData?.videoUrl || (currentShotId ? shotVideos[currentShotId] : undefined);
  const currentVideoDirectorPlan: VideoDirectorPlan = currentShotData?.videoDirectorPlan || {};
  const currentSelectedVideoMode = currentVideoDirectorPlan.selected_mode || currentVideoDirectorPlan.recommended_mode || 'SINGLE_FRAME';
  const hasReusableVideoPrompt = currentSelectedVideoMode === 'MULTI_KEYFRAME'
    ? !!currentVideoDirectorPlan.window_plans?.length && currentVideoDirectorPlan.window_plans.every((windowPlan: any) => String(windowPlan?.prompt_text || '').trim().length > 0)
    : [...(currentVideoDirectorPlan.ai_calls || [])].reverse().some((call: any) => String(call?.final_prompt || '').trim().length > 0);
  const currentEndPlanKeyframe = (currentVideoDirectorPlan.keyframes || []).find((keyframe: any) => keyframe.role === 'END');
  const currentEndLegacyKeyframe = (currentShotData?.keyframes || []).find((keyframe: any) => (
    Number(keyframe.plan_keyframe_index) === Number(currentEndPlanKeyframe?.index || 2)
  ));
  const currentEndFrameIndex = currentEndLegacyKeyframe?.frame_index ?? (currentEndPlanKeyframe ? 0 : undefined);
  const isGeneratingCurrentEndKeyframe = currentShotId && currentEndFrameIndex !== undefined
    ? generatingKeyframes.has(`${currentShotId}-${Number(currentEndFrameIndex)}`)
    : false;
  const getPlanClipKey = (clip: any) => String(clip?.clip_index || clip?.window_index || `${clip?.start_time}-${clip?.end_time}`);
  const currentPlanClips: any[] = mergeClipAudioWindows(currentVideoDirectorPlan, currentSelectedVideoMode);
  const currentMultiKeyframePlanReady = currentSelectedVideoMode !== 'MULTI_KEYFRAME' || (
    Array.isArray(currentVideoDirectorPlan.window_plans)
    && currentVideoDirectorPlan.window_plans.length > 0
    && currentVideoDirectorPlan.window_plans.every((windowPlan: any) => {
      const frameCount = Number(windowPlan?.selected_frame_count || windowPlan?.selectedFrameCount || 0);
      const keyframeIndexes = Array.isArray(windowPlan?.keyframe_indexes) ? windowPlan.keyframe_indexes : Array.isArray(windowPlan?.keyframeIndexes) ? windowPlan.keyframeIndexes : [];
      return [3, 4].includes(frameCount) && keyframeIndexes.length === frameCount;
    })
  );
  const selectedPreviewClip: any | null = selectedPreviewClipKey
    ? currentPlanClips.find((clip: any) => getPlanClipKey(clip) === selectedPreviewClipKey)
    : null;
  const previewAudioClip = selectedPreviewClip || currentPlanClips.find((clip: any) => clip.drive_audio_url || clip.driveAudioUrl || clip.final_audio_url || clip.finalAudioUrl) || null;
  const previewDriveAudioUrl = previewAudioClip?.drive_audio_url || previewAudioClip?.driveAudioUrl;
  const previewFinalAudioUrl = previewAudioClip?.final_audio_url || previewAudioClip?.finalAudioUrl;
  const previewVideoUrl = selectedPreviewClip?.video_url || currentShotVideoUrl;
  const previewVideoLabel = selectedPreviewClip ? `C${selectedPreviewClip.window_index || selectedPreviewClip.clip_index}` : 'Shot';
  const previewClipMarkers = !selectedPreviewClip && currentSelectedVideoMode === 'MULTI_KEYFRAME'
    ? currentPlanClips
      .filter((clip: any) => Number(clip.window_index || clip.clip_index || 0) > 1)
      .map((clip: any) => ({
        clipIndex: clip.window_index || clip.clip_index,
        startTime: Number(clip.start_time || 0),
      }))
    : [];
  const previewTimelineDuration = Number(currentShotData?.duration || videoMetadata.duration || 0);
  const [recommendingShotId, setRecommendingShotId] = useState<string | null>(null);
  const [planningKeyframesShotId, setPlanningKeyframesShotId] = useState<string | null>(null);
  const [generatingMissingKeyframesShotId, setGeneratingMissingKeyframesShotId] = useState<string | null>(null);

  const hasShotVideo = (shot: any) => {
    const shotId = shot?.id ? String(shot.id) : '';
    return !!(shot?.videoUrl || (shotId && shotVideos[shotId]));
  };

  const getShotImageUrl = useCallback((shot: any) => {
    const shotId = shot?.id ? String(shot.id) : '';
    return shot?.imageUrl || shot?.image_url || (shotId ? shotImages[shotId] : null);
  }, [shotImages]);

  const getVideoDirectorKeyframeImageUrl = useCallback((shot: any, keyframe: any) => {
    if (!keyframe) return null;
    if (keyframe.role === 'START') return getShotImageUrl(shot);
    if (keyframe.image_url || keyframe.imageUrl) return keyframe.image_url || keyframe.imageUrl;
    const legacyKeyframe = (shot?.keyframes || []).find((item: any) => (
      Number(item.plan_keyframe_index ?? item.planKeyframeIndex) === Number(keyframe.index)
    ));
    return legacyKeyframe?.image_url || legacyKeyframe?.imageUrl || null;
  }, [getShotImageUrl]);
  const currentEndKeyframeImageUrl = currentEndPlanKeyframe
    ? getVideoDirectorKeyframeImageUrl(currentShotData, currentEndPlanKeyframe)
    : null;

  const getBatchShotEligibility = useCallback((shot: any, autoCompleteOverride = autoCompleteDetails) => {
    const shotId = shot?.id ? String(shot.id) : '';
    if (!shotId) return { selectable: false, reason: '缺少分镜 ID' };
    if (generatingVideos.has(shotId) || shot?.videoStatus === 'generating') return { selectable: false, reason: '视频生成中' };
    if (storePendingVideos.has(shotId) || (!!shot?.videoTaskId && shot?.videoStatus === 'pending')) return { selectable: false, reason: '视频等待生成中' };

    const shotImageUrl = getShotImageUrl(shot);
    if (autoCompleteOverride) {
      if (!shotImageUrl) return { selectable: false, reason: '缺少主分镜图' };
      const audioReadiness = getAudioDriveReadiness(shot);
      return audioReadiness.ready ? { selectable: true, reason: '可自动补齐' } : { selectable: false, reason: audioReadiness.reason };
    }

    const audioReadiness = getAudioDriveReadiness(shot);
    if (!audioReadiness.ready) return { selectable: false, reason: audioReadiness.reason };

    const plan: VideoDirectorPlan = shot?.videoDirectorPlan || {};
    const selectedMode = plan.selected_mode || plan.recommended_mode;
    if (!selectedMode) return { selectable: false, reason: '未确定生成模式' };

    if (!shotImageUrl) return { selectable: false, reason: '缺少主分镜图' };

    if (selectedMode === 'SINGLE_FRAME') return { selectable: true, reason: '可生成' };

    const keyframes = plan.keyframes || [];
    if (!keyframes.length) return { selectable: false, reason: '未规划关键帧' };

    if (selectedMode === 'FIRST_LAST_FRAME') {
      const endKeyframe = keyframes.find((keyframe: any) => keyframe.role === 'END');
      if (!endKeyframe) return { selectable: false, reason: '缺少尾帧规划' };
      if (!getVideoDirectorKeyframeImageUrl(shot, endKeyframe)) return { selectable: false, reason: '尾帧图片未生成' };
      return { selectable: true, reason: '可生成' };
    }

    if (selectedMode === 'MULTI_KEYFRAME') {
      const clips = plan.window_plans || [];
      if (!clips.length) return { selectable: false, reason: '未规划关键帧' };
      const invalidClip = clips.find((clip: any) => ![3, 4].includes((clip.keyframe_indexes || []).length));
      if (invalidClip) return { selectable: false, reason: '关键帧规划不完整' };
      const missingClip = clips.find((clip: any) => (clip.keyframe_indexes || []).some((keyframeIndex: number) => {
        const keyframe = keyframes.find((item: any) => Number(item.index) === Number(keyframeIndex));
        return !getVideoDirectorKeyframeImageUrl(shot, keyframe);
      }));
      if (missingClip) {
        const clip: any = missingClip;
        return { selectable: false, reason: `C${clip.window_index || clip.clip_index || ''} 缺关键帧图` };
      }
      return { selectable: true, reason: '可生成' };
    }

    return { selectable: false, reason: '生成模式不支持' };
  }, [autoCompleteDetails, generatingVideos, getShotImageUrl, getVideoDirectorKeyframeImageUrl, storePendingVideos]);

  const selectableShotIds = useCallback(() => shotsList
    .map((shot: any) => shot?.id && getBatchShotEligibility(shot).selectable ? String(shot.id) : null)
    .filter((shotId: string | null): shotId is string => shotId !== null), [getBatchShotEligibility, shotsList]);

  // 检查当前分镜是否正在生成
  const isGeneratingCurrent = currentShotId ? generatingVideos.has(currentShotId) || currentShotData?.videoStatus === 'generating' : false;
  const isCurrentVideoPending = currentShotId ? storePendingVideos.has(currentShotId) || (!!currentShotData?.videoTaskId && currentShotData?.videoStatus === 'pending') : false;
  const latestFailedAiCallError = currentVideoDirectorPlan?.ai_calls
    ? [...currentVideoDirectorPlan.ai_calls].reverse().find((call: any) => String(call?.status || '').toLowerCase() !== 'success' && String(call?.error_message || '').trim())?.error_message
    : '';
  const currentVideoErrorMessage = currentShotData?.videoStatus === 'failed' && !currentShotVideoUrl && !currentVideoDirectorPlan.merged_video_url
    ? formatUserFacingError((currentVideoDirectorPlan as any).task_error_message || (currentVideoDirectorPlan as any).error_message || latestFailedAiCallError) || '当前 Shot 视频任务失败；如果已有部分 Clip 完成，可以重新生成缺失 Clip 或重新生成当前 Shot 视频。'
    : null;
  const currentAudioDriveReadiness = getAudioDriveReadiness(currentShotData);
  const currentVideoGenerateDisabledReason = !currentAudioDriveReadiness.ready
    ? currentAudioDriveReadiness.reason
    : '';
  const currentNeedsKeyframeReplan = currentAudioDriveReadiness.ready && !currentMultiKeyframePlanReady;
  const getCurrentShotVideoResult = () => {
    const clips = currentSelectedVideoMode === 'MULTI_KEYFRAME' && Array.isArray(currentVideoDirectorPlan.window_plans)
      ? currentVideoDirectorPlan.window_plans
      : [];
    const clipCount = clips.length;
    const completedClipCount = clips.filter((clip: any) => !!(clip.video_url || clip.local_path)).length;
    const allClipsReady = clipCount > 0 && completedClipCount === clipCount;
    const parsePlanTime = (value?: string | null) => {
      if (!value) return 0;
      const time = new Date(value).getTime();
      return Number.isFinite(time) ? time : 0;
    };
    const latestClipGeneratedAt = Math.max(0, ...clips.map((clip: any) => parsePlanTime(clip.generated_at)));
    const mergedAt = parsePlanTime(currentVideoDirectorPlan.merged_at);
    const hasVideo = !!(currentShotVideoUrl || currentVideoDirectorPlan.merged_video_url);
    const needsMerge = currentSelectedVideoMode === 'MULTI_KEYFRAME'
      && allClipsReady
      && (!hasVideo || !mergedAt || latestClipGeneratedAt > mergedAt);

    if (isGeneratingCurrent || isCurrentVideoPending) {
      return {
        label: isCurrentVideoPending ? '排队中' : '生成中',
        className: 'border-blue-100 bg-blue-50 text-blue-700',
        detail: clipCount > 0 ? `Clip ${completedClipCount}/${clipCount}` : '正在生成当前 Shot 视频',
      };
    }

    if (needsMerge) {
      return {
        label: '待合并',
        className: 'border-amber-100 bg-amber-50 text-amber-700',
        detail: `Clip ${completedClipCount}/${clipCount} 已完成，需重新合并 Shot 视频`,
      };
    }

    if (hasVideo) {
      return {
        label: '已完成',
        className: 'border-green-100 bg-green-50 text-green-700',
        detail: clipCount > 0 ? `Shot 视频已生成，Clip ${completedClipCount}/${clipCount}` : 'Shot 视频已生成',
      };
    }

    if (currentShotData?.videoStatus === 'failed') {
      return {
        label: '失败',
        className: 'border-red-100 bg-red-50 text-red-700',
        detail: currentVideoErrorMessage || (clipCount > 0 ? `Clip ${completedClipCount}/${clipCount}` : '视频任务失败'),
      };
    }

    return {
      label: '未完成',
      className: 'border-gray-200 bg-gray-50 text-gray-600',
      detail: clipCount > 0 ? `Clip ${completedClipCount}/${clipCount}` : '还没有生成当前 Shot 视频',
    };
  };
  const currentShotVideoResult = getCurrentShotVideoResult();

  // 初始化获取转场工作流
  useEffect(() => {
    if (transitionWorkflows.length === 0) {
      fetchTransitionWorkflows();
    }
  }, [fetchTransitionWorkflows, transitionWorkflows.length]);

  useEffect(() => {
    saveVideoTabUiState({ showKeyframes, showAudioRef, isSidePanelCollapsed });
  }, [showKeyframes, showAudioRef, isSidePanelCollapsed]);

  const updateCurrentShotVideoDirectorPlan = useCallback((plan: VideoDirectorPlan) => {
    if (!currentShotId) return;
    setShots(shotsList.map((shot: any) => (
      String(shot.id) === currentShotId ? { ...shot, videoDirectorPlan: plan } : shot
    )));
  }, [currentShotId, setShots, shotsList]);

  const buildVideoPromptDrafts = useCallback((plan: VideoDirectorPlan): VideoPromptDraft[] => {
    const selectedMode = plan.selected_mode || plan.recommended_mode || 'SINGLE_FRAME';
    const latestPromptCall = [...(plan.ai_calls || [])].reverse().find((call: any) => String(call?.final_prompt || '').trim().length > 0);
    const latestFinalPrompt = String(latestPromptCall?.final_prompt || '');
    if (selectedMode === 'MULTI_KEYFRAME' && plan.window_plans?.length) {
      return plan.window_plans.map((clip: any, index: number) => ({
        key: `window-${clip.window_index || index + 1}`,
        label: `C${clip.window_index || index + 1} · ${clip.start_time ?? 0}-${clip.end_time ?? currentShotData?.duration ?? 0}s`,
        prompt: String(clip.prompt_text || ''),
        source: 'window_plan' as const,
        index,
      }));
    }

    if (plan.clips?.length) {
      return plan.clips.map((clip: any, index: number) => ({
        key: `clip-${clip.clip_index || index + 1}`,
        label: `C${clip.clip_index || index + 1} · ${clip.start_time ?? 0}-${clip.end_time ?? currentShotData?.duration ?? 0}s`,
        prompt: String(clip.prompt_text || (index === 0 ? latestFinalPrompt : '')),
        source: 'clip' as const,
        index,
      }));
    }

    if (latestFinalPrompt) {
      return [{
        key: 'ai-call-latest',
        label: `C1 · 未规划 Clip · ${getVideoModeLabel(selectedMode)}`,
        prompt: latestFinalPrompt,
        source: 'ai_call' as const,
      }];
    }

    return [];
  }, [currentShotData?.duration]);

  const handleOpenVideoPromptModal = useCallback(() => {
    setVideoPromptDrafts(buildVideoPromptDrafts(currentVideoDirectorPlan));
    setIsVideoPromptModalOpen(true);
  }, [buildVideoPromptDrafts, currentVideoDirectorPlan]);

  const handleChangeVideoPromptDraft = useCallback((key: string, prompt: string) => {
    setVideoPromptDrafts((drafts) => drafts.map((draft) => (
      draft.key === key ? { ...draft, prompt } : draft
    )));
  }, []);

  const handleSaveVideoPrompts = useCallback(async () => {
    if (!effectiveNovelId || !effectiveChapterId || !currentShotData?.id || videoPromptDrafts.length === 0) return;

    const nextPlan: VideoDirectorPlan = JSON.parse(JSON.stringify(currentVideoDirectorPlan || {}));
    const selectedMode = nextPlan.selected_mode || nextPlan.recommended_mode || 'SINGLE_FRAME';

    videoPromptDrafts.forEach((draft) => {
      if (draft.source === 'window_plan' && draft.index !== undefined && nextPlan.window_plans?.[draft.index]) {
        nextPlan.window_plans[draft.index] = { ...nextPlan.window_plans[draft.index], prompt_text: draft.prompt };
      } else if (draft.source === 'clip' && draft.index !== undefined && nextPlan.clips?.[draft.index]) {
        nextPlan.clips[draft.index] = { ...nextPlan.clips[draft.index], prompt_text: draft.prompt };
      } else if (draft.source === 'ai_call') {
        const duration = Number(currentShotData?.duration || 0);
        nextPlan.clips = [{
          clip_index: 1,
          start_time: 0,
          end_time: duration,
          status: 'PENDING',
          prompt_text: draft.prompt,
        }];
      }
    });

    if (selectedMode !== 'MULTI_KEYFRAME' && nextPlan.ai_calls?.length) {
      for (let index = nextPlan.ai_calls.length - 1; index >= 0; index -= 1) {
        if (nextPlan.ai_calls[index]?.final_prompt !== undefined) {
          nextPlan.ai_calls[index] = { ...nextPlan.ai_calls[index], final_prompt: videoPromptDrafts[videoPromptDrafts.length - 1].prompt };
          break;
        }
      }
    }

    setIsSavingVideoPrompts(true);
    try {
      const result = await shotsApi.batchUpdateShots(effectiveNovelId, effectiveChapterId, [{
        id: currentShotData.id,
        video_director_plan: nextPlan,
      }]);
      if (!result.success) {
        throw new Error(result.message || '保存 AI 提示词失败');
      }
      updateCurrentShotVideoDirectorPlan(nextPlan);
      setIsVideoPromptModalOpen(false);
      toast.success('AI 提示词已保存');
    } catch (error) {
      console.error('保存视频 AI 提示词失败:', error);
      toast.error(error instanceof Error ? error.message : '保存 AI 提示词失败');
    } finally {
      setIsSavingVideoPrompts(false);
    }
  }, [currentShotData, currentVideoDirectorPlan, effectiveChapterId, effectiveNovelId, updateCurrentShotVideoDirectorPlan, videoPromptDrafts]);

  const handleRecommendVideoMode = useCallback(async (force = false) => {
    if (!effectiveNovelId || !effectiveChapterId || !currentShotId) return;
    const audioReadiness = getAudioDriveReadiness(currentShotData);
    if (!audioReadiness.ready) {
      if (force) toast.error(audioReadiness.reason || 'AudioDrive 未 READY，请先到音频生成页完成音频准备。');
      return;
    }
    setRecommendingShotId(currentShotId);
    try {
      const result = await shotsApi.recommendVideoMode(effectiveNovelId, effectiveChapterId, currentShotId, force);
      if (result.success && result.data) {
        updateCurrentShotVideoDirectorPlan(result.data);
      } else {
        toast.error(result.message || '视频模式推荐失败');
      }
    } catch (error) {
      console.error('视频模式推荐失败:', error);
      toast.error('视频模式推荐失败');
    } finally {
      setRecommendingShotId(null);
    }
  }, [currentShotData, currentShotId, effectiveChapterId, effectiveNovelId, updateCurrentShotVideoDirectorPlan]);

  const handleSelectVideoMode = useCallback(async (mode: VideoMode) => {
    if (!effectiveNovelId || !effectiveChapterId || !currentShotId) return;
    const maxClipDuration = currentVideoDirectorPlan.workflow_capability?.max_clip_duration || 15;
    if (mode === 'FIRST_LAST_FRAME' && (currentShotData?.duration || 0) > maxClipDuration) {
      toast.info(`当前 Workflow 单次最大 ${maxClipDuration}s，本 Shot ${currentShotData?.duration || 0}s，请使用多关键帧`);
      return;
    }
    const optimisticPlan = { ...currentVideoDirectorPlan, selected_mode: mode };
    updateCurrentShotVideoDirectorPlan(optimisticPlan);
    try {
      const result = await shotsApi.saveVideoDirectorPlan(effectiveNovelId, effectiveChapterId, currentShotId, { selected_mode: mode });
      if (result.success && result.data) {
        updateCurrentShotVideoDirectorPlan(result.data);
      } else {
        toast.error(result.message || '保存视频模式失败');
      }
    } catch (error) {
      console.error('保存视频模式失败:', error);
      toast.error('保存视频模式失败');
    }
  }, [currentShotData?.duration, currentShotId, currentVideoDirectorPlan, effectiveChapterId, effectiveNovelId, updateCurrentShotVideoDirectorPlan]);

  const handlePlanVideoKeyframes = useCallback(async (force = true) => {
    if (!effectiveNovelId || !effectiveChapterId || !currentShotId) return false;
    setPlanningKeyframesShotId(currentShotId);
    try {
      const result = await shotsApi.planVideoKeyframes(effectiveNovelId, effectiveChapterId, currentShotId, force);
      if (result.success && result.data) {
        const refreshed = await shotsApi.getShot(effectiveNovelId, effectiveChapterId, currentShotId);
        if (refreshed.success && refreshed.data) {
          setShots(shotsList.map((shot: any) => (
            String(shot.id) === currentShotId ? { ...shot, ...refreshed.data } : shot
          )));
          if (!refreshed.data.videoUrl) {
            setShotVideos((videos: Record<string, string>) => {
              const next = { ...videos };
              delete next[currentShotId];
              return next;
            });
          }
        } else {
          updateCurrentShotVideoDirectorPlan(result.data);
        }
        toast.success('关键帧规划已生成');
        return true;
      } else {
        toast.error(result.message || (result as any).detail || '关键帧规划失败');
        return false;
      }
    } catch (error) {
      console.error('关键帧规划失败:', error);
      toast.error('关键帧规划失败');
      return false;
    } finally {
      setPlanningKeyframesShotId(null);
    }
  }, [currentShotId, effectiveChapterId, effectiveNovelId, setShotVideos, setShots, shotsList, updateCurrentShotVideoDirectorPlan]);

  const handleGenerateMissingKeyframes = useCallback(async () => {
    if (!effectiveNovelId || !effectiveChapterId || !currentShotId || !currentShotData) return;
    let sourceShot = currentShotData;
    let sourcePlan = currentVideoDirectorPlan;
    try {
      const refreshed = await shotsApi.getShot(effectiveNovelId, effectiveChapterId, currentShotId);
      if (refreshed.success && refreshed.data) {
        sourceShot = refreshed.data;
        sourcePlan = refreshed.data.videoDirectorPlan || {};
        setShots(shotsList.map((shot: any) => (
          String(shot.id) === currentShotId ? { ...shot, ...refreshed.data } : shot
        )));
      }
    } catch (error) {
      console.error('刷新关键帧状态失败:', error);
    }
    const planKeyframes = sourcePlan.keyframes || [];
    const legacyKeyframes = sourceShot.keyframes || [];
    const activeKeyframeTasks = useChapterGenerateStore.getState().keyframeTasks;
    const nonStartPlanKeyframes = planKeyframes.filter((keyframe: any) => keyframe.role !== 'START');
    const missingLegacyKeyframes = nonStartPlanKeyframes
      .map((keyframe: any, index: number) => {
        const legacyKeyframe = legacyKeyframes.find((item: any) => Number(item.plan_keyframe_index) === Number(keyframe.index));
        const imageUrl = keyframe.image_url || keyframe.imageUrl || legacyKeyframe?.image_url || legacyKeyframe?.imageUrl;
        if (imageUrl) return null;
        const frameIndex = legacyKeyframe?.frame_index ?? index;
        const activeTask = activeKeyframeTasks.find((task: any) => (
          task.shotId === currentShotId
          && Number(task.frameIndex) === Number(frameIndex)
          && ['pending', 'running'].includes(String(task.status))
        ));
        return { ...(legacyKeyframe || { plan_keyframe_index: keyframe.index }), frame_index: frameIndex, activeTask };
      })
      .filter((keyframe: any) => keyframe && keyframe.frame_index !== undefined);

    const activeMissingTasks = missingLegacyKeyframes.filter((keyframe: any) => keyframe.activeTask);
    if (activeMissingTasks.length > 0) {
      toast.info(`已有 ${activeMissingTasks.length} 个关键帧生成任务在等待或运行，请等待完成`);
      return;
    }

    if (missingLegacyKeyframes.length === 0) {
      toast.info('没有缺失的关键帧图片');
      return;
    }

    setGeneratingMissingKeyframesShotId(currentShotId);
    try {
      for (const keyframe of missingLegacyKeyframes) {
        await generateKeyframeImage(effectiveNovelId, effectiveChapterId, currentShotId, Number(keyframe.frame_index));
      }
      toast.success(`已提交 ${missingLegacyKeyframes.length} 个关键帧图片任务`);
    } catch (error) {
      console.error('生成缺失关键帧失败:', error);
      toast.error('生成缺失关键帧失败');
    } finally {
      setGeneratingMissingKeyframesShotId(null);
    }
  }, [currentShotData, currentShotId, currentVideoDirectorPlan, effectiveChapterId, effectiveNovelId, generateKeyframeImage, setShots, shotsList]);

  const handleGenerateEndKeyframe = useCallback(async (mode: 'llm' | 'image_only' = 'llm') => {
    if (!effectiveNovelId || !effectiveChapterId || !currentShotId || !currentShotData) return;
    const endPlanKeyframe = (currentVideoDirectorPlan.keyframes || []).find((keyframe: any) => keyframe.role === 'END');
    const legacyKeyframes = currentShotData.keyframes || [];
    const legacyEndKeyframe = legacyKeyframes.find((keyframe: any) => (
      Number(keyframe.plan_keyframe_index) === Number(endPlanKeyframe?.index || 2)
    )) || (endPlanKeyframe ? { frame_index: 0 } : legacyKeyframes[0]);

    if (!legacyEndKeyframe || legacyEndKeyframe.frame_index === undefined) {
      toast.error('缺少 END 关键帧记录，请重新选择首尾帧模式或重新推荐');
      return;
    }

    if (mode === 'image_only' && !String(endPlanKeyframe?.prompt_text || legacyEndKeyframe?.prompt_text || '').trim()) {
      toast.error('当前 END 关键帧没有可复用的 AI 生图提示词，请先使用 LLM+重新生成。');
      return;
    }

    try {
      await generateKeyframeImage(
        effectiveNovelId,
        effectiveChapterId,
        currentShotId,
        Number(legacyEndKeyframe.frame_index),
        undefined,
        { skipLlmWhenPromptExists: mode === 'image_only' }
      );
      toast.success('已提交 END 关键帧生图任务');
    } catch (error) {
      console.error('生成 END 关键帧失败:', error);
      toast.error('生成 END 关键帧失败');
    }
  }, [currentShotData, currentShotId, currentVideoDirectorPlan.keyframes, effectiveChapterId, effectiveNovelId, generateKeyframeImage]);

  useEffect(() => {
    if (!effectiveNovelId || !effectiveChapterId || !currentShotId) return;
    if (currentVideoDirectorPlan.recommended_mode || recommendingShotId === currentShotId) return;
    if (!currentAudioDriveReadiness.ready) return;
    handleRecommendVideoMode(false);
  }, [currentAudioDriveReadiness.ready, currentShotId, currentVideoDirectorPlan.recommended_mode, effectiveChapterId, effectiveNovelId, handleRecommendVideoMode, recommendingShotId]);

  useEffect(() => {
    setVideoMetadata({ duration: null, width: null, height: null, sizeBytes: null });
    if (!previewVideoUrl) return;

    let cancelled = false;
    fetch(previewVideoUrl, { method: 'HEAD' })
      .then(async (response) => {
        if (cancelled) return;
        const contentLength = response.headers.get('content-length');
        let fallbackSize: number | null = null;
        if (!contentLength && response.headers.get('content-type')?.includes('application/json')) {
          try {
            const payload = await response.json();
            fallbackSize = Number(payload?.size) || null;
          } catch {
            fallbackSize = null;
          }
        }
        setVideoMetadata((metadata) => ({
          ...metadata,
          sizeBytes: contentLength ? Number(contentLength) : fallbackSize,
        }));
      })
      .catch(() => {
        // Some file servers may not expose Content-Length for HEAD requests.
      });

    return () => {
      cancelled = true;
    };
  }, [previewVideoUrl]);

  useEffect(() => {
    if (!isGeneratingCurrent || !effectiveNovelId || !effectiveChapterId || !currentShotId) return;
    let stopped = false;
    let timer: number | undefined;

    const refreshCurrentShot = async () => {
      try {
        const result = await shotsApi.getShot(effectiveNovelId, effectiveChapterId, currentShotId);
        if (!stopped && result.success && result.data) {
          setShots(shotsList.map((shot: any) => (
            String(shot.id) === currentShotId ? { ...shot, ...result.data } : shot
          )));
          if (result.data.videoUrl) {
            setShotVideos((videos: Record<string, string>) => ({ ...videos, [currentShotId]: result.data.videoUrl! }));
          }
          if (result.data.videoStatus !== 'generating') {
            setRegeneratingClipKey(null);
          }
        }
      } catch (error) {
        console.error('刷新当前视频状态失败:', error);
      }
      if (!stopped) {
        timer = window.setTimeout(refreshCurrentShot, 2000);
      }
    };

    timer = window.setTimeout(refreshCurrentShot, 2000);
    return () => {
      stopped = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [currentShotId, effectiveChapterId, effectiveNovelId, isGeneratingCurrent, setShotVideos, setShots, shotsList]);

  const handleToggleKeyframes = () => {
    const nextShowKeyframes = !showKeyframes;
    setShowKeyframes(nextShowKeyframes);
    saveVideoTabUiState({ showKeyframes: nextShowKeyframes, showAudioRef, isSidePanelCollapsed });
  };

  const handleToggleAudioRef = () => {
    const nextShowAudioRef = !showAudioRef;
    setShowAudioRef(nextShowAudioRef);
    saveVideoTabUiState({ showKeyframes, showAudioRef: nextShowAudioRef, isSidePanelCollapsed });
  };

  const handleToggleSidePanel = () => {
    const nextCollapsed = !isSidePanelCollapsed;
    setIsSidePanelCollapsed(nextCollapsed);
    saveVideoTabUiState({ showKeyframes, showAudioRef, isSidePanelCollapsed: nextCollapsed });
  };

  // 同步 currentShot 和 selectedVideo
  useEffect(() => {
    if (currentShot && currentShot !== selectedVideo) {
      setSelectedVideo(currentShot);
    }
  }, [currentShot, selectedVideo]);

  // 当用户点击视频列表时，切换分镜
  const handleVideoClick = (shotNum: number) => {
    setSelectedVideo(shotNum);
    const shot = shotsList[shotNum - 1];
    if (shot) {
      const shotId = shot.id || String(shotNum);
      setCurrentShot(shotId, shotNum);
    }
  };

  useEffect(() => {
    setSelectedPreviewClipKey(null);
    setRegeneratingClipKey(null);
  }, [currentShotId]);

  const hasVideo = !!currentShotVideoUrl;
  const hasPreviewVideo = !!previewVideoUrl;

  // 处理单个视频生成
  useEffect(() => {
    if (!showGenerateVideoMenu) return;
    const handleClick = () => setShowGenerateVideoMenu(false);
    window.addEventListener('click', handleClick);
    return () => window.removeEventListener('click', handleClick);
  }, [showGenerateVideoMenu]);

  const handleGenerateVideo = async (mode: 'llm' | 'video_only' = 'llm') => {
    if (!effectiveNovelId || !effectiveChapterId || !currentShotId) return;
    if (mode === 'video_only' && !hasReusableVideoPrompt) return;
    if (!currentAudioDriveReadiness.ready) {
      toast.error(currentAudioDriveReadiness.reason || 'AudioDrive 未 READY，请先到音频生成页完成音频准备。');
      return;
    }
    if (currentSelectedVideoMode === 'FIRST_LAST_FRAME' && !currentEndKeyframeImageUrl) {
      toast.error('首尾帧模式需要先生成 END 关键帧图片。');
      return;
    }
    if (hasVideo && !window.confirm(t('chapterGenerate.videoExistsConfirmDelete'))) return;
    setShowGenerateVideoMenu(false);

    try {
      if (!currentMultiKeyframePlanReady) {
        toast.info('AudioDrive 窗口已变化，先自动重新规划关键帧。');
        const planned = await handlePlanVideoKeyframes(true);
        if (!planned) return;
      }
      await generateShotVideo(effectiveNovelId, effectiveChapterId, currentShotId, currentSelectedVideoMode, {
        skipLlmWhenPromptExists: mode === 'video_only',
      });
      markTabComplete(3);
    } catch (error) {
      console.error(t('chapterGenerate.videoGenerateFailed') + ':', error);
      toast.error(error instanceof Error ? error.message : t('chapterGenerate.videoGenerateFailed'));
    }
  };

  const refreshCurrentShotData = useCallback(async () => {
    if (!effectiveNovelId || !effectiveChapterId || !currentShotId) return null;
    const result = await shotsApi.getShot(effectiveNovelId, effectiveChapterId, currentShotId);
    if (result.success && result.data) {
      setShots(shotsList.map((shot: any) => (
        String(shot.id) === currentShotId ? { ...shot, ...result.data } : shot
      )));
      if (result.data.videoUrl) {
        setShotVideos((prev) => ({ ...prev, [currentShotId]: result.data.videoUrl || '' }));
      }
      return result.data;
    }
    return null;
  }, [currentShotId, effectiveChapterId, effectiveNovelId, setShotVideos, setShots, shotsList]);

  useEffect(() => {
    if (!effectiveChapterId || !currentShotId || (!isGeneratingCurrent && !isCurrentVideoPending)) return;
    let cancelled = false;
    let timeoutId: ReturnType<typeof window.setTimeout> | null = null;

    const refreshActiveShot = async () => {
      if (cancelled) return;
      await checkVideoTaskStatus(effectiveChapterId);
      await refreshCurrentShotData();
      if (!cancelled) {
        timeoutId = window.setTimeout(refreshActiveShot, 2000);
      }
    };

    timeoutId = window.setTimeout(refreshActiveShot, 1000);
    return () => {
      cancelled = true;
      if (timeoutId) window.clearTimeout(timeoutId);
    };
  }, [checkVideoTaskStatus, currentShotId, effectiveChapterId, isCurrentVideoPending, isGeneratingCurrent, refreshCurrentShotData]);

  const handleRefreshAiCalls = useCallback(async () => {
    if (!effectiveNovelId || !effectiveChapterId || !currentShotId) return;
    setIsRefreshingAiCalls(true);
    try {
      const refreshed = await refreshCurrentShotData();
      if (refreshed) {
        toast.success(t('chapterGenerate.aiCallResultsRefreshed'));
      }
    } catch (error) {
      console.error('刷新 AI 调用结果失败:', error);
      toast.error(t('chapterGenerate.refreshAiCallResultsFailed'));
    } finally {
      setIsRefreshingAiCalls(false);
    }
  }, [currentShotId, effectiveChapterId, effectiveNovelId, refreshCurrentShotData, t]);

  const handleCancelCurrentVideo = useCallback(async () => {
    if (!currentShotId || !currentShotData?.videoTaskId) {
      toast.error(t('chapterGenerate.missingVideoTaskId'));
      return;
    }
    if (!window.confirm(t('chapterGenerate.cancelCurrentVideoConfirm'))) return;

    setIsCancellingVideo(true);
    try {
      const result = await taskApi.cancel(currentShotData.videoTaskId);
      if (!result.success) {
        throw new Error(result.message || (result as any).detail || t('chapterGenerate.cancelFailed'));
      }
      const nextGeneratingVideos = new Set(useChapterGenerateStore.getState().generatingVideos);
      nextGeneratingVideos.delete(currentShotId);
      useChapterGenerateStore.setState((state) => ({
        generatingVideos: nextGeneratingVideos,
        shots: state.shots.map((shot: any) => (
          String(shot.id) === currentShotId ? { ...shot, videoStatus: 'failed', videoTaskId: null } : shot
        )),
      }));
      setShots(shotsList.map((shot: any) => (
        String(shot.id) === currentShotId ? { ...shot, videoStatus: 'failed', videoTaskId: null } : shot
      )));
      await refreshCurrentShotData();
      toast.success(t('chapterGenerate.videoCancelled'));
    } catch (error) {
      console.error(t('chapterGenerate.cancelVideoFailed') + ':', error);
      toast.error(error instanceof Error ? error.message : t('chapterGenerate.cancelVideoFailed'));
    } finally {
      setIsCancellingVideo(false);
    }
  }, [currentShotData?.videoTaskId, currentShotId, refreshCurrentShotData, setShots, shotsList, t]);

  const handlePreviewClip = useCallback((clip: any) => {
    setSelectedPreviewClipKey(getPlanClipKey(clip));
  }, []);

  const handleRegenerateClip = useCallback(async (clip: any, mode: 'llm' | 'video_only' = 'llm') => {
    if (!effectiveNovelId || !effectiveChapterId || !currentShotId) return;
    const windowIndex = Number(clip.window_index || clip.clip_index);
    if (!windowIndex) return;
    const audioReadiness = getAudioDriveReadiness(currentShotData);
    if (!audioReadiness.ready) {
      toast.error(audioReadiness.reason || 'AudioDrive 未 READY，请先到音频生成页完成音频准备。');
      return;
    }
    const useExistingPrompt = mode === 'video_only';
    if (useExistingPrompt && !String(clip.prompt_text || '').trim()) {
      toast.info(`C${windowIndex} 缺少可复用的视频最终 Prompt，请先使用 LLM+生成Clip视频。`);
      return;
    }
    if (clip.video_url && !window.confirm(`确认重新生成 C${windowIndex}？完成后会自动重新合并整体视频。`)) return;

    const clipKey = getPlanClipKey(clip);
    setRegeneratingClipKey(clipKey);
    setSelectedPreviewClipKey(clipKey);
    try {
      const result = await shotsApi.generateVideoDirectorClip(effectiveNovelId, effectiveChapterId, currentShotId, windowIndex, {
        use_reference_audio: true,
        auto_merge: true,
        skip_llm_when_prompt_exists: useExistingPrompt,
      });
      if (result.success) {
        setShots(shotsList.map((shot: any) => (
          String(shot.id) === currentShotId ? { ...shot, videoStatus: 'generating', videoTaskId: result.data?.taskId || shot.videoTaskId } : shot
        )));
        toast.success(`C${windowIndex} 已提交${useExistingPrompt ? '仅生成视频' : 'LLM+生成视频'}，完成后会自动合并`);
      } else {
        setRegeneratingClipKey(null);
        toast.error(result.message || result.detail || 'Clip 重新生成失败');
      }
    } catch (error) {
      setRegeneratingClipKey(null);
      console.error('Clip 重新生成失败:', error);
      toast.error('Clip 重新生成失败');
    }
  }, [currentShotId, effectiveChapterId, effectiveNovelId, setShots, shotsList]);

  const handleMergeDirectorClips = useCallback(async () => {
    if (!effectiveNovelId || !effectiveChapterId || !currentShotId) return;
    setIsMergingClips(true);
    try {
      const result = await shotsApi.mergeVideoDirectorClips(effectiveNovelId, effectiveChapterId, currentShotId);
      if (result.success && result.data) {
        setSelectedPreviewClipKey(null);
        setShots(shotsList.map((shot: any) => (
          String(shot.id) === currentShotId
            ? { ...shot, videoUrl: result.data?.videoUrl || shot.videoUrl, videoDirectorPlan: result.data?.videoDirectorPlan || shot.videoDirectorPlan, videoStatus: 'completed' }
            : shot
        )));
        if (result.data.videoUrl) {
          setShotVideos((prev) => ({ ...prev, [currentShotId]: result.data?.videoUrl || '' }));
        }
        toast.success(result.data.skipped ? '没有 Clip 被重新生成，已跳过合并' : '整体视频已重新合并');
      } else {
        toast.error(result.message || result.detail || '重新合并失败');
      }
    } catch (error) {
      console.error('重新合并失败:', error);
      toast.error('重新合并失败');
    } finally {
      setIsMergingClips(false);
      refreshCurrentShotData().catch(() => undefined);
    }
  }, [currentShotId, effectiveChapterId, effectiveNovelId, refreshCurrentShotData, setShotVideos, setShots, shotsList]);

  const openVideoImageEdit = useCallback((target: VideoImageEditTarget) => {
    if (!target.imageUrl) return;
    if (target.type === 'keyframe' && target.frameIndex === undefined) {
      toast.error('缺少关键帧序号，无法编辑');
      return;
    }
    setImageEditTarget(target);
    setImageEditResultUrl(null);
    setImageEditResultSize(null);
  }, []);

  const closeVideoImageEdit = useCallback(() => {
    if (isEditingImage || isReplacingImage) return;
    setImageEditTarget(null);
    setImageEditResultUrl(null);
    setImageEditResultSize(null);
  }, [isEditingImage, isReplacingImage]);

  const handleEditVideoImage = useCallback(async (prompt: string) => {
    if (!effectiveNovelId || !effectiveChapterId || !currentShotId || !imageEditTarget) return;
    if (!prompt.trim()) {
      toast.warning('请输入图片编辑提示词');
      return;
    }
    setIsEditingImage(true);
    setImageEditResultUrl(null);
    setImageEditResultSize(null);
    try {
      const result = imageEditTarget.type === 'shot'
        ? await shotsApi.editImage(effectiveNovelId, effectiveChapterId, currentShotId, prompt)
        : await shotsApi.editKeyframeImage(effectiveNovelId, effectiveChapterId, currentShotId, Number(imageEditTarget.frameIndex), prompt);
      if (result.success && result.data?.imageUrl) {
        setImageEditResultUrl(result.data.imageUrl);
        toast.success('图片编辑完成');
      } else {
        toast.error(result.detail || result.message || '编辑图片失败');
      }
    } catch (error) {
      console.error('编辑图片失败:', error);
      toast.error('编辑图片失败');
    } finally {
      setIsEditingImage(false);
    }
  }, [currentShotId, effectiveChapterId, effectiveNovelId, imageEditTarget]);

  const handleReplaceVideoImage = useCallback(async () => {
    if (!effectiveNovelId || !effectiveChapterId || !currentShotId || !imageEditTarget || !imageEditResultUrl) return;
    setIsReplacingImage(true);
    try {
      const result = imageEditTarget.type === 'shot'
        ? await shotsApi.replaceImage(effectiveNovelId, effectiveChapterId, currentShotId, imageEditResultUrl)
        : await shotsApi.replaceKeyframeImage(effectiveNovelId, effectiveChapterId, currentShotId, Number(imageEditTarget.frameIndex), imageEditResultUrl);
      if (result.success && result.data) {
        setShots(shotsList.map((shot: any) => (String(shot.id) === currentShotId ? { ...shot, ...result.data } : shot)));
        if (imageEditTarget.type === 'shot') {
          setShotImages((images: Record<string, string>) => ({ ...images, [currentShotId]: result.data?.imageUrl || imageEditResultUrl }));
        }
        toast.success(imageEditTarget.type === 'shot' ? '已替换分镜图片' : '已替换关键帧图片');
        setImageEditTarget(null);
        setImageEditResultUrl(null);
        setImageEditResultSize(null);
      } else {
        toast.error(result.detail || result.message || '替换图片失败');
      }
    } catch (error) {
      console.error('替换图片失败:', error);
      toast.error('替换图片失败');
    } finally {
      setIsReplacingImage(false);
    }
  }, [currentShotId, effectiveChapterId, effectiveNovelId, imageEditResultUrl, imageEditTarget, setShotImages, setShots, shotsList]);

  // 打开批量选择弹窗
  const handleOpenBatchSelect = () => {
    setSelectedShotIds(new Set());
    setBatchSelectionMode(null);
    setShowBatchSelectModal(true);
  };

  const applyBatchShotSelection = (shotId: string, mode: 'select' | 'deselect') => {
    const shot = shotsList.find((item: any) => String(item?.id) === shotId);
    if (!getBatchShotEligibility(shot).selectable) return;
    setSelectedShotIds(prev => {
      const next = new Set(prev);
      if (mode === 'select') {
        next.add(shotId);
      } else {
        next.delete(shotId);
      }
      return next;
    });
    setBatchSelectionMode(null);
  };

  const handleBatchShotMouseDown = (event: React.MouseEvent, shotId: string, isSelectable: boolean) => {
    if (event.button !== 0 || !isSelectable) return;
    event.preventDefault();
    const mode = selectedShotIds.has(shotId) ? 'deselect' : 'select';
    setDragSelectionMode(mode);
    applyBatchShotSelection(shotId, mode);
  };

  const handleBatchShotMouseEnter = (shotId: string, isSelectable: boolean) => {
    if (!dragSelectionMode || !isSelectable) return;
    applyBatchShotSelection(shotId, dragSelectionMode);
  };

  // 全选/取消全选
  const toggleSelectAll = () => {
    if (batchSelectionMode === 'all') {
      setSelectedShotIds(new Set());
      setBatchSelectionMode(null);
    } else {
      setSelectedShotIds(new Set(selectableShotIds()));
      setBatchSelectionMode('all');
    }
  };

  const toggleSelectPendingVideos = () => {
    if (batchSelectionMode === 'pending') {
      setSelectedShotIds(new Set());
      setBatchSelectionMode(null);
      return;
    }

    const pendingShots = shotsList
      .map((shot: any) => {
        const eligibility = getBatchShotEligibility(shot);
        return shot?.id && !hasShotVideo(shot) && eligibility.selectable ? String(shot.id) : null;
      })
      .filter((shotId: string | null): shotId is string => shotId !== null);

    setSelectedShotIds(new Set(pendingShots));
    setBatchSelectionMode('pending');
  };

  useEffect(() => {
    if (!dragSelectionMode) return;
    const handleMouseUp = () => setDragSelectionMode(null);
    window.addEventListener('mouseup', handleMouseUp);
    return () => window.removeEventListener('mouseup', handleMouseUp);
  }, [dragSelectionMode]);

  const handleVideoMetadataLoaded = (event: React.SyntheticEvent<HTMLVideoElement>) => {
    const video = event.currentTarget;
    setVideoMetadata((metadata) => ({
      ...metadata,
      duration: Number.isFinite(video.duration) ? video.duration : null,
      width: video.videoWidth || null,
      height: video.videoHeight || null,
    }));
  };

  // 处理批量视频生成
  const handleGenerateAll = async () => {
    if (!effectiveNovelId || !effectiveChapterId) return;
    const selectedShotList = shotsList
      .filter((shot: any) => shot?.id && selectedShotIds.has(String(shot.id)))
      .filter((shot) => shot && getBatchShotEligibility(shot).selectable);
    if (!selectedShotList.length) {
      toast.info('没有可生成的视频分镜');
      return;
    }
    if (selectedShotList.some(hasShotVideo) && !window.confirm('视频已存在，确认重新生成并在成功后替换旧视频吗？')) return;

    setIsGeneratingAll(true);
    setShowBatchSelectModal(false);
    let successCount = 0;
    let failedCount = 0;
    const batchShotIds = selectedShotList.map((shot: any) => String(shot.id)).filter(Boolean);
    const previousVideoStatuses = new Map(
      selectedShotList.map((shot: any) => [String(shot.id), shot.videoStatus])
    );
    useChapterGenerateStore.setState((state) => ({
      pendingVideos: new Set([...state.pendingVideos, ...batchShotIds]),
      shots: state.shots.map((shot: any) => (
        batchShotIds.includes(String(shot.id))
          ? { ...shot, videoStatus: 'pending' as const }
          : shot
      )),
    }));
    try {
      const selectedModes: Record<string, VideoMode> = {};
      selectedShotList.forEach((shot: any) => {
        const plan = shot.videoDirectorPlan || {};
        const mode = plan.selected_mode || plan.recommended_mode;
        if (mode) selectedModes[String(shot.id)] = mode as VideoMode;
      });
      const result = await shotsApi.generateVideosBatch(effectiveNovelId, effectiveChapterId, {
        shot_ids: batchShotIds,
        selected_modes: selectedModes,
        auto_complete: autoCompleteDetails,
      });
      if (!result.success) {
        throw new Error(result.message || result.detail || '批量视频任务提交失败');
      }
      const batchTaskId = result.data?.taskId;
      if (batchTaskId) {
        useChapterGenerateStore.setState((state) => ({
          shots: state.shots.map((shot: any) => (
            batchShotIds.includes(String(shot.id))
              ? { ...shot, videoTaskId: batchTaskId }
              : shot
          )),
        }));
      }
      successCount = batchShotIds.length;
      checkVideoTaskStatus(effectiveChapterId);

      if (successCount > 0) {
        toast.success(`已提交批量视频任务：${successCount} 个分镜`);
      } else if (failedCount > 0) {
        toast.error('批量生成视频未提交成功任务');
      }
    } catch (error) {
      console.error(t('chapterGenerate.batchVideoGenerateFailed') + ':', error);
      const message = error instanceof Error ? error.message : '批量视频任务提交失败';
      toast.error(message);
      useChapterGenerateStore.setState((state) => ({
        generatingVideos: new Set([...state.generatingVideos].filter((shotId) => !batchShotIds.includes(String(shotId)))),
        pendingVideos: new Set([...state.pendingVideos].filter((shotId) => !batchShotIds.includes(String(shotId)))),
        shots: state.shots.map((shot: any) => (
          batchShotIds.includes(String(shot.id))
            ? { ...shot, videoStatus: previousVideoStatuses.get(String(shot.id)) || shot.videoStatus, videoTaskId: null }
            : shot
        )),
      }));
    } finally {
      setIsGeneratingAll(false);
    }
  };

  // 处理关键帧更新
  const handleKeyframesUpdate = useCallback((updatedKeyframes: KeyframeData[]) => {
    const shotIndex = selectedVideo - 1;
    const shot = shotsList[shotIndex];
    if (!shot) return;

    console.log('[VideoGenTab] Updating keyframes:', updatedKeyframes);
    // 更新 store.shots
    const updatedShots = shotsList.map((s: any, idx: number) =>
      idx === shotIndex ? { ...s, keyframes: updatedKeyframes } : s
    );
    setShots(updatedShots);
  }, [shotsList, selectedVideo, setShots]);

  // 处理参考音频更新
  const handleReferenceAudioUpdate = (audioUrl: string | null) => {
    const shotIndex = selectedVideo - 1;
    const shot = shotsList[shotIndex];
    if (!shot) return;

    // 更新 store.shots
    const updatedShots = shotsList.map((s: any, idx: number) =>
      idx === shotIndex ? { ...s, referenceAudioUrl: audioUrl || null } : s
    );
    setShots(updatedShots);
  };

  // 处理转场生成
  const handleGenerateTransition = async (from: number, to: number) => {
    if (!effectiveNovelId || !effectiveChapterId) return;
    try {
      // 使用选中的工作流（如果有）
      const useCustomConfig = !!selectedTransitionWorkflow && selectedTransitionWorkflow !== '';
      await generateTransition(effectiveNovelId, effectiveChapterId, from, to, useCustomConfig);
    } catch (error) {
      console.error(t('chapterGenerate.transitionGenerateFailed') + ':', error);
    }
  };

  // 保存当前分镜信息
  const handleSaveShot = async () => {
    if (!effectiveNovelId || !effectiveChapterId) return;

    setIsSaving(true);
    try {
      if (!currentShotData) {
        console.error(t('chapterGenerate.shotDataNotExist'));
        return;
      }

      // 调用批量更新接口
      const result = await shotsApi.batchUpdateShots(effectiveNovelId, effectiveChapterId, [{
        id: currentShotData.id,
        video_description: currentShotData.video_description,
        duration: currentShotData.duration,
        video_director_plan: currentShotData.videoDirectorPlan,
      }]);

      if (result.success) {
        console.log(t('chapterGenerate.shotSaveSuccess'));
      } else {
        console.error(t('chapterGenerate.shotSaveFailed') + ':', result.message);
      }
    } catch (error) {
      console.error(t('chapterGenerate.shotSaveFailed') + ':', error);
    } finally {
      setIsSaving(false);
    }
  };

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== 's') return;
      event.preventDefault();
      event.stopPropagation();
      if (!isSaving) {
        handleSaveShot();
      }
    };

    window.addEventListener('keydown', handleKeyDown, true);
    return () => window.removeEventListener('keydown', handleKeyDown, true);
  }, [effectiveNovelId, effectiveChapterId, currentShotData, isSaving]);

  const handleRefreshCurrentVideo = async () => {
    if (!effectiveNovelId || !effectiveChapterId || !currentShotId) return;

    setIsRefreshingVideo(true);
    try {
      await checkVideoTaskStatus(effectiveChapterId);

      const result = await shotsApi.getShot(effectiveNovelId, effectiveChapterId, currentShotId);
      if (result.success && result.data) {
        setShots(shotsList.map((shot: any) => (
          shot.id === currentShotId ? { ...shot, ...result.data } : shot
        )));

        if (result.data.videoUrl) {
          setShotVideos((prev) => ({ ...prev, [currentShotId]: result.data.videoUrl || '' }));
          toast.success('视频预览已刷新');
        } else {
          toast.info('当前分镜还没有视频');
        }
      }
    } catch (error) {
      console.error('刷新视频预览失败:', error);
      toast.error('刷新视频预览失败');
    } finally {
      setIsRefreshingVideo(false);
    }
  };

  const handlePictureInPicture = async () => {
    const video = previewVideoRef.current;
    if (!video || !previewVideoUrl) return;
    if (!document.pictureInPictureEnabled || typeof video.requestPictureInPicture !== 'function') {
      toast.error('当前浏览器不支持画中画播放');
      return;
    }
    try {
      if (document.pictureInPictureElement === video) {
        await document.exitPictureInPicture();
        return;
      }
      await video.requestPictureInPicture();
    } catch (error) {
      console.error('开启画中画失败:', error);
      toast.error('开启画中画失败');
    }
  };

  // 处理下载章节素材
  const handleDownloadMaterials = async () => {
    if (!effectiveNovelId || !effectiveChapterId) return;

    setIsDownloading(true);
    try {
      await downloadChapterMaterials(effectiveNovelId, effectiveChapterId);
    } catch (error) {
      console.error(t('chapterGenerate.downloadFailed') + ':', error);
    } finally {
      setIsDownloading(false);
    }
  };

  const getMergeShotVideoUrl = (shot: any) => {
    const shotId = shot?.id ? String(shot.id) : '';
    return shot?.videoUrl || (shotId ? shotVideos[shotId] : undefined) || shot?.videoDirectorPlan?.merged_video_url;
  };

  const mergeReadyShotIds = () => shotsList
    .filter((shot: any) => !!shot?.id && !!getMergeShotVideoUrl(shot))
    .map((shot: any) => String(shot.id));

  const handleOpenMergeSelect = () => {
    setSelectedMergeShotIds(new Set(mergeReadyShotIds()));
    setMergeIncludeTransitions(false);
    setShowMergeSelectModal(true);
  };

  const toggleMergeSelectAll = () => {
    const readyIds = mergeReadyShotIds();
    setSelectedMergeShotIds(selectedMergeShotIds.size === readyIds.length ? new Set() : new Set(readyIds));
  };

  const applyMergeShotSelection = (shotId: string, mode: 'select' | 'deselect') => {
    const shot = shotsList.find((item: any) => String(item.id) === shotId);
    if (!shot || !getMergeShotVideoUrl(shot)) return;
    setSelectedMergeShotIds(prev => {
      const next = new Set(prev);
      if (mode === 'select') next.add(shotId);
      else next.delete(shotId);
      return next;
    });
  };

  const handleMergeShotMouseDown = (event: React.MouseEvent, shotId: string, selectable: boolean) => {
    if (event.button !== 0 || !selectable) return;
    event.preventDefault();
    const mode = selectedMergeShotIds.has(shotId) ? 'deselect' : 'select';
    setMergeSelectionMode(mode);
    applyMergeShotSelection(shotId, mode);
  };

  const handleMergeShotMouseEnter = (shotId: string, selectable: boolean) => {
    if (!mergeSelectionMode || !selectable) return;
    applyMergeShotSelection(shotId, mergeSelectionMode);
  };

  useEffect(() => {
    if (!mergeSelectionMode) return;
    const handleMouseUp = () => setMergeSelectionMode(null);
    window.addEventListener('mouseup', handleMouseUp);
    return () => window.removeEventListener('mouseup', handleMouseUp);
  }, [mergeSelectionMode]);

  // 处理合并视频
  const handleMergeVideos = async (mode: MergeVideoMode, shotIds = Array.from(selectedMergeShotIds)) => {
    if (!effectiveNovelId || !effectiveChapterId) return;
    if (shotIds.length === 0) {
      toast.error(t('chapterGenerate.noVideosToMerge'));
      return;
    }

    setMergingMode(mode);
    try {
      const response = await fetch(
        `/api/novels/${effectiveNovelId}/chapters/${effectiveChapterId}/merge-videos`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mode, shot_ids: shotIds })
        }
      );

      const data = await response.json();

      if (response.ok && data.success) {
        setShowMergeSelectModal(false);
        toast.info(`已提交 ${shotIds.length} 个视频的章节合并任务，可在任务列表查看进度。`);
      } else {
        toast.error(data.message || t('chapterGenerate.mergeFailed'));
      }
    } catch (error) {
      console.error('Merge error:', error);
      toast.error(t('chapterGenerate.mergeFailed'));
    } finally {
      setMergingMode(null);
    }
  };

  // 计算已生成视频的数量
  const videoCount = shotsList.filter((shot: any) => shot.videoUrl || shotVideos[shot.id]).length;

  return (
    <div className="h-full flex flex-col">
      {currentVideoErrorMessage && (
        <div className="mx-8 mb-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          <div className="font-medium">视频生成失败</div>
          <div className="mt-1 whitespace-pre-wrap break-words">{currentVideoErrorMessage}</div>
        </div>
      )}
      <div className={`mx-8 mb-2 rounded-lg border px-3 py-2 text-sm ${currentAudioDriveReadiness.ready ? 'border-green-200 bg-green-50 text-green-700' : 'border-amber-200 bg-amber-50 text-amber-700'}`}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 font-medium">
            <Volume2 className="h-4 w-4" />
            AudioDrive {currentAudioDriveReadiness.ready ? 'READY' : '未就绪'}
          </div>
          <div className="text-xs">
            Timeline: {currentAudioDriveReadiness.timelineReady ? 'READY' : 'NOT_READY'} · Clip Audio: {currentAudioDriveReadiness.readyClipCount}/{currentAudioDriveReadiness.clipCount || 0}
          </div>
        </div>
        {!currentAudioDriveReadiness.ready && (
          <div className="mt-1 text-xs">{currentAudioDriveReadiness.reason}</div>
        )}
        {currentNeedsKeyframeReplan && (
          <div className="mt-1 text-xs text-amber-700">AudioDrive 重新构建了 execution_windows，点击生成视频会先自动重新规划关键帧。</div>
        )}
      </div>
      {/* 操作栏 */}
      <div className="flex-shrink-0 flex items-center justify-between mb-2 pb-2 border-b border-gray-200">
        <div className="ml-8 flex items-center gap-4">
          {isGeneratingCurrent ? (
            <button
              onClick={handleCancelCurrentVideo}
              disabled={isCancellingVideo || !effectiveChapterId}
              className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
            >
              <Loader2 className="w-4 h-4 animate-spin" />
              {isCancellingVideo ? t('chapterGenerate.cancellingVideo') : t('chapterGenerate.cancelVideoGeneration')}
            </button>
          ) : (
            <div className="relative inline-flex">
              <button
                onClick={() => handleGenerateVideo('llm')}
                disabled={!effectiveChapterId || !currentShotId || Boolean(currentVideoGenerateDisabledReason)}
                title={currentVideoGenerateDisabledReason || undefined}
                className="px-4 py-2 bg-blue-600 text-white rounded-l-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
              >
                <Film className="w-4 h-4" />
                LLM+生成当前Shot视频
              </button>
              <button
                type="button"
                onClick={(event) => {
                  event.stopPropagation();
                  setShowGenerateVideoMenu(prev => !prev);
                }}
                disabled={!effectiveChapterId || !currentShotId || Boolean(currentVideoGenerateDisabledReason)}
                title={currentVideoGenerateDisabledReason || undefined}
                className="px-2 py-2 bg-blue-600 text-white border-l border-blue-500 rounded-r-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center"
                aria-label="选择视频生成方式"
              >
                <ChevronDown className="w-4 h-4" />
              </button>
              {showGenerateVideoMenu && (
                <div className="absolute left-0 top-full z-[80] mt-1 w-56 rounded-lg border border-gray-200 bg-white py-1 shadow-lg">
                  <button
                    type="button"
                    onClick={() => handleGenerateVideo('llm')}
                    className="w-full px-3 py-2 text-left text-sm text-gray-700 hover:bg-blue-50"
                  >
                    LLM+生成当前Shot视频
                  </button>
                  <button
                    type="button"
                    onClick={() => handleGenerateVideo('video_only')}
                    disabled={!hasReusableVideoPrompt || Boolean(currentVideoGenerateDisabledReason)}
                    className="w-full px-3 py-2 text-left text-sm text-gray-700 hover:bg-blue-50 disabled:text-gray-400 disabled:hover:bg-white disabled:cursor-not-allowed"
                    title={currentVideoGenerateDisabledReason || (!hasReusableVideoPrompt ? '当前 Shot 没有可复用的视频最终 Prompt' : undefined)}
                  >
                    只生成当前Shot视频
                  </button>
                </div>
              )}
            </div>
          )}
          <button
            onClick={handleOpenBatchSelect}
            disabled={isGeneratingAll || !effectiveChapterId}
            className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            批量生成视频
          </button>
          <button
            onClick={handleSaveShot}
            disabled={isSaving || !effectiveChapterId}
            className="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
          >
            {isSaving ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                {t('common.saving')}
              </>
            ) : (
              <>
                <Save className="w-4 h-4" />
                保存视频规划
              </>
            )}
          </button>
          <button
            onClick={handleDownloadMaterials}
            disabled={isDownloading || !effectiveChapterId}
            className="px-4 py-2 bg-orange-600 text-white rounded-lg hover:bg-orange-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
          >
            {isDownloading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                {t('chapterGenerate.packing')}
              </>
            ) : (
              <>
                <Download className="w-4 h-4" />
                {t('chapterGenerate.downloadMaterials')}
              </>
            )}
          </button>
          <button
            onClick={handleOpenMergeSelect}
            disabled={mergingMode !== null || !effectiveChapterId || videoCount === 0}
            className="px-4 py-2 bg-pink-600 text-white rounded-lg hover:bg-pink-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
          >
            {mergingMode ? <Loader2 className="w-4 h-4 animate-spin" /> : <Combine className="w-4 h-4" />}
            {mergingMode ? '提交任务中...' : t('chapterGenerate.mergeVideo')}
          </button>
        </div>
        <div className="mr-8 flex min-w-[220px] max-w-[360px] flex-col items-end gap-1 text-right">
          <div className="text-sm text-gray-500">
            {t('chapterGenerate.shotId', { id: selectedVideo || 0, total: shotsList.length })}
          </div>
          <div className={`max-w-full rounded-lg border px-3 py-1.5 text-xs shadow-sm ${currentShotVideoResult.className}`}>
            <div className="flex items-center justify-end gap-2 font-medium">
              <Film className="h-3.5 w-3.5" />
              当前分镜：{currentShotVideoResult.label}
            </div>
            <div className="mt-0.5 truncate opacity-90" title={currentShotVideoResult.detail}>
              {currentShotVideoResult.detail}
            </div>
          </div>
        </div>
      </div>

      {/* 内容区 - 主编辑区 + 右侧视频预览 */}
      <div className="flex-1 min-h-0 flex flex-col lg:flex-row gap-4 overflow-hidden">
        {/* 中间：视频提示词编辑 + 视频导演 */}
        <div className="video-main-column flex-1 min-w-0 flex flex-col gap-4 overflow-y-auto pr-1">
          <VideoDirectorPanel
            shot={currentShotData}
            shotImageUrl={currentShotImageUrl}
            plan={currentVideoDirectorPlan}
            isRecommending={recommendingShotId === currentShotId}
            isPlanningKeyframes={planningKeyframesShotId === currentShotId}
            onRecommend={handleRecommendVideoMode}
            onPlanKeyframes={handlePlanVideoKeyframes}
            onGenerateMissingKeyframes={handleGenerateMissingKeyframes}
            onGenerateEndKeyframe={handleGenerateEndKeyframe}
            isGeneratingEndKeyframe={isGeneratingCurrentEndKeyframe}
            isGeneratingMissingKeyframes={generatingMissingKeyframesShotId === currentShotId}
            generatingKeyframes={generatingKeyframes}
            keyframeTasks={storeKeyframeTasks}
            onSelectMode={handleSelectVideoMode}
            onPreviewClip={handlePreviewClip}
            onRegenerateClip={handleRegenerateClip}
            onMergeClips={handleMergeDirectorClips}
            onPreviewImage={setPreviewImage}
            onEditImage={openVideoImageEdit}
            onOpenPromptModal={handleOpenVideoPromptModal}
            selectedPreviewClipKey={selectedPreviewClipKey}
            regeneratingClipKey={regeneratingClipKey}
            isMergingClips={isMergingClips}
            isShotVideoGenerating={isGeneratingCurrent}
          />

        </div>

        {/* 右侧：视频预览 + AI 调用结果 */}
        <div className="flex-shrink-0 lg:w-[360px] xl:w-[420px] min-h-0 flex flex-col gap-3 overflow-hidden">
        <div className="video-preview-card h-[360px] flex-shrink-0 flex flex-col border border-gray-200 rounded-lg overflow-hidden bg-white">
          <div className="flex-shrink-0 p-3 border-b border-gray-200 bg-gray-50 flex items-center justify-between">
            <div>
              <h3 className="text-sm font-medium text-gray-700">{t('chapterGenerate.videoPreview')} · {previewVideoLabel}</h3>
              {selectedPreviewClip && <div className="text-xs text-gray-500">C{selectedPreviewClip.window_index || selectedPreviewClip.clip_index} · {selectedPreviewClip.start_time}-{selectedPreviewClip.end_time}s</div>}
            </div>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={handlePictureInPicture}
                disabled={!hasPreviewVideo}
                className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-gray-600 hover:bg-white hover:text-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                title="画中画播放"
              >
                <PictureInPicture className="h-3.5 w-3.5" />
                画中画
              </button>
              <button
                type="button"
                onClick={handleRefreshCurrentVideo}
                disabled={isRefreshingVideo || !effectiveChapterId || !currentShotId}
                className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-gray-600 hover:bg-white hover:text-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                title="刷新视频预览"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${isRefreshingVideo ? 'animate-spin' : ''}`} />
                刷新
              </button>
            </div>
          </div>
          {currentPlanClips.length > 0 && currentSelectedVideoMode === 'MULTI_KEYFRAME' && (
            <div className="flex-shrink-0 border-b border-gray-200 bg-white px-3 py-2">
              <div className="flex gap-1 overflow-x-auto">
                <button
                  type="button"
                  onClick={() => setSelectedPreviewClipKey(null)}
                  disabled={!currentShotVideoUrl}
                  className={`rounded-md border px-2 py-1 text-xs transition-colors ${!selectedPreviewClip ? 'border-blue-300 bg-blue-50 text-blue-700' : 'border-gray-200 text-gray-600 hover:bg-gray-50'} disabled:opacity-50 disabled:cursor-not-allowed`}
                >
                  Shot 合并视频
                </button>
                {currentPlanClips.map((clip: any) => {
                  const clipKey = getPlanClipKey(clip);
                  const clipIndex = clip.window_index || clip.clip_index;
                  return (
                    <button
                      key={`preview-tab-${clipKey}`}
                      type="button"
                      onClick={() => setSelectedPreviewClipKey(clipKey)}
                      disabled={!clip.video_url}
                      title={!clip.video_url ? `C${clipIndex} 缺少可预览的视频记录` : `预览 C${clipIndex}`}
                      className={`rounded-md border px-2 py-1 text-xs transition-colors ${selectedPreviewClipKey === clipKey ? 'border-blue-300 bg-blue-50 text-blue-700' : 'border-gray-200 text-gray-600 hover:bg-gray-50'} disabled:opacity-50 disabled:cursor-not-allowed`}
                    >
                      C{clipIndex}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          <div className="video-preview-body flex-1 relative bg-gray-100">
            {hasPreviewVideo ? (
              <>
                <video
                  ref={previewVideoRef}
                  src={previewVideoUrl}
                  className="absolute inset-0 w-full h-full object-contain"
                  controls
                  onLoadedMetadata={handleVideoMetadataLoaded}
                />
                {previewClipMarkers.length > 0 && previewTimelineDuration > 0 && (
                  <div className="pointer-events-none absolute bottom-10 left-8 right-8 h-8">
                    {previewClipMarkers.map((marker: any) => {
                      const startPercent = Math.max(0, Math.min(100, (marker.startTime / previewTimelineDuration) * 100));
                      return (
                        <div key={`preview-marker-${marker.clipIndex}`} className="absolute bottom-0 -translate-x-1/2" style={{ left: `${startPercent}%` }}>
                          <div
                            className="mx-auto h-5 w-1 rounded-full bg-red-500 shadow-[0_0_0_2px_rgba(255,255,255,0.85)]"
                          />
                          <div className="absolute bottom-6 left-1/2 -translate-x-1/2 whitespace-nowrap rounded bg-black/70 px-1.5 py-0.5 text-[10px] font-medium text-white shadow">
                            C{marker.clipIndex} · {marker.startTime}s
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </>
            ) : isGeneratingCurrent ? (
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="text-center">
                  <Loader2 className="w-12 h-12 text-blue-500 animate-spin mx-auto mb-4" />
                  <p className="text-gray-600">{t('chapterGenerate.videoGenerating')}</p>
                </div>
              </div>
            ) : (
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="text-center text-gray-500">
                  <Film className="w-16 h-16 mx-auto mb-4 opacity-50" />
                  <p>{t('chapterGenerate.clickToGenerateVideo')}</p>
                </div>
              </div>
            )}
          </div>
          {hasPreviewVideo && (
            <div className="flex-shrink-0 border-t border-gray-200 bg-white px-3 py-2 text-xs text-gray-600 flex flex-wrap items-center gap-x-4 gap-y-1">
              <span>时长：{formatDuration(videoMetadata.duration)}</span>
              <span>分辨率：{videoMetadata.width && videoMetadata.height ? `${videoMetadata.width} x ${videoMetadata.height}` : '-'}</span>
              <span>大小：{formatFileSize(videoMetadata.sizeBytes)}</span>
              <span>码率：{formatBitrate(videoMetadata.sizeBytes, videoMetadata.duration)}</span>
            </div>
          )}
        </div>
        {(previewDriveAudioUrl || previewFinalAudioUrl) && (
          <div className="rounded-lg border border-gray-200 bg-white p-3">
            <div className="mb-2 flex items-center justify-between gap-2 text-xs text-gray-600">
              <span className="font-semibold text-gray-800">预览 Clip 音频</span>
              <span>C{previewAudioClip?.window_index || previewAudioClip?.clip_index || 1} · {previewAudioClip?.audio_status || previewAudioClip?.audioStatus || 'READY'}</span>
            </div>
            <div className="grid grid-cols-1 gap-2">
              {previewDriveAudioUrl && (
                <div className="rounded-md border border-cyan-100 bg-cyan-50/60 px-2 py-1.5">
                  <div className="mb-1 text-[11px] font-medium text-cyan-700">Drive 音频</div>
                  <audio src={previewDriveAudioUrl} controls preload="metadata" className="h-8 w-full" />
                </div>
              )}
              {previewFinalAudioUrl && (
                <div className="rounded-md border border-purple-100 bg-purple-50/60 px-2 py-1.5">
                  <div className="mb-1 text-[11px] font-medium text-purple-700">Final 音频</div>
                  <audio src={previewFinalAudioUrl} controls preload="metadata" className="h-8 w-full" />
                </div>
              )}
            </div>
          </div>
        )}
        <VideoAiCallsPanel
          calls={currentVideoDirectorPlan.ai_calls || []}
          novelId={effectiveNovelId}
          chapterId={effectiveChapterId}
          shotId={currentShotId}
          onRefresh={handleRefreshAiCalls}
          isRefreshing={isRefreshingAiCalls}
        />
        </div>

      </div>

      {/* 批量选择分镜弹窗 */}
      {showBatchSelectModal && createPortal((
        <div className="fixed inset-0 isolate z-[300] flex items-center justify-center bg-black/60 p-4 backdrop-blur-[1px]">
          <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl max-h-[80vh] flex flex-col">
            {/* 弹窗头部 */}
            <div className="flex items-center justify-between p-4 border-b border-gray-200">
              <div>
                <h3 className="text-lg font-semibold text-gray-800">{t('chapterGenerate.selectShotsToGenerate')}</h3>
                <p className="text-xs text-gray-500 mt-1">{t('chapterGenerate.selectShotsRegenerateHint')}</p>
              </div>
              <button
                onClick={() => setShowBatchSelectModal(false)}
                className="p-2 hover:bg-gray-100 rounded-full transition-colors"
                title={t('common.close')}
              >
                <X className="w-5 h-5 text-gray-500" />
              </button>
            </div>

            {/* 弹窗内容 - 分镜列表 */}
            <div className="flex-1 overflow-y-auto p-4 pb-8">
              <div className="flex items-center justify-between mb-3">
                <span className="text-sm text-gray-600">
                  已选择 {selectedShotIds.size} / 可选 {selectableShotIds().length} / 共 {shotsList.length} 个分镜
                </span>
                <div className="flex items-center gap-3">
                  <button
                    onClick={toggleSelectPendingVideos}
                    className={`text-sm flex items-center gap-1 transition-colors ${batchSelectionMode === 'pending' ? 'text-blue-700 font-medium' : 'text-gray-600 hover:text-blue-800'}`}
                  >
                    {batchSelectionMode === 'pending' ? <Check className="w-4 h-4" /> : <Square className="w-4 h-4" />}
                    选择所有未生成
                  </button>
                  <button
                    onClick={toggleSelectAll}
                    className={`text-sm flex items-center gap-1 transition-colors ${batchSelectionMode === 'all' ? 'text-blue-700 font-medium' : 'text-gray-600 hover:text-blue-800'}`}
                  >
                    {batchSelectionMode === 'all' ? <Check className="w-4 h-4" /> : <Square className="w-4 h-4" />}
                    {t('common.selectAll')}
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-4 gap-3">
                {shotsList.map((shot: any, idx: number) => {
                  const shotIndex = idx + 1;
                  const shotId = shot?.id ? String(shot.id) : '';
                  const isSelected = shotId ? selectedShotIds.has(shotId) : false;
                  const hasVideo = hasShotVideo(shot);
                  const isGenerating = shotId ? generatingVideos.has(shotId) || storePendingVideos.has(shotId) || shot?.videoStatus === 'generating' || (!!shot?.videoTaskId && shot?.videoStatus === 'pending') : false;
                  const eligibility = getBatchShotEligibility(shot);
                  const isSelectable = eligibility.selectable;
                  const shotImageUrl = getShotImageUrl(shot);

                  return (
                    <div
                      key={shot.id || `shot-${shotIndex}`}
                      onMouseDown={(event) => handleBatchShotMouseDown(event, shotId, isSelectable)}
                      onMouseEnter={() => handleBatchShotMouseEnter(shotId, isSelectable)}
                      title={isSelectable ? '可生成' : eligibility.reason}
                      className={`
                        relative aspect-video rounded-lg border-2 transition-all
                        group select-none
                        ${!isSelectable
                          ? 'border-gray-200 bg-gray-50 cursor-not-allowed opacity-60'
                          : 'cursor-pointer hover:shadow-md'
                        }
                        ${isSelectable && isSelected
                          ? 'border-blue-500 bg-blue-50'
                          : isSelectable && !isSelected
                            ? hasVideo
                              ? 'border-gray-300 bg-white hover:border-blue-300'
                              : 'border-gray-300 bg-white hover:border-gray-400'
                            : ''
                        }
                      `}
                    >
                      {/* 分镜编号 */}
                      <div className="absolute left-1 top-1 z-20 px-1.5 py-0.5 bg-black/60 text-white text-xs rounded">
                        #{shotIndex}
                      </div>

                      {/* 选择标记 - 只有可选分镜显示 */}
                      {isSelectable && (
                        <div className={`
                          absolute right-1 top-1 z-30 flex h-5 w-5 items-center justify-center rounded-full border shadow-sm transition-colors
                          ${isSelected ? 'border-blue-500 bg-blue-500' : 'border-white bg-white/90 group-hover:bg-blue-50'}
                        `}>
                          {isSelected && <Check className="h-3 w-3 text-white" />}
                        </div>
                      )}

                      {/* 内容区域 */}
                      <div className="w-full h-full overflow-hidden rounded-md bg-gray-100 flex items-center justify-center">
                        {shotImageUrl ? (
                          <img
                            src={shotImageUrl}
                            alt={`镜${shotIndex}`}
                            className={`h-full w-full object-cover transition-transform ${isSelectable ? 'group-hover:scale-105' : ''}`}
                            draggable={false}
                          />
                        ) : (
                          <Film className="w-8 h-8 text-gray-300" />
                        )}
                      </div>

                      {/* 状态图标 */}
                      <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center">
                        {isGenerating ? (
                          <Loader2 className="w-8 h-8 text-blue-500 animate-spin drop-shadow" />
                        ) : hasVideo ? (
                          <Film className="w-8 h-8 text-green-600 drop-shadow" />
                        ) : null}
                      </div>

                      {/* 状态标签 */}
                      <div className="absolute bottom-0 left-0 right-0 z-20 px-1 py-0.5 text-xs text-center bg-black/60 text-white rounded-b-lg truncate">
                        {isSelectable ? (hasVideo ? t('chapterGenerate.generated') : t('chapterGenerate.pending')) : eligibility.reason}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* 弹窗底部按钮 */}
            <div className="flex items-center justify-between gap-3 p-4 border-t border-gray-200">
              <label className="flex items-center gap-2 text-sm text-gray-700 select-none cursor-pointer">
                <input
                  type="checkbox"
                  checked={autoCompleteDetails}
                  onChange={(event) => {
                    const checked = event.target.checked;
                    setAutoCompleteDetails(checked);
                    const nextSelectableShotIds = shotsList
                      .map((shot: any) => {
                        const shotId = shot?.id ? String(shot.id) : '';
                        if (!shotId || generatingVideos.has(shotId) || storePendingVideos.has(shotId) || shot?.videoStatus === 'generating' || (!!shot?.videoTaskId && shot?.videoStatus === 'pending')) return null;
                        if (!getShotImageUrl(shot)) return null;
                        return getBatchShotEligibility(shot, checked).selectable ? shotId : null;
                      })
                      .filter((shotId: string | null): shotId is string => shotId !== null);
                    setSelectedShotIds(new Set(nextSelectableShotIds));
                    setBatchSelectionMode('all');
                  }}
                  className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                />
                自动完成细节（注意LLM可能会消耗大量的token）
              </label>
              <div className="flex items-center justify-end gap-3">
                <button
                  onClick={() => setShowBatchSelectModal(false)}
                  className="px-4 py-2 text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors"
                >
                  {t('common.cancel')}
                </button>
                <button
                  onClick={handleGenerateAll}
                  disabled={selectedShotIds.size === 0 || isGeneratingAll}
                  className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
                >
                  {isGeneratingAll ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      {t('chapterGenerate.generating')}
                    </>
                  ) : (
                    <>
                      <Film className="w-4 h-4" />
                      {t('chapterGenerate.generateShots', { count: selectedShotIds.size })}
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      ), document.body)}

      {/* 合并视频选择弹窗 */}
      {showMergeSelectModal && createPortal((
        <div className="fixed inset-0 isolate z-[300] flex items-center justify-center bg-black/60 p-4 backdrop-blur-[1px]">
          <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl max-h-[80vh] flex flex-col">
            <div className="flex items-center justify-between p-4 border-b border-gray-200">
              <div>
                <h3 className="text-lg font-semibold text-gray-800">选择要合并的分镜视频</h3>
                <p className="text-xs text-gray-500 mt-1">同一组分镜视频未变化时会复用缓存；选择不同分镜组合会生成不同章节视频。</p>
              </div>
              <button
                onClick={() => setShowMergeSelectModal(false)}
                className="p-2 hover:bg-gray-100 rounded-full transition-colors"
                title={t('common.close')}
              >
                <X className="w-5 h-5 text-gray-500" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-4 pb-8">
              <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
                <span className="text-sm text-gray-600">
                  已选择 {selectedMergeShotIds.size} / 可合并 {mergeReadyShotIds().length} / 共 {shotsList.length} 个分镜
                </span>
                <div className="flex items-center gap-4">
                  <label className="flex items-center gap-2 text-sm text-gray-700 select-none cursor-pointer">
                    <input
                      type="checkbox"
                      checked={mergeIncludeTransitions}
                      onChange={(event) => setMergeIncludeTransitions(event.target.checked)}
                      disabled={Object.keys(transitionVideos).length === 0}
                      className="h-4 w-4 rounded border-gray-300 text-pink-600 focus:ring-pink-500 disabled:opacity-50"
                    />
                    包含转场视频
                  </label>
                  <button
                    onClick={toggleMergeSelectAll}
                    className="text-sm flex items-center gap-1 text-gray-600 hover:text-pink-700 transition-colors"
                  >
                    {selectedMergeShotIds.size === mergeReadyShotIds().length && selectedMergeShotIds.size > 0 ? <Check className="w-4 h-4" /> : <Square className="w-4 h-4" />}
                    {selectedMergeShotIds.size === mergeReadyShotIds().length && selectedMergeShotIds.size > 0 ? '取消全选' : t('common.selectAll')}
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-4 gap-3">
                {shotsList.map((shot: any, idx: number) => {
                  const shotId = shot?.id ? String(shot.id) : '';
                  const shotIndex = shot.index || idx + 1;
                  const videoUrl = getMergeShotVideoUrl(shot);
                  const isSelected = shotId ? selectedMergeShotIds.has(shotId) : false;
                  const isGenerating = shotId ? generatingVideos.has(shotId) || storePendingVideos.has(shotId) : false;
                  const isFailed = shot?.videoStatus === 'failed';
                  const isSelectable = !!shotId && !!videoUrl;
                  const statusLabel = videoUrl ? '已生成' : isGenerating ? '生成中' : isFailed ? '失败' : '未生成';

                  return (
                    <div
                      key={shotId || `merge-shot-${shotIndex}`}
                      onMouseDown={(event) => handleMergeShotMouseDown(event, shotId, isSelectable)}
                      onMouseEnter={() => handleMergeShotMouseEnter(shotId, isSelectable)}
                      title={isSelectable ? `镜${shotIndex} 可合并` : `镜${shotIndex} ${statusLabel}`}
                      className={`
                        relative aspect-video rounded-lg border-2 transition-all
                        select-none
                        ${!isSelectable
                          ? 'border-gray-200 bg-gray-50 cursor-not-allowed opacity-60'
                          : 'cursor-pointer hover:shadow-md'
                        }
                        ${isSelectable && isSelected
                          ? 'border-blue-500 bg-blue-50'
                          : isSelectable && !isSelected
                            ? 'border-gray-300 bg-white hover:border-blue-300'
                            : ''
                        }
                      `}
                    >
                      <div className="absolute top-1 left-1 px-1.5 py-0.5 bg-black/60 text-white text-xs rounded">#{shotIndex}</div>
                      {isSelectable && (
                        <div className={`absolute top-1 right-1 w-5 h-5 rounded-full flex items-center justify-center ${isSelected ? 'bg-blue-500' : 'bg-gray-200'}`}>
                          {isSelected && <Check className="w-3 h-3 text-white" />}
                        </div>
                      )}
                      <div className="w-full h-full flex items-center justify-center">
                        {videoUrl ? <Film className="w-8 h-8 text-green-600" /> : isGenerating ? <Loader2 className="w-8 h-8 text-blue-500 animate-spin" /> : <Film className="w-8 h-8 text-gray-300" />}
                      </div>
                      <div className="absolute bottom-0 left-0 right-0 px-1 py-0.5 text-xs text-center bg-black/60 text-white rounded-b-lg truncate">
                        {statusLabel} · {Number(shot.duration || 0)}s
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="flex items-center justify-between gap-3 p-4 border-t border-gray-200">
              <div className="text-xs text-gray-500">
                将按分镜编号顺序合并所选视频{mergeIncludeTransitions ? '，并在相邻已选分镜之间插入已有转场' : ''}。
              </div>
              <div className="flex items-center gap-3">
                <button
                  onClick={() => setShowMergeSelectModal(false)}
                  className="px-4 py-2 text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors"
                >
                  {t('common.cancel')}
                </button>
                <button
                  onClick={() => handleMergeVideos(mergeIncludeTransitions ? 'shots_with_transitions' : 'shots_only')}
                  disabled={selectedMergeShotIds.size === 0 || mergingMode !== null}
                  className="px-4 py-2 bg-pink-600 text-white rounded-lg hover:bg-pink-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
                >
                  {mergingMode ? <Loader2 className="w-4 h-4 animate-spin" /> : <Combine className="w-4 h-4" />}
                  {mergingMode ? '提交任务中...' : `合并 ${selectedMergeShotIds.size} 个视频`}
                </button>
              </div>
            </div>
          </div>
        </div>
      ), document.body)}

      {/* 图片预览弹窗 */}
      <ImagePreviewModal
        isOpen={!!previewImage}
        url={previewImage}
        onClose={() => setPreviewImage(null)}
        showDownload={true}
      />

      <VideoPromptModal
        isOpen={isVideoPromptModalOpen}
        drafts={videoPromptDrafts}
        selectedMode={currentSelectedVideoMode}
        isSaving={isSavingVideoPrompts}
        onChange={handleChangeVideoPromptDraft}
        onClose={() => setIsVideoPromptModalOpen(false)}
        onSave={handleSaveVideoPrompts}
      />

      {imageEditTarget && (
        <ImageEditModal
          isOpen={!!imageEditTarget}
          itemName={imageEditTarget.itemName}
          imageUrl={imageEditTarget.imageUrl}
          resultUrl={imageEditResultUrl}
          isEditing={isEditingImage}
          isReplacing={isReplacingImage}
          resultSize={imageEditResultSize}
          onResultSizeChange={setImageEditResultSize}
          labels={{
            title: imageEditTarget.type === 'shot' ? '编辑分镜图片' : '编辑关键帧图片',
            optionsTitle: '编辑选项',
            keepOriginalLayout: '保持原图构图与布局',
            removeWeapons: '移除不需要的物体或干扰元素',
            makeFourView: '增强主体一致性与画面细节',
            other: '其它',
            otherPlaceholder: '输入额外编辑要求，例如：修正红框区域，保持人物和构图不变。',
            editButton: '编辑图片',
            editing: '编辑中...',
            replaceButton: imageEditTarget.type === 'shot' ? '替换分镜图片' : '替换关键帧图片',
            originalImage: '原图',
            editResult: '编辑结果',
            emptyResult: '生成后在这里预览',
          }}
          onClose={closeVideoImageEdit}
          onEdit={handleEditVideoImage}
          onReplace={handleReplaceVideoImage}
        />
      )}

      {/* 合并视频结果弹窗 */}
      {showMergeModal && mergedVideoUrl && (
          <div className="fixed inset-0 isolate z-[300] flex items-center justify-center bg-black/60 p-4 backdrop-blur-[1px]">
          <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl max-h-[80vh] flex flex-col">
            {/* 弹窗头部 */}
            <div className="flex items-center justify-between p-4 border-b border-gray-200">
              <div className="flex items-center gap-2">
                <Combine className="w-5 h-5 text-pink-600" />
                <h3 className="text-lg font-semibold text-gray-800">{t('chapterGenerate.mergeResult')}</h3>
              </div>
              <button
                onClick={() => {
                  setShowMergeModal(false);
                  setMergedVideoUrl(null);
                }}
                className="p-2 hover:bg-gray-100 rounded-full transition-colors"
                title={t('common.close')}
              >
                <X className="w-5 h-5 text-gray-500" />
              </button>
            </div>

            {/* 弹窗内容 - 视频播放器 */}
            <div className="flex-1 p-4 flex items-center justify-center bg-gray-100">
              <video
                src={mergedVideoUrl}
                controls
                className="max-w-full max-h-[60vh] w-full h-full object-contain rounded-lg shadow-lg"
              />
            </div>

            {/* 弹窗底部按钮 */}
            <div className="flex items-center justify-end gap-3 p-4 border-t border-gray-200">
              <button
                onClick={() => {
                  setShowMergeModal(false);
                  setMergedVideoUrl(null);
                }}
                className="px-4 py-2 text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors"
              >
                {t('common.close')}
              </button>
              <a
                href={mergedVideoUrl}
                download
                className="px-4 py-2 bg-pink-600 text-white rounded-lg hover:bg-pink-700 transition-colors flex items-center gap-2"
              >
                <Download className="w-4 h-4" />
                {t('common.download')}
              </a>
            </div>
          </div>
        </div>
      )}

      {/* 转场视频预览弹窗 */}
      {previewTransitionVideo && (
        <div className="fixed inset-0 isolate z-[300] flex items-center justify-center bg-black/60 backdrop-blur-[1px]">
          <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl max-h-[80vh] flex flex-col">
            <div className="flex items-center justify-between p-4 border-b border-gray-200">
              <div className="flex items-center gap-2">
                <Film className="w-5 h-5 text-emerald-600" />
                <h3 className="text-lg font-semibold text-gray-800">{t('chapterGenerate.transitionVideos')}</h3>
              </div>
              <button
                onClick={() => setPreviewTransitionVideo(null)}
                className="p-2 hover:bg-gray-100 rounded-full transition-colors"
                title={t('common.close')}
              >
                <X className="w-5 h-5 text-gray-500" />
              </button>
            </div>
            <div className="flex-1 p-4 flex items-center justify-center bg-gray-100">
              <video
                src={previewTransitionVideo}
                controls
                autoPlay
                className="max-w-full max-h-[60vh] w-full h-full object-contain rounded-lg shadow-lg"
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default VideoGenTab;
