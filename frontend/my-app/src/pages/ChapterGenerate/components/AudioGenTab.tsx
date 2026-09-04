import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Check, Clock, Image, Loader2, Mic, RefreshCw, Save, Square, Volume2, Wand2, X } from 'lucide-react';
import { audioDriveApi, type AudioDriveEvent, type AudioDriveExecutionWindow, type AudioTimeline } from '../../../api/audioDrive';
import { taskApi } from '../../../api/tasks';
import { useTranslation } from '../../../stores/i18nStore';
import { useChapterGenerateStore, useShotNavigatorSlice } from '../stores';

interface AudioGenTabProps {
  novelId: string;
  chapterId: string;
}

const statusClass: Record<string, string> = {
  READY: 'bg-green-100 text-green-700',
  GENERATING: 'bg-blue-100 text-blue-700',
  STALE: 'bg-amber-100 text-amber-700',
  FAILED: 'bg-red-100 text-red-700',
  NOT_GENERATED: 'bg-gray-100 text-gray-600',
  NOT_READY: 'bg-gray-100 text-gray-600',
};

const typeLabel: Record<string, string> = {
  DIALOGUE: '对白',
  NARRATION: '旁白',
  INNER_MONOLOGUE: '心理',
};

const typeClass: Record<string, string> = {
  DIALOGUE: 'bg-blue-50 text-blue-700 border-blue-200',
  NARRATION: 'bg-purple-50 text-purple-700 border-purple-200',
  INNER_MONOLOGUE: 'bg-amber-50 text-amber-700 border-amber-200',
};

const pauseAfterOptions: Array<{ value: AudioDriveEvent['pauseAfter']; label: string }> = [
  { value: 'NONE', label: 'NONE · 0.0s' },
  { value: 'SHORT', label: 'SHORT · 0.3s' },
  { value: 'MEDIUM', label: 'MEDIUM · 0.6s' },
  { value: 'LONG', label: 'LONG · 1.2s' },
];

function StatusBadge({ status }: { status?: string }) {
  const value = status || 'NOT_READY';
  return <span className={`rounded-full px-2 py-0.5 text-xs ${statusClass[value] || 'bg-gray-100 text-gray-600'}`}>{value}</span>;
}

function sortNarratorFirst<T extends { isNarrator?: boolean; name?: string }>(items: T[]) {
  return [...items].sort((a, b) => Number(Boolean(b.isNarrator || b.name === '旁白')) - Number(Boolean(a.isNarrator || a.name === '旁白')));
}

function normalizeWindow(window: AudioDriveExecutionWindow): AudioDriveExecutionWindow {
  return {
    ...window,
    windowIndex: window.windowIndex ?? window.window_index,
    startTime: window.startTime ?? window.start_time,
    endTime: window.endTime ?? window.end_time,
    audioStatus: window.audioStatus ?? window.audio_status,
    audioMessage: window.audioMessage ?? window.audio_message,
    driveAudioUrl: window.driveAudioUrl ?? window.drive_audio_url,
    finalAudioUrl: window.finalAudioUrl ?? window.final_audio_url,
    clipAudioDuration: window.clipAudioDuration ?? window.clip_audio_duration,
    speakerTimeline: window.speakerTimeline ?? window.speaker_timeline,
  };
}

function isShotAudioReady(shot: any) {
  const plan = shot?.videoDirectorPlan || {};
  const windows = Array.isArray(plan.window_plans) && plan.window_plans.length > 0
    ? plan.window_plans
    : Array.isArray(plan.execution_windows)
      ? plan.execution_windows
      : Array.isArray(plan.clips)
        ? plan.clips
        : [];
  return String(shot?.audioStatus || '').toUpperCase() === 'READY'
    && windows.length > 0
    && windows.every((window: any) => (
      String(window.audio_status || window.audioStatus || '').toUpperCase() === 'READY'
      && Boolean(window.drive_audio_url || window.driveAudioUrl)
      && Boolean(window.final_audio_url || window.finalAudioUrl)
    ));
}

const timelinePct = (value: number, total: number) => `${Math.max(0, Math.min(100, total > 0 ? (value / total) * 100 : 0))}%`;

function AudioTimelineChart({ timeline }: { timeline: AudioTimeline }) {
  const duration = Math.max(Number(timeline.totalDuration || 0), 0.001);
  const eventsBySpeaker = timeline.events.reduce((groups: Record<string, typeof timeline.events>, event) => {
    const speaker = event.voiceOwnerName || '声音';
    groups[speaker] = groups[speaker] || [];
    groups[speaker].push(event);
    return groups;
  }, {});
  const driveEvents = timeline.events.filter((event) => event.requiresVisibleLipsync && event.visibleSpeakerName);
  const ticks = [0, duration / 2, duration];

  return (
    <div className="rounded-lg border border-blue-100 bg-white p-3">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="text-sm font-semibold text-gray-900">Audio Timeline</div>
        <div className="text-xs text-gray-500">总时长：{timeline.totalDuration}s</div>
      </div>
      <div className="mb-2 grid grid-cols-[72px_minmax(0,1fr)] gap-2 text-[10px] text-gray-400">
        <div />
        <div className="relative h-4 border-t border-gray-200">
          {ticks.map((tick) => (
            <span key={tick} className="absolute top-0 -translate-x-1/2 border-l border-gray-200 pl-1" style={{ left: timelinePct(tick, duration) }}>{tick.toFixed(tick === 0 ? 0 : 1)}s</span>
          ))}
        </div>
      </div>
      <div className="space-y-2">
        {Object.entries(eventsBySpeaker).map(([speaker, speakerEvents]) => (
          <div key={speaker} className="grid grid-cols-[72px_minmax(0,1fr)] items-center gap-2">
            <div className="truncate text-xs font-medium text-gray-700" title={speaker}>{speaker}</div>
            <div className="relative h-9 rounded border border-gray-200 bg-gray-50">
              {speakerEvents.map((event) => (
                <div
                  key={event.audioEventId}
                  className="absolute top-1 h-7 overflow-hidden rounded bg-blue-100 px-2 text-[11px] leading-7 text-blue-800"
                  style={{ left: timelinePct(event.startTime, duration), width: timelinePct(event.endTime - event.startTime, duration) }}
                  title={`${event.startTime}s-${event.endTime}s · ${typeLabel[event.type] || event.type}`}
                >
                  {event.startTime}s-{event.endTime}s
                </div>
              ))}
            </div>
          </div>
        ))}
        <div className="grid grid-cols-[72px_minmax(0,1fr)] items-center gap-2 border-t border-gray-100 pt-2">
          <div className="text-xs font-medium text-cyan-700">Drive</div>
          <div className="relative h-8 rounded border border-cyan-100 bg-cyan-50/60">
            {driveEvents.map((event) => (
              <div
                key={`drive-${event.audioEventId}`}
                className="absolute top-1 h-6 overflow-hidden rounded bg-cyan-200 px-2 text-[11px] leading-6 text-cyan-900"
                style={{ left: timelinePct(event.startTime, duration), width: timelinePct(event.endTime - event.startTime, duration) }}
                title={`${event.startTime}s-${event.endTime}s · ${event.visibleSpeakerName}`}
              >
                {event.visibleSpeakerName}
              </div>
            ))}
          </div>
        </div>
        <div className="grid grid-cols-[72px_minmax(0,1fr)] items-center gap-2">
          <div className="text-xs font-medium text-purple-700">Final</div>
          <div className="relative h-8 rounded border border-purple-100 bg-purple-50/60">
            {timeline.events.map((event) => (
              <div
                key={`final-${event.audioEventId}`}
                className="absolute top-1 h-6 overflow-hidden rounded bg-purple-200 px-2 text-[11px] leading-6 text-purple-900"
                style={{ left: timelinePct(event.startTime, duration), width: timelinePct(event.endTime - event.startTime, duration) }}
                title={`${event.startTime}s-${event.endTime}s · ${event.voiceOwnerName}`}
              >
                {event.voiceOwnerName}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export function AudioGenTab({ novelId, chapterId }: AudioGenTabProps) {
  const { t } = useTranslation();
  const { currentShotIndex } = useShotNavigatorSlice();
  const { characters, shots, fetchShots, setAudioPrepareStatus, clearAudioPrepareStatus } = useChapterGenerateStore();

  const currentShot = shots.find((shot) => shot.index === currentShotIndex);
  const [events, setEvents] = useState<AudioDriveEvent[]>([]);
  const [timeline, setTimeline] = useState<AudioTimeline | null>(null);
  const [audioStatus, setAudioStatus] = useState('NOT_READY');
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [editingEvent, setEditingEvent] = useState<AudioDriveEvent | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [buildingTimeline, setBuildingTimeline] = useState(false);
  const [buildingWindows, setBuildingWindows] = useState(false);
  const [buildingClipAudio, setBuildingClipAudio] = useState<number | 'all' | null>(null);
  const [preparingAudio, setPreparingAudio] = useState(false);
  const [activePrepareTaskId, setActivePrepareTaskId] = useState<string | null>(null);
  const [showBatchAudioModal, setShowBatchAudioModal] = useState(false);
  const [selectedBatchShotIds, setSelectedBatchShotIds] = useState<Set<string>>(new Set());
  const [batchPreparing, setBatchPreparing] = useState(false);
  const [batchProgress, setBatchProgress] = useState('');
  const [maxClipDuration, setMaxClipDuration] = useState(15);
  const [clipWindows, setClipWindows] = useState<AudioDriveExecutionWindow[]>([]);
  const [message, setMessage] = useState<string>('');
  const batchDragRef = useRef<{ active: boolean; shouldSelect: boolean; touched: Set<string> }>({
    active: false,
    shouldSelect: true,
    touched: new Set(),
  });

  const selectedEvent = useMemo(
    () => events.find((event) => event.id === selectedEventId) || null,
    [events, selectedEventId],
  );

  const sortedCharacters = useMemo(() => sortNarratorFirst(characters), [characters]);
  const readyTtsCount = events.filter((event) => event.ttsStatus === 'READY').length;
  const staleCount = events.filter((event) => event.ttsStatus === 'STALE').length;
  const failedCount = events.filter((event) => event.ttsStatus === 'FAILED').length;
  const generatingCount = events.filter((event) => event.ttsStatus === 'GENERATING').length;
  const visibleSpeakerSelectValue = editingEvent?.visibleSpeakerCharacterId || (editingEvent?.visibleSpeakerName ? `name:${editingEvent.visibleSpeakerName}` : '');
  const audioReadyShotIds = useMemo(() => new Set(shots.filter(isShotAudioReady).map((shot: any) => String(shot.id))), [shots]);
  const selectableBatchShots = useMemo(() => shots.filter((shot: any) => Boolean(shot.id)), [shots]);
  const selectedBatchShots = useMemo(() => selectableBatchShots.filter((shot: any) => selectedBatchShotIds.has(String(shot.id))), [selectableBatchShots, selectedBatchShotIds]);

  const getRunningPrepareShotId = (step: string) => {
    const match = String(step || '').match(/镜\s*(\d+)/);
    if (!match) return null;
    const shotIndex = Number(match[1]);
    const shot = shots.find((item: any) => Number(item.index) === shotIndex);
    return shot?.id ? String(shot.id) : null;
  };

  const loadClipWindowsFromShot = () => {
    const plan = currentShot?.videoDirectorPlan as any;
    const windows = Array.isArray(plan?.window_plans)
      ? plan.window_plans
      : Array.isArray(plan?.execution_windows)
        ? plan.execution_windows
        : [];
    setClipWindows(windows.map(normalizeWindow));
  };

  const loadAudioDrive = async () => {
    if (!currentShot?.id) return;
    setLoading(true);
    try {
      const [eventsRes, timelineRes] = await Promise.all([
        audioDriveApi.fetchEvents(currentShot.id),
        audioDriveApi.fetchTimeline(currentShot.id),
      ]);
      const nextEvents = eventsRes.data?.events || [];
      setEvents(nextEvents);
      setAudioStatus(eventsRes.data?.audioStatus || 'NOT_READY');
      setTimeline(timelineRes.data || null);
      loadClipWindowsFromShot();
      setSelectedEventId((prev) => (
        prev && nextEvents.some((event) => event.id === prev)
          ? prev
          : nextEvents[0]?.id || null
      ));
    } catch (error) {
      console.error('加载 AudioDrive 数据失败:', error);
      setMessage('加载 AudioDrive 数据失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setSelectedEventId(null);
    setEditingEvent(null);
    setMessage('');
    loadAudioDrive();
  }, [currentShot?.id]);

  useEffect(() => {
    loadClipWindowsFromShot();
  }, [currentShot?.id, currentShot?.videoDirectorPlan]);

  useEffect(() => {
    setEditingEvent(selectedEvent ? { ...selectedEvent } : null);
  }, [selectedEvent?.id]);

  useEffect(() => {
    if (!currentShot?.id || generatingCount === 0) return;
    const timer = window.setInterval(loadAudioDrive, 3000);
    return () => window.clearInterval(timer);
  }, [currentShot?.id, generatingCount]);

  const saveEvent = async () => {
    if (!editingEvent) return;
    setSaving(true);
    setMessage('');
    try {
      const res = await audioDriveApi.updateEvent(editingEvent.id, {
        voiceOwnerCharacterId: editingEvent.voiceOwnerCharacterId,
        voiceOwnerName: editingEvent.voiceOwnerName,
        visibleSpeakerCharacterId: editingEvent.visibleSpeakerCharacterId,
        visibleSpeakerName: editingEvent.visibleSpeakerName,
        requiresVisibleLipsync: editingEvent.requiresVisibleLipsync,
        text: editingEvent.text,
        emotionPrompt: editingEvent.emotionPrompt,
        pauseAfter: editingEvent.pauseAfter,
      });
      if (!res.success) throw new Error(res.message || '保存失败');
      await loadAudioDrive();
      setMessage('Audio Event 已保存，下游状态已按规则标记');
    } catch (error) {
      setMessage((error as Error).message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const generateSelectedTts = async (force = false) => {
    if (!selectedEventId) return;
    setGenerating(true);
    setMessage('');
    try {
      const res = await audioDriveApi.generateEventTts(selectedEventId, force);
      if (!res.success) throw new Error(res.message || '提交 TTS 任务失败');
      setMessage('TTS 任务已提交到串行 worker');
      await loadAudioDrive();
    } catch (error) {
      setMessage((error as Error).message || '提交 TTS 任务失败');
    } finally {
      setGenerating(false);
    }
  };

  const generateShotTts = async (force = false) => {
    if (!currentShot?.id) return;
    setGenerating(true);
    setMessage('');
    try {
      const res = await audioDriveApi.generateShotTts(currentShot.id, { onlyStale: !force, force });
      if (!res.success) throw new Error(res.message || '提交批量 TTS 任务失败');
      setMessage(`批量 TTS 已提交到串行 worker，共 ${res.data?.tasks?.length || 0} 个任务`);
      await loadAudioDrive();
    } catch (error) {
      setMessage((error as Error).message || '提交批量 TTS 任务失败');
    } finally {
      setGenerating(false);
    }
  };

  const buildTimeline = async (force = false) => {
    if (!currentShot?.id) return;
    setBuildingTimeline(true);
    setMessage('');
    try {
      const res = force ? await audioDriveApi.rebuildTimeline(currentShot.id) : await audioDriveApi.buildTimeline(currentShot.id);
      if (!res.success) throw new Error(res.message || '构建 Timeline 失败');
      setTimeline(res.data || null);
      setAudioStatus('READY');
      setMessage('Audio Timeline 已构建，resolved_duration 已写回 Shot duration');
      await loadAudioDrive();
      await fetchShots(novelId, chapterId);
    } catch (error) {
      setMessage((error as Error).message || '构建 Timeline 失败');
    } finally {
      setBuildingTimeline(false);
    }
  };

  const buildExecutionWindows = async () => {
    if (!currentShot?.id) return;
    setBuildingWindows(true);
    setMessage('');
    try {
      const res = await audioDriveApi.buildExecutionWindows(currentShot.id, maxClipDuration);
      if (!res.success) throw new Error(res.message || '构建执行窗口失败');
      const windows = (res.data?.executionWindows || []).map(normalizeWindow);
      setClipWindows(windows);
      setMessage(`已构建 ${windows.length} 个执行窗口`);
      await fetchShots(novelId, chapterId);
    } catch (error) {
      setMessage((error as Error).message || '构建执行窗口失败');
    } finally {
      setBuildingWindows(false);
    }
  };

  const mergeClipAudioResult = (windowIndex: number, data: any) => {
    setClipWindows((prev) => prev.map((window) => (
      Number(window.windowIndex) === Number(windowIndex)
        ? normalizeWindow({
            ...window,
            audioStatus: data.audioStatus,
            audioMessage: data.message,
            driveAudioUrl: data.driveAudioUrl,
            finalAudioUrl: data.finalAudioUrl,
            speakerTimeline: data.speakerTimeline,
          })
        : window
    )));
  };

  const buildClipAudio = async (windowIndex: number, force = false) => {
    if (!currentShot?.id) return;
    setBuildingClipAudio(windowIndex);
    setMessage('');
    try {
      const res = await audioDriveApi.buildClipAudio(currentShot.id, windowIndex, force);
      if (!res.success) throw new Error(res.message || '构建 Clip Audio 失败');
      mergeClipAudioResult(windowIndex, res.data);
      setMessage(`Clip ${windowIndex} Audio 已构建`);
      await fetchShots(novelId, chapterId);
    } catch (error) {
      setMessage((error as Error).message || '构建 Clip Audio 失败');
    } finally {
      setBuildingClipAudio(null);
    }
  };

  const buildAllClipAudio = async (force = false) => {
    if (!currentShot?.id) return;
    let windows = clipWindows;
    setBuildingClipAudio('all');
    setMessage('');
    try {
      if (windows.length === 0) {
        const windowsRes = await audioDriveApi.buildExecutionWindows(currentShot.id, maxClipDuration);
        if (!windowsRes.success) throw new Error(windowsRes.message || '构建执行窗口失败');
        windows = (windowsRes.data?.executionWindows || []).map(normalizeWindow);
        setClipWindows(windows);
      }
      for (const window of windows) {
        const windowIndex = Number(window.windowIndex || window.window_index || 0);
        if (!windowIndex) continue;
        const res = await audioDriveApi.buildClipAudio(currentShot.id, windowIndex, force);
        if (!res.success) throw new Error(res.message || `Clip ${windowIndex} Audio 构建失败`);
        mergeClipAudioResult(windowIndex, res.data);
      }
      setMessage(`已构建 ${windows.length} 个 Clip Audio`);
      await fetchShots(novelId, chapterId);
    } catch (error) {
      setMessage((error as Error).message || '构建全部 Clip Audio 失败');
    } finally {
      setBuildingClipAudio(null);
    }
  };

  const prepareCurrentShotAudio = async () => {
    if (!currentShot?.id) return;
    setPreparingAudio(true);
    setBuildingClipAudio('all');
    try {
      const res = await audioDriveApi.prepareShotAudio(currentShot.id, {
        maxClipDuration,
        forceTts: false,
        forceClipAudio: true,
      });
      if (!res.success) throw new Error(res.message || '提交音频准备任务失败');
      const taskId = res.data?.taskId || '';
      setAudioPrepareStatus([String(currentShot.id)], String(currentShot.id));
      setActivePrepareTaskId(taskId || null);
      setMessage(`已提交持久化音频准备任务：${taskId}`);
      await fetchShots(novelId, chapterId);
      await loadAudioDrive();
    } catch (error) {
      setMessage((error as Error).message || '提交一键准备音频失败');
    } finally {
      setPreparingAudio(false);
      setBuildingClipAudio(null);
    }
  };

  const openBatchAudioModal = () => {
    setSelectedBatchShotIds(new Set(selectableBatchShots.filter((shot: any) => !isShotAudioReady(shot)).map((shot: any) => String(shot.id))));
    setBatchProgress('');
    setShowBatchAudioModal(true);
  };

  const toggleBatchShot = (shotId: string) => {
    setSelectedBatchShotIds((prev) => {
      const next = new Set(prev);
      if (next.has(shotId)) next.delete(shotId);
      else next.add(shotId);
      return next;
    });
  };

  const applyBatchShotSelection = (shotId: string, shouldSelect: boolean) => {
    setSelectedBatchShotIds((prev) => {
      const next = new Set(prev);
      if (shouldSelect) next.add(shotId);
      else next.delete(shotId);
      return next;
    });
  };

  const startBatchShotDrag = (shotId: string, isSelected: boolean, event: any) => {
    if (batchPreparing) return;
    event.preventDefault();
    const shouldSelect = !isSelected;
    batchDragRef.current = { active: true, shouldSelect, touched: new Set([shotId]) };
    applyBatchShotSelection(shotId, shouldSelect);
  };

  const enterBatchShotDrag = (shotId: string) => {
    const drag = batchDragRef.current;
    if (!drag.active || drag.touched.has(shotId) || batchPreparing) return;
    drag.touched.add(shotId);
    applyBatchShotSelection(shotId, drag.shouldSelect);
  };

  const endBatchShotDrag = () => {
    batchDragRef.current = { active: false, shouldSelect: true, touched: new Set() };
  };

  useEffect(() => {
    if (!showBatchAudioModal) return;
    window.addEventListener('pointerup', endBatchShotDrag);
    return () => window.removeEventListener('pointerup', endBatchShotDrag);
  }, [showBatchAudioModal]);

  useEffect(() => {
    if (!activePrepareTaskId) return;
    let cancelled = false;
    const refreshWhenDone = async () => {
      try {
        const res = await taskApi.fetch(activePrepareTaskId);
        const task = res.data as any;
        if (!task || cancelled) return;
        const status = String(task.status || '').toLowerCase();
        const step = task.currentStep || task.current_step || '';
        const metadata = task.metadata || task.metadataJson || task.metadata_json || {};
        const pendingShotIds = Array.isArray(metadata.shot_ids) ? metadata.shot_ids.map(String) : [];
        if (status === 'pending' || status === 'running' || status === 'queued') {
          setAudioPrepareStatus(pendingShotIds, getRunningPrepareShotId(step));
          setMessage(`音频准备任务执行中：${task.progress || 0}%${step ? ` · ${step}` : ''}`);
          return;
        }
        await fetchShots(novelId, chapterId);
        await loadAudioDrive();
        clearAudioPrepareStatus();
        if (status === 'completed') {
          setMessage('音频准备任务已完成，页面数据已刷新');
        } else {
          setMessage(task.errorMessage || task.error_message || '音频准备任务失败，页面数据已刷新');
        }
        setActivePrepareTaskId(null);
      } catch (error) {
        if (!cancelled) setMessage((error as Error).message || '查询音频准备任务失败');
      }
    };
    refreshWhenDone();
    const timer = window.setInterval(refreshWhenDone, 3000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [activePrepareTaskId, chapterId, novelId, shots]);

  const selectPendingAudioShots = () => {
    setSelectedBatchShotIds(new Set(selectableBatchShots.filter((shot: any) => !isShotAudioReady(shot)).map((shot: any) => String(shot.id))));
  };

  const toggleSelectAllAudioShots = () => {
    if (selectedBatchShotIds.size === selectableBatchShots.length) {
      setSelectedBatchShotIds(new Set());
    } else {
      setSelectedBatchShotIds(new Set(selectableBatchShots.map((shot: any) => String(shot.id))));
    }
  };

  const prepareBatchAudio = async () => {
    if (selectedBatchShots.length === 0) return;
    setBatchPreparing(true);
    try {
      setBatchProgress(`正在提交 ${selectedBatchShots.length} 个分镜的持久化音频准备任务...`);
      const res = await audioDriveApi.prepareBatchAudio({
        shotIds: selectedBatchShots.map((shot: any) => String(shot.id)),
        maxClipDuration,
        forceTts: false,
        forceClipAudio: true,
      });
      if (!res.success) throw new Error(res.message || '提交批量音频准备任务失败');
      const taskId = res.data?.taskId || '';
      setAudioPrepareStatus(selectedBatchShots.map((shot: any) => String(shot.id)), null);
      setActivePrepareTaskId(taskId || null);
      await fetchShots(novelId, chapterId);
      await loadAudioDrive();
      setBatchProgress(`已提交持久化任务：${taskId}，可关闭或刷新页面，后端会继续执行。`);
      setMessage(`已提交批量音频准备任务：${selectedBatchShots.length} 个分镜`);
      setShowBatchAudioModal(false);
    } catch (error) {
      setBatchProgress((error as Error).message || '提交批量音频准备任务失败');
    } finally {
      setBatchPreparing(false);
      setBuildingClipAudio(null);
    }
  };

  if (!currentShot) {
    return <div className="flex h-full items-center justify-center text-sm text-gray-500">请选择分镜</div>;
  }

  return (
    <div className="flex h-full flex-col bg-white">
      <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-gray-900">AudioDrive 工作区</h3>
            <StatusBadge status={audioStatus} />
          </div>
          <p className="mt-0.5 text-xs text-gray-500">分镜图生成和音频生成可并行；视频生成前会检查 Audio Timeline / resolved_duration。</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={prepareCurrentShotAudio} disabled={preparingAudio || events.length === 0} className="inline-flex items-center gap-1 rounded-lg bg-purple-600 px-3 py-2 text-sm text-white hover:bg-purple-700 disabled:opacity-50">
            {preparingAudio ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
            一键准备音频
          </button>
          <button onClick={openBatchAudioModal} disabled={batchPreparing || shots.length === 0} className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-3 py-2 text-sm text-white hover:bg-emerald-700 disabled:opacity-50">
            {batchPreparing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Volume2 className="h-4 w-4" />}
            批量准备音频
          </button>
          <button onClick={() => generateShotTts(false)} disabled={generating || events.length === 0} className="inline-flex items-center gap-1 rounded-lg bg-green-600 px-3 py-2 text-sm text-white hover:bg-green-700 disabled:opacity-50">
            {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Mic className="h-4 w-4" />}
            批量生成 TTS
          </button>
          <button onClick={() => buildTimeline(false)} disabled={buildingTimeline || events.length === 0} className="inline-flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50">
            {buildingTimeline ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
            构建 Timeline
          </button>
          <button onClick={() => buildAllClipAudio(false)} disabled={buildingClipAudio !== null || timeline?.status !== 'READY'} className="inline-flex items-center gap-1 rounded-lg bg-cyan-600 px-3 py-2 text-sm text-white hover:bg-cyan-700 disabled:opacity-50">
            {buildingClipAudio === 'all' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Volume2 className="h-4 w-4" />}
            构建全部 Clip Audio
          </button>
          <button onClick={loadAudioDrive} disabled={loading} className="rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50">
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {message && <div className="mx-4 mt-3 rounded-lg border border-blue-100 bg-blue-50 px-3 py-2 text-sm text-blue-700">{message}</div>}

      <div className="flex min-h-0 flex-1 overflow-hidden">
        <aside className="w-64 shrink-0 overflow-y-auto border-r border-gray-200 bg-gray-50 p-3">
          <h4 className="text-sm font-medium text-gray-800">Voice Profile</h4>
          <p className="mb-3 text-xs text-gray-500">角色库音色，可与分镜图生成并行准备</p>
          <div className="space-y-2">
            {sortedCharacters.map((character) => (
              <div key={character.id} className={`rounded-lg border bg-white p-3 ${character.isNarrator ? 'border-purple-200' : 'border-gray-200'}`}>
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-gray-900">{character.name}</div>
                    <div className="mt-0.5 text-xs text-gray-500">{character.isNarrator ? '旁白 Voice' : '角色 Voice'}</div>
                  </div>
                  {character.referenceAudioUrl ? <Check className="h-4 w-4 text-green-600" /> : <Clock className="h-4 w-4 text-gray-400" />}
                </div>
                {character.referenceAudioUrl ? (
                  <audio src={character.referenceAudioUrl} controls preload="metadata" className="mt-2 h-8 w-full" />
                ) : (
                  <div className="mt-2 rounded bg-amber-50 px-2 py-1 text-xs text-amber-700">未生成音色</div>
                )}
              </div>
            ))}
          </div>
        </aside>

        <aside className="w-72 shrink-0 overflow-y-auto border-r border-gray-200 p-3">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <h4 className="text-sm font-medium text-gray-800">Audio Events</h4>
              <p className="text-xs text-gray-500">镜 {currentShotIndex} · {events.length} 个声音事件</p>
            </div>
          </div>
          <div className="space-y-2">
            {events.map((event) => (
              <button
                key={event.id}
                onClick={() => setSelectedEventId(event.id)}
                className={`w-full rounded-lg border p-3 text-left transition-colors hover:bg-blue-50 ${selectedEventId === event.id ? 'border-blue-400 bg-blue-50' : 'border-gray-200 bg-white'}`}
              >
                <div className="mb-2 flex items-center gap-2">
                  <span className="text-xs font-medium text-gray-500">#{event.order}</span>
                  <span className={`rounded border px-1.5 py-0.5 text-xs ${typeClass[event.type] || typeClass.DIALOGUE}`}>{typeLabel[event.type] || event.type}</span>
                  <StatusBadge status={event.ttsStatus} />
                </div>
                <div className="text-sm font-medium text-gray-900">{event.voiceOwnerName || '未知声音'}</div>
                <div className="mt-1 line-clamp-2 text-xs text-gray-500">{event.text || '无文本'}</div>
                <div className="mt-2 text-xs text-gray-500">visible: {event.requiresVisibleLipsync ? event.visibleSpeakerName || '未指定' : 'NONE'}</div>
              </button>
            ))}
            {events.length === 0 && (
              <div className="rounded-lg border border-dashed border-gray-300 p-4 text-sm text-gray-500">
                当前 Shot 尚无 Audio Events。请先使用 V2.1 分镜拆分模板重新拆分，旧 dialogues 暂作为兼容数据保留。
              </div>
            )}
          </div>
        </aside>

        <main className="min-w-0 flex-1 overflow-y-auto p-5">
          {!editingEvent ? (
            <div className="flex h-full items-center justify-center text-sm text-gray-500">请选择一个 Audio Event</div>
          ) : (
            <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
              <section className="space-y-4">
                <div className="rounded-xl border border-gray-200 bg-white p-4">
                  <div className="mb-4 flex items-center justify-between">
                    <div>
                      <h4 className="text-base font-semibold text-gray-900">编辑 Audio Event #{editingEvent.order}</h4>
                      <p className="text-xs text-gray-500">Audio Events 是 TTS 的唯一业务输入，dialogues 仅兼容。</p>
                    </div>
                    <StatusBadge status={editingEvent.ttsStatus} />
                  </div>
                  <div className="space-y-4">
                    <label className="block">
                      <span className="mb-1 block text-sm font-medium text-gray-700">文本</span>
                      <textarea value={editingEvent.text || ''} onChange={(e) => setEditingEvent({ ...editingEvent, text: e.target.value })} rows={4} className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500" />
                    </label>
                    <div className="grid gap-3 md:grid-cols-2">
                      <label className="block">
                        <span className="mb-1 block text-sm font-medium text-gray-700">情绪</span>
                        <input value={editingEvent.emotionPrompt || ''} onChange={(e) => setEditingEvent({ ...editingEvent, emotionPrompt: e.target.value })} className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm" />
                      </label>
                      <label className="block">
                        <span className="mb-1 block text-sm font-medium text-gray-700">停顿</span>
                        <select value={editingEvent.pauseAfter} onChange={(e) => setEditingEvent({ ...editingEvent, pauseAfter: e.target.value as AudioDriveEvent['pauseAfter'] })} className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm">
                          {pauseAfterOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                        </select>
                      </label>
                      <label className="block">
                        <span className="mb-1 block text-sm font-medium text-gray-700">Voice Owner</span>
                        <select value={editingEvent.voiceOwnerCharacterId || ''} onChange={(e) => {
                          const character = characters.find((item) => item.id === e.target.value);
                          setEditingEvent({ ...editingEvent, voiceOwnerCharacterId: character?.id || null, voiceOwnerName: character?.name || editingEvent.voiceOwnerName });
                        }} className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm">
                          <option value="">按名称：{editingEvent.voiceOwnerName}</option>
                          {sortedCharacters.map((character) => <option key={character.id} value={character.id}>{character.name}</option>)}
                        </select>
                      </label>
                      <label className="block">
                        <span className="mb-1 block text-sm font-medium text-gray-700">Visible Speaker</span>
                        <select value={visibleSpeakerSelectValue} onChange={(e) => {
                          if (!e.target.value) {
                            setEditingEvent({ ...editingEvent, visibleSpeakerCharacterId: null, visibleSpeakerName: null, requiresVisibleLipsync: false });
                            return;
                          }
                          const character = characters.find((item) => item.id === e.target.value);
                          if (character) {
                            setEditingEvent({ ...editingEvent, visibleSpeakerCharacterId: character.id, visibleSpeakerName: character.name, requiresVisibleLipsync: true });
                          }
                        }} className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm">
                          <option value="">NONE</option>
                          {editingEvent.visibleSpeakerName && !editingEvent.visibleSpeakerCharacterId && (
                            <option value={`name:${editingEvent.visibleSpeakerName}`}>按名称：{editingEvent.visibleSpeakerName}</option>
                          )}
                          {sortedCharacters.filter((character) => !character.isNarrator).map((character) => <option key={character.id} value={character.id}>{character.name}</option>)}
                        </select>
                      </label>
                    </div>
                    <label className="flex items-center gap-2 text-sm text-gray-700">
                      <input type="checkbox" checked={editingEvent.requiresVisibleLipsync} onChange={(e) => setEditingEvent({ ...editingEvent, requiresVisibleLipsync: e.target.checked })} />
                      需要可见口型驱动
                    </label>
                    <div className="flex gap-2">
                      <button onClick={saveEvent} disabled={saving} className="inline-flex items-center gap-1 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50">
                        {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                        保存事件
                      </button>
                      <button onClick={() => generateSelectedTts(editingEvent.ttsStatus === 'READY')} disabled={generating || !editingEvent.text} className="inline-flex items-center gap-1 rounded-lg bg-green-600 px-4 py-2 text-sm text-white hover:bg-green-700 disabled:opacity-50">
                        {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Mic className="h-4 w-4" />}
                        {editingEvent.ttsStatus === 'READY' ? '重新生成 TTS' : '生成 TTS'}
                      </button>
                    </div>
                  </div>
                </div>
                <div className="rounded-xl border border-gray-200 bg-white p-4">
                  <div className="mb-2 flex items-center gap-2 text-sm font-medium text-gray-900"><Volume2 className="h-4 w-4" />TTS 结果</div>
                  {editingEvent.currentTtsAsset?.audioUrl ? (
                    <div className="space-y-2">
                      <audio src={editingEvent.currentTtsAsset.audioUrl} controls preload="metadata" className="h-8 w-full max-w-xl" />
                      <div className="text-xs text-gray-500">实际时长：{editingEvent.currentTtsAsset.durationSeconds ?? '-'}s · revision {editingEvent.currentTtsAsset.revision ?? '-'}</div>
                    </div>
                  ) : (
                    <div className="text-sm text-gray-500">尚未生成 TTS。</div>
                  )}
                </div>
              </section>

              <aside className="space-y-4">
                <div className="rounded-xl border border-gray-200 bg-white p-4">
                  <h4 className="text-sm font-semibold text-gray-900">前置准备</h4>
                  <div className="mt-3 space-y-2 text-sm">
                    <div className="flex justify-between"><span>Audio Events</span><span>{events.length}</span></div>
                    <div className="flex justify-between"><span>TTS READY</span><span>{readyTtsCount}/{events.length}</span></div>
                    <div className="flex justify-between"><span>STALE</span><span>{staleCount}</span></div>
                    <div className="flex justify-between"><span>FAILED</span><span>{failedCount}</span></div>
                    <div className="flex justify-between"><span>estimated_duration</span><span>{currentShot.estimatedDuration ?? currentShot.duration}s</span></div>
                    <div className="flex justify-between"><span>resolved_duration</span><span>{timeline?.totalDuration ?? '-'}s</span></div>
                  </div>
                  <button onClick={() => buildTimeline(true)} disabled={buildingTimeline || events.length === 0} className="mt-4 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50">重建 Timeline</button>
                </div>

                <div className="rounded-xl border border-gray-200 bg-white p-4">
                  <div className="mb-3 flex items-center justify-between">
                    <h4 className="text-sm font-semibold text-gray-900">Clip Audio</h4>
                    <StatusBadge status={clipWindows.length > 0 && clipWindows.every((window) => window.audioStatus === 'READY') ? 'READY' : 'NOT_READY'} />
                  </div>
                  <div className="mb-3 grid grid-cols-[1fr_auto] gap-2">
                    <label className="block">
                      <span className="mb-1 block text-xs text-gray-500">Max Clip Duration</span>
                      <input
                        type="number"
                        min={1}
                        max={60}
                        value={maxClipDuration}
                        onChange={(e) => setMaxClipDuration(Math.max(1, Math.min(60, Number(e.target.value) || 15)))}
                        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                      />
                    </label>
                    <button onClick={buildExecutionWindows} disabled={buildingWindows || timeline?.status !== 'READY'} className="self-end rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50">
                      {buildingWindows ? '构建中' : '构建窗口'}
                    </button>
                  </div>
                  <button onClick={() => buildAllClipAudio(true)} disabled={buildingClipAudio !== null || timeline?.status !== 'READY'} className="mb-3 w-full rounded-lg bg-cyan-600 px-3 py-2 text-sm text-white hover:bg-cyan-700 disabled:opacity-50">
                    {buildingClipAudio === 'all' ? '构建中...' : '重建全部 Clip Audio'}
                  </button>
                  <div className="space-y-3">
                    {clipWindows.map((window) => {
                      const windowIndex = Number(window.windowIndex || window.window_index || 0);
                      return (
                        <div key={`clip-audio-${windowIndex}`} className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs text-gray-700">
                          <div className="mb-2 flex items-center justify-between gap-2">
                            <div className="font-medium text-gray-900">Clip {windowIndex} · {window.startTime ?? window.start_time ?? '-'}s - {window.endTime ?? window.end_time ?? '-'}s</div>
                            <StatusBadge status={window.audioStatus} />
                          </div>
                          <div className="mb-2 flex gap-2">
                            <button onClick={() => buildClipAudio(windowIndex, false)} disabled={buildingClipAudio !== null || timeline?.status !== 'READY'} className="rounded border border-gray-300 bg-white px-2 py-1 hover:bg-gray-50 disabled:opacity-50">
                              {buildingClipAudio === windowIndex ? '构建中...' : '构建'}
                            </button>
                            <button onClick={() => buildClipAudio(windowIndex, true)} disabled={buildingClipAudio !== null || timeline?.status !== 'READY'} className="rounded border border-gray-300 bg-white px-2 py-1 hover:bg-gray-50 disabled:opacity-50">重建</button>
                            {window.clipAudioDuration !== undefined && <span className="self-center text-gray-500">{window.clipAudioDuration}s</span>}
                          </div>
                          {window.driveAudioUrl && (
                            <div className="mb-2 rounded-md border border-cyan-100 bg-white p-2">
                              <div className="mb-1 font-medium text-cyan-700">Drive 音频</div>
                              <audio src={window.driveAudioUrl} controls preload="metadata" className="h-8 w-full" />
                            </div>
                          )}
                          {window.finalAudioUrl && (
                            <div className="rounded-md border border-purple-100 bg-white p-2">
                              <div className="mb-1 font-medium text-purple-700">Final 音频</div>
                              <audio src={window.finalAudioUrl} controls preload="metadata" className="h-8 w-full" />
                            </div>
                          )}
                          {!window.driveAudioUrl && !window.finalAudioUrl && (
                            <div className="text-gray-500">尚未构建 drive/final 音频。</div>
                          )}
                        </div>
                      );
                    })}
                    {clipWindows.length === 0 && (
                      <div className="rounded-lg border border-dashed border-gray-300 p-3 text-sm text-gray-500">Timeline READY 后先构建执行窗口。</div>
                    )}
                  </div>
                </div>

                <div className="rounded-xl border border-gray-200 bg-white p-4">
                  <div className="mb-3 flex items-center justify-between">
                    <h4 className="text-sm font-semibold text-gray-900">Audio Timeline</h4>
                    <StatusBadge status={timeline?.status} />
                  </div>
                  {timeline ? (
                    <AudioTimelineChart timeline={timeline} />
                  ) : (
                    <div className="text-sm text-gray-500">Timeline 尚未构建。TTS READY 后点击“构建 Timeline”。</div>
                  )}
                </div>
              </aside>
            </div>
          )}
        </main>
      </div>
      {showBatchAudioModal && createPortal((
        <div className="fixed inset-0 isolate z-[300] flex items-center justify-center bg-black/60 p-4 backdrop-blur-[1px]">
          <div className="flex max-h-[84vh] w-full max-w-4xl flex-col rounded-xl bg-white shadow-2xl">
            <div className="flex items-start justify-between gap-4 border-b border-gray-200 px-5 py-4">
              <div>
                <h3 className="text-lg font-semibold text-gray-900">选择要准备音频的分镜</h3>
                <p className="mt-1 text-sm text-gray-500">按分镜顺序串行执行：TTS → Timeline → Clip Audio。已 READY 的分镜也可以重新选择准备。</p>
              </div>
              <button onClick={() => setShowBatchAudioModal(false)} disabled={batchPreparing} className="rounded-full p-2 text-gray-400 hover:bg-gray-100 hover:text-gray-600 disabled:opacity-50">
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto px-5 py-4">
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                <span className="text-sm text-gray-600">已选择 {selectedBatchShotIds.size} / {selectableBatchShots.length} 个分镜</span>
                <div className="flex items-center gap-3">
                  <button onClick={selectPendingAudioShots} disabled={batchPreparing} className="inline-flex items-center gap-1 text-sm text-blue-600 hover:text-blue-800 disabled:opacity-50">
                    <Check className="h-4 w-4" />只选择待准备
                  </button>
                  <button onClick={toggleSelectAllAudioShots} disabled={batchPreparing} className="inline-flex items-center gap-1 text-sm text-blue-600 hover:text-blue-800 disabled:opacity-50">
                    {selectedBatchShotIds.size === selectableBatchShots.length && selectableBatchShots.length > 0 ? <Square className="h-4 w-4" /> : <Check className="h-4 w-4" />}
                    {selectedBatchShotIds.size === selectableBatchShots.length && selectableBatchShots.length > 0 ? '取消全选' : '全选'}
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                {selectableBatchShots.map((shot: any) => {
                  const shotId = String(shot.id);
                  const isSelected = selectedBatchShotIds.has(shotId);
                  const isReady = audioReadyShotIds.has(shotId);
                  const imageUrl = shot.imageUrl || shot.image_url;
                  return (
                    <button
                      key={shotId}
                      type="button"
                      onClick={(event) => event.preventDefault()}
                      onPointerDown={(event) => startBatchShotDrag(shotId, isSelected, event)}
                      onPointerEnter={() => enterBatchShotDrag(shotId)}
                      onPointerUp={endBatchShotDrag}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault();
                          toggleBatchShot(shotId);
                        }
                      }}
                      disabled={batchPreparing}
                      className={`relative aspect-video select-none overflow-hidden rounded-lg border-2 text-left transition-all disabled:cursor-not-allowed disabled:opacity-70 ${isSelected ? 'border-blue-500 bg-blue-50 ring-2 ring-blue-100' : 'border-gray-200 bg-gray-50 hover:border-blue-300'}`}
                    >
                      {imageUrl ? <img src={imageUrl} alt={`镜${shot.index}`} draggable={false} className="h-full w-full object-cover" /> : <Image className="m-auto mt-10 h-8 w-8 text-gray-300" />}
                      <div className="absolute left-1 top-1 rounded bg-black/60 px-1.5 py-0.5 text-xs font-medium text-white">#{shot.index}</div>
                      <div className={`absolute right-1 top-1 flex h-5 w-5 items-center justify-center rounded-full ${isSelected ? 'bg-blue-500 text-white' : 'bg-white/85 text-gray-300'}`}>
                        {isSelected && <Check className="h-3.5 w-3.5" />}
                      </div>
                      <div className={`absolute bottom-0 left-0 right-0 px-2 py-1 text-center text-xs text-white ${isReady ? 'bg-green-600/85' : 'bg-black/60'}`}>
                        {isReady ? '音频 READY' : '待准备'}
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="flex items-center justify-between gap-3 border-t border-gray-200 px-5 py-4">
              <div className="min-w-0 text-sm text-gray-500">{batchProgress || '会跳过已 READY 的 TTS，但会重建 Timeline 和 Clip Audio，保证下游状态一致。'}</div>
              <div className="flex shrink-0 items-center gap-3">
                <button onClick={() => setShowBatchAudioModal(false)} disabled={batchPreparing} className="rounded-lg bg-gray-100 px-4 py-2 text-sm text-gray-700 hover:bg-gray-200 disabled:opacity-50">取消</button>
                <button onClick={prepareBatchAudio} disabled={batchPreparing || selectedBatchShotIds.size === 0} className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50">
                  {batchPreparing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Volume2 className="h-4 w-4" />}
                  准备 {selectedBatchShotIds.size} 个分镜音频
                </button>
              </div>
            </div>
          </div>
        </div>
      ), document.body)}
    </div>
  );
}

export default AudioGenTab;
