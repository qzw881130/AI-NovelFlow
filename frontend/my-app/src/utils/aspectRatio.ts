/**
 * 画面比例相关工具函数
 */

/**
 * 画面比例对应的 CSS 类名映射
 */
export const ASPECT_RATIO_CLASSES: Record<string, string> = {
  '16:9': 'aspect-video',
  '9:16': 'aspect-[9/16]',
  '4:3': 'aspect-[4/3]',
  '3:4': 'aspect-[3/4]',
  '1:1': 'aspect-square',
  '21:9': 'aspect-[21/9]',
  '2.35:1': 'aspect-[2.35/1]',
};

/**
 * 根据画面比例获取对应的 CSS 类名
 */
export function getAspectRatioClass(aspectRatio: string): string {
  return ASPECT_RATIO_CLASSES[aspectRatio] || 'aspect-video';
}

/** 将图片的实际像素尺寸约成宽高比。 */
export function formatAspectRatio(width: number, height: number): string {
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return '—';
  const roundedWidth = Math.round(width);
  const roundedHeight = Math.round(height);
  if (!roundedWidth || !roundedHeight) return '—';
  let a = roundedWidth;
  let b = roundedHeight;
  while (b !== 0) [a, b] = [b, a % b];
  return `${roundedWidth / a}:${roundedHeight / a}`;
}

/**
 * 画面比例选项
 */
export const ASPECT_RATIO_OPTIONS = [
  { value: '16:9', labelKey: 'novels.aspectRatio.widescreen', descKey: 'novels.aspectRatio.widescreenDesc' },
  { value: '9:16', labelKey: 'novels.aspectRatio.vertical', descKey: 'novels.aspectRatio.verticalDesc' },
  { value: '4:3', labelKey: 'novels.aspectRatio.standard', descKey: 'novels.aspectRatio.standardDesc' },
  { value: '3:4', labelKey: 'novels.aspectRatio.portrait', descKey: 'novels.aspectRatio.portraitDesc' },
  { value: '1:1', labelKey: 'novels.aspectRatio.square', descKey: 'novels.aspectRatio.squareDesc' },
  { value: '21:9', labelKey: 'novels.aspectRatio.ultrawide', descKey: 'novels.aspectRatio.ultrawideDesc' },
  { value: '2.35:1', labelKey: 'novels.aspectRatio.cinema', descKey: 'novels.aspectRatio.cinemaDesc' },
];
