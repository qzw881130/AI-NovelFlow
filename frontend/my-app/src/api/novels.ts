/**
 * 小说相关 API
 */
import { api, API_BASE } from './index';
import type { Novel, Chapter } from '../types';

export interface StoryWorldContext {
  world_type: string;
  era: string;
  historical_period: string;
  geographic_scope: string;
  cultural_system: string;
  technology_level: string;
  allow_time_travel: boolean;
  material_culture: {
    clothing: string;
    architecture: string;
    objects: string;
  };
  visual_exclusions: string[];
}

export interface StoryWorldContextData {
  context: StoryWorldContext | null;
  locked: boolean;
  updatedAt?: string | null;
  source?: { novelName: string; novelDescription: string };
  promptTemplateName?: string;
}

export interface NovelVideoMergeChapter {
  id: string;
  number: number;
  title: string;
  videoUrl: string;
}

export type CoverTextStyle = 'classic' | 'cinematic' | 'editorial' | 'vintage';

export interface NovelVideoCover {
  id: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  progress: number;
  currentStep?: string | null;
  errorMessage?: string | null;
  imageUrl?: string | null;
  frameSeconds: number;
  aspectRatio: '16:9' | '9:16' | '4:3' | '3:4' | '1:1';
  textStyle?: CoverTextStyle;
  title: string;
  author: string;
  production: string;
}

export interface YoutubeUpload {
  id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress: number;
  currentStep?: string | null;
  errorMessage?: string | null;
  title: string;
  privacyStatus: 'private' | 'unlisted' | 'public';
  youtubeUrl?: string | null;
  warnings?: string[];
  createdAt?: string | null;
}

export interface NovelVideoMergeHistory {
  id: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  progress: number;
  currentStep?: string | null;
  errorMessage?: string | null;
  videoUrl?: string | null;
  fileSize?: number | null;
  duration?: number | null;
  cacheHit: boolean;
  videoVariant: 'draft' | 'hd';
  targetMegapixels?: number | null;
  chapters: NovelVideoMergeChapter[];
  createdAt?: string | null;
  completedAt?: string | null;
  cover?: NovelVideoCover | null;
  covers?: NovelVideoCover[];
  activeCovers?: NovelVideoCover[];
  youtubeUpload?: YoutubeUpload | null;
}

export const novelApi = {
  /** 获取小说列表 */
  fetchList: () => api.get<Novel[]>('/novels/'),

  /** 获取单个小说 */
  fetch: (id: string) => api.get<Novel>(`/novels/${id}/`),

  /** 创建小说 */
  create: (data: Partial<Novel>) => api.post<Novel>('/novels/', data),

  /** 仅复制所有章回标题、正文和顺序到新小说 */
  copy: (id: string, title: string) => api.post<Novel>(`/novels/${id}/copy`, { title }),

  /** 获取已锁定的小说级故事世界上下文 */
  fetchStoryWorldContext: (id: string) => api.get<StoryWorldContextData>(`/novels/${id}/story-world-context`),

  /** 调用 #01 推荐故事世界上下文草稿 */
  recommendStoryWorldContext: (id: string) => api.post<StoryWorldContextData>(`/novels/${id}/story-world-context/recommend`),

  /** 保存并锁定人工确认后的故事世界上下文 */
  saveStoryWorldContext: (id: string, context: StoryWorldContext) => api.put<StoryWorldContextData>(`/novels/${id}/story-world-context`, { context }),

  /** 更新小说 */
  update: (id: string, data: Partial<Novel>) => api.put<Novel>(`/novels/${id}/`, data),

  /** 在活动小说与归档小说之间移动 */
  setArchived: (id: string, isArchived: boolean) =>
    api.patch<Novel>(`/novels/${id}/archive`, { isArchived }),

  /** 导出当前小说配置的提示词模板 */
  exportPromptTemplates: async (id: string, templateIds: Record<string, string | undefined>) => {
    const response = await fetch(`${API_BASE}/novels/${id}/prompt-templates/export`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ templateIds }),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || data.message || '导出提示词模板失败');
    }
    const blob = await response.blob();
    const disposition = response.headers.get('content-disposition') || '';
    const encodedFilenameMatch = disposition.match(/filename\*=UTF-8''([^;]+)/i);
    const filenameMatch = disposition.match(/filename="?([^";]+)"?/i);
    const filename = encodedFilenameMatch
      ? decodeURIComponent(encodedFilenameMatch[1])
      : filenameMatch?.[1] || 'prompt_templates.zip';
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  },

  /** 删除小说 */
  delete: (id: string) => api.delete(`/novels/${id}/`),

  /** 获取章节列表 */
  fetchChapters: (novelId: string) => api.get<Chapter[]>(`/novels/${novelId}/chapters/`),

  /** 合并选中的章回最终视频 */
  mergeChapterVideos: (novelId: string, chapterIds: string[], videoVariant: 'draft' | 'hd' = 'draft', targetMegapixels?: number) =>
    api.post<NovelVideoMergeHistory>(`/novels/${novelId}/video-merges`, { chapter_ids: chapterIds, video_variant: videoVariant, target_megapixels: targetMegapixels }),

  /** 获取小说章回视频合并历史 */
  fetchVideoMergeHistory: (novelId: string) =>
    api.get<NovelVideoMergeHistory[]>(`/novels/${novelId}/video-merges`),

  /** 下载合并视频，文件名由服务端根据小说标题和视频版本生成 */
  videoMergeDownloadUrl: (novelId: string, taskId: string) =>
    `${API_BASE}/novels/${encodeURIComponent(novelId)}/video-merges/${encodeURIComponent(taskId)}/download`,

  generateVideoCover: (novelId: string, taskId: string, data: {
    frameSeconds: number; aspectRatio: NovelVideoCover['aspectRatio']; textStyle: CoverTextStyle;
    title: string; author: string; production: string;
  }) => api.post<NovelVideoCover>(`/novels/${novelId}/video-merges/${taskId}/cover`, {
    frame_seconds: data.frameSeconds, aspect_ratio: data.aspectRatio,
    text_style: data.textStyle,
    title: data.title, author: data.author, production: data.production,
  }),

  videoCoverDownloadUrl: (novelId: string, taskId: string, coverId?: string) =>
    `${API_BASE}/novels/${encodeURIComponent(novelId)}/video-merges/${encodeURIComponent(taskId)}/cover/download${coverId ? `?cover_id=${encodeURIComponent(coverId)}` : ''}`,

  /** 导入小说 */
  import: async (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.upload<Novel>('/novels/import/', formData);
  },

  /** 解析角色 */
  parseCharacters: (novelId: string, params: { sync: boolean; start_chapter?: number; end_chapter?: number; is_incremental: boolean }) => {
    const searchParams = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined) searchParams.append(key, String(value));
    });
    return api.post(`/novels/${novelId}/parse-characters/?${searchParams.toString()}`);
  },
};
