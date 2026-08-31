import { useEffect, useMemo, useState } from 'react';
import { ListTodo, Loader2, RefreshCw, Square, CheckCircle, XCircle, Clock, AlertCircle, ChevronLeft, ChevronRight } from 'lucide-react';
import { useTranslation } from '../../stores/i18nStore';
import ComfyUIStatus from '../../components/ComfyUIStatus';
import { useTasksState } from './hooks/useTasksState';
import { ImagePreviewModal, VideoPreviewModal } from './components/PreviewModals';
import { WorkflowViewModal } from './components/WorkflowViewModal';
import { TaskCard } from './components/TaskCard';
import type { Task } from '../../types';

export default function Tasks() {
  const { t, i18n } = useTranslation();
  const [pageSize, setPageSize] = useState(30);
  const [currentPage, setCurrentPage] = useState(1);
  const {
    isLoading,
    filter,
    setFilter,
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
    filteredTasks,
    handleRefresh,
    handleDelete,
    handleCancelAll,
    toggleErrorDetail,
    handleViewWorkflow,
    handleRetry,
    fetchImageInfo,
    openImagePreview,
    openImageGallery,
    navigatePreviewImage,
    closeImagePreview,
    setPreviewVideo,
    setViewingWorkflow,
    setWorkflowData,
  } = useTasksState();

  const totalPages = Math.max(1, Math.ceil(filteredTasks.length / pageSize));
  const paginatedTasks = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return filteredTasks.slice(start, start + pageSize);
  }, [filteredTasks, currentPage, pageSize]);

  useEffect(() => {
    setCurrentPage(1);
  }, [filter, pageSize]);

  useEffect(() => {
    if (currentPage > totalPages) setCurrentPage(totalPages);
  }, [currentPage, totalPages]);

  // Helper functions
  const convertShotName = (name: string): string => {
    return name.replace(/镜(\d+)/g, (_, num) => `${t('workflow.shot', { defaultValue: 'Shot' })}${num}`);
  };

  const getTaskDisplayName = (task: Task): string => {
    const charMatch = task.name.match(/生成角色形象:\s*(.+)/);
    if (charMatch) return t('tasks.taskNames.characterPortrait', { name: charMatch[1] });
    const editImageMatch = task.name.match(/编辑(角色|场景|道具)图片:\s*(.+)/);
    if (editImageMatch) return t('tasks.taskNames.singleImageEdit', { name: `${editImageMatch[1]} ${editImageMatch[2]}` });
    const shotMatch = task.name.match(/生成分镜(图|视频|图片):\s*(.+)/);
    if (shotMatch) {
      const type = shotMatch[1] === '视频' ? 'shotVideo' : 'shotImage';
      return t(`tasks.taskNames.${type}`, { name: convertShotName(shotMatch[2]) });
    }
    const transMatch = task.name.match(/生成转场视频:\s*分镜\s*(\d+)\s*→\s*分镜\s*(\d+)/);
    if (transMatch) return t('tasks.taskNames.transitionVideo', { from: transMatch[1], to: transMatch[2] });
    return task.name;
  };

  const getTaskDisplayDescription = (task: Task): string => {
    if (!task.description) return '';
    const charMatch = task.description.match(/为角色\s*['"](.+)['"]\s*生成人设图/);
    if (charMatch) return t('tasks.taskDescriptions.characterPortrait', { name: charMatch[1] });
    const editImageMatch = task.description.match(/为(角色|场景|道具)\s*['"](.+)['"]\s*编辑图片/);
    if (editImageMatch) return t('tasks.taskDescriptions.singleImageEdit', { name: `${editImageMatch[1]} ${editImageMatch[2]}` });
    const shotImgMatch = task.description.match(/为章节\s*['"](.+)['"]\s*的分镜\s*(\d+)\s*生成图片/);
    if (shotImgMatch) return t('tasks.taskDescriptions.shotImage', { name: `Shot ${shotImgMatch[2]}` });
    const shotImgMatch2 = task.description.match(/为分镜\s*['"](.+)['"]\s*生成图片/);
    if (shotImgMatch2) return t('tasks.taskDescriptions.shotImage', { name: shotImgMatch2[1] });
    const shotVidMatch = task.description.match(/为章节\s*['"](.+)['"]\s*的分镜\s*(\d+)\s*生成视频/);
    if (shotVidMatch) return t('tasks.taskDescriptions.shotVideo', { name: `Shot ${shotVidMatch[2]}` });
    const shotVidMatch2 = task.description.match(/为分镜\s*['"](.+)['"]\s*生成视频/);
    if (shotVidMatch2) return t('tasks.taskDescriptions.shotVideo', { name: shotVidMatch2[1] });
    const transMatch = task.description.match(/生成从分镜\s*(\d+)\s*到\s*(\d+)\s*的转场视频/);
    if (transMatch) return t('tasks.taskDescriptions.transitionVideo', { from: transMatch[1], to: transMatch[2] });
    return task.description;
  };

  const getTaskTypeName = (type: Task['type']) => {
    const names: Record<string, string> = {
      'character_portrait': t('tasks.types.characterPortrait'),
      'shot_image': t('tasks.types.shotImage'),
      'single_image_edit': t('tasks.types.singleImageEdit'),
      'shot_video': t('tasks.types.shotVideo'),
      'chapter_video': t('tasks.types.chapterVideo'),
      'transition_video': t('tasks.types.transitionVideo'),
    };
    return names[type] || type;
  };

  const getWorkflowDisplayName = (task: Task): string => {
    if (!task.workflowName) return '';
    if (task.workflowIsSystem) return t(`tasks.workflowNames.${task.workflowName}`, { defaultValue: task.workflowName });
    return task.workflowName;
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
      return date.toLocaleString('en-GB');
    }
  };

  const getStatusIcon = (status: Task['status']) => {
    switch (status) {
      case 'completed': return <CheckCircle className="h-5 w-5 text-green-600" />;
      case 'failed': return <XCircle className="h-5 w-5 text-red-600" />;
      case 'running': return <Loader2 className="h-5 w-5 text-blue-600 animate-spin" />;
      case 'pending': return <Clock className="h-5 w-5 text-yellow-600" />;
      default: return <AlertCircle className="h-5 w-5 text-gray-400" />;
    }
  };

  const getStatusText = (status: Task['status']) => {
    const texts: Record<string, string> = {
      'pending': t('tasks.pending'), 'running': t('tasks.running'),
      'completed': t('tasks.completed'), 'failed': t('tasks.failed'),
    };
    return texts[status] || status;
  };

  const getStatusColor = (status: Task['status']) => {
    switch (status) {
      case 'completed': return 'bg-green-50 text-green-700 border-green-200';
      case 'failed': return 'bg-red-50 text-red-700 border-red-200';
      case 'running': return 'bg-blue-50 text-blue-700 border-blue-200';
      case 'pending': return 'bg-yellow-50 text-yellow-700 border-yellow-200';
      default: return 'bg-gray-50 text-gray-700 border-gray-200';
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{t('tasks.title')}</h1>
          <p className="mt-1 text-sm text-gray-500">{t('tasks.subtitle')}</p>
        </div>
        <div className="flex gap-2">
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
          <button onClick={handleRefresh} disabled={refreshing} className="btn-secondary">
            <RefreshCw className={`h-4 w-4 mr-2 ${refreshing ? 'animate-spin' : ''}`} />
            {t('common.refresh')}
          </button>
        </div>
      </div>

      <ComfyUIStatus />

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
              filter === stat.key ? 'ring-2 ring-primary-500 ' + stat.color : 'bg-gray-50 hover:bg-gray-100'
            }`}
          >
            <p className="text-2xl font-bold">{stats[stat.key as keyof typeof stats]}</p>
            <p className="text-sm text-gray-600">{stat.label}</p>
          </button>
        ))}
      </div>

      <div className="card">
        <div className="mb-4 flex items-center justify-between gap-4">
          <h2 className="text-lg font-semibold text-gray-900">{t('tasks.taskList')}</h2>
          <div className="flex items-center gap-3 text-sm text-gray-600">
            <span>每页</span>
            <select
              value={pageSize}
              onChange={(event) => setPageSize(Number(event.target.value))}
              className="rounded-lg border border-gray-300 bg-white px-2 py-1 focus:outline-none focus:ring-2 focus:ring-primary-500"
            >
              {[30, 50, 100].map((size) => (
                <option key={size} value={size}>{size}</option>
              ))}
            </select>
            <span>条</span>
            <span className="text-gray-400">共 {filteredTasks.length} 条</span>
          </div>
        </div>
        {isLoading ? (
          <div className="flex justify-center py-12">
            <Loader2 className="h-8 w-8 animate-spin text-primary-600" />
          </div>
        ) : filteredTasks.length === 0 ? (
          <div className="text-center py-12">
            <ListTodo className="mx-auto h-12 w-12 text-gray-300" />
            <h3 className="mt-4 text-lg font-medium text-gray-900">{t('tasks.noTasks')}</h3>
            <p className="mt-1 text-sm text-gray-500">{filter === 'all' ? t('tasks.noTasksCreated') : t('tasks.noTasksInStatus')}</p>
          </div>
        ) : (
          <>
            <div className="space-y-3">
              {paginatedTasks.map((task) => (
                <TaskCard
                  key={task.id}
                  task={task}
                  imageInfo={imageInfo}
                  expandedErrors={expandedErrors}
                  onDelete={handleDelete}
                  onRetry={handleRetry}
                  onViewWorkflow={handleViewWorkflow}
                  onToggleError={toggleErrorDetail}
                  onPreviewImage={openImagePreview}
                  onPreviewImages={openImageGallery}
                  onPreviewVideo={setPreviewVideo}
                  fetchImageInfo={fetchImageInfo}
                  getTaskDisplayName={getTaskDisplayName}
                  getTaskDisplayDescription={getTaskDisplayDescription}
                  getTaskTypeName={getTaskTypeName}
                  getWorkflowDisplayName={getWorkflowDisplayName}
                  getStatusIcon={getStatusIcon}
                  getStatusText={getStatusText}
                  getStatusColor={getStatusColor}
                  formatDate={formatDate}
                />
              ))}
            </div>
            <div className="mt-4 flex items-center justify-between border-t border-gray-100 pt-4 text-sm text-gray-600">
              <span>第 {currentPage} / {totalPages} 页</span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setCurrentPage((page) => Math.max(1, page - 1))}
                  disabled={currentPage <= 1}
                  className="inline-flex items-center gap-1 rounded-lg border border-gray-300 px-3 py-1.5 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <ChevronLeft className="h-4 w-4" />
                  上一页
                </button>
                <button
                  type="button"
                  onClick={() => setCurrentPage((page) => Math.min(totalPages, page + 1))}
                  disabled={currentPage >= totalPages}
                  className="inline-flex items-center gap-1 rounded-lg border border-gray-300 px-3 py-1.5 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  下一页
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      {previewVideo && <VideoPreviewModal videoUrl={previewVideo} onClose={() => setPreviewVideo(null)} />}
      <WorkflowViewModal
        viewingWorkflow={viewingWorkflow}
        workflowData={workflowData}
        loadingWorkflow={loadingWorkflow}
        onClose={() => { setViewingWorkflow(null); setWorkflowData(null); }}
        onPreviewImages={openImageGallery}
        convertShotName={convertShotName}
      />
      {previewImage && (
        <ImagePreviewModal
          imageUrl={previewImage}
          images={previewImages}
          currentIndex={previewImageIndex}
          onNavigate={navigatePreviewImage}
          onClose={closeImagePreview}
        />
      )}
    </div>
  );
}
