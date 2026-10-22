"""Explain Clip recovery authority failures without changing the submitted result."""

from app.models.task import Task
from app.services.effective_execution import task_execution_projection
from app.services.video_director_ai import safe_json_dict
from app.services.video_result_mode import is_candidate


def is_prior_approved_clip_owner(db, task: Task, clip: dict, index: int, revision: int) -> bool:
    owner_id = clip.get("generated_by_task_id")
    if not owner_id or owner_id == task.id:
        return False
    owner = db.get(Task, str(owner_id))
    metadata = safe_json_dict(owner.metadata_json) if owner else {}
    return bool(
        owner and owner.type == "shot_video" and owner.status == "completed"
        and owner.shot_id == task.shot_id and owner.chapter_id == task.chapter_id
        and owner.novel_id == task.novel_id and owner.result_url == clip.get("video_url")
        and owner.created_at and task.created_at and owner.created_at < task.created_at
        and metadata.get("execution_scope") == "CLIP"
        and metadata.get("clip_index") == index
        and metadata.get("clip_plan_revision") == revision
        and metadata.get("approval_status") == "APPROVED"
    )


def recovery_plan_mismatches(db, task: Task, shot) -> list[dict]:
    """Return the current values behind CLIP_RECOVERY_PLAN_CHANGED for task detail UI."""
    metadata = safe_json_dict(task.metadata_json)
    contract = metadata.get("execution_contract") or {}
    identity = contract.get("clip") or {}
    plan = safe_json_dict(shot.video_director_plan) if shot else {}
    index = int(metadata.get("clip_index") or 0)
    revision = int(metadata.get("clip_plan_revision") or 0)
    plan_revision = int(plan.get("clip_plan_revision") or 0)
    clip = next((item for item in plan.get("clip_plan") or []
                 if isinstance(item, dict) and item.get("clip_index") == index), None)
    mismatches = []
    if not clip:
        mismatches.append({"field": "clip", "expected": index, "actual": None})
    if plan_revision != revision:
        mismatches.append({"field": "clip_plan_revision", "expected": revision, "actual": plan_revision})
    for field, expected in (("clip_index", index), ("clip_plan_revision", revision)):
        if identity.get(field) != expected:
            mismatches.append({"field": f"execution_contract.clip.{field}",
                               "expected": expected, "actual": identity.get(field)})
    if clip and plan_revision == revision:
        try:
            actual = task_execution_projection(plan, clip, metadata)["effective_capability"]
        except ValueError as exc:
            actual = str(exc)
        expected = contract.get("capability")
        if actual != expected:
            mismatches.append({"field": "effective_capability", "expected": expected, "actual": actual})
    if clip and not is_candidate(metadata):
        owner_id = clip.get("generated_by_task_id")
        if owner_id not in {None, "", task.id} and not is_prior_approved_clip_owner(db, task, clip, index, revision):
            mismatches.append({"field": "generated_by_task_id", "expected": task.id, "actual": owner_id})
    return mismatches
