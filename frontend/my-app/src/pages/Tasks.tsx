import { useState, useEffect } from 'react';
import { 
  ListTodo, 
  Loader2, 
  CheckCircle, 
  XCircle, 
  Clock,
  RefreshCw,
  Trash2,
  Image as ImageIcon,
  Film,
  User,
  AlertCircle,
  Play,
  ChevronDown,
  ChevronUp,
  Terminal,
  Code,
  X,
  Square
} from 'lucide-react';
import ComfyUIStatus from '../components/ComfyUIStatus';
import JSONEditor from '../components/JSONEditor';
import type { Task } from '../types';
import { toast } from '../stores/toastStore';
import { useTranslation } from '../stores/i18nStore';

const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';

// 图片预览弹层组件
interface ImagePreviewModalProps {
  imageUrl: string;
  onClose: () => void;
}

function ImagePreviewModal({ imageUrl, onClose }: ImagePreviewModalProps) {
  const { t } = useTranslation();
  const [info, setInfo] = useState<{width: number, height: number, size?: string} | null>(null);

  useEffect(() => {
    // 获取图片尺寸
    const img = new Image();
    img.onload = () => {
      setInfo(prev => ({ ...prev, width: img.naturalWidth, height: img.naturalHeight }));
    };
    img.src = imageUrl;

    // 获取文件大小
    fetch(imageUrl, { method: 'HEAD' })
      .then(res => {
        const contentLength = res.headers.get('content-length');
        if (contentLength) {
          const size = parseInt(contentLength);
          const sizeStr = size > 1024 * 1024 
            ? `${(size / 1024 / 1024).toFixed(2)} MB`
            : size > 1024 
              ? `${(size / 1024).toFixed(1)} KB`
              : `${size} B`;
          setInfo(prev => ({ ...prev, size: sizeStr } as any));
        }
      })
      .catch(() => {});
  }, [imageUrl]);

  return (
    <div 
      className="fixed inset-0 bg-black bg-opacity-90 flex items-center justify-center z-50 p-4"
      onClick={onClose}
    >
      <div className="relative max-w-[90vw] max-h-[90vh] flex flex-col items-center">
        <img 
          src={imageUrl} 
          alt={t('tasks.preview')} 
          className="max-w-full max-h-[80vh] object-contain rounded-lg"
          onClick={(e) => e.stopPropagation()}
        />
        
        {/* 图片信息 */}
        {info && (
          <div className="mt-3 text-white text-sm opacity-80 flex items-center gap-4">
            <span>{t('tasks.dimensions')}: {info.width} × {info.height} px</span>
            {info.size && <span>{t('tasks.size')}: {info.size}</span>}
          </div>
        )}
        
        <button
          onClick={onClose}
          className="absolute -top-10 right-0 p-2 text-white hover:text-gray-300 transition-colors"
        >
          <X className="h-6 w-6" />
        </button>
        
        <div className="mt-4 text-white text-sm opacity-60">
          {t('tasks.clickOutsideToClose')}
        </div>
      </div>
    </div>
  );
}

// 视频预览弹层组件
interface VideoPreviewModalProps {
  videoUrl: string;
  onClose: () => void;
}

function VideoPreviewModal({ videoUrl, onClose }: VideoPreviewModalProps) {
  const { t } = useTranslation();
  return (
    <div 
      className="fixed inset-0 bg-black bg-opacity-90 flex items-center justify-center z-50 p-4"
      onClick={onClose}
    >
      <div className="relative max-w-[90vw] max-h-[90vh] flex flex-col items-center w-full">
        <video 
          src={videoUrl}
          controls
          autoPlay
          className="max-w-full max-h-[80vh] rounded-lg"
          onClick={(e) => e.stopPropagation()}
        />
        
        <button
          onClick={onClose}
          className="absolute -top-10 right-0 p-2 text-white hover:text-gray-300 transition-colors"
        >
          <X className="h-6 w-6" />
        </button>
        
        <div className="mt-4 text-white text-sm opacity-60">
          {t('tasks.clickOutsideToCloseVideo')}
        </div>
      </div>
    </div>
  );
}

export default function Tasks() {
  const { t, i18n } = useTranslation();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [filter, setFilter] = useState<'all' | 'pending' | 'running' | 'completed' | 'failed'>('all');
  const [refreshing, setRefreshing] = useState(false);
  const [expandedErrors, setExpandedErrors] = useState<Set<string>>(new Set());
  const [viewingWorkflow, setViewingWorkflow] = useState<Task | null>(null);
  const [workflowData, setWorkflowData] = useState<{workflow: any, prompt: string} | null>(null);
  const [loadingWorkflow, setLoadingWorkflow] = useState(false);
  const [previewImage, setPreviewImage] = useState<string | null>(null);
  const [imageInfo, setImageInfo] = useState<Record<string, {width: number, height: number, size?: string}>>({});
  const [previewVideo, setPreviewVideo] = useState<string | null>(null);  // 视频预览弹窗

  // 获取图片信息（尺寸和大小）
  const fetchImageInfo = async (url: string, taskId: string) => {
    try {
      // 获取图片尺寸
      const img = new Image();
      img.onload = () => {
        setImageInfo(prev => ({
          ...prev,
          [taskId]: {
            ...prev[taskId],
            width: img.naturalWidth,
            height: img.naturalHeight
          }
        }));
      };
      img.src = url;
      
      // 尝试获取文件大小
      const response = await fetch(url, { method: 'HEAD' });
      const contentLength = response.headers.get('content-length');
      if (contentLength) {
        const size = parseInt(contentLength);
        const sizeStr = size > 1024 * 1024 
          ? `${(size / 1024 / 1024).toFixed(2)} MB`
          : size > 1024 
            ? `${(size / 1024).toFixed(1)} KB`
            : `${size} B`;
        setImageInfo(prev => ({
          ...prev,
          [taskId]: {
            ...prev[taskId],
            size: sizeStr
          }
        }));
      }
    } catch (e) {
      console.log('Failed to fetch image info:', e);
    }
  };

  useEffect(() => {
    fetchTasks();
    // 自动刷新
    const interval = setInterval(fetchTasks, 3000);
    return () => clearInterval(interval);
  }, []);  // 移除 filter 依赖，始终获取全部任务

  // 获取所有任务（用于统计和列表显示）
  const fetchTasks = async () => {
    try {
      // 始终获取所有任务，确保统计数字正确
      const res = await fetch(`${API_BASE}/tasks/?limit=1000`);
      const data = await res.json();
      if (data.success) {
        setTasks(data.data || []);
      }
    } catch (error) {
      console.error('获取任务失败:', error);
    } finally {
      setIsLoading(false);
      setRefreshing(false);
    }
  };

  const handleRefresh = () => {
    setRefreshing(true);
    fetchTasks();
  };

  const handleDelete = async (taskId: string) => {
    if (!confirm(t('tasks.confirmDelete'))) return;
    
    try {
      await fetch(`${API_BASE}/tasks/${taskId}/`, { method: 'DELETE' });
      setTasks(tasks.filter(t => t.id !== taskId));
    } catch (error) {
      console.error('删除失败:', error);
    }
  };

  const handleCancelAll = async () => {
    const activeCount = tasks.filter(t => t.status === 'pending' || t.status === 'running').length;
    if (activeCount === 0) {
      toast.info(t('tasks.noTasksToTerminate'));
      return;
    }
    
    if (!confirm(t('tasks.confirmTerminateAll', { count: activeCount }))) return;
    
    try {
      const res = await fetch(`${API_BASE}/tasks/cancel-all/`, { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        toast.success(t('tasks.terminateSuccess', { message: data.message }));
        fetchTasks();
      } else {
        toast.error(data.message || t('tasks.terminateFailed'));
      }
    } catch (error) {
      console.error('终止任务失败:', error);
      toast.error(t('tasks.terminateFailed'));
    }
  };

  const toggleErrorDetail = (taskId: string) => {
    setExpandedErrors(prev => {
      const newSet = new Set(prev);
      if (newSet.has(taskId)) {
        newSet.delete(taskId);
      } else {
        newSet.add(taskId);
      }
      return newSet;
    });
  };

  const handleViewWorkflow = async (task: Task) => {
    if (!task.hasWorkflowJson && !task.hasPromptText) {
      toast.info(t('tasks.noWorkflowInfo'));
      return;
    }
    
    setViewingWorkflow(task);
    setLoadingWorkflow(true);
    
    try {
      const res = await fetch(`${API_BASE}/tasks/${task.id}/workflow/`);
      const data = await res.json();
      if (data.success) {
        setWorkflowData(data.data);
      } else {
        toast.error(data.message || t('tasks.failedToGetWorkflow'));
      }
    } catch (error) {
      console.error('获取工作流失败:', error);
      toast.error(t('tasks.failedToGetWorkflow'));
    } finally {
      setLoadingWorkflow(false);
    }
  };

  const handleRetry = async (taskId: string) => {
    try {
      const res = await fetch(`${API_BASE}/tasks/${taskId}/retry/`, { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        toast.success(t('tasks.taskRestarted'));
        fetchTasks();
      }
    } catch (error) {
      console.error('重试失败:', error);
    }
  };

  const getTaskIcon = (type: Task['type']) => {
    switch (type) {
      case 'character_portrait':
        return <User className="h-5 w-5" />;
      case 'shot_image':
        return <ImageIcon className="h-5 w-5" />;
      case 'shot_video':
      case 'chapter_video':
      case 'transition_video':
        return <Film className="h-5 w-5" />;
      default:
        return <ListTodo className="h-5 w-5" />;
    }
  };

  const getTaskTypeName = (type: Task['type']) => {
    const names: Record<string, string> = {
      'character_portrait': t('tasks.types.characterPortrait'),
      'shot_image': t('tasks.types.shotImage'),
      'shot_video': t('tasks.types.shotVideo'),
      'chapter_video': t('tasks.types.chapterVideo'),
      'transition_video': t('tasks.types.transitionVideo'),
    };
    return names[type] || type;
  };

  const getWorkflowDisplayName = (task: Task): string => {
    if (!task.workflowName) return '';
    if (task.workflowIsSystem) {
      return t(`tasks.workflowNames.${task.workflowName}`, { defaultValue: task.workflowName });
    }
    return task.workflowName;
  };

  // 将中文"镜X"转换为对应语言的"Shot X"
  const convertShotName = (name: string): string => {
    // 匹配"镜数字"格式（如"镜4"）
    return name.replace(/镜(\d+)/g, (match, num) => {
      return `${t('workflow.shot', { defaultValue: 'Shot' })}${num}`;
    });
  };

  // 解析任务名称，提取变量并翻译
  const getTaskDisplayName = (task: Task): string => {
    // 尝试从中文格式中提取名称
    const charMatch = task.name.match(/生成角色形象:\s*(.+)/);
    if (charMatch) {
      return t('tasks.taskNames.characterPortrait', { name: charMatch[1] });
    }
    // 匹配"生成分镜图:"或"生成分镜视频:"格式
    const shotMatch = task.name.match(/生成分镜(图|视频|图片):\s*(.+)/);
    if (shotMatch) {
      const type = shotMatch[1] === '视频' ? 'shotVideo' : 'shotImage';
      const shotName = convertShotName(shotMatch[2]);
      return t(`tasks.taskNames.${type}`, { name: shotName });
    }
    const transMatch = task.name.match(/生成转场视频:\s*分镜\s*(\d+)\s*→\s*分镜\s*(\d+)/);
    if (transMatch) {
      return t('tasks.taskNames.transitionVideo', { from: transMatch[1], to: transMatch[2] });
    }
    // 默认返回原名
    return task.name;
  };

  // 解析任务描述，提取变量并翻译
  const getTaskDisplayDescription = (task: Task): string => {
    if (!task.description) return '';
    // 尝试从中文格式中提取名称
    const charMatch = task.description.match(/为角色\s*['"](.+)['"]\s*生成人设图/);
    if (charMatch) {
      return t('tasks.taskDescriptions.characterPortrait', { name: charMatch[1] });
    }
    // 匹配"为章节 'xxx' 的分镜 x 生成图片"格式
    const shotImgMatch = task.description.match(/为章节\s*['"](.+)['"]\s*的分镜\s*(\d+)\s*生成图片/);
    if (shotImgMatch) {
      return t('tasks.taskDescriptions.shotImage', { name: `Shot ${shotImgMatch[2]}` });
    }
    // 匹配"为分镜 'xxx' 生成图片"格式
    const shotImgMatch2 = task.description.match(/为分镜\s*['"](.+)['"]\s*生成图片/);
    if (shotImgMatch2) {
      return t('tasks.taskDescriptions.shotImage', { name: shotImgMatch2[1] });
    }
    // 匹配"为章节 'xxx' 的分镜 x 生成视频"格式
    const shotVidMatch = task.description.match(/为章节\s*['"](.+)['"]\s*的分镜\s*(\d+)\s*生成视频/);
    if (shotVidMatch) {
      return t('tasks.taskDescriptions.shotVideo', { name: `Shot ${shotVidMatch[2]}` });
    }
    // 匹配"为分镜 'xxx' 生成视频"格式
    const shotVidMatch2 = task.description.match(/为分镜\s*['"](.+)['"]\s*生成视频/);
    if (shotVidMatch2) {
      return t('tasks.taskDescriptions.shotVideo', { name: shotVidMatch2[1] });
    }
    const transMatch = task.description.match(/生成从分镜\s*(\d+)\s*到\s*(\d+)\s*的转场视频/);
    if (transMatch) {
      return t('tasks.taskDescriptions.transitionVideo', { from: transMatch[1], to: transMatch[2] });
    }
    // 默认返回原描述
    return task.description;
  };

  // 格式化日期为 YYYY/MM/DD HH:mm:ss
  const formatDate = (dateStr: string) => {
    if (!dateStr) return '-';
    // 后端返回的是带时区的时间（如 2026-02-18T11:14:37+08:00）
    // 先解析为 Date 对象（自动处理时区转换为本地时间）
    const date = new Date(dateStr);
    if (isNaN(date.getTime())) return '-';
    
    // 转换为指定时区的时间字符串
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

  const getStatusIcon = (status: Task['status']) => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="h-5 w-5 text-green-600" />;
      case 'failed':
        return <XCircle className="h-5 w-5 text-red-600" />;
      case 'running':
        return <Loader2 className="h-5 w-5 text-blue-600 animate-spin" />;
      case 'pending':
        return <Clock className="h-5 w-5 text-yellow-600" />;
      default:
        return <AlertCircle className="h-5 w-5 text-gray-400" />;
    }
  };

  const getStatusText = (status: Task['status']) => {
    const texts: Record<string, string> = {
      'pending': t('tasks.pending'),
      'running': t('tasks.running'),
      'completed': t('tasks.completed'),
      'failed': t('tasks.failed'),
    };
    return texts[status] || status;
  };

  const getStatusColor = (status: Task['status']) => {
    switch (status) {
      case 'completed':
        return 'bg-green-50 text-green-700 border-green-200';
      case 'failed':
        return 'bg-red-50 text-red-700 border-red-200';
      case 'running':
        return 'bg-blue-50 text-blue-700 border-blue-200';
      case 'pending':
        return 'bg-yellow-50 text-yellow-700 border-yellow-200';
      default:
        return 'bg-gray-50 text-gray-700 border-gray-200';
    }
  };

  const stats = {
    all: tasks.length,
    pending: tasks.filter(t => t.status === 'pending').length,
    running: tasks.filter(t => t.status === 'running').length,
    completed: tasks.filter(t => t.status === 'completed').length,
    failed: tasks.filter(t => t.status === 'failed').length,
  };

  // 前端筛选任务列表
  const filteredTasks = filter === 'all' 
    ? tasks 
    : tasks.filter(t => t.status === filter);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{t('tasks.title')}</h1>
          <p className="mt-1 text-sm text-gray-500">
            {t('tasks.subtitle')}
          </p>
        </div>
        <div className="flex gap-2">
          {/* 终止所有任务按钮 */}
          <button
            onClick={handleCancelAll}
            disabled={stats.pending === 0 && stats.running === 0}
            className={`px-4 py-2 rounded-lg transition-colors flex items-center font-medium ${
              stats.pending === 0 && stats.running === 0
                ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
                : 'bg-red-50 text-red-600 hover:bg-red-100'
            }`}
          >
            <Square className="h-4 w-4 mr-2 fill-current" />
            {t('tasks.terminateAll')}
          </button>
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="btn-secondary"
          >
            <RefreshCw className={`h-4 w-4 mr-2 ${refreshing ? 'animate-spin' : ''}`} />
            {t('common.refresh')}
          </button>
        </div>
      </div>

      {/* ComfyUI Status */}
      <ComfyUIStatus />

      {/* Stats */}
      <div className="grid grid-cols-5 gap-4">
        {[
          { key: 'all', label: t('tasks.allTasks'), color: 'bg-gray-100' },
          { key: 'pending', label: t('tasks.pending'), color: 'bg-yellow-100 text-yellow-800' },
          { key: 'running', label: t('tasks.running'), color: 'bg-blue-100 text-blue-800' },
          { key: 'completed', label: t('tasks.completed'), color: 'bg-green-100 text-green-800' },
          { key: 'failed', label: t('tasks.failed'), color: 'bg-red-100 text-red-800' },
        ].map((stat) => (
          <button
            key={stat.key}
            onClick={() => setFilter(stat.key as any)}
            className={`p-4 rounded-lg text-center transition-all ${
              filter === stat.key 
                ? 'ring-2 ring-primary-500 ' + stat.color 
                : 'bg-gray-50 hover:bg-gray-100'
            }`}
          >
            <p className="text-2xl font-bold">{stats[stat.key as keyof typeof stats]}</p>
            <p className="text-sm text-gray-600">{stat.label}</p>
          </button>
        ))}
      </div>

      {/* Task List */}
      <div className="card">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">{t('tasks.taskList')}</h2>
        
        {isLoading ? (
          <div className="flex justify-center py-12">
            <Loader2 className="h-8 w-8 animate-spin text-primary-600" />
          </div>
        ) : filteredTasks.length === 0 ? (
          <div className="text-center py-12">
            <ListTodo className="mx-auto h-12 w-12 text-gray-300" />
            <h3 className="mt-4 text-lg font-medium text-gray-900">{t('tasks.noTasks')}</h3>
            <p className="mt-1 text-sm text-gray-500">
              {filter === 'all' ? t('tasks.noTasksCreated') : t('tasks.noTasksInStatus')}
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {filteredTasks.map((task) => (
              <div
                key={task.id}
                className={`p-4 rounded-lg border ${getStatusColor(task.status)} transition-all hover:shadow-md`}
              >
                <div className="flex items-start gap-4">
                  {/* Icon */}
                  <div className="p-2 bg-white rounded-lg shadow-sm">
                    {getTaskIcon(task.type)}
                  </div>
                  
                  {/* Content */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <h3 className="font-medium text-gray-900">{getTaskDisplayName(task)}</h3>
                      <span className="text-xs px-2 py-0.5 bg-white rounded-full">
                        {getTaskTypeName(task.type)}
                      </span>
                      {task.workflowName && (
                        <span className="text-xs px-2 py-0.5 bg-blue-100 text-blue-700 rounded-full" title={t('tasks.workflowUsed')}>
                          📋 {getWorkflowDisplayName(task)}
                        </span>
                      )}
                    </div>
                    
                    {task.description && (
                      <p className="text-sm mt-1 opacity-80">{getTaskDisplayDescription(task)}</p>
                    )}
                    
                    {/* Novel Name */}
                    {task.novelName && (
                      <p className="text-xs mt-2">
                        <span className="px-2 py-0.5 bg-purple-100 text-purple-700 rounded-full">
                          📖 {task.novelName}
                        </span>
                      </p>
                    )}
                    
                    {/* Progress */}
                    {task.status === 'running' && (
                      <div className="mt-2">
                        <div className="flex items-center justify-between text-xs mb-1">
                          <span>{task.currentStep || '处理中...'}</span>
                          <span>{task.progress}%</span>
                        </div>
                        <div className="h-2 bg-white rounded-full overflow-hidden">
                          <div 
                            className="h-full bg-primary-500 transition-all duration-500"
                            style={{ width: `${task.progress}%` }}
                          />
                        </div>
                      </div>
                    )}
                    
                    {/* Error Message */}
                    {task.status === 'failed' && task.errorMessage && (
                      <div className="mt-2">
                        <div 
                          className="p-2 bg-red-100 rounded text-xs text-red-700 flex items-start gap-2 cursor-pointer hover:bg-red-200 transition-colors"
                          onClick={() => toggleErrorDetail(task.id)}
                        >
                          <Terminal className="h-4 w-4 flex-shrink-0 mt-0.5" />
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center justify-between">
                              <span className="font-medium">{t('tasks.error')}: {task.errorMessage.slice(0, 100)}{task.errorMessage.length > 100 ? '...' : ''}</span>
                              {task.errorMessage.length > 100 && (
                                <span className="text-red-500 ml-2 flex-shrink-0">
                                  {expandedErrors.has(task.id) ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                                </span>
                              )}
                            </div>
                            {expandedErrors.has(task.id) && task.errorMessage.length > 100 && (
                              <div className="mt-2 p-2 bg-red-50 rounded border border-red-200 font-mono whitespace-pre-wrap break-all">
                                {task.errorMessage}
                              </div>
                            )}
                          </div>
                        </div>
                        {task.errorMessage.includes('ComfyUI') && (
                          <p className="text-xs text-red-600 mt-1 ml-6">
                            {t('tasks.comfyuiHint')}
                          </p>
                        )}
                      </div>
                    )}
                    
                    {/* Result */}
                    {task.status === 'completed' && task.resultUrl && (
                      <div className="mt-2">
                        {task.type === 'character_portrait' || task.type === 'shot_image' || task.type === 'scene_image' ? (
                          <div>
                            <div className="relative group inline-block">
                              <img 
                                src={task.resultUrl} 
                                alt={t('tasks.generatedResult')} 
                                className="h-32 w-auto object-contain rounded-lg border border-gray-200 cursor-pointer hover:shadow-lg transition-shadow bg-gray-50"
                                onClick={() => task.resultUrl && setPreviewImage(task.resultUrl)}
                                onLoad={() => task.resultUrl && fetchImageInfo(task.resultUrl, task.id)}
                                onError={(e) => {
                                  (e.target as HTMLImageElement).src = '';
                                  (e.target as HTMLImageElement).className = 'hidden';
                                }}
                              />
                              <div className="absolute inset-0 bg-black bg-opacity-0 group-hover:bg-opacity-30 transition-all rounded-lg flex items-center justify-center opacity-0 group-hover:opacity-100 cursor-pointer"
                                   onClick={() => task.resultUrl && setPreviewImage(task.resultUrl)}>
                                <span className="text-white text-xs font-medium">{t('tasks.viewOriginal')}</span>
                              </div>
                            </div>
                            {/* 图片信息 */}
                            {imageInfo[task.id] && (
                              <div className="mt-1 text-xs text-gray-500">
                                {imageInfo[task.id].width && (
                                  <span>{imageInfo[task.id].width} × {imageInfo[task.id].height} px</span>
                                )}
                                {imageInfo[task.id].size && (
                                  <span className="ml-2">· {imageInfo[task.id].size}</span>
                                )}
                              </div>
                            )}
                          </div>
                        ) : task.type === 'shot_video' || task.type === 'chapter_video' || task.type === 'transition_video' ? (
                          <button
                            onClick={() => task.resultUrl && setPreviewVideo(task.resultUrl)}
                            className="text-sm underline inline-flex items-center gap-1 text-green-600 hover:text-green-700"
                          >
                            <Play className="h-3 w-3" />
                            {t('tasks.viewResult')}
                          </button>
                        ) : (
                          <a 
                            href={task.resultUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-sm underline inline-flex items-center gap-1"
                          >
                            {t('tasks.viewResult')}
                          </a>
                        )}
                      </div>
                    )}
                    
                    {/* Meta */}
                    <div className="mt-2 text-xs opacity-60">
                      {t('common.createdAt')}: {formatDate(task.createdAt)}
                      {task.completedAt && ` · ${t('tasks.completedAt')}: ${formatDate(task.completedAt)}`}
                    </div>
                  </div>
                  
                  {/* Actions */}
                  <div className="flex items-center gap-2">
                    {getStatusIcon(task.status)}
                    <span className="text-sm font-medium min-w-[60px]">
                      {getStatusText(task.status)}
                    </span>
                    
                    {task.status === 'failed' && (
                      <button
                        onClick={() => handleRetry(task.id)}
                        className="p-2 text-gray-400 hover:text-primary-600 transition-colors"
                        title={t('tasks.retry')}
                      >
                        <Play className="h-4 w-4" />
                      </button>
                    )}
                    
                    {(task.hasWorkflowJson || task.hasPromptText) && (
                      <button
                        onClick={() => handleViewWorkflow(task)}
                        className="p-2 text-gray-400 hover:text-blue-600 transition-colors"
                        title={t('tasks.viewWorkflow')}
                      >
                        <Code className="h-4 w-4" />
                      </button>
                    )}
                    
                    <button
                      onClick={() => handleDelete(task.id)}
                      className="p-2 text-gray-400 hover:text-red-600 transition-colors"
                      title={t('common.delete')}
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Image Preview Modal */}
      {previewImage && (
        <ImagePreviewModal 
          imageUrl={previewImage} 
          onClose={() => setPreviewImage(null)} 
        />
      )}

      {/* Video Preview Modal */}
      {previewVideo && (
        <VideoPreviewModal 
          videoUrl={previewVideo} 
          onClose={() => setPreviewVideo(null)} 
        />
      )}

      {/* Workflow View Modal */}
      {viewingWorkflow && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg p-6 w-full max-w-4xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-gray-900">
                {t('tasks.workflowDetails')}
                <span className="ml-2 text-sm font-normal text-gray-500">
                  {(() => {
                    // Try to extract the actual name from the task name (format: "action: name")
                    const nameMatch = viewingWorkflow.name.match(/^[^:]+:\s*(.+)$/);
                    const actualName = nameMatch ? nameMatch[1] : viewingWorkflow.name;
                    // Convert Chinese "镜X" to localized "Shot X"
                    const localizedName = convertShotName(actualName);
                    // Use task type for localization
                    switch (viewingWorkflow.type) {
                      case 'character_portrait':
                        return t('tasks.taskNames.characterPortrait', { name: localizedName });
                      case 'shot_image':
                        return t('tasks.taskNames.shotImage', { name: localizedName });
                      case 'shot_video':
                        return t('tasks.taskNames.shotVideo', { name: localizedName });
                      case 'transition_video':
                        return t('tasks.taskNames.transitionVideo', { from: localizedName, to: '' });
                      case 'chapter_video':
                        return t('tasks.taskNames.chapterVideo', { name: localizedName });
                      default:
                        return viewingWorkflow.name;
                    }
                  })()}
                </span>
              </h3>
              <button
                onClick={() => {
                  setViewingWorkflow(null);
                  setWorkflowData(null);
                }}
                className="p-1 text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            
            {loadingWorkflow ? (
              <div className="flex justify-center py-12">
                <Loader2 className="h-8 w-8 animate-spin text-primary-600" />
              </div>
            ) : workflowData ? (
              <div className="space-y-4">
                {/* Prompt Section */}
                <div>
                  <h4 className="text-sm font-medium text-gray-700 mb-2">{t('tasks.generationPrompt')}</h4>
                  <div className="bg-gray-50 p-3 rounded-lg border border-gray-200">
                    <p className="text-sm text-gray-600 font-mono whitespace-pre-wrap break-all">
                      {workflowData.prompt}
                    </p>
                  </div>
                </div>
                
                {/* Workflow JSON Section */}
                {workflowData.workflow && (
                  <div>
                    <h4 className="text-sm font-medium text-gray-700 mb-2">{t('tasks.workflowJSON')}</h4>
                    <div className="border border-gray-200 rounded-lg overflow-hidden">
                      <JSONEditor
                        value={typeof workflowData.workflow === 'string' 
                          ? workflowData.workflow 
                          : JSON.stringify(workflowData.workflow, null, 2)}
                        onChange={() => {}}
                        readOnly={true}
                        height="50vh"
                      />
                    </div>
                  </div>
                )}
                
                <div className="flex justify-end pt-4">
                  <button
                    onClick={() => {
                      setViewingWorkflow(null);
                      setWorkflowData(null);
                    }}
                    className="btn-secondary"
                  >
                    {t('common.close')}
                  </button>
                </div>
              </div>
            ) : (
              <div className="text-center py-8 text-gray-500">
                {t('tasks.failedToLoadWorkflow')}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
