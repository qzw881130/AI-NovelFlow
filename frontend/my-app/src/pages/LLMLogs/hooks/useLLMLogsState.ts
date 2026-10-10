import { useState, useEffect, useCallback, useRef } from 'react';
import { toast } from '../../../stores/toastStore';
import { useTranslation } from '../../../stores/i18nStore';
import { llmLogsApi, LLM_CANCELLED_MESSAGE, type LLMLog, type Pagination, type FilterOptions, type LLMLogFilters, type LLMLogStatsGroupBy, type LLMLogStatsResponse, type LLMLogTokenStatsResponse } from '../../../api/llmLogs';

export type PromptTab = 'params' | 'system' | 'user' | 'images' | 'response';

const TASK_CATEGORY_TYPES: Record<string, string[]> = {
  story_context: ['story_world_context_recommender'],
  style_design: ['style'],
  asset_parse: ['parse_characters', 'parse_scenes', 'parse_props'],
  asset_generation: ['generate_character_appearance', 'generate_scene_setting', 'generate_prop_appearance'],
  shot_planning: ['split_chapter'],
  shot_image: ['shot_image_prompt'],
  video_director: ['video_mode_recommender', 'keyframe_description', 'keyframe_planner', 'keyframe_transition', 'clip_execution_planner'],
  keyframe_image: ['temporal_reference_selector', 'keyframe_image_prompt'],
  video_generation: ['expand_video_prompt', 'h3_single_frame_prompt', 'h3_first_last_frame_prompt', 'h3_multi_keyframe_prompt', 'h3_execution_optimizer_prompt'],
};

const TASK_CATEGORY_OPTIONS = [
  { value: 'story_context', labelKey: 'promptConfig.categories.storyContext' },
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
  const [autoRefreshInterval, setAutoRefreshInterval] = useState(5000);
  const [showStatsModal, setShowStatsModal] = useState(false);
  const [statsGroupBy, setStatsGroupBy] = useState<LLMLogStatsGroupBy>('hour');
  const [statsRangeValue, setStatsRangeValue] = useState(1);
  const [statsData, setStatsData] = useState<LLMLogStatsResponse | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);
  const [showTokenStatsModal, setShowTokenStatsModal] = useState(false);
  const [tokenStatsGroupBy, setTokenStatsGroupBy] = useState<LLMLogStatsGroupBy>('hour');
  const [tokenStatsRangeValue, setTokenStatsRangeValue] = useState(1);
  const [tokenStatsData, setTokenStatsData] = useState<LLMLogTokenStatsResponse | null>(null);
  const [tokenStatsLoading, setTokenStatsLoading] = useState(false);
  const [durationNow, setDurationNow] = useState(() => Date.now());
  const fetchLogsRequestRef = useRef(0);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => { if (e.key === 'Escape' && selectedLog) setSelectedLog(null); };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [selectedLog]);

  const fetchLogs = useCallback(async (options?: { silent?: boolean }) => {
    const requestId = fetchLogsRequestRef.current + 1;
    fetchLogsRequestRef.current = requestId;
    if (!options?.silent) setLoading(true);
    try {
      const data = await llmLogsApi.fetchList(pagination.page, pagination.page_size, filters);
      if (requestId === fetchLogsRequestRef.current && data.success && data.data) {
        setLogs(data.data.items);
        setPagination(data.data.pagination);
      }
    } catch (error) {
      console.error('加载日志失败:', error);
      if (requestId === fetchLogsRequestRef.current) {
        toast.error(t('llmLogs.loadFailed'));
      }
    } finally {
      // A silent refresh can supersede a foreground request that enabled the
      // spinner. The latest request must settle loading in either case.
      if (requestId === fetchLogsRequestRef.current) {
        setLoading(false);
      }
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
    if (log.status === 'pending' && seconds > 600) return '-';
    return `${seconds.toFixed(0)}s`;
  };

  const getTaskTypeCategoryLabel = (type: string | null) => {
    const categories: Record<string, string> = {
      story_world_context_recommender: 'storyContext',
      parse_characters: 'assetParse', parse_scenes: 'assetParse', parse_props: 'assetParse',
      style: 'styleDesign', generate_character_appearance: 'assetGeneration',
      generate_scene_setting: 'assetGeneration', generate_prop_appearance: 'assetGeneration',
      shot_image_prompt: 'shotImage', split_chapter: 'shotPlanning',
      video_mode_recommender: 'videoDirector', keyframe_description: 'videoDirector',
      keyframe_planner: 'videoDirector', keyframe_transition: 'videoDirector',
      keyframe_image_prompt: 'keyframeImage', temporal_reference_selector: 'keyframeImage',
      clip_execution_planner: 'videoDirector', expand_video_prompt: 'videoGeneration', h3_single_frame_prompt: 'videoGeneration',
      h3_first_last_frame_prompt: 'videoGeneration', h3_multi_keyframe_prompt: 'videoGeneration', h3_execution_optimizer_prompt: 'videoGeneration',
    };
    return type && categories[type]
      ? t(`promptConfig.categories.${categories[type]}`)
      : t('llmLogs.other');
  };

  const getTaskTypeNameLabel = (type: string | null) => {
    const labels: Record<string, string> = {
      story_world_context_recommender: t('promptConfig.types.storyWorldContextRecommender'),
      parse_characters: t('llmLogs.parseCharacters'), parse_scenes: t('llmLogs.parseScenes'),
      parse_props: t('llmLogs.parseProps'), style: t('promptConfig.types.style'),
      split_chapter: t('llmLogs.splitShots'), generate_character_appearance: t('llmLogs.generateAppearance'),
      generate_scene_setting: t('llmLogs.generateSceneSetting'),
      generate_prop_appearance: t('llmLogs.generatePropAppearance'),
      clip_execution_planner: t('llmLogs.clipExecutionPlanner'),
      expand_video_prompt: t('llmLogs.expandVideoPrompt'),
      shot_image_prompt: t('promptConfig.types.shotImagePrompt'),
      video_mode_recommender: t('promptConfig.types.videoModeRecommender'),
      keyframe_description: t('promptConfig.types.keyframeDescription'),
      keyframe_planner: t('promptConfig.types.keyframePlanner'),
      keyframe_transition: t('promptConfig.types.keyframeTransition'),
      keyframe_image_prompt: t('promptConfig.types.keyframeImagePrompt'),
      temporal_reference_selector: t('promptConfig.types.temporalReferenceSelector'),
      h3_single_frame_prompt: t('promptConfig.types.h3SingleFramePrompt'),
      h3_first_last_frame_prompt: t('promptConfig.types.h3FirstLastFramePrompt'),
      h3_multi_keyframe_prompt: t('promptConfig.types.h3MultiKeyframePrompt'),
      h3_execution_optimizer_prompt: t('promptConfig.types.h3ExecutionOptimizerPrompt'),
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

  const getStatusBadgeConfig = (status: string, errorMessage?: string | null) => {
    if (status === 'error' && errorMessage === LLM_CANCELLED_MESSAGE) {
      return { bg: 'bg-gray-100', text: 'text-gray-600', label: '已终止' };
    }
    if (status === 'success') return { bg: 'bg-green-100', text: 'text-green-700', label: t('common.success') };
    if (status === 'pending') return { bg: 'bg-amber-100', text: 'text-amber-700', label: t('llmLogs.pending') };
    return { bg: 'bg-red-100', text: 'text-red-700', label: t('common.failed') };
  };

  useEffect(() => {
    const logId = new URLSearchParams(window.location.search).get('logId');
    if (logId) void llmLogsApi.fetchDetail(logId).then(data => { if (data.success && data.data) setSelectedLog(data.data); }).catch(error => console.error('加载日志详情失败:', error));
  }, []);

  const closeModal = () => { setSelectedLog(null); setActivePromptTab('user'); };

  const fetchStats = useCallback(async (groupBy = statsGroupBy, rangeValue = statsRangeValue) => {
    setStatsLoading(true);
    try {
      const data = await llmLogsApi.fetchStats(groupBy, rangeValue, filters);
      if (data.success && data.data) setStatsData(data.data);
       else toast.error(data.message || t('llmLogs.statsLoadFailed'));
    } catch (error) {
      console.error('加载调用统计失败:', error);
      toast.error(t('llmLogs.statsLoadFailed'));
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

  const fetchTokenStats = useCallback(async (groupBy = tokenStatsGroupBy, rangeValue = tokenStatsRangeValue) => {
    setTokenStatsLoading(true);
    try {
      const data = await llmLogsApi.fetchTokenStats(groupBy, rangeValue, filters);
      if (data.success && data.data) setTokenStatsData(data.data);
       else toast.error(data.message || t('llmLogs.tokenStatsLoadFailed'));
    } catch (error) {
      console.error('加载 Token 消耗失败:', error);
      toast.error(t('llmLogs.tokenStatsLoadFailed'));
    } finally {
      setTokenStatsLoading(false);
    }
  }, [filters, tokenStatsGroupBy, tokenStatsRangeValue]);

  const openTokenStatsModal = () => {
    setShowTokenStatsModal(true);
    fetchTokenStats();
  };

  const closeTokenStatsModal = () => setShowTokenStatsModal(false);

  const changeTokenStatsGroupBy = (groupBy: LLMLogStatsGroupBy) => {
    const defaultRange = groupBy === 'day' ? 7 : 1;
    setTokenStatsGroupBy(groupBy);
    setTokenStatsRangeValue(defaultRange);
    fetchTokenStats(groupBy, defaultRange);
  };

  const changeTokenStatsRangeValue = (rangeValue: number) => {
    setTokenStatsRangeValue(rangeValue);
    fetchTokenStats(tokenStatsGroupBy, rangeValue);
  };

  return {
    logs, pagination, loading, filters, filterOptions, taskCategoryOptions: TASK_CATEGORY_OPTIONS, taskTypeOptions, selectedLog, activePromptTab, autoRefreshInterval,
    setPagination, setSelectedLog, setActivePromptTab, handleFilterChange, applyFilters, resetFilters, openLogDetail,
    setAutoRefreshInterval, fetchLogs, formatDate, truncateText, getDisplayDuration, getTaskTypeLabel, getTaskTypeNameLabel, getTaskTypeCategoryLabel, getStatusBadgeConfig, closeModal,
    showStatsModal, statsGroupBy, statsRangeValue, statsData, statsLoading, openStatsModal, closeStatsModal, changeStatsGroupBy, changeStatsRangeValue, fetchStats,
    showTokenStatsModal, tokenStatsGroupBy, tokenStatsRangeValue, tokenStatsData, tokenStatsLoading,
    openTokenStatsModal, closeTokenStatsModal, changeTokenStatsGroupBy, changeTokenStatsRangeValue, fetchTokenStats,
  };
}
