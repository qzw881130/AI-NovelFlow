"""Database-backed serial background queues.

The asyncio queues are wake-up signals only.  Every product job is written to
``background_jobs`` before it is signalled, so a backend restart can replay the
same execution descriptor instead of losing an in-memory closure.
"""
import asyncio
import importlib
import inspect
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, Optional


JobFactory = Callable[[], Awaitable[None]]


@dataclass
class PersistentJobRequest:
    task_id: str
    handler: str
    payload: Dict[str, Any]
    run_local: JobFactory

    async def __call__(self) -> None:
        """Keep the request callable for lightweight worker fakes in tests."""
        await self.run_local()


def persistent_job(
    task_id: str,
    handler: str,
    payload: Dict[str, Any],
    run_local: JobFactory,
) -> PersistentJobRequest:
    return PersistentJobRequest(
        task_id=task_id,
        handler=handler,
        payload=payload,
        run_local=run_local,
    )


class AsyncWorker:
    """FIFO worker that runs one async job at a time."""

    def __init__(self, name: str, manager: "WorkerManager"):
        self.name = name
        self.manager = manager
        self._queue: asyncio.Queue[Any] = asyncio.Queue()
        self._runner: Optional[asyncio.Task] = None
        self._signalled_job_ids: set[str] = set()

    def enqueue(self, job_factory: JobFactory) -> None:
        if isinstance(job_factory, PersistentJobRequest):
            job_id = self.manager.persist(job_factory, self.name)
            self.manager._local_factories.setdefault(job_id, job_factory.run_local)
            self.signal(job_id)
            return
        # Compatibility for non-product/test-only closures. Product callers
        # must use persistent_job so restart recovery remains possible.
        self._ensure_started()
        self._queue.put_nowait(job_factory)

    def signal(self, job_id: str) -> None:
        if job_id in self._signalled_job_ids:
            return
        self._ensure_started()
        self._signalled_job_ids.add(job_id)
        self._queue.put_nowait(job_id)

    def _ensure_started(self) -> None:
        if self._runner and not self._runner.done():
            return
        self._runner = asyncio.create_task(self._run())

    async def _run(self) -> None:
        while True:
            queued_item = await self._queue.get()
            try:
                if isinstance(queued_item, str):
                    await self.manager.run_persisted(queued_item)
                else:
                    await queued_item()
            except Exception as exc:
                print(f"[Worker:{self.name}] job failed: {exc}")
            finally:
                if isinstance(queued_item, str):
                    self._signalled_job_ids.discard(queued_item)
                self._queue.task_done()

    async def stop(self) -> None:
        if not self._runner:
            return
        self._runner.cancel()
        try:
            await self._runner
        except asyncio.CancelledError:
            pass
        self._runner = None
        self._signalled_job_ids.clear()
        while not self._queue.empty():
            self._queue.get_nowait()
            self._queue.task_done()


class WorkerManager:
    def __init__(self, session_factory=None):
        self._workers: Dict[str, AsyncWorker] = {}
        self._session_factory = session_factory
        self._local_factories: Dict[str, JobFactory] = {}

    def is_live(self, job_id: str) -> bool:
        return any(
            job_id in worker._signalled_job_ids
            and worker._runner is not None
            and not worker._runner.done()
            for worker in self._workers.values()
        )

    def _session(self):
        if self._session_factory is not None:
            return self._session_factory()
        from app.core.database import SessionLocal
        return SessionLocal()

    def worker(self, name: str) -> AsyncWorker:
        if name not in self._workers:
            self._workers[name] = AsyncWorker(name, self)
        return self._workers[name]

    def persist(self, request: PersistentJobRequest, queue_name: str) -> str:
        from app.models.background_job import BackgroundJob
        from sqlalchemy.exc import IntegrityError

        db = self._session()
        try:
            existing = db.query(BackgroundJob).filter(
                BackgroundJob.task_id == request.task_id,
                BackgroundJob.queue_name == queue_name,
                BackgroundJob.handler == request.handler,
                BackgroundJob.status.in_(["queued", "running"]),
            ).order_by(BackgroundJob.created_at.asc()).first()
            if existing:
                return existing.id

            # Reuse the existing primary-key constraint, including on databases
            # where this table already exists. Window continuation is a distinct
            # execution of the same product Task; payload edits are not.
            job_id = str(uuid.uuid5(uuid.NAMESPACE_URL, json.dumps([
                request.task_id, queue_name, request.handler,
                request.payload.get("only_window_index"),
            ], ensure_ascii=False)))
            finished = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
            if finished:
                return finished.id
            job = BackgroundJob(
                id=job_id,
                task_id=request.task_id,
                queue_name=queue_name,
                handler=request.handler,
                payload_json=json.dumps(request.payload, ensure_ascii=False),
                status="queued",
            )
            db.add(job)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                # The DB, rather than a process-local lock, arbitrates racing enqueues.
                existing = db.query(BackgroundJob).filter(
                    BackgroundJob.id == job_id,
                ).first()
                if existing is None:
                    raise
                return existing.id
            db.refresh(job)
            return job.id
        finally:
            db.close()

    async def run_persisted(self, job_id: str) -> None:
        from app.models.background_job import BackgroundJob
        from app.models.task import Task

        db = self._session()
        try:
            job = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
            if not job or job.status != "queued":
                return
            task = db.query(Task).filter(Task.id == job.task_id).first()
            if not task or task.status in {"completed", "failed", "cancelled"}:
                job.status = "completed"
                job.completed_at = datetime.utcnow()
                db.commit()
                return
            if task.comfyui_prompt_id and job.handler == "app.services.shot_video_service:generate_shot_video_task":
                # A submitted video is exclusively reconciled by TaskService.
                return
            handler = job.handler
            payload = json.loads(job.payload_json or "{}")
            claimed = db.query(BackgroundJob).filter(
                BackgroundJob.id == job_id,
                BackgroundJob.status == "queued",
            ).update({
                BackgroundJob.status: "running",
                BackgroundJob.attempts: BackgroundJob.attempts + 1,
                BackgroundJob.started_at: datetime.utcnow(),
                BackgroundJob.last_error: None,
            }, synchronize_session=False)
            db.commit()
            if not claimed:
                return
        finally:
            db.close()

        try:
            local = self._local_factories.pop(job_id, None)
            if local is not None:
                result = local()
            else:
                module_name, function_name = handler.rsplit(":", 1)
                function = getattr(importlib.import_module(module_name), function_name)
                result = function(**payload)
            if inspect.isawaitable(result):
                await result
        except asyncio.CancelledError:
            db = self._session()
            try:
                job = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
                task = db.query(Task).filter(Task.id == job.task_id).first() if job else None
                if task and task.status in {"completed", "failed", "cancelled"}:
                    job.status = "completed"
                    job.completed_at = datetime.utcnow()
                    db.commit()
                    return
            finally:
                db.close()
            # Process shutdown leaves an active execution recoverable.
            raise
        except Exception as exc:
            db = self._session()
            try:
                job = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
                if job:
                    job.status = "failed"
                    job.last_error = str(exc)
                    job.completed_at = datetime.utcnow()
                    task = db.query(Task).filter(Task.id == job.task_id).first()
                    if task and task.status in {"pending", "running"}:
                        task.status = "failed"
                        task.error_message = str(exc)
                        task.current_step = "后台任务执行异常"
                        task.completed_at = datetime.utcnow()
                    db.commit()
            finally:
                db.close()
            raise
        else:
            db = self._session()
            try:
                job = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
                if job:
                    job.status = "completed"
                    job.completed_at = datetime.utcnow()
                    db.commit()
            finally:
                db.close()

    def resume_persisted(self) -> int:
        """Replay queued/running descriptors after process restart."""
        from app.models.background_job import BackgroundJob
        from app.models.task import Task

        db = self._session()
        try:
            jobs = db.query(BackgroundJob).filter(
                BackgroundJob.status.in_(["queued", "running"])
            ).order_by(BackgroundJob.created_at.asc(), BackgroundJob.id.asc()).all()
            resumable = []
            for job in jobs:
                task = db.query(Task).filter(Task.id == job.task_id).first()
                if not task or task.status in {"completed", "failed", "cancelled"}:
                    job.status = "completed"
                    job.completed_at = datetime.utcnow()
                    continue
                if self.is_live(job.id):
                    continue
                if (
                    task
                    and task.comfyui_prompt_id
                    and job.handler == "app.services.shot_video_service:generate_shot_video_task"
                ):
                    # Shot-video provenance recovery is owned by TaskService;
                    # replaying here could submit a duplicate physical Clip.
                    continue
                job.status = "queued"
                job.started_at = None
                resumable.append((job.queue_name, job.id))
            db.commit()
        finally:
            db.close()

        for queue_name, job_id in resumable:
            self.worker(queue_name).signal(job_id)
        return len(resumable)

    async def stop(self) -> None:
        await asyncio.gather(
            *(worker.stop() for worker in self._workers.values()),
            return_exceptions=True,
        )

    def reconcile_terminal_jobs(self) -> int:
        """Close durable job rows whose product Task reached a terminal state."""
        from app.models.background_job import BackgroundJob
        from app.models.task import Task

        db = self._session()
        try:
            jobs = db.query(BackgroundJob).join(
                Task, Task.id == BackgroundJob.task_id
            ).filter(
                BackgroundJob.status.in_(["queued", "running"]),
                Task.status.in_(["completed", "failed", "cancelled"]),
            ).all()
            for job in jobs:
                job.status = "completed"
                job.completed_at = datetime.utcnow()
            if jobs:
                db.commit()
            return len(jobs)
        finally:
            db.close()


worker_manager = WorkerManager()


def ensure_task_active(db, task) -> None:
    db.refresh(task, attribute_names=["status"])
    if task.status not in {"pending", "running"}:
        raise asyncio.CancelledError()


def save_image_prompt(db, task, prompt_id, workflow, save_image_node_id, *, reserve_retry=False) -> None:
    """Persist the graph and retry context alongside each image prompt receipt."""
    from app.utils.workflow_seed import extract_workflow_seed
    ensure_task_active(db, task)
    metadata = json.loads(task.metadata_json or "{}")
    attempt = metadata.setdefault("image_attempt", {})
    if task.comfyui_prompt_id and task.comfyui_prompt_id != prompt_id:
        attempt["rewrite_retry_used"] = True
    attempt["save_image_node_id"] = save_image_node_id
    attempt.setdefault("rewrite_retry_used", False)
    if reserve_retry:
        # The synchronous G3 call owns its one retry. Reserve it before its
        # first wait, including a crash after retry submission but before receipt.
        attempt["rewrite_retry_reserved"] = True
    task.metadata_json = json.dumps(metadata, ensure_ascii=False)
    task.comfyui_prompt_id = prompt_id
    task.workflow_json = json.dumps(workflow, ensure_ascii=False, indent=2)
    task.seed = extract_workflow_seed(workflow)
    db.commit()


def saved_image_attempt(task):
    workflow = json.loads(task.workflow_json or "null")
    if not isinstance(workflow, dict) or not workflow:
        raise ValueError("已提交图片任务缺少 workflow 快照，拒绝重新提交")
    metadata = json.loads(task.metadata_json or "{}")
    return workflow, metadata.get("image_attempt", {})


async def resume_image_prompt(db, task, comfyui_service):
    """Resume the latest image receipt without rebuilding its inputs."""
    workflow, attempt = saved_image_attempt(task)
    node_id = attempt.get("save_image_node_id")
    result = await comfyui_service.client.wait_for_result(
        task.comfyui_prompt_id, workflow, node_id, timeout=7200,
    )
    ensure_task_active(db, task)
    message = str((result or {}).get("message") or "").lower()
    malformed = "format validation" in message or "thinking block" in message
    if (
        not (result or {}).get("success") and malformed
        and "rewrite_retry_used" in attempt and not attempt["rewrite_retry_used"]
        and not attempt.get("rewrite_retry_reserved", False)
        and any(isinstance(node, dict) and node.get("class_type") == "QwenPERewriteT8" for node in workflow.values())
    ):
        # Reserve the one retry before submission; a restart cannot renew it.
        metadata = json.loads(task.metadata_json or "{}")
        metadata["image_attempt"]["rewrite_retry_used"] = True
        task.metadata_json = json.dumps(metadata, ensure_ascii=False)
        db.commit()
        result = await comfyui_service.retry_prompt_rewrite_format_failure(
            result, workflow, node_id,
            lambda prompt_id, queued_workflow: save_image_prompt(
                db, task, prompt_id, queued_workflow, node_id,
            ),
        )
    ensure_task_active(db, task)
    return dict(result or {}, prompt_id=task.comfyui_prompt_id, submitted_workflow=workflow)


def resume_legacy_asset_jobs() -> int:
    """Backfill active asset Tasks created before durable jobs were deployed."""
    from app.models.background_job import BackgroundJob
    from app.models.novel import Character, Prop, Scene
    from app.models.task import Task

    db = worker_manager._session()
    recovered: list[tuple[str, dict]] = []
    try:
        tasks = db.query(Task).filter(
            Task.type.in_(["character_portrait", "scene_image", "prop_image"]),
            Task.status.in_(["pending", "running"]),
        ).order_by(Task.created_at.asc(), Task.id.asc()).all()
        for task in tasks:
            has_job = db.query(BackgroundJob.id).filter(
                BackgroundJob.task_id == task.id,
            ).first()
            if has_job:
                continue
            # Asset handlers resume a saved receipt/graph before rebuilding.
            # TaskService's video recovery does not own these asset results.
            if task.type == "character_portrait" and task.character_id:
                entity = db.query(Character).filter(Character.id == task.character_id).first()
                if entity:
                    recovered.append((task.type, {
                        "task_id": task.id,
                        "character_id": entity.id,
                        "name": entity.name,
                        "appearance": entity.appearance,
                        "description": entity.description,
                    }))
                    entity.generating_status = "pending"
            elif task.type == "scene_image" and task.scene_id:
                entity = db.query(Scene).filter(Scene.id == task.scene_id).first()
                if entity:
                    recovered.append((task.type, {
                        "task_id": task.id,
                        "scene_id": entity.id,
                        "name": entity.name,
                        "setting": entity.setting,
                        "description": entity.description,
                    }))
                    entity.generating_status = "pending"
            elif task.type == "prop_image" and task.prop_id:
                entity = db.query(Prop).filter(Prop.id == task.prop_id).first()
                if entity:
                    recovered.append((task.type, {
                        "task_id": task.id,
                        "prop_id": entity.id,
                        "name": entity.name,
                        "appearance": entity.appearance,
                        "description": entity.description,
                    }))
                    entity.generating_status = "pending"
            else:
                continue
            task.status = "pending"
            task.started_at = None
            task.current_step = "服务重启，等待持久化队列恢复..."
        db.commit()
    finally:
        db.close()

    for task_type, payload in recovered:
        if task_type == "character_portrait":
            from app.services.character_service import enqueue_character_portrait_task
            enqueue_character_portrait_task(**payload)
        elif task_type == "scene_image":
            from app.services.scene_service import enqueue_scene_image_task
            enqueue_scene_image_task(**payload)
        elif task_type == "prop_image":
            from app.services.prop_image_service import enqueue_prop_image_task
            enqueue_prop_image_task(**payload)
    return len(recovered)
