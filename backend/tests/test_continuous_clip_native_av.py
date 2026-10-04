import hashlib
import json
from pathlib import Path

import pytest

from app.models.novel import Novel, Chapter
from app.models.shot import Shot
from app.models.task import Task
from app.repositories.shot_repository import ShotRepository
from app.services import continuous_clip_av as av, shot_video_service as service


def physical(count, content=b"media"):
    return {"frame_count": count, "fps": 24, "timebase": "1/24", "video_duration": count/24,
            "has_audio": True, "audio_duration": count/24, "audio_start_time": 0,
            "width": 960, "height": 544, "sha256": hashlib.sha256(content).hexdigest()}


def unit(task_id, count, previous=None, *, capability="GENERATE", source_start=0):
    media = physical(count)
    if previous:
        media.update(physical_output_role=av.NATIVE_CONTINUITY_OUTPUT, overlap_frames=39,
                     overlap_duration=1.625, previous={"generated_by_task_id": previous[0],
                         "source_frame_start": source_start, "physical_output": physical(previous[1])})
    return {"task_id": task_id, "path": f"{task_id}.mp4", "capability": capability, "physical_output": media}


@pytest.fixture
def persistence(db_session, tmp_path, monkeypatch):
    novel = Novel(id="native-novel", title="Native")
    chapter = Chapter(id="native-chapter", novel_id=novel.id, number=1, title="Chapter")
    shot = Shot(id="native-shot", chapter_id=chapter.id, index=1)
    previous_path = tmp_path / "previous.mp4"
    previous_path.write_bytes(b"previous")
    previous_url = "/api/files/previous.mp4"
    identity = {"clip_id": f"{shot.id}:clip:1", "clip_index": 1, "clip_plan_revision": 1}
    source_metadata = {"execution_scope": "CLIP", **identity, "approval_status": "APPROVED",
                       "execution_contract": {"artifact_kind": "CLIP_ONLY", "capability": "GENERATE", "clip": identity}}
    source = Task(id="native-c1", type="shot_video", status="completed", name="C1", novel_id=novel.id,
                  chapter_id=chapter.id, shot_id=shot.id, result_url=previous_url, metadata_json=json.dumps(source_metadata))
    source_provenance = {"clip_index": 1, "clip_plan_revision": 1, "generated_by_task_id": source.id,
                         "result_url": previous_url, "physical_output": {**physical(209,b"previous"), "physical_output_role": "CLIP_ONLY"},
                         "source_frame_start": 0}
    clips = [{"clip_index": 1, "capability": "GENERATE", "generated_by_task_id": source.id,
              "video_url": previous_url, "execution_status": "APPROVED"},
             {"clip_index": 2, "capability": "EXTEND", "previous_clip_index": 1}]
    shot.video_director_plan = json.dumps({"canonical_visual_plan": True, "clip_plan_revision": 1, "clip_plan": clips})
    db_session.add_all([novel,chapter,shot,source]);db_session.commit()
    monkeypatch.setattr(service.file_storage, "base_dir", tmp_path)
    monkeypatch.setattr(service, "url_to_local_path", lambda url: str(tmp_path/url.rsplit('/',1)[-1]) if url else None)
    def probe(path):
        return physical(209 if Path(path).name == "previous.mp4" else 447, Path(path).read_bytes())
    monkeypatch.setattr(service, "probe_clip_av", probe)
    monkeypatch.setattr(av, "probe_clip_av", probe)
    monkeypatch.setattr(service, "_probe_video_duration", lambda _: 18.625)
    async def download(**_kwargs):
        path=tmp_path/'native.mp4';path.write_bytes(b'native');return str(path)
    monkeypatch.setattr(service.file_storage, "download_video", download)
    return novel,chapter,shot,source_provenance


async def persist_native(db, fixture, capability):
    novel,chapter,shot,previous = fixture
    identity = {"clip_id": f"{shot.id}:clip:2", "clip_index": 2, "clip_plan_revision": 1, "duration_seconds": 8}
    contract = {"capability": capability, "artifact_kind": av.NATIVE_CONTINUITY_OUTPUT,
                "clip": identity, "previous_clip": previous}
    if capability == "TEMPORAL_EXTEND":
        contract['temporal_anchor_manifest'] = {"anchors": [{"frame_position": 234, "source": {"id": "KF4"}}]}
    metadata = {"execution_scope": "CLIP", **identity, "capability": capability,
                "requested_duration": 8, "execution_contract": contract}
    task = Task(id="native-c2", type="shot_video", status="running", name="C2", novel_id=novel.id,
                chapter_id=chapter.id, shot_id=shot.id, metadata_json=json.dumps(metadata))
    db.add(task);db.commit()
    plan=json.loads(shot.video_director_plan);plan['clip_plan'][1]['capability']=capability
    shot.video_director_plan=json.dumps(plan);db.commit()
    result={"success":True,"video_url":"http://comfy/view?filename=native.mp4",
            "physical_output_role": av.NATIVE_CONTINUITY_OUTPUT, "output_node_id":"65"}
    await service._save_generated_video(result,task,novel.id,chapter.id,1,db,task.id,ShotRepository(db),
                                         clip_metadata=metadata,update_shot_result=False)
    return task,contract


@pytest.mark.asyncio
@pytest.mark.parametrize('capability',['EXTEND','TEMPORAL_EXTEND'])
async def test_native_persistence_roles_provenance_and_metadata_round_trip(db_session,persistence,capability):
    task,contract=await persist_native(db_session,persistence,capability)
    metadata=json.loads(task.metadata_json);output=metadata['physical_output']
    assert task.status=='completed'
    assert metadata['execution_contract']==contract
    assert metadata['actual_duration'] is None and metadata['requested_duration']==8
    assert output['physical_output_role']==av.NATIVE_CONTINUITY_OUTPUT
    assert output['raw_context_output']['physical_output_role']=='RAW_CONTEXT_OUTPUT'
    assert output['overlap_frames']==39 and output['overlap_duration']==1.625
    assert output['native_cumulative_duration']==18.625
    assert output['assembly_span']=={'start_frame':170,'end_frame':447,'replacement_frames':39,'net_new_frames':238,'net_new_duration':238/24}
    plan=json.loads(persistence[2].video_director_plan)
    assert plan['clip_plan'][1]['physical_output']==output
    assert plan['clip_plan'][1]['video_url']==task.result_url
    assert persistence[2].video_url is None
    if capability=='TEMPORAL_EXTEND':
        assert contract['temporal_anchor_manifest']['anchors'][0]['frame_position']==234


@pytest.mark.asyncio
async def test_resolver_prefers_exact_native_predecessor(db_session,persistence):
    task,_=await persist_native(db_session,persistence,'EXTEND')
    novel,chapter,shot,_=persistence
    provenance={'clip_index':2,'clip_plan_revision':1,'generated_by_task_id':task.id,'result_url':task.result_url}
    resolved=service.resolve_extend_previous_av(db_session,novel.id,chapter.id,shot,
                   {'previous_clip_index':2,'clip_plan_revision':1},provenance)
    assert resolved['generated_by_task_id']==task.id
    assert resolved['result_url']==task.result_url
    assert resolved['physical_output']['physical_output_role']==av.NATIVE_CONTINUITY_OUTPUT
    assert resolved['physical_output']['frame_count']==447
    metadata=json.loads(task.metadata_json);metadata.pop('physical_output');task.metadata_json=json.dumps(metadata)
    with pytest.raises(ValueError,match='NATIVE_CONTINUITY_OUTPUT_UNAVAILABLE'):
        service.resolve_extend_previous_av(db_session,novel.id,chapter.id,shot,
                        {'previous_clip_index':2,'clip_plan_revision':1},provenance)


@pytest.mark.asyncio
async def test_native_replacement_clears_successor_physical_metadata_and_assembly(db_session,persistence):
    from app.services.canonical_execution_invalidation import invalidate_current_canonical_execution
    task,_=await persist_native(db_session,persistence,'EXTEND')
    shot=persistence[2]
    plan=json.loads(shot.video_director_plan)
    plan['clip_plan'].append({'clip_index':3,'capability':'TEMPORAL_EXTEND','previous_clip_index':2,
                             'execution_status':'APPROVED','physical_output':{'sha256':'old'}})
    plan['assembly_spans']={'frame_count':770}
    shot.video_director_plan=json.dumps(plan)
    assert invalidate_current_canonical_execution(shot,{2},preserve_clip_indexes={2})=={3}
    plan=json.loads(shot.video_director_plan)
    assert 'physical_output' not in plan['clip_plan'][2]
    assert 'assembly_spans' not in plan
    assert plan['clip_plan'][1]['physical_output']['result_url']==task.result_url


@pytest.mark.asyncio
async def test_changed_native_bytes_and_previous_snapshot_are_rejected(db_session,persistence):
    task,_=await persist_native(db_session,persistence,'EXTEND')
    novel,chapter,shot,_=persistence
    source={'clip_index':2,'clip_plan_revision':1,'generated_by_task_id':task.id,'result_url':task.result_url}
    clip={'previous_clip_index':2,'clip_plan_revision':1}
    current=service.resolve_extend_previous_av(db_session,novel.id,chapter.id,shot,clip,source)
    changed={**source,'physical_output':{**current['physical_output'],'sha256':'old'}}
    with pytest.raises(ValueError,match='PREVIOUS_AV_UNAVAILABLE'):
        service.resolve_extend_previous_av(db_session,novel.id,chapter.id,shot,clip,changed)
    Path(current['local_path']).write_bytes(b'changed')
    with pytest.raises(ValueError,match='NATIVE_CONTINUITY_OUTPUT_INVALID'):
        service.resolve_extend_previous_av(db_session,novel.id,chapter.id,shot,clip,source)


@pytest.mark.asyncio
async def test_raw39_cannot_be_persisted_as_native(db_session,persistence,monkeypatch):
    novel,chapter,shot,previous=persistence
    metadata={'execution_scope':'CLIP','clip_index':2,'clip_plan_revision':1,
              'execution_contract':{'capability':'EXTEND','artifact_kind':av.NATIVE_CONTINUITY_OUTPUT,'previous_clip':previous}}
    task=Task(id='raw-rejected',type='shot_video',status='running',name='raw',novel_id=novel.id,
              chapter_id=chapter.id,shot_id=shot.id,metadata_json=json.dumps(metadata))
    db_session.add(task);db_session.commit()
    async def download(**_kwargs):raise AssertionError('Raw must be rejected before download')
    monkeypatch.setattr(service.file_storage,'download_video',download)
    await service._save_generated_video({'video_url':'raw39.mp4','output_node_id':'39'},task,novel.id,chapter.id,1,
                      db_session,task.id,ShotRepository(db_session),clip_metadata=metadata,update_shot_result=False)
    assert task.status=='failed' and task.error_message=='NATIVE_CONTINUITY_OUTPUT_UNAVAILABLE'
    assert task.result_url is None


def test_209_previous_447_native_replaces_overlap_without_raw_duplication():
    plan=av.continuous_assembly_spans([unit('c1',209),unit('c2',447,('c1',209),capability='EXTEND')])
    assert plan['frame_count']==447 and plan['frame_count']!=486
    assert [(s['task_id'],s['start_frame'],s['end_frame']) for s in plan['spans']]==[('c1',0,170),('c2',170,447)]
    assert plan['boundaries'][0]['global_overlap_start']==170


@pytest.mark.parametrize('invalid_audio',[{'has_audio':False},{'audio_start_time':.5},{'audio_duration':1}])
def test_native_persistence_rejects_missing_or_misaligned_audio(monkeypatch,invalid_audio):
    monkeypatch.setattr(av,'probe_clip_av',lambda _: {**physical(447),**invalid_audio})
    contract={'artifact_kind':av.NATIVE_CONTINUITY_OUTPUT,'capability':'EXTEND',
              'previous_clip':{'generated_by_task_id':'c1','physical_output':physical(209)}}
    result={'physical_output_role':av.NATIVE_CONTINUITY_OUTPUT,'output_node_id':'65','video_url':'native.mp4'}
    with pytest.raises(ValueError,match='NATIVE_CONTINUITY_OUTPUT_INVALID'):
        av.continuity_output_metadata(result,contract,'native.mp4','/api/files/native.mp4')


@pytest.mark.parametrize('previous_count,source_start,native_count,expected',[(277,170,600,770),(447,0,770,770)])
def test_chained_continuity_maps_local_previous_into_global(previous_count,source_start,native_count,expected):
    plan=av.continuous_assembly_spans([unit('c1',209),unit('c2',447,('c1',209),capability='EXTEND'),
       unit('c3',native_count,('c2',previous_count),capability='TEMPORAL_EXTEND',source_start=source_start)])
    assert plan['frame_count']==expected
    assert plan['boundaries'][1]['global_overlap_start']==408
    assert plan['boundaries'][1]['local_overlap_start']==previous_count-39
    assert plan['spans'][-1]['end_frame']==native_count


def test_cut_generate_retains_plain_boundary():
    plan=av.continuous_assembly_spans([unit('c1',209),unit('c2',447,('c1',209),capability='EXTEND'),unit('cut',100)])
    assert plan['frame_count']==547
    assert plan['spans'][-1]['start_frame']==0 and plan['spans'][-1]['global_start']==447
    assert len(plan['boundaries'])==1


@pytest.mark.parametrize('mutate',[
    lambda u:u['physical_output']['previous'].update(generated_by_task_id='wrong'),
    lambda u:u['physical_output'].update(overlap_frames=38),
    lambda u:u['physical_output'].update(fps=30),
    lambda u:u['physical_output']['previous']['physical_output'].update(frame_count=208),
    lambda u:u['physical_output'].update(physical_output_role='RAW_CONTEXT_OUTPUT'),
])
def test_invalid_mapping_timebase_and_raw_output_fail(mutate):
    second=unit('c2',447,('c1',209),capability='EXTEND');mutate(second)
    with pytest.raises(ValueError):av.continuous_assembly_spans([unit('c1',209),second])


def test_audio_uses_native_video_boundary_and_retains_full_tail():
    plan=av.continuous_assembly_spans([unit('c1',209),unit('c2',447,('c1',209),capability='EXTEND'),
                                    unit('c3',600,('c2',277),capability='TEMPORAL_EXTEND',source_start=170)])
    graph=av.continuous_assembly_filter(plan['spans'],960,544)
    assert '[v_joined]setpts=N/(24*TB)[v]' in graph
    assert 'trim=start_frame=238:end_frame=600' in graph
    assert 'atrim=start=9.916666666667:end=25.000000000000' in graph
    assert 'end_frame=598' not in graph
    assert 'trim=start_frame=170:end_frame=408' in graph
    assert 'atrim=start=7.083333333333:end=17.000000000000' in graph
    plan['spans'][-1]['physical_output']['audio_duration']=25.030
    assert 'end=25.030000000000' in av.continuous_assembly_filter(plan['spans'],960,544)


@pytest.mark.asyncio
async def test_native_reconciliation_keeps_clip_worker_authority(db_session,monkeypatch):
    from datetime import datetime,timedelta
    from unittest.mock import AsyncMock
    from app.services.task_service import TaskService
    task=Task(id='native-running',type='shot_video',status='running',name='native',
              started_at=datetime.utcnow()-timedelta(seconds=100),updated_at=datetime.utcnow()-timedelta(seconds=100),
              comfyui_prompt_id='native-prompt',metadata_json=json.dumps({'execution_scope':'CLIP','execution_contract':{'artifact_kind':av.NATIVE_CONTINUITY_OUTPUT}}))
    db_session.add(task);db_session.commit()
    svc=TaskService(db_session)
    svc.comfyui_service.get_queue_info=AsyncMock(return_value={'queue_running':[],'queue_pending':[]})
    svc.comfyui_service.client.get_prompt_state=AsyncMock(return_value={'state':'completed','history':{}})
    recover=AsyncMock(side_effect=AssertionError('No second legacy recovery owner'))
    monkeypatch.setattr(svc,'_recover_completed_shot_video_prompt',recover)
    await svc.reconcile_active_tasks([task],db=db_session)
    recover.assert_not_awaited()
