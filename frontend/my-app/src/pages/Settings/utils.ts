// Settings 页面工具函数

/**
 * 获取 Provider 显示名称（使用翻译键）
 */
export const getProviderDisplayName = (providerId: string, t: any): string => {
  const providerKeyMap: Record<string, string> = {
    'deepseek': 'systemSettings.providers.deepseek',
    'openai': 'systemSettings.providers.openai',
    'gemini': 'systemSettings.providers.gemini',
    'anthropic': 'systemSettings.providers.anthropic',
    'azure': 'systemSettings.providers.azure',
    'aliyun-bailian': 'systemSettings.providers.aliyunBailian',
    'ollama': 'systemSettings.providers.ollama',
    'custom': 'systemSettings.providers.custom',
  };
  const key = providerKeyMap[providerId];
  if (key) {
    return t(key, { defaultValue: providerId });
  }
  return providerId;
};

/**
 * 获取模型名称（使用翻译键）
 */
export const getModelName = (modelId: string, t: any): string => {
  const nameKeyMap: Record<string, string> = {
    'qwen-max': 'systemSettings.modelNames.qwenMax',
    'qwen-plus': 'systemSettings.modelNames.qwenPlus',
    'qwen-turbo': 'systemSettings.modelNames.qwenTurbo',
    'qwen-coder-plus': 'systemSettings.modelNames.qwenCoderPlus',
    'qwen-2.5-72b-instruct': 'systemSettings.modelNames.qwen25',
    'custom-model': 'systemSettings.modelNames.customModel',
  };
  const key = nameKeyMap[modelId];
  if (key) {
    return t(key, { defaultValue: '' });
  }
  return '';
};

/**
 * 获取模型描述（使用翻译键）
 */
export const getModelDescription = (modelId: string, t: any): string => {
  const descKeyMap: Record<string, string> = {
    'deepseek-chat': 'systemSettings.modelDescriptions.deepseekDesc',
    'deepseek-coder': 'systemSettings.modelDescriptions.deepseekCoderDesc',
    'deepseek-reasoner': 'systemSettings.modelDescriptions.deepseekReasonerDesc',
    'gpt-4o': 'systemSettings.modelDescriptions.gpt4oDesc',
    'gpt-4o-mini': 'systemSettings.modelDescriptions.gpt4oMiniDesc',
    'gpt-4-turbo': 'systemSettings.modelDescriptions.gpt4TurboDesc',
    'gpt-3.5-turbo': 'systemSettings.modelDescriptions.gpt35TurboDesc',
    'gemini-2.5-flash-preview-05-20': 'systemSettings.modelDescriptions.gemini25FlashPreviewDesc',
    'gemini-2.5-pro-preview-05-20': 'systemSettings.modelDescriptions.gemini25ProPreviewDesc',
    'gemini-2.0-flash': 'systemSettings.modelDescriptions.gemini20FlashDesc',
    'gemini-2.0-flash-lite': 'systemSettings.modelDescriptions.gemini20FlashLiteDesc',
    'gemini-2.0-pro-exp-02-05': 'systemSettings.modelDescriptions.gemini20ProExpDesc',
    'claude-3-5-sonnet-20241022': 'systemSettings.modelDescriptions.claude35SonnetDesc',
    'claude-3-opus-20240229': 'systemSettings.modelDescriptions.claude3OpusDesc',
    'claude-3-sonnet-20240229': 'systemSettings.modelDescriptions.claude3SonnetDesc',
    'claude-3-haiku-20240307': 'systemSettings.modelDescriptions.claude3HaikuDesc',
    'azure-gpt-4o': 'systemSettings.modelDescriptions.azureGpt4oDesc',
    'azure-gpt-4': 'systemSettings.modelDescriptions.azureGpt4Desc',
    'azure-gpt-35-turbo': 'systemSettings.modelDescriptions.azureGpt35TurboDesc',
    'qwen-max': 'systemSettings.modelDescriptions.qwenMaxDesc',
    'qwen-plus': 'systemSettings.modelDescriptions.qwenPlusDesc',
    'qwen-turbo': 'systemSettings.modelDescriptions.qwenTurboDesc',
    'qwen-coder-plus': 'systemSettings.modelDescriptions.qwenCoderPlusDesc',
    'qwen-2.5-72b-instruct': 'systemSettings.modelDescriptions.qwen25Desc',
    'deepseek-v3': 'systemSettings.modelDescriptions.deepseekV3AliDesc',
    'deepseek-r1': 'systemSettings.modelDescriptions.deepseekR1AliDesc',
    'custom-model': 'systemSettings.modelDescriptions.customModelDesc',
  };
  const key = descKeyMap[modelId];
  if (key) {
    return t(key, { defaultValue: '' });
  }
  return '';
};

/**
 * 获取工作流类型名称
 */
export const getTypeNames = (t: any) => ({
  character: t('systemSettings.workflow.character'),
  scene: t('systemSettings.workflow.scene'),
  shot: t('systemSettings.workflow.shot'),
  video: t('systemSettings.workflow.video'),
  transition: t('systemSettings.workflow.transition')
});

/**
 * 获取工作流显示名称（系统预设的使用翻译键）
 */
export const getWorkflowDisplayName = (workflow: any, t: any): string => {
  if (workflow.isSystem && workflow.nameKey) {
    return t(workflow.nameKey, { defaultValue: workflow.name });
  }
  return workflow.name;
};

/**
 * 获取工作流显示描述（系统预设的使用翻译键）
 */
export const getWorkflowDisplayDescription = (workflow: any, t: any): string => {
  if (workflow.isSystem && workflow.descriptionKey) {
    return t(workflow.descriptionKey, { defaultValue: workflow.description || '' });
  }
  return workflow.description || '';
};

/**
 * 检查工作流映射配置是否完整
 */
export const checkWorkflowMappingComplete = (workflow: any): boolean => {
  if (!workflow.nodeMapping) return false;
  
  const mapping = workflow.nodeMapping;
  
  switch (workflow.type) {
    case 'character':
    case 'scene':
      return !!(
        mapping.prompt_node_id &&
        mapping.prompt_node_id !== 'auto' &&
        mapping.save_image_node_id &&
        mapping.save_image_node_id !== 'auto'
      );
    case 'shot':
      const shotMapping = mapping as any;
      const hasBasicFields = !!(
        mapping.prompt_node_id &&
        mapping.prompt_node_id !== 'auto' &&
        mapping.save_image_node_id &&
        mapping.save_image_node_id !== 'auto' &&
        mapping.width_node_id &&
        mapping.width_node_id !== 'auto' &&
        mapping.height_node_id &&
        mapping.height_node_id !== 'auto'
      );
      const hasSingleReference = shotMapping.reference_image_node_id && shotMapping.reference_image_node_id !== 'auto';
      const hasDualReference = (
        shotMapping.character_reference_image_node_id &&
        shotMapping.character_reference_image_node_id !== 'auto' &&
        shotMapping.scene_reference_image_node_id &&
        shotMapping.scene_reference_image_node_id !== 'auto'
      );
      return hasBasicFields && (hasSingleReference || hasDualReference);
    case 'video':
      const videoMapping = mapping as any;
      return !!(
        mapping.prompt_node_id &&
        mapping.prompt_node_id !== 'auto' &&
        videoMapping.video_save_node_id &&
        videoMapping.video_save_node_id !== 'auto' &&
        videoMapping.reference_image_node_id &&
        videoMapping.reference_image_node_id !== 'auto'
      );
    case 'transition':
      const transitionMapping = mapping as any;
      return !!(
        transitionMapping.first_image_node_id &&
        transitionMapping.first_image_node_id !== 'auto' &&
        transitionMapping.last_image_node_id &&
        transitionMapping.last_image_node_id !== 'auto' &&
        transitionMapping.video_save_node_id &&
        transitionMapping.video_save_node_id !== 'auto' &&
        transitionMapping.frame_count_node_id &&
        transitionMapping.frame_count_node_id !== 'auto'
      );
    default:
      return false;
  }
};
