import { useState } from 'react';
import { appearancesApi, type UsageBatch } from '../../../api/appearances';
export function AppearanceUsagePanel({novelId,chapterId,dirty}:{novelId:string;chapterId:string;dirty:boolean}) {
  const [rows,setRows]=useState<{shotId:string;index:number;eligible:Record<string,string[]>;blocked:{code:string}[]}[]|null>(null);
  const [selected,setSelected]=useState<string[]>([]),[busy,setBusy]=useState(false),[error,setError]=useState(''),[result,setResult]=useState<UsageBatch|null>(null);
  return <section className="card space-y-3 min-w-0">
    <h3 className="font-semibold">生成实际使用的缺失外观图</h3>
    <p className="text-sm text-gray-600">仅生成所选 Shot 可信来源中待生成或失败的角色外观。请先在“资产准备”中解析分镜最终资产；未建立有效逻辑来源的 Shot 会显示依赖未就绪。</p>
    <div className="flex flex-wrap gap-2"><button className="btn-secondary" disabled={busy||dirty} onClick={async()=>{
      setBusy(true);setError('');try {const r=await appearancesApi.usage(novelId,chapterId);if(r.success&&r.data){setRows(r.data);setSelected([]);}else setError(String(r.message));}
      catch{setError('读取 Shot 用量失败');}finally{setBusy(false);}}}>检查 Shot 用量</button>
      <button className="btn-primary" disabled={busy||dirty||!selected.length} onClick={async()=>{setBusy(true);setError('');try{
        const r=await appearancesApi.used(novelId,chapterId,selected);if(r.data)setResult(r.data);else setError(String(r.message));
      }catch{setError('提交失败，请刷新核对任务');}finally{setBusy(false);}}}>生成所选 Shot 缺图</button></div>
    {dirty&&<p className="text-amber-700 text-sm">请先保存章回正文。</p>}
    {error&&<p role="alert" className="text-red-700 break-all">{error}</p>}
    {rows?.length===0&&<p className="text-sm">尚无 Shot，用量未就绪。</p>}
    {rows?.map(row=><label key={row.shotId} className="flex gap-2 text-sm border rounded p-2 min-w-0">
      <input type="checkbox" disabled={!!row.blocked.length||!Object.keys(row.eligible).length} checked={selected.includes(row.shotId)} onChange={e=>setSelected(e.target.checked?[...selected,row.shotId]:selected.filter(id=>id!==row.shotId))}/>
      <span className="break-all">Shot {row.index} · {row.shotId}<br/>{row.blocked.map(b=>b.code).join('；')||`可生成缺失外观 ${Object.keys(row.eligible).length} 项`}</span></label>)}
    {result&&<div className="text-sm"><p>已提交 {result.queued.length} · 跳过 {result.skipped.length} · 阻断 {result.blocked.length}</p><pre className="whitespace-pre-wrap break-all">{JSON.stringify(result,null,2)}</pre></div>}
  </section>;
}
