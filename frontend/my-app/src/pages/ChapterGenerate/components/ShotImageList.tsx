/**
 * ShotImageList - 分镜图列表组件（用于视频生成 Tab 左侧栏）
 *
 * 显示：
 * - 当前选中分镜的缩略图
 * - 点击可切换选中上一个/下一个分镜
 */

import { useState } from 'react';
import { Film, Eye, Copy, Image, Loader2 } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import { shotsApi } from '../../../api/shots';
import { ImageEditModal } from '../../../components/ImageEditModal';
import { toast } from '../../../stores/toastStore';
import { useChapterGenerateStore } from '../stores';

interface ShotImageListProps {
  /** 分镜列表 */
  shots?: any[];
  /** 当前选中的分镜索引 */
  currentShotIndex?: number;
  /** 分镜图片映射（key 为 shotId） */
  shotImages?: Record<string, string>;
  novelId?: string;
  chapterId?: string;
  /** 点击分镜回调 */
  onShotClick?: (shotId: string, index: number) => void;
  /** 图片点击查看大图回调 */
  onImageClick?: (url: string) => void;
  showVideoFields?: boolean;
  onDurationChange?: (duration: number) => void;
  onVideoDescriptionChange?: (description: string) => void;
  onCopyVideoDescription?: () => void;
}

export function ShotImageList({
  shots = [],
  currentShotIndex = 1,
  shotImages = {},
  novelId,
  chapterId,
  onShotClick,
  onImageClick,
  showVideoFields = false,
  onDurationChange,
  onVideoDescriptionChange,
  onCopyVideoDescription,
}: ShotImageListProps) {
  const { t } = useTranslation();
  const setShots = useChapterGenerateStore((state) => state.setShots);
  const setShotImages = useChapterGenerateStore((state) => state.setShotImages);
  const [isImageEditOpen, setIsImageEditOpen] = useState(false);
  const [imageEditResultUrl, setImageEditResultUrl] = useState<string | null>(null);
  const [imageEditResultSize, setImageEditResultSize] = useState<{ width: number; height: number } | null>(null);
  const [isEditingImage, setIsEditingImage] = useState(false);
  const [isReplacingImage, setIsReplacingImage] = useState(false);

  // 获取当前分镜数据
  const currentShot = shots[currentShotIndex - 1];
  const currentShotId = currentShot?.id || String(currentShotIndex);
  // 优先从 shot.imageUrl 获取，其次从 shotImages 映射获取
  const currentImageUrl = currentShot?.imageUrl || shotImages[currentShotId];

  const openImageEdit = () => {
    if (!currentImageUrl) return;
    setImageEditResultUrl(null);
    setImageEditResultSize(null);
    setIsImageEditOpen(true);
  };

  const closeImageEdit = () => {
    if (isEditingImage || isReplacingImage) return;
    setIsImageEditOpen(false);
    setImageEditResultUrl(null);
    setImageEditResultSize(null);
  };

  const handleEditImage = async (prompt: string) => {
    if (!novelId || !chapterId || !currentShotId) return;
    if (!prompt.trim()) {
      toast.warning('请输入分镜图片编辑提示词');
      return;
    }
    setIsEditingImage(true);
    setImageEditResultUrl(null);
    setImageEditResultSize(null);
    try {
      const result = await shotsApi.editImage(novelId, chapterId, currentShotId, prompt);
      if (result.success && result.data?.imageUrl) {
        setImageEditResultUrl(result.data.imageUrl);
        toast.success('分镜图片编辑完成');
      } else {
        toast.error(result.detail || result.message || '编辑分镜图片失败');
      }
    } catch (error) {
      console.error('编辑分镜图片失败:', error);
      toast.error('编辑分镜图片失败');
    } finally {
      setIsEditingImage(false);
    }
  };

  const handleReplaceImage = async () => {
    if (!novelId || !chapterId || !currentShotId || !imageEditResultUrl) return;
    setIsReplacingImage(true);
    try {
      const result = await shotsApi.replaceImage(novelId, chapterId, currentShotId, imageEditResultUrl);
      if (result.success && result.data) {
        setShots(shots.map((shot) => (shot.id === currentShotId ? { ...shot, ...result.data } : shot)));
        setShotImages((images) => ({ ...images, [currentShotId]: result.data!.imageUrl || imageEditResultUrl }));
        toast.success('已替换分镜图片');
        setIsImageEditOpen(false);
        setImageEditResultUrl(null);
        setImageEditResultSize(null);
      } else {
        toast.error(result.detail || result.message || '替换分镜图片失败');
      }
    } catch (error) {
      console.error('替换分镜图片失败:', error);
      toast.error('替换分镜图片失败');
    } finally {
      setIsReplacingImage(false);
    }
  };

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
      <div className={`flex-1 flex flex-col items-center px-2 py-3 overflow-y-auto ${showVideoFields ? 'justify-start' : 'justify-center'}`}>
        {shots.length === 0 ? (
          <div className="text-center text-gray-400 text-sm py-8">
            <Film className="w-12 h-12 mx-auto mb-2 opacity-50" />
            <p>{t('chapterGenerate.noShots')}</p>
          </div>
        ) : currentShot ? (
          <div className="w-full flex-1 rounded-xl border border-gray-200 bg-white p-2 shadow-sm space-y-3">
            {showVideoFields && (
              <div className="space-y-2">
                <div className="rounded-lg border border-gray-200 bg-white p-2">
                  <div className="flex items-center gap-2">
                    <label className="text-sm font-medium text-gray-700">时长</label>
                    <input
                      type="number"
                      value={currentShot?.duration || 5}
                      onChange={(event) => onDurationChange?.(Math.min(180, Math.max(1, parseInt(event.target.value) || 5)))}
                      min={1}
                      max={180}
                      className="w-20 px-2 py-1 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                    <span className="text-sm text-gray-500">秒</span>
                  </div>
                  <div className="mt-1 text-xs text-gray-400">建议 3-10 秒，最大 180 秒</div>
                </div>

                <div className="rounded-lg border border-gray-200 bg-white p-2">
                  <div className="flex items-center justify-between mb-2">
                    <h3 className="text-sm font-medium text-gray-700">视频描述</h3>
                    <button
                      type="button"
                      onClick={onCopyVideoDescription}
                      disabled={!currentShot?.video_description}
                      className="p-1.5 text-gray-400 hover:text-blue-600 transition-colors rounded hover:bg-blue-50 disabled:opacity-40 disabled:cursor-not-allowed"
                      title="复制"
                      aria-label="复制"
                    >
                      <Copy className="h-4 w-4" />
                    </button>
                  </div>
                  <textarea
                    value={currentShot?.video_description || ''}
                    onChange={(event) => onVideoDescriptionChange?.(event.target.value)}
                    placeholder="请输入视频生成用描述"
                    className="w-full h-32 px-2 py-2 border border-gray-300 rounded-lg resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
                  />
                </div>
              </div>
            )}

            {/* 分镜图 */}
            <div className="relative aspect-video rounded-lg bg-gray-100 overflow-hidden">
              {currentImageUrl ? (
                <>
                  <img
                    src={currentImageUrl}
                    alt={`${t('chapterGenerate.shot')}${currentShotIndex}`}
                    className="w-full h-full object-cover"
                  />
                  <div className="absolute top-2 right-2 flex items-center gap-2">
                    <button
                      onClick={() => onImageClick?.(currentImageUrl)}
                      className="p-2 bg-black/60 hover:bg-black/80 rounded-full text-white hover:text-blue-400 transition-all"
                      title={t('common.viewLargeImage')}
                    >
                      <Eye className="h-4 w-4" />
                    </button>
                    {novelId && chapterId && (
                      <button
                        type="button"
                        onClick={openImageEdit}
                        className="p-2 bg-black/60 hover:bg-black/80 rounded-full text-white hover:text-blue-400 transition-all"
                        title="编辑图片"
                      >
                        <Image className="h-4 w-4" />
                      </button>
                    )}
                  </div>
                </>
              ) : (
                <div className="w-full h-full flex items-center justify-center text-gray-400">
                  <Film className="w-12 h-12 opacity-50" />
                </div>
              )}
            </div>

            {/* 分镜描述 */}
            <p className="text-sm text-gray-700 line-clamp-3">
              {currentShot.description || t('common.noContent')}
            </p>

            {/* 切换按钮 */}
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <button
                onClick={handlePrevious}
                disabled={currentShotIndex <= 1}
                className="w-full sm:flex-1 min-h-10 px-3 py-2 bg-gray-100 hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-sm text-gray-700 flex items-center justify-center gap-1 whitespace-nowrap transition-colors"
              >
                上一个
              </button>
              <button
                onClick={handleNext}
                disabled={currentShotIndex >= shots.length}
                className="w-full sm:flex-1 min-h-10 px-3 py-2 bg-gray-100 hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-sm text-gray-700 flex items-center justify-center gap-1 whitespace-nowrap transition-colors"
              >
                下一个
              </button>
            </div>
          </div>
        ) : (
          <div className="text-center text-gray-500 text-sm">
            <p>{t('chapterGenerate.noShotSelected')}</p>
          </div>
        )}
      </div>
      {currentImageUrl && (
        <ImageEditModal
          isOpen={isImageEditOpen}
          itemName={`镜${currentShotIndex}`}
          imageUrl={currentImageUrl}
          resultUrl={imageEditResultUrl}
          isEditing={isEditingImage}
          isReplacing={isReplacingImage}
          resultSize={imageEditResultSize}
          onResultSizeChange={setImageEditResultSize}
          labels={{
            title: '编辑分镜图片',
            optionsTitle: '编辑选项',
            keepOriginalLayout: '保持原图构图与布局',
            removeWeapons: '移除不需要的物体或干扰元素',
            makeFourView: '增强主体一致性与画面细节',
            other: '其它',
            otherPlaceholder: '输入额外编辑要求，例如：修正红框区域，保持人物和构图不变。',
            editButton: '编辑图片',
            editing: '编辑中...',
            replaceButton: '替换分镜图片',
            originalImage: '原图',
            editResult: '编辑结果',
            emptyResult: '生成后在这里预览',
          }}
          onClose={closeImageEdit}
          onEdit={handleEditImage}
          onReplace={handleReplaceImage}
        />
      )}
    </div>
  );
}

export default ShotImageList;
