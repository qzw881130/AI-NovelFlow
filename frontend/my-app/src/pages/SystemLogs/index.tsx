import { useState } from 'react';
import { AlertTriangle, ChevronLeft, ChevronRight, Eye, Filter, Loader2, RefreshCw, ScrollText } from 'lucide-react';
import type { SystemLogItem, SystemLogView } from '../../api/systemLogs';
import { useTranslation } from '../../stores/i18nStore';
import { SystemLogDetailDrawer } from './components/SystemLogDetailDrawer';
import { SystemLogFilters } from './components/SystemLogFilters';
import { TechnicalId } from './components/TechnicalId';
import type { SystemLogDisplayMetadata } from './displayMetadata';
import { useSystemLogsState } from './hooks/useSystemLogsState';

const VIEW_KEYS: Array<[SystemLogView, string]> = [
  ['attention', 'attention'],
  ['errors', 'errors'],
  ['needs_review', 'needsReview'],
  ['all', 'all'],
];

const levelClasses: Record<string, string> = {
  ERROR: 'border-red-200 bg-red-50 text-red-700',
  REVIEW_REQUIRED: 'border-amber-200 bg-amber-50 text-amber-800',
  WARNING: 'border-yellow-200 bg-yellow-50 text-yellow-800',
  INFO: 'border-blue-200 bg-blue-50 text-blue-700',
};

function LevelBadge({ level }: { level: string }) {
  const { t } = useTranslation();
  return (
    <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${levelClasses[level] || 'border-gray-200 bg-gray-50 text-gray-700'}`}>
      {t(`systemLogs.levels.${level}`, { defaultValue: level })}
    </span>
  );
}

const compactScope = (item: SystemLogItem, metadata: SystemLogDisplayMetadata, unknown: string) => {
  const shotIndex = item.scope.shotIndex ?? (item.scope.shotId ? metadata.shots[item.scope.shotId]?.index : null);
  const values = [
    shotIndex != null ? `Shot ${shotIndex}` : null,
    item.scope.clipIndex != null ? `Clip ${item.scope.clipIndex}` : null,
    item.scope.frameIndex != null ? `Frame ${item.scope.frameIndex}` : null,
  ].filter(Boolean);
  return values.length ? values.join(' · ') : unknown;
};

export function SystemLogTableRow({ item, metadata, formatDate, onView }: {
  item: SystemLogItem;
  metadata: SystemLogDisplayMetadata;
  formatDate: (value: string | Date | null) => string;
  onView: () => void;
}) {
  const { t } = useTranslation();
  const unknown = t('systemLogs.unknown');
  const novel = item.scope.novelId ? metadata.novels[item.scope.novelId] : null;
  const chapter = item.scope.chapterId ? metadata.chapters[item.scope.chapterId] : null;
  return (
    <tr className="align-top hover:bg-gray-50">
      <td className="whitespace-nowrap px-3 py-3 text-xs text-gray-600">{formatDate(item.occurredAt)}</td>
      <td className="px-3 py-3"><LevelBadge level={item.level} /></td>
      <td className="px-3 py-3 text-sm text-gray-800"><span className="font-medium">{item.service || unknown}</span><span className="block text-xs text-gray-500">{item.provider || unknown}</span></td>
      <td className="px-3 py-3 text-sm text-gray-700"><span>{item.stage || unknown}</span><span className="block text-xs text-gray-500">{item.operation || unknown}</span></td>
      <td className="min-w-[190px] px-3 py-3 text-sm text-gray-800">
        <span className="block font-medium">{novel?.title || unknown}</span>
        <span className="block text-xs text-gray-600">{chapter ? `#${chapter.number} ${chapter.title}` : unknown}</span>
        <span className="mt-1 block text-gray-400"><TechnicalId value={item.scope.chapterId || item.scope.novelId} /></span>
      </td>
      <td className="px-3 py-3 text-xs text-gray-600">{compactScope(item, metadata, unknown)}{item.scope.shotId && <span className="mt-1 block text-gray-400"><TechnicalId value={item.scope.shotId} /></span>}</td>
      <td className="max-w-[150px] px-3 py-3 text-xs text-gray-600"><TechnicalId value={item.scope.taskId} /></td>
      <td className="max-w-[170px] px-3 py-3 font-mono text-xs text-gray-700"><span className="block break-all">{item.errorCode || unknown}</span></td>
      <td className="px-3 py-3 font-mono text-xs text-gray-600">{item.failureClass || unknown}</td>
      <td className="min-w-[220px] max-w-[360px] px-3 py-3 text-sm text-gray-700"><p className="line-clamp-2" title={item.summary}>{item.summary || unknown}</p></td>
      <td className="px-3 py-3">
        <button type="button" onClick={onView} className="inline-flex min-h-[44px] items-center gap-1 rounded-lg px-3 text-sm font-medium text-primary-700 hover:bg-primary-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500">
          <Eye aria-hidden="true" className="h-4 w-4" />{t('systemLogs.viewDetails')}
        </button>
      </td>
    </tr>
  );
}

export function SystemLogCard({ item, metadata, formatDate, onView }: {
  item: SystemLogItem;
  metadata: SystemLogDisplayMetadata;
  formatDate: (value: string | Date | null) => string;
  onView: () => void;
}) {
  const { t } = useTranslation();
  const unknown = t('systemLogs.unknown');
  const novel = item.scope.novelId ? metadata.novels[item.scope.novelId] : null;
  const chapter = item.scope.chapterId ? metadata.chapters[item.scope.chapterId] : null;
  return (
    <article className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs text-gray-500">{formatDate(item.occurredAt)}</p>
          <p className="mt-1 truncate text-sm font-semibold text-gray-900">{item.service || unknown}{item.provider ? ` / ${item.provider}` : ''}</p>
        </div>
        <LevelBadge level={item.level} />
      </div>
      <p className="mt-3 line-clamp-2 text-sm leading-6 text-gray-700">{item.summary || unknown}</p>
      <div className="mt-3 space-y-1 text-xs text-gray-500">
        <p>{novel?.title || unknown}{chapter ? ` · #${chapter.number} ${chapter.title}` : ''}</p>
        <p>{compactScope(item, metadata, unknown)}</p>
        <p className="break-all font-mono">{item.errorCode || unknown} · {item.failureClass || unknown}</p>
        <TechnicalId value={item.scope.taskId} />
      </div>
      <button type="button" onClick={onView} className="mt-3 inline-flex min-h-[44px] w-full items-center justify-center gap-1 rounded-lg border border-gray-200 text-sm font-medium text-primary-700 hover:bg-primary-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500">
        <Eye aria-hidden="true" className="h-4 w-4" />{t('systemLogs.viewDetails')}
      </button>
    </article>
  );
}

export default function SystemLogs() {
  const { t } = useTranslation();
  const state = useSystemLogsState();
  const [filtersOpen, setFiltersOpen] = useState(false);

  return (
    <main className="min-w-0 space-y-4 sm:space-y-6" aria-labelledby="system-logs-title">
      <header className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 id="system-logs-title" className="text-2xl font-bold text-gray-900">{t('systemLogs.title')}</h1>
          <p className="mt-1 text-sm text-gray-500">{t('systemLogs.subtitle')}</p>
          <p className="mt-1 text-xs text-gray-400">{t('systemLogs.refreshedAt', { time: state.formatDate(state.lastUpdated) })}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={() => setFiltersOpen(true)} className="btn-secondary min-h-[44px] gap-2">
            <Filter aria-hidden="true" className="h-4 w-4" />{t('systemLogs.filterButton')}
            {state.activeFilterCount > 0 && <span className="rounded-full bg-primary-100 px-2 py-0.5 text-xs text-primary-800">{state.activeFilterCount}</span>}
          </button>
          <button type="button" onClick={state.refresh} disabled={state.refreshing} className="btn-secondary min-h-[44px] gap-2 disabled:opacity-60">
            <RefreshCw aria-hidden="true" className={`h-4 w-4 ${state.refreshing ? 'animate-spin' : ''}`} />{t('systemLogs.refresh')}
          </button>
        </div>
      </header>

      <nav aria-label={t('systemLogs.title')} className="grid grid-cols-2 gap-2 rounded-xl border border-gray-200 bg-white p-2 sm:flex sm:w-fit">
        {VIEW_KEYS.map(([view, key]) => (
          <button key={view} type="button" onClick={() => state.changeView(view)} aria-pressed={state.urlState.view === view}
            className={`min-h-[44px] rounded-lg px-4 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 ${state.urlState.view === view ? 'bg-gray-900 text-white shadow-sm' : 'text-gray-600 hover:bg-gray-100'}`}>
            {t(`systemLogs.views.${key}`)}
          </button>
        ))}
      </nav>

      {state.listError && <div role="alert" className="flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700"><AlertTriangle aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" /><span className="break-all">{state.listError}</span></div>}

      <section className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm" aria-label={t('systemLogs.title')}>
        {state.loading ? (
          <div role="status" className="flex min-h-64 items-center justify-center gap-2 text-sm text-gray-500"><Loader2 aria-hidden="true" className="h-5 w-5 animate-spin" />{t('systemLogs.loading')}</div>
        ) : state.items.length === 0 ? (
          <div className="flex min-h-64 flex-col items-center justify-center p-6 text-center text-gray-500"><ScrollText aria-hidden="true" className="mb-3 h-10 w-10 text-gray-300" /><p>{t('systemLogs.noLogs')}</p></div>
        ) : <>
          <div className="hidden overflow-x-auto lg:block">
            <table className="min-w-[1500px] divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>{[
                  'time', 'level', 'service', 'stage', 'bookChapter', 'shotClipFrame',
                  'task', 'errorCode', 'failureClass', 'summary', 'details',
                ].map(column => <th key={column} className="px-3 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">{t(`systemLogs.columns.${column}`)}</th>)}</tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white">
                {state.items.map(item => <SystemLogTableRow key={item.eventId} item={item} metadata={state.displayMetadata} formatDate={state.formatDate} onView={() => state.openDetail(item.eventId)} />)}
              </tbody>
            </table>
          </div>
          <div className="space-y-3 bg-gray-50 p-3 lg:hidden">
            {state.items.map(item => <SystemLogCard key={item.eventId} item={item} metadata={state.displayMetadata} formatDate={state.formatDate} onView={() => state.openDetail(item.eventId)} />)}
          </div>
        </>}

        {(state.urlState.cursor || state.hasMore) && (
          <footer className="flex items-center justify-between gap-3 border-t border-gray-200 bg-white p-3 sm:px-4">
            <button type="button" onClick={state.previousPage} disabled={!state.urlState.cursor} className="btn-secondary min-h-[44px] gap-1 disabled:cursor-not-allowed disabled:opacity-40">
              <ChevronLeft aria-hidden="true" className="h-4 w-4" />{t('systemLogs.previous')}
            </button>
            <button type="button" onClick={state.nextPage} disabled={!state.hasMore || !state.nextCursor} className="btn-secondary min-h-[44px] gap-1 disabled:cursor-not-allowed disabled:opacity-40">
              {t('systemLogs.next')}<ChevronRight aria-hidden="true" className="h-4 w-4" />
            </button>
          </footer>
        )}
      </section>

      {filtersOpen && <SystemLogFilters state={state.urlState} options={state.filterOptions} optionsError={state.filterOptionsError} metadata={state.displayMetadata}
        onApply={state.applyFilters} onReset={state.resetFilters} onClose={() => setFiltersOpen(false)} />}
      {state.urlState.eventId && <SystemLogDetailDrawer eventId={state.urlState.eventId} preview={state.selectedPreview}
        detail={state.detail} metadata={state.displayMetadata} loading={state.detailLoading} error={state.detailError} formatDate={state.formatDate} onClose={state.closeDetail} />}
    </main>
  );
}
