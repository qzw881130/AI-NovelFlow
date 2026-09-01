import { useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useTranslation } from '../../stores/i18nStore';

// 导入 Store
import { useChapterGenerateStore } from './stores';

// 导入组件
import { FullTextModal, MergedImageModal, ImagePreviewModal, SplitConfirmDialog } from './components/Modals';
import { ChapterGenerateLayout } from './components/ChapterGenerateLayout';
import { ChapterResourcesModal } from './components/ChapterResourcesModal';

export default function ChapterGenerate() {
  const { t } = useTranslation();
  const { id, cid } = useParams<{ id: string; cid: string }>();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const activeTasksSyncedChapterRef = useRef<string | null>(null);

  // 使用 Store 获取状态和方法
  const store = useChapterGenerateStore();

  // 从 store 中解构需要的状态
  const {
    chapter, novel, parsedData, characters, scenes, props, loading,
    shotImages, shotVideos, transitionVideos, generatingShots, pendingShots,
    generatingVideos, pendingVideos, generatingTransitions, generatingAudios, generatingKeyframes,
    showFullTextModal, showMergedImageModal, showImagePreview,
    previewImageUrl, previewImageIndex, mergedImage, mergedImageLabel, isMerging,
    splitConfirmDialog, audioTasks, audioWarnings,
    currentShotIndex, shots,
  } = store;

  // 数据获取方法
  const {
    fetchNovel, fetchChapter, fetchCharacters, fetchScenes, fetchProps,
    setParsedData, getCharacterImage, getSceneImage, getPropImage,
  } = store;

  // 生成方法
  const {
    generateShotImage, generateAllImages, uploadShotImage, generateShotVideo,
    generateAllVideos, generateTransition, generateAllTransitions, generateShotAudio,
    generateAllAudio, fetchTransitionWorkflows, checkShotTaskStatus, checkVideoTaskStatus,
    checkTransitionTaskStatus, checkAudioTaskStatus, checkKeyframeTaskStatus, fetchActiveTasks,
  } = store;

  // UI 方法
  const {
    setShowFullTextModal, setShowMergedImageModal, setShowImagePreview,
    setMergedImage, setIsMerging, setSplitConfirmDialog, setCurrentShot,
  } = store;

  // Chapter Actions 方法
  const {
    handleSplitChapter, handleSaveJson,
    handleRegenerateCharacter, handleRegenerateScene, handleRegenerateProp,
  } = store;

  // 本地状态
  const [isUploading, setIsUploading] = useState(false);
  const [isGeneratingAll, setIsGeneratingAll] = useState(false);
  const [showResourcesModal, setShowResourcesModal] = useState(false);

  // 轮询任务状态
  useEffect(() => {
    if (!cid || !id) return;

    // 如果有生成中的任务，开始轮询
    const hasGeneratingTasks = generatingShots.size > 0 ||
                               generatingVideos.size > 0 ||
                               generatingTransitions.size > 0 ||
                               generatingAudios.size > 0 ||
                               generatingKeyframes.size > 0;

    if (!hasGeneratingTasks) return;

    let cancelled = false;
    let timeoutId: ReturnType<typeof window.setTimeout> | null = null;

    // 上一轮完成后再等 2 秒发下一轮，避免慢请求堆积成大量 pending。
    const pollTasks = async () => {
      if (cancelled) return;

      const checks = [];
      if (generatingShots.size > 0) {
        checks.push(checkShotTaskStatus(cid));
      }
      if (generatingVideos.size > 0) {
        checks.push(checkVideoTaskStatus(cid));
      }
      if (generatingTransitions.size > 0) {
        checks.push(checkTransitionTaskStatus(cid));
      }
      if (generatingAudios.size > 0) {
        checks.push(checkAudioTaskStatus(cid));
      }
      if (generatingKeyframes.size > 0) {
        checks.push(checkKeyframeTaskStatus(cid));
      }
      if (checks.length > 0) {
        await Promise.allSettled(checks);
      }

      if (!cancelled) {
        timeoutId = window.setTimeout(pollTasks, 2000);
      }
    };

    timeoutId = window.setTimeout(pollTasks, 2000);

    return () => {
      cancelled = true;
      if (timeoutId) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [cid, id, generatingShots.size, generatingVideos.size, generatingTransitions.size, generatingAudios.size, generatingKeyframes.size]);

  // 获取真实章节数据和角色列表
  useEffect(() => {
    if (cid && id) {
      activeTasksSyncedChapterRef.current = null;
      fetchNovel(id);
      fetchCharacters(id);
      fetchScenes(id);
      fetchProps(id);
      fetchChapter(id, cid);
      fetchTransitionWorkflows();
    }
  }, [cid, id, fetchProps]);

  // 刷新页面后本地 generating 集合为空，需要先从后端恢复一次任务状态。
  useEffect(() => {
    if (!cid || chapter?.id !== cid || activeTasksSyncedChapterRef.current === cid) return;

    activeTasksSyncedChapterRef.current = cid;
    fetchActiveTasks(cid);
  }, [cid, chapter?.id, fetchActiveTasks]);

  // 从章节数据初始化状态
  useEffect(() => {
    if (chapter) {
      // 初始化音频数据
      if (chapter.parsedData) {
        try {
          const parsed = typeof chapter.parsedData === 'string'
            ? JSON.parse(chapter.parsedData)
            : chapter.parsedData;
          if (parsed?.shots && Array.isArray(parsed.shots)) {
            // initAudioFromShots(parsed.shots);
          }
        } catch (e) {
          console.error('解析 parsedData 失败:', e);
        }
      }
    }
  }, [chapter?.id]);

  // 切换分镜时更新合并角色图
  useEffect(() => {
    if (shots && shots.length > 0) {
      // Merged image logic handled by store
    }
  }, [shots]);

  // 图片预览导航
  const navigateImagePreview = (direction: 'prev' | 'next') => {
    const imageEntries = shots?.map((shot, idx: number) => {
      const shotNum = idx + 1;
      const imageUrl = shotImages[shot.id] || shotImages[shotNum] || shot.imageUrl || (shot as any).image_url;
      return imageUrl ? { imageUrl, shotId: String(shot.id || shotNum), shotIndex: shotNum } : null;
    }).filter(Boolean) as { imageUrl: string; shotId: string; shotIndex: number }[] || [];

    if (imageEntries.length <= 1) return;

    const currentIndex = previewImageUrl ? imageEntries.findIndex(entry => entry.imageUrl === previewImageUrl) : -1;
    const safeIndex = currentIndex >= 0 ? currentIndex : Math.min(previewImageIndex, imageEntries.length - 1);

    let newIndex: number;
    if (direction === 'prev') {
      newIndex = safeIndex === 0 ? imageEntries.length - 1 : safeIndex - 1;
    } else {
      newIndex = safeIndex === imageEntries.length - 1 ? 0 : safeIndex + 1;
    }

    const nextImage = imageEntries[newIndex];
    if (!nextImage) return;

    setCurrentShot(nextImage.shotId, nextImage.shotIndex);
    setShowImagePreview(true, nextImage.imageUrl, nextImage.shotIndex - 1);
  };

  // 打开图片预览
  const onImageClick = (url: string) => {
    const allImages = shots?.map((shot, idx: number) => {
      const shotNum = idx + 1;
      return shotImages[shot.id] || shotImages[shotNum] || shot.imageUrl || (shot as any).image_url;
    }).filter(Boolean) as string[] || [];

    // 同时检查资源和分镜图片
    const allResourceImages = [
      ...(parsedData?.characters || []).map((name: string) => getCharacterImage(name)).filter(Boolean),
      ...(parsedData?.scenes || []).map((name: string) => getSceneImage(name)).filter(Boolean),
      ...(parsedData?.props || []).map((name: string) => getPropImage(name)).filter(Boolean),
    ] as string[];

    const combinedImages = [...allResourceImages, ...allImages];
    const index = combinedImages.indexOf(url);

    setShowImagePreview(true, url, index >= 0 ? index : 0);
  };

  // 音频相关方法
  const isShotAudioGenerating = (shotIndex: number, characterName?: string) => {
    const key = characterName ? `${shotIndex}-${characterName}` : `${shotIndex}`;
    return generatingTransitions.has(key);
  };

  const getShotAudioTasks = (shotIndex: number) => {
    const shot = shots[shotIndex - 1];
    if (!shot) return [];
    return audioTasks.filter(task => task.shotId === shot.id);
  };

  const handleGenerateAllShots = async (data: any, novelId?: string, chapterId?: string) => {
    if (!novelId || !chapterId || !data?.shots) return;
    setIsGeneratingAll(true);
    try {
      await generateAllImages(novelId, chapterId);
    } finally {
      setIsGeneratingAll(false);
    }
  };

  const handleGenerateAllVideos = async (data: any, images: any, novelId?: string, chapterId?: string) => {
    if (!novelId || !chapterId) return;
    await generateAllVideos(novelId, chapterId);
  };

  const handleGenerateTransition = (from: number, to: number, useCustom: boolean, novelId?: string, chapterId?: string) => {
    if (!novelId || !chapterId) return;
    generateTransition(novelId, chapterId, from, to);
  };

  const handleGenerateAllTransitions = (data: any, novelId?: string, chapterId?: string) => {
    if (!novelId || !chapterId) return;
    generateAllTransitions(novelId, chapterId);
  };

  const handleSplitChapterClick = () => {
    const hasResources = (shotImages && Object.keys(shotImages).length > 0) ||
      (shotVideos && Object.keys(shotVideos).length > 0) ||
      (transitionVideos && Object.keys(transitionVideos).length > 0);
    setSplitConfirmDialog({ isOpen: true, hasResources });
  };

  const doSplitChapter = async () => {
    if (id && cid) {
      await handleSplitChapter(id, cid);
    }
  };

  return (
    <div className="h-[calc(100vh-3rem)] flex flex-col overflow-hidden">
      {/* 主布局组件 */}
      <ChapterGenerateLayout
        chapter={chapter}
        novel={novel}
        parsedData={parsedData}
        shotImages={shotImages}
        shotVideos={shotVideos}
        transitionVideos={transitionVideos}
        characters={characters}
        scenes={scenes}
        props={props}
        generatingShots={generatingShots}
        pendingShots={pendingShots}
        generatingVideos={generatingVideos}
        generatingTransitions={generatingTransitions}
        loading={loading}
        getCharacterImage={getCharacterImage}
        getSceneImage={getSceneImage}
        getPropImage={getPropImage}
        onResourcesManageClick={() => setShowResourcesModal(true)}
        onImageClick={onImageClick}
      />

      {/* 弹窗组件 */}
      <FullTextModal
        isOpen={showFullTextModal}
        onClose={() => setShowFullTextModal(false)}
        chapterTitle={chapter?.title}
        chapterContent={chapter?.content}
      />

      <MergedImageModal
        isOpen={showMergedImageModal}
        onClose={() => setShowMergedImageModal(false)}
        mergedImage={mergedImage}
        imageLabel={mergedImageLabel}
        currentShot={currentShotIndex}
      />

      <ImagePreviewModal
        isOpen={showImagePreview}
        onClose={() => setShowImagePreview(false)}
        previewImageUrl={previewImageUrl}
        previewImageIndex={previewImageIndex}
        currentShot={currentShotIndex}
        totalImages={shots?.length || 0}
        onNavigate={navigateImagePreview}
        parsedDataShots={shots || []}
        shotImages={shotImages}
      />

      <SplitConfirmDialog
        isOpen={splitConfirmDialog.isOpen}
        onClose={() => setSplitConfirmDialog({ isOpen: false, hasResources: false })}
        onConfirm={doSplitChapter}
      />

      {/* 章节资源管理弹窗 */}
      <ChapterResourcesModal
        isOpen={showResourcesModal}
        onClose={() => setShowResourcesModal(false)}
        novelId={id}
        chapterId={cid}
      />

      <canvas ref={canvasRef} className="hidden" />
    </div>
  );
}
