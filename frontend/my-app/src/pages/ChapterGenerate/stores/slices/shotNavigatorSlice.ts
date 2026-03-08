/**
 * ShotNavigator Slice - 分镜导航状态管理
 *
 * 管理分镜导航相关的状态：
 * - currentShotId / currentShotIndex: 当前选中的分镜
 * - selectedShotIds: 批量选择模式中选中的分镜 ID 列表
 * - bulkMode: 批量模式开关状态
 */

import { StateCreator } from 'zustand';

// ========== Types ==========

export interface ShotNavigatorSliceState {
  /** 当前分镜 ID */
  currentShotId: string | null;

  /** 当前分镜索引 (从 1 开始) */
  currentShotIndex: number;

  /** 批量选择模式中选中的分镜 ID 列表 */
  selectedShotIds: string[];

  /** 批量模式开关状态 */
  bulkMode: boolean;
}

export interface ShotNavigatorSliceActions {
  /** 设置当前分镜（同时设置 ID 和索引） */
  setCurrentShot: (shotId: string, index: number) => void;

  /** 设置当前分镜索引（仅设置索引，用于 backward compatibility） */
  setCurrentShotIndex: (index: number) => void;

  /** 切换到上一分镜 */
  previousShot: (totalShots: number) => void;

  /** 切换到下一分镜 */
  nextShot: (totalShots: number) => void;

  /** 切换分镜选择状态 (批量模式) */
  toggleShotSelection: (shotId: string) => void;

  /** 全选所有分镜 */
  selectAll: (shotIds: string[]) => void;

  /** 清空选择 */
  clearSelection: () => void;

  /** 切换批量模式 */
  toggleBulkMode: () => void;

  /** 设置批量模式 */
  setBulkMode: (mode: boolean) => void;
}

export type ShotNavigatorSlice = ShotNavigatorSliceState & ShotNavigatorSliceActions;

// ========== Initial State ==========

const getInitialState = (): ShotNavigatorSliceState => {
  return {
    currentShotId: null,
    currentShotIndex: 1,
    selectedShotIds: [],
    bulkMode: false,
  };
};

// ========== Create Slice ==========

export const createShotNavigatorSlice: StateCreator<
  ShotNavigatorSlice,
  [],
  [],
  ShotNavigatorSlice
> = (_set, _get) => {
  const state = getInitialState();

  return {
    ...state,

    setCurrentShot: (shotId: string, index: number) => {
      _set({ currentShotId: shotId, currentShotIndex: index });
    },

    setCurrentShotIndex: (index: number) => {
      _set({ currentShotIndex: index, currentShotId: String(index) });
    },

    previousShot: (totalShots: number) => {
      _set((state) => ({
        currentShotIndex: state.currentShotIndex > 1 ? state.currentShotIndex - 1 : state.currentShotIndex,
        currentShotId: state.currentShotIndex > 1 ? String(state.currentShotIndex - 1) : state.currentShotId,
      }));
    },

    nextShot: (totalShots: number) => {
      _set((state) => ({
        currentShotIndex: state.currentShotIndex < totalShots ? state.currentShotIndex + 1 : state.currentShotIndex,
        currentShotId: state.currentShotIndex < totalShots ? String(state.currentShotIndex + 1) : state.currentShotId,
      }));
    },

    toggleShotSelection: (shotId: string) => {
      _set((state) => {
        const isSelected = state.selectedShotIds.includes(shotId);
        return {
          selectedShotIds: isSelected
            ? state.selectedShotIds.filter((id) => id !== shotId)
            : [...state.selectedShotIds, shotId],
        };
      });
    },

    selectAll: (shotIds: string[]) => {
      _set({ selectedShotIds: shotIds });
    },

    clearSelection: () => {
      _set({ selectedShotIds: [] });
    },

    toggleBulkMode: () => {
      _set((state) => {
        const newBulkMode = !state.bulkMode;
        return {
          bulkMode: newBulkMode,
          // 退出批量模式时清空选择
          selectedShotIds: newBulkMode ? state.selectedShotIds : [],
        };
      });
    },

    setBulkMode: (mode: boolean) => {
      _set({
        bulkMode: mode,
        selectedShotIds: mode ? _get().selectedShotIds : [],
      });
    },
  };
};
