import {useEffect,useState} from 'react';
import {useParams} from 'react-router-dom';
import type {Shot} from '../../../api/shots';
import {resolvedAssetsApi,type FrozenRSA} from '../../../api/resolvedAssets';
import {useChapterGenerateStore} from '../stores';
import {STAGE} from '../productionStages';

interface ResourcePanelProps {currentShot?:Shot;onImageClick?:(url:string)=>void}
export function ResourcePanel({currentShot,onImageClick}:ResourcePanelProps) {
  const {id,cid}=useParams<{id:string;cid:string}>();
  const [state,setState]=useState<FrozenRSA|null>(null),[error,setError]=useState('');
  useEffect(()=>{
    setState(null);setError('');if(!id||!cid||!currentShot)return;
    let alive=true;let timer:ReturnType<typeof setTimeout>;
    const load=async()=>{try{const r=await resolvedAssetsApi.current(id,cid,currentShot.id);if(alive){if(r.success&&r.data)setState(r.data);else setError(String(r.message));}}catch{if(alive)setError('冻结参考图读取失败');}if(alive)timer=setTimeout(load,6000);};
    void load();return()=>{alive=false;clearTimeout(timer);};
  },[id,cid,currentShot?.id]);
  const current=state?.shotId===currentShot?.id?state:null;
  const assets=current?.assets;
  const usable=!!assets?.logical_ready&&!['STALE','FAILED','RUNNING'].includes(current?.effectiveStatus||'');
  const groups=[
    {name:'角色',items:assets?.characters?.map(c=>({id:c.character_id,name:c.name,image:c.image,detail:c.appearance_id?'本 Shot 指定角色外观':'基础造型'}))||[]},
    {name:'场景',items:assets?.scene?[{id:assets.scene.scene_id,name:assets.scene.name,image:assets.scene.image,detail:''}]:[]},
    {name:'道具',items:assets?.props?.map(p=>({id:p.prop_id,name:p.name,image:p.image,detail:''}))||[]},
  ];
  return <section className="generate-resource-panel h-full min-h-0 flex flex-col text-sm" aria-label="当前 Shot 冻结参考图">
    <h3 className="font-semibold border-b pb-3">当前 Shot 冻结参考图</h3>
    <div className="flex-1 overflow-y-auto space-y-3 pt-3">
      {error&&<p className="text-red-700">{error}</p>}
      {!usable&&<p className="text-amber-700">{current?.effectiveStatus==='STALE'?'资产版本已失效，请重新解析。':'请先在资产准备中解析本 Shot 的最终资产。'}</p>}
      {usable&&groups.map(group=><div key={group.name}><h4 className="font-medium mb-2">{group.name}（{group.items.length}）</h4><div className="space-y-2">{group.items.map(item=><div key={item.id} className="flex items-center gap-3 rounded-lg border p-2">
        {item.image?<button aria-label={`查看 ${item.name} 冻结参考图`} onClick={()=>onImageClick?.(item.image!.url)}><img src={item.image.url} alt={item.name} className="w-20 h-20 object-contain bg-gray-50"/></button>:<div className="w-20 h-20 shrink-0 bg-gray-50 text-xs text-gray-500 flex items-center justify-center">待生成</div>}
        <div className="min-w-0"><p>{item.name}</p>{item.detail&&<p className="text-xs text-gray-500">{item.detail}</p>}</div>
      </div>)}</div></div>)}
      <button className="text-blue-700 underline" onClick={()=>useChapterGenerateStore.getState().setCurrentTab(STAGE.ASSETS)}>前往资产准备</button>
    </div>
  </section>;
}
export default ResourcePanel;
