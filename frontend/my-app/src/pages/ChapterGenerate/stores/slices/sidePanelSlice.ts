/**
 * SidePanel Slice - 侧边栏状态管理
 *
 * 管理三栏布局中侧边栏的宽度和收起状态：
 * - leftPanelWidth / rightPanelWidth: 侧边栏宽度
 * - leftPanelCollapsed / rightPanelCollapsed: 侧边栏收起状态
 */

import { StateCreator } from 'zustand';

// ========== Types ==========

export interface SidePanelSliceState {
  /** 左侧栏宽度 (200-400px) */
  leftPanelWidth: number;

  /** 右侧栏宽度 (200-450px) */
  rightPanelWidth: number;

  /** 左侧栏是否收起 */
  leftPanelCollapsed: boolean;

  /** 右侧栏是否收起 */
  rightPanelCollapsed: boolean;
}

export interface SidePanelSliceActions {
  /** 设置左侧栏宽度 */
  setLeftPanelWidth: (width: number) => void;

  /** 设置右侧栏宽度 */
  setRightPanelWidth: (width: number) => void;

  /** 切换左侧栏收起状态 */
  toggleLeftPanel: () => void;

  /** 切换右侧栏收起状态 */
  toggleRightPanel: () => void;

  /** 设置左侧栏收起状态 */
  setLeftPanelCollapsed: (collapsed: boolean) => void;

  /** 设置右侧栏收起状态 */
  setRightPanelCollapsed: (collapsed: boolean) => void;

  /** 保存状态到 localStorage */
  saveSidePanelState: () => void;
}

export type SidePanelSlice = SidePanelSliceState & SidePanelSliceActions;

// ========== Constants ==========

const MIN_LEFT_WIDTH = 200;
const MAX_LEFT_WIDTH = 400;
const MIN_RIGHT_WIDTH = 200;
const MAX_RIGHT_WIDTH = 450;
const COLLAPSED_WIDTH = 48;

// ========== Initial State ==========

const getInitialState = (): SidePanelSliceState => {
  // 尝试从 localStorage 恢复状态
  try {
    const saved = localStorage.getItem('chapterGenerate_sidePanel');
    if (saved) {
      const parsed = JSON.parse(saved);
      return {
        leftPanelWidth: parsed.leftPanelWidth ?? MIN_LEFT_WIDTH,
        rightPanelWidth: parsed.rightPanelWidth ?? MIN_RIGHT_WIDTH,
        leftPanelCollapsed: parsed.leftPanelCollapsed ?? false,
        rightPanelCollapsed: parsed.rightPanelCollapsed ?? false,
      };
    }
  } catch (e) {
    console.warn('Failed to restore sidePanel state from localStorage:', e);
  }

  return {
    leftPanelWidth: MIN_LEFT_WIDTH,
    rightPanelWidth: MIN_RIGHT_WIDTH,
    leftPanelCollapsed: false,
    rightPanelCollapsed: false,
  };
};

// ========== Create Slice ==========

export const createSidePanelSlice: StateCreator<
  SidePanelSlice,
  [],
  [],
  SidePanelSlice
> = (_set, _get) => {
  const state = getInitialState();

  return {
    ...state,

    setLeftPanelWidth: (width: number) => {
      const clampedWidth = Math.max(MIN_LEFT_WIDTH, Math.min(MAX_LEFT_WIDTH, width));
      _set({ leftPanelWidth: clampedWidth });
      // 设置宽度时自动展开
      if (_get().leftPanelCollapsed) {
        _set({ leftPanelCollapsed: false });
      }
      _get().saveSidePanelState();
    },

    setRightPanelWidth: (width: number) => {
      const clampedWidth = Math.max(MIN_RIGHT_WIDTH, Math.min(MAX_RIGHT_WIDTH, width));
      _set({ rightPanelWidth: clampedWidth });
      // 设置宽度时自动展开
      if (_get().rightPanelCollapsed) {
        _set({ rightPanelCollapsed: false });
      }
      _get().saveSidePanelState();
    },

    toggleLeftPanel: () => {
      _set((state) => ({ leftPanelCollapsed: !state.leftPanelCollapsed }));
      _get().saveSidePanelState();
    },

    toggleRightPanel: () => {
      _set((state) => ({ rightPanelCollapsed: !state.rightPanelCollapsed }));
      _get().saveSidePanelState();
    },

    setLeftPanelCollapsed: (collapsed: boolean) => {
      _set({ leftPanelCollapsed: collapsed });
      _get().saveSidePanelState();
    },

    setRightPanelCollapsed: (collapsed: boolean) => {
      _set({ rightPanelCollapsed: collapsed });
      _get().saveSidePanelState();
    },

    // 持久化方法
    saveSidePanelState: () => {
      try {
        const { leftPanelWidth, rightPanelWidth, leftPanelCollapsed, rightPanelCollapsed } = _get();
        localStorage.setItem(
          'chapterGenerate_sidePanel',
          JSON.stringify({ leftPanelWidth, rightPanelWidth, leftPanelCollapsed, rightPanelCollapsed })
        );
      } catch (e) {
        console.warn('Failed to save sidePanel state to localStorage:', e);
      }
    },
  };
};
