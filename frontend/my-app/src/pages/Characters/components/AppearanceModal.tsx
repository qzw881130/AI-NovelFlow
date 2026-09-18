import { useEffect, useState } from 'react';
import { X, RefreshCw } from 'lucide-react';
import type { Character } from '../../../types';
import { appearancesApi, type AppearanceAsset, type AppearanceList } from '../../../api/appearances';
import { ImagePreviewModal } from '../../../components/ImagePreviewModal';

const labels:Record<string,string>={NEEDS_GENERATION:'缺少外观图',GENERATING:'生成中',READY:'图已就绪',FAILED:'生成失败',REJECTED:'图已拒绝'};
export function AppearanceModal({character,onClose}:{character:Character;onClose:()=>void}) {
  const [data,setData]=useState<AppearanceList|null>(null), [error,setError]=useState(''), [busy,setBusy]=useState(false);
  const [seed,setSeed]=useState(''), [detail,setDetail]=useState<unknown>(null), [rejecting,setRejecting]=useState<AppearanceAsset|null>(null);
  const [reason,setReason]=useState('');
  const [preview,setPreview]=useState<{url:string;name:string}|null>(null);
  const load=async()=>{
    try { const r=await appearancesApi.list(character.novelId,character.id); if(r.success&&r.data)setData(r.data);else setError(String(r.message)); }
    catch {setError('读取外观失败，请重试');}
  };
  useEffect(()=>{void load();const timer=window.setInterval(()=>void load(),5000);return()=>window.clearInterval(timer);},[character.id]);
  useEffect(()=>{const handler=(e:KeyboardEvent)=>{if(e.key==='Escape')onClose();};window.addEventListener('keydown',handler);return()=>window.removeEventListener('keydown',handler);},[onClose]);
  const generate=async(a:AppearanceAsset)=>{
    const value=seed.trim()?Number(seed):undefined;
    if(value!==undefined&&(!Number.isSafeInteger(value)||value<0)){setError('Seed 必须为非负安全整数');return;}
    setBusy(true);setError('');
    try {const r=await appearancesApi.generate(character.novelId,character.id,a.id,['READY','REJECTED'].includes(a.status),value);
      if(!r.success)setError(String(r.message));await load();}
    catch {setError('提交失败，请刷新确认任务状态后再试');}finally {setBusy(false);}
  };
  const inspect=async(a:AppearanceAsset)=>{
    setBusy(true);try {const r=await appearancesApi.detail(character.novelId,character.id,a.id);if(r.success)setDetail(r.data);else setError(String(r.message));}
    catch {setError('读取生成证据失败');}finally {setBusy(false);}
  };
  return <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-2 sm:p-5" role="dialog" aria-modal="true" aria-label={`${character.name}角色外观`}>
    <div className="bg-white rounded-xl shadow-xl w-full max-w-4xl max-h-[92vh] flex flex-col min-w-0">
      <div className="flex items-center gap-2 p-4 border-b"><h2 className="font-semibold flex-1 min-w-0 break-words">{character.name} · 角色外观</h2>
        <button aria-label="刷新外观" onClick={()=>void load()} className="p-2"><RefreshCw size={18}/></button><button aria-label="关闭外观" onClick={onClose} className="p-2"><X size={20}/></button></div>
      <div className="overflow-y-auto p-4 space-y-4 min-w-0">
        <p className="text-sm text-gray-600">逻辑外观按原文时间线生效。图缺失、失败或拒绝时，仍使用该逻辑外观并等待图片就绪。</p>
        <label className="block text-sm">Seed（留空随机）<input value={seed} onChange={e=>setSeed(e.target.value)} inputMode="numeric" className="input-field w-full mt-1"/></label>
        {error&&<p role="alert" className="text-red-700 break-all">{error}</p>}
        {!data?<p>读取中…</p>:<>
          <section className="border rounded-lg p-3 space-y-2"><h3 className="font-semibold">BASE · 正式角色基图 · {data.base.status==='MISSING'?'缺图':'已有基图'}</h3>
            {data.base.imageUrl&&<button type="button" className="block w-full cursor-zoom-in" aria-label={`查看${character.name}基础参考图`} onClick={()=>setPreview({url:data.base.imageUrl!,name:`${character.name} · 基础参考图`})}><img alt={`${character.name} BASE`} src={data.base.imageUrl} className="w-full max-h-64 object-contain bg-gray-50"/></button>}
            <p className="text-sm whitespace-pre-wrap">{data.base.description}</p>
            {!data.base.imageUrl&&<p className="text-amber-700 text-sm">请先在角色卡片上传或生成正式基图。</p>}</section>
          {!data.appearances.length&&<p>尚无章回外观变化资产，请先完成角色归并和外观时间线。</p>}
          {data.appearances.map(a=><section key={a.id} className="border rounded-lg p-3 space-y-2 min-w-0">
            <h3 className="font-semibold">{a.description} · {a.status==='READY'&&!a.imageReady?'图像完整性阻断':labels[a.status]||a.status}</h3>
            <p className="text-xs text-gray-500 break-all">Appearance ID：{a.id}<br/>来源章回：{a.sourceChapterId}<br/>生成版本：{a.generationRevision} · {a.logicalCurrent?'逻辑来源有效':'逻辑来源已过期'}</p>
            {a.imageUrl&&<button type="button" className="block w-full cursor-zoom-in" aria-label={`查看${character.name}角色外观图`} onClick={()=>setPreview({url:a.imageUrl!,name:`${character.name} · ${a.description}`})}><img src={a.imageUrl} alt={a.description} className="w-full max-h-80 object-contain bg-gray-50"/></button>}
            {a.previousAppearanceId&&<p className="text-xs break-all">逻辑前一外观：{a.previousAppearanceId}（换装上下文，视觉参考仍为正式基图）</p>}
            {(a.generationBlocker||a.lastError)&&<p className="text-sm text-amber-700 break-all">{a.generationBlocker||a.lastError}</p>}
            {a.taskId&&<a className="text-xs text-blue-700 break-all block" href="/tasks">任务：{a.taskId}</a>}
            <div className="flex flex-wrap gap-2">
              <button className="btn-primary text-sm" disabled={busy||!!a.generationBlocker||!a.logicalCurrent||a.status==='GENERATING'} onClick={()=>void generate(a)}>{['READY','REJECTED'].includes(a.status)?'重新生成':'生成外观图'}</button>
              <button className="btn-secondary text-sm" disabled={busy} onClick={()=>void inspect(a)}>版本与生成证据</button>
              {a.status==='READY'&&<button className="btn-secondary text-sm" disabled={busy} onClick={()=>{setRejecting(a);setReason('');}}>拒绝此图</button>}
            </div>
          </section>)}
        </>}
        {rejecting&&<form className="border p-3 rounded space-y-2" onSubmit={async e=>{e.preventDefault();setBusy(true);try {
          const r=await appearancesApi.reject(character.novelId,character.id,rejecting,reason);if(r.success){setRejecting(null);await load();}else setError(String(r.message));
        }catch {setError('拒绝操作失败');}finally{setBusy(false);}}}>
          <label className="block text-sm">拒绝原因<textarea required value={reason} onChange={e=>setReason(e.target.value)} className="input-field w-full"/></label>
          <button disabled={busy||!reason.trim()} className="btn-primary">确认拒绝当前版本</button><button type="button" className="btn-secondary ml-2" onClick={()=>setRejecting(null)}>取消</button>
        </form>}
        {detail!=null&&<details open className="min-w-0"><summary>生成输入、工作流、任务与历史图版本</summary><pre className="text-xs whitespace-pre-wrap break-all bg-gray-50 p-2 max-h-96 overflow-y-auto">{JSON.stringify(detail,null,2)}</pre></details>}
      </div>
    </div>
    <ImagePreviewModal isOpen={!!preview} url={preview?.url||null} name={preview?.name} showDownload onClose={()=>setPreview(null)}/>
  </div>;
}
