import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { Task } from '../../../types';
import { toast } from '../../../stores/toastStore';

type Cue = { start: number; end: number; text: string; en_text?: string };

export function SubtitleEditor({ task, endpoint: endpointOverride, initialSrtUrl, onClose, onUpdated }: {
  task?: Task; endpoint?: string; initialSrtUrl?: string | null;
  onClose: () => void; onUpdated: () => void;
}) {
  const [cues, setCues] = useState<Cue[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [correcting, setCorrecting] = useState(false);
  const [correctedRows, setCorrectedRows] = useState<number[]>([]);
  const [correctionMessage, setCorrectionMessage] = useState('');
  const [srtUrl, setSrtUrl] = useState(initialSrtUrl || task?.subtitle?.srtUrl || '');
  const [enSrtUrl, setEnSrtUrl] = useState('');
  const [sourceUrl, setSourceUrl] = useState('');
  const [bilingual, setBilingual] = useState(false);
  const [playbackTime, setPlaybackTime] = useState(0);
  const previewVideo = useRef<HTMLVideoElement>(null);
  const endpoint = endpointOverride || `/api/novels/${task?.novelId}/chapters/${task?.chapterId}/merge-videos/${task?.id}/subtitles`;
  const activePreviewCue = cues.find(cue => cue.start <= playbackTime && playbackTime < cue.end);

  useEffect(() => {
    fetch(endpoint).then(async response => {
      const result = await response.json();
      if (!response.ok || !result.success) throw new Error(result.detail || '加载字幕失败');
      setCues(result.data.cues || []);
      setSrtUrl(result.data.srt_url || '');
      setEnSrtUrl(result.data.en_srt_url || '');
      setSourceUrl(result.data.source_url || '');
      setBilingual(result.data.mode === 'bilingual');
    }).catch(error => toast.error(error instanceof Error ? error.message : '加载字幕失败'))
      .finally(() => setLoading(false));
  }, [endpoint]);

  const change = (index: number, field: keyof Cue, value: string) => {
    setCues(previous => previous.map((cue, position) => {
      if (position !== index) return cue;
      const updated = { ...cue, [field]: field === 'text' || field === 'en_text' ? value : Number(value) };
      if (field === 'text' && value !== cue.text) delete updated.en_text;
      return updated;
    }));
  };

  const autoCorrect = async () => {
    setCorrecting(true);
    setCorrectionMessage('');
    try {
      const response = await fetch(`${endpoint}/auto-correct`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cues }),
      });
      const result = await response.json();
      if (!response.ok || !result.success) throw new Error(result.detail || '自动校正失败');
      const corrected = result.data?.cues as Cue[] | undefined;
      if (!Array.isArray(corrected) || corrected.length !== cues.length
        || corrected.some((cue, index) => cue.start !== cues[index].start || cue.end !== cues[index].end)) {
        throw new Error('自动校正结果的时间轴与原字幕不一致，未应用建议');
      }
      const changed = corrected.flatMap((cue, index) => cue.text !== cues[index].text ? [index] : []);
      setCues(corrected.map((cue, index) => cue.text !== cues[index].text ? { ...cue, en_text: '' } : cue));
      setCorrectedRows(changed);
      setCorrectionMessage(`自动校正建议已填入，修改了 ${changed.length} 条台词；时间戳保持不变。请核对后保存。`);
      toast.success(`自动校正完成，修改 ${changed.length} 条台词`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '自动校正失败');
    } finally {
      setCorrecting(false);
    }
  };

  const save = async () => {
    setSaving(true);
    try {
      const response = await fetch(endpoint, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cues }),
      });
      const result = await response.json();
      if (!response.ok || !result.success) throw new Error(result.detail || '保存字幕失败');
      toast.success('字幕修改已加入视频更新队列，可在任务列表查看进度');
      onUpdated();
      onClose();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '保存字幕失败');
    } finally {
      setSaving(false);
    }
  };

  return createPortal(
    <div className="fixed inset-0 z-[400] flex items-center justify-center bg-black/60 p-4">
      <div className="flex max-h-[90vh] w-full max-w-5xl flex-col rounded-xl bg-white shadow-xl">
        <div className="flex items-center justify-between border-b p-4">
          <div><h3 className="font-semibold">校对视频字幕</h3><p className="text-xs text-gray-500">时间单位：秒。自动校正只修改台词；保存后由后台队列更新 SRT 和烧录视频。</p></div>
          <button type="button" onClick={onClose} disabled={saving} className="text-gray-500 hover:text-gray-900">关闭</button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {loading ? <p className="text-sm text-gray-500">正在加载字幕…</p> : (
            <div className="space-y-2">
              {correctionMessage && <p className="rounded border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-800">{correctionMessage}</p>}
              {sourceUrl && cues.length > 0 && <div className="mx-auto max-w-2xl">
                <div className="relative overflow-hidden rounded bg-black">
                  <video ref={previewVideo} src={sourceUrl} controls preload="metadata" className="aspect-video w-full"
                    onTimeUpdate={event => setPlaybackTime(event.currentTarget.currentTime)} />
                  {activePreviewCue && <div className="pointer-events-none absolute inset-x-8 bottom-12 text-center font-semibold text-white [text-shadow:0_1px_3px_black,0_0_5px_black]">
                    <div className="whitespace-pre-wrap text-lg">{activePreviewCue.text}</div>
                    {bilingual && <div className="whitespace-pre-wrap text-xs">{activePreviewCue.en_text || '英文待翻译'}</div>}
                  </div>}
                </div>
                <p className="mt-1 text-xs text-gray-500">点击下方序号可定位画面；字幕随视频时间显示。最终视频以烧录结果为准。</p>
              </div>}
              {cues.map((cue, index) => <div key={index} className={`flex items-start gap-2 rounded border p-2 ${correctedRows.includes(index) ? 'border-blue-300 bg-blue-50/50' : ''}`}>
                <button type="button" onClick={() => { setPlaybackTime(cue.start); if (previewVideo.current) previewVideo.current.currentTime = cue.start; }}
                  className="w-8 pt-2 text-xs text-blue-600" title="预览该字幕">{index + 1}</button>
                <input aria-label={`第${index + 1}条开始时间`} type="number" step="0.001" min="0"
                  value={cue.start} onChange={event => change(index, 'start', event.target.value)}
                  disabled={correcting || saving}
                  className="w-24 rounded border px-2 py-1.5 text-sm" />
                <input aria-label={`第${index + 1}条结束时间`} type="number" step="0.001" min="0"
                  value={cue.end} onChange={event => change(index, 'end', event.target.value)}
                  disabled={correcting || saving}
                  className="w-24 rounded border px-2 py-1.5 text-sm" />
                <div className="min-w-0 flex-1 space-y-1">
                  <textarea aria-label={`第${index + 1}条中文字幕`} value={cue.text}
                    onChange={event => change(index, 'text', event.target.value)} rows={2}
                    disabled={correcting || saving}
                    className="w-full rounded border px-2 py-1.5 text-sm" />
                  {bilingual && <><textarea aria-label={`第${index + 1}条英文字幕`} value={cue.en_text || ''}
                    onChange={event => change(index, 'en_text', event.target.value)} rows={2}
                    disabled={correcting || saving} placeholder="留空时保存后自动翻译"
                    className="w-full rounded border px-2 py-1.5 text-sm" />
                    {(cue.en_text || '').length > 112 && <p className="text-xs text-amber-700">英文超过建议的两行长度，请预览换行。</p>}</>}
                </div>
                <button type="button" disabled={correcting || saving} onClick={() => setCues(previous => previous.filter((_, position) => position !== index))}
                  className="px-2 py-1.5 text-sm text-red-600">删除</button>
              </div>)}
              <button type="button" onClick={() => setCues(previous => [...previous, {
                start: previous.length ? previous[previous.length - 1].end : 0,
                end: previous.length ? previous[previous.length - 1].end + 2 : 2,
                text: '新字幕',
              }])} disabled={correcting || saving} className="rounded border px-3 py-1.5 text-sm">添加字幕</button>
            </div>
          )}
        </div>
        <div className="flex items-center justify-end gap-3 border-t p-4">
          <div className="mr-auto flex gap-3 text-sm text-blue-600">
            {srtUrl && <a href={srtUrl} download className="hover:underline">下载中文 SRT</a>}
            {enSrtUrl && <a href={enSrtUrl} download className="hover:underline">下载英文 SRT</a>}
          </div>
          <button type="button" onClick={onClose} disabled={saving} className="rounded border px-4 py-2 text-sm">取消</button>
          <button type="button" onClick={autoCorrect} disabled={loading || saving || correcting || !cues.length}
            className="rounded border border-blue-600 px-4 py-2 text-sm text-blue-700 disabled:opacity-50">{correcting ? '正在自动校正…' : '自动校正台词'}</button>
          <button type="button" onClick={save} disabled={loading || saving || correcting || !cues.length}
            className="rounded bg-blue-600 px-4 py-2 text-sm text-white disabled:opacity-50">{saving ? '正在加入队列…' : '保存并加入更新队列'}</button>
        </div>
      </div>
    </div>, document.body,
  );
}
