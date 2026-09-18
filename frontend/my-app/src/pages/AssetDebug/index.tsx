import {useEffect,useMemo,useRef,useState} from 'react';
import {Link,useSearchParams} from 'react-router-dom';
import {ArrowLeft,ChevronRight,Download,RefreshCw,Search} from 'lucide-react';
import {assetDebugApi,type DebugTrace,type DebugRecord,type DebugNode} from '../../api/assetDebug';
import {assetStatusLabel} from '../../utils/assetTerminology';

const kinds:Record<string,string>={chapter:'章回原文',lifecycle:'结构来源',rebuild:'显式重建',parse:'素材解析',candidate:'素材候选',resolution:'身份归一化',decision:'身份决策',
  character_binding:'本章角色关联',scene_binding:'本章场景关联',prop_binding:'本章道具关联',appearance_event:'角色外观事件',appearance_review:'人工复核',timeline:'外观时间线',
  character:'全局角色',identity:'角色类型',alias:'角色别名',scene:'全局场景',prop:'全局道具',appearance:'角色外观',appearance_generation:'角色外观生成',appearance_image:'角色外观图片版本',
  shot:'分镜',split:'拆分记录',source:'分镜来源',asset_head:'当前最终资产指针',rsa:'分镜最终资产',image_version:'冻结参考图版本',demand:'角色外观用量',media_attempt:'分镜/关键帧生成',media_artifact:'派生图像',task:'任务',llm_log:'LLM调用',
  audio_event:'音频事件',tts_asset:'TTS音频版本',audio_timeline:'音频时间线',audio_timeline_event:'时间线片段'};
const availability:Record<string,string>={AVAILABLE:'记录可读',MISSING:'记录缺失',CORRUPT:'证据损坏',OUT_OF_SCOPE:'所属小说不一致',LIMITED:'内容超出检查上限'};
const evidenceLabel:Record<string,string>={VALID:'可解析',MISSING:'未记录',INVALID_JSON:'JSON损坏',WRONG_TYPE:'类型不符',TOO_LARGE:'超出检查上限'};
const gateLabel:Record<string,string>={PASS:'通过',FAIL:'未通过',NOT_CHECKED:'未做当前准入校验'};
const factsLabels:Record<string,string>={candidateName:'候选名称',assetType:'素材类型',resolution:'身份决策',matchType:'匹配方式',matchedId:'匹配资产 ID',confidence:'置信度',llmUsed:'调用 LLM',promptVersion:'提示词版本',promptHash:'提示词 hash',metrics:'Resolver耗时与用量',manualAction:'人工决策',durationSeconds:'LLM耗时（秒）',tokenUsage:'Token用量',provider:'服务商',model:'模型',promptTemplateName:'实际提示词模板',source_hash:'原文版本 hash',input_hash:'输入 hash',result_hash:'结果 hash',seal:'记录 seal',rsa_id:'分镜最终资产 ID',rsa_hash:'分镜最终资产 hash',character_id:'角色 ID',appearance_id:'角色外观 ID',source_start:'原文起点',source_end:'原文终点',resolver_version:'解析器版本',parser_version:'解析版本',revision:'版本号',event_key:'外观事件标识',change_type:'变化类型',taskType:'任务类型',parentTaskId:'父任务 ID',promptId:'ComfyUI任务 ID',currentStep:'记录步骤',error:'错误原因',phase:'执行阶段',submission:'提交回执',uploads:'实际上传绑定',graphProof:'实际 graph 证明',promptTemplate:'提示词快照',localPrompt:'本地提示词',selections:'冻结外观选择',blockers:'阻塞原因',parents:'实际图片父版本',image:'产物图片',snapshot:'冻结图片',origin:'来源',originEvidence:'来源依据',rebuildId:'重建 ID'};
const text=(value:unknown)=>value==null?'未记录':typeof value==='boolean'?(value?'是':'否'):typeof value==='string'?value:JSON.stringify(value,null,2);
const displayLabel=(value:string)=>value.replace(/\bRSA\b/g,'分镜最终资产');
function JsonValue({value}:{value:unknown}) {return <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-all rounded bg-gray-50 p-3 text-xs leading-relaxed">{text(value)}</pre>;}

export default function AssetDebug() {
  const [params,setParams]=useSearchParams();
  const novelId=params.get('novel_id'),chapterId=params.get('chapter_id'),shotId=params.get('shot_id'),rsaId=params.get('rsa_id'),taskId=params.get('task_id');
  const recordKind=params.get('record_kind'),recordId=params.get('record_id');
  const limit=Math.max(20,Math.min(1200,Number(params.get('limit'))||400));
  const [trace,setTrace]=useState<DebugTrace|null>(null),[detail,setDetail]=useState<DebugRecord|null>(null),[loading,setLoading]=useState(false),[loadingDetail,setLoadingDetail]=useState(false),[error,setError]=useState(''),[detailError,setDetailError]=useState('');
  const [search,setSearch]=useState(''),[kind,setKind]=useState('all'),[revision,setRevision]=useState(0);
  const serial=useRef(0),detailSerial=useRef(0);
  useEffect(()=>{
    const version=++serial.current;setLoading(true);setError('');setTrace(null);setDetail(null);
    const load=async()=>{
      if(!taskId&&(!novelId||(!chapterId&&!(recordKind&&recordId))))throw new Error('请从章回资产准备或任务记录进入来源追踪');
      const result=taskId?await assetDebugApi.task(taskId,limit):recordKind&&recordId?await assetDebugApi.anchor(novelId!,recordKind,recordId,limit):await assetDebugApi.chapter(novelId!,chapterId!,{shot_id:shotId||undefined,rsa_id:rsaId||undefined,limit});
      if(version!==serial.current)return;
      if(!result.success||!result.data)throw new Error(String(result.message||'来源记录读取失败'));
      setTrace(result.data);
    };
    void load().catch(e=>{if(version===serial.current)setError(e instanceof Error?e.message:'读取失败');}).finally(()=>{if(version===serial.current)setLoading(false);});
    return()=>{serial.current++;};
  },[novelId,chapterId,shotId,rsaId,taskId,recordKind,recordId,limit,revision]);
  const focus=params.get('focus');
  const selected=trace?.nodes.find(n=>n.key===focus)||trace?.nodes.find(n=>n.key===trace.roots[trace.roots.length-1])||trace?.nodes[0];
  const select=(node:DebugNode)=>{const next=new URLSearchParams(params);next.set('focus',node.key);setParams(next);};
  useEffect(()=>{
    const version=++detailSerial.current;setDetail(null);setDetailError('');
    if(!trace||!selected||['MISSING','OUT_OF_SCOPE'].includes(selected.availability)){setLoadingDetail(false);return;}
    setLoadingDetail(true);
    assetDebugApi.record(trace.scope.novelId,selected.kind,selected.id).then(r=>{
      if(version!==detailSerial.current)return;
      if(r.success&&r.data)setDetail(r.data);else setDetailError(String(r.message||'记录详情读取失败'));
    }).catch(e=>{if(version===detailSerial.current)setDetailError(e instanceof Error?e.message:'详情读取失败');}).finally(()=>{if(version===detailSerial.current)setLoadingDetail(false);});
    return()=>{detailSerial.current++;};
  },[trace,selected?.key]);
  const visible=useMemo(()=>trace?.nodes.filter(n=>(kind==='all'||n.kind===kind)&&`${displayLabel(n.label)} ${n.id} ${n.recordStatus} ${text(n.facts)}`.toLowerCase().includes(search.toLowerCase()))||[],[trace,kind,search]);
  const incoming=trace?.edges.filter(e=>e.to===selected?.key)||[],outgoing=trace?.edges.filter(e=>e.from===selected?.key)||[];
  const related=(key:string,path:string)=>{const node=trace?.nodes.find(n=>n.key===key);return <button key={`${key}:${path}`} disabled={!node} onClick={()=>node&&select(node)} className="w-full rounded border p-2 text-left text-xs hover:bg-blue-50 disabled:text-gray-400"><span className="flex items-center gap-1 font-medium"><ChevronRight size={14}/>{displayLabel(node?.label||key)}</span><span className="block break-all mt-1 text-gray-500">{path}</span></button>;};
  const download=()=>{
    if(!trace)return;const data={trace,selectedRecord:detail};const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json;charset=utf-8'}));
    const a=document.createElement('a');a.href=url;a.download=`asset-debug-${trace.scope.taskId||trace.scope.shotId||trace.scope.chapterId}.json`;a.click();URL.revokeObjectURL(url);
  };
  const maker=trace?.scope.chapterId?`/novels/${trace.scope.novelId}/chapters/${trace.scope.chapterId}/generate?stage=assets`:null;
  return <main className="min-w-0 space-y-4" aria-label="资产来源追踪">
    <header className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><h1 className="text-xl font-bold">Debug · 资产来源追踪</h1><p className="mt-1 text-sm text-gray-600">{trace?.scope.novelTitle||'读取持久化来源'} · 依据已保存 ID 关联的只读视图</p></div><div className="flex flex-wrap gap-2">
      {maker&&<Link className="btn-secondary text-sm flex items-center gap-1" to={maker}><ArrowLeft size={16}/>资产准备</Link>}
      <button className="btn-secondary text-sm flex items-center gap-1" disabled={loading} onClick={()=>setRevision(r=>r+1)}><RefreshCw size={16}/>刷新记录</button>
      <button className="btn-secondary text-sm flex items-center gap-1" disabled={!trace||loading} onClick={download}><Download size={16}/>导出当前视图</button></div></header>
    {error&&<p role="alert" className="rounded border border-red-200 bg-red-50 p-3 text-red-700 break-all">{error}</p>}
    {loading&&<p role="status">正在读取来源记录…</p>}
    {trace&&<>
      <section aria-label="当前准入与证据覆盖" className="rounded-lg border bg-white p-3 space-y-2 text-sm">
        {focus&&!trace.nodes.some(n=>n.key===focus)&&<p className="text-amber-800">指定记录不在本次加载范围内，请提高上限或从该记录单独进入追踪。</p>}
        <p>记录节点 {trace.coverage.nodeCount} · 缺失 {trace.coverage.missingNodes.length} · 损坏/受限 {trace.coverage.invalidNodes.length} · 归属异常 {trace.coverage.scopeConflicts.length}</p>
        <p className="text-xs text-gray-500 break-all">读取时间：{trace.readAt} · 记录中的 READY/completed 与当前生成准入分别展示。</p>
        {trace.current.chapter?.result&&<p>章回结构：{trace.current.chapter.result.structuralReady?'已就绪':trace.current.chapter.result.needsRebuild?'需显式重建':'尚未就绪'} · 原始结构来源：{assetStatusLabel(trace.current.chapter.result.origin)}</p>}
        {trace.current.chapter?.issue!=null&&<p className="break-all text-amber-800">章回校验：{text(trace.current.chapter.issue)}</p>}
        {trace.current.shot&&<div className="flex flex-wrap gap-3">{Object.entries(trace.current.shot.checks).map(([key,check])=><span key={key} className={check.ready?'text-green-700':'text-amber-700'}>{check.ready?'✓':'✕'} {({source:'原文来源',assets:'分镜最终资产',primary:'主分镜图',audio:'音频时间线',plan:'视频规划',keyframes:'关键帧'} as Record<string,string>)[key]||key}</span>)}</div>}
        {trace.coverage.truncated&&<p className="text-amber-800">已达到加载上限，本次关系图不完整。{limit<1200&&<button className="ml-2 underline text-blue-700" onClick={()=>{const next=new URLSearchParams(params);next.set('limit',String(Math.min(1200,limit+400)));setParams(next);}}>加载更多记录</button>}</p>}
        {!!trace.diagnostics.length&&<details><summary>关系诊断</summary><JsonValue value={trace.diagnostics}/></details>}
      </section>
      <div className="grid grid-cols-1 xl:grid-cols-[minmax(260px,330px)_minmax(0,1fr)] gap-4 items-start">
        <aside className="min-w-0 rounded-lg border bg-white p-3 space-y-3" aria-label="来源记录列表">
          <label className="flex items-center gap-2 rounded border p-2"><Search size={16}/><input aria-label="搜索来源记录" className="min-w-0 w-full text-sm outline-none" placeholder="名称、ID、状态或 hash" value={search} onChange={e=>setSearch(e.target.value)}/></label>
          <select aria-label="证据类型" value={kind} onChange={e=>setKind(e.target.value)} className="w-full rounded border p-2 text-sm"><option value="all">全部类型（{trace.nodes.length}）</option>{Object.entries(kinds).filter(([key])=>trace.nodes.some(n=>n.kind===key)).map(([key,label])=><option key={key} value={key}>{label}（{trace.nodes.filter(n=>n.kind===key).length}）</option>)}</select>
          <div className="max-h-64 xl:max-h-[65vh] overflow-y-auto space-y-2">{visible.map(n=><button key={n.key} data-record-key={n.key} aria-pressed={selected?.key===n.key} onClick={()=>select(n)} className={`w-full rounded border p-2 text-left text-sm ${selected?.key===n.key?'border-blue-500 bg-blue-50':'hover:bg-gray-50'}`}><strong className="block break-words">{displayLabel(n.label)}</strong><span className="block text-xs break-all text-gray-500">{n.id}</span><span className={`block text-xs mt-1 ${n.availability==='AVAILABLE'?'text-gray-600':'text-amber-700'}`}>{availability[n.availability]} · {assetStatusLabel(n.recordStatus)}</span></button>)}</div>
          {!visible.length&&<p className="text-sm text-gray-500">没有匹配的已加载记录。</p>}
        </aside>
        {selected&&<section className="min-w-0 rounded-lg border bg-white p-3 sm:p-5 space-y-4" aria-label="来源记录详情" data-selected-record={selected.key}>
          <header><h2 className="font-semibold text-lg break-words">{displayLabel(selected.label)}</h2><p className="mt-1 text-xs text-gray-500 break-all">{selected.kind} · {selected.id}</p><p className="mt-2 text-sm">记录状态：{assetStatusLabel(selected.recordStatus)} · {availability[selected.availability]}</p></header>
          {!!selected.issues.length&&<div className="rounded bg-amber-50 p-3 text-sm text-amber-800">{selected.issues.map((i,index)=><p key={index} className="break-all">{i.field?`${i.field}：`:''}{i.code} · {i.message}</p>)}</div>}
          {loadingDetail&&<p role="status">正在读取保存内容…</p>}{detailError&&<p role="alert" className="text-red-700 break-all">{detailError}</p>}
          <dl className="space-y-3">{Object.entries(selected.facts).map(([key,value])=><div key={key} className="min-w-0"><dt className="text-xs text-gray-500 mb-1">{factsLabels[key]||key}</dt><dd className="min-w-0 text-sm break-all">{value!=null&&typeof value==='object'?<details><summary className="cursor-pointer">查看保存内容</summary><JsonValue value={value}/></details>:text(value)}</dd></div>)}</dl>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3"><div className="space-y-2"><h3 className="text-sm font-semibold">本记录引用的依据 / 产物</h3>{outgoing.map(e=>related(e.to,e.path))}{!outgoing.length&&<p className="text-xs text-gray-500">未记录可展开的关联 ID。</p>}</div><div className="space-y-2"><h3 className="text-sm font-semibold">引用本记录的节点</h3>{incoming.map(e=>related(e.from,e.path))}{!incoming.length&&<p className="text-xs text-gray-500">本次视图未包含上层引用。</p>}</div></div>
          {detail&&<>
            <section aria-label="记录校验结果" className="border-t pt-3 space-y-2"><h3 className="font-semibold text-sm">校验结果</h3><p className="text-sm">{detail.kind==='image_version'?'冻结图片完整性':'当前准入'}：{gateLabel[detail.currentGate.state]||detail.currentGate.state}</p>{detail.currentGate.issue!=null&&<JsonValue value={detail.currentGate.issue}/>}{detail.hashChecks.map(c=><p className="text-xs break-all" key={c.code}>{c.code}：{c.state==='PASS'?'哈希一致':'哈希不一致'} · {c.actual}</p>)}<p className="text-xs text-gray-500">哈希自洽仅表示保存内容一致，不能代替完整来源和当前准入校验。</p></section>
            <section aria-label="JSON证据状态" className="border-t pt-3 space-y-2"><h3 className="font-semibold text-sm">JSON证据状态</h3>{Object.entries(detail.jsonFields).map(([field,info])=><div key={field} className="text-xs break-all"><strong>{field}</strong> · {evidenceLabel[info.state]||info.state}{info.emptyConfirmed?' · 已记录空值':''}{info.redacted?' · 已脱敏/限长':''}{info.truncated?' · 展示受限':''}<p className="text-gray-500">长度 {info.length} · SHA {info.sha256||'未记录'}{info.error?` · ${info.error}`:''}</p></div>)}</section>
            <details className="border-t pt-3"><summary className="font-medium cursor-pointer">完整保存记录（脱敏展示）</summary><JsonValue value={detail.record}/></details>
          </>}
        </section>}
      </div>
    </>}
  </main>;
}
