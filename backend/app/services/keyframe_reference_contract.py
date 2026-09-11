"""Task-owned #09 reference facts, target guards and bounded prompt checks."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import re
import unicodedata
from urllib.parse import urlencode, urlsplit


CONTRACT_KEY = "keyframe_reference_contract"
CONTRACT_VERSION = 1
OBSERVATIONS_KEY = "keyframe_reference_observations"
_TASK_PROJECTIONS = ("type", "shot_id", "chapter_id", "novel_id", "parent_task_id", "comfyui_prompt_id",
                     "prompt_text", "reference_images", "workflow_id", "workflow_name", "workflow_json")


class KeyframeReferenceError(RuntimeError):
    def __init__(self, code, details=""):
        self.code = code
        super().__init__(f"#09 {code}" + (f": {details}" if details else ""))


def json_value(value, expected):
    if value is None or value == "":
        return expected()
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (ValueError, TypeError) as exc:
        raise KeyframeReferenceError("INVALID_SAVED_JSON") from exc
    if not isinstance(parsed, expected):
        raise KeyframeReferenceError("INVALID_SAVED_JSON_TYPE")
    try:
        json.dumps(parsed, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise KeyframeReferenceError("INVALID_SAVED_JSON") from exc
    return deepcopy(parsed)


def digest(value):
    content = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def read_contract(task):
    value = json_value(task.metadata_json, dict).get(CONTRACT_KEY)
    return deepcopy(value) if isinstance(value, dict) and value.get("version") == CONTRACT_VERSION else None


def seal_contract(contract, *, advance=False):
    """Seal an initial record at revision 0, or reseal/advance a staged copy.

    Staged edits retain the last stored token until a successful store/patch.
    This is a JSON integrity/CAS token, not an authenticated signature.
    """
    if (not isinstance(contract, dict) or type(contract.get("version")) is not int
            or contract["version"] != CONTRACT_VERSION or not isinstance(contract.get("attempt_id"), str)
            or not contract["attempt_id"].strip()):
        raise KeyframeReferenceError("CONTRACT_SEAL_INVALID")
    revision = contract.get("storage_revision", 0)
    if type(revision) is not int or revision < 0 or (advance and "storage_revision" not in contract):
        raise KeyframeReferenceError("CONTRACT_SEAL_INVALID")
    value = {key: item for key, item in contract.items() if key != "storage_hash"}
    value["storage_revision"] = revision + int(advance)
    try:
        storage_hash = digest(value)
    except (ValueError, TypeError) as exc:
        raise KeyframeReferenceError("CONTRACT_SEAL_INVALID") from exc
    contract.update(storage_revision=value["storage_revision"], storage_hash=storage_hash)
    return contract


def _validate_storage_seal(contract):
    if (not isinstance(contract, dict) or type(contract.get("storage_revision")) is not int
            or contract["storage_revision"] < 0 or not isinstance(contract.get("storage_hash"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", contract["storage_hash"])):
        raise KeyframeReferenceError("CONTRACT_SEAL_INVALID")
    candidate = deepcopy(contract)
    seal_contract(candidate)
    if candidate["storage_hash"] != contract["storage_hash"]:
        raise KeyframeReferenceError("CONTRACT_SEAL_INVALID")


def _assert_task_projections(task, contract, *, require_submitted=False):
    """Compare Task columns with this stored record, never with staged edits."""
    try:
        target, planned = contract["target"], contract["planned"]
        workflow, prompt, submit = contract.get("workflow", {}), contract["prompt"], contract["submit"]
        identity = {"type": "keyframe_image", "shot_id": target["shot_id"], "chapter_id": target["chapter_id"],
                    "novel_id": planned["novel_id"], "parent_task_id": planned["parent_task_id"]}
        if any(getattr(task, key, None) != value for key, value in identity.items()):
            raise KeyframeReferenceError("TASK_REPLACED")
        if getattr(task, "comfyui_prompt_id", None) != submit.get("prompt_id"):
            raise KeyframeReferenceError("TASK_SUBMISSION_CHANGED")
        expected = {"prompt_text": prompt.get("text"), "workflow_id": workflow.get("id", planned.get("requested_workflow_id")),
                    "workflow_name": workflow.get("name")}
        for key, value in expected.items():
            if getattr(task, key, None) != value:
                raise KeyframeReferenceError("TASK_PROJECTION_CHANGED", key)
        references = reference_images(contract) if contract.get("binding_resolved") else []
        if json_value(getattr(task, "reference_images", None), list) != references:
            raise KeyframeReferenceError("TASK_PROJECTION_CHANGED", "reference_images")
        acknowledged = isinstance(submit.get("prompt_id"), str) and bool(submit["prompt_id"].strip())
        if submit.get("state") in {"attempted", "unknown"} and submit["graph_hash"] != digest(contract["prepared_workflow"]):
            raise KeyframeReferenceError("HISTORY_SUBMISSION_MISMATCH")
        if require_submitted and (not acknowledged or submit.get("state") != "submitted"):
            raise KeyframeReferenceError("SUBMISSION_NOT_CONFIRMED")
        graph_json = getattr(task, "workflow_json", None)
        if acknowledged:
            if submit.get("state") != "submitted" or not graph_json:
                raise KeyframeReferenceError("TASK_PROJECTION_CHANGED", "workflow_json")
            assert_keyframe_graph_matches(json_value(graph_json, dict), contract, code="TASK_PROJECTION_CHANGED")
        elif graph_json not in (None, ""):
            raise KeyframeReferenceError("TASK_PROJECTION_CHANGED", "workflow_json before acknowledgement")
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise KeyframeReferenceError("CONTRACT_PROJECTION_INVALID") from exc


def assert_keyframe_graph_matches(graph, contract, *, code="HISTORY_SUBMISSION_MISMATCH"):
    """Check a candidate against the original v1 digest and full semantic graph.

    This also serves staged Task projections, so it never reseals or recursively
    checks the contract. Persisted consumers must call validate_frozen_contract
    first; this helper alone is not a frozen binding/cache/ownership proof.
    """
    from app.services.keyframe_reference_graph import KeyframeGraphError, semantic_graph_digest
    try:
        prepared = contract["prepared_workflow"]
        if (digest(prepared) != contract["submit"]["graph_hash"]
                or semantic_graph_digest(graph) != semantic_graph_digest(prepared)):
            raise KeyframeReferenceError(code, "workflow_json")
    except (KeyframeGraphError, KeyError, TypeError, AttributeError, ValueError) as exc:
        raise KeyframeReferenceError(code, "workflow_json") from exc


def _checked_contract(task, working):
    saved = read_contract(task)
    if not saved or not isinstance(working, dict) or saved.get("attempt_id") != working.get("attempt_id"):
        raise KeyframeReferenceError("TASK_REPLACED")
    _validate_storage_seal(saved)
    if (type(working.get("storage_revision")) is not int
            or (saved["storage_revision"], saved["storage_hash"]) != (working.get("storage_revision"), working.get("storage_hash"))):
        raise KeyframeReferenceError("CONTRACT_STALE")
    _assert_task_projections(task, saved)
    for section, fields in (("target", ("shot_id", "chapter_id")), ("planned", ("novel_id", "parent_task_id"))):
        if not isinstance(working.get(section), dict) or any(working[section].get(key) != saved[section][key] for key in fields):
            raise KeyframeReferenceError("TASK_REPLACED")
    return saved


def _task_cas_conditions(db, task, *, terminal=False):
    from app.models.task import Task
    from sqlalchemy.orm import aliased
    # Construct before either UPDATE; later ORM refreshes must not change the guard.
    conditions = [Task.id == task.id, Task.status == task.status, Task.metadata_json == task.metadata_json]
    conditions.extend(getattr(Task, key) == getattr(task, key) for key in _TASK_PROJECTIONS)
    if task.parent_task_id:
        parent = aliased(Task)
        parent_query = db.query(parent.id).filter(parent.id == task.parent_task_id)
        if terminal:
            # Error/ACK evidence may close a child after its parent stops; it may
            # not race a further parent-state change or revive either task.
            saved_parent = db.query(Task).filter(Task.id == task.parent_task_id).populate_existing().first()
            conditions.append(parent_query.filter(parent.status == saved_parent.status).exists() if saved_parent else ~parent_query.exists())
        else:
            conditions.append(parent_query.filter(parent.status.in_(["pending", "running"])).exists())
    return conditions


def _prepare_contract_write(task, saved, working, updates):
    from types import SimpleNamespace
    next_contract = deepcopy(working)
    old_submit, new_submit = saved["submit"], next_contract["submit"]
    if old_submit.get("prompt_id") != new_submit.get("prompt_id"):
        if (old_submit.get("prompt_id") is not None or old_submit.get("state") != "attempted"
                or new_submit.get("state") != "submitted" or not isinstance(new_submit.get("prompt_id"), str)
                or not new_submit["prompt_id"].strip() or updates.get("comfyui_prompt_id") != new_submit["prompt_id"]
                or not old_submit.get("graph_hash") or old_submit["graph_hash"] != new_submit.get("graph_hash")):
            raise KeyframeReferenceError("TASK_SUBMISSION_CHANGED")
    projected = {key: getattr(task, key) for key in _TASK_PROJECTIONS}
    projected.update(updates)
    _assert_task_projections(SimpleNamespace(**projected), next_contract)
    seal_contract(next_contract, advance=True)
    return next_contract


def reference_intent(keyframe):
    mode = keyframe.get("reference_mode", "auto_select")
    url = keyframe.get("reference_image_url")
    if not isinstance(mode, str) or mode not in {"auto_select", "custom", "none"} or (url is not None and not isinstance(url, str)):
        raise KeyframeReferenceError("INVALID_REFERENCE_MODE")
    if mode == "custom" and not url:
        raise KeyframeReferenceError("CUSTOM_REFERENCE_MISSING")
    return {"mode": mode, "url": url or None,
            "selection": "none" if mode == "none" else "custom" if mode == "custom" else "fixed_auto" if url else "dynamic_auto"}


def _frame_state(frame, index):
    return {"index": frame.get("index", frame.get("plan_keyframe_index", index)),
            "role": frame.get("role"), "time_seconds": frame.get("time_seconds"),
            "description": frame.get("description") or ""}


def snapshot_target(shot, frame_index):
    frames = json_value(shot.keyframes, list)
    if type(frame_index) is not int or not 0 <= frame_index < len(frames) or not isinstance(frames[frame_index], dict):
        raise KeyframeReferenceError("TARGET_NOT_FOUND")
    frame = frames[frame_index]
    plan = json_value(shot.video_director_plan, dict)
    plan_index = frame.get("plan_keyframe_index")
    planned = None
    if plan_index is not None:
        matches = [item for item in plan.get("keyframes", []) if isinstance(item, dict) and item.get("index") == plan_index]
        if len(matches) != 1:
            raise KeyframeReferenceError("PLAN_TARGET_NOT_UNIQUE")
        planned = matches[0]
        if planned.get("role") == "START":
            raise KeyframeReferenceError("START_USES_PRIMARY_STORYBOARD")
    previous = None
    if frame_index:
        previous_frame = frames[frame_index - 1]
        if not isinstance(previous_frame, dict):
            raise KeyframeReferenceError("INVALID_PREVIOUS_STATE")
        previous = _frame_state(previous_frame, frame_index - 1)
        previous_index = previous_frame.get("plan_keyframe_index")
        if previous_index is not None:
            matches = [item for item in plan.get("keyframes", []) if isinstance(item, dict) and item.get("index") == previous_index]
            if len(matches) != 1:
                raise KeyframeReferenceError("PREVIOUS_PLAN_NOT_UNIQUE")
            previous = _frame_state(matches[0], previous_index)
    draft = {"legacy": {"present": "prompt_text" in frame, "value": frame.get("prompt_text")},
             "plan": {"present": planned is not None and "prompt_text" in planned,
                      "value": planned.get("prompt_text") if planned else None}}
    return {
        "shot_id": shot.id, "chapter_id": shot.chapter_id, "frame_index": frame_index,
        "legacy_frame_index": frame.get("frame_index"), "plan_keyframe_index": plan_index,
        "legacy_state": _frame_state(frame, frame_index),
        "current_state": _frame_state(planned or frame, plan_index if plan_index is not None else frame_index),
        "previous_state_text": previous, "reference_intent": reference_intent(frame),
        "shot_state": {**{name: getattr(shot, name, None) for name in ("description", "video_description", "scene", "duration", "continuity_mode")},
                       "characters": json_value(shot.characters, list), "props": json_value(shot.props, list),
                       "dialogues": json_value(shot.dialogues, list)},
        "images": {"legacy": frame.get("image_url"), "plan": planned.get("image_url") if planned else None},
        "owners": {"legacy": frame.get("image_task_id"), "plan": planned.get("image_task_id") if planned else None},
        "draft": draft,
    }


def target_semantics(target):
    return {key: value for key, value in target.items() if key not in {"images", "owners", "draft"}}


def assert_target(shot, task_id, contract, *, claiming=False):
    if contract.get("execution_purpose") == "benchmark" and (
        getattr(shot, "_execution_purpose", None) != "benchmark"
        or getattr(shot, "_execution_task_id", None) != task_id
        or getattr(shot, "_execution_attempt_id", None) != contract.get("execution_attempt_id")
    ):
        raise KeyframeReferenceError("BENCHMARK_TARGET_NOT_PRIVATE")
    target = contract["target"]
    current = snapshot_target(shot, target["frame_index"])
    if target_semantics(current) != target_semantics(target) or current["images"] != target["images"]:
        raise KeyframeReferenceError("TARGET_CHANGED")
    expected_owners = target["owners"] if claiming else {"legacy": task_id, "plan": task_id if target["plan_keyframe_index"] is not None else None}
    if current["owners"] != expected_owners:
        raise KeyframeReferenceError("TARGET_OWNER_CHANGED")
    if current["draft"] != contract.get("draft", target["draft"]):
        raise KeyframeReferenceError("PROMPT_EDITED")
    return current


def assert_task_active(db, task, contract, *, statuses=("running",)):
    from app.models.task import Task
    if task.status not in statuses or task.type != "keyframe_image":
        raise KeyframeReferenceError("TASK_NOT_ACTIVE", task.status)
    saved = _checked_contract(task, contract)
    if task.parent_task_id:
        parent = db.query(Task).filter(Task.id == task.parent_task_id).populate_existing().first()
        if not parent or parent.status not in {"pending", "running"}:
            raise KeyframeReferenceError("PARENT_NOT_ACTIVE")
    return saved


def store_contract(db, task_id, contract, *, statuses=("running",), terminal=False, **fields):
    """Merge only this task namespace; never revive a terminal/deleted attempt."""
    from app.models.task import Task
    if isinstance(contract, dict) and contract.get("execution_purpose") == "benchmark":
        from app.models.shot import Shot
        if any(isinstance(item, Shot) for item in (*db.new, *db.dirty, *db.deleted)):
            raise KeyframeReferenceError("PRODUCTION_SHOT_DIRTY")
    for _ in range(3):
        task = db.query(Task).filter(Task.id == task_id).populate_existing().first()
        if not task:
            raise KeyframeReferenceError("TASK_REMOVED")
        saved = _checked_contract(task, contract)
        purpose = json_value(task.metadata_json, dict).get("execution_purpose", "production")
        if purpose not in ("production", "benchmark") or purpose != saved.get("execution_purpose", "production") or purpose != contract.get("execution_purpose", "production"):
            raise KeyframeReferenceError("EXECUTION_PURPOSE_CHANGED")
        if purpose == "benchmark":
            from app.services.task_execution import execution_record
            execution = execution_record(task)
            if execution["attempt_id"] != saved.get("execution_attempt_id") or execution["attempt_id"] != contract.get("execution_attempt_id"):
                raise KeyframeReferenceError("EXECUTION_ATTEMPT_CHANGED")
        if task.status == "completed":
            return False
        if not terminal:
            assert_task_active(db, task, contract, statuses=statuses)
        updates = dict(fields)
        if task.status not in {"pending", "running"}:
            updates = {key: value for key, value in updates.items() if key in {"result_url", "comfyui_prompt_id", "workflow_json"}}
        next_contract = _prepare_contract_write(task, saved, contract, updates)
        conditions = _task_cas_conditions(db, task, terminal=terminal)
        original_metadata = task.metadata_json
        metadata = json_value(original_metadata, dict)
        metadata[CONTRACT_KEY] = next_contract
        updates["metadata_json"] = json.dumps(metadata, ensure_ascii=False, allow_nan=False)
        try:
            updated = db.query(Task).filter(*conditions).update(updates, synchronize_session=False)
            if updated == 1:
                db.commit()
        except BaseException:
            db.rollback()
            raise
        if updated == 1:
            db.refresh(task)
            contract.clear()
            contract.update(next_contract)
            return True
        db.rollback()
    raise KeyframeReferenceError("TASK_WRITE_CONFLICT")


def patch_target(db, task_id, contract, *, claiming=False, prompt=None, image_url=None, ai_call=None):
    """Atomically CAS both keyframe representations and the task evidence."""
    from app.models.shot import Shot
    from app.models.task import Task
    if isinstance(contract, dict) and contract.get("execution_purpose") == "benchmark" and any(isinstance(item, Shot) for item in (*db.new, *db.dirty, *db.deleted)):
        raise KeyframeReferenceError("PRODUCTION_SHOT_DIRTY")
    for _ in range(3):
        task = db.query(Task).filter(Task.id == task_id).populate_existing().first()
        if not task:
            raise KeyframeReferenceError("TASK_REMOVED")
        saved = _checked_contract(task, contract)
        purpose = json_value(task.metadata_json, dict).get("execution_purpose", "production")
        if purpose not in ("production", "benchmark") or purpose != saved.get("execution_purpose", "production") or purpose != contract.get("execution_purpose", "production"):
            raise KeyframeReferenceError("EXECUTION_PURPOSE_CHANGED")
        benchmark = purpose == "benchmark"
        if task.status == "completed" and image_url and saved.get("result", {}).get("attachment") == ("archived" if benchmark else "attached"):
            return False
        assert_task_active(db, task, contract, statuses=("pending",) if claiming else ("running",))
        if benchmark:
            from app.services.task_execution import execution_record, load_execution_shot
            execution = execution_record(task)
            if execution["attempt_id"] != saved.get("execution_attempt_id") or execution["attempt_id"] != contract.get("execution_attempt_id"):
                raise KeyframeReferenceError("EXECUTION_ATTEMPT_CHANGED")
            if any(isinstance(item, Shot) for item in (*db.new, *db.dirty, *db.deleted)):
                raise KeyframeReferenceError("PRODUCTION_SHOT_DIRTY")
            shot = load_execution_shot(task)
        else:
            shot = db.query(Shot).filter(Shot.id == task.shot_id).populate_existing().first()
        if not shot:
            raise KeyframeReferenceError("TARGET_NOT_FOUND")
        assert_target(shot, task.id, contract, claiming=claiming)
        task_conditions = _task_cas_conditions(db, task)
        shot_conditions = [Shot.id == contract["target"]["shot_id"], Shot.chapter_id == contract["target"]["chapter_id"]]
        shot_conditions.extend(getattr(Shot, key) == getattr(shot, key) for key in contract["target"]["shot_state"])
        old_frames, old_plan, old_revision, old_metadata = shot.keyframes, shot.video_director_plan, shot.video_director_plan_revision, task.metadata_json
        frames, plan = json_value(old_frames, list), json_value(old_plan, dict)
        frame = frames[contract["target"]["frame_index"]]
        plan_index = contract["target"]["plan_keyframe_index"]
        planned = next((item for item in plan.get("keyframes", []) if isinstance(item, dict) and item.get("index") == plan_index), None) if plan_index is not None else None
        next_contract = deepcopy(contract)
        if claiming:
            frame["image_task_id"] = task.id
            if planned is not None:
                planned["image_task_id"] = task.id
        if prompt is not None:
            if next_contract.get("prompt", {}).get("text", prompt) != prompt:
                raise KeyframeReferenceError("PROMPT_BINDING_MISMATCH")
            next_contract.setdefault("prompt", {}).update(text=prompt, text_hash=digest(prompt))
            frame["prompt_text"] = prompt
            if planned is not None:
                planned["prompt_text"] = prompt
            next_contract["draft"] = {"legacy": {"present": True, "value": prompt},
                                      "plan": {"present": planned is not None, "value": prompt if planned is not None else None}}
        if image_url is not None:
            frame.update({"image_url": image_url, "image_task_id": task.id})
            if planned is not None:
                frame.update({key: planned.get(key) for key in ("description", "role", "time_seconds")})
                planned.update({"image_url": image_url, "image_task_id": task.id})
            next_contract.update({"phase": "completed", "result": {"url": image_url, "attachment": "archived" if benchmark else "attached"}})
        if ai_call is not None:
            # The unchanged shared formatter is used only on a fresh local copy.
            from types import SimpleNamespace
            from app.services.video_director_ai import append_video_ai_call
            plan = append_video_ai_call(SimpleNamespace(video_director_plan=plan), ai_call)
        shot_fields = {"keyframes": json.dumps(frames, ensure_ascii=False)}
        if plan != json_value(old_plan, dict):
            shot_fields.update(video_director_plan=json.dumps(plan, ensure_ascii=False), video_director_plan_revision=int(old_revision or 0) + 1)
        task_fields = {}
        if prompt is not None:
            task_fields["prompt_text"] = prompt
        if image_url is not None:
            task_fields.update(status="completed", progress=100, result_url=image_url, error_message=None, current_step="Completed", completed_at=datetime.utcnow())
        next_contract = _prepare_contract_write(task, saved, next_contract, task_fields)
        metadata = json_value(old_metadata, dict)
        metadata[CONTRACT_KEY] = next_contract
        if benchmark:
            execution["working_shot"].update(shot_fields)
            execution["revision"] += 1
            if image_url is not None:
                execution["result"] = deepcopy(next_contract["result"])
            metadata["execution"] = execution
        task_fields["metadata_json"] = json.dumps(metadata, ensure_ascii=False, allow_nan=False)
        try:
            count = 1 if benchmark else db.query(Shot).filter(*shot_conditions, Shot.keyframes == old_frames, Shot.video_director_plan == old_plan,
                                                             Shot.video_director_plan_revision == old_revision).update(shot_fields, synchronize_session=False)
            changed = db.query(Task).filter(*task_conditions).update(task_fields, synchronize_session=False) if count == 1 else 0
            if count == changed == 1:
                db.commit()
        except BaseException:
            db.rollback()
            raise
        if count == changed == 1:
            db.refresh(task)
            if not benchmark:
                db.refresh(shot)
            contract.clear()
            contract.update(next_contract)
            return True
        db.rollback()
    raise KeyframeReferenceError("TARGET_WRITE_CONFLICT")


def record_contract_observation(db, task_id, working_contract, error, *, artifact_url=None):
    """Append compact conflict evidence only; never repair or replace Task facts.

    Returns True on append, False if the Task was removed. The working record and
    stored seal are unchanged. Malformed metadata and exhausted CAS fail closed.
    """
    from app.models.task import Task
    working = working_contract if isinstance(working_contract, dict) else {}
    submit = working.get("submit") if isinstance(working.get("submit"), dict) else {}
    observation = {"at": datetime.utcnow().isoformat() + "Z", "attempt_id": working.get("attempt_id") if isinstance(working.get("attempt_id"), str) else None,
                   "expected_storage_revision": working.get("storage_revision") if type(working.get("storage_revision")) is int else None,
                   "expected_prompt_id": submit.get("prompt_id") if isinstance(submit.get("prompt_id"), str) else None,
                   "code": getattr(error, "code", type(error).__name__), "reason": str(error)[:1024]}
    if artifact_url is not None:
        observation["artifact_url"] = artifact_url
    for _ in range(3):
        task = db.query(Task).filter(Task.id == task_id).populate_existing().first()
        if not task:
            return False
        if task.type != "keyframe_image":
            raise KeyframeReferenceError("TASK_REPLACED")
        original = task.metadata_json
        metadata = json_value(original, dict)
        observations = metadata.setdefault(OBSERVATIONS_KEY, [])
        if not isinstance(observations, list):
            raise KeyframeReferenceError("INVALID_OBSERVATION_HISTORY")
        observations.append(observation)
        try:
            count = db.query(Task).filter(Task.id == task_id, Task.type == task.type, Task.status == task.status,
                                          Task.metadata_json == original).update(
                {"metadata_json": json.dumps(metadata, ensure_ascii=False, allow_nan=False)}, synchronize_session=False,
            )
            if count == 1:
                db.commit()
        except BaseException:
            db.rollback()
            raise
        if count == 1:
            db.refresh(task)
            return True
        db.rollback()
    raise KeyframeReferenceError("OBSERVATION_WRITE_CONFLICT")


def reference_manifest(contract):
    if not contract.get("binding_resolved"):
        raise KeyframeReferenceError("REFERENCE_NOT_BOUND")
    resolved, binding = contract.get("resolved"), contract.get("binding")
    if resolved is None:
        if binding is not None or contract.get("planned", {}).get("intent", {}).get("mode") != "none":
            raise KeyframeReferenceError("BINDING_MISMATCH")
        return []
    if (not isinstance(resolved, dict) or not isinstance(binding, dict)
            or not isinstance(resolved.get("sha256"), str) or not re.fullmatch(r"[0-9a-fA-F]{64}", resolved["sha256"])
            or binding.get("payload_sha256") != resolved["sha256"] or not binding.get("uploaded_filename")):
        raise KeyframeReferenceError("REFERENCE_NOT_BOUND")
    return [{"picture_index": 1, "type": resolved["source_kind"], "role": "EDIT_BASE",
             "label": resolved["label"], "source_keyframe_index": resolved.get("source_keyframe_index")}]


def reference_images(contract):
    manifest = reference_manifest(contract)
    return [{"label": manifest[0]["label"], "url": contract["resolved"]["url"]}] if manifest else []


def reference_cache_fingerprint(contract):
    """Canonical #09 cache key; usable on staged bound records before publication."""
    try:
        if (type(contract["version"]) is not int or contract["version"] != CONTRACT_VERSION
                or not isinstance(contract["context"], dict) or not contract["context"]
                or not isinstance(contract["llm_config"], dict) or not contract["llm_config"]):
            raise KeyframeReferenceError("CONTRACT_PROOF_INVALID", "cache context")
        resolved = contract["resolved"]
        reference = {key: resolved[key] for key in ("source_kind", "url", "sha256", "source_keyframe_index")} if resolved is not None else None
        workflow_hash, template_hash = contract["workflow"]["contract_hash"], contract["template"]["hash"]
        if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in (workflow_hash, template_hash)):
            raise KeyframeReferenceError("CONTRACT_PROOF_INVALID", "cache hashes")
        return digest({"version": CONTRACT_VERSION, "context": contract["context"], "reference": reference,
                       "workflow": workflow_hash, "template": template_hash, "llm_config": contract["llm_config"]})
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise KeyframeReferenceError("CONTRACT_PROOF_INVALID", "cache inputs") from exc


def semantic_reference_cache_fingerprint(contract, *, graph=None):
    """Derive a comparison key without replacing any persisted v1 evidence.

    Verify saved records with validate_frozen_contract before calling. A current
    bound, pre-prompt record can supply the worker's already prepared graph; its
    legacy stable hash must still match. Only the workflow component is folded.
    """
    from app.services.keyframe_reference_graph import (
        KeyframeGraphError, semantic_stable_graph_fingerprint, stable_graph_fingerprint,
    )
    try:
        graph = contract["prepared_workflow"] if graph is None else graph
        workflow = contract["workflow"]
        mapping = workflow["node_mapping"]
        if workflow["contract_hash"] != stable_graph_fingerprint(graph, mapping):
            raise KeyframeReferenceError("WORKFLOW_PROOF_INVALID")
        if contract["prompt"]["cache_fingerprint"] != reference_cache_fingerprint(contract):
            raise KeyframeReferenceError("CACHE_PROOF_INVALID")
        return reference_cache_fingerprint({**contract, "workflow": {
            **workflow, "contract_hash": semantic_stable_graph_fingerprint(graph, mapping),
        }})
    except (KeyframeGraphError, KeyError, TypeError, AttributeError, ValueError) as exc:
        raise KeyframeReferenceError("CACHE_PROOF_INVALID", "semantic graph inputs") from exc


def validate_frozen_contract(contract, task=None, *, require_submitted=False):
    """Recompute persisted #09 evidence and return the actual graph inspection.

    No current workflow, source URL, database or network lookup is performed.
    Call on sealed persisted records, not uncommitted staged working changes.
    """
    _validate_storage_seal(contract)
    from app.services.keyframe_reference_graph import (
        KeyframeGraphError, stable_graph_fingerprint, validate_keyframe_graph,
    )
    try:
        target, planned = contract["target"], contract["planned"]
        if (any(not isinstance(value, str) or not value.strip() for value in (target["shot_id"], target["chapter_id"], planned["novel_id"]))
                or type(target["frame_index"]) is not int or target["frame_index"] < 0
                or (planned["parent_task_id"] is not None and not isinstance(planned["parent_task_id"], str))):
            raise KeyframeReferenceError("CONTRACT_PROOF_INVALID", "target identity")
        if contract["binding_resolved"] is not True:
            raise KeyframeReferenceError("REFERENCE_NOT_BOUND")
        resolved, binding = contract["resolved"], contract["binding"]
        manifest = reference_manifest(contract)
        source = resolved["source_kind"] if resolved is not None else "NONE"
        count = int(resolved is not None)
        if count:
            if (source not in {"PRIMARY_STORYBOARD", "PREVIOUS_KEYFRAME", "CUSTOM_REFERENCE", "SAVED_REFERENCE"}
                    or contract["planned"]["intent"]["mode"] == "none"
                    or any(not isinstance(resolved[key], str) or not resolved[key].strip() for key in ("url", "label"))
                    or type(resolved["size"]) is not int or resolved["size"] <= 0
                    or type(binding["payload_size"]) is not int or binding["payload_size"] != resolved["size"]
                    or type(binding["picture_index"]) is not int or binding["picture_index"] != 1
                    or binding["field"] != "image" or type(binding["output_slot"]) is not int or binding["output_slot"] != 0):
                raise KeyframeReferenceError("BINDING_MISMATCH")
            source_index = resolved["source_keyframe_index"]
            if ((source == "PREVIOUS_KEYFRAME" and (type(source_index) is not int or source_index < 0))
                    or (source != "PREVIOUS_KEYFRAME" and source_index is not None)):
                raise KeyframeReferenceError("BINDING_MISMATCH", "source keyframe index")
        if (contract["manifest"] != manifest
                or contract["frozen_binding_hash"] != digest({"resolved": resolved, "binding": binding, "manifest": manifest})):
            raise KeyframeReferenceError("FROZEN_BINDING_CHANGED")
        template, workflow, prompt, submit = contract["template"], contract["workflow"], contract["prompt"], contract["submit"]
        if (not isinstance(template["text"], str) or not template["text"].strip()
                or template["hash"] != digest(template["text"]) or template["type"] != "keyframe_image_prompt"):
            raise KeyframeReferenceError("TEMPLATE_PROOF_INVALID")
        if (not isinstance(workflow["id"], str) or not workflow["id"].strip()
                or not isinstance(workflow["name"], str) or not workflow["name"].strip()
                or workflow["type"] not in {"keyframe_image", "shot"}):
            raise KeyframeReferenceError("WORKFLOW_PROOF_INVALID")
        validation = validate_reference_prompt(prompt["text"], source)
        if prompt["text_hash"] != digest(prompt["text"]) or prompt["validation"] != validation:
            raise KeyframeReferenceError("PROMPT_PROOF_INVALID")
        graph, mapping = contract["prepared_workflow"], workflow["node_mapping"]
        inspection = validate_keyframe_graph(graph, mapping, reference_count=count, expected_prompt=prompt["text"],
                                            expected_filename=binding["uploaded_filename"] if count else None)
        if count and binding["node_id"] != inspection["reference_node_id"]:
            raise KeyframeReferenceError("BINDING_MISMATCH", "reference node")
        if (workflow["output_node_id"] != inspection["save_image_node_id"] or workflow["family"] != inspection["family"]
                or workflow["contract_hash"] != stable_graph_fingerprint(graph, mapping)):
            raise KeyframeReferenceError("WORKFLOW_PROOF_INVALID")
        if contract["validation"].get("passed") is not True or contract["validation"].get("graph") != inspection:
            raise KeyframeReferenceError("GRAPH_PROOF_INVALID")
        if prompt["cache_fingerprint"] != reference_cache_fingerprint(contract):
            raise KeyframeReferenceError("CACHE_PROOF_INVALID")
        state, prompt_id = submit["state"], submit.get("prompt_id")
        if require_submitted or state == "submitted" or prompt_id is not None:
            if state != "submitted" or not isinstance(prompt_id, str) or not prompt_id.strip():
                raise KeyframeReferenceError("SUBMISSION_NOT_CONFIRMED")
        elif state not in {"not_submitted", "attempted", "unknown"}:
            raise KeyframeReferenceError("SUBMISSION_NOT_CONFIRMED")
        if state != "not_submitted":
            assert_keyframe_graph_matches(graph, contract)
        if task is not None:
            _checked_contract(task, contract)
            _assert_task_projections(task, contract, require_submitted=require_submitted)
        return inspection
    except KeyframeGraphError as exc:
        raise KeyframeReferenceError("GRAPH_PROOF_INVALID", exc.code) from exc
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise KeyframeReferenceError("CONTRACT_PROOF_INVALID", "missing or malformed proof") from exc


# This grammar concerns references only, not camera language or visual quality.
_ZH_NUMBER = r"[\u96f6\u3007\u4e00\u4e8c\u4e24\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\u5343]+"
_CARDINALS = "zero one two three four five six seven eight nine ten".split()
_ORDINALS = "first second third fourth fifth sixth seventh eighth ninth tenth".split()
_NUMBER = (r"(?:[0-9]+(?:st|nd|rd|th)?|" + _ZH_NUMBER + r"|(?<![a-z])(?:"
           + "|".join(_CARDINALS + _ORDINALS) + r")(?![a-z]))")
_INDEX = _NUMBER + r"(?![0-9a-z\u96f6\u3007\u4e00\u4e8c\u4e24\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\u5343])"
_COUNT_UNIT = r"(?:people\b|persons?\b|characters?\b|seconds?\b|chairs?\b|lights?\b|\u4eba(?!\u7269)|\u4e2a|\u540d|\u4f4d|\u79d2|\u628a|\u76cf)"
_LIST_SEPARATOR = r"\s*(?:[/,\u3001]|\b(?:and|or|nor)\b|\u548c|\u6216|\u53ca)\s*"
_INDEX_LIST = _INDEX + "(?:" + _LIST_SEPARATOR + _INDEX + r"(?!\s*" + _COUNT_UNIT + "))*"
_ZH_IMAGE = r"(?:(?:\u5408\u5e76\u89d2\u8272|\u89d2\u8272|\u4eba\u7269|\u573a\u666f|\u9053\u5177|\u81ea\u5b9a\u4e49|\u8f93\u5165)?(?:\u53c2\u8003)?(?:\u56fe\u7247|\u56fe\u50cf|\u56fe)|\u5e95\u56fe)"
_EN_IMAGE = r"(?:(?:reference|input)\s+)?(?:images?|pictures?)\b"
_NUMBER_REF = (
    r"(?<![a-z])(?:(?:reference|input)\s+)?(?:pictures?|images?|ref(?:erence)?s?)\s*#?\s*" + _INDEX_LIST + "|"
    + _ZH_IMAGE + r"\s*(?!" + _NUMBER + r"\s*" + _COUNT_UNIT + ")" + _INDEX_LIST + "|"
    r"\u7b2c\s*" + _INDEX + r"(?:\s*\u5f20?" + _LIST_SEPARATOR + r"\u7b2c?\s*" + _INDEX + r")*\s*\u5f20\s*" + _ZH_IMAGE + "|"
    r"(?<![a-z])(?:[0-9]+(?:st|nd|rd|th)|" + "|".join(_ORDINALS) + r")(?:" + _LIST_SEPARATOR
    + r"(?:[0-9]+(?:st|nd|rd|th)|" + "|".join(_ORDINALS) + r"))*\s+" + _EN_IMAGE
)
_PREVIOUS_ZH = r"(?:\u4e0a\u4e00|\u524d\u4e00)(?:\u4e2a)?(?:\u5173\u952e)?\u5e27"
_PREVIOUS_EN = r"(?<![a-z])previous\s+(?:keyframe|frame)"
_PREVIOUS = (_PREVIOUS_ZH + r"(?:\s*(?:\u56fe\u7247|\u56fe|\u753b\u9762))?|"
             + _PREVIOUS_EN + r"(?:\s+(?:image|picture))?")
_PRIMARY = r"\u4e3b\u5206\u955c(?:\s*START)?\s*(?:\u53c2\u8003)?\u56fe|(?<![a-z])primary\s+(?:storyboard|shot)(?:\s+(?:image|picture))?|(?<![a-z])storyboard\s+(?:image|picture)"
_ASSET = (r"(?:\u5408\u5e76\u89d2\u8272|\u89d2\u8272\u5408\u5e76|\u89d2\u8272|\u4eba\u7269|\u573a\u666f|\u9053\u5177)(?:\u6b63\u5f0f)?(?:\u53c2\u8003)?(?:\u56fe\u7247|\u56fe\u50cf|\u56fe)|"
          r"(?<![a-z])(?:(?:merged|formal|official)\s+)*(?:character|scene|prop)\s+(?:(?:formal|official|reference)\s+)*(?:image|picture|sheet)s?\b")
_GENERIC_REFERENCE = (r"(?:(?:\u672c\u6b21(?:\u7f16\u8f91)?|\u81ea\u5b9a\u4e49|\u5df2\u56fa\u5b9a)?\u53c2\u8003|\u8f93\u5165)(?:\u56fe\u7247|\u56fe\u50cf|\u56fe)|"
                      r"(?<![a-z])(?:(?:custom|fixed|saved)\s+)?(?:reference|input|uploaded)\s+(?:image|picture)s?\b")
# Only these adjacent text qualifiers exempt a previous-state phrase. Never
# consume its description: it can contain a later, affirmative image claim.
_PLANNED_TEXT = re.compile(
    _PREVIOUS_ZH + r"(?:\u7684)?(?:\u6587\u5b57|\u6587\u672c|\u89c4\u5212|\u63cf\u8ff0)|"
    + _PREVIOUS_EN + r"(?:'s)?\s+(?:planned\s+)?(?:text(?:-only)?|description|planning)\b", re.IGNORECASE,
)
_TERM = "(?:" + "|".join((_NUMBER_REF, _PREVIOUS, _PRIMARY, _ASSET, _GENERIC_REFERENCE)) + ")"
_DETERMINER = r"(?:(?:the|an?|any|additional|extra|other)\s+|\u4efb\u4f55|\u989d\u5916\u7684?|\u5176\u4ed6(?:\u7684)?)*"
# Shared image suffixes belong only to adjacent negated asset nouns, never later prose.
_NEGATED_TERM = (
    "(?:" + _TERM + r"|(?:[1\u4e00]\s*\u5f20\s*)?(?:\u89d2\u8272|\u573a\u666f|\u9053\u5177)"
    r"(?:" + _LIST_SEPARATOR + r"(?:\u89d2\u8272|\u573a\u666f|\u9053\u5177))+"
    r"(?:\u53c2\u8003)?(?:\u56fe\u7247|\u56fe\u50cf|\u56fe))"
)
_REFERENCE_LIST = r"<?" + _DETERMINER + _NEGATED_TERM + r">?(?:" + _LIST_SEPARATOR + r"<?" + _DETERMINER + _NEGATED_TERM + r">?)*"
_NOT_PROVIDED = (r"(?:(?:is|are|was|were|has\s+been|have\s+been)\s+)?(?:not|never)\s+(?:provided|supplied|uploaded)\b|"
                 r"(?:\u5e76)?(?:\u672a(?:\u63d0\u4f9b|\u4e0a\u4f20)|\u6ca1\u6709(?:\u63d0\u4f9b|\u4e0a\u4f20))")
_NEGATED = re.compile(
    r"(?:\b(?:do\s+not|don't|never|not)\s+(?:use|provide|supply|reference|preserve|keep|refer\s+to)\s*|"
    r"\b(?:no|without|not)\s+|"
    r"\u4e0d(?:\u5f97|\u8981|\u5e94|\u80fd|\u4f1a)?(?:\u4f7f\u7528|\u5f15\u7528|\u53c2\u8003|\u4fdd\u6301|\u6cbf\u7528|\u7ee7\u627f|\u63d0\u4f9b)|"
    r"\u7981\u6b62(?:\u4f7f\u7528|\u5f15\u7528|\u63d0\u4f9b)|\u672a\u63d0\u4f9b|\u6ca1\u6709(?:\u63d0\u4f9b)?|\u4e0d\u5b58\u5728|\u4e0d\u662f(?:\u4ee5)?|\u65e0)"
    r"\s*" + _REFERENCE_LIST + "|" + _REFERENCE_LIST + r"\s*(?:" + _NOT_PROVIDED + ")", re.IGNORECASE,
)
_ZERO_REFERENCE = re.compile(
    r"\b(?:no|zero|0)\s+(?:reference|input)\s+(?:image|picture)s?\b|"
    r"\b(?:reference|input)\s+(?:image|picture)s?\s*(?:count\s*(?:is|:|=)?|[:=])\s*(?:zero\b|0(?![0-9]))|"
    r"(?:^|[.!?;\n\u3002\uff1b])\s*(?:the\s+)?(?:reference|input)\s+(?:image|picture)s?\s+(?:" + _NOT_PROVIDED + r")|"
    r"(?:\u65e0|(?:\u6ca1\u6709|\u672a)\u63d0\u4f9b(?:\u4efb\u4f55)?)(?:\u53c2\u8003|\u8f93\u5165)(?:\u56fe\u7247|\u56fe\u50cf|\u56fe)|"
    r"(?:\u53c2\u8003|\u8f93\u5165)(?:\u56fe\u7247|\u56fe\u50cf|\u56fe)(?:\u6570\u91cf)?\s*(?:\u4e3a|\u662f|[:=])\s*[0\u96f6](?![0-9])(?:\u5f20)?", re.IGNORECASE,
)


def validate_reference_prompt(prompt, source_kind):
    """Check known reference phrases, not arbitrary NLP or image quality.

    Numbered lists, adjacent non-use/unprovided phrases and explicit previous
    text qualifiers are recognized. Distant pronouns, ellipsis and arbitrary
    paraphrases are not inferred; callers must still prove the actual binding.
    """
    if not isinstance(source_kind, str) or source_kind not in {"PRIMARY_STORYBOARD", "PREVIOUS_KEYFRAME", "CUSTOM_REFERENCE", "SAVED_REFERENCE", "NONE"}:
        raise KeyframeReferenceError("UNKNOWN_REFERENCE_SOURCE")
    if not isinstance(prompt, str) or not prompt.strip():
        raise KeyframeReferenceError("PROMPT_EMPTY")
    text = unicodedata.normalize("NFKC", prompt)
    if text.lstrip().startswith(("{", "[", "\"", "```")):
        raise KeyframeReferenceError("PROMPT_NOT_EDIT_PROSE")
    # Recover the explicit compact edit verb, not arbitrary concatenated prose.
    text = re.sub(r"\b(but|and)use(?=(?:picture|image|ref)[0-9])", r"\1 use ", text, flags=re.IGNORECASE)
    zero_declared = bool(_ZERO_REFERENCE.search(text))
    affirmative = _PLANNED_TEXT.sub(" ", text)
    affirmative = _ZERO_REFERENCE.sub(" ", affirmative)
    affirmative = _NEGATED.sub(" ", affirmative)
    indexes = []
    for match in re.finditer(_NUMBER_REF, affirmative, re.IGNORECASE):
        for number in re.finditer(_NUMBER, match.group(), re.IGNORECASE):
            value = number.group().lower()
            numeric = re.match(r"[0-9]+", value)
            if numeric:
                index = int(numeric.group())
            elif value in _CARDINALS:
                index = _CARDINALS.index(value)
            elif value in _ORDINALS:
                index = _ORDINALS.index(value) + 1
            else:
                digits = dict(zip("\u96f6\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d", range(10)))
                digits.update({"\u3007": 0, "\u4e24": 2})
                index, digit = 0, 0
                for character in value:
                    if character in digits:
                        digit = digit * 10 + digits[character]
                    else:
                        index += (digit or 1) * {"\u5341": 10, "\u767e": 100, "\u5343": 1000}[character]
                        digit = 0
                index += digit
            indexes.append(index)
    if any(index != 1 for index in indexes) or (source_kind == "NONE" and indexes):
        raise KeyframeReferenceError("UNBOUND_PICTURE_REFERENCE", sorted(set(indexes)))
    has_previous = bool(re.search(_PREVIOUS, affirmative, re.IGNORECASE))
    has_primary = bool(re.search(_PRIMARY, affirmative, re.IGNORECASE))
    if (has_previous and source_kind != "PREVIOUS_KEYFRAME") or (has_primary and source_kind != "PRIMARY_STORYBOARD"):
        raise KeyframeReferenceError("WRONG_REFERENCE_SOURCE")
    if re.search(_ASSET, affirmative, re.IGNORECASE):
        raise KeyframeReferenceError("UNBOUND_ASSET_REFERENCE")
    has_reference = bool(re.search(_GENERIC_REFERENCE, affirmative, re.IGNORECASE))
    if (source_kind == "NONE" and has_reference) or (source_kind != "NONE" and zero_declared):
        raise KeyframeReferenceError("WRONG_REFERENCE_SOURCE")
    if source_kind == "PRIMARY_STORYBOARD" and not has_primary:
        raise KeyframeReferenceError("PRIMARY_SOURCE_NOT_DECLARED")
    if source_kind == "PREVIOUS_KEYFRAME" and not has_previous:
        raise KeyframeReferenceError("PREVIOUS_SOURCE_NOT_DECLARED")
    if source_kind in {"CUSTOM_REFERENCE", "SAVED_REFERENCE"} and not (indexes or has_reference):
        raise KeyframeReferenceError("REFERENCE_SOURCE_NOT_DECLARED")
    if source_kind == "NONE" and not zero_declared:
        raise KeyframeReferenceError("NO_REFERENCE_NOT_DECLARED")
    return {"passed": True, "source_kind": source_kind, "picture_indexes": sorted(set(indexes))}


def frozen_keyframe_client(base_url):
    from app.services.comfyui.client import ComfyUIClient
    parts = urlsplit(base_url)
    if parts.scheme not in {"http", "https"} or not parts.netloc or parts.username or parts.password or parts.query or parts.fragment:
        raise KeyframeReferenceError("INVALID_COMFYUI_ENDPOINT")
    endpoint = base_url.rstrip("/")
    class FrozenKeyframeClient(ComfyUIClient):
        @property
        def base_url(self):
            return endpoint
    return FrozenKeyframeClient()


def select_keyframe_output(history, contract, base_url):
    validate_frozen_contract(contract, require_submitted=True)
    saved = contract.get("submit", {})
    prompt = history.get("prompt") if isinstance(history, dict) else None
    if not isinstance(prompt, list) or len(prompt) < 3 or prompt[1] != saved.get("prompt_id"):
        raise KeyframeReferenceError("HISTORY_SUBMISSION_MISMATCH")
    assert_keyframe_graph_matches(prompt[2], contract)
    status = history.get("status") or {}
    if status.get("status_str") == "error" or not (status.get("completed") is True or status.get("status_str") in {"success", "completed"}):
        raise KeyframeReferenceError("RESULT_NOT_COMPLETED")
    output = (history.get("outputs") or {}).get(contract["workflow"]["output_node_id"], {})
    images = output.get("images") if isinstance(output, dict) else None
    if not isinstance(images, list) or len(images) != 1 or not isinstance(images[0], dict):
        raise KeyframeReferenceError("RESULT_NODE_UNCERTAIN")
    image = images[0]
    name, folder = image.get("filename"), image.get("subfolder", "")
    if (not isinstance(name, str) or not name or "/" in name or "\\" in name or name in {".", ".."}
            or not isinstance(folder, str) or "\\" in folder or folder.startswith("/") or ".." in folder.split("/")
            or image.get("type") != "output"):
        raise KeyframeReferenceError("INVALID_OUTPUT_LOCATOR")
    return base_url.rstrip("/") + "/view?" + urlencode({"filename": name, "subfolder": folder, "type": "output"})
