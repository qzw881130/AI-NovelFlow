import {useEffect,useState} from 'react';
import {X} from 'lucide-react';
import {assetResolutionsApi,type BindingState} from '../../../api/assetResolutions';
import {assetStatusLabel} from '../../../utils/assetTerminology';
import {GenerateDialog} from './GenerateDialog';

interface ChapterResourcesModalProps {isOpen:boolean;onClose:()=>void;novelId?:string;chapterId?:string}
export function ChapterResourcesModal({isOpen,onClose,novelId,chapterId}:ChapterResourcesModalProps) {
  const [state,setState]=useState<BindingState|null>(null),[error,setError]=useState('');
  useEffect(()=>{
    setState(null);setError('');if(!isOpen||!novelId||!chapterId)return;
    let alive=true;
    assetResolutionsApi.bindings(novelId,chapterId).then(r=>{if(!alive)return;if(r.success&&r.data)setState(r.data);else setError(String(r.message));}).catch(()=>{if(alive)setError('本章分镜资产读取失败');});
    return()=>{alive=false;};
  },[isOpen,novelId,chapterId]);
  if(!isOpen)return null;
  const names:Record<string,string>={characters:'角色',scenes:'场景',props:'道具'};
  return <GenerateDialog label="本章分镜资产" onClose={onClose}>
    <div className="generate-resources-modal bg-white rounded-lg shadow-xl w-full max-w-4xl max-h-[90vh] overflow-y-auto p-4 sm:p-6 space-y-4">
      <div className="flex items-center justify-between"><h2 className="text-lg font-semibold">本章分镜资产</h2><button aria-label="关闭" onClick={onClose}><X/></button></div>
      <p className="text-sm text-gray-600">此处展示本章正式关联的分镜白名单。身份歧义或缺失素材请到章回素材解析页处理。</p>
      {error&&<p role="alert" className="text-red-700">{error}</p>}
      {!state&&!error&&<p>读取中…</p>}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">{state&&Object.entries(state.assets).map(([kind,group])=><section className="border rounded-lg p-3 space-y-2" key={kind}>
        <h3 className="font-medium">{names[kind]} · {assetStatusLabel(group.status)}</h3>
        {group.bindings.map(b=><div key={b.id} className="text-sm"><p>{b.name}</p><p className="text-xs text-gray-500 break-all">{b.assetId}</p></div>)}
        {!group.bindings.length&&<p className="text-sm text-gray-500">{group.emptyConfirmed?'已确认无此类素材':'尚未确认'}</p>}
      </section>)}</div>
      <div className="flex justify-end gap-3"><a className="btn-primary text-sm" href={`/novels/${novelId}/chapters/${chapterId}`}>前往章回素材解析</a><button className="btn-secondary text-sm" onClick={onClose}>关闭</button></div>
    </div>
  </GenerateDialog>;
}
export default ChapterResourcesModal;
