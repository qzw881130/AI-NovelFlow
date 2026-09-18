"""#06/#09 shared business RSA, exact actual graphs and immutable physical lineage."""
import asyncio
from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
from uuid import uuid4
import httpx
import pytest
from PIL import Image
from fastapi import HTTPException,FastAPI
from fastapi.testclient import TestClient
from app.core.database import get_db
from app.models.task import Task
from app.models.workflow import Workflow
from app.models.prompt_template import PromptTemplate
from app.models.llm_log import LLMLog
from app.models.rsa_media import RsaImageAttempt as Attempt,RsaMediaArtifact as Artifact
from app.services import rsa_image_service as service, rsa_media_contract as contract
from app.services.rsa_media_graph import inspect_graph,prepare_graph
from app.services.resolved_shot_assets_service import ResolvedShotAssetsService
from app.services.chapter_asset_parse_service import digest
from app.services.llm.base import LLMConfig, build_llm_request_info
from app.services.llm.providers.openai import OpenAICompatibleProvider
from app.services.llm.multimodal import canonical_log, redacted_wire, wire_evidence
from test_resolved_shot_assets import db_session,chapter,fixture,setup as base_setup


pytestmark=pytest.mark.PURE


@pytest.fixture
def setup(db_session,base_setup):
    actor,scene,appearance,shots,root=base_setup
    result=ResolvedShotAssetsService(db_session).resolveShotAssets(shots[0].id);assert result['data']['ready']
    directory=Path(__file__).parents[1]
    for kind,file,mapping in [
        ('shot_character_scene','shot_character_scene_flux2_klein_dual_ref_edit.json',{'prompt_node_id':'117','save_image_node_id':'9','character_reference_image_node_id':'76','scene_reference_image_node_id':'127','width_node_id':'123','height_node_id':'125'}),
        ('keyframe_image','character_appearance_flux2_klein.json',{'prompt_node_id':'117','save_image_node_id':'9','reference_image_node_id':'76'})]:
        db_session.add(Workflow(name=kind,type=kind,is_active=True,workflow_json=(directory/'workflows'/file).read_text(),node_mapping=json.dumps(mapping)))
    for kind,file in [('shot_image_prompt','06_NovelFlow_QwenEdit2511_ShotImagePrompt_V1.txt'),('keyframe_image_prompt','09_NovelFlow_QwenEdit2511_KeyframeImagePrompt_V1.txt')]:
        db_session.add(PromptTemplate(name=kind,type=kind,is_system=True,is_active=True,template=(directory/'prompt_templates'/file).read_text()))
    shots[0].keyframes=json.dumps([{'frame_index':0,'description':'刘备注视桃树','reference_mode':'auto_select','reference_image_url':None},
        {'frame_index':1,'description':'刘备转头','reference_mode':'auto_select','reference_image_url':None}]);db_session.commit()
    return actor,scene,appearance,shots,root,result['data']


class LLM:
    provider,model='test','rsa-vision'
    def __init__(self,db,conflict=False,fail=False,keyframe_prompts=None,on_response=None,cancel_call=None):
        self.db,self.conflict,self.fail,self.calls=db,conflict,fail,[]
        self.keyframe_prompts,self.on_response,self.cancel_call=keyframe_prompts,on_response,cancel_call
    async def chat_completion(self,**kwargs):
        self.calls.append(kwargs)
        if self.cancel_call==len(self.calls):raise asyncio.CancelledError()
        if self.fail:return {'success':False,'error':'LLM_FAILED'}
        payload,_=json.JSONDecoder().raw_decode(kwargs['user_content'][0]['text'].split('\n',1)[1].lstrip());manifest=payload['reference_image_manifest']
        if kwargs['task_type']=='shot_image_prompt':prompt='<Picture 1> 为刘备的正式角色参考，<Picture 2> 为桃园场景。保持已解析衣装，刘备站立于桃园。'
        elif self.keyframe_prompts:prompt=self.keyframe_prompts[len(self.calls)-1]
        else:prompt='<Picture 1> 是'+('上一关键帧' if manifest[0]['type']=='PREVIOUS_KEYFRAME' else '主分镜图')+'。保持同一人物衣装，改变姿态。'
        raw=json.dumps({'status':'ASSET_CONFLICT' if self.conflict else 'READY','final_prompt':None if self.conflict else prompt,'conflicts':['常服与铠甲冲突'] if self.conflict else []},ensure_ascii=False)
        config=LLMConfig(self.provider,self.model,'https://example.invalid','',image_input=True)
        adapter=OpenAICompatibleProvider(config)
        body=adapter._build_request_body(kwargs['system_prompt'],kwargs['user_content'],.2,4096,'json_object')
        info=build_llm_request_info(self.provider,config.api_url,adapter._get_endpoint(),self.model,{},redacted_wire(body))
        info['multimodal']=wire_evidence(config,kwargs['user_content'],body,adapter.MULTIMODAL_WIRE)
        log=LLMLog(id=str(uuid4()),provider=self.provider,model=self.model,status='success',task_type=kwargs['task_type'],novel_id=kwargs['novel_id'],chapter_id=kwargs['chapter_id'],
            system_prompt=kwargs['system_prompt'],user_prompt=canonical_log(kwargs['user_content']),request_info=json.dumps(info,ensure_ascii=False),response=raw)
        self.db.add(log);self.db.commit()
        if self.on_response:self.on_response(len(self.calls))
        return {'success':True,'content':raw,'llm_log_id':log.id}


class Remote:
    def __init__(self,fault=None,during=None):self.fault,self.during,self.submits=fault,during,0
    async def upload_image(self,path,*,upload_name,payload):
        self.payload=payload
        return {'success':True,'filename':upload_name,'subfolder':'','type':'input','payload_sha256':hashlib.sha256(payload).hexdigest(),'payload_size':len(payload)}
    def _client(self):
        image=BytesIO();Image.new('RGB',(160,96),'gold').save(image,format='PNG')
        return httpx.AsyncClient(transport=httpx.MockTransport(lambda req:httpx.Response(200,content=image.getvalue() if req.url.params.get('type')=='output' else (b'wrong' if self.fault=='upload' else self.payload))))
    async def queue_prompt(self,graph):
        self.submits+=1;self.graph=deepcopy(graph)
        if self.fault=='cid':return {'success':True,'prompt_id':123}
        return {'success':False} if self.fault=='ack' else {'success':True,'prompt_id':'remote-'+str(self.submits)}
    async def get_prompt_state(self,cid):
        if self.during:self.during()
        if self.fault=='interrupt':raise asyncio.CancelledError()
        graph=deepcopy(self.graph)
        if self.fault=='graph':graph['117']['inputs']['text']='changed'
        return {'state':'completed','history':{'prompt':[1,cid,graph],'status':{'completed':True,'status_str':'success'},'outputs':{'9':{'images':[{'filename':'image.png','subfolder':'','type':'output'}]}}}}


def enqueue(db,shot,**kwargs):
    return service.RsaImageService(db).enqueue(shot.id,**kwargs)['data']['taskId']


def run(db,tid,*,llm=None,remote=None,recover=False):
    row,task=db.get(Attempt,tid),db.get(Task,tid)
    if not recover:
        token=str(uuid4());row.status,row.claim_token='RUNNING',token;task.status,task.claim_token='running',token;db.commit()
    else:token=task.claim_token
    llm,remote=llm or LLM(db),remote or Remote()
    asyncio.run(service.RsaImageService(db,llm=llm,client=remote).execute(tid,token,recover=recover));db.expire_all()
    return db.get(Attempt,tid),llm,remote


UNBOUND_KEYFRAME_PROMPT='<Picture 1> 是主分镜图。使用角色参考图保持衣装，并改变姿态。'
VALID_KEYFRAME_PROMPT='<Picture 1> 是主分镜图。保持同一人物衣装，并改变姿态。'


def test_primary_and_two_keyframes_share_exact_rsa_and_version_lineage(db_session,setup):
    actor,scene,appearance,shots,root,rsa=setup;shot=shots[0]
    tid=enqueue(db_session,shot);row,llm,remote=run(db_session,tid)
    assert row.status=='SUCCEEDED',row.error
    primary=db_session.get(Artifact,row.artifact_id);assert primary.rsa_id==rsa['id']
    assert primary.data['manifest'][0]['members'][0]['image_revision_id']==rsa['assets']['characters'][0]['reference_image_id']
    assert primary.data['parents'][0]['reference']['image_revision_id']==rsa['assets']['characters'][0]['reference_image_id']
    assert len(llm.calls[0]['user_content'])==3 and remote.submits==1
    parent=primary
    for index in [0,1]:
        tid=enqueue(db_session,shot,stage='KEYFRAME',frame_index=index);row,llm,remote=run(db_session,tid)
        assert row.status=='SUCCEEDED',row.error
        artifact=db_session.get(Artifact,row.artifact_id)
        assert artifact.rsa_id==rsa['id'] and artifact.data['rsa_hash']==rsa['resultHash']
        assert artifact.data['parents']==[{'kind':'ARTIFACT','id':parent.id,'seal':parent.seal}]
        assert row.execution['uploads'][0]['remote_sha256']==parent.data['image']['sha256']
        contract.artifact_proof(db_session,artifact.id,rsa_id=rsa['id'],rsa_hash=rsa['resultHash'])
        parent=artifact
    assert db_session.query(Artifact).count()==3


def test_first_unbound_keyframe_prompt_retries_once_and_records_succeeded_review(db_session,setup):
    from app.services.task_execution import upsert_review_finding
    from app.services.task_service import TaskService
    shot=setup[3][0];primary,_,_=run(db_session,enqueue(db_session,shot));assert primary.status=='SUCCEEDED'
    tid=enqueue(db_session,shot,stage='KEYFRAME',frame_index=0)
    llm=LLM(db_session,keyframe_prompts=[UNBOUND_KEYFRAME_PROMPT,VALID_KEYFRAME_PROMPT]);remote=Remote()
    row,llm,remote=run(db_session,tid,llm=llm,remote=remote);task=db_session.get(Task,tid)
    assert row.status=='SUCCEEDED' and task.status=='completed' and db_session.get(Artifact,row.artifact_id)
    assert len(llm.calls)==2 and llm.calls[0]==llm.calls[1] and remote.submits==1
    attempts=row.execution['prompt_attempts']
    assert [item['state'] for item in attempts]==['REJECTED','VALIDATED']
    assert attempts[0]['code']=='UNBOUND_ASSET_REFERENCE' and attempts[0]['llm_log_id']
    assert attempts[0]['response_sha256']==hashlib.sha256(attempts[0]['raw_response'].encode()).hexdigest()
    metadata=json.loads(task.metadata_json);envelope=metadata['review_findings'];findings=envelope['items']
    assert envelope['version']==1 and len(findings)==1
    finding=findings[0]
    assert finding['fallback_outcome']=='SUCCEEDED' and finding['severity']=='REVIEW_REQUIRED' and finding['status']=='OPEN'
    assert finding['fallback_action']=='RETRY_PROMPT_ONCE_SAME_FROZEN_INPUTS' and finding['code']=='UNBOUND_ASSET_REFERENCE'
    assert {key:finding[key] for key in ('book_id','chapter_id','shot_id','shot_index','clip_index','frame_index','task_id')}=={
        'book_id':task.novel_id,'chapter_id':task.chapter_id,'shot_id':shot.id,'shot_index':shot.index,'clip_index':None,'frame_index':0,'task_id':tid}
    assert finding['evidence']['first_failed_llm_log_id']==attempts[0]['llm_log_id']
    assert finding['evidence']['first_response_sha256']==attempts[0]['response_sha256']
    assert UNBOUND_KEYFRAME_PROMPT not in task.metadata_json and 'data:image/' not in task.metadata_json
    repeated=upsert_review_finding(db_session,tid,code='UNBOUND_ASSET_REFERENCE',fallback_outcome='SUCCEEDED')
    db_session.expire_all();task=db_session.get(Task,tid);assert repeated['id']==finding['id']
    assert len(json.loads(task.metadata_json)['review_findings']['items'])==1
    listed=TaskService.format_task_list([task],{},{},{})[0];detail=TaskService.format_task_detail(task)
    assert listed['reviewFindings']==detail['reviewFindings']
    assert listed['reviewFindings'][0]['findingId']==repeated['id']
    assert listed['reviewFindings'][0]['fallbackOutcome']=='SUCCEEDED'
    assert listed['reviewFindings'][0]['evidence']['firstFailedLlmLogId']==attempts[0]['llm_log_id']
    assert listed['metadata'] is None and detail['metadata']['review_findings']['items'][0]['id']==finding['id']


def test_review_finding_allowlist_rejects_other_codes_and_non_keyframe_attempts(db_session,setup):
    from app.services.task_execution import ExecutionConflict, upsert_review_finding
    shot=setup[3][0];primary_id=enqueue(db_session,shot);run(db_session,primary_id)
    with pytest.raises(ExecutionConflict,match='SCOPE_UNVERIFIED'):
        upsert_review_finding(db_session,primary_id,code='UNBOUND_ASSET_REFERENCE')
    keyframe_id=enqueue(db_session,shot,stage='KEYFRAME',frame_index=0)
    with pytest.raises(ExecutionConflict,match='NOT_ALLOWED'):
        upsert_review_finding(db_session,keyframe_id,code='WRONG_REFERENCE_SOURCE')
    assert 'review_findings' not in json.loads(db_session.get(Task,keyframe_id).metadata_json)


def test_second_unbound_keyframe_prompt_is_hard_failure_without_submit(db_session,setup):
    shot=setup[3][0];run(db_session,enqueue(db_session,shot))
    tid=enqueue(db_session,shot,stage='KEYFRAME',frame_index=0)
    llm=LLM(db_session,keyframe_prompts=[UNBOUND_KEYFRAME_PROMPT,UNBOUND_KEYFRAME_PROMPT]);remote=Remote()
    row,llm,remote=run(db_session,tid,llm=llm,remote=remote);task=db_session.get(Task,tid)
    assert row.status=='FAILED' and task.status=='failed' and row.artifact_id is None
    assert len(llm.calls)==2 and llm.calls[0]==llm.calls[1] and remote.submits==0
    assert [item['code'] for item in row.execution['prompt_attempts']]==['UNBOUND_ASSET_REFERENCE','UNBOUND_ASSET_REFERENCE']
    findings=json.loads(task.metadata_json)['review_findings']['items']
    assert len(findings)==1 and findings[0]['fallback_outcome']=='FAILED'
    assert task.comfyui_prompt_id is None and task.prompt_text is None


def test_review_outcome_identity_survives_hard_shot_reindex_after_finding(db_session,setup):
    shot=setup[3][0];run(db_session,enqueue(db_session,shot));original_index=shot.index
    tid=enqueue(db_session,shot,stage='KEYFRAME',frame_index=0)
    def reindex(call):
        if call==2:
            shot.index=original_index+100;db_session.commit()
    llm=LLM(db_session,keyframe_prompts=[UNBOUND_KEYFRAME_PROMPT,VALID_KEYFRAME_PROMPT],on_response=reindex)
    row,_,remote=run(db_session,tid,llm=llm,remote=Remote());task=db_session.get(Task,tid)
    finding=json.loads(task.metadata_json)['review_findings']['items'][0]
    assert row.status=='FAILED' and task.status=='failed' and remote.submits==0
    assert finding['shot_index']==original_index and finding['fallback_outcome']=='FAILED'


@pytest.mark.parametrize('prompt,error',[('<Picture 1> 是上一关键帧。保持同一人物衣装。','WRONG_REFERENCE_SOURCE'),
    ('<Picture 2> 是主分镜图。保持同一人物衣装。','PICTURE_MANIFEST_MISMATCH')])
def test_wrong_keyframe_source_or_picture_never_falls_back(db_session,setup,prompt,error):
    shot=setup[3][0];run(db_session,enqueue(db_session,shot))
    tid=enqueue(db_session,shot,stage='KEYFRAME',frame_index=0);llm=LLM(db_session,keyframe_prompts=[prompt]);remote=Remote()
    row,llm,remote=run(db_session,tid,llm=llm,remote=remote)
    assert row.status=='FAILED' and error in row.error and len(llm.calls)==1 and remote.submits==0
    assert 'review_findings' not in json.loads(db_session.get(Task,tid).metadata_json)


def test_keyframe_upstream_asset_conflict_never_falls_back(db_session,setup):
    shot=setup[3][0];run(db_session,enqueue(db_session,shot))
    tid=enqueue(db_session,shot,stage='KEYFRAME',frame_index=0);llm=LLM(db_session,conflict=True);remote=Remote()
    row,llm,remote=run(db_session,tid,llm=llm,remote=remote)
    assert row.status=='FAILED' and 'UPSTREAM_ASSET_CONFLICT' in row.error and len(llm.calls)==1 and remote.submits==0
    assert 'review_findings' not in json.loads(db_session.get(Task,tid).metadata_json)


@pytest.mark.parametrize('mutation',['rsa','manifest','template'])
def test_fallback_rechecks_immutable_rsa_manifest_and_template(db_session,setup,mutation):
    shot=setup[3][0];run(db_session,enqueue(db_session,shot));tid=enqueue(db_session,shot,stage='KEYFRAME',frame_index=0)
    def change(_):
        attempt=db_session.get(Attempt,tid)
        if mutation=='rsa':setup[1].setting='changed';db_session.commit()
        elif mutation=='template':
            template=db_session.get(PromptTemplate,attempt.inputs['template']['id']);template.template+=' changed';db_session.commit()
        else:
            path=Path(contract.files.url_to_local_path(attempt.execution['manifest'][0]['image']['url']))
            Image.new('RGB',(160,96),'purple').save(path)
    llm=LLM(db_session,keyframe_prompts=[UNBOUND_KEYFRAME_PROMPT],on_response=change);remote=Remote()
    row,llm,remote=run(db_session,tid,llm=llm,remote=remote);task=db_session.get(Task,tid)
    assert row.status=='FAILED' and len(llm.calls)==1 and remote.submits==0
    assert len(json.loads(task.metadata_json)['review_findings']['items'])==1
    assert json.loads(task.metadata_json)['review_findings']['items'][0]['fallback_outcome']=='FAILED'


def test_direct_keyframe_requires_primary_lineage_and_none_is_not_fallback(db_session,setup):
    shot=setup[3][0]
    with pytest.raises(HTTPException):enqueue(db_session,shot,stage='KEYFRAME',frame_index=0)
    run(db_session,enqueue(db_session,shot))
    frames=json.loads(shot.keyframes);frames[0]['reference_mode']='none';shot.keyframes=json.dumps(frames);db_session.commit()
    with pytest.raises(HTTPException,match='LINEAGE_REFERENCE_REQUIRED'):enqueue(db_session,shot,stage='KEYFRAME',frame_index=0)


@pytest.mark.parametrize('failure',['conflict','llm','upload','ack','cid','graph'])
def test_prompt_or_transport_failure_does_not_publish_or_fallback(db_session,setup,failure):
    shot=setup[3][0]
    row,llm,remote=run(db_session,enqueue(db_session,shot),llm=LLM(db_session,conflict=failure=='conflict',fail=failure=='llm'),remote=Remote(failure))
    assert row.status=='FAILED' and not db_session.query(Artifact).count()
    assert shot.image_url is None and shot.image_status=='failed'
    if failure in {'conflict','llm','upload'}:assert remote.submits==0


@pytest.mark.parametrize('mutation',['rsa','shot','cancel','workflow'])
def test_late_changes_fence_output(db_session,setup,mutation):
    shot=setup[3][0];tid=enqueue(db_session,shot)
    def change():
        if mutation=='rsa':setup[1].setting='changed'
        elif mutation=='shot':shot.description+=' changed'
        elif mutation=='cancel':db_session.get(Task,tid).status='cancelled'
        else:db_session.get(Task,tid).workflow_json='{}'
        db_session.commit()
    row,_,_=run(db_session,tid,remote=Remote(during=change))
    assert row.status=='FAILED' and not db_session.query(Artifact).count()


def test_cache_is_bound_to_rsa_and_context(db_session,setup):
    shot=setup[3][0]
    with pytest.raises(HTTPException):enqueue(db_session,shot,prompt_text='unverified user prompt')
    first,_,_=run(db_session,enqueue(db_session,shot))
    second,llm,remote=run(db_session,enqueue(db_session,shot,prompt_text=first.execution['prompt']['text']))
    assert second.status=='SUCCEEDED',second.error
    assert not llm.calls and remote.submits==1
    setup[1].image_url=None;db_session.commit()
    with pytest.raises(HTTPException):enqueue(db_session,shot,prompt_text=first.execution['prompt']['text'])


def test_acknowledged_restart_only_polls_original_submission(db_session,setup):
    tid=enqueue(db_session,setup[3][0]);remote=Remote('interrupt')
    with pytest.raises(asyncio.CancelledError):run(db_session,tid,remote=remote)
    remote.fault=None
    row,llm,_=run(db_session,tid,remote=remote,recover=True)
    assert row.status=='SUCCEEDED',row.error
    assert remote.submits==1 and not llm.calls


def test_primary_rsa_change_prevents_keyframe_reinterpretation(db_session,setup):
    shot=setup[3][0];first,_,_=run(db_session,enqueue(db_session,shot));old_artifact=first.artifact_id
    Image.new('RGB',(160,96),'orange').save(setup[4]/'scene.png')
    new=ResolvedShotAssetsService(db_session).resolveShotAssets(shot.id)['data'];assert new['ready']
    with pytest.raises(HTTPException):enqueue(db_session,shot,stage='KEYFRAME',frame_index=0)
    assert db_session.get(Artifact,old_artifact).rsa_id!=new['id']


def test_single_reference_keyframe_prose_keeps_existing_named_source_syntax():
    raw=json.dumps({'status':'READY','final_prompt':'以主分镜图为编辑基线，保持同一衣装。','conflicts':[]})
    assert contract.parse_prompt(raw,1,'PRIMARY_STORYBOARD').startswith('以主分镜图')
    with pytest.raises(RuntimeError):contract.parse_prompt(raw,1,'PREVIOUS_KEYFRAME')
    with pytest.raises(ValueError):contract.parse_prompt(raw,2)


def test_existing_image_apis_use_rsa_and_batch_only_queues_ready_subset(db_session,chapter,setup,monkeypatch):
    from app.api import shots as api
    ResolvedShotAssetsService(db_session).resolveShotAssets(setup[3][1].id)
    def forbidden(*args,**kwargs):raise AssertionError('No Book/name based reference lookup')
    monkeypatch.setattr(api,'_build_shot_image_reference_manifest',forbidden)
    monkeypatch.setattr(api,'_resolve_shot_image_workflow_type',forbidden)
    app=FastAPI();app.include_router(api.router,prefix='/api/novels');app.dependency_overrides[get_db]=lambda:db_session
    client=TestClient(app);root=f'/api/novels/{chapter.novel_id}/chapters/{chapter.id}'
    bad=client.post(root+f'/shots/{setup[3][1].id}/generate',json={});assert bad.status_code==409
    before=setup[3][0].keyframes
    assert client.post(root+f'/shots/{setup[3][0].id}/keyframes/0/generate-image',json={}).status_code==409
    assert setup[3][0].keyframes==before
    result=client.post(root+'/shot-images/batch',json={'shot_ids':[s.id for s in setup[3]],'skip_llm_when_prompt_exists':False}).json()
    assert result['success'],result
    assert len(result['data']['tasks'])==len(result['data']['blocked'])==1
    tid=result['data']['tasks'][0]['taskId'];parent_id=result['data']['batchTaskId']
    row,_,_=run(db_session,tid);assert row.status=='SUCCEEDED',row.error
    service.settle_batches(db_session)
    parent=db_session.get(Task,parent_id)
    assert parent.status=='completed' and json.loads(parent.metadata_json)['result']['scope']=='REQUESTED_READY_SUBSET'
    assert json.loads(parent.metadata_json)['result']['blocked']==1


def test_cancel_and_retry_do_not_reuse_an_attempt(db_session,setup):
    from app.services.task_service import TaskService
    shot=setup[3][0];tid=enqueue(db_session,shot)
    assert asyncio.run(TaskService(db_session).cancel_task(tid))['success']
    db_session.expire_all()
    assert db_session.get(Attempt,tid).status=='FAILED' and shot.image_status=='failed'
    task=db_session.get(Task,tid);task.status='failed';db_session.commit()
    assert TaskService(db_session).retry_task(tid)['status_code']==409
    assert enqueue(db_session,shot)!=tid


def test_unconfirmed_recovery_never_reinvokes_llm_or_submits(db_session,setup):
    tid=enqueue(db_session,setup[3][0]);row,task=db_session.get(Attempt,tid),db_session.get(Task,tid)
    row.status,task.status='RUNNING','running';row.claim_token=task.claim_token='lost-owner';row.execution={'phase':'SUBMITTING','submit':{'state':'ATTEMPTED'}};db_session.commit()
    result,llm,remote=run(db_session,tid,recover=True)
    assert result.status=='FAILED' and 'NOT_REPLAYED' in result.error
    assert not llm.calls and remote.submits==0


def test_interrupted_fallback_before_submit_is_not_replayed(db_session,setup):
    shot=setup[3][0];run(db_session,enqueue(db_session,shot));tid=enqueue(db_session,shot,stage='KEYFRAME',frame_index=0)
    llm=LLM(db_session,keyframe_prompts=[UNBOUND_KEYFRAME_PROMPT],cancel_call=2);remote=Remote()
    with pytest.raises(asyncio.CancelledError):run(db_session,tid,llm=llm,remote=remote)
    db_session.expire_all();task=db_session.get(Task,tid);row=db_session.get(Attempt,tid)
    assert task.status=='running' and row.status=='RUNNING' and remote.submits==0
    assert [attempt['state'] for attempt in row.execution['prompt_attempts']]==['REJECTED','STARTED']
    assert json.loads(task.metadata_json)['review_findings']['items'][0]['fallback_outcome']=='PENDING'
    recovery_llm=LLM(db_session);row,recovery_llm,remote=run(db_session,tid,llm=recovery_llm,remote=remote,recover=True)
    task=db_session.get(Task,tid)
    assert row.status=='FAILED' and 'NOT_REPLAYED' in row.error and not recovery_llm.calls and remote.submits==0
    assert json.loads(task.metadata_json)['review_findings']['items'][0]['fallback_outcome']=='FAILED'


def test_review_finding_outcome_write_is_claim_fenced(db_session,setup):
    shot=setup[3][0];run(db_session,enqueue(db_session,shot));tid=enqueue(db_session,shot,stage='KEYFRAME',frame_index=0)
    def replace_owner(call):
        if call==2:
            db_session.get(Task,tid).claim_token='new-owner'
            db_session.get(Attempt,tid).claim_token='new-owner'
            db_session.commit()
    llm=LLM(db_session,keyframe_prompts=[UNBOUND_KEYFRAME_PROMPT,VALID_KEYFRAME_PROMPT],on_response=replace_owner);remote=Remote()
    row,_,remote=run(db_session,tid,llm=llm,remote=remote);task=db_session.get(Task,tid)
    finding=json.loads(task.metadata_json)['review_findings']['items'][0]
    assert row.status=='RUNNING' and task.status=='running' and task.claim_token=='new-owner'
    assert finding['fallback_outcome']=='PENDING' and remote.submits==0


def test_manifest_rehash_cannot_substitute_other_rsa_members(db_session,setup):
    shot=setup[3][0];tid=enqueue(db_session,shot);row=db_session.get(Attempt,tid)
    values=deepcopy(row.inputs);values['manifest'][0]['members'][0]['appearance_id']='made-up-appearance'
    row.inputs=values;row.input_hash=digest(values)
    task=db_session.get(Task,tid);metadata=json.loads(task.metadata_json);metadata['input_hash']=row.input_hash;task.metadata_json=json.dumps(metadata);db_session.commit()
    result,llm,remote=run(db_session,tid)
    assert result.status=='FAILED' and 'MANIFEST_CONFLICT' in result.error
    assert not llm.calls and remote.submits==0


def test_derived_artifact_rehash_cannot_hide_a_changed_parent(db_session,setup):
    shot=setup[3][0];row,_,_=run(db_session,enqueue(db_session,shot));artifact=db_session.get(Artifact,row.artifact_id)
    data=deepcopy(artifact.data);data['parents'][0]['reference']['image_revision_id']='wrong'
    artifact.data=data;artifact.seal=digest(data);db_session.commit()
    with pytest.raises(HTTPException):enqueue(db_session,shot,stage='KEYFRAME',frame_index=0)


def test_reference_sheet_pixels_and_layout_are_reproducible(db_session,setup):
    ref=setup[5]['assets']['characters'][0]['image'];refs=[deepcopy(ref),deepcopy(ref)]
    members=[{'name':'甲','image_revision_id':ref['image_revision_id']},{'name':'乙','image_revision_id':ref['image_revision_id']}]
    planned={'picture_index':1,'type':'MERGED_CHARACTER','members':members,'references':refs,'rsa_id':setup[5]['id'],'rsa_hash':setup[5]['resultHash']}
    inputs={'novel_id':setup[0].novel_id,'manifest':[planned],'rsa_id':setup[5]['id'],'rsa_hash':setup[5]['resultHash']}
    manifest=contract.build_reference_files(db_session,inputs,str(uuid4()));contract.validate_manifest(inputs,manifest)
    assert len(manifest[0]['composition']['tiles'])==2
    path=Path(contract.files.url_to_local_path(manifest[0]['image']['url']))
    Image.new('RGB',(160,96),'purple').save(path)
    manifest[0]['image']=contract.files.image_bytes(manifest[0]['image']['url'],{'max_source_bytes':26214400,'max_source_pixels':20000000})[1]
    with pytest.raises(ValueError,match='COMPOSITION_CHANGED'):contract.validate_manifest(inputs,manifest)


def test_validation_memo_reuses_identical_canonical_inputs(db_session,setup):
    shot=setup[3][0];attempt,_,_=run(db_session,enqueue(db_session,shot));artifact=db_session.get(Artifact,attempt.artifact_id)
    memo=contract.ValidationMemo()

    assert contract.artifact_proof(db_session,artifact.id,rsa_id=artifact.rsa_id,
                                   rsa_hash=artifact.data['rsa_hash'],memo=memo).id==artifact.id
    assert contract.artifact_proof(db_session,artifact.id,rsa_id=artifact.rsa_id,
                                   rsa_hash=artifact.data['rsa_hash'],memo=memo).id==artifact.id
    contract.validate_manifest(attempt.inputs,artifact.data['manifest'],memo=memo)
    contract.validate_manifest(attempt.inputs,artifact.data['manifest'],memo=memo)
    contract.verify_prompt_record(db_session,attempt.inputs,attempt.execution['prompt'],memo=memo)
    contract.verify_prompt_record(db_session,attempt.inputs,attempt.execution['prompt'],memo=memo)

    planned=attempt.inputs['manifest'][0]
    originals=[contract.files.image_bytes(ref['url'],contract.IMAGE_POLICY,memo=memo)[0] for ref in planned['references']]
    first=contract.compose_sheet(originals,planned['members'],memo=memo)
    second=contract.compose_sheet(originals,planned['members'],memo=memo)
    assert first==second
    payload,first_info=contract.files.image_bytes(planned['references'][0]['url'],contract.IMAGE_POLICY,memo=memo)
    _,second_info=contract.files.image_bytes(planned['references'][0]['url'],contract.IMAGE_POLICY,memo=memo)
    assert first_info==second_info
    assert contract.files.inspect_image(payload,contract.IMAGE_POLICY,memo=memo)==contract.files.inspect_image(
        payload,contract.IMAGE_POLICY,memo=memo)

    metrics=memo.report()
    for name in ('image_bytes','inspect_image','compose_sheet','validate_manifest','artifact_proof','verify_prompt_record'):
        assert metrics[name]['cache_hits']>0,name


def test_validation_memo_recomputes_when_image_bytes_change(db_session,setup):
    shot=setup[3][0];attempt,_,_=run(db_session,enqueue(db_session,shot));artifact=db_session.get(Artifact,attempt.artifact_id)
    reference=attempt.inputs['manifest'][0]['references'][0];memo=contract.ValidationMemo()
    assert contract.verify_image_version(db_session,reference,memo=memo)
    path=Path(contract.files.url_to_local_path(reference['url']));original=path.read_bytes()
    try:
        Image.new('RGB',(160,96),'purple').save(path)
        with pytest.raises(HTTPException,match='FROZEN_IMAGE_BYTES_CHANGED'):
            contract.verify_image_version(db_session,reference,memo=memo)
    finally:
        path.write_bytes(original)
    metrics=memo.report()['verify_image_version']
    assert metrics['real_executions']==2 and metrics['cache_hits']==0


def test_validation_memo_recomputes_when_composition_metadata_changes(db_session,setup):
    ref=setup[5]['assets']['characters'][0]['image'];refs=[deepcopy(ref),deepcopy(ref)]
    members=[{'name':'甲','image_revision_id':ref['image_revision_id']},{'name':'乙','image_revision_id':ref['image_revision_id']}]
    planned={'picture_index':1,'type':'MERGED_CHARACTER','members':members,'references':refs,
             'rsa_id':setup[5]['id'],'rsa_hash':setup[5]['resultHash']}
    inputs={'novel_id':setup[0].novel_id,'manifest':[planned],'rsa_id':setup[5]['id'],'rsa_hash':setup[5]['resultHash']}
    manifest=contract.build_reference_files(db_session,inputs,str(uuid4()));memo=contract.ValidationMemo()
    contract.validate_manifest(inputs,manifest,memo=memo)
    changed=deepcopy(manifest);changed[0]['composition']['method']='TAMPERED'
    with pytest.raises(ValueError,match='COMPOSITION_CHANGED'):
        contract.validate_manifest(inputs,changed,memo=memo)
    metrics=memo.report()['validate_manifest']
    assert metrics['real_executions']==2 and metrics['cache_hits']==0


def test_validation_memo_does_not_hide_changed_parent_artifact(db_session,setup):
    shot=setup[3][0];primary_attempt,_,_=run(db_session,enqueue(db_session,shot))
    child_attempt,_,_=run(db_session,enqueue(db_session,shot,stage='KEYFRAME',frame_index=0))
    primary=db_session.get(Artifact,primary_attempt.artifact_id);child=db_session.get(Artifact,child_attempt.artifact_id)
    memo=contract.ValidationMemo()
    assert contract.artifact_proof(db_session,child.id,rsa_id=child.rsa_id,rsa_hash=child.data['rsa_hash'],memo=memo).id==child.id
    data=deepcopy(primary.data);data['receipt']={**data['receipt'],'prompt_id':'changed-parent'}
    primary.data=data;primary.seal=digest(data);db_session.commit()
    with pytest.raises(HTTPException):
        contract.artifact_proof(db_session,child.id,rsa_id=child.rsa_id,rsa_hash=child.data['rsa_hash'],memo=memo)
    assert memo.report()['artifact_proof']['real_executions']>1


def test_phase7_migration_does_not_adopt_legacy_images(db_session,setup):
    from app.services.rsa_media_schema import upgrade
    shot=setup[3][0];shot.image_url='/legacy.png';shot.image_status='completed';db_session.commit()
    upgrade(db_session.bind);upgrade(db_session.bind)
    assert db_session.query(Artifact).count()==db_session.query(Attempt).count()==0
    with pytest.raises(HTTPException):contract.current_primary(db_session,shot)


@pytest.mark.parametrize('file,nodes,mapping',[('shot_character_scene_flux2_klein_dual_ref_edit.json',['76','127'],{'prompt_node_id':'117','save_image_node_id':'9','width_node_id':'123','height_node_id':'125'}),
    ('shot_character_scene_qwen_edit_2511.json',['170','171'],{'prompt_node_id':'184','save_image_node_id':'163','width_node_id':'182','height_node_id':'183'})])
def test_multi_reference_graph_order_and_seed_profile(file,nodes,mapping):
    graph=json.loads((Path(__file__).parents[1]/'workflows'/file).read_text())
    prepared=prepare_graph(graph,mapping,nodes,'16:9',42)
    proof=inspect_graph(prepared,mapping,nodes)
    assert prepared[proof['seed_node']]['inputs'][proof['seed_field']]==42
    with pytest.raises(ValueError):inspect_graph(prepared,mapping,list(reversed(nodes)))
