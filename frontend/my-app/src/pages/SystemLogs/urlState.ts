import type { SystemLogListQuery, SystemLogView } from '../../api/systemLogs';

export interface SystemLogUrlState {
  view: SystemLogView;
  level: string;
  service: string;
  provider: string;
  novelId: string;
  chapterId: string;
  shotId: string;
  taskId: string;
  errorCode: string;
  failureClass: string;
  cursor: string;
  eventId: string;
}

export const DEFAULT_SYSTEM_LOG_STATE: SystemLogUrlState = {
  view: 'attention',
  level: '',
  service: '',
  provider: '',
  novelId: '',
  chapterId: '',
  shotId: '',
  taskId: '',
  errorCode: '',
  failureClass: '',
  cursor: '',
  eventId: '',
};

const VIEWS: SystemLogView[] = ['attention', 'errors', 'needs_review', 'all'];

export function parseSystemLogUrlState(params: URLSearchParams): SystemLogUrlState {
  const view = params.get('view');
  const state: SystemLogUrlState = {
    view: VIEWS.includes(view as SystemLogView) ? view as SystemLogView : 'attention',
    level: params.get('level') || '',
    service: params.get('service') || '',
    provider: params.get('provider') || '',
    novelId: params.get('novel_id') || '',
    chapterId: params.get('chapter_id') || '',
    shotId: params.get('shot_id') || '',
    taskId: params.get('task_id') || '',
    errorCode: params.get('error_code') || '',
    failureClass: params.get('failure_class') || '',
    cursor: params.get('cursor') || '',
    eventId: params.get('event') || '',
  };
  if (!state.novelId) {
    state.chapterId = '';
    state.shotId = '';
  } else if (!state.chapterId) {
    state.shotId = '';
  }
  return state;
}

export function serializeSystemLogUrlState(state: SystemLogUrlState): URLSearchParams {
  const params = new URLSearchParams();
  params.set('view', state.view);
  const values: Array<[string, string]> = [
    ['level', state.level], ['service', state.service], ['provider', state.provider],
    ['novel_id', state.novelId], ['chapter_id', state.chapterId], ['shot_id', state.shotId],
    ['task_id', state.taskId], ['error_code', state.errorCode],
    ['failure_class', state.failureClass], ['cursor', state.cursor], ['event', state.eventId],
  ];
  values.forEach(([key, value]) => { if (value) params.set(key, value); });
  return params;
}

export function updateSystemLogUrlState(
  current: SystemLogUrlState,
  patch: Partial<SystemLogUrlState>,
  options: { keepCursor?: boolean; keepEvent?: boolean } = {},
): SystemLogUrlState {
  const next = { ...current, ...patch };
  if (patch.novelId !== undefined && patch.novelId !== current.novelId) {
    if (patch.chapterId === undefined) next.chapterId = '';
    if (patch.shotId === undefined) next.shotId = '';
  }
  if (patch.chapterId !== undefined && patch.chapterId !== current.chapterId && patch.shotId === undefined) {
    next.shotId = '';
  }
  if (!next.novelId) {
    next.chapterId = '';
    next.shotId = '';
  } else if (!next.chapterId) {
    next.shotId = '';
  }
  if (!options.keepCursor) next.cursor = '';
  if (!options.keepEvent) next.eventId = '';
  return next;
}

export function systemLogQueryFromState(state: SystemLogUrlState): SystemLogListQuery {
  return {
    view: state.view,
    level: state.level || undefined,
    service: state.service || undefined,
    provider: state.provider || undefined,
    novel_id: state.novelId || undefined,
    chapter_id: state.chapterId || undefined,
    shot_id: state.shotId || undefined,
    task_id: state.taskId || undefined,
    error_code: state.errorCode || undefined,
    failure_class: state.failureClass || undefined,
    cursor: state.cursor || undefined,
    limit: 50,
  };
}

export function countSystemLogFilters(state: SystemLogUrlState): number {
  return [
    state.level, state.service, state.provider, state.novelId, state.chapterId,
    state.shotId, state.taskId, state.errorCode, state.failureClass,
  ].filter(Boolean).length;
}
