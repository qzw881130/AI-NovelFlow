export const formatUserFacingError = (message?: unknown): string => {
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
