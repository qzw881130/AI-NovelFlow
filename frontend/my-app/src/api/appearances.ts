import { api } from './index';
export interface AppearanceAsset {
  id:string; description:string; status:string; imageReady:boolean; logicalCurrent:boolean; sourceChapterId:string; sourceEventId:string;
  previousAppearanceId:string|null; imageUrl:string|null; imageRevisionId:string|null; generationRevision:number;
  taskId:string|null; lastError:string|null; generationBlocker:string|null; source:{url:string; kind:string; sha256:string}|null;
}
export interface AppearanceList {base:{imageUrl:string|null; description:string; status:string}; appearances:AppearanceAsset[]}
export interface UsageBatch {queued:{appearanceId:string;taskId:string}[];skipped:{appearanceId:string;status:string}[];blocked:{shotId?:string;appearanceId?:string;code:string}[]}
const root=(n:string,c:string)=>`/novels/${n}/characters/${c}/appearances`;
export const appearancesApi={
  usage:(n:string,c:string)=>api.get<{shotId:string;index:number;eligible:Record<string,string[]>;blocked:{code:string}[]}[]>(`/novels/${n}/chapters/${c}/appearances/shot-usage`),
  list:(n:string,c:string)=>api.get<AppearanceList>(root(n,c)),
  detail:(n:string,c:string,id:string)=>api.get<AppearanceAsset & {attempts:unknown[];revisions:unknown[]}>(`${root(n,c)}/${id}`),
  generate:(n:string,c:string,id:string,regenerate:boolean,seed?:number)=>api.post<{taskId:string}>(`${root(n,c)}/${id}/generate`,{regenerate,seed}),
  reject:(n:string,c:string,a:AppearanceAsset,reason:string)=>api.post(`${root(n,c)}/${a.id}/reject`,{
    expected_generation_id:a.taskId,expected_image_revision_id:a.imageRevisionId,reason}),
  used:(n:string,c:string,shotIds:string[])=>api.post<UsageBatch>(`/novels/${n}/chapters/${c}/appearances/generate-used-missing`,{shot_ids:shotIds}),
};
