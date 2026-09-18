import {api} from './index';
export interface ChapterPipelineState {
  chapterId:string;origin:'NEW'|'LEGACY';condition:string;needsRebuild:boolean;structuralReady:boolean;missingStages:string[];
  rebuild:{id:string;taskId:string;status:string;error:string|null;steps:{chapterId:string;stage:string;at:string}[];result:unknown}|null;
}
export interface RuntimeReadiness {shotId:string;checks:Record<'source'|'assets'|'primary'|'audio'|'plan'|'keyframes',{ready:boolean;reason:unknown}>}
const root=(n:string,c:string)=>`/novels/${n}/chapters/${c}`;
export const chapterGovernanceApi={
  state:(n:string,c:string)=>api.get<ChapterPipelineState>(`${root(n,c)}/pipeline-state`),
  rebuild:(n:string,c:string,mode:'REBUILD'|'CONTINUE',include_previous:boolean)=>api.post<{id:string;taskId:string;status:string}>(`${root(n,c)}/rebuild-assets`,{mode,include_previous}),
  runtime:(n:string,c:string,s:string)=>api.get<RuntimeReadiness>(`${root(n,c)}/shots/${s}/runtime-readiness`),
};
