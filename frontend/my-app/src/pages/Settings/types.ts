// Settings 页面类型定义

import type { LLMProvider, ProxyConfig, LLMModel } from '../../types';

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
  nodeMapping?: {
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
  };
}

export interface SettingsFormData {
  llmProvider: LLMProvider;
  llmModel: string;
  llmApiKey: string;
  llmApiUrl: string;
  llmMaxTokens?: number;
  llmTemperature?: string;
  proxy: ProxyConfig;
  comfyUIHost: string;
}

export interface MappingForm {
  promptNodeId: string;
  saveImageNodeId: string;
  widthNodeId: string;
  heightNodeId: string;
  videoSaveNodeId: string;
  maxSideNodeId: string;
  referenceImageNodeId: string;
  frameCountNodeId: string;
  firstImageNodeId: string;
  lastImageNodeId: string;
  characterReferenceImageNodeId: string;
  sceneReferenceImageNodeId: string;
}

export interface AvailableNodes {
  clipTextEncode: string[];
  saveImage: string[];
  easyInt: string[];
  crPromptText: string[];
  vhsVideoCombine: string[];
  loadImage: string[];
}
