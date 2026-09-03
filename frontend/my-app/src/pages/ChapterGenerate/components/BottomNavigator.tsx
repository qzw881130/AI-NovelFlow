/**
 * BottomNavigator - 底部固定分镜导航条
 *
 * 支持：
 * - 横向滚动显示所有分镜缩略图
 * - 显示分镜状态（已完成/当前/待生成/失败）
 * - 点击切换分镜
 * - 批量选择模式
 * - 虚拟滚动（超过 20 个分镜时）
 */

import { useMemo, useRef, useEffect } from 'react';
import { ChevronUp, ChevronDown } from 'lucide-react';
import { useChapterGenerateStore } from '../stores';
import { useSidebar } from '../../../contexts/SidebarContext';
import { ShotThumbnail, ShotStatus as ShotThumbnailStatus } from './ShotThumbnail';
import type { Shot } from '../stores/slices/types';
import { useTranslation } from '../../../stores/i18nStore';

interface BottomNavigatorProps {
  /** 分镜列表数据 */
  shots?: Shot[];
  /** 分镜图片映射（key 为 shotId） */
  shotImages?: Record<string, string>;
  /** 生成中的分镜 ID 集合 */
  generatingShots?: Set<string>;
  /** 待生成的分镜 ID 集合 */
  pendingShots?: Set<string>;
  /** 分镜视频映射（key 为 shotId） */
  shotVideos?: Record<string, string>;
  /** 生成中的视频 ID 集合 */
  generatingVideos?: Set<string>;
  /** 待生成的视频 ID 集合 */
  pendingVideos?: Set<string>;
  /** 是否收起 */
  collapsed?: boolean;
  /** 收起状态变化回调 */
  onCollapsedChange?: (collapsed: boolean) => void;
}

export function BottomNavigator({
  shots: propShots,
  shotImages = {},
  generatingShots = new Set(),
  pendingShots = new Set(),
  shotVideos = {},
  generatingVideos = new Set(),
  pendingVideos = new Set(),
  collapsed = false,
  onCollapsedChange,
}: BottomNavigatorProps) {
  const { t } = useTranslation();
  const store = useChapterGenerateStore();
  const { sidebarWidth } = useSidebar();
  const scrollRef = useRef<HTMLDivElement>(null);

  // 从 store 获取分镜数据（统一使用 store.shots）
  const storeShots = useChapterGenerateStore((state) => state.shots);
  const shots = (propShots && propShots.length > 0) ? propShots : (storeShots || []);

  // 从 store 获取状态和方法
  const currentShotIndex = useChapterGenerateStore((state) => state.currentShotIndex);
  const currentShotId = useChapterGenerateStore((state) => state.currentShotId);
  const currentTab = useChapterGenerateStore((state) => state.currentTab);
  const selectedShotIds = useChapterGenerateStore((state) => state.selectedShotIds);
  const bulkMode = useChapterGenerateStore((state) => state.bulkMode);
  const setCurrentShot = useChapterGenerateStore((state) => state.setCurrentShot);
  const toggleShotSelection = useChapterGenerateStore((state) => state.toggleShotSelection);
  const setShowImagePreview = useChapterGenerateStore((state) => state.setShowImagePreview);
  const showImagePreview = useChapterGenerateStore((state) => state.showImagePreview);

  const goToShot = (index: number) => {
    if (index < 1 || index > shots.length) return;
    const shot = shots[index - 1];
    setCurrentShot(String(shot?.id || index), index);
  };

  const goToPreviousShot = () => goToShot(currentShotIndex - 1);
  const goToNextShot = () => goToShot(currentShotIndex + 1);

  const handleToggleCollapsed = () => {
    const newCollapsed = !collapsed;
    onCollapsedChange?.(newCollapsed);
  };

  // 获取分镜状态
  const getShotStatus = (shot: Shot, shotId: string, index: number): ShotThumbnailStatus => {
    const isCurrentShot = shotId === currentShotId || (!currentShotId && index === currentShotIndex);
    const hasImageResult = !!(shot.imageUrl || shotImages[shotId]);
    const hasVideoResult = !!(shot.videoUrl || shotVideos[shotId]);
    const imageIsGenerating = generatingShots.has(shotId) || shot.imageStatus === 'generating';
    const videoIsGenerating = generatingVideos.has(shotId) || shot.videoStatus === 'generating';

    if (currentTab === 1 && imageIsGenerating && !hasImageResult) return 'generating';
    if (currentTab === 3 && videoIsGenerating && !hasVideoResult) return 'generating';
    if (isCurrentShot) return 'current';
    if (currentTab === 1 && hasImageResult) return 'completed';
    if (currentTab === 3 && hasVideoResult) return 'completed';
    if (generatingShots.has(shotId) || generatingVideos.has(shotId) || shot.imageStatus === 'generating' || shot.videoStatus === 'generating') {
      return 'generating';
    }
    if (pendingShots.has(shotId) || pendingVideos.has(shotId)) {
      return 'queued';
    }
    if (currentTab === 3 && shot.videoStatus === 'failed' && !hasVideoResult) return 'failed';
    if (currentTab === 1 && shot.imageStatus === 'failed') return 'failed';
    if (currentTab === 3) {
      return (shot.videoUrl || shotVideos[shotId]) ? 'completed' : 'pending';
    }
    if (currentTab === 1) {
      return (shot.imageUrl || shotImages[shotId]) ? 'completed' : 'pending';
    }
    if (shotImages[shotId] || shotVideos[shotId]) {
      return 'completed';
    }
    return 'pending';
  };

  // 键盘导航
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (showImagePreview) {
        return;
      }
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
        return;
      }

      if (e.key === 'ArrowLeft') {
        e.preventDefault();
        goToPreviousShot();
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        goToNextShot();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [currentShotIndex, shots, showImagePreview]);

  // 滚动到当前分镜
  useEffect(() => {
    if (scrollRef.current && currentShotIndex > 0) {
      const thumbnailWidth = 140; // w-32 + gap
      const scrollPosition = (currentShotIndex - 1) * thumbnailWidth;
      scrollRef.current.scrollTo({
        left: scrollPosition,
        behavior: 'smooth',
      });
    }
  }, [currentShotIndex]);

  // 虚拟滚动优化（超过 20 个分镜时）
  const visibleShots = useMemo(() => {
    if (shots.length <= 20) return shots;
    // 简单实现：只显示前后各 10 个
    const start = Math.max(0, currentShotIndex - 11);
    const end = Math.min(shots.length, currentShotIndex + 10);
    return shots.slice(start, end);
  }, [shots, currentShotIndex]);

  // 处理点击缩略图
  const handleShotClick = (shotId: string, index: number) => {
    if (bulkMode) {
      toggleShotSelection(shotId);
    } else {
      setCurrentShot(shotId, index);
    }
  };

  // 处理双击（大图预览）
  const handleShotDoubleClick = (shot: Shot) => {
    const imageUrl = shot.imageUrl || shotImages[String(shot.id)];
    if (imageUrl) {
      setShowImagePreview(true, imageUrl, shot.index - 1);
    }
  };

  // 处理查看大图（眼睛图标点击）
  const handleViewLarge = (shot: Shot) => {
    const imageUrl = shot.imageUrl || shotImages[String(shot.id)];
    if (imageUrl) {
      setShowImagePreview(true, imageUrl, shot.index - 1);
    }
  };

  // 处理右键菜单
  const handleShotContextMenu = (shotId: string, index: number) => {
    // TODO: 显示上下文菜单
    console.log('Context menu for shot:', shotId, index);
  };

  if (shots.length === 0) {
    return (
      <div
        className="fixed bottom-0 right-0 h-32 bg-white border-t border-gray-200 flex items-center justify-center"
        style={{
          left: `${sidebarWidth}px`,
          width: `calc(100% - ${sidebarWidth}px)`
        }}
      >
        <p className="text-gray-500">{t('chapterGenerate.noShots')}</p>
      </div>
    );
  }

  return (
    <div
      className={`fixed bottom-0 right-0 bg-white border-t border-gray-200 shadow-lg transition-all duration-300 ease-in-out ${
        collapsed ? 'h-10' : 'h-48'
      }`}
      style={{
        left: `${sidebarWidth}px`,
        width: `calc(100% - ${sidebarWidth}px)`
      }}
    >
      {!collapsed && (
        <div className="flex flex-col h-full">
          {/* 收起/展开按钮 - 放在控制栏右侧 */}
          <div className="flex-shrink-0 flex items-center justify-between px-4 py-2 border-b border-gray-100">
            <div className="flex items-center gap-4">
              <span className="text-sm text-gray-600">
                {t('chapterGenerate.shotId', { id: currentShotIndex, total: shots.length })}
              </span>
              {bulkMode && (
                <span className="text-sm text-blue-600">
                  {t('chapterGenerate.selectedCount', { count: selectedShotIds.length })}
                </span>
              )}
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={goToPreviousShot}
                disabled={currentShotIndex <= 1}
                className="min-w-[104px] px-4 py-2 text-sm whitespace-nowrap border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {t('chapterGenerate.previousShot')}
              </button>
              <button
                onClick={goToNextShot}
                disabled={currentShotIndex >= shots.length}
                className="min-w-[104px] px-4 py-2 text-sm whitespace-nowrap border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {t('chapterGenerate.nextShot')}
              </button>

              {/* 收起按钮 */}
              <button
                onClick={handleToggleCollapsed}
                className="ml-2 w-7 h-7 bg-gray-100 border border-gray-300 rounded flex items-center justify-center hover:bg-gray-200 transition-colors"
                title={t('chapterGenerate.collapseNavbar')}
              >
                <ChevronDown className="w-4 h-4 text-gray-600" />
              </button>
            </div>
          </div>

          {/* 缩略图滚动区 - 为滚动条预留空间 */}
          <div className="flex-1 overflow-hidden py-3">
            <div
              ref={scrollRef}
              className="flex h-full items-center gap-2 overflow-x-auto overflow-y-hidden px-4 bottom-nav-scroll"
              style={{ scrollBehavior: 'smooth' }}
            >
              {shots.map((shot: Shot, index: number) => {
                const shotNum = index + 1;
                const shotIdStr = String(shot.id || shotNum);
                const thumbnailUrl = shot.imageUrl || shotImages[shotIdStr];
                const isCurrentShot = shot.id ? shot.id === currentShotId : shotNum === currentShotIndex;
                const isSelected = bulkMode ? selectedShotIds.includes(shotIdStr) : isCurrentShot;
                return (
                  <ShotThumbnail
                    key={shot.id || `shot-${index}`}
                    shotId={shotIdStr}
                    index={shotNum}
                    thumbnailUrl={thumbnailUrl}
                    status={getShotStatus(shot, shotIdStr, shotNum)}
                    isSelected={isSelected}
                    hasProps={Array.isArray(shot.props) && shot.props.length > 0}
                    duration={shot.duration}
                    onClick={() => handleShotClick(shotIdStr, shotNum)}
                    onDoubleClick={() => handleShotDoubleClick(shot)}
                    onContextMenu={() => handleShotContextMenu(shotIdStr, shotNum)}
                    onViewLarge={() => handleViewLarge(shot)}
                  />
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* 收起状态 */}
      {collapsed && (
        <div className="flex items-center justify-between h-full px-4">
          <span className="text-sm text-gray-500">{t('chapterGenerate.navbarCollapsed')}</span>
          <button
            onClick={handleToggleCollapsed}
            className="w-7 h-7 bg-gray-100 border border-gray-300 rounded flex items-center justify-center hover:bg-gray-200 transition-colors"
            title={t('chapterGenerate.expandNavbar')}
          >
            <ChevronUp className="w-4 h-4 text-gray-600" />
          </button>
        </div>
      )}
    </div>
  );
}

export default BottomNavigator;
