import { useState } from 'react';
import { shotsApi } from '../../../api/shots';

export function clipPlaybackErrorMessage(code?: string) {
  switch (code) {
    case 'RAW_CLIP_RECEIPT_UNAVAILABLE':
      return '旧任务缺少原始片段的输出记录，可播放累计视频。';
    case 'CLIP_PLAYBACK_RECEIPT_MISMATCH':
      return '原始片段的输出记录与当前任务不一致，已停止读取；累计视频仍可播放。';
    case 'RAW_CLIP_OUTPUT_UNAVAILABLE':
    case 'RAW_CLIP_AV_PAIR_UNAVAILABLE':
      return '生成记录中缺少原始片段的音视频文件，可播放累计视频。';
    case 'RAW_CLIP_FRAME_COUNT_MISMATCH':
      return '原始片段帧数校验未通过，累计视频仍可播放。';
    default:
      return '原始片段读取失败，可稍后重试或播放累计视频。';
  }
}

export type ClipPlaybackKind = 'independent_url' | 'cumulative_url';

// The preview and its refresh must resolve the same source, including the
// existing review fallback for old clips without an independent artifact.
export function resolveClipPlaybackResponse(response: {
  success: boolean; detail?: string; message?: string;
  data?: { independent_url?: string | null; cumulative_url?: string | null;
    review_url?: string | null; independent_error?: string | null };
}, kind: ClipPlaybackKind) {
  const review = kind === 'independent_url' && !response.data?.independent_url && !!response.data?.review_url;
  const url = review ? response.data?.review_url : response.data?.[kind];
  if (!response.success || !url) throw new Error(kind === 'independent_url' && response.data?.independent_error
    ? clipPlaybackErrorMessage(response.data.independent_error) : response.detail || response.message || '视频暂不可用');
  return { url, review, label: review ? '从累计视频截取 · 含已融合公共区，非原始单段'
    : kind === 'cumulative_url' ? '截至本片段的累计视频' : '原始单段 · 含自身公共区或过渡帧' };
}

export function ClipPlaybackButtons({ novelId, chapterId, shotId, clip, ready, playback, onPreview }: {
  novelId?: string; chapterId?: string; shotId: string; clip: any; ready: boolean;
  playback?: { independent_url?: string | null; review_url?: string | null } | null;
  onPreview: (clip: any) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [usedReview, setUsedReview] = useState(false);
  const reviewOnly = playback?.independent_url ? false : usedReview || Boolean(playback?.review_url);
  const play = async (kind: ClipPlaybackKind) => {
    if (!novelId || !chapterId || busy) return;
    setBusy(true);setError('');
    try {
      const r = await shotsApi.getClipPlayback(novelId, chapterId, shotId, Number(clip.clip_index));
      const source = resolveClipPlaybackResponse(r, kind);
      if (kind === 'independent_url') setUsedReview(source.review);
      onPreview({ ...clip, video_url: source.url, playback_kind: kind, playback_source_label: source.label });
    } catch (e) { setError(e instanceof Error ? e.message : '视频读取失败'); }
    finally { setBusy(false); }
  };
  return <div data-testid="clip-dual-playback" className="flex flex-wrap items-center gap-2">
    <button disabled={!ready || busy} onClick={() => play('independent_url')} title={reviewOnly ? '从累计视频截取，包含已经融合的公共区；不是原始单段' : '包含本片段自身携带的公共区或过渡帧'}
      className="rounded border border-blue-200 px-2.5 py-1 text-[11px] text-blue-700 disabled:opacity-40">{busy ? '准备播放…' : reviewOnly ? '播放片段预览（累计截取）' : '播放本片段'}</button>
    <button disabled={!ready || busy} onClick={() => play('cumulative_url')}
      className="rounded border border-blue-200 px-2.5 py-1 text-[11px] text-blue-700 disabled:opacity-40">播放累计视频</button>
    {error && <span role="alert" className="text-xs text-red-700">{error}</span>}
  </div>;
}
