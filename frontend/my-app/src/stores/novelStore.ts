import { create } from 'zustand';
import type { Novel, Chapter } from '../types';

// API 基础 URL
const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';

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
  deleteNovel: (id: string) => Promise<void>;
  importNovel: (file: File) => Promise<void>;
  updateNovel: (id: string, data: Partial<Novel>) => Promise<void>;
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
      const res = await fetch(`${API_BASE}/novels/`);
      const data = await res.json();
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
      const res = await fetch(`${API_BASE}/novels/${id}/`);
      const data = await res.json();
      if (data.success) {
        set({ currentNovel: data.data, isLoading: false });
      }
    } catch (error) {
      set({ error: '获取小说详情失败', isLoading: false });
    }
  },

  fetchChapters: async (novelId) => {
    try {
      const res = await fetch(`${API_BASE}/novels/${novelId}/chapters/`);
      const data = await res.json();
      if (data.success) {
        set({ chapters: data.data });
      }
    } catch (error) {
      set({ error: '获取章节列表失败' });
    }
  },

  createNovel: async (novelData) => {
    try {
      const res = await fetch(`${API_BASE}/novels/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(novelData),
      });
      const data = await res.json();
      if (data.success) {
        set((state) => ({ novels: [data.data, ...state.novels] }));
      }
    } catch (error) {
      set({ error: '创建小说失败' });
    }
  },

  deleteNovel: async (id) => {
    try {
      await fetch(`${API_BASE}/novels/${id}/`, { method: 'DELETE' });
      set((state) => ({
        novels: state.novels.filter((n) => n.id !== id),
      }));
    } catch (error) {
      set({ error: '删除小说失败' });
    }
  },

  importNovel: async (file) => {
    const formData = new FormData();
    formData.append('file', file);
    try {
      const res = await fetch(`${API_BASE}/novels/import/`, {
        method: 'POST',
        body: formData,
      });
      const data = await res.json();
      if (data.success) {
        set((state) => ({ novels: [data.data, ...state.novels] }));
      }
    } catch (error) {
      set({ error: '导入小说失败' });
    }
  },

  updateNovel: async (id, novelData) => {
    try {
      const res = await fetch(`${API_BASE}/novels/${id}/`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(novelData),
      });
      const data = await res.json();
      if (data.success) {
        set((state) => ({
          novels: state.novels.map((n) => (n.id === id ? data.data : n)),
          currentNovel: state.currentNovel?.id === id ? data.data : state.currentNovel,
        }));
      }
    } catch (error) {
      set({ error: '更新小说失败' });
    }
  },
}));
