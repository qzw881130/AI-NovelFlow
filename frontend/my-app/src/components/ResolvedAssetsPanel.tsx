import {useEffect,useRef,useState} from 'react';
import {api} from '../api';
import {resolvedAssetsApi,type AssetReadiness} from '../api/resolvedAssets';
import {appearancesApi,type UsageBatch} from '../api/appearances';
import {assetStatusLabel,assetBlockerLabel} from '../utils/assetTerminology';
import {ImagePreviewModal} from './ImagePreviewModal';

export function ResolvedAssetsPanel({novelId,chapterId,currentShotId,currentShotIndex=1,onReadiness}:{novelId:string;chapterId:string;currentShotId:string|null;currentShotIndex?:number;onReadiness?:(state:AssetReadiness)=>void}) {
  const [state,setState]=useState<AssetReadiness|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const [result,setResult]=useState<UsageBatch|null>(null),[detail,setDetail]=useState<unknown>(null);
  const [history,setHistory]=useState<{id:string;revision:number;status:string;resultHash:string}[]>([]),[actions,setActions]=useState<{name:string;message:string}[]>([]);
  const [preview,setPreview]=useState<{url:string;name:string}|null>(null);
  const serial=useRef(0);
  const selection=useRef(currentShotId);selection.current=currentShotId;
  const load=async()=>{const id=++serial.current;const response=await resolvedAssetsApi.readiness(novelId,chapterId);
    if(id!==serial.current)return;
    if(!response.success||!response.data)throw new Error(String(response.message||'资产就绪检查失败'));
    setState(response.data);onReadiness?.(response.data);return response.data;
  };
  useEffect(()=>{setState(null);setResult(null);setActions([]);let stopped=false;let timer:ReturnType<typeof setTimeout>;const refresh=async()=>{
    try{await load();}catch(e){if(!stopped)setError(e instanceof Error?e.message:'读取分镜最终资产失败');}
    if(!stopped)timer=setTimeout(refresh,6000);
  };void refresh();return()=>{stopped=true;clearTimeout(timer);serial.current++;};},[novelId,chapterId]);
  const act=async(operation:()=>Promise<void>)=>{setBusy(true);setError('');try{await operation();await load();}catch(e){setError(e instanceof Error?e.message:'操作失败');}finally{setBusy(false);}};
  const inspect=async(id:string)=>{const selected=selection.current;const r=await resolvedAssetsApi.detail(novelId,chapterId,id);if(r.success){if(selection.current===selected)setDetail(r.data);}else throw new Error(String(r.message));};
  const showHistory=async(shotId:string)=>{const r=await resolvedAssetsApi.history(novelId,chapterId,shotId);if(r.data&&selection.current===shotId)setHistory(r.data);};
  const generate=async(ids:string[])=>{const r=await appearancesApi.used(novelId,chapterId,ids);if(r.data)setResult(r.data);else throw new Error(String(r.message));};
  const processBlockers=async()=>{
    const resolved=await resolvedAssetsApi.resolveAll(novelId,chapterId);
    if(!resolved.data)throw new Error(String(resolved.message));setState(resolved.data);
    const unique=new Map(resolved.data.shots.flatMap(s=>s.view?.generationActions||[]).map(a=>[a.url,a]));
    const outcomes=[];
    for(const action of unique.values()){
      const response=await api.post<{taskId?:string}>(action.url,{});
      outcomes.push({name:action.name,message:response.success?'已提交基础参考图生成':String(response.message)});
    }
    setActions(outcomes);
    await generate(resolved.data.shots.map(s=>s.shotId));
  };
  const current=currentShotId?state?.shots.find(s=>s.shotId===currentShotId):state?.shots.find(s=>s.index===currentShotIndex);
  const frozenCurrent=!!current?.view?.logicalCurrent&&!['STALE','FAILED','RUNNING'].includes(current.effectiveStatus);
  useEffect(()=>{setDetail(null);setHistory([]);setPreview(null);},[novelId,chapterId,currentShotId]);
  const thumbnail=(image:{url:string}|null|undefined,label:string)=>image?<button type="button" className="block w-full cursor-zoom-in rounded focus-visible:outline-blue-600" aria-label={`查看${label}大图`} onClick={()=>setPreview({url:image.url,name:label})}><img src={image.url} alt={label} className="w-full h-44 object-contain rounded bg-gray-50 border"/></button>:<div className="h-28 flex items-center justify-center border border-dashed rounded bg-gray-50 text-gray-500">参考图待生成或待重新解析</div>;
  return <section className="asset-preparation h-full min-w-0 overflow-y-auto rounded-lg border bg-white p-3 sm:p-5" aria-label="资产准备">
    <div className="space-y-4 min-w-0">
      <header><h2 className="text-lg font-semibold">资产准备</h2><p className="mt-1 text-sm text-gray-500">确定每个 Shot 最终使用的角色外观、场景、道具及参考图版本。</p></header>
      <div className="grid grid-cols-3 gap-2 text-center text-sm">
        <div className="rounded-lg bg-green-50 p-3">就绪 Shot<strong className="block text-xl text-green-700">{state?.counts.ready??'—'}</strong></div>
        <div className="rounded-lg bg-amber-50 p-3">待处理 Shot<strong className="block text-xl text-amber-700">{state?(state.counts.blocked+state.counts.pending):'—'}</strong></div>
        <div className="rounded-lg bg-red-50 p-3">失败 Shot<strong className="block text-xl text-red-700">{state?.counts.failed??'—'}</strong></div>
      </div>
      {error&&<p role="alert" className="text-sm text-red-700 break-all">{error}</p>}
      <div className="flex flex-wrap gap-2">
        <button className="btn-primary text-sm" disabled={busy||!state?.shots.length} onClick={()=>void act(async()=>{const r=await resolvedAssetsApi.resolveAll(novelId,chapterId);if(r.data)setState(r.data);else throw new Error(String(r.message));})}>重新解析全部</button>
        <button className="btn-secondary text-sm" disabled={busy||!state?.shots.length} onClick={()=>void act(()=>generate(state!.shots.map(s=>s.shotId)))}>生成全部缺失角色外观</button>
        <button className="btn-secondary text-sm" disabled={busy||!state?.shots.length} onClick={()=>void act(processBlockers)}>处理全部阻塞项</button>
        <button className="btn-secondary text-sm" disabled={busy} onClick={()=>void act(async()=>{})}>资产就绪检查</button>
      </div>
      <details className="text-xs text-gray-500"><summary className="cursor-pointer">阻塞项处理说明</summary><p className="mt-2">“处理全部阻塞项”会重新检查并提交当前可生成的基础参考图和缺失角色外观。等待基图或需人工复核的项目会列出原因；生成完成后重新解析，形成新的分镜最终资产。</p></details>
      {state?.shots.length===0&&<p>尚无 Shot，请先完成分镜拆分。</p>}
      {current&&[current].map(row=><section key={row.shotId} className="rounded-lg border p-3 min-w-0" aria-label={`当前 Shot ${row.index} 资产`}>
        <h3 className="flex flex-wrap justify-between gap-2 font-semibold">当前 Shot #{row.index}<span className={row.ready?'text-green-700':'text-amber-700'}>{assetStatusLabel(row.effectiveStatus)}</span></h3>
        <div className="mt-3 space-y-4 text-sm min-w-0">
          <div className="flex flex-wrap gap-2"><button disabled={busy} className="btn-secondary text-xs" onClick={()=>void act(async()=>{const r=await resolvedAssetsApi.resolve(novelId,chapterId,row.shotId);if(!r.success)throw new Error(String(r.message));})}>重新解析当前 Shot</button>
            <button disabled={busy} className="btn-secondary text-xs" onClick={()=>void act(()=>generate([row.shotId]))}>生成当前缺失外观</button></div>
          {row.effectiveStatus==='STALE'&&<p className="rounded bg-amber-50 p-2 text-amber-800">以下为历史冻结版本，当前依赖已变化。重新解析后才能用于生成。</p>}
          <section><h3 className="border-b pb-1 font-semibold">角色（{row.assets?.logical_ready?row.view?.characters.length||0:'待解析'}）</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 mt-2">{row.view?.characters.map(c=>{const frozen=row.assets?.characters?.find(a=>a.character_id===c.characterId);return <div key={c.characterId} className="rounded-lg border p-3 space-y-2 min-w-0">
              {thumbnail(frozen?.image,`${c.name} · ${c.appearanceName}`)}
              <p className="font-medium">{c.name}</p><p>全局角色：{c.name}</p><p>当前外观：{c.appearanceName||'待解析'}</p>
              {!c.appearanceId&&<p>外观来源：角色基础造型</p>}
               <p>状态：{assetStatusLabel(c.appearanceStatus)} · 参考图：{frozenCurrent&&frozen?.image_status==='READY'?'✓ 已就绪':!frozenCurrent?'待重新解析':'待生成 / 不可用'}</p>
              {c.sourceChapter&&<p className="text-xs text-gray-500">来源：第{c.sourceChapter.number}回 · 角色外观事件</p>}
               {c.events.map(event=><div key={event.id}><p className="text-xs text-gray-500">外观事件：{event.key}</p>{event.evidence.map((e,i)=><blockquote key={i} className="border-l-2 pl-2 text-xs text-gray-600 whitespace-pre-wrap">{e.text}</blockquote>)}</div>)}
               {c.appearanceId&&row.view?.logicalCurrent&&['NEEDS_GENERATION','FAILED'].includes(c.appearanceStatus)&&<button disabled={busy} className="btn-secondary text-xs" onClick={()=>void act(()=>generate([row.shotId]))}>生成角色外观</button>}
              {frozen?.image&&<button type="button" className="text-xs text-blue-700 ml-2" onClick={()=>setPreview({url:frozen.image!.url,name:`${c.name} · ${c.appearanceName}`})}>查看冻结参考图</button>}
              <a href={`/characters?novel=${novelId}&highlight=${c.characterId}`} className="text-xs text-blue-700 ml-2">管理角色 / 基础参考图</a>
            </div>;})}</div>
            {!row.assets?.logical_ready&&<p className="py-2 text-gray-500">请重新解析当前 Shot，获取正式角色、外观与参考图依赖。</p>}
            {row.assets?.logical_ready&&row.assets.characters?.length===0&&<p className="py-2">本 Shot 已确认无可见角色。</p>}
          </section>
          <section><h3 className="border-b pb-1 font-semibold">场景（{row.assets?.scene?1:0}）</h3>{row.assets?.scene?<div className="max-w-md py-2 space-y-2">{thumbnail(row.assets.scene.image,row.assets.scene.name)}<p>{row.assets.scene.name} · {frozenCurrent&&row.assets.scene.reference_image_id?'✓ 已就绪':!frozenCurrent?'待重新解析':'参考图待生成'}</p></div>:<p>待解析</p>}</section>
          <section><h3 className="border-b pb-1 font-semibold">道具（{row.assets?.props?.length||0}）</h3><div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-2">{row.assets?.props?.map(p=><div key={p.prop_id} className="border rounded-lg p-3 space-y-2">{thumbnail(p.image,p.name)}<p>{p.name} · {frozenCurrent&&p.reference_image_id?'✓ 已就绪':!frozenCurrent?'待重新解析':'参考图待生成'} <a className="text-xs text-blue-700" href={`/props?novel=${novelId}&highlight=${p.prop_id}`}>管理</a></p></div>)}</div>{row.assets?.props?.length===0&&<p className="py-2">无</p>}</section>
          <div className="rounded-lg bg-gray-50 p-3 space-y-1"><p>{row.view?.logicalCurrent?'✓':'✕'} 角色身份已解析</p><p>{frozenCurrent&&row.assets?.characters?.every(c=>c.image_status==='READY')?'✓':'✕'} 角色外观已就绪</p><p>{frozenCurrent&&row.assets?.scene?.reference_image_id?'✓':'✕'} 场景已就绪</p><p>{frozenCurrent&&row.assets?.props?.every(p=>!!p.reference_image_id)?'✓':'✕'} 道具已就绪</p></div>
          <p className="font-medium">分镜最终资产：{assetStatusLabel(row.effectiveStatus)}</p>
          {!!row.issue&&<p className="text-amber-700 break-all">{typeof row.issue==='string'?assetBlockerLabel(row.issue):JSON.stringify(row.issue)}</p>}
          {row.assets?.blockers?.map((b,i)=><p key={i} className="text-amber-700 break-all">{assetBlockerLabel(b.code)}{b.detail?`：${typeof b.detail==='string'?b.detail:JSON.stringify(b.detail)}`:''}</p>)}
          <div className="flex flex-wrap gap-2">
          <a className="btn-secondary text-xs" href={`/asset-debug?${new URLSearchParams({novel_id:novelId,chapter_id:chapterId,shot_id:row.shotId,...(row.id?{rsa_id:row.id}: {})})}`}>Debug / 来源追踪</a>
          <button disabled={busy} className="btn-secondary text-xs" onClick={()=>void act(()=>showHistory(row.shotId))}>查看解析历史</button>
          {row.id&&<button disabled={busy} className="btn-secondary text-xs" onClick={()=>void act(()=>inspect(row.id!))}>最终资产版本与证据</button>}
          <button disabled={busy} className="btn-secondary text-xs" onClick={()=>void act(async()=>{const r=await resolvedAssetsApi.lineage(novelId,chapterId,row.shotId);if(r.data&&selection.current===row.shotId)setDetail(r.data);})}>图像来源链</button></div>
          <details><summary className="text-xs text-gray-500">内部 ID / hash</summary><p className="break-all text-xs">Shot：{row.shotId}<br/>分镜最终资产：{row.id||'未解析'}<br/>版本 {row.revision||'—'} · {row.resultHash}</p></details>
        </div>
      </section>)}
      {actions.map((a,i)=><p key={i} className="text-sm break-all">{a.name}：{a.message}</p>)}
      {result&&<div><p>角色外观：提交 {result.queued.length} · 跳过 {result.skipped.length} · 依赖未就绪 {result.blocked.length}</p><details><summary>处理详情</summary><pre className="text-xs whitespace-pre-wrap break-all">{JSON.stringify(result,null,2)}</pre></details></div>}
      {history.map(r=><button key={r.id} className="block text-xs text-blue-700 break-all" onClick={()=>void act(()=>inspect(r.id))}>版本 {r.revision} · {assetStatusLabel(r.status)} · {r.id}</button>)}
      {detail!=null&&<details open><summary>持久化版本与来源证据</summary><pre className="text-xs whitespace-pre-wrap break-all">{JSON.stringify(detail,null,2)}</pre></details>}
    </div>
    <ImagePreviewModal isOpen={!!preview} url={preview?.url||null} name={preview?.name} showDownload onClose={()=>setPreview(null)}/>
  </section>;
}
