import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from '../../../stores/i18nStore';
import { toast } from '../../../stores/toastStore';
import { taskApi } from '../../../api/tasks';
import type { Task } from '../../../types';
import type { TaskFilter, ImageInfo, WorkflowData, TaskStats } from '../types';

export function useTasksState() {
  const { t } = useTranslation();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [filter, setFilter] = useState<TaskFilter>('all');
  const [refreshing, setRefreshing] = useState(false);
  const [expandedErrors, setExpandedErrors] = useState<Set<string>>(new Set());
  const [viewingWorkflow, setViewingWorkflow] = useState<Task | null>(null);
  const [workflowData, setWorkflowData] = useState<WorkflowData | null>(null);
  const [loadingWorkflow, setLoadingWorkflow] = useState(false);
  const [previewImage, setPreviewImage] = useState<string | null>(null);
  const [imageInfo, setImageInfo] = useState<Record<string, ImageInfo>>({});
  const [previewVideo, setPreviewVideo] = useState<string | null>(null);

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
    try {
      const data = await taskApi.fetchList(1000);
      if (data.success && data.data) {
        setTasks(data.data as unknown as Task[]);
      }
    } catch (error) {
      console.error('获取任务失败:', error);
    } finally {
      setIsLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchTasks();
    const interval = setInterval(fetchTasks, 3000);
    return () => clearInterval(interval);
  }, [fetchTasks]);

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

  const stats: TaskStats = {
    all: tasks.length,
    pending: tasks.filter(t => t.status === 'pending').length,
    running: tasks.filter(t => t.status === 'running').length,
    completed: tasks.filter(t => t.status === 'completed').length,
    failed: tasks.filter(t => t.status === 'failed').length,
  };

  const filteredTasks = filter === 'all' ? tasks : tasks.filter(t => t.status === filter);

  return {
    // State
    tasks,
    isLoading,
    filter,
    setFilter,
    refreshing,
    expandedErrors,
    viewingWorkflow,
    workflowData,
    loadingWorkflow,
    previewImage,
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
    handleRetry,
    fetchImageInfo,
    setPreviewImage,
    setPreviewVideo,
    setViewingWorkflow,
    setWorkflowData,
  };
}
