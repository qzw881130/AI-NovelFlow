/**
 * ShotImageGenTab - 分镜图生成 Tab（阶段 3）
 *
 * 功能：
 * - 左侧：资源面板
 * - 中间：分镜预览 + 描述编辑 + 生成控制
 * - 右侧：任务状态
 */

import { cloneElement, isValidElement, useEffect, useRef, useState } from 'react';
import { useChapterGenerateStore } from '../stores';
import { Box, ChevronDown, Download, Image, Loader2, Upload, Eye, X, Check, Square, Save, Users } from 'lucide-react';
import { shotsApi } from '../../../api/shots';
import { taskApi } from '../../../api/tasks';
import { useTranslation } from '../../../stores/i18nStore';
import type { Shot } from '../../../api/shots';
import { ImageEditModal } from '../../../components/ImageEditModal';
import { toast } from '../../../stores/toastStore';

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
  const checkShotTaskStatus = useChapterGenerateStore((state) => state.checkShotTaskStatus);
  const uploadShotImage = useChapterGenerateStore((state) => state.uploadShotImage);
  const setShots = useChapterGenerateStore((state) => state.setShots);
  const setShotImages = useChapterGenerateStore((state) => state.setShotImages);
  const setShowImagePreview = useChapterGenerateStore((state) => state.setShowImagePreview);
  const setShowMergedImageModal = useChapterGenerateStore((state) => state.setShowMergedImageModal);
  const setMergedImage = useChapterGenerateStore((state) => state.setMergedImage);
  const markTabComplete = useChapterGenerateStore((state) => state.markTabComplete);

  // 订阅 generatingShots 和 shotImages 状态
  const storeGeneratingShots = useChapterGenerateStore((state) => state.generatingShots);
  const storePendingShots = useChapterGenerateStore((state) => state.pendingShots);
  const storeShotImages = useChapterGenerateStore((state) => state.shotImages);

  // 直接使用 store 状态
  const shotImages = storeShotImages;
  const generatingShots = storeGeneratingShots;
  const pendingShots = storePendingShots;

  const fileInputRef = useRef<HTMLInputElement>(null);
  const batchCancelRequestedRef = useRef(false);
  const batchShotIdsRef = useRef<string[]>([]);

  const [isGeneratingAll, setIsGeneratingAll] = useState(false);
  const [isCancellingAll, setIsCancellingAll] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [showBatchSelectModal, setShowBatchSelectModal] = useState(false);
  const [showGenerateMenu, setShowGenerateMenu] = useState(false);
  const [selectedShotIds, setSelectedShotIds] = useState<Set<string>>(new Set());
  const [skipBatchLlmWhenPromptExists, setSkipBatchLlmWhenPromptExists] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isDownloadingShotImageData, setIsDownloadingShotImageData] = useState(false);
  const [isDownloadingCurrentShotImageData, setIsDownloadingCurrentShotImageData] = useState(false);
  const [shotImagePrompts, setShotImagePrompts] = useState<Record<string, string>>({});
  const [submittingShotIds, setSubmittingShotIds] = useState<Set<string>>(new Set());
  const [submittingShotLabels, setSubmittingShotLabels] = useState<Record<string, string>>({});
  const [dragSelectionMode, setDragSelectionMode] = useState<'select' | 'deselect' | null>(null);
  const [isImageEditOpen, setIsImageEditOpen] = useState(false);
  const [imageEditResultUrl, setImageEditResultUrl] = useState<string | null>(null);
  const [imageEditResultSize, setImageEditResultSize] = useState<{ width: number; height: number } | null>(null);
  const [previewImageSize, setPreviewImageSize] = useState<{ width: number; height: number } | null>(null);
  const [isEditingImage, setIsEditingImage] = useState(false);
  const [isReplacingImage, setIsReplacingImage] = useState(false);

  // 统一使用 shots prop（来自 store.shots）
  const shotsList = shots;
  const currentShotIndex = currentShot ?? 1;
  const currentShotData = shotsList[currentShotIndex - 1];

  // 获取当前分镜对象
  const currentShotObj = shots.find(s => s.index === currentShotIndex);
  const currentShotId = currentShotObj?.id || shotsList[currentShotIndex - 1]?.id || '';
  const currentImageUrl = currentShotObj?.imageUrl || currentShotData?.imageUrl || shotImages[currentShotId];

  const hasImage = !!currentImageUrl;
  const hasCompletedCurrentImage = hasImage && currentShotObj?.imageStatus === 'completed';
  // 完全依赖 store 的 generatingShots 状态
  const isGeneratingCurrent = submittingShotIds.has(currentShotId) || (generatingShots.has(currentShotId) && !hasCompletedCurrentImage);
  const isSubmittingCurrent = submittingShotIds.has(currentShotId);
  const currentGenerationText = isSubmittingCurrent
    ? submittingShotLabels[currentShotId] || '处理中...'
    : generatingShots.has(currentShotId)
      ? '分镜图生成中...'
      : '';
  const currentPromptText = shotImagePrompts[currentShotId] ?? currentShotObj?.shotImagePrompt ?? currentShotData?.shotImagePrompt ?? '';
  const hasCurrentPromptText = currentPromptText.trim().length > 0;
  const isShotQueuedOrGenerating = (shotId: string) => generatingShots.has(shotId) || pendingShots.has(shotId);
  const selectableShotIds = shots
    .filter((shot) => !isShotQueuedOrGenerating(shot.id))
    .map((shot) => shot.id);
  const selectedRunnableShotIds = Array.from(selectedShotIds).filter((shotId) => !isShotQueuedOrGenerating(shotId));

  // 处理单张分镜图生成
  const handleGenerateShot = async (mode: 'llm' | 'image_only' = 'llm') => {
    if (!novelId || !chapterId || !currentShotId) return;
    if (isGeneratingCurrent) return;
    if (mode === 'image_only' && !hasCurrentPromptText) return;
    setShowGenerateMenu(false);
    setSubmittingShotIds(prev => new Set([...prev, currentShotId]));
    setSubmittingShotLabels(prev => ({
      ...prev,
      [currentShotId]: mode === 'image_only' ? '正在提交工作流...' : '正在生成提示词...',
    }));
    try {
      const promptText = await generateShotImage(
        novelId,
        chapterId,
        currentShotId,
        mode === 'image_only' ? currentPromptText.trim() : undefined,
        { useExistingPrompt: mode === 'image_only' }
      );
      if (promptText) {
        setShotImagePrompts(prev => ({ ...prev, [currentShotId]: promptText }));
      }
      await checkShotTaskStatus(chapterId);
    } catch (error) {
      console.error(t('chapterGenerate.generateFailed') + ':', error);
    } finally {
      setSubmittingShotIds(prev => {
        const next = new Set(prev);
        next.delete(currentShotId);
        return next;
      });
      setSubmittingShotLabels(prev => {
        const next = { ...prev };
        delete next[currentShotId];
        return next;
      });
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

  const applyShotSelection = (shotId: string, mode: 'select' | 'deselect') => {
    setSelectedShotIds(prev => {
      const next = new Set(prev);
      if (mode === 'select') {
        next.add(shotId);
      } else {
        next.delete(shotId);
      }
      return next;
    });
  };

  const handleShotSelectMouseDown = (event: React.MouseEvent, shotId: string, isGenerating: boolean) => {
    if (event.button !== 0 || isGenerating) return;
    event.preventDefault();
    const mode = selectedShotIds.has(shotId) ? 'deselect' : 'select';
    setDragSelectionMode(mode);
    applyShotSelection(shotId, mode);
  };

  const handleShotSelectMouseEnter = (shotId: string, isGenerating: boolean) => {
    if (!dragSelectionMode || isGenerating) return;
    applyShotSelection(shotId, dragSelectionMode);
  };

  const waitForShotImageCompletion = async (shotId: string) => {
    for (let attempt = 0; attempt < 360; attempt += 1) {
      if (batchCancelRequestedRef.current) return;
      await checkShotTaskStatus(chapterId!);
      const shot = useChapterGenerateStore.getState().shots.find(item => item.id === shotId);
      if (shot?.imageStatus === 'completed') return;
      if (shot?.imageStatus === 'failed') return;
      await new Promise(resolve => window.setTimeout(resolve, 2000));
    }
    toast.error('等待分镜图生成完成超时');
  };

  const cancelUnfinishedShotImageTasks = async (shotIds?: Set<string>) => {
    if (!chapterId) return [];
    const response = await fetch(`/api/tasks/?type=shot_image&chapter_id=${chapterId}`);
    const result = await response.json();
    const activeTasks = (result.success && Array.isArray(result.data) ? result.data : [])
      .filter((task: any) => ['pending', 'queued', 'running'].includes(String(task.status || '').toLowerCase()))
      .filter((task: any) => !shotIds || shotIds.has(String(task.shotId || '')));
    await Promise.allSettled(activeTasks.map((task: any) => taskApi.cancel(task.id)));
    return activeTasks;
  };

  useEffect(() => {
    if (!dragSelectionMode) return;
    const handleMouseUp = () => setDragSelectionMode(null);
    window.addEventListener('mouseup', handleMouseUp);
    return () => window.removeEventListener('mouseup', handleMouseUp);
  }, [dragSelectionMode]);

  useEffect(() => {
    if (!showGenerateMenu) return;
    const handleClick = () => setShowGenerateMenu(false);
    window.addEventListener('click', handleClick);
    return () => window.removeEventListener('click', handleClick);
  }, [showGenerateMenu]);

  useEffect(() => {
    setPreviewImageSize(null);
  }, [currentImageUrl]);

  // 全选/取消全选
  const toggleSelectAll = () => {
    if (selectedRunnableShotIds.length === selectableShotIds.length && selectableShotIds.length > 0) {
      setSelectedShotIds(new Set());
    } else {
      setSelectedShotIds(new Set(selectableShotIds));
    }
  };

  const selectPendingOnly = () => {
    const pendingOnlyIds = shots
      .filter((shot) => {
        const shotImageUrl = shot.imageUrl || shotImages[shot.id];
        return !shotImageUrl && !generatingShots.has(shot.id) && !pendingShots.has(shot.id);
      })
      .map((shot) => shot.id);
    setSelectedShotIds(new Set(pendingOnlyIds));
  };

  // 处理批量分镜图生成
  const handleGenerateAll = async () => {
    if (!novelId || !chapterId) return;
    const selectedIds = Array.from(selectedShotIds).filter((shotId) => !isShotQueuedOrGenerating(shotId));
    if (selectedIds.length === 0) return;

    setIsGeneratingAll(true);
    batchCancelRequestedRef.current = false;
    batchShotIdsRef.current = selectedIds;
    setShowBatchSelectModal(false);
    useChapterGenerateStore.setState(state => ({
      pendingShots: new Set([...state.pendingShots, ...selectedIds]),
      shots: state.shots.map(shot => (
        selectedIds.includes(shot.id)
          ? { ...shot, imageStatus: 'pending' as const, imageTaskId: null }
          : shot
      )),
    }));

    try {
      const result = await shotsApi.generateImagesBatch(novelId, chapterId, {
        shot_ids: selectedIds,
        skip_llm_when_prompt_exists: skipBatchLlmWhenPromptExists,
      });
      if (!result.success) {
        throw new Error(result.detail || result.message || '批量生成分镜图失败');
      }
      await checkShotTaskStatus(chapterId);
      toast.success(result.message || '批量分镜图任务已创建，关闭页面后会继续执行');
    } catch (error) {
      console.error(t('chapterGenerate.batchShotImageGenerateFailed') + ':', error);
      useChapterGenerateStore.setState(state => {
        const selectedSet = new Set(selectedIds);
        const nextPendingShots = new Set(state.pendingShots);
        selectedIds.forEach(shotId => nextPendingShots.delete(shotId));
        return {
          pendingShots: nextPendingShots,
          shots: state.shots.map(shot => {
            if (!selectedSet.has(shot.id)) return shot;
            return { ...shot, imageStatus: shot.imageUrl ? 'completed' as const : 'pending' as const };
          }),
        };
      });
      toast.error(error instanceof Error ? error.message : '批量生成分镜图失败');
    } finally {
      setIsGeneratingAll(false);
      batchShotIdsRef.current = [];
    }
  };

  const handleCancelGenerateAll = async () => {
    if (!chapterId || (!isGeneratingAll && generatingShots.size === 0 && pendingShots.size === 0)) return;
    if (!window.confirm('确认取消所有未完成的分镜图生成任务吗？')) return;

    batchCancelRequestedRef.current = true;
    setIsCancellingAll(true);
    try {
      const activeTasks = await cancelUnfinishedShotImageTasks();

      const batchShotIds = new Set(batchShotIdsRef.current);
      const activeShotIds = new Set<string>(activeTasks.map((task: any) => String(task.shotId || '')).filter(Boolean));
      useChapterGenerateStore.setState(state => {
        const nextGeneratingShots = new Set(state.generatingShots);
        const nextPendingShots = new Set(state.pendingShots);
        [...batchShotIds, ...activeShotIds].forEach(shotId => nextGeneratingShots.delete(shotId));
        [...batchShotIds, ...activeShotIds].forEach(shotId => nextPendingShots.delete(shotId));
        return {
          generatingShots: nextGeneratingShots,
          pendingShots: nextPendingShots,
          shots: state.shots.map(shot => {
            if (!batchShotIds.has(shot.id) && !activeShotIds.has(shot.id)) return shot;
            if (shot.imageUrl) return { ...shot, imageStatus: 'completed' as const, imageTaskId: null };
            return { ...shot, imageStatus: activeShotIds.has(shot.id) ? 'failed' as const : 'pending' as const, imageTaskId: null };
          }),
        };
      });
      await checkShotTaskStatus(chapterId);
      toast.success('已取消未完成的分镜图生成任务');
    } catch (error) {
      console.error('取消批量分镜图生成失败:', error);
      toast.error(error instanceof Error ? error.message : '取消批量分镜图生成失败');
    } finally {
      setIsGeneratingAll(false);
      setIsCancellingAll(false);
      batchShotIdsRef.current = [];
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
      const result = await shotsApi.batchUpdateShots(novelId, chapterId, [{
        ...currentShotData,
        shot_image_prompt: currentPromptText,
      }]);

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
      setMergedImage(currentShotData.mergedCharacterImage, t('chapterGenerate.mergedCharacterImage'));
      setShowMergedImageModal(true);
    }
  };

  // 查看合并道具图
  const handleViewMergedPropImage = () => {
    const currentShotData = shotsList[currentShotIndex - 1];
    if (currentShotData?.mergedPropImage) {
      setMergedImage(currentShotData.mergedPropImage, t('chapterGenerate.mergedPropImage'));
      setShowMergedImageModal(true);
    }
  };

  const handlePreviewShotImage = () => {
    if (!currentImageUrl) return;
    if (onImageClick) {
      onImageClick(currentImageUrl);
    } else {
      setShowImagePreview(true, currentImageUrl, currentShotIndex - 1);
    }
  };

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
        setShots(shotsList.map((shot) => (shot.id === currentShotId ? { ...shot, ...result.data } : shot)));
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

  const handleDownloadShotImageData = async () => {
    if (!novelId || !chapterId) {
      toast.error('缺少章节信息，无法打包分镜图数据');
      return;
    }
    setIsDownloadingShotImageData(true);
    try {
      await shotsApi.downloadShotImageDataPackage(novelId, chapterId);
      toast.success('分镜图数据已打包下载');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '打包分镜图数据失败');
    } finally {
      setIsDownloadingShotImageData(false);
    }
  };

  const handleDownloadCurrentShotImageData = async () => {
    if (!novelId || !chapterId || !currentShotId) {
      toast.error('缺少当前分镜信息，无法打包当前分镜图数据');
      return;
    }
    setIsDownloadingCurrentShotImageData(true);
    try {
      await shotsApi.downloadCurrentShotImageDataPackage(novelId, chapterId, currentShotId);
      toast.success('当前分镜图数据已打包下载');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '打包当前分镜图数据失败');
    } finally {
      setIsDownloadingCurrentShotImageData(false);
    }
  };

  const childrenWithSaveShortcut = isValidElement(children)
    ? cloneElement(children, { onSave: handleSaveShot } as { onSave: () => Promise<void> })
    : children;

  return (
    <div className="h-full flex flex-col">
      {/* 操作栏 */}
      <div className="flex-shrink-0 flex items-center justify-between mb-4 pb-4 border-b border-gray-200">
        <div className="flex items-center gap-4">
          <div className="relative inline-flex">
            <button
              onClick={() => handleGenerateShot('llm')}
              disabled={isGeneratingCurrent || !chapterId || !currentShotId}
              className="px-4 py-2 bg-blue-600 text-white rounded-l-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
            >
              {isGeneratingCurrent ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  {isSubmittingCurrent ? '处理中' : t('chapterGenerate.generating')}
                </>
              ) : (
                <>
                  <Image className="w-4 h-4" />
                  LLM+生成分镜
                </>
              )}
            </button>
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                setShowGenerateMenu(prev => !prev);
              }}
              disabled={isGeneratingCurrent || !chapterId || !currentShotId}
              className="px-2 py-2 bg-blue-600 text-white border-l border-blue-500 rounded-r-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center"
              aria-label="选择分镜生成方式"
            >
              <ChevronDown className="w-4 h-4" />
            </button>
            {showGenerateMenu && (
              <div className="absolute left-0 top-full z-20 mt-1 w-44 rounded-lg border border-gray-200 bg-white py-1 shadow-lg">
                <button
                  type="button"
                  onClick={() => handleGenerateShot('llm')}
                  className="w-full px-3 py-2 text-left text-sm text-gray-700 hover:bg-blue-50"
                >
                  LLM+生成分镜
                </button>
                <button
                  type="button"
                  onClick={() => handleGenerateShot('image_only')}
                  disabled={!hasCurrentPromptText}
                  className="w-full px-3 py-2 text-left text-sm text-gray-700 hover:bg-blue-50 disabled:text-gray-400 disabled:hover:bg-white disabled:cursor-not-allowed"
                  title={!hasCurrentPromptText ? '当前分镜没有主分镜图 AI 提示词' : undefined}
                >
                  只生成分镜
                </button>
              </div>
            )}
          </div>
          <button
            onClick={handleOpenBatchSelect}
            disabled={isGeneratingAll || !chapterId}
            className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {t('chapterGenerate.batchGenerate')}
          </button>
          {(isGeneratingAll || generatingShots.size > 0 || pendingShots.size > 0) && (
            <button
              onClick={handleCancelGenerateAll}
              disabled={isCancellingAll}
              className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
            >
              {isCancellingAll ? <Loader2 className="w-4 h-4 animate-spin" /> : <X className="w-4 h-4" />}
              取消批量
            </button>
          )}
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
            onClick={handleDownloadCurrentShotImageData}
            disabled={isDownloadingCurrentShotImageData || !chapterId || !currentShotId}
            className="px-4 py-2 bg-cyan-600 text-white rounded-lg hover:bg-cyan-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
          >
            {isDownloadingCurrentShotImageData ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Download className="w-4 h-4" />
            )}
            打包当前分镜图数据
          </button>
          <button
            onClick={handleDownloadShotImageData}
            disabled={isDownloadingShotImageData || !chapterId}
            className="px-4 py-2 bg-sky-600 text-white rounded-lg hover:bg-sky-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
          >
            {isDownloadingShotImageData ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Download className="w-4 h-4" />
            )}
            打包分镜图数据
          </button>
          <button
            onClick={handleViewMergedImage}
            disabled={!shotsList[currentShotIndex - 1]?.mergedCharacterImage}
            className="px-4 py-2 bg-orange-600 text-white rounded-lg hover:bg-orange-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
            title={!shotsList[currentShotIndex - 1]?.mergedCharacterImage ? t('chapterGenerate.noMergedCharacterImage') : t('chapterGenerate.viewMergedImage')}
          >
            <Users className="w-4 h-4" />
            {t('chapterGenerate.viewMergedImage')}
          </button>
          <button
            onClick={handleViewMergedPropImage}
            disabled={!shotsList[currentShotIndex - 1]?.mergedPropImage}
            className="px-4 py-2 bg-amber-600 text-white rounded-lg hover:bg-amber-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
            title={!shotsList[currentShotIndex - 1]?.mergedPropImage ? t('chapterGenerate.noMergedPropImage') : t('chapterGenerate.viewMergedPropImage')}
          >
            <Box className="w-4 h-4" />
            {t('chapterGenerate.viewMergedPropImage')}
          </button>
          <div className="text-sm text-gray-500">
            {t('chapterGenerate.shotId', { id: currentShot || 0, total: shotsList.length })}
          </div>
        </div>
      </div>

      {/* 内容区 */}
      <div className="flex-1 min-h-0 flex gap-4 overflow-hidden">
        {/* 表单编辑区 - 固定宽度 600px */}
        <div className="shot-image-form-panel w-[600px] flex-shrink-0 overflow-y-auto border border-gray-200 rounded-lg p-4">
          {childrenWithSaveShortcut}
        </div>

        {/* 分镜图预览区 - 自适应剩余宽度 */}
        <div className="flex-1 min-h-0 min-w-0 flex flex-col border border-gray-200 rounded-lg overflow-hidden">
          <div className="p-3 border-b border-gray-200 bg-white">
            <div className="flex items-center justify-between mb-2">
              <label className="text-sm font-medium text-gray-700">主分镜图 AI 提示词</label>
              <span className="text-xs text-gray-500">点击生成当前分镜后自动填入，可编辑后再次生成</span>
            </div>
            <textarea
              value={currentPromptText}
              onChange={(e) => setShotImagePrompts(prev => ({ ...prev, [currentShotId]: e.target.value }))}
              onKeyDown={(event) => {
                if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
                  event.preventDefault();
                  event.stopPropagation();
                  handleSaveShot();
                }
              }}
              disabled={!currentShotId || isGeneratingCurrent}
              rows={4}
              className="input-field text-sm leading-relaxed"
              placeholder="点击“生成当前分镜”后，这里会显示由主分镜图提示词模板生成的最终生图提示词。"
            />
          </div>
          <div className="p-3 border-b border-gray-200 bg-gray-50 flex items-center justify-between">
            <h3 className="text-sm font-medium text-gray-700">{t('chapterGenerate.shotPreview')}</h3>
            <div className="flex items-center gap-2">
              <button
                onClick={openImageEdit}
                disabled={!hasImage || isGeneratingCurrent || isUploading}
                className="px-3 py-1.5 text-xs bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-1"
                title={!hasImage ? '当前分镜暂无图片' : '编辑当前分镜图片'}
              >
                <Image className="w-3 h-3" />
                编辑分镜图
              </button>
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
            </div>
            {/* 隐藏的文件输入框 */}
            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg,image/jpg,image/webp"
              onChange={handleUploadImage}
              className="hidden"
            />
          </div>

          <div className="flex-1 min-h-0 overflow-hidden flex flex-col items-center justify-start bg-gray-100 p-6 relative">
            {hasImage ? (
              <>
                <div className="grid min-h-0 flex-1 w-full grid-rows-[minmax(0,1fr)_auto] justify-items-center overflow-hidden pb-2">
                  <div className="flex min-h-0 w-full items-start justify-center overflow-hidden">
                    <img
                      src={currentImageUrl}
                      alt={`${t('chapterGenerate.shot')}${currentShotIndex}`}
                      onClick={handlePreviewShotImage}
                      onLoad={(event) => {
                        setPreviewImageSize({
                          width: event.currentTarget.naturalWidth,
                          height: event.currentTarget.naturalHeight,
                        });
                      }}
                      className="h-full w-auto max-w-[82%] object-contain rounded-lg shadow-lg cursor-zoom-in hover:shadow-xl transition-shadow"
                    />
                  </div>
                  <div className="mt-2 h-5 flex-shrink-0 text-center text-xs text-gray-500">
                    {previewImageSize ? `图片尺寸：${previewImageSize.width} × ${previewImageSize.height}` : '图片尺寸：读取中...'}
                  </div>
                </div>
                {isGeneratingCurrent && (
                  <div className="absolute inset-0 flex flex-col items-center justify-center bg-gray-950/35 text-white backdrop-blur-[1px]">
                    <Loader2 className="h-8 w-8 animate-spin" />
                    <div className="mt-3 rounded-full bg-blue-600/95 px-4 py-1.5 text-sm font-medium shadow">
                      {currentGenerationText || '处理中...'}
                    </div>
                  </div>
                )}
                {/* 查看大图按钮 */}
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handlePreviewShotImage();
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
                <p className="text-gray-600">{currentGenerationText || t('chapterGenerate.generatingShotImage')}</p>
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
        <div className="fixed inset-0 isolate z-[300] flex items-center justify-center bg-black/60 backdrop-blur-[1px]">
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
                  {t('chapterGenerate.selectedShots', { selected: selectedRunnableShotIds.length, total: selectableShotIds.length })}
                </span>
                <div className="flex items-center gap-4">
                  <button
                    onClick={selectPendingOnly}
                    className="text-sm text-blue-600 hover:text-blue-800 flex items-center gap-1"
                  >
                    <Check className="w-4 h-4" />
                    只选择待生成
                  </button>
                  <button
                    onClick={toggleSelectAll}
                    className="text-sm text-blue-600 hover:text-blue-800 flex items-center gap-1"
                  >
                    {selectedRunnableShotIds.length === selectableShotIds.length && selectableShotIds.length > 0 ? (
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
                  const isQueued = pendingShots.has(shotId);
                  const isDisabled = isGenerating || isQueued;

                  return (
                    <div
                      key={shotId}
                      onMouseDown={(event) => handleShotSelectMouseDown(event, shotId, isDisabled)}
                      onMouseEnter={() => handleShotSelectMouseEnter(shotId, isDisabled)}
                      className={`
                        relative aspect-square rounded-lg border-2 transition-all
                        select-none
                        ${isDisabled
                          ? 'border-gray-200 bg-gray-50 cursor-not-allowed'
                          : 'cursor-pointer hover:shadow-md'
                        }
                        ${!isDisabled && isSelected
                          ? 'border-blue-500 bg-blue-50'
                          : !isDisabled && !isSelected
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

                      {/* 选择标记 - 已在队列中的分镜不可选 */}
                      {!isDisabled && (
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
                        ) : isDisabled ? (
                          <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
                        ) : (
                          <Image className="w-8 h-8 text-gray-300" />
                        )}
                      </div>

                      {/* 状态标签 */}
                      <div className="absolute bottom-0 left-0 right-0 px-1 py-0.5 text-xs text-center bg-black/60 text-white rounded-b-lg">
                        {isGenerating ? t('chapterGenerate.generating') : isQueued ? '队列中' : hasShotImage ? t('chapterGenerate.generated') : t('chapterGenerate.pending')}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* 弹窗底部按钮 */}
            <div className="flex items-center justify-between gap-3 p-4 border-t border-gray-200">
              <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={skipBatchLlmWhenPromptExists}
                  onChange={(event) => setSkipBatchLlmWhenPromptExists(event.target.checked)}
                  className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                />
                主分镜图 AI 提示词存在时，不重新生成
              </label>
              <div className="flex items-center justify-end gap-3">
                <button
                  onClick={() => setShowBatchSelectModal(false)}
                  className="px-4 py-2 text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors"
                >
                  {t('common.cancel')}
                </button>
                <button
                  onClick={handleGenerateAll}
                  disabled={selectedRunnableShotIds.length === 0 || isGeneratingAll}
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
                      {t('chapterGenerate.generateShots', { count: selectedRunnableShotIds.length })}
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

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
            otherPlaceholder: '输入额外编辑要求，例如：把人物表情改得更严肃，保持服装不变。',
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

export default ShotImageGenTab;
