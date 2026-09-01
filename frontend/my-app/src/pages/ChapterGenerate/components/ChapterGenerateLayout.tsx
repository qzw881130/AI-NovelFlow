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
import type { Chapter } from '../../../types';

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
  const storeShots = useChapterGenerateStore((state) => state.shots);
  const storeGeneratingShots = useChapterGenerateStore((state) => state.generatingShots);
  const storePendingShots = useChapterGenerateStore((state) => state.pendingShots);
  const storeGeneratingVideos = useChapterGenerateStore((state) => state.generatingVideos);
  const storeShotImages = useChapterGenerateStore((state) => state.shotImages);
  const storeShotVideos = useChapterGenerateStore((state) => state.shotVideos);

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
  const chapterSummary = `${shots.length} 个导演 Shot · 预计成片 ${estimatedMinutes}:${estimatedSeconds} · 当前 Shot #${currentShotIndex || 1} · 当前时长 ${currentShotDuration}秒`;

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
            currentShotIndex={currentShotIndex}
            shotImages={shotImages}
            onShotClick={(shotId, index) => {
              setCurrentShot(shotId, index);
            }}
            onImageClick={onImageClick}
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
          <TabNavigation />
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
      <div className="flex-shrink-0 px-4 py-2 bg-white border-b border-gray-200">
        <TabNavigation />
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
        collapsed={bottomNavCollapsed}
        onCollapsedChange={setBottomNavCollapsed}
      />

      {/* 为底部导航预留空间 */}
      <div className={bottomNavCollapsed ? 'h-10' : 'h-48'} />
    </div>
  );
}

export default ChapterGenerateLayout;
