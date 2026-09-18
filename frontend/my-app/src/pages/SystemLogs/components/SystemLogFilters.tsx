import { useRef, useState } from 'react';
import { Filter, X } from 'lucide-react';
import type { SystemLogFilterData } from '../../../api/systemLogs';
import { useTranslation } from '../../../stores/i18nStore';
import type { SystemLogUrlState } from '../urlState';
import { shortTechnicalId, type SystemLogDisplayMetadata } from '../displayMetadata';
import { useSystemLogDialog } from './useSystemLogDialog';

type FilterValues = Pick<SystemLogUrlState,
  'level' | 'service' | 'provider' | 'novelId' | 'chapterId' | 'shotId' |
  'taskId' | 'errorCode' | 'failureClass'>;

interface Props {
  state: SystemLogUrlState;
  options: SystemLogFilterData;
  optionsError: string;
  metadata: SystemLogDisplayMetadata;
  onApply: (values: FilterValues) => void;
  onReset: () => void;
  onClose: () => void;
}

const valuesFromState = (state: SystemLogUrlState): FilterValues => ({
  level: state.level,
  service: state.service,
  provider: state.provider,
  novelId: state.novelId,
  chapterId: state.chapterId,
  shotId: state.shotId,
  taskId: state.taskId,
  errorCode: state.errorCode,
  failureClass: state.failureClass,
});

const includeCurrent = (options: string[], current: string) => (
  current && !options.includes(current) ? [current, ...options] : options
);

export function SystemLogFilters({ state, options, optionsError, metadata, onApply, onReset, onClose }: Props) {
  const { t } = useTranslation();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [draft, setDraft] = useState<FilterValues>(() => valuesFromState(state));
  useSystemLogDialog(dialogRef);
  const chapterOptions = draft.novelId && Object.keys(metadata.chapters).length
    ? options.chapterIds.filter(value => metadata.chapters[value]?.novelId === draft.novelId)
    : options.chapterIds;
  const shotOptions = draft.chapterId && Object.keys(metadata.shots).length
    ? options.shotIds.filter(value => metadata.shots[value]?.chapterId === draft.chapterId)
    : options.shotIds;

  const set = (key: keyof FilterValues, value: string) => {
    setDraft(previous => {
      const next = { ...previous, [key]: value };
      if (key === 'novelId') {
        next.chapterId = '';
        next.shotId = '';
      }
      if (key === 'chapterId') next.shotId = '';
      return next;
    });
  };

  const select = (
    key: keyof FilterValues,
    choices: string[],
    disabled = false,
    label: (value: string) => string = value => value,
  ) => (
    <select
      value={draft[key]}
      disabled={disabled}
      onChange={event => set(key, event.target.value)}
      className="input-field min-h-[44px] disabled:bg-gray-100 disabled:text-gray-400"
    >
      <option value="">{t('systemLogs.all')}</option>
      {includeCurrent(choices, draft[key]).map(value => <option key={value} value={value}>{label(value)}</option>)}
    </select>
  );

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby="system-log-filter-title"
      onCancel={event => { event.preventDefault(); onClose(); }}
      onClick={event => { if (event.target === event.currentTarget) onClose(); }}
      className="fixed inset-0 m-0 h-[100dvh] max-h-none w-full max-w-none border-0 bg-white p-0 shadow-2xl backdrop:bg-gray-950/45 lg:inset-auto lg:left-1/2 lg:top-1/2 lg:h-auto lg:max-h-[88vh] lg:w-[min(900px,calc(100vw-3rem))] lg:-translate-x-1/2 lg:-translate-y-1/2 lg:rounded-2xl"
    >
      <form
        method="dialog"
        className="flex h-full min-h-0 flex-col lg:max-h-[88vh]"
        onSubmit={event => { event.preventDefault(); onApply(draft); onClose(); }}
      >
        <header className="flex min-h-16 shrink-0 items-center justify-between border-b border-gray-200 px-4 sm:px-6">
          <div className="flex items-center gap-2">
            <Filter aria-hidden="true" className="h-5 w-5 text-primary-600" />
            <h2 id="system-log-filter-title" className="text-lg font-semibold text-gray-900">{t('systemLogs.filterTitle')}</h2>
          </div>
          <button type="button" onClick={onClose} aria-label={t('systemLogs.close')}
            className="flex h-11 w-11 items-center justify-center rounded-lg text-gray-500 hover:bg-gray-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500">
            <X aria-hidden="true" className="h-5 w-5" />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-6">
          {optionsError && <p role="alert" className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">{optionsError}</p>}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <label className="text-sm font-medium text-gray-700">{t('systemLogs.filters.level')}{select('level', options.levels)}</label>
            <label className="text-sm font-medium text-gray-700">{t('systemLogs.filters.service')}{select('service', options.services)}</label>
            <label className="text-sm font-medium text-gray-700">{t('systemLogs.filters.provider')}{select('provider', options.providers)}</label>
            <label className="text-sm font-medium text-gray-700">{t('systemLogs.filters.book')}{select('novelId', options.novelIds, false, value => `${metadata.novels[value]?.title || t('systemLogs.unknown')} · ${shortTechnicalId(value)}`)}</label>
            <label className="text-sm font-medium text-gray-700">{t('systemLogs.filters.chapter')}{select('chapterId', chapterOptions, !draft.novelId, value => {
              const chapter = metadata.chapters[value];
              return `${chapter ? `#${chapter.number} ${chapter.title}` : t('systemLogs.unknown')} · ${shortTechnicalId(value)}`;
            })}</label>
            <label className="text-sm font-medium text-gray-700">{t('systemLogs.filters.shot')}{select('shotId', shotOptions, !draft.chapterId, value => {
              const shot = metadata.shots[value];
              return `${shot ? `Shot ${shot.index}` : t('systemLogs.unknown')} · ${shortTechnicalId(value)}`;
            })}</label>
            <label className="text-sm font-medium text-gray-700">{t('systemLogs.filters.taskId')}{select('taskId', options.taskIds, false, shortTechnicalId)}</label>
            <label className="text-sm font-medium text-gray-700">{t('systemLogs.filters.errorCode')}{select('errorCode', options.errorCodes)}</label>
            <label className="text-sm font-medium text-gray-700">{t('systemLogs.filters.failureClass')}{select('failureClass', options.failureClasses)}</label>
          </div>
        </div>

        <footer className="flex shrink-0 items-center justify-end gap-3 border-t border-gray-200 bg-white p-4 sm:px-6">
          <button type="button" onClick={() => { setDraft(valuesFromState({ ...DEFAULT_FILTER_STATE, view: state.view })); onReset(); onClose(); }}
            className="btn-secondary min-h-[44px]">{t('systemLogs.reset')}</button>
          <button type="submit" className="btn-primary min-h-[44px]">{t('systemLogs.apply')}</button>
        </footer>
      </form>
    </dialog>
  );
}

const DEFAULT_FILTER_STATE: SystemLogUrlState = {
  view: 'attention', level: '', service: '', provider: '', novelId: '', chapterId: '',
  shotId: '', taskId: '', errorCode: '', failureClass: '', cursor: '', eventId: '',
};
