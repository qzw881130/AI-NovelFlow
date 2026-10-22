import { lazy, Suspense, useEffect, useState } from 'react';
import { Download, X } from 'lucide-react';
import JSONEditor from '../../../components/JSONEditor';
import { workflowApi } from '../../../api/workflows';
import { useTranslation } from '../../../stores/i18nStore';
import { getWorkflowDisplayName } from '../utils';
import type { Workflow } from '../types';

const WorkflowGraphView = lazy(() => import('../../../components/WorkflowGraphView'));

interface Detail {
  id: string;
  workflowJson: unknown;
  nodeMapping: unknown;
}

export function WorkflowTemplateGraphModal({ workflow, onClose }: { workflow: Workflow | null; onClose: () => void }) {
  const { t } = useTranslation();
  const [detail, setDetail] = useState<Detail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [view, setView] = useState<'graph' | 'json'>('graph');

  useEffect(() => {
    if (!workflow) return;
    let active = true;
    setDetail(null);
    setLoading(true);
    setError(false);
    setView('graph');
    workflowApi.fetch(workflow.id).then(result => {
      if (!active) return;
      if (!result.success || !result.data) { setError(true); return; }
      const data = result.data as unknown as { workflowJson?: unknown; nodeMapping?: unknown };
      let mapping = data.nodeMapping ?? workflow.nodeMapping;
      if (typeof mapping === 'string') {
        try { mapping = JSON.parse(mapping); } catch { mapping = {}; }
      }
      setDetail({ id: workflow.id, workflowJson: data.workflowJson, nodeMapping: mapping });
    }).catch(() => {
      if (active) setError(true);
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [workflow?.id]);

  if (!workflow) return null;
  const currentDetail = detail?.id === workflow.id ? detail : null;
  const jsonText = currentDetail?.workflowJson == null ? '' : typeof currentDetail.workflowJson === 'string'
    ? currentDetail.workflowJson : JSON.stringify(currentDetail.workflowJson, null, 2);

  const downloadJson = () => {
    if (!jsonText) return;
    const blob = new Blob([jsonText], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${getWorkflowDisplayName(workflow, t).replace(/[\\/:*?"<>|\s]+/g, '_') || 'workflow'}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true" aria-label={t('tasks.workflowGraph')}>
      <div className="flex max-h-[92vh] w-full max-w-7xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl">
        <div className="flex items-center justify-between gap-3 border-b border-gray-100 px-5 py-4">
          <div className="min-w-0">
            <h3 className="text-base font-semibold text-gray-900">{t('tasks.workflowGraph')}</h3>
            <p className="truncate text-sm text-gray-500">{getWorkflowDisplayName(workflow, t)}</p>
          </div>
          <button type="button" onClick={onClose} aria-label={t('common.close')} className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"><X className="h-5 w-5" /></button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {loading && <div className="p-10 text-center text-sm text-gray-500">{t('common.loading')}</div>}
          {error && <div className="p-10 text-center text-sm text-red-600">{t('systemSettings.workflow.loadingFailed')}</div>}
          {!loading && !error && currentDetail && (
            <>
              <div className="mb-3 flex items-center justify-between gap-3">
                <div className="flex rounded-lg border border-gray-200 p-0.5" role="tablist" aria-label={t('tasks.workflowDetails')}>
                  <button type="button" role="tab" aria-selected={view === 'graph'} onClick={() => setView('graph')} className={`rounded-md px-3 py-1.5 text-sm ${view === 'graph' ? 'bg-blue-50 font-medium text-blue-700' : 'text-gray-600 hover:bg-gray-50'}`}>{t('tasks.workflowGraph')}</button>
                  <button type="button" role="tab" aria-selected={view === 'json'} onClick={() => setView('json')} className={`rounded-md px-3 py-1.5 text-sm ${view === 'json' ? 'bg-blue-50 font-medium text-blue-700' : 'text-gray-600 hover:bg-gray-50'}`}>{t('tasks.workflowJSON')}</button>
                </div>
                <button type="button" onClick={downloadJson} disabled={!jsonText} title={t('systemSettings.workflow.downloadWorkflow')} aria-label={t('systemSettings.workflow.downloadWorkflow')} className="rounded p-2 text-gray-500 hover:bg-blue-50 hover:text-blue-600 disabled:opacity-50"><Download className="h-4 w-4" /></button>
              </div>
              {view === 'graph' ? (
                <Suspense fallback={<div className="p-8 text-center text-sm text-gray-500">{t('common.loading')}</div>}>
                  <WorkflowGraphView workflow={currentDetail.workflowJson} nodeMapping={currentDetail.nodeMapping} />
                </Suspense>
              ) : (
                <div className="overflow-hidden rounded-lg border border-gray-200"><JSONEditor value={jsonText} onChange={() => {}} readOnly height="65vh" /></div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
