import { Copy, Download, Loader2, X } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import { toast } from '../../../stores/toastStore';
import type { LLMLog } from '../../../api/llmLogs';
import type { PromptTab } from '../hooks/useLLMLogsState';
import { LogSpeed } from './LogSpeed';

interface LogDetailModalProps {
  log: LLMLog;
  loading: boolean;
  loadError: string;
  onRetry: () => void;
  activeTab: PromptTab;
  onTabChange: (tab: PromptTab) => void;
  onClose: () => void;
  formatDate: (date: string) => string;
  getTaskTypeLabel: (type: string | null) => string;
  getDisplayDuration: (log: LLMLog) => string;
  getStatusBadgeConfig: (status: string) => { bg: string; text: string; label: string };
}

export function LogDetailModal({ log, loading, loadError, onRetry, activeTab, onTabChange, onClose, formatDate, getTaskTypeLabel, getDisplayDuration, getStatusBadgeConfig }: LogDetailModalProps) {
  const { t } = useTranslation();

  const getRequestInfo = () => {
    if (log.request_info) return log.request_info;
    return '未记录原始请求参数；请分别查看已保存的 System / User Prompt。';
  };

  const getActiveContent = () => {
    if (loading || loadError) return '';
    if (activeTab === 'params') return getRequestInfo();
    if (activeTab === 'system') return log.system_prompt || '';
    if (activeTab === 'user') return log.user_prompt || '';
    return log.response || '';
  };

  const getDisplayContent = () => {
    const content = getActiveContent();
    if ((activeTab !== 'response' && activeTab !== 'params') || !content) return content || '-';

    try {
      return JSON.stringify(JSON.parse(content), null, 2);
    } catch {
      return content;
    }
  };

  const activeContentLength = getActiveContent().length;

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
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4" role="dialog" aria-modal="true" aria-label={t('llmLogs.logDetails')}>
      <div className="bg-white rounded-lg w-full max-w-4xl max-h-[90vh] overflow-hidden flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <div>
            <h3 className="text-lg font-semibold text-gray-900">{t('llmLogs.logDetails')}</h3>
            <p className="text-sm text-gray-500">{formatDate(log.created_at)}</p>
            {log.novel_id&&<a className="text-xs text-blue-700 underline" href={`/asset-debug?${new URLSearchParams({novel_id:log.novel_id,record_kind:'llm_log',record_id:log.id})}`}>来源追踪 · {log.id}</a>}
          </div>
          <button type="button" aria-label="关闭日志详情" onClick={onClose} className="p-1 text-gray-400 hover:text-gray-600"><X className="h-5 w-5" /></button>
        </div>
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          <div className="flex flex-wrap items-center gap-4 text-sm">
            <span className="text-gray-500">{t('llmLogs.provider')}:</span><span className="font-medium">{log.provider}</span>
            <span className="text-gray-500">{t('llmLogs.model')}:</span><span className="font-medium">{log.model}</span>
            <span className="text-gray-500">{t('llmLogs.task')}:</span><span className="font-medium">{getTaskTypeLabel(log.task_type)}</span>
            <span className={`px-2 py-1 text-xs ${getStatusBadgeConfig(log.status).bg} ${getStatusBadgeConfig(log.status).text} rounded-full`}>{getStatusBadgeConfig(log.status).label}</span>
            <span className="text-gray-500">{t('llmLogs.proxy')}:</span><span className="font-medium">{log.used_proxy ? t('llmLogs.yes') : t('llmLogs.no')}</span>
            <span className="text-gray-500">{t('llmLogs.duration')}:</span>
            <span className="font-medium">{getDisplayDuration(log)}</span>
            <span className="text-gray-500">{t('llmLogs.speed')}:</span>
            <LogSpeed log={log} />
          </div>
          <div className="flex items-center gap-2 text-sm">
            <span className="text-gray-500">{t('llmLogs.promptTemplateName')}:</span>
            <span className="font-medium text-gray-900">{log.prompt_template_name || '-'}</span>
          </div>
          {log.execution_metadata?.operation === 'SHOT_CONTRACT_AUTO_REPAIR' && (
            <div className="rounded-lg border border-teal-200 bg-teal-50 p-4 text-sm">
              <h4 className="font-medium text-teal-900">Contract Auto Repair</h4>
              <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
                <div><span className="text-teal-700">Repair Type:</span> <span className="font-medium">{log.execution_metadata.repairType || '-'}</span></div>
                <div><span className="text-teal-700">Attempt:</span> <span className="font-medium">{log.execution_metadata.attempt ?? '-'} / {log.execution_metadata.budget ?? '-'}</span></div>
                <div><span className="text-teal-700">Before:</span> <span className="font-medium">{log.execution_metadata.violationsBefore ?? '-'}</span></div>
                <div><span className="text-teal-700">After:</span> <span className="font-medium">{log.execution_metadata.violationsAfter ?? '-'}</span></div>
                <div><span className="text-teal-700">Resolved:</span> <span className="font-medium">{log.execution_metadata.resolved ?? '-'}</span></div>
                <div><span className="text-teal-700">Introduced:</span> <span className="font-medium">{log.execution_metadata.introduced ?? '-'}</span></div>
                <div className="sm:col-span-2"><span className="text-teal-700">Outcome:</span> <span className="font-semibold">{log.execution_metadata.outcome || '-'}</span></div>
              </div>
              {log.execution_metadata.template && <p className="mt-3 break-all text-xs text-teal-800">
                Template: {log.execution_metadata.template.name || '-'} · {log.execution_metadata.template.version || '-'} · {log.execution_metadata.template.hash || '-'}
              </p>}
              {log.execution_metadata.parentRunId && <p className="mt-1 break-all text-xs text-teal-800">Parent Run: {log.execution_metadata.parentRunId}</p>}
              {log.execution_metadata.beforeHash && <p className="mt-1 break-all text-xs text-teal-800">Plan SHA: {log.execution_metadata.beforeHash} → {log.execution_metadata.afterHash || '-'}</p>}
              {log.execution_metadata.validatorError && <p className="mt-2 whitespace-pre-wrap break-words text-xs text-red-700">{log.execution_metadata.validatorError}</p>}
            </div>
          )}
          {log.error_message && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-4">
              <h4 className="text-sm font-medium text-red-700 mb-2">{t('llmLogs.errorMessage')}</h4>
              <pre className="text-sm text-red-600 whitespace-pre-wrap">{log.error_message}</pre>
            </div>
          )}
          <div className="flex items-center justify-between border-b border-gray-200">
            <div className="flex">
              <button onClick={() => onTabChange('params')}
                className={`px-4 py-2 text-sm font-medium transition-colors ${activeTab === 'params' ? 'text-blue-600 border-b-2 border-blue-600 bg-blue-50' : 'text-gray-600 hover:bg-gray-50'}`}>
                LLM参数
              </button>
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
          {loading ? <div role="status" className="flex items-center gap-2 rounded-lg bg-gray-50 p-4 text-sm text-gray-600"><Loader2 className="h-4 w-4 animate-spin"/>正在加载完整日志…</div>
          : loadError ? <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700"><p className="break-all">{loadError}</p><p className="mt-1">完整内容尚未加载。</p><button type="button" className="btn-secondary mt-3" onClick={onRetry}>重新加载完整日志</button></div>
          : <div className="bg-gray-50 rounded-lg p-4">
            <pre data-testid="llm-log-content" className="text-sm text-gray-700 whitespace-pre-wrap break-words overflow-x-auto">
              {getDisplayContent()}
            </pre>
          </div>}
        </div>
        <div className="flex-shrink-0 px-6 py-3 border-t border-gray-200 bg-white text-xs text-gray-500 text-right">
          {loading ? '正在加载完整内容…' : loadError ? '完整日志未加载' : t('llmLogs.characterCount', { count: activeContentLength })}
        </div>
      </div>
    </div>
  );
}
