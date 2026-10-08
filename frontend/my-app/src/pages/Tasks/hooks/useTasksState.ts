import { useState, useCallback } from 'react';
import { useSerialPolling } from '../../../hooks/useSerialPolling';
import { useTranslation } from '../../../stores/i18nStore';
import { toast } from '../../../stores/toastStore';
import { taskApi } from '../../../api/tasks';
import type { Task, VideoDirectorTaskClip } from '../../../types';
import type { TaskFilter, TaskTypeFilter, ImageInfo, WorkflowData, TaskStats } from '../types';

export function useTasksState({ page = 1, pageSize = 30 } = {}) {
  const { t } = useTranslation();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [filter, setFilter] = useState<TaskFilter>('all');
  const [typeFilter, setTypeFilter] = useState<TaskTypeFilter>('all');
  const [refreshing, setRefreshing] = useState(false);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [taskTypes, setTaskTypes] = useState<string[]>([]);
  const [stats, setStats] = useState<TaskStats>({ all: 0, pending: 0, running: 0, completed: 0, failed: 0, cancelled: 0 });
  const [expandedErrors, setExpandedErrors] = useState<Set<string>>(new Set());
  const [viewingWorkflow, setViewingWorkflow] = useState<Task | null>(null);
  const [workflowData, setWorkflowData] = useState<WorkflowData | null>(null);
  const [loadingWorkflow, setLoadingWorkflow] = useState(false);
  const [previewImage, setPreviewImage] = useState<string | null>(null);
  const [previewImages, setPreviewImages] = useState<Array<{ label?: string; url: string }>>([]);
  const [previewImageIndex, setPreviewImageIndex] = useState(0);
  const [imageInfo, setImageInfo] = useState<Record<string, ImageInfo>>({});
  const [previewVideo, setPreviewVideo] = useState<string | null>(null);

  const openImagePreview = (url: string) => {
    setPreviewImages([{ url }]);
    setPreviewImageIndex(0);
    setPreviewImage(url);
  };

  const openImageGallery = (images: Array<{ label?: string; url: string }>, index: number) => {
    const validImages = images.filter(image => image.url);
    if (!validImages.length) return;
    const safeIndex = Math.max(0, Math.min(index, validImages.length - 1));
    setPreviewImages(validImages);
    setPreviewImageIndex(safeIndex);
    setPreviewImage(validImages[safeIndex].url);
  };

  const navigatePreviewImage = (direction: 'prev' | 'next') => {
    if (previewImages.length <= 1) return;
    const nextIndex = direction === 'prev'
      ? (previewImageIndex === 0 ? previewImages.length - 1 : previewImageIndex - 1)
      : (previewImageIndex === previewImages.length - 1 ? 0 : previewImageIndex + 1);
    setPreviewImageIndex(nextIndex);
    setPreviewImage(previewImages[nextIndex].url);
  };

  const closeImagePreview = () => {
    setPreviewImage(null);
    setPreviewImages([]);
    setPreviewImageIndex(0);
  };

  const fetchImageInfo = async (url: string, taskId: string) => {
    try {
      const img = new Image();
      img.onload = () => {
        setImageInfo(prev => ({
          ...prev,
          [taskId]: { ...prev[taskId], width: img.naturalWidth, height: img.naturalHeight }
        }));
      };
      img.src = url;

      const response = await fetch(url, { method: 'HEAD' });
      const contentLength = response.headers.get('content-length');
      if (contentLength) {
        const size = parseInt(contentLength);
        const sizeStr = size > 1024 * 1024
          ? `${(size / 1024 / 1024).toFixed(2)} MB`
          : size > 1024 ? `${(size / 1024).toFixed(1)} KB` : `${size} B`;
        setImageInfo(prev => ({
          ...prev,
          [taskId]: { ...prev[taskId], size: sizeStr }
        }));
      }
    } catch (e) {
      console.log('Failed to fetch image info:', e);
    }
  };

  const fetchPage = useCallback((signal: AbortSignal) =>
    taskApi.fetchPage(page, pageSize, filter, typeFilter, signal), [page, pageSize, filter, typeFilter]);

  const fetchTasks = useSerialPolling({
    fetch: fetchPage,
    intervalMs: 3000,
    onSuccess: result => {
      if (!result.success || !result.data) throw new Error(result.message || '获取任务失败');
      setTasks(result.data.items as unknown as Task[]);
      setTotal(result.data.total);
      setTotalPages(Math.max(1, result.data.total_pages));
      setStats(result.data.stats);
      setTaskTypes(result.data.types);
    },
    onError: error => console.error('获取任务失败:', error),
    onSettled: () => {
      setIsLoading(false);
      setRefreshing(false);
    },
  });

  const handleRefresh = () => {
    setRefreshing(true);
    fetchTasks();
  };

  const handleDelete = async (taskId: string) => {
    if (!confirm(t('tasks.confirmDelete'))) return;
    try {
      const result = await taskApi.delete(taskId) as { success?: boolean; message?: string; detail?: string };
      if (!result.success) {
        toast.error(result.message || result.detail || t('common.deleteFailed'));
        return;
      }
      setTasks(current => current.filter(t => t.id !== taskId));
      void fetchTasks();
      toast.success(result.message || '任务已删除');
    } catch (error) {
      console.error('删除失败:', error);
      toast.error(error instanceof Error ? error.message : t('common.deleteFailed'));
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
      const data = await taskApi.cancelAll();
      if (data.success) {
        toast.success(t('tasks.terminateSuccess', { message: data.message || '' }));
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
      if (newSet.has(taskId)) newSet.delete(taskId);
      else newSet.add(taskId);
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
      const data = await taskApi.fetchWorkflow(task.id);
      if (data.success) {
        setWorkflowData(data.data as WorkflowData);
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

  const handleViewClipWorkflow = async (task: Task, clip: VideoDirectorTaskClip) => {
    if (!clip.windowIndex) {
      toast.info(t('tasks.noWorkflowInfo'));
      return;
    }
    if (!clip.hasWorkflowJson && !clip.promptText) {
      toast.info(t('tasks.noWorkflowInfo'));
      return;
    }
    setViewingWorkflow({
      ...task,
      name: `${task.name} · Clip ${clip.windowIndex}`,
      workflowName: clip.workflowName || task.workflowName,
      hasWorkflowJson: clip.hasWorkflowJson,
      hasPromptText: Boolean(clip.promptText),
      referenceImages: clip.referenceImages || [],
    });
    setLoadingWorkflow(true);
    try {
      const data = await taskApi.fetchClipWorkflow(task.id, clip.windowIndex);
      if (data.success) {
        setWorkflowData(data.data as WorkflowData);
      } else {
        toast.error(data.message || t('tasks.failedToGetWorkflow'));
      }
    } catch (error) {
      console.error('获取 Clip 工作流失败:', error);
      toast.error(t('tasks.failedToGetWorkflow'));
    } finally {
      setLoadingWorkflow(false);
    }
  };

  const handleRetry = async (taskId: string) => {
    try {
      const data = await taskApi.retry(taskId);
      if (data.success) {
        toast.success(t('tasks.taskRestarted'));
        fetchTasks();
      }
    } catch (error) {
      console.error('重试失败:', error);
    }
  };

  const filteredTasks = tasks;

  return {
    // State
    tasks,
    isLoading,
    filter,
    setFilter,
    typeFilter,
    setTypeFilter,
    refreshing,
    expandedErrors,
    viewingWorkflow,
    workflowData,
    loadingWorkflow,
    previewImage,
    previewImages,
    previewImageIndex,
    previewVideo,
    imageInfo,
    stats,
    total,
    totalPages,
    taskTypes,
    filteredTasks,
    // Actions
    fetchTasks,
    handleRefresh,
    handleDelete,
    handleCancelAll,
    toggleErrorDetail,
    handleViewWorkflow,
    handleViewClipWorkflow,
    handleRetry,
    fetchImageInfo,
    openImagePreview,
    openImageGallery,
    navigatePreviewImage,
    closeImagePreview,
    setPreviewImage,
    setPreviewVideo,
    setViewingWorkflow,
    setWorkflowData,
  };
}
