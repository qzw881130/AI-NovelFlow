import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { SystemConfig } from '../types';

// API 基础 URL
const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';

interface ConfigState extends SystemConfig {
  isLoading: boolean;
  error: string | null;
  setConfig: (config: Partial<SystemConfig>) => void;
  checkConnection: () => Promise<{ deepseek: boolean; comfyui: boolean }>;
}

const defaultConfig: SystemConfig = {
  deepseekApiKey: '',
  deepseekApiUrl: 'https://api.deepseek.com',
  comfyUIHost: 'http://192.168.50.1:8288',
  outputResolution: '1920x1080',
  outputFrameRate: 24,
};

export const useConfigStore = create<ConfigState>()(
  persist(
    (set, get) => ({
      ...defaultConfig,
      isLoading: false,
      error: null,
      
      setConfig: (config) => set((state) => ({ ...state, ...config })),
      
      checkConnection: async () => {
        set({ isLoading: true, error: null });
        try {
          // 检查 DeepSeek API
          const deepseekRes = await fetch(`${API_BASE}/health/deepseek/`);
          const deepseek = deepseekRes.ok;
          
          // 检查 ComfyUI
          const comfyRes = await fetch(`${API_BASE}/health/comfyui/`);
          const comfyui = comfyRes.ok;
          
          set({ isLoading: false });
          return { deepseek, comfyui };
        } catch (error) {
          set({ isLoading: false, error: '连接检查失败' });
          return { deepseek: false, comfyui: false };
        }
      },
    }),
    {
      name: 'novelflow-config',
    }
  )
);
