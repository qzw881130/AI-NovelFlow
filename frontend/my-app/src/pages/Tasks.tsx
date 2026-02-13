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
  Terminal
} from 'lucide-react';
import ComfyUIStatus from '../components/ComfyUIStatus';
import type { Task } from '../types';

const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';

export default function Tasks() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [filter, setFilter] = useState<'all' | 'pending' | 'running' | 'completed' | 'failed'>('all');
  const [refreshing, setRefreshing] = useState(false);
  const [expandedErrors, setExpandedErrors] = useState<Set<string>>(new Set());

  useEffect(() => {
    fetchTasks();
    // 自动刷新
    const interval = setInterval(fetchTasks, 3000);
    return () => clearInterval(interval);
  }, [filter]);

  const fetchTasks = async () => {
    try {
      const url = filter !== 'all' ? `${API_BASE}/tasks?status=${filter}` : `${API_BASE}/tasks`;
      const res = await fetch(url);
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
    if (!confirm('确定要删除这个任务吗？')) return;
    
    try {
      await fetch(`${API_BASE}/tasks/${taskId}`, { method: 'DELETE' });
      setTasks(tasks.filter(t => t.id !== taskId));
    } catch (error) {
      console.error('删除失败:', error);
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

  const handleRetry = async (taskId: string) => {
    try {
      const res = await fetch(`${API_BASE}/tasks/${taskId}/retry`, { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        alert('任务已重新启动');
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
        return <Film className="h-5 w-5" />;
      default:
        return <ListTodo className="h-5 w-5" />;
    }
  };

  const getTaskTypeName = (type: Task['type']) => {
    const names: Record<string, string> = {
      'character_portrait': '人设图生成',
      'shot_image': '分镜图生成',
      'shot_video': '视频生成',
      'chapter_video': '章节视频合成',
    };
    return names[type] || type;
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
      'pending': '等待中',
      'running': '运行中',
      'completed': '已完成',
      'failed': '失败',
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

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">任务队列</h1>
          <p className="mt-1 text-sm text-gray-500">
            查看和管理所有生成任务
          </p>
        </div>
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          className="btn-secondary"
        >
          <RefreshCw className={`h-4 w-4 mr-2 ${refreshing ? 'animate-spin' : ''}`} />
          刷新
        </button>
      </div>

      {/* ComfyUI Status */}
      <ComfyUIStatus />

      {/* Stats */}
      <div className="grid grid-cols-5 gap-4">
        {[
          { key: 'all', label: '全部', color: 'bg-gray-100' },
          { key: 'pending', label: '等待中', color: 'bg-yellow-100 text-yellow-800' },
          { key: 'running', label: '运行中', color: 'bg-blue-100 text-blue-800' },
          { key: 'completed', label: '已完成', color: 'bg-green-100 text-green-800' },
          { key: 'failed', label: '失败', color: 'bg-red-100 text-red-800' },
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
        <h2 className="text-lg font-semibold text-gray-900 mb-4">任务列表</h2>
        
        {isLoading ? (
          <div className="flex justify-center py-12">
            <Loader2 className="h-8 w-8 animate-spin text-primary-600" />
          </div>
        ) : tasks.length === 0 ? (
          <div className="text-center py-12">
            <ListTodo className="mx-auto h-12 w-12 text-gray-300" />
            <h3 className="mt-4 text-lg font-medium text-gray-900">暂无任务</h3>
            <p className="mt-1 text-sm text-gray-500">
              {filter === 'all' ? '还没有创建任何任务' : '该状态下没有任务'}
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {tasks.map((task) => (
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
                      <h3 className="font-medium text-gray-900">{task.name}</h3>
                      <span className="text-xs px-2 py-0.5 bg-white rounded-full">
                        {getTaskTypeName(task.type)}
                      </span>
                    </div>
                    
                    {task.description && (
                      <p className="text-sm mt-1 opacity-80">{task.description}</p>
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
                              <span className="font-medium">错误: {task.errorMessage.slice(0, 100)}{task.errorMessage.length > 100 ? '...' : ''}</span>
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
                            提示: 请检查 ComfyUI 中是否已安装所需的模型和节点
                          </p>
                        )}
                      </div>
                    )}
                    
                    {/* Result */}
                    {task.status === 'completed' && task.resultUrl && (
                      <div className="mt-2">
                        {task.type === 'character_portrait' || task.type === 'shot_image' ? (
                          <img 
                            src={task.resultUrl} 
                            alt="生成结果" 
                            className="h-20 w-20 object-cover rounded-lg"
                          />
                        ) : (
                          <a 
                            href={task.resultUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-sm underline"
                          >
                            查看结果
                          </a>
                        )}
                      </div>
                    )}
                    
                    {/* Meta */}
                    <div className="mt-2 text-xs opacity-60">
                      创建: {new Date(task.createdAt).toLocaleString()}
                      {task.completedAt && ` · 完成: ${new Date(task.completedAt).toLocaleString()}`}
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
                        title="重试"
                      >
                        <Play className="h-4 w-4" />
                      </button>
                    )}
                    
                    <button
                      onClick={() => handleDelete(task.id)}
                      className="p-2 text-gray-400 hover:text-red-600 transition-colors"
                      title="删除"
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
    </div>
  );
}
