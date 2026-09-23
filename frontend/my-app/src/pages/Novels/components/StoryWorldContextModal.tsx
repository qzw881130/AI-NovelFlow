import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Globe2, Loader2, LockKeyhole, Pencil, RefreshCw, X } from 'lucide-react';
import { novelApi, type StoryWorldContext } from '../../../api/novels';
import type { Novel } from '../../../types';
import { toast } from '../../../stores/toastStore';

interface StoryWorldContextModalProps {
  novel: Novel;
  onClose: () => void;
  onSaved: () => Promise<void>;
}

const EMPTY_CONTEXT: StoryWorldContext = {
  world_type: '',
  era: '',
  historical_period: '',
  geographic_scope: '',
  cultural_system: '',
  technology_level: '',
  allow_time_travel: false,
  material_culture: { clothing: '', architecture: '', objects: '' },
  visual_exclusions: [],
};

const textFields: Array<{ key: keyof StoryWorldContext; label: string }> = [
  { key: 'world_type', label: '世界类型' },
  { key: 'era', label: '时代层级' },
  { key: 'historical_period', label: '具体历史时期' },
  { key: 'geographic_scope', label: '地域范围' },
  { key: 'cultural_system', label: '文化体系' },
  { key: 'technology_level', label: '技术水平' },
];

export function StoryWorldContextModal({ novel, onClose, onSaved }: StoryWorldContextModalProps) {
  const [context, setContext] = useState<StoryWorldContext | null>(null);
  const [locked, setLocked] = useState(false);
  const [editing, setEditing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [recommending, setRecommending] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const descriptionFallback = !String(novel.description || '').trim();

  const recommend = async () => {
    setRecommending(true);
    setError('');
    try {
      const result = await novelApi.recommendStoryWorldContext(novel.id);
      if (!result.success || !result.data?.context) {
        throw new Error(result.message || '故事世界上下文推荐失败');
      }
      setContext(result.data.context);
      setLocked(false);
      setEditing(false);
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : '故事世界上下文推荐失败';
      setError(message);
      toast.error(message);
    } finally {
      setRecommending(false);
      setLoading(false);
    }
  };

  useEffect(() => {
    let active = true;
    const load = async () => {
      setLoading(true);
      try {
        const result = await novelApi.fetchStoryWorldContext(novel.id);
        if (!active) return;
        if (result.success && result.data?.context) {
          setContext(result.data.context);
          setLocked(result.data.locked);
          setLoading(false);
          return;
        }
        await recommend();
      } catch {
        if (active) await recommend();
      }
    };
    void load();
    return () => { active = false; };
  }, [novel.id]);

  const updateField = (key: keyof StoryWorldContext, value: string | boolean) => {
    setContext((current) => current ? { ...current, [key]: value } : current);
  };

  const updateMaterial = (key: keyof StoryWorldContext['material_culture'], value: string) => {
    setContext((current) => current ? {
      ...current,
      material_culture: { ...current.material_culture, [key]: value },
    } : current);
  };

  const validate = (value: StoryWorldContext) => {
    const required = textFields.map((field) => String(value[field.key] || '').trim());
    const materials = Object.values(value.material_culture).map((item) => item.trim());
    if ([...required, ...materials].some((item) => !item)) return '请完整填写故事世界上下文';
    if (value.visual_exclusions.length < 2 || value.visual_exclusions.length > 5) return '视觉排除项需要填写 2 至 5 项';
    return '';
  };

  const saveAndLock = async () => {
    if (!context) return;
    const validationError = validate(context);
    if (validationError) {
      setError(validationError);
      return;
    }
    setSaving(true);
    setError('');
    try {
      const result = await novelApi.saveStoryWorldContext(novel.id, context);
      if (!result.success || !result.data?.context) throw new Error(result.message || '保存故事世界上下文失败');
      setContext(result.data.context);
      setLocked(true);
      setEditing(false);
      await onSaved();
      toast.success('故事世界上下文已确认并锁定');
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : '保存故事世界上下文失败';
      setError(message);
      toast.error(message);
    } finally {
      setSaving(false);
    }
  };

  return createPortal(
    <div className="fixed inset-0 z-[300] flex items-center justify-center bg-black/55 p-4" role="dialog" aria-modal="true" aria-label="故事世界上下文">
      <div className="flex max-h-[92vh] w-full max-w-4xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-gray-200 px-6 py-4">
          <div>
            <div className="flex items-center gap-2">
              <Globe2 className="h-5 w-5 text-teal-600" />
              <h2 className="text-lg font-semibold text-gray-900">故事世界上下文</h2>
              {locked && <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2 py-0.5 text-xs text-green-700"><LockKeyhole className="h-3 w-3" />已锁定</span>}
            </div>
            <p className="mt-1 text-sm text-gray-500">《{novel.title}》 · 使用 #01 故事世界上下文推荐</p>
          </div>
          <button type="button" onClick={onClose} disabled={saving} className="rounded-lg p-2 text-gray-400 hover:bg-gray-100 hover:text-gray-600"><X className="h-5 w-5" /></button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          {descriptionFallback && (
            <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              小说描述为空，本次推荐使用小说名称“{novel.title}”同时作为名称和描述输入。
            </div>
          )}
          {(loading || recommending) && !context ? (
            <div className="flex min-h-64 items-center justify-center gap-2 text-gray-500"><Loader2 className="h-5 w-5 animate-spin" />正在调用 #01 推荐故事世界上下文...</div>
          ) : context ? (
            <div className="space-y-5">
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {textFields.map((field) => (
                  <label key={field.key} className="block text-sm font-medium text-gray-700">
                    {field.label}
                    <input
                      value={String(context[field.key] || '')}
                      onChange={(event) => updateField(field.key, event.target.value)}
                      readOnly={!editing}
                      className={`input-field mt-1 ${!editing ? 'bg-gray-50' : ''}`}
                    />
                  </label>
                ))}
              </div>

              <label className="flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-700">
                <input type="checkbox" checked={context.allow_time_travel} onChange={(event) => updateField('allow_time_travel', event.target.checked)} disabled={!editing} />
                允许原作明确支持的跨时代元素
              </label>

              <div>
                <h3 className="mb-3 text-sm font-semibold text-gray-800">物质文化体系</h3>
                <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                  {([
                    ['clothing', '服饰体系'],
                    ['architecture', '建筑体系'],
                    ['objects', '器物体系'],
                  ] as const).map(([key, label]) => (
                    <label key={key} className="block text-sm font-medium text-gray-700">
                      {label}
                      <textarea value={context.material_culture[key]} onChange={(event) => updateMaterial(key, event.target.value)} readOnly={!editing} rows={3} className={`input-field mt-1 ${!editing ? 'bg-gray-50' : ''}`} />
                    </label>
                  ))}
                </div>
              </div>

              <label className="block text-sm font-medium text-gray-700">
                视觉排除项 <span className="font-normal text-gray-400">每行一项，2 至 5 项</span>
                <textarea
                  value={context.visual_exclusions.join('\n')}
                  onChange={(event) => setContext({ ...context, visual_exclusions: event.target.value.split('\n').map((item) => item.trim()).filter(Boolean).slice(0, 5) })}
                  readOnly={!editing}
                  rows={5}
                  className={`input-field mt-1 ${!editing ? 'bg-gray-50' : ''}`}
                />
              </label>
            </div>
          ) : (
            <div className="rounded-lg border border-dashed border-gray-300 p-8 text-center text-gray-500">暂无故事世界上下文，请重新推荐。</div>
          )}
          {error && <p className="mt-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p>}
        </div>

        <div className="flex flex-wrap items-center justify-end gap-3 border-t border-gray-200 px-6 py-4">
          <button type="button" onClick={() => void recommend()} disabled={recommending || saving} className="btn-secondary">
            {recommending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}重新推荐
          </button>
          <button type="button" onClick={() => setEditing(true)} disabled={!context || recommending || saving || editing} className="btn-secondary"><Pencil className="mr-2 h-4 w-4" />编辑</button>
          <button type="button" onClick={() => void saveAndLock()} disabled={!context || recommending || saving} className="btn-primary">
            {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <LockKeyhole className="mr-2 h-4 w-4" />}确认并锁定
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
