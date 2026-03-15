/**
 * VideoGenTab - 视频生成 Tab（阶段 4）
 *
 * 布局参考分镜图生成页面：
 * - 中间：视频生成提示词编辑 + 视频预览
 * - 右侧：转场生成
 *
 * 注意：分镜资源列表在左侧可折叠区域显示（由 ChapterGenerateLayout 的左侧栏渲染）
 */

import { useState, useEffect } from 'react';
import { useChapterGenerateStore } from '../stores';
import { Film, Loader2, Download, Save, Square, Check, X, Image, ChevronDown, Eye, Combine } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import { shotsApi } from '../../../api/shots';
import { toast } from '../../../stores/toastStore';

interface VideoGenTabProps {
  chapter?: any;
  parsedData?: any;
  shotVideos?: Record<number, string>;
  shotImages?: Record<number, string>;
  transitionVideos?: Record<string, string>;
  generatingVideos?: Set<number>;
  generatingTransitions?: Set<string>;
  currentShot?: number;
  novelId?: string;
  chapterId?: string;
  shots?: any[];
}

export function VideoGenTab({
  chapter,
  parsedData,
  shotVideos = {},
  shotImages = {},
  transitionVideos = {},
  generatingVideos = new Set(),
  generatingTransitions = new Set(),
  currentShot,
  novelId,
  chapterId,
  shots = [],
}: VideoGenTabProps) {
  const { t } = useTranslation();
  const store = useChapterGenerateStore();
  const { markTabComplete, setCurrentShot, downloadChapterMaterials, generateShotVideo, setShots, generateTransition, transitionWorkflows, selectedTransitionWorkflow, setSelectedTransitionWorkflow, fetchTransitionWorkflows } = store;

  // 优先使用 props 传入的 novelId，否则从 chapter 对象获取
  const effectiveNovelId = novelId || chapter?.novelId;
  const effectiveChapterId = chapterId || chapter?.id;

  const [selectedVideo, setSelectedVideo] = useState<number>(1);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isGeneratingAll, setIsGeneratingAll] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);
  const [showBatchSelectModal, setShowBatchSelectModal] = useState(false);
  const [selectedShots, setSelectedShots] = useState<Set<number>>(new Set());
  const [previewImage, setPreviewImage] = useState<string | null>(null);

  // 合并视频相关状态
  const [isMerging, setIsMerging] = useState(false);
  const [showMergeModal, setShowMergeModal] = useState(false);
  const [mergedVideoUrl, setMergedVideoUrl] = useState<string | null>(null);

  const shotsList = parsedData?.shots || [];
  const currentShotData = shotsList[selectedVideo - 1];
  const isGeneratingCurrent = generatingVideos.has(selectedVideo);

  // 初始化获取转场工作流
  useEffect(() => {
    if (transitionWorkflows.length === 0) {
      fetchTransitionWorkflows();
    }
  }, [fetchTransitionWorkflows, transitionWorkflows.length]);

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

  const hasVideo = !!shotVideos[selectedVideo];

  // 处理单个视频生成
  const handleGenerateVideo = async () => {
    if (!effectiveNovelId || !effectiveChapterId) return;
    setIsGenerating(true);
    try {
      await generateShotVideo(effectiveNovelId, effectiveChapterId, selectedVideo);
      markTabComplete(3);
    } catch (error) {
      console.error(t('chapterGenerate.videoGenerateFailed') + ':', error);
    } finally {
      setIsGenerating(false);
    }
  };

  // 打开批量选择弹窗
  const handleOpenBatchSelect = () => {
    // 初始化选择：默认选中所有待生成的分镜（没有视频的）
    const pendingShots = shotsList
      .filter((_: any, idx: number) => !shotVideos[idx + 1])
      .map((_: any, idx: number) => idx + 1);
    setSelectedShots(new Set(pendingShots));
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
      return newSet;
    });
  };

  // 全选/取消全选
  const toggleSelectAll = () => {
    if (selectedShots.size === shotsList.length) {
      setSelectedShots(new Set());
    } else {
      setSelectedShots(new Set(shotsList.map((_: any, idx: number) => idx + 1)));
    }
  };

  // 处理批量视频生成
  const handleGenerateAll = async () => {
    if (!effectiveNovelId || !effectiveChapterId) return;
    setIsGeneratingAll(true);
    try {
      // 依次生成选中的分镜
      for (const index of selectedShots) {
        await generateShotVideo(effectiveNovelId, effectiveChapterId, index);
      }
    } catch (error) {
      console.error(t('chapterGenerate.batchVideoGenerateFailed') + ':', error);
    } finally {
      setIsGeneratingAll(false);
      setShowBatchSelectModal(false);
    }
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
      const result = await shotsApi.batchUpdateShots(effectiveNovelId, effectiveChapterId, [currentShotData]);

      if (result.success) {
        console.log(t('chapterGenerate.shotSaveSuccess'));

        // 更新 store.shots 和 parsedData.shots 状态
        if (result.data?.shots && result.data.shots.length > 0) {
          const updatedShot = result.data.shots[0];
          const currentShots = store.shots;

          // 更新 store.shots
          const newShots = currentShots.map((s: any) =>
            s.id === updatedShot.id ? { ...s, ...updatedShot } : s
          );
          setShots(newShots);

          // 同时更新 parsedData.shots
          if (parsedData?.shots) {
            const updatedParsedShots = parsedData.shots.map((s: any, idx: number) => {
              if (String(s.id) === String(updatedShot.id) || idx === selectedVideo - 1) {
                return { ...s, video_description: updatedShot.video_description };
              }
              return s;
            });
            store.setParsedData({ ...parsedData, shots: updatedParsedShots });
          }
        }
      } else {
        console.error(t('chapterGenerate.shotSaveFailed') + ':', result.message);
      }
    } catch (error) {
      console.error(t('chapterGenerate.shotSaveFailed') + ':', error);
    } finally {
      setIsSaving(false);
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
  const handleMergeVideos = async (includeTransitions: boolean) => {
    if (!effectiveNovelId || !effectiveChapterId) return;

    const videoList = Object.values(shotVideos).filter(Boolean);
    if (videoList.length === 0) {
      toast.error(t('chapterGenerate.noVideosToMerge'));
      return;
    }

    setIsMerging(true);
    try {
      const response = await fetch(
        `/api/novels/${effectiveNovelId}/chapters/${effectiveChapterId}/merge-videos/`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ include_transitions: includeTransitions })
        }
      );

      const data = await response.json();

      if (data.success) {
        setMergedVideoUrl(data.video_url);
        setShowMergeModal(true);
        toast.success(t('chapterGenerate.mergeSuccess'));
      } else {
        toast.error(data.message || t('chapterGenerate.mergeFailed'));
      }
    } catch (error) {
      console.error('Merge error:', error);
      toast.error(t('chapterGenerate.mergeFailed'));
    } finally {
      setIsMerging(false);
    }
  };

  return (
    <div className="h-full flex flex-col">
      {/* 操作栏 */}
      <div className="flex-shrink-0 flex items-center justify-between mb-4 pb-4 border-b border-gray-200">
        <div className="flex items-center gap-4">
          <button
            onClick={handleGenerateVideo}
            disabled={isGenerating || isGeneratingCurrent || !effectiveChapterId}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
          >
            {isGenerating || isGeneratingCurrent ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                {t('chapterGenerate.videoGenerating')}
              </>
            ) : (
              <>
                <Film className="w-4 h-4" />
                {t('chapterGenerate.generateCurrentShot')}
              </>
            )}
          </button>
          <button
            onClick={handleOpenBatchSelect}
            disabled={isGeneratingAll || !effectiveChapterId}
            className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {t('chapterGenerate.batchGenerate')}
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
                {t('chapterGenerate.saveShots')}
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
          <button
            onClick={() => handleMergeVideos(Object.keys(transitionVideos).length > 0)}
            disabled={isMerging || !effectiveChapterId || Object.keys(shotVideos).length === 0}
            className="px-4 py-2 bg-pink-600 text-white rounded-lg hover:bg-pink-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
          >
            {isMerging ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                {t('chapterGenerate.merging')}
              </>
            ) : (
              <>
                <Combine className="w-4 h-4" />
                {t('chapterGenerate.mergeVideo')}
              </>
            )}
          </button>
        </div>
        <div className="text-sm text-gray-500">
          {t('chapterGenerate.shotId', { id: selectedVideo || 0, total: shots.length })}
        </div>
      </div>

      {/* 内容区 - 两栏布局 */}
      <div className="flex-1 min-h-0 flex gap-4 overflow-hidden">
        {/* 中间：视频提示词编辑 + 视频预览 */}
        <div className="flex-1 min-w-0 flex flex-col gap-4">
          {/* 视频提示词编辑区 */}
          <div className="flex-shrink-0 border border-gray-200 rounded-lg p-4">
            <h3 className="text-sm font-medium text-gray-700 mb-3">{t('chapterGenerate.videoDescForVideo')}</h3>
            <textarea
              value={currentShotData?.video_description || ''}
              onChange={(e) => {
                // 更新 parsedData 中的分镜数据（仅本地状态）
                const shotIndex = selectedVideo - 1;
                const shotsList = parsedData?.shots || [];
                if (shotsList[shotIndex]) {
                  const updatedShots = [...shotsList];
                  updatedShots[shotIndex] = {
                    ...updatedShots[shotIndex],
                    video_description: e.target.value,
                  };
                  store.setParsedData({
                    ...parsedData,
                    shots: updatedShots,
                  });
                }
              }}
              placeholder={t('chapterGenerate.videoDescPlaceholder')}
              className="w-full h-40 px-3 py-2 border border-gray-300 rounded-lg resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
            />
            <div className="mt-2 flex items-center gap-2 text-xs text-gray-500">
              <span>{t('chapterGenerate.placeholderHint')}</span>
              <span className="px-1.5 py-0.5 bg-gray-100 rounded">{t('chapterGenerate.placeholderStyle')}</span>
              <span className="px-1.5 py-0.5 bg-gray-100 rounded">{t('chapterGenerate.placeholderScene')}</span>
              <span className="px-1.5 py-0.5 bg-gray-100 rounded">{t('chapterGenerate.placeholderCharacters')}</span>
            </div>
          </div>

          {/* 视频预览区 */}
          <div className="flex-1 min-h-0 flex flex-col border border-gray-200 rounded-lg overflow-hidden">
            <div className="flex-shrink-0 p-3 border-b border-gray-200 bg-gray-50">
              <h3 className="text-sm font-medium text-gray-700">{t('chapterGenerate.videoPreview')}</h3>
            </div>

            <div className="flex-1 relative bg-gray-100">
              {hasVideo ? (
                <video
                  src={shotVideos[selectedVideo]}
                  className="absolute inset-0 w-full h-full object-contain"
                  controls
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
          </div>
        </div>

        {/* 右侧：转场配置区 */}
        <div className="w-96 flex-shrink-0 overflow-y-auto border border-gray-200 rounded-lg p-4">
          <h3 className="text-sm font-medium text-gray-700 mb-3">{t('chapterGenerate.transitionConfig')}</h3>

          {/* 转场工作流选择 */}
          <div className="mb-4 p-3 bg-gray-50 rounded-lg">
            <label className="block text-xs font-medium text-gray-600 mb-2">
              {t('chapterGenerate.transitionWorkflow')}
            </label>
            <div className="relative">
              <select
                value={selectedTransitionWorkflow}
                onChange={(e) => setSelectedTransitionWorkflow(e.target.value)}
                className="w-full px-3 py-2 pr-8 text-sm border border-gray-300 rounded-lg appearance-none bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              >
                <option value="">{t('chapterGenerate.default')}</option>
                {transitionWorkflows.map((workflow: any) => (
                  <option key={workflow.id} value={workflow.id}>
                    {workflow.name}
                  </option>
                ))}
              </select>
              <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500 pointer-events-none" />
            </div>
          </div>

          {/* 转场列表 */}
          <div className="space-y-3">
            {shots.map((shot: any, idx: number) => {
              if (idx === shots.length - 1) return null;
              const from = idx + 1;
              const to = idx + 2;
              const hasTransition = !!transitionVideos[`${from}-${to}`];
              const isGeneratingTransition = generatingTransitions.has(`${from}-${to}`);

              // 获取前后分镜的缩略图
              const fromShot = shots[idx];
              const toShot = shots[idx + 1];
              const fromImage = shotImages[from] || fromShot?.imageUrl;
              const toImage = shotImages[to] || toShot?.imageUrl;

              return (
                <div
                  key={`transition-${from}-${to}`}
                  className="p-3 bg-white border border-gray-200 rounded-lg"
                >
                  {/* 分镜编号 */}
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-sm font-medium text-gray-700">
                      {t('chapterGenerate.transitionBetweenShots', { from, to })}
                    </span>
                    {hasTransition ? (
                      <span className="inline-flex items-center px-1.5 py-0.5 bg-green-100 text-green-700 rounded text-xs">
                        {t('chapterGenerate.generated')}
                      </span>
                    ) : isGeneratingTransition ? (
                      <Loader2 className="w-4 h-4 text-blue-500 animate-spin" />
                    ) : null}
                  </div>

                  {/* 分镜缩略图 */}
                  <div className="flex items-center gap-2 mb-3">
                    {/* 前一分镜缩略图 */}
                    <div className="flex-1 relative aspect-video rounded overflow-hidden bg-gray-100">
                      {fromImage ? (
                        <>
                          <img
                            src={fromImage}
                            alt={t('chapterGenerate.shotThumbnail')}
                            className="w-full h-full object-cover"
                          />
                          <button
                            onClick={() => setPreviewImage(fromImage)}
                            className="absolute top-1 right-1 p-1.5 bg-black/60 hover:bg-black/80 rounded-full text-white transition-colors"
                            title={t('chapterGenerate.viewLarge')}
                          >
                            <Eye className="w-4 h-4" />
                          </button>
                        </>
                      ) : (
                        <div className="w-full h-full flex items-center justify-center">
                          <Image className="w-6 h-6 text-gray-300" />
                        </div>
                      )}
                      <div className="absolute top-1 left-1 px-1.5 py-0.5 bg-black/60 text-white text-xs rounded">
                        {t('chapterGenerate.shot', { number: from })}
                      </div>
                    </div>

                    {/* 箭头 */}
                    <div className="flex-shrink-0 text-gray-400">→</div>

                    {/* 后一分镜缩略图 */}
                    <div className="flex-1 relative aspect-video rounded overflow-hidden bg-gray-100">
                      {toImage ? (
                        <>
                          <img
                            src={toImage}
                            alt={t('chapterGenerate.shotThumbnail')}
                            className="w-full h-full object-cover"
                          />
                          <button
                            onClick={() => setPreviewImage(toImage)}
                            className="absolute top-1 right-1 p-1.5 bg-black/60 hover:bg-black/80 rounded-full text-white transition-colors"
                            title={t('chapterGenerate.viewLarge')}
                          >
                            <Eye className="w-4 h-4" />
                          </button>
                        </>
                      ) : (
                        <div className="w-full h-full flex items-center justify-center">
                          <Image className="w-6 h-6 text-gray-300" />
                        </div>
                      )}
                      <div className="absolute top-1 left-1 px-1.5 py-0.5 bg-black/60 text-white text-xs rounded">
                        {t('chapterGenerate.shot', { number: to })}
                      </div>
                    </div>
                  </div>

                  {/* 生成按钮 */}
                  {!hasTransition && !isGeneratingTransition && (
                    <button
                      onClick={() => handleGenerateTransition(from, to)}
                      className="w-full px-3 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors"
                    >
                      {t('chapterGenerate.generateTransition')}
                    </button>
                  )}
                </div>
              );
            })}
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
                  {t('chapterGenerate.selectedShots', { selected: selectedShots.size, total: shotsList.length })}
                </span>
                <button
                  onClick={toggleSelectAll}
                  className="text-sm text-blue-600 hover:text-blue-800 flex items-center gap-1"
                >
                  {selectedShots.size === shotsList.length ? (
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
                {shotsList.map((shot: any, idx: number) => {
                  const shotIndex = idx + 1;
                  const isSelected = selectedShots.has(shotIndex);
                  const hasVideo = !!shotVideos[shotIndex];
                  const isGenerating = generatingVideos.has(shotIndex);
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
      {previewImage && (
        <div
          className="fixed inset-0 bg-black/80 flex items-center justify-center z-50"
          onClick={() => setPreviewImage(null)}
        >
          <div className="relative max-w-[90vw] max-h-[90vh]">
            <img
              src={previewImage}
              alt={t('chapterGenerate.shotThumbnail')}
              className="max-w-full max-h-[90vh] rounded-lg shadow-2xl"
            />
            <button
              onClick={() => setPreviewImage(null)}
              className="absolute -top-3 -right-3 w-8 h-8 bg-white rounded-full shadow-lg flex items-center justify-center hover:bg-gray-100 transition-colors"
            >
              <X className="w-5 h-5 text-gray-600" />
            </button>
          </div>
        </div>
      )}

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
    </div>
  );
}

export default VideoGenTab;
