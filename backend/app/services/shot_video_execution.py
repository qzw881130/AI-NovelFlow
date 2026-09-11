"""Fenced video runs. Media and diagnostics outlive losing workers; Shot is a sink.

Only the final whole-shot transaction may attach a production result. Terminal
settlement changes only an owned generating status. Recovery never resubmits jobs.
"""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
from io import BytesIO
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

from app.models.shot import Shot
from app.models.task import Task
from app.services.task_execution import (
    ExecutionConflict, artifact_directory, execution_purpose, execution_record,
    load_execution_shot, metadata,
)


HEARTBEAT_SECONDS = 15
LEASE_SECONDS = 120
REQUEST_KEYS = {
    "use_keyframes", "use_reference_audio", "selected_mode", "workflow_id",
    "only_window_index", "auto_merge_clips", "skip_llm_when_prompt_exists",
}
TASK_TARGET = ("type", "shot_id", "chapter_id", "novel_id", "workflow_id", "parent_task_id")
RESULT_KEYS = {
    "prompt_id", "workflow_json", "video_url", "local_path", "source_video_url",
    "generated_at", "generated_by_task_id", "error_message", "h3_prompt_gate_failed",
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def _assert_no_dirty_shot(db):
    if any(isinstance(item, Shot) for item in (*db.new, *db.dirty, *db.deleted)):
        raise ExecutionConflict("LIVE_SHOT_DIRTY_IN_VIDEO_TRANSACTION")


def _clip_projection(data):
    run = data["video_run"]
    plan = json.loads(data["execution"]["working_shot"].get("video_director_plan") or "{}")
    collection = "window_plans" if run["mode"] == "MULTI_KEYFRAME" else "clips"
    items = plan.get(collection) or []
    return [deepcopy(item) for spec in run["expected"] for position, item in enumerate(items, 1)
            if int(item.get("window_index") or item.get("clip_index") or position) == spec["clip_index"]]


def has_video_execution(task):
    """Malformed or benchmark metadata must never fall through to legacy recovery."""
    if task.type != "shot_video":
        return False
    try:
        data = metadata(task)
        return "execution" in data or "video_run" in data or data.get("execution_purpose") == "benchmark"
    except (ValueError, ExecutionConflict):
        return True


def _expected_clips(shot, request):
    from app.services import shot_video_service as video
    plan = video.safe_json_dict(shot.video_director_plan)
    mode = request["selected_mode"] or plan.get("selected_mode") or "SINGLE_FRAME"
    if mode not in {"SINGLE_FRAME", "FIRST_LAST_FRAME", "MULTI_KEYFRAME"}:
        raise ExecutionConflict("INVALID_VIDEO_MODE")
    windows = video.safe_json_list(plan.get("window_plans"))
    if mode == "MULTI_KEYFRAME" and not windows:
        raise ExecutionConflict("MISSING_EXECUTION_WINDOWS")
    if mode == "MULTI_KEYFRAME" and len(windows) > 1:
        clips = [{
            "clip_index": int(window.get("window_index") or index),
            "start_time": float(window.get("start_time") or 0), "end_time": float(window.get("end_time") or 0),
            "selected_frame_count": int(window.get("selected_frame_count") or 0),
            "workflow_key": window.get("workflow_key"), "keyframe_indexes": window.get("keyframe_indexes") or [],
            "workflow_type": "three_frame_video" if int(window.get("selected_frame_count") or 0) == 3 else "four_frame_video",
        } for index, window in enumerate(windows, 1)]
    else:
        duration = video._resolved_duration_from_plan(shot, plan)
        clip = deepcopy((plan.get("clips") or [{}])[0])
        if windows:
            window = windows[0]
            clip.update(clip_index=window.get("window_index") or 1, start_time=window.get("start_time") or 0,
                        end_time=window.get("end_time") or duration, selected_frame_count=window.get("selected_frame_count"),
                        workflow_key=window.get("workflow_key"), keyframe_indexes=window.get("keyframe_indexes") or [])
        if not clip:
            clip = {"clip_index": 1, "start_time": 0, "end_time": duration}
        clips = [{key: value for key, value in clip.items() if key in {
            "clip_index", "start_time", "end_time", "selected_frame_count", "workflow_key", "workflow_type", "keyframe_indexes",
        }}]
        clips[0].setdefault("clip_index", 1)
    indexes = [int(clip["clip_index"]) for clip in clips]
    if len(set(indexes)) != len(indexes) or indexes != sorted(indexes) or any(index < 1 for index in indexes):
        raise ExecutionConflict("INVALID_CLIP_ORDER")
    for clip in clips:
        if mode == "MULTI_KEYFRAME" and (clip.get("selected_frame_count") not in {3, 4}
                or len(clip.get("keyframe_indexes") or []) != clip["selected_frame_count"]):
            raise ExecutionConflict("INVALID_CLIP_FRAMES")
    only = request["only_window_index"]
    if only is not None:
        clips = [clip for clip in clips if clip["clip_index"] == only]
        if not clips:
            raise ExecutionConflict("CLIP_NOT_FOUND")
    return mode, clips


def _handle(task, data):
    run = data["video_run"]
    return {"task_id": task.id, "run_id": run["run_id"], "claim_token": task.claim_token, "attempt": task.attempt,
            "target": deepcopy(run["target"]), "expected_hash": run["expected_hash"],
            "attempts": {key: slot["attempt_id"] for key, slot in run["clips"].items()},
            "request_hash": digest(run["request"]), "purpose": execution_purpose(task), "directory": run["directory"]}


def _check_data(task, data, handle):
    record = execution_record(task)
    run = data.get("video_run") or {}
    if (not record or run.get("version") != 1 or record["attempt_id"] != handle["run_id"]
            or execution_purpose(task) != handle["purpose"]
            or run.get("run_id") != handle["run_id"] or run.get("target") != handle["target"]
            or run.get("directory") != handle["directory"]
            or any(getattr(task, key) != value for key, value in handle["target"].items())
            or task.claim_token != handle["claim_token"] or task.attempt != handle["attempt"]
            or run.get("expected_hash") != handle["expected_hash"] or digest(run.get("expected")) != handle["expected_hash"]
            or digest(run.get("request")) != handle["request_hash"] or record.get("request") != run.get("request")
            or {key: slot.get("attempt_id") for key, slot in run.get("clips", {}).items()} != handle["attempts"]):
        raise ExecutionConflict("VIDEO_EXECUTION_REPLACED")
    if task.status != "running" or run.get("phase") not in {"running", "merging"} or run.get("superseded_by"):
        raise ExecutionConflict("VIDEO_EXECUTION_NOT_ACTIVE")


def _conditions(db, task, data, *, target=True, compare_metadata=True, parent_active=True):
    from sqlalchemy.orm import aliased
    conditions = [Task.id == task.id, Task.status == task.status,
                  Task.claim_token == task.claim_token, Task.attempt == task.attempt]
    if compare_metadata:
        conditions.append(Task.metadata_json == task.metadata_json)
    conditions.extend(getattr(Task, key) == getattr(task, key) for key in TASK_TARGET)
    if task.parent_task_id:
        parent = aliased(Task)
        parent_query = db.query(parent.id).filter(parent.id == task.parent_task_id)
        if parent_active:
            conditions.append(parent_query.filter(parent.status.in_(["pending", "running"])).exists())
        else:
            saved_parent = db.query(Task).filter(Task.id == task.parent_task_id).populate_existing().first()
            conditions.append(parent_query.filter(parent.status == saved_parent.status).exists() if saved_parent else ~parent_query.exists())
    if target and data["video_run"].get("publication_target"):
        conditions.append(db.query(Shot.id).filter(*[
            getattr(Shot, key) == value for key, value in data["video_run"]["publication_target"].items()
        ]).exists())
    return conditions


def check_current(db, handle, *, target=True, parent_active=True):
    with db.no_autoflush:
        task = db.query(Task).filter(Task.id == handle["task_id"]).populate_existing().first()
        if not task:
            raise ExecutionConflict("VIDEO_TASK_REMOVED")
        data = metadata(task)
        _check_data(task, data, handle)
        if db.query(Task.id).filter(*_conditions(db, task, data, target=target, compare_metadata=False, parent_active=parent_active)).first() is None:
            raise ExecutionConflict("VIDEO_TARGET_OR_PARENT_REPLACED")
        return task, data


def settle_terminated_video(db, task):
    """Settle a fenced production failure/cancellation, including before claim.

    Call after the Task terminal CAS and db.refresh(task), before the caller's
    commit. This helper never commits, flushes, or changes Task/media/plan facts.
    False means inapplicable or ownership/source drift; do not undo Task failure.
    """
    if task.type != "shot_video" or task.status not in {"failed", "cancelled"}:
        return False
    try:
        if execution_purpose(task) != "production":
            return False
        record = execution_record(task)
        if record is None:
            return False
        request = record.get("request")
        if not isinstance(request, dict) or "only_window_index" not in request or request["only_window_index"] is not None:
            return False
        if request.get("workflow_id") not in (None, task.workflow_id):
            return False
        snapshot = record["shot_snapshot"]
        if not {"id", "chapter_id", "video_url", "video_director_plan", "video_director_plan_revision"} <= snapshot.keys():
            return False
        source = {key: value for key, value in snapshot.items() if key not in {"created_at", "updated_at"}}
        source.update(video_task_id=task.id, video_status="generating")
        run = metadata(task).get("video_run")
        if run is not None:
            if (run.get("version") != 1 or run.get("run_id") != record["attempt_id"] or run.get("scope") != "whole_shot"
                    or run.get("request") != request or run.get("superseded_by") or run.get("phase") == "completed"
                    or any(run.get("target", {}).get(key) != getattr(task, key) for key in TASK_TARGET)
                    or run.get("publication_target") != source):
                return False
    except (ExecutionConflict, ValueError, TypeError, KeyError, AttributeError):
        return False
    _assert_no_dirty_shot(db)
    with db.no_autoflush:
        task_condition = db.query(Task.id).filter(*[
            getattr(Task, column.key) == getattr(task, column.key) for column in Task.__table__.columns
            if column.key not in {"created_at", "updated_at"}
        ]).exists()
        conditions = [getattr(Shot, key) == value for key, value in source.items()] + [task_condition]
        if db.query(Shot.id).filter(*conditions).first() is None:
            return False
        return db.query(Shot).filter(*conditions).update({"video_status": "failed"}, synchronize_session=False) == 1


def _write(db, handle, mutate, *, private_shot=None, publish=False, target=True, parent_active=True, extra_conditions=()):
    """No dirty ORM projections or internally committing Shot repositories here."""
    for _ in range(4):
        _assert_no_dirty_shot(db)
        task, data = check_current(db, handle, target=target, parent_active=parent_active)
        conditions = _conditions(db, task, data, target=target, parent_active=parent_active) + list(extra_conditions)
        if private_shot is not None and data["execution"]["revision"] != private_shot._execution_revision:
            raise ExecutionConflict("PRIVATE_SHOT_CHANGED")
        fields = mutate(data) or {}
        if private_shot is not None:
            data["execution"]["revision"] += 1
        fields.update(metadata_json=json.dumps(data, ensure_ascii=False, allow_nan=False), heartbeat_at=datetime.utcnow())
        try:
            count = db.query(Task).filter(*conditions).update(fields, synchronize_session=False)
            attached = 1
            if count == 1 and publish:
                run = data["video_run"]
                source = run["publication_target"]
                plan = json.loads(data["execution"]["working_shot"]["video_director_plan"] or "{}")
                plan.update(merged_video_url=run["result"]["url"], merged_at=fields["completed_at"].isoformat(),
                            video_execution_task_id=task.id, video_execution_attempt_id=run["run_id"])
                for key in ("error_message", "task_error_message"):
                    plan.pop(key, None)
                attached = db.query(Shot).filter(*[getattr(Shot, key) == value for key, value in source.items()]).update({
                    "video_url": run["result"]["url"], "video_status": "completed", "video_task_id": task.id,
                    "video_director_plan": json.dumps(plan, ensure_ascii=False),
                    "video_director_plan_revision": int(source["video_director_plan_revision"] or 0) + 1,
                }, synchronize_session=False)
            elif count == 1 and fields.get("status") in {"failed", "cancelled"}:
                db.refresh(task)
                settle_terminated_video(db, task)
            if count == attached == 1:
                db.commit()
                db.refresh(task)
                if private_shot is not None:
                    private_shot._execution_revision = data["execution"]["revision"]
                    for key, value in data["execution"]["working_shot"].items():
                        setattr(private_shot, key, deepcopy(value))
                return data
            db.rollback()
        except BaseException:
            db.rollback()
            raise
    raise ExecutionConflict("VIDEO_WRITE_CONFLICT")


def capture(handle, kind, value):
    path = Path(handle["directory"]) / f"{kind}-{uuid4().hex}.json"
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False)
    return {"path": str(path), "sha256": file_digest(path)}


def observe(db, handle, kind, value):
    """Archive first: deletion, malformed metadata, and CAS exhaustion lose no bytes."""
    event = {"at": datetime.utcnow().isoformat(), "run_id": handle["run_id"], "claim_token": handle["claim_token"],
             "kind": kind, "attachment": "detached", "evidence": capture(handle, kind, value)}
    for _ in range(4):
        if any(isinstance(item, Shot) for item in (*db.new, *db.dirty, *db.deleted)):
            return event
        task = db.query(Task).filter(Task.id == handle["task_id"]).populate_existing().first()
        if not task:
            return event
        try:
            data = metadata(task)
        except (ValueError, ExecutionConflict):
            return event
        observations = data.setdefault("video_observations", [])
        if not isinstance(observations, list):
            return event
        observations.append(event)
        count = db.query(Task).filter(Task.id == task.id, Task.status == task.status,
                                     Task.metadata_json == task.metadata_json).update(
            {"metadata_json": json.dumps(data, ensure_ascii=False, allow_nan=False)}, synchronize_session=False)
        if count == 1:
            db.commit()
            return event
        db.rollback()
    return event


def fail_execution(db, handle, message, *, clip_index=None, gate_failed=False, extra_conditions=()):
    capture(handle, "failure", {"message": str(message), "clip_index": clip_index, "run_id": handle["run_id"]})
    def fail(data):
        run = data["video_run"]
        run.update(phase="failed", failure={"message": str(message), "clip_index": clip_index})
        for slot in run["clips"].values():
            if slot["submission"]["state"] == "submitting":
                slot["submission"]["state"] = "unknown"
            if slot["spec"]["clip_index"] == clip_index and slot["receipt"] is None:
                slot["state"] = "FAILED"
                slot["gate_failed"] = gate_failed
        working = data["execution"]["working_shot"]
        working["video_status"] = "failed"
        plan = json.loads(working.get("video_director_plan") or "{}")
        for collection in ("window_plans", "clips"):
            for position, item in enumerate(plan.get(collection) or [], 1):
                index = int(item.get("window_index") or item.get("clip_index") or position)
                if index == clip_index and run["clips"].get(str(index), {}).get("state") == "FAILED":
                    item.update(status="FAILED", error_message=str(message))
                    if gate_failed:
                        item["h3_prompt_gate_failed"] = True
        working["video_director_plan"] = json.dumps(plan, ensure_ascii=False)
        data["execution"]["revision"] += 1
        return {"status": "failed", "error_message": str(message), "current_step": "Video execution failed",
                "video_director_clips": json.dumps(_clip_projection(data), ensure_ascii=False),
                "completed_at": datetime.utcnow()}
    try:
        _write(db, handle, fail, target=False, parent_active=False, extra_conditions=extra_conditions)
        return True
    except ExecutionConflict:
        observe(db, handle, "late-failure", {"message": str(message), "clip_index": clip_index})
        return False


def refresh_private_shot(db, shot):
    task, data = check_current(db, shot._video_execution)
    record = data["execution"]
    if (shot._execution_task_id != task.id or shot._execution_attempt_id != record["attempt_id"]
            or shot._execution_claim_token != task.claim_token):
        raise ExecutionConflict("PRIVATE_SHOT_REPLACED")
    for key, value in record["working_shot"].items():
        setattr(shot, key, deepcopy(value))
    shot._execution_revision = record["revision"]


def mutate_private_plan(db, shot, mutator):
    def change(data):
        working = data["execution"]["working_shot"]
        plan = json.loads(working.get("video_director_plan") or "{}")
        updated = mutator(deepcopy(plan))
        plan = plan if updated is None else updated
        working["video_director_plan"] = json.dumps(plan, ensure_ascii=False)
        return {"video_director_clips": json.dumps(_clip_projection(data), ensure_ascii=False)}
    return _write(db, shot._video_execution, change, private_shot=shot)


def save_gate_record(db, task, record):
    handle = task._video_execution
    def save(data):
        slot = data["video_run"]["clips"][str(record["clip_index"])]
        if slot["attempt_id"] != record["attempt_id"]:
            raise ExecutionConflict("CLIP_ATTEMPT_REPLACED")
        gate = data.setdefault("h3_prompt_gate", {"version": 1, "clips": {}})
        records = gate["clips"].setdefault(str(record["clip_index"]), [])
        for index, previous in enumerate(records):
            if previous.get("attempt_id") == record["attempt_id"]:
                records[index] = deepcopy(record)
                break
        else:
            records.append(deepcopy(record))
    try:
        _write(db, handle, save)
    except ExecutionConflict:
        observe(db, handle, "detached-gate", record)


def claim_video_execution(db, task_id):
    _assert_no_dirty_shot(db)
    task = db.query(Task).filter(Task.id == task_id).populate_existing().first()
    if not task or task.status != "pending":
        return None
    if task.type != "shot_video":
        raise ExecutionConflict("NOT_A_VIDEO_TASK")
    data = metadata(task)
    record = execution_record(task)
    if not record or "video_run" in data:
        raise ExecutionConflict("VIDEO_RUN_ALREADY_STARTED_OR_MISSING")
    request = record.get("request")
    if not isinstance(request, dict) or not REQUEST_KEYS <= request.keys():
        raise ExecutionConflict("VIDEO_REQUEST_NOT_FROZEN")
    if any(type(request[key]) is not bool for key in (
            "use_keyframes", "use_reference_audio", "auto_merge_clips", "skip_llm_when_prompt_exists")):
        raise ExecutionConflict("INVALID_VIDEO_REQUEST_OPTIONS")
    if request["workflow_id"] not in (None, task.workflow_id):
        raise ExecutionConflict("VIDEO_REQUEST_WORKFLOW_CHANGED")
    if request["only_window_index"] is not None and (type(request["only_window_index"]) is not int or request["only_window_index"] < 1):
        raise ExecutionConflict("INVALID_REQUESTED_CLIP")
    shot = load_execution_shot(task)
    mode, expected = _expected_clips(shot, request)
    if request.get("actual_state_handoff") is not None:
        from app.services.actual_state_handoff import validate_handoff_scope
        validate_handoff_scope(request, json.loads(shot.video_director_plan or "{}"), mode)
    source = None
    if execution_purpose(task) == "production":
        live = db.query(Shot).filter(Shot.id == task.shot_id).populate_existing().first()
        if not live or live.video_task_id not in {record["shot_snapshot"].get("video_task_id"), task.id}:
            raise ExecutionConflict("VIDEO_TARGET_REPLACED")
        source = {key: getattr(live, key) for key in record["shot_snapshot"] if key not in {"created_at", "updated_at"}}
        if any(value != record["shot_snapshot"][key] for key, value in source.items()
               if key not in {"video_task_id", "video_status"}):
            raise ExecutionConflict("VIDEO_SOURCE_CHANGED_BEFORE_START")
    plan = json.loads(shot.video_director_plan or "{}")
    # Old receipts remain in shot_snapshot and the live Shot, never in new slots.
    for collection in ("clips", "window_plans"):
        for item in plan.get(collection) or []:
            for key in RESULT_KEYS:
                item.pop(key, None)
            item["status"] = "PENDING"
    for key in ("merged_video_url", "merged_at", "error_message", "task_error_message"):
        plan.pop(key, None)
    record["working_shot"]["video_director_plan"] = json.dumps(plan, ensure_ascii=False)
    record["revision"] += 1
    now, token = datetime.utcnow(), uuid4().hex
    data["execution"] = record
    data["video_run"] = {
        "version": 1, "run_id": record["attempt_id"], "phase": "running", "mode": mode,
        "scope": "clip" if request["only_window_index"] is not None else "whole_shot", "request": deepcopy(request),
        "expected": expected, "expected_hash": digest(expected), "target": {key: getattr(task, key) for key in TASK_TARGET},
        "publication_target": source, "directory": str(artifact_directory(task)),
        "clips": {str(clip["clip_index"]): {"spec": clip, "attempt_id": uuid4().hex, "state": "PENDING",
                  "submission": {"state": "not_submitted"}, "receipt": None} for clip in expected},
    }
    if request["only_window_index"] is not None and request["auto_merge_clips"]:
        data["video_run"]["auto_merge_note"] = "Clip-only artifact; old clips are not eligible for whole-shot publication"
    conditions = _conditions(db, task, data)
    count = db.query(Task).filter(*conditions).update({
        "status": "running", "claim_token": token, "worker_id": f"shot-video-{token}",
        "attempt": int(task.attempt or 0) + 1, "claimed_at": now, "heartbeat_at": now, "started_at": now,
        "current_step": "Preparing private video execution", "comfyui_prompt_id": None,
        "workflow_json": None, "result_url": None, "error_message": None,
        "metadata_json": json.dumps(data, ensure_ascii=False, allow_nan=False),
        "video_director_clips": json.dumps(_clip_projection(data), ensure_ascii=False),
    }, synchronize_session=False)
    if count != 1:
        db.rollback()
        return None
    db.commit()
    db.refresh(task)
    handle = _handle(task, data)
    shot = load_execution_shot(task)
    task._video_execution = shot._video_execution = handle
    return task, shot, handle


def frozen_client(endpoint):
    from app.services.comfyui.client import ComfyUIClient
    class BoundClient(ComfyUIClient):
        @property
        def base_url(self):
            return endpoint
    return BoundClient()


def _same_graph(left, right):
    from app.services.keyframe_reference_graph import H3_NUMBER_PORTS, KeyframeGraphError, numeric_graph_digest
    try:
        return (numeric_graph_digest(left, extra_number_ports=H3_NUMBER_PORTS)
                == numeric_graph_digest(right, extra_number_ports=H3_NUMBER_PORTS))
    except KeyframeGraphError:
        return False


def verify_history(slot, history):
    submit = slot["submission"]
    if not isinstance(history, dict) or not isinstance(history.get("status"), dict):
        raise ExecutionConflict("MISSING_SUCCESSFUL_HISTORY")
    payload = history.get("prompt") or []
    status = history.get("status") or {}
    if (submit.get("state") != "acknowledged" or not submit.get("prompt_id")
            or status.get("completed") is not True or status.get("status_str") not in {"success", "completed"}
            or not isinstance(payload, list) or len(payload) < 3 or payload[1] != submit["prompt_id"] or not _same_graph(payload[2], submit.get("graph"))
            or digest(submit.get("graph")) != submit.get("graph_hash")):
        raise ExecutionConflict("HISTORY_NOT_PROVEN_FOR_CLIP_ATTEMPT")
    outputs = (history.get("outputs") or {}).get(submit["output_node"])
    if not isinstance(outputs, dict):
        raise ExecutionConflict("MISSING_CONFIGURED_VIDEO_OUTPUT")
    candidates = [item for key in ("images", "videos", "gifs") for item in (outputs or {}).get(key, [])
                  if isinstance(item, dict) and str(item.get("filename") or "").lower().endswith((".mp4", ".webm", ".mov"))]
    if len(candidates) != 1:
        raise ExecutionConflict("AMBIGUOUS_OR_MISSING_VIDEO_OUTPUT")
    output = {key: candidates[0].get(key, default) for key, default in (("filename", ""), ("subfolder", ""), ("type", "output"))}
    return submit["endpoint"].rstrip("/") + "/view?" + urlencode(output)


def _url_identity(url):
    value = urlsplit(url)
    return value.scheme, value.netloc, value.path, parse_qs(value.query)


def verified_clip_receipt(run, index):
    """The same per-member checks are used before handoff and by the final barrier."""
    spec = next(item for item in run["expected"] if item["clip_index"] == index)
    slot = run["clips"][str(index)]
    receipt, submit = slot.get("receipt") or {}, slot["submission"]
    if (slot["spec"] != spec or slot["state"] != "SUCCEEDED" or slot.get("gate_failed")
            or receipt.get("run_id") != run["run_id"] or receipt.get("attempt_id") != slot["attempt_id"]
            or receipt.get("clip_index") != index or receipt.get("prompt_id") != submit.get("prompt_id")
            or not submit.get("prompt_id") or receipt.get("graph_hash") != submit.get("graph_hash")):
        raise ExecutionConflict("INCOMPLETE_SAME_ATTEMPT_BARRIER")
    directory = Path(run["directory"]).resolve()
    if (not Path(receipt["path"]).resolve().is_relative_to(directory)
            or not Path(receipt["history"]["path"]).resolve().is_relative_to(directory)
            or not receipt.get("bytes") or Path(receipt["path"]).stat().st_size != receipt["bytes"]):
        raise ExecutionConflict("CLIP_ARTIFACT_NOT_OWNED_OR_EMPTY")
    if file_digest(receipt["history"]["path"]) != receipt["history"]["sha256"]:
        raise ExecutionConflict("HISTORY_HASH_CHANGED")
    history = json.loads(Path(receipt["history"]["path"]).read_text(encoding="utf-8"))
    if verify_history(slot, history) != receipt["source_url"] or file_digest(receipt["path"]) != receipt["sha256"]:
        raise ExecutionConflict("CLIP_RECEIPT_CHANGED")
    return deepcopy(receipt)


def completion_manifest(data):
    run = data["video_run"]
    expected = run["expected"]
    indexes = [clip["clip_index"] for clip in expected]
    if (not expected or indexes != sorted(set(indexes)) or digest(expected) != run["expected_hash"]
            or set(run["clips"]) != {str(clip["clip_index"]) for clip in expected}):
        raise ExecutionConflict("INVALID_COMPLETION_MEMBERSHIP")
    manifest, cids = [], set()
    for spec in expected:
        receipt = verified_clip_receipt(run, spec["clip_index"])
        if receipt["prompt_id"] in cids:
            raise ExecutionConflict("INCOMPLETE_SAME_ATTEMPT_BARRIER")
        cids.add(receipt["prompt_id"])
        manifest.append({key: receipt[key] for key in ("run_id", "attempt_id", "clip_index", "prompt_id", "graph_hash", "path", "sha256")})
    return manifest


def begin_merge(db, handle):
    token = uuid4().hex
    def begin(data):
        run = data["video_run"]
        if run["phase"] != "running":
            raise ExecutionConflict("MERGE_ALREADY_CLAIMED")
        manifest = completion_manifest(data)
        run.update(phase="merging", merge={"token": token, "manifest": manifest, "manifest_hash": digest(manifest)})
        return {"current_step": "Merging verified same-attempt clips", "progress": 85}
    return _write(db, handle, begin)["video_run"]["merge"]


def publish_result(db, handle, merge, path):
    from app.utils.path_utils import local_path_to_url
    if not Path(path).resolve().is_relative_to(Path(handle["directory"]).resolve()) or not Path(path).stat().st_size:
        raise ExecutionConflict("RESULT_ARTIFACT_NOT_OWNED_OR_EMPTY")
    result = {"path": str(path), "url": local_path_to_url(str(path)), "sha256": file_digest(path), "bytes": Path(path).stat().st_size,
              "manifest_hash": merge["manifest_hash"]}
    _, current = check_current(db, handle)
    purpose = execution_purpose(SimpleNamespace(metadata_json=current))
    attach = purpose == "production" and current["video_run"]["scope"] == "whole_shot"
    def complete(data):
        run = data["video_run"]
        if (run["phase"] != "merging" or run["merge"] != merge or digest(completion_manifest(data)) != merge["manifest_hash"]
                or file_digest(path) != result["sha256"]):
            raise ExecutionConflict("MERGE_OWNERSHIP_OR_INPUTS_CHANGED")
        result.update(kind=run["scope"], attachment="archived" if purpose == "benchmark" else "attached" if attach else "detached")
        run.update(phase="completed", result=result)
        data["execution"]["result"] = deepcopy(result)
        data["execution"]["working_shot"].update(video_url=result["url"], video_status="completed", video_task_id=handle["task_id"])
        return {"status": "completed", "result_url": result["url"], "progress": 100, "error_message": None,
                "completed_at": datetime.utcnow(), "current_step": "Clip complete (not a whole-shot publication)" if run["scope"] == "clip" else "Video execution complete"}
    _write(db, handle, complete, publish=attach)
    return result


def completed_video_artifact(db, task_id, *, shot_id=None):
    """Manual-merge interface: validate an attached result, never compose live URLs."""
    try:
        task = db.query(Task).filter(Task.id == task_id).populate_existing().first()
        if not task or not has_video_execution(task) or task.status != "completed" or execution_purpose(task) != "production":
            raise ExecutionConflict("COMPLETED_PRODUCTION_VIDEO_RUN_REQUIRED")
        record, data = execution_record(task), metadata(task)
        run = data["video_run"]
        result = run["result"]
        mode, expected = _expected_clips(SimpleNamespace(**record["shot_snapshot"]), record["request"])
        if (run["phase"] != "completed" or run["scope"] != "whole_shot" or run["run_id"] != record["attempt_id"]
                or record["request"].get("only_window_index") is not None or run["request"] != record["request"]
                or run["expected"] != expected or run["mode"] != mode or run["merge"]["manifest"] != completion_manifest(data)
                or result["attachment"] != "attached" or result["url"] != task.result_url
                or result["manifest_hash"] != digest(completion_manifest(data)) or file_digest(result["path"]) != result["sha256"]
                or (shot_id is not None and task.shot_id != shot_id)):
            raise ExecutionConflict("INVALID_COMPLETED_VIDEO_RECEIPT")
        shot = db.query(Shot).filter(Shot.id == task.shot_id).populate_existing().first()
        if not shot or shot.video_task_id != task.id or shot.video_url != result["url"]:
            raise ExecutionConflict("VIDEO_PUBLICATION_SUPERSEDED")
        return {"success": True, "skipped": True, "video_url": result["url"], "run_id": run["run_id"],
                "plan": json.loads(shot.video_director_plan or "{}")}
    except (ExecutionConflict, KeyError, TypeError, ValueError, OSError) as error:
        return {"success": False, "message": str(error)}


async def _heartbeat(handle, session_factory):
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        db = session_factory()
        try:
            _write(db, handle, lambda data: {})
        except ExecutionConflict:
            return
        except Exception as error:
            db.rollback()
            observe(db, handle, "heartbeat-error", {"message": str(error)})
            return
        finally:
            db.close()


async def reconcile_video_execution(db, task, *, now=None, lease_timeout_seconds=LEASE_SECONDS):
    """None = legacy; False = handled/unchanged; True = expired run fenced.

    TaskService MUST skip its legacy video branches for either boolean result.
    No network request is made while a lease is live or a task is terminal.
    """
    if not has_video_execution(task):
        return None
    task = db.query(Task).filter(Task.id == task.id).populate_existing().first()
    if not task or task.status not in {"pending", "running"}:
        return False
    _assert_no_dirty_shot(db)
    data = metadata(task)
    heartbeat = task.heartbeat_at
    clock = now or datetime.utcnow()
    if not data.get("video_run"):
        started = task.started_at or task.created_at
        timeout = 1800 if task.status == "pending" else lease_timeout_seconds
        if not started or started.replace(tzinfo=None) > clock.replace(tzinfo=None) - timedelta(seconds=timeout):
            return False
        record = execution_record(task)
        count = db.query(Task).filter(Task.id == task.id, Task.status == task.status, Task.metadata_json == task.metadata_json,
                                     Task.heartbeat_at == heartbeat).update({
            "status": "failed", "error_message": "INTERRUPTED_BEFORE_VIDEO_CLAIM: no automatic resubmission",
            "current_step": "Video execution interrupted", "completed_at": clock,
        }, synchronize_session=False)
        if count != 1:
            db.rollback()
            return False
        db.refresh(task)
        settle_terminated_video(db, task)
        db.commit()
        observe(db, {"task_id": task.id, "run_id": record["attempt_id"], "claim_token": task.claim_token,
                     "directory": str(artifact_directory(task))}, "interrupted-before-claim", {"execution": record})
        return True
    if task.status != "running":
        return False
    if heartbeat and heartbeat.replace(tzinfo=None) > clock.replace(tzinfo=None) - timedelta(seconds=lease_timeout_seconds):
        return False
    handle = _handle(task, data)
    saved_slots = deepcopy(list(data["video_run"]["clips"].values()))
    if not fail_execution(db, handle, "INTERRUPTED_VIDEO_RUN: no automatic resubmission", extra_conditions=(Task.heartbeat_at == heartbeat,)):
        return False
    from app.services.file_storage import file_storage
    for slot in saved_slots:
        submit = slot["submission"]
        if submit.get("state") != "acknowledged":
            continue
        try:
            state = await frozen_client(submit["endpoint"]).get_prompt_state(submit["prompt_id"])
            history = state.get("history") or {}
            observe(db, handle, "recovery-history", {"clip_attempt_id": slot["attempt_id"], "submission": submit, "state": state})
            url = verify_history(slot, history)
            destination = Path(handle["directory"]) / f"recovered-{slot['attempt_id']}-{uuid4().hex}.mp4"
            path = await file_storage.download_video(url=url, novel_id=task.novel_id, chapter_id=task.chapter_id,
                                                    shot_number=slot["spec"]["clip_index"], destination=destination)
            if path and Path(path) == destination and Path(path).stat().st_size:
                observe(db, handle, "recovery-output", {"attempt_id": slot["attempt_id"], "prompt_id": submit["prompt_id"],
                                                       "path": str(path), "sha256": file_digest(path), "source_url": url})
            else:
                raise ExecutionConflict("RECOVERY_ARTIFACT_NOT_ARCHIVED")
        except Exception as error:
            observe(db, handle, "recovery-error", {"attempt_id": slot["attempt_id"], "message": str(error)})
    return True


def _video_reference_inputs(video, shot, plan, frames, mode, multi, clip, mapping, *, check_files=True):
    keyframes = frames
    transitions = video.safe_json_list(plan.get("transitions"))
    start_url, keyframe_paths = shot.image_url, []
    if mode == "MULTI_KEYFRAME":
        indexes = clip.get("keyframe_indexes") or []
        by_index = {int(frame["index"]): frame for frame in frames}
        keyframes = [by_index[index] for index in indexes]
        transitions = video._filter_transitions_for_keyframe_indexes(transitions, indexes)
        if multi and not (indexes[0] == 1 and keyframes[0].get("role") == "START"):
            start_url = keyframes[0].get("image_url")
        keyframe_paths = [video.url_to_local_path(frame.get("image_url")) for frame in keyframes[1:]]
    elif mode == "FIRST_LAST_FRAME":
        end = next((frame for frame in frames if frame.get("role") == "END"), {})
        keyframe_paths = [video.url_to_local_path(end.get("image_url"))]
        mapping.update(reference_image_node_id=mapping.get("first_image_node_id"), keyframe_node_1=mapping.get("last_image_node_id"))
    start_path = video.url_to_local_path(start_url)
    if check_files and (not start_path or any(not path or not Path(path).is_file() for path in [start_path, *keyframe_paths])):
        raise ExecutionConflict("VIDEO_REFERENCE_MISSING")
    references = [{"label": f"C{clip['clip_index']} start", "url": start_url}] + [
        {"label": f"C{clip['clip_index']} frame {index}", "url": video.local_path_to_url(path)} for index, path in enumerate(keyframe_paths, 1)]
    return {"keyframes": keyframes, "transitions": transitions, "start_url": start_url, "start_path": start_path,
            "keyframe_paths": keyframe_paths, "references": references, "mapping": mapping}


async def _validate_visual_inputs(db, shot, handle, video, plan, frames, run, workflows, multi, *, observer=None):
    from PIL import Image
    from app.services import visual_state_validator as validator

    request = validator.VisualStateValidation.model_validate(run["request"]["visual_state_validation"], strict=True)
    if not request.enabled:
        return {}, {}, None
    source = {"run_id": handle["run_id"], "request_hash": handle["request_hash"],
              "snapshot_hash": digest(check_current(db, handle)[1]["execution"]["shot_snapshot"]),
              "plan_revision": shot.video_director_plan_revision,
              "declared_characters": video.safe_json_list(shot.characters), "declared_props": video.safe_json_list(shot.props)}
    _write(db, handle, lambda current: current.update(visual_state_validation={
        "version": 1, "enabled": True, "decision": "UNKNOWN", "source": source, "status": "preparing",
    }) or {"current_step": "Validating selected visual states"})
    selections, frozen, references, artifacts = {}, {}, [], {}
    preparing = {}
    try:
        for clip in run["expected"]:
            key = str(clip["clip_index"])
            preparing = {"clip_index": clip["clip_index"], "reference_index": None}
            inputs = _video_reference_inputs(video, shot, plan, frames, run["mode"], multi, clip,
                                             video.safe_json_dict(workflows[key]["node_mapping"]), check_files=False)
            selections[key], frozen[key] = inputs, []
            paths = [inputs["start_path"], *inputs["keyframe_paths"]]
            for index, path in enumerate(paths):
                preparing = {"clip_index": clip["clip_index"], "reference_index": index,
                             "source_path": path, "source_url": inputs["references"][index]["url"]}
                check_current(db, handle)
                if not path:
                    raise ExecutionConflict("VIDEO_REFERENCE_MISSING")
                with Path(path).open("rb") as stream:
                    payload = stream.read(32 * 1024 * 1024 + 1)
                if not payload or len(payload) > 32 * 1024 * 1024:
                    raise ExecutionConflict("VISUAL_REFERENCE_EMPTY_OR_TOO_LARGE")
                preparing["image_sha256"] = hashlib.sha256(payload).hexdigest()
                with Image.open(BytesIO(payload)) as image:
                    extension = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}.get(image.format)
                    if extension is None:
                        raise ExecutionConflict("VISUAL_REFERENCE_FORMAT_UNSUPPORTED")
                    image.verify()
                # verify() checks structure/checksums but does not decode JPEG pixels.
                with Image.open(BytesIO(payload)) as image:
                    image.load()
                frame_index = None
                if run["mode"] == "MULTI_KEYFRAME":
                    frame_index = inputs["keyframes"][index].get("index")
                elif run["mode"] == "FIRST_LAST_FRAME" and index:
                    frame_index = next((frame.get("index") for frame in frames if frame.get("role") == "END"), None)
                reference = validator.VisualReference(clip_index=clip["clip_index"], reference_index=index, payload=payload,
                    source_url=inputs["references"][index]["url"], role="START" if index == 0 else "END" if index == len(paths) - 1 else "KF",
                    keyframe_index=frame_index)
                if reference.sha256 not in artifacts:
                    destination = Path(handle["directory"]) / f"visual-reference-{uuid4().hex}{extension}"
                    with destination.open("xb") as stream:
                        stream.write(payload)
                    artifacts[reference.sha256] = {"path": str(destination), "sha256": reference.sha256, "bytes": len(payload)}
                references.append(reference)
                frozen[key].append({"reference_index": index, "source_path": path, "payload": payload, "sha256": reference.sha256})
    except Exception as error:
        report = {"version": 1, "enabled": True, "decision": "UNKNOWN", "source": source,
                  "status": "operational_error", "artifacts": list(artifacts.values()),
                  "findings": [{"decision": "UNKNOWN", "reason": "VISUAL_REFERENCE_PREPARATION_FAILED",
                                **preparing, "detail": str(error)[:512], "conflicting_fields": [],
                                "recommended_next_action": "REGENERATE_KEYFRAME"}]}
        event = observe(db, handle, "visual-state-preparation-error", report)
        try:
            _write(db, handle, lambda current: current.update(visual_state_validation={**report, "evidence": event["evidence"]}))
        except ExecutionConflict:
            pass
        raise
    # All chosen anchors are observed before building even C1's H3 prompt.
    report = await validator.validate_references(request, references, observer=observer if observer is not None else validator.get_visual_state_observer())
    report.update(source=source, artifacts=list(artifacts.values()))
    event = observe(db, handle, "visual-state-validation", report)
    evidence = event["evidence"]
    _write(db, handle, lambda current: current.update(visual_state_validation={
        **report, "status": "evaluated", "evidence": evidence, "uploads": {},
    }))
    if any(finding["reason"] == "INVALID_CONTRACT" for finding in report["findings"]):
        raise ExecutionConflict("INVALID_VISUAL_STATE_CONTRACT")
    if report["decision"] == "BLOCK":
        reasons = sorted({finding["reason"] for finding in report["findings"] if finding["decision"] == "BLOCK"})
        raise ExecutionConflict("VISUAL_STATE_BLOCKED: " + ", ".join(reasons))
    return selections, frozen, evidence


async def _prepare_actual_handoff(db, shot, handle, video, clip, inputs, frozen, audio, observer):
    from app.services import actual_state_frames, actual_state_handoff, visual_state_validator

    _, data = check_current(db, handle)
    run = data["video_run"]
    predecessor = verified_clip_receipt(run, 1)
    if run["scope"] != "whole_shot" or [item["clip_index"] for item in run["expected"]] != [1, 2]:
        raise ExecutionConflict("HANDOFF_SCOPE_CHANGED")
    if run["clips"]["2"]["submission"] != {"state": "not_submitted"} or run["clips"]["2"]["receipt"] is not None:
        raise ExecutionConflict("HANDOFF_C2_ALREADY_STARTED")
    source = {"run_id": handle["run_id"], "request_hash": handle["request_hash"], "predecessor_receipt": predecessor,
              "original_p0_evidence": data["visual_state_validation"]["evidence"],
              "snapshot_hash": digest(data["execution"]["shot_snapshot"])}
    _write(db, handle, lambda current: current.update(actual_state_handoff={
        "version": 1, "status": "preparing", "decision": "HUMAN_REVIEW", "can_submit_c2": False, "source": source,
    }) or {"current_step": "Preparing actual C1 state for C2"})
    directory = Path(handle["directory"]) / f"handoff-tail-{uuid4().hex}"
    tail = await actual_state_frames.extract_tail_window(predecessor["path"], directory, expected_sha256=predecessor["sha256"])
    observe(db, handle, "actual-state-tail", tail)
    current = check_current(db, handle)[1]
    if verified_clip_receipt(current["video_run"], 1) != predecessor:
        raise ExecutionConflict("HANDOFF_PREDECESSOR_CHANGED")
    references = []
    for index, item in enumerate(tail.get("observation_candidates") or []):
        path = Path(item["path"]).resolve()
        if not path.is_relative_to(directory.resolve()) or file_digest(path) != item["sha256"]:
            raise ExecutionConflict("HANDOFF_FRAME_NOT_OWNED_OR_CHANGED")
        references.append(visual_state_validator.VisualReference(2, index, path.read_bytes(), video.local_path_to_url(str(path)), "START"))
    if tail.get("can_use") and (not references or tail["selected"]["sha256"] not in {ref.sha256 for ref in references}
            or tail["last_frame_index"] not in {item["frame_index"] for item in tail["observation_candidates"]}):
        raise ExecutionConflict("HANDOFF_TAIL_EVIDENCE_INCOMPLETE")
    if tail.get("can_use") and (not Path(tail["selected"]["path"]).resolve().is_relative_to(directory.resolve())
            or not any(all(item[field] == tail["selected"][field] for field in ("path", "sha256", "frame_index", "pts"))
                       for item in tail["observation_candidates"])):
        raise ExecutionConflict("HANDOFF_SELECTED_FRAME_NOT_OWNED")
    snapshot = deepcopy(data["execution"]["shot_snapshot"])
    snapshot.update(characters=video.safe_json_list(snapshot.get("characters")), props=video.safe_json_list(snapshot.get("props")))
    report = await actual_state_handoff.resolve_handoff(
        visual_request=run["request"]["visual_state_validation"], snapshot=snapshot, expected_clips=run["expected"],
        original_validation=data["visual_state_validation"], tail_evidence=tail, references=references, observer=observer)
    report.update(source=source, status="resolved", post_handoff_status="NOT_MEASURED")
    event = observe(db, handle, "actual-state-handoff", report)
    _write(db, handle, lambda current: current.update(actual_state_handoff={**report, "evidence": event["evidence"], "uploads": {}}))
    if not report["can_submit_c2"]:
        raise ExecutionConflict("ACTUAL_STATE_HANDOFF_" + report["decision"] + ": " + ", ".join(item["reason"] for item in report["issues"]))
    current = check_current(db, handle)[1]
    if verified_clip_receipt(current["video_run"], 1) != predecessor:
        raise ExecutionConflict("HANDOFF_PREDECESSOR_CHANGED")
    selected = tail["selected"]
    selected_ref = next(ref for ref in references if ref.sha256 == selected["sha256"]
                        and ref.source_url == video.local_path_to_url(str(Path(selected["path"]).resolve())))
    if file_digest(selected["path"]) != selected_ref.sha256:
        raise ExecutionConflict("HANDOFF_SELECTED_FRAME_CHANGED")
    effective = deepcopy(inputs)
    trusted = report["trusted_handoff_state"]["confirmed_actual_fields"]
    description = "Validated actual C1 ending frame for C2. Confirmed coarse state: " + json.dumps(trusted, ensure_ascii=False, sort_keys=True)
    effective["keyframes"][0].update(image_url=selected_ref.source_url, description=description)
    effective.update(start_url=selected_ref.source_url, start_path=selected["path"])
    effective["references"][0] = {"label": "C2 actual validated C1 handoff frame", "url": selected_ref.source_url}
    effective_frozen = list(frozen)
    effective_frozen[0] = {"reference_index": 0, "source_path": selected["path"], "payload": selected_ref.payload, "sha256": selected_ref.sha256}
    context = {"version": 1, "source": "actual_state_handoff", "run_id": handle["run_id"], "from_clip": 1, "to_clip": 2,
               "clip_attempt_id": run["clips"]["2"]["attempt_id"],
               "planned_context_hash": video.prompt_digest(video._h3_prompt_context(db, shot, "MULTI_KEYFRAME", clip, bool(audio.get("enabled")))),
               "start_image_url": selected_ref.source_url, "start_image_sha256": selected_ref.sha256,
               "keyframes": effective["keyframes"], "transitions": effective["transitions"], "trusted_state": trusted,
               "canonical_state": report["canonical_state"]["requirements"], "evidence_hash": event["evidence"]["sha256"]}
    _write(db, handle, lambda current: current["actual_state_handoff"].update(
        effective_context=deepcopy(context), effective_context_hash=video.prompt_digest(context)))
    return effective, effective_frozen, event["evidence"], context


async def run_video_execution(db, task_id):
    from app.services import shot_video_service as video
    from app.models.novel import Chapter, Novel, Character
    from app.models.workflow import Workflow
    try:
        claimed = claim_video_execution(db, task_id)
    except (ExecutionConflict, ValueError, TypeError, KeyError) as error:
        db.rollback()
        task = db.query(Task).filter(Task.id == task_id).populate_existing().first()
        if task and task.status == "pending":
            count = db.query(Task).filter(Task.id == task_id, Task.status == "pending", Task.metadata_json == task.metadata_json).update({
                "status": "failed", "error_message": str(error), "current_step": "Video execution rejected",
                "completed_at": datetime.utcnow(),
            }, synchronize_session=False)
            if count == 1:
                db.refresh(task)
                settle_terminated_video(db, task)
                db.commit()
            else:
                db.rollback()
        return
    if claimed is None:
        return
    task, shot, handle = claimed
    heartbeat = asyncio.create_task(_heartbeat(handle, video.SessionLocal))
    clip_index = None
    try:
        _, data = check_current(db, handle)
        run, request = data["video_run"], data["video_run"]["request"]
        mode = run["mode"]
        novel = db.query(Novel).filter(Novel.id == task.novel_id).first()
        chapter = db.query(Chapter).filter(Chapter.id == task.chapter_id, Chapter.novel_id == task.novel_id).first()
        if not novel or not chapter:
            raise ExecutionConflict("VIDEO_TARGET_NOT_FOUND")
        plan = video.safe_json_dict(shot.video_director_plan)
        frames = video._hydrate_plan_keyframes_from_legacy(shot, plan.get("keyframes") or [])
        mutate_private_plan(db, shot, lambda current: {**current, "keyframes": frames})
        appearances = {character.name: character.appearance for character in db.query(Character).filter(
            Character.novel_id == novel.id, Character.name.in_(video.safe_json_list(shot.characters))).all() if character.appearance}
        style, scene_setting, prop_appearances = "", None, {}
        if novel.style_prompt_template_id:
            from app.models.prompt_template import PromptTemplate
            template = db.query(PromptTemplate).filter(PromptTemplate.id == novel.style_prompt_template_id).first()
            style = template.template if template else ""
        if shot.scene:
            from app.models.novel import Scene
            scene = db.query(Scene).filter(Scene.novel_id == novel.id, Scene.name == shot.scene).first()
            scene_setting = scene.setting if scene else None
        if video.safe_json_list(shot.props):
            from app.models.novel import Prop
            prop_appearances = {prop.name: prop.appearance for prop in db.query(Prop).filter(
                Prop.novel_id == novel.id, Prop.name.in_(video.safe_json_list(shot.props))).all() if prop.appearance}
        workflows = {}
        multi = mode == "MULTI_KEYFRAME" and len(video.safe_json_list(plan.get("window_plans"))) > 1
        for spec in run["expected"]:
            workflow = (db.query(Workflow).filter(Workflow.type == spec["workflow_type"], Workflow.is_active == True).first()
                        if multi else db.query(Workflow).filter(Workflow.id == task.workflow_id).first())
            if not workflow:
                raise ExecutionConflict("VIDEO_WORKFLOW_MISSING")
            workflows[str(spec["clip_index"])] = {field: getattr(workflow, field) for field in (
                "id", "type", "name", "workflow_json", "node_mapping", "extension")}
        _write(db, handle, lambda current: current["video_run"].update(workflows=workflows))
        visual_inputs, frozen_images, visual_evidence = {}, {}, None
        handoff_enabled = bool((request.get("actual_state_handoff") or {}).get("enabled"))
        handoff_observer = None
        if handoff_enabled:
            from app.services.actual_state_handoff import validate_reference_slots
            for spec in run["expected"]:
                captured = workflows[str(spec["clip_index"])]
                validate_reference_slots(video.safe_json_dict(captured["workflow_json"]),
                                         video.safe_json_dict(captured["node_mapping"]), spec["selected_frame_count"])
            from app.services.visual_state_validator import get_visual_state_observer
            handoff_observer = get_visual_state_observer()
            if handoff_observer is None:
                report = {"version": 1, "status": "resolved", "decision": "HUMAN_REVIEW", "can_submit_c2": False,
                          "issues": [{"reason": "OBSERVER_NOT_CONFIGURED"}], "post_handoff_status": "NOT_MEASURED"}
                event = observe(db, handle, "actual-state-handoff", report)
                _write(db, handle, lambda current: current.update(actual_state_handoff={**report, "evidence": event["evidence"]}))
                raise ExecutionConflict("ACTUAL_STATE_HANDOFF_HUMAN_REVIEW: OBSERVER_NOT_CONFIGURED")
        if run["request"].get("visual_state_validation") is not None:
            visual_inputs, frozen_images, visual_evidence = await _validate_visual_inputs(
                db, shot, handle, video, plan, frames, run, workflows, multi, observer=handoff_observer)
        for position, spec in enumerate(run["expected"], 1):
            refresh_private_shot(db, shot)
            clip = deepcopy(spec)
            clip_index = clip["clip_index"]
            key = str(clip_index)
            slot = deepcopy(check_current(db, handle)[1]["video_run"]["clips"][key])
            shot._video_clip_attempt_id = slot["attempt_id"]
            workflow = SimpleNamespace(**workflows[key])
            inputs = visual_inputs.get(key) or _video_reference_inputs(
                video, shot, plan, frames, mode, multi, clip, video.safe_json_dict(workflow.node_mapping))
            effective_context = None
            clip_frozen = frozen_images.get(key)
            clip_visual_evidence, visual_root = visual_evidence, "visual_state_validation"
            if handoff_enabled and clip_index == 2:
                # Route metadata is part of the base H3 context. Normalize it
                # before hashing, exactly as the ordinary per-clip path does.
                video._update_window_plan(shot, clip_index, {
                    "workflow_type": workflow.type, "workflow_name": workflow.name,
                }, db, task=task)
                audio = video._resolve_audio_drive_for_h3(video.safe_json_dict(shot.video_director_plan), clip, inputs["mapping"])
                inputs, clip_frozen, clip_visual_evidence, effective_context = await _prepare_actual_handoff(
                    db, shot, handle, video, clip, inputs, clip_frozen, audio, handoff_observer)
                visual_root = "actual_state_handoff"
            mapping, keyframes, transitions = inputs["mapping"], inputs["keyframes"], inputs["transitions"]
            start_url, start_path, keyframe_paths = inputs["start_url"], inputs["start_path"], inputs["keyframe_paths"]
            references = inputs["references"]
            if multi:
                video._update_window_plan(shot, clip_index, {
                    "status": "PROMPT_BUILDING", "workflow_type": workflow.type,
                    "workflow_name": workflow.name, "reference_images": references,
                }, db, task=task)
            audio = video._resolve_audio_drive_for_h3(video.safe_json_dict(shot.video_director_plan), clip, mapping)
            extension = video.safe_json_dict(workflow.extension)
            prompt, gate = await video._build_h3_prompt_for_worker(
                db=db, task=task, novel=novel, shot=shot, selected_mode=mode, clip=clip, workflow=workflow,
                workflow_capability={"max_clip_duration": int(extension.get("max_clip_duration") or extension.get("max_seconds") or 15),
                                     "frame_count": extension.get("frame_count"), "workflow_name": workflow.name},
                start_image_url=start_url, keyframes=keyframes, transitions=transitions, reference_images=references,
                character_appearances=appearances, audio_drive=audio,
                skip_llm_when_prompt_exists=request["skip_llm_when_prompt_exists"],
                **({"effective_context": effective_context} if effective_context is not None else {}),
            )
            check_current(db, handle)
            service = video.ComfyUIService()
            endpoint = service.client.base_url
            service.client = frozen_client(endpoint)
            ack = {}
            bound_images = []

            def images_bound(bindings):
                expected = clip_frozen
                if (len(bindings) != len(expected) or any(
                        binding["reference_index"] != item["reference_index"] or binding["sha256"] != item["sha256"]
                        or binding["bytes"] != len(item["payload"]) for binding, item in zip(bindings, expected))):
                    raise ExecutionConflict("VISUAL_STATE_UPLOAD_BINDING_MISMATCH")
                def save(current):
                    visual = current[visual_root]
                    if visual["evidence"] != clip_visual_evidence or visual["decision"] == "BLOCK":
                        raise ExecutionConflict("VISUAL_STATE_EVIDENCE_CHANGED")
                    visual["uploads"][key] = deepcopy(bindings)
                _write(db, handle, save)
                bound_images.extend(deepcopy(bindings))

            def before_submit(graph):
                gate(graph)
                def prepare(current):
                    if clip_visual_evidence is not None:
                        visual = current[visual_root]
                        if (not bound_images or visual["evidence"] != clip_visual_evidence or visual["uploads"].get(key) != bound_images
                                or any(graph.get(item["node_id"], {}).get("inputs", {}).get(item["field"]) != item["upload"]["filename"]
                                       for item in bound_images)):
                            raise ExecutionConflict("VISUAL_STATE_INPUTS_NOT_BOUND")
                    if effective_context is not None:
                        validate_reference_slots(graph, mapping, clip["selected_frame_count"])
                        if (not current["actual_state_handoff"]["can_submit_c2"] or
                                verified_clip_receipt(current["video_run"], 1) != current["actual_state_handoff"]["source"]["predecessor_receipt"]):
                            raise ExecutionConflict("HANDOFF_PREDECESSOR_CHANGED")
                    item = current["video_run"]["clips"][key]
                    if item["submission"]["state"] != "not_submitted":
                        raise ExecutionConflict("CLIP_ALREADY_SUBMITTED")
                    item.update(state="RUNNING", submission={"state": "submitting", "graph": deepcopy(graph),
                                "graph_hash": digest(graph), "endpoint": endpoint, "output_node": str(mapping.get("video_save_node_id", "1"))})
                    return {"prompt_text": prompt, "reference_images": json.dumps(references, ensure_ascii=False),
                            "current_step": f"Generating clip {position}/{len(run['expected'])}"}
                _write(db, handle, prepare)

            def on_queued(prompt_id, graph):
                ack.update(prompt_id=prompt_id, graph=deepcopy(graph))
                observe(db, handle, "ack", {"clip_index": clip_index, "attempt_id": slot["attempt_id"], **ack})
                def acknowledge(current):
                    item = current["video_run"]["clips"][key]
                    if (not prompt_id or item["submission"]["state"] != "submitting" or item["submission"]["graph"] != graph
                            or any(other["submission"].get("prompt_id") == prompt_id for other in current["video_run"]["clips"].values())):
                        raise ExecutionConflict("INVALID_CLIP_ACK")
                    item["submission"].update(state="acknowledged", prompt_id=prompt_id)
                    return {"comfyui_prompt_id": prompt_id, "workflow_json": json.dumps(graph, ensure_ascii=False)}
                try:
                    _write(db, handle, acknowledge)
                except ExecutionConflict:
                    pass
                video._save_h3_prompt_gate(db, task, gate.validation_record, prompt_id=prompt_id)

            duration = video.contract_clip_duration(clip.get("start_time") or 0, clip.get("end_time") or video._resolved_duration_from_plan(shot, plan))
            result = await service.generate_shot_video_with_workflow(
                prompt=prompt, workflow_json=workflow.workflow_json, node_mapping=mapping, aspect_ratio=novel.aspect_ratio or "16:9",
                character_reference_path=start_path, frame_count=video.legal_h3_frame_count(duration, 25), duration_seconds=duration,
                style=style, character_appearances=appearances, scene_setting=scene_setting, prop_appearances=prop_appearances,
                reference_audio_path=video.url_to_local_path(shot.reference_audio_url) if request["use_reference_audio"] and not audio.get("enabled") else None,
                drive_audio_path=audio.get("drive_audio_path"), final_audio_path=audio.get("final_audio_path"), keyframe_paths=keyframe_paths,
                on_before_submit=before_submit, on_prompt_queued=on_queued,
                **({"frozen_image_inputs": clip_frozen, "on_image_inputs_bound": images_bound} if clip_visual_evidence else {}),
            )
            observe(db, handle, "worker-result", {"clip_index": clip_index, "attempt_id": slot["attempt_id"], "result": result})
            if not result.get("success"):
                video._save_h3_prompt_gate(db, task, gate.validation_record, error=result.get("message") or "Generation failed",
                                          failure_kind=result.get("failure_kind"))
                fail_execution(db, handle, result.get("message") or "Generation failed", clip_index=clip_index)
            if not ack.get("prompt_id"):
                raise ExecutionConflict("CLIP_ACK_UNKNOWN: no automatic resubmission")
            if result.get("prompt_id") not in (None, ack["prompt_id"]):
                raise ExecutionConflict("RESULT_CID_CHANGED")
            # Evidence collection is allowed after lease loss; acceptance below is not.
            proof_slot = {**slot, "submission": {"state": "acknowledged", "prompt_id": ack["prompt_id"], "graph": ack["graph"],
                          "graph_hash": digest(ack["graph"]), "endpoint": endpoint, "output_node": str(mapping.get("video_save_node_id", "1"))}}
            deadline = asyncio.get_running_loop().time() + 30
            while True:
                state = await service.client.get_prompt_state(ack["prompt_id"])
                if state.get("state") not in {"queued", "history"} or asyncio.get_running_loop().time() >= deadline:
                    break
                await asyncio.sleep(1)
            history = state.get("history") or {}
            history_file = capture(handle, "history", history)
            observe(db, handle, "history-observed", {"clip_index": clip_index, "prompt_id": ack["prompt_id"], "history": history_file, "state": state.get("state")})
            url = verify_history(proof_slot, history)
            if result.get("video_url") and _url_identity(url) != _url_identity(result["video_url"]):
                raise ExecutionConflict("RESULT_OUTPUT_CHANGED")
            destination = Path(handle["directory"]) / f"clip-{clip_index}-{slot['attempt_id']}-{uuid4().hex}.mp4"
            path = await video.file_storage.download_video(url=url, novel_id=task.novel_id, chapter_id=task.chapter_id,
                                                          shot_number=clip_index, destination=destination)
            if not path or Path(path) != destination:
                raise ExecutionConflict("ATTEMPT_DOWNLOAD_FAILED")
            raw = {"path": str(path), "sha256": file_digest(path), "bytes": Path(path).stat().st_size}
            observe(db, handle, "download", {"clip_index": clip_index, **raw})
            check_current(db, handle)
            # Audio locking rewrites its input. Keep the downloaded evidence immutable.
            processed = Path(handle["directory"]) / f"processed-{slot['attempt_id']}-{uuid4().hex}.mp4"
            with Path(path).open("rb") as source, processed.open("xb") as target:
                shutil.copyfileobj(source, target)
            path = processed
            from app.services.rendered_subtitles import lock_generated_audio
            await lock_generated_audio(video.file_storage, str(path), clip.get("subtitle_audio_path"), clip.get("subtitle_snapshot"))
            receipt = {"run_id": handle["run_id"], "attempt_id": slot["attempt_id"], "clip_index": clip_index,
                       "prompt_id": ack["prompt_id"], "graph_hash": digest(ack["graph"]), "source_url": url,
                       "path": str(path), "sha256": file_digest(path), "bytes": Path(path).stat().st_size, "raw": raw, "history": history_file}
            observe(db, handle, "output", receipt)
            def accept(current):
                item = current["video_run"]["clips"][key]
                if item["receipt"] is not None or item["submission"] != proof_slot["submission"]:
                    raise ExecutionConflict("CLIP_RECEIPT_OWNERSHIP_CHANGED")
                item.update(state="SUCCEEDED", receipt=receipt)
                return {"progress": int(position / len(run["expected"]) * 80)}
            _write(db, handle, accept)
            fields = {"status": "SUCCEEDED", "video_url": video.local_path_to_url(str(path)), "local_path": str(path),
                      "prompt_id": ack["prompt_id"], "workflow_json": ack["graph"], "source_video_url": url,
                      "generated_at": datetime.utcnow().isoformat(), "generated_by_task_id": task.id,
                      "execution_attempt_id": handle["run_id"], "clip_attempt_id": slot["attempt_id"]}
            if mode == "MULTI_KEYFRAME":
                video._update_window_plan(shot, clip_index, fields, db, task=task)
            else:
                video._update_clip_result(shot, clip, fields, db)
        merge = begin_merge(db, handle)
        if len(merge["manifest"]) == 1:
            output = Path(merge["manifest"][0]["path"])
        else:
            output = Path(handle["directory"]) / f"merge-{merge['token']}-{uuid4().hex}.mp4"
            merged = await video.file_storage.merge_videos([item["path"] for item in merge["manifest"]], str(output))
            observe(db, handle, "merge-output", {"merge": merge, "result": merged, "path": str(output),
                                                "sha256": file_digest(output) if output.is_file() else None})
            if not merged.get("success"):
                raise ExecutionConflict(merged.get("message") or "MERGE_FAILED")
            segments = merged.get("media_segments") or []
            if [(item.get("source_path"), item.get("source_sha256")) for item in segments] != [
                    (item["path"], item["sha256"]) for item in merge["manifest"]]:
                raise ExecutionConflict("MERGE_INPUT_RECEIPT_MISMATCH")
        publish_result(db, handle, merge, output)
    except asyncio.CancelledError:
        fail_execution(db, handle, "VIDEO_WORKER_INTERRUPTED", clip_index=clip_index)
        raise
    except Exception as error:
        fail_execution(db, handle, str(error), clip_index=clip_index)
    finally:
        heartbeat.cancel()
        try:
            await heartbeat
        except asyncio.CancelledError:
            pass
