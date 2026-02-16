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

const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';

// 图片预览弹层组件
interface ImagePreviewModalProps {
  imageUrl: string;
  onClose: () => void;
}

function ImagePreviewModal({ imageUrl, onClose }: ImagePreviewModalProps) {
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
          alt="预览" 
          className="max-w-full max-h-[80vh] object-contain rounded-lg"
          onClick={(e) => e.stopPropagation()}
        />
        
        {/* 图片信息 */}
        {info && (
          <div className="mt-3 text-white text-sm opacity-80 flex items-center gap-4">
            <span>尺寸: {info.width} × {info.height} px</span>
            {info.size && <span>大小: {info.size}</span>}
          </div>
        )}
        
        <button
          onClick={onClose}
          className="absolute -top-10 right-0 p-2 text-white hover:text-gray-300 transition-colors"
        >
          <X className="h-6 w-6" />
        </button>
        
        <div className="mt-4 text-white text-sm opacity-60">
          点击图片外部关闭预览
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
          点击视频外部关闭预览
        </div>
      </div>
    </div>
  );
}

export default function Tasks() {
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
    if (!confirm('确定要删除这个任务吗？')) return;
    
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
      toast('没有需要终止的任务', 'info');
      return;
    }
    
    if (!confirm(`确定要终止所有 ${activeCount} 个进行中的任务吗？\n\n此操作不可恢复！`)) return;
    
    try {
      const res = await fetch(`${API_BASE}/tasks/cancel-all/`, { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        toast(data.message, 'success');
        fetchTasks();
      } else {
        toast(data.message || '终止任务失败', 'error');
      }
    } catch (error) {
      console.error('终止任务失败:', error);
      toast('终止任务失败', 'error');
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
      toast.info('该任务没有保存工作流信息');
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
        toast.error(data.message || '获取工作流失败');
        setViewingWorkflow(null);
      }
    } catch (error) {
      console.error('获取工作流失败:', error);
      toast.error('获取工作流失败');
      setViewingWorkflow(null);
    } finally {
      setLoadingWorkflow(false);
    }
  };

  const handleRetry = async (taskId: string) => {
    try {
      const res = await fetch(`${API_BASE}/tasks/${taskId}/retry/`, { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        toast.success('任务已重新启动');
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
      'character_portrait': '人设图生成',
      'shot_image': '分镜图生成',
      'shot_video': '视频生成',
      'chapter_video': '章节视频合成',
      'transition_video': '转场视频生成',
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

  // 前端筛选任务列表
  const filteredTasks = filter === 'all' 
    ? tasks 
    : tasks.filter(t => t.status === filter);

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
            终止所有任务
          </button>
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="btn-secondary"
          >
            <RefreshCw className={`h-4 w-4 mr-2 ${refreshing ? 'animate-spin' : ''}`} />
            刷新
          </button>
        </div>
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
        ) : filteredTasks.length === 0 ? (
          <div className="text-center py-12">
            <ListTodo className="mx-auto h-12 w-12 text-gray-300" />
            <h3 className="mt-4 text-lg font-medium text-gray-900">暂无任务</h3>
            <p className="mt-1 text-sm text-gray-500">
              {filter === 'all' ? '还没有创建任何任务' : '该状态下没有任务'}
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
                      <h3 className="font-medium text-gray-900">{task.name}</h3>
                      <span className="text-xs px-2 py-0.5 bg-white rounded-full">
                        {getTaskTypeName(task.type)}
                      </span>
                      {task.workflowName && (
                        <span className="text-xs px-2 py-0.5 bg-blue-100 text-blue-700 rounded-full" title="使用的工作流">
                          📋 {task.workflowName}
                        </span>
                      )}
                    </div>
                    
                    {task.description && (
                      <p className="text-sm mt-1 opacity-80">{task.description}</p>
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
                          <div>
                            <div className="relative group inline-block">
                              <img 
                                src={task.resultUrl} 
                                alt="生成结果" 
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
                                <span className="text-white text-xs font-medium">查看原图</span>
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
                            查看结果
                          </button>
                        ) : (
                          <a 
                            href={task.resultUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-sm underline inline-flex items-center gap-1"
                          >
                            查看结果
                          </a>
                        )}
                      </div>
                    )}
                    
                    {/* Meta */}
                    <div className="mt-2 text-xs opacity-60">
                      创建: {new Date(new Date(task.createdAt).getTime() + 8 * 60 * 60 * 1000).toLocaleString('zh-CN')}
                      {task.completedAt && ` · 完成: ${new Date(new Date(task.completedAt).getTime() + 8 * 60 * 60 * 1000).toLocaleString('zh-CN')}`}
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
                    
                    {(task.hasWorkflowJson || task.hasPromptText) && (
                      <button
                        onClick={() => handleViewWorkflow(task)}
                        className="p-2 text-gray-400 hover:text-blue-600 transition-colors"
                        title="查看提交的工作流"
                      >
                        <Code className="h-4 w-4" />
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
                任务工作流详情
                <span className="ml-2 text-sm font-normal text-gray-500">
                  {viewingWorkflow.name}
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
                  <h4 className="text-sm font-medium text-gray-700 mb-2">生成提示词</h4>
                  <div className="bg-gray-50 p-3 rounded-lg border border-gray-200">
                    <p className="text-sm text-gray-600 font-mono whitespace-pre-wrap break-all">
                      {workflowData.prompt}
                    </p>
                  </div>
                </div>
                
                {/* Workflow JSON Section */}
                {workflowData.workflow && (
                  <div>
                    <h4 className="text-sm font-medium text-gray-700 mb-2">提交给ComfyUI的工作流JSON</h4>
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
                    关闭
                  </button>
                </div>
              </div>
            ) : (
              <div className="text-center py-8 text-gray-500">
                无法加载工作流数据
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
