import { useState } from 'react';
import { ImageInputs } from './ImageInputs';
import { H3AVTimeline } from '../../../components/H3AVTimeline';
import { Copy, Download, X } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import { toast } from '../../../stores/toastStore';
import type { LLMLog } from '../../../api/llmLogs';
import type { PromptTab } from '../hooks/useLLMLogsState';
import { ProviderLogo } from '../../../components/ProviderLogo';
import { chapterLabel } from '../columns';

interface LogDetailModalProps {
  log: LLMLog;
  activeTab: PromptTab;
  onTabChange: (tab: PromptTab) => void;
  onClose: () => void;
  formatDate: (date: string) => string;
  getTaskTypeLabel: (type: string | null) => string;
  getDisplayDuration: (log: LLMLog) => string;
  getStatusBadgeConfig: (status: string, errorMessage?: string | null) => { bg: string; text: string; label: string };
}

export function LogDetailModal({ log, activeTab, onTabChange, onClose, formatDate, getTaskTypeLabel, getDisplayDuration, getStatusBadgeConfig }: LogDetailModalProps) {
  const { t } = useTranslation();
  const [formattedView, setFormattedView] = useState<{ logId: string; tab: PromptTab } | null>(null);

  const getRequestInfo = () => {
    if (log.request_info) return log.request_info;

    return JSON.stringify({
      provider: log.provider,
      model: log.model,
      usedProxy: log.used_proxy,
      durationSeconds: log.duration,
      taskType: log.task_type,
      promptTemplateName: log.prompt_template_name,
      novelId: log.novel_id,
      chapterId: log.chapter_id,
      shotId: log.shot_id,
      characterId: log.character_id,
      payload: {
        model: log.model,
        messages: [
          { role: 'system', content: log.system_prompt || '' },
          { role: 'user', content: log.user_prompt || '' },
        ],
      },
    }, null, 2);
  };

  const getActiveContent = () => {
    if (activeTab === 'images') return JSON.stringify(log.image_inputs ?? [], null, 2);
    if (activeTab === 'params') return getRequestInfo();
    if (activeTab === 'system') return log.system_prompt || '';
    if (activeTab === 'user') return log.user_prompt || '';
    return log.response || '';
  };

  const activeContent = getActiveContent();
  const formattedJson = (() => {
    if (activeTab === 'images' || !activeContent) return null;
    try {
      const parsed = JSON.parse(activeContent);
      return parsed !== null && typeof parsed === 'object' ? JSON.stringify(parsed, null, 2) : null;
    } catch {
      return null;
    }
  })();
  const isFormatted = formattedJson !== null && formattedView?.logId === log.id && formattedView.tab === activeTab;
  const activeContentLength = activeContent.length;
  const avTimeline = (() => {
    if (log.task_type !== 'h3_execution_optimizer_prompt') return undefined;
    try { return JSON.parse(log.response || '{}').av_timeline; } catch { return undefined; }
  })();

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
      <div role="dialog" aria-modal="true" aria-label={t('llmLogs.logDetails')} className="bg-white rounded-lg w-full min-w-0 max-w-[1200px] max-h-[92vh] overflow-hidden flex flex-col">
        <div className="flex shrink-0 items-center justify-between px-4 sm:px-6 py-3 border-b">
          <div>
            <h3 className="text-lg font-semibold text-gray-900">{t('llmLogs.logDetails')}</h3>
            <p className="text-sm text-gray-500">{formatDate(log.created_at)}</p>
          </div>
          <button onClick={onClose} aria-label="关闭日志详情" className="p-1 text-gray-400 hover:text-gray-600"><X className="h-5 w-5" /></button>
        </div>
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="min-w-0 flex-shrink-0 space-y-3 px-4 sm:px-6 pt-3">
            <div className="max-h-[24vh] overflow-y-auto space-y-3 break-words">
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
                <span className="text-gray-500">{t('llmLogs.provider')}:</span>
                <span className="inline-flex items-center gap-1.5 font-medium">
                  <ProviderLogo provider={log.provider} label={log.provider} className="h-5 w-5" />
                  {log.provider}
                </span>
                <span className="text-gray-500">{t('llmLogs.model')}:</span><span className="font-medium">{log.model}</span>
                <span className="text-gray-500">{t('llmLogs.task')}:</span><span className="font-medium">{getTaskTypeLabel(log.task_type)}</span>
                {log.task_type && <code className="break-all text-xs text-gray-500">{log.task_type}</code>}
                <span className={`px-2 py-1 text-xs ${getStatusBadgeConfig(log.status, log.error_message).bg} ${getStatusBadgeConfig(log.status, log.error_message).text} rounded-full`}>{getStatusBadgeConfig(log.status, log.error_message).label}</span>
                <span className="text-gray-500">{t('llmLogs.proxy')}:</span><span className="font-medium">{log.used_proxy ? t('llmLogs.yes') : t('llmLogs.no')}</span>
                <span className="text-gray-500">{t('llmLogs.duration')}:</span>
                <span className="font-medium">{getDisplayDuration(log)}</span>
              </div>
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="text-gray-500">{t('llmLogs.promptTemplateName')}:</span>
                <span className="font-medium text-gray-900">{log.prompt_template_name ? t(`promptConfig.templateNames.${log.prompt_template_name}`, { defaultValue: log.prompt_template_name }) : '-'}</span>
              </div>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
                <span><span className="text-gray-500">小说：</span>{log.novel_title || log.novel_id || '—'}</span>
                <span><span className="text-gray-500">章回：</span>{chapterLabel(log.chapter_number, log.chapter_title, log.chapter_id)}</span>
                <span><span className="text-gray-500">Shot：</span>{log.shot_index != null ? `Shot ${log.shot_index}` : log.shot_id || '—'}</span>
              </div>
              {log.error_message && (
                <div className="bg-red-50 border border-red-200 rounded-lg p-4">
                  <h4 className="text-sm font-medium text-red-700 mb-2">{t('llmLogs.errorMessage')}</h4>
                  <pre className="text-sm text-red-600 whitespace-pre-wrap">{log.error_message}</pre>
                </div>
              )}
            </div>
            <div className="flex min-w-0 items-center justify-between gap-2 border-b border-gray-200">
              <div className="flex min-w-0 overflow-x-auto whitespace-nowrap">
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
                {!!log.image_inputs?.length && <button onClick={() => onTabChange('images')}
                  className={`px-4 py-2 text-sm font-medium ${activeTab === 'images' ? 'text-blue-600 border-b-2 border-blue-600 bg-blue-50' : 'text-gray-600 hover:bg-gray-50'}`}>
                  图片输入 ({log.image_inputs.length})
                </button>}
                {log.response && (
                  <button onClick={() => onTabChange('response')}
                    className={`px-4 py-2 text-sm font-medium transition-colors ${activeTab === 'response' ? 'text-blue-600 border-b-2 border-blue-600 bg-blue-50' : 'text-gray-600 hover:bg-gray-50'}`}>
                    {t('llmLogs.llmResponse')}
                  </button>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-1">
                {formattedJson !== null && (
                  <button
                    type="button"
                    onClick={() => setFormattedView(isFormatted ? null : { logId: log.id, tab: activeTab })}
                    className="rounded px-2 py-1 text-sm text-blue-600 hover:bg-blue-50"
                    aria-pressed={isFormatted}
                  >
                    {t(isFormatted ? 'llmLogs.showRawJson' : 'llmLogs.prettyJson')}
                  </button>
                )}
                <button
                  type="button"
                  onClick={handleCopy}
                  disabled={!activeContent}
                  className="p-1.5 text-gray-400 hover:text-blue-600 transition-colors rounded hover:bg-blue-50 disabled:opacity-40 disabled:cursor-not-allowed"
                  title={t('common.copy')}
                  aria-label={t('common.copy')}
                >
                  <Copy className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  onClick={handleDownload}
                  disabled={!activeContent}
                  className="p-1.5 text-gray-400 hover:text-blue-600 transition-colors rounded hover:bg-blue-50 disabled:opacity-40 disabled:cursor-not-allowed"
                  title={t('common.download')}
                  aria-label={t('common.download')}
                >
                  <Download className="h-4 w-4" />
                </button>
              </div>
            </div>
          </div>
          <div data-testid="log-detail-content" className="min-h-0 min-w-0 flex-1 overflow-y-auto px-4 sm:px-6 py-4">
            {activeTab === 'response' && <H3AVTimeline timeline={avTimeline} />}
            {activeTab === 'images' && log.image_inputs?.length ? <ImageInputs images={log.image_inputs} /> : <div className="bg-gray-50 rounded-lg p-4">
              <pre className="text-sm text-gray-700 whitespace-pre-wrap break-words overflow-x-auto">
                {isFormatted ? formattedJson : activeContent || '-'}
              </pre>
            </div>}
          </div>
        </div>
        <div className="flex-shrink-0 px-6 py-3 border-t border-gray-200 bg-white text-xs text-gray-500 text-right">
          {activeTab === 'images' ? `图片输入：${log.image_inputs?.length || 0}` : t('llmLogs.characterCount', { count: activeContentLength })}
        </div>
      </div>
    </div>
  );
}
