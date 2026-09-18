import {useEffect,useRef,useState} from 'react';
import {chapterShotSplitsApi,type ChapterCompletion,type CompletionReadiness,type SplitState} from '../../../api/chapterShotSplits';
import {assetStatusLabel} from '../../../utils/assetTerminology';
import {ChapterGovernancePanel} from './ChapterGovernancePanel';
import {useChapterGenerateStore} from '../stores';

export function ShotSourcePanel({novelId,chapterId,revision,onGate}:{novelId:string;chapterId:string;revision:string;onGate?:(ready:boolean)=>void}) {
  const [state,setState]=useState<SplitState|null>(null),[error,setError]=useState(''),[history,setHistory]=useState<{id:string;status:string;taskId:string}[]>([]),[detail,setDetail]=useState<unknown>(null);
  const [completionReadiness,setCompletionReadiness]=useState<CompletionReadiness|null>(null),[completion,setCompletion]=useState<ChapterCompletion|null>(null),[actionMessage,setActionMessage]=useState('');
  const requestId=useRef(0);
  const load=async()=>{const id=++requestId.current;try {
    const r=await chapterShotSplitsApi.state(novelId,chapterId);
    if(id!==requestId.current)return;
    if(r.success&&r.data){setState(r.data);setError('');onGate?.(r.data.canSplit);
      useChapterGenerateStore.setState(previous=>({tabProgress:r.data!.phase5Ready?{...previous.tabProgress,0:true}:{}}));
      const [readinessResult,completionResult]=await Promise.all([chapterShotSplitsApi.completionReadiness(novelId,chapterId),chapterShotSplitsApi.completion(novelId,chapterId)]);
      setCompletionReadiness(readinessResult.data||null);setCompletion(completionResult.data||null);
    }else {setError(String(r.message));onGate?.(false);}
  }catch{if(id===requestId.current){setError('读取分镜来源失败');onGate?.(false);}}};
  useEffect(()=>{void load();},[novelId,chapterId,revision]);
  useEffect(()=>{if(state?.runStatus!=='RUNNING')return;const id=window.setInterval(()=>void load(),5000);return()=>window.clearInterval(id);},[state?.runStatus,novelId,chapterId]);
  return <><ChapterGovernancePanel novelId={novelId} chapterId={chapterId}/><details className="border rounded-lg p-3 bg-white mb-3 min-w-0 flex-shrink-0" open>
    <summary className="font-medium cursor-pointer">本章分镜资产 · 分镜来源 {state?.phase5Ready?'已就绪':assetStatusLabel(state?.runStatus)}</summary>
    <div className="space-y-2 mt-2 text-sm max-h-72 overflow-y-auto min-w-0">
      <p>白名单仅来自本章正式 Binding；原文按 Unicode code point、[start,end) 精确定位。正式编辑保存新Revision；未记录的数据漂移仍被阻断。</p>
      <p className="text-xs text-gray-600">Treatment覆盖仅验证来源、处理意图及事件关联，不能证明画面语义质量。缺合同的旧数据需显式重建。</p>
      {error&&<p role="alert" className="text-red-700 break-all">{error}</p>}
      {actionMessage&&<p className="text-blue-700 break-all">{actionMessage}</p>}
      {!!state?.splitBlocker&&<p className="text-amber-700 break-all">{typeof state.splitBlocker==='string'?state.splitBlocker:JSON.stringify(state.splitBlocker)}</p>}
      {state?.scope&&Object.entries(state.scope).map(([kind,group])=><div key={kind} className="break-all"><strong>{kind}</strong>：{group.bindings.map(b=>`${b.name} (${b.assetId})`).join('；')||(group.emptyConfirmed?'已确认空集合':'未就绪')}</div>)}
      {!!state?.issues.length&&<pre className="whitespace-pre-wrap break-all text-amber-700">{JSON.stringify(state.issues,null,2)}</pre>}
      {state?.shots.map(row=><details key={row.shotId} className={`border rounded p-2 ${row.completionDisposition==='DEGRADED_NARRATION_CARD'?'border-amber-400 bg-amber-50':''}`}><summary>Shot {row.index} · {row.completionDisposition==='DEGRADED_NARRATION_CARD'?'DEGRADED · NARRATION_CARD':assetStatusLabel(row.status)} {row.source?`[${row.source.sourceStart}, ${row.source.sourceEnd})`:''}</summary>
        <p className="text-xs break-all">{row.shotId}</p>{!!row.issue&&<p className="text-amber-700 break-all">{JSON.stringify(row.issue)}</p>}
        {row.completionDisposition==='DEGRADED_NARRATION_CARD'&&<div className="flex flex-wrap gap-2 my-2"><button className="btn-secondary text-xs" onClick={async()=>{const response=await chapterShotSplitsApi.prepareNarrationCardAudio(novelId,chapterId,row.shotId);setActionMessage(response.success?'正式旁白准备任务已提交':String(response.message));void load();}}>准备 exact-source 旁白</button><button className="btn-secondary text-xs" onClick={async()=>{const response=await chapterShotSplitsApi.renderNarrationCard(novelId,chapterId,row.shotId);setActionMessage(response.success?'中性卡片渲染任务已提交':String(response.message));void load();}}>渲染中性卡片</button></div>}
        <button className="btn-secondary text-xs my-1" onClick={async()=>{const response=await chapterShotSplitsApi.validateTreatments(novelId,chapterId,row.shotId);if(response.data)setDetail(response.data);}}>只读检查原文处理覆盖</button>
        {row.source&&<><p className="text-xs break-all">Run：{row.source.splitRunId} · source hash：{row.source.sourceHash}</p>
          <p className="text-xs font-medium mt-1">{row.source.sourceContract?'连续归属':'原文证据'} · {row.source.sourceContractVersion||'legacy-v1'}</p>
          {(row.source.sourceContract?[row.source.sourceContract.ownership_range]:row.source.sourceRanges).map((r,i)=><p key={i} className="whitespace-pre-wrap bg-gray-50 p-2 mt-1">[{r.start}, {r.end}) {r.text}</p>)}
          {!!row.source.sourceContract&&<><p className="text-xs font-medium mt-2">引用证据</p>
            {row.source.sourceContract.citation_ranges.map((r,i)=><p key={i} className="whitespace-pre-wrap border-l-2 border-blue-200 pl-2 mt-1">[{r.start}, {r.end}) {r.text}</p>)}</>}
          <pre className="whitespace-pre-wrap break-all text-xs">{JSON.stringify(row.source.assetBindings,null,2)}</pre></>}
      </details>)}
      <div className="border rounded p-2 bg-slate-50"><p className="font-medium">Chapter Completion Manifest</p>
        <p className="text-xs">NORMAL {completionReadiness?.counts.normal??0} · DEGRADED {completionReadiness?.counts.degraded??0} · TOTAL {completionReadiness?.counts.total??0}</p>
        {completionReadiness?.entries.map(entry=><p key={entry.shotId} className={entry.ready?'text-xs':'text-xs text-amber-700'}>#{entry.shotIndex} {entry.completionDisposition} {entry.sourceRange?`[${entry.sourceRange[0]}, ${entry.sourceRange[1]})`:''} · {entry.ready?'READY':String(entry.blocker)}</p>)}
        {!!completionReadiness?.blocker&&<p className="text-xs text-amber-700 break-all">{String(completionReadiness.blocker)}</p>}
        <button className="btn-primary text-xs mt-2" disabled={!completionReadiness?.ready||!completionReadiness.manifestHash} onClick={async()=>{if(!completionReadiness?.manifestHash)return;const response=await chapterShotSplitsApi.complete(novelId,chapterId,completionReadiness.manifestHash);setActionMessage(response.success?'章回完整交付任务已提交':String(response.message));void load();}}>按封存 Manifest 完成章回</button>
        {completion&&<p className="text-xs mt-2 text-amber-800">{completion.outcome} · Manifest {completion.manifestHash} · Normal {completion.normalCount} · Degraded {completion.degradedCount}</p>}
      </div>
      <div className="flex flex-wrap gap-2"><button className="btn-secondary text-xs" onClick={()=>void load()}>重新检查分镜来源</button>
      <a className="btn-secondary text-xs" href={`/asset-debug?novel_id=${novelId}&chapter_id=${chapterId}`}>章回来源追踪</a>
      <button className="btn-secondary text-xs" onClick={async()=>{const r=await chapterShotSplitsApi.runs(novelId,chapterId);if(r.data)setHistory(r.data);}}>拆分历史与实际输入</button></div>
      {history.map((run,index)=><div key={run.id} className="flex flex-wrap gap-2 items-center"><button className="text-blue-700 text-xs break-all text-left" onClick={async()=>{const r=await chapterShotSplitsApi.detail(novelId,chapterId,run.id);if(r.data)setDetail(r.data);}}>{run.status} · {run.id}</button>{index===0&&run.status==='NEEDS_REVIEW'&&<button className="btn-secondary text-xs" onClick={async()=>{const response=await chapterShotSplitsApi.admitNarrationCard(novelId,chapterId,run.id);setActionMessage(response.success?'R-CD1 narration-card child 已发布':String(response.message));void load();}}>尝试受控降级为 NARRATION_CARD</button>}</div>)}
      {detail!=null&&<pre className="whitespace-pre-wrap break-all text-xs max-h-72 overflow-y-auto">{JSON.stringify(detail,null,2)}</pre>}
    </div>
  </details></>;
}
