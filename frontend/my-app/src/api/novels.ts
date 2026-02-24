/**
 * 小说相关 API
 */

import { get, post, put, del, ApiResponse } from './client';

export interface Novel {
  id: number;
  title: string;
  author: string;
  description: string;
  total_chapters: number;
  created_at: string;
  updated_at: string;
}

export interface Chapter {
  id: number;
  novel_id: number;
  chapter_number: number;
  title: string;
  content: string;
  parsed_content?: string;
  characters?: string;
  scenes?: string;
  shots?: string;
  created_at: string;
  updated_at: string;
  has_transition_videos?: boolean;
}

export interface NovelDetail extends Novel {
  chapters: Chapter[];
}

export const novelApi = {
  /**
   * 获取小说列表
   */
  list: () => get<Novel[]>('/novels/'),
  
  /**
   * 获取小说详情
   */
  get: (id: number) => get<NovelDetail>(`/novels/${id}/`),
  
  /**
   * 创建小说
   */
  create: (data: Partial<Novel>) => post<Novel>('/novels/', data),
  
  /**
   * 更新小说
   */
  update: (id: number, data: Partial<Novel>) => put<Novel>(`/novels/${id}/`, data),
  
  /**
   * 删除小说
   */
  delete: (id: number) => del<void>(`/novels/${id}/`),
  
  /**
   * 获取章节详情
   */
  getChapter: (novelId: number, chapterId: number) => 
    get<Chapter>(`/novels/${novelId}/chapters/${chapterId}/`),
  
  /**
   * 更新章节
   */
  updateChapter: (novelId: number, chapterId: number, data: Partial<Chapter>) =>
    put<Chapter>(`/novels/${novelId}/chapters/${chapterId}/`, data),
  
  /**
   * 删除章节
   */
  deleteChapter: (novelId: number, chapterId: number) =>
    del<void>(`/novels/${novelId}/chapters/${chapterId}/`),
  
  /**
   * 解析角色
   */
  parseCharacters: (novelId: number, chapterId: number) =>
    post<void>(`/novels/${novelId}/chapters/${chapterId}/parse-characters/`),
  
  /**
   * 解析场景
   */
  parseScenes: (novelId: number, chapterId: number) =>
    post<void>(`/novels/${novelId}/chapters/${chapterId}/parse-scenes/`),
  
  /**
   * 章节分镜拆分
   */
  splitChapter: (novelId: number, chapterId: number) =>
    post<void>(`/novels/${novelId}/chapters/${chapterId}/split/`),
  
  /**
   * 清除章节资源
   */
  clearResources: (novelId: number, chapterId: number) =>
    post<void>(`/novels/${novelId}/chapters/${chapterId}/clear-resources`),
};
