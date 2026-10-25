import { CandidateResultSummary } from './CandidateResultSummary';
import {
  CheckCircle, XCircle, Loader2, Clock, AlertCircle,
  Terminal, ChevronUp, ChevronDown, Play, Code, Trash2, Film, Image as ImageIcon, User, ListTodo, Music, Copy
} from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import type { Task, VideoDirectorTaskClip } from '../../../types';
import { useState } from 'react';
import { toast } from '../../../stores/toastStore';
import type { ImageInfo } from '../types';
import { formatUserFacingError } from '../../../utils';
import { formatAspectRatio } from '../../../utils/aspectRatio';
import { WaveformAudioPlayer } from '../../../components/WaveformAudioPlayer';

interface TaskCardProps {
  task: Task;
  imageInfo: Record<string, ImageInfo>;
  expandedErrors: Set<string>;
  onDelete: (id: string) => void;
  onRetry: (id: string) => void;
  onViewWorkflow: (task: Task) => void;
  onImageReview: (task: Task) => void;
  onViewClipWorkflow: (task: Task, clip: VideoDirectorTaskClip) => void;
  onToggleError: (id: string) => void;
  onPreviewImage: (url: string) => void;
  onPreviewImages: (images: Array<{ label?: string; url: string }>, index: number) => void;
  onPreviewVideo: (url: string) => void;
  onNameplateApproved: () => void;
  fetchImageInfo: (url: string, taskId: string) => void;
  getTaskDisplayName: (task: Task) => string;
  getTaskDisplayDescription: (task: Task) => string;
  getTaskTypeName: (type: Task['type']) => string;
  getWorkflowDisplayName: (task: Task) => string;
  getStatusIcon: (status: Task['status']) => JSX.Element;
  getStatusText: (status: Task['status']) => string;
  getStatusColor: (status: Task['status']) => string;
  formatDate: (dateStr: string) => string;
}

const preflightCheckLabels: Record<string, string> = {
  SHOT_EXISTS: '分镜归属',
  SHOT_IMAGE_READY: '主分镜图',
  CLIP_PLAN_READY: '片段计划',
  TASK_RELATION_VALID: '任务关系',
  ACTIVE_VIDEO_TASK: '重复执行',
  IDENTITY_FEATURES_RECORDED: '人物稳定特征',
  IDENTITY_PORTRAIT_READY: '人物参考图',
};

function backgroundMusicFilename(task: Task): string {
  const chapter = task.chapterTitle?.trim() || (task.chapterNumber != null ? `第${task.chapterNumber}章` : '章回');
  const name = [task.novelName?.trim() || '小说', chapter, '背景音乐'].join('-')
    .replace(/[\\/:*?"<>|：\x00-\x1f]/g, '-')
    .replace(/-+/g, '-')
    .replace(/^[. -]+|[. -]+$/g, '')
    .slice(0, 150);
  return `${name}.m4a`;
}

function videoErrorCategory(message?: string | null, currentStep?: string | null): string | null {
  if (!message) return null;
  if (message.includes('GENERATION_PREFLIGHT_FAILED')) {
    const checkId = Object.keys(preflightCheckLabels).find(id => message.includes(id));
    return checkId ? `视频生成预检 · ${preflightCheckLabels[checkId]}` : '视频生成预检';
  }
  if (currentStep === '已完成视频回执接受失败' || message.includes('CLIP_RECEIPT_ACCEPTANCE_')) {
    return '视频生成预检 · 已完成 Clip 回执接受';
  }
  if (currentStep === 'Clip 结果恢复被拒绝' || message.includes('CLIP_RECOVERY_')
      || message.includes('CANONICAL_RECOVERY_CONFLICT')) {
    return '视频生成预检 · Clip 结果恢复与回写';
  }
  if (message.includes('PREVIOUS_AV_BINDING_UNVERIFIED')) return '执行阶段 · 续接工作流绑定';
  if (message.includes('PHASE_B_INPUT_NOT_COVERED')) return '执行阶段 · H3 Phase B 输入';
  if (message.includes('H3_PROMPT_LANGUAGE_MISMATCH')) return '执行阶段 · 提示词语言一致性';
  if (message.includes('PHASE_B_PREFLIGHT_FAILED')) return '执行阶段 · 提示词结构校验';
  return null;
}

type RecoveryMismatch = { field: string; expected?: unknown; actual?: unknown };

function clipRecoveryPlanMismatches(message?: string | null): RecoveryMismatch[] | null {
  const prefix = 'CLIP_RECOVERY_PLAN_CHANGED:';
  if (!message?.startsWith(prefix)) return null;
  try {
    const parsed: unknown = JSON.parse(message.slice(prefix.length));
    return Array.isArray(parsed) && parsed.every(item => item && typeof item.field === 'string')
      ? parsed as RecoveryMismatch[] : null;
  } catch {
    return null;
  }
}

const recoveryFieldLabels: Record<string, string> = {
  clip: '片段是否存在',
  clip_plan_revision: '片段计划版本',
  'execution_contract.clip.clip_index': '执行合同中的片段序号',
  'execution_contract.clip.clip_plan_revision': '执行合同中的计划版本',
  effective_capability: '实际执行类型',
  generated_by_task_id: '当前结果归属任务',
};

function detailValue(value: unknown): string {
  if (value == null || value === '') return '无';
  return typeof value === 'string' ? value : JSON.stringify(value);
}

function formatElapsedDuration(seconds: number): string {
  if (seconds <= 60) return `${seconds} 秒`;
  return `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
}

export function TaskCard({
  task,
  imageInfo,
  expandedErrors,
  onDelete,
  onRetry,
  onViewWorkflow,
  onImageReview,
  onViewClipWorkflow,
  onToggleError,
  onPreviewImage,
  onPreviewImages,
  onPreviewVideo,
  onNameplateApproved,
  fetchImageInfo,
  getTaskDisplayName,
  getTaskDisplayDescription,
  getTaskTypeName,
  getWorkflowDisplayName,
  getStatusIcon,
  getStatusText,
  getStatusColor,
  formatDate,
}: TaskCardProps) {
  const { t } = useTranslation();
  const [approvingNameplate, setApprovingNameplate] = useState(false);
  const [nameplatePreviewOpened, setNameplatePreviewOpened] = useState(false);

  const approveNameplate = async () => {
    if (!task.novelId || !task.chapterId) return;
    setApprovingNameplate(true);
    try {
      const response = await fetch(
        `/api/novels/${task.novelId}/chapters/${task.chapterId}/nameplate-preview/${task.id}/approve`,
        { method: 'POST' },
      );
      const result = await response.json();
      if (!response.ok || !result.success) throw new Error(result.detail || '确认姓名牌失败');
      toast.success('已将主角姓名牌预览用于章回成片');
      onNameplateApproved();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '确认姓名牌失败');
    } finally {
      setApprovingNameplate(false);
    }
  };

  const getTaskIcon = (type: Task['type']) => {
    switch (type) {
      case 'character_portrait': return <User className="h-5 w-5" />;
      case 'prop_image': return <ImageIcon className="h-5 w-5" />;
      case 'shot_image': return <ImageIcon className="h-5 w-5" />;
      case 'shot_image_repair':
      case 'shot_image_repair_candidate': return <ImageIcon className="h-5 w-5" />;
      case 'keyframe_image': return <ImageIcon className="h-5 w-5" />;
      case 'single_image_edit': return <ImageIcon className="h-5 w-5" />;
      case 'novel_video_cover': return <ImageIcon className="h-5 w-5" />;
      case 'character_audio':
      case 'narrator_audio':
      case 'chapter_background_music': return <Music className="h-5 w-5" />;
      case 'shot_video':
      case 'shot_video_hd':
      case 'shot_video_hd_batch':
      case 'chapter_video':
      case 'transition_video':
      case 'novel_video': return <Film className="h-5 w-5" />;
      default: return <ListTodo className="h-5 w-5" />;
    }
  };

  const getElapsedSeconds = () => {
    if (task.status !== 'completed' || !task.completedAt) return null;
    const startValue = task.startedAt || task.createdAt;
    if (!startValue) return null;
    const parseDate = (value: string) => new Date(value.replace(/\//g, '-')).getTime();
    const startedAt = parseDate(startValue);
    const completedAt = parseDate(task.completedAt);
    if (!Number.isFinite(startedAt) || !Number.isFinite(completedAt) || completedAt < startedAt) return null;
    return Math.max(0, Math.round((completedAt - startedAt) / 1000));
  };

  const elapsedSeconds = getElapsedSeconds();
  const musicDownloadName = task.type === 'chapter_background_music' ? backgroundMusicFilename(task) : null;
  const resultAudioUrl = task.resultUrl && musicDownloadName
    ? `${task.resultUrl}${task.resultUrl.includes('?') ? '&' : '?'}download_name=${encodeURIComponent(musicDownloadName)}`
    : task.resultUrl;
  const videoDirectorClips = task.videoDirectorClips || [];
  const hasMultiClipDetails = videoDirectorClips.length > 0;
  const previousClip = task.clipExecution?.execution_contract?.previous_clip;
  const previousVideoUrl = task.clipExecution?.previous_approved_video_url || previousClip?.result_url;
  const previousVideoLabel = previousClip?.clip_index != null
    ? `Previous AV · C${previousClip.clip_index}`
    : 'Previous AV';
  const temporalAnchors = (task.clipExecution?.execution_contract?.temporal_anchor_manifest?.anchors || [])
    .filter(anchor => !!anchor.image_url);
  const temporalAnchorImages = temporalAnchors.map(anchor => {
    const source = anchor.source?.keyframe_index != null
      ? `KF${anchor.source.keyframe_index}`
      : anchor.source?.id || anchor.anchor_id;
    const label = [
      source,
      anchor.slot != null ? t('tasks.temporalSlot', { slot: anchor.slot }) : undefined,
      anchor.frame_position != null ? t('tasks.framePosition', { frame: anchor.frame_position }) : undefined,
    ].filter(Boolean).join(' · ');
    return { label, url: anchor.image_url! };
  });
  const isVideoTask = task.type.includes('video');
  const ordinaryReferenceLabel = (label?: string) => {
    if (!isVideoTask) return label;
    // This persisted label identifies an ordinary Picture slot, not a KF index.
    const directorSlot = label?.match(/^Director Visual Ref (\d+)$/);
    return directorSlot ? `Director Visual Anchor / Picture ${directorSlot[1]}` : label;
  };
  const displayErrorMessage = formatUserFacingError(task.errorMessage) || task.errorMessage;
  const errorCategory = isVideoTask ? videoErrorCategory(task.errorMessage, task.currentStep) : null;
  const hasErrorDetails = Boolean(task.errorMessage && displayErrorMessage &&
    (errorCategory || task.errorMessage !== displayErrorMessage || displayErrorMessage.length > 100));
  const recoveryMismatches = clipRecoveryPlanMismatches(task.errorMessage);
  const chapterLabel = task.chapterNumber != null
    ? task.chapterTitle
      ? t('tasks.chapterContext', { number: task.chapterNumber, title: task.chapterTitle })
      : t('tasks.chapterNumber', { number: task.chapterNumber })
    : task.chapterTitle || task.chapterId;
  const comfyError = task.comfyuiError;
  const comfyErrorTitles: Record<string, string> = {
    COMFYUI_CONFIG_NOT_INITIALIZED: t('tasks.comfyConfigNotInitialized'),
    COMFYUI_CONFIG_MISMATCH: t('tasks.comfyConfigMismatch'),
    COMFYUI_CONNECTION_FAILED: t('tasks.comfyConnectionFailed'),
    COMFYUI_UPLOAD_FAILED: t('tasks.comfyUploadFailed'),
    COMFYUI_HTTP_ERROR: t('tasks.comfyHttpError'),
    COMFYUI_PROMPT_SUBMIT_FAILED: t('tasks.comfySubmitFailed'),
    COMFYUI_INVALID_WORKFLOW: t('tasks.comfySubmitFailed'),
    COMFYUI_EXECUTOR_STALLED: t('tasks.comfyExecutionFailed'),
    COMFYUI_EXECUTION_FAILED: t('tasks.comfyExecutionFailed'),
  };
  const comfyStages: Record<string, string> = {
    PREVIOUS_AV_UPLOAD: t('tasks.comfyPreviousUpload'),
    ORDINARY_REFERENCE_UPLOAD: t('tasks.comfyReferenceUpload'),
    TEMPORAL_ANCHOR_UPLOAD: t('tasks.comfyAnchorUpload'),
    START_IMAGE_UPLOAD: t('tasks.comfyStartUpload'),
    END_IMAGE_UPLOAD: t('tasks.comfyEndUpload'),
    IMAGE_UPLOAD: t('tasks.comfyImageUpload'),
    ASSET_UPLOAD: t('tasks.comfyAssetUpload'),
    PROMPT_SUBMIT: t('tasks.comfyPromptSubmit'),
    EXECUTION_STATUS: t('tasks.comfyExecutionStatus'),
  };
  const comfyEndpointHost = (() => {
    try { return comfyError?.effective_url ? new URL(comfyError.effective_url).host : ''; }
    catch { return ''; }
  })();
  const comfyErrorSummary = comfyError?.error_code === 'COMFYUI_CONFIG_NOT_INITIALIZED'
    ? t('tasks.comfyConfigRequired')
    : comfyError ? [comfyEndpointHost, comfyError.underlying_error.slice(0, 120),
      t('tasks.comfyAttempts', { count: comfyError.attempts })].filter(Boolean).join(' · ') : '';
  const copyTaskId = async () => {
    try {
      await navigator.clipboard.writeText(task.id);
    } catch {
      // Ignore clipboard failures; the full ID is visible for manual selection.
    }
  };
  const getClipStatusText = (status?: string) => {
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
  const clipStatusClass = (status?: string) => {
    switch ((status || '').toUpperCase()) {
      case 'SUCCEEDED': return 'bg-green-100 text-green-700';
      case 'FAILED': return 'bg-red-100 text-red-700';
      case 'RUNNING':
      case 'QUEUED':
      case 'PROMPT_BUILDING': return 'bg-blue-100 text-blue-700';
      default: return 'bg-gray-100 text-gray-600';
    }
  };

  return (
    <div className={`p-4 rounded-lg border ${getStatusColor(task.status)} transition-all hover:shadow-md`}>
      <div className="flex items-start gap-4">
        <div className="p-2 bg-white rounded-lg shadow-sm">{getTaskIcon(task.type)}</div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="font-medium text-gray-900">{getTaskDisplayName(task)}</h3>
            <span className="text-xs px-2 py-0.5 bg-white rounded-full">{getTaskTypeName(task.type)}</span>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-gray-500">
            <span>{t('tasks.taskId')}:</span>
            <code className="select-all rounded bg-white/70 px-1.5 py-0.5 font-mono text-[11px] text-gray-600">{task.id}</code>
            <button
              type="button"
              onClick={copyTaskId}
              className="rounded p-1 text-gray-400 hover:bg-white hover:text-blue-600"
              title="复制 Task ID"
            >
              <Copy className="h-3.5 w-3.5" />
            </button>
            {task.workflowName && (
              <span className="max-w-full break-all rounded-full bg-blue-100 px-2 py-0.5 text-blue-700" title={t('tasks.workflowUsed')}>
                📋 {getWorkflowDisplayName(task)}
              </span>
            )}
          </div>
          <CandidateResultSummary task={task} onPreviewVideo={onPreviewVideo} />
          {(task.clipExecution?.generation_quality_warnings?.length ?? 0) > 0 && (
            <p className="mt-2 rounded border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800" data-generation-quality-warning>
              提示词语言一致性：已记录警告，未阻断生成。{task.clipExecution?.generation_quality_warnings?.join('；')}
            </p>
          )}
          {task.description && <p className="text-sm mt-1 opacity-80">{getTaskDisplayDescription(task)}</p>}
          {(task.novelName || chapterLabel) && (
            <p className="mt-2 flex flex-wrap gap-1.5 text-xs">
              {task.novelName && <span className="px-2 py-0.5 bg-purple-100 text-purple-700 rounded-full">📖 {task.novelName}</span>}
              {chapterLabel && <span className="px-2 py-0.5 bg-indigo-100 text-indigo-700 rounded-full">📑 {chapterLabel}</span>}
            </p>
          )}
          {task.status === 'running' && (
            <div className="mt-2">
              <div className="flex items-center justify-between text-xs mb-1">
                <span>{task.currentStep || '处理中...'}</span>
                <span>{task.progress}%</span>
              </div>
              <div className="h-2 bg-white rounded-full overflow-hidden">
                <div className="h-full bg-primary-500 transition-all duration-500" style={{ width: `${task.progress}%` }} />
              </div>
            </div>
          )}
          {task.status === 'failed' && comfyError && (
            <div className="mt-2 p-2 bg-red-100 rounded text-xs text-red-700" data-comfyui-error>
              <button type="button" className="flex w-full items-start gap-2 text-left" onClick={() => onToggleError(task.id)} aria-expanded={expandedErrors.has(task.id)}>
                <Terminal className="h-4 w-4 flex-shrink-0 mt-0.5" />
                <span className="flex-1 min-w-0">
                  <span className="block font-medium">{comfyErrorTitles[comfyError.error_code] || comfyError.error_code}{comfyStages[comfyError.stage] ? ` · ${comfyStages[comfyError.stage]}` : ''}</span>
                  <span className="block mt-1 break-words">{comfyErrorSummary}</span>
                </span>
                {expandedErrors.has(task.id) ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
              </button>
              {expandedErrors.has(task.id) && (
                <dl className="mt-2 p-2 bg-red-50 rounded border border-red-200 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 break-all" data-comfyui-error-details>
                  {[
                    ['Error Code', comfyError.error_code], ['Stage', comfyError.stage],
                    ...(comfyError.configured_url ? [['Configured Endpoint', comfyError.configured_url]] : []),
                    ['Effective Endpoint', comfyError.effective_url || '—'],
                    ['Underlying Error', comfyError.underlying_error],
                    ['HTTP Status', comfyError.http_status ?? '—'], ['Attempts', comfyError.attempts],
                    ['Prompt Submitted', comfyError.prompt_submitted ? t('tasks.comfyYes') : t('tasks.comfyNo')],
                    ...(comfyError.proxy ? [['Proxy', comfyError.proxy]] : []),
                  ].map(([label, value]) => <div key={String(label)} className="contents"><dt className="font-medium">{label}</dt><dd>{value}</dd></div>)}
                </dl>
              )}
            </div>
          )}
          {task.status === 'failed' && !comfyError && displayErrorMessage && (
            <div className="mt-2">
              <button type="button"
                className="w-full p-2 bg-red-100 rounded text-xs text-red-700 flex items-start gap-2 text-left enabled:cursor-pointer enabled:hover:bg-red-200 transition-colors"
                onClick={() => onToggleError(task.id)}
                disabled={!hasErrorDetails}
                aria-expanded={hasErrorDetails ? expandedErrors.has(task.id) : undefined}
              >
                <Terminal className="h-4 w-4 flex-shrink-0 mt-0.5" />
                <span className="flex-1 min-w-0">
                  <span className="flex items-center justify-between">
                    <span className="font-medium">
                      {t('tasks.error')}: {errorCategory && <span data-error-category className="mr-1 rounded bg-red-200 px-1.5 py-0.5">{errorCategory}</span>}
                      {displayErrorMessage.slice(0, 100)}{displayErrorMessage.length > 100 ? '...' : ''}
                    </span>
                    {hasErrorDetails && (
                      <span className="text-red-500 ml-2 flex-shrink-0">
                        {expandedErrors.has(task.id) ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                      </span>
                    )}
                  </span>
                </span>
              </button>
              {expandedErrors.has(task.id) && hasErrorDetails && (
                <div className="mt-1 p-2 bg-red-50 rounded border border-red-200 text-xs text-red-800 whitespace-pre-wrap break-all">
                  <div>{displayErrorMessage}</div>
                  {recoveryMismatches?.map((item, index) => <div key={`${item.field}-${index}`} className="mt-1">
                    {recoveryFieldLabels[item.field] || item.field}：期望 {detailValue(item.expected)}；实际 {detailValue(item.actual)}
                  </div>)}
                  {task.errorMessage?.startsWith('CLIP_RECOVERY_PLAN_CHANGED') && !recoveryMismatches &&
                    <div className="mt-1">此历史任务只保存了错误码，未保存各项比较结果。</div>}
                  <div className="mt-2 font-mono">原始错误：{task.errorMessage}</div>
                </div>
              )}
              {displayErrorMessage.includes('ComfyUI') && (
                <p className="text-xs text-red-600 mt-1 ml-6">{t('tasks.comfyuiHint')}</p>
              )}
            </div>
          )}
          {(!!task.referenceImages?.length || previousVideoUrl || temporalAnchors.length > 0) && (
            <div className="mt-3 space-y-2" data-generation-inputs>
              <div className="text-xs font-medium text-gray-600">
                {isVideoTask ? t('tasks.generationInputs') : t('tasks.referenceImages')}
              </div>
              {previousVideoUrl && (
                <div data-input-kind="previous-av">
                  <div className="text-xs text-gray-500 mb-1">{t('tasks.referenceVideo')}</div>
                  <button
                    type="button"
                    onClick={() => onPreviewVideo(previousVideoUrl)}
                    className="group relative h-16 w-24 overflow-hidden rounded-md border border-gray-200 bg-black"
                    title={previousVideoLabel}
                  >
                    <video src={previousVideoUrl} muted preload="metadata" className="h-full w-full object-cover" />
                    <span className="absolute inset-0 flex items-center justify-center bg-black/15 text-white opacity-0 transition-opacity group-hover:opacity-100">
                      <Play className="h-5 w-5 fill-current" />
                    </span>
                    <span className="absolute bottom-0 left-0 right-0 truncate bg-black/55 px-1 py-0.5 text-[10px] text-white">
                      {previousVideoLabel}
                    </span>
                  </button>
                </div>
              )}
              {!!task.referenceImages?.length && (
                <div data-input-kind="ordinary-image">
                  {isVideoTask && <div className="text-xs text-gray-500 mb-1">{t('tasks.ordinaryImageReferences')}</div>}
                  <div className="flex flex-wrap gap-2">
                    {task.referenceImages.map((image, index) => (
                      <button
                        key={`${image.url}-${index}`}
                        type="button"
                        onClick={() => onPreviewImages(task.referenceImages || [], index)}
                        className={isVideoTask
                          ? 'group relative w-36 overflow-hidden rounded-md border border-gray-200 bg-white text-left hover:shadow-md transition-shadow'
                          : 'group relative h-16 w-24 overflow-hidden rounded-md border border-gray-200 bg-white hover:shadow-md transition-shadow'}
                        title={ordinaryReferenceLabel(image.label) || t('tasks.referenceImage')}
                      >
                        <img
                          src={image.url}
                          alt={ordinaryReferenceLabel(image.label) || t('tasks.referenceImage')}
                          className={isVideoTask ? 'h-20 w-full object-cover' : 'h-full w-full object-cover'}
                          onError={(e) => {
                            (e.target as HTMLImageElement).className = 'hidden';
                          }}
                        />
                        {image.label && (
                          <span className={isVideoTask ? 'block px-1 py-1 text-[10px] text-gray-700'
                            : 'absolute bottom-0 left-0 right-0 truncate bg-black/55 px-1 py-0.5 text-[10px] text-white'}>
                            {ordinaryReferenceLabel(image.label)}
                          </span>
                        )}
                        <span className="absolute inset-0 bg-black/0 group-hover:bg-black/20 transition-colors" />
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {temporalAnchorImages.length > 0 && (
                <div data-input-kind="temporal-anchor">
                  <div className="text-xs text-gray-500 mb-1">{t('tasks.temporalAnchors')}</div>
                  <div className="flex flex-wrap gap-2">
                    {temporalAnchorImages.map((image, index) => (
                      <button
                        key={`${image.url}-${index}`}
                        type="button"
                        onClick={() => onPreviewImages(temporalAnchorImages, index)}
                        className="group w-36 overflow-hidden rounded-md border border-gray-200 bg-white text-left hover:shadow-md transition-shadow"
                        title={image.label}
                      >
                        <img src={image.url} alt={image.label} className="h-20 w-full object-cover" />
                        <span className="block px-1 py-1 text-[10px] text-gray-700">
                          {image.label}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
          {hasMultiClipDetails && (
            <div className="mt-3 rounded-lg border border-blue-100 bg-white/70 p-3">
              <div className="mb-2 flex items-center justify-between gap-2">
                <div className="text-xs font-medium text-blue-900">{t('tasks.multiClipDetails')}</div>
                <div className="text-[11px] text-blue-700">{t('tasks.clipCount', { count: videoDirectorClips.length })}</div>
              </div>
              <div className="space-y-2">
                {videoDirectorClips.map((clip, clipIndex) => (
                  <div key={`${task.id}-clip-${clip.windowIndex || clipIndex}`} className="rounded-md border border-gray-200 bg-white p-2 text-xs text-gray-700">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium text-gray-900">Clip {clip.windowIndex || clipIndex + 1}</span>
                        <span className={`rounded-full px-2 py-0.5 ${clipStatusClass(clip.status)}`}>{getClipStatusText(clip.status)}</span>
                        <span>{clip.startTime ?? '-'}s - {clip.endTime ?? '-'}s</span>
                        {clip.workflowName && <span className="rounded-full bg-blue-50 px-2 py-0.5 text-blue-700">{clip.workflowName}</span>}
                        {clip.promptId && <span className="text-gray-500">{t('tasks.promptId', { id: clip.promptId })}</span>}
                        {clip.seed != null && <span className="font-mono text-gray-500">Seed: {clip.seed}</span>}
                        {clip.dialogueCount !== undefined && clip.dialogueCount !== null && <span className="text-gray-500">{t('tasks.dialogueCount', { count: clip.dialogueCount })}</span>}
                      </div>
                      {(clip.hasWorkflowJson || clip.promptText) && (
                        <button
                          type="button"
                          onClick={() => onViewClipWorkflow(task, clip)}
                          className="shrink-0 rounded p-1.5 text-gray-400 transition-colors hover:bg-blue-50 hover:text-blue-600"
                          title={t('tasks.viewClipWorkflow')}
                        >
                          <Code className="h-4 w-4" />
                        </button>
                      )}
                    </div>
                    {clip.errorMessage && <div className="mt-1 text-red-600">
                      {videoErrorCategory(clip.errorMessage) && <span data-error-category className="mr-1 rounded bg-red-100 px-1.5 py-0.5">{videoErrorCategory(clip.errorMessage)}</span>}
                      {formatUserFacingError(clip.errorMessage)}
                    </div>}
                    {clip.promptText && <div className="mt-1 line-clamp-2 text-gray-500" title={clip.promptText}>Prompt: {clip.promptText}</div>}
                    {!!clip.referenceImages?.length && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {clip.referenceImages.map((image, index) => (
                          <button
                            key={`${image.url}-${index}`}
                            type="button"
                            onClick={() => onPreviewImages(clip.referenceImages || [], index)}
                            className="h-12 w-16 overflow-hidden rounded border border-gray-200 bg-gray-50"
                            title={image.label || t('tasks.referenceImage')}
                          >
                            <img src={image.url} alt={image.label || t('tasks.referenceImage')} className="h-full w-full object-cover" />
                          </button>
                        ))}
                      </div>
                    )}
                    {clip.videoUrl && (
                      <button onClick={() => onPreviewVideo(clip.videoUrl!)} className="mt-2 inline-flex items-center gap-1 text-green-600 hover:text-green-700 underline">
                        <Play className="h-3 w-3" />{t('tasks.viewClipVideo')}
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
          {task.status === 'completed' && task.resultUrl && (
            <div className="mt-2">
              {task.type === 'character_portrait' || task.type === 'shot_image' || task.type === 'shot_image_repair' || task.type === 'shot_image_repair_candidate' || task.type === 'scene_image' || task.type === 'prop_image' || task.type === 'keyframe_image' || task.type === 'single_image_edit' || task.type === 'novel_video_cover' ? (
                <div>
                  <div className="relative group inline-block">
                    <img
                      src={task.resultUrl}
                      alt={t('tasks.generatedResult')}
                      className="h-32 w-auto object-contain rounded-lg border border-gray-200 cursor-pointer hover:shadow-lg transition-shadow bg-gray-50"
                      onClick={() => task.resultUrl && onPreviewImage(task.resultUrl)}
                      onLoad={() => task.resultUrl && fetchImageInfo(task.resultUrl, task.id)}
                      onError={(e) => {
                        (e.target as HTMLImageElement).src = '';
                        (e.target as HTMLImageElement).className = 'hidden';
                      }}
                    />
                    <div
                      className="absolute inset-0 bg-black bg-opacity-0 group-hover:bg-opacity-30 transition-all rounded-lg flex items-center justify-center opacity-0 group-hover:opacity-100 cursor-pointer"
                      onClick={() => task.resultUrl && onPreviewImage(task.resultUrl)}
                    >
                      <span className="text-white text-xs font-medium">{t('tasks.viewOriginal')}</span>
                    </div>
                  </div>
                  {imageInfo[task.id] && (
                    <div className="mt-1 text-xs text-gray-500">
                      {imageInfo[task.id].width && <span>{imageInfo[task.id].width} × {imageInfo[task.id].height} px</span>}
                      {imageInfo[task.id].size && <span className="ml-2">· {imageInfo[task.id].size}</span>}
                      {imageInfo[task.id].width && imageInfo[task.id].height &&
                        <span className="ml-2">· 比例 {formatAspectRatio(imageInfo[task.id].width, imageInfo[task.id].height)}</span>}
                    </div>
                  )}
                </div>
              ) : task.type === 'novel_video' ? (
                <video
                  src={task.resultUrl}
                  controls
                  playsInline
                  preload="metadata"
                  className="w-full max-w-2xl rounded-lg bg-black"
                  aria-label={task.name}
                />
              ) : task.type === 'shot_video' || task.type === 'shot_video_hd' || task.type === 'chapter_video' || task.type === 'transition_video' ? (
                <div>
                  <div className="relative group inline-block cursor-pointer" onClick={() => task.resultUrl && onPreviewVideo(task.resultUrl)}>
                    <div className="h-32 w-48 bg-gray-900 rounded-lg flex items-center justify-center overflow-hidden">
                      <video src={task.resultUrl} className="w-full h-full object-cover opacity-80 group-hover:opacity-100 transition-opacity" preload="metadata" />
                      <div className="absolute inset-0 flex items-center justify-center">
                        <div className="w-12 h-12 bg-black bg-opacity-50 rounded-full flex items-center justify-center group-hover:bg-opacity-70 transition-all group-hover:scale-110">
                          <Play className="h-6 w-6 text-white ml-1" />
                        </div>
                      </div>
                    </div>
                  </div>
                  <div className="mt-1 text-xs text-gray-500">
                    <button onClick={() => task.resultUrl && onPreviewVideo(task.resultUrl)} className="text-green-600 hover:text-green-700 underline inline-flex items-center gap-1">
                      <Play className="h-3 w-3" />{t('tasks.viewResult')}
                    </button>
                  </div>
                </div>
              ) : task.type === 'character_audio' || task.type === 'narrator_audio' || task.type === 'chapter_background_music' ? (
                <div>
                  {task.type === 'chapter_background_music' && (
                    <p className="mb-1 text-xs font-medium text-gray-600">整章背景音乐试听轨（包含未配乐区间）</p>
                  )}
                  <div className="flex items-center gap-3 p-3 bg-gray-50 rounded-lg border border-gray-200">
                    <div className="w-10 h-10 bg-purple-100 rounded-full flex items-center justify-center">
                      <Music className="h-5 w-5 text-purple-600" />
                    </div>
                    <div className="min-w-0 flex-1">
                      {task.type === 'chapter_background_music' ? (
                        <WaveformAudioPlayer src={task.resultUrl!} label={`${task.chapterTitle || '章回'}背景音乐`} compact />
                      ) : (
                        <audio src={resultAudioUrl} controls className="h-8 w-full" preload="metadata" />
                      )}
                    </div>
                  </div>
                  <div className="mt-1 text-xs text-gray-500">
                    <a href={resultAudioUrl} download={musicDownloadName || true} className="text-purple-600 hover:text-purple-700 underline inline-flex items-center gap-1">
                      {t('common.download')}
                    </a>
                  </div>
                </div>
              ) : task.type === 'shot_export' ? (
                <a href={task.resultUrl} download className="text-sm underline inline-flex items-center gap-1">下载生产包</a>
              ) : (
                <a href={task.resultUrl} target="_blank" rel="noopener noreferrer" className="text-sm underline inline-flex items-center gap-1">
                  {t('tasks.viewResult')}
                </a>
              )}
            </div>
          )}
          {task.type === 'chapter_video' && task.nameplatePreview?.url && (
            <div className="mt-3 rounded-lg border border-red-100 bg-red-50/40 p-3 text-sm">
              <div className="font-medium text-gray-800">主角首次出镜姓名牌</div>
              <div className="mt-1 text-xs text-gray-500">
                {task.nameplatePreview.status === 'approved'
                  ? task.nameplatePreview.autoApproved ? '已自动通过并用于章回成片' : '已确认并用于章回成片'
                  : '自动确定出场时间和人物附近的位置，请预览效果后确认。'}
              </div>
              <div className="mt-2 flex flex-wrap gap-2">
                <button type="button" onClick={() => {
                  setNameplatePreviewOpened(true);
                  onPreviewVideo(task.nameplatePreview!.url!);
                }}
                  className="rounded border border-red-200 bg-white px-3 py-1.5 text-red-700 hover:bg-red-50">
                  预览红色竖牌
                </button>
                {task.nameplatePreview.status === 'pending_confirmation' && (
                  <button type="button" onClick={approveNameplate} disabled={approvingNameplate || !nameplatePreviewOpened}
                    className="rounded bg-red-600 px-3 py-1.5 text-white hover:bg-red-700 disabled:opacity-50">
                    {approvingNameplate ? '确认中…' : nameplatePreviewOpened ? '确认用于成片' : '请先预览'}
                  </button>
                )}
              </div>
            </div>
          )}
          {task.type === 'chapter_video' && (task.nameplatePreview?.warnings?.length ?? 0) > 0 && (
            <div className="mt-2 text-xs text-amber-700">
              {task.nameplatePreview?.warnings?.join('；')}
            </div>
          )}
          <div className="mt-2 text-xs opacity-60">
            {task.seed != null && <span className="mr-2 font-mono">Seed: {task.seed}</span>}
            {task.sourceTaskId && <span className="mr-2 font-mono">Source: {task.sourceTaskId}</span>}
            {t('common.createdAt')}: {formatDate(task.createdAt)}
            {task.completedAt && ` · ${t('tasks.completedAt')}: ${formatDate(task.completedAt)}`}
            {elapsedSeconds !== null && (
              <span title={task.type === 'shot_image' ? '从开始处理到最终审核结束，包含提示词生成、每次 ComfyUI 生图和 AI 审核' : undefined}>
                {' · '}{task.type === 'shot_image' ? '总耗时' : '耗时'}: {formatElapsedDuration(elapsedSeconds)}
              </span>
            )}
            {task.type === 'shot_image' && task.shotImageQuality && task.shotImageQuality.generation_count > 0 && (
              <span>
                {' · '}生图 {task.shotImageQuality.generation_count} 次
                {task.shotImageQuality.retry_count > 0 && `（自动重试 ${task.shotImageQuality.retry_count} 次）`}
                {' · '}AI 审核 {task.shotImageQuality.review_count} 次
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {task.status === 'completed' && task.resultUrl && task.hasPromptText &&
            ['character_portrait', 'shot_image', 'shot_image_repair_candidate', 'scene_image', 'prop_image', 'keyframe_image', 'single_image_edit'].includes(task.type) && (
              <button onClick={() => onImageReview(task)} className="rounded px-2 py-1 text-sm font-medium text-blue-600 hover:bg-blue-50">AI 评审</button>
          )}
          {getStatusIcon(task.status)}
          <span className="text-sm font-medium min-w-[60px]">{getStatusText(task.status)}</span>
          {(task.type !== 'chapter_ai_split' && task.type !== 'chapter_ai_split_batch' && task.type !== 'shot_image_repair' && task.type !== 'shot_image_repair_candidate') && (task.status === 'failed' || (task.type === 'shot_video_batch' && task.status === 'paused')) && (
            <button onClick={() => onRetry(task.id)} className="p-2 text-gray-400 hover:text-primary-600 transition-colors" title={task.type === 'shot_video_batch' ? '恢复未完成的 Shot' : t('tasks.retry')}>
              <Play className="h-4 w-4" />
            </button>
          )}
          {!hasMultiClipDetails && (task.hasWorkflowJson || task.hasPromptText) && (
            <button onClick={() => onViewWorkflow(task)} className="p-2 text-gray-400 hover:text-blue-600 transition-colors" title={t('tasks.viewWorkflow')}>
              <Code className="h-4 w-4" />
            </button>
          )}
          {(!(task.type === 'chapter_ai_split' || task.type === 'chapter_ai_split_batch') || !['pending', 'running'].includes(task.status)) && <button onClick={() => onDelete(task.id)} className="p-2 text-gray-400 hover:text-red-600 transition-colors" title={t('common.delete')}>
            <Trash2 className="h-4 w-4" />
          </button>}
        </div>
      </div>
    </div>
  );
}
