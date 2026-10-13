"""Delivery-only coalescing for one Task/Clip failure chain.

Events remain independent ledger rows. Ambiguous ownership is never merged.
"""
import json
from datetime import datetime, timedelta, timezone

from app.models.notification import BusinessEvent
from app.models.task import Task


INTERMEDIATE_FAILURES = {
    "clip.prompt.build.failed", "clip.prompt.optimize.failed", "preflight.repair.failed",
}


def _index(value):
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
        return number if 0 < number < 100000 and str(value).strip() in {str(number), f"{number}.0"} else None
    except (TypeError, ValueError):
        return None


def _details(row):
    try:
        value = json.loads(row.details_json or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _clip(row):
    index = _index(_details(row).get("clip_index"))
    if index:
        return index
    if row.shot_id and isinstance(row.clip_id, str):
        prefix = f"{row.shot_id}:clip:"
        if row.clip_id.startswith(prefix):
            return _index(row.clip_id[len(prefix):])
    return None


def _naive_utc(value):
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def _matching_task(db, row, clip):
    if not row.shot_id or not clip:
        return None
    if row.task_id:
        candidates = [db.get(Task, row.task_id)]
    else:
        # The saved AI call has no Task ID. Search only clip-scoped video Tasks
        # of this Shot, then verify metadata and the actual execution interval.
        candidates = (db.query(Task).filter(
            Task.shot_id == row.shot_id, Task.type == "shot_video",
        ).order_by(Task.created_at.desc()).limit(50).all())
    matches = []
    for task in candidates:
        if not task or task.type != "shot_video" or task.shot_id != row.shot_id:
            continue
        try:
            meta = json.loads(task.metadata_json or "{}")
        except (TypeError, ValueError):
            continue
        if not isinstance(meta, dict) or meta.get("execution_scope") != "CLIP" or _index(meta.get("clip_index")) != clip:
            continue
        if (row.clip_id and meta.get("clip_id") and not row.clip_id.startswith(f"{row.shot_id}:clip:")
                and row.clip_id != meta["clip_id"]):
            continue
        began = task.started_at or task.created_at
        if not began or _naive_utc(row.timestamp) < _naive_utc(began):
            continue
        if task.completed_at and _naive_utc(row.timestamp) > _naive_utc(task.completed_at):
            continue
        matches.append(task)
    return matches[0] if len(matches) == 1 else None


def _final_event(db, row, task_id, clip):
    finals = db.query(BusinessEvent).filter(
        BusinessEvent.event_type == "clip.generation.failed",
        BusinessEvent.task_id == task_id,
        BusinessEvent.is_test == row.is_test,
        BusinessEvent.timestamp >= row.timestamp,
    ).all()
    for final in finals:
        if row.shot_id and final.shot_id != row.shot_id:
            continue
        if not row.shot_id and _index(_details(row).get("shot_index")) != _index(_details(final).get("shot_index")):
            continue
        row_pseudo = bool(row.shot_id and row.clip_id and row.clip_id.startswith(f"{row.shot_id}:clip:"))
        final_pseudo = bool(final.shot_id and final.clip_id and final.clip_id.startswith(f"{final.shot_id}:clip:"))
        if row.clip_id and final.clip_id and row.clip_id != final.clip_id and not (row_pseudo or final_pseudo):
            continue
        if _clip(final) == clip or row.clip_id and final.clip_id == row.clip_id:
            return final
    return None


def failure_delivery_decision(db, row, *, final_subscribed: bool, external_enabled: bool):
    """Return send, hold or suppress; PAGE_SOUND is handled independently."""
    if row.event_type not in INTERMEDIATE_FAILURES or not final_subscribed or not external_enabled:
        return "send"
    clip = _clip(row)
    if not clip and row.task_id and not row.is_test:
        task = db.get(Task, row.task_id)
        if task and task.type == "shot_video" and (not row.shot_id or task.shot_id == row.shot_id):
            try:
                meta = json.loads(task.metadata_json or "{}")
                clip = _index(meta.get("clip_index")) if isinstance(meta, dict) else None
            except (TypeError, ValueError):
                pass
    if not clip or not (row.shot_id or _index(_details(row).get("shot_index"))):
        return "send"
    # Simulation must never inspect a real Task, even if its payload names one.
    task = None if row.is_test else _matching_task(db, row, clip)
    task_id = task.id if task else row.task_id
    if not task_id:
        return "send"
    if _final_event(db, row, task_id, clip):
        return "suppress"
    if row.is_test and row.task_id:
        # The development UI can submit the two synthetic events in sequence.
        # A bounded hold keeps a forgotten first simulation from staying pending.
        recorded = _naive_utc(row.recorded_at) if row.recorded_at else None
        if recorded and datetime.now(timezone.utc).replace(tzinfo=None) - recorded < timedelta(minutes=5):
            return "hold"
    if task and task.status == "failed":
        # The Task commit and final event write use separate sessions. Give that
        # write time to appear; if it never does, deliver the prompt failure.
        terminal_at = task.completed_at or task.updated_at
        if terminal_at and datetime.now(timezone.utc).replace(tzinfo=None) - _naive_utc(terminal_at) >= timedelta(seconds=30):
            return "send"
        return "hold"
    if task and task.status in {"pending", "queued", "running"}:
        return "hold"
    return "send"
