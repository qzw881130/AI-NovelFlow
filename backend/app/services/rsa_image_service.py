"""Persistent production #06/#09 worker sharing one pinned RSA and immutable lineage."""
import asyncio
import base64
from copy import deepcopy
from datetime import datetime,timedelta
import hashlib
import json
import secrets
import re
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy import or_
from app.models.rsa_media import RsaImageAttempt as Attempt, RsaMediaArtifact as Artifact
from app.models.shot import Shot
from app.models.novel import Novel
from app.models.task import Task
from app.models.workflow import Workflow
from app.models.prompt_template import PromptTemplate
from app.models.llm_log import LLMLog
from app.models.chapter_shot_split import ChapterShotSplitRun
from app.services.chapter_asset_parse_service import digest
from app.services.resolved_shot_assets_service import require_frozen_rsa
from app.services.keyframe_reference_contract import KeyframeReferenceError, snapshot_target, target_semantics, frozen_keyframe_client
from app.services.comfyui.client import ComfyUIClient
from app.services.comfyui.workflows import WorkflowBuilder
from app.services.llm_service import LLMService
from app.services import rsa_media_contract as contract
from app.services.rsa_media_graph import prepare_graph,inspect_graph
from app.services.appearance_image_contract import output_receipt,receipt_url
from app.services.keyframe_reference_graph import semantic_graph_digest
from app.services.resolved_asset_images import IMAGE_POLICY
from app.services.task_execution import ExecutionConflict, upsert_review_finding

WORKER_ID='rsa-media-'+uuid4().hex
UNACKNOWLEDGED_ERROR='UNCONFIRMED_RSA_MEDIA_NOT_REPLAYED'
RECOVERABLE_VIDEO_BATCH_ERRORS={
    'BATCH_EXECUTION_REVIEW_REQUIRED: child attempt or result evidence exists',
    'BATCH_WORKER_INTERRUPTED: terminal child evidence preserved; automatic resubmission disabled',
}
ADOPTION_RECOVERY_SECONDS=900


def _frame_patch(db,shot,index,fields):
    frames=json.loads(shot.keyframes or '[]');plan=json.loads(shot.video_director_plan or '{}')
    old_frames,old_plan=shot.keyframes,shot.video_director_plan
    frames[index].update(fields)
    plan_index=frames[index].get('plan_keyframe_index')
    if plan_index is not None:
        matches=[f for f in plan.get('keyframes',[]) if f.get('index')==plan_index]
        if len(matches)!=1:raise RuntimeError('PLAN_TARGET_CHANGED')
        matches[0].update(fields)
    values={'keyframes':json.dumps(frames,ensure_ascii=False)}
    if plan_index is not None:
        values.update(video_director_plan=json.dumps(plan,ensure_ascii=False),video_director_plan_revision=(shot.video_director_plan_revision or 0)+1)
    if db.query(Shot).filter_by(id=shot.id,keyframes=old_frames,video_director_plan=old_plan).update(values,synchronize_session=False)!=1:
        raise RuntimeError('KEYFRAME_PUBLICATION_CONFLICT')
    db.expire(shot)


def _submission_graph(inputs, uploads, prompt, task_id):
    graph=deepcopy(inputs['workflow']['graph']);mapping=inputs['workflow']['mapping'];nodes=inputs['workflow']['reference_nodes']
    WorkflowBuilder()._set_prompt(graph,str(mapping['prompt_node_id']),prompt)
    for node,receipt in zip(nodes,uploads):graph[node]['inputs']['image']=receipt['filename']
    graph[str(mapping['save_image_node_id'])]['inputs']['filename_prefix']='rsa-'+task_id
    proof=inspect_graph(graph,mapping,nodes,filenames=[u['filename'] for u in uploads],prompt=prompt)
    return graph,proof


def settle_terminal(db,task):
    row=db.get(Attempt,task.id)
    if row and row.status in {'PENDING','RUNNING'} and task.status in {'failed','cancelled'}:
        execution=deepcopy(row.execution)
        if execution.get('review_finding',{}).get('id'):
            finding=upsert_review_finding(db,task.id,code='UNBOUND_ASSET_REFERENCE',fallback_outcome='FAILED',terminal=True,commit=False)
            execution['review_finding']['fallback_outcome']=finding['fallback_outcome'];row.execution=execution
        row.status,row.error,row.completed_at='FAILED',task.error_message or 'TASK_TERMINATED',datetime.utcnow()
        shot=db.get(Shot,row.shot_id)
        if shot and row.stage=='SHOT' and shot.image_task_id==task.id:
            shot.image_status='failed'
        elif shot and row.stage=='KEYFRAME':
            frames=json.loads(shot.keyframes or '[]')
            if row.frame_index<len(frames) and frames[row.frame_index].get('image_task_id')==task.id:
                _frame_patch(db,shot,row.frame_index,{'image_status':'failed'})


def failed_unacknowledged_attempt_ids(db,parent_task_id=None,limit=None,now=None):
    cutoff=(now or datetime.utcnow())-timedelta(seconds=ADOPTION_RECOVERY_SECONDS)
    query=(db.query(Attempt).join(Task,Task.id==Attempt.id)
        .filter(Attempt.status=='FAILED',Attempt.error==UNACKNOWLEDGED_ERROR,
            Attempt.artifact_id.is_(None),Attempt.completed_at>=cutoff,
            Task.status=='failed',Task.error_message==UNACKNOWLEDGED_ERROR))
    if parent_task_id is not None:query=query.filter(Task.parent_task_id==parent_task_id)
    result=[]
    for row in query.order_by(Attempt.created_at,Attempt.id).all():
        if (row.execution or {}).get('submit',{}).get('state')=='ATTEMPTED':
            result.append(row.id)
            if limit is not None and len(result)>=limit:break
    return result


def completed_unreceipted_adoption_ids(db,parent_task_id=None,limit=None,now=None):
    cutoff=(now or datetime.utcnow())-timedelta(seconds=ADOPTION_RECOVERY_SECONDS)
    query=(db.query(Attempt).join(Task,Task.id==Attempt.id)
        .filter(Attempt.status=='SUCCEEDED',Attempt.artifact_id.is_not(None),
            Attempt.completed_at>=cutoff,Task.status=='completed',Task.parent_task_id.is_not(None)))
    if parent_task_id is not None:query=query.filter(Task.parent_task_id==parent_task_id)
    result=[]
    for row in query.order_by(Attempt.completed_at,Attempt.id).all():
        adoption=(row.execution or {}).get('adoption') or {};task=db.get(Task,row.id);parent=db.get(Task,task.parent_task_id)
        receipt=(json.loads(parent.metadata_json or '{}').get('verified_resume') or {}) if parent else {}
        if (adoption.get('version')=='rsa-media-verified-adoption-v1'
                and row.id not in (receipt.get('recoveredTaskIds') or [])):
            result.append(row.id)
            if limit is not None and len(result)>=limit:break
    return result


def rsa_recovery_attempt_ids(db,parent_task_id,limit=8):
    result=failed_unacknowledged_attempt_ids(db,parent_task_id=parent_task_id,limit=limit)
    if len(result)<limit:
        rows=(db.query(Attempt).join(Task,Task.id==Attempt.id)
            .filter(Attempt.status=='RUNNING',Task.status=='running',Task.parent_task_id==parent_task_id)
            .order_by(Attempt.created_at,Attempt.id).all())
        for row in rows:
            if (row.execution or {}).get('submit',{}).get('state') in {'ATTEMPTED','SUBMITTED'}:
                result.append(row.id)
                if len(result)>=limit:break
    if len(result)<limit:
        for task_id in completed_unreceipted_adoption_ids(db,parent_task_id=parent_task_id,limit=limit-len(result)):
            if task_id not in result:result.append(task_id)
    return result


def _recoverable_video_batch_parent(parent):
    return bool(parent and parent.type=='shot_video_batch' and parent.status=='failed'
        and parent.error_message in RECOVERABLE_VIDEO_BATCH_ERRORS)


class RsaImageService:
    def __init__(self,db,*,llm=None,client=None,memo=None):
        self.db,self.llm,self.client=db,llm,client
        self.memo=memo or contract.ValidationMemo()

    def enqueue(self,shot_id,*,stage='SHOT',frame_index=-1,workflow_id=None,workflow_type=None,prompt_text=None,
                skip_prompt=False,rsa_id=None,rsa_hash=None,parent_task_id=None,batch_order=None):
        db=self.db;shot=db.get(Shot,shot_id)
        if stage not in {'SHOT','KEYFRAME'} or (stage=='SHOT' and frame_index!=-1):raise HTTPException(422,'INVALID_RSA_MEDIA_TARGET')
        if not shot:raise HTTPException(404,'分镜不存在')
        from app.services.chapter_governance import require_source
        require_source(db,shot_id)
        intent={'workflow_id':workflow_id,'workflow_type':workflow_type,'prompt_text':prompt_text,'skip_prompt':bool(skip_prompt),'parent_task_id':parent_task_id}
        primary=parent=source_kind=target=None
        if stage=='KEYFRAME':
            target=snapshot_target(shot,frame_index)
            primary=contract.current_primary(db,shot)
            if rsa_id and (rsa_id!=primary.rsa_id or rsa_hash!=primary.data['rsa_hash']):raise HTTPException(409,'RSA_PRIMARY_MANIFEST_CONFLICT')
            rsa_id,rsa_hash=primary.rsa_id,primary.data['rsa_hash']
        rsa=contract.pin_rsa(db,shot.id,rsa_id,rsa_hash,memo=self.memo)
        if primary:parent,source_kind=contract.keyframe_parent(db,shot,frame_index,target,primary)
        if parent_task_id:
            owner=db.get(Task,parent_task_id)
            if (not owner or owner.status not in {'pending','running'} or owner.novel_id!=rsa.novel_id
                    or json.loads(owner.metadata_json or '{}').get('execution_purpose','production')!='production'):
                raise HTTPException(409,'PARENT_TASK_NOT_ACTIVE')
        active=db.query(Attempt).filter(Attempt.shot_id==shot_id,Attempt.stage==stage,Attempt.frame_index==frame_index,Attempt.status.in_(['PENDING','RUNNING'])).first()
        if active:
            t=db.get(Task,active.id)
            if t and t.status in {'pending','running'} and active.rsa_id==rsa.id and active.rsa_hash==rsa.result_hash:
                if active.inputs.get('request')!=intent or (stage=='KEYFRAME' and target_semantics(target)!=target_semantics(active.inputs['target'])):
                    raise HTTPException(409,'TARGET_HAS_DIFFERENT_ACTIVE_INTENT')
                return {'success':True,'data':{'taskId':t.id,'task_id':t.id,'status':t.status,'rsaId':rsa.id,'reused':True}}
            if t:settle_terminal(db,t)
            else:active.status,active.error='FAILED','TASK_MISSING'
            db.commit()
            if active.status in {'PENDING','RUNNING'}:raise HTTPException(409,'TARGET_HAS_DIFFERENT_ACTIVE_RSA')
        manifest=contract.planned_manifest(rsa,stage,parent,source_kind)
        kinds=[m['type'] for m in manifest]
        expected='keyframe_image' if stage=='KEYFRAME' else {('MERGED_CHARACTER','SCENE','MERGED_PROP'):'shot',('MERGED_CHARACTER','SCENE'):'shot_character_scene',('SCENE','MERGED_PROP'):'shot_scene_prop',('SCENE',):'shot_scene'}[tuple(kinds)]
        if workflow_type and workflow_type!=expected:raise HTTPException(409,'WORKFLOW_REFERENCE_PROFILE_MISMATCH')
        wf=db.get(Workflow,workflow_id) if workflow_id else db.query(Workflow).filter_by(type=expected,is_active=True).first()
        if not wf or wf.type!=expected or not wf.is_active:raise HTTPException(409,'RSA_MEDIA_WORKFLOW_REQUIRED: '+expected)
        mapping=json.loads(wf.node_mapping or '{}')
        keys={'MERGED_CHARACTER':'character_reference_image_node_id','SCENE':'scene_reference_image_node_id','MERGED_PROP':'prop_reference_image_node_id'}
        required=['reference_image_node_id'] if stage=='KEYFRAME' else [keys[m['type']] for m in manifest]
        for field in required:
            if not isinstance(mapping.get(field),str) or not mapping[field].strip():
                raise HTTPException(409,{'code':'RSA_WORKFLOW_REFERENCE_MAPPING_REQUIRED','workflowId':wf.id,'field':field})
        nodes=[str(mapping['reference_image_node_id'])] if stage=='KEYFRAME' else [str(mapping[keys[m['type']]]) for m in manifest]
        novel=db.get(Novel,rsa.novel_id);aspect=novel.aspect_ratio or '16:9'
        seed=secrets.randbits(52)
        graph=prepare_graph(json.loads(wf.workflow_json),mapping,nodes,aspect,seed)
        template_type='shot_image_prompt' if stage=='SHOT' else 'keyframe_image_prompt'
        template_id=getattr(novel,template_type+'_template_id')
        template=db.get(PromptTemplate,template_id) if template_id else db.query(PromptTemplate).filter_by(type=template_type,is_system=True,is_active=True).first()
        if not template or template.type!=template_type or not template.is_active:raise HTTPException(409,'RSA_MEDIA_TEMPLATE_REQUIRED')
        source=db.get(ChapterShotSplitRun,rsa.inputs['logical']['source']['split_run_id'])
        policy=contract.policy()
        if stage=='SHOT':
            old_task,old_image,old_status=shot.image_task_id,shot.image_url,shot.image_status
            target={'shot_id':shot.id,'image_url':old_image,'image_task_id':old_task,'image_status':old_status}
        elif skip_prompt:
            values=[d['value'] for d in target['draft'].values() if d['present']]
            if not values or any(v!=values[0] for v in values):raise HTTPException(409,'VERIFIED_KEYFRAME_PROMPT_REQUIRED_USE_LLM_PLUS')
            prompt_text=values[0]
        effective_source = require_source(db, shot.id)
        context={'shot':deepcopy(effective_source.snapshot), 'resolved_assets':deepcopy(rsa.data),
                 'logical_assets':deepcopy(rsa.inputs['logical']), 'visual_style':deepcopy(source.inputs['basis']['style']['text']),
                 'aspect_ratio':aspect,'workflow_prompt_prefix':inspect_graph(graph,mapping,nodes)['effective_prompt']}
        for key in ('characters','props','dialogues'):context['shot'][key]=json.loads(context['shot'][key])
        if stage=='KEYFRAME':context.update(current_keyframe=target['current_state'],previous_keyframe_state_text=target['previous_state_text'])
        parents=([{'kind':'ARTIFACT','id':parent.id,'seal':parent.seal}] if parent else
                 [{'kind':'IMAGE_VERSION','reference':deepcopy(ref)} for m in manifest for ref in m['references']])
        inputs={'version':contract.VERSION,'novel_id':rsa.novel_id,'chapter_id':rsa.chapter_id,'shot_id':shot.id,'stage':stage,'frame_index':frame_index,
            'request':intent,
            'rsa_id':rsa.id,'rsa_hash':rsa.result_hash,'target':target,'primary_artifact_id':primary.id if primary else None,
            'manifest':manifest,'parents':parents,'context':context,'policy':policy,'seed':seed,
            'template':{'id':template.id,'name':template.name,'source_hash':digest(template.template),'text':template.template+policy['definition']['system_suffix']},
            'workflow':{'id':wf.id,'name':wf.name,'type':wf.type,'graph':graph,'mapping':mapping,'reference_nodes':nodes},
            'endpoint':frozen_keyframe_client(ComfyUIClient().base_url).base_url,'parent_task_id':parent_task_id}
        cache_data={k:inputs[k] for k in ('version','rsa_id','rsa_hash','manifest','context','policy','template','workflow')}
        cache_data=deepcopy(cache_data)
        graph_without_seed=cache_data['workflow']['graph'];inspection=inspect_graph(graph_without_seed,mapping,nodes)
        graph_without_seed[inspection['seed_node']]['inputs'][inspection['seed_field']]=0
        inputs['prompt_cache_key']=digest(cache_data)
        reused=None
        if prompt_text is not None:
            for candidate in db.query(Attempt).filter_by(shot_id=shot_id,stage=stage,frame_index=frame_index).order_by(Attempt.created_at.desc()):
                p=candidate.execution.get('prompt') or {}
                if candidate.inputs.get('prompt_cache_key')==inputs['prompt_cache_key'] and p.get('text')==prompt_text and p.get('validated'):
                    log=db.get(LLMLog,p.get('llm_log_id')) if p.get('llm_log_id') else None
                    if log and log.status=='success' and log.response==p.get('raw_response') and digest(candidate.inputs)==candidate.input_hash:
                        contract.verify_prompt_record(db,{**inputs,'prompt_log_contract':candidate.inputs.get('prompt_log_contract')},p)
                        reused=deepcopy(p);reused['reused_from']=candidate.id;break
            if not reused:raise HTTPException(409,'PROMPT_RSA_BINDING_UNVERIFIED_USE_LLM_PLUS')
        inputs['reused_prompt']=reused
        inputs['prompt_log_contract']=reused.get('input_log_contract') if reused else contract.PROMPT_LOG_CONTRACT
        tid=str(uuid4());task=Task(id=tid,type='shot_image' if stage=='SHOT' else 'keyframe_image',status='pending',
            name=f"{'主分镜图' if stage=='SHOT' else '关键帧'} RSA生成：{shot.index}/{frame_index}",novel_id=rsa.novel_id,chapter_id=rsa.chapter_id,shot_id=shot.id,
            workflow_id=wf.id,workflow_name=wf.name,parent_task_id=parent_task_id,batch_order=batch_order,current_step='等待冻结RSA图像工作队列',
            metadata_json=json.dumps({'execution_purpose':'production','rsa_media_attempt':tid,'rsa_id':rsa.id,'rsa_hash':rsa.result_hash,'input_hash':digest(inputs)}))
        row=Attempt(id=tid,novel_id=rsa.novel_id,chapter_id=rsa.chapter_id,shot_id=shot.id,stage=stage,frame_index=frame_index,rsa_id=rsa.id,rsa_hash=rsa.result_hash,
            status='PENDING',inputs=inputs,input_hash=digest(inputs),execution={'phase':'PENDING'})
        db.add_all([task,row])
        try:
            if stage=='SHOT':
                if db.query(Shot).filter_by(id=shot.id,image_task_id=old_task,image_url=old_image,image_status=old_status).update({'image_task_id':tid,'image_status':'generating'},synchronize_session=False)!=1:
                    raise RuntimeError('SHOT_IMAGE_ADMISSION_CONFLICT')
            else:_frame_patch(db,shot,frame_index,{'image_task_id':tid,'image_status':'generating'})
            db.commit()
        except Exception:
            db.rollback();raise
        return {'success':True,'data':{'taskId':tid,'task_id':tid,'status':'pending','rsaId':rsa.id,'rsaHash':rsa.result_hash,'reused':False}}

    def guard(self,task_id,token,*,dependencies=True):
        db=self.db;db.expire_all();row,task=db.get(Attempt,task_id),db.get(Task,task_id)
        if (not row or not task or row.status!='RUNNING' or task.status!='running' or task.claim_token!=token or row.claim_token!=token
                or digest(row.inputs)!=row.input_hash):raise RuntimeError('RSA_MEDIA_EXECUTION_FENCED')
        meta=json.loads(task.metadata_json or '{}')
        if (meta.get('rsa_media_attempt')!=row.id or meta.get('input_hash')!=row.input_hash or meta.get('execution_purpose')!='production'
                or task.shot_id!=row.shot_id or task.novel_id!=row.novel_id or task.chapter_id!=row.chapter_id
                or task.workflow_id!=row.inputs['workflow']['id'] or task.parent_task_id!=row.inputs['parent_task_id']):raise RuntimeError('RSA_MEDIA_TASK_BINDING_CHANGED')
        if task.parent_task_id:
            parent=db.get(Task,task.parent_task_id)
            if not parent or parent.status not in {'pending','running'}:raise RuntimeError('RSA_MEDIA_PARENT_TERMINATED')
        if row.execution.get('submit',{}).get('state')=='SUBMITTED':
            if (task.comfyui_prompt_id!=row.execution['submit']['prompt_id'] or digest(json.loads(task.workflow_json or '{}'))!=row.execution['submit']['graph_hash']
                    or task.prompt_text!=row.execution['prompt']['text']):raise RuntimeError('RSA_MEDIA_TASK_SUBMISSION_CHANGED')
        shot=db.get(Shot,row.shot_id)
        if not shot:raise RuntimeError('RSA_MEDIA_SHOT_REMOVED')
        if row.stage=='SHOT':
            if shot.image_task_id!=task_id or shot.image_status!='generating' or shot.image_url!=row.inputs['target']['image_url']:
                raise RuntimeError('RSA_MEDIA_TARGET_CHANGED')
        else:
            target=snapshot_target(shot,row.frame_index)
            expected=row.inputs['target']
            if (target_semantics(target)!=target_semantics(expected) or target['draft']!=expected['draft'] or target['images']!=expected['images']
                    or target['owners']['legacy']!=task_id or (expected['plan_keyframe_index'] is not None and target['owners']['plan']!=task_id)):
                raise RuntimeError('RSA_MEDIA_KEYFRAME_TARGET_CHANGED')
        if dependencies:
            from app.services.chapter_governance import require_source
            require_source(db,row.shot_id)
            rsa=require_frozen_rsa(db,row.shot_id,row.rsa_id,row.rsa_hash,memo=self.memo)
            contract.validate_inputs_rsa(db,row.inputs,rsa,memo=self.memo)
            if contract.policy()['hash']!=row.inputs['policy']['hash']:raise RuntimeError('RSA_MEDIA_PROMPT_POLICY_CHANGED')
            template=db.get(PromptTemplate,row.inputs['template']['id'])
            if not template or digest(template.template)!=row.inputs['template']['source_hash']:raise RuntimeError('RSA_MEDIA_TEMPLATE_CHANGED')
            if row.stage=='KEYFRAME':
                primary=contract.current_primary(db,shot)
                if primary.id!=row.inputs['primary_artifact_id']:raise RuntimeError('PRIMARY_LINEAGE_CHANGED')
                parent,kind=contract.keyframe_parent(db,shot,row.frame_index,row.inputs['target'],primary)
                if parent.id!=row.inputs['manifest'][0]['artifact_id'] or kind!=row.inputs['manifest'][0]['type']:raise RuntimeError('KEYFRAME_LINEAGE_CHANGED')
        return row,task,shot

    async def discover_submission(self,tid,inputs,execution,client,*,prompt_id=None):
        submit=execution.get('submit') or {};durable_client_id=submit.get('client_id')
        if prompt_id:
            state=await client.get_prompt_state(prompt_id)
            history=state.get('history') if state.get('state') in {'completed','history'} else None
            prompt=history.get('prompt') if isinstance(history,dict) else None
            if not isinstance(prompt,list) or len(prompt)<4 or prompt[1]!=prompt_id or not isinstance(prompt[3],dict):
                raise RuntimeError('RSA_MEDIA_ADOPTION_UNVERIFIED')
            discovered=await client.discover_prompt_by_client_id(prompt[3].get('client_id'))
            if discovered.get('state')!='found' or discovered.get('prompt_id')!=prompt_id:
                raise RuntimeError('RSA_MEDIA_ADOPTION_AMBIGUOUS' if discovered.get('state')=='ambiguous' else 'RSA_MEDIA_ADOPTION_UNVERIFIED')
        else:
            if not durable_client_id:raise RuntimeError('UNCONFIRMED_RSA_MEDIA_NOT_REPLAYED')
            discovered=await client.discover_prompt_by_client_id(durable_client_id)
            if discovered.get('state')=='ambiguous':raise RuntimeError('RSA_MEDIA_ADOPTION_AMBIGUOUS')
            if discovered.get('state')!='found':raise RuntimeError('UNCONFIRMED_RSA_MEDIA_NOT_REPLAYED')
        if durable_client_id and discovered.get('client_id')!=durable_client_id:
            raise RuntimeError('RSA_MEDIA_ADOPTION_CLIENT_MISMATCH')
        manifest=execution.get('manifest');prompt_record=execution.get('prompt');uploads=execution.get('uploads')
        if not isinstance(manifest,list) or not isinstance(prompt_record,dict) or not isinstance(uploads,list):
            raise RuntimeError('RSA_MEDIA_ADOPTION_LOCAL_EVIDENCE_MISSING')
        contract.validate_manifest(inputs,manifest,memo=self.memo)
        contract.verify_prompt_record(self.db,inputs,prompt_record,memo=self.memo)
        if len(uploads)!=len(manifest):raise RuntimeError('RSA_MEDIA_ADOPTION_UPLOAD_SET_CHANGED')
        for index,(upload,reference) in enumerate(zip(uploads,manifest),1):
            if (upload.get('picture_index')!=index or upload.get('payload_sha256')!=reference['image']['sha256']
                    or upload.get('remote_sha256')!=reference['image']['sha256']
                    or upload.get('manifest_hash')!=digest(reference)):
                raise RuntimeError('RSA_MEDIA_ADOPTION_UPLOAD_CHANGED')
        expected_graph,expected_proof=_submission_graph(inputs,uploads,prompt_record['text'],tid)
        graph=execution.get('graph');proof=execution.get('graph_proof')
        if (graph!=expected_graph or proof!=expected_proof or submit.get('graph_hash')!=digest(expected_graph)):
            raise RuntimeError('RSA_MEDIA_ADOPTION_LOCAL_GRAPH_CHANGED')
        remote_graph=discovered.get('graph')
        try:remote_proof=inspect_graph(remote_graph,inputs['workflow']['mapping'],inputs['workflow']['reference_nodes'],
            filenames=[u['filename'] for u in uploads],prompt=prompt_record['text'])
        except Exception as exc:raise RuntimeError('RSA_MEDIA_ADOPTION_GRAPH_MISMATCH') from exc
        if remote_proof!=expected_proof or semantic_graph_digest(remote_graph)!=semantic_graph_digest(expected_graph):
            raise RuntimeError('RSA_MEDIA_ADOPTION_GRAPH_MISMATCH')
        history=discovered.get('history')
        if history is not None:
            receipt=output_receipt(history,discovered['prompt_id'],expected_graph,inputs['workflow']['mapping']['save_image_node_id'])
            filename=receipt['image']['filename']
            if not filename.startswith('rsa-'+tid+'_'):
                raise RuntimeError('RSA_MEDIA_ADOPTION_OUTPUT_IDENTITY_MISMATCH')
        return discovered,expected_graph

    async def reconcile_failed_unacknowledged(self,tid,prompt_id):
        db=self.db;row,task=db.get(Attempt,tid),db.get(Task,tid)
        if (not row or not task or row.status!='FAILED' or task.status!='failed' or row.artifact_id
                or row.error!='UNCONFIRMED_RSA_MEDIA_NOT_REPLAYED' or task.error_message!=row.error
                or (row.execution or {}).get('submit',{}).get('state')!='ATTEMPTED'):
            raise RuntimeError('RSA_MEDIA_ADOPTION_NOT_ELIGIBLE')
        inputs,execution=deepcopy(row.inputs),deepcopy(row.execution);meta=json.loads(task.metadata_json or '{}')
        if (digest(inputs)!=row.input_hash or meta.get('rsa_media_attempt')!=row.id or meta.get('input_hash')!=row.input_hash
                or meta.get('execution_purpose')!='production' or task.shot_id!=row.shot_id or task.novel_id!=row.novel_id
                or task.chapter_id!=row.chapter_id or task.workflow_id!=inputs['workflow']['id']
                or task.parent_task_id!=inputs['parent_task_id'] or db.query(Artifact.id).filter_by(task_id=tid).first()):
            raise RuntimeError('RSA_MEDIA_ADOPTION_TASK_BINDING_CHANGED')
        shot=db.get(Shot,row.shot_id)
        if not shot:raise RuntimeError('RSA_MEDIA_SHOT_REMOVED')
        from app.services.chapter_governance import require_source
        require_source(db,row.shot_id)
        rsa=require_frozen_rsa(db,row.shot_id,row.rsa_id,row.rsa_hash,memo=self.memo)
        contract.validate_inputs_rsa(db,inputs,rsa,memo=self.memo)
        if row.stage=='SHOT':
            if shot.image_task_id!=tid or shot.image_status!='failed' or shot.image_url!=inputs['target']['image_url']:
                raise RuntimeError('RSA_MEDIA_ADOPTION_TARGET_CHANGED')
        else:
            target=snapshot_target(shot,row.frame_index);expected=inputs['target']
            if (target_semantics(target)!=target_semantics(expected) or target['draft']!=expected['draft']
                    or target['images']!=expected['images'] or target['owners']['legacy']!=tid
                    or (expected['plan_keyframe_index'] is not None and target['owners']['plan']!=tid)):
                raise RuntimeError('RSA_MEDIA_ADOPTION_TARGET_CHANGED')
        client=self.client or frozen_keyframe_client(inputs['endpoint'])
        discovered,graph=await self.discover_submission(tid,inputs,execution,client,prompt_id=prompt_id)
        if discovered.get('history') is None:raise RuntimeError('RSA_MEDIA_ADOPTION_RESULT_NOT_COMPLETE')
        parent=db.get(Task,task.parent_task_id) if task.parent_task_id else None
        recover_parent=_recoverable_video_batch_parent(parent)
        if parent and parent.status not in {'pending','running'} and not recover_parent:
            raise RuntimeError('RSA_MEDIA_PARENT_TERMINATED')
        old_task=(task.status,task.claim_token,task.attempt,task.error_message,task.comfyui_prompt_id,task.metadata_json)
        old_row=(row.status,row.claim_token,row.error,deepcopy(row.execution),row.artifact_id)
        token=str(uuid4());now=datetime.utcnow()
        execution['submit'].update(state='SUBMITTED',prompt_id=discovered['prompt_id'],ack_source='DISCOVERY_V1')
        execution['phase']='SUBMITTED';execution['adoption']={
            'version':'rsa-media-verified-adoption-v1','client_id':discovered['client_id'],
            'prompt_id':discovered['prompt_id'],'locations':discovered['locations'],
            'graph_hash':digest(graph),'semantic_graph_hash':semantic_graph_digest(graph),
            'reconciled_at':now.isoformat()}
        parent_count=1
        if recover_parent:
            conditions=[getattr(Task,column.key)==getattr(parent,column.key) for column in Task.__table__.columns
                if column.key not in {'created_at','updated_at'}]
            parent_count=db.query(Task).filter(*conditions).update({'status':'running','error_message':None,
                'completed_at':None,'current_step':'Verified child adoption in progress','heartbeat_at':now},
                synchronize_session=False)
        task_count=db.query(Task).filter(Task.id==tid,Task.status==old_task[0],Task.claim_token==old_task[1],
            Task.attempt==old_task[2],Task.error_message==old_task[3],Task.comfyui_prompt_id.is_(None),
            Task.metadata_json==old_task[5]).update({'status':'running','claim_token':token,'worker_id':WORKER_ID,
                'heartbeat_at':now,'attempt':old_task[2]+1,'error_message':None,'completed_at':None,
                'current_step':'已验证远端提交，继续回收结果','comfyui_prompt_id':discovered['prompt_id'],
                'workflow_json':json.dumps(graph,ensure_ascii=False)},synchronize_session=False)
        row_count=db.query(Attempt).filter(Attempt.id==tid,Attempt.status==old_row[0],Attempt.claim_token==old_row[1],
            Attempt.error==old_row[2],Attempt.execution==old_row[3],Attempt.artifact_id.is_(None)).update({
                'status':'RUNNING','claim_token':token,'error':None,'completed_at':None,'execution':execution},synchronize_session=False)
        if parent_count!=1 or task_count!=1 or row_count!=1:
            db.rollback();raise RuntimeError('RSA_MEDIA_ADOPTION_FENCED')
        db.expire_all();shot=db.get(Shot,row.shot_id)
        if row.stage=='SHOT':shot.image_status='generating'
        else:_frame_patch(db,shot,row.frame_index,{'image_task_id':tid,'image_status':'generating'})
        db.commit()
        await self.execute(tid,token,recover=True)
        db.expire_all();row,task=db.get(Attempt,tid),db.get(Task,tid)
        if not row or row.status!='SUCCEEDED' or not task or task.status!='completed' or not row.artifact_id:
            raise RuntimeError('RSA_MEDIA_ADOPTION_PUBLICATION_FAILED')
        authorize_completed_adoption(db,tid)
        return {'taskId':tid,'promptId':discovered['prompt_id'],'artifactId':row.artifact_id,
            'status':row.status,'adoption':execution['adoption']}

    def save(self,tid,token,execution,step,*,review_finding=None,**fields):
        self.guard(tid,token,dependencies=False)
        finding=None
        if review_finding:
            finding=upsert_review_finding(self.db,tid,code='UNBOUND_ASSET_REFERENCE',claim_token=token,commit=False,**review_finding)
            execution['review_finding']={'id':finding['id'],'fallback_outcome':finding['fallback_outcome']}
        now=datetime.utcnow()
        task_values={'current_step':step,'heartbeat_at':now,**fields}
        if self.db.query(Task).filter_by(id=tid,status='running',claim_token=token).update(
                task_values,synchronize_session=False)!=1:
            self.db.rollback();raise RuntimeError('RSA_MEDIA_EXECUTION_FENCED')
        if self.db.query(Attempt).filter_by(id=tid,status='RUNNING',claim_token=token).update(
                {'execution':deepcopy(execution)},synchronize_session=False)!=1:
            self.db.rollback();raise RuntimeError('RSA_MEDIA_EXECUTION_FENCED')
        self.db.commit()
        return finding

    async def waiting(self,awaitable,tid,token):
        job=asyncio.ensure_future(awaitable)
        try:
            while True:
                done,_=await asyncio.wait({job},timeout=15)
                if done:return job.result()
                _,task,_=self.guard(tid,token);task.heartbeat_at=datetime.utcnow();self.db.commit()
        finally:
            if not job.done():
                job.cancel()
                try:await job
                except BaseException:pass

    def fail(self,tid,token,execution,error):
        db=self.db;db.rollback();row,task=db.get(Attempt,tid),db.get(Task,tid)
        if not row or row.claim_token!=token or row.status=='SUCCEEDED':return
        if task and execution.get('review_finding',{}).get('id'):
            try:
                finding=upsert_review_finding(db,tid,code='UNBOUND_ASSET_REFERENCE',fallback_outcome='FAILED',claim_token=token,commit=False)
                execution['review_finding']['fallback_outcome']=finding['fallback_outcome']
            except ExecutionConflict:
                db.rollback();return
        row.execution,row.error,row.status,row.completed_at=deepcopy(execution),str(error),'FAILED',datetime.utcnow()
        if task and task.claim_token==token:
            if task.status in {'pending','running'}:
                task.status,task.error_message,task.current_step,task.completed_at='failed',str(error),'RSA图像生成失败',datetime.utcnow()
            if execution.get('submit',{}).get('prompt_id'):task.comfyui_prompt_id=execution['submit']['prompt_id']
        shot=db.get(Shot,row.shot_id)
        if shot and row.stage=='SHOT' and shot.image_task_id==tid:shot.image_status='failed'
        elif shot and row.stage=='KEYFRAME':
            frames=json.loads(shot.keyframes or '[]')
            if row.frame_index<len(frames) and frames[row.frame_index].get('image_task_id')==tid:_frame_patch(db,shot,row.frame_index,{'image_status':'failed'})
        db.commit()

    async def execute(self,tid,token,*,recover=False):
        row=self.db.get(Attempt,tid);inputs,execution=deepcopy(row.inputs),deepcopy(row.execution)
        frozen_attempt_input_hash=row.input_hash
        client=self.client or frozen_keyframe_client(inputs['endpoint'])
        try:
            self.guard(tid,token)
            if not recover:
                manifest=contract.build_reference_files(self.db,inputs,tid,memo=self.memo);contract.validate_manifest(inputs,manifest,memo=self.memo)
                execution.update(phase='REFERENCES_READY',manifest=manifest,manifest_hash=digest(manifest))
                self.save(tid,token,execution,'冻结实际参考图',reference_images=json.dumps([{'label':m['type'],'url':m['image']['url']} for m in manifest],ensure_ascii=False))
                if inputs['reused_prompt']:
                    prompt_record=deepcopy(inputs['reused_prompt']);prompt=prompt_record['text']
                else:
                    payload={**inputs['context'],'rsa_id':inputs['rsa_id'],'rsa_hash':inputs['rsa_hash'],'reference_image_manifest':manifest}
                    user=inputs['policy']['definition']['user_template'].format_map({'payload':json.dumps(payload,ensure_ascii=False)})
                    content=[{'type':'text','text':user}]
                    for m in manifest:
                        raw,info=contract.files.image_bytes(m['image']['url'],IMAGE_POLICY,memo=self.memo)
                        mime={'PNG':'image/png','JPEG':'image/jpeg','WEBP':'image/webp'}[info['format']]
                        content.append({'type':'image_url','image_url':{'url':f'data:{mime};base64,'+base64.b64encode(raw).decode()}})
                    task_type='shot_image_prompt' if inputs['stage']=='SHOT' else 'keyframe_image_prompt'
                    llm_request={'system_prompt':inputs['template']['text'],'user_content':content,'response_format':'json_object',
                        'temperature':0.2,'max_tokens':4096,'task_type':task_type,'prompt_template_name':inputs['template']['name'],
                        'novel_id':inputs['novel_id'],'chapter_id':inputs['chapter_id']}
                    frozen_llm_input_hash=digest(llm_request)
                    execution.update(phase='PROMPT_BUILDING',llm_input={'system':inputs['template']['text'],'user':user,
                        'manifest_hash':digest(manifest),'frozen_input_hash':frozen_llm_input_hash},prompt_attempts=[])
                    self.save(tid,token,execution,'检查RSA冲突并构建提示词')
                    llm=self.llm or LLMService()
                    for ordinal in (1,2):
                        if ordinal==2:
                            current,_,_=self.guard(tid,token)
                            if (current.input_hash!=frozen_attempt_input_hash or current.inputs!=inputs
                                    or current.execution.get('manifest')!=manifest
                                    or current.execution.get('manifest_hash')!=digest(manifest)
                                    or digest(llm_request)!=frozen_llm_input_hash):
                                raise RuntimeError('RSA_MEDIA_FALLBACK_INPUTS_CHANGED')
                            contract.validate_manifest(inputs,manifest,memo=self.memo)
                        prompt_attempt={'ordinal':ordinal,'state':'STARTED','frozen_input_sha256':frozen_llm_input_hash}
                        execution['prompt_attempts'].append(prompt_attempt)
                        self.save(tid,token,execution,f'调用RSA提示词模型 {ordinal}/2')
                        try:
                            response=await self.waiting(llm.chat_completion(**deepcopy(llm_request)),tid,token)
                        except Exception as exc:
                            prompt_attempt.update(state='FAILED',code='RSA_MEDIA_LLM_CALL_FAILED',message=str(exc))
                            raise
                        raw_response=response.get('content')
                        prompt_attempt.update({'state':'RECEIVED','llm_log_id':response.get('llm_log_id'),
                            'response_sha256':hashlib.sha256(raw_response.encode('utf-8')).hexdigest() if isinstance(raw_response,str) else None,
                            'raw_response':raw_response,'response':deepcopy(response)})
                        execution['llm_response']=deepcopy(response)
                        self.save(tid,token,execution,'校验RSA提示词输出')
                        if not response.get('success'):
                            prompt_attempt.update(state='FAILED',code='RSA_MEDIA_LLM_FAILED',message=str(response.get('error') or 'RSA_MEDIA_LLM_FAILED'))
                            raise RuntimeError(response.get('error') or 'RSA_MEDIA_LLM_FAILED')
                        log=self.db.get(LLMLog,response.get('llm_log_id')) if response.get('llm_log_id') else None
                        if (not log or log.status!='success' or log.response!=response.get('content') or log.system_prompt!=inputs['template']['text']
                                or log.novel_id!=inputs['novel_id'] or log.chapter_id!=inputs['chapter_id'] or json.loads(log.user_prompt)[0]!={'type':'text','text':user}):
                            prompt_attempt.update(state='FAILED',code='RSA_MEDIA_LLM_LOG_UNVERIFIED',message='RSA_MEDIA_LLM_LOG_UNVERIFIED')
                            raise RuntimeError('RSA_MEDIA_LLM_LOG_UNVERIFIED')
                        request_info_hash=digest(json.loads(log.request_info or '{}'))
                        prompt_attempt.update(state='LOG_VERIFIED',llm_log_id=log.id,request_info_hash=request_info_hash)
                        try:
                            prompt=contract.parse_prompt(response['content'],len(manifest),manifest[0]['type'] if inputs['stage']=='KEYFRAME' else None)
                        except KeyframeReferenceError as exc:
                            prompt_attempt.update(state='REJECTED',code=exc.code,message=str(exc))
                            if inputs['stage']=='KEYFRAME' and ordinal==1 and exc.code=='UNBOUND_ASSET_REFERENCE':
                                finding_evidence={'attempt_execution_path':'RsaImageAttempt.execution.prompt_attempts[0]',
                                    'first_failed_llm_log_id':log.id,'first_response_sha256':prompt_attempt['response_sha256'],
                                    'frozen_input_sha256':frozen_llm_input_hash,'manifest_sha256':execution['manifest_hash'],
                                    'rsa_hash':inputs['rsa_hash'],'template_sha256':inputs['template']['source_hash']}
                                self.save(tid,token,execution,'未绑定资产引用，使用相同冻结输入重试一次',review_finding={
                                    'message':'Fresh keyframe prompt contained an asset reference not bound to the frozen manifest.',
                                    'evidence':finding_evidence,'fallback_outcome':'PENDING'})
                                continue
                            raise
                        except Exception as exc:
                            prompt_attempt.update(state='REJECTED',code=str(exc).split(':',1)[0],message=str(exc))
                            raise
                        prompt_attempt.update(state='VALIDATED',prompt_sha256=hashlib.sha256(prompt.encode('utf-8')).hexdigest())
                        prompt_record={'text':prompt,'validated':True,'llm_log_id':log.id,'raw_response':response['content'],'cache_key':inputs['prompt_cache_key'],
                            'system_prompt':log.system_prompt,'logged_user_prompt':log.user_prompt,'payload':payload,
                            'input_log_contract':inputs.get('prompt_log_contract'),'request_info_hash':request_info_hash}
                        execution['prompt']=prompt_record
                        self.save(tid,token,execution,'RSA提示词校验通过')
                        break
                execution['prompt']=prompt_record
                self.guard(tid,token);contract.validate_manifest(inputs,manifest,memo=self.memo);contract.verify_prompt_record(self.db,inputs,prompt_record,memo=self.memo)
                uploads=[]
                for index,m in enumerate(manifest,1):
                    raw,info=contract.files.image_bytes(m['image']['url'],IMAGE_POLICY,memo=self.memo)
                    receipt=await self.waiting(client.upload_image(contract.files.url_to_local_path(info['url']),upload_name=f'rsa-{tid}-{index}.png',payload=raw),tid,token)
                    if not receipt.get('success') or receipt.get('payload_sha256')!=info['sha256'] or receipt.get('payload_size')!=len(raw):raise RuntimeError('RSA_MEDIA_UPLOAD_UNVERIFIED')
                    async with client._client() as http:
                        remote=await self.waiting(http.get(receipt_url(inputs['endpoint'],{'filename':receipt['filename'].rsplit('/',1)[-1],'subfolder':receipt['subfolder'],'type':'input'}),timeout=30),tid,token)
                        remote.raise_for_status()
                    if hashlib.sha256(remote.content).hexdigest()!=info['sha256']:raise RuntimeError('RSA_MEDIA_REMOTE_REFERENCE_CHANGED')
                    uploads.append({**receipt,'remote_sha256':info['sha256'],'picture_index':index,'manifest_hash':digest(m)})
                    execution['uploads']=deepcopy(uploads)
                    self.save(tid,token,execution,f'已验证参考图上传 {index}/{len(manifest)}')
                graph,proof=_submission_graph(inputs,uploads,prompt,tid);nodes=inputs['workflow']['reference_nodes']
                if inputs['stage']=='KEYFRAME':
                    contract.validate_reference_prompt(proof['effective_prompt'],inputs['manifest'][0]['type'])
                elif set(re.findall(r'<Picture\s+(\d+)>',proof['effective_prompt']))!={str(i) for i in range(1,len(nodes)+1)}:
                    raise RuntimeError('WORKFLOW_PROMPT_MANIFEST_CONFLICT')
                execution.update(phase='SUBMITTING',uploads=uploads,graph=graph,graph_proof=proof,
                    submit={'state':'ATTEMPTED','graph_hash':digest(graph),'client_id':client.client_id})
                self.save(tid,token,execution,'提交冻结RSA图像工作流',prompt_text=prompt)
                self.guard(tid,token);contract.validate_manifest(inputs,manifest,memo=self.memo)
                contract.verify_prompt_record(self.db,inputs,prompt_record,memo=self.memo)
                queued=await self.waiting(client.queue_prompt(graph),tid,token)
                if not queued.get('success') or not isinstance(queued.get('prompt_id'),str) or not queued['prompt_id'].strip():
                    execution['submit']['state']='UNKNOWN';raise RuntimeError('RSA_MEDIA_SUBMISSION_UNCONFIRMED')
                execution['submit'].update(state='SUBMITTED',prompt_id=queued['prompt_id'],ack_source='QUEUE_RESPONSE');execution['phase']='SUBMITTED'
                try:
                    self.save(tid,token,execution,'ComfyUI生成中',comfyui_prompt_id=queued['prompt_id'],workflow_json=json.dumps(graph,ensure_ascii=False))
                except OperationalError:
                    # Remote admission may already be durable. Leave the last local
                    # ATTEMPTED envelope intact for stale-owner verified discovery.
                    self.db.rollback();return
            else:
                submit_state=execution.get('submit',{}).get('state')
                if submit_state=='ATTEMPTED':
                    discovered,graph=await self.discover_submission(tid,inputs,execution,client)
                    execution['submit'].update(state='SUBMITTED',prompt_id=discovered['prompt_id'],ack_source='DISCOVERY_V1')
                    execution['phase']='SUBMITTED';execution['adoption']={
                        'version':'rsa-media-verified-adoption-v1','client_id':discovered['client_id'],
                        'prompt_id':discovered['prompt_id'],'locations':discovered['locations'],
                        'graph_hash':digest(graph),'semantic_graph_hash':semantic_graph_digest(graph)}
                    self.save(tid,token,execution,'已验证远端提交，继续回收结果',comfyui_prompt_id=discovered['prompt_id'],workflow_json=json.dumps(graph,ensure_ascii=False))
                elif submit_state=='SUBMITTED':
                    graph=execution['graph']
                    if recover:
                        execution['adoption']={'version':'rsa-media-verified-adoption-v1',
                            'source':'ACKNOWLEDGED_RESTART','client_id':execution['submit'].get('client_id'),
                            'prompt_id':execution['submit']['prompt_id'],'graph_hash':digest(graph),
                            'semantic_graph_hash':semantic_graph_digest(graph)}
                else:raise RuntimeError('UNCONFIRMED_RSA_MEDIA_NOT_REPLAYED')
                if digest(graph)!=execution['submit']['graph_hash']:raise RuntimeError('RSA_MEDIA_SAVED_GRAPH_CHANGED')
                contract.validate_manifest(inputs,execution['manifest'],memo=self.memo)
            cid=execution['submit']['prompt_id'];deadline=asyncio.get_running_loop().time()+7200;missing=None
            while True:
                self.guard(tid,token)
                state=await self.waiting(client.get_prompt_state(cid),tid,token)
                if state.get('state')=='completed':
                    receipt=output_receipt(state['history'],cid,graph,inputs['workflow']['mapping']['save_image_node_id']);break
                missing=(missing or asyncio.get_running_loop().time()) if state.get('state')=='missing' else None
                if state.get('state')=='error' or (missing and asyncio.get_running_loop().time()-missing>60):raise RuntimeError('RSA_MEDIA_REMOTE_JOB_FAILED_OR_MISSING')
                if asyncio.get_running_loop().time()>deadline:raise RuntimeError('RSA_MEDIA_TIMEOUT')
                _,task,_=self.guard(tid,token);task.heartbeat_at=datetime.utcnow();self.db.commit();await asyncio.sleep(2)
            async with client._client() as http:
                remote=await self.waiting(http.get(receipt_url(inputs['endpoint'],receipt['image']),timeout=60),tid,token);remote.raise_for_status()
            contract.files.inspect_image(remote.content,IMAGE_POLICY,memo=self.memo)
            if len(remote.content)>IMAGE_POLICY['max_source_bytes']:raise RuntimeError('RSA_MEDIA_OUTPUT_TOO_LARGE')
            receipt['remote_sha256']=hashlib.sha256(remote.content).hexdigest()
            path=contract.artifact_dir(inputs['novel_id'],tid)/'result.png'
            if not path.exists():
                with path.open('xb') as out:out.write(remote.content)
            _,image=contract.files.image_bytes(contract.files.local_path_to_url(str(path)),IMAGE_POLICY,memo=self.memo)
            if image['sha256']!=receipt['remote_sha256']:raise RuntimeError('RSA_MEDIA_OUTPUT_BYTES_CHANGED')
            execution.update(phase='OUTPUT_VERIFIED',receipt=receipt,image=image)
            self.save(tid,token,execution,'发布RSA图像与lineage')
            if self.db.query(Attempt).filter_by(id=tid,status='RUNNING',claim_token=token).update({'status':'RUNNING'},synchronize_session=False)!=1:raise RuntimeError('RSA_MEDIA_PUBLICATION_FENCED')
            row,task,shot=self.guard(tid,token)
            contract.validate_manifest(inputs,execution['manifest'],memo=self.memo)
            contract.verify_prompt_record(self.db,inputs,execution['prompt'],memo=self.memo)
            aid=str(uuid4());data={'id':aid,'task_id':tid,'shot_id':row.shot_id,'stage':row.stage,'frame_index':row.frame_index,'rsa_id':row.rsa_id,'rsa_hash':row.rsa_hash,
                'input_hash':row.input_hash,'image':image,'parents':inputs['parents'],'manifest':execution['manifest'],'receipt':receipt}
            artifact=Artifact(id=aid,task_id=tid,shot_id=row.shot_id,rsa_id=row.rsa_id,stage=row.stage,frame_index=row.frame_index,data=data,seal=digest(data))
            self.db.add(artifact)
            if row.stage=='SHOT':
                shot.image_url,shot.image_path,shot.image_status,shot.shot_image_prompt=image['url'],str(path),'completed',execution['prompt']['text']
                for m in execution['manifest']:
                    if m['type']=='MERGED_CHARACTER':shot.merged_character_image=m['image']['url']
                    if m['type']=='MERGED_PROP':shot.merged_prop_image=m['image']['url']
            else:_frame_patch(self.db,shot,row.frame_index,{'image_url':image['url'],'image_task_id':tid,'image_status':'completed','prompt_text':execution['prompt']['text'],'rsa_artifact_id':aid})
            execution.update(phase='COMPLETED',artifact_id=aid)
            if execution.get('review_finding',{}).get('id'):
                finding=upsert_review_finding(self.db,tid,code='UNBOUND_ASSET_REFERENCE',fallback_outcome='SUCCEEDED',claim_token=token,commit=False)
                execution['review_finding']['fallback_outcome']=finding['fallback_outcome']
            row.status,row.artifact_id,row.completed_at='SUCCEEDED',aid,datetime.utcnow()
            row.execution=deepcopy(execution)
            task.status,task.progress,task.result_url,task.current_step,task.completed_at='completed',100,image['url'],'RSA图像与lineage已发布',datetime.utcnow()
            self.db.commit()
        except asyncio.CancelledError:
            self.db.rollback();task=self.db.get(Task,tid)
            if task and task.claim_token==token:task.heartbeat_at=datetime.utcnow()-timedelta(minutes=5);self.db.commit()
            raise
        except Exception as exc:self.fail(tid,token,execution,exc)


def authorize_completed_adoption(db,task_id):
    row,task=db.get(Attempt,task_id),db.get(Task,task_id)
    adoption=(row.execution or {}).get('adoption') if row and isinstance(row.execution,dict) else None
    if (not row or row.status!='SUCCEEDED' or not row.artifact_id or not task or task.status!='completed'
            or not task.parent_task_id or not isinstance(adoption,dict)
            or adoption.get('version')!='rsa-media-verified-adoption-v1'):
        return False
    parent=db.get(Task,task.parent_task_id);receipt=(json.loads(parent.metadata_json or '{}').get('verified_resume') or {}) if parent else {}
    if task_id in (receipt.get('recoveredTaskIds') or []):return False
    from app.api.shots import authorize_verified_video_batch_resume
    authorize_verified_video_batch_resume(db,task.parent_task_id,task.id)
    return True


async def run_next_rsa_image_task(db=None):
    from app.core.database import SessionLocal
    owned=db is None;db=db or SessionLocal()
    try:
        settle_batches(db)
        for row in db.query(Attempt).filter(Attempt.status.in_(['PENDING','RUNNING'])).all():
            task=db.get(Task,row.id)
            if task and task.status in {'failed','cancelled'}:settle_terminal(db,task);db.commit()
            elif not task:
                row.status,row.error='FAILED','TASK_REMOVED'
                shot=db.get(Shot,row.shot_id)
                if shot and row.stage=='SHOT' and shot.image_task_id==row.id:shot.image_status='failed'
                elif shot and row.stage=='KEYFRAME':
                    frames=json.loads(shot.keyframes or '[]')
                    if row.frame_index<len(frames) and frames[row.frame_index].get('image_task_id')==row.id:_frame_patch(db,shot,row.frame_index,{'image_status':'failed'})
                db.commit()
        pending=db.query(Attempt).join(Task,Task.id==Attempt.id).filter(Attempt.status=='PENDING',Task.status=='pending').order_by(Attempt.created_at).first()
        recover=False
        if pending is None:
            pending=db.query(Attempt).join(Task,Task.id==Attempt.id).filter(Attempt.status=='RUNNING',Task.status=='running',or_(Task.heartbeat_at.is_(None),Task.heartbeat_at<datetime.utcnow()-timedelta(seconds=90))).order_by(Attempt.created_at).first();recover=True
        if not pending:return False
        task=db.get(Task,pending.id);tid=task.id;old_token,old_status,old_heartbeat=task.claim_token,task.status,task.heartbeat_at;token=str(uuid4())
        if db.query(Task).filter_by(id=tid,status=old_status,claim_token=old_token,heartbeat_at=old_heartbeat).update({'status':'running','claim_token':token,'worker_id':WORKER_ID,'heartbeat_at':datetime.utcnow(),'started_at':task.started_at or datetime.utcnow(),'attempt':(task.attempt or 0)+1},synchronize_session=False)!=1:
            db.rollback();return False
        pending.status,pending.claim_token='RUNNING',token;db.commit()
        await RsaImageService(db).execute(tid,token,recover=recover)
        db.expire_all();authorize_completed_adoption(db,tid)
        settle_batches(db)
        return True
    finally:
        if owned:db.close()


async def reconcile_failed_unacknowledged_tasks(db=None,limit=None):
    from app.core.database import SessionLocal
    owned=db is None;lookup=db or SessionLocal()
    try:
        task_ids=failed_unacknowledged_attempt_ids(lookup,limit=limit)
        completed_ids=completed_unreceipted_adoption_ids(lookup,limit=limit)
    finally:
        if owned:lookup.close()
    adopted=0
    for task_id in task_ids:
        session=SessionLocal() if owned else db
        try:
            await RsaImageService(session).reconcile_failed_unacknowledged(task_id,None)
            adopted+=1
        except (HTTPException,RuntimeError,ValueError,KeyError,TypeError,OSError):
            session.rollback()
        finally:
            if owned:session.close()
    for task_id in completed_ids:
        session=SessionLocal() if owned else db
        try:
            if authorize_completed_adoption(session,task_id):adopted+=1
        except (HTTPException,RuntimeError,ValueError,KeyError,TypeError,OSError):
            session.rollback()
        finally:
            if owned:session.close()
    return adopted


def settle_batches(db):
    for parent in db.query(Task).filter(Task.type=='shot_image_batch',Task.status.in_(['pending','running'])).all():
        meta=json.loads(parent.metadata_json or '{}')
        if not meta.get('rsa_image_batch') or not meta.get('admission_complete'):continue
        children=db.query(Task).filter_by(parent_task_id=parent.id).all()
        expected=set(meta.get('task_ids',[]));missing=expected-{t.id for t in children}
        done=sum(t.status=='completed' for t in children);failed=sum(t.status in {'failed','cancelled'} for t in children)+len(missing)
        parent.progress=int((done+failed)/len(expected)*100) if expected else 100
        parent.current_step=f"READY子集：完成 {done} / 执行失败 {failed} / 准入阻断 {len(meta.get('blocked',[]))}"
        if all(t.status in {'completed','failed','cancelled'} for t in children):
            parent.status='failed' if failed else 'completed';parent.completed_at=datetime.utcnow()
            meta['result']={'completed':done,'failed':failed,'blocked':len(meta.get('blocked',[])),'scope':'REQUESTED_READY_SUBSET'}
            parent.metadata_json=json.dumps(meta,ensure_ascii=False)
        db.commit()


def enqueue_rsa_image_batch(db,novel_id,chapter_id,shot_ids,skip_existing_prompt=True):
    from app.models.novel import Chapter
    chapter=db.query(Chapter).filter_by(id=chapter_id,novel_id=novel_id).first()
    if not chapter:raise HTTPException(404,'章回不存在')
    if not shot_ids:raise HTTPException(422,'请选择Shot')
    shots=[]
    for sid in dict.fromkeys(shot_ids):
        shot=db.query(Shot).filter_by(id=sid,chapter_id=chapter_id).first()
        if not shot:raise HTTPException(404,'分镜不存在')
        shots.append(shot)
    ready,blocked=[],[]
    memo=contract.ValidationMemo()
    service=RsaImageService(db,memo=memo)
    for shot in shots:
        try:
            rsa=contract.pin_rsa(db,shot.id,memo=memo)
            if db.query(Attempt.id).filter(Attempt.shot_id==shot.id,Attempt.stage=='SHOT',Attempt.status.in_(['PENDING','RUNNING'])).first():
                raise HTTPException(409,'SHOT_ALREADY_GENERATING')
            ready.append((shot.id,rsa.id,rsa.result_hash))
        except (HTTPException,ValueError,RuntimeError) as exc:
            blocked.append({'shotId':shot.id,'code':str(exc.detail if isinstance(exc,HTTPException) else exc)})
    if not ready:return {'success':False,'data':{'batchTaskId':None,'tasks':[],'blocked':blocked},'message':'所选Shot均未通过RSA Gate'}
    parent=Task(id=str(uuid4()),type='shot_image_batch',status='running',novel_id=novel_id,chapter_id=chapter_id,name='RSA主分镜图READY子集',
        current_step='准入检查',started_at=datetime.utcnow(),metadata_json=json.dumps({'execution_purpose':'production','rsa_image_batch':True,'admission_complete':False,'blocked':blocked}))
    db.add(parent);db.commit();pid=parent.id;tasks=[]
    for order,(sid,rid,rhash) in enumerate(ready):
        try:
            shot=db.get(Shot,sid);text=shot.shot_image_prompt if skip_existing_prompt and shot.shot_image_prompt else None
            result=service.enqueue(sid,rsa_id=rid,rsa_hash=rhash,prompt_text=text,parent_task_id=pid,batch_order=order)
            tasks.append({'shotId':sid,**result['data']})
        except (HTTPException,ValueError,RuntimeError,KeyError) as exc:
            db.rollback();blocked.append({'shotId':sid,'code':str(exc.detail if isinstance(exc,HTTPException) else exc)})
    parent=db.get(Task,pid)
    parent.metadata_json=json.dumps({'execution_purpose':'production','rsa_image_batch':True,'admission_complete':True,'blocked':blocked,'task_ids':[t['taskId'] for t in tasks]},ensure_ascii=False)
    db.commit();settle_batches(db)
    return {'success':bool(tasks),'data':{'batchTaskId':pid,'tasks':tasks,'blocked':blocked},'message':'已提交通过RSA Gate的Shot子集'}
