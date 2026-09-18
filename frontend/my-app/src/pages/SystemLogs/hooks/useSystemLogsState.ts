import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  systemLogsApi,
  type SystemLogDetail,
  type SystemLogFilterData,
  type SystemLogItem,
  type SystemLogView,
} from '../../../api/systemLogs';
import { useTranslation } from '../../../stores/i18nStore';
import {
  countSystemLogFilters,
  DEFAULT_SYSTEM_LOG_STATE,
  parseSystemLogUrlState,
  serializeSystemLogUrlState,
  systemLogQueryFromState,
  updateSystemLogUrlState,
  type SystemLogUrlState,
} from '../urlState';
import {
  EMPTY_DISPLAY_METADATA,
  loadSystemLogDisplayMetadata,
  type SystemLogDisplayMetadata,
} from '../displayMetadata';

const EMPTY_FILTERS: SystemLogFilterData = {
  views: ['attention', 'errors', 'needs_review', 'all'],
  levels: [],
  services: [],
  providers: [],
  errorCodes: [],
  failureClasses: [],
  novelIds: [],
  chapterIds: [],
  shotIds: [],
  taskIds: [],
};

const isAbort = (error: unknown) => error instanceof DOMException && error.name === 'AbortError';

export function useSystemLogsState() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const urlKey = searchParams.toString();
  const urlState = useMemo(() => parseSystemLogUrlState(new URLSearchParams(urlKey)), [urlKey]);
  const [items, setItems] = useState<SystemLogItem[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [listError, setListError] = useState('');
  const [filterOptions, setFilterOptions] = useState<SystemLogFilterData>(EMPTY_FILTERS);
  const [filterOptionsError, setFilterOptionsError] = useState('');
  const [displayMetadata, setDisplayMetadata] = useState<SystemLogDisplayMetadata>(EMPTY_DISPLAY_METADATA);
  const [detail, setDetail] = useState<SystemLogDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState('');
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [revision, setRevision] = useState(0);
  const listRequest = useRef(0);
  const detailRequest = useRef(0);

  const writeUrl = useCallback((next: SystemLogUrlState, replace = false) => {
    setSearchParams(serializeSystemLogUrlState(next), { replace });
  }, [setSearchParams]);

  useEffect(() => {
    const canonical = serializeSystemLogUrlState(urlState).toString();
    if (canonical !== urlKey) setSearchParams(canonical, { replace: true });
  }, [setSearchParams, urlKey, urlState]);

  const queryKey = useMemo(() => JSON.stringify(systemLogQueryFromState(urlState)), [urlState]);

  useEffect(() => {
    const requestId = ++listRequest.current;
    const controller = new AbortController();
    if (items.length) setRefreshing(true);
    else setLoading(true);
    setListError('');
    const load = async () => {
      try {
        const response = await systemLogsApi.list(JSON.parse(queryKey), controller.signal);
        if (requestId !== listRequest.current) return;
        if (!response.success || !response.data) {
          const message = String(response.message || t('systemLogs.loadError'));
          if (urlState.cursor && message.includes('CURSOR')) {
            writeUrl({ ...urlState, cursor: '' }, true);
          }
          throw new Error(message);
        }
        setItems(response.data.items);
        setNextCursor(response.data.nextCursor);
        setHasMore(response.data.hasMore);
        setLastUpdated(new Date());
      } catch (error) {
        if (requestId !== listRequest.current || isAbort(error)) return;
        setListError(error instanceof Error ? error.message : t('systemLogs.loadError'));
      } finally {
        if (requestId === listRequest.current) {
          setLoading(false);
          setRefreshing(false);
        }
      }
    };
    void load();
    return () => {
      listRequest.current++;
      controller.abort();
    };
  }, [queryKey, revision]);

  useEffect(() => {
    const controller = new AbortController();
    setFilterOptionsError('');
    void systemLogsApi.filters(controller.signal).then(response => {
      if (!response.success || !response.data) {
        setFilterOptionsError(String(response.message || t('systemLogs.filterOptionsError')));
        return;
      }
      setFilterOptions(response.data);
    }).catch(error => {
      if (!isAbort(error)) setFilterOptionsError(t('systemLogs.filterOptionsError'));
    });
    return () => controller.abort();
  }, [t]);

  useEffect(() => {
    let cancelled = false;
    void loadSystemLogDisplayMetadata().then(metadata => {
      if (!cancelled) setDisplayMetadata(metadata);
    }).catch(() => {
      if (!cancelled) setDisplayMetadata(EMPTY_DISPLAY_METADATA);
    });
    return () => { cancelled = true; };
  }, [revision]);

  useEffect(() => {
    const eventId = urlState.eventId;
    if (!eventId) {
      detailRequest.current++;
      setDetail(null);
      setDetailError('');
      setDetailLoading(false);
      return;
    }
    const requestId = ++detailRequest.current;
    const controller = new AbortController();
    setDetail(null);
    setDetailError('');
    setDetailLoading(true);
    void systemLogsApi.detail(eventId, controller.signal).then(response => {
      if (requestId !== detailRequest.current) return;
      if (!response.success || !response.data) throw new Error(String(response.message || t('systemLogs.loadError')));
      if (response.data.eventId !== eventId) throw new Error(t('systemLogs.loadError'));
      setDetail(response.data);
    }).catch(error => {
      if (requestId !== detailRequest.current || isAbort(error)) return;
      setDetailError(error instanceof Error ? error.message : t('systemLogs.loadError'));
    }).finally(() => {
      if (requestId === detailRequest.current) setDetailLoading(false);
    });
    return () => {
      detailRequest.current++;
      controller.abort();
    };
  }, [urlState.eventId, t]);

  const changeView = useCallback((view: SystemLogView) => {
    writeUrl(updateSystemLogUrlState(urlState, { view }));
  }, [urlState, writeUrl]);

  const applyFilters = useCallback((filters: Pick<SystemLogUrlState,
    'level' | 'service' | 'provider' | 'novelId' | 'chapterId' | 'shotId' |
    'taskId' | 'errorCode' | 'failureClass'>) => {
    writeUrl(updateSystemLogUrlState(urlState, filters));
  }, [urlState, writeUrl]);

  const resetFilters = useCallback(() => {
    writeUrl({ ...DEFAULT_SYSTEM_LOG_STATE, view: urlState.view });
  }, [urlState.view, writeUrl]);

  const openDetail = useCallback((eventId: string) => {
    writeUrl(updateSystemLogUrlState(urlState, { eventId }, { keepCursor: true, keepEvent: true }));
  }, [urlState, writeUrl]);

  const closeDetail = useCallback(() => {
    writeUrl({ ...urlState, eventId: '' }, true);
  }, [urlState, writeUrl]);

  const nextPage = useCallback(() => {
    if (nextCursor) writeUrl({ ...urlState, cursor: nextCursor, eventId: '' });
  }, [nextCursor, urlState, writeUrl]);

  const previousPage = useCallback(() => navigate(-1), [navigate]);
  const refresh = useCallback(() => setRevision(value => value + 1), []);

  const formatDate = useCallback((value: string | Date | null) => {
    if (!value) return t('systemLogs.unknown');
    const date = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(date.getTime())) return t('systemLogs.unknown');
    try {
      return new Intl.DateTimeFormat(i18n.language, {
        timeZone: i18n.timezone,
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
      }).format(date);
    } catch {
      return date.toISOString();
    }
  }, [i18n.language, i18n.timezone, t]);

  return {
    urlState,
    items,
    nextCursor,
    hasMore,
    loading,
    refreshing,
    listError,
    filterOptions,
    filterOptionsError,
    displayMetadata,
    selectedPreview: items.find(item => item.eventId === urlState.eventId) || null,
    detail,
    detailLoading,
    detailError,
    lastUpdated,
    activeFilterCount: countSystemLogFilters(urlState),
    changeView,
    applyFilters,
    resetFilters,
    openDetail,
    closeDetail,
    nextPage,
    previousPage,
    refresh,
    formatDate,
  };
}
