import json
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from app.models.background_job import BackgroundJob
from app.models.novel import Novel, Prop
from app.models.task import Task
from app.services import background_workers
from app.services.background_workers import PersistentJobRequest, WorkerManager


async def _noop():
    return None


def _request(task_id: str, value: str = "payload") -> PersistentJobRequest:
    return PersistentJobRequest(
        task_id=task_id,
        handler="app.services.example:run",
        payload={"value": value},
        run_local=_noop,
    )


def test_persistent_job_is_stored_and_active_enqueue_is_deduplicated(db_session, db_engine):
    task = Task(id="task-1", type="prop_image", status="pending", name="prop")
    db_session.add(task)
    db_session.commit()
    manager = WorkerManager(sessionmaker(bind=db_engine, autocommit=False, autoflush=False))

    first_id = manager.persist(_request(task.id), "prop_image")
    second_id = manager.persist(_request(task.id, "changed"), "prop_image")

    assert first_id == second_id
    job = db_session.query(BackgroundJob).filter(BackgroundJob.id == first_id).one()
    assert job.status == "queued"
    assert job.queue_name == "prop_image"
    assert json.loads(job.payload_json) == {"value": "payload"}


def test_restart_requeues_running_job_from_database(db_session, db_engine, monkeypatch):
    task = Task(id="task-2", type="scene_image", status="running", name="scene")
    job = BackgroundJob(
        id="job-2",
        task_id=task.id,
        queue_name="scene_image",
        handler="app.services.example:run",
        payload_json="{}",
        status="running",
    )
    db_session.add_all([task, job])
    db_session.commit()
    manager = WorkerManager(sessionmaker(bind=db_engine, autocommit=False, autoflush=False))
    signalled = []

    class FakeWorker:
        def signal(self, job_id):
            signalled.append(job_id)

    monkeypatch.setattr(manager, "worker", lambda name: FakeWorker())

    assert manager.resume_persisted() == 1
    db_session.expire_all()
    assert db_session.query(BackgroundJob).filter_by(id=job.id).one().status == "queued"
    assert signalled == [job.id]


def test_restart_does_not_replay_terminal_task(db_session, db_engine, monkeypatch):
    task = Task(id="task-3", type="prop_image", status="completed", name="prop")
    job = BackgroundJob(
        id="job-3",
        task_id=task.id,
        queue_name="prop_image",
        handler="app.services.example:run",
        payload_json="{}",
        status="running",
    )
    db_session.add_all([task, job])
    db_session.commit()
    manager = WorkerManager(sessionmaker(bind=db_engine, autocommit=False, autoflush=False))
    monkeypatch.setattr(manager, "worker", lambda name: (_ for _ in ()).throw(AssertionError(name)))

    assert manager.resume_persisted() == 0
    db_session.expire_all()
    assert db_session.query(BackgroundJob).filter_by(id=job.id).one().status == "completed"


def test_legacy_running_prop_without_prompt_is_backfilled(db_session, db_engine, monkeypatch):
    novel = Novel(id="novel-1", title="novel")
    prop = Prop(
        id="prop-1",
        novel_id=novel.id,
        name="床",
        appearance="木床",
        description="道具",
        generating_status="running",
    )
    task = Task(
        id="task-4",
        type="prop_image",
        status="running",
        name="prop",
        prop_id=prop.id,
        novel_id=novel.id,
    )
    db_session.add_all([novel, prop, task])
    db_session.commit()
    manager = WorkerManager(sessionmaker(bind=db_engine, autocommit=False, autoflush=False))
    monkeypatch.setattr(background_workers, "worker_manager", manager)
    captured = []
    monkeypatch.setattr(
        "app.services.prop_image_service.enqueue_prop_image_task",
        lambda **payload: captured.append(payload),
    )

    assert background_workers.resume_legacy_asset_jobs() == 1
    db_session.expire_all()
    recovered = db_session.query(Task).filter_by(id=task.id).one()
    assert recovered.status == "pending"
    assert recovered.started_at is None
    assert captured == [{
        "task_id": task.id,
        "prop_id": prop.id,
        "name": prop.name,
        "appearance": prop.appearance,
        "description": prop.description,
    }]


def test_all_product_worker_enqueues_use_persistent_descriptors():
    app_root = Path(__file__).parents[1] / "app"
    violations = []
    for path in app_root.rglob("*.py"):
        if path.name == "background_workers.py":
            continue
        source = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(source.splitlines(), 1):
            if "worker_manager.worker(" in line and ".enqueue(persistent_job(" not in line:
                violations.append(f"{path.relative_to(app_root)}:{line_number}")
    assert violations == []

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from app.services.background_workers import (
    persistent_job, resume_image_prompt, save_image_prompt,
)
from app.services.comfyui.service import ComfyUIService


def _manager(engine):
    return WorkerManager(sessionmaker(bind=engine, autocommit=False, autoflush=False))


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
@pytest.mark.parametrize("job_status", ["queued", "running"])
def test_terminal_task_never_replayed(db_session, db_engine, monkeypatch, status, job_status):
    task = Task(id="terminal", type="prop_image", status=status, name="terminal")
    job = BackgroundJob(id="terminal-job", task_id=task.id, queue_name="prop_image",
                        handler="example:run", payload_json="{}", status=job_status)
    db_session.add_all([task, job]); db_session.commit()
    manager = _manager(db_engine)
    monkeypatch.setattr(manager, "worker", lambda _: pytest.fail("terminal replay"))
    assert manager.resume_persisted() == 0
    db_session.expire_all()
    assert db_session.get(Task, task.id).status == status
    assert db_session.get(BackgroundJob, job.id).status == "completed"


def test_database_rejects_racing_active_descriptors(db_session, db_engine):
    task=Task(id="racing",type="prop_image",status="pending",name="racing")
    db_session.add(task);db_session.commit()
    manager=_manager(db_engine)
    job_id=manager.persist(_request(task.id),"image")
    db_session.add(BackgroundJob(id=job_id, task_id=task.id, queue_name="image",
                                handler="app.services.example:run", status="queued"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
    assert db_session.query(BackgroundJob).count()==1
    # A finished execution has the same identity and cannot be revived by API retry.
    job=db_session.get(BackgroundJob,job_id);job.status="completed";db_session.commit()
    assert _manager(db_engine).persist(_request(task.id,"changed"),"image")==job_id
    db_session.refresh(job)
    assert job.status=="completed"


@pytest.mark.asyncio
async def test_duplicate_startup_and_claim_do_not_duplicate_execution(db_session, db_engine):
    task = Task(id="startup", type="prop_image", status="pending", name="startup")
    db_session.add(task); db_session.commit()
    manager = _manager(db_engine)
    entered, finish = asyncio.Event(), asyncio.Event()
    calls = []
    async def local():
        calls.append("run")
        entered.set()
        await finish.wait()
    manager.worker("image").enqueue(persistent_job(task.id, "example:run", {}, local))
    await asyncio.wait_for(entered.wait(), 1)
    job = db_session.query(BackgroundJob).one(); db_session.refresh(job)
    assert manager.resume_persisted() == 0
    await manager.run_persisted(job.id)
    assert calls == ["run"]
    finish.set()
    await asyncio.wait_for(manager.worker("image")._queue.join(), 1)
    db_session.refresh(job)
    assert job.status == "completed" and job.attempts == 1
    await manager.stop()


@pytest.mark.asyncio
async def test_shutdown_leaves_running_job_recoverable(db_session, db_engine, monkeypatch):
    task = Task(id="shutdown", type="prop_image", status="pending", name="shutdown")
    db_session.add(task); db_session.commit()
    manager = _manager(db_engine); entered = asyncio.Event()
    async def local():
        entered.set(); await asyncio.Event().wait()
    manager.worker("image").enqueue(persistent_job(task.id, "example:run", {}, local))
    await asyncio.wait_for(entered.wait(), 1)
    await manager.stop()
    db_session.expire_all(); job = db_session.query(BackgroundJob).one()
    assert job.status == "running"
    signals = []
    restarted = _manager(db_engine)
    monkeypatch.setattr(restarted, "worker", lambda _: SimpleNamespace(signal=signals.append))
    assert restarted.resume_persisted() == 1
    assert signals == [job.id]


@pytest.mark.asyncio
async def test_worker_exception_ends_active_task_and_is_not_replayed(db_session, db_engine, monkeypatch):
    task = Task(id="error", type="prop_image", status="pending", name="error")
    db_session.add(task); db_session.commit()
    manager = _manager(db_engine)
    job_id = manager.persist(_request(task.id), "image")
    async def fail(**kwargs):
        raise RuntimeError("handler failed")
    monkeypatch.setattr(background_workers.importlib, "import_module", lambda _: SimpleNamespace(run=fail))
    with pytest.raises(RuntimeError, match="handler failed"):
        await manager.run_persisted(job_id)
    db_session.expire_all()
    assert db_session.get(Task, task.id).status == "failed"
    assert db_session.get(BackgroundJob, job_id).status == "failed"
    assert manager.resume_persisted() == 0


@pytest.mark.asyncio
async def test_running_cancellation_closes_job_without_killing_consumer(db_session, db_engine):
    task = Task(id="cancel-running", type="prop_image", status="pending", name="cancel")
    db_session.add(task); db_session.commit()
    manager = _manager(db_engine)
    async def local():
        db_session.refresh(task); task.status = "cancelled"; db_session.commit()
        raise asyncio.CancelledError()
    manager.worker("image").enqueue(persistent_job(task.id, "example:run", {}, local))
    await asyncio.wait_for(manager.worker("image")._queue.join(), 1)
    db_session.expire_all(); job = db_session.query(BackgroundJob).one()
    assert job.status == "completed" and task.status == "cancelled"
    assert not manager.worker("image")._runner.done()
    await manager.stop()


@pytest.mark.parametrize("status", ["queued", "running"])
def test_video_prompt_is_delegated_even_with_stale_queued_job(db_session, db_engine, monkeypatch, status):
    task = Task(id="video", type="shot_video", status="running", name="video", comfyui_prompt_id="existing")
    job = BackgroundJob(id="video-job", task_id=task.id, queue_name="shot_video",
        handler="app.services.shot_video_service:generate_shot_video_task", payload_json="{}", status=status)
    db_session.add_all([task, job]); db_session.commit()
    manager = _manager(db_engine)
    monkeypatch.setattr(manager, "worker", lambda _: pytest.fail("duplicate video generation"))
    assert manager.resume_persisted() == 0
    assert task.comfyui_prompt_id == "existing"


def _image_workflow():
    return {"pe": {"class_type": "QwenPERewriteT8", "inputs": {"seed": 42}},
            "save": {"class_type": "SaveImage", "inputs": {}},
            "reference": {"class_type": "LoadImage", "inputs": {"image": "frozen.png"}}}


@pytest.mark.asyncio
async def test_image_retry_receipt_and_budget_survive_restarts(db_session):
    task = Task(id="image-retry", type="prop_image", status="running", name="retry",
                metadata_json=json.dumps({"required_image_provenance": {"revision": 7}}))
    db_session.add(task); db_session.commit()
    graph = _image_workflow()
    save_image_prompt(db_session, task, "initial", graph, "save")
    service = ComfyUIService.__new__(ComfyUIService); service.client = MagicMock()
    malformed = {"success": False, "message": "unmatched thinking block close"}
    service.client.wait_for_result = AsyncMock(return_value=malformed)
    service.client.queue_prompt = AsyncMock(return_value={"success": True, "prompt_id": "retry"})
    result = await resume_image_prompt(db_session, task, service)
    assert result["prompt_id"] == "retry"
    db_session.expire_all(); task = db_session.get(Task, task.id)
    assert json.loads(task.metadata_json)["image_attempt"]["rewrite_retry_used"] is True
    assert json.loads(task.metadata_json)["required_image_provenance"] == {"revision": 7}
    assert json.loads(task.workflow_json)["reference"]["inputs"]["image"] == "frozen.png"
    latest_seed = json.loads(task.workflow_json)["pe"]["inputs"]["seed"]
    assert latest_seed != 42
    await resume_image_prompt(db_session, task, service)
    assert service.client.queue_prompt.await_count == 1
    assert service.client.wait_for_result.await_args.args[0] == "retry"
    assert service.client.wait_for_result.await_args.args[1]["pe"]["inputs"]["seed"] == latest_seed


@pytest.mark.asyncio
async def test_initial_g3_retry_callback_persists_consumed_budget(db_session):
    task = Task(id="normal-retry", type="scene_image", status="running", name="retry")
    db_session.add(task); db_session.commit()
    graph = _image_workflow()
    save_image_prompt(db_session, task, "first", graph, "save")
    save_image_prompt(db_session, task, "second", graph, "save")
    service = ComfyUIService.__new__(ComfyUIService); service.client = MagicMock()
    service.client.wait_for_result = AsyncMock(return_value={"success": False, "message": "format validation"})
    service.client.queue_prompt = AsyncMock(side_effect=AssertionError("budget renewed"))
    await resume_image_prompt(db_session, task, service)
    service.client.queue_prompt.assert_not_awaited()


@pytest.mark.asyncio
async def test_old_image_receipt_without_retry_context_fails_closed(db_session):
    task = Task(id="old-receipt", type="scene_image", status="running", name="old",
                comfyui_prompt_id="old", workflow_json=json.dumps(_image_workflow()))
    db_session.add(task); db_session.commit()
    service = ComfyUIService.__new__(ComfyUIService); service.client = MagicMock()
    service.client.wait_for_result = AsyncMock(return_value={"success": False, "message": "format validation"})
    service.client.queue_prompt = AsyncMock(side_effect=AssertionError("unknown old budget"))
    await resume_image_prompt(db_session, task, service)
    service.client.queue_prompt.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["character", "scene", "prop", "shot", "keyframe"])
@pytest.mark.parametrize("cancelled", [False, True])
async def test_each_image_handler_resumes_frozen_graph_without_rebuilding(db_session, monkeypatch, kind, cancelled):
    from app.models.novel import Character, Scene, Chapter
    from app.models.shot import Shot
    from app.services import character_service, scene_service, prop_image_service, shot_image_service, shot_keyframe_service
    novel = Novel(id="resume-novel", title="resume")
    chapter = Chapter(id="resume-chapter", novel_id=novel.id, number=1, title="chapter")
    character = Character(id="resume-character", novel_id=novel.id, name="character")
    scene = Scene(id="resume-scene", novel_id=novel.id, name="scene")
    prop = Prop(id="resume-prop", novel_id=novel.id, name="prop", existence="REAL")
    shot = Shot(id="resume-shot", chapter_id=chapter.id, index=1, keyframes='[{"frame_index":1}]')
    task = Task(id="resume-image", type="keyframe_image" if kind == "keyframe" else "shot_image" if kind == "shot" else kind+"_image",
                status="running", name="resume", novel_id=novel.id, chapter_id=chapter.id, shot_id=shot.id)
    db_session.add_all([novel, chapter, character, scene, prop, shot, task]); db_session.commit()
    graph = {"save": {"class_type": "SaveImage", "inputs": {}}}
    save_image_prompt(db_session, task, "frozen-prompt", graph, "save")
    async def wait(*args, **kwargs):
        if cancelled:
            task.status = "cancelled"; db_session.commit()
            raise RuntimeError("transport failed after cancellation")
        return {"success":False,"message":"GPU OOM"}
    service = SimpleNamespace(client=SimpleNamespace(wait_for_result=AsyncMock(side_effect=wait)),
        builder=MagicMock(side_effect=AssertionError("must not rebuild")))
    monkeypatch.setattr("app.core.database.SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    from contextlib import nullcontext
    with pytest.raises(asyncio.CancelledError) if cancelled else nullcontext():
        if kind in {"character", "scene", "prop"}:
            module, cls, method, entity = {
                "character":(character_service, character_service.CharacterService, "_generate_portrait_task", character),
                "scene":(scene_service, scene_service.SceneService, "_generate_scene_image_task", scene),
                "prop":(prop_image_service, prop_image_service.PropService, "_generate_prop_image_task", prop),
            }[kind]
            obj=cls.__new__(cls); obj.comfyui_service=service
            await getattr(obj,method)(task.id, entity.id, entity.name, "identity", "description")
        elif kind == "shot":
            monkeypatch.setattr(shot_image_service, "SessionLocal", lambda: db_session)
            monkeypatch.setattr(shot_image_service, "ComfyUIService", lambda: service)
            await shot_image_service.generate_shot_image_task(task.id,novel.id,chapter.id,1,"shot prompt","deleted-workflow")
        else:
            monkeypatch.setattr(shot_keyframe_service, "ComfyUIService", lambda: service)
            obj=shot_keyframe_service.ShotKeyframeService.__new__(shot_keyframe_service.ShotKeyframeService)
            with pytest.raises(ValueError, match="GPU OOM"):
                await obj._generate_keyframe_image_task(db_session,task.id,shot.id,0,"deleted-workflow")
    assert service.client.wait_for_result.await_count == 1
    assert service.client.wait_for_result.await_args.args[:3] == ("frozen-prompt",graph,"save")
    db_session.refresh(task)
    assert json.loads(task.workflow_json) == graph
    assert task.status == ("cancelled" if cancelled else "failed") and task.comfyui_prompt_id == "frozen-prompt"


@pytest.mark.asyncio
@pytest.mark.parametrize("live", [False, True])
async def test_pending_timeout_exempts_only_live_execution(db_session, db_engine, monkeypatch, live):
    from app.services.task_service import TaskService
    task=Task(id="pending-old",type="prop_image",status="pending",name="pending",
              created_at=datetime.utcnow()-timedelta(hours=2))
    job=BackgroundJob(id="pending-job",task_id=task.id,queue_name="image",handler="example:run",status="queued")
    db_session.add_all([task,job]);db_session.commit()
    monkeypatch.setattr(background_workers.worker_manager,"is_live",lambda jid:live)
    service=TaskService(db_session)
    service.comfyui_service.get_queue_info=AsyncMock(return_value={"queue_running":[],"queue_pending":[]})
    await service.reconcile_active_tasks([task],db=db_session)
    db_session.refresh(task)
    assert task.status == ("pending" if live else "failed")


@pytest.mark.asyncio
async def test_interrupted_clip_only_task_fails_without_second_recovery_authority(db_session, monkeypatch):
    from app.services.task_service import TaskService
    task=Task(id="interrupted-clip",type="shot_video",status="running",name="clip",comfyui_prompt_id="existing-video",
              started_at=datetime.utcnow()-timedelta(hours=2),updated_at=datetime.utcnow()-timedelta(hours=2),
              metadata_json=json.dumps({"execution_scope":"CLIP","execution_contract":{"artifact_kind":"CLIP_ONLY"}}))
    job=BackgroundJob(id="clip-job",task_id=task.id,queue_name="shot_video",handler="app.services.shot_video_service:generate_shot_video_task",status="running")
    db_session.add_all([task,job]);db_session.commit()
    service=TaskService(db_session)
    service.comfyui_service.get_queue_info=AsyncMock(return_value={"queue_running":[],"queue_pending":[]})
    service.comfyui_service.client.get_prompt_state=AsyncMock(return_value={"state":"completed","history":{"outputs":{}}})
    monkeypatch.setattr(service,"_recover_completed_shot_video_prompt",AsyncMock(side_effect=AssertionError("second authority")))
    await service.reconcile_active_tasks([task],db=db_session)
    assert task.status == "failed" and task.comfyui_prompt_id == "existing-video"
    service._recover_completed_shot_video_prompt.assert_not_awaited()

@pytest.mark.parametrize("module_name, function_name, payload", [
    ("app.api.shots", "enqueue_shot_image_batch_task", {"batch_task_id":"descriptor-image-batch"}),
    ("app.api.shots", "enqueue_shot_video_batch_task", {"batch_task_id":"descriptor-video-batch"}),
    ("app.api.shots", "enqueue_chapter_video_merge_task", {"task_id":"descriptor-chapter-merge"}),
    ("app.services.hd_repaint_service", "enqueue_hd_repaint_task", {"task_id":"descriptor-hd"}),
    ("app.services.hd_repaint_service", "enqueue_hd_repaint_batch", {"batch_id":"descriptor-hd-batch"}),
    ("app.services.novel_video_merge_service", "enqueue_novel_video_merge_task", {"task_id":"descriptor-novel-merge"}),
    ("app.services.shot_audio_service", "enqueue_shot_audio_task", {
        "task_id":"descriptor-audio","novel_id":"novel","chapter_id":"chapter","shot_index":3,
        "character_name":"角色","text":"台词","emotion_prompt":"自然","reference_audio_url":"/ref.flac",
        "workflow_id":"audio-workflow","dialogue_type":"narration"}),
    ("app.services.transition_service", "enqueue_transition_video_task", {
        "task_id":"descriptor-transition","novel_id":"novel","chapter_id":"chapter",
        "from_index":2,"to_index":3,"workflow_id":"transition-workflow","duration_seconds":2.5,"frame_count":49}),
])
def test_enqueue_descriptors_preserve_parameters_without_executing_business(monkeypatch, module_name, function_name, payload):
    import importlib
    import inspect
    module=importlib.import_module(module_name)
    captured=[]
    monkeypatch.setattr(module,"worker_manager",SimpleNamespace(worker=lambda _:SimpleNamespace(enqueue=captured.append)))
    for name in ("shot_image_batch_locks","shot_video_batch_locks","_active_hd_tasks","_active_hd_batches"):
        if hasattr(module,name):monkeypatch.setattr(module,name,set())
    getattr(module,function_name)(**payload)
    assert len(captured)==1 and isinstance(captured[0],PersistentJobRequest)
    request=captured[0]
    assert request.payload==payload
    handler_module,handler_name=request.handler.split(":")
    handler=getattr(importlib.import_module(handler_module),handler_name)
    inspect.signature(handler).bind(**json.loads(json.dumps(request.payload)))


@pytest.mark.asyncio
@pytest.mark.parametrize("kind",["dialogue","voice","transition"])
async def test_non_image_prompt_receipt_is_resumed_without_resubmitting(db_session, monkeypatch, kind):
    from app.models.novel import Chapter
    from app.services import character_service,shot_audio_service,transition_service
    novel=Novel(id="audio-novel",title="audio")
    chapter=Chapter(id="audio-chapter",novel_id=novel.id,number=1,title="chapter")
    graph={"output":{"class_type":"SaveAudio","inputs":{}}}
    metadata={"audio_attempt":{"save_audio_node_id":"output"},"transition_attempt":{
        "video_save_node_id":"output","first_video_name":"first","second_video_name":"second"}}
    task=Task(id="audio-resume",type="shot_audio",status="running",name="resume",comfyui_prompt_id="receipt",
        workflow_json=json.dumps(graph),metadata_json=json.dumps(metadata),novel_id=novel.id,chapter_id=chapter.id)
    db_session.add_all([novel,chapter,task]);db_session.commit()
    client=SimpleNamespace(wait_for_audio_result=AsyncMock(return_value={"success":False,"message":"GPU OOM"}),
        wait_for_result=AsyncMock(return_value={"success":False,"message":"GPU OOM"}),
        queue_prompt=AsyncMock(side_effect=AssertionError("resubmitted")))
    service=SimpleNamespace(client=client)
    monkeypatch.setattr("app.core.database.SessionLocal",lambda:db_session)
    monkeypatch.setattr(db_session,"close",lambda:None)
    if kind=="voice":
        obj=character_service.CharacterService.__new__(character_service.CharacterService);obj.comfyui_service=service
        await obj._generate_voice_task(task.id,"character","name","voice")
    elif kind=="dialogue":
        obj=shot_audio_service.ShotAudioService.__new__(shot_audio_service.ShotAudioService);obj.comfyui_service=service
        await obj._generate_audio_task(task.id,novel.id,chapter.id,1,"name","text","emotion","deleted-ref","deleted-workflow")
    else:
        monkeypatch.setattr(transition_service,"SessionLocal",lambda:db_session)
        monkeypatch.setattr(transition_service,"ComfyUIService",lambda:service)
        await transition_service.generate_transition_video_task(task.id,novel.id,chapter.id,1,2,"deleted-workflow")
    wait=client.wait_for_result if kind=="transition" else client.wait_for_audio_result
    assert wait.await_count==1 and wait.await_args.args[:3]==("receipt",graph,"output")
    client.queue_prompt.assert_not_awaited()
    assert task.status=="failed" and task.comfyui_prompt_id=="receipt"

@pytest.mark.asyncio
async def test_taskservice_next_window_gets_new_descriptor_after_delegated_job(db_session, db_engine, monkeypatch):
    from app.models.novel import Chapter
    from app.models.shot import Shot
    from app.services.task_service import TaskService
    from app.services import shot_video_service
    novel=Novel(id="next-novel",title="next")
    chapter=Chapter(id="next-chapter",novel_id=novel.id,number=1,title="chapter")
    shot=Shot(id="next-shot",chapter_id=chapter.id,index=1,image_url="/image.png")
    task=Task(id="next-task",type="shot_video",status="running",name="next",novel_id=novel.id,
        chapter_id=chapter.id,shot_id=shot.id,workflow_id="workflow",comfyui_prompt_id="finished-window")
    old=BackgroundJob(id="old-window-job",task_id=task.id,queue_name="shot_video",status="running",
        handler="app.services.shot_video_service:generate_shot_video_task",payload_json='{"only_window_index":1}')
    db_session.add_all([novel,chapter,shot,task,old]);db_session.commit()
    manager=_manager(db_engine);captured=[]
    monkeypatch.setattr(background_workers,"worker_manager",manager)
    monkeypatch.setattr(shot_video_service,"worker_manager",SimpleNamespace(worker=lambda queue:SimpleNamespace(
        enqueue=lambda request:captured.append((manager.persist(request,queue),request.payload)))))
    monkeypatch.setattr(shot_video_service,"_queued_shot_video_task_ids",set())
    TaskService(db_session)._enqueue_remaining_shot_video_clip(task,2,db_session)
    db_session.expire_all()
    assert db_session.get(BackgroundJob,old.id).status=="completed"
    assert captured[0][0]!=old.id and captured[0][1]["only_window_index"]==2
    assert task.comfyui_prompt_id is None


@pytest.mark.asyncio
async def test_keyframe_retry_and_fallback_are_bounded_after_restart(db_session, monkeypatch):
    from app.models.novel import Chapter
    from app.models.shot import Shot
    from app.services import shot_keyframe_service
    novel=Novel(id="kf-novel",title="keyframe")
    chapter=Chapter(id="kf-chapter",novel_id=novel.id,number=1,title="chapter")
    shot=Shot(id="kf-shot",chapter_id=chapter.id,index=1,keyframes='[{"frame_index":1}]')
    task=Task(id="kf-task",type="keyframe_image",status="running",name="keyframe",
        comfyui_prompt_id="latest-fallback",workflow_json=json.dumps(_image_workflow()),metadata_json=json.dumps({
            "image_attempt":{"save_image_node_id":"save","rewrite_retry_used":True,"rewrite_fallback_used":True}}))
    db_session.add_all([novel,chapter,shot,task]);db_session.commit()
    client=SimpleNamespace(wait_for_result=AsyncMock(return_value={"success":False,"message":"thinking block"}),
        queue_prompt=AsyncMock(side_effect=AssertionError("retry renewed")))
    monkeypatch.setattr(shot_keyframe_service,"ComfyUIService",lambda:SimpleNamespace(client=client))
    obj=shot_keyframe_service.ShotKeyframeService.__new__(shot_keyframe_service.ShotKeyframeService)
    with pytest.raises(ValueError,match="thinking block"):
        await obj._generate_keyframe_image_task(db_session,task.id,shot.id,0,"deleted-workflow")
    client.queue_prompt.assert_not_awaited()
    assert task.status=="failed" and task.comfyui_prompt_id=="latest-fallback"

@pytest.mark.parametrize("status", ["queued", "failed", "completed", "cancelled"])
def test_pending_or_terminal_execution_restart_is_deterministic(db_session, db_engine, monkeypatch, status):
    task=Task(id="pending-restart",type="prop_image",status="pending",name="pending")
    job=BackgroundJob(id="restart-job",task_id=task.id,queue_name="image",handler="example:run",status=status)
    db_session.add_all([task,job]);db_session.commit()
    manager=_manager(db_engine);signals=[]
    monkeypatch.setattr(manager,"worker",lambda _:SimpleNamespace(signal=signals.append))
    assert manager.resume_persisted()==(1 if status=="queued" else 0)
    assert signals==([job.id] if status=="queued" else [])


def test_background_job_table_creation_is_idempotent(db_session, db_engine):
    from app.core.database import Base
    from sqlalchemy import inspect
    task=Task(id="schema-task",type="prop_image",status="pending",name="schema")
    db_session.add(task);db_session.commit()
    Base.metadata.create_all(bind=db_engine)
    Base.metadata.create_all(bind=db_engine)
    assert db_session.get(Task,task.id).name=="schema"
    indexes=inspect(db_engine).get_indexes("background_jobs")
    assert inspect(db_engine).get_pk_constraint("background_jobs")["constrained_columns"]==["id"]


def test_legacy_asset_with_saved_prompt_is_backfilled_without_losing_receipt(db_session, db_engine, monkeypatch):
    novel=Novel(id="legacy-receipt-novel",title="legacy")
    prop=Prop(id="legacy-receipt-prop",novel_id=novel.id,name="prop",existence="REAL")
    task=Task(id="legacy-receipt-task",type="prop_image",status="running",name="legacy",prop_id=prop.id,
        comfyui_prompt_id="legacy-prompt",workflow_json=json.dumps(_image_workflow()))
    db_session.add_all([novel,prop,task]);db_session.commit()
    manager=_manager(db_engine)
    monkeypatch.setattr(background_workers,"worker_manager",manager)
    captured=[]
    monkeypatch.setattr("app.services.prop_image_service.enqueue_prop_image_task",lambda **payload:captured.append(payload))
    assert background_workers.resume_legacy_asset_jobs()==1
    db_session.refresh(task)
    assert captured[0]["task_id"]==task.id
    assert task.comfyui_prompt_id=="legacy-prompt" and json.loads(task.workflow_json)==_image_workflow()


@pytest.mark.asyncio
async def test_normal_g3_reserves_retry_before_a_receipt_gap(db_session):
    task=Task(id="reserved-retry",type="prop_image",status="running",name="reserved")
    db_session.add(task);db_session.commit()
    save_image_prompt(db_session,task,"first-receipt",_image_workflow(),"save",reserve_retry=True)
    # A crash may hide whether G3 issued its retry. Recovery must not renew it.
    db_session.expire_all();task=db_session.get(Task,task.id)
    service=ComfyUIService.__new__(ComfyUIService);service.client=MagicMock()
    service.client.wait_for_result=AsyncMock(return_value={"success":False,"message":"thinking block"})
    service.client.queue_prompt=AsyncMock(side_effect=AssertionError("reserved retry renewed after restart"))
    result=await resume_image_prompt(db_session,task,service)
    assert result["success"] is False
    assert json.loads(task.metadata_json)["image_attempt"]["rewrite_retry_reserved"] is True
    service.client.queue_prompt.assert_not_awaited()
