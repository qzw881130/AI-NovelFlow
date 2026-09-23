import asyncio
import copy
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.shot import Shot
from app.models.task import Task
from app.models.workflow import Workflow
from app.services.background_workers import worker_manager
from app.services.comfyui import ComfyUIService
from app.services.file_storage import file_storage
from app.utils.path_utils import local_path_to_url, url_to_local_path
from app.utils.time_utils import format_datetime
from app.utils.workflow_seed import extract_workflow_seed


ALLOWED_HD_MEGAPIXELS = {0.5, 0.8, 1.0, 1.2, 1.5, 1.8, 2.0}
_active_hd_tasks: set[str] = set()
_active_hd_batches: set[str] = set()


def _json_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _json_list(value) -> list:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def hd_task_megapixels(task: Task) -> Optional[float]:
    value = _json_dict(task.metadata_json).get("target_megapixels")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def format_hd_execution(task: Task) -> dict:
    return {
        "id": task.id,
        "status": task.status,
        "videoUrl": task.result_url,
        "targetMegapixels": hd_task_megapixels(task),
        "sourceTaskId": task.source_task_id,
        "parentTaskId": task.parent_task_id,
        "progress": task.progress or 0,
        "currentStep": task.current_step,
        "errorMessage": task.error_message,
        "createdAt": format_datetime(task.created_at),
        "startedAt": format_datetime(task.started_at),
        "completedAt": format_datetime(task.completed_at),
    }


def get_hd_repaint_variants(db: Session, shot_id: str) -> list[dict]:
    tasks = db.query(Task).filter(
        Task.type == "shot_video_hd",
        Task.shot_id == shot_id,
    ).order_by(Task.created_at.desc(), Task.id.desc()).all()
    grouped: dict[float, list[Task]] = {}
    for task in tasks:
        megapixels = hd_task_megapixels(task)
        if megapixels is not None:
            grouped.setdefault(megapixels, []).append(task)

    variants = []
    for megapixels in sorted(grouped):
        executions = grouped[megapixels]
        active = next((task for task in executions if task.status in {"pending", "running"}), None)
        completed = [task for task in executions if task.status == "completed" and task.result_url]
        latest_completed = max(completed, key=lambda task: task.completed_at or task.created_at or datetime.min) if completed else None
        latest = executions[0]
        status_task = active or latest_completed or latest
        variants.append({
            "targetMegapixels": megapixels,
            "status": status_task.status,
            "videoUrl": latest_completed.result_url if latest_completed else None,
            "taskId": status_task.id,
            "latestCompletedTaskId": latest_completed.id if latest_completed else None,
            "sourceTaskId": (latest_completed or status_task).source_task_id,
            "errorMessage": status_task.error_message,
            "executions": [format_hd_execution(task) for task in executions],
        })
    return variants


def get_latest_completed_hd_task(db: Session, shot_id: str, target_megapixels: float) -> Optional[Task]:
    for task in db.query(Task).filter(
        Task.type == "shot_video_hd",
        Task.shot_id == shot_id,
        Task.status == "completed",
        Task.result_url.isnot(None),
    ).order_by(Task.completed_at.desc(), Task.created_at.desc()).all():
        if hd_task_megapixels(task) == float(target_megapixels):
            return task
    return None


def clone_hd_task_for_retry(db: Session, source: Task, parent_task_id: str = None, batch_order: int = None) -> Task:
    metadata = _json_dict(source.metadata_json)
    metadata["retry_of_task_id"] = source.id
    clips = _json_list(source.video_director_clips)
    for clip in clips:
        for key in ["replay_workflow_json", "repaint_prompt_id", "video_url", "local_path", "source_video_url", "generated_at", "seed"]:
            clip.pop(key, None)
        clip["status"] = "PENDING"
    task = Task(
        type="shot_video_hd",
        status="pending",
        name=source.name,
        description=source.description,
        novel_id=source.novel_id,
        chapter_id=source.chapter_id,
        shot_id=source.shot_id,
        source_task_id=source.source_task_id,
        parent_task_id=parent_task_id,
        batch_order=batch_order,
        workflow_id=source.workflow_id,
        workflow_json=json.dumps(metadata.get("source_workflow_json"), ensure_ascii=False) if metadata.get("source_workflow_json") else None,
        prompt_text=source.prompt_text,
        reference_images=source.reference_images,
        video_director_clips=json.dumps(clips, ensure_ascii=False) if clips else None,
        seed=metadata.get("source_seed"),
        metadata_json=json.dumps(metadata, ensure_ascii=False),
        current_step="等待高清 Replay",
    )
    db.add(task)
    db.flush()
    return task


def _workflow_mapping(db: Session, workflow_id: Optional[str] = None, workflow_type: Optional[str] = None, workflow_name: Optional[str] = None) -> tuple[Optional[Workflow], dict]:
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first() if workflow_id else None
    if not workflow and workflow_name:
        workflow = db.query(Workflow).filter(Workflow.name == workflow_name).first()
    if not workflow and workflow_type:
        workflow = db.query(Workflow).filter(Workflow.type == workflow_type, Workflow.is_active == True).first()
    return workflow, _json_dict(workflow.node_mapping) if workflow else {}


def _node_value(workflow: dict, node_id: str):
    return workflow.get(str(node_id), {}).get("inputs", {}).get("value")


def _is_cancelled(db: Session, task: Task) -> bool:
    db.refresh(task)
    return task.status == "cancelled"


def clone_workflow_for_hd(source_workflow: dict, megapixels_node_id: str, target_megapixels: float) -> dict:
    if not source_workflow or not megapixels_node_id:
        raise ValueError("原 Execution 缺少实际 Workflow 或 Megapixels 节点映射")
    node_id = str(megapixels_node_id)
    if node_id not in source_workflow:
        raise ValueError(f"原 Execution Workflow 中不存在 Megapixels 节点 {node_id}")
    replay = copy.deepcopy(source_workflow)
    if not ComfyUIService().builder._set_value(replay, node_id, float(target_megapixels)):
        raise ValueError(f"Megapixels 节点 {node_id} 不支持 value 覆盖")
    expected = copy.deepcopy(source_workflow)
    ComfyUIService().builder._set_value(expected, node_id, float(target_megapixels))
    if replay != expected:
        raise ValueError("高清 Replay 修改了 Megapixels 之外的 Workflow 参数")
    return replay


def resolve_source_video_task(db: Session, shot: Shot, source_task_id: Optional[str] = None) -> Task:
    query = db.query(Task).filter(Task.type == "shot_video", Task.shot_id == shot.id, Task.status == "completed")
    source = query.filter(Task.id == source_task_id).first() if source_task_id else None
    if source_task_id and not source:
        raise ValueError("指定的初稿视频 Execution 不存在、未完成或不属于当前 Shot")
    if not source and shot.video_task_id:
        source = query.filter(Task.id == shot.video_task_id).first()
    if not source and shot.video_url:
        source = query.filter(Task.result_url == shot.video_url).order_by(Task.completed_at.desc(), Task.created_at.desc()).first()
    if not source:
        source = query.order_by(Task.completed_at.desc(), Task.created_at.desc()).first()
    if not source:
        raise ValueError("未找到成功的初稿视频 Execution")
    return source


def build_hd_repaint_snapshot(db: Session, shot: Shot, source: Task, target_megapixels: float) -> tuple[dict, list]:
    target = float(target_megapixels)
    if target not in ALLOWED_HD_MEGAPIXELS:
        raise ValueError("Megapixels 仅支持 0.5、0.8、1.0、1.2、1.5、1.8、2.0")
    source_clips = _json_list(source.video_director_clips)
    replay_clips = []
    if len(source_clips) > 1:
        for position, clip in enumerate(sorted(source_clips, key=lambda item: int(item.get("window_index") or 0)), 1):
            source_workflow = clip.get("workflow_json")
            if not isinstance(source_workflow, dict):
                raise ValueError(f"原 Execution 的 Clip {position} 缺少实际 Workflow 快照")
            workflow, mapping = _workflow_mapping(
                db,
                workflow_id=clip.get("workflow_id"),
                workflow_type=clip.get("workflow_type"),
                workflow_name=clip.get("workflow_name"),
            )
            mp_node = clip.get("megapixels_node_id") or mapping.get("megapixels_node_id")
            save_node = clip.get("video_save_node_id") or mapping.get("video_save_node_id")
            if not mp_node or not save_node:
                raise ValueError(f"原 Execution 的 Clip {position} 缺少冻结的 Megapixels/输出节点映射")
            replay_clips.append({
                "window_index": int(clip.get("window_index") or position),
                "start_time": clip.get("start_time"),
                "end_time": clip.get("end_time"),
                "source_workflow_json": copy.deepcopy(source_workflow),
                "source_seed": clip.get("seed") or extract_workflow_seed(source_workflow),
                "source_prompt_id": clip.get("prompt_id"),
                "workflow_id": clip.get("workflow_id") or (workflow.id if workflow else None),
                "workflow_type": clip.get("workflow_type"),
                "workflow_name": clip.get("workflow_name") or (workflow.name if workflow else None),
                "megapixels_node_id": str(mp_node),
                "video_save_node_id": str(save_node),
                "source_megapixels": _node_value(source_workflow, str(mp_node)),
                "target_megapixels": target,
                "status": "PENDING",
            })
        return {
            "replay_mode": "multi_clip",
            "source_task_id": source.id,
            "source_video_url": source.result_url or shot.video_url,
            "target_megapixels": target,
        }, replay_clips

    source_workflow = _json_dict(source.workflow_json)
    if not source_workflow:
        raise ValueError("原 Execution 缺少实际提交的 Workflow 快照")
    source_metadata = _json_dict(source.metadata_json)
    workflow, mapping = _workflow_mapping(db, workflow_id=source.workflow_id)
    mp_node = source_metadata.get("megapixels_node_id") or mapping.get("megapixels_node_id")
    save_node = source_metadata.get("video_save_node_id") or mapping.get("video_save_node_id")
    if not mp_node or not save_node:
        raise ValueError("原 Execution 缺少冻结的 Megapixels/输出节点映射")
    return {
        "replay_mode": "single",
        "source_task_id": source.id,
        "source_video_url": source.result_url or shot.video_url,
        "source_workflow_json": copy.deepcopy(source_workflow),
        "source_seed": source.seed or extract_workflow_seed(source_workflow),
        "source_megapixels": _node_value(source_workflow, str(mp_node)),
        "target_megapixels": target,
        "megapixels_node_id": str(mp_node),
        "video_save_node_id": str(save_node),
        "workflow_id": source.workflow_id or (workflow.id if workflow else None),
    }, []


async def _queue_or_resume_workflow(db: Session, task: Task, workflow: dict, save_node_id: str, prompt_id: Optional[str] = None, on_prompt_queued=None) -> dict:
    client = ComfyUIService().client
    if not prompt_id:
        queue_result = await client.queue_prompt(workflow)
        if not queue_result.get("success"):
            raise ValueError(queue_result.get("error") or "提交高清 Replay Workflow 失败")
        prompt_id = queue_result.get("prompt_id")
        task.comfyui_prompt_id = prompt_id
        task.workflow_json = json.dumps(workflow, ensure_ascii=False, indent=2)
        if on_prompt_queued:
            on_prompt_queued(prompt_id)
        db.commit()
    result = await client.wait_for_result(prompt_id, workflow, str(save_node_id), timeout=7200)
    if not result or not result.get("success"):
        raise ValueError((result or {}).get("message") or "高清 Replay 生成失败")
    video_url = result.get("video_url") or result.get("image_url")
    if not video_url:
        raise ValueError("高清 Replay 未返回视频")
    return {"video_url": video_url, "prompt_id": prompt_id}


async def run_hd_repaint_task(task_id: str) -> None:
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task or task.status == "cancelled":
            return
        shot = db.query(Shot).filter(Shot.id == task.shot_id).first()
        if not shot:
            raise ValueError("高清重绘关联的 Shot 不存在")
        metadata = _json_dict(task.metadata_json)
        target_mp = float(metadata.get("target_megapixels") or 1.0)
        task.status = "running"
        task.started_at = task.started_at or datetime.utcnow()
        task.completed_at = None
        task.error_message = None
        task.current_step = "Replay 原视频 Execution"
        shot.hd_video_status = "generating"
        shot.hd_video_task_id = task.id
        parent_batch_id = task.parent_task_id
        if parent_batch_id:
            parent_batch = db.query(Task).filter(
                Task.id == parent_batch_id,
                Task.type == "shot_video_hd_batch",
            ).first()
            if parent_batch and parent_batch.status in {"failed", "completed"}:
                parent_batch.status = "running"
                parent_batch.completed_at = None
                parent_batch.error_message = None
                parent_batch.current_step = "高清重绘恢复中"
        db.commit()
        if parent_batch_id:
            enqueue_hd_repaint_batch(parent_batch_id)

        clips = _json_list(task.video_director_clips)
        if metadata.get("replay_mode") == "multi_clip":
            local_paths = []
            for position, clip in enumerate(clips, 1):
                if _is_cancelled(db, task):
                    return
                if clip.get("status") == "SUCCEEDED" and clip.get("local_path") and Path(clip["local_path"]).exists():
                    local_paths.append(clip["local_path"])
                    continue
                source_workflow = clip.get("source_workflow_json")
                replay_workflow = clip.get("replay_workflow_json") or clone_workflow_for_hd(
                    source_workflow,
                    clip.get("megapixels_node_id"),
                    target_mp,
                )
                clip["replay_workflow_json"] = replay_workflow
                clip["status"] = "RUNNING"
                clip["seed"] = extract_workflow_seed(replay_workflow)
                task.video_director_clips = json.dumps(clips, ensure_ascii=False)
                task.current_step = f"高清 Replay Clip {position}/{len(clips)}"
                db.commit()
                def save_clip_prompt_id(prompt_id: str):
                    clip["repaint_prompt_id"] = prompt_id
                    task.video_director_clips = json.dumps(clips, ensure_ascii=False)
                    db.commit()

                result = await _queue_or_resume_workflow(
                    db,
                    task,
                    replay_workflow,
                    clip.get("video_save_node_id"),
                    clip.get("repaint_prompt_id"),
                    save_clip_prompt_id,
                )
                if _is_cancelled(db, task):
                    return
                clip["repaint_prompt_id"] = result["prompt_id"]
                local_path = await file_storage.download_video(
                    result["video_url"],
                    task.novel_id,
                    task.chapter_id,
                    (shot.index * 1000) + position,
                    variant="hd",
                    filename_suffix=task.id[:8],
                )
                if not local_path:
                    raise ValueError(f"高清 Clip {position} 下载失败")
                clip.update({
                    "status": "SUCCEEDED",
                    "video_url": local_path_to_url(local_path),
                    "local_path": local_path,
                    "source_video_url": result["video_url"],
                    "generated_at": datetime.utcnow().isoformat(),
                })
                local_paths.append(local_path)
                task.video_director_clips = json.dumps(clips, ensure_ascii=False)
                task.comfyui_prompt_id = None
                db.commit()

            story_dir = file_storage._get_story_dir(task.novel_id)
            chapter_short = task.chapter_id[:8]
            output_dir = story_dir / f"chapter_{chapter_short}" / "hd-videos" / "merged"
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"shot_{shot.index:03d}_{task.id[:8]}.mp4"
            merge_result = await file_storage.merge_videos(local_paths, str(output_path))
            if not merge_result.get("success"):
                raise ValueError(merge_result.get("message") or "高清 Clip 合并失败")
            final_url = local_path_to_url(str(output_path))
            if not final_url:
                raise ValueError("无法生成高清合并视频访问地址")
        else:
            source_workflow = metadata.get("source_workflow_json")
            replay_workflow = _json_dict(task.workflow_json) if task.comfyui_prompt_id else clone_workflow_for_hd(
                source_workflow,
                metadata.get("megapixels_node_id"),
                target_mp,
            )
            task.seed = extract_workflow_seed(replay_workflow)
            result = await _queue_or_resume_workflow(
                db,
                task,
                replay_workflow,
                metadata.get("video_save_node_id"),
                task.comfyui_prompt_id,
            )
            if _is_cancelled(db, task):
                return
            local_path = await file_storage.download_video(
                result["video_url"],
                task.novel_id,
                task.chapter_id,
                shot.index,
                variant="hd",
                filename_suffix=task.id[:8],
            )
            if not local_path:
                raise ValueError("高清视频下载失败")
            final_url = local_path_to_url(local_path)
            if not final_url:
                raise ValueError("无法生成高清视频访问地址")

        if _is_cancelled(db, task):
            return
        task.status = "completed"
        task.progress = 100
        task.result_url = final_url
        task.current_step = "高清重绘完成"
        task.completed_at = datetime.utcnow()
        task.error_message = None
        task.comfyui_prompt_id = None
        shot.hd_video_url = final_url
        shot.hd_video_status = "completed"
        shot.hd_video_task_id = task.id
        shot.hd_video_source_task_id = task.source_task_id
        shot.hd_video_megapixels = target_mp
        db.commit()
    except Exception as exc:
        task = db.query(Task).filter(Task.id == task_id).first()
        if task:
            task.status = "failed"
            task.error_message = str(exc)
            task.current_step = "高清重绘失败"
            task.completed_at = datetime.utcnow()
            shot = db.query(Shot).filter(Shot.id == task.shot_id).first()
            if shot:
                shot.hd_video_status = "failed"
            db.commit()
    finally:
        _active_hd_tasks.discard(task_id)
        db.close()


def enqueue_hd_repaint_task(task_id: str) -> None:
    if task_id in _active_hd_tasks:
        return
    _active_hd_tasks.add(task_id)
    worker_manager.worker("shot_video_hd").enqueue(lambda: run_hd_repaint_task(task_id))


async def run_hd_repaint_batch_task(batch_id: str) -> None:
    db = SessionLocal()
    try:
        batch = db.query(Task).filter(Task.id == batch_id).first()
        if not batch or batch.status == "cancelled":
            return
        batch.status = "running"
        batch.started_at = batch.started_at or datetime.utcnow()
        db.commit()
        children = db.query(Task).filter(
            Task.parent_task_id == batch_id,
            Task.type == "shot_video_hd",
        ).order_by(Task.batch_order.asc()).all()
        while True:
            db.expire_all()
            batch = db.query(Task).filter(Task.id == batch_id).first()
            children = db.query(Task).filter(Task.parent_task_id == batch_id, Task.type == "shot_video_hd").all()
            terminal = [child for child in children if child.status in {"completed", "failed", "cancelled"}]
            completed = len([child for child in children if child.status == "completed"])
            failed = len([child for child in children if child.status == "failed"])
            if not batch:
                return
            batch.progress = int(len(terminal) / len(children) * 100) if children else 100
            batch.current_step = f"高清重绘 {len(terminal)}/{len(children)}；成功 {completed}，失败 {failed}"
            db.commit()
            if not batch or batch.status == "cancelled" or len(terminal) == len(children):
                break
            await asyncio.sleep(3)
        if batch and batch.status != "cancelled":
            batch.status = "completed" if failed == 0 else "failed"
            batch.completed_at = datetime.utcnow()
            batch.error_message = None if failed == 0 else batch.current_step
            db.commit()
    finally:
        _active_hd_batches.discard(batch_id)
        db.close()


def enqueue_hd_repaint_batch(batch_id: str) -> None:
    if batch_id in _active_hd_batches:
        return
    _active_hd_batches.add(batch_id)
    worker_manager.worker("shot_video_hd_batch").enqueue(lambda: run_hd_repaint_batch_task(batch_id))


def resume_active_hd_repaints() -> None:
    db = SessionLocal()
    try:
        db.query(Task).filter(
            Task.type == "shot_video_hd",
            Task.status == "completed",
            Task.error_message.isnot(None),
        ).update({Task.error_message: None}, synchronize_session=False)
        db.commit()
        children = db.query(Task).filter(Task.type == "shot_video_hd", Task.status.in_(["pending", "running"])).order_by(Task.created_at.asc()).all()
        for task in children:
            enqueue_hd_repaint_task(task.id)
        batches = db.query(Task).filter(Task.type == "shot_video_hd_batch", Task.status.in_(["pending", "running"])).order_by(Task.created_at.asc()).all()
        for batch in batches:
            enqueue_hd_repaint_batch(batch.id)
    finally:
        db.close()
