import {
  CheckCircle, XCircle, Loader2, Clock, AlertCircle,
  Terminal, ChevronUp, ChevronDown, Play, Code, Trash2, Film, Image as ImageIcon, User, ListTodo, Music
} from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import type { Task } from '../../../types';
import type { ImageInfo } from '../types';

interface TaskCardProps {
  task: Task;
  imageInfo: Record<string, ImageInfo>;
  expandedErrors: Set<string>;
  onDelete: (id: string) => void;
  onRetry: (id: string) => void;
  onViewWorkflow: (task: Task) => void;
  onToggleError: (id: string) => void;
  onPreviewImage: (url: string) => void;
  onPreviewVideo: (url: string) => void;
  fetchImageInfo: (url: string, taskId: string) => void;
  getTaskDisplayName: (task: Task) => string;
  getTaskDisplayDescription: (task: Task) => string;
  getTaskTypeName: (type: Task['type']) => string;
  getWorkflowDisplayName: (task: Task) => string;
  getStatusIcon: (status: Task['status']) => JSX.Element;
  getStatusText: (status: Task['status']) => string;
  getStatusColor: (status: Task['status']) => string;
  formatDate: (dateStr: string) => string;
}

export function TaskCard({
  task,
  imageInfo,
  expandedErrors,
  onDelete,
  onRetry,
  onViewWorkflow,
  onToggleError,
  onPreviewImage,
  onPreviewVideo,
  fetchImageInfo,
  getTaskDisplayName,
  getTaskDisplayDescription,
  getTaskTypeName,
  getWorkflowDisplayName,
  getStatusIcon,
  getStatusText,
  getStatusColor,
  formatDate,
}: TaskCardProps) {
  const { t } = useTranslation();

  const getTaskIcon = (type: Task['type']) => {
    switch (type) {
      case 'character_portrait': return <User className="h-5 w-5" />;
      case 'prop_image': return <ImageIcon className="h-5 w-5" />;
      case 'shot_image': return <ImageIcon className="h-5 w-5" />;
      case 'keyframe_image': return <ImageIcon className="h-5 w-5" />;
      case 'character_audio':
      case 'narrator_audio': return <Music className="h-5 w-5" />;
      case 'shot_video':
      case 'chapter_video':
      case 'transition_video': return <Film className="h-5 w-5" />;
      default: return <ListTodo className="h-5 w-5" />;
    }
  };

  return (
    <div className={`p-4 rounded-lg border ${getStatusColor(task.status)} transition-all hover:shadow-md`}>
      <div className="flex items-start gap-4">
        <div className="p-2 bg-white rounded-lg shadow-sm">{getTaskIcon(task.type)}</div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="font-medium text-gray-900">{getTaskDisplayName(task)}</h3>
            <span className="text-xs px-2 py-0.5 bg-white rounded-full">{getTaskTypeName(task.type)}</span>
            {task.workflowName && (
              <span className="text-xs px-2 py-0.5 bg-blue-100 text-blue-700 rounded-full" title={t('tasks.workflowUsed')}>
                📋 {getWorkflowDisplayName(task)}
              </span>
            )}
          </div>
          {task.description && <p className="text-sm mt-1 opacity-80">{getTaskDisplayDescription(task)}</p>}
          {task.novelName && (
            <p className="text-xs mt-2">
              <span className="px-2 py-0.5 bg-purple-100 text-purple-700 rounded-full">📖 {task.novelName}</span>
            </p>
          )}
          {task.status === 'running' && (
            <div className="mt-2">
              <div className="flex items-center justify-between text-xs mb-1">
                <span>{task.currentStep || '处理中...'}</span>
                <span>{task.progress}%</span>
              </div>
              <div className="h-2 bg-white rounded-full overflow-hidden">
                <div className="h-full bg-primary-500 transition-all duration-500" style={{ width: `${task.progress}%` }} />
              </div>
            </div>
          )}
          {task.status === 'failed' && task.errorMessage && (
            <div className="mt-2">
              <div
                className="p-2 bg-red-100 rounded text-xs text-red-700 flex items-start gap-2 cursor-pointer hover:bg-red-200 transition-colors"
                onClick={() => onToggleError(task.id)}
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
                <p className="text-xs text-red-600 mt-1 ml-6">{t('tasks.comfyuiHint')}</p>
              )}
            </div>
          )}
          {task.status === 'completed' && task.resultUrl && (
            <div className="mt-2">
              {task.type === 'character_portrait' || task.type === 'shot_image' || task.type === 'scene_image' || task.type === 'prop_image' || task.type === 'keyframe_image' ? (
                <div>
                  <div className="relative group inline-block">
                    <img
                      src={task.resultUrl}
                      alt={t('tasks.generatedResult')}
                      className="h-32 w-auto object-contain rounded-lg border border-gray-200 cursor-pointer hover:shadow-lg transition-shadow bg-gray-50"
                      onClick={() => task.resultUrl && onPreviewImage(task.resultUrl)}
                      onLoad={() => task.resultUrl && fetchImageInfo(task.resultUrl, task.id)}
                      onError={(e) => {
                        (e.target as HTMLImageElement).src = '';
                        (e.target as HTMLImageElement).className = 'hidden';
                      }}
                    />
                    <div
                      className="absolute inset-0 bg-black bg-opacity-0 group-hover:bg-opacity-30 transition-all rounded-lg flex items-center justify-center opacity-0 group-hover:opacity-100 cursor-pointer"
                      onClick={() => task.resultUrl && onPreviewImage(task.resultUrl)}
                    >
                      <span className="text-white text-xs font-medium">{t('tasks.viewOriginal')}</span>
                    </div>
                  </div>
                  {imageInfo[task.id] && (
                    <div className="mt-1 text-xs text-gray-500">
                      {imageInfo[task.id].width && <span>{imageInfo[task.id].width} × {imageInfo[task.id].height} px</span>}
                      {imageInfo[task.id].size && <span className="ml-2">· {imageInfo[task.id].size}</span>}
                    </div>
                  )}
                </div>
              ) : task.type === 'shot_video' || task.type === 'chapter_video' || task.type === 'transition_video' ? (
                <div>
                  <div className="relative group inline-block cursor-pointer" onClick={() => task.resultUrl && onPreviewVideo(task.resultUrl)}>
                    <div className="h-32 w-48 bg-gray-900 rounded-lg flex items-center justify-center overflow-hidden">
                      <video src={task.resultUrl} className="w-full h-full object-cover opacity-80 group-hover:opacity-100 transition-opacity" preload="metadata" />
                      <div className="absolute inset-0 flex items-center justify-center">
                        <div className="w-12 h-12 bg-black bg-opacity-50 rounded-full flex items-center justify-center group-hover:bg-opacity-70 transition-all group-hover:scale-110">
                          <Play className="h-6 w-6 text-white ml-1" />
                        </div>
                      </div>
                    </div>
                  </div>
                  <div className="mt-1 text-xs text-gray-500">
                    <button onClick={() => task.resultUrl && onPreviewVideo(task.resultUrl)} className="text-green-600 hover:text-green-700 underline inline-flex items-center gap-1">
                      <Play className="h-3 w-3" />{t('tasks.viewResult')}
                    </button>
                  </div>
                </div>
              ) : task.type === 'character_audio' || task.type === 'narrator_audio' ? (
                <div>
                  <div className="flex items-center gap-3 p-3 bg-gray-50 rounded-lg border border-gray-200">
                    <div className="w-10 h-10 bg-purple-100 rounded-full flex items-center justify-center">
                      <Music className="h-5 w-5 text-purple-600" />
                    </div>
                    <div className="flex-1">
                      <audio
                        src={task.resultUrl}
                        controls
                        className="w-full h-8"
                        preload="metadata"
                      />
                    </div>
                  </div>
                  <div className="mt-1 text-xs text-gray-500">
                    <a href={task.resultUrl} download className="text-purple-600 hover:text-purple-700 underline inline-flex items-center gap-1">
                      {t('common.download')}
                    </a>
                  </div>
                </div>
              ) : (
                <a href={task.resultUrl} target="_blank" rel="noopener noreferrer" className="text-sm underline inline-flex items-center gap-1">
                  {t('tasks.viewResult')}
                </a>
              )}
            </div>
          )}
          <div className="mt-2 text-xs opacity-60">
            {t('common.createdAt')}: {formatDate(task.createdAt)}
            {task.completedAt && ` · ${t('tasks.completedAt')}: ${formatDate(task.completedAt)}`}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {getStatusIcon(task.status)}
          <span className="text-sm font-medium min-w-[60px]">{getStatusText(task.status)}</span>
          {task.status === 'failed' && (
            <button onClick={() => onRetry(task.id)} className="p-2 text-gray-400 hover:text-primary-600 transition-colors" title={t('tasks.retry')}>
              <Play className="h-4 w-4" />
            </button>
          )}
          {(task.hasWorkflowJson || task.hasPromptText) && (
            <button onClick={() => onViewWorkflow(task)} className="p-2 text-gray-400 hover:text-blue-600 transition-colors" title={t('tasks.viewWorkflow')}>
              <Code className="h-4 w-4" />
            </button>
          )}
          <button onClick={() => onDelete(task.id)} className="p-2 text-gray-400 hover:text-red-600 transition-colors" title={t('common.delete')}>
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
