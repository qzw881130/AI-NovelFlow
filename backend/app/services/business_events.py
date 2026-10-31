"""Small durable event ledger, fed by committed business results (not notifications).

The ORM adapter observes existing Task/Shot/Review saves. It never mutates those
objects; external delivery runs separately through NotificationService.
"""
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import event, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.database import SessionLocal
from app.models.notification import BusinessEvent
from app.models.task import Task
from app.models.shot import Shot
from app.models.novel import Chapter
from app.models.image_quality_review import ImageQualityReview
from app.services.notification_registry import EVENT_REGISTRY, GRID_TASK_EVENTS

logger = logging.getLogger(__name__)
IDS = ("novel_id", "chapter_id", "shot_id", "visual_state_id", "clip_id", "task_id", "review_id", "llm_log_id")
DETAIL_KEYS = {"shot_index", "visual_state_index", "clip_index", "task_type", "review_id",
               "created_count", "updated_count", "deleted_count",
               "failed_dimensions", "warning_dimensions", "review_dimensions", "template_id", "template_version",
               "llm_log_id", "result_key_sha256", "comfyui_prompt_id", "error_code", "stage",
               "blocking_findings", "repair_levels", "l1_invocations", "reused_result", "revision",
               "clip_count", "dimension", "status", "summary", "historical_source", "attempt",
               "example_id", "chapter_count", "duration_ms", "source_task_id",
               "planned_duration", "optimized_duration", "actual_duration",
               "duration_delta", "actual_duration_delta", "video_duration",
               "elapsed_time", "success_count", "failure_count", "cancelled_count", "total_count",
               "novel_name", "chapter_number", "music_cue_count", "music_chapter_count",
               "no_music_required", "panel_index", "grid_step"}
DISPLAY_KEYS = {"shot_index", "clip_index", "visual_state_index", "duration_ms",
                "actual_duration", "video_duration", "elapsed_time", "clip_count",
                "chapter_count", "success_count", "failure_count", "cancelled_count", "total_count",
                "stage", "repair_levels", "summary", "error_code", "novel_name", "chapter_number"}


def obj(value, default=None):
    try:
        result = json.loads(value) if isinstance(value, str) else value
        return result if result is not None else ({} if default is None else default)
    except (TypeError, ValueError):
        return {} if default is None else default


def text_summary(value):
    text = str(value or "")
    text = re.sub(r"(?i)data:[^\s]+|Bearer\s+\S+|(?:sk-|sk_)[\w-]+", "[redacted]", text)
    text = re.sub(r"(?i)(api[_ -]?key|token|secret|password|authorization)\s*[:=]\s*[^\s,;]+", r"\1=[redacted]", text)
    return text[:500]


def safe_details(value):
    if not isinstance(value, dict):
        return {}
    def clean(v):
        if isinstance(v, dict):
            return {k: clean(x) for k, x in v.items() if k in DETAIL_KEYS}
        if isinstance(v, list):
            return [clean(x) for x in v[:30]]
        return v if isinstance(v, (bool, int, float)) or v is None else text_summary(v)
    return clean(value)


def record_event(db, event_type, payload=None, *, dedupe_key=None, timestamp=None,
                 historical=False, is_test=False):
    """Independent event transaction; callers must commit the business result first.

    The unique key, rather than a check-then-insert, is the deduplication authority.
    Historical imports are explicitly marked and never send notifications.
    """
    if event_type not in EVENT_REGISTRY:
        return None
    payload = payload or {}
    key = dedupe_key or str(uuid4())
    existing = db.query(BusinessEvent).filter_by(dedupe_key=key).first()
    if existing:
        return existing
    raw_status = str(payload.get("raw_status") or payload.get("status") or "INFO")
    status = payload.get("status")
    if status not in {"SUCCESS", "FAIL", "ERROR", "INFO"}:
        status = "ERROR" if event_type.endswith(".error") else "FAIL" if event_type.endswith(".failed") else "SUCCESS" if event_type.endswith((".completed", ".passed")) else "INFO"
    row = BusinessEvent(event_type=event_type, dedupe_key=key,
        timestamp=timestamp or datetime.now(timezone.utc),
        **{k: str(payload[k]) if payload.get(k) is not None else None for k in IDS},
        raw_status=raw_status, status=status,
        needs_attention=status in {"FAIL", "ERROR"} or event_type == "task.review.required" or raw_status in {"WARNING", "REVIEW"},
        source=text_summary(payload.get("source") or "business"), trigger=payload.get("trigger"),
        message=text_summary(payload.get("message") or EVENT_REGISTRY[event_type].description),
        details_json=json.dumps(safe_details({**(payload.get("details") if isinstance(payload.get("details"), dict) else {}),
                                               **({key: payload[key] for key in DISPLAY_KEYS if key in payload}
                                                  if is_test else {})}), ensure_ascii=False),
        historical=historical, is_test=is_test,
        notification_status="historical" if historical else "pending")
    db.add(row)
    try:
        db.commit()
        db.refresh(row)
        return row
    except IntegrityError:
        db.rollback()
        return db.query(BusinessEvent).filter_by(dedupe_key=key).first()


def publish(event_type, payload=None, *, dedupe_key=None, timestamp=None, historical=False):
    """Best effort and no network I/O on the generation/review call stack."""
    try:
        with SessionLocal() as db:
            row = record_event(db, event_type, payload, dedupe_key=dedupe_key,
                               timestamp=timestamp, historical=historical)
            return row.id if row else None
    except Exception:
        logger.exception("Business result retained; event persistence failed: %s", event_type)
        return None


def task_context(task):
    meta = obj(task.metadata_json)
    optimizer = meta.get("h3_prompt_optimizer") or {}
    anchor = (meta.get("reference_selector_input") or {}).get("current_anchor") or {}
    # Do not mistake legacy zero-based frame_index for the Director state index.
    provenance = meta.get("canonical_image_provenance") or {}
    state_index = anchor.get("index") or provenance.get("state_index") or meta.get("plan_keyframe_index")
    clip_index = task.clip_index if task.type in GRID_TASK_EVENTS else meta.get("clip_index")
    clip_id = meta.get("clip_id") or (f"{task.shot_id}:clip:{clip_index}"
                                     if task.type in GRID_TASK_EVENTS and task.shot_id and clip_index else None)
    return {"novel_id": task.novel_id, "chapter_id": task.chapter_id, "shot_id": task.shot_id,
            "task_id": task.id, "clip_id": clip_id,
            "llm_log_id": optimizer.get("llm_log_id"),
            "visual_state_id": str(state_index) if state_index is not None else None,
            "trigger": meta.get("trigger") or ("automatic" if task.parent_task_id or meta.get("auto_pipeline") else None),
            "details": {"visual_state_index": state_index, "clip_index": clip_index,
                        "task_type": task.type, "comfyui_prompt_id": task.comfyui_prompt_id,
                        "panel_index": meta.get("panel_index"), "grid_step": meta.get("grid_step"),
                        "total_count": (len(meta.get("shot_ids") or []) if task.type in {"grid_auto_batch", "grid_board_batch", "grid_review_batch"}
                                        else meta.get("expected_count") if task.type in {"grid_batch", "grid_chapter_plan_batch"} else None),
                        "error_code": optimizer.get("error_code"),
                        "source_task_id": task.source_task_id,
                        "planned_duration": meta.get("planned_duration"),
                        "optimized_duration": meta.get("optimized_duration"),
                        "actual_duration": meta.get("actual_duration"),
                        "duration_delta": meta.get("duration_delta"),
                        "actual_duration_delta": meta.get("actual_duration_delta")}}


def review_event(review, task=None):
    if review.status not in {"success", "error"}:
        return None
    snapshot = obj(review.input_snapshot_json)
    anchor = (snapshot.get("target") or {}).get("current_anchor") or {}
    payload = task_context(task) if task else {k: snapshot.get(k) for k in IDS}
    payload.update({k: snapshot[k] for k in IDS if snapshot.get(k) is not None})
    state_index = anchor.get("index")
    if state_index is not None:
        payload["visual_state_id"] = str(state_index)
    verdict = review.overall if review.status == "success" else "ERROR"
    code = ("image.review.error" if review.status == "error" else
            "image.review.failed" if verdict == "FAIL" else
            "image.review.warning" if verdict == "WARNING" else "image.review.passed")
    dimensions = obj(review.dimensions_json)
    payload.update(review_id=review.id, task_id=review.task_id, llm_log_id=review.llm_log_id,
        source="image_quality_review", trigger=review.trigger, raw_status=verdict,
        status="ERROR" if verdict == "ERROR" else "SUCCESS" if verdict == "PASS" else "INFO" if verdict == "WARNING" else "FAIL",
        message=review.summary if review.status == "success" else "图片 AI 评审执行异常，请查看原始评审记录。",
        details={**payload.get("details", {}), "visual_state_index": state_index or payload.get("visual_state_id"),
                 "failed_dimensions": [k for k, v in dimensions.items() if (v.get("status") if isinstance(v, dict) else v) == "FAIL"],
                 "warning_dimensions": [k for k, v in dimensions.items() if (v.get("status") if isinstance(v, dict) else v) == "WARNING"],
                 "review_dimensions": [{"dimension": k, "status": v.get("status") if isinstance(v, dict) else v} for k, v in dimensions.items()],
                 "template_id": review.template_id, "template_version": review.template_version,
                 "result_key_sha256": hashlib.sha256(str(snapshot.get("generated_image") or "").encode()).hexdigest()})
    return code, payload, f"review:{review.id}:{code}", review.completed_at or review.created_at


def task_events(task):
    """One generation event per saved result; regeneration replaces its synonym."""
    if task.status not in {"completed", "failed"}:
        return []
    meta = obj(task.metadata_json)
    suffix = "completed" if task.status == "completed" else "failed"
    code = None
    if task.type == "keyframe_image":
        code = f"visual_state.generation.{suffix}"
    elif task.type in {"character_portrait", "scene_image", "prop_image"}:
        entity = {"character_portrait": "character", "scene_image": "scene", "prop_image": "prop"}[task.type]
        code = f"{entity}.image.generation.{suffix}"
    elif task.type in {"shot_image", "single_image_edit"}:
        code = f"image.generation.{suffix}"
    elif task.type == "shot_video":
        if meta.get("execution_scope") == "CLIP" or meta.get("clip_index"):
            code = (f"clip.result.recovery.{suffix}" if meta.get("manual_receipt_recovery")
                    else "clip.regeneration.completed" if suffix == "completed" and meta.get("is_clip_regeneration")
                    else f"clip.generation.{suffix}")
        else:
            code = f"shot.generation.{suffix}"
    elif task.type in {"shot_image_batch", "shot_video_batch"}:
        code = f"batch.generation.{suffix}"
    elif task.type == "chapter_background_music":
        code = f"background_music.generation.{suffix}"
    elif task.type == "novel_video":
        code = f"novel.video.merge.{suffix}"
    elif task.type in GRID_TASK_EVENTS:
        code = f"{GRID_TASK_EVENTS[task.type][0]}.{suffix}"
    if not code:
        return []
    payload = task_context(task)
    if task.type == "chapter_background_music":
        payload["details"].update(
            music_cue_count=len(meta.get("cues") or []),
            no_music_required=not bool(meta.get("cues")) and suffix == "completed",
        )
    elif task.type == "novel_video":
        payload["details"]["music_chapter_count"] = meta.get("background_music_chapter_count") or 0
    payload.update(source="task.result", raw_status=task.status,
                   message=text_summary(task.error_message) if suffix == "failed" and task.error_message
                   else EVENT_REGISTRY[code].description)
    # A retry is a new attempt; repeated saves of the same Comfy result are not.
    attempt = task.comfyui_prompt_id or str(task.started_at or task.created_at or task.id)
    result = [(code, payload, f"task:{task.id}:{attempt}:{code}", task.completed_at or task.updated_at or task.created_at)]
    error = meta.get("comfyui_error") or {}
    if suffix == "failed" and error.get("error_code") == "COMFYUI_CONNECTION_FAILED":
        result.append(("comfyui.connection.failed", {**payload, "details": {**payload["details"], "error_code": error["error_code"]}},
                       f"connection:{task.id}:{attempt}", task.completed_at))
    return result


def shot_events(shot, previous, db):
    plan = obj(shot.video_director_plan)
    chapter = db.get(Chapter, shot.chapter_id)
    base = {"shot_id": shot.id, "chapter_id": shot.chapter_id,
            "novel_id": chapter.novel_id if chapter else None, "source": "video_director.saved_result",
            "details": {"shot_index": shot.index}}
    results = []
    old_calls = {(str(c.get("step")), c.get("created_at")) for c in previous.get("ai_calls", [])}
    for call in plan.get("ai_calls", []):
        step = str(call.get("step"))
        if (step, call.get("created_at")) in old_calls or step not in {"11", "12", "13", "14"}:
            continue
        parsed = call.get("parsed_result") or {}
        parsed = parsed if isinstance(parsed, dict) else {}
        if step == "14" and parsed.get("reused_result"):
            continue  # Reusing an optimizer result is not another optimization.
        suffix = "completed" if call.get("status") == "success" else "failed"
        code = f"clip.prompt.{'optimize' if step == '14' else 'build'}.{suffix}"
        clip_index = call.get("clip_index")
        payload = {**base, "clip_id": f"{shot.id}:clip:{clip_index}" if clip_index else None,
                   "llm_log_id": parsed.get("llm_log_id"), "raw_status": call.get("status"),
                   "details": {**base["details"], "clip_index": clip_index, "stage": step,
                               "error_code": parsed.get("error_code"),
                               "blocking_findings": (parsed.get("authority_check") or {}).get("blocking_findings", [])}}
        key = f"ai:{shot.id}:{step}:{parsed.get('llm_log_id') or call.get('created_at')}:{suffix}"
        stamp = datetime.fromisoformat(call["created_at"]) if call.get("created_at") else None
        results.append((code, payload, key, stamp))
        repair = parsed.get("preflight_repair")
        # L0/no-repair preflight failures are optimization failures, not failed
        # L1 repair attempts. The optimizer event above retains their findings.
        if repair and int(parsed.get("l1_invocations_this_call", repair.get("l1_invocations")) or 0) > 0:
            passed = (parsed.get("authority_check") or {}).get("passed", False)
            results.append((f"preflight.repair.{'completed' if passed else 'failed'}",
                            {**payload, "source": "h3_preflight_repair.final", "details": {**payload["details"], "l1_invocations": repair.get("l1_invocations")}},
                            f"{key}:repair", stamp))
    return results


def install_business_event_hooks(factory=SessionLocal):
    """Observe committed ORM writes across workers, HTTP and recovery paths.

    No historical scan runs on startup. Bulk SQL writes are handled explicitly
    at their owning service. Returns a remover for isolated tests.
    """
    target = factory.class_
    if getattr(target, "_novelflow_event_hooks", False):
        return lambda: None

    def capture_previous(db, _context, _instances):
        try:
            previous = db.info.setdefault("event_previous_plans", {})
            for item in db.dirty:
                if isinstance(item, Shot) and inspect(item).attrs.video_director_plan.history.has_changes():
                    # Assignment to an expired attribute has no ORM old value.
                    # Read it before UPDATE, otherwise old calls could be replayed.
                    previous[item.id] = obj(db.connection().execute(select(Shot.video_director_plan).where(Shot.id == item.id)).scalar())
        except Exception:
            logger.exception("Could not capture prior event source; skip unavailable history")

    def collect(db, _context):
        try:
            pending = db.info.setdefault("business_events", {})
            for item in list(db.new) + list(db.dirty):
                state = inspect(item)
                rows = []
                if isinstance(item, ImageQualityReview) and state.attrs.status.history.has_changes():
                    row = review_event(item, db.get(Task, item.task_id))
                    rows = [row] if row else []
                elif isinstance(item, Task):
                    if state.attrs.status.history.has_changes():
                        rows = task_events(item)
                elif isinstance(item, Shot) and state.attrs.video_director_plan.history.has_changes():
                    previous = db.info.get("event_previous_plans", {}).pop(item.id, None)
                    if previous is not None or item in db.new:
                        rows = shot_events(item, previous or {}, db)
                for code, payload, key, stamp in rows:
                    pending[key] = (code, payload, stamp)
        except Exception:
            logger.exception("Event extraction failed; business save is unaffected")

    def committed(db):
        if db.in_nested_transaction():
            return
        pending = db.info.pop("business_events", {})
        for key, (code, payload, stamp) in pending.items():
            # Dedicated transaction; never commit/rollback a business Session.
            try:
                with factory() as events_db:
                    record_event(events_db, code, payload, dedupe_key=key, timestamp=stamp)
            except Exception:
                logger.exception("Business committed; event %s could not be saved", code)

    def rolled_back(db):
        db.info.pop("business_events", None)
        db.info.pop("event_previous_plans", None)

    event.listen(target, "before_flush", capture_previous)
    event.listen(target, "after_flush", collect)
    event.listen(target, "after_commit", committed)
    event.listen(target, "after_rollback", rolled_back)
    target._novelflow_event_hooks = True
    def remove():
        for name, fn in (("before_flush", capture_previous), ("after_flush", collect), ("after_commit", committed), ("after_rollback", rolled_back)):
            event.remove(target, name, fn)
        target._novelflow_event_hooks = False
    return remove


def shot_operation_event(business_db, shot, event_type, *, stage, success, operation_id=None, details=None):
    """For operations with no Task row (planner and final assembly)."""
    try:
        with sessionmaker(bind=business_db.get_bind())() as db:
            chapter = db.get(Chapter, shot.chapter_id)
            payload = {"novel_id": chapter.novel_id if chapter else None, "chapter_id": shot.chapter_id,
                       "shot_id": shot.id, "source": stage, "raw_status": "completed" if success else "failed",
                       "details": {"shot_index": shot.index, "stage": stage, **(details or {})}}
            row = record_event(db, event_type, payload,
                               dedupe_key=f"{event_type}:{shot.id}:{operation_id or uuid4()}")
            return row.id if row else None
    except Exception:
        logger.exception("Event failed; Shot operation remains unchanged")


def observed_assembly(fn):
    """Observe the final return of the existing merger, including early failures."""
    from functools import wraps
    @wraps(fn)
    async def wrapper(db, shot, *args, **kwargs):
        operation_id = str(uuid4())
        try:
            result = await fn(db, shot, *args, **kwargs)
        except Exception:
            shot_operation_event(db, shot, "shot.assembly.failed", stage="shot_video.merge", success=False, operation_id=operation_id)
            raise
        if not result.get("skipped"):
            success = bool(result.get("success"))
            # The native accumulated output can be reused without creating a new
            # file. Same final URL/revision is the same assembly result.
            plan = result.get("plan") or {}
            identity = f"{result.get('video_url')}:{plan.get('clip_plan_revision')}" if success else operation_id
            shot_operation_event(db, shot, f"shot.assembly.{'completed' if success else 'failed'}",
                                 stage="shot_video.merge", success=success, operation_id=identity,
                                 details={"clip_count": len(plan.get("clip_plan") or [])})
        return result
    return wrapper
