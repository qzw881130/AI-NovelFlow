"""Task-local output policy; candidate execution never adopts production artifacts."""
from copy import deepcopy
import hashlib
import json
from typing import Literal

ResultMode = Literal["APPLY", "CANDIDATE_ONLY"]


def result_mode(metadata=None):
    mode = (metadata or {}).get("result_mode", "APPLY")
    if mode not in ("APPLY", "CANDIDATE_ONLY"):
        raise ValueError("RESULT_MODE_INVALID")
    return mode


def is_candidate(metadata=None):
    return result_mode(metadata) == "CANDIDATE_ONLY"


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def freeze_candidate_source(shot, plan, compiled):
    # Keep the original plan, including official result bindings. This is audit
    # evidence only: it is never copied back to Shot, including on retry.
    source = {"shot_id": shot.id, "chapter_id": shot.chapter_id,
              "shot": {k: getattr(shot, k, None) for k in (
                  "description", "video_description", "duration", "dialogues",
                  "characters", "scene", "props")}, "clip_plan": deepcopy(plan)}
    return {"source_revision": plan.get("clip_plan_revision"),
            "source_clip_plan_fingerprint": _fingerprint(plan),
            "candidate_source": source, "candidate_source_fingerprint": _fingerprint(source),
            "candidate_execution_inputs": deepcopy(compiled)}


def validate_candidate_source(shot, metadata, compiled=None):
    if not is_candidate(metadata):
        return
    plan = json.loads(shot.video_director_plan or "{}")
    current = freeze_candidate_source(shot, plan, {})
    if (not metadata.get("candidate_source")
            or current["candidate_source_fingerprint"] != metadata.get("candidate_source_fingerprint")
            or _fingerprint(metadata["candidate_source"]) != metadata["candidate_source_fingerprint"]):
        raise ValueError("CANDIDATE_SOURCE_CHANGED: source Shot / Clip Plan no longer matches frozen input")
    if compiled is not None and compiled != metadata.get("candidate_execution_inputs"):
        raise ValueError("CANDIDATE_EXECUTION_INPUTS_CHANGED: Previous AV / references / execution contract changed")


def applied_task_filter():
    """SQLite metadata predicate for official-result queries (legacy NULL = APPLY)."""
    from sqlalchemy import case, func
    from app.models.task import Task
    valid = case((func.json_valid(Task.metadata_json) == 1, Task.metadata_json), else_="{}")
    return func.coalesce(func.json_extract(valid, "$.result_mode"), "APPLY") == "APPLY"
