/**
 * ChapterGenerate 页面辅助函数
 */

/**
 * 根据画面比例计算图片容器尺寸
 */
export const getAspectRatioStyle = (aspectRatio: string): React.CSSProperties => {
  const baseSize = 120;
  
  switch (aspectRatio) {
    case '16:9':
      return { width: baseSize, height: Math.round(baseSize * 9 / 16) };
    case '9:16':
      return { width: Math.round(baseSize * 9 / 16), height: baseSize };
    case '4:3':
      return { width: baseSize, height: Math.round(baseSize * 3 / 4) };
    case '3:4':
      return { width: Math.round(baseSize * 3 / 4), height: baseSize };
    case '1:1':
      return { width: baseSize, height: baseSize };
    case '21:9':
      return { width: baseSize, height: Math.round(baseSize * 9 / 21) };
    case '2.35:1':
      return { width: baseSize, height: Math.round(baseSize / 2.35) };
    default:
      return { width: baseSize, height: Math.round(baseSize * 9 / 16) };
  }
};

/**
 * 验证分镜场景是否在场景库中
 */
export const getInvalidSceneShots = (editableJson: string, scenes: { name: string }[]): any[] => {
  if (!editableJson.trim() || scenes.length === 0) return [];
  try {
    const parsed = JSON.parse(editableJson);
    if (!parsed.shots || !Array.isArray(parsed.shots)) return [];
    const sceneNames = scenes.map(s => s.name);
    return parsed.shots.filter((shot: any) => shot.scene && !sceneNames.includes(shot.scene));
  } catch (e) {
    return [];
  }
};
