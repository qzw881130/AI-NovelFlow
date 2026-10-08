/**
 * API 配置
 * 统一管理 API 基础 URL 和请求配置
 */

export const API_BASE = import.meta.env.VITE_API_URL 
  ? `${import.meta.env.VITE_API_URL}/api` 
  : '/api';

/**
 * 通用请求封装
 */
export const api = {
  get: async <T>(url: string, options?: { signal?: AbortSignal }): Promise<{ success: boolean; data?: T; message?: string }> => {
    const res = await fetch(`${API_BASE}${url}`, options);
    return res.json();
  },

  post: async <T>(url: string, body?: unknown): Promise<{ success: boolean; data?: T; message?: string }> => {
    const res = await fetch(`${API_BASE}${url}`, {
      method: 'POST',
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    return res.json();
  },

  put: async <T>(url: string, body: unknown): Promise<{ success: boolean; data?: T; message?: string }> => {
    const res = await fetch(`${API_BASE}${url}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    return res.json();
  },

  delete: async <T>(url: string): Promise<{ success: boolean; data?: T; message?: string }> => {
    const res = await fetch(`${API_BASE}${url}`, { method: 'DELETE' });
    return res.json();
  },

  upload: async <T>(url: string, formData: FormData): Promise<{ success: boolean; data?: T; message?: string }> => {
    const res = await fetch(`${API_BASE}${url}`, {
      method: 'POST',
      body: formData,
    });
    return res.json();
  },
};
