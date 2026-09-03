/**
 * ChapterGenerateLayout - 分镜生成页面主布局组件
 *
 * 整合：
 * - Header (返回按钮 + 章节标题)
 * - TabNavigation (四阶段 Tab)
 * - ThreeColumnLayout (三栏容器)
 * - BottomNavigator (底部导航)
 */

import { useEffect, useRef, useState } from 'react';
import type React from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { ArrowLeft, ChevronLeft, ChevronRight } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import { useChapterGenerateStore } from '../stores';
import { novelApi } from '../../../api/novels';
import { shotsApi } from '../../../api/shots';
import type { Chapter } from '../../../types';
import { toast } from '../../../stores/toastStore';
import { DIALOGUE_WARNING_STYLES, getDialogueDurationWarningStats } from '../../../utils';

// 布局组件
import { ThreeColumnLayout } from './ThreeColumnLayout';
import { TabNavigation } from './TabNavigation';
import { BottomNavigator } from './BottomNavigator';
import { ResourcePanel } from './ResourcePanel';
import { ShotForm } from './ShotForm';

// Tab 页面组件
import { ShotSplitTab } from './ShotSplitTab';
import { AudioGenTab } from './AudioGenTab';
import { ShotImageGenTab } from './ShotImageGenTab';
import { VideoGenTab } from './VideoGenTab';
import { ShotImageList } from './ShotImageList';

interface ChapterGenerateLayoutProps {
  /** 章节数据 */
  chapter?: any;
  /** 小说数据 */
  novel?: any;
  /** 分镜数据 */
  parsedData?: any;
  /** 分镜图片映射（key 为 shotId） */
  shotImages?: Record<string, string>;
  /** 分镜视频映射 */
  shotVideos?: Record<string, string>;
  /** 转场视频映射 */
  transitionVideos?: Record<string, string>;
  /** 角色列表 */
  characters?: any[];
  /** 场景列表 */
  scenes?: any[];
  /** 道具列表 */
  props?: any[];
  /** 生成中的分镜 */
  generatingShots?: Set<string>;
  /** 待生成的分镜 */
  pendingShots?: Set<string>;
  /** 生成中的视频 */
  generatingVideos?: Set<string>;
  /** 待生成的视频 */
  pendingVideos?: Set<string>;
  /** 生成中的转场 */
  generatingTransitions?: Set<string>;
  /** 加载状态 */
  loading?: boolean;
  /** 获取角色图片方法 */
  getCharacterImage?: (name: string) => string | undefined;
  /** 获取场景图片方法 */
  getSceneImage?: (name: string) => string | null;
  /** 获取道具图片方法 */
  getPropImage?: (name: string) => string | null;
  /** 章节资源管理弹窗打开回调 */
  onResourcesManageClick?: () => void;
  /** 图片点击查看大图回调 */
  onImageClick?: (url: string) => void;
}

export function ChapterGenerateLayout({
  chapter: propChapter,
  novel: propNovel,
  parsedData: propParsedData,
  shotImages: propShotImages = {},
  shotVideos: propShotVideos = {},
  transitionVideos = {},
  characters = [],
  scenes = [],
  props = [],
  generatingShots: propGeneratingShots = new Set(),
  pendingShots: propPendingShots = new Set(),
  generatingVideos: propGeneratingVideos = new Set(),
  pendingVideos: propPendingVideos = new Set(),
  generatingTransitions = new Set(),
  loading = false,
  getCharacterImage,
  getSceneImage,
  getPropImage,
  onResourcesManageClick,
  onImageClick,
}: ChapterGenerateLayoutProps) {
  const { t } = useTranslation();
  const { id, cid } = useParams<{ id: string; cid: string }>();
  const navigate = useNavigate();
  const [bottomNavCollapsed, setBottomNavCollapsed] = useState(false);
  const [chapterList, setChapterList] = useState<Chapter[]>([]);
  const [isSavingShots, setIsSavingShots] = useState(false);
  const [openVideoStatsKey, setOpenVideoStatsKey] = useState<string | null>(null);
  const initialShotHashAppliedRef = useRef(false);
  const pendingShotHashIndexRef = useRef<number | null>(null);

  // 使用选择器正确订阅 store 状态
  const storeParsedData = useChapterGenerateStore((state) => state.parsedData);
  const storeChapter = useChapterGenerateStore((state) => state.chapter);
  const storeNovel = useChapterGenerateStore((state) => state.novel);
  const currentTab = useChapterGenerateStore((state) => state.currentTab);
  const currentShotIndex = useChapterGenerateStore((state) => state.currentShotIndex);
  const currentShotId = useChapterGenerateStore((state) => state.currentShotId);
  const leftPanelCollapsed = useChapterGenerateStore((state) => state.leftPanelCollapsed);
  const rightPanelCollapsed = useChapterGenerateStore((state) => state.rightPanelCollapsed);
  const setCurrentTab = useChapterGenerateStore((state) => state.setCurrentTab);
  const markTabComplete = useChapterGenerateStore((state) => state.markTabComplete);
  const loadWorkflowState = useChapterGenerateStore((state) => state.loadWorkflowState);
  const setCurrentShot = useChapterGenerateStore((state) => state.setCurrentShot);
  const setRightPanelCollapsed = useChapterGenerateStore((state) => state.setRightPanelCollapsed);
  const setRightPanelWidth = useChapterGenerateStore((state) => state.setRightPanelWidth);
  const saveChapterResources = useChapterGenerateStore((state) => state.saveChapterResources);
  const storeShots = useChapterGenerateStore((state) => state.shots);
  const storeGeneratingShots = useChapterGenerateStore((state) => state.generatingShots);
  const storePendingShots = useChapterGenerateStore((state) => state.pendingShots);
  const storeGeneratingVideos = useChapterGenerateStore((state) => state.generatingVideos);
  const storePendingVideos = useChapterGenerateStore((state) => state.pendingVideos);
  const storeShotImages = useChapterGenerateStore((state) => state.shotImages);
  const storeShotVideos = useChapterGenerateStore((state) => state.shotVideos);
  const setShots = useChapterGenerateStore((state) => state.setShots);

  // 优先从 store 获取最新数据，确保与 ShotSplitTab 等组件同步
  const parsedData = storeParsedData || propParsedData;
  const chapter = storeChapter || propChapter;
  const novel = storeNovel || propNovel;

  // 调试日志：打印 store 中的状态
  console.log('[ChapterGenerateLayout] storeGeneratingShots:', [...storeGeneratingShots]);
  console.log('[ChapterGenerateLayout] storeShotImages keys:', Object.keys(storeShotImages));

  // 直接使用 store 状态（组件已通过选择器订阅，状态更新时自动重新渲染）
  const generatingShots = storeGeneratingShots;
  const pendingShots = storePendingShots;
  const generatingVideos = storeGeneratingVideos;
  const pendingVideos = storePendingVideos;
  const shotImages = storeShotImages;
  const shotVideos = storeShotVideos;

  console.log('[ChapterGenerateLayout] final generatingShots:', [...generatingShots]);

  // 获取分镜列表（统一使用 store.shots）
  const shots = storeShots;
  const currentShotById = currentShotId ? shots.find((shot) => shot.id === currentShotId) : undefined;
  const currentShot = currentShotById || shots[currentShotIndex - 1];
  const sortedChapters = [...chapterList].sort((a, b) => a.number - b.number);
  const currentChapterIndex = sortedChapters.findIndex((item) => item.id === cid);
  const previousChapter = currentChapterIndex > 0 ? sortedChapters[currentChapterIndex - 1] : null;
  const nextChapter = currentChapterIndex >= 0 && currentChapterIndex < sortedChapters.length - 1
    ? sortedChapters[currentChapterIndex + 1]
    : null;
  const estimatedDuration = shots.reduce((total, shot) => total + (Number(shot.duration) || 0), 0);
  const estimatedMinutes = Math.floor(estimatedDuration / 60).toString().padStart(2, '0');
  const estimatedSeconds = Math.round(estimatedDuration % 60).toString().padStart(2, '0');
  const currentShotDuration = Number(currentShot?.duration) || 0;
  const chapterWordCount = (chapter?.content || '').replace(/\s/g, '').length;
  const chapterSummary = `${chapterWordCount.toLocaleString()} 字 · ${shots.length} 个导演 Shot · 预计成片 ${estimatedMinutes}:${estimatedSeconds} · 当前 Shot #${currentShotIndex || 1} · 当前时长 ${currentShotDuration}秒`;
  const hasQueueStats = pendingShots.size > 0 || pendingVideos.size > 0;
  const dialogueWarningStats = getDialogueDurationWarningStats(shots);
  const parsePlanTime = (value?: string | null) => {
    if (!value) return 0;
    const time = new Date(value).getTime();
    return Number.isFinite(time) ? time : 0;
  };
  const videoStats = shots.reduce((stats, shot) => {
    const shotId = String(shot.id || '');
    const plan: any = shot.videoDirectorPlan || {};
    const mode = plan.selected_mode || plan.recommended_mode || 'SINGLE_FRAME';
    const clips = mode === 'MULTI_KEYFRAME' && Array.isArray(plan.window_plans) ? plan.window_plans : [];
    const hasShotVideo = !!(shot.videoUrl || shotVideos[shotId] || plan.merged_video_url);
    const isGenerating = generatingVideos.has(shotId) || pendingVideos.has(shotId) || shot.videoStatus === 'generating' || shot.videoStatus === 'pending';
    const isFailed = shot.videoStatus === 'failed';
    const allClipsReady = clips.length > 0 && clips.every((clip: any) => !!(clip.video_url || clip.local_path));
    const latestClipGeneratedAt = Math.max(0, ...clips.map((clip: any) => parsePlanTime(clip.generated_at)));
    const mergedAt = parsePlanTime(plan.merged_at);
    const needsMerge = mode === 'MULTI_KEYFRAME' && allClipsReady && (!hasShotVideo || !mergedAt || latestClipGeneratedAt > mergedAt);

    if (isGenerating) stats.generating.push(shot);
    else if (needsMerge) stats.needsMerge.push(shot);
    else if (hasShotVideo) stats.completed.push(shot);
    else if (isFailed) stats.failed.push(shot);
    else stats.incomplete.push(shot);
    return stats;
  }, { completed: [] as any[], generating: [] as any[], failed: [] as any[], needsMerge: [] as any[], incomplete: [] as any[] });

  const renderVideoGenerationStats = () => {
    if (currentTab !== 3 || shots.length === 0) return null;
    const items = [
      ['completed', '已完成', videoStats.completed, 'border-green-100 bg-green-50 text-green-700'],
      ['generating', '生成中', videoStats.generating, 'border-blue-100 bg-blue-50 text-blue-700'],
      ['needsMerge', '待合并', videoStats.needsMerge, 'border-amber-100 bg-amber-50 text-amber-700'],
      ['failed', '失败', videoStats.failed, 'border-red-100 bg-red-50 text-red-700'],
      ['incomplete', '未完成', videoStats.incomplete, 'border-gray-200 bg-gray-50 text-gray-600'],
    ] as const;

    return (
      <div className="flex items-center gap-2 rounded-full border border-gray-200 bg-white px-3 py-1 text-xs shadow-sm">
        <span className="font-medium text-gray-700">视频生成结果</span>
        {items.map(([key, label, shotItems, className]) => (
          <span key={key} className="relative inline-flex">
            <button
              type="button"
              onClick={() => setOpenVideoStatsKey(openVideoStatsKey === key ? null : key)}
              className={`rounded-full border px-2 py-0.5 ${className}`}
            >
              {label} {shotItems.length}
            </button>
            {openVideoStatsKey === key && (
            <span className="absolute left-1/2 top-full z-[90] w-64 -translate-x-1/2 pt-2">
              <span className="block rounded-lg border border-gray-200 bg-white p-2 text-left shadow-xl">
                <span className="mb-2 block text-xs font-medium text-gray-700">{label}分镜编号</span>
                {shotItems.length > 0 ? (
                  <span className="block max-h-72 overflow-y-auto">
                    {shotItems.map((shot: any) => (
                      <button
                        key={shot.id || shot.index}
                        type="button"
                        onClick={() => {
                          setCurrentShot(String(shot.id), Number(shot.index || 1));
                          setOpenVideoStatsKey(null);
                        }}
                        className="mr-1 mb-1 rounded-md border border-gray-200 bg-gray-50 px-2 py-1 text-xs text-gray-700 hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700"
                      >
                        镜{shot.index || '-'}
                      </button>
                    ))}
                  </span>
                ) : (
                  <span className="block text-xs text-gray-400">暂无分镜</span>
                )}
              </span>
            </span>
            )}
          </span>
        ))}
      </div>
    );
  };
  const renderQueueStats = () => {
    if (!hasQueueStats) return null;
    return (
      <div className="flex flex-wrap items-center gap-2 text-xs text-gray-600">
        <span className="rounded-full border border-blue-100 bg-blue-50 px-2.5 py-1 text-blue-700">
          生成分镜图：待处理 {pendingShots.size} 个
        </span>
        <span className="rounded-full border border-purple-100 bg-purple-50 px-2.5 py-1 text-purple-700">
          生成视频：待处理 {pendingVideos.size} 个
        </span>
      </div>
    );
  };
  const renderDialogueWarningStats = () => {
    if (currentTab !== 0 || dialogueWarningStats.checkedCount === 0) return null;
    const items = [
      ['normal', '正常'],
      ['notice', '提醒'],
      ['warning', '警告'],
      ['critical', '严重'],
    ] as const;

    return (
      <div className="flex items-center gap-2 rounded-full border border-gray-200 bg-white px-3 py-1 text-xs shadow-sm">
        <span className="font-medium text-gray-700">台词时长预警</span>
        {items.map(([level, label]) => (
          <span key={level} className={`rounded-full px-2 py-0.5 ${DIALOGUE_WARNING_STYLES[level].badgeClassName}`}>
            {label} {dialogueWarningStats.stats[level]}
          </span>
        ))}
      </div>
    );
  };

  const updateCurrentShot = (updates: Record<string, any>) => {
    if (!currentShot) return;
    setShots(shots.map((shot) => shot.id === currentShot.id ? { ...shot, ...updates } : shot));
  };

  const saveShotSplitData = async (shotsToSave = shots, successMessage = t('chapterGenerate.shotSaveSuccess')) => {
    if (!id || !cid || isSavingShots) return;
    setIsSavingShots(true);
    try {
      await saveChapterResources(id, cid);
      if (shotsToSave.length > 0) {
        const result = await shotsApi.batchUpdateShots(
          id,
          cid,
          shotsToSave.map((shot) => ({
            id: shot.id,
            description: shot.description,
            video_description: shot.video_description,
            characters: shot.characters,
            scene: shot.scene,
            props: shot.props,
            duration: shot.duration,
            continuity_mode: shot.continuity_mode || 'NORMAL',
            dialogues: shot.dialogues,
          }))
        );
        if (!result.success) {
          throw new Error(result.message || t('common.unknownError'));
        }
      }
      markTabComplete(0);
      toast.success(successMessage);
    } catch (error) {
      console.error(t('chapterGenerate.saveFailed') + ':', error);
      toast.error(t('chapterGenerate.saveFailedRetry'));
    } finally {
      setIsSavingShots(false);
    }
  };

  const copyCurrentShotVideoDescription = async () => {
    const content = currentShot?.video_description || '';
    if (!content) return;
    try {
      await navigator.clipboard.writeText(content);
      toast.success('已复制视频描述');
    } catch {
      toast.error('复制视频描述失败');
    }
  };

  const goToChapter = (chapterId?: string) => {
    if (!id || !chapterId) return;
    navigate(`/novels/${id}/chapters/${chapterId}/generate`);
  };

  const parseShotHash = () => {
    const hash = window.location.hash.replace(/^#/, '').trim();
    const match = hash.match(/^(?:shot-?|s)?(\d+)$/i);
    if (!match) return null;
    const index = Number(match[1]);
    return Number.isFinite(index) && index > 0 ? index : null;
  };

  const updateShotHash = (index: number) => {
    if (!index) return;
    const nextHash = `#shot-${index}`;
    if (window.location.hash === nextHash) return;
    window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}${nextHash}`);
  };

  const renderChapterContent = () => {
    const content = chapter?.content || t('common.noContent');
    const ranges = ((currentShot as any)?.sourceRanges || (currentShot as any)?.source_ranges || []) as { start: number; end: number }[];
    if (!chapter?.content || !Array.isArray(ranges) || ranges.length === 0) {
      return <div className="text-sm text-gray-600 whitespace-pre-wrap leading-relaxed">{content}</div>;
    }

    const normalizedRanges = ranges
      .map((range) => ({
        start: Math.max(0, Math.min(content.length, Number(range.start))),
        end: Math.max(0, Math.min(content.length, Number(range.end))),
      }))
      .filter((range) => range.end > range.start)
      .sort((a, b) => a.start - b.start);

    if (normalizedRanges.length === 0) {
      return <div className="text-sm text-gray-600 whitespace-pre-wrap leading-relaxed">{content}</div>;
    }

    const parts: React.ReactNode[] = [];
    let cursor = 0;
    normalizedRanges.forEach((range, index) => {
      if (range.start > cursor) parts.push(content.slice(cursor, range.start));
      parts.push(
        <mark key={`${range.start}-${range.end}-${index}`} className="bg-yellow-100 text-gray-900 rounded px-0.5">
          {content.slice(range.start, range.end)}
        </mark>
      );
      cursor = range.end;
    });
    if (cursor < content.length) parts.push(content.slice(cursor));

    return <div className="text-sm text-gray-600 whitespace-pre-wrap leading-relaxed">{parts}</div>;
  };

  useEffect(() => {
    if (id && cid) {
      loadWorkflowState(id, cid);
    }
  }, [id, cid, loadWorkflowState]);

  useEffect(() => {
    if (!id) return;
    novelApi.fetchChapters(id).then((res) => {
      if (res.success && res.data) setChapterList(res.data);
    }).catch((error) => {
      console.error('加载章节列表失败:', error);
    });
  }, [id]);

  useEffect(() => {
    if (currentTab !== 0) return;
    setRightPanelCollapsed(false);
    setRightPanelWidth(760);
  }, [currentTab, setRightPanelCollapsed, setRightPanelWidth]);

  useEffect(() => {
    initialShotHashAppliedRef.current = false;
    pendingShotHashIndexRef.current = null;
  }, [cid]);

  useEffect(() => {
    if (shots.length === 0) return;
    if (!initialShotHashAppliedRef.current) {
      initialShotHashAppliedRef.current = true;
      const hashShotIndex = parseShotHash();
      if (hashShotIndex && hashShotIndex <= shots.length) {
        const shot = shots[hashShotIndex - 1];
        if (shot && currentShotIndex !== hashShotIndex) {
          pendingShotHashIndexRef.current = hashShotIndex;
          setCurrentShot(shot.id, hashShotIndex);
        }
        return;
      }
    }
    const currentIndex = currentShotId ? shots.findIndex((shot) => shot.id === currentShotId) : -1;
    if (currentIndex >= 0) {
      if (currentShotIndex !== currentIndex + 1) {
        setCurrentShot(shots[currentIndex].id, currentIndex + 1);
      }
      return;
    }
    setCurrentShot(shots[0].id, 1);
  }, [shots, currentShotId, currentShotIndex, setCurrentShot]);

  useEffect(() => {
    if (!currentShotIndex || shots.length === 0) return;
    const pendingShotHashIndex = pendingShotHashIndexRef.current;
    if (pendingShotHashIndex && currentShotIndex !== pendingShotHashIndex) return;
    if (pendingShotHashIndex === currentShotIndex) pendingShotHashIndexRef.current = null;
    updateShotHash(currentShotIndex);
  }, [currentShotIndex, shots.length]);

  useEffect(() => {
    const handleHashChange = () => {
      const hashShotIndex = parseShotHash();
      if (!hashShotIndex || hashShotIndex > shots.length) return;
      const shot = shots[hashShotIndex - 1];
      if (shot) {
        pendingShotHashIndexRef.current = hashShotIndex;
        setCurrentShot(shot.id, hashShotIndex);
      }
    };
    window.addEventListener('hashchange', handleHashChange);
    return () => window.removeEventListener('hashchange', handleHashChange);
  }, [shots, setCurrentShot]);

  const renderChapterSwitch = () => (
    <div className="flex items-center gap-2 flex-shrink-0">
      <button
        type="button"
        onClick={() => goToChapter(previousChapter?.id)}
        disabled={!previousChapter}
        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm border border-gray-300 rounded-lg text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap transition-colors"
        title={previousChapter ? previousChapter.title : '已经是第一回'}
      >
        <ChevronLeft className="h-4 w-4 flex-shrink-0" />
        上一回
      </button>
      <button
        type="button"
        onClick={() => goToChapter(nextChapter?.id)}
        disabled={!nextChapter}
        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm border border-gray-300 rounded-lg text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap transition-colors"
        title={nextChapter ? nextChapter.title : '已经是最后一回'}
      >
        下一回
        <ChevronRight className="h-4 w-4 flex-shrink-0" />
      </button>
    </div>
  );

  // 渲染左侧栏内容（根据当前 Tab 变化）
  const renderLeftPanel = () => {
    switch (currentTab) {
      case 0: // 分镜拆分
        return (
          <div className="flex flex-col h-full">
            <h3 className="text-sm font-semibold text-gray-700 mb-3 flex-shrink-0">{t('chapterDetail.rawContent')}</h3>
            <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin">
              {renderChapterContent()}
            </div>
          </div>
        );
      case 1: // 分镜图生成
        return (
          <ResourcePanel
            currentShot={currentShot}
            getCharacterImage={getCharacterImage}
            getSceneImage={getSceneImage}
            getPropImage={getPropImage}
            onImageClick={onImageClick}
          />
        );
      case 2: // 音频生成
        // 音频生成 Tab 有自己的三栏布局，左侧栏显示空
        return null;
      case 3: // 视频生成
        return (
          <ShotImageList
            shots={shots}
            novelId={id}
            chapterId={cid}
            currentShotIndex={currentShotIndex}
            shotImages={shotImages}
            onShotClick={(shotId, index) => {
              setCurrentShot(shotId, index);
            }}
            onImageClick={onImageClick}
            showVideoFields
            onDurationChange={(duration) => updateCurrentShot({ duration })}
            onVideoDescriptionChange={(video_description) => updateCurrentShot({ video_description })}
            onCopyVideoDescription={copyCurrentShotVideoDescription}
          />
        );
      default:
        return null;
    }
  };

  // 渲染中间内容（根据当前 Tab 变化）
  const renderCenterContent = () => {
    switch (currentTab) {
      case 0: // 分镜拆分
        return (
          <ShotSplitTab
            chapter={chapter}
            novelId={id}
            chapterId={cid}
          />
        );
      case 1: // 分镜图生成
        return (
          <ShotImageGenTab
            chapter={chapter}
            currentShot={currentShotIndex}
            shotImages={shotImages}
            generatingShots={generatingShots}
            novelId={id}
            chapterId={cid}
            shots={storeShots}
            onImageClick={onImageClick}
          >
            <ShotForm
              shotIndex={currentShotIndex}
              shotData={currentShot}
              showDialogues={false}
              showVideoDescription={false}
            />
          </ShotImageGenTab>
        );
      case 3: // 视频生成
        return (
          <VideoGenTab
            chapter={chapter}
            shotVideos={shotVideos}
            shotImages={shotImages}
            transitionVideos={transitionVideos}
            generatingVideos={generatingVideos}
            generatingTransitions={generatingTransitions}
            currentShot={currentShotIndex}
            novelId={id}
            chapterId={cid}
            shots={shots}
          />
        );
      default:
        return <div className="p-4 text-gray-500">请选择一个阶段</div>;
    }
  };

  // 渲染右侧栏内容
  const renderRightPanel = () => {
    if (currentTab === 0) {
      return (
        <div className="h-full overflow-y-auto rounded-lg border border-gray-200 bg-white p-4">
          {currentShot ? (
            <ShotForm
              shotIndex={currentShotIndex}
              shotData={currentShot}
              showVideoDescription={true}
              showDuration={true}
              onSave={saveShotSplitData}
            />
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-gray-500">
              {t('chapterGenerate.selectShotToEdit')}
            </div>
          )}
        </div>
      );
    }
    // 分镜图、音频和视频生成 Tab 不显示右侧系统状态栏。
    return null;
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4" />
          <p className="text-gray-600">加载中...</p>
        </div>
      </div>
    );
  }

  // 音频生成 Tab 使用自己的三栏布局
  if (currentTab === 2) {
    return (
      <div className="h-full min-h-0 overflow-hidden flex flex-col">
        {/* Header */}
        <div className="flex-shrink-0 px-4 py-2 border-b border-gray-200 bg-white">
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-4 min-w-0">
              <Link
                to={`/novels/${id}`}
                className="p-2 text-gray-400 hover:text-gray-600 transition-colors flex-shrink-0"
              >
                <ArrowLeft className="h-5 w-5" />
              </Link>
              <div className="min-w-0">
                <h1 className="text-xl font-bold text-gray-900 truncate">
                  {chapter?.title || t('chapterGenerate.unnamedChapter')}
                </h1>
                <p className="text-sm text-gray-500 mt-1 truncate">{chapterSummary}</p>
              </div>
            </div>
            <div className="flex items-center gap-3 flex-shrink-0">
              {renderChapterSwitch()}
              {/* 章节资源管理按钮 */}
              <button
                onClick={onResourcesManageClick}
                className="px-3 py-1.5 text-sm bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors flex items-center gap-2 whitespace-nowrap flex-shrink-0"
                title="管理本章节使用的角色、场景、道具"
              >
                <span>📦</span>
                章节资源
              </button>
            </div>
          </div>
        </div>

        {/* TabNavigation */}
        <div className="flex-shrink-0 px-4 py-2 bg-white border-b border-gray-200">
          <div className="relative">
            <TabNavigation />
            <div className="absolute right-0 top-1">
              {renderQueueStats()}
            </div>
          </div>
        </div>

        {/* AudioGenTab 完全接管 */}
        <div className="flex-1 min-h-0 overflow-hidden">
          <AudioGenTab
            novelId={id || ''}
            chapterId={cid || ''}
          />
        </div>

        {/* BottomNavigator */}
        <BottomNavigator
          shots={shots}
          shotImages={shotImages}
          generatingShots={generatingShots}
          pendingShots={pendingShots}
          shotVideos={shotVideos}
          generatingVideos={generatingVideos}
          pendingVideos={pendingVideos}
          collapsed={bottomNavCollapsed}
          onCollapsedChange={setBottomNavCollapsed}
        />

        {/* 为底部导航预留空间 */}
        <div className={bottomNavCollapsed ? 'h-10' : 'h-48'} />
      </div>
    );
  }

  return (
    <div className="h-full min-h-0 overflow-hidden flex flex-col">
      {/* Header */}
      <div className="flex-shrink-0 px-4 py-2 border-b border-gray-200 bg-white">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-4 min-w-0">
            <Link
              to={`/novels/${id}`}
              className="p-2 text-gray-400 hover:text-gray-600 transition-colors flex-shrink-0"
            >
              <ArrowLeft className="h-5 w-5" />
            </Link>
            <div className="min-w-0">
              <h1 className="text-xl font-bold text-gray-900 truncate">
                {chapter?.title || t('chapterGenerate.unnamedChapter')}
              </h1>
                <p className="text-sm text-gray-500 mt-1 truncate">{chapterSummary}</p>
            </div>
          </div>
          <div className="flex items-center gap-3 flex-shrink-0">
            {renderChapterSwitch()}
            {/* 章节资源管理按钮 */}
            <button
              onClick={onResourcesManageClick}
              className="px-3 py-1.5 text-sm bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors flex items-center gap-2 whitespace-nowrap flex-shrink-0"
              title="管理本章节使用的角色、场景、道具"
            >
              <span>📦</span>
              章节资源
            </button>
          </div>
        </div>
      </div>

      {/* TabNavigation */}
      <div className="relative z-[120] flex-shrink-0 px-4 py-2 bg-white border-b border-gray-200">
          <div className="relative">
            <TabNavigation />
            <div className="absolute left-1/2 top-1 z-[130] -translate-x-1/2">
            {renderDialogueWarningStats() || renderVideoGenerationStats()}
            </div>
            <div className="absolute right-0 top-1">
              {renderQueueStats()}
          </div>
        </div>
      </div>

      {/* 三栏布局 */}
      <div className="flex-1 min-h-0 pl-4 pr-0 py-2">
        <ThreeColumnLayout
          leftPanel={renderLeftPanel()}
          centerContent={renderCenterContent()}
          rightPanel={renderRightPanel()}
          minRightWidth={currentTab === 0 ? 740 : 320}
          maxRightWidth={currentTab === 0 ? 920 : 440}
        />
      </div>

      {/* BottomNavigator */}
      <BottomNavigator
        shots={shots}
        shotImages={shotImages}
        generatingShots={generatingShots}
        pendingShots={pendingShots}
        shotVideos={shotVideos}
        generatingVideos={generatingVideos}
        pendingVideos={pendingVideos}
        collapsed={bottomNavCollapsed}
        onCollapsedChange={setBottomNavCollapsed}
      />

      {/* 为底部导航预留空间 */}
      <div className={bottomNavCollapsed ? 'h-10' : 'h-48'} />
    </div>
  );
}

export default ChapterGenerateLayout;
