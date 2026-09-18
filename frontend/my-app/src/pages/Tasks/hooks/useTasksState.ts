import { useState, useEffect, useCallback, useRef } from 'react';
import { useTranslation } from '../../../stores/i18nStore';
import { toast } from '../../../stores/toastStore';
import { taskApi } from '../../../api/tasks';
import type { Task, VideoDirectorTaskClip } from '../../../types';
import type { TaskFilter, TaskTypeFilter, ImageInfo, WorkflowData, TaskStats } from '../types';

export function useTasksState() {
  const { t } = useTranslation();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [filter, setFilter] = useState<TaskFilter>('all');
  const [typeFilter, setTypeFilter] = useState<TaskTypeFilter>('all');
  const [refreshing, setRefreshing] = useState(false);
  const [expandedErrors, setExpandedErrors] = useState<Set<string>>(new Set());
  const [viewingWorkflow, setViewingWorkflow] = useState<Task | null>(null);
  const [workflowData, setWorkflowData] = useState<WorkflowData | null>(null);
  const [loadingWorkflow, setLoadingWorkflow] = useState(false);
  const [workflowError, setWorkflowError] = useState('');
  const workflowRequestRef = useRef(0);
  const workflowAbortRef = useRef<AbortController|null>(null);
  const workflowTargetRef = useRef<{task:Task;clip?:VideoDirectorTaskClip}|null>(null);
  const taskListAbortRef = useRef<AbortController|null>(null);
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

  const fetchTasks = useCallback(async () => {
    if (taskListAbortRef.current) return;
    const controller = new AbortController();
    taskListAbortRef.current = controller;
    try {
      const data = await taskApi.fetchList(1000, controller.signal);
      if (!controller.signal.aborted && data.success && data.data) {
        setTasks(data.data as unknown as Task[]);
      }
    } catch (error) {
      if (!controller.signal.aborted) console.error('获取任务失败:', error);
    } finally {
      if (taskListAbortRef.current === controller) {
        taskListAbortRef.current = null;
        setIsLoading(false);
        setRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    if (viewingWorkflow) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      await fetchTasks();
      if (!stopped) timer = setTimeout(poll, 3000);
    };
    void poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
      taskListAbortRef.current?.abort();
      taskListAbortRef.current = null;
    };
  }, [fetchTasks, !!viewingWorkflow]);

  useEffect(() => () => {
    workflowRequestRef.current++;
    workflowAbortRef.current?.abort();
    taskListAbortRef.current?.abort();
  }, []);

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
      setTasks(tasks.filter(t => t.id !== taskId));
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

  const loadWorkflow = async (task: Task, clip?: VideoDirectorTaskClip) => {
    const requestId = ++workflowRequestRef.current;
    workflowAbortRef.current?.abort();
    const controller = new AbortController();
    workflowAbortRef.current = controller;
    workflowTargetRef.current = {task,clip};
    setViewingWorkflow(clip ? {...task,name:`${task.name} · Clip ${clip.windowIndex}`,
      workflowName:clip.workflowName||task.workflowName,hasWorkflowJson:clip.hasWorkflowJson,
      hasPromptText:Boolean(clip.promptText),referenceImages:clip.referenceImages||[]} : task);
    setWorkflowData(null);
    setWorkflowError('');
    setLoadingWorkflow(true);
    let timedOut = false;
    const timeout = window.setTimeout(() => {timedOut=true;controller.abort();},30000);
    try {
      const data = clip?.windowIndex ? await taskApi.fetchClipWorkflow(task.id,clip.windowIndex,controller.signal)
        : await taskApi.fetchWorkflow(task.id,controller.signal);
      if (requestId !== workflowRequestRef.current) return;
      if (!data.success || !data.data) throw new Error(String(data.message || t('tasks.failedToGetWorkflow')));
      setWorkflowData(data.data as WorkflowData);
    } catch (error) {
      if (requestId !== workflowRequestRef.current) return;
      setWorkflowError(timedOut?'读取工作流详情超时，请重试':error instanceof Error?error.message:t('tasks.failedToGetWorkflow'));
    } finally {
      window.clearTimeout(timeout);
      if (requestId === workflowRequestRef.current) {
        setLoadingWorkflow(false);
        workflowAbortRef.current = null;
      }
    }
  };

  const closeWorkflow = () => {
    workflowRequestRef.current++;
    workflowAbortRef.current?.abort();
    workflowAbortRef.current = null;
    workflowTargetRef.current = null;
    setViewingWorkflow(null);
    setWorkflowData(null);
    setWorkflowError('');
    setLoadingWorkflow(false);
  };
  const retryWorkflow = () => {
    const target=workflowTargetRef.current;
    if(target)void loadWorkflow(target.task,target.clip);
  };

  const handleViewWorkflow = async (task: Task) => {
    if (!task.hasWorkflowJson && !task.hasPromptText) {toast.info(t('tasks.noWorkflowInfo'));return;}
    await loadWorkflow(task);
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
    await loadWorkflow(task,clip);
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

  const typeFilteredTasks = typeFilter === 'all' ? tasks : tasks.filter(task => task.type === typeFilter);
  const stats: TaskStats = {
    all: typeFilteredTasks.length,
    pending: typeFilteredTasks.filter(t => t.status === 'pending').length,
    running: typeFilteredTasks.filter(t => t.status === 'running').length,
    completed: typeFilteredTasks.filter(t => t.status === 'completed').length,
    failed: typeFilteredTasks.filter(t => t.status === 'failed').length,
    cancelled: typeFilteredTasks.filter(t => t.status === 'cancelled').length,
  };

  const filteredTasks = filter === 'all' ? typeFilteredTasks : typeFilteredTasks.filter(t => t.status === filter);

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
    workflowError,
    previewImage,
    previewImages,
    previewImageIndex,
    previewVideo,
    imageInfo,
    stats,
    filteredTasks,
    // Actions
    fetchTasks,
    handleRefresh,
    handleDelete,
    handleCancelAll,
    toggleErrorDetail,
    handleViewWorkflow,
    handleViewClipWorkflow,
    closeWorkflow,
    retryWorkflow,
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
