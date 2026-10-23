import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Camera, Loader2, X } from 'lucide-react';
import { shotsApi, type ContinuationMode } from '../../../api/shots';
import { toast } from '../../../stores/toastStore';
import { captureVideoFrame, savePreviousClipFrame, type PreviousClipFrameTarget } from '../previousClipFrame';
import { resolveClipPlaybackResponse } from './ClipPlaybackButtons';

export function PreviousClipFrameModal({ target, novelId, chapterId, continuationMode, blocked, onSaved, onClose }: {
  target: PreviousClipFrameTarget;
  novelId: string;
  chapterId: string;
  continuationMode?: ContinuationMode;
  blocked: boolean;
  onSaved: (shot: any) => void;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const inFlight = useRef(false);
  const [source, setSource] = useState<{ url: string; label: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');
  const [ready, setReady] = useState(false);
  const [seeking, setSeeking] = useState(false);
  const [duration, setDuration] = useState(0);
  const [position, setPosition] = useState(0);
  const [seekInput, setSeekInput] = useState('0');

  useEffect(() => {
    dialog.current?.showModal();
    return () => dialog.current?.close();
  }, []);

  useEffect(() => {
    let cancelled = false;
    shotsApi.getClipPlayback(novelId, chapterId, target.shotId, target.previousClipIndex).then(response => {
      // Prefer the original clip; old receipts can expose a review or cumulative asset.
      const kind = response.data?.independent_url || response.data?.review_url ? 'independent_url' : 'cumulative_url';
      const resolved = resolveClipPlaybackResponse(response, kind);
      if (!cancelled) setSource(resolved);
    }).catch(cause => {
      if (!cancelled) setError(cause instanceof Error ? cause.message : '前序视频读取失败');
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [novelId, chapterId, target]);

  const close = () => { if (!inFlight.current) onClose(); };
  const seek = () => {
    const seconds = Number(seekInput);
    if (!video.current || !seekInput.trim() || !Number.isFinite(seconds) || seconds < 0 || seconds > duration) {
      setError(`请输入 0～${duration.toFixed(3)} 秒之间的位置`);
      return;
    }
    setError('');
    video.current.pause();
    video.current.currentTime = seconds;
  };
  const capture = async () => {
    if (inFlight.current || blocked || saved || !video.current) return;
    inFlight.current = true;
    setSaving(true);
    setError('');
    let committed = false;
    try {
      const file = await captureVideoFrame(video.current);
      const getShot = () => shotsApi.getShot(novelId, chapterId, target.shotId, undefined, false, continuationMode);
      await savePreviousClipFrame(target, file, {
        getShot,
        upload: (frameIndex, image) => shotsApi.uploadKeyframeImage(novelId, chapterId, target.shotId, frameIndex, image),
      });
      committed = true;
      setSaved(true);
      // Re-read authoritative dependencies too: replacing an input may invalidate consumers.
      const fresh = await getShot();
      if (!fresh.success || !fresh.data) throw new Error(fresh.message || '页面更新失败');
      onSaved(fresh.data);
      toast.success(`已从 C${target.previousClipIndex} 截取并替换视觉状态 ${target.stateIndex} 图片`);
      onClose();
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : '截帧失败';
      setError(committed ? `状态图已保存，但页面刷新失败，请关闭弹窗后刷新页面。${message}` : message);
    } finally {
      inFlight.current = false;
      setSaving(false);
    }
  };

  return createPortal(
    <dialog ref={dialog} aria-labelledby="previous-clip-frame-title" onCancel={event => { event.preventDefault(); close(); }}
      className="m-auto w-[calc(100vw-2rem)] max-w-4xl rounded-xl bg-white p-0 shadow-2xl backdrop:bg-black/60">
      <section className="flex max-h-[90vh] flex-col">
        <header className="flex items-center justify-between border-b px-5 py-4">
          <div>
            <h2 id="previous-clip-frame-title" className="text-lg font-semibold">从上一个 Clip 提取</h2>
            <p className="mt-1 text-sm text-gray-500">视觉状态 {target.stateIndex}（C{target.ownerClipIndex}）← 前一个 Clip C{target.previousClipIndex}</p>
          </div>
          <button type="button" aria-label="关闭截帧窗口" disabled={saving} onClick={close} className="rounded p-1 text-gray-500 hover:bg-gray-100 disabled:opacity-50"><X className="h-5 w-5" /></button>
        </header>
        <div className="space-y-3 overflow-y-auto p-5">
          {loading && <p role="status" className="flex items-center gap-2 text-sm text-gray-500"><Loader2 className="h-4 w-4 animate-spin" />正在读取 C{target.previousClipIndex} 视频…</p>}
          {source && <>
            <p className="text-xs text-gray-500">{source.label} · 以播放器内时间定位</p>
            <video ref={video} src={source.url} crossOrigin="anonymous" controls preload="auto" playsInline
              aria-label={`前一个 Clip C${target.previousClipIndex} 视频`}
              className={`max-h-[50vh] w-full rounded-lg bg-black object-contain ${saving ? 'pointer-events-none' : ''}`}
              onLoadedMetadata={event => {
                const media = event.currentTarget;
                if (Number.isFinite(media.duration)) {
                  setDuration(media.duration);
                  // Start close to the last frame; the user may seek anywhere.
                  media.currentTime = Math.max(0, media.duration - 0.1);
                }
              }}
              onLoadedData={() => setReady(true)} onSeeking={() => setSeeking(true)}
              onSeeked={event => { setSeeking(false); setReady(event.currentTarget.readyState >= 2); setPosition(event.currentTarget.currentTime); setSeekInput(event.currentTarget.currentTime.toFixed(3)); }}
              onTimeUpdate={event => setPosition(event.currentTarget.currentTime)}
              onError={() => { setReady(false); setError('前序视频加载失败，无法截取画面'); }} />
            <div className="flex flex-wrap items-center gap-3 text-sm text-gray-600">
              <span className="tabular-nums">当前位置 {position.toFixed(3)} / {duration.toFixed(3)} 秒</span>
              <label className="flex items-center gap-2">定位到（秒）
                <input type="number" min="0" max={duration} step="0.001" value={seekInput} disabled={!ready || saving}
                  onFocus={() => video.current?.pause()} onChange={event => setSeekInput(event.target.value)}
                  onKeyDown={event => { if (event.key === 'Enter') seek(); }}
                  className="w-28 rounded border border-gray-300 px-2 py-1" />
              </label>
              <button type="button" disabled={!ready || saving} onClick={seek} className="rounded border px-3 py-1 hover:bg-gray-50 disabled:opacity-50">定位</button>
            </div>
          </>}
          <p className="text-sm text-gray-500">拖动播放进度条或输入秒数选择画面。点击“截取帧”将以视频原始分辨率替换当前状态图；已使用旧图的片段及合成状态按现有规则更新。</p>
          {blocked && <p role="status" className="text-sm text-amber-700">当前 Shot 正在生成或规划，请等待完成后再截取替换。</p>}
          {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
        </div>
        <footer className="flex justify-end gap-3 border-t px-5 py-4">
          <button type="button" disabled={saving} onClick={close} className="rounded-lg bg-gray-100 px-4 py-2 text-sm disabled:opacity-50">取消</button>
          <button type="button" disabled={!ready || seeking || saving || saved || blocked} onClick={() => void capture()}
            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white disabled:opacity-50">
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Camera className="h-4 w-4" />}{saving ? '正在保存…' : saved ? '已保存' : '截取帧'}
          </button>
        </footer>
      </section>
    </dialog>, document.body,
  );
}
