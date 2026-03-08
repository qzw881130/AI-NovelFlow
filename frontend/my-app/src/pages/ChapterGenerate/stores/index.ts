/**
 * ChapterGenerate Store - 基于 Zustand 的状态管理
 *
 * 使用 Slice 模式组织状态：
 * - DataSlice: 章节数据、资源数据、分镜数据
 * - GenerationSlice: 图片/视频/转场/音频生成
 * - UiSlice: 界面状态、标签页、弹窗
 * - WorkflowSlice: 工作流状态管理 (新增)
 * - SidePanelSlice: 侧边栏状态管理 (新增)
 * - ShotNavigatorSlice: 分镜导航状态管理 (新增)
 */

import { create } from 'zustand';
import type { ChapterGenerateStore } from './slices/types';

// Import slice creators
import { createDataSlice, type DataSlice } from './slices/dataSlice';
import { createGenerationSlice, type GenerationSlice } from './slices/generationSlice';
import { createUiSlice, type UiSlice } from './slices/uiSlice';
import { createChapterActionsSlice, type ChapterActionsSlice } from './slices/chapterActionsSlice';
// New slices for layout optimization
import { createWorkflowSlice, type WorkflowSlice } from './slices/workflowSlice';
import { createSidePanelSlice, type SidePanelSlice } from './slices/sidePanelSlice';
import { createShotNavigatorSlice, type ShotNavigatorSlice } from './slices/shotNavigatorSlice';

// Compose store from slices
export const useChapterGenerateStore = create<ChapterGenerateStore>()((...args) => {
  const dataSlice = createDataSlice(...args);
  const genSlice = createGenerationSlice(...args);
  const uiSlice = createUiSlice(...args);
  const chapterActionsSlice = createChapterActionsSlice(...args);
  // New slices
  const workflowSlice = createWorkflowSlice(...args);
  const sidePanelSlice = createSidePanelSlice(...args);
  const shotNavigatorSlice = createShotNavigatorSlice(...args);

  return {
    // Data Slice
    ...dataSlice,

    // Generation Slice
    ...genSlice,

    // UI Slice
    ...uiSlice,

    // Chapter Actions Slice
    ...chapterActionsSlice,

    // New Slices
    ...workflowSlice,
    ...sidePanelSlice,
    ...shotNavigatorSlice,
  };
});

// Export types
export type { ChapterGenerateStore } from './slices/types';
export type { DataSlice } from './slices/dataSlice';
export type { GenerationSlice } from './slices/generationSlice';
export type { UiSlice } from './slices/uiSlice';
export type { ChapterActionsSlice } from './slices/chapterActionsSlice';
// New slice types
export type { WorkflowSlice } from './slices/workflowSlice';
export type { SidePanelSlice } from './slices/sidePanelSlice';
export type { ShotNavigatorSlice } from './slices/shotNavigatorSlice';

// Re-export slice types for convenience
export type {
  Shot,
  ShotStatus,
  DialogueData,
  AudioTask,
  AudioWarning,
  ShotWorkflow,
  TransitionWorkflow,
  DataSliceState,
  GenerationSliceState,
  UiSliceState,
  // New slice states
  WorkflowSliceState,
  SidePanelSliceState,
  ShotNavigatorSliceState,
} from './slices/types';

// Export individual slice hooks for selective usage
export function useDataSlice(): DataSlice {
  return useChapterGenerateStore((state) => ({
    // State
    chapter: state.chapter,
    novel: state.novel,
    parsedData: state.parsedData,
    editableJson: state.editableJson,
    loading: state.loading,
    characters: state.characters,
    scenes: state.scenes,
    props: state.props,
    shots: state.shots,
    chapterCharacters: state.chapterCharacters,
    chapterScenes: state.chapterScenes,
    chapterProps: state.chapterProps,
    // Actions
    fetchNovel: state.fetchNovel,
    fetchChapter: state.fetchChapter,
    fetchCharacters: state.fetchCharacters,
    fetchScenes: state.fetchScenes,
    fetchProps: state.fetchProps,
    fetchShots: state.fetchShots,
    fetchShotsWithReturn: state.fetchShotsWithReturn,
    setParsedData: state.setParsedData,
    setEditableJson: state.setEditableJson,
    setShots: state.setShots,
    updateShot: state.updateShot,
    getCharacterImage: state.getCharacterImage,
    getSceneImage: state.getSceneImage,
    getPropImage: state.getPropImage,
    initChapterResources: state.initChapterResources,
    addResourceToChapter: state.addResourceToChapter,
    removeResourceFromChapter: state.removeResourceFromChapter,
    saveChapterResources: state.saveChapterResources,
  }));
}

export function useGenerationSlice(): GenerationSlice {
  return useChapterGenerateStore((state) => ({
    // Image Generation State
    generatingShots: state.generatingShots,
    pendingShots: state.pendingShots,
    shotImages: state.shotImages,
    isGeneratingAll: state.isGeneratingAll,
    uploadingShotIndex: state.uploadingShotIndex,
    // Video Generation State
    generatingVideos: state.generatingVideos,
    pendingVideos: state.pendingVideos,
    shotVideos: state.shotVideos,
    // Transition Generation State
    transitionVideos: state.transitionVideos,
    generatingTransitions: state.generatingTransitions,
    currentTransition: state.currentTransition,
    transitionWorkflows: state.transitionWorkflows,
    selectedTransitionWorkflow: state.selectedTransitionWorkflow,
    transitionDuration: state.transitionDuration,
    // Shot Workflows
    shotWorkflows: state.shotWorkflows,
    activeShotWorkflow: state.activeShotWorkflow,
    // Audio Generation State
    generatingAudios: state.generatingAudios,
    audioWarnings: state.audioWarnings,
    audioTasks: state.audioTasks,
    audioUrls: state.audioUrls,
    audioSources: state.audioSources,
    uploadingAudios: state.uploadingAudios,
    // Image Generation Actions
    generateShotImage: state.generateShotImage,
    generateAllImages: state.generateAllImages,
    uploadShotImage: state.uploadShotImage,
    setShotImages: state.setShotImages,
    // Video Generation Actions
    generateShotVideo: state.generateShotVideo,
    generateAllVideos: state.generateAllVideos,
    setShotVideos: state.setShotVideos,
    // Transition Generation Actions
    generateTransition: state.generateTransition,
    generateAllTransitions: state.generateAllTransitions,
    fetchTransitionWorkflows: state.fetchTransitionWorkflows,
    setSelectedTransitionWorkflow: state.setSelectedTransitionWorkflow,
    setTransitionDuration: state.setTransitionDuration,
    // Audio Generation Actions
    generateShotAudio: state.generateShotAudio,
    generateAllAudio: state.generateAllAudio,
    regenerateAudio: state.regenerateAudio,
    uploadDialogueAudio: state.uploadDialogueAudio,
    deleteDialogueAudio: state.deleteDialogueAudio,
    getAudioUrl: state.getAudioUrl,
    getAudioSource: state.getAudioSource,
    isShotAudioGenerating: state.isShotAudioGenerating,
    isAudioUploading: state.isAudioUploading,
    getShotAudioTasks: state.getShotAudioTasks,
    initAudioFromShots: state.initAudioFromShots,
    // Task Polling Actions
    checkShotTaskStatus: state.checkShotTaskStatus,
    checkVideoTaskStatus: state.checkVideoTaskStatus,
    checkTransitionTaskStatus: state.checkTransitionTaskStatus,
    checkAudioTaskStatus: state.checkAudioTaskStatus,
    fetchActiveTasks: state.fetchActiveTasks,
  }));
}

export function useUiSlice(): UiSlice {
  return useChapterGenerateStore((state) => ({
    // Tab State
    activeTab: state.activeTab,
    // Navigation State
    currentShot: state.currentShot,
    currentVideo: state.currentVideo,
    // JSON Editor State
    jsonEditMode: state.jsonEditMode,
    editorKey: state.editorKey,
    // Modal State
    showFullTextModal: state.showFullTextModal,
    showMergedImageModal: state.showMergedImageModal,
    showImagePreview: state.showImagePreview,
    previewImageUrl: state.previewImageUrl,
    previewImageIndex: state.previewImageIndex,
    // Merge Image State
    mergedImage: state.mergedImage,
    isMerging: state.isMerging,
    // Confirm Dialog State
    splitConfirmDialog: state.splitConfirmDialog,
    // Transition Config State
    showTransitionConfig: state.showTransitionConfig,
    // Generation Status State
    isGenerating: state.isGenerating,
    isSplitting: state.isSplitting,
    isSavingJson: state.isSavingJson,
    // Tab Actions
    setActiveTab: state.setActiveTab,
    // Navigation Actions - backward compatible, calls setCurrentShotIndex
    setCurrentShot: (index: number) => state.setCurrentShotIndex(index),
    setCurrentVideo: state.setCurrentVideo,
    // JSON Editor Actions
    setJsonEditMode: state.setJsonEditMode,
    resetEditorKey: state.resetEditorKey,
    // Modal Actions
    setShowFullTextModal: state.setShowFullTextModal,
    setShowMergedImageModal: state.setShowMergedImageModal,
    setShowImagePreview: state.setShowImagePreview,
    // Merge Image Actions
    setMergedImage: state.setMergedImage,
    setIsMerging: state.setIsMerging,
    // Confirm Dialog Actions
    setSplitConfirmDialog: state.setSplitConfirmDialog,
    // Transition Config Actions
    setShowTransitionConfig: state.setShowTransitionConfig,
    // Generation Status Actions
    setIsGenerating: state.setIsGenerating,
    setIsSplitting: state.setIsSplitting,
    setIsSavingJson: state.setIsSavingJson,
  }));
}

// New slice hooks
export function useWorkflowSlice(): WorkflowSlice {
  return useChapterGenerateStore((state) => ({
    // State
    currentTab: state.currentTab,
    tabProgress: state.tabProgress,
    // Actions
    setCurrentTab: state.setCurrentTab,
    markTabComplete: state.markTabComplete,
    resetTabProgress: state.resetTabProgress,
    saveWorkflowState: state.saveWorkflowState,
  }));
}

export function useSidePanelSlice(): SidePanelSlice {
  return useChapterGenerateStore((state) => ({
    // State
    leftPanelWidth: state.leftPanelWidth,
    rightPanelWidth: state.rightPanelWidth,
    leftPanelCollapsed: state.leftPanelCollapsed,
    rightPanelCollapsed: state.rightPanelCollapsed,
    // Actions
    setLeftPanelWidth: state.setLeftPanelWidth,
    setRightPanelWidth: state.setRightPanelWidth,
    toggleLeftPanel: state.toggleLeftPanel,
    toggleRightPanel: state.toggleRightPanel,
    setLeftPanelCollapsed: state.setLeftPanelCollapsed,
    setRightPanelCollapsed: state.setRightPanelCollapsed,
    saveSidePanelState: state.saveSidePanelState,
  }));
}

export function useShotNavigatorSlice(): ShotNavigatorSlice {
  return useChapterGenerateStore((state) => ({
    // State
    currentShotId: state.currentShotId,
    currentShotIndex: state.currentShotIndex,
    selectedShotIds: state.selectedShotIds,
    bulkMode: state.bulkMode,
    // Actions
    setCurrentShot: state.setCurrentShot,
    setCurrentShotIndex: state.setCurrentShotIndex,
    previousShot: state.previousShot,
    nextShot: state.nextShot,
    toggleShotSelection: state.toggleShotSelection,
    selectAll: state.selectAll,
    clearSelection: state.clearSelection,
    toggleBulkMode: state.toggleBulkMode,
    setBulkMode: state.setBulkMode,
  }));
}

export default useChapterGenerateStore;
