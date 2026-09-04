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
type ApiResponse<T> = { success: boolean; data?: T; message?: string };

async function parseResponse<T>(res: Response): Promise<ApiResponse<T>> {
  const data = await res.json().catch(() => ({}));
  if (res.ok) return data;
  return {
    success: false,
    message: data?.message || data?.detail || data?.error || `请求失败 (${res.status})`,
  };
}

export const api = {
  get: async <T>(url: string): Promise<ApiResponse<T>> => {
    const res = await fetch(`${API_BASE}${url}`);
    return parseResponse<T>(res);
  },

  post: async <T>(url: string, body?: unknown): Promise<ApiResponse<T>> => {
    const res = await fetch(`${API_BASE}${url}`, {
      method: 'POST',
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    return parseResponse<T>(res);
  },

  put: async <T>(url: string, body: unknown): Promise<ApiResponse<T>> => {
    const res = await fetch(`${API_BASE}${url}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    return parseResponse<T>(res);
  },

  patch: async <T>(url: string, body: unknown): Promise<ApiResponse<T>> => {
    const res = await fetch(`${API_BASE}${url}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    return parseResponse<T>(res);
  },

  delete: async <T>(url: string): Promise<ApiResponse<T>> => {
    const res = await fetch(`${API_BASE}${url}`, { method: 'DELETE' });
    return parseResponse<T>(res);
  },

  upload: async <T>(url: string, formData: FormData): Promise<ApiResponse<T>> => {
    const res = await fetch(`${API_BASE}${url}`, {
      method: 'POST',
      body: formData,
    });
    return parseResponse<T>(res);
  },
};
