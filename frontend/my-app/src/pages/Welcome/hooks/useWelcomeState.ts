import { useEffect } from 'react';
import { useConfigStore } from '../../../stores/configStore';
import { useTranslation } from '../../../stores/i18nStore';

export function useWelcomeState() {
  const { t } = useTranslation();
  const { checkConnection, connectionStatus, isLoading, llmProvider, llmModel, comfyUIHost } = useConfigStore();

  const providerName = t(`systemSettings.providers.${llmProvider}`);
  const modelName = llmModel;
  // 基于连接状态判断是否已配置（API Key 不暴露给前端，所以不能依赖 llmApiKey）
  const isConfigured = connectionStatus.llm === true && connectionStatus.comfyui === true;

  const handleCheck = () => checkConnection();

  useEffect(() => { void handleCheck(); }, []);

  return { status: connectionStatus, checking: isLoading, providerName, modelName, isConfigured, handleCheck, comfyUIHost };
}
