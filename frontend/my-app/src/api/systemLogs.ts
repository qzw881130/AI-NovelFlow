import { api } from './index';

export type SystemLogView = 'attention' | 'errors' | 'needs_review' | 'all';

export type SystemLogSource =
  | 'external_failure_observation'
  | 'task_compact_diagnostic'
  | 'review_finding'
  | 'task_terminal'
  | 'llm_lifecycle';

export type SystemLogQualityFlag =
  | 'STRUCTURED_V1'
  | 'LEGACY_SUMMARY_ONLY'
  | 'TIMESTAMP_FALLBACK'
  | 'UNKNOWN_SUBMISSION_STATE'
  | 'NOT_SUBMITTED_PROVEN';

export interface SystemLogScope {
  novelId: string | null;
  chapterId: string | null;
  shotId: string | null;
  shotIndex: number | null;
  clipIndex: number | null;
  frameIndex: number | null;
  referenceIndex: number | null;
  taskId: string | null;
  attemptKind: string | null;
  attemptId: string | null;
  attemptNo: number | null;
  retryNo: number | null;
}

export interface SystemLogSubmission {
  queueCalled?: boolean | null;
  submitted?: boolean | null;
  state: string | null;
  cid: string | null;
  queueSeen?: boolean | null;
  remoteUploadEffect?: string | null;
}

export interface SystemLogItem {
  eventId: string;
  source: SystemLogSource;
  occurredAt: string;
  level: string;
  service: string;
  provider: string | null;
  stage: string;
  operation: string;
  errorCode: string;
  failureClass: string | null;
  summary: string;
  scope: SystemLogScope;
  submission: SystemLogSubmission | null;
  diagnosticQuality: SystemLogQualityFlag | null;
  diagnosticQualityFlags: SystemLogQualityFlag[];
}

export interface SystemLogEvidence {
  evidenceId: string | null;
  path: string | null;
  sha256: string | null;
  bytes: number | null;
  truncated: boolean | null;
  redactionVersion: number | null;
}

export interface SystemLogDiagnostic {
  version: number;
  diagnosticId: string;
  errorCode: string;
  failureClass: string;
  level: string;
  stage: string;
  operation: string;
  service: string;
  provider: string | null;
  scope: SystemLogScope;
  timing: { startedAt: string | null; finishedAt: string | null; elapsedMs: number | null };
  reference: {
    referenceIndex: number | null;
    filename: string | null;
    bytes: number | null;
    sha256: string | null;
    sourceId: string | null;
    revision: string | number | boolean | null;
  };
  upstream: { rsaId: string | null; rsaHash: string | null; manifestHash: string | null };
  externalCall: {
    endpoint: string | null;
    method: string | null;
    timeoutMs: number | null;
    exceptionType: string | null;
    exceptionMessage: string | null;
    httpStatus: number | null;
    responseContentType: string | null;
    responseBodySha256: string | null;
    responseBodyBytes: number | null;
    responseExcerptTruncated: boolean | null;
    receiptStatus: string | null;
    receiptViolation: string | null;
  };
  submission: {
    queueCalled: boolean | null;
    submitted: boolean | null;
    state: string | null;
    cid: string | null;
    queueSeen: boolean | null;
    remoteUploadEffect: string | null;
  };
  evidence: SystemLogEvidence;
  redacted: boolean;
  truncated: boolean;
}

export interface SystemLogDetailPayload {
  diagnostic?: SystemLogDiagnostic;
  evidence?: SystemLogEvidence;
  domainState?: {
    taskId?: string;
    taskType?: string;
    taskStatus?: string;
    novelId?: string | null;
    chapterId?: string | null;
    shotId?: string | null;
    attemptNo?: number | null;
    completedAt?: string | null;
    availability?: string;
  } | null;
  llm?: {
    logId: string;
    provider: string;
    model: string;
    status: string;
    taskType: string | null;
    durationSeconds: number | null;
  };
  reviewFinding?: {
    findingId: string;
    code: string;
    message: string;
    status: string;
    fallbackAction: string;
    fallbackOutcome: string;
    evidence: {
      attemptExecutionPath: string;
      firstFailedLlmLogId: string;
      firstResponseSha256: string;
      frozenInputSha256: string;
      manifestSha256: string;
      rsaHash: string;
      templateSha256: string;
    };
  };
}

export interface SystemLogDetail extends SystemLogItem {
  detail: SystemLogDetailPayload;
}

export interface SystemLogListData {
  items: SystemLogItem[];
  nextCursor: string | null;
  hasMore: boolean;
}

export interface SystemLogFilterData {
  views: SystemLogView[];
  levels: string[];
  services: string[];
  providers: string[];
  errorCodes: string[];
  failureClasses: string[];
  novelIds: string[];
  chapterIds: string[];
  shotIds: string[];
  taskIds: string[];
}

export interface SystemLogListQuery {
  view?: SystemLogView;
  level?: string;
  service?: string;
  provider?: string;
  novel_id?: string;
  chapter_id?: string;
  shot_id?: string;
  task_id?: string;
  error_code?: string;
  failure_class?: string;
  cursor?: string;
  limit?: number;
}

const append = (params: URLSearchParams, key: string, value: string | number | undefined) => {
  if (value !== undefined && value !== '') params.set(key, String(value));
};

export const buildSystemLogQuery = (query: SystemLogListQuery = {}) => {
  const params = new URLSearchParams();
  append(params, 'view', query.view);
  append(params, 'level', query.level);
  append(params, 'service', query.service);
  append(params, 'provider', query.provider);
  append(params, 'novel_id', query.novel_id);
  append(params, 'chapter_id', query.chapter_id);
  append(params, 'shot_id', query.shot_id);
  append(params, 'task_id', query.task_id);
  append(params, 'error_code', query.error_code);
  append(params, 'failure_class', query.failure_class);
  append(params, 'cursor', query.cursor);
  append(params, 'limit', query.limit);
  return params.toString();
};

export const systemLogsApi = {
  list(query: SystemLogListQuery = {}, signal?: AbortSignal) {
    const encoded = buildSystemLogQuery(query);
    return api.get<SystemLogListData>(`/system-logs/${encoded ? `?${encoded}` : ''}`, { signal });
  },
  filters(signal?: AbortSignal) {
    return api.get<SystemLogFilterData>('/system-logs/filters', { signal });
  },
  detail(eventId: string, signal?: AbortSignal) {
    return api.get<SystemLogDetail>(`/system-logs/${encodeURIComponent(eventId)}`, { signal });
  },
};
