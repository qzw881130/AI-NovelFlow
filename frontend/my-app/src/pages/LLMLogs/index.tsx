import { useEffect, useRef, useState } from 'react';
import { ScrollText, ChevronLeft, ChevronRight, Filter, Eye, RefreshCw, BarChart3, X, Loader2, Download, Square, Columns } from 'lucide-react';
import { useTranslation } from '../../stores/i18nStore';
import type { LLMLog } from '../../api/llmLogs';
import { useLLMLogsState } from './hooks/useLLMLogsState';
import { LogDetailModal } from './components/LogDetailModal';
import { LogSpeed } from './components/LogSpeed';
import { ProviderLogo } from '../../components/ProviderLogo';
import { llmLogsApi } from '../../api/llmLogs';
import { toast } from '../../stores/toastStore';
import { getTerminableLogIds } from './selection';
import { LOG_COLUMNS_STORAGE_KEY, chapterLabel, defaultLogColumns, logColumns, normalizeLogColumns, requiredLogColumns } from './columns';
import type { LogColumnKey } from './columns';
import { TokenUsageHierarchyModal } from './components/TokenUsageHierarchyModal';

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
                className="h-9 w-32 rounded-lg border border-gray-300 bg-white px-3 py-0 text-sm leading-9 text-gray-700 shadow-sm focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-500"
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
                <div className="flex h-64 items-end gap-1 border-b border-gray-300 px-1 pt-6">
                  {state.statsData.items.map((item, index) => (
                    <div key={item.key} className="group relative flex min-w-0 flex-1 flex-col items-center justify-end">
                      <div className="absolute bottom-full mb-2 hidden rounded bg-gray-900 px-2 py-1 text-xs text-white shadow group-hover:block whitespace-nowrap">
                        {item.key} · {item.count} 次
                      </div>
                      {item.count > 0 && (
                        <div className="mb-1 text-[10px] font-medium leading-none text-gray-600">
                          {item.count}
                        </div>
                      )}
                      <div
                        className={`w-full max-w-8 rounded-t ${item.count > 0 ? 'bg-orange-500' : 'bg-gray-200'}`}
                        style={{ height: `${Math.max(item.count > 0 ? 8 : 2, (item.count / maxCount) * 196)}px` }}
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

const formatTokenCount = (value: number) => new Intl.NumberFormat('zh-CN').format(value);

function TokenStatsModal({ state }: { state: ReturnType<typeof useLLMLogsState> }) {
  const items = state.tokenStatsData?.items || [];
  const maxTokens = Math.max(1, ...items.flatMap(item => [item.input_tokens, item.output_tokens]));
  const visibleTickEvery = state.tokenStatsGroupBy === 'minute' ? 10 : state.tokenStatsGroupBy === 'hour' ? 4 : 1;
  const rangeOptions = state.tokenStatsGroupBy === 'day'
    ? [{ value: 7, label: '最近 7 天' }, { value: 31, label: '最近 31 天' }]
    : state.tokenStatsGroupBy === 'hour'
      ? [{ value: 1, label: '最近 1 天' }, { value: 3, label: '最近 3 天' }]
      : [{ value: 1, label: '最近 1 小时' }];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={state.closeTokenStatsModal}>
      <div className="w-full max-w-5xl rounded-xl bg-white shadow-2xl" onClick={(event) => event.stopPropagation()}>
        <div className="flex items-center justify-between gap-3 border-b border-gray-200 px-5 py-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Token 消耗</h2>
            <p className="text-sm text-gray-500">按当前筛选条件统计输入和输出 Token</p>
          </div>
          <button type="button" onClick={state.closeTokenStatsModal} className="rounded-lg p-2 text-gray-400 hover:bg-gray-100 hover:text-gray-600">
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
                  onClick={() => state.changeTokenStatsGroupBy(groupBy)}
                  className={`rounded-lg px-3 py-1.5 text-sm transition-colors ${state.tokenStatsGroupBy === groupBy ? 'bg-primary-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'}`}
                >
                  {groupBy === 'day' ? '按天' : groupBy === 'hour' ? '按小时' : '按分钟'}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-2">
              <select
                value={state.tokenStatsRangeValue}
                onChange={(event) => state.changeTokenStatsRangeValue(Number(event.target.value))}
                className="h-9 w-32 rounded-lg border border-gray-300 bg-white px-3 py-0 text-sm leading-9 text-gray-700 shadow-sm focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-500"
              >
                {rangeOptions.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
              <button type="button" onClick={() => state.fetchTokenStats()} className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50">
                <RefreshCw className="h-4 w-4" />刷新
              </button>
            </div>
          </div>

          <div className="rounded-xl bg-gray-50 p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap gap-4 text-sm font-medium">
                <span className="inline-flex items-center gap-1.5 text-blue-700"><span className="h-2.5 w-2.5 rounded-sm bg-blue-500" />输入 {state.tokenStatsData ? formatTokenCount(state.tokenStatsData.total_input_tokens) : '-'}</span>
                <span className="inline-flex items-center gap-1.5 text-violet-700"><span className="h-2.5 w-2.5 rounded-sm bg-violet-500" />输出 {state.tokenStatsData ? formatTokenCount(state.tokenStatsData.total_output_tokens) : '-'}</span>
                <span className="inline-flex items-center gap-1.5 text-gray-800"><span className="h-2.5 w-2.5 rounded-sm bg-gray-700" />总计 {state.tokenStatsData ? formatTokenCount(state.tokenStatsData.total_input_tokens + state.tokenStatsData.total_output_tokens) : '-'}</span>
              </div>
              <div className="text-xs text-gray-500">单位：Token</div>
            </div>
            {state.tokenStatsLoading ? (
              <div className="flex h-80 items-center justify-center text-gray-500">
                <Loader2 className="mr-2 h-5 w-5 animate-spin" />加载 Token 消耗中...
              </div>
            ) : !state.tokenStatsData || items.every(item => item.input_tokens === 0 && item.output_tokens === 0) ? (
              <div className="flex h-80 items-center justify-center text-gray-500">暂无 Token 消耗数据</div>
            ) : (
              <div className="h-80">
                <div className="flex h-64 items-end gap-1 border-b border-gray-300 px-1 pt-6">
                  {items.map((item) => (
                    <div key={item.key} className="group relative flex min-w-0 flex-1 items-end justify-center gap-px">
                      <div className="absolute bottom-full z-10 mb-2 hidden rounded bg-gray-900 px-2 py-1 text-xs text-white shadow group-hover:block whitespace-nowrap">
                        {item.key} · 输入 {formatTokenCount(item.input_tokens)} · 输出 {formatTokenCount(item.output_tokens)} · 总计 {formatTokenCount(item.input_tokens + item.output_tokens)}
                      </div>
                      <div
                        className="w-[45%] max-w-4 rounded-t bg-blue-500"
                        style={{ height: `${Math.max(item.input_tokens > 0 ? 4 : 1, (item.input_tokens / maxTokens) * 220)}px` }}
                      />
                      <div
                        className="w-[45%] max-w-4 rounded-t bg-violet-500"
                        style={{ height: `${Math.max(item.output_tokens > 0 ? 4 : 1, (item.output_tokens / maxTokens) * 220)}px` }}
                      />
                    </div>
                  ))}
                </div>
                <div className="mt-2 flex gap-1 px-1 text-[11px] text-gray-500">
                  {items.map((item, index) => (
                    <div key={item.key} className="min-w-0 flex-1 text-center">
                      {index % visibleTickEvery === 0 || index === items.length - 1 ? <span className="truncate block">{item.label}</span> : null}
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

function LogTableRow({ log, visibleColumns, selected, onSelectionStart, onSelectionEnter, onView, formatDate, truncateText, getTaskTypeLabel, getDisplayDuration, getStatusBadgeConfig }: {
  log: LLMLog; onView: () => void; formatDate: (d: string) => string;
  visibleColumns: LogColumnKey[];
  selected: boolean;
  onSelectionStart: (id: string) => void;
  onSelectionEnter: (id: string) => void;
  truncateText: (t: string, m?: number) => string; getTaskTypeLabel: (t: string | null) => string;
  getDisplayDuration: (log: LLMLog) => string;
  getStatusBadgeConfig: (s: string, errorMessage?: string | null) => { bg: string; text: string; label: string };
}) {
  const { t } = useTranslation();
  const badge = getStatusBadgeConfig(log.status, log.error_message);
  const renderCell = (key: LogColumnKey) => {
    switch (key) {
      case 'time': return formatDate(log.created_at);
      case 'provider': return <span className="inline-flex items-center" title={log.provider}><ProviderLogo provider={log.provider} label={log.provider} className="h-6 w-6" /></span>;
      case 'model': return log.model;
      case 'task_type': return getTaskTypeLabel(log.task_type);
      case 'novel': return <span title={log.novel_title || log.novel_id || ''}>{log.novel_title || log.novel_id || '—'}</span>;
      case 'chapter': return <span title={log.chapter_title || log.chapter_id || ''}>{chapterLabel(log.chapter_number, log.chapter_title, log.chapter_id)}</span>;
      case 'shot': return log.shot_index != null ? `Shot ${log.shot_index}` : log.shot_id || '—';
      case 'template': return <div className="max-w-[180px] truncate" title={log.prompt_template_name || ''}>{log.prompt_template_name ? t(`promptConfig.templateNames.${log.prompt_template_name}`, { defaultValue: log.prompt_template_name }) : '—'}</div>;
      case 'status': return <span className={`rounded-full px-2 py-1 text-xs ${badge.bg} ${badge.text}`}>{badge.label}</span>;
      case 'proxy': return log.used_proxy ? t('llmLogs.yes') : t('llmLogs.no');
      case 'duration': return getDisplayDuration(log);
      case 'speed': return <LogSpeed log={log} />;
      case 'input_tokens': return log.metrics?.input_tokens == null ? '—' : formatTokenCount(log.metrics.input_tokens);
      case 'output_tokens': return log.metrics?.output_tokens == null ? '—' : formatTokenCount(log.metrics.output_tokens);
      case 'total_tokens': return log.metrics?.total_tokens == null
        ? (log.metrics?.input_tokens != null && log.metrics?.output_tokens != null ? formatTokenCount(log.metrics.input_tokens + log.metrics.output_tokens) : '—')
        : formatTokenCount(log.metrics.total_tokens);
      case 'prompt': return <div className="max-w-[150px] truncate" title={log.user_prompt}>{truncateText(log.user_prompt, 50)}</div>;
    }
  };
  return (
    <tr
      className={selected ? 'bg-blue-50/60 hover:bg-blue-50' : 'hover:bg-gray-50'}
      onPointerEnter={() => onSelectionEnter(log.id)}
    >
      <td
        className="w-14 cursor-pointer select-none px-4 py-3 text-center"
        onPointerDown={(event) => {
          if (event.button !== 0) return;
          event.preventDefault();
          onSelectionStart(log.id);
        }}
        title="按住鼠标并拖过其他行可连续选择"
      >
        <input type="checkbox" checked={selected} readOnly tabIndex={-1} className="pointer-events-none h-4 w-4 rounded border-gray-300 text-primary-600" aria-label={`选择日志 ${log.id}`} />
      </td>
      {visibleColumns.map(key => {
        const textWidth = key === 'task_type' ? 'max-w-[260px]' : key === 'chapter' ? 'max-w-[200px]' : key === 'novel' ? 'max-w-[160px]' : key === 'model' || key === 'shot' ? 'max-w-[180px]' : '';
        return <td key={key} className="whitespace-nowrap px-4 py-3 text-sm text-gray-600">
          {textWidth ? <div className={'truncate ' + textWidth} title={key === 'task_type' ? getTaskTypeLabel(log.task_type) : undefined}>{renderCell(key)}</div> : renderCell(key)}
        </td>;
      })}
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
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [isDownloading, setIsDownloading] = useState(false);
  const [isTerminating, setIsTerminating] = useState(false);
  const [showHierarchy, setShowHierarchy] = useState(false);
  const [showColumnControl, setShowColumnControl] = useState(false);
  const [visibleColumns, setVisibleColumns] = useState<LogColumnKey[]>(() => {
    try {
      const stored = localStorage.getItem(LOG_COLUMNS_STORAGE_KEY);
      return stored ? normalizeLogColumns(JSON.parse(stored)) : [...defaultLogColumns];
    } catch {
      return [...defaultLogColumns];
    }
  });
  const terminationInFlight = useRef(false);
  const dragSelectionValue = useRef<boolean | null>(null);

  const updateVisibleColumns = (columns: LogColumnKey[]) => {
    const normalized = normalizeLogColumns(columns);
    setVisibleColumns(normalized);
    try { localStorage.setItem(LOG_COLUMNS_STORAGE_KEY, JSON.stringify(normalized)); } catch { /* Storage may be disabled. */ }
  };

  useEffect(() => {
    const stopDragging = () => {
      dragSelectionValue.current = null;
      document.body.style.userSelect = '';
    };
    window.addEventListener('pointerup', stopDragging);
    window.addEventListener('pointercancel', stopDragging);
    window.addEventListener('blur', stopDragging);
    return () => {
      window.removeEventListener('pointerup', stopDragging);
      window.removeEventListener('pointercancel', stopDragging);
      window.removeEventListener('blur', stopDragging);
      document.body.style.userSelect = '';
    };
  }, []);

  const updateSelection = (id: string, selected: boolean) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (selected) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  const beginDragSelection = (id: string) => {
    const shouldSelect = !selectedIds.has(id);
    dragSelectionValue.current = shouldSelect;
    document.body.style.userSelect = 'none';
    updateSelection(id, shouldSelect);
  };

  const continueDragSelection = (id: string) => {
    if (dragSelectionValue.current !== null) updateSelection(id, dragSelectionValue.current);
  };

  const pageIds = state.logs.map((log) => log.id);
  const allPageSelected = pageIds.length > 0 && pageIds.every((id) => selectedIds.has(id));
  const toggleCurrentPage = () => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (allPageSelected) pageIds.forEach((id) => next.delete(id));
      else pageIds.forEach((id) => next.add(id));
      return next;
    });
  };

  const downloadSelected = async () => {
    if (!selectedIds.size) return;
    setIsDownloading(true);
    try {
      await llmLogsApi.downloadSelected(Array.from(selectedIds));
      toast.success(`已打包 ${selectedIds.size} 条大模型日志`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '打包下载失败');
    } finally {
      setIsDownloading(false);
    }
  };

  const terminableIds = getTerminableLogIds(selectedIds, state.logs);
  const terminateSelected = async () => {
    if (!terminableIds.length || terminationInFlight.current) return;
    const ids = [...terminableIds];
    if (!window.confirm('确定终止所选日志中的进行中任务吗？已完成的任务不会受影响，终止后未完成的响应将被忽略。')) return;
    terminationInFlight.current = true;
    setIsTerminating(true);
    try {
      const result = await llmLogsApi.cancelSelected(ids);
      const cancelled = new Set(result.cancelled_ids);
      setSelectedIds(current => new Set(Array.from(current).filter(id => !cancelled.has(id))));
      const skippedCount = result.skipped_ids.length;
      toast.success(cancelled.size
        ? `已终止 ${cancelled.size} 个任务${skippedCount ? `，另有 ${skippedCount} 个已结束或已终止，未重复处理` : ''}`
        : '所选任务已结束，没有需要终止的进行中任务');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '终止任务失败');
    } finally {
      await state.fetchLogs({ silent: true });
      terminationInFlight.current = false;
      setIsTerminating(false);
    }
  };

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
      <div className="card">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-100 px-4 py-3">
          <div className="flex items-center gap-3 text-sm text-gray-600">
            <span>已选择 {selectedIds.size} 条</span>
            {selectedIds.size > 0 && <button type="button" onClick={() => setSelectedIds(new Set())} className="text-gray-500 hover:text-gray-800">清空选择</button>}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <button type="button" onClick={() => setShowColumnControl(value => !value)} aria-expanded={showColumnControl} className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50">
                <Columns className="h-4 w-4" />显示列
              </button>
              {showColumnControl && <div className="absolute right-0 top-full z-20 mt-2 w-56 rounded-lg border border-gray-200 bg-white p-3 shadow-xl">
                <p className="mb-2 text-xs text-gray-500">按需显示日志列；时间、任务类型、状态始终显示。</p>
                <div className="max-h-72 space-y-1 overflow-y-auto">
                  {logColumns.map(column => <label key={column.key} className="flex cursor-pointer items-center gap-2 rounded px-1 py-1 text-sm hover:bg-gray-50">
                    <input type="checkbox" checked={visibleColumns.includes(column.key)} disabled={requiredLogColumns.has(column.key)}
                      onChange={event => updateVisibleColumns(event.target.checked ? [...visibleColumns, column.key] : visibleColumns.filter(key => key !== column.key))}
                      className="h-4 w-4 rounded border-gray-300 text-primary-600" />{column.label}{requiredLogColumns.has(column.key) && <span className="text-xs text-gray-400">必显</span>}
                  </label>)}
                </div>
                <div className="mt-2 flex justify-between border-t pt-2 text-sm"><button type="button" onClick={() => updateVisibleColumns([...defaultLogColumns])} className="text-primary-600">恢复默认</button><button type="button" onClick={() => setShowColumnControl(false)} className="text-gray-600">完成</button></div>
              </div>}
            </div>
            <button
              type="button"
              onClick={() => void terminateSelected()}
              disabled={!terminableIds.length || isTerminating}
              title="仅终止选中的进行中任务"
              className="inline-flex items-center gap-1.5 rounded-lg border border-red-200 bg-red-50 px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isTerminating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Square className="h-4 w-4" />}
              {isTerminating ? '终止中...' : '终止任务'}
            </button>
            <button
              type="button"
              onClick={() => void downloadSelected()}
              disabled={!selectedIds.size || isDownloading}
              className="inline-flex items-center gap-1.5 rounded-lg bg-orange-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-orange-600 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isDownloading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
              {isDownloading ? '打包中...' : '打包下载'}
            </button>
            <button
              type="button"
              onClick={state.openStatsModal}
              className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
            >
              <BarChart3 className="h-4 w-4" />查看调用统计
            </button>
            <button
              type="button"
              onClick={state.openTokenStatsModal}
              className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
            >
              <BarChart3 className="h-4 w-4" />查看 Token 消耗
            </button>
            <button type="button" onClick={() => setShowHierarchy(true)} className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"><BarChart3 className="h-4 w-4" />小说 / 章回 / Shot Token</button>
          </div>
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
            <table className="w-max min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="w-14 px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">
                    <label className="inline-flex cursor-pointer flex-col items-center gap-1 normal-case">
                      <input type="checkbox" checked={allPageSelected} onChange={toggleCurrentPage} className="h-4 w-4 rounded border-gray-300 text-primary-600" />
                      <span>选择</span>
                    </label>
                  </th>
                  {logColumns.filter(column => visibleColumns.includes(column.key)).map(column => (
                    <th key={column.key} className="whitespace-nowrap px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{column.label}</th>
                  ))}
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('common.actions')}</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {state.logs.map((log) => (
                  <LogTableRow key={log.id} log={log} visibleColumns={visibleColumns} selected={selectedIds.has(log.id)}
                    onSelectionStart={beginDragSelection} onSelectionEnter={continueDragSelection}
                    onView={() => state.openLogDetail(log)}
                    formatDate={state.formatDate} truncateText={state.truncateText}
                    getDisplayDuration={state.getDisplayDuration}
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
          onClose={state.closeModal} formatDate={state.formatDate} getTaskTypeLabel={state.getTaskTypeLabel}
          getDisplayDuration={state.getDisplayDuration} getStatusBadgeConfig={state.getStatusBadgeConfig} />
      )}
      {state.showStatsModal && <StatsModal state={state} />}
      {state.showTokenStatsModal && <TokenStatsModal state={state} />}
      {showHierarchy && <TokenUsageHierarchyModal onClose={() => setShowHierarchy(false)} />}
    </div>
  );
}
