import { Link } from 'react-router-dom';
import { Sparkles, CheckCircle, XCircle, Loader2, ArrowRight } from 'lucide-react';
import { useTranslation } from '../../stores/i18nStore';
import { useWelcomeState } from './hooks/useWelcomeState';
import { WorkflowOverview } from './components/WorkflowOverview';

function StatusItem({ name, status, successMsg, failMsg, noConfigMsg, hasConfig }: {
  name: string; status: boolean | undefined; successMsg: string; failMsg: string; noConfigMsg: string; hasConfig: boolean;
}) {
  const { t } = useTranslation();
  const checking = status === undefined;
  return (
    <div className="flex items-center justify-between p-4 bg-gray-50 rounded-lg">
      <div className="flex items-center gap-3">
        <div className={`p-2 rounded-lg ${checking ? 'bg-gray-100' : status ? 'bg-green-100' : 'bg-red-100'}`}>
          {checking ? <Loader2 className="h-5 w-5 animate-spin text-gray-500" />
            : status ? <CheckCircle className="h-5 w-5 text-green-600" /> : <XCircle className="h-5 w-5 text-red-600" />}
        </div>
        <div>
          <p className="font-medium text-gray-900">{name}</p>
          <p className="text-sm text-gray-500">{checking ? t('common.loading') : status ? successMsg : hasConfig ? failMsg : noConfigMsg}</p>
        </div>
      </div>
      <Link to="/settings" className="text-primary-600 hover:text-primary-700 text-sm font-medium">{t('common.settings')}</Link>
    </div>
  );
}

export default function Welcome() {
  const { t } = useTranslation();
  const state = useWelcomeState();

  return (
    <div className="space-y-8">
      {/* Hero */}
      <div className="text-center py-12">
        <div className="flex justify-center mb-6">
          <div className="p-4 bg-primary-100 rounded-2xl"><Sparkles className="h-16 w-16 text-primary-600" /></div>
        </div>
        <h1 className="text-4xl font-bold text-gray-900 mb-4">{t('welcome.title')}</h1>
        <p className="text-xl text-gray-600 max-w-2xl mx-auto">{t('welcome.subtitle')}</p>
      </div>

      {/* Workflow */}
      <div className="card">
        <h2 className="text-lg font-semibold text-gray-900 mb-6">{t('welcome.features.workflow.title')}</h2>
        <WorkflowOverview />
      </div>

      {/* System Status */}
      <div className="card">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-lg font-semibold text-gray-900">{t('welcome.systemStatus')}</h2>
          <button onClick={state.handleCheck} disabled={state.checking} className="btn-secondary text-sm">
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
      <div className="flex justify-center gap-4">
        <Link to="/novels" className={`btn-primary ${!state.isConfigured ? 'opacity-50 cursor-not-allowed' : ''}`}
          onClick={(e) => !state.isConfigured && e.preventDefault()}>
          {t('welcome.getStarted')}<ArrowRight className="ml-2 h-4 w-4" />
        </Link>
        <Link to="/settings" className="btn-secondary">{t('nav.systemSettings')}</Link>
      </div>
    </div>
  );
}
