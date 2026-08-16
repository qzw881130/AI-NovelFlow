import { Copy, Download, X } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import { toast } from '../../../stores/toastStore';
import type { LLMLog } from '../../../api/llmLogs';
import type { PromptTab } from '../hooks/useLLMLogsState';

interface LogDetailModalProps {
  log: LLMLog;
  activeTab: PromptTab;
  onTabChange: (tab: PromptTab) => void;
  onClose: () => void;
  formatDate: (date: string) => string;
  getTaskTypeLabel: (type: string) => string;
  getStatusBadgeConfig: (status: string) => { bg: string; text: string; label: string };
}

export function LogDetailModal({ log, activeTab, onTabChange, onClose, formatDate, getTaskTypeLabel, getStatusBadgeConfig }: LogDetailModalProps) {
  const { t } = useTranslation();

  const getActiveContent = () => {
    if (activeTab === 'system') return log.system_prompt || '';
    if (activeTab === 'user') return log.user_prompt || '';
    return log.response || '';
  };

  const handleCopy = async () => {
    const content = getActiveContent();
    if (!content) return;
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(content);
      } else {
        const textarea = document.createElement('textarea');
        textarea.value = content;
        textarea.style.position = 'fixed';
        textarea.style.left = '-9999px';
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
      }
      toast.success(t('common.copied'));
    } catch (error) {
      console.error('复制日志内容失败:', error);
      toast.error(t('common.copyFailed'));
    }
  };

  const handleDownload = () => {
    const content = getActiveContent();
    if (!content) return;
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    const safeTaskType = (log.task_type || 'llm-log').replace(/[\\/:*?"<>|\s]+/g, '_');
    const safeTab = activeTab.replace(/[\\/:*?"<>|\s]+/g, '_');
    const safeTime = (log.created_at || '').replace(/[\\/:*?"<>|\s]+/g, '_');
    link.href = url;
    link.download = `${safeTaskType}_${safeTab}_${safeTime || log.id}.txt`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg w-full max-w-4xl max-h-[90vh] overflow-hidden flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <div>
            <h3 className="text-lg font-semibold text-gray-900">{t('llmLogs.logDetails')}</h3>
            <p className="text-sm text-gray-500">{formatDate(log.created_at)}</p>
          </div>
          <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-600"><X className="h-5 w-5" /></button>
        </div>
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          <div className="flex items-center gap-4 text-sm">
            <span className="text-gray-500">{t('llmLogs.provider')}:</span><span className="font-medium">{log.provider}</span>
            <span className="text-gray-500">{t('llmLogs.model')}:</span><span className="font-medium">{log.model}</span>
            <span className="text-gray-500">{t('llmLogs.task')}:</span><span className="font-medium">{getTaskTypeLabel(log.task_type)}</span>
            <span className={`px-2 py-1 text-xs ${getStatusBadgeConfig(log.status).bg} ${getStatusBadgeConfig(log.status).text} rounded-full`}>{getStatusBadgeConfig(log.status).label}</span>
            <span className="text-gray-500">{t('llmLogs.proxy')}:</span><span className="font-medium">{log.used_proxy ? t('llmLogs.yes') : t('llmLogs.no')}</span>
            <span className="text-gray-500">{t('llmLogs.duration')}:</span>
            <span className="font-medium">{log.duration ? `${log.duration.toFixed(2)}s` : '-'}</span>
          </div>
          {log.error_message && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-4">
              <h4 className="text-sm font-medium text-red-700 mb-2">{t('llmLogs.errorMessage')}</h4>
              <pre className="text-sm text-red-600 whitespace-pre-wrap">{log.error_message}</pre>
            </div>
          )}
          <div className="flex items-center justify-between border-b border-gray-200">
            <div className="flex">
              <button onClick={() => onTabChange('system')}
                className={`px-4 py-2 text-sm font-medium transition-colors ${activeTab === 'system' ? 'text-blue-600 border-b-2 border-blue-600 bg-blue-50' : 'text-gray-600 hover:bg-gray-50'}`}>
                System Prompt
              </button>
              <button onClick={() => onTabChange('user')}
                className={`px-4 py-2 text-sm font-medium transition-colors ${activeTab === 'user' ? 'text-blue-600 border-b-2 border-blue-600 bg-blue-50' : 'text-gray-600 hover:bg-gray-50'}`}>
                User Prompt
              </button>
              {log.response && (
                <button onClick={() => onTabChange('response')}
                  className={`px-4 py-2 text-sm font-medium transition-colors ${activeTab === 'response' ? 'text-blue-600 border-b-2 border-blue-600 bg-blue-50' : 'text-gray-600 hover:bg-gray-50'}`}>
                  {t('llmLogs.llmResponse')}
                </button>
              )}
            </div>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={handleCopy}
                disabled={!getActiveContent()}
                className="p-1.5 text-gray-400 hover:text-blue-600 transition-colors rounded hover:bg-blue-50 disabled:opacity-40 disabled:cursor-not-allowed"
                title={t('common.copy')}
                aria-label={t('common.copy')}
              >
                <Copy className="h-4 w-4" />
              </button>
              <button
                type="button"
                onClick={handleDownload}
                disabled={!getActiveContent()}
                className="p-1.5 text-gray-400 hover:text-blue-600 transition-colors rounded hover:bg-blue-50 disabled:opacity-40 disabled:cursor-not-allowed"
                title={t('common.download')}
                aria-label={t('common.download')}
              >
                <Download className="h-4 w-4" />
              </button>
            </div>
          </div>
          <div className="bg-gray-50 rounded-lg p-4">
            {activeTab === 'system' && <pre className="text-sm text-gray-700 whitespace-pre-wrap overflow-x-auto">{log.system_prompt || '-'}</pre>}
            {activeTab === 'user' && <pre className="text-sm text-gray-700 whitespace-pre-wrap overflow-x-auto">{log.user_prompt}</pre>}
            {activeTab === 'response' && log.response && <pre className="text-sm text-gray-700 whitespace-pre-wrap overflow-x-auto max-h-96">{log.response}</pre>}
          </div>
        </div>
      </div>
    </div>
  );
}
