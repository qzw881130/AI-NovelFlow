/**
 * ShotImageGenTab - 分镜图生成 Tab（阶段 3）
 *
 * 功能：
 * - 左侧：资源面板
 * - 中间：分镜预览 + 描述编辑 + 生成控制
 * - 右侧：任务状态
 */

import { useRef, useState } from 'react';
import { useChapterGenerateStore } from '../stores';
import { Image, Loader2, Upload, Eye, X, Check, Square, Save, Users } from 'lucide-react';
import { shotsApi } from '../../../api/shots';
import { useTranslation } from '../../../stores/i18nStore';
import type { Shot } from '../../../api/shots';

interface ShotImageGenTabProps {
  chapter?: any;
  currentShot?: number;
  shotImages?: Record<string, string>;
  generatingShots?: Set<string>;
  novelId?: string;
  chapterId?: string;
  shots?: Shot[];
  children?: React.ReactNode;
  onImageClick?: (url: string) => void;
}

export function ShotImageGenTab({
  chapter,
  currentShot,
  shotImages: propShotImages = {},
  generatingShots: propGeneratingShots = new Set(),
  novelId,
  chapterId,
  shots = [],
  children,
  onImageClick,
}: ShotImageGenTabProps) {
  const { t } = useTranslation();

  // 使用选择器正确订阅 store 状态，确保状态更新时组件重新渲染
  const generateShotImage = useChapterGenerateStore((state) => state.generateShotImage);
  const generateAllImages = useChapterGenerateStore((state) => state.generateAllImages);
  const uploadShotImage = useChapterGenerateStore((state) => state.uploadShotImage);
  const setShowImagePreview = useChapterGenerateStore((state) => state.setShowImagePreview);
  const setShowMergedImageModal = useChapterGenerateStore((state) => state.setShowMergedImageModal);
  const setMergedImage = useChapterGenerateStore((state) => state.setMergedImage);
  const markTabComplete = useChapterGenerateStore((state) => state.markTabComplete);

  // 订阅 generatingShots 和 shotImages 状态
  const storeGeneratingShots = useChapterGenerateStore((state) => state.generatingShots);
  const storeShotImages = useChapterGenerateStore((state) => state.shotImages);

  // 直接使用 store 状态
  const shotImages = storeShotImages;
  const generatingShots = storeGeneratingShots;

  const fileInputRef = useRef<HTMLInputElement>(null);

  const [isGeneratingAll, setIsGeneratingAll] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [showBatchSelectModal, setShowBatchSelectModal] = useState(false);
  const [selectedShotIds, setSelectedShotIds] = useState<Set<string>>(new Set());
  const [isSaving, setIsSaving] = useState(false);

  // 统一使用 shots prop（来自 store.shots）
  const shotsList = shots;
  const currentShotIndex = currentShot ?? 1;
  const currentShotData = shotsList[currentShotIndex - 1];

  // 获取当前分镜对象
  const currentShotObj = shots.find(s => s.index === currentShotIndex);
  const currentShotId = currentShotObj?.id || shotsList[currentShotIndex - 1]?.id || '';

  const hasImage = !!(currentShotObj?.imageUrl || currentShotData?.imageUrl || shotImages[currentShotId]);
  // 完全依赖 store 的 generatingShots 状态
  const isGeneratingCurrent = generatingShots.has(currentShotId);

  // 处理单张分镜图生成
  const handleGenerateShot = async () => {
    if (!novelId || !chapterId || !currentShotId) return;
    try {
      await generateShotImage(novelId, chapterId, currentShotId);
    } catch (error) {
      console.error(t('chapterGenerate.generateFailed') + ':', error);
    }
  };

  // 打开批量选择弹窗
  const handleOpenBatchSelect = () => {
    // 初始化选择：默认选中所有待生成的分镜（没有图片的）
    const pendingShotIds = shots
      .filter((shot) => !shot.imageUrl && !shotImages[shot.id])
      .map((shot) => shot.id);
    setSelectedShotIds(new Set(pendingShotIds));
    setShowBatchSelectModal(true);
  };

  // 切换分镜选择状态
  const toggleShotSelection = (shotId: string) => {
    setSelectedShotIds(prev => {
      const newSet = new Set(prev);
      if (newSet.has(shotId)) {
        newSet.delete(shotId);
      } else {
        newSet.add(shotId);
      }
      return newSet;
    });
  };

  // 全选/取消全选
  const toggleSelectAll = () => {
    if (selectedShotIds.size === shots.length) {
      setSelectedShotIds(new Set());
    } else {
      setSelectedShotIds(new Set(shots.map(s => s.id)));
    }
  };

  // 处理批量分镜图生成
  const handleGenerateAll = async () => {
    if (!novelId || !chapterId) return;
    setIsGeneratingAll(true);
    try {
      // 依次生成选中的分镜
      for (const shotId of selectedShotIds) {
        await generateShotImage(novelId, chapterId, shotId);
      }
    } catch (error) {
      console.error(t('chapterGenerate.batchShotImageGenerateFailed') + ':', error);
    } finally {
      setIsGeneratingAll(false);
      setShowBatchSelectModal(false);
    }
  };

  // 处理本地图片上传
  const handleUploadImage = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !novelId || !chapterId || !currentShotId) return;

    // 验证文件类型
    const allowedTypes = ['image/png', 'image/jpeg', 'image/jpg', 'image/webp'];
    if (!allowedTypes.includes(file.type)) {
      alert(t('chapterGenerate.unsupportedImageType'));
      return;
    }

    setIsUploading(true);
    try {
      await uploadShotImage(novelId, chapterId, currentShotId, file);
    } catch (error) {
      console.error(t('chapterGenerate.uploadFailed') + ':', error);
      alert(t('chapterGenerate.uploadFailedRetry'));
    } finally {
      setIsUploading(false);
      // 重置文件输入，允许重复上传同一文件
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  // 触发文件选择
  const triggerFileSelect = () => {
    fileInputRef.current?.click();
  };

  // 保存当前分镜信息
  const handleSaveShot = async () => {
    if (!novelId || !chapterId) return;

    setIsSaving(true);
    try {
      const currentShotData = shotsList[currentShotIndex - 1];
      if (!currentShotData) {
        console.error(t('chapterGenerate.shotDataNotExist'));
        return;
      }

      // 调用批量更新接口
      const result = await shotsApi.batchUpdateShots(novelId, chapterId, [currentShotData]);

      if (result.success) {
        console.log(t('chapterGenerate.shotSaveSuccess'));
        // 可以添加 toast 提示
      } else {
        console.error(t('chapterGenerate.shotSaveFailed') + ':', result.message);
      }
    } catch (error) {
      console.error(t('chapterGenerate.shotSaveFailed') + ':', error);
    } finally {
      setIsSaving(false);
    }
  };

  // 查看合并角色图
  const handleViewMergedImage = () => {
    const currentShotData = shotsList[currentShotIndex - 1];
    if (currentShotData?.mergedCharacterImage) {
      setMergedImage(currentShotData.mergedCharacterImage);
      setShowMergedImageModal(true);
    }
  };

  return (
    <div className="h-full flex flex-col">
      {/* 操作栏 */}
      <div className="flex-shrink-0 flex items-center justify-between mb-4 pb-4 border-b border-gray-200">
        <div className="flex items-center gap-4">
          <button
            onClick={handleGenerateShot}
            disabled={isGeneratingCurrent || !chapterId}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
          >
            {isGeneratingCurrent ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                {t('chapterGenerate.generating')}
              </>
            ) : (
              <>
                <Image className="w-4 h-4" />
                {t('chapterGenerate.generateCurrentShot')}
              </>
            )}
          </button>
          <button
            onClick={handleOpenBatchSelect}
            disabled={isGeneratingAll || !chapterId}
            className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {t('chapterGenerate.batchGenerate')}
          </button>
          <button
            onClick={handleSaveShot}
            disabled={isSaving || !chapterId}
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
                {t('chapterGenerate.saveShots')}
              </>
            )}
          </button>
        </div>
        <div className="flex items-center gap-4">
          <button
            onClick={handleViewMergedImage}
            disabled={!shotsList[currentShotIndex - 1]?.mergedCharacterImage}
            className="px-4 py-2 bg-orange-600 text-white rounded-lg hover:bg-orange-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
            title={!shotsList[currentShotIndex - 1]?.mergedCharacterImage ? t('chapterGenerate.noMergedCharacterImage') : t('chapterGenerate.viewMergedImage')}
          >
            <Users className="w-4 h-4" />
            {t('chapterGenerate.viewMergedImage')}
          </button>
          <div className="text-sm text-gray-500">
            {t('chapterGenerate.shotId', { id: currentShot || 0, total: shotsList.length })}
          </div>
        </div>
      </div>

      {/* 内容区 */}
      <div className="flex-1 min-h-0 flex gap-4 overflow-hidden">
        {/* 表单编辑区 - 固定宽度 600px */}
        <div className="w-[600px] flex-shrink-0 overflow-y-auto border border-gray-200 rounded-lg p-4">
          {children}
        </div>

        {/* 分镜图预览区 - 自适应剩余宽度 */}
        <div className="flex-1 min-w-0 flex flex-col border border-gray-200 rounded-lg overflow-hidden">
          <div className="p-3 border-b border-gray-200 bg-gray-50 flex items-center justify-between">
            <h3 className="text-sm font-medium text-gray-700">{t('chapterGenerate.shotPreview')}</h3>
            {/* 上传按钮 */}
            <button
              onClick={triggerFileSelect}
              disabled={isUploading}
              className="px-3 py-1.5 text-xs bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-1"
              title={t('chapterGenerate.uploadImageFromLocal')}
            >
              {isUploading ? (
                <>
                  <Loader2 className="w-3 h-3 animate-spin" />
                  {t('common.uploading')}
                </>
              ) : (
                <>
                  <Upload className="w-3 h-3" />
                  {t('chapterGenerate.uploadImage')}
                </>
              )}
            </button>
            {/* 隐藏的文件输入框 */}
            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg,image/jpg,image/webp"
              onChange={handleUploadImage}
              className="hidden"
            />
          </div>

          <div className="flex-1 flex items-center justify-center bg-gray-100 p-4 relative">
            {hasImage ? (
              <>
                <img
                  src={currentShotObj?.imageUrl || currentShotData?.imageUrl || shotImages[currentShotId]}
                  alt={`${t('chapterGenerate.shot')}${currentShotIndex}`}
                  className="max-w-full max-h-full object-contain rounded-lg shadow-lg"
                />
                {/* 查看大图按钮 */}
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    const imageUrl = currentShotObj?.imageUrl || currentShotData?.imageUrl || shotImages[currentShotId];
                    if (onImageClick) {
                      onImageClick(imageUrl);
                    } else {
                      // 如果没有 onImageClick 回调，直接使用 store 方法
                      setShowImagePreview(true, imageUrl, currentShotIndex - 1);
                    }
                  }}
                  className="absolute top-6 right-6 p-2 bg-black/60 hover:bg-black/80 rounded-full text-white hover:text-blue-400 transition-all"
                  title={t('common.viewLargeImage')}
                >
                  <Eye className="h-5 w-5" />
                </button>
              </>
            ) : isGeneratingCurrent ? (
              <div className="text-center">
                <Loader2 className="w-12 h-12 text-blue-500 animate-spin mx-auto mb-4" />
                <p className="text-gray-600">{t('chapterGenerate.generatingShotImage')}</p>
              </div>
            ) : (
              <div className="text-center text-gray-500">
                <Image className="w-16 h-16 mx-auto mb-4 opacity-50" />
                <p>{t('chapterGenerate.clickToGenerateShotImage')}</p>
                <p className="text-xs mt-2">{t('chapterGenerate.orUploadHint')}</p>
              </div>
            )}
          </div>
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
            <div className="flex-1 overflow-y-auto p-4">
              <div className="flex items-center justify-between mb-3">
                <span className="text-sm text-gray-600">
                  {t('chapterGenerate.selectedShots', { selected: selectedShotIds.size, total: shots.length })}
                </span>
                <button
                  onClick={toggleSelectAll}
                  className="text-sm text-blue-600 hover:text-blue-800 flex items-center gap-1"
                >
                  {selectedShotIds.size === shots.length ? (
                    <>
                      <Square className="w-4 h-4" />
                      {t('common.deselectAll')}
                    </>
                  ) : (
                    <>
                      <Check className="w-4 h-4" />
                      {t('common.selectAll')}
                    </>
                  )}
                </button>
              </div>

              <div className="grid grid-cols-4 gap-3">
                {shots.map((shot: Shot) => {
                  const shotId = shot.id;
                  const shotIndex = shot.index;
                  const isSelected = selectedShotIds.has(shotId);
                  // 优先使用 shot.imageUrl
                  const shotImageUrl = shot.imageUrl || shotImages[shotId];
                  const hasShotImage = !!shotImageUrl;
                  const isGenerating = generatingShots.has(shotId);

                  return (
                    <div
                      key={shotId}
                      onClick={() => !isGenerating && toggleShotSelection(shotId)}
                      className={`
                        relative aspect-square rounded-lg border-2 transition-all
                        ${isGenerating
                          ? 'border-gray-200 bg-gray-50 cursor-not-allowed'
                          : 'cursor-pointer hover:shadow-md'
                        }
                        ${!isGenerating && isSelected
                          ? 'border-blue-500 bg-blue-50'
                          : !isGenerating && !isSelected
                            ? hasShotImage
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
                        {hasShotImage ? (
                          <img
                            src={shotImageUrl}
                            alt={`${t('chapterGenerate.shot')}${shotIndex}`}
                            className="w-full h-full object-cover rounded-lg"
                          />
                        ) : isGenerating ? (
                          <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
                        ) : (
                          <Image className="w-8 h-8 text-gray-300" />
                        )}
                      </div>

                      {/* 状态标签 */}
                      <div className="absolute bottom-0 left-0 right-0 px-1 py-0.5 text-xs text-center bg-black/60 text-white rounded-b-lg">
                        {hasShotImage ? t('chapterGenerate.generated') : isGenerating ? t('chapterGenerate.generating') : t('chapterGenerate.pending')}
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
                disabled={selectedShotIds.size === 0 || isGeneratingAll}
                className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
              >
                {isGeneratingAll ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    {t('chapterGenerate.generating')}
                  </>
                ) : (
                  <>
                    <Image className="w-4 h-4" />
                    {t('chapterGenerate.generateShots', { count: selectedShotIds.size })}
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default ShotImageGenTab;
