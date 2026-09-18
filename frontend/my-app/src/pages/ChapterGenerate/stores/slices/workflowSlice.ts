/**
 * Workflow Slice - 工作流状态管理
 *
 * 管理五阶段工作流，迁移旧四阶段存储索引。
 * - tabProgress: 各 Tab 的完成状态
 */

import { StateCreator } from 'zustand';
import {restoreProductionStages,WORKFLOW_STATE_VERSION} from '../../productionStages';

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
  /** 当前 Tab 索引 (0-4) */
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
      return restoreProductionStages(parsed);
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
      if(!Number.isInteger(index)||index<0||index>4)return;
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
          getWorkflowStorageKey(),
          JSON.stringify({ version:WORKFLOW_STATE_VERSION,currentTab, tabProgress })
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
          const restored=restoreProductionStages(parsed);
          _set(restored);
          localStorage.setItem(getWorkflowStorageKey(novelId,chapterId),JSON.stringify({version:WORKFLOW_STATE_VERSION,...restored}));
          return;
        }
      } catch (e) {
        console.warn('Failed to load workflow state from localStorage:', e);
      }

      _set({ currentTab: 0, tabProgress: {} });
    },
  };
};
