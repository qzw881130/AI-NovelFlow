import {useEffect,useState} from 'react';
import {chapterGovernanceApi,type RuntimeReadiness} from '../../../api/chapterGovernance';
import type {Shot} from '../../../api/shots';
import {assetBlockerLabel} from '../../../utils/assetTerminology';
import {useChapterGenerateStore} from '../stores';
import {STAGE} from '../productionStages';
export function AssetDependencySummary({novelId,chapterId,shot,video=false}:{novelId:string;chapterId:string;shot?:Shot;video?:boolean}) {
  const [state,setState]=useState<RuntimeReadiness|null>(null),[error,setError]=useState('');
  useEffect(()=>{
    setState(null);setError('');if(!shot)return;
    let alive=true;let timer:ReturnType<typeof setTimeout>;
    const load=async()=>{try{const r=await chapterGovernanceApi.runtime(novelId,chapterId,shot.id);if(alive){if(r.success&&r.data){setState(r.data);setError('');}else setError(String(r.message));}}catch{if(alive)setError('资产就绪检查失败');}if(alive)timer=setTimeout(load,6000);};
    void load();return()=>{alive=false;clearTimeout(timer);};
  },[novelId,chapterId,shot?.id,shot?.updatedAt]);
  const current=state?.shotId===shot?.id?state:null;
  const labels:{key:keyof RuntimeReadiness['checks'];label:string}[]=[{key:'assets',label:'分镜最终资产'},{key:'primary',label:'分镜图'},{key:'audio',label:'Audio Timeline'},{key:'keyframes',label:'关键帧'},{key:'plan',label:'视频规划'}];
  const reason=current?.checks.assets.reason;
  return <section className="rounded-lg border bg-white px-3 py-2 my-2 text-sm" aria-label={video?'视频生成前置条件':'资产准备摘要'}>
    <div className="flex flex-wrap items-center justify-between gap-2"><span>{video?'视频生成前置条件':'资产准备'} · 当前 Shot #{shot?.index||'—'}：{current?(current.checks.assets.ready?'已就绪':'依赖未就绪'):'检查中'}</span>
      <button className="text-blue-700 underline" onClick={()=>useChapterGenerateStore.getState().setCurrentTab(STAGE.ASSETS)}>前往资产准备</button></div>
    {video&&<div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs">{labels.map(item=><span key={item.key}>{current?.checks[item.key].ready?'✓':'⚠'} {item.label}</span>)}</div>}
    {!!reason&&<p className="mt-1 text-xs text-amber-700 break-all">当前 Shot 依赖未就绪：{typeof reason==='string'?assetBlockerLabel(reason):JSON.stringify(reason)}</p>}
    {error&&<p className="text-xs text-red-700">{error}</p>}
  </section>;
}
