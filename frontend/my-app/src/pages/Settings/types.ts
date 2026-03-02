// Settings 页面类型定义

import type { LLMProvider, ProxyConfig, LLMModel } from '../../types';

export interface Workflow {
  id: string;
  name: string;
  nameKey?: string;
  description?: string;
  descriptionKey?: string;
  type: 'character' | 'scene' | 'shot' | 'video' | 'transition' | 'prop' | 'voice_design' | 'audio';
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
    // 音色设计相关节点
    voice_prompt_node_id?: string;
    ref_text_node_id?: string;
    save_audio_node_id?: string;
    // 音频生成相关节点
    reference_audio_node_id?: string;
    text_node_id?: string;
    emotion_prompt_node_id?: string;
  };
  extension?: {
    [key: string]: any;
  };
}

// 扩展属性配置
export interface ExtensionConfig {
  name: string;
  label: string;
  labelKey: string;
  options: {
    value: string;
    label: string;
    labelKey: string;
  }[];
  default: string;
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
  // 音色设计相关节点
  voicePromptNodeId: string;
  refTextNodeId: string;
  saveAudioNodeId: string;
  // 音频生成相关节点
  referenceAudioNodeId: string;
  textNodeId: string;
  emotionPromptNodeId: string;
}

export interface AvailableNodes {
  clipTextEncode: string[];
  saveImage: string[];
  easyInt: string[];
  crPromptText: string[];
  vhsVideoCombine: string[];
  loadImage: string[];
  // 音色设计相关节点
  qwen3TtsVoiceDesign: string[];
  saveAudio: string[];
  // 音频生成相关节点
  loadAudio: string[];
  qwen3TtsVoiceClone: string[];
}
