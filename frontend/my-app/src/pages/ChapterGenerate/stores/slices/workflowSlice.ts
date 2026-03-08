/**
 * Workflow Slice - 工作流状态管理
 *
 * 管理四阶段工作流的状态：
 * - currentTab: 当前选中的 Tab 索引 (0-3)
 * - tabProgress: 各 Tab 的完成状态
 */

import { StateCreator } from 'zustand';

// ========== Types ==========

export interface WorkflowSliceState {
  /** 当前 Tab 索引 (0-3) */
  currentTab: number;

  /** 各 Tab 的完成状态 */
  tabProgress: Record<number, boolean>;
}

export interface WorkflowSliceActions {
  /** 切换 Tab */
  setCurrentTab: (index: number) => void;

  /** 标记 Tab 为完成 */
  markTabComplete: (tabIndex: number) => void;

  /** 重置 Tab 完成状态 */
  resetTabProgress: () => void;

  /** 保存状态到 localStorage */
  saveWorkflowState: () => void;
}

export type WorkflowSlice = WorkflowSliceState & WorkflowSliceActions;

// ========== Initial State ==========

const getInitialState = (): WorkflowSliceState => {
  // 尝试从 localStorage 恢复状态
  try {
    const saved = localStorage.getItem('chapterGenerate_workflow');
    if (saved) {
      const parsed = JSON.parse(saved);
      return {
        currentTab: parsed.currentTab ?? 0,
        tabProgress: parsed.tabProgress ?? {},
      };
    }
  } catch (e) {
    console.warn('Failed to restore workflow state from localStorage:', e);
  }

  return {
    currentTab: 0,
    tabProgress: {},
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
      _set({ currentTab: index });
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
        const { currentTab, tabProgress } = _get();
        localStorage.setItem(
          'chapterGenerate_workflow',
          JSON.stringify({ currentTab, tabProgress })
        );
      } catch (e) {
        console.warn('Failed to save workflow state to localStorage:', e);
      }
    },
  };
};
