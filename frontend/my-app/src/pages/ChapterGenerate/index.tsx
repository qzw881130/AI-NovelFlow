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

  // 使用 Store 获取状态和方法
  const store = useChapterGenerateStore();

  // 从 store 中解构需要的状态
  const {
    chapter, novel, parsedData, characters, scenes, props, loading,
    shotImages, shotVideos, transitionVideos, generatingShots, pendingShots,
    generatingVideos, pendingVideos, generatingTransitions,
    showFullTextModal, showMergedImageModal, showImagePreview,
    previewImageUrl, previewImageIndex, mergedImage, isMerging,
    splitConfirmDialog, audioTasks, audioWarnings,
    currentShotIndex,
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
    checkTransitionTaskStatus, checkAudioTaskStatus,
  } = store;

  // UI 方法
  const {
    setShowFullTextModal, setShowMergedImageModal, setShowImagePreview,
    setMergedImage, setIsMerging, setSplitConfirmDialog,
  } = store;

  // Chapter Actions 方法
  const {
    handleSplitChapter, handleSaveJson, handleMergeCharacterImages,
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
                               generatingTransitions.size > 0;

    if (!hasGeneratingTasks) return;

    // 每 2 秒轮询一次
    const intervalId = setInterval(async () => {
      await Promise.all([
        checkShotTaskStatus(cid),
        checkVideoTaskStatus(cid),
        checkTransitionTaskStatus(cid),
      ]);
    }, 2000);

    return () => clearInterval(intervalId);
  }, [cid, id, generatingShots.size, generatingVideos.size, generatingTransitions.size]);

  // 获取真实章节数据和角色列表
  useEffect(() => {
    if (cid && id) {
      fetchNovel(id);
      fetchCharacters(id);
      fetchScenes(id);
      fetchProps(id);
      fetchChapter(id, cid);
      fetchTransitionWorkflows();
    }
  }, [cid, id, fetchProps]);

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
    if (parsedData?.shots && parsedData.shots.length > 0) {
      // Merged image logic handled by store
    }
  }, [parsedData?.shots]);

  // 图片预览导航
  const navigateImagePreview = (direction: 'prev' | 'next') => {
    const allImages = parsedData?.shots?.map((_shot: any, idx: number) => {
      const shotNum = idx + 1;
      return shotImages[shotNum] || parsedData?.shots?.[idx]?.image_url;
    }).filter(Boolean) as string[] || [];

    if (allImages.length <= 1) return;

    let newIndex: number;
    if (direction === 'prev') {
      newIndex = previewImageIndex === 0 ? allImages.length - 1 : previewImageIndex - 1;
    } else {
      newIndex = previewImageIndex === allImages.length - 1 ? 0 : previewImageIndex + 1;
    }

    setShowImagePreview(true, allImages[newIndex] || null, newIndex);
  };

  // 打开图片预览
  const onImageClick = (url: string) => {
    const allImages = parsedData?.shots?.map((_shot: any, idx: number) => {
      const shotNum = idx + 1;
      return shotImages[shotNum] || parsedData?.shots?.[idx]?.image_url;
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
    return audioTasks.filter(task => task.shotIndex === shotIndex);
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
    <div className="h-screen flex flex-col overflow-hidden">
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
        currentShot={currentShotIndex}
      />

      <ImagePreviewModal
        isOpen={showImagePreview}
        onClose={() => setShowImagePreview(false)}
        previewImageUrl={previewImageUrl}
        previewImageIndex={previewImageIndex}
        currentShot={currentShotIndex}
        totalImages={parsedData?.shots?.length || 0}
        onNavigate={navigateImagePreview}
        parsedDataShots={parsedData?.shots || []}
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