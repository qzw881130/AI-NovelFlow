"""One-click, resumable Shot production for grid novels only."""

import asyncio
import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.image_quality_review import ImageQualityReview
from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.task import Task
from app.schemas.grid_shot import load_grid_data, read_grid_clip_plan
from app.services.background_workers import persistent_job, worker_manager
from app.services.grid_pipeline import GridPipeline, GridPipelineError
from app.services.grid_tasks import GRID_TASK_TYPES, enqueue_grid_job, run_grid_job
from app.services.image_quality_review import current_image_reviews, review_image_task


AUTO_HANDLER = "app.services.grid_auto_batch:run_grid_auto_batch"
MAX_PANEL_RETRIES = 1


def _meta(task: Task) -> dict:
    try:
        value = json.loads(task.metadata_json or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def enqueue_grid_auto_batch(db: Session, novel: Novel, chapter: Chapter,
                            shot_ids: list[str], *, merge_chapter: bool = False) -> Task:
    if novel.video_mode != "grid" or chapter.novel_id != novel.id:
        raise GridPipelineError("仅宫格模式小说可使用自动批量生成")
    if not shot_ids or len(shot_ids) != len(set(shot_ids)) or len(shot_ids) > 100:
        raise GridPipelineError("请选择 1 至 100 个不重复的 Shot")
    shots = db.query(Shot).filter(Shot.chapter_id == chapter.id, Shot.id.in_(shot_ids)).all()
    if len(shots) != len(shot_ids):
        raise GridPipelineError("所选 Shot 不属于当前章回")
    active = db.query(Task.id).filter(Task.chapter_id == chapter.id,
                                      Task.status.in_(["pending", "running"]),
                                      Task.type.in_(GRID_TASK_TYPES | {"grid_batch", "grid_auto_batch", "grid_chapter_plan_batch"})).first()
    if active:
        raise GridPipelineError("本章已有宫格生成任务，请等待或取消后再提交")
    parent = Task(type="grid_auto_batch", status="pending", novel_id=novel.id,
                  chapter_id=chapter.id, execution_scope="BATCH",
                  name=f"自动批量生成 Shot · {chapter.title}", progress=0,
                  current_step=f"等待执行 {len(shot_ids)} 个 Shot",
                  metadata_json=json.dumps({"video_mode": "grid", "shot_ids": shot_ids,
                                            "merge_chapter": merge_chapter,
                                            "shot_results": {shot_id: {"status": "pending"} for shot_id in shot_ids},
                                            "panel_retries": {}}, ensure_ascii=False))
    db.add(parent)
    db.flush()
    try:
        worker_manager.worker("grid").enqueue(
            persistent_job(parent.id, AUTO_HANDLER, {"task_id": parent.id},
                           lambda: run_grid_auto_batch(parent.id)), db=db)
    except Exception:
        db.rollback()
        raise
    return parent


def _check_active(db: Session, parent: Task) -> None:
    db.refresh(parent, attribute_names=["status"])
    if parent.status == "cancelled":
        raise asyncio.CancelledError()


def _set_progress(db: Session, parent: Task, shot_id: str, status: str,
                  message: str = "", *, step: str | None = None) -> None:
    metadata = _meta(parent)
    metadata.setdefault("shot_results", {})[shot_id] = {"status": status, "message": message,
                                                          "step": step}
    parent.metadata_json = json.dumps(metadata, ensure_ascii=False)
    finished = sum(item.get("status") in {"completed", "failed", "needs_review"}
                   for item in metadata["shot_results"].values())
    parent.progress = round(finished / len(metadata["shot_ids"]) * 100)
    parent.current_step = message
    db.commit()


async def _run_step(db: Session, parent: Task, novel: Novel, chapter: Chapter,
                    shot: Shot | None, step: str, *, panel_index: int | None = None,
                    clip_index: int | None = None) -> None:
    _check_active(db, parent)
    children = db.query(Task).filter(Task.parent_task_id == parent.id,
                                     Task.shot_id == (shot.id if shot else None),
                                     Task.type.in_(GRID_TASK_TYPES),
                                     Task.status.in_(["pending", "running"])).all()
    existing = next((child for child in children if _meta(child).get("grid_step") == step
                     and _meta(child).get("panel_index") == panel_index
                     and child.clip_index == clip_index), None)
    if existing is None:
        child = enqueue_grid_job(db, novel, chapter, shot, step, panel_index=panel_index,
                                 clip_index=clip_index, parent_task_id=parent.id,
                                 batch_order=db.query(Task).filter(Task.parent_task_id == parent.id).count() + 1,
                                 enqueue=False)
    else:
        child = existing
    await run_grid_job(child.id)
    db.expire_all()
    child = db.get(Task, child.id)
    if child.status != "completed":
        raise GridPipelineError(child.error_message or f"{step} 未完成")


def _review_prompt(shot: Shot, panel, speakers: list[str]) -> str:
    return ("评审这张单独的 16:9 宫格子图，不能按整板或其他格评审。"
            f"Shot 情节：{shot.description}。本格剧情：{panel.beat}。"
            f"机位与焦点：{panel.camera}。动作：{panel.action}。"
            f"本格应出现的人物（每人仅一次）：{'、'.join(panel.characters) or '无人'}。"
            f"本格台词说话人：{'、'.join(speakers) or '无'}。"
            "如果是过肩镜头，说话人应是明确的清晰主体，听话人肩部可以虚化。"
            "检查人物身份和面容、人物数量、说话人的画面焦点、行囊与木杖等有主道具的归属、"
            "动作、场景与轴线连续性。不得把参考图中的其他人物或白底排版带入生成图。")


async def _review_panel(db: Session, parent: Task, shot: Shot, index: int) -> tuple[str, str]:
    _check_active(db, parent)
    grid = load_grid_data(shot.grid_data)
    panel = grid.panels[index - 1]
    lines = json.loads(shot.dialogues or "[]")
    speakers = list(dict.fromkeys(
        str(lines[number - 1].get("speaker") or "") for number in panel.dialogue_indexes
        if 1 <= number <= len(lines) and isinstance(lines[number - 1], dict)
        and lines[number - 1].get("speaker") != "旁白"))
    references = panel.image_reference_images or grid.board_reference_images or []
    references = [ref for ref in references if ref.get("role") != "CHARACTER_IDENTITY"
                  or ref.get("name") in panel.characters or "、" in str(ref.get("name") or "")]
    reviews = db.query(Task).filter(Task.parent_task_id == parent.id,
                                    Task.shot_id == shot.id, Task.type == "grid_panel_review",
                                    Task.result_url == panel.image_url).all()
    review_task = next((item for item in reviews if _meta(item).get("panel_index") == index
                        and _meta(item).get("panel_image_task_id") == panel.image_task_id), None)
    if review_task is None:
        review_task = Task(type="grid_panel_review", status="running", novel_id=parent.novel_id,
                           chapter_id=parent.chapter_id, shot_id=shot.id,
                           parent_task_id=parent.id, name=f"AI 审核子格 · Shot {shot.index} · 格 {index}",
                           progress=20, current_step="正在 AI 初审", result_url=panel.image_url,
                           prompt_text=_review_prompt(shot, panel, speakers),
                           reference_images=json.dumps([
                               {"picture": i, "url": ref["url"], "kind": ref.get("role"),
                                "name": ref.get("name")} for i, ref in enumerate(references, 1)
                           ], ensure_ascii=False),
                           metadata_json=json.dumps({"video_mode": "grid", "grid_step": "panel_review",
                                                     "panel_index": index, "grid_revision": grid.revision,
                                                     "panel_image_task_id": panel.image_task_id,
                                                     "structured_target": {"panel": panel.model_dump(),
                                                                           "speakers": speakers}}, ensure_ascii=False),
                           started_at=datetime.utcnow())
        db.add(review_task)
        db.commit()
    state = current_image_reviews(db, [{"taskId": review_task.id, "imageUrl": panel.image_url}])[0]
    if state["qualityStatus"] in {"PASS", "WARNING", "FAIL"} and state["reviewId"]:
        review = db.get(ImageQualityReview, state["reviewId"])
        review_task.status, review_task.progress = "completed", 100
        review_task.current_step = f"AI 初审 {review.overall}"
        review_task.completed_at = review_task.completed_at or datetime.utcnow()
        db.commit()
        return review.overall, review.summary or ""
    if state["qualityStatus"] == "RUNNING" and state["reviewId"]:
        # The durable parent can replay after a worker restart. Only this parent
        # executes its review, so a stranded running claim is safe to reset.
        record = db.get(ImageQualityReview, state["reviewId"])
        record.status = "pending"
        db.commit()
    if review_task.status != "running":
        review_task.status, review_task.current_step = "running", "正在重试 AI 初审"
        db.commit()
    review = await review_image_task(db, review_task.id, trigger="manual")
    _check_active(db, parent)
    if review.status != "success":
        review_task.status, review_task.error_message = "failed", review.error_message or review.status
        review_task.completed_at = datetime.utcnow()
        db.commit()
        raise GridPipelineError(f"格 {index} AI 初审异常：{review.error_message or review.status}")
    review_task.status, review_task.progress = "completed", 100
    review_task.current_step = f"AI 初审 {review.overall}"
    review_task.completed_at = datetime.utcnow()
    db.commit()
    return review.overall or "ERROR", review.summary or ""


async def _review_panels(db: Session, parent: Task, novel: Novel, chapter: Chapter,
                         shot: Shot) -> None:
    pipeline = GridPipeline(db)
    for index in range(1, len(load_grid_data(shot.grid_data).panels) + 1):
        while True:
            _check_active(db, parent)
            db.refresh(shot)
            panel = load_grid_data(shot.grid_data).panels[index - 1]
            if panel.review_status == "passed":
                break
            key = f"{shot.id}:{index}"
            attempts = _meta(parent).get("panel_retries", {}).get(key, 0)
            if panel.review_status == "pending":
                result, summary = await _review_panel(db, parent, shot, index)
                _check_active(db, parent)
                db.refresh(shot)
                if result == "PASS":
                    pipeline.review_panel(shot, index, "passed", f"AI 初审通过：{summary}")
                    break
                status = "failed" if result == "FAIL" else "warning"
                pipeline.review_panel(shot, index, status, f"AI 初审{result}：{summary}")
            if attempts >= MAX_PANEL_RETRIES:
                raise GridPipelineError(f"格 {index} 未通过 AI 初审；请在逐格页面核对或重做")
            _set_progress(db, parent, shot.id, "running",
                          f"Shot {shot.index} · 格 {index} 初审有疑点，正在单格重做", step="panel_generate")
            pipeline.prepare_panel_retry(novel, shot, index)
            await _run_step(db, parent, novel, chapter, shot, "panel_generate", panel_index=index)
            metadata = _meta(parent)
            metadata.setdefault("panel_retries", {})[key] = attempts + 1
            parent.metadata_json = json.dumps(metadata, ensure_ascii=False)
            db.commit()


async def _run_shot(db: Session, parent: Task, novel: Novel, chapter: Chapter, shot: Shot) -> None:
    def update(step: str, label: str):
        _set_progress(db, parent, shot.id, "running", f"Shot {shot.index} · {label}", step=step)

    if shot.video_url:
        return
    grid = load_grid_data(shot.grid_data)
    if not grid:
        update("panels_plan", "规划子格")
        await _run_step(db, parent, novel, chapter, shot, "panels_plan")
        db.refresh(shot)
        grid = load_grid_data(shot.grid_data)
    if not grid.board_prompt:
        update("board_prepare", "编写整板提示词")
        await _run_step(db, parent, novel, chapter, shot, "board_prepare")
        db.refresh(shot)
        grid = load_grid_data(shot.grid_data)
    if not grid.board_image_url:
        update("board_generate", "生成整板")
        await _run_step(db, parent, novel, chapter, shot, "board_generate")
        db.refresh(shot)
    update("panel_review", "逐格 AI 初审")
    await _review_panels(db, parent, novel, chapter, shot)
    db.refresh(shot)
    grid = load_grid_data(shot.grid_data)
    plan = read_grid_clip_plan(shot.video_director_plan, grid_revision=grid.revision)
    if not plan:
        update("clips_plan", "规划 Clip")
        await _run_step(db, parent, novel, chapter, shot, "clips_plan")
        db.refresh(shot)
        plan = read_grid_clip_plan(shot.video_director_plan, grid_revision=grid.revision)
    for clip in plan["clip_plan"]:
        index = clip["clip_index"]
        if not clip.get("prompt"):
            update("clip_prepare", f"编译 C{index} 六段式提示词")
            await _run_step(db, parent, novel, chapter, shot, "clip_prepare", clip_index=index)
            db.refresh(shot)
            plan = read_grid_clip_plan(shot.video_director_plan, grid_revision=grid.revision)
            clip = plan["clip_plan"][index - 1]
        if not clip.get("video_url"):
            update("clip_generate", f"生成 C{index} H3 视频")
            await _run_step(db, parent, novel, chapter, shot, "clip_generate", clip_index=index)
            db.refresh(shot)
            plan = read_grid_clip_plan(shot.video_director_plan, grid_revision=grid.revision)
    if not shot.video_url:
        update("shot_merge", "合并 Shot")
        await _run_step(db, parent, novel, chapter, shot, "shot_merge")


async def run_grid_auto_batch(task_id: str) -> None:
    db = worker_manager._session()
    try:
        parent = db.get(Task, task_id)
        if not parent or parent.type != "grid_auto_batch" or parent.status not in {"pending", "running"}:
            return
        metadata = _meta(parent)
        novel, chapter = db.get(Novel, parent.novel_id), db.get(Chapter, parent.chapter_id)
        if not novel or not chapter or novel.video_mode != "grid":
            raise GridPipelineError("自动批量任务所属宫格小说或章回不存在")
        parent.status, parent.started_at = "running", parent.started_at or datetime.utcnow()
        db.commit()
        for shot_id in metadata["shot_ids"]:
            _check_active(db, parent)
            if _meta(parent).get("shot_results", {}).get(shot_id, {}).get("status") in {"completed", "failed", "needs_review"}:
                continue
            shot = db.get(Shot, shot_id)
            if not shot or shot.chapter_id != chapter.id:
                _set_progress(db, parent, shot_id, "failed", "Shot 已不存在")
                continue
            try:
                await _run_shot(db, parent, novel, chapter, shot)
                db.refresh(shot)
                if not shot.video_url:
                    raise GridPipelineError("Shot 合并结果缺失")
                _set_progress(db, parent, shot_id, "completed", f"Shot {shot.index} 已完成")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                db.refresh(parent)
                if parent.status == "cancelled":
                    return
                status = "needs_review" if "初审" in str(exc) else "failed"
                _set_progress(db, parent, shot_id, status, f"Shot {shot.index}：{exc}")
        metadata = _meta(parent)
        failures = {key: value for key, value in metadata["shot_results"].items()
                    if value.get("status") != "completed"}
        if metadata.get("merge_chapter") and not failures:
            all_shots = db.query(Shot).filter(Shot.chapter_id == chapter.id).all()
            if all_shots and all(item.video_url for item in all_shots):
                try:
                    parent.current_step = "合并章回视频"
                    db.commit()
                    if not chapter.final_video:
                        await _run_step(db, parent, novel, chapter, None, "chapter_merge")
                except Exception as exc:
                    failures["chapter"] = {"status": "failed", "message": str(exc)}
            else:
                failures["chapter"] = {"status": "failed", "message": "仍有未完成的 Shot，无法合并章回"}
        parent.status = "failed" if failures else "completed"
        parent.error_message = "；".join(item.get("message", "") for item in failures.values()) or None
        completed_shots = sum(value.get("status") == "completed" for value in metadata["shot_results"].values())
        parent.current_step = (f"完成 {completed_shots}/{len(metadata['shot_ids'])} 个 Shot；"
                               "请处理未通过的子格或失败步骤" if failures else "自动批量生成完成")
        parent.progress = 100
        parent.completed_at = datetime.utcnow()
        db.commit()
    except asyncio.CancelledError:
        db.refresh(parent, attribute_names=["status"])
        if parent.status == "cancelled":
            return
        raise
    finally:
        db.close()
