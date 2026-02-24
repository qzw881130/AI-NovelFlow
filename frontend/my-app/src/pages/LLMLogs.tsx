import { useState, useEffect } from 'react';
import { 
  ScrollText, 
  ChevronLeft, 
  ChevronRight, 
  Filter,
  Eye,
  X,
  RefreshCw
} from 'lucide-react';
import { toast } from '../stores/toastStore';
import { useTranslation } from '../stores/i18nStore';

interface LLMLog {
  id: string;
  created_at: string;
  provider: string;
  model: string;
  system_prompt: string;
  user_prompt: string;
  response: string;
  status: string;
  error_message: string;
  task_type: string;
  novel_id: string;
  chapter_id: string;
  character_id: string;
  used_proxy: boolean;
  duration: number;  // 请求耗时，单位秒
}

interface Pagination {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';

export default function LLMLogs() {
  const { t, i18n } = useTranslation();
  const [logs, setLogs] = useState<LLMLog[]>([]);
  const [pagination, setPagination] = useState<Pagination>({ page: 1, page_size: 20, total: 0, total_pages: 0 });
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({
    provider: '',
    model: '',
    task_type: '',
    status: ''
  });
  const [filterOptions, setFilterOptions] = useState({
    providers: [] as string[],
    models: [] as string[],
    task_types: [] as string[]
  });
  const [selectedLog, setSelectedLog] = useState<LLMLog | null>(null);
  const [activePromptTab, setActivePromptTab] = useState<'system' | 'user' | 'response'>('user');

  // ESC 键关闭弹窗
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && selectedLog) {
        setSelectedLog(null);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [selectedLog]);

  useEffect(() => {
    fetchLogs();
    fetchFilterOptions();
  }, [pagination.page]);

  const fetchLogs = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.append('page', pagination.page.toString());
      params.append('page_size', pagination.page_size.toString());
      if (filters.provider) params.append('provider', filters.provider);
      if (filters.model) params.append('model', filters.model);
      if (filters.task_type) params.append('task_type', filters.task_type);
      if (filters.status) params.append('status', filters.status);

      const res = await fetch(`${API_BASE}/llm-logs/?${params}`);
      const data = await res.json();
      if (data.success) {
        setLogs(data.data.items);
        setPagination(data.data.pagination);
      }
    } catch (error) {
      console.error('加载日志失败:', error);
      toast.error('加载日志失败');
    } finally {
      setLoading(false);
    }
  };

  const fetchFilterOptions = async () => {
    try {
      const res = await fetch(`${API_BASE}/llm-logs/filters`);
      const data = await res.json();
      if (data.success) {
        setFilterOptions(data.data);
      }
    } catch (error) {
      console.error('加载筛选选项失败:', error);
    }
  };

  const handleFilterChange = (key: string, value: string) => {
    setFilters(prev => ({ ...prev, [key]: value }));
    setPagination(prev => ({ ...prev, page: 1 }));
  };

  const applyFilters = () => {
    fetchLogs();
  };

  const resetFilters = () => {
    setFilters({ provider: '', model: '', task_type: '', status: '' });
    setPagination(prev => ({ ...prev, page: 1 }));
    setTimeout(fetchLogs, 0);
  };

  const formatDate = (dateStr: string) => {
    if (!dateStr) return '-';
    // 后端返回的是带时区的时间（如 2026-02-18T11:14:37+08:00）
    // 先解析为 Date 对象（自动处理时区转换为本地时间）
    const date = new Date(dateStr);
    if (isNaN(date.getTime())) return '-';
    
    // 转换为指定时区的时间字符串
    // 使用 Intl.DateTimeFormat 进行时区转换
    const options: Intl.DateTimeFormatOptions = {
      timeZone: i18n.timezone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false
    };
    
    try {
      // 使用 Intl.DateTimeFormat 进行正确的时区转换
      const formatter = new Intl.DateTimeFormat('en-GB', options);
      const parts = formatter.formatToParts(date);
      
      // 提取各部分
      const getPart = (type: string) => parts.find(p => p.type === type)?.value || '';
      const year = getPart('year');
      const month = getPart('month');
      const day = getPart('day');
      const hour = getPart('hour');
      const minute = getPart('minute');
      const second = getPart('second');
      
      return `${year}/${month}/${day} ${hour}:${minute}:${second}`;
    } catch (e) {
      // 如果时区不支持，返回原始解析时间
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
      'parse_characters': t('llmLogs.parseCharacters'),
      'parse_scenes': t('llmLogs.parseScenes'),
      'split_chapter': t('llmLogs.splitShots'),
      'generate_character_appearance': t('llmLogs.generateAppearance'),
      'expand_video_prompt': t('llmLogs.expandVideoPrompt')
    };
    return labels[type] || type || '-';
  };

  const getStatusBadge = (status: string) => {
    if (status === 'success') {
      return <span className="px-2 py-1 text-xs bg-green-100 text-green-700 rounded-full">{t('common.success')}</span>;
    }
    return <span className="px-2 py-1 text-xs bg-red-100 text-red-700 rounded-full">{t('status.failed')}</span>;
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">{t('llmLogs.title')}</h1>
        <p className="mt-1 text-sm text-gray-500">
          {t('llmLogs.subtitle')}
        </p>
      </div>

      {/* Filters */}
      <div className="card">
        <div className="flex items-center gap-2 mb-4">
          <Filter className="h-4 w-4 text-gray-500" />
          <span className="text-sm font-medium text-gray-700">{t('llmLogs.filterConditions')}</span>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <label className="block text-xs text-gray-500 mb-1">{t('llmLogs.llmProvider')}</label>
            <select
              value={filters.provider}
              onChange={(e) => handleFilterChange('provider', e.target.value)}
              className="input-field text-sm w-full"
            >
              <option value="">{t('llmLogs.all')}</option>
              {filterOptions.providers.map(p => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">{t('llmLogs.model')}</label>
            <select
              value={filters.model}
              onChange={(e) => handleFilterChange('model', e.target.value)}
              className="input-field text-sm w-full"
            >
              <option value="">{t('llmLogs.all')}</option>
              {filterOptions.models.map(m => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">{t('llmLogs.taskType')}</label>
            <select
              value={filters.task_type}
              onChange={(e) => handleFilterChange('task_type', e.target.value)}
              className="input-field text-sm w-full"
            >
              <option value="">{t('llmLogs.all')}</option>
              {filterOptions.task_types.map(t => (
                <option key={t} value={t}>{getTaskTypeLabel(t)}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">{t('common.status')}</label>
            <select
              value={filters.status}
              onChange={(e) => handleFilterChange('status', e.target.value)}
              className="input-field text-sm w-full"
            >
              <option value="">{t('llmLogs.all')}</option>
              <option value="success">{t('common.success')}</option>
              <option value="error">{t('common.failed')}</option>
            </select>
          </div>
        </div>
        <div className="flex items-center gap-2 mt-4">
          <button
            onClick={applyFilters}
            className="btn-primary text-sm"
          >
            {t('llmLogs.applyFilter')}
          </button>
          <button
            onClick={resetFilters}
            className="btn-secondary text-sm"
          >
            {t('llmLogs.reset')}
          </button>
          <button
            onClick={fetchLogs}
            className="inline-flex items-center gap-1 px-3 py-1.5 text-sm text-gray-600 hover:text-gray-700 hover:bg-gray-100 rounded-md transition-colors"
          >
            <RefreshCw className="h-4 w-4" />
            {t('llmLogs.refresh')}
          </button>
        </div>
      </div>

      {/* Logs Table */}
      <div className="card overflow-hidden">
        {loading ? (
          <div className="flex justify-center py-12">
            <div className="animate-spin h-6 w-6 border-2 border-primary-600 border-t-transparent rounded-full" />
          </div>
        ) : logs.length === 0 ? (
          <div className="text-center py-12 text-gray-500">
            <ScrollText className="h-12 w-12 mx-auto mb-3 text-gray-300" />
            <p>{t('llmLogs.noLogs')}</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('llmLogs.timestamp')}</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('llmLogs.llmProvider')}</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('llmLogs.model')}</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('llmLogs.taskType')}</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('common.status')}</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('llmLogs.proxy')}</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('llmLogs.duration')}</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('llmLogs.promptPreview')}</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('common.actions')}</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {logs.map((log) => (
                  <tr key={log.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-600">
                      {formatDate(log.created_at)}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-900">
                      {log.provider}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-600">
                      {log.model}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-600">
                      {getTaskTypeLabel(log.task_type)}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      {getStatusBadge(log.status)}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-600">
                      {log.used_proxy ? t('llmLogs.yes') : t('llmLogs.no')}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-600">
                      {log.duration ? `${log.duration.toFixed(2)}s` : '-'}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600 max-w-[150px]">
                      <div className="truncate" title={log.user_prompt}>
                        {truncateText(log.user_prompt, 50)}
                      </div>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-sm">
                      <button
                        onClick={() => setSelectedLog(log)}
                        className="text-primary-600 hover:text-primary-700 inline-flex items-center gap-1"
                      >
                        <Eye className="h-4 w-4" />
                        {t('llmLogs.viewDetails')}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination */}
        {pagination.total_pages > 0 && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-gray-200">
            <div className="text-sm text-gray-500">
              {t('llmLogs.pagination', { total: pagination.total, page: pagination.page, totalPages: pagination.total_pages })}
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setPagination(prev => ({ ...prev, page: prev.page - 1 }))}
                disabled={pagination.page <= 1}
                className="p-2 text-gray-600 hover:bg-gray-100 rounded disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              <button
                onClick={() => setPagination(prev => ({ ...prev, page: prev.page + 1 }))}
                disabled={pagination.page >= pagination.total_pages}
                className="p-2 text-gray-600 hover:bg-gray-100 rounded disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Detail Modal */}
      {selectedLog && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg w-full max-w-4xl max-h-[90vh] overflow-hidden flex flex-col">
            <div className="flex items-center justify-between px-6 py-4 border-b">
              <div>
                <h3 className="text-lg font-semibold text-gray-900">{t('llmLogs.logDetails')}</h3>
                <p className="text-sm text-gray-500">{formatDate(selectedLog.created_at)}</p>
              </div>
              <button
                onClick={() => {
                  setSelectedLog(null);
                  setActivePromptTab('user');
                }}
                className="p-1 text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-6 space-y-4">
              <div className="flex items-center gap-4 text-sm">
                <span className="text-gray-500">{t('llmLogs.provider')}:</span>
                <span className="font-medium">{selectedLog.provider}</span>
                <span className="text-gray-500">{t('llmLogs.model')}:</span>
                <span className="font-medium">{selectedLog.model}</span>
                <span className="text-gray-500">{t('llmLogs.task')}:</span>
                <span className="font-medium">{getTaskTypeLabel(selectedLog.task_type)}</span>
                <span>{getStatusBadge(selectedLog.status)}</span>
                <span className="text-gray-500">{t('llmLogs.proxy')}:</span>
                <span className="font-medium">{selectedLog.used_proxy ? t('llmLogs.yes') : t('llmLogs.no')}</span>
                <span className="text-gray-500">{t('llmLogs.duration')}:</span>
                <span className="font-medium">
                  {selectedLog.duration ? `${selectedLog.duration.toFixed(2)}s` : '-'}
                </span>
              </div>
              
              {selectedLog.error_message && (
                <div className="bg-red-50 border border-red-200 rounded-lg p-4">
                  <h4 className="text-sm font-medium text-red-700 mb-2">{t('llmLogs.errorMessage')}</h4>
                  <pre className="text-sm text-red-600 whitespace-pre-wrap">{selectedLog.error_message}</pre>
                </div>
              )}

              {/* Tab 切换 */}
              <div className="flex border-b border-gray-200">
                <button
                  onClick={() => setActivePromptTab('system')}
                  className={`px-4 py-2 text-sm font-medium transition-colors ${
                    activePromptTab === 'system'
                      ? 'text-blue-600 border-b-2 border-blue-600 bg-blue-50'
                      : 'text-gray-600 hover:bg-gray-50'
                  }`}
                >
                  System Prompt
                </button>
                <button
                  onClick={() => setActivePromptTab('user')}
                  className={`px-4 py-2 text-sm font-medium transition-colors ${
                    activePromptTab === 'user'
                      ? 'text-blue-600 border-b-2 border-blue-600 bg-blue-50'
                      : 'text-gray-600 hover:bg-gray-50'
                  }`}
                >
                  User Prompt
                </button>
                {selectedLog.response && (
                  <button
                    onClick={() => setActivePromptTab('response')}
                    className={`px-4 py-2 text-sm font-medium transition-colors ${
                      activePromptTab === 'response'
                        ? 'text-blue-600 border-b-2 border-blue-600 bg-blue-50'
                        : 'text-gray-600 hover:bg-gray-50'
                    }`}
                  >
                    {t('llmLogs.llmResponse')}
                  </button>
                )}
              </div>

              {/* Tab 内容 */}
              <div className="bg-gray-50 rounded-lg p-4">
                {activePromptTab === 'system' && (
                  <pre className="text-sm text-gray-700 whitespace-pre-wrap overflow-x-auto">
                    {selectedLog.system_prompt || '-'}
                  </pre>
                )}
                {activePromptTab === 'user' && (
                  <pre className="text-sm text-gray-700 whitespace-pre-wrap overflow-x-auto">
                    {selectedLog.user_prompt}
                  </pre>
                )}
                {activePromptTab === 'response' && selectedLog.response && (
                  <pre className="text-sm text-gray-700 whitespace-pre-wrap overflow-x-auto max-h-96">
                    {selectedLog.response}
                  </pre>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
