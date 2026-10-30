import { useRef, useState } from 'react';
import { Upload } from 'lucide-react';

type Panel = {
  index: number;
  beat: string;
  camera: string;
  action: string;
  characters: string[];
  image_url?: string;
  review_status: string;
  review_note?: string;
};
type Preview = { prompt: string; referenceImages: { role: string; name: string; url: string }[]; size: number[] };

const checks = [
  '人物身份与人数正确，没有复制、串脸或年龄错位',
  '镜头景别、视线轴和过肩前景符合当前格的规划',
  '台词人与焦点符合镜头规划；露脸时人物及口型正确，画外音时不强求露脸',
  '行囊、木杖等道具归属正确，场景与相邻格连续',
];

export function GridPanelReview({ panel, speakers, preview, disabled, onApprove, onReject,
  onPrepare, onGenerate, onReplace, onOpenImage, availableCharacters, onRevise }: {
  panel: Panel;
  speakers: string[];
  preview: Preview | null;
  disabled: boolean;
  onApprove: (note: string) => void;
  onReject: (note: string) => void;
  onPrepare: () => void;
  onGenerate: () => void;
  onReplace: (file: File) => void;
  onOpenImage: () => void;
  availableCharacters: string[];
  onRevise: (plan: { beat: string; camera: string; action: string; characters: string[] }) => void;
}) {
  const [checked, setChecked] = useState<boolean[]>(checks.map(() => false));
  const [note, setNote] = useState('');
  const [editing, setEditing] = useState(false);
  const [plan, setPlan] = useState(() => ({ beat: panel.beat, camera: panel.camera,
    action: panel.action, characters: panel.characters }));
  const fileRef = useRef<HTMLInputElement>(null);
  const buttonClass = 'rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 hover:border-blue-400 disabled:cursor-not-allowed disabled:opacity-40';
  const status = ({ passed: '已通过', failed: '需重做', pending: '待审核', warning: '待复核' } as Record<string, string>)[panel.review_status] || panel.review_status;
  const offscreenSpeakers = speakers.filter(speaker => !panel.characters.includes(speaker));

  return <section className="rounded-lg border bg-gray-50 p-4">
    <div className="flex items-center justify-between gap-3"><h3 className="font-semibold">格 {panel.index} · 逐格验收</h3><span className="text-xs">{status}</span></div>
    <p className="mt-2 text-sm text-gray-700">{panel.beat}</p>
    <p className="mt-1 text-xs text-gray-600">{panel.camera}</p>
    <button type="button" disabled={disabled} onClick={() => setEditing(value => !value)} className="mt-2 text-xs text-blue-700">{editing ? '收起规划修订' : '修订本格规划'}</button>
    {editing && <div className="mt-2 space-y-2 rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm">
      <label className="block">剧情画面<textarea value={plan.beat} onChange={event => setPlan(value => ({ ...value, beat: event.target.value }))} rows={2} className="mt-1 w-full rounded border p-2" /></label>
      <label className="block">机位与焦点<textarea value={plan.camera} onChange={event => setPlan(value => ({ ...value, camera: event.target.value }))} rows={2} className="mt-1 w-full rounded border p-2" /></label>
      <label className="block">画面动作<textarea value={plan.action} onChange={event => setPlan(value => ({ ...value, action: event.target.value }))} rows={2} className="mt-1 w-full rounded border p-2" /></label>
      <div>可见人物<div className="mt-1 flex flex-wrap gap-3">{availableCharacters.map(name => <label key={name} className="flex items-center gap-1"><input type="checkbox" checked={plan.characters.includes(name)} onChange={event => setPlan(value => ({ ...value, characters: event.target.checked ? [...value.characters, name] : value.characters.filter(item => item !== name) }))} />{name}</label>)}</div></div>
      <p className="text-xs text-blue-800">保存后需重做并重新审核本格；引用本格的 Clip 会等待重新编译和生成。</p>
      <button type="button" disabled={disabled || !plan.beat.trim() || !plan.camera.trim() || !plan.action.trim()} onClick={() => onRevise(plan)} className="rounded bg-blue-600 px-3 py-2 text-white disabled:opacity-40">保存修订</button>
    </div>}
    {speakers.length > 0 && <p className="mt-2 rounded border border-amber-200 bg-amber-50 p-2 text-sm text-amber-900">本格台词人：{speakers.join('、')}。请核对人物身份与镜头规划{offscreenSpeakers.length > 0 ? `；${offscreenSpeakers.join('、')}规划为画外音，不要求其露脸` : '，露脸说话人应清晰且口型正确'}。</p>}
    {panel.image_url && <><button type="button" onClick={onOpenImage} aria-label={`放大查看格 ${panel.index} 原图`} title="在页面内放大查看细节" className="mt-3 block w-full cursor-zoom-in rounded-lg focus-visible:outline-2 focus-visible:outline-blue-600"><img src={panel.image_url} alt={`格 ${panel.index} 原图`} className="aspect-video w-full rounded-lg border object-contain" /></button><p className="mt-1 text-xs text-gray-500">点击图片可在页面内放大检查脸部与道具细节。</p></>}
    <div className="mt-3 grid gap-2 sm:grid-cols-2">{checks.map((label, index) => <label key={label} className="flex items-start gap-2 rounded border bg-white p-2 text-sm"><input type="checkbox" checked={checked[index]} onChange={event => setChecked(previous => previous.map((value, i) => i === index ? event.target.checked : value))} className="mt-1" /><span>{label}</span></label>)}</div>
    <label className="mt-3 block text-xs text-gray-600">问题备注（标记需重做时建议填写）<textarea value={note} onChange={event => setNote(event.target.value)} rows={2} className="mt-1 w-full rounded border p-2 text-sm" placeholder="例如：说话人与前景人物颠倒；行囊在老翁背上" /></label>
    {panel.review_note && <p className="mt-2 text-xs text-gray-600">上次审核：{panel.review_note}</p>}
    <div className="mt-3 flex flex-wrap gap-2">
      <button type="button" disabled={disabled || !checked.every(Boolean)} className="rounded-lg bg-blue-600 px-3 py-2 text-sm text-white disabled:cursor-not-allowed disabled:opacity-40" onClick={() => onApprove(`已核对：${checks.join('；')}${note ? `。备注：${note}` : ''}`)}>四项确认，审核通过</button>
      <button type="button" disabled={disabled} className={buttonClass} onClick={() => onReject(note || '逐格验收发现画面问题')}>标记需重做</button>
      <button type="button" disabled={disabled} className={buttonClass} onClick={onPrepare}>预览单格重做输入</button>
      <button type="button" disabled={disabled || !preview} className={buttonClass} onClick={onGenerate}>AI 重做此格</button>
      <button type="button" disabled={disabled} className={buttonClass} onClick={() => fileRef.current?.click()}><Upload className="mr-1 inline h-4 w-4" />上传替换此格</button>
      <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={event => { const file = event.target.files?.[0]; if (file) onReplace(file); event.target.value = ''; }} />
    </div>
    {preview && <div className="mt-3 rounded border border-blue-200 bg-blue-50 p-3"><p className="text-sm font-medium">即将提交的单格输入 · {preview.size.join(' × ')}</p><div className="mt-2 flex flex-wrap gap-2">{preview.referenceImages.map((ref, i) => <div key={i} className="w-20"><img src={ref.url} alt={ref.name} className="aspect-video w-full rounded object-cover" /><span className="text-xs">Picture {i + 1} · {ref.name}</span></div>)}</div><pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap text-xs">{preview.prompt}</pre></div>}
  </section>;
}
