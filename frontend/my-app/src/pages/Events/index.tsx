import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Activity, AlertCircle, ArrowUpRight, ChevronLeft, ChevronRight, Loader2, RefreshCw, X } from 'lucide-react';
import { eventsApi, type BusinessEvent, type EventDetail, type EventOptions, type EventPage } from '../../api/events';
import { ImageReviewModal, DIMENSION_NAMES } from '../Tasks/components/ImageReviewModal';

const statusClass = { SUCCESS: 'bg-green-50 text-green-700', FAIL: 'bg-red-50 text-red-700', ERROR: 'bg-orange-50 text-orange-800', INFO: 'bg-blue-50 text-blue-700' };
const time = (value: string) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—';
const triggerName = (value: string | null) => value === 'manual' ? '手动' : value === 'automatic' ? '自动' : value || '未记录';
const initialFilters = { event_type: '', status: '', novel_id: '', chapter_id: '', shot_id: '', start_time: '', end_time: '' };
function Status({ event }: { event: BusinessEvent }) {
  return <span className={`inline-flex rounded px-2 py-1 text-xs font-medium ${statusClass[event.status]}`}>{event.raw_status === 'WARNING' ? 'INFO · REVIEW' : event.status}</span>;
}

export default function Events() {
  const [options, setOptions] = useState<EventOptions>({ events: [], novels: [], chapters: [], shots: [] });
  const [filters, setFilters] = useState(initialFilters);
  const [view, setView] = useState('all');
  const [page, setPage] = useState(1);
  const [refresh, setRefresh] = useState(0);
  const [autoRefreshInterval, setAutoRefreshInterval] = useState(0);
  const [autoRefreshTick, setAutoRefreshTick] = useState(0);
  const [data, setData] = useState<EventPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const listRequestInFlight = useRef(false);
  const lastListRequestKey = useRef('');
  const [selected, setSelected] = useState<string | null>(() => new URLSearchParams(window.location.search).get('event'));
  const [detail, setDetail] = useState<EventDetail | null>(null);
  const [detailError, setDetailError] = useState('');
  const [review, setReview] = useState<EventDetail['review_target']>(null);

  useEffect(() => {
    if (!autoRefreshInterval) return;
    const timer = window.setInterval(() => {
      if (!listRequestInFlight.current) setAutoRefreshTick(value => value + 1);
    }, autoRefreshInterval);
    return () => window.clearInterval(timer);
  }, [autoRefreshInterval]);
  useEffect(() => { let active = true; void eventsApi.options().then(value => { if (active) setOptions(value); }).catch(err => { if (active) setError(String(err)); }); return () => { active = false; }; }, [refresh]);
  useEffect(() => {
    let active = true;
    const query = new URLSearchParams({ page: String(page), page_size: '25', view, timezone_offset: String(new Date().getTimezoneOffset()) });
    Object.entries(filters).forEach(([key, value]) => { if (value) query.set(key, key.endsWith('_time') ? new Date(value).toISOString() : value); });
    const requestKey = `${query.toString()}:${refresh}`;
    if (lastListRequestKey.current !== requestKey) setLoading(true);
    lastListRequestKey.current = requestKey;
    listRequestInFlight.current = true;
    setError('');
    void eventsApi.list(query).then(value => { if (active) setData(value); }).catch(err => { if (active) setError(String(err)); }).finally(() => { if (active) { listRequestInFlight.current = false; setLoading(false); } });
    return () => { active = false; };
  }, [filters, page, view, refresh, autoRefreshTick]);
  useEffect(() => {
    let active = true; setDetail(null); setDetailError('');
    if (selected) void eventsApi.detail(selected).then(value => { if (active) setDetail(value); }).catch(err => { if (active) setDetailError(String(err)); });
    return () => { active = false; };
  }, [selected, refresh]);
  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') { if (review) setReview(null); else setSelected(null); } };
    window.addEventListener('keydown', close); return () => window.removeEventListener('keydown', close);
  }, [review]);
  const chapters = options.chapters.filter(c => !filters.novel_id || c.novel_id === filters.novel_id);
  const shots = options.shots.filter(s => (!filters.chapter_id || s.chapter_id === filters.chapter_id) && chapters.some(c => c.id === s.chapter_id));
  const groups = useMemo(() => Array.from(new Set(options.events.map(e => e.category))), [options.events]);
  const change = (key: keyof typeof initialFilters, value: string) => {
    setPage(1); setFilters(old => ({ ...old, [key]: value, ...(key === 'novel_id' ? { chapter_id: '', shot_id: '' } : key === 'chapter_id' ? { shot_id: '' } : {}) }));
  };
  const selectClass = 'mt-1 w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900';
  return <div className="mx-auto max-w-[1600px] space-y-5 p-6" data-testid="event-center">
    <header className="flex flex-wrap items-center justify-between gap-3">
      <div><h1 className="flex items-center gap-2 text-2xl font-semibold text-gray-900"><Activity className="text-blue-600" />事件中心</h1><p className="mt-1 text-sm text-gray-500">查看已发生的业务事件，定位评审、生成和合并结果。</p></div>
      <div className="flex flex-wrap items-center gap-3"><label className="inline-flex items-center gap-2 text-sm text-gray-600">自动更新<select aria-label="自动更新频率" className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900" value={autoRefreshInterval} onChange={e => setAutoRefreshInterval(Number(e.target.value))}><option value={0}>不更新</option><option value={5000}>每5秒刷新</option><option value={20000}>每20秒刷新</option></select></label><Link to="/settings#notifications" className="text-sm text-blue-600">消息通知设置</Link><button className="inline-flex items-center gap-2 rounded-lg border bg-white px-3 py-2 text-sm" onClick={() => setRefresh(v => v + 1)}><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />刷新</button></div>
    </header>
    <div className="flex flex-wrap gap-2" role="tablist" aria-label="事件视图">
      {([['all', '全部事件'], ['attention', '需要关注'], ['today', '今日异常']] as const).map(([key, label]) => <button key={key} role="tab" aria-selected={view === key} onClick={() => { setView(key); setPage(1); }} className={`rounded-lg border px-4 py-2 text-sm ${view === key ? 'border-blue-600 bg-blue-600 text-white' : 'bg-white text-gray-600'}`}>{label}<span className="ml-2 opacity-80">{data?.counts[key] ?? '—'}</span></button>)}
    </div>
    <section className="grid gap-3 rounded-xl border bg-white p-4 sm:grid-cols-2 xl:grid-cols-4" aria-label="事件筛选">
      <label className="text-xs text-gray-500">事件类型<select aria-label="事件类型" className={selectClass} value={filters.event_type} onChange={e => change('event_type', e.target.value)}><option value="">全部类型</option>{groups.map(group => <optgroup label={group} key={group}>{options.events.filter(e => e.category === group).map(e => <option key={e.event_type} value={e.event_type}>{e.name}</option>)}</optgroup>)}</select></label>
      <label className="text-xs text-gray-500">状态<select aria-label="状态" className={selectClass} value={filters.status} onChange={e => change('status', e.target.value)}><option value="">全部状态</option>{Object.keys(statusClass).map(s => <option key={s}>{s}</option>)}</select></label>
      <label className="text-xs text-gray-500">小说<select aria-label="小说" className={selectClass} value={filters.novel_id} onChange={e => change('novel_id', e.target.value)}><option value="">全部小说</option>{options.novels.map(n => <option value={n.id} key={n.id}>{n.title}</option>)}</select></label>
      <label className="text-xs text-gray-500">章节<select aria-label="章节" className={selectClass} value={filters.chapter_id} onChange={e => change('chapter_id', e.target.value)}><option value="">全部章节</option>{chapters.map(c => <option value={c.id} key={c.id}>{c.title}</option>)}</select></label>
      <label className="text-xs text-gray-500">Shot<select aria-label="Shot" className={selectClass} value={filters.shot_id} onChange={e => change('shot_id', e.target.value)}><option value="">全部 Shot</option>{shots.map(s => <option value={s.id} key={s.id}>Shot {s.index} · {options.chapters.find(c => c.id === s.chapter_id)?.title}</option>)}</select></label>
      <label className="text-xs text-gray-500">开始时间<input aria-label="开始时间" type="datetime-local" className={selectClass} value={filters.start_time} onChange={e => change('start_time', e.target.value)} /></label>
      <label className="text-xs text-gray-500">结束时间<input aria-label="结束时间" type="datetime-local" className={selectClass} value={filters.end_time} onChange={e => change('end_time', e.target.value)} /></label>
      <div className="flex items-end"><button onClick={() => { setFilters(initialFilters); setPage(1); }} className="rounded-lg border px-4 py-2 text-sm text-gray-600">重置筛选</button></div>
    </section>
    {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}
    <section className="overflow-hidden rounded-xl border bg-white">
      <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="border-b bg-gray-50 text-xs text-gray-500"><tr>{['时间', '事件类型', '小说 / 章节', 'Shot', '视觉状态 / Clip', '状态', '操作'].map(h => <th key={h} className="px-4 py-3 font-medium">{h}</th>)}</tr></thead>
        <tbody className={`divide-y ${loading ? 'opacity-50' : ''}`}>{data?.items.map(event => <tr key={event.event_id} className="hover:bg-blue-50/40">
          <td className="whitespace-nowrap px-4 py-4 text-xs text-gray-600">{time(event.timestamp)}{event.historical && <div className="mt-1 text-gray-400">历史回填</div>}{event.is_test && <div className="text-amber-600">模拟事件</div>}</td>
          <td className="max-w-sm px-4 py-4"><button className="font-medium text-gray-900 hover:text-blue-600" onClick={() => setSelected(event.event_id)}>{event.name}</button><div className="mt-1 text-xs text-gray-400">{event.event_type}</div><p className="mt-1 line-clamp-2 text-xs text-gray-500">{event.message}</p></td>
          <td className="max-w-xs px-4 py-4"><div className="truncate text-gray-800">{event.novel_title || '—'}</div><div className="mt-1 truncate text-xs text-gray-500">{event.chapter_title || '—'}</div></td>
          <td className="whitespace-nowrap px-4 py-4 text-gray-700">{event.shot_index ? `Shot ${event.shot_index}` : '—'}</td>
          <td className="whitespace-nowrap px-4 py-4 text-gray-700">{event.visual_state_id ? `视觉状态 ${event.visual_state_id}` : event.details.clip_index ? `C${event.details.clip_index}` : '—'}</td>
          <td className="px-4 py-4"><Status event={event} /></td><td className="px-4 py-4"><button className="whitespace-nowrap text-blue-600" aria-label={`查看事件 ${event.event_id}`} onClick={() => setSelected(event.event_id)}>详情</button></td>
        </tr>)}</tbody></table></div>
      {!loading && !data?.items.length && !error && <div className="py-16 text-center text-sm text-gray-500">暂无符合条件的事件</div>}
      <footer className="flex items-center justify-between border-t px-4 py-3 text-sm text-gray-500"><span>{loading ? '读取中…' : `共 ${data?.total ?? 0} 条 · 每页 25 条`}</span><div className="flex items-center gap-3"><button aria-label="上一页" disabled={page === 1 || loading} className="rounded border p-1 disabled:opacity-30" onClick={() => setPage(p => p - 1)}><ChevronLeft className="h-4 w-4" /></button><span>{page} / {Math.max(1, Math.ceil((data?.total ?? 0) / 25))}</span><button aria-label="下一页" disabled={loading || page * 25 >= (data?.total ?? 0)} className="rounded border p-1 disabled:opacity-30" onClick={() => setPage(p => p + 1)}><ChevronRight className="h-4 w-4" /></button></div></footer>
    </section>
    <p className="text-xs text-gray-400">事件记录独立于通知开关。历史回填不补发通知；图片评审结果不改变图片生成状态。</p>
    {selected && <div className="fixed inset-0 z-40 flex justify-end bg-black/30" onClick={() => setSelected(null)}><aside role="dialog" aria-modal="true" aria-label="事件详情" className="flex h-full w-full max-w-2xl flex-col bg-white shadow-2xl" onClick={e => e.stopPropagation()}>
      <header className="flex items-center justify-between border-b px-6 py-5"><h2 className="text-lg font-semibold">事件详情</h2><button aria-label="关闭事件详情" onClick={() => setSelected(null)}><X className="h-5 w-5" /></button></header>
      <div className="overflow-y-auto p-6 space-y-5">{detailError && <p role="alert" className="text-red-600">{detailError}</p>}{!detail && !detailError && <Loader2 className="animate-spin" />}
        {detail && <><div className="flex items-start justify-between gap-3"><div><h3 className="text-xl font-semibold">{detail.name}</h3><p className="mt-1 break-all text-xs text-gray-500">{detail.event_type}</p></div><Status event={detail} /></div>
          {detail.needs_attention && <div className="flex gap-2 rounded-lg bg-amber-50 p-3 text-sm text-amber-800"><AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />此事件需要关注。{detail.event_type.startsWith('image.review.') ? '评审结论独立于图片生成状态。' : '可通过下方关联操作查看业务记录。'}</div>}
          <p className="rounded-lg bg-gray-50 p-4 text-sm leading-relaxed text-gray-700">{detail.message}</p>
          {Array.isArray(detail.details.failed_dimensions) && detail.details.failed_dimensions.length > 0 && <div className="flex flex-wrap items-center gap-2 text-xs"><span className="text-gray-500">需关注维度</span>{detail.details.failed_dimensions.map(value => <span key={String(value)} className="rounded bg-amber-50 px-2 py-1 text-amber-800">{DIMENSION_NAMES[String(value)] || String(value)}</span>)}</div>}
          <dl className="grid grid-cols-[7rem_1fr] gap-x-4 gap-y-3 text-sm">{[
            ['事件 ID', detail.event_id], ['原始状态', detail.raw_status], ['发生时间', time(detail.timestamp)],
            ['入库时间', time(detail.recorded_at)], ['记录类型', detail.historical ? '历史回填（未发送通知）' : detail.is_test ? '模拟事件' : '实时业务事件'],
            ['小说', detail.novel_title], ['章节', detail.chapter_title], ['Shot', detail.shot_index ? `Shot ${detail.shot_index}` : null],
            ['视觉状态', detail.visual_state_id], ['Clip', detail.clip_id], ['任务 ID', detail.task_id],
            ['评审记录 ID', detail.review_id], ['事件来源', detail.source], ['触发方式', triggerName(detail.trigger)], ['通知状态', detail.notification_status],
          ].map(([label, value]) => <div key={label} className="contents"><dt className="text-gray-500">{label}</dt><dd className="break-all text-gray-900">{value || '—'}</dd></div>)}</dl>
          <div className="flex flex-wrap gap-2">{detail.links.map(link => <Link key={link.href} to={link.href} className="inline-flex items-center gap-1 rounded-lg border border-blue-200 px-3 py-2 text-sm text-blue-600">{link.label}<ArrowUpRight className="h-4 w-4" /></Link>)}{detail.review_target && <button className="rounded-lg bg-blue-600 px-3 py-2 text-sm text-white" onClick={() => setReview(detail.review_target)}>查看 AI 评审记录</button>}</div>
          <div><h4 className="mb-2 text-sm font-semibold">详细信息</h4><pre className="overflow-auto rounded-lg bg-gray-50 p-4 text-xs leading-relaxed">{JSON.stringify(detail.details, null, 2)}</pre></div>
          {Object.keys(detail.notification_result).length > 0 && <details className="text-sm text-gray-600"><summary className="cursor-pointer">通知分发结果</summary><pre className="mt-2 overflow-auto rounded bg-gray-50 p-3 text-xs">{JSON.stringify(detail.notification_result, null, 2)}</pre></details>}
        </>}
      </div>
    </aside></div>}
    {review && <ImageReviewModal key={review.review_id} task={review} initialReviewId={review.review_id} onClose={() => setReview(null)} />}
  </div>;
}
