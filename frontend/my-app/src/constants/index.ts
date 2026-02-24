/**
 * 应用常量
 */

export * from './llm';

/**
 * 应用版本
 */
export const APP_VERSION = '1.0.0';

/**
 * 本地存储键名
 */
export const STORAGE_KEYS = {
  CONFIG: 'novelflow-config',
  CONFIG_V2: 'novelflow-config-v2',
  PARSE_CHARACTERS_PROMPT: 'novelfow_parse_characters_prompt',
  I18N_LANGUAGE: 'novelflow-i18n-language',
} as const;

/**
 * 视频输出分辨率预设
 */
export const RESOLUTION_PRESETS = [
  { id: '1920x1080', name: '1080p (1920×1080)', width: 1920, height: 1080 },
  { id: '1280x720', name: '720p (1280×720)', width: 1280, height: 720 },
  { id: '2560x1440', name: '2K (2560×1440)', width: 2560, height: 1440 },
  { id: '3840x2160', name: '4K (3840×2160)', width: 3840, height: 2160 },
  { id: '1080x1920', name: '竖屏 1080×1920', width: 1080, height: 1920 },
  { id: '720x1280', name: '竖屏 720×1280', width: 720, height: 1280 },
] as const;

/**
 * 帧率预设
 */
export const FRAME_RATE_PRESETS = [24, 25, 30, 60] as const;

/**
 * 默认分镜数量范围
 */
export const SHOT_COUNT_RANGE = {
  min: 1,
  max: 50,
  default: 10,
} as const;
