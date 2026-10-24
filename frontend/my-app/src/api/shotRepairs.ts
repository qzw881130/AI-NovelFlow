import { API_BASE } from './index';

export interface ShotRepairTask {
  taskId: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  progress: number;
  currentStep: string | null;
  errorMessage: string | null;
  resultUrl: string | null;
  sourceTaskId: string | null;
}

const endpoint = (novelId: string, chapterId: string, shotId: string) =>
  `${API_BASE}/novels/${novelId}/chapters/${chapterId}/shots/${shotId}/repair-image`;

async function request(url: string, method: 'GET' | 'POST'): Promise<ShotRepairTask | null> {
  const response = await fetch(url, { method });
  const body = await response.json();
  if (!response.ok || !body.success) throw new Error(body.detail || body.message || '分镜图修复请求失败');
  return body.data || null;
}

export const shotRepairsApi = {
  latest: (novelId: string, chapterId: string, shotId: string) => request(endpoint(novelId, chapterId, shotId), 'GET'),
  enqueue: (novelId: string, chapterId: string, shotId: string) => request(endpoint(novelId, chapterId, shotId), 'POST'),
};
