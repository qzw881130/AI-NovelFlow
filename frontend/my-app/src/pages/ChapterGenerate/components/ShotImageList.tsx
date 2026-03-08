/**
 * ShotImageList - 分镜图列表组件（用于视频生成 Tab 左侧栏）
 *
 * 显示：
 * - 当前选中分镜的缩略图
 * - 点击可切换选中上一个/下一个分镜
 */

import { Film, Eye, ChevronUp, ChevronDown } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';

interface ShotImageListProps {
  /** 分镜列表 */
  shots?: any[];
  /** 当前选中的分镜索引 */
  currentShotIndex?: number;
  /** 分镜图片映射 */
  shotImages?: Record<number, string>;
  /** 点击分镜回调 */
  onShotClick?: (shotId: string, index: number) => void;
  /** 图片点击查看大图回调 */
  onImageClick?: (url: string) => void;
}

export function ShotImageList({
  shots = [],
  currentShotIndex = 1,
  shotImages = {},
  onShotClick,
  onImageClick,
}: ShotImageListProps) {
  const { t } = useTranslation();

  // 获取当前分镜数据
  const currentShot = shots[currentShotIndex - 1];
  const currentShotId = currentShot?.id || String(currentShotIndex);
  const currentImageUrl = shotImages[currentShotIndex];

  // 切换上一个分镜
  const handlePrevious = () => {
    if (currentShotIndex > 1) {
      const prevShot = shots[currentShotIndex - 2];
      const prevShotId = prevShot?.id || String(currentShotIndex - 1);
      onShotClick?.(prevShotId, currentShotIndex - 1);
    }
  };

  // 切换下一个分镜
  const handleNext = () => {
    if (currentShotIndex < shots.length) {
      const nextShot = shots[currentShotIndex];
      const nextShotId = nextShot?.id || String(currentShotIndex + 1);
      onShotClick?.(nextShotId, currentShotIndex + 1);
    }
  };

  return (
    <div className="h-full flex flex-col">
      {/* 标题 */}
      <div className="flex-shrink-0 pb-3 border-b border-gray-200">
        <h3 className="text-sm font-semibold text-gray-700">{t('chapterGenerate.shotResources')}</h3>
      </div>

      {/* 当前分镜图 */}
      <div className="flex-1 flex flex-col items-center justify-center p-4">
        {shots.length === 0 ? (
          <div className="text-center text-gray-400 text-sm py-8">
            <Film className="w-12 h-12 mx-auto mb-2 opacity-50" />
            <p>{t('chapterGenerate.noShots')}</p>
          </div>
        ) : currentShot ? (
          <div className="w-full">
            {/* 分镜图 */}
            <div className="relative aspect-video rounded-lg bg-gray-100 overflow-hidden mb-4">
              {currentImageUrl ? (
                <>
                  <img
                    src={currentImageUrl}
                    alt={`${t('chapterGenerate.shot')}${currentShotIndex}`}
                    className="w-full h-full object-cover"
                  />
                  {/* 查看大图按钮 */}
                  <button
                    onClick={() => onImageClick?.(currentImageUrl)}
                    className="absolute top-2 right-2 p-2 bg-black/60 hover:bg-black/80 rounded-full text-white hover:text-blue-400 transition-all"
                    title={t('common.viewLargeImage')}
                  >
                    <Eye className="h-4 w-4" />
                  </button>
                </>
              ) : (
                <div className="w-full h-full flex items-center justify-center text-gray-400">
                  <Film className="w-12 h-12 opacity-50" />
                </div>
              )}
            </div>

            {/* 分镜描述 */}
            <p className="text-sm text-gray-700 mb-4 line-clamp-3">
              {currentShot.description || t('common.noContent')}
            </p>

            {/* 切换按钮 */}
            <div className="flex items-center justify-between gap-2">
              <button
                onClick={handlePrevious}
                disabled={currentShotIndex <= 1}
                className="flex-1 px-3 py-2 bg-gray-100 hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-sm text-gray-700 flex items-center justify-center gap-1 transition-colors"
              >
                <ChevronUp className="w-4 h-4" />
                {t('chapterGenerate.previousShot')}
              </button>
              <button
                onClick={handleNext}
                disabled={currentShotIndex >= shots.length}
                className="flex-1 px-3 py-2 bg-gray-100 hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-sm text-gray-700 flex items-center justify-center gap-1 transition-colors"
              >
                {t('chapterGenerate.nextShot')}
                <ChevronDown className="w-4 h-4" />
              </button>
            </div>
          </div>
        ) : (
          <div className="text-center text-gray-500 text-sm">
            <p>{t('chapterGenerate.noShotSelected')}</p>
          </div>
        )}
      </div>
    </div>
  );
}

export default ShotImageList;
