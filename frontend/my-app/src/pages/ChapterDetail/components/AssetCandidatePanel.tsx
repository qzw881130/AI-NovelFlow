import { useCallback, useEffect, useRef, useState } from 'react';
import { Loader2, RefreshCw, Sparkles } from 'lucide-react';
import { chapterAssetsApi, type AssetKind, type AssetParseRun } from '../../../api/chapterAssets';
import { AssetResolutionPanel } from './AssetResolutionPanel';

const LABELS: Record<AssetKind, string> = { characters: '角色', scenes: '场景', props: '道具' };
const STATUS: Record<string, string> = {
  RUNNING: '正在解析', SUCCEEDED: '候选校验已通过', NEEDS_REVIEW: '候选待检查',
  FAILED: '解析失败', STALE: '原文已变化 · 请重新解析', EXPIRED: '解析超时 · 请重新解析', INTERRUPTED: '解析已中断',
  SUPERSEDED: '已有更新的解析记录 · 仅供查看',
  PARSER_OUTDATED: '解析器校验规则已升级 · 请重新解析',
};

export function AssetCandidatePanel({ novelId, chapterId, sourceVersion, dirty }: {
  novelId: string; chapterId: string; sourceVersion: string; dirty: boolean;
}) {
  const [runs, setRuns] = useState<AssetParseRun[]>([]);
  const [detail, setDetail] = useState<AssetParseRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const sequence = useRef(0);
  const submitting = useRef(false);

  const load = useCallback(async (runId?: string) => {
    const ticket = ++sequence.current;
    try {
      const response = await chapterAssetsApi.list(novelId, chapterId);
      if (ticket !== sequence.current) return;
      if (!response.success || !response.data) throw new Error(String(response.message || '读取解析历史失败'));
      setRuns(response.data);
      const id = runId || response.data[0]?.id;
      if (!id) { setDetail(null); return; }
      const result = await chapterAssetsApi.get(novelId, chapterId, id);
      if (ticket !== sequence.current) return;
      if (!result.success || !result.data) throw new Error(String(result.message || '读取候选失败'));
      setDetail(result.data);
    } catch (cause) {
      if (ticket === sequence.current) setError(cause instanceof Error ? cause.message : '读取失败');
    }
  }, [novelId, chapterId]);

  useEffect(() => { void load(); return () => { sequence.current++; }; }, [load, sourceVersion]);
  const running = busy || runs.some(run => run.effectiveStatus === 'RUNNING');
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => { void load(); }, 3000);
    return () => window.clearInterval(timer);
  }, [running, load]);

  const parse = async (kinds: AssetKind[]) => {
    if (submitting.current || running || dirty) return;
    submitting.current = true;
    setBusy(true);
    setError('');
    try {
      const response = await chapterAssetsApi.parse(novelId, chapterId, kinds);
      if (!response.success) setError(String(response.message || '解析未通过，请检查记录'));
      await load(response.data?.id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '解析请求失败');
      await load();
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  };

  return (
    <section id="chapter-asset-candidates" className="card space-y-4 min-w-0">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold">章回素材候选 · V3.1.2</h2>
        <button type="button" className="btn-secondary text-sm" onClick={() => void load()}>
          <RefreshCw className="mr-1 h-4 w-4" />刷新记录
        </button>
      </div>
      <p className="text-sm text-gray-600">解析已保存的完整章回，保存候选和原文证据，再自动执行身份归并；正式关联及歧义项见下方。</p>
      {dirty && <p role="status" className="text-sm text-amber-700">标题或正文尚未保存，请先保存再解析。</p>}
      <div className="flex flex-wrap gap-2">
        <button type="button" disabled={running || dirty} onClick={() => void parse(['characters', 'scenes', 'props'])} className="btn-primary">
          {running ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Sparkles className="mr-1 h-4 w-4" />}解析全部素材
        </button>
        {(Object.keys(LABELS) as AssetKind[]).map(kind => (
          <button type="button" key={kind} disabled={running || dirty} className="btn-secondary" onClick={() => void parse([kind])}>仅解析{LABELS[kind]}</button>
        ))}
      </div>
      {error && <p role="alert" className="break-words text-sm text-red-700">{error}</p>}
      {runs.length === 0 ? <p className="text-sm text-gray-500">尚无新链解析记录。旧 parsedData 或空数组不代表已确认无素材。</p> : (
        <label className="block text-sm">解析历史（每次重跑保留独立记录）
          <select className="input-field mt-1" value={detail?.id || ''} onChange={event => void load(event.target.value)}>
            {runs.map(run => <option key={run.id} value={run.id}>{run.createdAt} · {run.kinds.map(kind => LABELS[kind]).join('/')} · {STATUS[run.effectiveStatus] || run.effectiveStatus}</option>)}
          </select>
        </label>
      )}
      {detail && <div className="space-y-3">
        <p className={`rounded-lg p-3 text-sm ${detail.phase1Ready ? 'bg-green-50 text-green-800' : 'bg-amber-50 text-amber-800'}`}>
          {STATUS[detail.effectiveStatus] || detail.effectiveStatus} · {detail.candidateCount} 项候选
        </p>
        <div className="break-all text-xs text-gray-500">Run ID: {detail.id}<br />Task ID: {detail.taskId}<br />原文版本: {detail.sourceHash}</div>
        {detail.issues.length > 0 && <pre className="whitespace-pre-wrap break-all rounded bg-red-50 p-3 text-xs text-red-800">{JSON.stringify(detail.issues, null, 2)}</pre>}
        {detail.phase1Ready && detail.candidateCount === 0 && <p className="text-sm">本次请求的素材类型已成功解析，明确确认候选为空。</p>}
        {detail.candidates?.map(candidate => <article key={candidate.id} className="min-w-0 rounded-lg border border-gray-200 p-3 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-semibold">{candidate.name}</h3>
            <span className="text-xs text-gray-500">{LABELS[candidate.assetType]} {candidate.entity_type} {candidate.entity_type === 'GROUP' ? `规模：${candidate.group_size_hint ?? '不确定'}` : ''} {candidate.chapter_presence?.role}</span>
            {candidate.validationStatus === 'NEEDS_REVIEW' && <span className="text-xs text-amber-700">候选待检查</span>}
          </div>
          <p className="break-words text-sm text-gray-700">{candidate.description}</p>
          <p className="break-words text-sm text-gray-600">{candidate.appearance || candidate.setting}</p>
          <div className="text-sm">原文依据：{candidate.source_evidence.map((quote, index) => <blockquote key={index} className="my-1 border-l-2 border-blue-200 pl-2 break-words">{quote.text}</blockquote>)}</div>
          {candidate.chapter_appearances && <div className="text-sm">
            <p className="font-medium">章内持续外观变化：{candidate.chapter_appearances.length === 0 ? '[]（未发现新变化；不代表已解析继承或BASE）' : ''}</p>
            {candidate.chapter_appearances.map(change => <div key={change.event_key} className="mt-2 rounded bg-gray-50 p-2">
              {change.event_key} · {change.change_type}<p>{change.appearance_description || '变化尚不确定'}</p>
              {change.source_evidence.map((quote, index) => <blockquote key={index}>{quote.text}</blockquote>)}
            </div>)}
          </div>}
          {candidate.issues.length > 0 && <pre className="whitespace-pre-wrap break-all text-xs text-red-700">{JSON.stringify(candidate.issues, null, 2)}</pre>}
          <p className="break-all font-mono text-xs text-gray-400">Candidate ID: {candidate.id}</p>
        </article>)}
        <details className="text-sm"><summary className="cursor-pointer">原文快照、实际Prompt版本与LLM原始响应</summary>
          <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap break-all rounded bg-gray-50 p-3 text-xs">{JSON.stringify({ source: detail.source, calls: detail.calls }, null, 2)}</pre>
        </details>
      </div>}
      <AssetResolutionPanel novelId={novelId} chapterId={chapterId} revision={`${detail?.id}:${detail?.effectiveStatus}:${busy}`} disabled={dirty||busy}/>
    </section>
  );
}
