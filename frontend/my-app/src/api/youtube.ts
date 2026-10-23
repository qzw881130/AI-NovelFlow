import { api, API_BASE } from './index';
import type { YoutubeUpload } from './novels';

export interface YoutubeSettings {
  clientId: string;
  hasClientSecret: boolean;
  connected: boolean;
  redirectUri: string;
  defaultTags: string;
}

export interface YoutubePlaylist { id: string; title: string }

export const youtubeApi = {
  settings: () => api.get<YoutubeSettings>('/youtube/settings'),
  saveSettings: (data: Partial<YoutubeSettings> & { clientSecret?: string }) =>
    api.post<YoutubeSettings>('/youtube/settings', data),
  uploadClientFile: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return api.upload<YoutubeSettings>('/youtube/client-file', form);
  },
  authUrl: () => api.get<{ url: string }>('/youtube/auth-url'),
  playlists: () => api.get<YoutubePlaylist[]>('/youtube/playlists'),
  upload: (novelId: string, mergeId: string, data: {
    title: string; description: string; tags: string;
    privacyStatus: 'private' | 'unlisted' | 'public'; playlistId: string; coverId: string;
  }) => api.post<YoutubeUpload>(`/novels/${encodeURIComponent(novelId)}/video-merges/${encodeURIComponent(mergeId)}/youtube-upload`, data),
  retry: (uploadId: string) => api.post<YoutubeUpload>(`/youtube/uploads/${encodeURIComponent(uploadId)}/retry`),
  callbackOrigin: () => new URL(API_BASE, window.location.href).origin,
};
