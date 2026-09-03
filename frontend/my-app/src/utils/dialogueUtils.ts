const SLOW_DIALOGUE_EMOTIONS = ['庄严', '缓慢', '沉稳', '郑重', '肃穆', 'solemn', 'slow', 'measured'];
export type DialogueDurationWarningLevel = 'normal' | 'notice' | 'warning' | 'critical';

export const DIALOGUE_WARNING_STYLES: Record<DialogueDurationWarningLevel, { label: string; shortLabel: string; className: string; badgeClassName: string }> = {
  normal: {
    label: '正常',
    shortLabel: '正常',
    className: 'border-green-200 bg-green-50 text-green-700',
    badgeClassName: 'bg-green-100 text-green-700',
  },
  notice: {
    label: '提醒',
    shortLabel: '偏密',
    className: 'border-yellow-200 bg-yellow-50 text-yellow-700',
    badgeClassName: 'bg-yellow-100 text-yellow-700',
  },
  warning: {
    label: '警告',
    shortLabel: '过满',
    className: 'border-orange-200 bg-orange-50 text-orange-700',
    badgeClassName: 'bg-orange-100 text-orange-700',
  },
  critical: {
    label: '严重',
    shortLabel: '不足',
    className: 'border-red-200 bg-red-50 text-red-700',
    badgeClassName: 'bg-red-100 text-red-700',
  },
};

export const estimateDialogueSeconds = (text?: string, emotionPrompt?: string) => {
  const chineseChars = (text || '').match(/[\u4e00-\u9fff]/g)?.length || 0;
  if (chineseChars <= 0) return 0;
  const charsPerSecond = SLOW_DIALOGUE_EMOTIONS.some(keyword => String(emotionPrompt || '').includes(keyword)) ? 2.8 : 3.2;
  return Math.max(1.5, (chineseChars / charsPerSecond) + 0.8);
};

export const dialogueText = (dialogue: any) => String(dialogue?.text || dialogue?.dialogue || '').trim();
export const dialogueSpeaker = (dialogue: any) => String(dialogue?.character_name || dialogue?.speaker || dialogue?.character || '').trim();
export const dialogueEmotion = (dialogue: any) => String(dialogue?.emotion_prompt || dialogue?.emotion || '').trim();

export const numberOrNull = (value: any): number | null => {
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue : null;
};

export const getClipDialoguesForDisplay = (shot: any, clip: any) => {
  if (Array.isArray(clip?.clip_dialogues) && clip.clip_dialogues.length > 0) return clip.clip_dialogues;
  const dialogues = Array.isArray(shot?.dialogues) ? shot.dialogues : [];
  if (!dialogues.length) return [];

  const clipStart = numberOrNull(clip?.start_time) ?? 0;
  const clipEnd = numberOrNull(clip?.end_time) ?? numberOrNull(shot?.duration) ?? clipStart;
  const timedDialogues = dialogues.filter((dialogue: any) => (
    numberOrNull(dialogue?.start_time ?? dialogue?.start ?? dialogue?.time ?? dialogue?.timestamp) !== null
    || numberOrNull(dialogue?.end_time ?? dialogue?.end) !== null
  ));

  if (timedDialogues.length > 0) {
    return timedDialogues.filter((dialogue: any) => {
      const start = numberOrNull(dialogue?.start_time ?? dialogue?.start ?? dialogue?.time ?? dialogue?.timestamp) ?? clipStart;
      const end = numberOrNull(dialogue?.end_time ?? dialogue?.end) ?? start;
      return start < clipEnd && end > clipStart;
    });
  }

  const duration = Math.max(numberOrNull(shot?.duration) ?? clipEnd, clipEnd, 1);
  return dialogues
    .map((dialogue: any, index: number) => ({ dialogue, index }))
    .sort((a: any, b: any) => {
      const aOrder = numberOrNull(a.dialogue?.order);
      const bOrder = numberOrNull(b.dialogue?.order);
      if (aOrder !== null && bOrder !== null) return aOrder - bOrder;
      if (aOrder !== null) return -1;
      if (bOrder !== null) return 1;
      return a.index - b.index;
    })
    .filter(({ index }: any) => {
      const position = (index / Math.max(dialogues.length, 1)) * duration;
      return clipStart <= position && (position < clipEnd || (index === dialogues.length - 1 && position <= clipEnd));
    })
    .map(({ dialogue }: any) => dialogue);
};

export const getDialogueMinimumTotalSeconds = (dialogues: any[] = []) => dialogues.reduce((total, dialogue) => (
  total + estimateDialogueSeconds(dialogueText(dialogue), dialogueEmotion(dialogue))
), 0);

export const getDialogueDurationWarning = (duration?: number | null, minRequiredSeconds?: number | null) => {
  const shotDuration = Math.max(0, Number(duration) || 0);
  const minSeconds = Math.max(0, Number(minRequiredSeconds) || 0);
  const ratio = shotDuration > 0 ? minSeconds / shotDuration : minSeconds > 0 ? Infinity : 0;
  const suggestedDuration = minSeconds > 0 ? Math.ceil(minSeconds / 0.85) : 0;
  let level: DialogueDurationWarningLevel = 'normal';

  if (ratio > 1) level = 'critical';
  else if (ratio > 0.85) level = 'warning';
  else if (ratio > 0.7) level = 'notice';

  return {
    level,
    ratio,
    duration: shotDuration,
    minRequiredSeconds: minSeconds,
    suggestedDuration,
    style: DIALOGUE_WARNING_STYLES[level],
  };
};

export const getShotDialogueDurationWarning = (shot: any) => {
  const dialogues = Array.isArray(shot?.dialogues) ? shot.dialogues : [];
  const minRequiredSeconds = getDialogueMinimumTotalSeconds(dialogues);
  return getDialogueDurationWarning(numberOrNull(shot?.duration), minRequiredSeconds);
};

export const getDialogueDurationWarningStats = (shots: any[] = []) => {
  const stats: Record<DialogueDurationWarningLevel, number> = {
    normal: 0,
    notice: 0,
    warning: 0,
    critical: 0,
  };
  let checkedCount = 0;

  shots.forEach((shot) => {
    const dialogues = Array.isArray(shot?.dialogues) ? shot.dialogues : [];
    if (dialogues.length === 0) return;
    checkedCount += 1;
    stats[getShotDialogueDurationWarning(shot).level] += 1;
  });

  return {
    checkedCount,
    stats,
    issueCount: stats.notice + stats.warning + stats.critical,
  };
};
