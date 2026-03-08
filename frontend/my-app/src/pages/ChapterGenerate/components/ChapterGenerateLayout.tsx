/**
 * ChapterGenerateLayout - 分镜生成页面主布局组件
 *
 * 整合：
 * - Header (返回按钮 + 章节标题)
 * - TabNavigation (四阶段 Tab)
 * - ThreeColumnLayout (三栏容器)
 * - BottomNavigator (底部导航)
 */

import { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import { useChapterGenerateStore } from '../stores';

// 布局组件
import { ThreeColumnLayout } from './ThreeColumnLayout';
import { TabNavigation } from './TabNavigation';
import { BottomNavigator } from './BottomNavigator';
import { ResourcePanel } from './ResourcePanel';
import { ShotForm } from './ShotForm';
import ComfyUIStatus from '../../../components/ComfyUIStatus';

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
  /** 分镜图片映射 */
  shotImages?: Record<number, string>;
  /** 分镜视频映射 */
  shotVideos?: Record<number, string>;
  /** 转场视频映射 */
  transitionVideos?: Record<string, string>;
  /** 角色列表 */
  characters?: any[];
  /** 场景列表 */
  scenes?: any[];
  /** 道具列表 */
  props?: any[];
  /** 生成中的分镜 */
  generatingShots?: Set<number>;
  /** 待生成的分镜 */
  pendingShots?: Set<number>;
  /** 生成中的视频 */
  generatingVideos?: Set<number>;
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
  shotImages = {},
  shotVideos = {},
  transitionVideos = {},
  characters = [],
  scenes = [],
  props = [],
  generatingShots = new Set(),
  pendingShots = new Set(),
  generatingVideos = new Set(),
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
  const store = useChapterGenerateStore();
  const [bottomNavCollapsed, setBottomNavCollapsed] = useState(false);

  // 优先从 store 获取最新数据，确保与 ShotSplitTab 等组件同步
  const parsedData = store.parsedData || propParsedData;
  const chapter = store.chapter || propChapter;
  const novel = store.novel || propNovel;

  const {
    currentTab,
    currentShotIndex,
    currentShotId,
    leftPanelCollapsed,
    rightPanelCollapsed,
    setCurrentTab,
    markTabComplete,
    setCurrentShot,
  } = store;

  // 获取分镜列表
  const shots = parsedData?.shots || [];
  const currentShot = shots[currentShotIndex - 1];

  // 渲染左侧栏内容（根据当前 Tab 变化）
  const renderLeftPanel = () => {
    switch (currentTab) {
      case 0: // 分镜拆分
        return (
          <div className="flex flex-col h-full">
            <h3 className="text-sm font-semibold text-gray-700 mb-3 flex-shrink-0">{t('chapterDetail.rawContent')}</h3>
            <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin">
              <div className="text-sm text-gray-600 whitespace-pre-wrap leading-relaxed">
                {chapter?.content || t('common.noContent')}
              </div>
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
            parsedData={parsedData}
            novelId={id}
            chapterId={cid}
          />
        );
      case 1: // 分镜图生成
        return (
          <ShotImageGenTab
            chapter={chapter}
            parsedData={parsedData}
            currentShot={currentShotIndex}
            shotImages={shotImages}
            generatingShots={generatingShots}
            novelId={id}
            chapterId={cid}
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
            parsedData={parsedData}
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
    // 音频生成 Tab 有自己的布局，不显示右侧栏
    if (currentTab === 2) return null;
    return <ComfyUIStatus />;
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
      <div className="h-full flex flex-col">
        {/* Header */}
        <div className="flex-shrink-0 px-4 py-2 border-b border-gray-200 bg-white">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <Link
                to={`/novels/${id}`}
                className="p-2 text-gray-400 hover:text-gray-600 transition-colors"
              >
                <ArrowLeft className="h-5 w-5" />
              </Link>
              <div>
                <h1 className="text-xl font-bold text-gray-900">
                  {chapter?.title || t('chapterGenerate.unnamedChapter')}
                </h1>
                <p className="text-sm text-gray-500 mt-1">
                  {t('chapterGenerate.shotCount', { count: shots.length })}
                </p>
              </div>
            </div>
            {/* 章节资源管理按钮 */}
            <button
              onClick={onResourcesManageClick}
              className="px-3 py-1.5 text-sm bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors flex items-center gap-2"
              title="管理本章节使用的角色、场景、道具"
            >
              <span>📦</span>
              章节资源
            </button>
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
        <div className={bottomNavCollapsed ? 'h-10' : 'h-40'} />
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="flex-shrink-0 px-4 py-2 border-b border-gray-200 bg-white">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link
              to={`/novels/${id}`}
              className="p-2 text-gray-400 hover:text-gray-600 transition-colors"
            >
              <ArrowLeft className="h-5 w-5" />
            </Link>
            <div>
              <h1 className="text-xl font-bold text-gray-900">
                {chapter?.title || t('chapterGenerate.unnamedChapter')}
              </h1>
              <p className="text-sm text-gray-500 mt-1">
                {t('chapterGenerate.shotCount', { count: shots.length })}
              </p>
            </div>
          </div>
          {/* 章节资源管理按钮 */}
          <button
            onClick={onResourcesManageClick}
            className="px-3 py-1.5 text-sm bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors flex items-center gap-2"
            title="管理本章节使用的角色、场景、道具"
          >
            <span>📦</span>
            章节资源
          </button>
        </div>
      </div>

      {/* TabNavigation */}
      <div className="flex-shrink-0 px-4 py-2 bg-white border-b border-gray-200">
        <TabNavigation />
      </div>

      {/* 三栏布局 */}
      <div className="flex-1 min-h-0 px-4 py-2">
        <ThreeColumnLayout
          leftPanel={renderLeftPanel()}
          centerContent={renderCenterContent()}
          rightPanel={renderRightPanel()}
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
      <div className={bottomNavCollapsed ? 'h-10' : 'h-40'} />
    </div>
  );
}

export default ChapterGenerateLayout;
