/**
 * 健康检查相关 API
 */
import { api } from './index';

export interface SystemStats {
  status: 'online' | 'offline';
  gpuUsage: number;
  vramUsed: number;
  vramTotal: number;
  vramPercent: number;
  queueSize: number;
  temperature?: number;
  gpuSource?: 'real' | 'estimated' | 'comfyui' | 'windows_gpu_monitor' | 'comfyui_fallback';
  gpuName?: string;
  ramUsed?: number;
  ramTotal?: number;
  ramPercent?: number;
}

export interface HealthResponse {
  status: string;
  data?: {
    gpu_usage?: number | null;
    vram_used?: number | null;
    vram_total?: number | null;
    queue_running?: number | null;
    queue_pending?: number | null;
    temperature?: number | null;
    gpu_source?: 'real' | 'estimated' | 'comfyui' | 'windows_gpu_monitor' | 'comfyui_fallback';
    device_name?: string;
    ram_used?: number | null;
    ram_total?: number | null;
    ram_percent?: number | null;
  };
}

export interface DiskUsage {
  mount_point: string;
  name: string;
  total_bytes: number;
  used_bytes: number;
  used_percent: number;
}

export const healthApi = {
  /**
   * 获取 ComfyUI 状态
   */
  getComfyUIStatus: async (): Promise<HealthResponse> => {
    const response = await fetch('/api/health/comfyui');
    if (!response.ok) {
      return { status: 'error' };
    }
    return response.json();
  },

  getSystemStatus: async (signal?: AbortSignal): Promise<HealthResponse> => {
    const response = await fetch('/api/health/system-status', { signal });
    if (!response.ok) {
      return { status: 'error' };
    }
    return response.json();
  },

  getDisks: async (signal?: AbortSignal): Promise<DiskUsage[]> => {
    const response = await fetch('/api/health/disks', { signal });
    if (!response.ok) throw new Error(`Disk usage request failed: ${response.status}`);
    const data: { disks: DiskUsage[] } = await response.json();
    return data.disks;
  },
};
