import { useCallback, useEffect, useState } from 'react';
import { ArrowLeft, ArrowRight, Loader2, RefreshCw, Search, X } from 'lucide-react';
import { llmLogsApi } from '../../../api/llmLogs';
import type { TokenUsageHierarchy, TokenUsageNode } from '../../../api/llmLogs';

const number = (value: number) => new Intl.NumberFormat('zh-CN').format(value);

function UsageCell({ value, emphasis = false, warning = false }: { value: number; emphasis?: boolean; warning?: boolean }) {
  const color = emphasis ? 'font-semibold text-slate-900' : warning && value ? 'font-medium text-amber-700' : 'text-slate-600';
  return <td className={'border-b border-slate-100 px-3 py-2.5 text-right tabular-nums ' + color}>{number(value)}</td>;
}

export function TokenUsageHierarchyModal({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<TokenUsageHierarchy | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  // undefined: no selection; null: the unassigned bucket.
  const [novelId, setNovelId] = useState<string | null | undefined>(undefined);
  const [chapterId, setChapterId] = useState<string | null | undefined>(undefined);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const result = await llmLogsApi.fetchTokenUsageHierarchy();
      if (!result.success || !result.data) throw new Error(result.message || '获取 Token 用量失败');
      setData(result.data);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '获取 Token 用量失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const novel = novelId === undefined ? undefined : data?.novels.find(item => item.id === novelId);
  const chapter = chapterId === undefined ? undefined : novel?.chapters.find(item => item.id === chapterId);
  const level = !novel ? 'novels' : !chapter ? 'chapters' : 'shots';
  const scope: TokenUsageNode | null = level === 'shots' ? chapter! : level === 'chapters' ? novel! : data;
  const rows: TokenUsageNode[] = level === 'shots' ? chapter!.shots : level === 'chapters' ? novel!.chapters : data?.novels || [];
  const visibleRows = rows.filter(item => item.label.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const levelName = level === 'novels' ? '小说' : level === 'chapters' ? '章回' : 'Shot';

  const goToNovels = () => { setNovelId(undefined); setChapterId(undefined); setQuery(''); };
  const goToChapters = () => { setChapterId(undefined); setQuery(''); };
  const goBack = level === 'shots' ? goToChapters : goToNovels;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/55 p-3 sm:p-6" onClick={onClose}>
      <div className="flex max-h-[86vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl" onClick={event => event.stopPropagation()}>
        <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-4">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold text-slate-900">Token 用量</h2>
            <p className="mt-0.5 text-xs text-slate-500">按小说、章回和 Shot 查看历史 LLM 调用</p>
          </div>
          <button type="button" onClick={onClose} aria-label="关闭" className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100"><X className="h-5 w-5" /></button>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
          <nav aria-label="Token 用量层级" className="flex min-w-0 items-center gap-2 text-sm">
            {level !== 'novels' && <button type="button" onClick={goBack} aria-label="返回上一级" className="mr-1 rounded-lg p-1 text-slate-500 hover:bg-slate-100"><ArrowLeft className="h-4 w-4" /></button>}
            <button type="button" onClick={goToNovels} className={'shrink-0 hover:text-blue-600 ' + (level === 'novels' ? 'font-semibold text-slate-900' : 'text-slate-500')}>全部小说</button>
            {novel && <><span className="text-slate-300">/</span><button type="button" onClick={goToChapters} className={'max-w-[200px] truncate hover:text-blue-600 ' + (level === 'chapters' ? 'font-semibold text-slate-900' : 'text-slate-500')} title={novel.label}>{novel.label}</button></>}
            {chapter && <><span className="text-slate-300">/</span><span className="max-w-[200px] truncate font-semibold text-slate-900" title={chapter.label}>{chapter.label}</span></>}
          </nav>
          <button type="button" onClick={() => void load()} disabled={loading} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-50"><RefreshCw className={'h-3.5 w-3.5 ' + (loading ? 'animate-spin' : '')} />刷新</button>
        </div>

        {loading ? <div className="flex items-center justify-center gap-2 py-20 text-sm text-slate-500"><Loader2 className="h-5 w-5 animate-spin" />加载中...</div>
          : error ? <p className="py-20 text-center text-sm text-red-600">{error}</p>
          : !data?.call_count ? <p className="py-20 text-center text-sm text-slate-500">暂无 LLM 调用日志</p>
          : <>
            {scope && <div className="mx-5 grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-slate-200 bg-slate-200 sm:grid-cols-5">
              {[
                ['总 Token', scope.total_tokens],
                ['输入 Token', scope.input_tokens],
                ['输出 Token', scope.output_tokens],
                ['调用次数', scope.call_count],
                ['未计量', scope.missing_usage_count],
              ].map(([label, value]) => <div key={label} className="bg-slate-50 px-3 py-2.5">
                <div className="text-[11px] text-slate-500">{label}</div>
                <div className={'mt-0.5 text-base font-semibold tabular-nums ' + (label === '未计量' && value ? 'text-amber-700' : 'text-slate-900')}>{number(Number(value))}</div>
              </div>)}
            </div>}

            <div className="flex items-center justify-between gap-3 px-5 py-3">
              <span className="text-sm font-medium text-slate-800">{levelName} 明细 <span className="ml-1 font-normal text-slate-400">{rows.length}</span></span>
              <label className="flex w-52 items-center gap-2 rounded-lg border border-slate-200 px-2.5 py-1.5 text-sm focus-within:border-blue-400">
                <Search className="h-4 w-4 shrink-0 text-slate-400" />
                <input value={query} onChange={event => setQuery(event.target.value)} placeholder={'搜索' + levelName} aria-label={'搜索' + levelName} className="min-w-0 flex-1 bg-transparent outline-none" />
              </label>
            </div>

            <div className="min-h-0 flex-1 overflow-auto px-5">
              <table className="w-full min-w-[600px] table-fixed border-separate border-spacing-0 text-sm">
                <colgroup><col style={{ width: '31%' }} /><col style={{ width: '16%' }} /><col style={{ width: '16%' }} /><col style={{ width: '17%' }} /><col style={{ width: '9%' }} /><col style={{ width: '11%' }} /></colgroup>
                <thead className="sticky top-0 z-10 bg-slate-50 text-xs font-medium text-slate-500">
                  <tr><th scope="col" className="rounded-l-lg px-3 py-2 text-left">{levelName}</th><th scope="col" className="px-3 py-2 text-right">输入</th><th scope="col" className="px-3 py-2 text-right">输出</th><th scope="col" className="px-3 py-2 text-right">总 Token</th><th scope="col" className="px-3 py-2 text-right">调用</th><th scope="col" title="供应商未返回可确定的总 Token 数" className="rounded-r-lg px-3 py-2 text-right">未计量</th></tr>
                </thead>
                <tbody>
                  {visibleRows.map(item => <tr key={item.id ?? 'unassigned'} className="group hover:bg-slate-50">
                    <td className="border-b border-slate-100 px-3 py-2.5">
                      {level === 'shots' ? <span className="block truncate text-slate-700" title={item.label}>{item.label}</span> :
                        <button type="button" onClick={() => { if (level === 'novels') setNovelId(item.id); else setChapterId(item.id); setQuery(''); }} className="flex w-full items-center justify-between gap-2 text-left font-medium text-slate-800 hover:text-blue-600">
                          <span className="truncate" title={item.label}>{item.label}</span><ArrowRight className="h-3.5 w-3.5 shrink-0 text-slate-400 group-hover:text-blue-500" />
                        </button>}
                    </td>
                    <UsageCell value={item.input_tokens} /><UsageCell value={item.output_tokens} /><UsageCell value={item.total_tokens} emphasis /><UsageCell value={item.call_count} /><UsageCell value={item.missing_usage_count} warning />
                  </tr>)}
                </tbody>
              </table>
              {visibleRows.length === 0 && <p className="py-10 text-center text-sm text-slate-500">没有匹配的{levelName}</p>}
            </div>
            <p className="border-t border-slate-100 px-5 py-3 text-xs leading-5 text-slate-500">数据来自供应商实际返回的 Token。“未归属”表示日志缺少对应关联；“未计量”表示供应商未返回可确定的总数。仅返回总数时，输入与输出可能显示为 0。</p>
          </>}
      </div>
    </div>
  );
}
