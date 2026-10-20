export const logColumns = [
  { key: 'time', label: '时间', required: true },
  { key: 'provider', label: 'LLM 提供商' },
  { key: 'model', label: '模型' },
  { key: 'task_type', label: '任务类型', required: true },
  { key: 'novel', label: '小说' },
  { key: 'chapter', label: '章回' },
  { key: 'shot', label: 'Shot' },
  { key: 'template', label: '提示词名称' },
  { key: 'status', label: '状态', required: true },
  { key: 'proxy', label: '代理' },
  { key: 'duration', label: '耗时' },
  { key: 'speed', label: '速度 (Tokens/s)' },
  { key: 'input_tokens', label: '输入 Token' },
  { key: 'output_tokens', label: '输出 Token' },
  { key: 'total_tokens', label: '总 Token' },
  { key: 'prompt', label: '提示词预览' },
] as const;

export type LogColumnKey = typeof logColumns[number]['key'];
export const requiredLogColumns = new Set<LogColumnKey>(['time', 'task_type', 'status']);
export const defaultLogColumns: LogColumnKey[] = [
  'time', 'provider', 'model', 'task_type', 'novel', 'chapter', 'shot',
  'template', 'status', 'proxy', 'duration', 'speed', 'total_tokens', 'prompt',
];
export const LOG_COLUMNS_STORAGE_KEY = 'llm-log-visible-columns-v1';

export function chapterLabel(number: number | null | undefined, title: string | null | undefined, id: string | null | undefined): string {
  if (number == null) return id || '—';
  const name = title?.trim() || '';
  return /^第.{1,10}章/.test(name) ? name : `第${number}章${name ? ` · ${name}` : ''}`;
}

export function normalizeLogColumns(value: unknown): LogColumnKey[] {
  if (!Array.isArray(value)) return [...defaultLogColumns];
  const selected = new Set(value.filter((key): key is LogColumnKey =>
    typeof key === 'string' && logColumns.some(column => column.key === key)));
  requiredLogColumns.forEach(key => selected.add(key));
  return logColumns.map(column => column.key).filter(key => selected.has(key));
}
