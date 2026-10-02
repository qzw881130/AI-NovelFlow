"""Narrow invalidation helpers for current canonical Clip execution authority."""

from __future__ import annotations

import json
from typing import Iterable

from sqlalchemy.orm import Session

from app.models.task import Task


ACTIVE_TASK_STATUSES = {"pending", "queued", "processing", "running"}
CURRENT_CLIP_ARTIFACT_FIELDS = {
    "generated_by_task_id",
    "video_url",
    "local_path",
    "source_video_url",
    "generated_at",
    "approval_status",
    "assembled_result",
    "assembled_media_duration",
    "actual_duration",
    "error_message",
}
CURRENT_ASSEMBLY_FIELDS = {
    "merged_video_url",
    "merged_at",
    "assembly_status",
    "assembly_clip_plan_revision",
    "assembly_task_ids",
    "assembly_mode",
    "assembled_result",
}
CURRENT_CLIP_PLAN_FIELDS = {
    "clip_plan",
    "clip_plan_validation",
    "clip_plan_findings",
    "temporal_anchors",
    "clip_plan_approval_mode",
    "execution_readiness",
}


class CanonicalExecutionConflict(ValueError):
    """Raised when invalidation would race an active semantic Clip task."""


def _json_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _clip_index(clip: dict) -> int | None:
    try:
        return int(clip.get("clip_index"))
    except (TypeError, ValueError):
        return None


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def canonical_clip_dependency_closure(plan: dict, directly_affected: Iterable[int]) -> set[int]:
    """Follow explicit Previous-AV edges; independent GENERATE/CUT Clips break the chain."""
    affected = {int(index) for index in directly_affected}
    clips = [item for item in plan.get("clip_plan") or [] if isinstance(item, dict)]
    changed = True
    while changed:
        changed = False
        for clip in clips:
            index = _clip_index(clip)
            capability = str(clip.get("capability") or "").upper()
            if index is None or index in affected or capability not in {"EXTEND", "TEMPORAL_EXTEND"}:
                continue
            try:
                previous_index = int(clip.get("previous_clip_index"))
            except (TypeError, ValueError):
                continue
            if previous_index in affected:
                affected.add(index)
                changed = True
    return affected


def ensure_no_active_canonical_clip_tasks(
    db: Session,
    shot_id: str,
    plan: dict,
    clip_indexes: Iterable[int],
    *,
    exclude_task_ids: Iterable[str] = (),
) -> None:
    """Reject invalidation that could race a queued/running current-revision Clip task."""
    indexes = {int(index) for index in clip_indexes}
    if not indexes:
        return
    revision = _safe_int(plan.get("clip_plan_revision"))
    excluded = {str(task_id) for task_id in exclude_task_ids}
    conflicts = []
    tasks = db.query(Task).filter(
        Task.shot_id == shot_id,
        Task.type == "shot_video",
        Task.status.in_(sorted(ACTIVE_TASK_STATUSES)),
    ).all()
    for task in tasks:
        if str(task.id) in excluded:
            continue
        metadata = _json_dict(task.metadata_json)
        if (
            metadata.get("execution_scope") == "CLIP"
            and _safe_int(metadata.get("clip_plan_revision")) == revision
            and _safe_int(metadata.get("clip_index")) in indexes
        ):
            conflicts.append(f"C{_safe_int(metadata.get('clip_index'))}:{task.id}")
    if conflicts:
        raise CanonicalExecutionConflict(
            "CANONICAL_RECOVERY_CONFLICT: affected Clip has an active task: " + ", ".join(conflicts)
        )


def _state_index_from_source(source: dict | None) -> int | None:
    if not isinstance(source, dict):
        return None
    raw_index = source.get("keyframe_index")
    if raw_index is None:
        source_id = str(source.get("id") or "")
        raw_index = source_id[2:] if source_id.upper().startswith("KF") else None
    try:
        return int(raw_index) if raw_index is not None else None
    except (TypeError, ValueError):
        return None


def current_visual_state_consumers(
    db: Session,
    shot,
    state_index: int,
    previous_image_url: str | None,
) -> set[int]:
    """Return current Clips whose exact CLIP_ONLY task physically consumed the old state image."""
    if not previous_image_url:
        return set()
    plan = _json_dict(shot.video_director_plan)
    if plan.get("canonical_visual_plan") is not True:
        return set()
    revision = _safe_int(plan.get("clip_plan_revision"))
    consumers = set()
    for clip in plan.get("clip_plan") or []:
        if not isinstance(clip, dict):
            continue
        index = _clip_index(clip)
        task_id = str(clip.get("generated_by_task_id") or "")
        result_url = str(clip.get("video_url") or "")
        if index is None or not task_id or not result_url:
            continue
        task = db.query(Task).filter(Task.id == task_id).first()
        metadata = _json_dict(task.metadata_json) if task else {}
        contract = metadata.get("execution_contract") or {}
        if not (
            task
            and task.type == "shot_video"
            and task.status == "completed"
            and task.shot_id == shot.id
            and task.result_url == result_url
            and metadata.get("execution_scope") == "CLIP"
            and _safe_int(metadata.get("clip_index")) == index
            and _safe_int(metadata.get("clip_plan_revision")) == revision
            and contract.get("artifact_kind") == "CLIP_ONLY"
        ):
            continue

        ordinary_references = (metadata.get("video_reference_manifest") or {}).get("references") or []
        ordinary_match = any(
            isinstance(reference, dict)
            and _safe_int(reference.get("source_keyframe_index")) == int(state_index)
            and str(reference.get("image_url") or "") == str(previous_image_url)
            for reference in ordinary_references
        )
        temporal_anchors = (contract.get("temporal_anchor_manifest") or {}).get("anchors") or []
        temporal_match = any(
            isinstance(anchor, dict)
            and _state_index_from_source(anchor.get("source") or anchor.get("provenance")) == int(state_index)
            and str(anchor.get("image_url") or "") == str(previous_image_url)
            for anchor in temporal_anchors
        )
        if ordinary_match or temporal_match:
            consumers.add(index)
    return consumers


def sync_temporal_anchor_state_image(plan: dict, state_index: int, image_url: str, task_id: str) -> None:
    """Keep derived temporal-anchor execution inputs aligned with their canonical state image."""
    for anchor in plan.get("temporal_anchors") or []:
        if not isinstance(anchor, dict):
            continue
        source = anchor.get("source") or anchor.get("provenance")
        if _state_index_from_source(source) != int(state_index):
            continue
        anchor["image_url"] = image_url
        if isinstance(source, dict):
            source["image_task_id"] = task_id


def invalidate_current_canonical_execution(
    shot,
    directly_affected: Iterable[int],
    *,
    preserve_clip_indexes: Iterable[int] = (),
) -> set[int]:
    """Clear only current Clip/assembly authority for the affected Previous-AV closure."""
    plan = _json_dict(shot.video_director_plan)
    if plan.get("canonical_visual_plan") is not True:
        return set()
    direct = {int(index) for index in directly_affected}
    if not direct:
        return set()
    closure = canonical_clip_dependency_closure(plan, direct)
    preserved = {int(index) for index in preserve_clip_indexes}
    invalidated = closure - preserved

    for clip in plan.get("clip_plan") or []:
        if not isinstance(clip, dict) or _clip_index(clip) not in invalidated:
            continue
        for field in CURRENT_CLIP_ARTIFACT_FIELDS:
            clip.pop(field, None)
        clip["execution_status"] = "PLANNED"
        if "status" in clip:
            clip["status"] = "PENDING"

    # Replacing even a preserved direct Clip changes an assembly source.
    for field in CURRENT_ASSEMBLY_FIELDS:
        plan.pop(field, None)
    for clip in plan.get("clip_plan") or []:
        if isinstance(clip, dict) and _clip_index(clip) in closure:
            clip.pop("assembled_result", None)
            clip.pop("assembled_media_duration", None)

    shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
    shot.video_url = None
    shot.video_task_id = None
    shot.video_status = "pending"
    return invalidated


def invalidate_downstream_for_canonical_visual_plan_replacement(shot, plan: dict) -> dict:
    """Drop current downstream authority when a new canonical visual plan replaces the old one."""
    # clip_plan_revision is intentionally retained as a monotonic watermark.
    # The next semantic planning pass increments it, keeping historical Tasks
    # revision-isolated without deleting their rows or physical artifacts.
    for field in CURRENT_CLIP_PLAN_FIELDS:
        plan.pop(field, None)
    for field in CURRENT_ASSEMBLY_FIELDS:
        plan.pop(field, None)

    shot.video_url = None
    shot.video_task_id = None
    shot.video_status = "pending"
    shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
    return plan
