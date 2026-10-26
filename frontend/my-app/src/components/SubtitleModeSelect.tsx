export type SubtitleMode = 'none' | 'zh' | 'bilingual';

export function SubtitleModeSelect({ value, onChange }: {
  value: SubtitleMode;
  onChange: (value: SubtitleMode) => void;
}) {
  return <label className="flex items-center gap-2 text-sm text-gray-700">
    <span>字幕</span>
    <select aria-label="字幕模式" value={value} onChange={event => onChange(event.target.value as SubtitleMode)}
      className="rounded border border-gray-300 bg-white px-2 py-1.5 text-sm">
      <option value="none">无字幕</option>
      <option value="zh">中文字幕（中文 SRT + 烧录）</option>
      <option value="bilingual">中英双语（中英 SRT + 烧录）</option>
    </select>
  </label>;
}
