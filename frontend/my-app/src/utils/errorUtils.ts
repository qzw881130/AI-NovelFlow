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

  return rawMessage;
};
