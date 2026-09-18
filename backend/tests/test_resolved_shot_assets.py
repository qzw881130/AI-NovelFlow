"""Phase6: immutable RSA, actual image versions and the real Phase5 -> demand -> Phase4 contract."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import pytest
from fastapi import HTTPException, FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from app.core.database import get_db
from app.models.novel import Scene, Character, Prop
from app.models.shot import Shot
from app.models.task import Task
from app.models.workflow import Workflow
from app.models.appearance_timeline import CharacterAppearance
from app.models.resolved_shot_assets import ResolvedShotAssets as RSA, ShotAssetHead as Head, ResolvedImageVersion as ImageVersion, ShotAppearanceDemand as Demand
from app.services import appearance_image_contract as images, appearance_generation_service as generation
from app.services import resolved_shot_assets_service as resolver
from app.services.appearance_usage import plan_used_missing, verify_usage
from app.services.chapter_asset_parse_service import digest
from test_chapter_shot_split import db_session, chapter, fixture, execute, LLM, row_snapshot
from test_appearance_generation import run as generate_image


@pytest.fixture
def setup(db_session,chapter,fixture,tmp_path,monkeypatch):
    assert execute(db_session,chapter)['success']
    root=tmp_path/'images';root.mkdir()
    monkeypatch.setattr(images.file_storage,'base_dir',root)
    for module in (images,generation):
        monkeypatch.setattr(module,'url_to_local_path',lambda url:str(root/url.removeprefix('/api/files/')) if url and url.startswith('/api/files/') else None)
        monkeypatch.setattr(module,'local_path_to_url',lambda path:'/api/files/'+str(Path(path).relative_to(root)))
    Image.new('RGB',(160,96),'navy').save(root/'actor.png')
    Image.new('RGB',(160,96),'green').save(root/'scene.png')
    fixture.image_url='/api/files/actor.png'
    scene=db_session.query(Scene).filter_by(novel_id=chapter.novel_id,name='桃园').one();scene.image_url='/api/files/scene.png'
    db_session.commit()
    shots=db_session.query(Shot).filter_by(chapter_id=chapter.id).order_by(Shot.index).all()
    appearance=db_session.query(CharacterAppearance).one()
    return fixture,scene,appearance,shots,root


def resolve(db,shot):
    return resolver.ResolvedShotAssetsService(db).resolveShotAssets(shot.id)


def test_base_ready_frozen_image_versions_and_idempotent_read_only_consumption(db_session,setup):
    actor,scene,appearance,shots,root=setup
    before=[row_snapshot(a) for a in (actor,scene,appearance)]
    result=resolve(db_session,shots[0]);assert result['success'],result
    data=result['data'];assert data['ready'] and data['assets']['characters'][0]['appearance_id'] is None
    rsa=db_session.get(RSA,data['id']);frozen=deepcopy(rsa.data)
    assert frozen['characters'][0]['selection']['kind']=='BASE' and frozen['scene']['scene_id']==scene.id
    assert db_session.query(ImageVersion).count()==2 and not db_session.query(Demand).count()
    assert resolve(db_session,shots[0])['reused'] and db_session.query(RSA).count()==1
    assert resolver.require_frozen_rsa(db_session,shots[0].id,rsa.id,rsa.result_hash).id==rsa.id
    assert [row_snapshot(a) for a in (actor,scene,appearance)]==before
    assert frozen==rsa.data
    ref=frozen['characters'][0]['image'];assert ref['url']!=actor.image_url
    assert images.image_bytes(ref['url'],{'max_source_bytes':26214400,'max_source_pixels':20000000})[1]['sha256']==ref['sha256']


@pytest.mark.parametrize('status',['NEEDS_GENERATION','FAILED','REJECTED','GENERATING'])
def test_latest_logical_appearance_never_uses_base_or_old_image(db_session,setup,status):
    actor,scene,appearance,shots,root=setup
    appearance.status=status;appearance.reference_image_url=actor.image_url;db_session.commit()
    result=resolve(db_session,shots[1]);assert result['success'],result
    data=result['data'];assert data['effectiveStatus']=='BLOCKED'
    chosen=data['assets']['characters'][0]
    assert chosen['appearance_id']==appearance.id and chosen['image'] is None and chosen['selection']['kind']=='APPEARANCE'
    assert chosen['reference_image_id'] is None
    assert db_session.get(Task,data['taskId']).status=='completed'  # BLOCKED is a completed check, not an execution failure.


def test_real_demand_survives_image_state_changes_and_requires_explicit_new_rsa(db_session,chapter,setup,monkeypatch):
    actor,scene,appearance,shots,root=setup
    assert resolve(db_session,shots[0])['data']['ready']
    blocked=resolve(db_session,shots[1])['data'];assert blocked['status']=='BLOCKED'
    before=deepcopy(db_session.get(RSA,blocked['id']).data)
    demand=db_session.query(Demand).one();assert verify_usage(db_session,demand.id,appearance.id)
    plan=plan_used_missing(db_session,chapter.novel_id,chapter.id,[s.id for s in shots])
    assert plan['eligible']=={appearance.id:[demand.id]} and plan['skipped'][0]['status']=='NO_APPEARANCE_DEMAND'
    graph=json.loads((Path(__file__).parents[1]/'workflows/character_appearance_flux2_klein.json').read_text())
    db_session.add(Workflow(name='Appearance fixture',type=images.WORKFLOW_TYPE,is_active=True,workflow_json=json.dumps(graph),
        node_mapping=json.dumps({'load_image_node_id':'76','prompt_node_id':'117','save_image_node_id':'9','seed_node_id':'102'})));db_session.commit()
    task=generation.AppearanceGenerationService(db_session).enqueue(actor.novel_id,actor.id,appearance.id,usage_ids=[demand.id])['data']['taskId']
    assert verify_usage(db_session,demand.id,appearance.id)
    generate_image(db_session,task,monkeypatch)
    assert appearance.status=='READY',db_session.get(Task,task).error_message
    assert db_session.get(RSA,blocked['id']).data==before
    assert resolver.current_rsa(db_session,shots[1].id)['effectiveStatus']=='STALE'
    ready=resolve(db_session,shots[1])['data'];assert ready['ready'] and ready['id']!=blocked['id']
    assert ready['assets']['characters'][0]['appearance_id']==appearance.id
    assert verify_usage(db_session,demand.id,appearance.id)  # Frozen logical demand is independent of image revisions.
    assert db_session.get(generation.Generation,task).inputs['purpose']=='USED_BY_SHOTS'


def test_same_url_different_bytes_and_missing_snapshot_require_new_versions(db_session,setup):
    actor,scene,appearance,shots,root=setup
    first=resolve(db_session,shots[0])['data'];old_ref=first['assets']['characters'][0]['image']
    old_bytes=images.image_bytes(old_ref['url'],{'max_source_bytes':26214400,'max_source_pixels':20000000})[0]
    Image.new('RGB',(160,96),'red').save(root/'actor.png')
    with pytest.raises(HTTPException):resolver.require_frozen_rsa(db_session,shots[0].id,first['id'],first['resultHash'])
    second=resolve(db_session,shots[0])['data'];assert second['ready'] and second['id']!=first['id']
    assert second['assets']['characters'][0]['reference_image_id']!=old_ref['image_revision_id']
    assert images.image_bytes(old_ref['url'],{'max_source_bytes':26214400,'max_source_pixels':20000000})[0]==old_bytes
    new_ref=second['assets']['characters'][0]['image']
    Path(images.url_to_local_path(new_ref['url'])).write_bytes(b'corrupt snapshot')
    assert not resolver.current_rsa(db_session,shots[0].id)['ready']
    third=resolve(db_session,shots[0])['data'];assert third['ready']
    assert third['assets']['characters'][0]['reference_image_id']!=new_ref['image_revision_id']


@pytest.mark.parametrize('mutation',['scene_missing','base_failed','source_edit','failed_split','missing_task'])
def test_upstream_failures_do_not_revive_prior_ready(db_session,chapter,setup,mutation):
    actor,scene,appearance,shots,root=setup
    first=resolve(db_session,shots[0])['data']
    if mutation=='scene_missing':scene.image_url=None;db_session.commit()
    elif mutation=='base_failed':actor.generating_status='failed';db_session.commit()
    elif mutation=='source_edit':shots[0].description+='changed';db_session.commit()
    elif mutation=='failed_split':assert not execute(db_session,chapter,LLM(db_session,fail=True))['success']
    else:db_session.delete(db_session.get(Task,first['taskId']));db_session.commit()
    assert not resolver.current_rsa(db_session,shots[0].id)['ready']
    with pytest.raises(HTTPException):resolver.require_frozen_rsa(db_session,shots[0].id,first['id'],first['resultHash'])
    second=resolve(db_session,shots[0])['data']
    if mutation=='missing_task':assert second['ready'] and second['id']!=first['id']
    else:assert not second['ready']


def test_legacy_cannot_produce_base_or_demand(db_session,chapter,setup):
    old=Shot(chapter_id=chapter.id,index=3,description='legacy',characters='["刘备"]',scene='桃园')
    db_session.add(old);db_session.commit()
    result=resolve(db_session,old)['data'];assert result['status']=='BLOCKED'
    assert not result['assets']['logical_ready'] and result['assets']['characters']==[]
    assert db_session.query(Demand).count()==0


def test_capture_failure_retains_failed_head_and_no_fallback(db_session,setup,monkeypatch):
    actor,scene,appearance,shots,root=setup
    first=resolve(db_session,shots[0])['data']
    Image.new('RGB',(160,96),'red').save(root/'actor.png')
    original=resolver.freeze_image
    def tamper(db,observation,payload):
        result=original(db,observation,payload)
        if observation['origin']['kind']=='CHARACTER_BASE':Image.new('RGB',(160,96),'yellow').save(root/'actor.png')
        return result
    monkeypatch.setattr(resolver,'freeze_image',tamper)
    result=resolve(db_session,shots[0]);assert not result['success']
    assert result['data']['status']=='FAILED' and resolver.current_rsa(db_session,shots[0].id)['effectiveStatus']=='FAILED'
    assert db_session.get(RSA,first['id']).status=='READY'


def test_manifest_conflict_and_partial_readiness_api(db_session,chapter,setup):
    from app.api.resolved_shot_assets import router
    actor,scene,appearance,shots,root=setup
    app=FastAPI();app.include_router(router,prefix='/api/novels');app.dependency_overrides[get_db]=lambda:db_session
    client=TestClient(app);base=f'/api/novels/{chapter.novel_id}/chapters/{chapter.id}'
    assert client.get(base+'/asset-readiness').json()['data']['counts']['ready']==0
    result=client.post(base+'/resolve-assets',json={}).json();assert result['success'],result
    state=result['data'];assert state['readyShotIds']==[shots[0].id] and state['blockedShotIds']==[shots[1].id] and state['failedShotIds']==[]
    assert not state['chapterReady']
    manifest=state['readyManifest'][0]
    request={'rsa_id':manifest['rsa_id'],'rsa_hash':manifest['rsa_hash']}
    assert client.post(base+f'/shots/{shots[0].id}/resolved-assets/validate',json=request).status_code==200
    assert client.post(base+f'/shots/{shots[1].id}/resolved-assets/validate',json=request).status_code==409
    request['rsa_hash']='wrong';assert client.post(base+f'/shots/{shots[0].id}/resolved-assets/validate',json=request).status_code==409
    count=db_session.query(RSA).count();assert client.get(base+'/asset-readiness').json()['data']['readyShotIds']==[shots[0].id]
    assert db_session.query(RSA).count()==count


def test_demand_cannot_be_reassigned_or_survive_source_mutation(db_session,setup):
    actor,scene,appearance,shots,root=setup
    resolve(db_session,shots[1]);demand=db_session.query(Demand).one()
    with pytest.raises(HTTPException):verify_usage(db_session,demand.id,'some-other-appearance')
    shots[1].video_description+='changed';db_session.commit()
    with pytest.raises(HTTPException):verify_usage(db_session,demand.id,appearance.id)


def test_consumer_never_calls_appearance_selector(db_session,setup,monkeypatch):
    from app.services.appearance_timeline_service import AppearanceTimelineService
    result=resolve(db_session,setup[3][0])['data']
    def forbidden(*args,**kwargs):raise AssertionError('Consumption must not reselect an Appearance')
    monkeypatch.setattr(AppearanceTimelineService,'at',forbidden)
    assert resolver.require_frozen_rsa(db_session,setup[3][0].id,result['id'],result['resultHash'])


@pytest.mark.parametrize('target',['wire_url','scene_id','base_choice','definition','task'])
def test_rehashed_or_manifest_tampering_cannot_change_frozen_business_assets(db_session,setup,target):
    result=resolve(db_session,setup[3][0])['data'];row=db_session.get(RSA,result['id'])
    data,inputs=deepcopy(row.data),deepcopy(row.inputs)
    if target=='wire_url':
        data['references']['character:'+setup[0].id]['url']=setup[0].image_url
        data.update(resolver.materialize(inputs['logical'],inputs['images'],data['references']))
    elif target=='scene_id':
        inputs['logical']['scene']['scene_id']='not-the-bound-scene'
        data.update(resolver.materialize(inputs['logical'],inputs['images'],data['references']))
    elif target=='base_choice':
        inputs['logical']['characters'][0]['selection']['reason']='fabricated fallback'
        data.update(resolver.materialize(inputs['logical'],inputs['images'],data['references']))
    elif target=='definition':
        setup[1].setting='changed accepted scene description';db_session.commit()
    else:
        db_session.get(Task,row.task_id).metadata_json='{}';db_session.commit()
    if target in {'wire_url','scene_id','base_choice'}:
        row.inputs,row.data=inputs,data;row.input_hash,row.result_hash=digest(inputs),digest(data);row.seal=resolver.rsa_seal(row)
        task=db_session.get(Task,row.task_id);meta=json.loads(task.metadata_json);meta.update(rsa_hash=row.result_hash,rsa_seal=row.seal);task.metadata_json=json.dumps(meta);db_session.commit()
    with pytest.raises((HTTPException,KeyError)):resolver.require_frozen_rsa(db_session,setup[3][0].id,row.id,row.result_hash)


def test_rejected_appearance_demand_does_not_auto_regenerate(db_session,chapter,setup):
    setup[2].status='REJECTED';db_session.commit()
    resolve(db_session,setup[3][1])
    plan=plan_used_missing(db_session,chapter.novel_id,chapter.id,[setup[3][1].id])
    assert not plan['eligible'] and plan['skipped'][0]['status']=='REJECTED'


def test_orphaned_running_attempt_expires_without_old_ready_fallback(db_session,setup):
    from datetime import datetime,timedelta
    first=resolve(db_session,setup[3][0])['data'];row=db_session.get(RSA,first['id'])
    row.status='RUNNING';row.expires_at=datetime.utcnow()-timedelta(minutes=1)
    task=db_session.get(Task,row.task_id);task.status='running';db_session.commit()
    assert resolver.expire_rsa_task(db_session,task)
    assert resolver.current_rsa(db_session,setup[3][0].id)['effectiveStatus']=='FAILED'
    assert row.status=='FAILED'


def test_unexpected_preflight_failure_is_a_new_failed_attempt(db_session,setup,monkeypatch):
    first=resolve(db_session,setup[3][0])['data']
    def failure(*args,**kwargs):raise RuntimeError('local storage offline')
    monkeypatch.setattr(resolver,'observe_all',failure)
    result=resolve(db_session,setup[3][0])
    assert not result['success'] and result['data']['status']=='FAILED' and result['data']['id']!=first['id']
    assert resolver.current_rsa(db_session,setup[3][0].id)['effectiveStatus']=='FAILED'


def test_read_only_frozen_checks_survive_session_restart(db_session,setup):
    from sqlalchemy.orm import Session
    result=resolve(db_session,setup[3][0])['data']
    with Session(db_session.bind) as other:
        row=resolver.require_frozen_rsa(other,setup[3][0].id,result['id'],result['resultHash'])
        assert row.data['characters'][0]['reference_image_id']==result['assets']['characters'][0]['reference_image_id']


def test_schema_upgrade_does_not_infer_versions_or_demands(db_session,setup):
    from app.services.resolved_shot_assets_schema import upgrade
    before=[row_snapshot(x) for x in (setup[0],setup[1],*setup[3])]
    upgrade(db_session.bind);upgrade(db_session.bind)
    assert before==[row_snapshot(x) for x in (setup[0],setup[1],*setup[3])]
    assert db_session.query(RSA).count()==db_session.query(ImageVersion).count()==db_session.query(Demand).count()==0


def test_partial_batch_reports_admission_conflict_and_ready_subset(db_session,chapter,setup,monkeypatch):
    from app.api.resolved_shot_assets import resolve_chapter,ResolveChapterRequest
    original=resolver.ResolvedShotAssetsService.resolveShotAssets
    def resolve_some(self,shot_id):
        if shot_id==setup[3][1].id:raise HTTPException(409,'RSA_RESOLUTION_RUNNING')
        return original(self,shot_id)
    monkeypatch.setattr(resolver.ResolvedShotAssetsService,'resolveShotAssets',resolve_some)
    result=resolve_chapter(chapter.novel_id,chapter.id,ResolveChapterRequest(),db_session)
    assert not result['success'] and result['data']['readyShotIds']==[setup[3][0].id]
    assert result['data']['attempts'][1]['message']=='RSA_RESOLUTION_RUNNING'
