const audioDriveIssueMessages: Record<string, string> = {
  NONE_SEGMENT_LIPSYNC_CONTRADICTION: '提示词口型约束检查未通过：规则检查发现无可见说话者（NONE）片段的描述可能与口型约束冲突，并不代表生成视频中人物实际开口。请检查该片段的说话、张嘴或口型描述，明确静默约束后重新生成提示词。',
  MISSING_AUDIO_TEXT_RENDERING_CONSTRAINT: '音频文字约束不完整：请补充音频仅用于口型驱动、禁止转写及字幕的提示词约束。',
  UNKNOWN_SUBJECT_REFERENCE: '人物引用无法识别：请核对说话者时间轴与参考图人物的对应关系后重新生成提示词。',
  MISSING_SUBJECT_REFERENCE_IN_PROMPT: '提示词缺少说话人物引用：请补充时间轴中说话者对应的参考图人物。',
  INVALID_SPEAKER_TIMELINE: '说话者时间轴格式或时间范围无效：请检查片段起止时间并重新准备音频。',
  INVALID_AUDIO_SPEAKER_SEMANTICS: '音频说话者标记不符合要求：请检查旁白、画外音与可见说话者的标记后重新准备音频。',
  UNRESOLVED_VISIBLE_SPEAKER: '可见说话者无法匹配参考图人物：请检查角色名称和参考图后重新生成提示词。',
  DIALOGUE_TEXT_LEAKAGE: '提示词含有可能触发朗读的台词文本：请移除重复台词，使用驱动音频和说话者时间轴约束口型。',
};

// Only unwrap error envelopes, never search the manifest or prompt for error codes.
const formatAudioDriveAudit = (value: unknown, depth = 0): string | undefined => {
  if (depth > 8) return undefined;
  if (typeof value === 'string') {
    const text = value.trim();
    try {
      return formatAudioDriveAudit(JSON.parse(text), depth + 1);
    } catch {
      // Some API errors prefix (or suffix) the JSON with a human-readable message.
      const start = text.indexOf('{');
      if (start < 0) return undefined;
      let nesting = 0;
      let quoted = false;
      let escaped = false;
      for (let i = start; i < text.length; i++) {
        const char = text[i];
        if (quoted) {
          if (escaped) escaped = false;
          else if (char === '\\') escaped = true;
          else if (char === '"') quoted = false;
        } else if (char === '"') quoted = true;
        else if (char === '{') nesting++;
        else if (char === '}' && --nesting === 0) {
          try {
            return formatAudioDriveAudit(JSON.parse(text.slice(start, i + 1)), depth + 1);
          } catch {
            return undefined;
          }
        }
      }
      return undefined;
    }
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined;
  const audit = value as Record<string, unknown>;
  if (audit.source === 'AudioDrive' && (Array.isArray(audit.issues) || Array.isArray(audit.blocking_issues))) {
    const issues = [...(Array.isArray(audit.blocking_issues) ? audit.blocking_issues : []),
      ...(Array.isArray(audit.issues) ? audit.issues : [])];
    const messages = new Set<string>();
    for (const issue of issues) {
      const code = typeof issue === 'string' ? issue : issue?.code;
      messages.add(typeof code === 'string' && Object.prototype.hasOwnProperty.call(audioDriveIssueMessages, code)
        ? audioDriveIssueMessages[code]
        : '音频驱动提示词检查发现未识别的问题：请检查说话者时间轴和人物引用，重新生成提示词；如仍失败，请查看原始日志。');
    }
    const context = audit.audio_drive_context as Record<string, unknown> | undefined;
    const driveAudio = context && typeof context.drive_audio === 'string' ? context.drive_audio : '';
    const clipMatch = driveAudio.match(/(?:^|[/\\])clip_0*(\d+)(?=[_.\/\\-]|$)/i);
    const clip = clipMatch ? `Clip ${Number(clipMatch[1])} ` : '';
    return `${clip}AudioDrive 审计未通过。${[...messages].join(' ') || '请检查音频驱动提示词和说话者时间轴后重试；详情请查看原始日志。'}`;
  }
  for (const key of ['detail', 'error', 'message']) {
    const formatted = formatAudioDriveAudit(audit[key], depth + 1);
    if (formatted) return formatted;
  }
  return undefined;
};

export const formatUserFacingError = (message?: unknown): string => {
  const audioDriveError = formatAudioDriveAudit(message);
  if (audioDriveError) return audioDriveError;

  const rawMessage = String(message || '').trim();
  if (!rawMessage) return '';

  const lowerMessage = rawMessage.toLowerCase();
  const isAuthError = lowerMessage.includes('authentication fails')
    || lowerMessage.includes('unauthorized')
    || lowerMessage.includes('401')
    || rawMessage.includes('认证失败');

  if (isAuthError) {
    return 'LLM 认证失败，请检查系统设置中的 API Key 是否正确或已过期。';
  }

  if (rawMessage.includes('DIALOGUE_DURATION_INSUFFICIENT')) {
    return 'Clip 台词时长不足：当前 Clip 时长不足以容纳分配到的台词，请缩短台词、延长 Clip，或重新规划关键帧时间轴。';
  }

  const isVideoDecodeError = rawMessage.includes('视频输出解码校验失败')
    || rawMessage.includes('Invalid NAL unit size')
    || rawMessage.includes('Error splitting the input into NAL units')
    || rawMessage.includes('Error submitting packet to decoder');

  if (isVideoDecodeError) {
    return '合并视频解码失败：系统已自动尝试修复但仍未生成可播放视频。请重新合并整体视频；如果仍失败，请重新生成相关 Clip。';
  }

  return rawMessage;
};
