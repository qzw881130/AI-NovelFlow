"""Recover submitted canonical Clips from their exact ComfyUI receipt, without generation."""
from app.models.task import Task
from app.repositories.shot_repository import ShotRepository
from app.services.canonical_execution_invalidation import (
    CanonicalExecutionConflict, canonical_clip_dependency_closure,
    ensure_no_active_canonical_clip_tasks,
)
from app.services.continuous_clip_av import CONTINUOUS_CAPABILITIES, NATIVE_CONTINUITY_OUTPUT
from app.services.video_director_ai import safe_json_dict


INTERRUPTED_CLIP_ERROR = "服务重启中断 Clip 回写；已保留 ComfyUI prompt，未重新生成"
_recovering_task_ids: set[str] = set()


async def recover_completed_clip(task, history: dict, db, comfyui_service) -> bool:
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
        if (task.comfyui_prompt_id != prompt_id
                or safe_json_dict(task.metadata_json).get("execution_contract") != contract
                or not (task.status in {"pending", "running"}
                        or task.status == "failed" and task.error_message == INTERRUPTED_CLIP_ERROR)):
            raise CanonicalExecutionConflict("CLIP_RECOVERY_EXECUTION_CHANGED")
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
            validate_result=validate_result,
        )
        if task.status == "completed":
            task.error_message = None
            task.current_step = "已恢复生成结果"
            db.commit()
        return task.status in {"completed", "failed", "cancelled"}
    finally:
        _recovering_task_ids.discard(task.id)
