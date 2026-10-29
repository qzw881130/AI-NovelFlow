import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, CheckCircle2, ChevronLeft, ChevronRight, Film, Image as ImageIcon, LayoutGrid, Loader2 } from 'lucide-react';
import { API_BASE } from '../../api';
import { novelApi } from '../../api/novels';
import type { Chapter } from '../../types';
import { toast } from '../../stores/toastStore';
import { GridTaskPanel, type GridTask } from './GridTaskPanel';
import { GridAutoBatchModal } from './GridAutoBatchModal';
import { GridPanelReview } from './GridPanelReview';
import { FinalShotVideo } from './FinalShotVideo';

type Stage = 'shot_split' | 'shot_image' | 'video_gen';
type Panel = { index: number; beat: string; camera: string; action: string; characters: string[]; dialogue_indexes: number[]; image_url?: string; image_task_id?: string; review_status: string; review_note?: string };
type GridData = { revision: number; layout: string; panels: Panel[]; board_image_url?: string; board_image_task_id?: string; board_prompt?: string; board_reference_images?: { role: string; name: string; url: string }[]; panel_width: number; panel_height: number };
type Clip = { clip_index: number; duration: number; panel_indexes: number[]; reference_strategy: 'split_panels' | 'whole_board'; dialogues: { id: string; speaker: string; text: string }[]; reference_images?: { picture_index: number; role: string; url: string; panel_index?: number }[]; prompt?: string; video_url?: string };
type Shot = { id: string; index: number; description: string; duration: number; dialogues: { speaker: string; text: string }[]; gridData?: GridData; gridClipPlan?: { clip_plan: Clip[] }; videoUrl?: string };
type ChapterData = { novel: { id: string; title: string; videoMode: string }; chapter: { id: string; title: string; finalVideo?: string }; shots: Shot[] };
type BoardPreview = { prompt: string; referenceImages: { role: string; name: string; url: string }[]; boardSize: number[] };
type PanelPreview = { prompt: string; referenceImages: { role: string; name: string; url: string }[]; size: number[] };

async function request<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { method,
    headers: body && !(body instanceof FormData) ? { 'Content-Type': 'application/json' } : undefined,
    body: body instanceof FormData ? body : body === undefined ? undefined : JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok || !result.success) throw new Error(result.detail || result.message || `请求失败（${response.status}）`);
  return result.data as T;
}

const stages: { key: Stage; label: string }[] = [
  { key: 'shot_split', label: '分镜拆分' }, { key: 'shot_image', label: '分镜图生成' },
  { key: 'video_gen', label: '视频生成' },
];

const parseStageHash = (): Stage | null => {
  const value = new URLSearchParams(window.location.hash.slice(1)).get('tab');
  return stages.find(item => item.key === value)?.key || null;
};

const parseShotHash = (): number | null => {
  const hash = window.location.hash.slice(1).trim();
  const value = new URLSearchParams(hash).get('shot') || hash.match(/^(?:shot-?|s)?(\d+)$/i)?.[1];
  if (!value || !/^\d+$/.test(value)) return null;
  const index = Number(value);
  return Number.isSafeInteger(index) && index > 0 ? index : null;
};

const gridModeHash = (stage: Stage, shotIndex: number) => `#tab=${stage}&shot=${shotIndex + 1}`;

export default function GridModePage() {
  const { id, cid } = useParams<{ id: string; cid: string }>();
  const navigate = useNavigate();
  const base = `/novels/${id}/chapters/${cid}/grid`;
  const [data, setData] = useState<ChapterData | null>(null);
  const [chapterList, setChapterList] = useState<Chapter[]>([]);
  const [tasks, setTasks] = useState<GridTask[]>([]);
  const [stage, setStage] = useState<Stage>(() => parseStageHash() || 'shot_split');
  const [shotIndex, setShotIndex] = useState(() => (parseShotHash() || 1) - 1);
  const [panelIndex, setPanelIndex] = useState(0);
  const [clipIndex, setClipIndex] = useState(0);
  const [layout, setLayout] = useState('auto');
  const [imageView, setImageView] = useState<'board' | 'panels'>('board');
  const [strategy, setStrategy] = useState<'split_panels' | 'whole_board'>('split_panels');
  const [panelPreview, setPanelPreview] = useState<PanelPreview | null>(null);
  const [busy, setBusy] = useState('');
  const [autoBatchOpen, setAutoBatchOpen] = useState(false);
  const [openedNameplateTaskId, setOpenedNameplateTaskId] = useState<string | null>(null);
  const currentChapterId = useRef(cid);
  currentChapterId.current = cid;
  const refresh = useCallback(async () => {
    const [chapter, taskRows] = await Promise.all([
      request<ChapterData>(base), request<GridTask[]>(`/tasks/?chapter_id=${cid}&summary=true&limit=500`),
    ]);
    if (currentChapterId.current !== cid) return;
    setData(chapter);
    setTasks(taskRows.filter(item => item.type.startsWith('grid_')));
  }, [base, cid]);
  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    novelApi.fetchChapters(id).then(result => {
      if (!cancelled && result.success && result.data) setChapterList(result.data);
    }).catch(error => {
      if (!cancelled) toast.error(`加载章回列表失败：${String(error)}`);
    });
    return () => { cancelled = true; };
  }, [id]);
  useEffect(() => {
    setData(null);
    setTasks([]);
    setStage(parseStageHash() || 'shot_split');
    setShotIndex((parseShotHash() || 1) - 1);
    setPanelIndex(0);
    setClipIndex(0);
    setLayout('auto');
    setImageView('board');
    setStrategy('split_panels');
    setPanelPreview(null);
    setBusy('');
    setAutoBatchOpen(false);
    setOpenedNameplateTaskId(null);
  }, [cid]);
  useEffect(() => { refresh().catch(error => toast.error(String(error))); }, [refresh]);
  const sortedChapters = [...chapterList].sort((a, b) => a.number - b.number);
  const currentChapterIndex = sortedChapters.findIndex(item => item.id === cid);
  const previousChapter = currentChapterIndex > 0 ? sortedChapters[currentChapterIndex - 1] : null;
  const nextChapter = currentChapterIndex >= 0 && currentChapterIndex < sortedChapters.length - 1 ? sortedChapters[currentChapterIndex + 1] : null;
  const goToChapter = (chapterId?: string) => {
    if (id && chapterId && chapterId !== cid) navigate(`/novels/${id}/chapters/${chapterId}/generate${gridModeHash(stage, 0)}`);
  };
  const hasActiveTask = tasks.some(item => item.status === 'pending' || item.status === 'running');
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!document.hidden) refresh().catch(() => undefined);
    }, hasActiveTask ? 3000 : 10000);
    return () => window.clearInterval(timer);
  }, [hasActiveTask, refresh]);
  const currentData = data?.chapter.id === cid ? data : null;
  const shots = currentData?.shots || [];
  useEffect(() => {
    if (!currentData || shotIndex < shots.length || (shots.length === 0 && shotIndex === 0)) return;
    setShotIndex(0);
  }, [currentData, shotIndex, shots.length]);
  useEffect(() => {
    if (!currentData || (shots.length > 0 && shotIndex >= shots.length) || (shots.length === 0 && shotIndex !== 0)) return;
    const nextHash = gridModeHash(stage, shotIndex);
    if (window.location.hash !== nextHash) {
      window.history.replaceState(window.history.state, '', `${window.location.pathname}${window.location.search}${nextHash}`);
    }
  }, [currentData, stage, shotIndex, shots.length]);
  useEffect(() => {
    const handleHashChange = () => {
      const requestedStage = parseStageHash();
      const requestedShot = parseShotHash();
      if (requestedStage) setStage(requestedStage);
      if (requestedShot) setShotIndex(requestedShot - 1);
    };
    window.addEventListener('hashchange', handleHashChange);
    return () => window.removeEventListener('hashchange', handleHashChange);
  }, []);
  const gridsReady = shots.filter(s => Boolean(s.gridData?.board_image_url)).length;
  const panels = shots.flatMap(s => s.gridData?.panels || []);
  const panelsPassed = panels.filter(p => p.review_status === 'passed').length;
  const allClips = shots.flatMap(s => s.gridClipPlan?.clip_plan || []);
  const clipsDone = allClips.filter(c => Boolean(c.video_url)).length;
  const shotsDone = shots.filter(s => Boolean(s.videoUrl)).length;
  const chapterMergeTask = tasks.find(item => item.type === 'grid_chapter_merge' && item.status === 'completed');
  const nameplatePreview = chapterMergeTask?.nameplatePreview;
  const nameplatePreviewOpened = openedNameplateTaskId === chapterMergeTask?.id;
  const shot = shots[shotIndex];
  const grid = shot?.gridData;
  const hasReplacedPanels = Boolean(grid?.panels.some(panel => panel.image_task_id && panel.image_task_id !== grid.board_image_task_id));
  useEffect(() => {
    setPanelIndex(0);
    setClipIndex(0);
    setStrategy(shot?.gridClipPlan?.clip_plan[0]?.reference_strategy || 'split_panels');
    setImageView(hasReplacedPanels ? 'panels' : 'board');
    setPanelPreview(null);
  }, [shot?.id]);
  useEffect(() => {
    if (hasReplacedPanels) setImageView('panels');
  }, [hasReplacedPanels, shot?.id]);
  const boardPreview: BoardPreview | null = grid?.board_prompt ? {
    prompt: grid.board_prompt, referenceImages: grid.board_reference_images || [],
    boardSize: [grid.panel_width * Number(grid.layout.split('x')[1]), grid.panel_height * Number(grid.layout.split('x')[0])],
  } : null;
  const clips = shot?.gridClipPlan?.clip_plan || [];
  const clip = clips[clipIndex];
  const selectedPanel = grid?.panels[panelIndex];
  const panelSpeakers = selectedPanel?.dialogue_indexes.map(number => shot?.dialogues[number - 1]?.speaker).filter((name): name is string => Boolean(name && name !== '旁白')) || [];
  const shotBase = shot ? `${base}/shots/${shot.id}` : '';
  const shotTasks = tasks.filter(item => item.shotId === shot?.id);
  const activeTask = tasks.find(item => ['pending', 'running'].includes(item.status));
  const unresolvedFailure = (shotId: string) => {
    const seen = new Set<string>();
    for (const task of tasks) {
      if (task.shotId !== shotId) continue;
      const key = `${task.gridStep || task.type}:${task.clipIndex || 0}:${task.panelIndex || 0}`;
      if (seen.has(key)) continue;
      seen.add(key);
      if (task.status === 'failed') return true;
    }
    return false;
  };
  const failedBoard = shotTasks.find(item => item.type === 'grid_board_image' && item.status === 'failed');
  const failedClip = shotTasks.find(item => item.type === 'grid_h3_clip' && item.clipIndex === clip?.clip_index && item.status === 'failed');
  const run = async (label: string, action: () => Promise<unknown>, nextStage?: Stage) => {
    const actionChapterId = cid;
    setBusy(label);
    try { const result = await action(); if (result === null) return; await refresh(); if (currentChapterId.current !== actionChapterId) return; if (nextStage) setStage(nextStage); toast.success((result && typeof result === 'object' && 'taskId' in result) ? `${label}已加入队列` : `${label}已完成`); }
    catch (error) { if (currentChapterId.current === actionChapterId) toast.error(error instanceof Error ? error.message : String(error)); }
    finally { if (currentChapterId.current === actionChapterId) setBusy(''); }
  };
  const selectShot = (index: number) => setShotIndex(index);
  const buttonClass = 'rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 hover:border-blue-400 disabled:cursor-not-allowed disabled:opacity-40';
  const primaryClass = 'rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-40';
  const button = (label: string, action: () => Promise<unknown>, enabled = true, primary = false, next?: Stage) =>
    <button type="button" disabled={Boolean(busy) || hasActiveTask || !enabled} className={primary ? primaryClass : buttonClass} onClick={() => run(label, action, next)}>{label}</button>;
  const confirmAction = (message: string, action: () => Promise<unknown>) =>
    window.confirm(message) ? action() : Promise.resolve(null);
  const batch = (label: string, step: string, count: number) => button(`${label} · ${count}`, () => {
    if (['board_generate', 'clip_generate'].includes(step))
      return confirmAction(`将提交 ${count} 项「${label}」任务，确认开始？`, () => request(`${base}/batch`, 'POST', { step }));
    return request(`${base}/batch`, 'POST', { step });
  }, count > 0);

  const submitAutoBatch = (shotIds: string[], mergeChapter: boolean) => {
    setAutoBatchOpen(false);
    void run('批量自动生成 Shot', () => request(`${base}/auto-batch`, 'POST', {
      shot_ids: shotIds, merge_chapter: mergeChapter,
    }), 'video_gen');
  };

  return <div className="min-h-full bg-gray-50 pb-10">
    <header className="border-b border-gray-200 bg-white px-5 py-4">
      <div className="flex flex-wrap items-center gap-3"><Link to={`/novels/${id}`} aria-label="返回章回列表" className="rounded p-2 text-gray-500 hover:bg-gray-100"><ArrowLeft className="h-5 w-5" /></Link>
        <div className="min-w-0"><h1 className="truncate text-lg font-semibold text-gray-900">{currentData?.chapter.title || '加载中'} <span className="rounded-full bg-blue-50 px-2 py-1 text-xs text-blue-700">宫格图生视频</span></h1>
          <p className="text-xs text-gray-500">{shots.length} 个叙事 Shot · {shots.reduce((n, s) => n + (s.gridData?.panels.length || 0), 0)} 个子格 · {shots.reduce((n, s) => n + (s.gridClipPlan?.clip_plan.length || 0), 0)} 条 Clip</p></div>
        <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
          {busy && <span className="inline-flex items-center gap-2 text-sm text-blue-700"><Loader2 className="h-4 w-4 animate-spin" />{busy}中，请等待</span>}
          <button type="button" className="rounded-lg bg-green-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-40" disabled={!shots.some(item => !item.videoUrl) || hasActiveTask || Boolean(busy)} onClick={() => setAutoBatchOpen(true)}>批量自动生成 Shot</button>
          <button type="button" onClick={() => goToChapter(previousChapter?.id)} disabled={!previousChapter} title={previousChapter?.title || '已经是第一回'} className="inline-flex items-center gap-1 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"><ChevronLeft className="h-4 w-4" />上一回</button>
          <select aria-label="跳转章回" value={currentChapterIndex >= 0 ? cid : ''} onChange={event => goToChapter(event.target.value)} disabled={sortedChapters.length === 0} className="w-48 max-w-full cursor-pointer rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40">
            {currentChapterIndex < 0 && <option value="">选择章回</option>}
            {sortedChapters.map(item => <option key={item.id} value={item.id}>{item.number}. {item.title}</option>)}
          </select>
          <button type="button" onClick={() => goToChapter(nextChapter?.id)} disabled={!nextChapter} title={nextChapter?.title || '已经是最后一回'} className="inline-flex items-center gap-1 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40">下一回<ChevronRight className="h-4 w-4" /></button>
        </div>
      </div>
    </header>
    <nav aria-label="生成阶段" className="flex gap-1 border-b border-gray-200 bg-white px-6 pt-2">{stages.map(item => <button key={item.key} type="button" onClick={() => setStage(item.key)} className={`border-b-2 px-4 py-3 text-sm ${stage === item.key ? 'border-blue-600 font-medium text-blue-700' : 'border-transparent text-gray-500'}`}>{item.label}</button>)}<span className="px-4 py-3 text-sm text-gray-300">音频生成</span><span className="px-4 py-3 text-sm text-gray-300">高清重绘</span></nav>
    <div className="grid gap-2 border-b border-gray-200 bg-white px-5 py-3 text-sm sm:grid-cols-4">
      <div>整板图 <strong>{gridsReady}/{shots.length}</strong></div><div>子格审核 <strong>{panelsPassed}/{panels.length}</strong></div>
      <div>H3 Clip <strong>{clipsDone}/{allClips.length}</strong></div><div>Shot 合片 <strong>{shotsDone}/{shots.length}</strong></div>
      {activeTask && <p className="sm:col-span-4 text-xs text-blue-700">后台正在执行：{activeTask.name}。可继续查看画面和提示词；生成操作将在任务结束后恢复。</p>}
    </div>
    <div className="px-5 pt-4 2xl:hidden"><GridTaskPanel tasks={tasks} shots={shots} onRefresh={() => refresh().catch(error => toast.error(String(error)))} onAction={(label, action) => { void run(label, action); }} onResumeBatch={step => { void run('继续批量任务', () => request(`${base}/batch`, 'POST', { step })); }} /></div>
    {autoBatchOpen && <GridAutoBatchModal shots={shots} onClose={() => setAutoBatchOpen(false)} onSubmit={submitAutoBatch} />}
    <div className="grid gap-4 p-5 md:grid-cols-[190px_minmax(0,1fr)] 2xl:grid-cols-[250px_minmax(0,1fr)_300px]">
      <aside className="rounded-xl border border-gray-200 bg-white p-4 md:sticky md:top-4 md:max-h-[calc(100vh-2rem)] md:self-start md:overflow-y-auto"><h2 className="font-semibold">叙事 Shot</h2><p className="mt-1 text-xs text-gray-500">一个 Shot 管一段情节，内部按顺序排多个机位。</p>
        <div className="mt-3 space-y-2">{shots.map((item, i) => <button key={item.id} type="button" onClick={() => selectShot(i)} className={`w-full overflow-hidden rounded-lg border text-left ${shotIndex === i ? 'border-blue-500 bg-blue-50' : 'border-gray-200'}`}>
          {item.gridData?.board_image_url && <img src={item.gridData.board_image_url} alt={`Shot ${item.index} 宫格`} className="aspect-video w-full object-cover" />}
          <span className="block px-3 py-2 text-sm font-medium">Shot {item.index} · {item.description.split('｜')[0]}</span><span className="block px-3 text-xs text-gray-500">{item.gridData?.layout || '待规划'} · {item.gridData?.panels.length || 0} 格 · {item.gridClipPlan?.clip_plan.length || 0} Clips</span><span className={`block px-3 pb-2 pt-1 text-xs ${unresolvedFailure(item.id) ? 'text-red-700' : 'text-green-700'}`}>{tasks.some(t => t.shotId === item.id && ['pending', 'running'].includes(t.status)) ? '任务执行中' : unresolvedFailure(item.id) ? '有失败任务，可重试' : item.videoUrl ? 'Shot 视频完成' : item.gridClipPlan?.clip_plan.some(c => c.video_url) ? `视频 ${item.gridClipPlan.clip_plan.filter(c => c.video_url).length}/${item.gridClipPlan.clip_plan.length}` : item.gridData?.board_image_url ? `子格审核 ${item.gridData.panels.filter(p => p.review_status === 'passed').length}/${item.gridData.panels.length}` : item.gridData?.board_prompt ? '待生成整板' : item.gridData ? '待准备整板提示词' : '待规划子格'}</span>
        </button>)}</div>
      </aside>
      <main className="min-w-0 space-y-4">
        <section className="rounded-xl border border-gray-200 bg-white p-4"><h2 className="font-semibold">{stage === 'shot_split' ? '准备与拆分' : stage === 'shot_image' ? '整板生图与逐格审阅' : 'Clip 与 H3 视频'}</h2>
          <div className="mt-3 flex flex-wrap gap-2">
            {stage === 'shot_split' && <>{button('AI 拆分本章', () => request(`${base}/plan`, 'POST'), shots.length === 0, true)}
              <select value={layout} onChange={event => setLayout(event.target.value)} className={buttonClass}><option value="auto">自动随机 2×2 / 2×3</option><option value="2x2">2×2 · 4 格</option><option value="2x3">2×3 · 6 格</option><option value="3x3">3×3 · 实验</option></select>
              {button('规划当前 Shot 子格', () => request(`${shotBase}/panels/plan`, 'POST', { layout: layout === 'auto' ? null : layout }), Boolean(shot && !grid), true, 'shot_image')}
              {layout === 'auto' && batch('批量规划未规划的 Shot', 'panels_plan', shots.filter(s => !s.gridData).length)}</>}
            {stage === 'shot_image' && <>{button('生成整板提示词', () => request(`${shotBase}/board/prepare`, 'POST'), Boolean(grid && !grid.board_image_url))}
              {button(grid?.board_image_url ? '重新生成当前宫格' : '生成当前宫格', () => grid?.board_image_url ? confirmAction('重新生成会使当前宫格的逐格审核、Clip 和合片失效，确认继续？', () => request(`${shotBase}/board/generate`, 'POST')) : request(`${shotBase}/board/generate`, 'POST'), Boolean(boardPreview && grid?.board_prompt), true)}
              {batch('批量准备整板提示词', 'board_prepare', shots.filter(s => s.gridData && !s.gridData.board_prompt && !s.gridData.board_image_url).length)}
              {batch('批量生成已准备整板', 'board_generate', shots.filter(s => s.gridData?.board_prompt && !s.gridData.board_image_url).length)}</>}
            {stage === 'video_gen' && <>{button(clips.length ? '重新规划本 Shot 的 Clip' : '规划本 Shot 的 Clip', () => clips.length ? confirmAction('重新规划会清除当前 Clip 提示词，确认继续？', () => request(`${shotBase}/clips/plan`, 'POST')) : request(`${shotBase}/clips/plan`, 'POST'), Boolean(grid?.panels.every(p => p.review_status === 'passed')) && !clips.some(c => c.video_url), true)}
              {batch('批量规划已审核 Shot 的 Clip', 'clips_plan', shots.filter(s => s.gridData?.panels.every(p => p.image_url && p.review_status === 'passed') && !s.gridClipPlan).length)}
              {batch('批量编译 H3 提示词', 'clip_prepare', allClips.filter(c => !c.prompt).length)}
              {batch('批量生成已编译 Clip', 'clip_generate', allClips.filter(c => c.prompt && !c.video_url).length)}
              {button('合并本 Shot', () => request(`${shotBase}/merge`, 'POST'), clips.length > 0 && clips.every(c => Boolean(c.video_url)))}
              {batch('批量合并已完成 Shot', 'shot_merge', shots.filter(s => !s.videoUrl && s.gridClipPlan?.clip_plan.length && s.gridClipPlan.clip_plan.every(c => Boolean(c.video_url))).length)}
              {button('合并章回视频', () => request(`${base}/merge`, 'POST'), shots.length > 0 && shots.every(s => Boolean(s.videoUrl)))}</>}
          </div>
        </section>
        {!shot && <section className="rounded-xl border bg-white p-8 text-center text-sm text-gray-500">先在“分镜拆分”中将章节正文规划成叙事 Shot。</section>}
        {shot && <section className="rounded-xl border border-gray-200 bg-white p-5"><div className="flex items-start justify-between gap-3"><div><h2 className="text-lg font-semibold">Shot {shot.index} · {shot.description.split('｜')[0]}</h2><p className="mt-1 text-sm text-gray-600">{shot.description.split('｜').slice(1).join('｜')}</p></div><span className="whitespace-nowrap rounded-full bg-indigo-50 px-3 py-1 text-xs text-indigo-700">{grid?.layout || '未规划'} · {shot.duration}s</span></div>
          {stage === 'shot_split' && <div className="mt-5">{grid ? <><p className="mb-2 text-sm font-medium">逐格镜头规划 · 修订 {grid.revision}</p><div className={`grid gap-2 ${grid.layout.endsWith('3') ? 'grid-cols-3' : 'grid-cols-2'}`}>{grid.panels.map(panel => <div key={panel.index} className="rounded-lg border bg-gray-50 p-3 text-sm"><strong>格 {panel.index} · {panel.camera}</strong><p className="mt-1 text-gray-600">{panel.beat}</p></div>)}</div></> : <p className="text-sm text-gray-500">选择版式后规划子格。自动版式会在 2×2 和 2×3 中随机选择并固定种子；3×3 可单独实验。</p>}</div>}
          {stage === 'shot_image' && <div className="mt-5 space-y-4">{failedBoard && !grid?.board_image_url && <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800"><strong>当前整板生成失败</strong><p className="mt-1">{failedBoard.errorMessage || '请查看右侧任务详情'}</p>{button('重试此整板', () => request(`/tasks/${failedBoard.id}/retry`, 'POST'), true)}</div>}{boardPreview && <section className="rounded-lg border border-blue-200 bg-blue-50 p-4"><h3 className="font-medium">即将提交的整板输入 · {boardPreview.boardSize.join(' × ')}</h3><div className="mt-2 flex gap-2">{boardPreview.referenceImages.map((ref, i) => <div key={i} className="w-24"><img src={ref.url} alt={ref.name} className="aspect-video w-full rounded object-cover" /><span className="text-xs">{ref.role} · {ref.name}</span></div>)}</div><pre className="mt-3 max-h-52 overflow-auto whitespace-pre-wrap text-xs">{boardPreview.prompt}</pre></section>}
            {grid?.board_image_url && <>{hasReplacedPanels && <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800">部分子格已单独重做；整板是初稿，H3 将使用下方逐格视图中的最新版图片。</p>}<div className="flex gap-2"><button type="button" onClick={() => setImageView('board')} className={buttonClass}><LayoutGrid className="mr-1 inline h-4 w-4" />整板初稿</button><button type="button" onClick={() => setImageView('panels')} className={buttonClass}><ImageIcon className="mr-1 inline h-4 w-4" />逐格最新版</button></div>
              {imageView === 'board' ? <img src={grid.board_image_url} alt="宫格整板" className="w-full rounded-lg" /> : <div className={`grid gap-2 ${grid.layout.endsWith('3') ? 'grid-cols-3' : 'grid-cols-2'}`}>{grid.panels.map((panel, i) => <button key={i} type="button" onClick={() => { setPanelIndex(i); setPanelPreview(null); }} className={`overflow-hidden rounded-lg border-2 text-left ${i === panelIndex ? 'border-blue-500' : 'border-transparent'}`}><img src={panel.image_url} alt={`格 ${panel.index}`} className="aspect-video w-full object-cover" /><span className="block p-2 text-xs">格 {panel.index} · {{ passed: '已通过', failed: '需重做', pending: '待审核' }[panel.review_status] || panel.review_status}</span></button>)}</div>}
              {selectedPanel && <GridPanelReview key={`${shot.id}:${selectedPanel.index}:${selectedPanel.image_url}`} panel={selectedPanel} speakers={panelSpeakers} preview={panelPreview} disabled={Boolean(busy) || hasActiveTask}
                onApprove={note => { void run('审核通过', () => request(`${shotBase}/panels/${selectedPanel.index}/review`, 'PATCH', { status: 'passed', note })); }}
                onReject={note => { void run('标记需重做', () => request(`${shotBase}/panels/${selectedPanel.index}/review`, 'PATCH', { status: 'failed', note })); }}
                onPrepare={() => { void run('预览单格重做输入', async () => { setPanelPreview(await request<PanelPreview>(`${shotBase}/panels/${selectedPanel.index}/prepare`, 'POST')); }); }}
                onGenerate={() => { void run('AI 重做此格', () => request(`${shotBase}/panels/${selectedPanel.index}/generate`, 'POST')); }}
                onReplace={file => { const form = new FormData(); form.append('file', file); void run('替换子格', () => request(`${shotBase}/panels/${selectedPanel.index}/replace`, 'POST', form)); }} />}
            </>}
            {!grid?.board_image_url && <p className="text-sm text-gray-500">先规划子格，再预览整板提示词与实际素材参考图，然后生成。</p>}</div>}
          {stage === 'video_gen' && <div className="mt-5 space-y-4">{clips.length === 0 ? <p className="text-sm text-gray-500">所有子格审核通过后，按动作和台词规划 Clip。</p> : <><div className="grid gap-2 sm:grid-cols-2">{clips.map((item, i) => <button key={i} type="button" onClick={() => { setClipIndex(i); setStrategy(item.reference_strategy); }} className={`rounded-lg border p-3 text-left ${i === clipIndex ? 'border-blue-500 bg-blue-50' : 'border-gray-200'}`}><strong>C{item.clip_index} · {item.duration}s</strong><p className="mt-1 text-xs">子格 {item.panel_indexes.join(' → ')} · {item.dialogues.length} 句台词 · {item.video_url ? '已生成' : '待生成'}</p></button>)}</div>
            {clip && <><div className="rounded-lg border p-4"><h3 className="font-medium">C{clip.clip_index} · 参考图与六段式提示词</h3><p className="mt-1 text-xs text-gray-500">默认只送当前 Clip 的子格。整板直传可显式选择；不自动附加白底角色图。</p><div className="mt-3 flex flex-wrap gap-2"><select value={strategy} onChange={event => setStrategy(event.target.value as typeof strategy)} className={buttonClass}><option value="split_panels">裁切子格</option><option value="whole_board">整板直传</option></select>{button('编译并校验提示词', () => clip.video_url ? confirmAction('重新编译会使此 Clip 视频和现有合片失效，确认继续？', () => request(`${shotBase}/clips/${clip.clip_index}/prepare`, 'POST', { reference_strategy: strategy })) : request(`${shotBase}/clips/${clip.clip_index}/prepare`, 'POST', { reference_strategy: strategy }), true, true)}{button(clip.video_url ? '重做此 Clip' : '生成此 Clip', () => clip.video_url ? confirmAction('确认重新生成此 Clip？完成后需要重新合并 Shot。', () => request(`${shotBase}/clips/${clip.clip_index}/generate`, 'POST')) : request(`${shotBase}/clips/${clip.clip_index}/generate`, 'POST'), Boolean(clip.prompt && strategy === clip.reference_strategy), true)}</div>
              {failedClip && !clip.video_url && <div className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800"><strong>C{clip.clip_index} 生成失败</strong><p className="mt-1">{failedClip.errorMessage || '请查看右侧任务详情'}</p>{button('从此 Clip 续做', () => request(`/tasks/${failedClip.id}/retry`, 'POST'), true)}</div>}
              {clip.reference_images && <div className="mt-4 flex flex-wrap gap-3">{clip.reference_images.map(ref => <div key={ref.picture_index} className="w-36"><img src={ref.url} alt={`Picture ${ref.picture_index}`} className="aspect-video w-full rounded object-cover" /><span className="text-xs">Picture {ref.picture_index} · {ref.role === 'GRID_BOARD' ? '整板' : `子格 ${ref.panel_index}`}</span></div>)}</div>}
              <div className="mt-4"><h4 className="text-sm font-medium">原文台词</h4>{clip.dialogues.length ? clip.dialogues.map(line => <p key={line.id} className="text-sm">{line.id} · {line.speaker}：{line.text}</p>) : <p className="text-sm text-gray-500">无台词</p>}</div>
              {clip.prompt && <pre className="mt-4 max-h-96 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-900 p-4 text-xs text-slate-100">{clip.prompt}</pre>}
              {clip.video_url && <video controls src={clip.video_url} className="mt-4 w-full rounded-lg" />}
            </div></>}
          </>}</div>}
        </section>}
      </main>
      <aside className="space-y-4 md:col-span-2 2xl:sticky 2xl:top-4 2xl:col-auto 2xl:max-h-[calc(100vh-2rem)] 2xl:self-start 2xl:overflow-y-auto"><div className="hidden 2xl:block"><GridTaskPanel tasks={tasks} shots={shots} onRefresh={() => refresh().catch(error => toast.error(String(error)))} onAction={(label, action) => { void run(label, action); }} onResumeBatch={step => { void run('继续批量任务', () => request(`${base}/batch`, 'POST', { step })); }} /></div>
        <section className="rounded-xl border bg-white p-4"><h2 className="font-semibold">最终 Shot 视频</h2>{shot?.videoUrl ? <FinalShotVideo key={`${shot.id}:${shot.videoUrl}`} videoUrl={shot.videoUrl} /> : <p className="mt-3 text-sm text-gray-500">Clip 完成后合并本 Shot。</p>}</section>
        <section className="rounded-xl border bg-white p-4"><h2 className="font-semibold">章回合片</h2>{currentData?.chapter.finalVideo ? <><video controls src={nameplatePreviewOpened && nameplatePreview?.url ? nameplatePreview.url : currentData.chapter.finalVideo} className="mt-3 w-full rounded" /><a href={currentData.chapter.finalVideo} download className="mt-2 inline-flex text-sm text-blue-700"><Film className="mr-1 h-4 w-4" />下载视频</a></> : <p className="mt-3 text-sm text-gray-500">全部 Shot 合片后可生成章回视频。</p>}
          {nameplatePreview?.url && <div className="mt-3 rounded-lg border border-red-100 bg-red-50 p-3 text-sm">
            <p className="font-medium text-red-800">首次出镜姓名牌 · {nameplatePreview.status === 'approved' ? '已用于成片' : '待确认'}</p>
            <div className="mt-2 flex flex-wrap gap-2"><button type="button" className={buttonClass} onClick={() => setOpenedNameplateTaskId(chapterMergeTask?.id || null)}>预览姓名牌版本</button>
              {nameplatePreview.status === 'pending_confirmation' && chapterMergeTask && <button type="button" className={primaryClass} disabled={!nameplatePreviewOpened || Boolean(busy)} onClick={() => void run('确认姓名牌', () => request(`/novels/${id}/chapters/${cid}/nameplate-preview/${chapterMergeTask.id}/approve`, 'POST'))}>确认用于成片</button>}
            </div>
          </div>}
          {!!nameplatePreview?.warnings?.length && <p className="mt-2 text-xs text-amber-700">{nameplatePreview.warnings.join('；')}</p>}
        </section>
        <section className="rounded-xl border bg-white p-4 text-xs text-gray-500"><CheckCircle2 className="mr-1 inline h-4 w-4" />所有输入和结果按 Shot 修订号保存，任务详情可追溯。</section>
      </aside>
    </div>
  </div>;
}
