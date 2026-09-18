"""Explicit, resumable-by-new-attempt rebuild using the same Phase1-6 services."""
import asyncio
from copy import deepcopy
from datetime import datetime,timedelta
import hashlib
import json
from pathlib import Path
from uuid import uuid4
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy.exc import IntegrityError
from app.models.novel import Chapter,Character,Scene,Prop
from app.models.shot import Shot
from app.models.task import Task
from app.models.chapter_governance import ChapterLifecycle,ChapterRebuildRun as Run
from app.services.asset_identity import row_snapshot
from app.services.chapter_asset_parse_service import ChapterAssetParseService,digest,source_hash
from app.services.asset_resolution_service import AssetResolutionService,binding_state
from app.services.appearance_timeline_service import AppearanceTimelineService
from app.services.chapter_shot_split_service import ChapterShotSplitService,split_state,previous_shots
from app.services.resolved_shot_assets_service import ResolvedShotAssetsService
from app.services.chapter_governance import pipeline_state
from app.services.rebuild_context import rebuild_owner
from app.utils.path_utils import url_to_local_path

TASK_TYPE='chapter_asset_rebuild'
VERSION='chapter-rebuild-v1'


def file_hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def protection_snapshot(db,novel_id):
    rows={};files={}
    for model in (Character,Scene,Prop):
        rows[model.__tablename__]={a.id:row_snapshot(a) for a in db.query(model).filter_by(novel_id=novel_id).order_by(model.id)}
        for data in rows[model.__tablename__].values():
            for key in ('image_url','reference_audio_url'):
                url=data.get(key);path=url_to_local_path(url) if url else None
                if path and Path(path).is_file():files[url]=file_hash(path)
    return {'rows':rows,'files':files}


def check_protection(db,novel_id,expected):
    for model in (Character,Scene,Prop):
        actual={r.id:row_snapshot(r) for r in db.query(model).filter_by(novel_id=novel_id).populate_existing()}
        for key,value in expected['rows'][model.__tablename__].items():
            if actual.get(key)!=value:raise RuntimeError('PROTECTED_BOOK_ASSET_CHANGED: '+key)
    for url,sha in expected['files'].items():
        path=url_to_local_path(url)
        if not path or not Path(path).is_file() or file_hash(path)!=sha:raise RuntimeError('PROTECTED_BOOK_FILE_CHANGED: '+url)


def response(run):
    return {'id':run.id,'taskId':run.task_id,'novelId':run.novel_id,'chapterId':run.chapter_id,'status':run.status,
        'inputHash':run.input_hash,'resultHash':run.result_hash,'steps':run.steps,'result':run.result,'error':run.error,'createdAt':run.created_at}


def settle_rebuild(db,task):
    run=db.query(Run).filter_by(task_id=task.id).first()
    if run and run.status in {'PENDING','RUNNING'} and task.status in {'failed','cancelled'}:
        run.status,run.error,run.completed_at='FAILED',task.error_message or 'REBUILD_TERMINATED',datetime.utcnow()
        run.result_hash=digest(run.result)


class ChapterRebuildService:
    def __init__(self,db,llm=None):self.db,self.llm=db,llm

    def enqueue(self,novel_id,chapter_id,*,mode='REBUILD',include_previous=False,
                source_contract_version='chapter-shot-ownership-v2'):
        db=self.db;chapter=db.query(Chapter).filter_by(id=chapter_id,novel_id=novel_id).first()
        if not chapter:raise HTTPException(404,'章回不存在')
        if mode not in {'REBUILD','CONTINUE'}:raise HTTPException(422,'INVALID_REBUILD_MODE')
        chapters=db.query(Chapter).filter(Chapter.novel_id==novel_id,Chapter.number<=chapter.number).order_by(Chapter.number,Chapter.id).all() if include_previous else [chapter]
        ids=[c.id for c in chapters]
        active=db.query(Task).filter(Task.status.in_(['pending','running','queued']),Task.chapter_id.in_(ids)).first()
        if active:raise HTTPException(409,{'code':'CHAPTER_TASK_ACTIVE','taskId':active.id})
        existing=db.query(Run).filter(Run.novel_id==novel_id,Run.status.in_(['PENDING','RUNNING'])).first()
        if existing:raise HTTPException(409,{'code':'BOOK_REBUILD_RUNNING','runId':existing.id})
        from app.services.chapter_scope import run_version
        try:run_version(source_contract_version)
        except ValueError as exc:raise HTTPException(422,str(exc)) from exc
        snapshots=[{'chapter_id':c.id,'number':c.number,'title':c.title,'content':c.content,'source_hash':source_hash(c),
            'old_shots':previous_shots(db,c.id),'old_resources':{k:getattr(c,k) for k in ('parsed_data','character_images','shot_images','shot_videos','transition_videos','final_video')},
            'initial_state':pipeline_state(db,novel_id,c.id)} for c in chapters]
        inputs=jsonable_encoder({'version':VERSION,'mode':mode,'include_previous':include_previous,
            'source_contract_version':source_contract_version,'chapters':snapshots,'protected':protection_snapshot(db,novel_id)})
        rid,tid=str(uuid4()),str(uuid4())
        row=Run(id=rid,task_id=tid,novel_id=novel_id,chapter_id=chapter_id,status='PENDING',inputs=inputs,input_hash=digest(inputs),result={'chapters':{}})
        task=Task(id=tid,type=TASK_TYPE,status='pending',novel_id=novel_id,chapter_id=chapter_id,name='显式重建章回资产',current_step='等待重建队列',
            metadata_json=json.dumps({'execution_purpose':'production','rebuild_id':rid,'input_hash':row.input_hash}))
        db.add_all([row,task])
        for item in snapshots:
            head=db.get(ChapterLifecycle,item['chapter_id'])
            if not head:
                head=ChapterLifecycle(chapter_id=item['chapter_id'],novel_id=novel_id,origin=item['initial_state']['origin'],origin_evidence=item['initial_state']['originEvidence']);db.add(head)
            head.rebuild_id=rid
        try:db.commit()
        except IntegrityError as exc:db.rollback();raise HTTPException(409,'BOOK_REBUILD_RUNNING') from exc
        return {'success':True,'data':response(row)}

    def guard(self,rid,token):
        db=self.db;db.expire_all();run=db.get(Run,rid);task=db.get(Task,run.task_id) if run else None
        if (not run or not task or run.status!='RUNNING' or task.status!='running' or run.claim_token!=token or task.claim_token!=token
            or digest(run.inputs)!=run.input_hash or json.loads(task.metadata_json or '{}').get('input_hash')!=run.input_hash):raise RuntimeError('REBUILD_EXECUTION_FENCED')
        for item in run.inputs['chapters']:
            chapter=db.get(Chapter,item['chapter_id']);head=db.get(ChapterLifecycle,item['chapter_id'])
            if not chapter or chapter.novel_id!=run.novel_id or source_hash(chapter)!=item['source_hash'] or not head or head.rebuild_id!=rid:
                raise RuntimeError('REBUILD_SOURCE_OR_OWNER_CHANGED')
        check_protection(db,run.novel_id,run.inputs['protected'])
        task.heartbeat_at=datetime.utcnow()
        return run,task

    def step(self,rid,token,cid,stage,result):
        db=self.db;run=db.get(Run,rid)
        if not run or run.claim_token!=token:raise RuntimeError('REBUILD_OWNER_CHANGED')
        run.steps=[*run.steps,{'chapterId':cid,'stage':stage,'at':datetime.utcnow().isoformat(),'receipt':jsonable_encoder(result)}]
        db.commit()

    async def waiting(self,awaitable,rid,token):
        operation=asyncio.ensure_future(awaitable)
        try:
            while True:
                done,_=await asyncio.wait({operation},timeout=15)
                if done:return operation.result()
                self.guard(rid,token);self.db.commit()
        finally:
            if not operation.done():
                operation.cancel()
                try:await operation
                except BaseException:pass

    def finish(self,rid,token,status,error=None):
        run,task=self.guard(rid,token)
        run.status,run.error,run.completed_at=status,error,datetime.utcnow();run.result_hash=digest(run.result)
        task.status='failed' if status=='FAILED' else 'completed';task.progress=100;task.completed_at=datetime.utcnow()
        task.current_step='重建结果：'+status;task.error_message=error
        task.metadata_json=json.dumps({'execution_purpose':'production','rebuild_id':rid,'input_hash':run.input_hash,'result_hash':run.result_hash,'gate_status':status})
        self.db.commit()

    async def execute(self,rid,token):
        db=self.db
        context_token = rebuild_owner.set((rid, token))
        try:
            run,task=self.guard(rid,token);inputs=deepcopy(run.inputs);novel_id=run.novel_id
            for position,item in enumerate(inputs['chapters'],1):
                cid=item['chapter_id'];run,task=self.guard(rid,token)
                task.current_step=f"{position}/{len(inputs['chapters'])} 解析当前原文";db.commit()
                state=pipeline_state(db,novel_id,cid)
                if inputs['mode']=='REBUILD' or any(v['status']!='SUCCEEDED' for v in state['candidates'].values()):
                    result=await self.waiting(ChapterAssetParseService(db,self.llm).parse(novel_id,cid,['characters','scenes','props']),rid,token)
                    self.step(rid,token,cid,'CANDIDATES',result)
                    if not result['success']:self.finish(rid,token,'FAILED','CANDIDATE_PARSE_FAILED');return
                self.guard(rid,token)
                bindings=binding_state(db,novel_id,cid)
                if not bindings['phase2Ready']:
                    if inputs['mode']=='CONTINUE' and any(x['status']=='NEEDS_REVIEW' for x in bindings['assets'].values()):
                        self.finish(rid,token,'NEEDS_REVIEW','请先完成身份归并Review');return
                    result=await self.waiting(AssetResolutionService(db,self.llm).resolve(novel_id,cid),rid,token)
                    self.step(rid,token,cid,'BINDINGS',result)
                    if not result['success']:
                        status='NEEDS_REVIEW' if result['data']['status']=='NEEDS_REVIEW' else 'FAILED'
                        self.finish(rid,token,status,'BINDINGS_'+status);return
                timeline=AppearanceTimelineService(db).build(novel_id,cid);self.step(rid,token,cid,'TIMELINE',timeline)
                if not timeline['success']:
                    self.finish(rid,token,'NEEDS_REVIEW' if timeline['data']['status']=='NEEDS_REVIEW' else 'BLOCKED','TIMELINE_NOT_READY: 检查前章依赖或事件定位');return
                self.guard(rid,token)
                source_state=split_state(db,novel_id,cid)
                selected_source_contract=inputs.get('source_contract_version')
                if not source_state['phase5Ready'] or source_state.get('sourceContractVersion')!=selected_source_contract:
                    result=await self.waiting(ChapterShotSplitService(db,self.llm).split(
                        novel_id,cid,source_contract_version=selected_source_contract),rid,token)
                    self.step(rid,token,cid,'SHOT_SOURCE',result)
                    if not result['success']:
                        self.finish(rid,token,'NEEDS_REVIEW' if result.get('data',{}).get('status')=='NEEDS_REVIEW' else 'FAILED','SHOT_SPLIT_NOT_READY');return
                run,task=self.guard(rid,token)
                result=deepcopy(run.result);result['chapters'][cid]={'structuralReady':True,'source':split_state(db,novel_id,cid)};run.result=result;run.result_hash=digest(result);db.commit()
                rsa_results=[ResolvedShotAssetsService(db).resolveShotAssets(s.id) for s in db.query(Shot).filter_by(chapter_id=cid).order_by(Shot.index,Shot.id)]
                self.step(rid,token,cid,'RSA',rsa_results)
                run,task=self.guard(rid,token)
                result=deepcopy(run.result);result['chapters'][cid]['rsa']=jsonable_encoder([r['data'] for r in rsa_results]);run.result=result;run.result_hash=digest(result);db.commit()
            rows=[rsa for chapter in run.result['chapters'].values() for rsa in chapter.get('rsa',[])]
            self.finish(rid,token,'SUCCEEDED' if rows and all(r['ready'] for r in rows) else 'BLOCKED',None if rows and all(r['ready'] for r in rows) else '结构已重建；请准备缺失图片并重新解析RSA')
        except BaseException as exc:
            db.rollback();run=db.get(Run,rid);task=db.get(Task,run.task_id) if run else None
            if run and run.claim_token==token and run.status in {'PENDING','RUNNING'}:
                run.status,run.error,run.completed_at='FAILED',str(exc) or 'REBUILD_INTERRUPTED',datetime.utcnow();run.result_hash=digest(run.result)
                if task and task.status in {'pending','running'}:task.status,task.error_message,task.completed_at='failed',run.error,datetime.utcnow()
                db.commit()
            if isinstance(exc,asyncio.CancelledError):raise
            if not isinstance(exc,Exception):raise
        finally:
            rebuild_owner.reset(context_token)


async def run_next_rebuild():
    from app.core.database import SessionLocal
    db=SessionLocal()
    try:
        for run in db.query(Run).filter(Run.status.in_(['PENDING','RUNNING'])).all():
            task=db.get(Task,run.task_id)
            if not task or task.status in {'failed','cancelled'} or (run.status=='RUNNING' and (not task.heartbeat_at or task.heartbeat_at<datetime.utcnow()-timedelta(minutes=2))):
                run.status,run.error,run.completed_at='FAILED','REBUILD_INTERRUPTED',datetime.utcnow();run.result_hash=digest(run.result)
                if task and task.status in {'pending','running'}:task.status,task.error_message='failed','REBUILD_INTERRUPTED'
                db.commit()
        row=db.query(Run).join(Task,Task.id==Run.task_id).filter(Run.status=='PENDING',Task.status=='pending').order_by(Run.created_at).first()
        if not row:return False
        token=str(uuid4());task=db.get(Task,row.task_id)
        if db.query(Task).filter_by(id=task.id,status='pending').update({'status':'running','claim_token':token,'heartbeat_at':datetime.utcnow(),'started_at':datetime.utcnow()},synchronize_session=False)!=1:
            db.rollback();return False
        row.status,row.claim_token='RUNNING',token;rid=row.id;db.commit()
        await ChapterRebuildService(db).execute(rid,token);return True
    finally:db.close()
