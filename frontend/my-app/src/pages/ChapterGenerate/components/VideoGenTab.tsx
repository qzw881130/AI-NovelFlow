/**
 * VideoGenTab - 视频生成 Tab（阶段 4）
 *
 * 布局参考分镜图生成页面：
 * - 中间：视频生成提示词编辑 + 视频预览
 * - 右侧：关键帧设置 + 转场生成
 *
 * 注意：分镜资源列表在左侧可折叠区域显示（由 ChapterGenerateLayout 的左侧栏渲染）
 */

import { useState, useEffect, useCallback } from 'react';
import { useChapterGenerateStore } from '../stores';
import { Film, Loader2, Download, Save, Square, Check, X, Image, ChevronDown, Eye, Combine, Layers, ChevronUp, Volume2, Play, Copy, Info, ChevronLeft, ChevronRight, RefreshCw, Sparkles } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import { shotsApi } from '../../../api/shots';
import { toast } from '../../../stores/toastStore';
import KeyframesManager from '../../../components/KeyframesManager';
import AudioReferenceSelector from '../../../components/AudioReferenceSelector';
import { ImagePreviewModal } from '../../../components/ImagePreviewModal';
import type { KeyframeData } from '../../../types';
import type { VideoAiCall, VideoDirectorPlan, VideoMode } from '../../../api/shots';

const VIDEO_TAB_UI_STORAGE_KEY = 'chapterGenerate_videoTab_ui';
type MergeVideoMode = 'shots_only' | 'shots_with_transitions';
type BatchSelectionMode = 'all' | 'pending' | null;

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

const formatAiCallValue = (value: any) => {
  if (value === null || value === undefined || value === '') return '-';
  if (typeof value === 'string') return value;
  return JSON.stringify(value, null, 2);
};

const copyText = async (text?: string | null) => {
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    toast.success('已复制');
  } catch {
    toast.error('复制失败');
  }
};

function VideoAiCallsPanel({ calls = [] }: { calls?: VideoAiCall[] }) {
  const [expanded, setExpanded] = useState(false);
  const [openIndex, setOpenIndex] = useState(Math.max(0, calls.length - 1));
  const latest = calls[calls.length - 1];

  useEffect(() => {
    if (calls.length > 0) setOpenIndex(calls.length - 1);
  }, [calls.length]);

  if (!calls.length) {
    return (
      <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 px-3 py-3 text-sm text-gray-500">
        暂无 AI 调用结果。重新推荐或生成视频后会显示 #07/#11/#12/#13 的返回。
      </div>
    );
  }

  const visibleCalls = expanded ? calls : [latest];

  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50">
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-200">
        <div>
          <div className="text-sm font-semibold text-gray-800">AI 调用结果</div>
          <div className="text-xs text-gray-500">共 {calls.length} 次，默认显示最近一次</div>
        </div>
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="px-2 py-1 text-xs rounded border border-gray-200 bg-white text-gray-700 hover:bg-gray-100"
        >
          {expanded ? '只看最近' : '展开全部'}
        </button>
      </div>
      <div className="p-3 space-y-2">
        {visibleCalls.map((call, idx) => {
          const actualIndex = expanded ? idx : calls.length - 1;
          const isOpen = openIndex === actualIndex;
          const responseText = formatAiCallValue(call.response);
          const parsedText = formatAiCallValue(call.parsed_result);
          const promptText = formatAiCallValue(call.final_prompt);
          return (
            <div key={`${call.step}-${call.created_at}-${actualIndex}`} className="rounded-lg border border-gray-200 bg-white overflow-hidden">
              <button
                type="button"
                onClick={() => setOpenIndex(isOpen ? -1 : actualIndex)}
                className="w-full px-3 py-2 flex items-center justify-between gap-3 text-left hover:bg-gray-50"
              >
                <div>
                  <div className="text-sm font-medium text-gray-800">#{call.step || '--'} {call.title || call.task_type || 'AI 调用'}</div>
                  <div className="text-xs text-gray-500">
                    {call.prompt_template_name || '-'} · {call.status || '-'} · {call.created_at ? new Date(call.created_at).toLocaleString() : '-'}
                    {call.clip_index ? ` · Clip ${call.clip_index}` : ''}
                  </div>
                </div>
                <ChevronDown className={`w-4 h-4 text-gray-400 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
              </button>
              {isOpen && (
                <div className="px-3 pb-3 space-y-3">
                  {call.input_summary && <div className="text-xs text-gray-500">{call.input_summary}</div>}
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs font-medium text-gray-600">返回结果</span>
                      <button type="button" onClick={() => copyText(responseText)} className="text-xs text-blue-600 hover:text-blue-800 flex items-center gap-1"><Copy className="w-3 h-3" />复制</button>
                    </div>
                    <pre className="max-h-40 overflow-auto rounded bg-gray-900 p-2 text-xs text-gray-100 whitespace-pre-wrap">{responseText}</pre>
                  </div>
                  {call.parsed_result !== undefined && (
                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs font-medium text-gray-600">解析结果</span>
                        <button type="button" onClick={() => copyText(parsedText)} className="text-xs text-blue-600 hover:text-blue-800 flex items-center gap-1"><Copy className="w-3 h-3" />复制</button>
                      </div>
                      <pre className="max-h-32 overflow-auto rounded bg-gray-900 p-2 text-xs text-gray-100 whitespace-pre-wrap">{parsedText}</pre>
                    </div>
                  )}
                  {call.final_prompt && (
                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs font-medium text-gray-600">最终 Prompt</span>
                        <button type="button" onClick={() => copyText(promptText)} className="text-xs text-blue-600 hover:text-blue-800 flex items-center gap-1"><Copy className="w-3 h-3" />复制</button>
                      </div>
                      <pre className="max-h-40 overflow-auto rounded bg-gray-900 p-2 text-xs text-gray-100 whitespace-pre-wrap">{promptText}</pre>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

interface VideoDirectorPanelProps {
  shot: any;
  shotImageUrl?: string | null;
  plan: VideoDirectorPlan;
  isRecommending: boolean;
  onRecommend: (force?: boolean) => void;
  onPlanKeyframes: (force?: boolean) => void;
  onGenerateMissingKeyframes: () => void;
  onSelectMode: (mode: VideoMode) => void;
}

function VideoDirectorPanel({
  shot,
  shotImageUrl,
  plan,
  isRecommending,
  onRecommend,
  onPlanKeyframes,
  onGenerateMissingKeyframes,
  onSelectMode,
}: VideoDirectorPanelProps) {
  const selectedMode = plan.selected_mode || plan.recommended_mode || 'SINGLE_FRAME';
  const maxClipDuration = plan.workflow_capability?.max_clip_duration || 15;
  const firstLastAvailable = plan.first_last_available ?? ((shot?.duration || 0) <= maxClipDuration);
  const keyframes = plan.keyframes || [];
  const clips = selectedMode === 'MULTI_KEYFRAME' ? (plan.window_plans || []) : (plan.clips || []);
  const hasWindowPlans = selectedMode === 'MULTI_KEYFRAME' && clips.length > 0;
  const legacyKeyframes = shot?.keyframes || [];
  const getKeyframeImageUrl = (kf: any) => {
    if (!kf) return null;
    if (kf.role === 'START') return shotImageUrl || null;
    if (kf.image_url) return kf.image_url;
    const legacyKeyframe = legacyKeyframes.find((item: any) => Number(item.plan_keyframe_index) === Number(kf.index));
    return legacyKeyframe?.image_url || null;
  };
  const missingKeyframes = selectedMode === 'MULTI_KEYFRAME'
    ? keyframes.filter((kf: any) => kf.role !== 'START' && !getKeyframeImageUrl(kf))
    : [];
  const threeFrameClipCount = clips.filter((clip: any) => Number(clip.selected_frame_count || clip.frame_count) === 3).length;
  const fourFrameClipCount = clips.filter((clip: any) => Number(clip.selected_frame_count || clip.frame_count) === 4).length;
  const [selectedKeyframeIndex, setSelectedKeyframeIndex] = useState(0);
  const selectedKeyframe = keyframes[selectedKeyframeIndex] || keyframes[0];
  const hasNextKeyframe = selectedKeyframeIndex < keyframes.length - 1;
  const selectedTransition = plan.transitions?.find((transition) => (
    hasNextKeyframe
      ? Number(transition.from_keyframe_index) === Number(selectedKeyframe?.index)
      : Number(transition.to_keyframe_index) === Number(selectedKeyframe?.index)
  ));

  useEffect(() => {
    setSelectedKeyframeIndex(0);
  }, [shot?.id, selectedMode]);

  const renderModeButton = (mode: VideoMode, disabled = false, title = '') => (
    <button
      type="button"
      onClick={() => !disabled && onSelectMode(mode)}
      disabled={disabled}
      title={title}
      className={`flex-1 rounded-lg border px-3 py-2 text-sm font-medium transition-colors ${
        selectedMode === mode
          ? 'border-blue-500 bg-blue-50 text-blue-700'
          : 'border-gray-200 bg-white text-gray-700 hover:border-blue-300 hover:bg-blue-50'
      } ${disabled ? 'cursor-not-allowed bg-gray-50 text-gray-400 hover:border-gray-200 hover:bg-gray-50' : ''}`}
    >
      {getVideoModeLabel(mode)}{plan.recommended_mode === mode ? ' ★' : ''}{disabled ? '（当前不可用）' : ''}
    </button>
  );

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

  return (
    <div className="flex-shrink-0 border border-gray-200 rounded-lg p-4 space-y-4 bg-white">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-gray-800 flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-blue-600" />
            视频导演
          </h3>
          <p className="mt-1 text-xs text-gray-500">
            AI推荐：{isRecommending ? '推荐中...' : getVideoModeLabel(plan.recommended_mode)}
            {plan.recommendation_reason ? ` · ${plan.recommendation_reason}` : ''}
          </p>
        </div>
        <button
          type="button"
          onClick={() => onRecommend(true)}
          disabled={isRecommending}
          className="px-3 py-1.5 rounded-lg border border-gray-200 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50 transition-colors flex items-center gap-1.5"
        >
          <RefreshCw className={`w-4 h-4 ${isRecommending ? 'animate-spin' : ''}`} />
          重新推荐
        </button>
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
              disabled={isRecommending}
              className="px-3 py-1.5 rounded-lg border border-blue-200 bg-white text-sm text-blue-700 hover:bg-blue-50 disabled:opacity-50 transition-colors whitespace-nowrap"
            >
              {isRecommending ? '规划中...' : hasWindowPlans ? '重新规划关键帧' : 'AI规划关键帧'}
            </button>
            <button
              type="button"
              onClick={onGenerateMissingKeyframes}
              disabled={isRecommending || !hasWindowPlans || missingKeyframes.length === 0}
              className="px-3 py-1.5 rounded-lg bg-blue-600 text-sm text-white hover:bg-blue-700 disabled:opacity-50 transition-colors whitespace-nowrap"
              title={!hasWindowPlans ? '请先完成 #08 关键帧规划' : ''}
            >
              生成缺失关键帧{missingKeyframes.length > 0 ? ` ${missingKeyframes.length}` : ''}
            </button>
          </div>
        </div>
      )}

      {selectedMode === 'SINGLE_FRAME' && (
        <div className="grid grid-cols-[220px_1fr] gap-4">
          <div>
            <div className="text-xs font-medium text-gray-600 mb-2">起始帧</div>
            <div className="aspect-video rounded-lg bg-gray-100 overflow-hidden border border-gray-200">
              {shotImageUrl ? (
                <img src={shotImageUrl} alt="当前主分镜图" className="w-full h-full object-cover" />
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
        <div className="grid grid-cols-[1fr_1fr] gap-4">
          <div>
            <div className="text-xs font-semibold text-gray-600 mb-2">START · 0s</div>
            <div className="aspect-video rounded-lg bg-gray-100 overflow-hidden border border-gray-200">
              {shotImageUrl ? <img src={shotImageUrl} alt="START" className="w-full h-full object-cover" /> : <div className="w-full h-full flex items-center justify-center"><Image className="w-8 h-8 text-gray-300" /></div>}
            </div>
          </div>
          <div>
            <div className="text-xs font-semibold text-gray-600 mb-2">END · {shot?.duration || 0}s</div>
            <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm text-gray-700 min-h-[140px] whitespace-pre-wrap">
              {keyframes.find((kf) => kf.role === 'END')?.description || '等待 AI 规划尾帧'}
            </div>
          </div>
          <div className="col-span-2">
            <div className="text-xs font-semibold text-gray-600 mb-1">Transition</div>
            <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm text-gray-700 min-h-20 whitespace-pre-wrap">
              {selectedTransition?.transition_description || '等待 AI 规划当前关键帧到下一关键帧的动作和镜头变化'}
            </div>
          </div>
        </div>
      )}

      {selectedMode === 'MULTI_KEYFRAME' && (
        <div className="space-y-4">
          <div>
            <div className="flex items-center justify-between mb-2">
              <div>
                <div className="text-sm font-semibold text-gray-700">关键帧时间轴</div>
                <div className="text-xs text-gray-500">{keyframes.length} 条 Keyframe + {Math.max(0, keyframes.length - 1)} 条 Transition（相邻间隔 ≤ {maxClipDuration}s）</div>
              </div>
            </div>
            <div className="flex items-start gap-2 overflow-x-auto pb-2">
              {keyframes.map((kf, idx) => (
                <button
                  key={`${kf.index}-${kf.time_seconds}`}
                  type="button"
                  onClick={() => setSelectedKeyframeIndex(idx)}
                  className={`relative min-w-24 rounded-xl px-3 py-2 text-center transition-all ${selectedKeyframeIndex === idx
                    ? 'border border-blue-300 bg-blue-50 text-blue-700 shadow-sm ring-2 ring-blue-100'
                    : 'border border-transparent text-gray-700 hover:bg-gray-50 hover:text-blue-600'
                  }`}
                >
                  <div className={`mx-auto mb-1 h-3 w-3 rounded-full border-2 ${selectedKeyframeIndex === idx
                    ? 'border-blue-600 bg-blue-500 ring-4 ring-blue-100'
                    : getKeyframeImageUrl(kf)
                      ? 'border-green-500 bg-green-100'
                      : 'border-blue-500 bg-white'
                  }`} />
                  <div className="text-sm font-semibold">KF{kf.index} · {kf.time_seconds}s</div>
                  <div className="text-[11px] text-gray-500">{kf.role}</div>
                  <div className={`text-[11px] ${getKeyframeImageUrl(kf) ? 'text-green-600' : 'text-amber-600'}`}>{getKeyframeImageUrl(kf) ? (kf.role === 'START' ? 'Primary Storyboard' : '已生成') : '缺图'}</div>
                  {selectedKeyframeIndex === idx && (
                    <div className="absolute -bottom-1 left-3 right-3 h-1 rounded-full bg-blue-500" />
                  )}
                </button>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-[minmax(260px,45%)_1fr] gap-4">
            <div>
              <div className="aspect-video rounded-lg bg-gray-100 overflow-hidden border border-gray-200 flex items-center justify-center">
                {getKeyframeImageUrl(selectedKeyframe) ? (
                  <img src={getKeyframeImageUrl(selectedKeyframe)!} alt={`KF${selectedKeyframe.index}`} className="w-full h-full object-cover" />
                ) : shotImageUrl && selectedKeyframe?.role === 'START' ? (
                  <img src={shotImageUrl} alt="START" className="w-full h-full object-cover" />
                ) : (
                  <Image className="w-12 h-12 text-gray-300" />
                )}
              </div>
              <div className="mt-2 flex items-center justify-between">
                <span className="text-sm font-medium text-gray-700">KF{selectedKeyframe?.index || 1} · {selectedKeyframe?.time_seconds || 0}s</span>
                <span className={`text-xs ${getKeyframeImageUrl(selectedKeyframe) ? 'text-green-600' : 'text-amber-600'}`}>
                  {getKeyframeImageUrl(selectedKeyframe) ? '图片已就绪' : '等待生成图片'}
                </span>
              </div>
            </div>
            <div className="space-y-3">
              <div>
                <div className="text-xs font-semibold text-gray-600 mb-1">Keyframe description</div>
                <textarea
                  readOnly
                  value={selectedKeyframe?.role === 'START' ? (shot?.description || '') : (selectedKeyframe?.description || '')}
                  className="w-full h-28 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm resize-none"
                />
              </div>
              <div>
                <div className="text-xs font-semibold text-gray-600 mb-1">
                  {hasNextKeyframe ? '到下一关键帧 Transition' : '上一关键帧到当前 Transition'}
                </div>
                <textarea
                  readOnly
                  value={selectedTransition?.transition_description || ''}
                  placeholder={hasNextKeyframe ? '等待 #10 规划当前关键帧到下一关键帧的过渡' : '最后一个关键帧，将显示上一段进入当前帧的 Transition'}
                  className="w-full h-24 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm resize-none"
                />
              </div>
            </div>
          </div>

        </div>
      )}

      <div className="rounded-lg border border-gray-200 bg-white p-3">
        <div className="flex items-center justify-between gap-3 mb-2">
          <div className="text-sm font-semibold text-gray-700">执行计划 · {clips.length} Clips</div>
          <div className="text-xs text-gray-500">预计 H3 任务 {clips.length}</div>
        </div>
        {selectedMode === 'MULTI_KEYFRAME' && (
          <div className="grid grid-cols-2 gap-2 text-sm mb-3">
            <div className="rounded-lg border border-gray-200 px-3 py-2 flex items-center justify-between">3帧 Clips <span className="font-semibold text-gray-800">{threeFrameClipCount}</span></div>
            <div className="rounded-lg border border-gray-200 px-3 py-2 flex items-center justify-between">4帧 Clips <span className="font-semibold text-gray-800">{fourFrameClipCount}</span></div>
          </div>
        )}
        {clips.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {clips.map((clip: any) => {
              const clipIndex = clip.clip_index || clip.window_index;
              const frameCount = clip.selected_frame_count || clip.frame_count;
              const keyframeLabel = Array.isArray(clip.keyframe_indexes) && clip.keyframe_indexes.length > 0
                ? ` · ${clip.keyframe_indexes.map((item: number) => `KF${item}`).join('/')}`
                : '';
              const clipStatus = clip.status || 'PENDING';
              return (
                <span key={`${clipIndex}-${clip.start_time}-${clip.end_time}`} className={`rounded-md border px-2 py-1 text-xs ${getClipStatusClass(clipStatus)}`}>
                  C{clipIndex} {clip.start_time}-{clip.end_time}s{frameCount ? ` · ${frameCount}KF` : ''}{keyframeLabel}{clip.workflow_key ? ` · ${clip.workflow_key}` : ''} · {clipStatus}
                </span>
              );
            })}
          </div>
        ) : (
          <div className="rounded-md border border-dashed border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
            {selectedMode === 'MULTI_KEYFRAME' ? '等待 #08 生成 window_plans 后才能执行多关键帧视频。' : '暂无执行 Clip，请重新推荐或保存视频规划。'}
          </div>
        )}
      </div>

      <VideoAiCallsPanel calls={plan.ai_calls || []} />
    </div>
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
  const { markTabComplete, setCurrentShot, downloadChapterMaterials, generateShotVideo, generateKeyframeImage, setShots, setShotVideos, checkVideoTaskStatus, generateTransition, transitionWorkflows, selectedTransitionWorkflow, setSelectedTransitionWorkflow, fetchTransitionWorkflows, transitionDuration, setTransitionDuration } = store;

  // 直接订阅 store 状态（确保状态更新时组件重新渲染）
  const storeShots = useChapterGenerateStore((state) => state.shots);
  const storeShotVideos = useChapterGenerateStore((state) => state.shotVideos);
  const storeShotImages = useChapterGenerateStore((state) => state.shotImages);
  const storeTransitionVideos = useChapterGenerateStore((state) => state.transitionVideos);
  const storeGeneratingVideos = useChapterGenerateStore((state) => state.generatingVideos);
  const storeGeneratingTransitions = useChapterGenerateStore((state) => state.generatingTransitions);

  // 优先使用 store 状态，props 作为备用
  const shotVideos = storeShotVideos;
  const shotImages = storeShotImages;
  const transitionVideos = storeTransitionVideos;
  const generatingVideos = propGeneratingVideos ?? storeGeneratingVideos;
  const generatingTransitions = propGeneratingTransitions ?? storeGeneratingTransitions;

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
  const [selectedShots, setSelectedShots] = useState<Set<number>>(new Set());
  const [batchSelectionMode, setBatchSelectionMode] = useState<BatchSelectionMode>(null);
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
  const [showMergeMenu, setShowMergeMenu] = useState(false);
  const [showMergeModal, setShowMergeModal] = useState(false);
  const [mergedVideoUrl, setMergedVideoUrl] = useState<string | null>(null);
  const [isRefreshingVideo, setIsRefreshingVideo] = useState(false);
  const [videoMetadata, setVideoMetadata] = useState<VideoMetadata>({
    duration: null,
    width: null,
    height: null,
    sizeBytes: null,
  });

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
  const [recommendingShotId, setRecommendingShotId] = useState<string | null>(null);

  const hasShotVideo = (shot: any) => {
    const shotId = shot?.id ? String(shot.id) : '';
    return !!(shot?.videoUrl || (shotId && shotVideos[shotId]));
  };

  // 检查当前分镜是否正在生成
  const isGeneratingCurrent = currentShotId ? generatingVideos.has(currentShotId) : false;

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

  const handleRecommendVideoMode = useCallback(async (force = false) => {
    if (!effectiveNovelId || !effectiveChapterId || !currentShotId) return;
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
  }, [currentShotId, effectiveChapterId, effectiveNovelId, updateCurrentShotVideoDirectorPlan]);

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
    if (!effectiveNovelId || !effectiveChapterId || !currentShotId) return;
    setRecommendingShotId(currentShotId);
    try {
      const result = await shotsApi.planVideoKeyframes(effectiveNovelId, effectiveChapterId, currentShotId, force);
      if (result.success && result.data) {
        updateCurrentShotVideoDirectorPlan(result.data);
        toast.success('关键帧规划已生成');
      } else {
        toast.error(result.message || (result as any).detail || '关键帧规划失败');
      }
    } catch (error) {
      console.error('关键帧规划失败:', error);
      toast.error('关键帧规划失败');
    } finally {
      setRecommendingShotId(null);
    }
  }, [currentShotId, effectiveChapterId, effectiveNovelId, updateCurrentShotVideoDirectorPlan]);

  const handleGenerateMissingKeyframes = useCallback(async () => {
    if (!effectiveNovelId || !effectiveChapterId || !currentShotId || !currentShotData) return;
    const planKeyframes = currentVideoDirectorPlan.keyframes || [];
    const legacyKeyframes = currentShotData.keyframes || [];
    const nonStartPlanKeyframes = planKeyframes.filter((keyframe: any) => keyframe.role !== 'START');
    const missingLegacyKeyframes = nonStartPlanKeyframes
      .filter((keyframe: any) => {
        const legacyKeyframe = legacyKeyframes.find((item: any) => Number(item.plan_keyframe_index) === Number(keyframe.index));
        return !keyframe.image_url && !legacyKeyframe?.image_url;
      })
      .map((keyframe: any, index: number) => {
        const mappedKeyframe = legacyKeyframes.find((item: any) => Number(item.plan_keyframe_index) === Number(keyframe.index));
        if (mappedKeyframe) return mappedKeyframe;
        return legacyKeyframes[index] || { frame_index: index };
      })
      .filter((keyframe: any) => keyframe && !keyframe.image_url && keyframe.frame_index !== undefined);

    if (missingLegacyKeyframes.length === 0) {
      toast.info('没有缺失的关键帧图片');
      return;
    }

    try {
      for (const keyframe of missingLegacyKeyframes) {
        await generateKeyframeImage(effectiveNovelId, effectiveChapterId, currentShotId, Number(keyframe.frame_index));
      }
      toast.success(`已提交 ${missingLegacyKeyframes.length} 个关键帧图片任务`);
    } catch (error) {
      console.error('生成缺失关键帧失败:', error);
      toast.error('生成缺失关键帧失败');
    }
  }, [currentShotData, currentShotId, currentVideoDirectorPlan.keyframes, effectiveChapterId, effectiveNovelId, generateKeyframeImage]);

  useEffect(() => {
    if (!effectiveNovelId || !effectiveChapterId || !currentShotId) return;
    if (currentVideoDirectorPlan.recommended_mode || recommendingShotId === currentShotId) return;
    handleRecommendVideoMode(false);
  }, [currentShotId, currentVideoDirectorPlan.recommended_mode, effectiveChapterId, effectiveNovelId, handleRecommendVideoMode, recommendingShotId]);

  useEffect(() => {
    setVideoMetadata({ duration: null, width: null, height: null, sizeBytes: null });
    if (!currentShotVideoUrl) return;

    let cancelled = false;
    fetch(currentShotVideoUrl, { method: 'HEAD' })
      .then((response) => {
        if (cancelled) return;
        const contentLength = response.headers.get('content-length');
        setVideoMetadata((metadata) => ({
          ...metadata,
          sizeBytes: contentLength ? Number(contentLength) : null,
        }));
      })
      .catch(() => {
        // Some file servers may not expose Content-Length for HEAD requests.
      });

    return () => {
      cancelled = true;
    };
  }, [currentShotVideoUrl]);

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

  const hasVideo = !!currentShotVideoUrl;

  // 处理单个视频生成
  const handleGenerateVideo = async () => {
    if (!effectiveNovelId || !effectiveChapterId || !currentShotId) return;
    if (hasVideo && !window.confirm('视频已存在，确认删除旧的吗？')) return;

    try {
      await generateShotVideo(effectiveNovelId, effectiveChapterId, currentShotId, currentSelectedVideoMode);
      markTabComplete(3);
    } catch (error) {
      console.error(t('chapterGenerate.videoGenerateFailed') + ':', error);
      toast.error(error instanceof Error ? error.message : t('chapterGenerate.videoGenerateFailed'));
    }
  };

  // 打开批量选择弹窗
  const handleOpenBatchSelect = () => {
    setSelectedShots(new Set(shotsList.map((_: any, idx: number) => idx + 1)));
    setBatchSelectionMode('all');
    setShowBatchSelectModal(true);
  };

  // 切换分镜选择状态
  const toggleShotSelection = (index: number) => {
    setSelectedShots(prev => {
      const newSet = new Set(prev);
      if (newSet.has(index)) {
        newSet.delete(index);
      } else {
        newSet.add(index);
      }
      setBatchSelectionMode(null);
      return newSet;
    });
  };

  // 全选/取消全选
  const toggleSelectAll = () => {
    if (batchSelectionMode === 'all') {
      setSelectedShots(new Set());
      setBatchSelectionMode(null);
    } else {
      setSelectedShots(new Set(shotsList.map((_: any, idx: number) => idx + 1)));
      setBatchSelectionMode('all');
    }
  };

  const toggleSelectPendingVideos = () => {
    if (batchSelectionMode === 'pending') {
      setSelectedShots(new Set());
      setBatchSelectionMode(null);
      return;
    }

    const pendingShots = shotsList
      .map((shot: any, idx: number) => {
        const shotId = shot?.id ? String(shot.id) : '';
        const isGenerating = shotId ? generatingVideos.has(shotId) : false;
        return !hasShotVideo(shot) && !isGenerating ? idx + 1 : null;
      })
      .filter((index: number | null): index is number => index !== null);

    setSelectedShots(new Set(pendingShots));
    setBatchSelectionMode('pending');
  };

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
    const selectedShotList = Array.from(selectedShots)
      .map(index => shotsList[index - 1])
      .filter(Boolean);
    if (selectedShotList.some(hasShotVideo) && !window.confirm('视频已存在，确认删除旧的吗？')) return;

    setIsGeneratingAll(true);
    try {
      // 依次生成选中的分镜
      for (const shot of selectedShotList) {
        if (shot?.id) {
          const plan = shot.videoDirectorPlan || {};
          await generateShotVideo(
            effectiveNovelId,
            effectiveChapterId,
            shot.id,
            plan.selected_mode || plan.recommended_mode || 'SINGLE_FRAME'
          );
        }
      }
    } catch (error) {
      console.error(t('chapterGenerate.batchVideoGenerateFailed') + ':', error);
    } finally {
      setIsGeneratingAll(false);
      setShowBatchSelectModal(false);
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

  const handleSaveShortcut = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
      event.preventDefault();
      event.stopPropagation();
      handleSaveShot();
    }
  };

  const copyVideoDescription = async () => {
    const content = currentShotData?.video_description || '';
    if (!content) return;
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(content);
      } else {
        const textarea = document.createElement('textarea');
        textarea.value = content;
        textarea.style.position = 'fixed';
        textarea.style.left = '-9999px';
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
      }
      toast.success(t('common.copied'));
    } catch (error) {
      console.error('复制视频描述失败:', error);
      toast.error(t('common.copyFailed'));
    }
  };

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

  // 处理合并视频
  const handleMergeVideos = async (mode: MergeVideoMode) => {
    if (!effectiveNovelId || !effectiveChapterId) return;

    // 从 shots 数据中获取所有视频 URL
    const videoList = shotsList
      .filter((shot: any) => shot.videoUrl || shotVideos[shot.id])
      .map((shot: any) => shot.videoUrl || shotVideos[shot.id])
      .filter(Boolean);

    if (videoList.length === 0) {
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
          body: JSON.stringify({ mode })
        }
      );

      const data = await response.json();

      if (response.ok && data.success) {
        setMergedVideoUrl(data.video_url);
        setShowMergeModal(true);
        toast.success(t(data.cache_hit ? 'chapterGenerate.mergeCacheHit' : 'chapterGenerate.mergeSuccess'));
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
      {/* 操作栏 */}
      <div className="flex-shrink-0 flex items-center justify-between mb-4 pb-4 border-b border-gray-200">
        <div className="flex items-center gap-4">
          <button
            onClick={handleGenerateVideo}
            disabled={isGeneratingCurrent || !effectiveChapterId}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
          >
            {isGeneratingCurrent ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                {t('chapterGenerate.videoGenerating')}
              </>
            ) : (
              <>
                <Film className="w-4 h-4" />
                生成当前 Shot 视频
              </>
            )}
          </button>
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
          <div
            className="relative"
            onBlur={(event) => {
              if (!event.relatedTarget || !event.currentTarget.contains(event.relatedTarget as Node)) {
                setShowMergeMenu(false);
              }
            }}
            onKeyDown={(event) => {
              if (event.key === 'Escape') setShowMergeMenu(false);
            }}
          >
            <button
              onClick={() => setShowMergeMenu((visible) => !visible)}
              disabled={mergingMode !== null || !effectiveChapterId || videoCount === 0}
              className="px-4 py-2 bg-pink-600 text-white rounded-lg hover:bg-pink-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
              aria-haspopup="menu"
              aria-expanded={showMergeMenu}
            >
              {mergingMode ? <Loader2 className="w-4 h-4 animate-spin" /> : <Combine className="w-4 h-4" />}
              {mergingMode ? t('chapterGenerate.merging') : t('chapterGenerate.mergeVideo')}
              {!mergingMode && <ChevronDown className={`w-4 h-4 transition-transform ${showMergeMenu ? 'rotate-180' : ''}`} />}
            </button>
            {showMergeMenu && !mergingMode && (
              <div className="absolute right-0 top-full mt-2 min-w-56 overflow-hidden rounded-lg border border-gray-200 bg-white py-1 shadow-lg z-30" role="menu">
                <button
                  onClick={() => {
                    setShowMergeMenu(false);
                    handleMergeVideos('shots_only');
                  }}
                  className="w-full px-4 py-2.5 text-left text-sm text-gray-700 hover:bg-pink-50 hover:text-pink-700 transition-colors"
                  role="menuitem"
                >
                  {t('chapterGenerate.mergeShotsOnly')}
                </button>
                <button
                  onClick={() => {
                    setShowMergeMenu(false);
                    handleMergeVideos('shots_with_transitions');
                  }}
                  disabled={Object.keys(transitionVideos).length === 0}
                  className="w-full px-4 py-2.5 text-left text-sm text-gray-700 hover:bg-pink-50 hover:text-pink-700 disabled:text-gray-300 disabled:hover:bg-white disabled:cursor-not-allowed transition-colors"
                  role="menuitem"
                >
                  {t('chapterGenerate.mergeShotsAndTransitions')}
                </button>
              </div>
            )}
          </div>
        </div>
        <div className="text-sm text-gray-500">
          {t('chapterGenerate.shotId', { id: selectedVideo || 0, total: shotsList.length })}
        </div>
      </div>

      {/* 内容区 - 主编辑区 + 右侧视频预览 */}
      <div className="flex-1 min-h-0 flex flex-col lg:flex-row gap-4 overflow-hidden">
        {/* 中间：视频提示词编辑 + 视频导演 */}
        <div className="video-main-column flex-1 min-w-0 flex flex-col gap-4 overflow-y-auto pr-1">
          {/* 时长设置 */}
          <div className="flex-shrink-0 border border-gray-200 rounded-lg p-4">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <label className="text-sm font-medium text-gray-700">{t('chapterGenerate.durationLabel')}</label>
                <input
                  type="number"
                  value={currentShotData?.duration || 5}
                  onChange={(e) => {
                    const shotIndex = selectedVideo - 1;
                    if (shotsList[shotIndex]) {
                      const updatedShots = shotsList.map((s: any, idx: number) =>
                        idx === shotIndex
                          ? { ...s, duration: Math.min(180, Math.max(1, parseInt(e.target.value) || 5)) }
                          : s
                      );
                      setShots(updatedShots);
                    }
                  }}
                  min={1}
                  max={180}
                  className="w-20 px-2 py-1 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <span className="text-sm text-gray-500">{t('common.second')}</span>
              </div>
              <span className="text-xs text-gray-400">{t('common.recommended')} 3-10 {t('common.second')}，{t('common.max')} 180 {t('common.second')}</span>
            </div>
          </div>

          {/* 视频提示词编辑区 */}
          <div className="video-description-card flex-shrink-0 border border-gray-200 rounded-lg p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-medium text-gray-700">{t('chapterGenerate.videoDescForVideo')}</h3>
              <button
                type="button"
                onClick={copyVideoDescription}
                disabled={!currentShotData?.video_description}
                className="p-1.5 text-gray-400 hover:text-blue-600 transition-colors rounded hover:bg-blue-50 disabled:opacity-40 disabled:cursor-not-allowed"
                title={t('common.copy')}
                aria-label={t('common.copy')}
              >
                <Copy className="h-4 w-4" />
              </button>
            </div>
            <textarea
              value={currentShotData?.video_description || ''}
              onKeyDown={handleSaveShortcut}
              onChange={(e) => {
                const shotIndex = selectedVideo - 1;
                if (shotsList[shotIndex]) {
                  const updatedShots = shotsList.map((s: any, idx: number) =>
                    idx === shotIndex
                      ? { ...s, video_description: e.target.value }
                      : s
                  );
                  setShots(updatedShots);
                }
              }}
              placeholder={t('chapterGenerate.videoDescPlaceholder')}
              className="video-description-textarea w-full h-40 px-3 py-2 border border-gray-300 rounded-lg resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
            />
            <div className="mt-2 flex items-center gap-2 text-xs text-gray-500">
              <span>{t('chapterGenerate.placeholderHint')}</span>
              <span className="px-1.5 py-0.5 bg-gray-100 rounded">{t('chapterGenerate.placeholderStyle')}</span>
              <span className="px-1.5 py-0.5 bg-gray-100 rounded">{t('chapterGenerate.placeholderScene')}</span>
              <span className="px-1.5 py-0.5 bg-gray-100 rounded">{t('chapterGenerate.placeholderCharacters')}</span>
            </div>
          </div>

          <VideoDirectorPanel
            shot={currentShotData}
            shotImageUrl={currentShotImageUrl}
            plan={currentVideoDirectorPlan}
            isRecommending={recommendingShotId === currentShotId}
            onRecommend={handleRecommendVideoMode}
            onPlanKeyframes={handlePlanVideoKeyframes}
            onGenerateMissingKeyframes={handleGenerateMissingKeyframes}
            onSelectMode={handleSelectVideoMode}
          />

        </div>

        {/* 右侧：视频预览区 */}
        <div className="video-preview-card flex-shrink-0 lg:w-[360px] xl:w-[420px] min-h-[360px] lg:min-h-0 flex flex-col border border-gray-200 rounded-lg overflow-hidden bg-white">
          <div className="flex-shrink-0 p-3 border-b border-gray-200 bg-gray-50 flex items-center justify-between">
            <h3 className="text-sm font-medium text-gray-700">{t('chapterGenerate.videoPreview')}</h3>
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

          <div className="video-preview-body flex-1 relative bg-gray-100">
            {hasVideo ? (
              <video
                src={currentShotVideoUrl}
                className="absolute inset-0 w-full h-full object-contain"
                controls
                onLoadedMetadata={handleVideoMetadataLoaded}
              />
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
          {hasVideo && (
            <div className="flex-shrink-0 border-t border-gray-200 bg-white px-3 py-2 text-xs text-gray-600 flex flex-wrap items-center gap-x-4 gap-y-1">
              <span>时长：{formatDuration(videoMetadata.duration)}</span>
              <span>分辨率：{videoMetadata.width && videoMetadata.height ? `${videoMetadata.width} x ${videoMetadata.height}` : '-'}</span>
              <span>大小：{formatFileSize(videoMetadata.sizeBytes)}</span>
              <span>码率：{formatBitrate(videoMetadata.sizeBytes, videoMetadata.duration)}</span>
            </div>
          )}
        </div>

      </div>

      {/* 批量选择分镜弹窗 */}
      {showBatchSelectModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
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
                  {t('chapterGenerate.selectedShots', { selected: selectedShots.size, total: shotsList.length })}
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
                  const shotId = shot.id;
                  const isSelected = selectedShots.has(shotIndex);
                  const hasVideo = hasShotVideo(shot);
                  const isGenerating = shotId ? generatingVideos.has(shotId) : false;
                  const isPending = !hasVideo && !isGenerating;

                  return (
                    <div
                      key={shot.id || `shot-${shotIndex}`}
                      onClick={() => !isGenerating && toggleShotSelection(shotIndex)}
                      className={`
                        relative aspect-video rounded-lg border-2 transition-all
                        ${isGenerating
                          ? 'border-gray-200 bg-gray-50 cursor-not-allowed'
                          : 'cursor-pointer hover:shadow-md'
                        }
                        ${!isGenerating && isSelected
                          ? 'border-blue-500 bg-blue-50'
                          : !isGenerating && !isSelected
                            ? hasVideo
                              ? 'border-gray-300 bg-white hover:border-blue-300'
                              : 'border-gray-300 bg-white hover:border-gray-400'
                            : ''
                        }
                      `}
                    >
                      {/* 分镜编号 */}
                      <div className="absolute top-1 left-1 px-1.5 py-0.5 bg-black/60 text-white text-xs rounded">
                        #{shotIndex}
                      </div>

                      {/* 选择标记 - 所有非生成中的分镜都显示 */}
                      {!isGenerating && (
                        <div className={`
                          absolute top-1 right-1 w-5 h-5 rounded-full flex items-center justify-center
                          ${isSelected ? 'bg-blue-500' : 'bg-gray-200'}
                        `}>
                          {isSelected && <Check className="w-3 h-3 text-white" />}
                        </div>
                      )}

                      {/* 内容区域 */}
                      <div className="w-full h-full flex items-center justify-center">
                        {hasVideo ? (
                          <Film className="w-8 h-8 text-green-600" />
                        ) : isGenerating ? (
                          <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
                        ) : (
                          <Film className="w-8 h-8 text-gray-300" />
                        )}
                      </div>

                      {/* 状态标签 */}
                      <div className="absolute bottom-0 left-0 right-0 px-1 py-0.5 text-xs text-center bg-black/60 text-white rounded-b-lg">
                        {hasVideo ? t('chapterGenerate.generated') : isGenerating ? t('chapterGenerate.generating') : t('chapterGenerate.pending')}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* 弹窗底部按钮 */}
            <div className="flex items-center justify-end gap-3 p-4 border-t border-gray-200">
              <button
                onClick={() => setShowBatchSelectModal(false)}
                className="px-4 py-2 text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors"
              >
                {t('common.cancel')}
              </button>
              <button
                onClick={handleGenerateAll}
                disabled={selectedShots.size === 0 || isGeneratingAll}
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
                    {t('chapterGenerate.generateShots', { count: selectedShots.size })}
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 图片预览弹窗 */}
      <ImagePreviewModal
        isOpen={!!previewImage}
        url={previewImage}
        onClose={() => setPreviewImage(null)}
        showDownload={true}
      />

      {/* 合并视频结果弹窗 */}
      {showMergeModal && mergedVideoUrl && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
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
