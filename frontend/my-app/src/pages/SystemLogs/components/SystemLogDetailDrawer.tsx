import { useRef } from 'react';
import { ExternalLink, Loader2, X } from 'lucide-react';
import { Link } from 'react-router-dom';
import type { SystemLogDetail, SystemLogItem } from '../../../api/systemLogs';
import { useTranslation } from '../../../stores/i18nStore';
import type { SystemLogDisplayMetadata } from '../displayMetadata';
import { TechnicalId } from './TechnicalId';
import { useSystemLogDialog } from './useSystemLogDialog';

interface Props {
  eventId: string;
  preview: SystemLogItem | null;
  detail: SystemLogDetail | null;
  metadata: SystemLogDisplayMetadata;
  loading: boolean;
  error: string;
  formatDate: (value: string | Date | null) => string;
  onClose: () => void;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-gray-200 bg-white p-4">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-[0.14em] text-gray-500">{title}</h3>
      <dl className="grid min-w-0 grid-cols-1 gap-x-5 gap-y-3 sm:grid-cols-2">{children}</dl>
    </section>
  );
}

function Field({ label, value, mono = false }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-gray-500">{label}</dt>
      <dd className={`mt-0.5 break-all text-sm text-gray-900 ${mono ? 'font-mono' : ''}`}>{value}</dd>
    </div>
  );
}

export function SystemLogDetailDrawer({ eventId, preview, detail, metadata, loading, error, formatDate, onClose }: Props) {
  const { t } = useTranslation();
  const dialogRef = useRef<HTMLDialogElement>(null);
  useSystemLogDialog(dialogRef);
  const event = detail || preview;
  const payload = detail?.detail;
  const diagnostic = payload?.diagnostic;
  const evidence = payload?.evidence || diagnostic?.evidence;
  const review = payload?.reviewFinding;
  const llm = payload?.llm;
  const llmLogId = llm?.logId || review?.evidence.firstFailedLlmLogId;
  const scope = event?.scope;
  const submission = diagnostic?.submission || event?.submission;
  const unknown = t('systemLogs.unknown');
  const unavailable = t('systemLogs.unavailable');
  const novel = scope?.novelId ? metadata.novels[scope.novelId] : null;
  const chapter = scope?.chapterId ? metadata.chapters[scope.chapterId] : null;
  const shotIndex = scope?.shotIndex ?? (scope?.shotId ? metadata.shots[scope.shotId]?.index : null);
  const show = (value: unknown): React.ReactNode => {
    if (value === null || value === undefined || value === '') return unknown;
    if (typeof value === 'boolean') return t(value ? 'systemLogs.boolean.yes' : 'systemLogs.boolean.no');
    return String(value);
  };

  const assetParams = new URLSearchParams();
  if (scope?.taskId) assetParams.set('task_id', scope.taskId);
  else if (scope?.novelId && scope.chapterId) {
    assetParams.set('novel_id', scope.novelId);
    assetParams.set('chapter_id', scope.chapterId);
    if (scope.shotId) assetParams.set('shot_id', scope.shotId);
  }
  const assetHref = assetParams.size ? `/asset-debug?${assetParams.toString()}` : null;

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby="system-log-detail-title"
      onCancel={event => { event.preventDefault(); onClose(); }}
      onClick={event => { if (event.target === event.currentTarget) onClose(); }}
      className="fixed inset-0 m-0 ml-auto h-[100dvh] max-h-none w-full max-w-none border-0 bg-gray-50 p-0 shadow-2xl backdrop:bg-gray-950/45 lg:left-auto lg:w-[min(760px,calc(100vw-5rem))]"
    >
      <div className="flex h-full min-h-0 flex-col">
        <header className="flex min-h-16 shrink-0 items-center justify-between gap-3 border-b border-gray-200 bg-white px-4 sm:px-6">
          <div className="min-w-0">
            <h2 id="system-log-detail-title" className="truncate text-lg font-semibold text-gray-900">{t('systemLogs.viewDetails')}</h2>
            <TechnicalId value={eventId} className="text-gray-500" />
          </div>
          <button type="button" onClick={onClose} aria-label={t('systemLogs.close')}
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-gray-500 hover:bg-gray-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500">
            <X aria-hidden="true" className="h-5 w-5" />
          </button>
        </header>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4 sm:p-6">
          {loading && <p role="status" className="flex items-center gap-2 rounded-xl border bg-white p-4 text-sm text-gray-600"><Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />{t('systemLogs.loading')}</p>}
          {error && <p role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</p>}
          {!event && !loading && !error && <p className="rounded-xl border bg-white p-4 text-sm text-gray-500">{unavailable}</p>}

          {event && <>
            <Section title={t('systemLogs.sections.overview')}>
              <Field label={t('systemLogs.fields.time')} value={formatDate(event.occurredAt)} />
              <Field label={t('systemLogs.fields.level')} value={show(event.level)} />
              <Field label={t('systemLogs.fields.diagnosticQuality')} value={event.diagnosticQualityFlags.length ? event.diagnosticQualityFlags.join(' · ') : unknown} />
              <Field label={t('systemLogs.fields.message')} value={show(event.summary)} />
              <Field label={t('systemLogs.fields.errorCode')} value={show(event.errorCode)} mono />
              <Field label={t('systemLogs.fields.failureClass')} value={show(event.failureClass)} mono />
            </Section>

            <Section title={t('systemLogs.sections.scope')}>
              <Field label={t('systemLogs.fields.taskId')} value={<TechnicalId value={scope?.taskId} />} />
              <Field label={t('systemLogs.fields.attemptKind')} value={show(scope?.attemptKind)} />
              <Field label={t('systemLogs.fields.attemptId')} value={<TechnicalId value={scope?.attemptId} />} />
              <Field label={t('systemLogs.fields.attemptNo')} value={show(scope?.attemptNo)} />
              <Field label={t('systemLogs.fields.retryNo')} value={show(scope?.retryNo)} />
              <Field label={t('systemLogs.fields.novelId')} value={<span><span className="block font-medium">{novel?.title || unknown}</span><TechnicalId value={scope?.novelId} /></span>} />
              <Field label={t('systemLogs.fields.chapterId')} value={<span><span className="block font-medium">{chapter ? `#${chapter.number} ${chapter.title}` : unknown}</span><TechnicalId value={scope?.chapterId} /></span>} />
              <Field label={t('systemLogs.fields.shotId')} value={<span><span className="block font-medium">{shotIndex != null ? `Shot ${shotIndex}` : unknown}</span><TechnicalId value={scope?.shotId} /></span>} />
              <Field label={t('systemLogs.fields.shotIndex')} value={shotIndex != null ? `Shot ${shotIndex}` : unknown} />
              <Field label={t('systemLogs.fields.clipIndex')} value={scope?.clipIndex != null ? `Clip ${scope.clipIndex}` : unknown} />
              <Field label={t('systemLogs.fields.frameIndex')} value={scope?.frameIndex != null ? `Frame ${scope.frameIndex}` : unknown} />
            </Section>

            <Section title={t('systemLogs.sections.operation')}>
              <Field label={t('systemLogs.fields.stage')} value={show(event.stage)} />
              <Field label={t('systemLogs.fields.operation')} value={show(event.operation)} />
              <Field label={t('systemLogs.fields.service')} value={show(event.service)} />
              <Field label={t('systemLogs.fields.provider')} value={show(event.provider)} />
            </Section>

            <Section title={t('systemLogs.sections.externalCall')}>
              <Field label={t('systemLogs.fields.endpoint')} value={show(diagnostic?.externalCall.endpoint)} mono />
              <Field label={t('systemLogs.fields.method')} value={show(diagnostic?.externalCall.method)} />
              <Field label={t('systemLogs.fields.elapsedMs')} value={show(diagnostic?.timing.elapsedMs)} />
              <Field label={t('systemLogs.fields.timeoutMs')} value={show(diagnostic?.externalCall.timeoutMs)} />
              <Field label={t('systemLogs.fields.exceptionType')} value={show(diagnostic?.externalCall.exceptionType)} />
              <Field label={t('systemLogs.fields.exceptionMessage')} value={show(diagnostic?.externalCall.exceptionMessage)} />
              <Field label={t('systemLogs.fields.httpStatus')} value={show(diagnostic?.externalCall.httpStatus)} />
              <Field label={t('systemLogs.fields.responseContentType')} value={show(diagnostic?.externalCall.responseContentType)} />
              <Field label={t('systemLogs.fields.responseBodySha256')} value={show(diagnostic?.externalCall.responseBodySha256)} mono />
              <Field label={t('systemLogs.fields.responseBodyBytes')} value={show(diagnostic?.externalCall.responseBodyBytes)} />
              <Field label={t('systemLogs.fields.responseExcerpt')} value={t('systemLogs.responseExcerptUnavailable')} />
            </Section>

            <Section title={t('systemLogs.sections.reference')}>
              <Field label={t('systemLogs.fields.referenceFilename')} value={show(diagnostic?.reference.filename)} />
              <Field label={t('systemLogs.fields.referenceBytes')} value={show(diagnostic?.reference.bytes)} />
              <Field label={t('systemLogs.fields.referenceSha256')} value={show(diagnostic?.reference.sha256)} mono />
              <Field label={t('systemLogs.fields.sourceId')} value={<TechnicalId value={diagnostic?.reference.sourceId} />} />
              <Field label={t('systemLogs.fields.revision')} value={show(diagnostic?.reference.revision)} />
            </Section>

            <Section title={t('systemLogs.sections.upstream')}>
              <Field label={t('systemLogs.fields.rsaId')} value={<TechnicalId value={diagnostic?.upstream.rsaId} />} />
              <Field label={t('systemLogs.fields.rsaHash')} value={show(diagnostic?.upstream.rsaHash)} mono />
              <Field label={t('systemLogs.fields.manifestHash')} value={show(diagnostic?.upstream.manifestHash)} mono />
            </Section>

            <Section title={t('systemLogs.sections.submission')}>
              <Field label={t('systemLogs.fields.queueCalled')} value={show(submission?.queueCalled)} />
              <Field label={t('systemLogs.fields.submitted')} value={show(submission?.submitted)} />
              <Field label={t('systemLogs.fields.submissionState')} value={show(submission?.state)} />
              <Field label={t('systemLogs.fields.cid')} value={<TechnicalId value={submission?.cid} />} />
              <Field label={t('systemLogs.fields.queueSeen')} value={show(submission?.queueSeen)} />
              <Field label={t('systemLogs.fields.remoteUploadEffect')} value={show(submission?.remoteUploadEffect)} />
            </Section>

            {review && <Section title={t('systemLogs.sections.review')}>
              <Field label={t('systemLogs.fields.message')} value={show(review.message)} />
              <Field label={t('systemLogs.fields.reviewStatus')} value={show(review.status)} />
              <Field label={t('systemLogs.fields.fallbackAction')} value={show(review.fallbackAction)} />
              <Field label={t('systemLogs.fields.fallbackOutcome')} value={show(review.fallbackOutcome)} />
              <Field label={t('systemLogs.fields.llmLogId')} value={<TechnicalId value={review.evidence.firstFailedLlmLogId} />} />
            </Section>}

            {llm && <Section title={t('systemLogs.sections.llm')}>
              <Field label={t('systemLogs.fields.llmLogId')} value={<TechnicalId value={llm.logId} />} />
              <Field label={t('systemLogs.fields.provider')} value={show(llm.provider)} />
              <Field label={t('systemLogs.fields.model')} value={show(llm.model)} />
              <Field label={t('systemLogs.fields.duration')} value={show(llm.durationSeconds)} />
            </Section>}

            <Section title={t('systemLogs.sections.evidence')}>
              <Field label={t('systemLogs.fields.evidenceId')} value={<TechnicalId value={evidence?.evidenceId} />} />
              <Field label={t('systemLogs.fields.evidencePath')} value={show(evidence?.path)} mono />
              <Field label={t('systemLogs.fields.evidenceSha256')} value={show(evidence?.sha256)} mono />
              <Field label={t('systemLogs.fields.evidenceBytes')} value={show(evidence?.bytes)} />
              <Field label={t('systemLogs.fields.evidenceTruncated')} value={show(evidence?.truncated)} />
              <Field label={t('systemLogs.fields.redactionVersion')} value={show(evidence?.redactionVersion)} />
            </Section>

            <Section title={t('systemLogs.sections.links')}>
              {scope?.taskId ? <Field label={t('systemLogs.links.task')} value={<Link className="inline-flex min-h-[44px] items-center gap-1 text-primary-700 underline" to="/tasks">{t('systemLogs.links.task')}<ExternalLink aria-hidden="true" className="h-4 w-4" /></Link>} /> : null}
              {assetHref ? <Field label={t('systemLogs.links.assetDebug')} value={<Link className="inline-flex min-h-[44px] items-center gap-1 text-primary-700 underline" to={assetHref}>{t('systemLogs.links.assetDebug')}<ExternalLink aria-hidden="true" className="h-4 w-4" /></Link>} /> : null}
              {llmLogId ? <Field label={t('systemLogs.links.llmLog')} value={<Link className="inline-flex min-h-[44px] items-center gap-1 text-primary-700 underline" to="/llm-logs" title={llmLogId}>{t('systemLogs.links.llmLog')}<ExternalLink aria-hidden="true" className="h-4 w-4" /></Link>} /> : null}
              {!scope?.taskId && !assetHref && !llmLogId ? <Field label={t('systemLogs.sections.links')} value={unavailable} /> : null}
            </Section>
          </>}
        </div>
      </div>
    </dialog>
  );
}
