import { create } from 'zustand';
import type { Novel, Chapter } from '../types';
import { novelApi } from '../api/novels';

interface NovelState {
  novels: Novel[];
  currentNovel: Novel | null;
  chapters: Chapter[];
  isLoading: boolean;
  error: string | null;
  fetchNovels: () => Promise<void>;
  fetchNovel: (id: string) => Promise<void>;
  fetchChapters: (novelId: string) => Promise<void>;
  createNovel: (data: Partial<Novel>) => Promise<void>;
  copyNovel: (sourceId: string, title: string) => Promise<Novel>;
  deleteNovel: (id: string) => Promise<void>;
  importNovel: (file: File) => Promise<void>;
  updateNovel: (id: string, data: Partial<Novel>) => Promise<void>;
  setNovelArchived: (id: string, isArchived: boolean) => Promise<void>;
}

export const useNovelStore = create<NovelState>((set, get) => ({
  novels: [],
  currentNovel: null,
  chapters: [],
  isLoading: false,
  error: null,

  fetchNovels: async () => {
    set({ isLoading: true });
    try {
      const data = await novelApi.fetchList();
      if (data.success) {
        set({ novels: data.data, isLoading: false });
      }
    } catch (error) {
      set({ error: '获取小说列表失败', isLoading: false });
    }
  },

  fetchNovel: async (id) => {
    set({ isLoading: true });
    try {
      const data = await novelApi.fetch(id);
      if (data.success) {
        set({ currentNovel: data.data, isLoading: false });
      }
    } catch (error) {
      set({ error: '获取小说详情失败', isLoading: false });
    }
  },

  fetchChapters: async (novelId) => {
    try {
      const data = await novelApi.fetchChapters(novelId);
      if (data.success) {
        set({ chapters: data.data });
      }
    } catch (error) {
      set({ error: '获取章节列表失败' });
    }
  },

  createNovel: async (novelData) => {
    try {
      const data = await novelApi.create(novelData);
      if (!data.success || !data.data) throw new Error((data as { detail?: string; message?: string }).detail || data.message || '创建小说失败');
      set((state) => ({ novels: [data.data!, ...state.novels] }));
    } catch (error) {
      set({ error: '创建小说失败' });
      throw error;
    }
  },

  copyNovel: async (sourceId, title) => {
    const response = await novelApi.copy(sourceId, title);
    if (!response.success || !response.data) {
      throw new Error(response.message || '复制小说失败');
    }
    const copied = response.data;
    set((state) => ({ novels: [copied, ...state.novels], error: null }));
    return copied;
  },

  deleteNovel: async (id) => {
    try {
      await novelApi.delete(id);
      set((state) => ({
        novels: state.novels.filter((n) => n.id !== id),
      }));
    } catch (error) {
      set({ error: '删除小说失败' });
    }
  },

  importNovel: async (file) => {
    try {
      const data = await novelApi.import(file);
      if (data.success && data.data) {
        set((state) => ({ novels: [data.data!, ...state.novels] }));
      }
    } catch (error) {
      set({ error: '导入小说失败' });
    }
  },

  updateNovel: async (id, novelData) => {
    try {
      const data = await novelApi.update(id, novelData);
      if (!data.success || !data.data) throw new Error((data as { detail?: string; message?: string }).detail || data.message || '更新小说失败');
      set((state) => ({
        novels: state.novels.map((n) => (n.id === id ? data.data! : n)),
        currentNovel: state.currentNovel?.id === id ? data.data! : state.currentNovel,
      }));
    } catch (error) {
      set({ error: '更新小说失败' });
      throw error;
    }
  },

  setNovelArchived: async (id, isArchived) => {
    const response = await novelApi.setArchived(id, isArchived);
    if (!response.success || !response.data) {
      throw new Error(response.message || (isArchived ? '归档失败' : '恢复失败'));
    }
    set((state) => ({
      novels: state.novels.map((novel) => novel.id === id ? response.data! : novel),
      currentNovel: state.currentNovel?.id === id ? response.data! : state.currentNovel,
      error: null,
    }));
  },
}));
