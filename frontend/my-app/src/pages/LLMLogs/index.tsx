import { ScrollText, ChevronLeft, ChevronRight, Filter, Eye, RefreshCw, BarChart3, X, Loader2 } from 'lucide-react';
import { useTranslation } from '../../stores/i18nStore';
import type { LLMLog } from '../../api/llmLogs';
import { useLLMLogsState } from './hooks/useLLMLogsState';
import { LogDetailModal } from './components/LogDetailModal';

function StatsModal({ state }: { state: ReturnType<typeof useLLMLogsState> }) {
  const maxCount = Math.max(1, ...(state.statsData?.items || []).map(item => item.count));
  const visibleTickEvery = state.statsGroupBy === 'minute' ? 10 : state.statsGroupBy === 'hour' ? 4 : 1;
  const rangeOptions = state.statsGroupBy === 'day'
    ? [{ value: 7, label: '最近 7 天' }, { value: 31, label: '最近 31 天' }]
    : state.statsGroupBy === 'hour'
      ? [{ value: 1, label: '最近 1 天' }, { value: 3, label: '最近 3 天' }]
      : [{ value: 1, label: '最近 1 小时' }];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={state.closeStatsModal}>
      <div className="w-full max-w-5xl rounded-xl bg-white shadow-2xl" onClick={(event) => event.stopPropagation()}>
        <div className="flex items-center justify-between gap-3 border-b border-gray-200 px-5 py-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">LLM 调用统计</h2>
            <p className="text-sm text-gray-500">按当前筛选条件统计调用次数</p>
          </div>
          <button type="button" onClick={state.closeStatsModal} className="rounded-lg p-2 text-gray-400 hover:bg-gray-100 hover:text-gray-600">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="space-y-4 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2">
              {(['day', 'hour', 'minute'] as const).map(groupBy => (
                <button
                  key={groupBy}
                  type="button"
                  onClick={() => state.changeStatsGroupBy(groupBy)}
                  className={`rounded-lg px-3 py-1.5 text-sm transition-colors ${state.statsGroupBy === groupBy ? 'bg-primary-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'}`}
                >
                  {groupBy === 'day' ? '按天' : groupBy === 'hour' ? '按小时' : '按分钟'}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-2">
              <select
                value={state.statsRangeValue}
                onChange={(event) => state.changeStatsRangeValue(Number(event.target.value))}
                className="input-field h-9 w-36 text-sm"
              >
                {rangeOptions.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
              <button type="button" onClick={() => state.fetchStats()} className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50">
                <RefreshCw className="h-4 w-4" />刷新
              </button>
            </div>
          </div>

          <div className="rounded-xl bg-gray-50 p-4">
            <div className="mb-3 flex items-center justify-between">
              <div className="text-sm font-medium text-gray-900">调用次数 {state.statsData ? state.statsData.total : '-'}</div>
              <div className="text-xs text-gray-500">最高单桶 {state.statsData ? maxCount : '-'}</div>
            </div>
            {state.statsLoading ? (
              <div className="flex h-80 items-center justify-center text-gray-500">
                <Loader2 className="mr-2 h-5 w-5 animate-spin" />加载统计中...
              </div>
            ) : !state.statsData || state.statsData.items.length === 0 ? (
              <div className="flex h-80 items-center justify-center text-gray-500">暂无统计数据</div>
            ) : (
              <div className="h-80">
                <div className="flex h-64 items-end gap-1 border-b border-gray-300 px-1">
                  {state.statsData.items.map((item, index) => (
                    <div key={item.key} className="group relative flex min-w-0 flex-1 flex-col items-center justify-end">
                      <div className="absolute bottom-full mb-2 hidden rounded bg-gray-900 px-2 py-1 text-xs text-white shadow group-hover:block whitespace-nowrap">
                        {item.key} · {item.count} 次
                      </div>
                      <div
                        className={`w-full max-w-8 rounded-t ${item.count > 0 ? 'bg-orange-500' : 'bg-gray-200'}`}
                        style={{ height: `${Math.max(item.count > 0 ? 8 : 2, (item.count / maxCount) * 220)}px` }}
                      />
                    </div>
                  ))}
                </div>
                <div className="mt-2 flex gap-1 px-1 text-[11px] text-gray-500">
                  {state.statsData.items.map((item, index) => (
                    <div key={item.key} className="min-w-0 flex-1 text-center">
                      {index % visibleTickEvery === 0 || index === state.statsData!.items.length - 1 ? <span className="truncate block">{item.label}</span> : null}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function LogTableRow({ log, onView, formatDate, truncateText, getTaskTypeLabel, getStatusBadgeConfig }: {
  log: LLMLog; onView: () => void; formatDate: (d: string) => string;
  truncateText: (t: string, m?: number) => string; getTaskTypeLabel: (t: string | null) => string;
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
      <td className="px-4 py-3 text-sm text-gray-600 max-w-[180px]">
        <div className="truncate" title={log.prompt_template_name || ''}>{log.prompt_template_name || '-'}</div>
      </td>
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
        <div className="flex items-center justify-between gap-4 mb-4">
          <div className="flex items-center gap-2">
            <Filter className="h-4 w-4 text-gray-500" />
            <span className="text-sm font-medium text-gray-700">{t('llmLogs.filterConditions')}</span>
          </div>
          <div className="flex flex-nowrap items-center gap-2 flex-shrink-0">
            <label className="text-sm text-gray-600 whitespace-nowrap">{t('llmLogs.autoRefresh')}</label>
            <select
              value={state.autoRefreshInterval}
              onChange={(e) => state.setAutoRefreshInterval(Number(e.target.value))}
              className="input-field text-sm w-32 whitespace-nowrap flex-shrink-0"
            >
              <option value={0}>{t('llmLogs.autoRefreshOff')}</option>
              <option value={5000}>{t('llmLogs.autoRefresh5s')}</option>
              <option value={20000}>{t('llmLogs.autoRefresh20s')}</option>
              <option value={60000}>{t('llmLogs.autoRefresh1m')}</option>
            </select>
          </div>
        </div>
        <div className="flex flex-nowrap gap-4 overflow-x-auto pb-2">
          <div className="min-w-[220px] flex-shrink-0">
            <label className="block text-xs text-gray-500 mb-1">{t('llmLogs.llmProvider')}</label>
            <select value={state.filters.provider} onChange={(e) => state.handleFilterChange('provider', e.target.value)} className="input-field text-sm w-full truncate whitespace-nowrap">
              <option value="">{t('llmLogs.all')}</option>
              {state.filterOptions.providers.map(o => <option key={o} value={o}>{o}</option>)}
            </select>
          </div>
          <div className="min-w-[260px] flex-shrink-0">
            <label className="block text-xs text-gray-500 mb-1">{t('llmLogs.model')}</label>
            <select value={state.filters.model} onChange={(e) => state.handleFilterChange('model', e.target.value)} className="input-field text-sm w-full truncate whitespace-nowrap">
              <option value="">{t('llmLogs.all')}</option>
              {state.filterOptions.models.map(o => <option key={o} value={o}>{o}</option>)}
            </select>
          </div>
          <div className="min-w-[220px] flex-shrink-0">
            <label className="block text-xs text-gray-500 mb-1">{t('llmLogs.category')}</label>
            <select value={state.filters.category} onChange={(e) => state.handleFilterChange('category', e.target.value)} className="input-field text-sm w-full truncate whitespace-nowrap">
              <option value="">{t('llmLogs.all')}</option>
              {state.taskCategoryOptions.map(o => <option key={o.value} value={o.value}>{t(o.labelKey)}</option>)}
            </select>
          </div>
          <div className="min-w-[300px] flex-shrink-0">
            <label className="block text-xs text-gray-500 mb-1">{t('llmLogs.taskType')}</label>
            <select value={state.filters.task_type} onChange={(e) => state.handleFilterChange('task_type', e.target.value)} className="input-field text-sm w-full truncate whitespace-nowrap">
              <option value="">{t('llmLogs.all')}</option>
              {state.taskTypeOptions.map(o => <option key={o} value={o}>{state.getTaskTypeNameLabel(o)}</option>)}
            </select>
          </div>
          <div className="min-w-[180px] flex-shrink-0">
            <label className="block text-xs text-gray-500 mb-1">{t('common.status')}</label>
            <select value={state.filters.status} onChange={(e) => state.handleFilterChange('status', e.target.value)} className="input-field text-sm w-full truncate whitespace-nowrap">
              <option value="">{t('llmLogs.all')}</option>
              <option value="pending">{t('llmLogs.pending')}</option>
              <option value="success">{t('common.success')}</option>
              <option value="error">{t('common.failed')}</option>
            </select>
          </div>
        </div>
        <div className="flex flex-nowrap items-center justify-end gap-2 mt-4 overflow-x-auto pb-1">
          <button onClick={state.applyFilters} className="btn-primary text-sm whitespace-nowrap flex-shrink-0">{t('llmLogs.applyFilter')}</button>
          <button onClick={state.resetFilters} className="btn-secondary text-sm whitespace-nowrap flex-shrink-0">{t('llmLogs.reset')}</button>
          <button onClick={() => state.fetchLogs()} className="inline-flex items-center gap-1 px-3 py-1.5 text-sm text-gray-600 hover:text-gray-700 hover:bg-gray-100 rounded-md transition-colors whitespace-nowrap flex-shrink-0">
            <RefreshCw className="h-4 w-4" />{t('llmLogs.refresh')}
          </button>
        </div>
      </div>

      {/* Logs Table */}
      <div className="card overflow-hidden">
        <div className="flex items-center justify-end border-b border-gray-100 px-4 py-3">
          <button
            type="button"
            onClick={state.openStatsModal}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
          >
            <BarChart3 className="h-4 w-4" />查看调用统计
          </button>
        </div>
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
                    t('llmLogs.promptTemplateName'), t('common.status'), t('llmLogs.proxy'), t('llmLogs.duration'), t('llmLogs.promptPreview'), t('common.actions')
                  ].map((h, i) => (
                    <th key={i} className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {state.logs.map((log) => (
                  <LogTableRow key={log.id} log={log} onView={() => state.openLogDetail(log)}
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
      {state.showStatsModal && <StatsModal state={state} />}
    </div>
  );
}
