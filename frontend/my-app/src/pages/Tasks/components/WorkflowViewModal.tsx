import { useEffect, useState } from 'react';
import { ChevronDown, ChevronUp, Copy, Download, Loader2, Play, X } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import { toast } from '../../../stores/toastStore';
import JSONEditor from '../../../components/JSONEditor';
import type { Task } from '../../../types';
import type { WorkflowData } from '../types';

interface WorkflowViewModalProps {
  viewingWorkflow: Task | null;
  workflowData: WorkflowData | null;
  loadingWorkflow: boolean;
  onClose: () => void;
  onPreviewImages: (images: Array<{ label?: string; url: string }>, index: number) => void;
  onPreviewVideo: (url: string) => void;
  convertShotName: (name: string) => string;
}

export function WorkflowViewModal({
  viewingWorkflow,
  workflowData,
  loadingWorkflow,
  onClose,
  onPreviewImages,
  onPreviewVideo,
  convertShotName,
}: WorkflowViewModalProps) {
  const { t } = useTranslation();
  const [showBoundParameters, setShowBoundParameters] = useState(false);
  const [showOnlyMappedNodes, setShowOnlyMappedNodes] = useState(true);

  useEffect(() => {
    setShowBoundParameters(false);
    setShowOnlyMappedNodes(true);
  }, [viewingWorkflow?.id, viewingWorkflow?.name, workflowData]);

  if (!viewingWorkflow) return null;

  const workflowJsonText = workflowData?.workflow
    ? typeof workflowData.workflow === 'string'
      ? workflowData.workflow
      : JSON.stringify(workflowData.workflow, null, 2)
    : '';

  const getTaskLocalizedName = () => {
    const nameMatch = viewingWorkflow.name.match(/^[^:]+:\s*(.+)$/);
    const actualName = nameMatch ? nameMatch[1] : viewingWorkflow.name;
    const localizedName = convertShotName(actualName);
    switch (viewingWorkflow.type) {
      case 'character_portrait':
        return t('tasks.taskNames.characterPortrait', { name: localizedName });
      case 'shot_image':
        return t('tasks.taskNames.shotImage', { name: localizedName });
      case 'shot_video':
      case 'shot_video_hd':
        return t('tasks.taskNames.shotVideo', { name: localizedName });
      case 'transition_video':
        return t('tasks.taskNames.transitionVideo', { from: localizedName, to: '' });
      case 'chapter_video':
        return t('tasks.taskNames.chapterVideo', { name: localizedName });
      default:
        return viewingWorkflow.name;
    }
  };

  const downloadWorkflowJson = () => {
    if (!workflowJsonText) return;
    const blob = new Blob([workflowJsonText], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    const safeName = getTaskLocalizedName().replace(/[\\/:*?"<>|\s]+/g, '_') || 'workflow';
    link.href = url;
    link.download = `${safeName}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const copyText = async (content: string) => {
    if (!content) return;
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(content);
      } else {
        const textarea = document.createElement('textarea');
        textarea.value = content;
        textarea.style.position = 'fixed';
        textarea.style.left = '-9999px';
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
      }
      toast.success(t('common.copied'));
    } catch (error) {
      console.error('复制生成提示词失败:', error);
      toast.error(t('common.copyFailed'));
    }
  };

  const promptItems = workflowData?.promptItems || [];
  const workflowObject = typeof workflowData?.workflow === 'string'
    ? (() => {
        try { return JSON.parse(workflowData.workflow); } catch { return null; }
      })()
    : workflowData?.workflow;
  const allBoundNodes = workflowObject && typeof workflowObject === 'object'
    ? (Array.isArray(workflowObject.nodes)
        ? workflowObject.nodes.map((node: any) => [String(node.id), node]).filter(([, node]: any) => node?.inputs)
        : Object.entries(workflowObject).filter(([, node]: any) => node?.inputs))
      .map(([id, node]: any) => {
        const inputs = { ...node.inputs };
        if (node.class_type === 'CR Prompt Text') {
          delete inputs.prompt;
          delete inputs.text;
        }
        return {
          id,
          title: node._meta?.title || node.title || node.class_type || node.type || `Node ${id}`,
          inputs: Object.entries(inputs),
        };
      })
      .filter((node: any) => node.inputs.length > 0)
    : [];
  const mappedNodeIds = new Set(
    Object.values(workflowData?.nodeMapping || {})
      .filter((nodeId): nodeId is string | number => typeof nodeId === 'string' || typeof nodeId === 'number')
      .map(String),
  );
  const boundNodes = showOnlyMappedNodes
    ? allBoundNodes.filter((node: any) => mappedNodeIds.has(node.id))
    : allBoundNodes;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg w-full max-w-4xl max-h-[90vh] flex flex-col overflow-hidden">
        <div className="flex items-center justify-between p-6 border-b border-gray-100 flex-shrink-0 bg-white">
          <h3 className="text-lg font-semibold text-gray-900">
            {t('tasks.workflowDetails')}
            <span className="ml-2 text-sm font-normal text-gray-500">{getTaskLocalizedName()}</span>
          </h3>
          <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-600">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-6">
          {loadingWorkflow ? (
            <div className="flex justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-primary-600" />
            </div>
          ) : workflowData ? (
            <div className="space-y-4">
              {workflowData.seed != null && (
                <div className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-700">
                  Seed: <span className="font-mono font-medium">{workflowData.seed}</span>
                </div>
              )}
              {(!!viewingWorkflow.referenceImages?.length || viewingWorkflow.clipExecution?.previous_approved_video_url) && (
                <div>
                  <h4 className="text-sm font-medium text-gray-700 mb-2">
                    {viewingWorkflow.referenceImages?.length ? t('tasks.referenceImages') : t('tasks.referenceVideo')}
                  </h4>
                  <div className="flex flex-wrap gap-2">
                    {(viewingWorkflow.referenceImages || []).map((image, index) => (
                      <button
                        key={`${image.url}-${index}`}
                        type="button"
                        onClick={() => onPreviewImages(viewingWorkflow.referenceImages || [], index)}
                        className="group relative h-20 w-32 overflow-hidden rounded-md border border-gray-200 bg-white hover:shadow-md transition-shadow"
                        title={image.label || t('tasks.referenceImage')}
                      >
                        <img
                          src={image.url}
                          alt={image.label || t('tasks.referenceImage')}
                          className="h-full w-full object-cover"
                        />
                        {image.label && (
                          <span className="absolute bottom-0 left-0 right-0 truncate bg-black/55 px-1 py-0.5 text-xs text-white">
                            {image.label}
                          </span>
                        )}
                        <span className="absolute inset-0 bg-black/0 group-hover:bg-black/20 transition-colors" />
                      </button>
                    ))}
                    {viewingWorkflow.clipExecution?.previous_approved_video_url && (
                      <button
                        type="button"
                        onClick={() => onPreviewVideo(viewingWorkflow.clipExecution!.previous_approved_video_url!)}
                        className="group relative h-20 w-32 overflow-hidden rounded-md border border-gray-200 bg-black"
                        title={t('tasks.referenceVideo')}
                      >
                        <video src={viewingWorkflow.clipExecution.previous_approved_video_url} muted preload="metadata" className="h-full w-full object-cover" />
                        <span className="absolute inset-0 flex items-center justify-center bg-black/15 text-white opacity-0 transition-opacity group-hover:opacity-100">
                          <Play className="h-6 w-6 fill-current" />
                        </span>
                        <span className="absolute bottom-0 left-0 right-0 truncate bg-black/55 px-1 py-0.5 text-xs text-white">
                          {t('tasks.referenceVideo')}
                        </span>
                      </button>
                    )}
                  </div>
                </div>
              )}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <h4 className="text-sm font-medium text-gray-700">
                    {t('tasks.generationPrompt')}{promptItems.length > 0 ? `（${promptItems.length} 项）` : ''}
                  </h4>
                  {promptItems.length === 0 && (
                    <button type="button" onClick={() => void copyText(workflowData.prompt)} className="p-1.5 text-gray-400 hover:text-blue-600 transition-colors rounded hover:bg-blue-50" title={t('common.copy')} aria-label={t('common.copy')}>
                      <Copy className="h-4 w-4" />
                    </button>
                  )}
                </div>
                {promptItems.length > 0 ? (
                  <div className="space-y-3">
                    {promptItems.map((item) => (
                      <div key={`${item.nodeId}-${item.role}`} className="overflow-hidden rounded-lg border border-gray-200 bg-gray-50">
                        <div className="flex items-center justify-between gap-3 border-b border-gray-200 bg-white px-3 py-2">
                          <div className="min-w-0">
                            <span className="text-sm font-medium text-gray-800">{item.label}</span>
                            <span className="ml-2 text-xs text-gray-400">Node {item.nodeId} · {item.nodeTitle}</span>
                          </div>
                          <button type="button" onClick={() => void copyText(item.content)} className="shrink-0 rounded p-1.5 text-gray-400 hover:bg-blue-50 hover:text-blue-600" title={`复制${item.label}`}>
                            <Copy className="h-4 w-4" />
                          </button>
                        </div>
                        <pre className="max-h-56 overflow-y-auto whitespace-pre-wrap break-words p-3 font-mono text-sm text-gray-600">{item.content}</pre>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="bg-gray-50 p-3 rounded-lg border border-gray-200 h-72 overflow-y-auto">
                    <p className="text-sm text-gray-600 font-mono whitespace-pre-wrap break-all">{workflowData.prompt}</p>
                  </div>
                )}
              </div>
              {boundNodes.length > 0 && (
                <section className="overflow-hidden rounded-lg border border-gray-200">
                  <div className="flex items-center justify-between gap-3 bg-gray-50 px-3 py-2.5">
                    <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
                      <span className="text-sm font-medium text-gray-700">{t('tasks.boundWorkflowParameters', { count: boundNodes.reduce((total: number, node: any) => total + node.inputs.length, 0) })}</span>
                      <label className="flex cursor-pointer items-center gap-1.5 text-xs font-normal text-gray-600">
                        <input
                          type="checkbox"
                          checked={showOnlyMappedNodes}
                          onChange={(event) => setShowOnlyMappedNodes(event.target.checked)}
                          className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                        />
                        {t('tasks.showOnlyMappedNodes')}
                      </label>
                    </div>
                    <button
                      type="button"
                      onClick={() => setShowBoundParameters(value => !value)}
                      aria-expanded={showBoundParameters}
                      aria-label={showBoundParameters ? t('common.collapse') : t('common.expand')}
                      className="shrink-0 rounded p-1 text-gray-500 hover:bg-gray-200"
                    >
                      {showBoundParameters ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                    </button>
                  </div>
                  {showBoundParameters && (
                    <div className="max-h-96 space-y-2 overflow-y-auto p-3">
                      {showOnlyMappedNodes && mappedNodeIds.size === 0 && (
                        <p className="px-1 text-xs text-amber-700">{t('tasks.noMappedNodes')}</p>
                      )}
                      {boundNodes.map((node: any) => (
                        <details key={node.id} className="rounded-md border border-gray-200" open={boundNodes.length <= 8}>
                          <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-gray-700">
                            <span className="mr-2 font-mono text-gray-400">#{node.id}</span>{node.title}
                          </summary>
                          <dl className="divide-y divide-gray-100 border-t border-gray-100">
                            {node.inputs.map(([name, value]: [string, unknown]) => (
                              <div key={name} className="grid grid-cols-[minmax(7rem,0.35fr)_minmax(0,1fr)] gap-3 px-3 py-2 text-xs">
                                <dt className="break-all font-mono text-gray-500">{name}</dt>
                                <dd className="break-all font-mono text-gray-700">{typeof value === 'string' ? value : JSON.stringify(value)}</dd>
                              </div>
                            ))}
                          </dl>
                        </details>
                      ))}
                    </div>
                  )}
                </section>
              )}
              {workflowData.workflow && (
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <h4 className="text-sm font-medium text-gray-700">{t('tasks.workflowJSON')}</h4>
                    <button
                      type="button"
                      onClick={downloadWorkflowJson}
                      className="p-1.5 text-gray-400 hover:text-blue-600 transition-colors rounded hover:bg-blue-50"
                      title="下载工作流 JSON"
                      aria-label="下载工作流 JSON"
                    >
                      <Download className="h-4 w-4" />
                    </button>
                  </div>
                  <div className="border border-gray-200 rounded-lg overflow-hidden">
                    <JSONEditor
                      value={workflowJsonText}
                      onChange={() => {}}
                      readOnly={true}
                      height="50vh"
                    />
                  </div>
                </div>
              )}
              <div className="flex justify-end pt-4">
                <button onClick={onClose} className="btn-secondary">{t('common.close')}</button>
              </div>
            </div>
          ) : (
            <div className="text-center py-8 text-gray-500">{t('tasks.failedToLoadWorkflow')}</div>
          )}
        </div>
      </div>
    </div>
  );
}
