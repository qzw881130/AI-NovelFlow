import { useId, useState } from 'react';
import { Link } from 'react-router-dom';
import { Sparkles, CheckCircle, XCircle, Loader2, ArrowRight, ChevronDown, ChevronUp } from 'lucide-react';
import { useTranslation } from '../../stores/i18nStore';
import { useWelcomeState } from './hooks/useWelcomeState';
import { WorkflowOverview } from './components/WorkflowOverview';

function StatusItem({ name, status, successMsg, failMsg, noConfigMsg, hasConfig }: {
  name: string; status: boolean | undefined; successMsg: string; failMsg: string; noConfigMsg: string; hasConfig: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex min-w-0 flex-col gap-3 p-4 bg-gray-50 rounded-lg sm:flex-row sm:items-center sm:justify-between">
      <div className="flex min-w-0 items-start gap-3 sm:items-center">
        <div className={`shrink-0 p-2 rounded-lg ${status ? 'bg-green-100' : 'bg-red-100'}`}>
          {status ? <CheckCircle className="h-5 w-5 text-green-600" /> : <XCircle className="h-5 w-5 text-red-600" />}
        </div>
        <div className="min-w-0 break-words">
          <p className="font-medium text-gray-900">{name}</p>
          <p className="text-sm text-gray-500">{status ? successMsg : hasConfig ? failMsg : noConfigMsg}</p>
        </div>
      </div>
      <Link to="/settings" className="inline-flex min-h-[44px] shrink-0 items-center self-start text-primary-600 hover:text-primary-700 text-sm font-medium sm:self-center">{t('common.settings')}</Link>
    </div>
  );
}

export default function Welcome() {
  const { t } = useTranslation();
  const state = useWelcomeState();
  const workflowId = useId();
  const [workflowCollapsed, setWorkflowCollapsed] = useState(() => (
    typeof window !== 'undefined' && window.matchMedia('(max-width: 1023px)').matches
  ));

  return (
    <div className="min-w-0 space-y-6 sm:space-y-8">
      {/* Hero */}
      <div className="text-center py-6 sm:py-12">
        <div className="flex justify-center mb-6">
          <div className="p-4 bg-primary-100 rounded-2xl"><Sparkles className="h-12 w-12 text-primary-600 sm:h-16 sm:w-16" /></div>
        </div>
        <h1 className="text-3xl sm:text-4xl font-bold text-gray-900 mb-4 break-words">{t('welcome.title')}</h1>
        <p className="text-base sm:text-xl text-gray-600 max-w-2xl mx-auto break-words">{t('welcome.subtitle')}</p>
      </div>

      {/* Workflow */}
      <div className="card min-w-0 p-4 sm:p-6">
        <div className="flex items-center justify-between gap-3">
          <h2 className="min-w-0 break-words text-lg font-semibold text-gray-900">{t('welcome.features.workflow.title')}</h2>
          <button
            type="button"
            aria-expanded={!workflowCollapsed}
            aria-controls={workflowId}
            onClick={() => setWorkflowCollapsed((value) => !value)}
            className="inline-flex min-h-[44px] shrink-0 items-center gap-1.5 rounded-lg px-3 py-2 text-sm text-gray-600 hover:bg-gray-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500"
          >
            {workflowCollapsed ? t('common.expand') : t('common.collapse')}
            {workflowCollapsed ? <ChevronDown className="h-4 w-4" /> : <ChevronUp className="h-4 w-4" />}
          </button>
        </div>
        <div id={workflowId} hidden={workflowCollapsed}>
          <div className="pt-6">
            <WorkflowOverview />
          </div>
        </div>
      </div>

      {/* System Status */}
      <div className="card min-w-0 p-4 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
          <h2 className="min-w-0 break-words text-lg font-semibold text-gray-900">{t('welcome.systemStatus')}</h2>
          <button onClick={state.handleCheck} disabled={state.checking} className="btn-secondary min-h-[44px] text-sm">
            {state.checking ? <><Loader2 className="h-4 w-4 mr-2 animate-spin" />{t('common.loading')}</> : t('common.refresh')}
          </button>
        </div>
        <div className="space-y-4">
          <StatusItem name={`${state.providerName} (${state.modelName})`} status={state.status?.llm}
            successMsg={t('systemSettings.connectionSuccess')} failMsg={t('systemSettings.connectionFailed')}
            noConfigMsg={t('systemSettings.enterApiKey')} hasConfig={true} />
          <StatusItem name="ComfyUI" status={state.status?.comfyui}
            successMsg={t('systemSettings.connectionSuccess')} failMsg={t('systemSettings.connectionFailed')}
            noConfigMsg={t('systemSettings.comfyUIHost')} hasConfig={!!state.comfyUIHost} />
        </div>
        {!state.isConfigured && (
          <div className="mt-6 p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
            <p className="text-sm text-yellow-800"><strong>{t('common.info')}:</strong> {t('welcome.pleaseConfigure')}</p>
          </div>
        )}
      </div>

      {/* Quick Actions */}
      <div className="flex flex-col justify-center gap-3 sm:flex-row sm:flex-wrap sm:gap-4">
        <Link to="/novels" aria-disabled={!state.isConfigured} className={`btn-primary min-h-[44px] text-center ${!state.isConfigured ? 'opacity-50 cursor-not-allowed' : ''}`}
          onClick={(e) => !state.isConfigured && e.preventDefault()}>
          {t('welcome.getStarted')}<ArrowRight className="ml-2 h-4 w-4 shrink-0" />
        </Link>
        <Link to="/settings" className="btn-secondary min-h-[44px] text-center">{t('nav.systemSettings')}</Link>
      </div>
    </div>
  );
}
