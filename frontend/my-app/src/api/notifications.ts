import { API_BASE } from './index';

export interface PageSoundConfig {
  enabled: boolean;
  soundId: string;
  volume: number;
}

export interface NotificationEvent {
  event_code: string;
  name: string;
  category: string;
  description: string;
  enabled: boolean;
}

export interface NotificationConfig {
  pageSound: PageSoundConfig;
  feishu: { enabled: boolean; webhookMasked: string; secretMasked: string };
  telegram: { enabled: boolean; botTokenMasked: string; chatIdMasked: string };
  events: NotificationEvent[];
  sounds: { id: string; name: string; url: string }[];
  latestPageSoundId: number;
}

export interface DispatchResult {
  event_code: string;
  status: string;
  channels: Record<string, string>;
}

type ConfigUpdate = {
  pageSound?: PageSoundConfig;
  feishu?: { enabled: boolean; webhook?: string; secret?: string };
  telegram?: { enabled: boolean; botToken?: string; chatId?: string };
  eventSwitches?: Record<string, boolean>;
};

async function request<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}/notifications${path}`, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok || !result.success) {
    throw new Error(result.detail || result.message || '请求失败');
  }
  return result.data as T;
}

export const notificationApi = {
  getConfig: () => request<NotificationConfig>('/config'),
  updateConfig: (body: ConfigUpdate) => request<NotificationConfig>('/config', 'PUT', body),
  testChannel: (channel: 'FEISHU' | 'TELEGRAM') =>
    request<{ channel: string; status: string }>('/test-channel', 'POST', { channel }),
  testEvent: (event_code: string, payload: Record<string, unknown>) =>
    request<DispatchResult>('/test-event', 'POST', { event_code, payload }),
  getPageSound: (afterId: number) =>
    request<{ deliveries: { id: number; eventCode: string; isTest: boolean }[]; pageSound: PageSoundConfig }>(
      `/page-sound?after_id=${afterId}`,
    ),
};
