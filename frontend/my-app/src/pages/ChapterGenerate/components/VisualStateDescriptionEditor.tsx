import { useRef, useState } from 'react';
import { Loader2, Save } from 'lucide-react';

interface Props {
  description: string;
  label: string;
  revision: number;
  disabled?: boolean;
  onSave: (description: string, expectedDescription: string, expectedRevision: number) => Promise<void>;
}

export function VisualStateDescriptionEditor({ description, label, revision, disabled, onSave }: Props) {
  const [draft, setDraft] = useState<{ text: string; original: string; revision: number } | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const savingRef = useRef(false);

  const save = async () => {
    if (!draft || disabled || savingRef.current || !draft.text.trim()) return;
    savingRef.current = true;
    setSaving(true);
    setError('');
    try {
      await onSave(draft.text.trim(), draft.original, draft.revision);
      setDraft(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '保存失败，请重试');
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  };

  return (
    <div>
      <div className="mb-1 flex items-center justify-between gap-2">
        <label className="text-xs font-semibold text-gray-600">{label}</label>
        <div className="flex items-center gap-2">
          {draft ? <>
            <button type="button" onClick={() => { setDraft(null); setError(''); }} disabled={saving} className="text-xs text-gray-500 hover:text-gray-700 disabled:opacity-50">取消</button>
            <button type="button" onClick={() => void save()} disabled={saving || disabled || !draft.text.trim() || draft.text.trim() === draft.original}
              className="inline-flex items-center gap-1 rounded border border-blue-200 px-2 py-0.5 text-xs text-blue-700 hover:bg-blue-50 disabled:opacity-50">
              {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}{saving ? '保存中...' : '保存'}
            </button>
          </> : <button type="button" disabled={disabled} onClick={() => { setError(''); setDraft({ text: description, original: description, revision }); }}
            title={disabled ? '生成或规划中，完成后可编辑' : `编辑${label}`} className="text-xs text-blue-600 hover:text-blue-800 disabled:opacity-50">编辑</button>}
        </div>
      </div>
      <textarea aria-label={label} readOnly={!draft} disabled={saving}
        value={draft ? draft.text : description} onChange={event => setDraft(value => value ? { ...value, text: event.target.value } : null)}
        className={`h-28 w-full resize-none rounded-lg border px-3 py-2 text-sm ${draft ? 'border-blue-300 bg-white focus:ring-1 focus:ring-blue-400' : 'border-gray-200 bg-gray-50'}`} />
      {error && <p role="alert" className="mt-1 text-xs text-red-600">{error}</p>}
    </div>
  );
}
