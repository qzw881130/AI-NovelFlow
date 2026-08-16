import { ScrollText, ChevronLeft, ChevronRight, Filter, Eye, RefreshCw } from 'lucide-react';
import { useTranslation } from '../../stores/i18nStore';
import type { LLMLog } from '../../api/llmLogs';
import { useLLMLogsState } from './hooks/useLLMLogsState';
import { LogDetailModal } from './components/LogDetailModal';

function LogTableRow({ log, onView, formatDate, truncateText, getTaskTypeLabel, getStatusBadgeConfig }: {
  log: LLMLog; onView: () => void; formatDate: (d: string) => string;
  truncateText: (t: string, m?: number) => string; getTaskTypeLabel: (t: string) => string;
  getStatusBadgeConfig: (s: string) => { bg: string; text: string; label: string };
}) {
  const { t } = useTranslation();
  const badge = getStatusBadgeConfig(log.status);
  return (
    <tr className="hover:bg-gray-50">
      <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-600">{formatDate(log.created_at)}</td>
      <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-900">{log.provider}</td>
      <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-600">{log.model}</td>
      <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-600">{getTaskTypeLabel(log.task_type)}</td>
      <td className="px-4 py-3 whitespace-nowrap"><span className={`px-2 py-1 text-xs ${badge.bg} ${badge.text} rounded-full`}>{badge.label}</span></td>
      <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-600">{log.used_proxy ? t('llmLogs.yes') : t('llmLogs.no')}</td>
      <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-600">{log.duration ? `${log.duration.toFixed(2)}s` : '-'}</td>
      <td className="px-4 py-3 text-sm text-gray-600 max-w-[150px]">
        <div className="truncate" title={log.user_prompt}>{truncateText(log.user_prompt, 50)}</div>
      </td>
      <td className="px-4 py-3 whitespace-nowrap text-sm">
        <button onClick={onView} className="text-primary-600 hover:text-primary-700 inline-flex items-center gap-1">
          <Eye className="h-4 w-4" />{t('llmLogs.viewDetails')}
        </button>
      </td>
    </tr>
  );
}

export default function LLMLogs() {
  const { t } = useTranslation();
  const state = useLLMLogsState();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">{t('llmLogs.title')}</h1>
        <p className="mt-1 text-sm text-gray-500">{t('llmLogs.subtitle')}</p>
      </div>

      {/* Filters */}
      <div className="card">
        <div className="flex items-center gap-2 mb-4">
          <Filter className="h-4 w-4 text-gray-500" />
          <span className="text-sm font-medium text-gray-700">{t('llmLogs.filterConditions')}</span>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { key: 'provider', label: t('llmLogs.llmProvider'), options: state.filterOptions.providers },
            { key: 'model', label: t('llmLogs.model'), options: state.filterOptions.models },
            { key: 'task_type', label: t('llmLogs.taskType'), options: state.filterOptions.task_types, useLabel: true },
            { key: 'status', label: t('common.status'), options: ['success', 'error'], isStatus: true }
          ].map(({ key, label, options, useLabel, isStatus }) => (
            <div key={key}>
              <label className="block text-xs text-gray-500 mb-1">{label}</label>
              <select value={state.filters[key as keyof typeof state.filters]}
                onChange={(e) => state.handleFilterChange(key, e.target.value)} className="input-field text-sm w-full">
                <option value="">{t('llmLogs.all')}</option>
                {isStatus ? (
                  [<option key="success" value="success">{t('common.success')}</option>, <option key="error" value="error">{t('common.failed')}</option>]
                ) : options?.map((o: string) => (
                  <option key={o} value={o}>{useLabel ? state.getTaskTypeLabel(o) : o}</option>
                ))}
              </select>
            </div>
          ))}
        </div>
        <div className="flex items-center gap-2 mt-4">
          <button onClick={state.applyFilters} className="btn-primary text-sm">{t('llmLogs.applyFilter')}</button>
          <button onClick={state.resetFilters} className="btn-secondary text-sm">{t('llmLogs.reset')}</button>
          <button onClick={state.fetchLogs} className="inline-flex items-center gap-1 px-3 py-1.5 text-sm text-gray-600 hover:text-gray-700 hover:bg-gray-100 rounded-md transition-colors">
            <RefreshCw className="h-4 w-4" />{t('llmLogs.refresh')}
          </button>
          <div className="ml-auto flex items-center gap-2">
            <label className="text-sm text-gray-600 whitespace-nowrap">{t('llmLogs.autoRefresh')}</label>
            <select
              value={state.autoRefreshInterval}
              onChange={(e) => state.setAutoRefreshInterval(Number(e.target.value))}
              className="input-field text-sm w-32"
            >
              <option value={0}>{t('llmLogs.autoRefreshOff')}</option>
              <option value={5000}>{t('llmLogs.autoRefresh5s')}</option>
              <option value={20000}>{t('llmLogs.autoRefresh20s')}</option>
              <option value={60000}>{t('llmLogs.autoRefresh1m')}</option>
            </select>
          </div>
        </div>
      </div>

      {/* Logs Table */}
      <div className="card overflow-hidden">
        {state.loading ? (
          <div className="flex justify-center py-12"><div className="animate-spin h-6 w-6 border-2 border-primary-600 border-t-transparent rounded-full" /></div>
        ) : state.logs.length === 0 ? (
          <div className="text-center py-12 text-gray-500">
            <ScrollText className="h-12 w-12 mx-auto mb-3 text-gray-300" />
            <p>{t('llmLogs.noLogs')}</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  {[
                    t('llmLogs.timestamp'), t('llmLogs.llmProvider'), t('llmLogs.model'), t('llmLogs.taskType'),
                    t('common.status'), t('llmLogs.proxy'), t('llmLogs.duration'), t('llmLogs.promptPreview'), t('common.actions')
                  ].map((h, i) => (
                    <th key={i} className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {state.logs.map((log) => (
                  <LogTableRow key={log.id} log={log} onView={() => state.setSelectedLog(log)}
                    formatDate={state.formatDate} truncateText={state.truncateText}
                    getTaskTypeLabel={state.getTaskTypeLabel} getStatusBadgeConfig={state.getStatusBadgeConfig} />
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination */}
        {state.pagination.total_pages > 0 && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-gray-200">
            <div className="text-sm text-gray-500">
              {t('llmLogs.pagination', { total: state.pagination.total, page: state.pagination.page, totalPages: state.pagination.total_pages })}
            </div>
            <div className="flex items-center gap-2">
              <button onClick={() => state.setPagination(prev => ({ ...prev, page: prev.page - 1 }))}
                disabled={state.pagination.page <= 1} className="p-2 text-gray-600 hover:bg-gray-100 rounded disabled:opacity-50 disabled:cursor-not-allowed">
                <ChevronLeft className="h-4 w-4" />
              </button>
              <button onClick={() => state.setPagination(prev => ({ ...prev, page: prev.page + 1 }))}
                disabled={state.pagination.page >= state.pagination.total_pages} className="p-2 text-gray-600 hover:bg-gray-100 rounded disabled:opacity-50 disabled:cursor-not-allowed">
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}
      </div>

      {state.selectedLog && (
        <LogDetailModal log={state.selectedLog} activeTab={state.activePromptTab} onTabChange={state.setActivePromptTab}
          onClose={state.closeModal} formatDate={state.formatDate} getTaskTypeLabel={state.getTaskTypeLabel} getStatusBadgeConfig={state.getStatusBadgeConfig} />
      )}
    </div>
  );
}
