import {api} from './index';
export interface FrozenImage {image_revision_id:string;url:string;sha256:string}
export interface CharacterAssetView {characterId:string;name:string;appearanceId:string|null;appearanceName:string;appearanceStatus:string;
  sourceChapter:{id:string;number:number;title:string}|null;events:{id:string;key:string;evidence:{text:string}[]}[]}
export interface ResolvedCharacter {character_id:string;name:string;appearance_id:string|null;selection:{kind:string;reason:string;sourceChapterId:string|null;sourceEventIds:string[]};reference_image_id:string|null;image:FrozenImage|null;image_status:string}
export interface FrozenRSA {id:string|null;shotId:string;taskId?:string;revision?:number;status:string;effectiveStatus:string;ready:boolean;issue?:unknown;resultHash?:string;inputHash?:string;
  view?:{logicalCurrent:boolean;characters:CharacterAssetView[];generationActions:{kind:string;id:string;name:string;url:string}[]};
  assets:{logical_ready?:boolean;characters?:ResolvedCharacter[];scene?:{scene_id:string;name:string;reference_image_id:string|null;image?:FrozenImage|null};props?:{prop_id:string;name:string;reference_image_id:string|null;image?:FrozenImage|null}[];blockers?:{slot?:string;code:string;detail?:unknown}[]}|null}
export interface AssetReadiness {chapterReady:boolean;shots:(FrozenRSA&{index:number})[];readyShotIds:string[];blockedShotIds:string[];failedShotIds:string[];pendingShotIds:string[];
  counts:{total:number;ready:number;blocked:number;failed:number;pending:number};readyManifest:{shot_id:string;rsa_id:string;rsa_hash:string}[]}
const root=(n:string,c:string)=>`/novels/${n}/chapters/${c}`;
export const resolvedAssetsApi={
  current:(n:string,c:string,s:string)=>api.get<FrozenRSA>(`${root(n,c)}/shots/${s}/resolved-assets`),
  lineage:(n:string,c:string,s:string)=>api.get<unknown>(`${root(n,c)}/shots/${s}/image-lineage`),
  readiness:(n:string,c:string)=>api.get<AssetReadiness>(`${root(n,c)}/asset-readiness`),
  resolveAll:(n:string,c:string)=>api.post<AssetReadiness>(`${root(n,c)}/resolve-assets`,{}),
  resolve:(n:string,c:string,s:string)=>api.post<FrozenRSA>(`${root(n,c)}/shots/${s}/resolve-assets`),
  detail:(n:string,c:string,id:string)=>api.get<FrozenRSA&{inputs:unknown}>(`${root(n,c)}/resolved-assets/${id}`),
  history:(n:string,c:string,s:string)=>api.get<{id:string;revision:number;status:string;resultHash:string}[]>(`${root(n,c)}/shots/${s}/resolved-assets/history`),
};
