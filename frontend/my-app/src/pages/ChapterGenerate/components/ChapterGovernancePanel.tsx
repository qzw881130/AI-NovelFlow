import {useEffect,useRef,useState} from 'react';
import {chapterGovernanceApi,type ChapterPipelineState} from '../../../api/chapterGovernance';
import {assetStatusLabel} from '../../../utils/assetTerminology';
import {useChapterGenerateStore} from '../stores';

const stages:Record<string,string>={CANDIDATES:'章回素材解析',CHAPTER_BINDINGS:'已有角色归一化与素材关联',BINDINGS:'本章资产关联',APPEARANCE_TIMELINE:'角色外观时间线',TIMELINE:'角色外观时间线',SHOT_SOURCE:'分镜拆分与来源',RSA:'分镜最终资产'};
export function ChapterGovernancePanel({novelId,chapterId}:{novelId:string;chapterId:string}) {
  const [state,setState]=useState<ChapterPipelineState|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[previous,setPrevious]=useState(false);
  const serial=useRef(0),seen=useRef<string|null>(null);
  const load=async()=>{
    const id=++serial.current;const r=await chapterGovernanceApi.state(novelId,chapterId);
    if(id!==serial.current)return;
    if(!r.success||!r.data)throw new Error(String(r.message||'章回状态读取失败'));
    setState(r.data);setError('');
    const run=r.data.rebuild;
    if(run&&!['PENDING','RUNNING'].includes(run.status)&&seen.current!==run.id){
      seen.current=run.id;
      await useChapterGenerateStore.getState().fetchShots(novelId,chapterId);
      void useChapterGenerateStore.getState().initChapterResources();
    }
  };
  useEffect(()=>{
    setState(null);seen.current=null;
    let stopped=false;let timer:ReturnType<typeof setTimeout>;
    const poll=async()=>{try{await load();}catch(e){if(!stopped)setError(e instanceof Error?e.message:'状态读取失败');}if(!stopped)timer=setTimeout(poll,6000);};
    void poll();return()=>{stopped=true;serial.current++;clearTimeout(timer);};
  },[novelId,chapterId]);
  const running=!!state?.rebuild&&['PENDING','RUNNING'].includes(state.rebuild.status);
  const submit=async(mode:'REBUILD'|'CONTINUE')=>{setBusy(true);setError('');try{
    const r=await chapterGovernanceApi.rebuild(novelId,chapterId,mode,previous);
    if(!r.success)throw new Error(String(r.message));await load();
  }catch(e){setError(e instanceof Error?e.message:'重建提交失败');}finally{setBusy(false);}};
  return <section aria-label="章回资产链状态" className="rounded-lg border bg-white p-3 mb-3 text-sm space-y-2 flex-shrink-0">
    <p className="font-medium">{state?.structuralReady?'✓ 分镜结构来源已就绪':state?.needsRebuild?'章回结构需要重建':state?.condition==='NOT_PARSED'?'新章待解析':'章回结构准备中'}</p>
    {state?.needsRebuild&&<p className="text-amber-700">{state.origin==='LEGACY'?'本章包含旧版派生结构。':'本章的原文、资产关联或分镜来源已变化。'}请显式重建；原角色、场景、道具、参考图与声音会保留。</p>}
    {state&&!state.structuralReady&&<p className="text-gray-600">待完成：{state.missingStages.map(s=>stages[s]||s).join(' → ')||'重建结果确认'}</p>}
    {error&&<p role="alert" className="text-red-700 break-all">{error}</p>}
    {state?.rebuild&&<div><p>最近重建：{assetStatusLabel(state.rebuild.status)}</p>{state.rebuild.error&&<p className="break-all text-amber-700">{state.rebuild.error}</p>}<details><summary className="cursor-pointer">重建阶段记录</summary><ol className="list-decimal pl-5">{state.rebuild.steps.map((s,i)=><li key={i}>{stages[s.stage]||s.stage} · {s.at}</li>)}</ol><a className="text-blue-700" href="/tasks">查看重建及子任务日志</a></details></div>}
    {state&&!state.structuralReady&&<><label className="flex items-center gap-2"><input type="checkbox" checked={previous} disabled={running||busy} onChange={e=>setPrevious(e.target.checked)}/>按顺序包含前章（用于外观继承）</label><div className="flex flex-wrap gap-2">
      <button className="btn-primary text-xs" disabled={running||busy} onClick={()=>void submit('REBUILD')}>从原文重建章回资产</button>
      {state.rebuild&&<button className="btn-secondary text-xs" disabled={running||busy} onClick={()=>void submit('CONTINUE')}>继续重建已确认阶段</button>}
      <a className="text-blue-700 text-xs self-center" href={`/novels/${novelId}/chapters/${chapterId}`}>处理素材 / 角色外观复核</a>
    </div></>}
  </section>;
}
