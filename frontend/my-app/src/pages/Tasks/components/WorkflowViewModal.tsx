import { Copy, Download, Loader2, X } from 'lucide-react';
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
  convertShotName: (name: string) => string;
}

export function WorkflowViewModal({
  viewingWorkflow,
  workflowData,
  loadingWorkflow,
  onClose,
  convertShotName,
}: WorkflowViewModalProps) {
  const { t } = useTranslation();

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

  const copyPrompt = async () => {
    if (!workflowData?.prompt) return;
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(workflowData.prompt);
      } else {
        const textarea = document.createElement('textarea');
        textarea.value = workflowData.prompt;
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
              <div>
                <div className="flex items-center justify-between mb-2">
                  <h4 className="text-sm font-medium text-gray-700">{t('tasks.generationPrompt')}</h4>
                  <button
                    type="button"
                    onClick={copyPrompt}
                    className="p-1.5 text-gray-400 hover:text-blue-600 transition-colors rounded hover:bg-blue-50"
                    title={t('common.copy')}
                    aria-label={t('common.copy')}
                  >
                    <Copy className="h-4 w-4" />
                  </button>
                </div>
                <div className="bg-gray-50 p-3 rounded-lg border border-gray-200 h-72 overflow-y-auto">
                  <p className="text-sm text-gray-600 font-mono whitespace-pre-wrap break-all">{workflowData.prompt}</p>
                </div>
              </div>
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
