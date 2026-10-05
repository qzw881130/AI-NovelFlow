"""Derived execution images and the shared final image write; no preparation state."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.models.task import Task
from app.services.clip_execution_compiler import (
    get_generate_visual_start_readiness, EARLY_COMPOSITION_CONTRACT, execution_temporal_state_ids,
)
from app.services.canonical_execution_invalidation import (
    ACTIVE_TASK_STATUSES, CanonicalExecutionConflict, canonical_clip_dependency_closure,
    current_visual_state_consumers, ensure_no_active_canonical_clip_tasks,
    invalidate_current_canonical_execution, sync_temporal_anchor_state_image,
)
from app.utils.path_utils import url_to_local_path


def json_dict(value):
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def state_provenance(shot, state_index: int) -> dict | None:
    plan = json_dict(shot.video_director_plan)
    if plan.get("canonical_visual_plan") is not True:
        return None
    state = next((s for s in plan.get("keyframes", []) if s.get("index") == state_index), None)
    if not state:
        raise CanonicalExecutionConflict("CANONICAL_IMAGE_STATE_CHANGED")
    identity = {k: state.get(k) for k in ("index", "role", "time_seconds", "description")}
    if state_index == 1 and state.get("role") == "START":
        identity["shot_description"] = shot.description
    return {"shot_id": shot.id, "clip_plan_revision": plan.get("clip_plan_revision"),
            "state_index": state_index, "state_id": f"KF{state_index}",
            "state_fingerprint": hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}


def frame_provenance(shot, frame_index: int) -> dict | None:
    frames = json.loads(shot.keyframes or "[]")
    if not 0 <= frame_index < len(frames):
        raise ValueError("关键帧序号超出范围")
    index = frames[frame_index].get("plan_keyframe_index")
    if json_dict(shot.video_director_plan).get("canonical_visual_plan") is True and index is None:
        raise CanonicalExecutionConflict("CANONICAL_IMAGE_STATE_CHANGED")
    return state_provenance(shot, int(index)) if index is not None else None


def validate_image_provenance(shot, expected: dict | None, *, frame_index: int | None = None, task_id=None):
    current = frame_provenance(shot, frame_index) if frame_index is not None else state_provenance(shot, 1)
    if current != expected:
        raise CanonicalExecutionConflict("CANONICAL_IMAGE_STATE_CHANGED: 图片任务所属视觉状态或 revision 已变化")
    if task_id and current:
        frames = json.loads(shot.keyframes or "[]")
        current_task_id = frames[frame_index].get("image_task_id") if frame_index is not None else shot.image_task_id
        if current_task_id != task_id:
            raise CanonicalExecutionConflict("CANONICAL_IMAGE_ATTEMPT_CHANGED: 图片结果已被新尝试或人工替换取代")


def task_provenance(task):
    return json_dict(getattr(task, "metadata_json", None)).get("canonical_image_provenance")


def image_exists(url):
    return bool(url and Path(url_to_local_path(url) or url).is_file())


def project_required_execution_images(shot, plan: dict, tasks=(), clip_indexes=None) -> list[dict]:
    """Two independent authorities, deduplicated by current Shot/State identity."""
    if plan.get("canonical_visual_plan") is not True or (plan.get("clip_plan_validation") or {}).get("temporal_contract") != "ELIGIBLE_THEN_SELECTED_V1":
        return []
    if (plan.get("clip_plan_validation") or {}).get("composition_contract") != EARLY_COMPOSITION_CONTRACT:
        return []
    states = {f"KF{s['index']}": s for s in plan.get("keyframes", [])}
    anchors = {a.get("anchor_id"): a for a in plan.get("temporal_anchors", [])}
    items = {}
    for clip in plan.get("clip_plan", []):
        ci = clip.get("clip_index")
        if clip_indexes is not None and ci not in clip_indexes:
            continue
        start = get_generate_visual_start_readiness(shot, plan, clip)
        needs = []
        if start["applicable"]:
            needs.append(("GENERATE_VISUAL_START", f"KF{start['visual_state_index']}", start.get("image_url"), start.get("grounding_source")))
        if clip.get("capability") == "TEMPORAL_EXTEND":
            for sid in execution_temporal_state_ids(clip):
                anchor = anchors.get(f"clip-{ci}-{sid}") or {}
                if sid in (clip.get("selected_temporal_target_ids") or []):
                    needs.append(("SELECTED_TEMPORAL_TARGET", sid, anchor.get("image_url"), "KEYFRAME_IMAGE"))
                if sid == clip.get("early_composition_state_id"):
                    needs.append(("EARLY_COMPOSITION", sid, anchor.get("image_url"), "KEYFRAME_IMAGE"))
        for kind, sid, url, source in needs:
            state = states.get(sid)
            if not state:
                raise ValueError(f"REQUIRED_VISUAL_STATE_UNAVAILABLE: {sid}")
            index = state["index"]
            consumer = {"kind": kind, "consumer_clip_index": ci,
                        "clip_local_time": round(float(state.get("time_seconds") or 0) - float(clip.get("start_time") or 0), 6) if kind != "GENERATE_VISUAL_START" else None,
                        "image_url": url, "ready": image_exists(url)}
            if index not in items:
                provenance = state_provenance(shot, index)
                matching = sorted((t for t in tasks if t.shot_id == shot.id and t.type in {"keyframe_image", "shot_image"} and task_provenance(t) == provenance), key=lambda t: str(t.created_at or ""), reverse=True)
                frames = json.loads(shot.keyframes or "[]")
                frame = next((f for f in frames if f.get("plan_keyframe_index") == index), {})
                current_task_id = frame.get("image_task_id") or state.get("image_task_id")
                if index == 1 and state.get("role") == "START":
                    current_task_id = shot.image_task_id
                active = next((t for t in matching if t.status in ACTIVE_TASK_STATUSES and t.id == current_task_id), None)
                latest = matching[0] if matching else None
                def status(t):
                    return {"task_id": t.id, "status": t.status, "current_step": t.current_step, "error_message": t.error_message} if t else None
                items[index] = {"kind": kind, "state_index": index, "state_id": sid,
                    "shot_time": state.get("time_seconds"), "description": state.get("description"),
                    "consumer_clip_index": ci, "clip_local_time": consumer["clip_local_time"],
                    "image_source": source or ("SHOT_IMAGE" if index == 1 and state.get("role") == "START" else "KEYFRAME_IMAGE"),
                    "image_url": url, "state_image_url": state.get("image_url") or state.get("imageUrl"),
                    "provenance": provenance, "active_task": status(active),
                    "failure": status(latest) if latest and latest.id == current_task_id and latest.status in {"failed", "cancelled"} else None,
                    "consumers": []}
            items[index]["consumers"].append(consumer)
    for item in items.values():
        item["ready"] = all(c["ready"] for c in item["consumers"])
        item["missing"] = not item["ready"]
        if item["ready"]:
            item["failure"] = None
        item["consumer_clip_indexes"] = sorted({c["consumer_clip_index"] for c in item["consumers"]})
    return list(items.values())


def _active_physical_consumers(db, shot, index, old_url, plan):
    if not old_url:
        return set()
    consumers = set()
    for task in db.query(Task).filter(Task.shot_id == shot.id, Task.type == "shot_video", Task.status.in_(sorted(ACTIVE_TASK_STATUSES))).all():
        metadata = json_dict(task.metadata_json)
        if metadata.get("execution_scope") != "CLIP" or metadata.get("clip_plan_revision") != plan.get("clip_plan_revision"):
            continue
        refs = (metadata.get("video_reference_manifest") or {}).get("references") or []
        anchors = ((metadata.get("execution_contract") or {}).get("temporal_anchor_manifest") or {}).get("anchors") or []
        ordinary = any(r.get("source_keyframe_index") == index and r.get("image_url") == old_url for r in refs)
        temporal = any(((a.get("source") or a.get("provenance") or {}).get("keyframe_index") == index
                        or (a.get("source") or a.get("provenance") or {}).get("id") == f"KF{index}")
                       and a.get("image_url") == old_url for a in anchors)
        if ordinary or temporal:
            consumers.add(int(metadata["clip_index"]))
    return consumers


def commit_visual_state_image(db, shot, image_url: str, *, frame_index: int | None,
                              expected_provenance: dict | None, task_id=None, local_path=None):
    """Validate before mutation; caller owns the transaction and Task completion."""
    db.refresh(shot)
    validate_image_provenance(shot, expected_provenance, frame_index=frame_index, task_id=task_id)
    plan = json_dict(shot.video_director_plan)
    canonical = plan.get("canonical_visual_plan") is True
    frames = json.loads(shot.keyframes or "[]")
    index = expected_provenance["state_index"] if expected_provenance else None
    if not canonical and frame_index is not None:
        index = frames[frame_index].get("plan_keyframe_index")
        index = int(index) if index is not None else None
    state = next((s for s in plan.get("keyframes", [])
                  if (s.get("index") if canonical else int(s.get("index") or -1)) == index), {})
    old_urls = {state.get("image_url"), state.get("imageUrl")}
    main_old_urls = set()
    if frame_index is None:
        main_old_urls.add(shot.image_url)
        # Manual replacement must also recover the old physical source while a
        # START attempt has temporarily cleared the Shot URL.
        previous_task_id = shot.image_task_id
        image_task = db.query(Task).filter(Task.id == previous_task_id).first() if previous_task_id else None
        if image_task:
            main_old_urls.add(json_dict(image_task.metadata_json).get("canonical_image_previous_url"))
        old_urls.update(main_old_urls)
    else:
        old_urls.update((frames[frame_index].get("image_url"), frames[frame_index].get("imageUrl")))
    for anchor in plan.get("temporal_anchors", []):
        source = anchor.get("source") or anchor.get("provenance") or {}
        if source.get("keyframe_index") == index or source.get("id") == f"KF{index}":
            old_urls.add(anchor.get("image_url"))
    old_urls.discard(None)
    old_urls.discard(image_url)
    consumers, active = set(), set()
    if canonical and index:
        for old_url in old_urls:
            consumers.update(current_visual_state_consumers(db, shot, index, old_url))
            active.update(_active_physical_consumers(db, shot, index, old_url, plan))
    if canonical:
        ensure_no_active_canonical_clip_tasks(db, shot.id, plan, canonical_clip_dependency_closure(plan, consumers | active))
    if frame_index is None:
        shot.image_url, shot.image_path, shot.image_status, shot.image_task_id = image_url, local_path, "completed", task_id
        # A dead URL or alias of the replaced main image must not mask its new
        # binding after the caller safely cleans up the old physical file.
        state_url = state.get("image_url") or state.get("imageUrl")
        if state and (not image_exists(state_url) or state_url in main_old_urls):
            state.pop("image_url", None)
            state.pop("imageUrl", None)
            state["image_task_id"] = task_id
    else:
        frames[frame_index].update(image_url=image_url, image_task_id=task_id)
        shot.keyframes = json.dumps(frames, ensure_ascii=False)
        if state:
            state["image_url"] = image_url
            if canonical or task_id:
                state["image_task_id"] = task_id
    if index:
        if canonical:
            sync_temporal_anchor_state_image(plan, index, image_url, task_id)
        shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
    if consumers:
        invalidate_current_canonical_execution(shot, consumers)
    return consumers


async def prepare_required_images(db, shot, revision: int, submit_keyframe, submit_start, *, clip_indexes=None, state_indexes=None):
    """Thin per-item adapter around existing image entry points. Never starts video."""
    db.refresh(shot)
    plan = json_dict(shot.video_director_plan)
    if plan.get("clip_plan_revision") != revision:
        raise CanonicalExecutionConflict("CLIP_PLAN_REVISION_CHANGED")
    if (plan.get("clip_plan_validation") or {}).get("temporal_contract") != "ELIGIBLE_THEN_SELECTED_V1" or (plan.get("clip_plan_validation") or {}).get("passed") is not True:
        raise CanonicalExecutionConflict("CLIP_PLAN_NOT_READY")
    if (plan.get("clip_plan_validation") or {}).get("composition_contract") != EARLY_COMPOSITION_CONTRACT:
        raise CanonicalExecutionConflict("COMPOSITION_CONTRACT_REPLAN_REQUIRED")
    valid_clips = {c.get("clip_index") for c in plan.get("clip_plan", [])}
    if clip_indexes is not None and not set(clip_indexes).issubset(valid_clips):
        raise ValueError("未知 Clip scope")
    tasks = db.query(Task).filter(Task.shot_id == shot.id, Task.type.in_(["keyframe_image", "shot_image"])).all()
    required = project_required_execution_images(shot, plan, tasks, clip_indexes)
    if state_indexes is not None and not set(state_indexes).issubset({i["state_index"] for i in required}):
        raise ValueError("State 不属于当前 required scope")
    results = []
    for item in required:
        if state_indexes is not None and item["state_index"] not in state_indexes:
            continue
        result = {"state_index": item["state_index"], "state_id": item["state_id"], "consumer_clip_indexes": item["consumer_clip_indexes"], "task_id": None}
        try:
            db.refresh(shot)
            if state_provenance(shot, item["state_index"]) != item["provenance"]:
                raise CanonicalExecutionConflict("CANONICAL_IMAGE_STATE_CHANGED")
            # Earlier submissions may await prompt work. Recompute this item's
            # authority, physical readiness and active attempt immediately before use.
            current_plan = json_dict(shot.video_director_plan)
            current_tasks = db.query(Task).filter(Task.shot_id == shot.id, Task.type.in_(["keyframe_image", "shot_image"])).all()
            current = next((i for i in project_required_execution_images(shot, current_plan, current_tasks, clip_indexes)
                            if i["state_index"] == item["state_index"]), None)
            if current is None:
                raise CanonicalExecutionConflict("REQUIRED_IMAGE_SCOPE_CHANGED")
            item = current
            result["consumer_clip_indexes"] = item["consumer_clip_indexes"]
            if item["ready"]:
                result["status"] = "READY"
            elif item["active_task"]:
                result.update(status="REUSED", task_id=item["active_task"]["task_id"])
            elif image_exists(item["state_image_url"]):
                commit_visual_state_image(db, shot, item["state_image_url"], frame_index=_frame_index(shot, item["state_index"]), expected_provenance=item["provenance"])
                db.commit()
                result["status"] = "READY"
            else:
                if item["state_index"] == 1 and next(s for s in plan["keyframes"] if s["index"] == 1).get("role") == "START":
                    task_id = await submit_start(item["provenance"])
                else:
                    task_id = await submit_keyframe(_frame_index(shot, item["state_index"]), item["provenance"])
                result.update(status="QUEUED", task_id=task_id)
        except Exception as exc:
            db.rollback()
            detail = getattr(exc, "detail", None)
            result.update(status="FAILED", reason=str(detail) if detail else str(exc))
        results.append(result)
    db.refresh(shot)
    return results


def _frame_index(shot, state_index):
    frames = json.loads(shot.keyframes or "[]")
    return next(i for i, frame in enumerate(frames) if frame.get("plan_keyframe_index") == state_index)


def project_clip_execution_readiness(db, shot, plan, required):
    from app.services.shot_video_service import resolve_extend_previous_av
    from app.services.clip_execution_compiler import get_canonical_execution_readiness
    from app.models.novel import Chapter
    chapter = db.query(Chapter).filter(Chapter.id == shot.chapter_id).first()
    output = []
    clips = plan.get("clip_plan", [])
    for clip in clips:
        ci = clip["clip_index"]
        images_ready = all(c["ready"] for i in required for c in i["consumers"] if c["consumer_clip_index"] == ci)
        result = {"clip_index": ci, "images_ready": images_ready, "ready": images_ready,
                  "code": "READY" if images_ready else "REQUIRED_IMAGES_MISSING", "previous_clip_index": clip.get("previous_clip_index")}
        guard = get_canonical_execution_readiness(shot, plan, [clip])
        if not guard["ready"]:
            result.update(ready=False, code=guard["code"])
        if images_ready and guard["ready"] and clip.get("capability") in {"EXTEND", "TEMPORAL_EXTEND"}:
            previous = next((c for c in clips if c["clip_index"] == clip.get("previous_clip_index")), {})
            try:
                resolve_extend_previous_av(db, chapter.novel_id if chapter else "", shot.chapter_id, shot,
                    {**clip, "clip_plan_revision": plan.get("clip_plan_revision")},
                    {"clip_index": previous.get("clip_index"), "clip_plan_revision": plan.get("clip_plan_revision"),
                     "generated_by_task_id": previous.get("generated_by_task_id"), "result_url": previous.get("video_url")})
            except ValueError:
                result.update(ready=False, code="WAITING_PREVIOUS_AV")
        output.append(result)
    return output
