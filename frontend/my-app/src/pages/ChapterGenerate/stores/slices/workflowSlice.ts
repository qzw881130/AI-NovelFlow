/**
 * Workflow Slice - 工作流状态管理
 *
 * 管理四阶段工作流的状态：
 * - currentTab: 当前选中的 Tab 索引 (0-3)
 * - tabProgress: 各 Tab 的完成状态
 */

import { StateCreator } from 'zustand';

const WORKFLOW_STORAGE_PREFIX = 'chapterGenerate_workflow';

const getWorkflowStorageKey = (novelId?: string, chapterId?: string) => {
  if (novelId && chapterId) {
    return `${WORKFLOW_STORAGE_PREFIX}_${novelId}_${chapterId}`;
  }

  if (typeof window !== 'undefined') {
    const match = window.location.pathname.match(/\/novels\/([^/]+)\/chapters\/([^/]+)\/generate/);
    if (match) {
      return `${WORKFLOW_STORAGE_PREFIX}_${match[1]}_${match[2]}`;
    }
  }

  return WORKFLOW_STORAGE_PREFIX;
};

// ========== Types ==========

export interface WorkflowSliceState {
  /** 当前 Tab 索引 (0-3) */
  currentTab: number;

  /** 各 Tab 的完成状态 */
  tabProgress: Record<number, boolean>;
  hdTargetMegapixels: number;
}

export interface WorkflowSliceActions {
  /** 切换 Tab */
  setCurrentTab: (index: number) => void;
  setHdTargetMegapixels: (value: number) => void;

  /** 标记 Tab 为完成 */
  markTabComplete: (tabIndex: number) => void;

  /** 重置 Tab 完成状态 */
  resetTabProgress: () => void;

  /** 保存状态到 localStorage */
  saveWorkflowState: () => void;

  /** 按章节加载状态 */
  loadWorkflowState: (novelId?: string, chapterId?: string) => void;
}

export type WorkflowSlice = WorkflowSliceState & WorkflowSliceActions;

// ========== Initial State ==========

const getInitialState = (): WorkflowSliceState => {
  // 尝试从 localStorage 恢复状态
  try {
    const saved = localStorage.getItem(getWorkflowStorageKey());
    if (saved) {
      const parsed = JSON.parse(saved);
      return {
        currentTab: Number.isInteger(parsed.currentTab) && parsed.currentTab >= 0 && parsed.currentTab <= 4 ? parsed.currentTab : 0,
        tabProgress: parsed.tabProgress ?? {},
        hdTargetMegapixels: Number(parsed.hdTargetMegapixels) || 1.0,
      };
    }
  } catch (e) {
    console.warn('Failed to restore workflow state from localStorage:', e);
  }

  return {
    currentTab: 0,
    tabProgress: {},
    hdTargetMegapixels: 1.0,
  };
};

// ========== Create Slice ==========

export const createWorkflowSlice: StateCreator<
  WorkflowSlice,
  [],
  [],
  WorkflowSlice
> = (_set, _get) => {
  const state = getInitialState();

  return {
    ...state,

    setCurrentTab: (index: number) => {
      _set({ currentTab: Math.max(0, Math.min(4, Math.trunc(index))) });
      _get().saveWorkflowState();
    },

    setHdTargetMegapixels: (value: number) => {
      _set({ hdTargetMegapixels: value });
      _get().saveWorkflowState();
    },

    markTabComplete: (tabIndex: number) => {
      _set((state) => ({
        tabProgress: {
          ...state.tabProgress,
          [tabIndex]: true,
        },
      }));
      _get().saveWorkflowState();
    },

    resetTabProgress: () => {
      _set({ tabProgress: {} });
      _get().saveWorkflowState();
    },

    // 持久化方法
    saveWorkflowState: () => {
      try {
        const { currentTab, tabProgress, hdTargetMegapixels } = _get();
        localStorage.setItem(
          getWorkflowStorageKey(),
          JSON.stringify({ currentTab, tabProgress, hdTargetMegapixels })
        );
      } catch (e) {
        console.warn('Failed to save workflow state to localStorage:', e);
      }
    },

    loadWorkflowState: (novelId?: string, chapterId?: string) => {
      try {
        const saved = localStorage.getItem(getWorkflowStorageKey(novelId, chapterId));
        if (saved) {
          const parsed = JSON.parse(saved);
          _set({
            currentTab: Number.isInteger(parsed.currentTab) && parsed.currentTab >= 0 && parsed.currentTab <= 4 ? parsed.currentTab : 0,
            tabProgress: parsed.tabProgress ?? {},
            hdTargetMegapixels: Number(parsed.hdTargetMegapixels) || 1.0,
          });
          return;
        }
      } catch (e) {
        console.warn('Failed to load workflow state from localStorage:', e);
      }

      _set({ currentTab: 0, tabProgress: {} });
    },
  };
};
