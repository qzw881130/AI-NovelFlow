import { useState, useEffect, useCallback, useRef } from 'react';
import { toast } from '../../../stores/toastStore';
import { useTranslation } from '../../../stores/i18nStore';
import { llmLogsApi, type LLMLog, type Pagination, type FilterOptions, type LLMLogFilters, type LLMLogStatsGroupBy, type LLMLogStatsResponse } from '../../../api/llmLogs';

export type PromptTab = 'params' | 'system' | 'user' | 'response';

const TASK_CATEGORY_TYPES: Record<string, string[]> = {
  style_design: ['style'],
  asset_parse: ['parse_characters', 'parse_scenes', 'parse_props'],
  asset_generation: ['generate_character_appearance'],
  shot_planning: ['split_chapter'],
  shot_image: ['shot_image_prompt'],
  video_director: ['video_mode_recommender', 'keyframe_description', 'keyframe_planner', 'keyframe_transition'],
  keyframe_image: ['keyframe_image_prompt'],
  video_generation: ['expand_video_prompt', 'h3_single_frame_prompt', 'h3_first_last_frame_prompt', 'h3_multi_keyframe_prompt'],
};

const TASK_CATEGORY_OPTIONS = [
  { value: 'style_design', labelKey: 'promptConfig.categories.styleDesign' },
  { value: 'asset_parse', labelKey: 'promptConfig.categories.assetParse' },
  { value: 'asset_generation', labelKey: 'promptConfig.categories.assetGeneration' },
  { value: 'shot_planning', labelKey: 'promptConfig.categories.shotPlanning' },
  { value: 'shot_image', labelKey: 'promptConfig.categories.shotImage' },
  { value: 'video_director', labelKey: 'promptConfig.categories.videoDirector' },
  { value: 'keyframe_image', labelKey: 'promptConfig.categories.keyframeImage' },
  { value: 'video_generation', labelKey: 'promptConfig.categories.videoGeneration' },
];

export function useLLMLogsState() {
  const { t, i18n } = useTranslation();
  const [logs, setLogs] = useState<LLMLog[]>([]);
  const [pagination, setPagination] = useState<Pagination>({ page: 1, page_size: 20, total: 0, total_pages: 0 });
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState<LLMLogFilters>({ provider: '', model: '', category: '', task_type: '', status: '' });
  const [filterOptions, setFilterOptions] = useState<FilterOptions>({ providers: [], models: [], task_types: [] });
  const [selectedLog, setSelectedLog] = useState<LLMLog | null>(null);
  const [activePromptTab, setActivePromptTab] = useState<PromptTab>('user');
  const [autoRefreshInterval, setAutoRefreshInterval] = useState(0);
  const [showStatsModal, setShowStatsModal] = useState(false);
  const [statsGroupBy, setStatsGroupBy] = useState<LLMLogStatsGroupBy>('hour');
  const [statsRangeValue, setStatsRangeValue] = useState(1);
  const [statsData, setStatsData] = useState<LLMLogStatsResponse | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);
  const [durationNow, setDurationNow] = useState(() => Date.now());
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
    if (!logs.some(log => log.status === 'pending')) return;
    const intervalId = window.setInterval(() => setDurationNow(Date.now()), 1000);
    return () => window.clearInterval(intervalId);
  }, [logs]);

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
    setFilters(prev => ({ ...prev, [key]: value, ...(key === 'category' ? { task_type: '' } : {}) }));
    setPagination(prev => ({ ...prev, page: 1 }));
  };

  const applyFilters = () => fetchLogs();
  const resetFilters = () => {
    setFilters({ provider: '', model: '', category: '', task_type: '', status: '' });
    setPagination(prev => ({ ...prev, page: 1 }));
    setTimeout(fetchLogs, 0);
  };

  const taskTypeOptions = filters.category
    ? filterOptions.task_types.filter(type => TASK_CATEGORY_TYPES[filters.category]?.includes(type))
    : filterOptions.task_types;

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

  const getDisplayDuration = (log: LLMLog) => {
    if (typeof log.duration === 'number') return `${log.duration.toFixed(2)}s`;
    if (log.status === 'error') return '-';
    if (log.status !== 'pending' || !log.created_at) return '-';
    const createdAt = new Date(log.created_at).getTime();
    if (Number.isNaN(createdAt)) return '-';
    const seconds = Math.max(0, (durationNow - createdAt) / 1000);
    if (seconds > 600) return '-';
    return `${seconds.toFixed(0)}s`;
  };

  const getTaskTypeCategoryLabel = (type: string | null) => {
    const categories: Record<string, string> = {
      'parse_characters': '素材解析',
      'parse_scenes': '素材解析',
      'parse_props': '素材解析',
      'style': '风格设计',
      'generate_character_appearance': '素材生成',
      'shot_image_prompt': '分镜生图',
      'split_chapter': '分镜规划',
      'video_mode_recommender': '视频导演',
      'keyframe_description': '视频导演',
      'keyframe_planner': '视频导演',
      'keyframe_transition': '视频导演',
      'keyframe_image_prompt': '关键帧生图',
      'expand_video_prompt': '视频生成',
      'h3_single_frame_prompt': '视频生成',
      'h3_first_last_frame_prompt': '视频生成',
      'h3_multi_keyframe_prompt': '视频生成',
    };
    return (type && categories[type]) || '其他';
  };

  const getTaskTypeNameLabel = (type: string | null) => {
    const labels: Record<string, string> = {
      'parse_characters': t('llmLogs.parseCharacters'), 'parse_scenes': t('llmLogs.parseScenes'),
      'parse_props': t('llmLogs.parseProps'),
      'style': '风格提示词',
      'split_chapter': t('llmLogs.splitShots'), 'generate_character_appearance': t('llmLogs.generateAppearance'),
      'expand_video_prompt': t('llmLogs.expandVideoPrompt'),
      'shot_image_prompt': '主分镜图提示词',
      'video_mode_recommender': '视频模式推荐',
      'keyframe_description': '关键帧描述',
      'keyframe_planner': '关键帧规划',
      'keyframe_transition': '关键帧过渡规划',
      'keyframe_image_prompt': '关键帧生图提示词',
      'h3_single_frame_prompt': 'H3 单帧视频提示词',
      'h3_first_last_frame_prompt': 'H3 首尾帧视频提示词',
      'h3_multi_keyframe_prompt': 'H3 多关键帧视频提示词',
    };
    if (!type) return '-';
    return labels[type] || type;
  };

  const getTaskTypeLabel = (type: string | null) => {
    if (!type) return '-';
    const category = getTaskTypeCategoryLabel(type);
    const label = getTaskTypeNameLabel(type);
    return `${category} / ${label}`;
  };

  const getStatusBadgeConfig = (status: string) => {
    if (status === 'success') return { bg: 'bg-green-100', text: 'text-green-700', label: t('common.success') };
    if (status === 'pending') return { bg: 'bg-amber-100', text: 'text-amber-700', label: t('llmLogs.pending') };
    return { bg: 'bg-red-100', text: 'text-red-700', label: t('common.failed') };
  };

  const closeModal = () => { setSelectedLog(null); setActivePromptTab('user'); };

  const fetchStats = useCallback(async (groupBy = statsGroupBy, rangeValue = statsRangeValue) => {
    setStatsLoading(true);
    try {
      const data = await llmLogsApi.fetchStats(groupBy, rangeValue, filters);
      if (data.success && data.data) setStatsData(data.data);
      else toast.error(data.message || '加载调用统计失败');
    } catch (error) {
      console.error('加载调用统计失败:', error);
      toast.error('加载调用统计失败');
    } finally {
      setStatsLoading(false);
    }
  }, [filters, statsGroupBy, statsRangeValue]);

  const openStatsModal = () => {
    setShowStatsModal(true);
    fetchStats();
  };

  const closeStatsModal = () => setShowStatsModal(false);

  const changeStatsGroupBy = (groupBy: LLMLogStatsGroupBy) => {
    const defaultRange = groupBy === 'day' ? 7 : 1;
    setStatsGroupBy(groupBy);
    setStatsRangeValue(defaultRange);
    fetchStats(groupBy, defaultRange);
  };

  const changeStatsRangeValue = (rangeValue: number) => {
    setStatsRangeValue(rangeValue);
    fetchStats(statsGroupBy, rangeValue);
  };

  return {
    logs, pagination, loading, filters, filterOptions, taskCategoryOptions: TASK_CATEGORY_OPTIONS, taskTypeOptions, selectedLog, activePromptTab, autoRefreshInterval,
    setPagination, setSelectedLog, setActivePromptTab, handleFilterChange, applyFilters, resetFilters, openLogDetail,
    setAutoRefreshInterval, fetchLogs, formatDate, truncateText, getDisplayDuration, getTaskTypeLabel, getTaskTypeNameLabel, getTaskTypeCategoryLabel, getStatusBadgeConfig, closeModal,
    showStatsModal, statsGroupBy, statsRangeValue, statsData, statsLoading, openStatsModal, closeStatsModal, changeStatsGroupBy, changeStatsRangeValue, fetchStats,
  };
}
