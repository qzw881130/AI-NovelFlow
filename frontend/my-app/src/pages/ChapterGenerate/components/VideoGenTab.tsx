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
import { useShotReferenceImages } from '../useShotReferenceImages';
import { Film, Loader2, Download, Save, Square, Check, X, Image, ChevronDown, Eye, Combine, Layers, ChevronUp, Volume2, Play, Copy, Info, ChevronLeft, ChevronRight, RefreshCw, Sparkles, PictureInPicture, Trash2 } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import { shotsApi } from '../../../api/shots';
import { taskApi } from '../../../api/tasks';
import { RequiredImagesPreparation } from './RequiredImagesPreparation';
import { getClipArtifactPresentation, getPreviousAvPresentation } from '../nativeClipPresentation';
import { canPrepareMaterials, clipPreparationPresentation, prepareCurrentRequiredImages } from '../requiredImagePreparation';
import type { Task } from '../../../api/tasks';
import { toast } from '../../../stores/toastStore';
import KeyframesManager from '../../../components/KeyframesManager';
import AudioReferenceSelector from '../../../components/AudioReferenceSelector';
import { ImagePreviewModal } from '../../../components/ImagePreviewModal';
import { ImageEditModal } from '../../../components/ImageEditModal';
import type { KeyframeData } from '../../../types';
import type { CanonicalVisualState, SemanticClipPlan, VideoAiCall, VideoDirectorPlan, VideoMode } from '../../../api/shots';
import { DIALOGUE_GAP_SECONDS, dialogueEmotion, dialogueSpeaker, dialogueText, estimateDialogueSeconds, formatUserFacingError, getClipDialoguesForDisplay, numberOrNull } from '../../../utils';
import { getSemanticClipCounts, getSemanticClipStatus, getSemanticShotStatus, getTemporalTargetLabel, isSemanticShot, type SemanticClipStatus } from '../../../utils/semanticBatch';
import {
  buildVideoDirectorShotSavePayload,
  canUseLegacyShotGeneration,
  classifyVisualStateImageStatus,
  getVisualStateExecutionImageStatus,
  getAdjacentCanonicalTransitions,
  getCanonicalVisualStates,
  getRequiredMissingCanonicalVisualStates,
  isCanonicalVisualPlan,
} from '../videoDirectorAuthority';
import {
  buildSemanticBatchRequest,
  getBatchShotStatusProjection,
  getCanonicalBatchEligibility,
  getCanonicalSemanticReadiness,
  getCurrentSemanticExecutionState,
  getCarryInLabel,
  hasLegacyBatchPlanningState,
  getOwnedVisualStateLabel,
  getSelectableBatchShotIndexes,
  getSemanticCapabilityLabel,
  getSemanticContinuityLabel,
  getSemanticShotStatusFromPlan,
  hasCurrentAssembly,
  hasValidCurrentClipPlan,
  reconcileBatchSelection,
  resolveSemanticClipTask,
  shouldShowLegacyBatchCompatibility,
  type BatchShotCategory,
  type BatchShotFilter,
  type SemanticShotStatus,
} from '../semanticClipAuthority';

const VIDEO_TAB_UI_STORAGE_KEY = 'chapterGenerate_videoTab_ui';
type MergeVideoMode = 'shots_only' | 'shots_with_transitions';
const BATCH_CATEGORY_META: Array<{
  key: BatchShotCategory;
  label: string;
  activeClassName: string;
  countClassName: string;
}> = [
  { key: 'ready', label: '可生成', activeClassName: 'border-green-300 bg-green-50 text-green-800', countClassName: 'bg-green-100 text-green-800' },
  { key: 'generating', label: '生成中', activeClassName: 'border-blue-300 bg-blue-50 text-blue-800', countClassName: 'bg-blue-100 text-blue-800' },
  { key: 'queued', label: '队列中', activeClassName: 'border-purple-300 bg-purple-50 text-purple-800', countClassName: 'bg-purple-100 text-purple-800' },
  { key: 'completed', label: '已完成', activeClassName: 'border-emerald-300 bg-emerald-50 text-emerald-800', countClassName: 'bg-emerald-100 text-emerald-800' },
  { key: 'missing_preparation', label: '缺准备', activeClassName: 'border-amber-300 bg-amber-50 text-amber-800', countClassName: 'bg-amber-100 text-amber-800' },
  { key: 'failed', label: '失败', activeClassName: 'border-red-300 bg-red-50 text-red-800', countClassName: 'bg-red-100 text-red-800' },
];

type VideoImageEditTarget = {
  type: 'shot' | 'keyframe';
  imageUrl: string;
  itemName: string;
  frameIndex?: number;
};

function ClipMetadataDetails({ children, task }: { children: (task?: Task) => React.ReactNode; task?: Task }) {
  const detailsRef = useRef<HTMLDetailsElement | null>(null);
  const summaryRef = useRef<HTMLElement | null>(null);
  const popoverRef = useRef<HTMLDivElement | null>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [taskSnapshot, setTaskSnapshot] = useState<{ source: Task; data: Task } | null>(null);
  const [placement, setPlacement] = useState<{ left: number; top?: number; bottom?: number; maxHeight: number }>({ left: 0, top: 0, maxHeight: 256 });

  useEffect(() => {
    if (!isOpen || !task) return;
    let cancelled = false;
    taskApi.fetch(task.id).then((response) => {
      const data = response.data;
      if (!cancelled && data?.id === task.id
        && data.clipExecution?.clip_plan_revision === task.clipExecution?.clip_plan_revision) {
        setTaskSnapshot({ source: task, data });
      }
    }).catch(() => { if (!cancelled) setTaskSnapshot(null); });
    return () => { cancelled = true; };
  }, [isOpen, task]);

  const updatePlacement = useCallback(() => {
    const summary = summaryRef.current;
    if (!summary) return;
    const rect = summary.getBoundingClientRect();
    if (rect.bottom < 0 || rect.top > window.innerHeight) {
      if (detailsRef.current) detailsRef.current.open = false;
      return;
    }
    const width = Math.min(320, window.innerWidth - 24);
    const left = Math.max(12, Math.min(rect.right - width, window.innerWidth - width - 12));
    const spaceBelow = window.innerHeight - rect.bottom - 12;
    const spaceAbove = rect.top - 12;
    if (spaceBelow < 160 && spaceAbove > spaceBelow) {
      setPlacement({ left, bottom: window.innerHeight - rect.top + 6, maxHeight: Math.min(256, spaceAbove) });
    } else {
      setPlacement({ left, top: rect.bottom + 6, maxHeight: Math.min(256, spaceBelow) });
    }
  }, []);

  useEffect(() => {
    if (!isOpen) return;
    const closeOnOutsideClick = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!detailsRef.current?.contains(target) && !popoverRef.current?.contains(target) && detailsRef.current) {
        detailsRef.current.open = false;
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && detailsRef.current) detailsRef.current.open = false;
    };
    window.addEventListener('resize', updatePlacement);
    window.addEventListener('scroll', updatePlacement, true);
    document.addEventListener('pointerdown', closeOnOutsideClick);
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      window.removeEventListener('resize', updatePlacement);
      window.removeEventListener('scroll', updatePlacement, true);
      document.removeEventListener('pointerdown', closeOnOutsideClick);
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, [isOpen, updatePlacement]);

  return (
    <details ref={detailsRef} className="relative text-[11px] text-gray-500" onToggle={(event) => {
      if (event.currentTarget.open) updatePlacement();
      setIsOpen(event.currentTarget.open);
    }}>
      <summary ref={summaryRef} className="cursor-pointer">详情</summary>
      {isOpen && createPortal(
        <div
          ref={popoverRef}
          role="tooltip"
          className="fixed z-[120] w-80 max-w-[calc(100vw-1.5rem)] overflow-y-auto rounded-md border border-gray-200 bg-white p-3 text-[11px] leading-relaxed text-gray-600 shadow-xl"
          style={placement}
        >
          {children(taskSnapshot?.source === task ? taskSnapshot?.data : task)}
        </div>,
        document.body,
      )}
    </details>
  );
}

function ClipExecutionDetails({ clip, plan, task, previousTask }: { clip: SemanticClipPlan; plan: VideoDirectorPlan; task?: Task; previousTask?: Task }) {
  const metadata = task?.clipExecution;
  const artifact = getClipArtifactPresentation(clip, task);
  const previousClip = plan.clip_plan?.find(item => item.clip_index === clip.previous_clip_index);
  const previous = getPreviousAvPresentation(clip, task, previousClip, previousTask);
  const list = (value: unknown): any[] => Array.isArray(value) ? value.filter(item => item != null) : [];
  const owned = list(clip.visual_state_indexes);
  const selected = list(clip.selected_temporal_target_ids);
  const required = list(plan.required_execution_images).filter(item =>
    list(item.consumer_clip_indexes).includes(Number(clip.clip_index)));
  const readiness = list(plan.clip_execution_readiness).find(item => Number(item.clip_index) === Number(clip.clip_index));
  // Only the backend's final physical manifest owns Picture numbering. State
  // indexes, carry-in and selected targets never fill gaps in this list.
  const references = list(metadata?.video_reference_manifest?.references);
  const anchors = list(metadata?.execution_contract?.temporal_anchor_manifest?.anchors);
  const revision = plan.clip_plan_revision;
  return (
    <div data-testid="clip-execution-details">
      <div>Clip {clip.clip_index ?? '—'} · {clip.start_time ?? '—'}–{clip.end_time ?? '—'}s · Revision {revision ?? '未提供'}</div>
      <div>Continuity：{clip.continuity_to_previous || '未提供'}</div>
      <div>Capability：{clip.capability || '未提供'}</div>
      <div>Owned states：{owned.length ? owned.map(index => `KF${index}`).join('、') : '无'}</div>
      <div>Carry-in：{clip.carry_in_state_index != null ? `KF${clip.carry_in_state_index}（仅承接，非 owned/reference）` : '无'}</div>
      <div>Selected temporal targets：{selected.length ? selected.join('、') : '无'}</div>
      <div>Early Composition Anchor：{clip.early_composition_state_id || '无独立选择（可由合格 timed target 承担）'}</div>
      <div>Required images：{required.length ? required.map(item => `${item.state_id || `KF${item.state_index}`} ${list(item.consumers).some(c => c.kind === 'EARLY_COMPOSITION') ? '早期构图 · ' : ''}${item.ready === true ? '已就绪' : item.missing === true ? '缺失，请准备图片' : '状态未提供'}`).join('、') : '未提供或无'}</div>
      <div>Previous AV dependency：{previous.label}</div>
      {artifact.continuous && <>
        <div>Native continuity output：{artifact.outputStatus}</div>
        <div>Native overlap：{artifact.overlapLabel}</div>
        <div>{artifact.playbackUnavailableReason}</div>
      </>}
      <div>Approval：{metadata?.approval_status || clip.execution_status || '未提供'}</div>
      {task && <div>生成结果：{task.resultUrl ? artifact.resultLabel : '无结果文件'}</div>}
      <details className="mt-1">
        <summary className="cursor-pointer">执行诊断 / URL</summary>
        <div>Readiness：{readiness?.code || '未提供'}</div>
        {previous.debugUrl && <div className="break-all">Previous AV URL：{previous.debugUrl}</div>}
        {task && <div className="break-all">执行 Task {task.id} · {artifact.resultLabel} · {task.resultUrl || '无结果文件'}</div>}
        {metadata?.physical_output?.raw_context_output && <div className="break-all">
          Raw context output（仅诊断）：node {metadata.physical_output.raw_context_output.output_node_id || '未提供'}
          {metadata.physical_output.raw_context_output.result_url || metadata.physical_output.raw_context_output.source_video_url || ''}
        </div>}
      </details>
      <div>Physical reference manifest：{references.length ? '' : '未提供或为空；不从 State 编号推断'}</div>
      {references.map((reference, index) => (
        <div key={index} className="break-all">
          {reference.slot != null ? `Picture ${reference.slot}` : 'Picture 未提供'} · {reference.kind || '类型未提供'}
          {reference.source_keyframe_index != null ? ` · State KF${reference.source_keyframe_index}` : ''}
          {reference.image_url ? ` · ${reference.image_url}` : ' · 图片未提供'}
          {reference.binding?.workflow_node_id ? ` · node ${reference.binding.workflow_node_id}` : ''}
        </div>
      ))}
      <div>Materialized temporal anchors：{anchors.length ? anchors.map(anchor => `${anchor.anchor_id || 'ID 未提供'} · ${anchor.time_seconds ?? '—'}s`).join('、') : '未提供或无'}</div>
      {!revision && <div>历史数据仅供查看，不代表当前执行依据</div>}
    </div>
  );
}

function SemanticClipExecutionPanel({ shot, chapterId, novelId, onPreparationShot, onPreviewClip, onRegenerateClip, onAssemble, onTasksChange, regeneratingClipKey, isShotVideoGenerating, isAssembling }: { shot: any; chapterId?: string; novelId?: string; onPreparationShot: (shot: any) => void; onPreviewClip: (clip: any | null) => void; onRegenerateClip: (clip: any, mode?: 'llm' | 'video_only') => void; onAssemble: () => void; onTasksChange?: (tasks: Task[]) => void; regeneratingClipKey?: string | null; isShotVideoGenerating?: boolean; isAssembling?: boolean }) {
  const plan = (shot?.videoDirectorPlan || {}) as VideoDirectorPlan;
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(false);
  const clips = Array.isArray(plan.clip_plan) ? [...plan.clip_plan].sort((a, b) => Number(a.clip_index) - Number(b.clip_index)) : [];
  const revision = Number(plan.clip_plan_revision || 0);
  const shotStatus = getSemanticShotStatusFromPlan(plan, tasks);
  const currentAssembly = hasCurrentAssembly(plan, tasks);

  useEffect(() => {
    if (!chapterId || !shot?.id || clips.length === 0) {
      setTasks([]);
      return;
    }
    let cancelled = false;
    let requestId = 0;
    const refresh = () => {
      const currentRequest = ++requestId;
      setLoading(true);
      taskApi.fetchShotTasks(chapterId, String(shot.id))
        .then((response) => {
          if (!cancelled && currentRequest === requestId) {
            const nextTasks = Array.isArray(response.data) ? response.data : [];
            setTasks(nextTasks);
            onTasksChange?.(nextTasks);
          }
        })
        .catch(() => {
          if (!cancelled && currentRequest === requestId) {
            setTasks([]);
            onTasksChange?.([]);
          }
        })
        .finally(() => {
          if (!cancelled && currentRequest === requestId) setLoading(false);
        });
    };
    refresh();
    const interval = window.setInterval(refresh, 2000);
    return () => { cancelled = true; window.clearInterval(interval); };
  }, [chapterId, shot?.id, revision, clips.length, onTasksChange]);

  if (clips.length === 0) return null;
  return (
    <div>
      <details data-testid="semantic-clip-debug-metadata" className="mb-2 rounded-md border border-dashed border-gray-200 bg-gray-50 px-2.5 py-1.5 text-[11px] text-gray-500">
        <summary className="cursor-pointer font-medium text-gray-600">片段执行诊断</summary>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <span className="font-medium text-gray-700">Revision {revision}</span>
          <span className="rounded-full border border-blue-200 bg-blue-50 px-2 py-0.5 text-blue-700">{plan.clip_plan_approval_mode || 'AUTO_APPROVE'}</span>
          <span className={`rounded-full border px-2 py-0.5 ${plan.clip_plan_validation?.passed ? 'border-green-200 bg-green-50 text-green-700' : 'border-gray-200 bg-gray-50 text-gray-600'}`}>
            {plan.clip_plan_validation?.passed ? 'PASS' : '未验证'}
          </span>
          {loading && <span>正在读取执行结果…</span>}
        </div>
      </details>
      <div className="space-y-1.5">
        {clips.map((clip: any, index: number) => {
          const task = resolveSemanticClipTask(clip, tasks, revision);
          const metadata = task?.clipExecution;
          const approvalStatus = metadata?.approval_status || clip.execution_status || 'PLANNED';
          const clipStatus = getSemanticClipStatus(clip, tasks, revision);
          const hasCurrentClipArtifact = clipStatus === 'COMPLETED';
          const clipGenerateLabel = hasCurrentClipArtifact ? '重新生成片段' : '生成片段';
          const currentPromptGenerateLabel = hasCurrentClipArtifact ? '使用当前提示词重新生成' : '使用当前提示词生成';
          const clipStatusLabel: Record<SemanticClipStatus, string> = {
            NOT_STARTED: '待生成',
            RUNNING: '生成中',
            WAITING_REVIEW: '待审核',
            FAILED: '失败',
            COMPLETED: '已完成',
          };
          const dialogueAssignment = metadata?.dialogue_assignment || clip.dialogue_assignment;
          const carryInLabel = getCarryInLabel(clip);
          const artifact = getClipArtifactPresentation(clip, task);
          const isContinuation = artifact.continuous;
          const previousClip = clips.find(item => item.clip_index === clip.previous_clip_index);
          const previousTask = previousClip ? resolveSemanticClipTask(previousClip, tasks, revision) : undefined;
          const clipKey = String(clip.clip_index);
          const isRegenerating = regeneratingClipKey === clipKey;
          const preparation = clipPreparationPresentation(shot, Number(clip.clip_index));
          const clipGenerationDisabled = !!isShotVideoGenerating || !!regeneratingClipKey || !preparation.executionReady;
          return (
            <div key={`${revision}-${clip.clip_index}`} className="rounded-lg border border-gray-200 bg-white px-3 py-2 shadow-sm">
              <RequiredImagesPreparation shot={shot} novelId={novelId} chapterId={chapterId} clipIndex={Number(clip.clip_index)} onShot={onPreparationShot} />
              <p className="my-1 text-xs text-gray-600">图片准备：{preparation.imagesReady ? '已就绪' : '未就绪'} · 片段执行：{preparation.label}</p>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                <div className="flex min-w-[116px] items-center gap-2">
                  <span className="text-sm font-semibold text-gray-900">片段 {clip.clip_index}</span>
                  <span className="text-xs tabular-nums text-gray-600">{clip.start_time}–{clip.end_time}s</span>
                </div>
                <span className="rounded-md bg-gray-100 px-2 py-1 text-[11px] font-medium text-gray-700" title={clip.capability}>{getSemanticCapabilityLabel(clip.capability)}</span>
                <span className="rounded-md bg-slate-50 px-2 py-1 text-[11px] text-slate-600">{getSemanticContinuityLabel(clip.continuity_to_previous)}</span>
                <span className="text-[11px] tabular-nums text-gray-600">
                  {Number(clip.planned_duration ?? (Number(clip.end_time) - Number(clip.start_time)))}s{isContinuation && artifact.nativeDuration != null ? ` · Native 累计输出 ${Number(artifact.nativeDuration).toFixed(3).replace(/\.000$/, '')}s` : !isContinuation && metadata?.actual_duration != null ? ` · 实际 ${metadata.actual_duration}s` : ''}
                </span>
                <span className={`text-[10px] font-medium ${clipStatus === 'COMPLETED' ? 'text-green-700' : clipStatus === 'FAILED' ? 'text-red-700' : clipStatus === 'RUNNING' ? 'text-blue-700' : 'text-gray-500'}`}>{clipStatusLabel[clipStatus]}</span>
                {carryInLabel && (
                  <span className="rounded-full border border-indigo-200 bg-indigo-50 px-2 py-0.5 text-[10px] font-medium text-indigo-700">
                    {carryInLabel}
                  </span>
                )}
                <span className="text-[11px] text-gray-600">视觉状态：{getOwnedVisualStateLabel(clip).replace(/KF/g, '')}</span>
                <div className="ml-auto flex items-center gap-2">
                  {artifact.playbackUrl && (
                    <button type="button" onClick={() => onPreviewClip({ ...clip, clip_index: clip.clip_index, video_url: artifact.playbackUrl })} className="rounded-md border border-blue-200 px-2.5 py-1 text-[11px] font-medium text-blue-700 hover:bg-blue-50">
                      播放片段 {clip.clip_index}
                    </button>
                  )}
                  {isContinuation && <button type="button" disabled title={artifact.playbackUnavailableReason} className="rounded-md border border-gray-200 px-2.5 py-1 text-[11px] text-gray-500">
                    独立预览暂不可用
                  </button>}
                  <div className="relative inline-flex">
                    <button
                      type="button"
                      onClick={() => onRegenerateClip({ ...clip, clip_index: clip.clip_index }, 'llm')}
                      disabled={clipGenerationDisabled}
                      className="inline-flex items-center gap-1 rounded-l-md border border-blue-200 px-2.5 py-1 text-[11px] font-medium text-blue-700 hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {isRegenerating && <Loader2 className="h-3 w-3 animate-spin" />}
                      {isRegenerating ? '生成中...' : clipGenerateLabel}
                    </button>
                    <button
                      type="button"
                      onClick={() => onRegenerateClip({ ...clip, clip_index: clip.clip_index }, 'video_only')}
                      disabled={clipGenerationDisabled || !clip.prompt_text}
                      title={!clip.prompt_text ? '缺少可复用的片段提示词，请先生成片段' : undefined}
                      className="rounded-r-md border border-l-0 border-blue-200 px-2.5 py-1 text-[11px] font-medium text-blue-700 hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {currentPromptGenerateLabel}
                    </button>
                  </div>
                  <ClipMetadataDetails task={task}>
                    {(detailTask) => <ClipExecutionDetails clip={clip} plan={plan} task={detailTask} previousTask={previousTask} />}
                  </ClipMetadataDetails>
                </div>
              </div>
              {Array.isArray(dialogueAssignment) && dialogueAssignment.length > 0 && (
                <details className="mt-1.5 border-t border-gray-100 pt-1.5 text-[10px] text-gray-600">
                  <summary className="cursor-pointer">对白分配 · {dialogueAssignment.length} 段</summary>
                  <div className="mt-1 grid gap-1 sm:grid-cols-2">
                    {dialogueAssignment.map((span: any, spanIndex: number) => (
                      <div key={`${span.dialogue_id}-${span.segment_index}-${spanIndex}`} className="rounded bg-gray-50 px-2 py-1">
                        <span className="font-medium text-gray-700">{span.dialogue_id}{span.segment_index > 1 ? `.part${span.segment_index}` : ''} · {span.speaker}:</span> {span.text}
                      </div>
                    ))}
                  </div>
                </details>
              )}
            </div>
          );
        })}
      </div>
      {shotStatus === 'CLIPS_COMPLETE' && (
        <button type="button" onClick={onAssemble} disabled={isAssembling || !!isShotVideoGenerating} className="mt-2 rounded-md border border-green-200 bg-green-50 px-3 py-1.5 text-xs font-medium text-green-700 hover:bg-green-100 disabled:cursor-not-allowed disabled:opacity-50">
          {isAssembling ? '正在合并最终视频...' : '合并最终视频'}
        </button>
      )}
      {currentAssembly && (
        <button type="button" onClick={() => onPreviewClip(null)} className="mt-2 rounded-md border border-gray-200 bg-gray-50 px-2.5 py-1 text-[11px] font-medium text-gray-700 hover:bg-gray-100">
          播放最终 Shot
        </button>
      )}
      {plan.clip_plan_validation?.dialogue_ownership && (
        <div className={`mt-3 rounded border px-2.5 py-2 text-[11px] ${plan.clip_plan_validation.dialogue_ownership.passed ? 'border-green-200 bg-green-50 text-green-900' : 'border-red-200 bg-red-50 text-red-900'}`}>
          Dialogue text allocation: {plan.clip_plan_validation.dialogue_ownership.passed ? 'PASS' : 'FAILED'}
        </div>
      )}
    </div>
  );
}

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

const getLatestH3FinalPrompt = (plan: VideoDirectorPlan, clipIndex?: number) => {
  const call = [...(plan.ai_calls || [])].reverse().find((item) => {
    if (!['11', '12', '13'].includes(String(item?.step || ''))) return false;
    if (!String(item?.final_prompt || '').trim()) return false;
    return clipIndex === undefined || Number(item?.clip_index) === clipIndex;
  });
  return String(call?.final_prompt || '');
};

const getKeyframeReferenceImages = (plan: VideoDirectorPlan, keyframeIndex?: number) => {
  if (keyframeIndex === undefined) return [];
  const keyframeLabel = new RegExp(`KF\\s*${keyframeIndex}\\b`);
  const call = [...(plan.ai_calls || [])].reverse().find((item) => (
    ['temporal_reference_selector', 'keyframe_image_prompt'].includes(String(item?.task_type || ''))
    && keyframeLabel.test(String(item?.input_summary || ''))
    && Array.isArray(item?.reference_images)
    && item.reference_images.length > 0
  ));
  return (call?.reference_images || []).filter((image: any) => image?.url);
};

const getReferenceDisplayName = (reference: any) => {
  if (reference?.source === 'current_resource') return `${reference.label || '资源图'}（当前资源补充预览）`;
  const sources = Array.isArray(reference?.sources) ? reference.sources.map(String) : [];
  const source = String(sources[0] || reference?.label || '');
  const kind = String(reference?.kind || reference?.type || '');
  const names = (prefix: string) => sources
    .filter((item: string) => item.startsWith(prefix))
    .map((item: string) => item.slice(prefix.length))
    .filter(Boolean)
    .join('、');
  if (kind === 'SCENE') return `场景：${names('SCENE:') || source.replace(/^SCENE:/, '') || '未命名'}`;
  if (kind === 'CHARACTER_IDENTITY') return `角色：${names('CHAR:') || source.replace(/^CHAR:/, '') || '未命名'}`;
  if (kind === 'DIRECTOR_VISUAL_ANCHOR') return source === 'SHOT_IMAGE' ? '主分镜图' : `视觉锚点：${source || '未命名'}`;
  if (kind === 'TEMPORAL_ANCHOR') return `时间锚点：${source}`;
  if (kind === 'PROP') return `道具：${names('PROP:') || source.replace(/^PROP:/, '') || '未命名'}`;
  return String(reference?.label || source || '参考图');
};

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

const parseAiCallTimestamp = (value?: string | null) => {
  if (!value) return null;
  const normalized = value.trim().replace(' ', 'T');
  const timezoneAware = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(normalized);
  const date = new Date(timezoneAware ? normalized : `${normalized}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
};

const formatAiCallTimestamp = (value: string | null | undefined, language: string, timezone: string) => {
  const date = parseAiCallTimestamp(value);
  if (!date) return '-';
  try {
    return date.toLocaleString(language, { timeZone: timezone });
  } catch {
    return date.toLocaleString(language);
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
  const { t, i18n } = useTranslation();
  const [panelOpen, setPanelOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [openIndex, setOpenIndex] = useState(Math.max(0, calls.length - 1));
  const [viewingData, setViewingData] = useState<{ title: string; content: string } | null>(null);
  const [isDownloading, setIsDownloading] = useState(false);
  const sortedCalls = [...calls].sort((a, b) => {
    const aTime = parseAiCallTimestamp(a.created_at)?.getTime() || 0;
    const bTime = parseAiCallTimestamp(b.created_at)?.getTime() || 0;
    return aTime - bTime;
  });
  const latest = sortedCalls[sortedCalls.length - 1];
  const failedCallCount = calls.filter((call) => ['failed', 'error'].includes(String(call.status || '').toLowerCase())).length;

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

  useEffect(() => {
    setPanelOpen(false);
    setExpanded(false);
    setViewingData(null);
  }, [shotId]);

  if (!calls.length) {
    return (
      <div data-testid="debug-inspector" className="rounded-lg border border-dashed border-gray-200 bg-gray-50">
        <div className="flex items-center justify-between px-3 py-2">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-gray-800">
              调试检查器
              <span className="rounded-full bg-gray-200 px-1.5 py-0.5 text-[10px] font-medium text-gray-600">0</span>
              <button
                type="button"
                onClick={handleDownloadLlmData}
                disabled={isDownloading}
                className="inline-flex items-center gap-1 rounded border border-gray-200 bg-white px-2 py-0.5 text-xs font-normal text-gray-700 hover:bg-gray-100 disabled:opacity-50"
              >
                <Download className="h-3 w-3" />{isDownloading ? t('chapterGenerate.downloading') : '导出调试数据'}
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
    <div data-testid="debug-inspector" className={`flex min-h-0 flex-col rounded-lg border border-gray-200 bg-gray-50 ${panelOpen ? 'flex-1' : 'flex-none'}`}>
      <div className={`flex items-center justify-between px-3 py-2 ${panelOpen ? 'border-b border-gray-200' : ''}`}>
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-gray-800">
            调试检查器
            <span className="rounded-full bg-gray-200 px-1.5 py-0.5 text-[10px] font-medium text-gray-600">{calls.length}</span>
            {failedCallCount > 0 && (
              <span className="rounded-full bg-red-100 px-1.5 py-0.5 text-[10px] font-medium text-red-700">{failedCallCount} 个失败</span>
            )}
            <button
              type="button"
              onClick={handleDownloadLlmData}
              disabled={isDownloading}
              className="inline-flex items-center gap-1 rounded border border-gray-200 bg-white px-2 py-0.5 text-xs font-normal text-gray-700 hover:bg-gray-100 disabled:opacity-50"
            >
              <Download className="h-3 w-3" />{isDownloading ? t('chapterGenerate.downloading') : '导出调试数据'}
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
                    {call.prompt_template_name || '-'} · {call.status || '-'} · {formatAiCallTimestamp(call.created_at, i18n.language, i18n.timezone)}
                    {call.clip_index ? ` · Clip ${call.clip_index}` : ''}
                  </div>
                </div>
                <ChevronDown className={`w-4 h-4 text-gray-400 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
              </button>
              {isOpen && (
                <div className="px-3 pb-3">
                  {call.input_summary && <div className="text-xs text-gray-500">{call.input_summary}</div>}
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
                   {call.parsed_result !== undefined && call.parsed_result !== null && (
                     <div className="min-w-0">
                       <div className="flex items-center justify-between mb-1">
                         <span className="text-xs font-medium text-gray-600">解析结果</span>
                         <button type="button" onClick={() => copyText(formatAiCallValue(call.parsed_result))} className="text-blue-600 hover:text-blue-800" title={t('common.copy')}><Copy className="w-3 h-3" /></button>
                       </div>
                       <pre className="max-h-40 overflow-auto rounded bg-gray-900 p-2 text-xs text-gray-100 whitespace-pre-wrap">{formatAiCallValue(call.parsed_result)}</pre>
                     </div>
                   )}
                   {call.submitted_reference_bindings?.length ? (
                     <div className="min-w-0">
                       <div className="mb-1 text-xs font-medium text-gray-600">实际参考图绑定</div>
                       <pre className="max-h-40 overflow-auto rounded bg-gray-900 p-2 text-xs text-gray-100 whitespace-pre-wrap">{formatAiCallValue(call.submitted_reference_bindings)}</pre>
                     </div>
                   ) : null}
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
    {viewingData && createPortal((
      <div className="fixed inset-0 z-[300] flex items-center justify-center bg-black/50 p-4" onClick={() => setViewingData(null)}>
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
    ), document.body)}
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
  selectedMode?: VideoMode;
  isSaving: boolean;
  onChange: (key: string, prompt: string) => void;
  onClose: () => void;
  onSave: () => void;
}) {
  if (!isOpen) return null;

  const hasDrafts = drafts.length > 0;

  return createPortal((
    <div className="fixed inset-0 z-[300] flex items-center justify-center bg-black/50 px-4">
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
  ), document.body);
}

interface VideoDirectorPanelProps {
  shot: any;
  shotImageUrl?: string | null;
  plan: VideoDirectorPlan;
  isRecommending: boolean;
  isPlanningKeyframes: boolean;
  isPlanningClips: boolean;
  onRecommend: (force?: boolean) => void;
  onPlanKeyframes: (force?: boolean) => void;
  onPlanClips: (force?: boolean) => void;
  onGenerateMissingKeyframes: () => void;
  onGenerateKeyframe: (frameIndex: number, mode?: 'llm' | 'image_only') => void;
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
  semanticClipPlan?: any[];
  semanticClipPlanShot?: any;
  semanticShotStatus?: SemanticShotStatus;
  onSemanticClipTasksChange?: (tasks: Task[]) => void;
  chapterId?: string;
  novelId?: string;
  onPreparationShot: (shot: any) => void;
}

function VideoDirectorPanel({
  shot,
  shotImageUrl,
  plan,
  isRecommending,
  isPlanningKeyframes,
  isPlanningClips,
  onRecommend,
  onPlanKeyframes,
  onPlanClips,
  onGenerateMissingKeyframes,
  onGenerateKeyframe,
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
  semanticClipPlan,
  semanticClipPlanShot,
  semanticShotStatus = 'NOT_STARTED',
  onSemanticClipTasksChange,
  chapterId,
  novelId,
  onPreparationShot,
}: VideoDirectorPanelProps) {
  const { t } = useTranslation();
  const { referenceImages: shotReferenceImages, referenceImagesLoading: shotReferenceImagesLoading } = useShotReferenceImages(shot, !!shotImageUrl);
  const [showEndKeyframeMenu, setShowEndKeyframeMenu] = useState(false);
  const [showSelectedKeyframeMenu, setShowSelectedKeyframeMenu] = useState(false);
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
      setShowSelectedKeyframeMenu(false);
    }
  }, [isShotVideoGenerating]);
  const isCanonicalPlan = isCanonicalVisualPlan(plan);
  const isHistoricalPlan = !isCanonicalPlan && hasLegacyBatchPlanningState(plan);
  const selectedMode = plan.selected_mode || plan.recommended_mode || 'SINGLE_FRAME';
  const maxClipDuration = plan.workflow_capability?.max_clip_duration || 15;
  const firstLastAvailable = plan.first_last_available ?? ((shot?.duration || 0) <= maxClipDuration);
  const keyframes = isCanonicalPlan ? getCanonicalVisualStates(plan) : (plan.keyframes || []);
  const clips = isCanonicalPlan ? [] : selectedMode === 'MULTI_KEYFRAME' ? (plan.window_plans || []) : (plan.clips || []);
  const hasSemanticClipPlan = Array.isArray(semanticClipPlan) && semanticClipPlan.length > 0;
  const semanticPlanUsesKeyframes = hasSemanticClipPlan && semanticClipPlan.some((clip: any) => (
    Array.isArray(clip?.keyframe_indexes) && clip.keyframe_indexes.length > 0
  ));
  // A legacy MULTI_KEYFRAME recommendation can coexist with a semantic plan
  // compiled to SINGLE_FRAME/continuation. In that case its KF timeline is no
  // longer an execution input and must not be presented as missing work.
  const showKeyframeExecutionTimeline = isCanonicalPlan || (
    selectedMode === 'MULTI_KEYFRAME' && (!hasSemanticClipPlan || semanticPlanUsesKeyframes)
  );
  const hasWindowPlans = !isCanonicalPlan && selectedMode === 'MULTI_KEYFRAME' && clips.length > 0;
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
    if (isCanonicalPlan) {
      const required = plan.required_execution_images?.find(item => item.state_index === Number(kf.index));
      if (required) return !!required.active_task && !required.ready;
      const legacy = legacyKeyframes.find((frame: any) => Number(frame.plan_keyframe_index) === Number(kf.index));
      return keyframeTasks.some((task: any) => task.taskId === legacy?.image_task_id
        && task.canonicalImageProvenance?.clip_plan_revision === plan.clip_plan_revision
        && ['pending', 'queued', 'processing', 'running'].includes(task.status));
    }
    if (generatingKeyframes.has(`${shotId}-${frameIndex}`)) return true;
    return keyframeTasks.some((task: any) => (
      task.shotId === shotId
      && Number(task.frameIndex) === Number(frameIndex)
      && ['pending', 'running'].includes(String(task.status))
    ));
  };
  const requiredMissingKeyframes = isCanonicalPlan
    ? getRequiredMissingCanonicalVisualStates(plan, getKeyframeImageUrl)
    : [];
  const canonicalSemanticReadiness = getCanonicalSemanticReadiness(plan, getKeyframeImageUrl);
  const showSemanticClipPlan = hasSemanticClipPlan;
  const optionalMissingKeyframes = isCanonicalPlan
    ? keyframes.filter((kf: any) => getVisualStateExecutionImageStatus(kf, plan, getKeyframeImageUrl(kf)) === 'OPTIONAL_MISSING')
    : [];
  const missingKeyframes = showKeyframeExecutionTimeline
    ? isCanonicalPlan
      ? requiredMissingKeyframes
      : keyframes.filter((kf: any) => kf.role !== 'START' && !getKeyframeImageUrl(kf))
    : [];
  const activeMissingKeyframes = missingKeyframes.filter((kf: any) => isKeyframeGenerating(kf));
  const hasGeneratingMissingKeyframes = missingKeyframes.some((kf: any) => isKeyframeGenerating(kf));
  const missingKeyframeButtonLabel = hasGeneratingMissingKeyframes
    ? `${isCanonicalPlan ? '状态图片' : '关键帧'}任务中 ${activeMissingKeyframes.length}/${missingKeyframes.length}`
    : `${isCanonicalPlan ? requiredMissingKeyframes.length > 0 ? '批量生成必需状态图片' : '批量生成可选状态图' : '生成缺失关键帧'}${missingKeyframes.length > 0 ? ` ${missingKeyframes.length}` : ''}`;
  const threeFrameClipCount = clips.filter((clip: any) => Number(clip.selected_frame_count || clip.frame_count) === 3).length;
  const fourFrameClipCount = clips.filter((clip: any) => Number(clip.selected_frame_count || clip.frame_count) === 4).length;
  const [selectedKeyframeIndex, setSelectedKeyframeIndex] = useState(0);
  const [selectedClipKey, setSelectedClipKey] = useState<string | null>(null);
  const [isEndDescriptionExpanded, setIsEndDescriptionExpanded] = useState(false);
  const [isAdvancedDirectorOpen, setIsAdvancedDirectorOpen] = useState(false);
  const [viewingPromptClip, setViewingPromptClip] = useState<any | null>(null);
  const [hoveredReferenceImage, setHoveredReferenceImage] = useState<any | null>(null);
  const selectedKeyframe = keyframes[selectedKeyframeIndex] || keyframes[0];
  const selectedKeyframeFrameIndex = getKeyframeFrameIndex(selectedKeyframe);
  const selectedKeyframeImageUrl = getKeyframeImageUrl(selectedKeyframe);
  const selectedStateImageStatus = isCanonicalPlan && selectedKeyframe
    ? getVisualStateExecutionImageStatus(selectedKeyframe, plan, selectedKeyframeImageUrl) : null;
  const selectedKeyframeReferenceImages = selectedKeyframe?.role === 'START'
    ? shotReferenceImages
    : getKeyframeReferenceImages(plan, Number(selectedKeyframe?.index));
  const selectedReferenceImagesLoading = selectedKeyframe?.role === 'START' && shotReferenceImagesLoading;
  useEffect(() => { setHoveredReferenceImage(null); }, [shot, plan, selectedKeyframe?.index]);
  const selectedKeyframeIsGenerating = isKeyframeGenerating(selectedKeyframe);
  const selectedLegacyKeyframe = legacyKeyframes.find((item: any) => (
    Number(item.plan_keyframe_index ?? item.planKeyframeIndex) === Number(selectedKeyframe?.index)
  ));
  const hasReusableSelectedKeyframePrompt = !!String(
    selectedKeyframe?.prompt_text || selectedLegacyKeyframe?.prompt_text || ''
  ).trim();
  const selectedKeyframePrimaryActionLabel = isCanonicalPlan
    ? selectedStateImageStatus === 'REQUIRED_MISSING' ? '生成必需状态图片' : selectedKeyframeImageUrl ? '重新生成状态图片' : '生成可选状态图'
    : selectedKeyframeImageUrl ? 'LLM+重新生成关键帧' : 'LLM+生成关键帧';
  const selectedKeyframeCurrentPromptActionLabel = isCanonicalPlan
    ? selectedStateImageStatus === 'REQUIRED_MISSING' ? '使用当前提示词生成必需状态图片' : selectedKeyframeImageUrl ? '使用当前提示词重新生成状态图片' : '使用当前提示词生成可选状态图'
    : selectedKeyframeImageUrl ? '仅重新生成关键帧' : '仅生成关键帧';
  const hasNextKeyframe = selectedKeyframeIndex < keyframes.length - 1;
  const transitions = plan.transitions || [];
  const canonicalAdjacentTransitions = getAdjacentCanonicalTransitions(plan, Number(selectedKeyframe?.index));
  const previousTransition = isCanonicalPlan ? canonicalAdjacentTransitions.previous : transitions.find((transition) => (
    Number(transition.to_keyframe_index) === Number(selectedKeyframe?.index)
  ));
  const nextTransition = isCanonicalPlan ? canonicalAdjacentTransitions.next : transitions.find((transition) => (
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
  const semanticExecutionSummary = !hasSemanticClipPlan
    ? '视频执行 · 尚未规划'
    : isShotVideoGenerating
      ? `视频执行 · ${semanticClipPlan.length} 个片段 · 生成中`
      : semanticShotStatus === 'FAILED'
        ? '视频执行 · 有片段失败'
        : semanticShotStatus === 'WAITING_REVIEW'
          ? `视频执行 · ${semanticClipPlan.length} 个片段 · 待审核`
          : semanticShotStatus === 'CLIPS_COMPLETE' || semanticShotStatus === 'ASSEMBLED'
            ? `视频执行 · ${semanticClipPlan.length} 个片段 · 已完成`
            : semanticShotStatus === 'PARTIAL'
              ? `视频执行 · ${semanticClipPlan.length} 个片段 · 部分完成`
              : `视频执行 · ${semanticClipPlan.length} 个片段 · 待生成`;

  useEffect(() => {
    if (!showEndKeyframeMenu) return;
    const handleClick = () => setShowEndKeyframeMenu(false);
    window.addEventListener('click', handleClick);
    return () => window.removeEventListener('click', handleClick);
  }, [showEndKeyframeMenu]);

  useEffect(() => {
    if (!showSelectedKeyframeMenu) return;
    const handleClick = () => setShowSelectedKeyframeMenu(false);
    window.addEventListener('click', handleClick);
    return () => window.removeEventListener('click', handleClick);
  }, [showSelectedKeyframeMenu]);

  useEffect(() => {
    setSelectedKeyframeIndex(0);
    setSelectedClipKey(null);
    setIsEndDescriptionExpanded(false);
    setIsAdvancedDirectorOpen(false);
    setShowSelectedKeyframeMenu(false);
  }, [shot?.id, selectedMode]);

  useEffect(() => {
    if (selectedKeyframeIndex >= keyframes.length) setSelectedKeyframeIndex(0);
  }, [keyframes.length, selectedKeyframeIndex]);

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
    switch ((status || 'PENDING').toUpperCase()) {
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
      default: return t('tasks.clipStatuses.pending');
    }
  };
  const getVisualStateRoleLabel = (role?: string) => {
    if (role === 'START') return t('chapterGenerate.visualStateRoleStart');
    if (role === 'END') return t('chapterGenerate.visualStateRoleEnd');
    return t('chapterGenerate.visualStateRoleIntermediate');
  };
  const getVisualStateImageStatusLabel = (keyframe: any) => {
    const status = getVisualStateExecutionImageStatus(keyframe, plan, getKeyframeImageUrl(keyframe));
    if (status === 'READY') return t('chapterGenerate.visualStateReady');
    if (status === 'REQUIRED_MISSING') return t('chapterGenerate.visualStateRequiredMissing');
    if (status === 'NOT_NEEDED') return t('chapterGenerate.stateImageNotNeeded', { defaultValue: '当前执行无需状态图' });
    return t('chapterGenerate.visualStateOptionalMissing');
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

  if (isHistoricalPlan) {
    const historicalMode = plan.selected_mode || plan.recommended_mode;
    const historicalKeyframes = Array.isArray(plan.keyframes) ? plan.keyframes : [];
    const historicalWindows = Array.isArray(plan.window_plans) ? plan.window_plans : [];
    const historicalRecommendation = (plan.ai_calls || []).find((call: any) => String(call?.step) === '07');
    return (
      <section
        data-testid="historical-video-plan-boundary"
        className="flex-shrink-0 rounded-lg border border-amber-200 bg-amber-50 p-5"
      >
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="max-w-2xl">
            <div className="flex items-center gap-2 text-sm font-semibold text-amber-950">
              <Info className="h-4 w-4" />
              旧版视频规划
            </div>
            <p className="mt-2 text-sm leading-6 text-amber-900">
              此分镜使用旧版视频规划格式。当前视频生成使用新版任意数量视觉状态规划；请重新规划后继续制作。
            </p>
          </div>
          <button
            type="button"
            data-testid="canonical-replan-cta"
            onClick={() => onPlanKeyframes(true)}
            disabled={isPlanningKeyframes || !!isShotVideoGenerating}
            className="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg bg-amber-700 px-4 py-2 text-sm font-medium text-white hover:bg-amber-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isPlanningKeyframes ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            {isPlanningKeyframes ? '正在使用新版规划…' : '使用新版规划重新规划'}
          </button>
        </div>

        <details data-testid="historical-plan-details" className="mt-4 border-t border-amber-200 pt-3">
          <summary className="cursor-pointer text-sm font-medium text-amber-900">查看旧版规划详情</summary>
          <div className="mt-3 grid gap-2 text-xs text-amber-950 sm:grid-cols-2">
            <div className="rounded-md border border-amber-200 bg-white/70 px-3 py-2">旧版模式：{historicalMode || '未记录'}</div>
            <div className="rounded-md border border-amber-200 bg-white/70 px-3 py-2">分镜时长：{Number(shot?.duration || 0)}s</div>
            <div className="rounded-md border border-amber-200 bg-white/70 px-3 py-2">旧版关键帧：{historicalKeyframes.length}</div>
            <div className="rounded-md border border-amber-200 bg-white/70 px-3 py-2">旧版窗口计划：{historicalWindows.length}</div>
            {plan.recommended_mode && (
              <div className="rounded-md border border-amber-200 bg-white/70 px-3 py-2">历史推荐值：{plan.recommended_mode}</div>
            )}
            {historicalRecommendation && (
              <div className="rounded-md border border-amber-200 bg-white/70 px-3 py-2">历史 #07 记录：{historicalRecommendation.status || '已记录'}</div>
            )}
            {(plan.recommendation_reason || plan.notice) && (
              <div className="rounded-md border border-amber-200 bg-white/70 px-3 py-2 sm:col-span-2">
                历史说明：{plan.recommendation_reason || plan.notice}
              </div>
            )}
          </div>
          <p className="mt-3 text-xs text-amber-800">以上信息仅供查阅，不能在此选择、保存或执行旧版规划。</p>
        </details>
      </section>
    );
  }

  if (!isCanonicalPlan) {
    return (
      <section
        data-testid="missing-video-plan-state"
        className="flex-shrink-0 rounded-lg border border-blue-200 bg-blue-50 p-5"
      >
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-blue-950">
              <Sparkles className="h-4 w-4" />
              新版视频规划
            </div>
            <p className="mt-2 text-sm leading-6 text-blue-900">此分镜尚未规划视觉时间轴。创建任意数量视觉状态后，即可继续图片与视频制作。</p>
          </div>
          <button
            type="button"
            data-testid="initial-canonical-plan-cta"
            onClick={() => onPlanKeyframes(false)}
            disabled={isPlanningKeyframes || !!isShotVideoGenerating}
            className="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isPlanningKeyframes ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            {isPlanningKeyframes ? '正在规划视觉时间轴…' : '规划视觉时间轴'}
          </button>
        </div>
      </section>
    );
  }

  return (
    <>
    <div className="flex-shrink-0 border border-gray-200 rounded-lg p-4 space-y-4 bg-white">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-gray-800 flex items-center gap-2 min-w-0">
            <Sparkles className="w-4 h-4 text-blue-600" />
            视频导演
            <span className="truncate text-xs font-normal text-gray-500">
              {isCanonicalPlan
                ? `${t('chapterGenerate.visualTimeline')} · ${keyframes.length} ${t('chapterGenerate.visualStates')}`
                : `AI推荐：${isRecommending ? '推荐中...' : getVideoModeLabel(plan.recommended_mode)}${plan.recommendation_reason ? ` · ${plan.recommendation_reason}` : ''}`}
            </span>
          </h3>
        </div>
        <div className="flex items-center gap-2">
          {!isCanonicalPlan && <button
            type="button"
            onClick={onOpenPromptModal}
            className="px-3 py-1.5 rounded-lg border border-blue-200 bg-blue-50 text-sm text-blue-700 hover:bg-blue-100 transition-colors flex items-center gap-1.5 whitespace-nowrap"
          >
            <Copy className="w-4 h-4" />
            AI提示词
          </button>}
          {!isCanonicalPlan && <button
            type="button"
            onClick={() => onRecommend(true)}
            disabled={isRecommending || !!isShotVideoGenerating}
            title={isShotVideoGenerating ? '当前 Shot 视频生成中，请等待完成后再重新推荐' : undefined}
            className="px-3 py-1.5 rounded-lg border border-gray-200 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50 transition-colors flex items-center gap-1.5 whitespace-nowrap"
          >
            <RefreshCw className={`w-4 h-4 ${isRecommending ? 'animate-spin' : ''}`} />
            重新推荐视频生成模式
          </button>}
        </div>
      </div>

      {!isCanonicalPlan && (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
          <div>
            <div className="text-sm font-medium text-amber-900">{t('chapterGenerate.historicalVideoPlan')}</div>
            <div className="text-xs text-amber-800">{t('chapterGenerate.historicalVideoPlanHint')}</div>
          </div>
          <button
            type="button"
            onClick={() => onPlanKeyframes(true)}
            disabled={isPlanningKeyframes || !!isShotVideoGenerating}
            className="shrink-0 rounded-md border border-amber-300 bg-white px-3 py-1.5 text-xs font-medium text-amber-900 hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isPlanningKeyframes ? t('chapterGenerate.planningVisualTimeline') : t('chapterGenerate.replanVisualTimeline')}
          </button>
        </div>
      )}

      {!isCanonicalPlan && plan.notice && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {plan.notice}
        </div>
      )}

      {!isCanonicalPlan && <div className="flex gap-2">
        {renderModeButton('SINGLE_FRAME')}
        {renderModeButton('FIRST_LAST_FRAME', !firstLastAvailable, `当前 Workflow 单次最大 ${maxClipDuration}s，本 Shot ${shot?.duration || 0}s`)}
        {renderModeButton('MULTI_KEYFRAME')}
      </div>}

      {showKeyframeExecutionTimeline && (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-blue-100 bg-blue-50 px-3 py-2">
          <div className="text-xs text-blue-700">
            {isCanonicalPlan
              ? `${t('chapterGenerate.visualTimelineHint')}${optionalMissingKeyframes.length > 0 ? ` · ${t('chapterGenerate.optionalMissingStates', { count: optionalMissingKeyframes.length })}` : ''}`
              : '#08 只规划关键帧时间轴和 3/4 帧 window_plans；关键帧图片需在规划后单独生成。'}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                if (!isCanonicalPlan || keyframes.length === 0 || window.confirm(t('chapterGenerate.replanVisualTimelineConfirm'))) {
                  onPlanKeyframes(true);
                }
              }}
              disabled={isPlanningKeyframes || !!isShotVideoGenerating}
              title={isShotVideoGenerating ? '当前 Shot 视频生成中，请等待完成后再重新规划关键帧' : undefined}
              className="px-3 py-1.5 rounded-lg border border-blue-200 bg-white text-sm text-blue-700 hover:bg-blue-50 disabled:opacity-50 transition-colors whitespace-nowrap"
            >
              {isPlanningKeyframes
                ? t('chapterGenerate.planningVisualTimeline')
                : isCanonicalPlan
                  ? keyframes.length > 0 ? t('chapterGenerate.replanVisualTimeline') : t('chapterGenerate.planVisualTimeline')
                  : hasWindowPlans ? '重新规划关键帧' : 'AI规划关键帧'}
            </button>
              <button
                type="button"
                onClick={onGenerateMissingKeyframes}
              disabled={isPlanningKeyframes || isGeneratingMissingKeyframes || (!isCanonicalPlan && hasGeneratingMissingKeyframes) || (!isCanonicalPlan && !hasWindowPlans) || missingKeyframes.length === 0 || !!isShotVideoGenerating}
              className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm transition-colors whitespace-nowrap disabled:cursor-not-allowed disabled:opacity-50 ${isCanonicalPlan ? 'border-gray-300 bg-white text-gray-700 hover:bg-gray-50' : 'border-blue-600 bg-blue-600 text-white hover:bg-blue-700'}`}
                title={isShotVideoGenerating
                  ? '当前 Shot 视频生成中，请等待完成后再生成关键帧'
                  : isCanonicalPlan
                    ? '只准备当前 Clip 计划的执行必需图片；已有图片复用，活跃任务等待，其余缺失图片继续提交。'
                    : !hasWindowPlans
                      ? '请先完成 #08 关键帧规划'
                      : missingKeyframes.length === 0
                        ? t('chapterGenerate.noRequiredMissingVisualStates')
                        : ''}
              >
              {(isGeneratingMissingKeyframes || hasGeneratingMissingKeyframes) && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              {isGeneratingMissingKeyframes ? '正在提交关键帧任务...' : missingKeyframeButtonLabel}
              </button>
          </div>
        </div>
      )}

      {!isCanonicalPlan && selectedMode === 'SINGLE_FRAME' && (
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

      {!isCanonicalPlan && selectedMode === 'FIRST_LAST_FRAME' && (
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

      {showKeyframeExecutionTimeline && (
        <div className="space-y-4">
          <div>
            <div className="flex items-center justify-between mb-2">
              <div>
                <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                  <span className="text-sm font-semibold text-gray-700">{isCanonicalPlan ? t('chapterGenerate.visualTimeline') : t('chapterGenerate.keyframeTimeline')}</span>
                  <span className="text-xs font-normal text-gray-500">
                    {isCanonicalPlan
                      ? t('chapterGenerate.visualTimelineSummary', { states: keyframes.length, transitions: transitions.length })
                      : t('chapterGenerate.keyframeTimelineSummary', { keyframes: keyframes.length, transitions: Math.max(0, keyframes.length - 1), clips: clips.length, maxClipDuration })}
                  </span>
                </div>
              </div>
            </div>
            <div className="rounded-lg border border-gray-200 bg-white px-3 py-2">
              {!isCanonicalPlan && clips.length > 0 && (
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
              {keyframes.length === 0 && isCanonicalPlan && (
                <div className="rounded-md border border-dashed border-gray-200 bg-gray-50 px-3 py-6 text-center text-sm text-gray-500">
                  {t('chapterGenerate.visualTimelineNotPlanned')}
                </div>
              )}
              <div className="flex items-stretch gap-2 overflow-x-auto pb-1">
                {keyframes.map((kf, idx) => {
                  const isCurrentKeyframe = selectedKeyframeIndex === idx;
                  const isInSelectedClip = selectedClipKeyframes.has(Number(kf.index));
                  const keyframeClipCount = clips.filter((clip: any) => clipContainsKeyframe(clip, Number(kf.index))).length;
                  const keyframeImageUrl = getKeyframeImageUrl(kf);
                  const hasImage = !!keyframeImageUrl;
                  const isGenerating = isKeyframeGenerating(kf);
                  const marker = keyframeClipCount > 1 ? '⇄' : kf.role === 'START' || kf.role === 'END' ? '★' : '◇';
                  const canonicalImageStatus = isCanonicalPlan ? getVisualStateExecutionImageStatus(kf, plan, keyframeImageUrl) : null;
                  return (
                    <button
                      key={`${kf.index}-${kf.time_seconds}`}
                      type="button"
                      onClick={() => {
                        setSelectedKeyframeIndex(idx);
                        setSelectedClipKey(null);
                      }}
                      title={`${kf.role}${keyframeClipCount > 1 ? ` · ${t('chapterGenerate.sharedBoundary')}` : ''}${isGenerating ? ` · ${t('chapterGenerate.generatingShort')}` : hasImage ? ` · ${t('chapterGenerate.generated')}` : isCanonicalPlan ? ` · ${getVisualStateImageStatusLabel(kf)}` : ` · ${t('chapterGenerate.missingImage')}`}`}
                      className={`relative ${isCanonicalPlan ? 'w-44 min-w-44 p-2 text-left' : 'h-14 min-w-24 px-2 py-1 text-center'} rounded-lg transition-all ${isCurrentKeyframe
                        ? 'border border-blue-300 bg-blue-50 text-blue-700 shadow-sm ring-2 ring-blue-100'
                        : isInSelectedClip
                          ? 'border border-blue-100 bg-blue-50/50 text-blue-700'
                          : 'border border-transparent text-gray-700 hover:bg-gray-50 hover:text-blue-600'
                      }`}
                    >
                      {isCanonicalPlan ? (
                        <>
                          <div className="relative mb-2 aspect-video overflow-hidden rounded-md border border-gray-200 bg-gray-100">
                            {isGenerating ? (
                              <div className="flex h-full items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-blue-500" /></div>
                            ) : keyframeImageUrl ? (
                              <img src={keyframeImageUrl} alt={`${t('chapterGenerate.visualState')} ${kf.index}`} className="h-full w-full object-cover" />
                            ) : (
                              <div className="flex h-full flex-col items-center justify-center gap-1 text-gray-400"><Image className="h-6 w-6" /><span className="text-[10px]">{getVisualStateImageStatusLabel(kf)}</span></div>
                            )}
                          </div>
                          <div className="flex items-center justify-between gap-2 text-xs font-semibold">
                            <span>{t('chapterGenerate.visualState')} {kf.index}</span>
                            <span className="tabular-nums text-gray-500">{kf.time_seconds}s</span>
                          </div>
                          <div className="mt-1 flex flex-wrap items-center gap-1">
                            <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-medium text-gray-600">{getVisualStateRoleLabel(kf.role)}</span>
                            {kf.timed_visual_target === true && <span className="rounded bg-indigo-100 px-1.5 py-0.5 text-[10px] font-medium text-indigo-700">{t('chapterGenerate.timedVisualTarget')}</span>}
                            <span className={`text-[10px] ${isGenerating ? 'text-blue-600' : canonicalImageStatus === 'READY' ? 'text-green-600' : canonicalImageStatus === 'REQUIRED_MISSING' ? 'text-red-600' : 'text-gray-500'}`}>
                              {isGenerating ? t('chapterGenerate.generatingShort') : getVisualStateImageStatusLabel(kf)}
                            </span>
                          </div>
                          <div className="mt-1 truncate text-[11px] text-gray-500" title={kf.role === 'START' ? shot?.description || '' : kf.description || ''}>
                            {kf.role === 'START' ? shot?.description || t('chapterGenerate.noVisualStateDescription') : kf.description || t('chapterGenerate.noVisualStateDescription')}
                          </div>
                        </>
                      ) : (
                        <>
                          <div className="flex items-center justify-center gap-1 text-[11px] text-gray-500">
                            {isGenerating ? <Loader2 className="h-3 w-3 animate-spin text-blue-500" /> : <span className={`h-2.5 w-2.5 rounded-full border ${hasImage ? 'border-green-500 bg-green-100' : 'border-gray-400 bg-gray-100'}`} />}
                            <span>{marker}</span>
                          </div>
                          <div className="mt-0.5 text-xs font-semibold">KF{kf.index} · {kf.time_seconds}s</div>
                          <div className={`text-[11px] ${isGenerating ? 'text-blue-600' : hasImage ? 'text-green-600' : 'text-amber-600'}`}>{isGenerating ? t('chapterGenerate.generatingShort') : hasImage ? t('chapterGenerate.generated') : t('chapterGenerate.missingImage')}</div>
                        </>
                      )}
                      {isCurrentKeyframe && <div className="absolute -bottom-1 left-2 right-2 h-1 rounded-full bg-blue-500" />}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      )}

      <div
        data-testid="canonical-execution-summary"
        className={`rounded-lg border px-3 py-2.5 ${semanticShotStatus === 'FAILED' ? 'border-red-200 bg-red-50 text-red-800' : 'border-slate-200 bg-slate-50 text-slate-700'}`}
      >
        <div className="text-sm font-semibold">{semanticExecutionSummary}</div>
        {!hasSemanticClipPlan && optionalMissingKeyframes.length > 0 && (
          <div className="mt-1 text-xs text-gray-500">
            {keyframes.length} 个视觉状态 · {t('chapterGenerate.optionalMissingStates', { count: optionalMissingKeyframes.length })}
          </div>
        )}
      </div>

      <details
        data-testid="advanced-director-details"
        open={isAdvancedDirectorOpen}
        onToggle={(event) => setIsAdvancedDirectorOpen(event.currentTarget.open)}
        className="rounded-lg border border-slate-200 bg-slate-50/70"
      >
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-100">
          <span>高级导演详情</span>
          <span className="text-xs font-normal text-slate-500">视觉状态描述、完整转场与片段检查</span>
        </summary>
        <div className="space-y-4 border-t border-slate-200 p-3">
        {showKeyframeExecutionTimeline && (
          <div className="grid grid-cols-[minmax(260px,45%)_1fr] gap-4">
            <div>
              <div className="flex items-stretch gap-2">
                <div className="relative aspect-video min-w-0 flex-1 rounded-lg bg-gray-100 overflow-hidden border border-gray-200 flex items-center justify-center">
                  {selectedKeyframeIsGenerating ? (
                    <div className="flex flex-col items-center gap-2 text-blue-500">
                      <Loader2 className="w-10 h-10 animate-spin" />
                      <div className="text-sm">{t('chapterGenerate.keyframeImageGenerating')}</div>
                    </div>
                  ) : selectedKeyframeImageUrl ? (
                    <>
                      <img src={selectedKeyframeImageUrl} alt={`KF${selectedKeyframe.index}`} className="w-full h-full object-cover" />
                      <div className="absolute top-2 right-2 z-10 flex items-center gap-2">
                        <button type="button" onClick={() => onPreviewImage(selectedKeyframeImageUrl)} className="p-2 rounded-full bg-black/70 text-white shadow-lg ring-1 ring-white/30 transition-all hover:bg-black/85 hover:text-blue-300" title={t('chapterGenerate.viewLargeImage')}><Eye className="h-4 w-4" /></button>
                        <button type="button" onClick={() => onEditImage({ type: selectedKeyframe?.role === 'START' ? 'shot' : 'keyframe', imageUrl: selectedKeyframeImageUrl, itemName: `${t('chapterGenerate.shot')}${shot?.index || ''} KF${selectedKeyframe?.index || ''}`, frameIndex: selectedKeyframeFrameIndex })} className="p-2 rounded-full bg-black/70 text-white shadow-lg ring-1 ring-white/30 transition-all hover:bg-black/85 hover:text-blue-300" title={t('chapterGenerate.editImage')}><Image className="h-4 w-4" /></button>
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
                {(selectedReferenceImagesLoading || selectedKeyframeReferenceImages.length > 0) && (
                  <div className="relative z-20 w-16 shrink-0 self-stretch rounded-lg border border-gray-200 bg-gray-50">
                    <div className="absolute inset-0 space-y-1 overflow-y-auto p-1 scrollbar-thin" aria-label="分镜参考图">
                      <span className="text-[10px] text-gray-500">历史生成参考，非当前 Clip 输入</span>
                      {selectedReferenceImagesLoading && <span className="text-[10px] text-gray-500">加载中...</span>}
                      {selectedKeyframeReferenceImages.map((reference: any, index: number) => (
                        <div
                          key={`${reference.url}-${index}`}
                          onMouseEnter={() => setHoveredReferenceImage(reference)}
                          onMouseLeave={() => setHoveredReferenceImage(null)}
                          className="relative aspect-square cursor-zoom-in overflow-visible rounded border border-gray-200 bg-white"
                          title={getReferenceDisplayName(reference)}
                        >
                          <img src={reference.url} alt={reference.label || `Reference ${index + 1}`} className="h-full w-full rounded object-cover" />
                        </div>
                      ))}
                    </div>
                    {hoveredReferenceImage && (
                      <div className="pointer-events-none absolute left-full top-0 z-[100] ml-2 w-[28rem] rounded-lg border border-gray-200 bg-white p-2 shadow-xl">
                        <img src={hoveredReferenceImage.url} alt={getReferenceDisplayName(hoveredReferenceImage)} className="max-h-[28rem] w-full rounded object-contain" />
                        <div className="px-1 pt-2 text-sm font-medium text-gray-700">{getReferenceDisplayName(hoveredReferenceImage)}</div>
                      </div>
                    )}
                  </div>
                )}
              </div>
              <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm font-medium text-gray-700">
                  {isCanonicalPlan ? `${t('chapterGenerate.visualState')} ${selectedKeyframe?.index || 1}` : `KF${selectedKeyframe?.index || 1}`} · {selectedKeyframe?.time_seconds || 0}s
                  {isCanonicalPlan && selectedKeyframe?.role ? ` · ${getVisualStateRoleLabel(selectedKeyframe.role)}` : ''}
                </span>
                <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
                  {selectedKeyframe?.role !== 'START' && (
                    <div className="relative inline-flex">
                      <button
                        type="button"
                        onClick={() => selectedKeyframeFrameIndex !== undefined && onGenerateKeyframe(selectedKeyframeFrameIndex, 'llm')}
                        disabled={selectedKeyframeFrameIndex === undefined || selectedKeyframeIsGenerating || isPlanningKeyframes || !!isShotVideoGenerating || !selectedKeyframe?.description}
                        title={isShotVideoGenerating
                          ? `当前 Shot 视频生成中，请等待完成后再生成${isCanonicalPlan ? '状态图片' : '关键帧'}`
                          : !selectedKeyframe?.description
                            ? `当前${isCanonicalPlan ? '视觉状态' : '关键帧'}缺少描述，请先重新规划`
                            : isCanonicalPlan
                              ? selectedKeyframeImageUrl
                                ? '重新构建提示词并重新生成当前状态图片'
                                : selectedStateImageStatus === 'REQUIRED_MISSING' ? '生成当前片段执行必需的视觉状态图片' : '生成可选视觉锚点；仅在需要加强该时刻的构图、人物、道具或状态控制时使用'
                              : '使用 LLM 构建新的生图提示词并生成当前关键帧'}
                        className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-l-md border border-blue-200 bg-white px-2.5 py-1 text-xs font-medium text-blue-700 transition-colors hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {selectedKeyframeIsGenerating
                          ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          : selectedKeyframeImageUrl
                            ? <RefreshCw className="h-3.5 w-3.5" />
                            : <Sparkles className="h-3.5 w-3.5" />}
                        {selectedKeyframeIsGenerating ? '生成中...' : selectedKeyframePrimaryActionLabel}
                      </button>
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          setShowSelectedKeyframeMenu((open) => !open);
                        }}
                        disabled={selectedKeyframeFrameIndex === undefined || selectedKeyframeIsGenerating || isPlanningKeyframes || !!isShotVideoGenerating || !selectedKeyframe?.description}
                        title={isShotVideoGenerating
                          ? `当前 Shot 视频生成中，请等待完成后再选择${isCanonicalPlan ? '状态图片生成方式' : '关键帧生成模式'}`
                          : undefined}
                        className="inline-flex items-center rounded-r-md border border-l-0 border-blue-200 bg-white px-2 py-1 text-xs text-blue-700 transition-colors hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-50"
                        aria-label={isCanonicalPlan ? '选择状态图片生成方式' : '选择关键帧生成模式'}
                      >
                        <ChevronDown className="h-3.5 w-3.5" />
                      </button>
                      {showSelectedKeyframeMenu && (
                        <div className="absolute bottom-full right-0 z-[80] mb-1 w-52 rounded-lg border border-gray-200 bg-white py-1 shadow-lg">
                          <button
                            type="button"
                            onClick={() => {
                              setShowSelectedKeyframeMenu(false);
                              if (selectedKeyframeFrameIndex !== undefined) onGenerateKeyframe(selectedKeyframeFrameIndex, 'llm');
                            }}
                            className="w-full px-3 py-2 text-left text-xs text-gray-700 hover:bg-blue-50"
                          >
                            {selectedKeyframePrimaryActionLabel}
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              setShowSelectedKeyframeMenu(false);
                              if (selectedKeyframeFrameIndex !== undefined) onGenerateKeyframe(selectedKeyframeFrameIndex, 'image_only');
                            }}
                            disabled={!hasReusableSelectedKeyframePrompt || !!isShotVideoGenerating}
                            title={!hasReusableSelectedKeyframePrompt
                              ? isCanonicalPlan
                                ? '当前视觉状态没有可复用的生图提示词，请先生成可选状态图'
                                : '当前关键帧没有可复用的 AI 生图提示词，请先使用 LLM+生成'
                              : undefined}
                            className="w-full px-3 py-2 text-left text-xs text-gray-700 hover:bg-blue-50 disabled:cursor-not-allowed disabled:text-gray-400 disabled:hover:bg-white"
                          >
                            {selectedKeyframeCurrentPromptActionLabel}
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                  <span className={`text-xs ${selectedKeyframeIsGenerating ? 'text-blue-600' : selectedKeyframeImageUrl ? 'text-green-600' : isCanonicalPlan ? 'text-gray-500' : 'text-amber-600'}`}>
                    {selectedKeyframeIsGenerating
                      ? t('chapterGenerate.imageGenerating')
                      : selectedKeyframeImageUrl
                        ? t('chapterGenerate.imageReady')
                        : isCanonicalPlan
                          ? getVisualStateImageStatusLabel(selectedKeyframe)
                          : t('chapterGenerate.waitingImageGeneration')}
                  </span>
                </div>
              </div>
              {isCanonicalPlan && selectedKeyframe?.role !== 'START' && !selectedKeyframeImageUrl && selectedStateImageStatus !== 'REQUIRED_MISSING' && (
                <p className="mt-1 text-[11px] leading-4 text-gray-500">
                  可选视觉锚点；仅在需要加强该时刻的构图、人物、道具或状态控制时生成。
                </p>
              )}
            </div>
            <div className="space-y-3">
              <div>
                <div className="text-xs font-semibold text-gray-600 mb-1">{isCanonicalPlan ? t('chapterGenerate.visualStateDescription') : t('chapterGenerate.keyframeDescription')}</div>
                <textarea
                  readOnly
                  value={selectedKeyframe?.role === 'START' ? (shot?.description || '') : (selectedKeyframe?.description || '')}
                  className="w-full h-28 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm resize-none"
                />
              </div>
              <div>
                <div className="text-xs font-semibold text-gray-600 mb-1">
                  {isCanonicalPlan ? t('chapterGenerate.previousStateTransition') : t('chapterGenerate.previousTransition')}{previousTransition ? ` · ${isCanonicalPlan ? t('chapterGenerate.visualStateShort') : 'KF'}${previousTransition.from_keyframe_index} → ${isCanonicalPlan ? t('chapterGenerate.visualStateShort') : 'KF'}${previousTransition.to_keyframe_index} · ${previousTransition.start_time ?? ''}-${previousTransition.end_time ?? ''}s` : ''}
                </div>
                <textarea
                  readOnly
                  value={previousTransition?.transition_description || ''}
                  placeholder={selectedKeyframeIndex === 0
                    ? t(isCanonicalPlan ? 'chapterGenerate.noPreviousStateTransition' : 'chapterGenerate.noPreviousTransition')
                    : t(isCanonicalPlan ? 'chapterGenerate.waitingPreviousStateTransition' : 'chapterGenerate.waitingPreviousTransitionPlan')}
                  className="w-full h-20 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm resize-none"
                />
              </div>
              <div>
                <div className="text-xs font-semibold text-gray-600 mb-1">
                  {isCanonicalPlan ? t('chapterGenerate.nextStateTransition') : t('chapterGenerate.nextTransition')}{nextTransition ? ` · ${isCanonicalPlan ? t('chapterGenerate.visualStateShort') : 'KF'}${nextTransition.from_keyframe_index} → ${isCanonicalPlan ? t('chapterGenerate.visualStateShort') : 'KF'}${nextTransition.to_keyframe_index} · ${nextTransition.start_time ?? ''}-${nextTransition.end_time ?? ''}s` : ''}
                </div>
                <textarea
                  readOnly
                  value={nextTransition?.transition_description || ''}
                  placeholder={hasNextKeyframe
                    ? t(isCanonicalPlan ? 'chapterGenerate.waitingNextStateTransition' : 'chapterGenerate.waitingNextTransitionPlan')
                    : t(isCanonicalPlan ? 'chapterGenerate.noNextStateTransition' : 'chapterGenerate.noNextTransition')}
                  className="w-full h-20 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm resize-none"
                />
              </div>
            </div>
          </div>
        )}

      <div className="rounded-lg border border-gray-200 bg-white p-3">
        <div className="flex items-center justify-between gap-3 mb-2">
          <div>
            <div className="text-sm font-semibold text-gray-700">{t('chapterGenerate.executionPlan')} · {showSemanticClipPlan ? semanticClipPlan.length : clips.length} {t('chapterGenerate.clips')}</div>
            {showSemanticClipPlan && <div className="mt-0.5 text-xs text-gray-500">查看片段预览、恢复与对话分配</div>}
            {isCanonicalPlan && <div className="mt-0.5 text-xs text-gray-500">
              {canonicalSemanticReadiness.state === 'NO_VISUAL_PLAN'
                ? t('chapterGenerate.noVisualTimeline')
                : canonicalSemanticReadiness.state === 'REQUIRED_IMAGES_MISSING'
                  ? t('chapterGenerate.requiredVisualStatesMissing')
                  : canonicalSemanticReadiness.state === 'CLIP_PLAN_MISSING'
                    ? t('chapterGenerate.clipPlanMissing')
                    : canonicalSemanticReadiness.state === 'CLIP_PLAN_STALE'
                      ? t('chapterGenerate.clipPlanNeedsReplan')
                      : canonicalSemanticReadiness.state === 'GENERATE_VISUAL_START_MISSING'
                        ? canonicalSemanticReadiness.reason
                      : t('chapterGenerate.clipPlanReady')}
            </div>}
          </div>
          <div className="flex items-center gap-2">
            {!isCanonicalPlan && <div className="text-xs text-gray-500">{t('chapterGenerate.estimatedH3Tasks', { count: hasSemanticClipPlan ? semanticClipPlan.length : clips.length })}</div>}
            {isCanonicalPlan && <button
              type="button"
              onClick={() => {
                if (!hasSemanticClipPlan || window.confirm(t('chapterGenerate.replanClipsConfirm'))) onPlanClips(hasSemanticClipPlan);
              }}
              disabled={!canonicalSemanticReadiness.planningAllowed || isPlanningClips || !!isShotVideoGenerating}
              title={canonicalSemanticReadiness.state === 'NO_VISUAL_PLAN'
                ? t('chapterGenerate.planVisualTimelineFirst')
                : canonicalSemanticReadiness.state === 'REQUIRED_IMAGES_MISSING'
                  ? t('chapterGenerate.generateRequiredVisualStatesFirst')
                  : undefined}
              className="rounded-md border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isPlanningClips ? t('chapterGenerate.planningClips') : hasSemanticClipPlan ? t('chapterGenerate.replanClips') : t('chapterGenerate.planClips')}
            </button>}
          </div>
        </div>
        {!hasSemanticClipPlan && selectedMode === 'MULTI_KEYFRAME' && (
          <div className="grid grid-cols-2 gap-2 text-sm mb-3">
            <div className="rounded-lg border border-gray-200 px-3 py-2 flex items-center justify-between">{t('chapterGenerate.threeFrameClips')} <span className="font-semibold text-gray-800">{threeFrameClipCount}</span></div>
            <div className="rounded-lg border border-gray-200 px-3 py-2 flex items-center justify-between">{t('chapterGenerate.fourFrameClips')} <span className="font-semibold text-gray-800">{fourFrameClipCount}</span></div>
          </div>
        )}
        {showSemanticClipPlan ? (
          <SemanticClipExecutionPanel
            key={`${(semanticClipPlanShot || shot)?.id}-${(semanticClipPlanShot || shot)?.videoDirectorPlan?.clip_plan_revision}`}
            shot={semanticClipPlanShot || shot}
            chapterId={chapterId}
            novelId={novelId}
            onPreparationShot={onPreparationShot}
            onPreviewClip={onPreviewClip}
            onRegenerateClip={onRegenerateClip}
            onAssemble={onMergeClips}
            onTasksChange={onSemanticClipTasksChange}
            regeneratingClipKey={regeneratingClipKey}
            isShotVideoGenerating={isShotVideoGenerating}
            isAssembling={isMergingClips}
          />
        ) : clips.length > 0 ? (
          <div className="grid grid-cols-[repeat(auto-fit,minmax(320px,1fr))] gap-3">
            {clips.map((clip: any) => {
              const clipIndex = clip.clip_index || clip.window_index;
              const frameCount = clip.selected_frame_count || clip.frame_count;
              const clipHasVideo = !!(clip.video_url || clip.local_path || (selectedMode !== 'MULTI_KEYFRAME' && shot?.videoUrl));
              const clipStatus = clip.status || (clipHasVideo ? 'SUCCEEDED' : 'PENDING');
              const clipKey = getClipKey(clip);
              const isPreviewing = selectedPreviewClipKey === clipKey;
              const isRegenerating = regeneratingClipKey === clipKey;
              const clipGenerationDisabled = isRegenerating || !!isShotVideoGenerating;
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
                    minRequiredSeconds: dialogue.projection_mode === 'intersection' || dialogue.dialogue_timing_source === 'official_projection'
                      ? Number(dialogue.projected_duration ?? dialogue.end_time - dialogue.start_time) || 0
                      : estimateDialogueSeconds(text, emotion),
                    timingSource: dialogue.projection_mode === 'intersection' ? 'official_projection' : dialogue.dialogue_timing_source,
                    localStart: dialogue.local_start_time,
                    localEnd: dialogue.local_end_time,
                  };
                })
                .filter((dialogue: any) => dialogue.text);
              const clipDuration = Math.max(0, (numberOrNull(clip.end_time) ?? numberOrNull(shot?.duration) ?? 0) - (numberOrNull(clip.start_time) ?? 0));
              const totalMinDialogueSeconds = clipDialogues.reduce((sum: number, dialogue: any) => sum + dialogue.minRequiredSeconds, 0);
              const usesOfficialProjection = clipDialogues.length > 0 && clipDialogues.every((dialogue: any) => dialogue.timingSource === 'official_projection');
              const dialogueGapSeconds = usesOfficialProjection ? 0 : Math.max(0, clipDialogues.length - 1) * DIALOGUE_GAP_SECONDS;
              const dialogueOccupancySeconds = totalMinDialogueSeconds + dialogueGapSeconds;
              const dialogueDurationInsufficient = clipDialogues.length > 0 && clipDuration > 0 && dialogueOccupancySeconds > clipDuration + 0.05;
              return (
                <div key={`${clipIndex}-${clip.start_time}-${clip.end_time}`} className={`rounded-lg border p-3 ${isPreviewing ? 'border-blue-300 bg-blue-50 ring-2 ring-blue-100' : 'border-gray-200 bg-white'}`}>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-semibold text-gray-800">C{clipIndex} · {clip.start_time}-{clip.end_time}s · {clipTitleFrameLabel}</div>
                      <div className="mt-1 text-xs text-gray-500">
                        {clipFrameLabel}
                        {clip.workflow_key ? ` · ${clip.workflow_key}` : ''}
                        {clip.seed != null ? ` · Seed ${clip.seed}` : ''}
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
                      <span className="font-medium">Clip 台词</span>
                      <span className={dialogueDurationInsufficient ? 'text-red-700' : 'text-gray-500'}>
                        {usesOfficialProjection ? `Official timeline 实际覆盖 ${totalMinDialogueSeconds.toFixed(2)}s` : `预计对白发声约 ${totalMinDialogueSeconds.toFixed(2)}s${clipDialogues.length > 1 ? ` · 加换人间隔约 ${dialogueGapSeconds.toFixed(2)}s，占用约 ${dialogueOccupancySeconds.toFixed(2)}s` : ''}`} / Clip {clipDuration ? `${clipDuration.toFixed(2)}s` : '-'}
                      </span>
                    </div>
                    {clipDialogues.length > 0 ? (
                      <div className="space-y-1">
                        {clipDialogues.map((dialogue: any) => (
                          <div key={dialogue.key} className="rounded border border-white/70 bg-white/70 px-2 py-1">
                            <div className="flex flex-wrap items-center gap-2 text-[11px] text-gray-500">
                              <span className="font-medium text-gray-700">{dialogue.speaker}</span>
                              {dialogue.emotion && <span>情绪：{dialogue.emotion}</span>}
                              <span>{dialogue.timingSource === 'official_projection' ? `覆盖 ${Number(dialogue.localStart ?? 0).toFixed(2)}–${Number(dialogue.localEnd ?? 0).toFixed(2)}s，实际投影 ${dialogue.minRequiredSeconds.toFixed(2)}s` : `预计发声 ${dialogue.minRequiredSeconds.toFixed(2)}s`}</span>
                            </div>
                            <div className="mt-0.5 text-gray-700">{dialogue.text}</div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="text-gray-500">无分配台词；该 Clip 只保留环境声和动作声。</div>
                    )}
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
                          title={isShotVideoGenerating ? '当前 Shot 视频生成中，请等待完成后再操作 Clip' : undefined}
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
                          title={isShotVideoGenerating ? '当前 Shot 视频生成中，请等待完成后再选择生成模式' : undefined}
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
                              disabled={!clip.prompt_text || !!isShotVideoGenerating}
                              title={isShotVideoGenerating ? '当前 Shot 视频生成中，请等待完成后再操作 Clip' : !clip.prompt_text ? '缺少可复用的 Clip 视频最终 Prompt，请先使用 LLM+生成Clip视频' : undefined}
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
            {isCanonicalPlan
              ? canonicalSemanticReadiness.state === 'NO_VISUAL_PLAN'
                ? t('chapterGenerate.noVisualTimeline')
                : canonicalSemanticReadiness.state === 'REQUIRED_IMAGES_MISSING'
                  ? t('chapterGenerate.requiredVisualStatesMissing')
                  : canonicalSemanticReadiness.state === 'CLIP_PLAN_STALE'
                    ? t('chapterGenerate.clipPlanNeedsReplan')
                    : t('chapterGenerate.clipPlanMissing')
              : selectedMode === 'MULTI_KEYFRAME' ? '等待 #08 生成 window_plans 后才能执行多关键帧视频。' : '暂无执行 Clip，请重新推荐或保存视频规划。'}
          </div>
        )}
      </div>
        </div>
      </details>
    </div>
    {viewingPromptClip?.prompt_text && createPortal((
      <div className="fixed inset-0 z-[300] flex items-center justify-center bg-black/50 p-4" onClick={() => setViewingPromptClip(null)}>
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
    ), document.body)}
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
  const { markTabComplete, setCurrentShot, setCurrentTab, downloadChapterMaterials, generateShotVideo, generateKeyframeImage, setShots, setShotVideos, setShotImages, checkVideoTaskStatus, generateTransition, transitionWorkflows, selectedTransitionWorkflow, setSelectedTransitionWorkflow, fetchTransitionWorkflows, transitionDuration, setTransitionDuration } = store;

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
  const [isDownloadingVideoMaterials, setIsDownloadingVideoMaterials] = useState(false);
  const [showResetVideoDataConfirm, setShowResetVideoDataConfirm] = useState(false);
  const [isResettingVideoData, setIsResettingVideoData] = useState(false);
  const [showBatchSelectModal, setShowBatchSelectModal] = useState(false);
  const [materialShotIds, setMaterialShotIds] = useState<Set<string>>(new Set());
  const [preparingMaterials, setPreparingMaterials] = useState(false);
  const [materialResults, setMaterialResults] = useState<string[]>([]);
  const [selectedShots, setSelectedShots] = useState<Set<number>>(new Set());
  const [batchFilter, setBatchFilter] = useState<BatchShotFilter>('ready');
  const [dragSelectionMode, setDragSelectionMode] = useState<'select' | 'deselect' | null>(null);
  const [autoCompleteDetails, setAutoCompleteDetails] = useState(true);
  const [autoAssemble, setAutoAssemble] = useState(true);
  const [batchShotTasks, setBatchShotTasks] = useState<Record<string, Task[]>>({});
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
  const [selectedPreviewClipUrl, setSelectedPreviewClipUrl] = useState<string | null>(null);
  const [semanticClipTasks, setSemanticClipTasks] = useState<Task[]>([]);
  const [regeneratingClipKey, setRegeneratingClipKey] = useState<string | null>(null);
  const regeneratingClipWasActiveRef = useRef(false);
  const [isMergingClips, setIsMergingClips] = useState(false);
  const [isCancellingVideo, setIsCancellingVideo] = useState(false);
  const [isRefreshingAiCalls, setIsRefreshingAiCalls] = useState(false);
  const [showGenerateVideoMenu, setShowGenerateVideoMenu] = useState(false);
  const [showWorkspaceActionsMenu, setShowWorkspaceActionsMenu] = useState(false);
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
  const currentIsCanonicalPlan = isCanonicalVisualPlan(currentVideoDirectorPlan);
  const currentIsHistoricalPlan = !currentIsCanonicalPlan && hasLegacyBatchPlanningState(currentVideoDirectorPlan);

  useEffect(() => {
    setIsVideoPromptModalOpen(false);
    setVideoPromptDrafts([]);
    setShowGenerateVideoMenu(false);
  }, [currentIsCanonicalPlan, currentIsHistoricalPlan, currentShotId]);

  const currentSelectedVideoMode = currentIsCanonicalPlan
    ? undefined
    : currentVideoDirectorPlan.selected_mode || currentVideoDirectorPlan.recommended_mode || 'SINGLE_FRAME';
  const hasSemanticClipPlan = currentIsCanonicalPlan
    ? hasValidCurrentClipPlan(currentVideoDirectorPlan)
    : Array.isArray(currentVideoDirectorPlan.clip_plan) && currentVideoDirectorPlan.clip_plan.length > 0;
  const hasReusableVideoPrompt = !currentIsCanonicalPlan && currentSelectedVideoMode === 'MULTI_KEYFRAME'
    ? !!currentVideoDirectorPlan.window_plans?.length && currentVideoDirectorPlan.window_plans.every((windowPlan: any) => (
      String(windowPlan?.prompt_text || getLatestH3FinalPrompt(currentVideoDirectorPlan, Number(windowPlan?.window_index))).trim().length > 0
    ))
    : !currentIsCanonicalPlan && getLatestH3FinalPrompt(currentVideoDirectorPlan).trim().length > 0;
  const currentEndPlanKeyframe = (currentVideoDirectorPlan.keyframes || []).find((keyframe: any) => keyframe.role === 'END');
  const currentEndLegacyKeyframe = (currentShotData?.keyframes || []).find((keyframe: any) => (
    Number(keyframe.plan_keyframe_index) === Number(currentEndPlanKeyframe?.index || 2)
  ));
  const currentEndFrameIndex = currentEndLegacyKeyframe?.frame_index ?? (currentEndPlanKeyframe ? 0 : undefined);
  const isGeneratingCurrentEndKeyframe = currentShotId && currentEndFrameIndex !== undefined
    ? generatingKeyframes.has(`${currentShotId}-${Number(currentEndFrameIndex)}`)
    : false;
  const getPlanClipKey = (clip: any) => String(clip?.clip_index || clip?.window_index || `${clip?.start_time}-${clip?.end_time}`);
  const semanticClipPlanRevision = Number(currentVideoDirectorPlan.clip_plan_revision || 0);
  const currentPlanClips: any[] = hasSemanticClipPlan
    ? (currentVideoDirectorPlan.clip_plan || []).map((clip: any) => {
      const task = resolveSemanticClipTask(clip, semanticClipTasks, semanticClipPlanRevision);
      return {
        ...clip,
        video_url: getClipArtifactPresentation(clip, task).playbackUrl,
        preview_task_status: task?.status,
      };
    })
    : currentSelectedVideoMode === 'MULTI_KEYFRAME' ? (currentVideoDirectorPlan.window_plans || []) : (currentVideoDirectorPlan.clips || []);
  const selectedPreviewClip: any | null = selectedPreviewClipKey
    ? currentPlanClips.find((clip: any) => getPlanClipKey(clip) === selectedPreviewClipKey)
    : null;
  const currentFinalShotVideoUrl = currentIsCanonicalPlan
    ? hasCurrentAssembly(currentVideoDirectorPlan, semanticClipTasks) ? (currentVideoDirectorPlan.merged_video_url || currentShotVideoUrl) : undefined
    : currentShotVideoUrl;
  const previewVideoUrl = hasSemanticClipPlan
    ? selectedPreviewClipKey ? selectedPreviewClip?.video_url || undefined : currentFinalShotVideoUrl
    : selectedPreviewClipUrl || selectedPreviewClip?.video_url || currentFinalShotVideoUrl;
  const previewVideoLabel = selectedPreviewClip ? `C${selectedPreviewClip.window_index || selectedPreviewClip.clip_index}` : 'Shot';
  const previewClipMarkers = !selectedPreviewClip && !hasSemanticClipPlan && currentSelectedVideoMode === 'MULTI_KEYFRAME'
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
  const [planningClipsShotId, setPlanningClipsShotId] = useState<string | null>(null);
  const [isSubmittingCanonicalShot, setIsSubmittingCanonicalShot] = useState(false);
  const [generatingMissingKeyframesShotId, setGeneratingMissingKeyframesShotId] = useState<string | null>(null);

  const hasShotVideo = (shot: any) => {
    const shotId = shot?.id ? String(shot.id) : '';
    if (isSemanticShot(shot)) return getSemanticShotStatus(shot, batchShotTasks[shotId] || []) === 'ASSEMBLED';
    return !!(shot?.videoUrl || (shotId && shotVideos[shotId]));
  };

  useEffect(() => {
    if (!showBatchSelectModal || !effectiveChapterId) return;
    let cancelled = false;
    const refresh = async () => {
      const semanticShots = shotsList.filter((shot: any) => isSemanticShot(shot));
      const entries = await Promise.all(semanticShots.map(async (shot: any) => {
        try {
          const response = await taskApi.fetchShotTasks(effectiveChapterId, String(shot.id));
          return [String(shot.id), Array.isArray(response.data) ? response.data : []] as const;
        } catch {
          return [String(shot.id), []] as const;
        }
      }));
      if (!cancelled) setBatchShotTasks(Object.fromEntries(entries));
    };
    refresh();
    const interval = window.setInterval(refresh, 2000);
    return () => { cancelled = true; window.clearInterval(interval); };
  }, [showBatchSelectModal, effectiveChapterId, shotsList]);

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
  const getMissingVideoKeyframeLabels = useCallback((shot: any, plan: VideoDirectorPlan) => {
    if (isCanonicalVisualPlan(plan)) {
      return getRequiredMissingCanonicalVisualStates(
        plan,
        (state) => getVideoDirectorKeyframeImageUrl(shot, state),
      ).map((state) => `${t('chapterGenerate.visualStateShort')}${state.index}`);
    }
    const selectedMode = plan.selected_mode || plan.recommended_mode || 'SINGLE_FRAME';
    const planKeyframes = Array.isArray(plan.keyframes) ? plan.keyframes : [];
    const missingLabels: string[] = [];

    if (selectedMode === 'SINGLE_FRAME') {
      return getShotImageUrl(shot) ? missingLabels : ['KF1（主分镜图）'];
    }

    let requiredKeyframes = planKeyframes;
    if (selectedMode === 'FIRST_LAST_FRAME') {
      requiredKeyframes = planKeyframes.filter((keyframe: any) => (
        keyframe.role === 'START' || keyframe.role === 'END'
      ));
    } else if (selectedMode === 'MULTI_KEYFRAME') {
      const semanticClips = Array.isArray(plan.clip_plan) ? plan.clip_plan : [];
      const windowPlans = Array.isArray(plan.window_plans) ? plan.window_plans : [];
      const executionClips = semanticClips.length > 0 ? semanticClips : windowPlans;
      const requiredIndexes = new Set<number>();
      executionClips.forEach((clip: any) => {
        (clip?.keyframe_indexes || []).forEach((index: number) => requiredIndexes.add(Number(index)));
      });
      if (requiredIndexes.size > 0) {
        requiredKeyframes = planKeyframes.filter((keyframe: any) => requiredIndexes.has(Number(keyframe.index)));
      } else if (semanticClips.length > 0) {
        // 语义 Clip 计划若未引用关键帧，只要求主分镜图作为起始视觉输入。
        requiredKeyframes = planKeyframes.filter((keyframe: any) => keyframe.role === 'START');
      }
    }

    if (requiredKeyframes.length === 0) {
      return getShotImageUrl(shot) ? missingLabels : ['KF1（主分镜图）'];
    }

    requiredKeyframes.forEach((keyframe: any, index: number) => {
      if (!getVideoDirectorKeyframeImageUrl(shot, keyframe)) {
        missingLabels.push(`KF${keyframe.index ?? index + 1}`);
      }
    });
    return Array.from(new Set(missingLabels));
  }, [getShotImageUrl, getVideoDirectorKeyframeImageUrl, t]);
  const currentMissingVideoKeyframes = getMissingVideoKeyframeLabels(currentShotData, currentVideoDirectorPlan);
  const currentVideoKeyframeBlockReason = currentMissingVideoKeyframes.length > 0
    ? `缺少关键帧图片：${currentMissingVideoKeyframes.join('、')}，请先生成缺失关键帧图`
    : '';
  const currentCanonicalReadiness = getCanonicalSemanticReadiness(
    currentVideoDirectorPlan,
    (state) => getVideoDirectorKeyframeImageUrl(currentShotData, state),
  );
  const currentOptionalMissingVisualStateCount = currentIsCanonicalPlan
    ? getCanonicalVisualStates(currentVideoDirectorPlan).filter((state) => (
      classifyVisualStateImageStatus(state, getVideoDirectorKeyframeImageUrl(currentShotData, state)) === 'OPTIONAL_MISSING'
    )).length
    : 0;
  const currentSemanticShotStatus = currentIsCanonicalPlan
    ? getSemanticShotStatusFromPlan(currentVideoDirectorPlan, semanticClipTasks)
    : 'NOT_STARTED';
  const currentCanonicalExecutionPendingReason = currentCanonicalReadiness.state === 'NO_VISUAL_PLAN'
    ? t('chapterGenerate.planVisualTimelineFirst')
    : currentCanonicalReadiness.state === 'REQUIRED_IMAGES_MISSING'
      ? t('chapterGenerate.generateRequiredVisualStatesFirst')
      : currentCanonicalReadiness.state === 'CLIP_PLAN_MISSING'
        ? t('chapterGenerate.planClipsFirst')
        : currentCanonicalReadiness.state === 'CLIP_PLAN_STALE'
          ? t('chapterGenerate.clipPlanNeedsReplan')
          : currentCanonicalReadiness.state === 'GENERATE_VISUAL_START_MISSING'
            ? currentCanonicalReadiness.reason || '缺少片段起始视觉图'
          : currentSemanticShotStatus === 'ASSEMBLED'
            ? t('chapterGenerate.finalVideoComplete')
            : '';
  const isCurrentVideoGenerateDisabled = currentIsCanonicalPlan
    ? !effectiveChapterId || !currentShotId || !currentCanonicalReadiness.executionAllowed || currentSemanticShotStatus === 'ASSEMBLED' || isSubmittingCanonicalShot
    : !effectiveChapterId || !currentShotId || !!currentVideoKeyframeBlockReason;
  const currentEndKeyframeImageUrl = currentEndPlanKeyframe
    ? getVideoDirectorKeyframeImageUrl(currentShotData, currentEndPlanKeyframe)
    : null;

  const getBatchShotEligibility = useCallback((shot: any, autoCompleteOverride = autoCompleteDetails) => {
    const shotId = shot?.id ? String(shot.id) : '';
    if (!shotId) return { selectable: false, reason: '缺少分镜 ID' };
    if (generatingVideos.has(shotId) || shot?.videoStatus === 'generating') return { selectable: false, reason: '视频生成中' };
    if (storePendingVideos.has(shotId)) return { selectable: false, reason: '视频队列中' };

    const plan: VideoDirectorPlan = shot?.videoDirectorPlan || {};
    if (isCanonicalVisualPlan(plan)) {
      const eligibility = getCanonicalBatchEligibility(
        plan,
        batchShotTasks[shotId] || [],
        (state) => getVideoDirectorKeyframeImageUrl(shot, state),
        autoAssemble,
      );
      if (eligibility.selectable && !getShotImageUrl(shot)) return { selectable: false, reason: '缺少主分镜图' };
      return eligibility;
    }

    if (isSemanticShot(shot)) {
      const status = getSemanticShotStatus(shot, batchShotTasks[shotId] || []);
      if (status === 'ASSEMBLED') return { selectable: false, reason: '当前版本已完成' };
      if (status === 'WAITING_REVIEW') return { selectable: false, reason: '等待审核' };
      if (status === 'CLIPS_COMPLETE' && !autoAssemble) return { selectable: false, reason: 'Clip 已完成' };
      if (!getShotImageUrl(shot)) return { selectable: false, reason: '缺少主分镜图' };
      return { selectable: true, reason: status === 'CLIPS_COMPLETE' ? '待合并' : '可执行缺失 Clip' };
    }

    const shotImageUrl = getShotImageUrl(shot);
    if (autoCompleteOverride) {
      return shotImageUrl
        ? { selectable: true, reason: '可自动补齐' }
        : { selectable: false, reason: '缺少主分镜图' };
    }

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
  }, [autoAssemble, autoCompleteDetails, batchShotTasks, generatingVideos, getShotImageUrl, getVideoDirectorKeyframeImageUrl, storePendingVideos]);

  const batchShotItems = shotsList.map((shot: any, idx: number) => {
    const shotIndex = idx + 1;
    const shotId = shot?.id ? String(shot.id) : '';
    const plan: VideoDirectorPlan = shot?.videoDirectorPlan || {};
    const tasks = shotId ? batchShotTasks[shotId] || [] : [];
    const semanticStatus = isSemanticShot(shot) ? getSemanticShotStatus(shot, tasks) : null;
    const semanticExecution = isSemanticShot(shot)
      ? getCurrentSemanticExecutionState(plan, tasks)
      : { isGenerating: false, isQueued: false, isFailed: false, failureReason: null };
    const eligibility = getBatchShotEligibility(shot);
    const projection = getBatchShotStatusProjection({
      eligibility,
      isGenerating: (!!shotId && generatingVideos.has(shotId)) || shot?.videoStatus === 'generating' || semanticExecution.isGenerating,
      isQueued: (!!shotId && storePendingVideos.has(shotId)) || semanticExecution.isQueued,
      isFailed: shot?.videoStatus === 'failed' || semanticStatus === 'FAILED' || semanticExecution.isFailed,
      isCompleted: hasShotVideo(shot),
      failureReason: semanticExecution.failureReason,
    });
    return {
      shot,
      shotIndex,
      shotId,
      eligibility,
      semanticStatus,
      isLegacy: !isSemanticShot(shot) && hasLegacyBatchPlanningState(plan),
      ...projection,
    };
  });
  const batchCategoryCounts = batchShotItems.reduce((counts, item) => {
    counts[item.category] += 1;
    return counts;
  }, {
    ready: 0,
    generating: 0,
    queued: 0,
    completed: 0,
    missing_preparation: 0,
    failed: 0,
  } as Record<BatchShotCategory, number>);
  const visibleBatchShotItems = batchFilter === 'all'
    ? batchShotItems
    : batchShotItems.filter((item) => item.category === batchFilter);
  const selectableVisibleShotIndexes = getSelectableBatchShotIndexes(batchShotItems, batchFilter);
  const executableSelectedIndexes = reconcileBatchSelection(selectedShots, batchShotItems);
  const executableSelectedSet = new Set(executableSelectedIndexes);
  const selectedFailedCount = batchShotItems.filter((item) => (
    executableSelectedSet.has(item.shotIndex) && item.category === 'failed'
  )).length;
  const allVisibleSelectableSelected = selectableVisibleShotIndexes.length > 0
    && selectableVisibleShotIndexes.every((index) => executableSelectedSet.has(index));
  const legacyCompatibilityVisible = shouldShowLegacyBatchCompatibility(visibleBatchShotItems)
    || shouldShowLegacyBatchCompatibility(batchShotItems.filter((item) => executableSelectedSet.has(item.shotIndex)));
  const batchSelectionSignature = batchShotItems.map((item) => `${item.shotIndex}:${item.selectable ? 1 : 0}`).join('|');

  useEffect(() => {
    setSelectedShots((previous) => {
      const next = reconcileBatchSelection(previous, batchShotItems);
      if (next.length === previous.size && next.every((index) => previous.has(index))) return previous;
      return new Set(next);
    });
  // batchSelectionSignature intentionally captures only changes that can invalidate selection.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batchSelectionSignature]);

  // 检查当前分镜是否正在生成
  const isGeneratingCurrent = currentShotId ? generatingVideos.has(currentShotId) || currentShotData?.videoStatus === 'generating' : false;

  useEffect(() => {
    if (!regeneratingClipKey) {
      regeneratingClipWasActiveRef.current = false;
      return;
    }
    if (isGeneratingCurrent) {
      regeneratingClipWasActiveRef.current = true;
      return;
    }
    if (regeneratingClipWasActiveRef.current) {
      regeneratingClipWasActiveRef.current = false;
      setRegeneratingClipKey(null);
    }
  }, [isGeneratingCurrent, regeneratingClipKey]);
  const isCurrentVideoPending = currentShotId ? storePendingVideos.has(currentShotId) : false;
  const latestFailedAiCallError = currentVideoDirectorPlan?.ai_calls
    ? [...currentVideoDirectorPlan.ai_calls].reverse().find((call: any) => String(call?.status || '').toLowerCase() !== 'success' && String(call?.error_message || '').trim())?.error_message
    : '';
  const currentVideoErrorMessage = currentShotData?.videoStatus === 'failed' && !currentShotVideoUrl && !currentVideoDirectorPlan.merged_video_url
    ? formatUserFacingError((currentVideoDirectorPlan as any).task_error_message || (currentVideoDirectorPlan as any).error_message || latestFailedAiCallError) || '当前 Shot 视频任务失败；如果已有部分 Clip 完成，可以重新生成缺失 Clip 或重新生成当前 Shot 视频。'
    : null;
  const getCurrentShotVideoResult = () => {
    if (currentIsCanonicalPlan) {
      const clipCount = currentVideoDirectorPlan.clip_plan?.length || 0;
      const completedClipCount = (currentVideoDirectorPlan.clip_plan || []).filter((clip) => (
        getSemanticClipStatus(clip, semanticClipTasks, Number(currentVideoDirectorPlan.clip_plan_revision || 0)) === 'COMPLETED'
      )).length;
      if (isGeneratingCurrent || isCurrentVideoPending || isSubmittingCanonicalShot) {
        return { label: isCurrentVideoPending ? '队列中' : '正在生成', className: 'border-blue-100 bg-blue-50 text-blue-700', detail: `视频片段 ${completedClipCount}/${clipCount}` };
      }
      if (currentSemanticShotStatus === 'ASSEMBLED') {
        return { label: '最终视频已完成', className: 'border-green-100 bg-green-50 text-green-700', detail: `最终合并视频 · 视频片段 ${completedClipCount}/${clipCount}` };
      }
      if (currentSemanticShotStatus === 'CLIPS_COMPLETE') {
        return { label: '片段已完成，待合并', className: 'border-amber-100 bg-amber-50 text-amber-700', detail: `视频片段 ${completedClipCount}/${clipCount} 已完成，待生成最终视频` };
      }
      if (currentSemanticShotStatus === 'FAILED') {
        return { label: '生成失败', className: 'border-red-100 bg-red-50 text-red-700', detail: currentVideoErrorMessage || `视频片段 ${completedClipCount}/${clipCount}` };
      }
      if (currentCanonicalReadiness.state !== 'READY') {
        return { label: '准备不完整', className: 'border-gray-200 bg-gray-50 text-gray-600', detail: currentCanonicalExecutionPendingReason };
      }
      return { label: currentSemanticShotStatus === 'PARTIAL' ? '部分完成' : '已准备，可生成', className: 'border-gray-200 bg-gray-50 text-gray-600', detail: `视频片段 ${completedClipCount}/${clipCount}` };
    }
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
        label: isCurrentVideoPending ? '队列中' : '生成中',
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
    if (isCanonicalVisualPlan(plan)) return [];
    const selectedMode = plan.selected_mode || plan.recommended_mode || 'SINGLE_FRAME';
    const latestFinalPrompt = getLatestH3FinalPrompt(plan);
    if (selectedMode === 'MULTI_KEYFRAME' && plan.window_plans?.length) {
      return plan.window_plans.map((clip: any, index: number) => {
        const clipIndex = Number(clip.window_index || index + 1);
        return {
          key: `window-${clipIndex}`,
          label: `C${clipIndex} · ${clip.start_time ?? 0}-${clip.end_time ?? currentShotData?.duration ?? 0}s`,
          prompt: String(clip.prompt_text || getLatestH3FinalPrompt(plan, clipIndex)),
          source: 'window_plan' as const,
          index,
        };
      });
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
    if (isCanonicalVisualPlan(currentVideoDirectorPlan)) return;
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
    if (isCanonicalVisualPlan(currentVideoDirectorPlan)) {
      setIsVideoPromptModalOpen(false);
      toast.info(t('chapterGenerate.canonicalExecutionPending'));
      return;
    }

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
  }, [currentShotData, currentVideoDirectorPlan, effectiveChapterId, effectiveNovelId, t, updateCurrentShotVideoDirectorPlan, videoPromptDrafts]);

  const handleRecommendVideoMode = useCallback(async (force = false) => {
    if (!effectiveNovelId || !effectiveChapterId || !currentShotId) return;
    if (isCanonicalVisualPlan(currentVideoDirectorPlan)) return;
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
  }, [currentShotId, currentVideoDirectorPlan, effectiveChapterId, effectiveNovelId, updateCurrentShotVideoDirectorPlan]);

  const handleSelectVideoMode = useCallback(async (mode: VideoMode) => {
    if (!effectiveNovelId || !effectiveChapterId || !currentShotId) return;
    if (isCanonicalVisualPlan(currentVideoDirectorPlan)) return;
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
    if (!effectiveNovelId || !effectiveChapterId || !currentShotId) return;
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
        toast.success(isCanonicalVisualPlan(result.data) ? '视觉时间轴已生成' : '关键帧规划已生成');
      } else {
        toast.error(result.message || (result as any).detail || '关键帧规划失败');
      }
    } catch (error) {
      console.error('关键帧规划失败:', error);
      toast.error('关键帧规划失败');
    } finally {
      setPlanningKeyframesShotId(null);
    }
  }, [currentShotId, effectiveChapterId, effectiveNovelId, setShotVideos, setShots, shotsList, updateCurrentShotVideoDirectorPlan]);

  const handlePlanSemanticClips = useCallback(async (force = false) => {
    if (!effectiveNovelId || !effectiveChapterId || !currentShotId) return;
    const readiness = getCanonicalSemanticReadiness(
      currentVideoDirectorPlan,
      (state) => getVideoDirectorKeyframeImageUrl(currentShotData, state),
    );
    if (!readiness.planningAllowed) {
      toast.info(readiness.state === 'NO_VISUAL_PLAN'
        ? t('chapterGenerate.planVisualTimelineFirst')
        : t('chapterGenerate.generateRequiredVisualStatesFirst'));
      return;
    }
    setPlanningClipsShotId(currentShotId);
    try {
      const result = await shotsApi.planVideoClips(effectiveNovelId, effectiveChapterId, currentShotId, {
        temporal_anchors: currentVideoDirectorPlan.temporal_anchors || [],
        approval_mode: 'AUTO_APPROVE',
        force,
      });
      if (!result.success || !result.data) {
        throw new Error(result.message || result.detail || t('chapterGenerate.planClipsFailed'));
      }
      const nextPlan: VideoDirectorPlan = {
        ...currentVideoDirectorPlan,
        clip_plan: result.data.clips,
        clip_plan_validation: result.data.validation,
        clip_plan_revision: result.data.revision ?? currentVideoDirectorPlan.clip_plan_revision,
        temporal_anchors: result.data.temporal_anchors ?? currentVideoDirectorPlan.temporal_anchors,
        execution_readiness: result.data.execution_readiness ?? currentVideoDirectorPlan.execution_readiness,
        clip_plan_approval_mode: 'AUTO_APPROVE',
      };
      const refreshed = await shotsApi.getShot(effectiveNovelId, effectiveChapterId, currentShotId);
      if (refreshed.success && refreshed.data) {
        setShots(shotsList.map((shot: any) => (
          String(shot.id) === currentShotId ? { ...shot, ...refreshed.data } : shot
        )));
      } else {
        updateCurrentShotVideoDirectorPlan(nextPlan);
      }
      setSemanticClipTasks([]);
      setSelectedPreviewClipKey(null);
      setSelectedPreviewClipUrl(null);
      if (result.data.validation?.passed) toast.success(t('chapterGenerate.clipPlanReady'));
      else toast.info(t('chapterGenerate.clipPlanNeedsReplan'));
    } catch (error) {
      console.error('视频片段规划失败:', error);
      toast.error(error instanceof Error ? error.message : t('chapterGenerate.planClipsFailed'));
    } finally {
      setPlanningClipsShotId(null);
    }
  }, [currentShotData, currentShotId, currentVideoDirectorPlan, effectiveChapterId, effectiveNovelId, getVideoDirectorKeyframeImageUrl, setShots, shotsList, t, updateCurrentShotVideoDirectorPlan]);

  const acceptPreparationShot = useCallback((fresh: any) => {
    const state = useChapterGenerateStore.getState();
    const tasks = [...state.keyframeTasks];
    const generating = new Set(state.generatingKeyframes);
    const generatingShotsNext = new Set(state.generatingShots);
    for (const item of fresh.videoDirectorPlan?.required_execution_images || []) {
      if (!item.active_task) continue;
      const frame = (fresh.keyframes || []).find((f: any) => Number(f.plan_keyframe_index) === item.state_index);
      if (frame) {
        const next = { shotId: fresh.id, frameIndex: Number(frame.frame_index), taskId: item.active_task.task_id,
          status: item.active_task.status, currentStep: item.active_task.current_step,
          errorMessage: item.active_task.error_message, canonicalImageProvenance: item.provenance };
        const position = tasks.findIndex(t => t.taskId === next.taskId);
        if (position >= 0) tasks[position] = next; else tasks.push(next);
        generating.add(`${fresh.id}-${frame.frame_index}`);
      } else if (item.image_source === 'SHOT_IMAGE') generatingShotsNext.add(fresh.id);
    }
    useChapterGenerateStore.setState({ shots: state.shots.map(shot => shot.id === fresh.id ? { ...shot, ...fresh } : shot),
      keyframeTasks: tasks, generatingKeyframes: generating, generatingShots: generatingShotsNext });
  }, []);
  const prepareShotMaterials = useCallback(async (shot: any) => {
    if (!effectiveNovelId || !effectiveChapterId) return [];
    return prepareCurrentRequiredImages(shot, undefined, undefined, {
      getShot: async () => { const r = await shotsApi.getShot(effectiveNovelId, effectiveChapterId, shot.id); if (!r.success || !r.data) throw new Error('读取分镜失败'); return r.data; },
      prepare: async (revision, clips, states) => { const r = await shotsApi.prepareRequiredImages(effectiveNovelId, effectiveChapterId, shot.id, revision, clips, states); if (!r.success || !r.data) throw new Error('图片准备失败'); return r.data; },
      onShot: acceptPreparationShot,
    });
  }, [effectiveNovelId, effectiveChapterId, acceptPreparationShot]);

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
    if (isCanonicalVisualPlan(sourcePlan)) {
      setGeneratingMissingKeyframesShotId(currentShotId);
      try {
        const results = await prepareShotMaterials(sourceShot);
        const failures = results.filter(item => item.status === 'FAILED');
        if (failures.length) toast.error(failures.map(item => `${item.state_id}: ${item.reason}`).join('；'));
        else toast.success(`图片准备：已提交 ${results.filter(item => item.status === 'QUEUED').length} 个，等待 ${results.filter(item => item.status === 'REUSED').length} 个，复用 ${results.filter(item => item.status === 'READY').length} 张`);
      } catch (error) { toast.error(error instanceof Error ? error.message : '图片准备失败'); }
      finally { setGeneratingMissingKeyframesShotId(null); }
      return;
    }
    const planKeyframes = sourcePlan.keyframes || [];
    const legacyKeyframes = sourceShot.keyframes || [];
    const activeKeyframeTasks = useChapterGenerateStore.getState().keyframeTasks;
    const nonStartPlanKeyframes = planKeyframes.filter((keyframe: any) => (
      keyframe.role !== 'START'
      && (!isCanonicalVisualPlan(sourcePlan)
        || getRequiredMissingCanonicalVisualStates(sourcePlan).some((state) => Number(state.index) === Number(keyframe.index)))
    ));
    const missingLegacyKeyframes = nonStartPlanKeyframes
      .map((keyframe: any, index: number) => {
        const legacyKeyframe = legacyKeyframes.find((item: any) => Number(item.plan_keyframe_index) === Number(keyframe.index));
        const imageUrl = keyframe.image_url || keyframe.imageUrl || legacyKeyframe?.image_url || legacyKeyframe?.imageUrl;
        if (imageUrl && !isCanonicalVisualPlan(sourcePlan)) return null;
        const frameIndex = legacyKeyframe?.frame_index ?? planKeyframes
          .filter((state: any) => state.role !== 'START')
          .findIndex((state: any) => Number(state.index) === Number(keyframe.index));
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
  }, [currentShotData, currentShotId, currentVideoDirectorPlan, effectiveChapterId, effectiveNovelId, generateKeyframeImage, setShots, shotsList, prepareShotMaterials]);

  const handleGenerateVideoKeyframe = useCallback(async (frameIndex: number, mode: 'llm' | 'image_only' = 'llm') => {
    if (!effectiveNovelId || !effectiveChapterId || !currentShotId) return;
    try {
      await generateKeyframeImage(
        effectiveNovelId,
        effectiveChapterId,
        currentShotId,
        frameIndex,
        undefined,
        { skipLlmWhenPromptExists: mode === 'image_only' },
      );
      toast.success(mode === 'image_only' ? '已使用现有提示词提交关键帧图片任务' : '已提交关键帧图片任务');
    } catch (error) {
      console.error('生成关键帧失败:', error);
      toast.error(error instanceof Error ? error.message : '生成关键帧失败');
    }
  }, [currentShotId, effectiveChapterId, effectiveNovelId, generateKeyframeImage]);

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
    setSelectedPreviewClipUrl(null);
    setSemanticClipTasks([]);
    setRegeneratingClipKey(null);
    setShowWorkspaceActionsMenu(false);
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

  useEffect(() => {
    if (!showWorkspaceActionsMenu) return;
    const handleClick = () => setShowWorkspaceActionsMenu(false);
    window.addEventListener('click', handleClick);
    return () => window.removeEventListener('click', handleClick);
  }, [showWorkspaceActionsMenu]);

  const handleGenerateCanonicalShot = async () => {
    if (!effectiveNovelId || !effectiveChapterId || !currentShotId || !currentIsCanonicalPlan) return;
    if (!currentCanonicalReadiness.executionAllowed) {
      toast.info(currentCanonicalExecutionPendingReason || t('chapterGenerate.planClipsFirst'));
      return;
    }
    if (currentSemanticShotStatus === 'ASSEMBLED') {
      toast.info(t('chapterGenerate.finalVideoComplete'));
      return;
    }

    setIsSubmittingCanonicalShot(true);
    useChapterGenerateStore.setState((state) => ({
      pendingVideos: new Set([...state.pendingVideos, currentShotId]),
      shots: state.shots.map((shot: any) => String(shot.id) === currentShotId
        ? { ...shot, videoStatus: 'pending' as const }
        : shot),
    }));
    try {
      const result = await shotsApi.generateVideosBatch(
        effectiveNovelId,
        effectiveChapterId,
        buildSemanticBatchRequest([currentShotId], true),
      );
      if (!result.success) throw new Error(result.detail || result.message || t('chapterGenerate.semanticExecutionFailed'));
      await checkVideoTaskStatus(effectiveChapterId);
      toast.success(result.message || t('chapterGenerate.semanticExecutionSubmitted'));
    } catch (error) {
      useChapterGenerateStore.setState((state) => {
        const pendingVideos = new Set(state.pendingVideos);
        pendingVideos.delete(currentShotId);
        return { pendingVideos };
      });
      console.error('Canonical semantic Shot execution failed:', error);
      toast.error(error instanceof Error ? error.message : t('chapterGenerate.semanticExecutionFailed'));
    } finally {
      setIsSubmittingCanonicalShot(false);
    }
  };

  const handleGenerateVideo = async (mode: 'llm' | 'video_only' = 'llm') => {
    if (!effectiveNovelId || !effectiveChapterId || !currentShotId) return;
    if (!canUseLegacyShotGeneration(currentVideoDirectorPlan)) {
      toast.info(t('chapterGenerate.canonicalExecutionPending'));
      return;
    }
    if (currentVideoKeyframeBlockReason) {
      toast.error(currentVideoKeyframeBlockReason);
      return;
    }
    if (mode === 'video_only' && !hasReusableVideoPrompt) return;

    // MULTI_KEYFRAME needs the #08 window plan before the video task can be queued.
    // Generate it here as well as from the explicit planning action so the main
    // Generate button does not submit a task that the backend must reject.
    if (currentSelectedVideoMode === 'MULTI_KEYFRAME' && !currentVideoDirectorPlan.window_plans?.length) {
      setPlanningKeyframesShotId(currentShotId);
      try {
        const planResult = await shotsApi.planVideoKeyframes(
          effectiveNovelId,
          effectiveChapterId,
          currentShotId,
          true,
        );
        if (!planResult.success || !planResult.data) {
          throw new Error(planResult.message || (planResult as any).detail || '关键帧时间轴规划失败');
        }
        const refreshed = await shotsApi.getShot(effectiveNovelId, effectiveChapterId, currentShotId);
        if (refreshed.success && refreshed.data) {
          setShots(shotsList.map((shot: any) => (
            String(shot.id) === currentShotId ? { ...shot, ...refreshed.data } : shot
          )));
          const missingAfterPlanning = getMissingVideoKeyframeLabels(refreshed.data, refreshed.data.videoDirectorPlan || planResult.data);
          if (missingAfterPlanning.length > 0) {
            toast.info(`关键帧规划已完成，请先生成缺失关键帧图：${missingAfterPlanning.join('、')}`);
            return;
          }
        } else {
          updateCurrentShotVideoDirectorPlan(planResult.data);
          const missingAfterPlanning = getMissingVideoKeyframeLabels(
            { ...currentShotData, videoDirectorPlan: planResult.data },
            planResult.data,
          );
          if (missingAfterPlanning.length > 0) {
            toast.info(`关键帧规划已完成，请先生成缺失关键帧图：${missingAfterPlanning.join('、')}`);
            return;
          }
        }
      } catch (error) {
        console.error('自动关键帧规划失败:', error);
        toast.error(error instanceof Error ? error.message : '关键帧时间轴规划失败');
        return;
      } finally {
        setPlanningKeyframesShotId(null);
      }
    }

    if (currentSelectedVideoMode === 'FIRST_LAST_FRAME' && !currentEndKeyframeImageUrl) {
      toast.error('首尾帧模式需要先生成 END 关键帧图片。');
      return;
    }
    if (hasVideo && !window.confirm(t('chapterGenerate.videoExistsConfirmDelete'))) return;
    setShowGenerateVideoMenu(false);

    try {
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
    setSelectedPreviewClipKey(clip ? getPlanClipKey(clip) : null);
    setSelectedPreviewClipUrl(clip?.video_url || null);
  }, []);

  const handleRegenerateClip = useCallback(async (clip: any, mode: 'llm' | 'video_only' = 'llm') => {
    if (!effectiveNovelId || !effectiveChapterId || !currentShotId) return;
    const windowIndex = Number(clip.window_index || clip.clip_index);
    if (!windowIndex) return;
    const useExistingPrompt = mode === 'video_only';
    if (useExistingPrompt && !String(clip.prompt_text || '').trim()) {
      toast.info(currentIsCanonicalPlan
        ? `片段 ${windowIndex} 缺少可复用的提示词，请先生成片段。`
        : `C${windowIndex} 缺少可复用的视频最终 Prompt，请先使用 LLM+生成Clip视频。`);
      return;
    }
    if (clip.video_url && !window.confirm(`确认重新生成 C${windowIndex}？本次只生成该 Clip，不会自动合并整体视频。`)) return;

    const clipKey = getPlanClipKey(clip);
    setRegeneratingClipKey(clipKey);
    setSelectedPreviewClipKey(clipKey);
    try {
      const result = await shotsApi.generateVideoDirectorClip(effectiveNovelId, effectiveChapterId, currentShotId, windowIndex, {
        use_reference_audio: true,
        auto_merge: false,
        skip_llm_when_prompt_exists: useExistingPrompt,
        clip_plan_revision: Number(currentVideoDirectorPlan.clip_plan_revision || 0),
      });
      if (result.success) {
        regeneratingClipWasActiveRef.current = true;
        useChapterGenerateStore.setState((state) => {
          const nextGeneratingVideos = new Set(state.generatingVideos);
          nextGeneratingVideos.add(currentShotId);
          return {
            generatingVideos: nextGeneratingVideos,
          };
        });
        toast.success(currentIsCanonicalPlan
          ? `片段 ${windowIndex} 已提交${useExistingPrompt ? '使用当前提示词生成' : '生成'}`
          : `C${windowIndex} 已提交${useExistingPrompt ? '仅生成视频' : 'LLM+生成视频'}`);
      } else {
        setRegeneratingClipKey(null);
        toast.error(result.message || result.detail || 'Clip 重新生成失败');
      }
    } catch (error) {
      setRegeneratingClipKey(null);
      console.error('Clip 重新生成失败:', error);
      toast.error('Clip 重新生成失败');
    }
  }, [currentIsCanonicalPlan, currentShotId, effectiveChapterId, effectiveNovelId, currentVideoDirectorPlan.clip_plan_revision]);

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
    setSelectedShots(new Set());
    setBatchFilter('ready');
    setShowBatchSelectModal(true);
  };

  const applyBatchShotSelection = (index: number, mode: 'select' | 'deselect') => {
    const item = batchShotItems.find((candidate) => candidate.shotIndex === index);
    if (!item?.selectable) return;
    setSelectedShots(prev => {
      const next = new Set(prev);
      if (mode === 'select') {
        next.add(index);
      } else {
        next.delete(index);
      }
      return next;
    });
  };

  const handleBatchShotMouseDown = (event: React.MouseEvent, index: number, isSelectable: boolean) => {
    if (event.button !== 0 || !isSelectable) return;
    event.preventDefault();
    const mode = selectedShots.has(index) ? 'deselect' : 'select';
    setDragSelectionMode(mode);
    applyBatchShotSelection(index, mode);
  };

  const handleBatchShotMouseEnter = (index: number, isSelectable: boolean) => {
    if (!dragSelectionMode || !isSelectable) return;
    applyBatchShotSelection(index, dragSelectionMode);
  };

  const handleBatchFilterChange = (filter: BatchShotFilter) => {
    setBatchFilter(filter);
    setSelectedShots(new Set());
  };

  // 全选/取消当前筛选中的可执行 Shot
  const toggleSelectAll = () => {
    if (allVisibleSelectableSelected) {
      setSelectedShots((previous) => {
        const next = new Set(previous);
        selectableVisibleShotIndexes.forEach((index) => next.delete(index));
        return next;
      });
    } else {
      setSelectedShots((previous) => new Set([...previous, ...selectableVisibleShotIndexes]));
    }
  };

  const handleBatchShotNextAction = (shotIndex: number, goToPrimaryImage = false) => {
    const shot = shotsList[shotIndex - 1];
    if (!shot) return;
    handleVideoClick(shotIndex);
    if (goToPrimaryImage) setCurrentTab(1);
    setShowBatchSelectModal(false);
  };

  const selectedBatchShots = executableSelectedIndexes
    .map((index) => shotsList[index - 1])
    .filter(Boolean);
  const selectedSemanticShots = selectedBatchShots.filter((shot: any) => isSemanticShot(shot));
  const selectedSemanticCounts = selectedSemanticShots.reduce((summary, shot: any) => {
    const counts = getSemanticClipCounts(shot, batchShotTasks[String(shot.id)] || []);
    const status = getSemanticShotStatus(shot, batchShotTasks[String(shot.id)] || []);
    return {
      pending: summary.pending + counts.pending,
      reusable: summary.reusable + counts.reusable,
      assembly: summary.assembly + (autoAssemble && status === 'CLIPS_COMPLETE' ? 1 : 0),
    };
  }, { pending: 0, reusable: 0, assembly: 0 });
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
    const selectedShotList = executableSelectedIndexes
      .map(index => shotsList[index - 1])
      .filter((shot) => shot && getBatchShotEligibility(shot).selectable);
    if (!selectedShotList.length) {
      toast.info('没有可生成的视频分镜');
      return;
    }
    const semanticSelected = selectedShotList.filter((shot: any) => isSemanticShot(shot));
    const legacySelected = selectedShotList.filter((shot: any) => (
      !isSemanticShot(shot) && !isCanonicalVisualPlan(shot?.videoDirectorPlan || {})
    ));
    if (legacySelected.some(hasShotVideo) && !window.confirm('所选 Shot 已有视频，是否继续执行 legacy 批量生成？')) return;
    if (semanticSelected.some((shot: any) => {
      const status = getSemanticShotStatus(shot, batchShotTasks[String(shot.id)] || []);
      return ['PARTIAL', 'FAILED', 'CLIPS_COMPLETE'].includes(status);
    }) && !window.confirm('所选 Shot 已有部分或全部 Clip 结果。批量任务会复用当前版本的有效结果，只执行缺失或失败的 Clip。是否继续？')) return;

    setIsGeneratingAll(true);
    setShowBatchSelectModal(false);
    const selectedShotIds = selectedShotList.map((shot: any) => String(shot.id)).filter(Boolean);
    useChapterGenerateStore.setState((state) => ({
      pendingVideos: new Set([...state.pendingVideos, ...selectedShotIds]),
      shotVideos: Object.fromEntries(Object.entries(state.shotVideos).filter(([key]) => !selectedShotIds.includes(key))),
      shots: state.shots.map((shot: any) => (
        selectedShotIds.includes(String(shot.id))
          ? { ...shot, videoStatus: 'pending' as const, videoUrl: null }
          : shot
      )),
    }));
    try {
      const request = semanticSelected.length === selectedShotList.length
        ? buildSemanticBatchRequest(selectedShotIds, autoAssemble)
        : {
          shot_ids: selectedShotIds,
          auto_complete_details: autoCompleteDetails,
          use_reference_audio: true,
          skip_llm_when_prompt_exists: false,
          force_rerun: semanticSelected.length > 0 ? false : true,
          auto_assemble: autoAssemble,
        };
      const result = await shotsApi.generateVideosBatch(effectiveNovelId, effectiveChapterId, request);
      if (!result.success) {
        throw new Error(result.detail || result.message || '批量生成视频失败');
      }
      await checkVideoTaskStatus(effectiveChapterId);
      toast.success(result.message || `已创建 ${selectedShotIds.length} 个持久化分镜视频任务`);
    } catch (error) {
      console.error(t('chapterGenerate.batchVideoGenerateFailed') + ':', error);
      const errorMessage = formatUserFacingError(error instanceof Error ? error.message : '批量生成视频失败');
      useChapterGenerateStore.setState((state) => {
        const nextPendingVideos = new Set(state.pendingVideos);
        selectedShotIds.forEach((shotId) => nextPendingVideos.delete(shotId));
        return {
          pendingVideos: nextPendingVideos,
          shots: state.shots.map((shot: any) => selectedShotIds.includes(String(shot.id))
            ? { ...shot, videoStatus: shot.videoUrl ? 'completed' as const : 'pending' as const }
            : shot),
        };
      });
      toast.error(errorMessage || '批量生成视频失败');
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
      const updatePayload = buildVideoDirectorShotSavePayload(currentShotData);
      const result = await shotsApi.batchUpdateShots(effectiveNovelId, effectiveChapterId, [updatePayload]);

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

  const handleDownloadVideoMaterials = async () => {
    if (!effectiveNovelId || !effectiveChapterId || !currentShotId) return;
    setIsDownloadingVideoMaterials(true);
    try {
      await shotsApi.downloadShotVideoMaterialsPackage(effectiveNovelId, effectiveChapterId, currentShotId);
      toast.success('视频素材包已开始下载');
    } catch (error) {
      console.error('下载视频素材失败:', error);
      toast.error(error instanceof Error ? error.message : '下载视频素材失败');
    } finally {
      setIsDownloadingVideoMaterials(false);
    }
  };

  const handleResetShotVideoData = async () => {
    if (!effectiveNovelId || !effectiveChapterId || !currentShotId) return;
    setIsResettingVideoData(true);
    try {
      await shotsApi.resetShotVideoData(effectiveNovelId, effectiveChapterId, currentShotId);
      const refreshed = await shotsApi.getShot(effectiveNovelId, effectiveChapterId, currentShotId);
      if (refreshed.success && refreshed.data) {
        setShots(shotsList.map((shot: any) => String(shot.id) === currentShotId ? { ...shot, ...refreshed.data } : shot));
      }
      setShotVideos((prev) => { const next = { ...prev }; delete next[currentShotId]; return next; });
      setShowResetVideoDataConfirm(false);
      toast.success('当前 Shot 视频阶段已重置');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '重置当前 Shot 视频数据失败');
    } finally {
      setIsResettingVideoData(false);
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
  const currentCanonicalPrimaryAction = currentIsCanonicalPlan ? (() => {
    if (isGeneratingCurrent || isCurrentVideoPending || isSubmittingCanonicalShot) {
      return { label: isCurrentVideoPending ? '队列中…' : '生成中…', disabled: true, onClick: () => undefined };
    }
    if (currentSemanticShotStatus === 'ASSEMBLED') {
      return {
        label: '查看最终视频',
        disabled: !currentFinalShotVideoUrl,
        onClick: () => {
          setSelectedPreviewClipKey(null);
          setSelectedPreviewClipUrl(null);
          window.requestAnimationFrame(() => {
            previewVideoRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
            previewVideoRef.current?.play().catch(() => undefined);
          });
        },
      };
    }
    if (currentCanonicalReadiness.state === 'NO_VISUAL_PLAN') {
      return { label: '规划视觉时间轴', disabled: planningKeyframesShotId === currentShotId, onClick: () => handlePlanVideoKeyframes(false) };
    }
    if (currentCanonicalReadiness.state === 'REQUIRED_IMAGES_MISSING') {
      return { label: '生成必需状态图片', disabled: generatingMissingKeyframesShotId === currentShotId, onClick: handleGenerateMissingKeyframes };
    }
    if (currentCanonicalReadiness.state === 'CLIP_PLAN_MISSING' || currentCanonicalReadiness.state === 'CLIP_PLAN_STALE') {
      const isStale = currentCanonicalReadiness.state === 'CLIP_PLAN_STALE';
      return { label: isStale ? '重新规划视频片段' : '规划视频片段', disabled: planningClipsShotId === currentShotId, onClick: () => handlePlanSemanticClips(isStale) };
    }
    if (currentCanonicalReadiness.state === 'GENERATE_VISUAL_START_MISSING') {
      const stateIndex = currentCanonicalReadiness.missingVisualStateIndex;
      return { label: stateIndex ? `生成视觉状态 ${stateIndex}` : '生成片段起始视觉图', disabled: generatingMissingKeyframesShotId === currentShotId, onClick: handleGenerateMissingKeyframes };
    }
    if (currentSemanticShotStatus === 'CLIPS_COMPLETE') {
      return { label: '合并最终视频', disabled: isMergingClips, onClick: handleMergeDirectorClips };
    }
    if (currentSemanticShotStatus === 'FAILED') {
      return { label: '重试当前 Shot', disabled: isCurrentVideoGenerateDisabled, onClick: handleGenerateCanonicalShot };
    }
    return { label: '生成当前 Shot 视频', disabled: isCurrentVideoGenerateDisabled, onClick: handleGenerateCanonicalShot };
  })() : null;

  return (
    <div className="h-full flex flex-col">
      {currentVideoErrorMessage && (
        <div className="mx-8 mb-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          <div className="font-medium">视频生成失败</div>
          <div className="mt-1 whitespace-pre-wrap break-words">{currentVideoErrorMessage}</div>
        </div>
      )}
      {/* Canonical Shot production header */}
      <div
        data-testid="canonical-production-header"
        className="mb-2 flex-shrink-0 border-b border-gray-200 px-4 pb-3 xl:px-8"
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-[240px] flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-semibold text-gray-900">Shot {selectedVideo || 0}</span>
              <span className="text-xs tabular-nums text-gray-500">{Number(currentShotData?.duration || 0)} 秒</span>
              <span className={`rounded-full border px-2 py-0.5 text-xs font-medium ${currentShotVideoResult.className}`}>
                {currentShotVideoResult.label}
              </span>
            </div>
            <div className="mt-1 text-xs text-gray-600" title={currentShotVideoResult.detail}>
              {currentShotVideoResult.detail}
            </div>
            {currentIsCanonicalPlan && currentOptionalMissingVisualStateCount > 0 && (
              <div className="mt-1 text-xs text-gray-500">
                {getCanonicalVisualStates(currentVideoDirectorPlan).length} 个视觉状态 · {t('chapterGenerate.optionalMissingStates', { count: currentOptionalMissingVisualStateCount })}
              </div>
            )}
          </div>

          <div className="flex flex-wrap items-center justify-end gap-2">
            {currentCanonicalPrimaryAction && (
              <button
                type="button"
                data-testid="canonical-primary-action"
                onClick={currentCanonicalPrimaryAction.onClick}
                disabled={currentCanonicalPrimaryAction.disabled}
                className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {(isGeneratingCurrent || isCurrentVideoPending || isSubmittingCanonicalShot) ? <Loader2 className="h-4 w-4 animate-spin" /> : <Film className="h-4 w-4" />}
                {currentCanonicalPrimaryAction.label}
              </button>
            )}
            <button
              type="button"
              onClick={handleOpenBatchSelect}
              disabled={!effectiveChapterId}
              className="rounded-lg border border-green-300 bg-white px-3 py-2 text-sm font-medium text-green-700 transition-colors hover:bg-green-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              批量生成视频
            </button>
            <div className="relative">
              <button
                type="button"
                onClick={(event) => {
                  event.stopPropagation();
                  setShowWorkspaceActionsMenu((open) => !open);
                }}
                className="inline-flex items-center gap-1 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                aria-expanded={showWorkspaceActionsMenu}
              >
                更多
                <ChevronDown className="h-4 w-4" />
              </button>
              {showWorkspaceActionsMenu && (
                <div className="absolute right-0 top-full z-[90] mt-1 w-56 overflow-hidden rounded-lg border border-gray-200 bg-white py-1 shadow-xl">
                  <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-gray-400">生产与下载</div>
                  <button type="button" onClick={() => { setShowWorkspaceActionsMenu(false); handleOpenMergeSelect(); }} disabled={mergingMode !== null || !effectiveChapterId || videoCount === 0} className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-40">
                    {mergingMode ? <Loader2 className="h-4 w-4 animate-spin" /> : <Combine className="h-4 w-4" />}
                    {mergingMode ? '提交任务中...' : t('chapterGenerate.mergeVideo')}
                  </button>
                  <button type="button" onClick={() => { setShowWorkspaceActionsMenu(false); handleDownloadMaterials(); }} disabled={isDownloading || !effectiveChapterId} className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-40">
                    {isDownloading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                    {isDownloading ? t('chapterGenerate.packing') : '导出章节素材包'}
                  </button>
                  <button type="button" onClick={() => { setShowWorkspaceActionsMenu(false); handleDownloadVideoMaterials(); }} disabled={isDownloadingVideoMaterials || !effectiveChapterId || !currentShotId} className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-40">
                    {isDownloadingVideoMaterials ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                    {isDownloadingVideoMaterials ? '打包中...' : '导出 Shot 生产包'}
                  </button>
                  <div className="my-1 border-t border-gray-100" />
                  <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-gray-400">恢复操作</div>
                  {isGeneratingCurrent && (
                    <button type="button" onClick={() => { setShowWorkspaceActionsMenu(false); handleCancelCurrentVideo(); }} disabled={isCancellingVideo || !effectiveChapterId} className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-red-700 hover:bg-red-50 disabled:opacity-40">
                      <Square className="h-4 w-4" />
                      {isCancellingVideo ? t('chapterGenerate.cancellingVideo') : t('chapterGenerate.cancelVideoGeneration')}
                    </button>
                  )}
                  {!currentIsCanonicalPlan && (
                    <button type="button" onClick={() => { setShowWorkspaceActionsMenu(false); setShowResetVideoDataConfirm(true); }} disabled={!effectiveChapterId || !currentShotId || isGeneratingCurrent || isCurrentVideoPending} className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-red-700 hover:bg-red-50 disabled:opacity-40" title="清除当前 Shot 的视频、关键帧、Clip 任务和执行计划">
                      <Trash2 className="h-4 w-4" />
                      重置视频阶段
                    </button>
                  )}
                </div>
              )}
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
            isPlanningClips={planningClipsShotId === currentShotId}
            onRecommend={handleRecommendVideoMode}
            onPlanKeyframes={handlePlanVideoKeyframes}
            onPlanClips={handlePlanSemanticClips}
            onGenerateMissingKeyframes={handleGenerateMissingKeyframes}
            onGenerateKeyframe={handleGenerateVideoKeyframe}
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
            semanticClipPlan={currentVideoDirectorPlan.clip_plan}
            semanticClipPlanShot={currentShotData}
            semanticShotStatus={currentSemanticShotStatus}
            onSemanticClipTasksChange={setSemanticClipTasks}
            chapterId={effectiveChapterId}
            novelId={effectiveNovelId}
            onPreparationShot={acceptPreparationShot}
          />

        </div>

        {/* 右侧：视频预览 + AI 调用结果 */}
        <div className="flex-shrink-0 lg:w-[360px] xl:w-[420px] min-h-0 flex flex-col gap-3 overflow-hidden">
        <div className="video-preview-card h-[360px] flex-shrink-0 flex flex-col border border-gray-200 rounded-lg overflow-hidden bg-white">
          <div className="flex-shrink-0 p-3 border-b border-gray-200 bg-gray-50 flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-gray-800">{selectedPreviewClip ? `片段预览 · ${previewVideoLabel}` : '最终 Shot 视频'}</h3>
              {selectedPreviewClip && <div className="text-xs text-gray-500">C{selectedPreviewClip.window_index || selectedPreviewClip.clip_index} · {selectedPreviewClip.start_time}-{selectedPreviewClip.end_time}s</div>}
              {!selectedPreviewClip && currentFinalShotVideoUrl && <div className="text-xs text-green-700">当前权威合并结果</div>}
            </div>
            <div className="flex items-center gap-1">
              {selectedPreviewClip && (
                <button
                  type="button"
                  onClick={() => { setSelectedPreviewClipKey(null); setSelectedPreviewClipUrl(null); }}
                  className="rounded-md px-2 py-1 text-xs text-blue-700 hover:bg-blue-50"
                >
                  返回最终视频
                </button>
              )}
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
                  <p>{currentIsCanonicalPlan && currentCanonicalPrimaryAction
                    ? `下一步：${currentCanonicalPrimaryAction.label.replace(/…$/, '')}`
                    : t('chapterGenerate.clickToGenerateVideo')}</p>
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
        {!currentIsHistoricalPlan && (
          <VideoAiCallsPanel
            calls={currentVideoDirectorPlan.ai_calls || []}
            novelId={effectiveNovelId}
            chapterId={effectiveChapterId}
            shotId={currentShotId}
            onRefresh={handleRefreshAiCalls}
            isRefreshing={isRefreshingAiCalls}
          />
        )}
        </div>

      </div>

      {showResetVideoDataConfirm && createPortal(
        <div
          className="fixed inset-0 z-[300] flex items-center justify-center bg-black/50 p-4"
          onClick={() => !isResettingVideoData && setShowResetVideoDataConfirm(false)}
        >
          <div
            className="w-full max-w-lg rounded-xl bg-white p-6 shadow-2xl"
            role="dialog"
            aria-modal="true"
            aria-labelledby="reset-shot-video-title"
            onClick={(event) => event.stopPropagation()}
          >
            <h2 id="reset-shot-video-title" className="text-lg font-semibold text-gray-900">重置当前 Shot 视频阶段？</h2>
            <p className="mt-3 text-sm leading-6 text-gray-600">
              将删除当前 Shot 的视频、关键帧图片、Clip Tasks、Clip 执行计划和 Assembly 数据。Shot 主图、描述、台词及角色/场景/道具关联会保留。此操作不可撤销。
            </p>
            <div className="mt-6 flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setShowResetVideoDataConfirm(false)}
                disabled={isResettingVideoData}
                className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
              >取消</button>
              <button
                type="button"
                onClick={handleResetShotVideoData}
                disabled={isResettingVideoData}
                className="inline-flex items-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
              >
                {isResettingVideoData && <Loader2 className="h-4 w-4 animate-spin" />}
                {isResettingVideoData ? '正在重置...' : '确认重置'}
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}

      {/* 批量选择分镜弹窗 */}
      {showBatchSelectModal && createPortal((
        <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/50 p-4">
          <div className="flex max-h-[86vh] w-full max-w-5xl flex-col rounded-xl bg-white shadow-xl">
            <div className="flex items-start justify-between border-b border-gray-200 px-5 py-4">
              <div>
                <h3 className="text-lg font-semibold text-gray-800">{t('chapterGenerate.selectShotsToGenerate')}</h3>
                <p className="mt-1 text-xs text-gray-500">按生产状态筛选，只能选择当前执行权威判定为可执行的 Shot。</p>
              </div>
              <button
                onClick={() => setShowBatchSelectModal(false)}
                className="p-2 hover:bg-gray-100 rounded-full transition-colors"
                title={t('common.close')}
              >
                <X className="w-5 h-5 text-gray-500" />
              </button>
            </div>

            <div className="border-b border-gray-100 px-5 py-4">
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7" aria-label="Batch Shot 状态筛选">
                {BATCH_CATEGORY_META.map((category) => {
                  const isActive = batchFilter === category.key;
                  return (
                    <button
                      key={category.key}
                      type="button"
                      data-batch-category={category.key}
                      onClick={() => handleBatchFilterChange(category.key)}
                      className={`flex items-center justify-between rounded-lg border px-3 py-2 text-sm transition-colors ${isActive ? category.activeClassName : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300 hover:bg-gray-50'}`}
                    >
                      <span className="font-medium">{category.label}</span>
                      <span className={`ml-2 min-w-6 rounded-full px-1.5 py-0.5 text-center text-xs tabular-nums ${isActive ? category.countClassName : 'bg-gray-100 text-gray-600'}`}>
                        {batchCategoryCounts[category.key]}
                      </span>
                    </button>
                  );
                })}
                <button
                  type="button"
                  data-batch-category="all"
                  onClick={() => handleBatchFilterChange('all')}
                  className={`flex items-center justify-between rounded-lg border px-3 py-2 text-sm transition-colors ${batchFilter === 'all' ? 'border-slate-400 bg-slate-100 text-slate-800' : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300 hover:bg-gray-50'}`}
                >
                  <span className="font-medium">全部</span>
                  <span className="ml-2 min-w-6 rounded-full bg-gray-100 px-1.5 py-0.5 text-center text-xs tabular-nums text-gray-600">{batchShotItems.length}</span>
                </button>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto px-5 py-4">
              <section data-testid="batch-material-preparation" className="mb-4 rounded-lg border border-amber-200 p-3">
                <h4 className="text-sm font-semibold">素材准备</h4>
                <p className="my-1 text-xs text-gray-600">可选择缺准备的分镜。只准备当前片段计划的必需图片；素材已准备后，请手动选择并点击原有“批量生成视频”。</p>
                {shotsList.filter((shot: any) => canPrepareMaterials(shot)).map((shot: any) => (
                  <div key={shot.id} className="my-2">
                    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={materialShotIds.has(shot.id)} disabled={preparingMaterials} onChange={() => setMaterialShotIds(current => { const next = new Set(current); if (next.has(shot.id)) next.delete(shot.id); else next.add(shot.id); return next; })} />Shot #{shot.index} · Revision {shot.videoDirectorPlan.clip_plan_revision}</label>
                    <RequiredImagesPreparation shot={shot} novelId={effectiveNovelId} chapterId={effectiveChapterId} onShot={acceptPreparationShot} hidePrepare />
                  </div>
                ))}
                <button type="button" disabled={preparingMaterials || !materialShotIds.size} onClick={async () => {
                  setPreparingMaterials(true); setMaterialResults([]);
                  const report: string[] = [];
                  try {
                    for (const id of materialShotIds) {
                      const shot = useChapterGenerateStore.getState().shots.find(s => s.id === id);
                      if (!shot) continue;
                      try {
                        const items = await prepareShotMaterials(shot);
                        report.push(...items.map(item => `Shot #${shot.index} · ${item.state_id} · ${item.status}${item.reason ? `：${item.reason}` : ''}`));
                      } catch (error) { report.push(`Shot #${shot.index}：${error instanceof Error ? error.message : '准备失败'}`); }
                      setMaterialResults([...report]);
                    }
                  } finally { setPreparingMaterials(false); }
                }} className="mt-2 rounded border border-amber-300 bg-white px-3 py-1.5 text-sm text-amber-800 disabled:opacity-50">{preparingMaterials ? '正在提交图片…' : '生成全部必需视觉状态图'}</button>
                {materialResults.map((result, i) => <p key={i} className="mt-1 text-xs text-gray-600">{result}</p>)}
              </section>

              <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                <span className="text-sm text-gray-600">
                  当前筛选 {visibleBatchShotItems.length} 个 · 可选择 {selectableVisibleShotIndexes.length} 个 · 已选择 {executableSelectedIndexes.length} 个
                  {selectedSemanticShots.length > 0 && ` · 待执行 Clip ${selectedSemanticCounts.pending} · 可复用 ${selectedSemanticCounts.reusable}${autoAssemble ? ` · 待合并 Shot ${selectedSemanticCounts.assembly}` : ''}`}
                </span>
                <button
                  type="button"
                  onClick={toggleSelectAll}
                  disabled={selectableVisibleShotIndexes.length === 0}
                  className="flex items-center gap-1.5 text-sm font-medium text-blue-700 transition-colors hover:text-blue-900 disabled:cursor-not-allowed disabled:text-gray-400"
                >
                  {allVisibleSelectableSelected ? <Check className="h-4 w-4" /> : <Square className="h-4 w-4" />}
                  {allVisibleSelectableSelected ? '取消当前筛选全选' : `全选当前筛选（${selectableVisibleShotIndexes.length}）`}
                </button>
              </div>

              {visibleBatchShotItems.length === 0 ? (
                <div className="rounded-xl border border-dashed border-gray-300 bg-gray-50 px-6 py-10 text-center">
                  <Film className="mx-auto h-10 w-10 text-gray-300" />
                  <div className="mt-3 text-sm font-semibold text-gray-800">
                    {batchFilter === 'ready' ? '当前没有可生成的 Shot' : '当前分类没有 Shot'}
                  </div>
                  {batchFilter === 'ready' && (
                    <>
                      <p className="mt-2 text-sm text-gray-600">
                        已完成 {batchCategoryCounts.completed} 个，缺准备 {batchCategoryCounts.missing_preparation} 个。可切换分类查看结果或阻塞原因。
                      </p>
                      <div className="mt-4 flex justify-center gap-2">
                        <button type="button" onClick={() => handleBatchFilterChange('completed')} className="rounded-lg border border-emerald-200 bg-white px-3 py-2 text-sm text-emerald-700 hover:bg-emerald-50">查看已完成</button>
                        <button type="button" onClick={() => handleBatchFilterChange('missing_preparation')} className="rounded-lg border border-amber-200 bg-white px-3 py-2 text-sm text-amber-700 hover:bg-amber-50">查看缺准备</button>
                      </div>
                    </>
                  )}
                </div>
              ) : (
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  {visibleBatchShotItems.map((item) => {
                    const { shot, shotIndex } = item;
                    const isSelected = executableSelectedSet.has(shotIndex);
                    const thumbnailUrl = getShotImageUrl(shot);
                    const statusMeta = BATCH_CATEGORY_META.find((category) => category.key === item.category)!;
                    const missingPrimaryImage = item.category === 'missing_preparation' && item.reason.includes('主分镜图');

                    return (
                      <div
                        key={shot.id || `shot-${shotIndex}`}
                        data-batch-shot-category={item.category}
                        onMouseDown={(event) => handleBatchShotMouseDown(event, shotIndex, item.selectable)}
                        onMouseEnter={() => handleBatchShotMouseEnter(shotIndex, item.selectable)}
                        title={item.reason}
                        className={`flex min-h-[116px] select-none overflow-hidden rounded-xl border-2 transition-all ${item.selectable ? 'cursor-pointer hover:shadow-md' : 'border-gray-200 bg-gray-50'} ${item.selectable && isSelected ? 'border-blue-500 bg-blue-50' : item.selectable ? 'border-gray-300 bg-white hover:border-blue-300' : ''}`}
                      >
                        <div className="relative w-36 flex-none bg-gray-100">
                          {thumbnailUrl ? (
                            <img src={thumbnailUrl} alt={`Shot ${shot.index || shotIndex}`} className="h-full w-full object-cover" />
                          ) : (
                            <div className="flex h-full min-h-[116px] items-center justify-center"><Film className="h-8 w-8 text-gray-300" /></div>
                          )}
                          <span className="absolute left-2 top-2 rounded bg-black/65 px-1.5 py-0.5 text-xs font-medium text-white">Shot #{shot.index || shotIndex}</span>
                        </div>
                        <div className="flex min-w-0 flex-1 flex-col p-3">
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                              <div className="flex flex-wrap items-center gap-2">
                                <span className={`rounded-full border px-2 py-0.5 text-xs font-medium ${statusMeta.activeClassName}`}>{statusMeta.label}</span>
                                <span className="text-xs tabular-nums text-gray-500">{Number(shot.duration || 0)}s</span>
                              </div>
                              <p className={`mt-2 line-clamp-2 text-sm ${item.category === 'failed' ? 'text-red-700' : 'text-gray-600'}`}>{item.reason}</p>
                            </div>
                            {item.selectable && (
                              <span className={`flex h-6 w-6 flex-none items-center justify-center rounded-full ${isSelected ? 'bg-blue-600' : 'bg-gray-200'}`} aria-label={isSelected ? '已选择' : '未选择'}>
                                {isSelected && <Check className="h-3.5 w-3.5 text-white" />}
                              </span>
                            )}
                          </div>
                          <div className="mt-auto flex items-end justify-between gap-3 pt-3">
                            <span className="text-xs text-gray-400">
                              {item.selectable ? (item.retry ? '点击选择重试' : '点击选择生成') : '不可提交'}
                            </span>
                            {(item.category === 'completed' || item.category === 'missing_preparation') && (
                              <button
                                type="button"
                                onClick={() => handleBatchShotNextAction(shotIndex, missingPrimaryImage)}
                                className="rounded-md border border-gray-200 bg-white px-2.5 py-1 text-xs font-medium text-gray-700 hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700"
                              >
                                {missingPrimaryImage ? '去生成主图' : '查看当前 Shot'}
                              </button>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="border-t border-gray-200 bg-gray-50 px-5 py-4">
              {legacyCompatibilityVisible && (
                <details className="mb-3 rounded-lg border border-gray-200 bg-white px-3 py-2">
                  <summary className="cursor-pointer text-sm font-medium text-gray-700">高级兼容设置（legacy Shot）</summary>
                  <label className="mt-3 flex cursor-pointer select-none items-start gap-2 text-sm text-gray-700">
                    <input
                      type="checkbox"
                      checked={autoCompleteDetails}
                      onChange={(event) => {
                        setAutoCompleteDetails(event.target.checked);
                        setSelectedShots(new Set());
                      }}
                      className="mt-0.5 h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    />
                    <span>自动完成细节（仅 legacy Shot）<span className="block text-[11px] text-gray-500">只影响历史兼容 Shot；canonical Shot 始终使用 Semantic Batch 权威。</span></span>
                  </label>
                </details>
              )}
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div>
                  <label className="flex cursor-pointer select-none items-start gap-2 text-sm text-gray-700">
                    <input type="checkbox" checked={autoAssemble} onChange={(event) => setAutoAssemble(event.target.checked)} className="mt-0.5 h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500" />
                    <span>生成完成后自动合并 Shot <span className="block text-[11px] text-gray-500">每个 Shot 的全部 Clip 完成后生成最终视频。</span></span>
                  </label>
                  {executableSelectedIndexes.length === 0 && <p className="mt-2 text-xs text-gray-500">请先从“可生成”或可重试的“失败”分类中选择 Shot。</p>}
                </div>
                <div className="flex items-center justify-end gap-3">
                <button
                  onClick={() => setShowBatchSelectModal(false)}
                  className="px-4 py-2 text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors"
                >
                  {t('common.cancel')}
                </button>
                <button
                  onClick={handleGenerateAll}
                  disabled={executableSelectedIndexes.length === 0 || isGeneratingAll}
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
                      {selectedFailedCount === executableSelectedIndexes.length && selectedFailedCount > 0
                        ? `重试 ${selectedFailedCount} 个失败 Shot`
                        : `生成 ${executableSelectedIndexes.length} 个 Shot`}
                    </>
                  )}
                </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      ), document.body)}

      {/* 合并视频选择弹窗 */}
      {showMergeSelectModal && createPortal((
        <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/50 p-4">
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
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[200] p-4">
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
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
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
