export const formatUserFacingError = (message?: unknown): string => {
  const rawMessage = String(message || '').trim();
  if (!rawMessage) return '';

  if (rawMessage.includes('PHASE_B_PREFLIGHT_FAILED')) {
    return '视频导演提示词未通过结构校验，视频尚未提交生成。请重试当前 Shot；如果持续失败，请检查 Phase B 提示词格式。';
  }

  if (rawMessage.includes('PREVIOUS_AV_BINDING_UNVERIFIED')) {
    return '上一段音视频的续接绑定未通过验证：当前工作流的原生遮罩上下文节点路径与系统已验证的结构不一致。Clip 在 H3 Phase B 输入校验时停止，尚未提交 ComfyUI。请检查续接工作流的采样、放大和输出节点连接，或选择已验证的续接工作流。';
  }

  if (rawMessage.includes('PHASE_B_INPUT_NOT_COVERED')) {
    return 'H3 Phase B 输入校验未通过，当前 Clip 尚未提交视频生成。请展开原始错误查看具体原因，并检查所选工作流及生成输入。';
  }

  const lowerMessage = rawMessage.toLowerCase();
  const isAuthError = lowerMessage.includes('authentication fails')
    || lowerMessage.includes('unauthorized')
    || /(?:status(?:\s+code)?|http)\s*[:=]?\s*401\b/i.test(rawMessage)
    || rawMessage.includes('认证失败');

  if (isAuthError) {
    return 'LLM 认证失败，请检查系统设置中的 API Key 是否正确或已过期。';
  }

  if (rawMessage.includes('PHASE_B_DIRECTOR_FAILED')) {
    if (/(?:\b502\b|\b503\b|\b504\b|upstream_error|Upstream service temporarily unavailable)/i.test(rawMessage)) {
      const status = rawMessage.match(/API 错误\s*\((502|503|504)\)/)?.[1];
      return `LLM 请求失败：接口返回${status ? ` HTTP ${status}` : '上游错误'}（上游服务暂时不可用）。Phase B 导演规划未完成，本次 Clip 尚未提交视频生成。请稍后恢复批次或重试 Clip；详情见大模型日志。`;
    }
    return 'LLM 导演规划调用失败，视频尚未提交。请查看大模型日志中的具体错误后重试。';
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
