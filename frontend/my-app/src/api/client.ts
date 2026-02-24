/**
 * API 基础配置和请求封装
 */

const getBaseUrl = () => {
  if (import.meta.env.VITE_API_URL) {
    return import.meta.env.VITE_API_URL + '/api';
  }
  return '/api';
};

export const API_BASE_URL = getBaseUrl();

/**
 * API 响应结构
 */
export interface ApiResponse<T = unknown> {
  success: boolean;
  data?: T;
  message?: string;
  error?: string;
  detail?: string;
}

/**
 * 分页响应结构
 */
export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

/**
 * 请求配置
 */
export interface RequestConfig extends RequestInit {
  params?: Record<string, string | number | boolean | undefined>;
}

/**
 * 构建 URL 查询参数
 */
function buildQueryString(params?: Record<string, string | number | boolean | undefined>): string {
  if (!params) return '';
  
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      searchParams.append(key, String(value));
    }
  });
  
  const queryString = searchParams.toString();
  return queryString ? `?${queryString}` : '';
}

/**
 * 统一的 fetch 封装
 */
export async function request<T>(
  endpoint: string,
  config: RequestConfig = {}
): Promise<ApiResponse<T>> {
  const { params, ...fetchConfig } = config;
  
  const url = endpoint.startsWith('http')
    ? endpoint
    : `${API_BASE_URL}${endpoint}${buildQueryString(params)}`;
  
  const response = await fetch(url, {
    ...fetchConfig,
    headers: {
      'Content-Type': 'application/json',
      ...fetchConfig.headers,
    },
  });
  
  // 尝试解析 JSON
  let data: ApiResponse<T>;
  const contentType = response.headers.get('content-type');
  
  if (contentType?.includes('application/json')) {
    data = await response.json();
  } else {
    data = {
      success: response.ok,
      message: response.statusText,
    };
  }
  
  // 统一错误处理
  if (!response.ok) {
    return {
      ...data,
      success: false,
      error: data.detail || data.error || data.message || `HTTP Error: ${response.status}`,
    };
  }
  
  return data;
}

/**
 * GET 请求
 */
export async function get<T>(endpoint: string, params?: Record<string, string | number | boolean | undefined>): Promise<ApiResponse<T>> {
  return request<T>(endpoint, { method: 'GET', params });
}

/**
 * POST 请求
 */
export async function post<T>(endpoint: string, body?: unknown): Promise<ApiResponse<T>> {
  return request<T>(endpoint, {
    method: 'POST',
    body: body ? JSON.stringify(body) : undefined,
  });
}

/**
 * PUT 请求
 */
export async function put<T>(endpoint: string, body?: unknown): Promise<ApiResponse<T>> {
  return request<T>(endpoint, {
    method: 'PUT',
    body: body ? JSON.stringify(body) : undefined,
  });
}

/**
 * DELETE 请求
 */
export async function del<T>(endpoint: string): Promise<ApiResponse<T>> {
  return request<T>(endpoint, { method: 'DELETE' });
}

/**
 * 上传文件
 */
export async function upload<T>(
  endpoint: string,
  formData: FormData
): Promise<ApiResponse<T>> {
  const url = endpoint.startsWith('http')
    ? endpoint
    : `${API_BASE_URL}${endpoint}`;
  
  const response = await fetch(url, {
    method: 'POST',
    body: formData,
    // 不设置 Content-Type，让浏览器自动设置 multipart/form-data
  });
  
  const data = await response.json();
  
  if (!response.ok) {
    return {
      success: false,
      error: data.detail || data.error || `HTTP Error: ${response.status}`,
    };
  }
  
  return data;
}
