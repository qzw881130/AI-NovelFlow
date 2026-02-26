import { useEffect, useState } from 'react';
import { useConfigStore } from '../../../stores/configStore';
import { useTranslation } from '../../../stores/i18nStore';

export function useWelcomeState() {
  const { t } = useTranslation();
  const { checkConnection, llmProvider, llmModel, llmApiKey, comfyUIHost } = useConfigStore();
  const [status, setStatus] = useState<{ llm: boolean; comfyui: boolean } | null>(null);
  const [checking, setChecking] = useState(false);

  const providerName = t(`systemSettings.providers.${llmProvider}`);
  const modelName = llmModel;
  // 基于连接状态判断是否已配置（API Key 不暴露给前端，所以不能依赖 llmApiKey）
  const isConfigured = status?.llm && status?.comfyui;

  const handleCheck = async () => {
    setChecking(true);
    const result = await checkConnection();
    setStatus(result);
    setChecking(false);
  };

  useEffect(() => { handleCheck(); }, []);

  return { status, checking, providerName, modelName, isConfigured, handleCheck, llmApiKey, comfyUIHost };
}
