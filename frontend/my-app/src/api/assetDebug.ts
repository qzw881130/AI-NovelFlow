import {api} from './index';
export interface EvidenceState {state:string;sha256:string|null;length:number;error?:string|null;emptyConfirmed:boolean;redacted?:boolean;truncated?:boolean}
export interface DebugNode {key:string;kind:string;id:string;label:string;availability:string;recordStatus:string;createdAt?:string|null;facts:Record<string,unknown>;issues:{code:string;field?:string;message?:string}[]}
export interface DebugEdge {from:string;to:string;path:string}
export interface DebugTrace {
  version:string;readOnly:boolean;readAt:string;
  scope:{novelId:string;novelTitle:string;chapterId:string|null;shotId:string|null;taskId:string|null;rsaId:string|null};
  roots:string[];nodes:DebugNode[];edges:DebugEdge[];diagnostics:{code:string;key?:string;path?:string}[];
  current:{chapter?:{state:string;result:{origin:string;condition:string;structuralReady:boolean;needsRebuild:boolean;missingStages:string[]}|null;issue:unknown};shot?:{shotId:string;checks:Record<string,{ready:boolean;reason:unknown}>;issue?:unknown}};
  coverage:{truncated:boolean;nodeCount:number;nodeLimit:number;missingNodes:string[];invalidNodes:string[];scopeConflicts:string[]};
}
export interface DebugRecord extends DebugNode {record:Record<string,unknown>;jsonFields:Record<string,EvidenceState>;textFields:Record<string,{sha256:string;length:number;truncated:boolean}>;
  hashChecks:{code:string;state:string;expected:string;actual:string}[];currentGate:{state:string;issue:unknown;result?:unknown}}
export const assetDebugApi={
  anchor:(n:string,kind:string,id:string,limit=400)=>api.get<DebugTrace>(`/novels/${n}/asset-debug?${new URLSearchParams({kind,record_id:id,limit:String(limit)})}`),
  chapter:(n:string,c:string,options:{shot_id?:string;rsa_id?:string;limit?:number})=>{
    const params=new URLSearchParams();for(const [key,value] of Object.entries(options))if(value)params.set(key,String(value));
    return api.get<DebugTrace>(`/novels/${n}/chapters/${c}/asset-debug?${params}`);
  },
  task:(id:string,limit=400)=>api.get<DebugTrace>(`/tasks/${id}/asset-debug?limit=${limit}`),
  record:(n:string,kind:string,id:string)=>api.get<DebugRecord>(`/novels/${n}/asset-debug/records/${encodeURIComponent(kind)}/${encodeURIComponent(id)}`),
};
