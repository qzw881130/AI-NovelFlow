"""Durable, serial jobs for the grid production path."""

import asyncio
import hashlib
import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.task import Task
from app.schemas.grid_shot import load_grid_data, read_grid_clip_plan
from app.services.background_workers import persistent_job, worker_manager
from app.services.grid_pipeline import GridPipeline, GridPipelineError


GRID_STEPS = {
    "chapter_plan": ("grid_chapter_plan", "规划叙事 Shot"),
    "panels_plan": ("grid_panels_plan", "规划宫格子图"),
    "board_prepare": ("grid_board_prepare", "编写整板提示词"),
    "board_generate": ("grid_board_image", "生成宫格整板"),
    "panel_generate": ("grid_panel_image", "重做宫格子图"),
    "clips_plan": ("grid_clips_plan", "分配 Clip"),
    "clip_prepare": ("grid_clip_prepare", "编译 H3 提示词"),
    "clip_generate": ("grid_h3_clip", "生成 H3 Clip"),
    "shot_merge": ("grid_shot_merge", "合并 Shot"),
    "chapter_merge": ("grid_chapter_merge", "合并章回"),
}
GRID_TASK_TYPES = {item[0] for item in GRID_STEPS.values()}
HANDLER = "app.services.grid_tasks:run_grid_job"


def _plan(shot: Shot | None):
    data = load_grid_data(shot.grid_data) if shot else None
    return data, read_grid_clip_plan(shot.video_director_plan, grid_revision=data.revision) if data else None


def _fingerprint(chapter: Chapter, shot: Shot | None, step: str, *, panel_index=None,
                 clip_index=None, layout=None, strategy=None) -> str:
    data, plan = _plan(shot)
    common = {"step": step, "chapter_id": chapter.id, "shot_id": shot.id if shot else None,
              "revision": data.revision if data else None}
    if step == "chapter_plan":
        value = {**common, "text": chapter.content}
    elif step == "panels_plan":
        value = {**common, "layout": layout, "description": shot.description,
                 "dialogues": shot.dialogues, "duration": shot.duration}
    elif step in {"board_prepare", "board_generate"}:
        value = {**common, "layout": data.layout if data else None,
                 "panels": [(p.index, p.beat, p.camera, p.action) for p in data.panels] if data else None,
                 "prompt": data.board_prompt if step == "board_generate" and data else None,
                 "references": data.board_reference_images if step == "board_generate" and data else None}
    elif step == "panel_generate":
        panel = data.panels[panel_index - 1] if data and panel_index and 1 <= panel_index <= len(data.panels) else None
        value = {**common, "index": panel_index, "prompt": panel.image_prompt if panel else None,
                 "references": panel.image_reference_images if panel else None}
    elif step == "clips_plan":
        value = {**common, "duration": shot.duration,
                 "panels": [(p.index, p.image_url, p.review_status) for p in data.panels] if data else None,
                 "dialogues": shot.dialogues}
    elif step in {"clip_prepare", "clip_generate"}:
        clip = plan["clip_plan"][clip_index - 1] if plan and clip_index and 1 <= clip_index <= len(plan["clip_plan"]) else None
        value = {**common, "index": clip_index, "strategy": strategy if step == "clip_prepare" else None,
                 "panels": [(p.index, p.image_url) for p in data.panels] if data else None,
                 "clip": {key: item for key, item in clip.items() if key not in
                          {"video_url", "video_task_id", "validation"} and (step != "clip_prepare" or key not in
                          {"prompt", "prompt_template_snapshot", "reference_images"})} if clip else None}
    elif step == "shot_merge":
        value = {**common, "clip_videos": [c.get("video_url") for c in plan["clip_plan"]] if plan else None}
    else:
        value = {**common, "shot_videos": [(s.id, s.video_url) for s in
                 sorted(chapter.shots, key=lambda item: item.index)]}
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _validate(db: Session, novel: Novel, chapter: Chapter, shot: Shot | None, step: str,
              *, panel_index=None, clip_index=None) -> None:
    if not novel or not chapter or novel.video_mode != "grid" or chapter.novel_id != novel.id or (shot and shot.chapter_id != chapter.id):
        raise GridPipelineError("宫格任务的小说、章回或 Shot 不匹配")
    if step == "chapter_plan":
        if db.query(Shot.id).filter(Shot.chapter_id == chapter.id).first():
            raise GridPipelineError("本章已有叙事 Shot")
        return
    if step == "chapter_merge":
        shots = db.query(Shot).filter(Shot.chapter_id == chapter.id).all()
        if not shots or any(not item.video_url for item in shots):
            raise GridPipelineError("请先完成所有 Shot 合片")
        return
    if not shot:
        raise GridPipelineError("缺少 Shot")
    data, plan = _plan(shot)
    if step == "panels_plan":
        return
    if not data:
        raise GridPipelineError("请先规划宫格子图")
    if step == "board_generate" and not data.board_prompt:
        raise GridPipelineError("请先预览整板提示词")
    if step == "panel_generate" and (not panel_index or not 1 <= panel_index <= len(data.panels)
                                     or not data.panels[panel_index - 1].image_prompt):
        raise GridPipelineError("请先预览此格重做输入")
    if step == "clips_plan" and any(not p.image_url or p.review_status == "failed" for p in data.panels):
        raise GridPipelineError("请先生成全部子格并处理初审 FAIL 的子格")
    if step == "clips_plan" and plan and any(item.get("video_url") for item in plan["clip_plan"]):
        raise GridPipelineError("已有生成的 Clip；请逐条重做，不可直接重新规划")
    if step in {"clip_prepare", "clip_generate", "shot_merge"}:
        if not plan:
            raise GridPipelineError("请先规划 Clip")
        if step != "shot_merge" and (not clip_index or not 1 <= clip_index <= len(plan["clip_plan"])):
            raise GridPipelineError("Clip 编号无效")
        if step == "clip_generate" and not plan["clip_plan"][clip_index - 1].get("prompt"):
            raise GridPipelineError("请先编译并预览 H3 提示词")
        if step == "shot_merge" and any(not item.get("video_url") for item in plan["clip_plan"]):
            raise GridPipelineError("请先生成所有 Clip")


def active_grid_shot_ids(db: Session, chapter_id: str) -> set[str]:
    """Shot reservations held by queued or running grid jobs and auto batches."""
    active = db.query(Task).filter(Task.chapter_id == chapter_id,
                                   Task.status.in_(["pending", "running"]),
                                   Task.type.in_(GRID_TASK_TYPES | {"grid_auto_batch", "grid_board_batch", "grid_review_batch"})).all()
    reserved = {task.shot_id for task in active if task.shot_id}
    for task in active:
        if task.type in {"grid_auto_batch", "grid_board_batch", "grid_review_batch"}:
            try:
                metadata = json.loads(task.metadata_json or "{}")
                results = metadata.get("shot_results") or {}
                reserved.update(shot_id for shot_id in metadata.get("shot_ids", [])
                                if results.get(shot_id, {}).get("status") not in
                                {"completed", "failed", "needs_review"})
            except (TypeError, ValueError):
                pass
    return reserved


def enqueue_grid_job(db: Session, novel: Novel, chapter: Chapter, shot: Shot | None, step: str,
                     *, panel_index: int | None = None, clip_index: int | None = None,
                     layout: str | None = None, strategy: str | None = None,
                     source_task_id: str | None = None, parent_task_id: str | None = None,
                     batch_order: int | None = None, enqueue: bool = True) -> Task:
    if step not in GRID_STEPS:
        raise GridPipelineError("未知的宫格任务步骤")
    if parent_task_id is None and shot and shot.id in active_grid_shot_ids(db, chapter.id):
        raise GridPipelineError("此 Shot 已有宫格任务在排队或执行")
    _validate(db, novel, chapter, shot, step, panel_index=panel_index, clip_index=clip_index)
    active = db.query(Task).filter(Task.chapter_id == chapter.id, Task.type.in_(GRID_TASK_TYPES),
                                   Task.status.in_(["pending", "running"])).all()
    if any(item.shot_id == (shot.id if shot else None) and item.clip_index == clip_index and
           json.loads(item.metadata_json or "{}").get("grid_step") == step for item in active):
        raise GridPipelineError("此步骤已有待执行或进行中的任务")
    fingerprint = _fingerprint(chapter, shot, step, panel_index=panel_index, clip_index=clip_index,
                               layout=layout, strategy=strategy)
    task_type, label = GRID_STEPS[step]
    name = f"{label} · {chapter.title}" + (f" · Shot {shot.index}" if shot else "")
    if panel_index:
        name += f" · 格 {panel_index}"
    if clip_index:
        name += f" · C{clip_index}"
    metadata = {"video_mode": "grid", "grid_step": step, "grid_revision":
                load_grid_data(shot.grid_data).revision if shot and shot.grid_data else None,
                "grid_input_fingerprint": fingerprint, "layout": layout, "strategy": strategy,
                "panel_index": panel_index}
    task = Task(type=task_type, status="pending", novel_id=novel.id, chapter_id=chapter.id,
                shot_id=shot.id if shot else None, clip_index=clip_index,
                parent_task_id=parent_task_id, batch_order=batch_order, source_task_id=source_task_id,
                name=name, progress=0, current_step="等待宫格任务队列", metadata_json=json.dumps(metadata, ensure_ascii=False))
    db.add(task)
    db.flush()
    try:
        if enqueue:
            worker_manager.worker("grid").enqueue(persistent_job(task.id, HANDLER, {"task_id": task.id},
                                                          lambda: run_grid_job(task.id)), db=db)
        else:
            # The durable auto-batch job owns the serial worker. Its children run
            # inline so waiting for a second job on the same queue cannot deadlock.
            db.commit()
    except Exception:
        db.rollback()
        raise
    return task


def _refresh_batch(db: Session, batch_id: str | None) -> None:
    if not batch_id:
        return
    batch = db.get(Task, batch_id)
    if not batch or batch.type != "grid_batch" or batch.status == "cancelled":
        return
    children = db.query(Task).filter(Task.parent_task_id == batch_id).order_by(Task.batch_order).all()
    if not children:
        return
    failures = [child for child in children if child.status in {"failed", "cancelled"}]
    if failures:
        first = failures[0]
        for child in children:
            if child.status == "pending" and (child.batch_order or 0) > (first.batch_order or 0):
                child.status, child.current_step = "cancelled", "前一步失败，未执行"
                child.error_message = f"批量任务停在第 {first.batch_order} 项"
                child.completed_at = datetime.utcnow()
        batch.status, batch.current_step = "failed", f"停在第 {first.batch_order} 项：{first.name}"
        batch.error_message = first.error_message or batch.current_step
        batch.completed_at = datetime.utcnow()
    elif len(children) >= (json.loads(batch.metadata_json or "{}").get("expected_count") or len(children)) and all(child.status == "completed" for child in children):
        batch.status, batch.current_step = "completed", "批量生成完成"
        batch.completed_at = datetime.utcnow()
    else:
        batch.status, batch.current_step = "running", "按顺序执行宫格任务"
    batch.progress = round(sum(child.status == "completed" for child in children) / len(children) * 100)
    db.commit()


def _refresh_parent(db: Session, batch_id: str | None) -> None:
    if not batch_id:
        return
    batch = db.get(Task, batch_id)
    if batch and batch.type == "grid_chapter_plan_batch":
        from app.services.chapter_ai_split_service import refresh_split_batch
        refresh_split_batch(db, batch_id)
    else:
        _refresh_batch(db, batch_id)


async def run_grid_job(task_id: str) -> None:
    db = worker_manager._session()
    task = None
    try:
        task = db.get(Task, task_id)
        if not task or task.status not in {"pending", "running"}:
            return
        metadata = json.loads(task.metadata_json or "{}")
        step = metadata.get("grid_step")
        if step not in GRID_STEPS or task.type != GRID_STEPS[step][0]:
            raise GridPipelineError("任务步骤与类型不匹配")
        novel = db.get(Novel, task.novel_id)
        chapter = db.get(Chapter, task.chapter_id)
        shot = db.get(Shot, task.shot_id) if task.shot_id else None
        if not novel or not chapter:
            raise GridPipelineError("任务所属小说或章回不存在")
        if task.parent_task_id:
            batch = db.get(Task, task.parent_task_id)
            ordered_batch = batch and batch.type == "grid_batch"
            earlier = db.query(Task).filter(Task.parent_task_id == task.parent_task_id,
                                            Task.batch_order < task.batch_order).all() if ordered_batch else []
            if not batch or batch.status == "cancelled" or (ordered_batch and
                    (batch.status == "failed" or any(item.status != "completed" for item in earlier))):
                task.status, task.current_step = "cancelled", "前一步未完成，未执行"
                task.completed_at = datetime.utcnow()
                db.commit()
                _refresh_parent(db, task.parent_task_id)
                return
        _validate(db, novel, chapter, shot, step, panel_index=metadata.get("panel_index"),
                  clip_index=task.clip_index)
        actual = _fingerprint(chapter, shot, step, panel_index=metadata.get("panel_index"),
                              clip_index=task.clip_index, layout=metadata.get("layout"),
                              strategy=metadata.get("strategy"))
        if actual != metadata.get("grid_input_fingerprint"):
            raise GridPipelineError("宫格输入已变化，请从当前步骤重新提交")
        task.status, task.current_step = "running", GRID_STEPS[step][1]
        task.started_at = task.started_at or datetime.utcnow()
        task.progress = max(task.progress or 0, 5)
        db.commit()
        pipeline = GridPipeline(db)
        if step == "chapter_plan":
            await pipeline.plan_chapter(novel, chapter, task=task)
        elif step == "panels_plan":
            await pipeline.plan_panels(novel, chapter, shot, metadata.get("layout"), task=task)
        elif step == "board_prepare":
            await pipeline.prepare_board(novel, chapter, shot, task=task)
        elif step == "board_generate":
            await pipeline.generate_board(novel, chapter, shot, task=task)
        elif step == "panel_generate":
            await pipeline.generate_panel_retry(novel, chapter, shot, metadata["panel_index"], task=task)
        elif step == "clips_plan":
            await pipeline.plan_clips(novel, chapter, shot, task=task)
        elif step == "clip_prepare":
            await pipeline.prepare_clip(novel, chapter, shot, task.clip_index,
                                        metadata.get("strategy"), task=task)
        elif step == "clip_generate":
            await pipeline.generate_clip(novel, chapter, shot, task.clip_index, task=task)
        elif step == "shot_merge":
            await pipeline.merge_shot(novel, chapter, shot, task=task)
        elif step == "chapter_merge":
            await pipeline.merge_chapter(novel, chapter, task=task)
        _refresh_parent(db, task.parent_task_id)
    except asyncio.CancelledError:
        # A user-cancelled product Task must not cancel the serial worker itself.
        # Process shutdown still propagates so its durable job can be replayed.
        if task:
            db.refresh(task, attribute_names=["status"])
            if task.status == "cancelled":
                _refresh_parent(db, task.parent_task_id)
                return
        raise
    except Exception as exc:
        if task:
            db.refresh(task, attribute_names=["status"])
            if task.status != "cancelled":
                task.status, task.error_message, task.current_step = "failed", str(exc), "执行失败"
                task.completed_at = datetime.utcnow()
                db.commit()
                _refresh_parent(db, task.parent_task_id)
        raise
    finally:
        db.close()


def reconcile_grid_batches() -> int:
    """Close batch parents after a restart between child writeback and refresh."""
    db = worker_manager._session()
    try:
        batches = db.query(Task.id).filter(Task.type.in_(["grid_batch", "grid_chapter_plan_batch"]),
                                           Task.status.in_(["pending", "running"])).all()
        for (batch_id,) in batches:
            _refresh_parent(db, batch_id)
        return len(batches)
    finally:
        db.close()


def enqueue_grid_retry(db: Session, source: Task) -> dict:
    metadata = json.loads(source.metadata_json or "{}")
    step = metadata.get("grid_step")
    if step not in GRID_STEPS:
        return {"success": False, "status_code": 400, "message": "不是可续做的宫格步骤"}
    novel = db.get(Novel, source.novel_id)
    chapter = db.get(Chapter, source.chapter_id)
    shot = db.get(Shot, source.shot_id) if source.shot_id else None
    if not novel or not chapter:
        return {"success": False, "status_code": 404, "message": "任务所属小说或章回不存在"}
    try:
        task = enqueue_grid_job(db, novel, chapter, shot, step,
                                panel_index=metadata.get("panel_index"), clip_index=source.clip_index,
                                layout=metadata.get("layout"), strategy=metadata.get("strategy"),
                                source_task_id=source.id)
    except (GridPipelineError, ValueError) as exc:
        return {"success": False, "status_code": 409, "message": str(exc)}
    return {"success": True, "message": "已从此步骤重新排队",
            "data": {"taskId": task.id, "retryOfTaskId": source.id, "status": task.status}}
