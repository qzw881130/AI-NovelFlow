/**
 * 工作流相关 API
 */

import { get, post, put, del, upload, ApiResponse } from './client';

export interface WorkflowNodeMapping {
  prompt_node_id?: string;
  save_image_node_id?: string;
  width_node_id?: string;
  height_node_id?: string;
  video_save_node_id?: string;
  max_side_node_id?: string;
  reference_image_node_id?: string;
  frame_count_node_id?: string;
  first_image_node_id?: string;
  last_image_node_id?: string;
  character_reference_image_node_id?: string;
  scene_reference_image_node_id?: string;
}

export interface Workflow {
  id: string;
  name: string;
  nameKey?: string;
  description?: string;
  descriptionKey?: string;
  type: 'character' | 'scene' | 'shot' | 'video' | 'transition';
  typeName: string;
  isSystem: boolean;
  isActive: boolean;
  nodeMapping?: WorkflowNodeMapping;
  workflowJson?: string;
}

export const workflowApi = {
  /**
   * 获取工作流列表
   */
  list: (type?: string) => get<Workflow[]>('/workflows/', { type }),
  
  /**
   * 获取工作流详情
   */
  get: (id: string) => get<Workflow>(`/workflows/${id}/`),
  
  /**
   * 上传工作流
   */
  upload: async (data: {
    name: string;
    type: string;
    description?: string;
    file: File;
  }) => {
    const formData = new FormData();
    formData.append('name', data.name);
    formData.append('type', data.type);
    if (data.description) {
      formData.append('description', data.description);
    }
    formData.append('file', data.file);
    return upload<Workflow>('/workflows/upload/', formData);
  },
  
  /**
   * 更新工作流
   */
  update: (id: string, data: Partial<Workflow>) => 
    put<Workflow>(`/workflows/${id}/`, data),
  
  /**
   * 删除工作流
   */
  delete: (id: string) => del<void>(`/workflows/${id}/`),
  
  /**
   * 设置默认工作流
   */
  setDefault: (id: string) => post<void>(`/workflows/${id}/set-default/`),
};

export default workflowApi;
