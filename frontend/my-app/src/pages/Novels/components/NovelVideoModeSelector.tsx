export type NovelVideoMode = 'grid' | 'single';

interface NovelVideoModeSelectorProps {
  value: NovelVideoMode;
  onChange?: (value: NovelVideoMode) => void;
  disabled?: boolean;
  note?: string;
}

export function NovelVideoModeSelector({ value, onChange, disabled = false, note }: NovelVideoModeSelectorProps) {
  const choices: { value: NovelVideoMode; label: string; description: string }[] = [
    { value: 'grid', label: '宫格图生视频', description: '2×2 / 2×3 宫格规划，逐格审阅，再分配 Clip。' },
    { value: 'single', label: '单镜图生视频', description: '沿用现有单镜图和正式 Phase B 流程。' },
  ];

  return <section className="rounded-xl border border-gray-200 bg-white p-4">
    <h3 className="mb-3 text-sm font-semibold text-gray-800">生视频模式</h3>
    <div className="grid gap-3 md:grid-cols-2">
      {choices.map(choice => <label key={choice.value} className={`flex gap-3 rounded-lg border p-3 ${value === choice.value ? 'border-blue-500 bg-blue-50' : 'border-gray-200'} ${disabled ? 'cursor-not-allowed opacity-70' : 'cursor-pointer'}`}>
        <input type="radio" name="novel-video-mode" checked={value === choice.value} disabled={disabled} onChange={() => onChange?.(choice.value)} />
        <span><strong className="block text-sm text-gray-900">{choice.label}</strong><span className="mt-1 block text-xs text-gray-600">{choice.description}</span></span>
      </label>)}
    </div>
    {note && <p className="mt-3 text-xs text-amber-700">{note}</p>}
  </section>;
}
