import { useState, useEffect, useCallback, useRef } from 'react';
import { toast } from '../../../stores/toastStore';
import { useTranslation } from '../../../stores/i18nStore';
import { llmLogsApi, type LLMLog, type Pagination, type FilterOptions } from '../../../api/llmLogs';

export type PromptTab = 'params' | 'system' | 'user' | 'response';

export function useLLMLogsState() {
  const { t, i18n } = useTranslation();
  const [logs, setLogs] = useState<LLMLog[]>([]);
  const [pagination, setPagination] = useState<Pagination>({ page: 1, page_size: 20, total: 0, total_pages: 0 });
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({ provider: '', model: '', task_type: '', status: '' });
  const [filterOptions, setFilterOptions] = useState<FilterOptions>({ providers: [], models: [], task_types: [] });
  const [selectedLog, setSelectedLog] = useState<LLMLog | null>(null);
  const [activePromptTab, setActivePromptTab] = useState<PromptTab>('user');
  const [autoRefreshInterval, setAutoRefreshInterval] = useState(0);
  const isFetchingLogsRef = useRef(false);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => { if (e.key === 'Escape' && selectedLog) setSelectedLog(null); };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [selectedLog]);

  const fetchLogs = useCallback(async (options?: { silent?: boolean }) => {
    if (isFetchingLogsRef.current) return;
    isFetchingLogsRef.current = true;
    if (!options?.silent) setLoading(true);
    try {
      const data = await llmLogsApi.fetchList(pagination.page, pagination.page_size, filters);
      if (data.success && data.data) { setLogs(data.data.items); setPagination(data.data.pagination); }
    } catch (error) {
      console.error('加载日志失败:', error);
      toast.error('加载日志失败');
    } finally {
      isFetchingLogsRef.current = false;
      if (!options?.silent) setLoading(false);
    }
  }, [pagination.page, pagination.page_size, filters]);

  useEffect(() => { fetchLogs(); fetchFilterOptions(); }, [fetchLogs]);

  useEffect(() => {
    if (!autoRefreshInterval) return;

    let cancelled = false;
    let timeoutId: ReturnType<typeof window.setTimeout> | null = null;

    const refresh = async () => {
      if (cancelled) return;
      await fetchLogs({ silent: true });
      if (!cancelled) {
        timeoutId = window.setTimeout(refresh, autoRefreshInterval);
      }
    };

    timeoutId = window.setTimeout(refresh, autoRefreshInterval);

    return () => {
      cancelled = true;
      if (timeoutId) window.clearTimeout(timeoutId);
    };
  }, [autoRefreshInterval, fetchLogs]);

  const fetchFilterOptions = async () => {
    try {
      const data = await llmLogsApi.fetchFilterOptions();
      if (data.success && data.data) setFilterOptions(data.data);
    } catch (error) {
      console.error('加载筛选选项失败:', error);
    }
  };

  const handleFilterChange = (key: string, value: string) => {
    setFilters(prev => ({ ...prev, [key]: value }));
    setPagination(prev => ({ ...prev, page: 1 }));
  };

  const applyFilters = () => fetchLogs();
  const resetFilters = () => {
    setFilters({ provider: '', model: '', task_type: '', status: '' });
    setPagination(prev => ({ ...prev, page: 1 }));
    setTimeout(fetchLogs, 0);
  };

  const openLogDetail = async (log: LLMLog) => {
    setSelectedLog(log);
    try {
      const data = await llmLogsApi.fetchDetail(log.id);
      if (data.success && data.data) setSelectedLog(data.data);
    } catch (error) {
      console.error('加载日志详情失败:', error);
    }
  };

  const formatDate = (dateStr: string) => {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    if (isNaN(date.getTime())) return '-';
    const options: Intl.DateTimeFormatOptions = {
      timeZone: i18n.timezone, year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
    };
    try {
      const formatter = new Intl.DateTimeFormat('en-GB', options);
      const parts = formatter.formatToParts(date);
      const getPart = (type: string) => parts.find(p => p.type === type)?.value || '';
      return `${getPart('year')}/${getPart('month')}/${getPart('day')} ${getPart('hour')}:${getPart('minute')}:${getPart('second')}`;
    } catch {
      const formatted = date.toLocaleString('en-GB');
      const [datePart, timePart] = formatted.split(', ');
      const [day, month, year] = datePart.split('/');
      return `${year}/${month}/${day} ${timePart}`;
    }
  };

  const truncateText = (text: string, maxLength: number = 100) => {
    if (!text) return '-';
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength) + '...';
  };

  const getTaskTypeLabel = (type: string) => {
    const labels: Record<string, string> = {
      'parse_characters': t('llmLogs.parseCharacters'), 'parse_scenes': t('llmLogs.parseScenes'),
      'split_chapter': t('llmLogs.splitShots'), 'generate_character_appearance': t('llmLogs.generateAppearance'),
      'expand_video_prompt': t('llmLogs.expandVideoPrompt')
    };
    return labels[type] || type || '-';
  };

  const getStatusBadgeConfig = (status: string) => {
    if (status === 'success') return { bg: 'bg-green-100', text: 'text-green-700', label: t('common.success') };
    return { bg: 'bg-red-100', text: 'text-red-700', label: t('status.failed') };
  };

  const closeModal = () => { setSelectedLog(null); setActivePromptTab('user'); };

  return {
    logs, pagination, loading, filters, filterOptions, selectedLog, activePromptTab, autoRefreshInterval,
    setPagination, setSelectedLog, setActivePromptTab, handleFilterChange, applyFilters, resetFilters, openLogDetail,
    setAutoRefreshInterval, fetchLogs, formatDate, truncateText, getTaskTypeLabel, getStatusBadgeConfig, closeModal
  };
}
