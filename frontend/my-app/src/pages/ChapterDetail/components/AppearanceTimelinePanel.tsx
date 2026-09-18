import { useCallback, useEffect, useRef, useState } from 'react';
import { appearanceTimelinesApi as api, type EventSource, type LocatedEvent, type TimelineRun, type AppearanceSelection } from '../../../api/appearanceTimelines';

const STATUS:Record<string,string>={SUCCEEDED:'逻辑时间线已就绪',NEEDS_REVIEW:'外观事件/继承待检查',FAILED:'构建失败',RUNNING:'构建中',STALE:'来源已变化，请重建',SUPERSEDED:'历史版本'};
const IMAGE:Record<string,string>={NEEDS_GENERATION:'外观图待生成',GENERATING:'外观图生成中',READY:'外观图已就绪',FAILED:'外观图生成失败',REJECTED:'外观图已拒绝',BASE_REFERENCE_PRESENT:'基础参考图已登记'};
const selectionText=(s:AppearanceSelection)=>s.kind==='BASE'?'BASE（已核验无前置变化）':s.kind==='UNRESOLVED'?`阻断：${s.reason}`:`${s.reason==='PREVIOUS_ACTIVE'?'继承上一生效外观':'本章外观事件'} · ${s.appearanceId}`;

function EventReview({item,source,busy,onSubmit}:{item:LocatedEvent;source:EventSource;busy:boolean;onSubmit:(id:string,data:any)=>Promise<void>}) {
  const [start,setStart]=useState(item.source_start??0),[end,setEnd]=useState(item.source_end??0);
  const [description,setDescription]=useState(item.proposal.appearance_description||'');
  const [reason,setReason]=useState('');
  const text=Array.from(source.content).slice(start,end).join('');
  const valid=Number.isInteger(start)&&Number.isInteger(end)&&start>=0&&end>start&&end<=Array.from(source.content).length;
  const submit=(action:'LOCATE'|'CONFIRM_NEW'|'IGNORE')=>onSubmit(item.proposal.id,{
    action,expected_source_hash:source.sourceHash,expected_proposal_hash:item.proposal_hash,reason,
    ...(action==='IGNORE'?{}:{source_start:start,source_end:end,evidence_text:text}),
    ...(action==='CONFIRM_NEW'?{appearance_description:description}:{}),
  });
  return <details className="rounded border border-amber-200 p-3" open={item.status==='NEEDS_REVIEW'}>
    <summary className="cursor-pointer text-sm font-medium">{item.proposal.event_key} · {item.proposal.change_type} · {item.status} · 人工定位/确认</summary>
    <div className="mt-3 space-y-3 text-sm">
      <p className="break-all text-xs">Event ID: {item.proposal.id}<br/>Character ID: {item.proposal.character_id}</p>
      <p>{item.proposal.appearance_description||'原提议未确定具体外观'}</p>
      {item.proposal.source_evidence.map((q,index)=><blockquote key={index} className="border-l-2 pl-2">{q.text}</blockquote>)}
      {item.locationProof?.code&&<p className="text-amber-800">{item.locationProof.code}</p>}
      <label className="block">在原文中选中对应变化短句（按Unicode码点计数，非UTF-16代码单元）
        <textarea readOnly aria-label={`事件${item.proposal.event_key}原文`} value={source.content} rows={5} className="input-field mt-1 font-mono text-xs"
          onSelect={event => {
            const el = event.currentTarget;
            if (el.selectionStart !== el.selectionEnd) {
              setStart(Array.from(el.value.slice(0, el.selectionStart)).length);
              setEnd(Array.from(el.value.slice(0, el.selectionEnd)).length);
            }
          }}/>
      </label>
      <div className="flex flex-wrap gap-2">{item.locationProof?.candidate_spans?.map(([a,b])=><button type="button" key={`${a}-${b}`} className="btn-secondary text-xs" onClick={()=>{setStart(a);setEnd(b);}}>选择 [{a}, {b})</button>)}</div>
      <div className="grid grid-cols-2 gap-2">
        <label>起点<input aria-label="外观事件起点" type="number" min={0} className="input-field" value={start} onChange={e=>setStart(Number(e.target.value))}/></label>
        <label>终点（不含）<input aria-label="外观事件终点" type="number" min={0} className="input-field" value={end} onChange={e=>setEnd(Number(e.target.value))}/></label>
      </div>
      <p className="break-words rounded bg-gray-50 p-2">所选原文：{text||'尚未选中'}</p>
      <label className="block">持续外观描述<input aria-label="确认的外观描述" className="input-field mt-1" value={description} onChange={e=>setDescription(e.target.value)}/></label>
      <label className="block">确认依据<input aria-label="外观确认依据" className="input-field mt-1" value={reason} onChange={e=>setReason(e.target.value)}/></label>
      <div className="flex flex-wrap gap-2">
        <button className="btn-secondary" disabled={busy||!valid||!reason.trim()} onClick={()=>void submit('LOCATE')}>仅确认位置</button>
        <button className="btn-primary" disabled={busy||!valid||!reason.trim()||!description.trim()} onClick={()=>void submit('CONFIRM_NEW')}>确认持续换装</button>
        <button className="btn-secondary" disabled={busy||!reason.trim()} onClick={()=>void submit('IGNORE')}>确认无持续变化</button>
      </div>
      <p className="text-xs text-gray-500">仅确认位置保留原模型change_type；UNCERTAIN仍需确认换装或确认无变化。操作保留审计记录，后续受影响时间线需重建。</p>
    </div>
  </details>;
}

export function AppearanceTimelinePanel({novelId,chapterId,revision,disabled}:{novelId:string;chapterId:string;revision:string;disabled:boolean}) {
  const [runs,setRuns]=useState<TimelineRun[]>([]),[detail,setDetail]=useState<TimelineRun|null>(null),[source,setSource]=useState<EventSource|null>(null);
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  const sequence=useRef(0),submitting=useRef(false);
  const load=useCallback(async(id?:string)=>{
    const ticket=++sequence.current;
    try{
      const [history,events]=await Promise.all([api.list(novelId,chapterId),api.events(novelId,chapterId)]);
      if(ticket!==sequence.current)return;
      if(history.success){setRuns(history.data||[]);const current=id||history.data?.[0]?.id;if(current){const r=await api.get(novelId,chapterId,current);if(ticket===sequence.current&&r.success)setDetail(r.data||null);}else setDetail(null);}
      if(ticket!==sequence.current)return;
      setSource(events.success?events.data||null:null);
      if(!history.success)setError(String(history.message||'读取时间线失败'));
    }catch(cause){if(ticket===sequence.current)setError(cause instanceof Error?cause.message:'读取失败');}
  },[novelId,chapterId]);
  useEffect(()=>{void load();return()=>{sequence.current++;};},[load,revision]);
  const build=async(through=false)=>{
    if(disabled||submitting.current)return;submitting.current=true;setBusy(true);setError('');
    try{const r=through?await api.rebuildThrough(novelId,chapterId):await api.build(novelId,chapterId);if(!r.success)setError(String(r.message||'时间线尚未通过，请查看定位或前置依赖问题'));await load();}
    catch(cause){setError(cause instanceof Error?cause.message:'构建失败');}finally{submitting.current=false;setBusy(false);}
  };
  const review=async(id:string,data:any)=>{
    if(disabled||submitting.current)return;submitting.current=true;setBusy(true);setError('');
    try{const r=await api.review(novelId,chapterId,id,data);if(!r.success)setError(String(r.message||'确认失败'));await load();}
    catch(cause){setError(cause instanceof Error?cause.message:'确认失败');}finally{submitting.current=false;setBusy(false);}
  };
  const target=detail?.result?.chapters.find(item=>item.chapterId===chapterId);
  return <section aria-label="外观事件与时间线" className="space-y-4 border-t pt-5 min-w-0">
    <h3 className="text-lg font-semibold">外观事件定位与时间线</h3>
    <p className="text-sm text-gray-600">只根据已确认角色关联与原文事件计算。BASE、上一生效外观与未知状态分开；缺图不会改变已生效的外观。位置为从0开始、终点不含的Unicode字符区间。</p>
    <div className="flex flex-wrap gap-2">
      <button className="btn-primary" disabled={busy||disabled} onClick={()=>void build()}>构建本章时间线</button>
      <button className="btn-secondary" disabled={busy||disabled} onClick={()=>void build(true)}>重建前置章回至本章</button>
      <button className="btn-secondary" onClick={()=>void load()}>刷新时间线</button>
    </div>
    {disabled&&<p className="text-sm text-amber-800">请先保存原文并完成本章角色归并。</p>}
    {error&&<p role="alert" className="break-words text-sm text-red-700">{error}</p>}
    {runs.length>0&&<label className="block text-sm">时间线历史<select aria-label="时间线历史" className="input-field mt-1" value={detail?.id||''} onChange={e=>void load(e.target.value)}>
      {runs.map(run=><option key={run.id} value={run.id}>{run.createdAt} · {STATUS[run.effectiveStatus]||run.effectiveStatus}</option>)}
    </select></label>}
    {detail&&<div className="space-y-3">
      <p className={`rounded p-3 text-sm ${detail.phase3Ready?'bg-green-50 text-green-800':'bg-amber-50 text-amber-800'}`}>{STATUS[detail.effectiveStatus]||detail.effectiveStatus}</p>
      <p className="break-all text-xs text-gray-500">Timeline ID: {detail.id}<br/>Task ID: {detail.taskId}<br/>依赖版本: {detail.inputHash}</p>
      {detail.issues.length>0&&<pre className="whitespace-pre-wrap break-all bg-red-50 p-2 text-xs">{JSON.stringify(detail.issues,null,2)}</pre>}
      {target?.characters.length===0&&<p className="text-sm">已验证本章无角色成员。</p>}
      {target?.characters.map(actor=><article key={actor.characterId} className="rounded border p-3 text-sm space-y-2">
        <h4 className="font-semibold">{actor.name} · {actor.logicalReady?'逻辑已解析':'需要检查'}</h4>
        <p className="break-all">章初：{selectionText(actor.entry)}</p>
        {actor.segments.map(segment=><div key={segment.start} className="rounded bg-gray-50 p-2 break-all">
          [{segment.start}, {segment.end}) · {selectionText(segment.selection)}
          <p className="text-xs text-gray-500">{IMAGE[segment.selection.imageStatus||'']||segment.selection.imageStatus}</p>
          {segment.selection.sourceChapterId&&<p className="text-xs">来源章回：{segment.selection.sourceChapterId}</p>}
          {segment.selection.sourceEventIds.length>0&&<p className="text-xs">来源事件：{segment.selection.sourceEventIds.join(', ')}</p>}
        </div>)}
        {actor.issues.length>0&&<pre className="whitespace-pre-wrap break-all text-xs text-amber-800">{JSON.stringify(actor.issues,null,2)}</pre>}
      </article>)}
      <details><summary className="cursor-pointer text-sm">前置章回覆盖、位置证明与冻结结果</summary><pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(detail,null,2)}</pre></details>
    </div>}
    {source&&source.events.length>0&&<div className="space-y-3"><h4 className="font-medium">本章外观事件（{source.events.length}）</h4>
      {source.events.map(item=><EventReview key={`${item.proposal.id}:${JSON.stringify(item.review)}`} item={item} source={source} busy={busy||disabled} onSubmit={review}/>)}
    </div>}
  </section>;
}
