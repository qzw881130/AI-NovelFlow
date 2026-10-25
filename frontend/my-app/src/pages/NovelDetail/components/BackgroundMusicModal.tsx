import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Loader2, Music2, RefreshCw, X } from 'lucide-react';
import { novelApi, type ChapterBackgroundMusic } from '../../../api/novels';
import type { Chapter } from '../../../types';
import { toast } from '../../../stores/toastStore';

export function BackgroundMusicModal({ novelId, chapters, onClose }: {
  novelId: string;
  chapters: Chapter[];
  onClose: () => void;
}) {
  const eligibleIds = chapters.filter(chapter => chapter.finalVideo || chapter.chapterVideoUrl).map(chapter => chapter.id);
  const [selectedIds, setSelectedIds] = useState<string[]>(eligibleIds);
  const [musicByChapter, setMusicByChapter] = useState<Record<string, ChapterBackgroundMusic>>({});
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const selectableIds = eligibleIds.filter(id => !['pending', 'running'].includes(musicByChapter[id]?.status || ''));
  const readySelectedIds = selectedIds.filter(id => selectableIds.includes(id));

  useEffect(() => {
    let cancelled = false;
    const refresh = async () => {
      try {
        const result = await novelApi.fetchBackgroundMusic(novelId);
        if (!cancelled && result.success && result.data) setMusicByChapter(result.data);
      } catch {
        if (!cancelled) toast.error('加载背景音乐任务失败');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void refresh();
    const timer = setInterval(() => { void refresh(); }, 4000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [novelId]);

  const submit = async () => {
    if (!readySelectedIds.length) return;
    setSubmitting(true);
    try {
      const response = await novelApi.generateBackgroundMusic(novelId, readySelectedIds);
      if (!response.success) throw new Error(response.message || '提交背景音乐任务失败');
      setMusicByChapter(current => ({ ...current, ...Object.fromEntries((response.data || []).map(item => [item.chapterId, item])) }));
      toast.success(`已加入 ${readySelectedIds.length} 个章回的背景音乐任务`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '提交背景音乐任务失败');
    } finally {
      setSubmitting(false);
    }
  };

  return createPortal(
    <div className="fixed inset-0 z-[120] flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true" aria-label="生成背景音乐">
      <div className="flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b px-6 py-4">
          <div>
            <h2 className="flex items-center gap-2 text-lg font-semibold text-gray-900"><Music2 className="h-5 w-5 text-violet-600" />生成背景音乐</h2>
            <p className="mt-1 text-sm text-gray-500">按剧情、对白与环境声规划必要配乐；可能决定某章不配乐。生成后请逐段试听。</p>
          </div>
          <button type="button" onClick={onClose} className="rounded p-2 text-gray-500 hover:bg-gray-100" aria-label="关闭"><X className="h-5 w-5" /></button>
        </div>
        <div className="flex items-center justify-between border-b bg-gray-50 px-6 py-3">
          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input type="checkbox" checked={selectableIds.length > 0 && selectableIds.every(id => readySelectedIds.includes(id))}
              onChange={event => setSelectedIds(event.target.checked ? selectableIds : [])} />全选可用章回
          </label>
          <span className="flex items-center gap-1 text-xs text-gray-500"><RefreshCw className="h-3.5 w-3.5" />任务状态自动刷新</span>
        </div>
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-5">
          {loading && <p className="text-sm text-gray-500">正在加载...</p>}
          {chapters.map(chapter => {
            const item = musicByChapter[chapter.id];
            const eligible = eligibleIds.includes(chapter.id);
            const active = item?.status === 'running' || item?.status === 'pending';
            return <div key={chapter.id} className="rounded-lg border border-gray-200 p-4">
              <div className="flex items-start gap-3">
                <input type="checkbox" className="mt-1" disabled={!eligible || active}
                  checked={selectedIds.includes(chapter.id) && !active}
                  onChange={event => setSelectedIds(ids => event.target.checked ? [...ids, chapter.id] : ids.filter(id => id !== chapter.id))} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-sm font-medium text-gray-900">第 {chapter.number} 章 · {chapter.title}</h3>
                    {item && <span className={`rounded px-2 py-0.5 text-xs ${item.status === 'completed' ? 'bg-green-50 text-green-700' : item.status === 'failed' ? 'bg-red-50 text-red-700' : 'bg-blue-50 text-blue-700'}`}>
                      {item.stale ? '成片已变化' : item.status === 'completed' ? item.audioUrl ? '可试听' : '无需配乐' : item.status === 'failed' ? '生成失败' : `${item.currentStep || '排队中'} ${item.progress}%`}
                    </span>}
                  </div>
                  {!eligible && <p className="mt-1 text-xs text-gray-500">缺少初稿章回视频</p>}
                  {item?.errorMessage && <p className="mt-2 text-xs text-red-700">{item.errorMessage}</p>}
                  {item?.noMusicReason && <p className="mt-2 text-xs text-gray-600">留白原因：{item.noMusicReason}</p>}
                  {item?.audioUrl && <div className="mt-3"><p className="mb-1 text-xs font-medium text-gray-600">整章背景音乐试听轨</p><audio controls preload="none" src={item.audioUrl} className="h-9 w-full" /></div>}
                  {!!item?.cues.length && <div className="mt-3 space-y-2">{item.cues.map(cue =>
                    <div key={cue.index} className="rounded border border-violet-100 bg-violet-50/50 p-3 text-xs text-gray-700">
                      <p className="font-medium">配乐 {cue.index} · Shot {cue.startShot}–{cue.endShot} · {cue.startSeconds.toFixed(1)}–{cue.endSeconds.toFixed(1)} 秒</p>
                      <p className="mt-1">原因：{cue.reason}</p>
                      <p className="mt-1">风格：{cue.style}</p>
                      <p className="mt-1">旋律意图：{cue.melody}</p>
                      {cue.audioUrl && <>
                        <p className="mt-2 text-gray-500">片段试听 {cue.durationSeconds.toFixed(1)} 秒{cue.rawAudioSeconds ? ` · 原始输出 ${cue.rawAudioSeconds.toFixed(1)} 秒` : ''}</p>
                        <audio controls preload="none" src={cue.audioUrl} className="mt-1 h-8 w-full" />
                      </>}
                    </div>)}</div>}
                </div>
              </div>
            </div>;
          })}
        </div>
        <div className="border-t bg-white px-6 py-4">
          <button type="button" onClick={submit} disabled={!readySelectedIds.length || submitting}
            className="btn-primary w-full justify-center disabled:cursor-not-allowed disabled:opacity-50">
            {submitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Music2 className="mr-2 h-4 w-4" />}
            {submitting ? '提交中...' : `批量生成音乐（${readySelectedIds.length} 章）`}
          </button>
        </div>
      </div>
    </div>, document.body,
  );
}
