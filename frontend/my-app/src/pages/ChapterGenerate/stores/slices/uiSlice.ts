/**
 * UI Slice - 管理界面状态、标签页、弹窗等
 */
import type { StateCreator } from 'zustand';
import type { UiSliceState, ChapterGenerateStore } from './types';

export interface UiSlice extends UiSliceState {
  // ========== 标签页 ==========
  setActiveTab: (tab: UiSliceState['activeTab']) => void;

  // ========== 导航 ==========
  setCurrentShot: (shotId: string, index: number) => void;
  setCurrentVideo: (index: number) => void;

  // ========== JSON 编辑器 ==========
  setJsonEditMode: (mode: UiSliceState['jsonEditMode']) => void;
  resetEditorKey: () => void;

  // ========== 弹窗 ==========
  setShowFullTextModal: (show: boolean) => void;
  setShowMergedImageModal: (show: boolean) => void;
  setShowImagePreview: (show: boolean, url?: string | null, index?: number) => void;

  // ========== 合并图片 ==========
  setMergedImage: (image: string | null) => void;
  setIsMerging: (merging: boolean) => void;

  // ========== 确认对话框 ==========
  setSplitConfirmDialog: (dialog: UiSliceState['splitConfirmDialog']) => void;

  // ========== 转场配置 ==========
  setShowTransitionConfig: (show: boolean) => void;

  // ========== 生成状态 ==========
  setIsGenerating: (generating: boolean) => void;
  setIsSplitting: (splitting: boolean) => void;
  setIsSavingJson: (saving: boolean) => void;
}

export const createUiSlice: StateCreator<
  ChapterGenerateStore,
  [],
  [],
  UiSlice
> = (set, get) => ({
  // ========== 初始状态 ==========
  // 标签页
  activeTab: 'prepare',

  // 导航
  currentShot: 1,
  currentVideo: 1,

  // JSON 编辑器
  jsonEditMode: 'text',
  editorKey: 0,

  // 弹窗
  showFullTextModal: false,
  showMergedImageModal: false,
  showImagePreview: false,
  previewImageUrl: null,
  previewImageIndex: 0,

  // 合并图片
  mergedImage: null,
  isMerging: false,

  // 确认对话框
  splitConfirmDialog: { isOpen: false, hasResources: false },

  // 转场配置
  showTransitionConfig: false,

  // 生成状态
  isGenerating: false,
  isSplitting: false,
  isSavingJson: false,

  // ========== 标签页方法 ==========

  setActiveTab: (tab) => {
    set({ activeTab: tab });
  },

  // ========== 导航方法 ==========

  setCurrentShot: (shotId, index) => {
    set({ currentShot: index });
  },

  setCurrentVideo: (index) => {
    set({ currentVideo: index });
  },

  // ========== JSON 编辑器方法 ==========

  setJsonEditMode: (mode) => {
    set({ jsonEditMode: mode });
  },

  resetEditorKey: () => {
    set(state => ({ editorKey: state.editorKey + 1 }));
  },

  // ========== 弹窗方法 ==========

  setShowFullTextModal: (show) => {
    set({ showFullTextModal: show });
  },

  setShowMergedImageModal: (show) => {
    set({ showMergedImageModal: show });
  },

  setShowImagePreview: (show, url = null, index = 0) => {
    set({
      showImagePreview: show,
      previewImageUrl: url,
      previewImageIndex: index
    });
  },

  // ========== 合并图片方法 ==========

  setMergedImage: (image) => {
    set({ mergedImage: image });
  },

  setIsMerging: (merging) => {
    set({ isMerging: merging });
  },

  // ========== 确认对话框方法 ==========

  setSplitConfirmDialog: (dialog) => {
    set({ splitConfirmDialog: dialog });
  },

  // ========== 转场配置方法 ==========

  setShowTransitionConfig: (show) => {
    set({ showTransitionConfig: show });
  },

  // ========== 生成状态方法 ==========

  setIsGenerating: (generating) => {
    set({ isGenerating: generating });
  },

  setIsSplitting: (splitting) => {
    set({ isSplitting: splitting });
  },

  setIsSavingJson: (saving) => {
    set({ isSavingJson: saving });
  },
});
