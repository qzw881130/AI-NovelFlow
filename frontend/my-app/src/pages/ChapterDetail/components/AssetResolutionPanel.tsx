import { useCallback, useEffect, useRef, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { assetResolutionsApi, type BindingState, type IdentityCatalog, type IdentityDecision, type ResolutionRun } from '../../../api/assetResolutions';
import type { AssetKind } from '../../../api/chapterAssets';
import { AppearanceTimelinePanel } from './AppearanceTimelinePanel';

const LABEL: Record<AssetKind, string> = { characters: '角色', scenes: '场景', props: '道具' };
const STATUS: Record<string,string> = { SUCCEEDED:'已归并', NEEDS_REVIEW:'存在歧义', RUNNING:'归并中', FAILED:'执行失败', STALE:'来源已变化', SUPERSEDED:'已被新记录替代', NOT_RESOLVED:'未归并' };

function ReviewCard({ review, catalog, disabled, submit }: {review: IdentityDecision; catalog: IdentityCatalog; disabled: boolean;
  submit: (id: string, action: 'MATCH'|'CREATE'|'IGNORE', assetId: string, name: string, confirmType: boolean) => Promise<void>}) {
  const [assetId, setAssetId] = useState('');
  const [name, setName] = useState(review.candidate.name);
  const [confirmType, setConfirmType] = useState(false);
  const choices = catalog.assets[review.assetType].filter(asset => !asset.is_narrator && (review.assetType !== 'characters' || !asset.entity_type || asset.entity_type === review.candidate.entity_type));
  const chosen = choices.find(asset => asset.asset_id === assetId);
  const needsType = review.assetType === 'characters' && chosen && !chosen.entity_type;
  const generic = review.candidate.entity_type === 'GROUP' && catalog.genericGroups.includes(name.trim());
  return <article className="space-y-3 rounded-lg border border-amber-200 bg-amber-50 p-3 min-w-0">
    <h4 className="font-semibold">{review.candidate.name} · {review.candidate.entity_type || LABEL[review.assetType]} · {review.candidate.chapter_presence?.role}</h4>
    <p className="text-sm">{review.reason}（置信度 {review.confidence}）</p>
    {review.candidate.source_evidence.map((quote,index) => <blockquote key={index} className="border-l-2 border-amber-400 pl-2 text-sm break-words">{quote.text}</blockquote>)}
    <div className="space-y-1 text-sm">
      <p className="font-medium">检索候选（Top {review.shortlist.length}）</p>
      {review.shortlist.map(asset => <div key={asset.asset_id} className="rounded bg-white p-2 break-words">
        {asset.canonical_name} · {asset.entity_type || (review.assetType === 'characters' ? '旧类型待确认' : LABEL[review.assetType])}
        <span className="ml-2">匹配置信度 {review.candidateMatches.find(item => item.asset_id === asset.asset_id)?.confidence ?? '—'}</span>
        <p className="text-xs text-gray-600">{asset.description}</p><p className="break-all font-mono text-xs">{asset.asset_id}</p>
      </div>)}
    </div>
    <label className="block text-sm">匹配已有资产
      <select aria-label={`为${review.candidate.name}选择已有资产`} className="input-field mt-1" value={assetId} disabled={disabled}
        onChange={event => {setAssetId(event.target.value);setConfirmType(false);}}>
        <option value="">请选择（同小说、兼容类型）</option>
        {choices.map(asset => <option key={asset.asset_id} value={asset.asset_id}>{asset.canonical_name} · {asset.asset_id}</option>)}
      </select>
    </label>
    {needsType && <label className="flex gap-2 text-sm"><input type="checkbox" checked={confirmType} disabled={disabled} onChange={event => setConfirmType(event.target.checked)} />确认该旧角色类型为 {review.candidate.entity_type}（保存身份元数据）</label>}
    <button className="btn-secondary" disabled={disabled || !assetId || Boolean(needsType && !confirmType)} onClick={() => void submit(review.id,'MATCH',assetId,'',confirmType)}>匹配已有</button>
    <label className="block text-sm">新资产规范名
      <input aria-label={`为${review.candidate.name}输入规范名`} className="input-field mt-1" value={name} disabled={disabled} onChange={event => setName(event.target.value)} />
    </label>
    {generic && <p className="text-sm text-amber-800">泛GROUP必须补充地点或归属，例如“安喜县衙外百姓”。</p>}
    <div className="flex flex-wrap gap-2">
      <button className="btn-primary" disabled={disabled || !name.trim() || generic} onClick={() => void submit(review.id,'CREATE','',name.trim(),false)}>创建新资产</button>
      <button className="btn-secondary" disabled={disabled} onClick={() => void submit(review.id,'IGNORE','','',false)}>忽略此候选</button>
    </div>
  </article>;
}

export function AssetResolutionPanel({ novelId, chapterId, revision, disabled }: {novelId: string; chapterId: string; revision: string; disabled: boolean}) {
  const [runs,setRuns] = useState<ResolutionRun[]>([]);
  const [bindings,setBindings] = useState<BindingState|null>(null);
  const [catalog,setCatalog] = useState<IdentityCatalog|null>(null);
  const [kind,setKind] = useState<AssetKind|'all'>('all');
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  const sequence=useRef(0), submitting=useRef(false);
  const load=useCallback(async()=>{
    const ticket=++sequence.current;
    try {
      const [r,b,c]=await Promise.all([assetResolutionsApi.list(novelId,chapterId),assetResolutionsApi.bindings(novelId,chapterId),assetResolutionsApi.catalog(novelId)]);
      if(ticket!==sequence.current)return;
      if(!r.success||!b.success||!c.success)throw new Error(String(r.message||b.message||c.message||'读取身份归并失败'));
      setRuns(r.data||[]);setBindings(b.data||null);setCatalog(c.data||null);
    } catch(cause){if(ticket===sequence.current)setError(cause instanceof Error?cause.message:'读取失败');}
  },[novelId,chapterId]);
  useEffect(()=>{void load();return()=>{sequence.current++;};},[load,revision]);
  const running=busy||runs.some(run=>run.effectiveStatus==='RUNNING');
  useEffect(()=>{if(!running)return;const timer=window.setInterval(()=>void load(),3000);return()=>window.clearInterval(timer);},[running,load]);
  const resolve=async()=>{
    if(submitting.current||disabled||running)return;submitting.current=true;setBusy(true);setError('');
    try{const r=await assetResolutionsApi.resolve(novelId,chapterId,kind==='all'?['characters','scenes','props']:[kind]);
      if(!r.success&&r.data?.status!=='NEEDS_REVIEW')setError(String(r.message||'归并未通过，请检查执行记录'));await load();
    }catch(cause){setError(cause instanceof Error?cause.message:'归并失败');}finally{submitting.current=false;setBusy(false);}
  };
  const submit=async(id:string,action:'MATCH'|'CREATE'|'IGNORE',assetId:string,name:string,confirmType:boolean)=>{
    if(submitting.current||!catalog||disabled)return;submitting.current=true;setBusy(true);setError('');
    try{const r=await assetResolutionsApi.review(novelId,chapterId,id,{action,asset_id:assetId||undefined,canonical_name:name||undefined,
      confirm_legacy_type:confirmType,expected_catalog_hash:catalog.hash});if(!r.success)setError(String(r.message||'处理失败'));await load();
    }catch(cause){setError(cause instanceof Error?cause.message:'处理失败');}finally{submitting.current=false;setBusy(false);}
  };
  const reviews=runs.flatMap(run=>run.reviews);
  return <section className="space-y-4 border-t pt-5 min-w-0" aria-label="章回身份归并">
    <h3 className="text-lg font-semibold">身份归并与正式章回关联</h3>
    <p className="text-sm text-gray-600">解析成功后自动执行 Resolver；已有候选可补执行。精确名与强别名自动复用，只有 AMBIGUOUS 项需要人工处理。</p>
    <div className="flex flex-wrap gap-2">
      <select aria-label="归并素材类型" className="input-field w-auto" value={kind} disabled={running||disabled} onChange={event=>setKind(event.target.value as AssetKind|'all')}>
        <option value="all">全部素材</option>{(Object.keys(LABEL) as AssetKind[]).map(k=><option key={k} value={k}>{LABEL[k]}</option>)}
      </select>
      <button className="btn-primary" disabled={running||disabled} onClick={()=>void resolve()}>{running&&<Loader2 className="mr-1 h-4 w-4 animate-spin"/>}归并当前候选</button>
      <button className="btn-secondary" onClick={()=>void load()}>刷新关联</button>
    </div>
    {error&&<p role="alert" className="text-sm text-red-700 break-words">{error}</p>}
    {bindings&&<div className="space-y-3">
      <p className={`rounded p-3 text-sm ${bindings.phase2Ready?'bg-green-50 text-green-800':'bg-amber-50 text-amber-800'}`}>{bindings.phase2Ready?'Phase 2 已就绪：正式章回关联已建立':'Phase 2 尚未就绪：请完成各类归并或处理歧义'}</p>
      {(Object.keys(LABEL) as AssetKind[]).map(k=><div key={k} className="rounded border p-3 text-sm space-y-1">
        <h4 className="font-medium">{LABEL[k]} · {STATUS[bindings.assets[k].status]||bindings.assets[k].status}</h4>
        {bindings.assets[k].emptyConfirmed&&<p>已确认本章无此类正式成员</p>}
        {bindings.assets[k].bindings.map(b=><div key={b.id} className="break-all">{b.name} · {b.entityType} · {b.method}<p className="font-mono text-xs text-gray-500">Asset ID: {b.assetId}<br/>Binding ID: {b.id}</p></div>)}
      </div>)}
    </div>}
    {reviews.length>0&&catalog&&<div className="space-y-3"><h4 className="font-semibold">待处理歧义（{reviews.length}）</h4>{reviews.map(review=><ReviewCard key={review.id} review={review} catalog={catalog} disabled={running||disabled} submit={submit}/>)}</div>}
    {runs.map(run=><details key={run.id} className="rounded border p-3 text-sm">
      <summary className="cursor-pointer break-all">{STATUS[run.effectiveStatus]||run.effectiveStatus} · Resolution {run.id}</summary>
      <p className="my-2 break-all text-xs">Task ID: {run.taskId}</p>
      {run.decisions.map(d=><p key={d.id} className="my-1 break-words">{d.candidate.name} → {d.resolution} / {d.matchType} · {d.status} · LLM {d.llmUsed?'是':'否'} · {d.reason}</p>)}
      <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(run,null,2)}</pre>
    </details>)}
    <AppearanceTimelinePanel novelId={novelId} chapterId={chapterId}
      revision={`${revision}:${bindings?.assets.characters.runId}:${bindings?.assets.characters.status}`}
      disabled={disabled||busy||bindings?.assets.characters.status!=='SUCCEEDED'}/>
  </section>;
}
