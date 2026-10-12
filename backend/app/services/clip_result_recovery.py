"""Recover submitted canonical Clips from their exact ComfyUI receipt, without generation."""
import json
from datetime import datetime

from app.models.task import Task
from app.models.workflow import Workflow
from app.repositories.shot_repository import ShotRepository
from app.services.canonical_execution_invalidation import (
    CanonicalExecutionConflict, canonical_clip_dependency_closure,
    ensure_no_active_canonical_clip_tasks,
)
from app.services.continuous_clip_av import CONTINUOUS_CAPABILITIES, NATIVE_CONTINUITY_OUTPUT
from app.services.video_director_ai import safe_json_dict


INTERRUPTED_CLIP_ERROR = "服务重启中断 Clip 回写；已保留 ComfyUI prompt，未重新生成"
_recovering_task_ids: set[str] = set()


async def recover_completed_clip(task, history: dict, db, comfyui_service, *, validate_media=None,
                                 download_video_func=None) -> bool:
    """Use the original submitted graph and the normal Clip persistence path only."""
    from app.services.shot_video_service import _save_generated_video, resolve_extend_previous_av

    if task.id in _recovering_task_ids:
        return True
    metadata = safe_json_dict(task.metadata_json)
    contract = metadata.get("execution_contract") or {}
    capability = contract.get("capability")
    if (task.type != "shot_video" or metadata.get("execution_scope") != "CLIP"
            or capability not in {"GENERATE", "EXTEND", "TEMPORAL_EXTEND"}
            or not task.comfyui_prompt_id or not history):
        return False
    receipt = history.get("prompt") or []
    if not isinstance(receipt, list) or len(receipt) < 3 or receipt[1] != task.comfyui_prompt_id:
        raise CanonicalExecutionConflict("CLIP_RECOVERY_RECEIPT_MISMATCH")
    submitted = safe_json_dict(task.workflow_json)
    if not submitted or submitted != receipt[2]:
        raise CanonicalExecutionConflict("CLIP_RECOVERY_WORKFLOW_MISMATCH")
    native = capability in CONTINUOUS_CAPABILITIES
    if contract.get("artifact_kind") != (NATIVE_CONTINUITY_OUTPUT if native else "CLIP_ONLY"):
        return False
    output_node = "65" if native else str(metadata.get("video_save_node_id") or "")
    if not output_node or output_node not in submitted:
        return False
    if native and submitted[output_node].get("class_type") != "MiniMaxH3StreamLiveExtensionAVToVHS":
        return False
    result = comfyui_service.client._parse_outputs(
        history.get("outputs") or {}, submitted, output_node, strict_output_node=True,
    )
    if not result or not result.get("success") or not result.get("video_url"):
        return False
    result["comfyui_history"] = history
    if native:
        result.update(physical_output_role=NATIVE_CONTINUITY_OUTPUT, output_node_id="65")
    prompt_id = task.comfyui_prompt_id
    shot_repo = ShotRepository(db)
    shot = shot_repo.get_by_id(task.shot_id)
    if not shot or shot.chapter_id != task.chapter_id:
        raise CanonicalExecutionConflict("CLIP_RECOVERY_SHOT_MISMATCH")

    def validate_result():
        # The shared saver may have just added validated native AV metadata.
        db.flush()
        db.refresh(task)
        db.refresh(shot)
        if task.comfyui_prompt_id != prompt_id:
            raise CanonicalExecutionConflict("CLIP_RECOVERY_EXECUTION_CHANGED:PROMPT_ID")
        if safe_json_dict(task.metadata_json).get("execution_contract") != contract:
            raise CanonicalExecutionConflict("CLIP_RECOVERY_EXECUTION_CHANGED:CONTRACT")
        if not (task.status in {"pending", "running"}
                or task.status == "failed" and task.error_message == INTERRUPTED_CLIP_ERROR):
            raise CanonicalExecutionConflict(f"CLIP_RECOVERY_EXECUTION_CHANGED:STATUS:{task.status}:{task.error_message}")
        plan = safe_json_dict(shot.video_director_plan)
        index = int(metadata.get("clip_index") or 0)
        revision = int(metadata.get("clip_plan_revision") or 0)
        clip = next((c for c in plan.get("clip_plan") or [] if c.get("clip_index") == index), None)
        identity = contract.get("clip") or {}
        if (not clip or int(plan.get("clip_plan_revision") or 0) != revision
                or identity.get("clip_index") != index or identity.get("clip_plan_revision") != revision
                or clip.get("capability") != capability
                or clip.get("generated_by_task_id") not in {None, "", task.id}):
            raise CanonicalExecutionConflict("CLIP_RECOVERY_PLAN_CHANGED")
        # A newer attempt, including a finished one, supersedes this receipt.
        for other in db.query(Task).filter(
            Task.shot_id == task.shot_id, Task.type == "shot_video", Task.id != task.id,
        ).all():
            other_meta = safe_json_dict(other.metadata_json)
            if (other_meta.get("execution_scope") == "CLIP"
                    and other_meta.get("clip_index") == index
                    and other_meta.get("clip_plan_revision") == revision
                    and other.created_at and task.created_at and other.created_at >= task.created_at):
                raise CanonicalExecutionConflict("CLIP_RECOVERY_SUPERSEDED")
        affected = canonical_clip_dependency_closure(plan, {index})
        ensure_no_active_canonical_clip_tasks(db, shot.id, plan, affected, exclude_task_ids={task.id})
        if native:
            resolve_extend_previous_av(db, task.novel_id, task.chapter_id, shot, clip, contract.get("previous_clip"))

    _recovering_task_ids.add(task.id)
    try:
        validate_result()
        task.status = "running"
        task.error_message = None
        task.completed_at = None
        task.current_step = "正在恢复已生成的 Clip..."
        db.commit()
        await _save_generated_video(
            result, task, task.novel_id, task.chapter_id, int(shot.index), db, task.id, shot_repo,
            clip_metadata=metadata, update_shot_result=False,
            artifact_suffix=f"clip_{metadata['clip_index']}_{task.id[:8]}",
            validate_result=validate_result, validate_media=validate_media,
            download_video_func=download_video_func,
        )
        if task.status == "completed":
            task.error_message = None
            task.current_step = "已恢复生成结果"
            db.commit()
        return task.status in {"completed", "failed", "cancelled"}
    finally:
        _recovering_task_ids.discard(task.id)


async def accept_cancelled_generate_receipt(source_task, expected_prompt_id: str,
                                            clip_plan_revision: int, db, comfyui_service) -> Task:
    """Accept an already completed C1 receipt as a new Task; keep cancellation intact."""
    from app.services.continuous_clip_av import probe_clip_av
    from app.services.file_storage import file_storage
    from app.services.h3_execution_optimizer import effective_execution_duration, workflow_duration_limits
    from app.services.shot_video_service import _clear_shot_video_error

    source_metadata = safe_json_dict(source_task.metadata_json)
    contract = source_metadata.get("execution_contract") or {}
    identity = contract.get("clip") or {}
    if (source_task.type != "shot_video" or source_task.status != "cancelled"
            or source_task.result_url or source_metadata.get("execution_scope") != "CLIP"
            or contract.get("capability") != "GENERATE" or contract.get("artifact_kind") != "CLIP_ONLY"
            or source_metadata.get("clip_index") != 1 or source_metadata.get("clip_plan_revision") != clip_plan_revision
            or identity.get("clip_index") != 1 or identity.get("clip_plan_revision") != clip_plan_revision
            or source_task.comfyui_prompt_id != expected_prompt_id):
        raise CanonicalExecutionConflict("CLIP_RECEIPT_ACCEPTANCE_SOURCE_MISMATCH")

    existing = db.query(Task).filter(Task.source_task_id == source_task.id, Task.type == "shot_video").all()
    if existing:
        completed = next((task for task in existing if task.status == "completed"), None)
        if completed:
            return completed
        if any(task.status != "failed" for task in existing):
            raise CanonicalExecutionConflict("CLIP_RECEIPT_ACCEPTANCE_ALREADY_STARTED")

    shot_repo = ShotRepository(db)
    shot = shot_repo.get_by_id(source_task.shot_id)
    plan = safe_json_dict(shot.video_director_plan) if shot else {}
    clip = next((item for item in plan.get("clip_plan") or [] if item.get("clip_index") == 1), None)
    if (not shot or shot.chapter_id != source_task.chapter_id
            or int(plan.get("clip_plan_revision") or 0) != clip_plan_revision
            or not clip or clip.get("capability") != "GENERATE"
            or clip.get("generated_by_task_id") or clip.get("video_url")):
        raise CanonicalExecutionConflict("CLIP_RECEIPT_ACCEPTANCE_PLAN_CHANGED")
    for other in db.query(Task).filter(Task.shot_id == shot.id, Task.type == "shot_video", Task.id != source_task.id).all():
        meta = safe_json_dict(other.metadata_json)
        if (meta.get("execution_scope") == "CLIP" and meta.get("clip_index") == 1
                and meta.get("clip_plan_revision") == clip_plan_revision
                and other.created_at and source_task.created_at and other.created_at >= source_task.created_at
                and not (other.source_task_id == source_task.id and other.status == "failed")):
            raise CanonicalExecutionConflict("CLIP_RECEIPT_ACCEPTANCE_SUPERSEDED")
    affected = canonical_clip_dependency_closure(plan, {1})
    ensure_no_active_canonical_clip_tasks(db, shot.id, plan, affected)

    submitted = safe_json_dict(source_task.workflow_json)
    optimizer = source_metadata.get("h3_prompt_optimizer") or {}
    workflow = db.get(Workflow, source_task.workflow_id) if source_task.workflow_id else None
    if (not submitted or not workflow or optimizer.get("status") != "OPTIMIZED"
            or (optimizer.get("authority_check") or {}).get("passed") is not True
            or not source_task.prompt_text or optimizer.get("optimized_prompt") != source_task.prompt_text
            or not any((node.get("inputs") or {}).get("value") == source_task.prompt_text
                       for node in submitted.values() if isinstance(node, dict))):
        raise CanonicalExecutionConflict("CLIP_RECEIPT_ACCEPTANCE_PROMPT_UNVERIFIED")
    planned = float(clip["planned_duration"])
    if float(source_metadata.get("planned_duration") or 0) != planned:
        raise CanonicalExecutionConflict("CLIP_RECEIPT_ACCEPTANCE_PLAN_CHANGED")
    limits = workflow_duration_limits(safe_json_dict(workflow.extension), "GENERATE")
    durations = effective_execution_duration(planned, optimizer, limits)
    node_mapping = safe_json_dict(workflow.node_mapping)
    duration_node = submitted.get(str(node_mapping.get("duration_seconds_node_id"))) or {}
    actual_submission = (duration_node.get("inputs") or {}).get("value")
    if not isinstance(actual_submission, (int, float)) or abs(actual_submission - durations["effective_duration"]) > 1e-6:
        raise CanonicalExecutionConflict("CLIP_RECEIPT_ACCEPTANCE_DURATION_BINDING_MISMATCH")

    prompt_state = await comfyui_service.client.get_prompt_state(expected_prompt_id)
    receipt_source = "COMFYUI_LIVE_HISTORY"
    if prompt_state.get("state") == "completed":
        history = prompt_state.get("history") or {}
    elif prompt_state.get("state") == "missing":
        # ComfyUI keeps output files across restarts but may discard its in-memory
        # history. A prior acceptance attempt persisted the verified receipt before
        # its download failed; reuse only that exact business Task's receipt.
        history = next((safe_json_dict(task.metadata_json).get("comfyui_history")
                        for task in sorted(existing, key=lambda item: item.created_at or datetime.min, reverse=True)
                        if task.status == "failed" and task.error_message == "下载视频失败"
                        and safe_json_dict(task.metadata_json).get("manual_receipt_recovery")
                        and task.comfyui_prompt_id == expected_prompt_id
                        and task.workflow_json == source_task.workflow_json
                        and safe_json_dict(task.metadata_json).get("comfyui_history")), None)
        if not history:
            raise CanonicalExecutionConflict("CLIP_RECEIPT_ACCEPTANCE_NOT_COMPLETED")
        receipt_source = "PRIOR_VALIDATED_BUSINESS_TASK"
    else:
        raise CanonicalExecutionConflict("CLIP_RECEIPT_ACCEPTANCE_NOT_COMPLETED")
    receipt = history.get("prompt") or []
    if (history.get("status", {}).get("status_str") != "success" or len(receipt) < 3
            or receipt[1] != expected_prompt_id or receipt[2] != submitted):
        raise CanonicalExecutionConflict("CLIP_RECEIPT_ACCEPTANCE_RECEIPT_MISMATCH")

    metadata = dict(source_metadata)
    metadata.update({
        **durations, "planned_duration": planned,
        "duration_delta": durations["effective_duration"] - planned,
        "approval_status": "GENERATING", "manual_receipt_recovery": True,
        "recovered_from_task_id": source_task.id,
        "receipt_source": receipt_source,
        "human_acceptance": {"accepted": True, "accepted_at": datetime.utcnow().isoformat(),
                             "scope": "C1_VIDEO_QUALITY_AND_15_SECOND_EXECUTION"},
    })
    task = Task(
        type="shot_video", status="pending", name=f"接受已完成视频 Clip: 镜{shot.index} · C1",
        description="以原 ComfyUI 回执登记用户已接受的 C1 视频；不重新生成",
        source_task_id=source_task.id, novel_id=source_task.novel_id,
        chapter_id=source_task.chapter_id, shot_id=shot.id,
        workflow_id=source_task.workflow_id, workflow_name=source_task.workflow_name,
        workflow_json=source_task.workflow_json, comfyui_prompt_id=expected_prompt_id,
        prompt_text=source_task.prompt_text, reference_images=source_task.reference_images,
        seed=source_task.seed, metadata_json=json.dumps(metadata, ensure_ascii=False),
        started_at=datetime.utcnow(), current_step="正在核验已有 ComfyUI 回执",
    )
    db.add(task)
    db.commit()
    try:
        handled = await recover_completed_clip(
            task, history, db, comfyui_service, validate_media=probe_clip_av,
            download_video_func=file_storage.download_video_receipt,
        )
        db.refresh(task)
        if not handled or task.status != "completed" or not task.result_url:
            raise ValueError(task.error_message or "CLIP_RECEIPT_ACCEPTANCE_RESULT_UNAVAILABLE")
        db.refresh(shot)
        _clear_shot_video_error(shot, shot_repo, video_status="pending")
        db.commit()
        return task
    except Exception as exc:
        db.rollback()
        db.refresh(task)
        if task.status != "completed":
            task.status = "failed"
            task.error_message = str(exc)
            task.current_step = "已完成视频回执接受失败"
            task.completed_at = datetime.utcnow()
            db.commit()
        raise
