import {ResolvedAssetsPanel} from '../../../components/ResolvedAssetsPanel';
import {useChapterGenerateStore} from '../stores';
import {STAGE} from '../productionStages';
import type {AssetReadiness} from '../../../api/resolvedAssets';
export function AssetPreparationTab({novelId,chapterId,onReadiness}:{novelId:string;chapterId:string;onReadiness?:(state:AssetReadiness)=>void}) {
  const currentShotId=useChapterGenerateStore(s=>s.currentShotId),currentShotIndex=useChapterGenerateStore(s=>s.currentShotIndex);
  return <ResolvedAssetsPanel novelId={novelId} chapterId={chapterId} currentShotId={currentShotId} currentShotIndex={currentShotIndex} onReadiness={state=>{
    onReadiness?.(state);
    useChapterGenerateStore.setState(previous=>({tabProgress:{...previous.tabProgress,[STAGE.ASSETS]:state.chapterReady}}));
  }}/>;
}
