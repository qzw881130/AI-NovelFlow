"""
分镜视频生成服务

封装分镜视频生成的后台任务逻辑
"""
import json
import os
import random
import subprocess
from datetime import datetime
from pathlib import Path

from app.models.novel import Novel, Chapter
from app.models.task import Task
from app.models.workflow import Workflow
from app.core.database import SessionLocal
from app.services.comfyui import ComfyUIService
from app.services.comfyui.errors import persist_task_comfyui_error
from app.services.file_storage import file_storage
from app.utils.path_utils import local_path_to_url, url_to_local_path
from app.repositories.shot_repository import ShotRepository
from app.services.background_workers import persistent_job, worker_manager
from app.services.video_director_ai import build_h3_video_prompt, safe_json_dict, safe_json_list
from app.services.video_reference_resources import resolve_video_reference_resources
from app.services.dialogue_ownership import assign_dialogues_to_clips
from app.services.clip_execution_compiler import (
    ClipExecutionCompileError,
    compile_extend_clip,
    compile_generate_clip,
    compile_temporal_extend_clip,
    get_canonical_execution_readiness,
)
from app.services.canonical_execution_invalidation import (
    CanonicalExecutionConflict,
    canonical_clip_dependency_closure,
    ensure_no_active_canonical_clip_tasks,
    invalidate_current_canonical_execution,
)
from app.services.prop_policy import PROP_EXISTENCE_REAL, get_visual_prop_names
from app.utils.workflow_seed import extract_workflow_seed
from app.services.continuous_clip_av import (
    CONTINUOUS_CAPABILITIES, NATIVE_CONTINUITY_OUTPUT, is_clip_execution_contract,
    probe_clip_av, validate_native_output, continuity_output_metadata, continuous_assembly_spans,
)
from app.services.native_av_mux import preserve_native_av


# A task can be observed by the batch runner and the reconciliation loop at the
# same time.  Keep only one queued/running coroutine per persistent task id;
# otherwise both coroutines may download the same Clip and start competing
# merges for the same Shot output.
_queued_shot_video_task_ids: set[str] = set()


def resolve_extend_previous_av(db, novel_id: str, chapter_id: str, shot, clip: dict, provenance: dict | None = None) -> dict:
    """Resolve the immutable Previous AV snapshot for one new EXTEND Task."""
    provenance = provenance or {}
    try:
        previous_index = int(clip.get("previous_clip_index"))
        revision = int(clip.get("clip_plan_revision") or provenance.get("clip_plan_revision"))
        source_task_id = str(provenance.get("generated_by_task_id") or "")
        result_url = str(provenance.get("result_url") or "")
        source_revision = int(provenance.get("clip_plan_revision"))
        source_index = int(provenance.get("clip_index"))
    except (TypeError, ValueError):
        raise ValueError("PREVIOUS_AV_UNAVAILABLE")
    if not source_task_id or not result_url or source_revision != revision or source_index != previous_index:
        raise ValueError("PREVIOUS_AV_UNAVAILABLE")
    source_task = db.query(Task).filter(Task.id == source_task_id).first()
    if not source_task or source_task.status != "completed" or source_task.type != "shot_video":
        raise ValueError("PREVIOUS_AV_UNAVAILABLE")
    if source_task.novel_id != novel_id or source_task.chapter_id != chapter_id or source_task.shot_id != shot.id:
        raise ValueError("PREVIOUS_AV_UNAVAILABLE")
    metadata = safe_json_dict(source_task.metadata_json)
    source_contract = metadata.get("execution_contract") or {}
    if (
        metadata.get("execution_scope") != "CLIP"
        or not is_clip_execution_contract(source_contract)
        or metadata.get("approval_status") != "APPROVED"
        or int(metadata.get("clip_index") or 0) != previous_index
        or int(metadata.get("clip_plan_revision") or 0) != revision
        or source_task.result_url != result_url
    ):
        raise ValueError("PREVIOUS_AV_UNAVAILABLE")
    plan = safe_json_dict(shot.video_director_plan)
    source_clip = next((item for item in plan.get("clip_plan", []) if isinstance(item, dict) and int(item.get("clip_index") or 0) == previous_index), None)
    if (
        not source_clip
        or int(plan.get("clip_plan_revision") or 0) != revision
        or source_clip.get("execution_status") != "APPROVED"
        or source_clip.get("generated_by_task_id") != source_task_id
        or source_clip.get("video_url") != result_url
    ):
        raise ValueError("PREVIOUS_AV_UNAVAILABLE")
    local_path = url_to_local_path(result_url)
    if not local_path or not Path(local_path).is_file() or not os.access(local_path, os.R_OK):
        raise ValueError("PREVIOUS_AV_UNAVAILABLE")
    if source_contract.get("capability") in CONTINUOUS_CAPABILITIES:
        physical = validate_native_output(metadata, result_url, local_path)
        if source_clip.get("physical_output") != physical:
            raise ValueError("NATIVE_CONTINUITY_OUTPUT_INVALID")
    elif source_contract.get("capability") == "GENERATE" and source_contract.get("artifact_kind") == "CLIP_ONLY":
        # The first GENERATE is the bootstrap AV source for a continuity run.
        physical = {**probe_clip_av(local_path), "physical_output_role": "CLIP_ONLY"}
    else:
        raise ValueError("PREVIOUS_AV_UNAVAILABLE")
    source = {key: physical[key] for key in (
        "frame_count", "fps", "timebase", "video_duration", "has_audio", "audio_duration",
        "audio_start_time", "width", "height", "sha256", "physical_output_role",
    )}
    if provenance.get("physical_output") is not None and provenance["physical_output"] != source:
        raise ValueError("PREVIOUS_AV_UNAVAILABLE")
    if provenance.get("source_frame_start", 0) != 0:
        raise ValueError("PREVIOUS_AV_UNAVAILABLE")
    return {
        "clip_index": previous_index,
        "clip_plan_revision": revision,
        "generated_by_task_id": source_task_id,
        "result_url": result_url,
        "local_path": local_path,
        "physical_output": source,
    }


def _probe_video_duration(path: str) -> float | None:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return float(result.stdout.strip()) if result.returncode == 0 else None
    except Exception:
        return None


def _resolve_shot_image_asset(shot) -> tuple[str | None, str | None]:
    image_url = shot.image_url
    image_path = url_to_local_path(image_url) if image_url else None
    if not image_path and shot.image_path:
        image_path = shot.image_path
        image_url = local_path_to_url(image_path)
    if not image_path or not Path(image_path).is_file():
        return None, None
    return image_url, image_path


def _filter_transitions_for_keyframe_indexes(transitions: list, keyframe_indexes: list) -> list:
    index_set = {int(index) for index in keyframe_indexes or []}
    return [
        transition for transition in transitions or []
        if isinstance(transition, dict)
        and int(transition.get("from_keyframe_index") or -1) in index_set
        and int(transition.get("to_keyframe_index") or -1) in index_set
    ]


def _project_semantic_clip_transitions(
    transitions: list,
    visual_state_indexes: list,
    carry_in_state_index=None,
) -> list:
    """Project canonical transitions into one semantic Clip without changing ownership."""
    owned_indexes = []
    for raw_index in visual_state_indexes or []:
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if index > 0 and index not in owned_indexes:
            owned_indexes.append(index)
    if not owned_indexes:
        return []

    allowed_pairs = set(zip(owned_indexes, owned_indexes[1:]))
    try:
        carry_in = int(carry_in_state_index) if carry_in_state_index is not None else None
    except (TypeError, ValueError):
        carry_in = None
    if carry_in is not None and carry_in > 0 and carry_in != owned_indexes[0]:
        allowed_pairs.add((carry_in, owned_indexes[0]))

    projected = []
    for transition in transitions or []:
        if not isinstance(transition, dict):
            continue
        try:
            endpoints = (
                int(transition.get("from_keyframe_index")),
                int(transition.get("to_keyframe_index")),
            )
        except (TypeError, ValueError):
            continue
        if endpoints in allowed_pairs:
            projected.append(transition)
    return projected


def resolve_clip_reference_resources(db, novel_id: str, shot, plan: dict, clip: dict) -> dict:
    """Shared API/worker resource resolution from the same owned canonical context."""
    states = {int(item["index"]): item for item in plan.get("keyframes") or [] if isinstance(item, dict) and item.get("index") is not None}
    owned = [states[int(index)] for index in clip.get("visual_state_indexes") or [] if int(index) in states]
    transitions = _project_semantic_clip_transitions(
        plan.get("transitions") or [], clip.get("visual_state_indexes") or [], clip.get("carry_in_state_index"),
    )
    return resolve_video_reference_resources(db, novel_id, shot, owned, transitions, clip)


def _to_float_or_none(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dialogue_time_range(dialogue: dict):
    if not isinstance(dialogue, dict):
        return None, None
    start = None
    end = None
    for key in ("start_time", "start", "begin_time", "time", "time_seconds", "timestamp"):
        start = _to_float_or_none(dialogue.get(key))
        if start is not None:
            break
    for key in ("end_time", "end", "finish_time"):
        end = _to_float_or_none(dialogue.get(key))
        if end is not None:
            break
    if start is None and end is None:
        return None, None
    if end is None:
        end = start
    if start is None:
        start = end
    return start, end


def _dialogue_assignment_source(official_timeline: list | None) -> str:
    has_valid_timeline = any(
        isinstance(item, dict)
        and item.get("id") is not None
        and _to_float_or_none(item.get("start_time")) is not None
        and _to_float_or_none(item.get("end_time")) is not None
        and _to_float_or_none(item.get("end_time")) > _to_float_or_none(item.get("start_time"))
        for item in official_timeline or []
    )
    return "official_timeline" if has_valid_timeline else "legacy_estimated_fallback"


def _clip_dialogues_for_prompt(dialogues: list, clip: dict, shot_duration: float, official_timeline: list | None = None) -> list:
    if not dialogues:
        return []
    if official_timeline is not None and not official_timeline and any(
        isinstance(dialogue, dict) and str(dialogue.get("text") or dialogue.get("dialogue") or "").strip()
        for dialogue in dialogues
    ):
        raise ValueError("DIALOGUE_TIMELINE_UNAVAILABLE")
    clip_start = _to_float_or_none(clip.get("start_time")) or 0
    clip_end = _to_float_or_none(clip.get("end_time")) or shot_duration or clip_start
    if clip_end <= clip_start:
        return dialogues

    official_by_id = {
        str(item.get("id")): item
        for item in official_timeline or []
        if isinstance(item, dict)
        and item.get("id") is not None
        and _to_float_or_none(item.get("start_time")) is not None
        and _to_float_or_none(item.get("end_time")) is not None
        and _to_float_or_none(item.get("end_time")) > _to_float_or_none(item.get("start_time"))
    }
    if official_by_id:
        official_dialogues = []
        fallback_dialogues = []
        ordered_dialogues = sorted(
            enumerate(dialogues),
            key=lambda item: (
                (_to_float_or_none(item[1].get("order")) if isinstance(item[1], dict) else None) is None,
                _to_float_or_none(item[1].get("order")) if isinstance(item[1], dict) else None,
                item[0],
            ),
        )
        for index, dialogue in ordered_dialogues:
            if not isinstance(dialogue, dict):
                continue
            dialogue_id = str(dialogue.get("id") or f"D{index + 1}")
            official = official_by_id.get(dialogue_id)
            if not official:
                if str(dialogue.get("text") or dialogue.get("dialogue") or "").strip():
                    fallback_dialogues.append(dialogue)
                continue
            start = float(official["start_time"])
            end = float(official["end_time"])
            overlap_start = max(start, clip_start)
            overlap_end = min(end, clip_end)
            if overlap_start < overlap_end:
                official_dialogues.append({
                    **dialogue,
                    "dialogue_id": dialogue_id,
                    "segment_index": 1,
                    "start_time": overlap_start,
                    "end_time": overlap_end,
                    "local_start_time": round(overlap_start - clip_start, 2),
                    "local_end_time": round(overlap_end - clip_start, 2),
                    "projected_duration": round(overlap_end - overlap_start, 2),
                    "is_continuation": overlap_start > start,
                    "continues_in_next_clip": overlap_end < end,
                    "dialogue_timing_source": "official",
                    "projection_mode": "intersection",
                })
        if fallback_dialogues:
            raise ValueError("OFFICIAL_DIALOGUE_TIMELINE_INCOMPLETE")
        return official_dialogues

    timed_dialogues = []
    has_timed_dialogue = False
    for dialogue in dialogues:
        start, end = _dialogue_time_range(dialogue)
        if start is None and end is None:
            continue
        has_timed_dialogue = True
        if start < clip_end and end >= clip_start:
            timed_dialogues.append(dialogue)
    if has_timed_dialogue:
        return timed_dialogues

    ordered_dialogues = sorted(
        enumerate(dialogues),
        key=lambda item: (
            (_to_float_or_none(item[1].get("order")) if isinstance(item[1], dict) else None) is None,
            _to_float_or_none(item[1].get("order")) if isinstance(item[1], dict) else None,
            item[0],
        ),
    )
    ordered_dialogues = [dialogue for _, dialogue in ordered_dialogues]
    duration = max(float(shot_duration or clip_end), clip_end, 1)
    selected = []
    total = len(ordered_dialogues)
    for index, dialogue in enumerate(ordered_dialogues):
        position = (index / max(total, 1)) * duration
        if clip_start <= position < clip_end or (index == total - 1 and clip_start <= position <= clip_end):
            selected.append(dialogue)
    return selected


def _semantic_clip_prompt_context(video_director_plan: dict, clip_metadata: dict) -> dict:
    """Keep semantic Clip identity and project its official dialogue into Clip-local time."""
    try:
        clip_index = int(clip_metadata.get("clip_index"))
    except (TypeError, ValueError):
        raise ValueError("semantic Clip index 无效")
    semantic_clip = next((
        item for item in video_director_plan.get("clip_plan", [])
        if isinstance(item, dict) and int(item.get("clip_index") or 0) == clip_index
    ), None)
    if not semantic_clip:
        raise ValueError("semantic Clip 不存在")
    clip = dict(semantic_clip)
    clip_start = _to_float_or_none(clip.get("start_time"))
    clip_end = _to_float_or_none(clip.get("end_time"))
    if clip_start is None or clip_end is None or clip_end <= clip_start:
        raise ValueError("semantic Clip 时间范围无效")

    source_dialogues = (
        clip_metadata["dialogue_assignment"]
        if "dialogue_assignment" in clip_metadata
        else semantic_clip.get("dialogue_assignment") or []
    )
    projected_dialogues = []
    for dialogue in source_dialogues:
        if not isinstance(dialogue, dict):
            continue
        start = _to_float_or_none(dialogue.get("start_time"))
        end = _to_float_or_none(dialogue.get("end_time"))
        if start is None or end is None or end <= start:
            projected_dialogues.append(dict(dialogue))
            continue
        if start < clip_start or end > clip_end:
            raise ValueError("semantic Clip dialogue assignment outside clip interval")
        dialogue_id = str(dialogue.get("dialogue_id") or dialogue.get("id") or "")
        projected_dialogues.append({
            **dialogue,
            "dialogue_id": dialogue_id or dialogue.get("dialogue_id"),
            "id": dialogue_id or dialogue.get("id"),
            "start_time": round(start, 2),
            "end_time": round(end, 2),
            "local_start_time": round(start - clip_start, 2),
            "local_end_time": round(end - clip_start, 2),
            "projection_mode": "intersection",
            "dialogue_timing_source": "official_projection",
        })

    selected_indexes = clip.get("visual_state_indexes") or []
    selected_indexes = {int(index) for index in selected_indexes}
    source_keyframes = [item for item in video_director_plan.get("keyframes") or [] if isinstance(item, dict)]
    source_transitions = video_director_plan.get("transitions") or []
    keyframes = [
        item for item in source_keyframes
        if int(item.get("index") or -1) in selected_indexes
    ] if selected_indexes else source_keyframes
    transitions = _project_semantic_clip_transitions(
        source_transitions,
        clip.get("visual_state_indexes") or [],
        clip.get("carry_in_state_index"),
    )
    return {
        "clip": clip,
        "clip_dialogues": projected_dialogues,
        "keyframes": keyframes,
        "transitions": transitions,
    }


def _select_video_prompt_context(
    video_director_plan: dict,
    clip_metadata: dict | None,
    selected_mode: str,
    duration: float,
    clip_only_execution: bool,
) -> dict:
    """Select the prompt context used by the worker for semantic or legacy clips."""
    window_plans = video_director_plan.get("window_plans") if isinstance(video_director_plan.get("window_plans"), list) else []
    clip = (video_director_plan.get("clips") or [{}])[0] if isinstance(video_director_plan.get("clips"), list) else {}
    semantic_context = None
    if clip_metadata and clip_metadata.get("execution_scope") == "CLIP":
        semantic_context = _semantic_clip_prompt_context(video_director_plan, clip_metadata)
        clip = semantic_context["clip"]
    if selected_mode == "MULTI_KEYFRAME" and window_plans and not clip_only_execution:
        window_plan = window_plans[0]
        clip = {
            "clip_index": window_plan.get("window_index") or 1,
            "start_time": window_plan.get("start_time") or 0,
            "end_time": window_plan.get("end_time") or duration,
            "selected_frame_count": window_plan.get("selected_frame_count"),
            "workflow_key": window_plan.get("workflow_key"),
            "keyframe_indexes": window_plan.get("keyframe_indexes") or [],
        }
    if not clip:
        clip = {"clip_index": 1, "start_time": 0, "end_time": duration, "status": "PENDING"}

    if semantic_context is not None:
        return semantic_context

    keyframes = video_director_plan.get("keyframes") if isinstance(video_director_plan.get("keyframes"), list) else []
    transitions = video_director_plan.get("transitions") if isinstance(video_director_plan.get("transitions"), list) else []
    if selected_mode == "MULTI_KEYFRAME" and clip.get("keyframe_indexes"):
        selected_indexes = {int(index) for index in clip.get("keyframe_indexes") or []}
        keyframes = [
            item for item in keyframes
            if isinstance(item, dict) and int(item.get("index") or -1) in selected_indexes
        ]
        transitions = _filter_transitions_for_keyframe_indexes(transitions, clip.get("keyframe_indexes") or [])
    return {"clip": clip, "clip_dialogues": None, "keyframes": keyframes, "transitions": transitions}


def _sync_task_video_director_clips(task, window_plans: list) -> None:
    if task is not None:
        task.video_director_clips = json.dumps(window_plans, ensure_ascii=False)


def _update_window_plan(shot, window_index: int, fields: dict, db, task=None) -> None:
    plan = safe_json_dict(shot.video_director_plan)
    window_plans = plan.get("window_plans") if isinstance(plan.get("window_plans"), list) else []
    for window_plan in window_plans:
        if isinstance(window_plan, dict) and int(window_plan.get("window_index") or 0) == int(window_index):
            window_plan.update(fields)
            break
    shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
    _sync_task_video_director_clips(task, window_plans)
    db.commit()


def _update_window_plan_status(shot, window_index: int, status: str, db, task=None) -> None:
    _update_window_plan(shot, window_index, {"status": status}, db, task=task)


def _update_clip_prompt(shot, clip: dict, prompt_text: str, db) -> None:
    plan = safe_json_dict(shot.video_director_plan)
    clip_index = int((clip or {}).get("clip_index") or 1)
    semantic_clip = next((item for item in plan.get("clip_plan") or [] if isinstance(item, dict) and int(item.get("clip_index") or 0) == clip_index), None)
    if semantic_clip is not None:
        semantic_clip["prompt_text"] = prompt_text
        shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
        db.commit()
        return
    clips = plan.get("clips") if isinstance(plan.get("clips"), list) else []
    clip_index = int((clip or {}).get("clip_index") or 1)
    clip_start = (clip or {}).get("start_time", 0)
    clip_end = (clip or {}).get("end_time")
    updated = False

    for index, existing_clip in enumerate(clips):
        if not isinstance(existing_clip, dict):
            continue
        if int(existing_clip.get("clip_index") or index + 1) == clip_index:
            existing_clip["prompt_text"] = prompt_text
            updated = True
            break

    if not updated:
        clips.append({
            "clip_index": clip_index,
            "start_time": clip_start,
            "end_time": clip_end,
            "status": (clip or {}).get("status") or "PENDING",
            "prompt_text": prompt_text,
        })

    plan["clips"] = clips
    shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
    db.commit()


def get_semantic_clip_prompt(plan: dict, clip: dict) -> str:
    """Canonical prompt first; pre-fix legacy data only for identical Clip boundaries."""
    if "prompt_text" in clip:
        return str(clip.get("prompt_text") or "")
    for legacy in plan.get("clips") or []:
        if not isinstance(legacy, dict):
            continue
        if (
            legacy.get("clip_index") == clip.get("clip_index")
            and legacy.get("start_time") == clip.get("start_time")
            and legacy.get("end_time") == clip.get("end_time")
        ):
            return str(legacy.get("prompt_text") or "")
    return ""


def _update_clip_result(shot, clip: dict, fields: dict, db) -> None:
    plan = safe_json_dict(shot.video_director_plan)
    clips = plan.get("clips") if isinstance(plan.get("clips"), list) else []
    clip_index = int((clip or {}).get("clip_index") or 1)
    clip_start = (clip or {}).get("start_time", 0)
    clip_end = (clip or {}).get("end_time")
    updated = False

    for index, existing_clip in enumerate(clips):
        if not isinstance(existing_clip, dict):
            continue
        if int(existing_clip.get("clip_index") or index + 1) == clip_index:
            existing_clip.update(fields)
            updated = True
            break

    if not updated:
        clips.append({
            "clip_index": clip_index,
            "start_time": clip_start,
            "end_time": clip_end,
            **fields,
        })

    plan["clips"] = clips
    shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
    db.commit()


def _mark_shot_video_failed(shot, shot_repo: ShotRepository, message: str):
    plan = safe_json_dict(shot.video_director_plan)
    plan["task_error_message"] = message
    plan["error_message"] = message
    return shot_repo.update(shot, video_status="failed", video_director_plan=plan)


def _clear_shot_video_error(shot, shot_repo: ShotRepository, **fields):
    plan = safe_json_dict(shot.video_director_plan)
    plan.pop("task_error_message", None)
    plan.pop("error_message", None)
    return shot_repo.update(shot, video_director_plan=plan, **fields)


def _is_task_cancelled(db, task) -> bool:
    db.refresh(task)
    return task.status == "cancelled"


def _cleanup_task_generated_clip_videos(db, task, shot) -> None:
    plan = safe_json_dict(shot.video_director_plan)
    window_plans = plan.get("window_plans") if isinstance(plan.get("window_plans"), list) else []
    changed = False
    for window_plan in window_plans:
        if not isinstance(window_plan, dict) or window_plan.get("generated_by_task_id") != task.id:
            continue
        local_path = window_plan.get("local_path") or url_to_local_path(window_plan.get("video_url"))
        if local_path:
            try:
                path = Path(local_path)
                if path.exists() and path.is_file():
                    path.unlink()
            except Exception as exc:
                print(f"[VideoTask {task.id}] Failed to delete cancelled clip video {local_path}: {exc}")
        for key in ["video_url", "local_path", "source_video_url", "generated_at", "generated_by_task_id"]:
            window_plan.pop(key, None)
        window_plan["status"] = "CANCELLED"
        window_plan["error_message"] = "任务已取消，已清理本任务生成的 Clip 视频"
        changed = True
    if changed:
        shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
        _sync_task_video_director_clips(task, window_plans)
        db.commit()


def _reset_multi_clip_window_plans_for_task(db, task, shot, only_window_index: int | None = None, preserve_prompt_text: bool = False) -> list:
    plan = safe_json_dict(shot.video_director_plan)
    window_plans = plan.get("window_plans") if isinstance(plan.get("window_plans"), list) else []
    reset_keys = [
        "prompt_id",
        "workflow_json",
        "video_url",
        "local_path",
        "source_video_url",
        "generated_at",
        "generated_by_task_id",
        "error_message",
        "seed",
    ]
    if not preserve_prompt_text:
        reset_keys.insert(1, "prompt_text")
    for window_plan in window_plans:
        if not isinstance(window_plan, dict):
            continue
        window_index = int(window_plan.get("window_index") or 0)
        if only_window_index is not None and window_index != int(only_window_index):
            continue
        for key in reset_keys:
            window_plan.pop(key, None)
        window_plan["status"] = "PENDING"
    if only_window_index is None:
        plan.pop("merged_video_url", None)
        plan.pop("merged_at", None)
    shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
    _sync_task_video_director_clips(task, window_plans)
    db.commit()
    return window_plans


def _local_url_from_path(path: str) -> str:
    relative_path = path.replace(str(file_storage.base_dir), "").replace("\\", "/")
    return f"/api/files/{relative_path.lstrip('/')}"


def _parse_iso_datetime(value: str):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _hydrate_plan_keyframes_from_legacy(shot, plan_keyframes: list) -> list:
    try:
        legacy_keyframes = json.loads(shot.keyframes) if shot.keyframes else []
    except Exception:
        legacy_keyframes = []
    legacy_by_plan_index = {
        int(keyframe.get("plan_keyframe_index")): keyframe
        for keyframe in legacy_keyframes
        if isinstance(keyframe, dict) and keyframe.get("plan_keyframe_index") is not None
    }
    hydrated = []
    changed = False
    for keyframe in plan_keyframes:
        if not isinstance(keyframe, dict):
            continue
        next_keyframe = dict(keyframe)
        plan_index = next_keyframe.get("index")
        try:
            legacy_keyframe = legacy_by_plan_index.get(int(plan_index)) if plan_index is not None else None
        except Exception:
            legacy_keyframe = None
        if legacy_keyframe:
            for field in ("image_url", "image_task_id"):
                if not next_keyframe.get(field) and legacy_keyframe.get(field):
                    next_keyframe[field] = legacy_keyframe.get(field)
                    changed = True
        hydrated.append(next_keyframe)
    if changed:
        plan = safe_json_dict(shot.video_director_plan)
        plan["keyframes"] = hydrated
        shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
    return hydrated


def _get_reusable_video_prompt(video_director_plan: dict) -> str:
    clips = video_director_plan.get("clips") if isinstance(video_director_plan.get("clips"), list) else []
    for clip in clips:
        prompt = (clip or {}).get("prompt_text")
        if isinstance(prompt, str) and prompt.strip():
            return prompt.strip()
    ai_calls = video_director_plan.get("ai_calls") if isinstance(video_director_plan.get("ai_calls"), list) else []
    for call in reversed(ai_calls):
        prompt = (call or {}).get("final_prompt")
        if isinstance(prompt, str) and prompt.strip():
            return prompt.strip()
    return ""


def enqueue_shot_video_task(
    task_id: str,
    novel_id: str,
    chapter_id: str,
    shot_index: int,
    workflow_id: str,
    shot_image_url: str,
    use_keyframes: bool = True,
    use_reference_audio: bool = True,
    selected_mode: str = "SINGLE_FRAME",
    only_window_index: int | None = None,
    auto_merge_clips: bool = False,
    skip_llm_when_prompt_exists: bool = False,
    clip_metadata: dict | None = None,
) -> None:
    """Queue shot video generation in its dedicated serial worker."""
    if task_id in _queued_shot_video_task_ids:
        print(f"[VideoTask {task_id}] Duplicate enqueue ignored")
        return

    _queued_shot_video_task_ids.add(task_id)

    async def _run_once():
        try:
            await generate_shot_video_task(
                task_id,
                novel_id,
                chapter_id,
                shot_index,
                workflow_id,
                shot_image_url,
                use_keyframes=use_keyframes,
                use_reference_audio=use_reference_audio,
                selected_mode=selected_mode,
                only_window_index=only_window_index,
                auto_merge_clips=auto_merge_clips,
                skip_llm_when_prompt_exists=skip_llm_when_prompt_exists,
                clip_metadata=clip_metadata,
            )
        finally:
            _queued_shot_video_task_ids.discard(task_id)

    try:
        payload = {
            "task_id": task_id,
            "novel_id": novel_id,
            "chapter_id": chapter_id,
            "shot_index": shot_index,
            "workflow_id": workflow_id,
            "shot_image_url": shot_image_url,
            "use_keyframes": use_keyframes,
            "use_reference_audio": use_reference_audio,
            "selected_mode": selected_mode,
            "only_window_index": only_window_index,
            "auto_merge_clips": auto_merge_clips,
            "skip_llm_when_prompt_exists": skip_llm_when_prompt_exists,
            "clip_metadata": clip_metadata,
        }
        worker_manager.worker("shot_video").enqueue(persistent_job(
            task_id,
            "app.services.shot_video_service:generate_shot_video_task",
            payload,
            _run_once,
        ))
    except Exception:
        _queued_shot_video_task_ids.discard(task_id)
        raise


async def generate_shot_video_task(
    task_id: str,
    novel_id: str,
    chapter_id: str,
    shot_index: int,
    workflow_id: str,
    shot_image_url: str,
    use_keyframes: bool = True,
    use_reference_audio: bool = True,
    selected_mode: str = "SINGLE_FRAME",
    only_window_index: int | None = None,
    auto_merge_clips: bool = False,
    skip_llm_when_prompt_exists: bool = False,
    clip_metadata: dict | None = None,
):
    """
    后台任务：生成分镜视频

    Args:
        task_id: 任务ID
        novel_id: 小说ID
        chapter_id: 章节ID
        shot_index: 分镜索引
        workflow_id: 工作流ID
        shot_image_url: 分镜图片URL
        use_keyframes: 是否使用关键帧（如果存在），默认 True
        use_reference_audio: 是否使用参考音频（如果存在），默认 True
    """
    db = SessionLocal()
    phase_b_generate = False
    clip_only_execution = False
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            return
        if task.status == "cancelled":
            return

        task.status = "running"
        task.started_at = datetime.utcnow()
        task.current_step = "准备生成视频..."
        db.commit()

        chapter = db.query(Chapter).filter(
            Chapter.id == chapter_id,
            Chapter.novel_id == novel_id
        ).first()

        if not chapter:
            task.status = "failed"
            task.error_message = "章节不存在"
            db.commit()
            return

        novel = db.query(Novel).filter(Novel.id == novel_id).first()
        if not novel:
            task.status = "failed"
            task.error_message = "小说不存在"
            db.commit()
            return

        workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
        if not workflow:
            task.status = "failed"
            task.error_message = "工作流不存在"
            db.commit()
            return

        node_mapping = json.loads(workflow.node_mapping) if workflow.node_mapping else {}
        print(f"[VideoTask {task_id}] Node mapping: {node_mapping}")

        # 使用 ShotRepository 获取分镜数据
        shot_repo = ShotRepository(db)
        shot = shot_repo.get_by_chapter_and_index(chapter_id, shot_index)

        if not shot:
            task.status = "failed"
            task.error_message = "分镜不存在"
            db.commit()
            return

        if clip_metadata and clip_metadata.get("execution_scope") == "CLIP" and clip_metadata.get("capability") == "SINGLE_FRAME":
            shot_image_url, shot_image_path = _resolve_shot_image_asset(shot)
            if not shot_image_path:
                task.status = "failed"
                task.error_message = "semantic SINGLE_FRAME Clip 缺少当前 Shot 的有效分镜图，已阻止使用 workflow 默认图片。"
                task.current_step = "缺少 Shot Image"
                clip_metadata["reference_asset"] = None
                metadata = safe_json_dict(task.metadata_json)
                metadata.update(clip_metadata)
                metadata["approval_status"] = "FAILED"
                task.metadata_json = json.dumps(metadata, ensure_ascii=False)
                _mark_shot_video_failed(shot, shot_repo, task.error_message)
                db.commit()
                return
            clip_metadata["reference_asset"] = {
                "source": "SHOT_IMAGE",
                "shot_id": shot.id,
                "url": shot_image_url,
                "path": shot_image_path,
            }

        # 视频生成优先由 11/12/13 Prompt Builder 产出最终 H3 prompt。
        shot_prompt = (clip_metadata or {}).get("prompt_text") or (shot.video_description or "").strip() or (shot.description or "")
        video_director_plan = safe_json_dict(shot.video_director_plan)
        selected_mode = selected_mode or video_director_plan.get("selected_mode") or "SINGLE_FRAME"

        task.prompt_text = shot_prompt
        if clip_metadata:
            metadata = safe_json_dict(task.metadata_json)
            metadata.update(clip_metadata)
            metadata.setdefault("execution_scope", "CLIP")
            metadata.setdefault("requested_duration", clip_metadata.get("planned_duration"))
            metadata.setdefault("approval_status", "GENERATING")
            task.metadata_json = json.dumps(metadata, ensure_ascii=False)
        task.description = f"{task.description}；视频模式：{selected_mode}"
        db.commit()

        duration = float((clip_metadata or {}).get("requested_duration") or shot.duration or 4)
        fps = 25
        raw_frame_count = int(fps * duration)
        frame_count = ((raw_frame_count // 8) * 8) + 1
        print(f"[VideoTask {task_id}] Duration: {duration}s, FPS: {fps}, Raw frames: {raw_frame_count}, Adjusted frames: {frame_count}")

        character_reference_path = None
        if shot_image_url:
            full_path = url_to_local_path(shot_image_url)
            if full_path:
                character_reference_path = full_path
                print(f"[VideoTask {task_id}] Found shot image: {full_path}")
            else:
                print(f"[VideoTask {task_id}] Shot image not found at: {shot_image_url}")

        if clip_metadata and clip_metadata.get("execution_scope") == "CLIP" and clip_metadata.get("capability") == "SINGLE_FRAME":
            if not character_reference_path:
                task.status = "failed"
                task.error_message = "semantic SINGLE_FRAME Clip 的 Shot Image 无法解析为本地资产，已阻止使用 workflow 默认图片。"
                task.current_step = "Shot Image 无效"
                db.commit()
                return
            task_metadata = safe_json_dict(task.metadata_json)
            task_metadata["reference_asset"] = clip_metadata["reference_asset"]
            task.metadata_json = json.dumps(task_metadata, ensure_ascii=False)

        # 获取占位符替换所需的资源数据
        # 从 Shot 模型直接获取角色、场景、道具
        shot_characters = json.loads(shot.characters) if shot.characters else []
        shot_scene = shot.scene or ""
        shot_props = get_visual_prop_names(db, novel_id, json.loads(shot.props) if shot.props else [])

        # 获取角色外貌描述（从 Character 表中获取）
        character_appearances = {}
        from app.models.novel import Character
        for char_name in shot_characters:
            character = db.query(Character).filter(
                Character.novel_id == novel_id,
                Character.name == char_name
            ).first()
            if character and character.appearance:
                character_appearances[char_name] = character.appearance

        # 获取场景环境设定（从 Scene 表中获取）
        scene_setting = None
        if shot_scene:
            from app.models.novel import Scene
            scene = db.query(Scene).filter(
                Scene.novel_id == novel_id,
                Scene.name == shot_scene
            ).first()
            if scene and scene.setting:
                scene_setting = scene.setting

        # 获取道具外观描述（从 Prop 表中获取）
        prop_appearances = {}
        if shot_props:
            from app.models.novel import Prop
            for prop_name in shot_props:
                prop = db.query(Prop).filter(
                    Prop.novel_id == novel_id,
                    Prop.name == prop_name,
                    Prop.existence == PROP_EXISTENCE_REAL,
                ).first()
                if prop and prop.appearance:
                    prop_appearances[prop_name] = prop.appearance

        # 获取风格设置（从 PromptTemplate 中获取）
        style = ""
        if novel.style_prompt_template_id:
            from app.models.prompt_template import PromptTemplate
            template = db.query(PromptTemplate).filter(
                PromptTemplate.id == novel.style_prompt_template_id
            ).first()
            if template:
                style = template.template or ""

        print(f"[VideoTask {task_id}] Style: {style}")
        print(f"[VideoTask {task_id}] Characters: {character_appearances}")
        print(f"[VideoTask {task_id}] Scene: {scene_setting}")
        print(f"[VideoTask {task_id}] Props: {prop_appearances}")

        # 获取参考音频路径
        reference_audio_path = None
        if use_reference_audio and shot.reference_audio_url:
            audio_local_path = url_to_local_path(shot.reference_audio_url)
            if audio_local_path:
                reference_audio_path = audio_local_path
                print(f"[VideoTask {task_id}] Found reference audio: {audio_local_path}")
            else:
                print(f"[VideoTask {task_id}] Reference audio not found at: {shot.reference_audio_url}")
        elif not use_reference_audio:
            print(f"[VideoTask {task_id}] Skipping reference audio (use_reference_audio=False)")

        # 获取关键帧图片路径。FIRST_LAST/MULTI 使用 Video Director Plan，不再使用旧的 shot.keyframes 间隔模型。
        keyframe_paths = []
        plan_keyframes = video_director_plan.get("keyframes") if isinstance(video_director_plan.get("keyframes"), list) else []
        plan_keyframes = _hydrate_plan_keyframes_from_legacy(shot, plan_keyframes)
        if plan_keyframes is not video_director_plan.get("keyframes"):
            video_director_plan["keyframes"] = plan_keyframes
            db.commit()
        plan_keyframes_by_index = {
            int(kf.get("index")): kf
            for kf in plan_keyframes
            if isinstance(kf, dict) and kf.get("index") is not None
        }
        if not use_keyframes:
            print(f"[VideoTask {task_id}] Skipping keyframes (use_keyframes=False)")

        clip_only_execution = bool(
            clip_metadata
            and is_clip_execution_contract(clip_metadata.get("execution_contract", {}))
            and clip_metadata.get("execution_contract", {}).get("capability") in {"GENERATE", "EXTEND", "TEMPORAL_EXTEND"}
        )
        phase_b_generate = clip_only_execution and clip_metadata.get("execution_contract", {}).get("capability") == "GENERATE"
        phase_b_manifest = None
        temporal_manifest = None
        temporal_image_paths = []
        reference_image_paths = None
        if clip_only_execution:
            try:
                plan_revision = int(clip_metadata.get("clip_plan_revision"))
                semantic_clip = next((
                    item for item in video_director_plan.get("clip_plan", [])
                    if isinstance(item, dict) and int(item.get("clip_index") or 0) == int(clip_metadata.get("clip_index") or 0)
                ), None)
                if not semantic_clip or plan_revision != int(video_director_plan.get("clip_plan_revision") or 0):
                    raise ClipExecutionCompileError("Clip 执行失败：Shot 中已不存在相同 revision/Clip identity")
                if video_director_plan.get("canonical_visual_plan") is True:
                    readiness = get_canonical_execution_readiness(shot, video_director_plan, [semantic_clip])
                    if not readiness["ready"]:
                        raise ClipExecutionCompileError(readiness["code"], detail=readiness["blocking_clips"][0])
                resource_references = resolve_clip_reference_resources(db, novel_id, shot, video_director_plan, semantic_clip)
                if clip_metadata.get("capability") == "EXTEND":
                    previous_contract = (clip_metadata.get("execution_contract") or {}).get("previous_clip") or {}
                    previous_provenance = resolve_extend_previous_av(
                        db, novel_id, chapter_id, shot, semantic_clip, previous_contract,
                    )
                    compiled = compile_extend_clip(
                        shot, video_director_plan, semantic_clip, plan_revision, previous_provenance,
                        resource_references=resource_references,
                    )
                elif clip_metadata.get("capability") == "TEMPORAL_EXTEND":
                    previous_contract = (clip_metadata.get("execution_contract") or {}).get("previous_clip") or {}
                    previous_provenance = resolve_extend_previous_av(
                        db, novel_id, chapter_id, shot, semantic_clip, previous_contract,
                    )
                    selected_anchor_ids = [str(item) for item in semantic_clip.get("temporal_anchor_ids") or []]
                    anchors_by_id = {
                        str(item.get("anchor_id") or item.get("id")): item
                        for item in video_director_plan.get("temporal_anchors") or []
                        if isinstance(item, dict) and (item.get("anchor_id") or item.get("id"))
                    }
                    source_anchors = []
                    for anchor_id in selected_anchor_ids:
                        anchor = anchors_by_id.get(anchor_id)
                        if not anchor:
                            raise ClipExecutionCompileError("TEMPORAL_ANCHOR_UNAVAILABLE")
                        source_anchors.append({
                            "anchor_id": anchor_id,
                            "time_seconds": anchor.get("time_seconds"),
                            "image_url": anchor.get("image_url") or anchor.get("image") or anchor.get("image_path"),
                            "source": anchor.get("source") or anchor.get("provenance"),
                        })
                    compiled = compile_temporal_extend_clip(
                        shot, video_director_plan, semantic_clip, plan_revision,
                        previous_provenance, source_anchors,
                        resource_references=resource_references,
                    )
                else:
                    compiled = compile_generate_clip(
                        shot, video_director_plan, semantic_clip, plan_revision,
                        resource_references=resource_references,
                    )
                task_metadata = safe_json_dict(task.metadata_json)
                task_metadata.update(compiled)
                task.metadata_json = json.dumps(task_metadata, ensure_ascii=False)
                phase_b_manifest = compiled["video_reference_manifest"]
                temporal_manifest = (compiled.get("execution_contract") or {}).get("temporal_anchor_manifest")
                reference_image_paths = []
                for reference in phase_b_manifest["references"]:
                    source_url = reference.get("image_url")
                    local_path = url_to_local_path(source_url) if source_url else None
                    if not local_path and source_url and Path(source_url).is_file():
                        local_path = source_url
                    if not local_path or not Path(local_path).is_file():
                        raise ClipExecutionCompileError(f"参考图 {reference.get('slot')} 无法解析为本地图片")
                    reference["local_path"] = local_path
                    reference_image_paths.append(local_path)
                if temporal_manifest:
                    for anchor in temporal_manifest.get("anchors", []):
                        source_url = anchor.get("image_url")
                        local_path = url_to_local_path(source_url) if source_url else None
                        if not local_path and source_url and Path(source_url).is_file():
                            local_path = source_url
                        if not local_path or not Path(local_path).is_file() or not os.access(local_path, os.R_OK):
                            raise ClipExecutionCompileError("TEMPORAL_ANCHOR_UNAVAILABLE")
                        anchor["local_path"] = local_path
                        temporal_image_paths.append(local_path)
                    task_metadata = safe_json_dict(task.metadata_json)
                    task_metadata["execution_contract"]["temporal_anchor_manifest"] = temporal_manifest
                    task.metadata_json = json.dumps(task_metadata, ensure_ascii=False)
            except (ClipExecutionCompileError, TypeError, ValueError) as exc:
                task.status = "failed"
                task.error_message = str(exc) if str(exc) == "PREVIOUS_AV_UNAVAILABLE" else str(exc)
                task.current_step = "Clip 执行编译失败"
                metadata = safe_json_dict(task.metadata_json)
                metadata["approval_status"] = "FAILED"
                task.metadata_json = json.dumps(metadata, ensure_ascii=False)
                db.commit()
                return

        window_plans = video_director_plan.get("window_plans") if isinstance(video_director_plan.get("window_plans"), list) else []
        if selected_mode == "MULTI_KEYFRAME" and len(window_plans) > 1 and not clip_only_execution:
            window_plans = _reset_multi_clip_window_plans_for_task(
                db,
                task,
                shot,
                only_window_index=only_window_index,
                preserve_prompt_text=skip_llm_when_prompt_exists,
            )
            video_director_plan = safe_json_dict(shot.video_director_plan)
            await _generate_multi_clip_video_task(
                db=db,
                task=task,
                novel=novel,
                shot=shot,
                shot_repo=shot_repo,
                novel_id=novel_id,
                chapter_id=chapter_id,
                shot_index=shot_index,
                shot_image_url=shot_image_url,
                shot_image_path=character_reference_path,
                plan_keyframes_by_index=plan_keyframes_by_index,
                window_plans=window_plans,
                video_director_plan=video_director_plan,
                style=style,
                character_appearances=character_appearances,
                scene_setting=scene_setting,
                prop_appearances=prop_appearances,
                reference_audio_path=reference_audio_path,
                task_id=task_id,
                only_window_index=only_window_index,
                auto_merge_clips=auto_merge_clips,
                skip_llm_when_prompt_exists=skip_llm_when_prompt_exists,
            )
            return

        if clip_only_execution:
            keyframe_paths = []
        elif selected_mode == "SINGLE_FRAME":
            keyframe_paths = []
        elif selected_mode == "FIRST_LAST_FRAME":
            end_keyframe = next((kf for kf in plan_keyframes if isinstance(kf, dict) and kf.get("role") == "END"), None)
            end_image_url = end_keyframe.get("image_url") if isinstance(end_keyframe, dict) else None
            end_keyframe_path = url_to_local_path(end_image_url) if end_image_url else None
            if not end_keyframe_path:
                task.status = "failed"
                task.error_message = "首尾帧模式需要 END 关键帧图片，请先生成尾帧。"
                task.current_step = "缺少 END 关键帧"
                _mark_shot_video_failed(shot, shot_repo, task.error_message)
                db.commit()
                return
            keyframe_paths = [end_keyframe_path]
        elif selected_mode == "MULTI_KEYFRAME":
            if not window_plans:
                task.status = "failed"
                task.error_message = "多关键帧模式缺少 window_plans，请先完成 #08 关键帧时间轴规划。"
                task.current_step = "缺少执行计划"
                _mark_shot_video_failed(shot, shot_repo, task.error_message)
                db.commit()
                return
            if len(window_plans) > 1:
                task.status = "failed"
                task.error_message = "多关键帧多 Clip 执行器尚未接入，不能用单次 H3 调用替代。"
                task.current_step = "多 Clip 执行器未接入"
                _mark_shot_video_failed(shot, shot_repo, task.error_message)
                db.commit()
                return
            keyframe_indexes = window_plans[0].get("keyframe_indexes") if isinstance(window_plans[0].get("keyframe_indexes"), list) else []
            frame_count = int(window_plans[0].get("selected_frame_count") or 0)
            if frame_count not in {3, 4} or len(keyframe_indexes) != frame_count:
                task.status = "failed"
                task.error_message = "多关键帧单 Clip 必须配置 3 或 4 个 keyframe_indexes。"
                task.current_step = "执行计划无效"
                _mark_shot_video_failed(shot, shot_repo, task.error_message)
                db.commit()
                return
            keyframe_paths = []
            for keyframe_index in keyframe_indexes[1:]:
                keyframe = plan_keyframes_by_index.get(int(keyframe_index))
                image_url = keyframe.get("image_url") if keyframe else None
                keyframe_path = url_to_local_path(image_url) if image_url else None
                if not keyframe_path:
                    task.status = "failed"
                    task.error_message = f"Keyframe {keyframe_index} 尚未生成图片，请先生成缺失关键帧图。"
                    task.current_step = "缺少关键帧图片"
                    _mark_shot_video_failed(shot, shot_repo, task.error_message)
                    db.commit()
                    return
                keyframe_paths.append(keyframe_path)

        reference_images = []
        if clip_only_execution:
            reference_images = [
                {"label": f"Picture {item['slot']} · {item['kind']} · {item.get('source_name') or 'KF' + str(item.get('source_keyframe_index'))}", "url": item["image_url"]}
                for item in (phase_b_manifest or {}).get("references", [])
            ]
        elif character_reference_path:
            shot_image_reference_url = local_path_to_url(character_reference_path)
            if shot_image_reference_url:
                reference_images.append({"label": "首帧" if selected_mode == "FIRST_LAST_FRAME" else "分镜图", "url": shot_image_reference_url})
        for idx, keyframe_path in enumerate(keyframe_paths, 1):
            keyframe_url = local_path_to_url(keyframe_path)
            if keyframe_url:
                label = "尾帧" if selected_mode == "FIRST_LAST_FRAME" and idx == 1 else f"关键帧 {idx}"
                reference_images.append({"label": label, "url": keyframe_url})
        task.reference_images = json.dumps(reference_images, ensure_ascii=False) if reference_images else None

        extension = safe_json_dict(workflow.extension)
        workflow_capability = {
            "max_clip_duration": int(extension.get("max_clip_duration") or extension.get("max_seconds") or 15),
            "frame_count": extension.get("frame_count"),
            "workflow_name": workflow.name,
        }
        if clip_metadata and clip_metadata.get("execution_scope") == "CLIP":
            semantic_clip = next((
                item for item in video_director_plan.get("clip_plan", [])
                if int(item.get("clip_index") or 0) == int(clip_metadata.get("clip_index") or 0)
            ), None)
            if (
                int(video_director_plan.get("clip_plan_revision") or 0) != int(clip_metadata.get("clip_plan_revision") or 0)
                or not semantic_clip
            ):
                task.status = "failed"
                task.error_message = "Clip 执行失败：Shot 中已不存在相同 revision/Clip identity"
                task.current_step = "Clip 计划已变化"
                db.commit()
                return
        prompt_context = _select_video_prompt_context(
            video_director_plan,
            clip_metadata,
            selected_mode,
            duration,
            clip_only_execution,
        )
        clip = prompt_context["clip"]
        keyframes_for_prompt = prompt_context["keyframes"]
        transitions_for_prompt = prompt_context["transitions"]
        if clip_metadata and clip_metadata.get("execution_scope") == "CLIP":
            clip_dialogues = prompt_context["clip_dialogues"]
            metadata = safe_json_dict(task.metadata_json)
            metadata["dialogue_assignment"] = clip_metadata.get("dialogue_assignment") or []
            task.metadata_json = json.dumps(metadata, ensure_ascii=False)
            for planned_clip in video_director_plan.get("clip_plan", []):
                if int(planned_clip.get("clip_index") or 0) == int(clip_metadata.get("clip_index") or 0):
                    planned_clip["dialogue_assignment"] = clip_metadata.get("dialogue_assignment") or []
                    break
            shot.video_director_plan = json.dumps(video_director_plan, ensure_ascii=False)
            db.commit()
        else:
            clip_dialogues = _clip_dialogues_for_prompt(
                safe_json_list(shot.dialogues),
                clip,
                duration,
                video_director_plan.get("dialogue_timeline_source"),
            )

        reusable_prompt = (clip_metadata or {}).get("prompt_text") or ""
        if skip_llm_when_prompt_exists and not reusable_prompt:
            reusable_prompt = (
                get_semantic_clip_prompt(video_director_plan, clip)
                if clip_only_execution else _get_reusable_video_prompt(video_director_plan)
            )
        if skip_llm_when_prompt_exists and not reusable_prompt:
            task.status = "failed"
            task.error_message = "当前 Shot 没有可复用的视频最终 Prompt，请先使用 LLM+生成当前Shot视频。"
            task.current_step = "缺少视频最终 Prompt"
            if not clip_metadata:
                _mark_shot_video_failed(shot, shot_repo, task.error_message)
            db.commit()
            return
        if reusable_prompt:
            task.current_step = "复用已有 H3 视频提示词..."
            shot_prompt = reusable_prompt
            db.commit()
        else:
            task.current_step = "正在构建 H3 视频提示词..."
            if selected_mode == "MULTI_KEYFRAME" and clip.get("clip_index"):
                _update_window_plan_status(shot, int(clip.get("clip_index") or 1), "PROMPT_BUILDING", db, task=task)
            db.commit()
            shot_prompt = await build_h3_video_prompt(
                db=db,
                novel=novel,
                shot=shot,
                selected_mode=selected_mode,
                clip=clip,
                workflow_capability=workflow_capability,
                workflow_type=workflow.type,
                workflow_name=workflow.name,
                start_image_url=shot_image_url,
                keyframes=keyframes_for_prompt,
                transitions=transitions_for_prompt,
                clip_dialogues=clip_dialogues,
                reference_images=reference_images,
                character_appearances=character_appearances,
                temporal_anchors=[
                    {key: value for key, value in item.items() if key not in {"local_path", "image_url"}}
                    for item in ((temporal_manifest or {}).get("anchors") or [])
                ],
                video_reference_manifest=phase_b_manifest,
                previous_av_present=bool(
                    clip_only_execution and compiled["execution_contract"].get("previous_clip")
                ),
                current_visual_state=next((
                    item for item in video_director_plan.get("keyframes") or []
                    if isinstance(item, dict) and item.get("index") == clip.get("carry_in_state_index")
                ), None) if clip_only_execution else None,
            )
        if _is_task_cancelled(db, task):
            _cleanup_task_generated_clip_videos(db, task, shot)
            _mark_shot_video_failed(shot, shot_repo, "视频任务已取消")
            db.commit()
            return
        task.prompt_text = shot_prompt
        if selected_mode != "MULTI_KEYFRAME":
            _update_clip_prompt(shot, clip, shot_prompt, db)
        db.commit()

        task.current_step = "正在调用 ComfyUI 生成视频..."
        task.progress = 30
        seed = random.randint(1, 2**32)
        if selected_mode == "MULTI_KEYFRAME" and clip.get("clip_index"):
            _update_window_plan_status(shot, int(clip.get("clip_index") or 1), "RUNNING", db, task=task)
        db.commit()

        comfyui_service = ComfyUIService()

        def save_prompt_id(prompt_id: str, submitted_workflow: dict = None):
            task.comfyui_prompt_id = prompt_id
            if submitted_workflow:
                task.workflow_json = json.dumps(submitted_workflow, ensure_ascii=False, indent=2)
                actual_seed = extract_workflow_seed(submitted_workflow)
                task.seed = actual_seed
                if actual_seed is not None:
                    if selected_mode == "MULTI_KEYFRAME" and clip.get("clip_index"):
                        _update_window_plan(shot, int(clip.get("clip_index") or 1), {"seed": actual_seed}, db, task=task)
                    else:
                        _update_clip_result(shot, clip, {"seed": actual_seed}, db)
                if clip_only_execution and temporal_manifest is not None:
                    node_mapping = json.loads(workflow.node_mapping or "{}")
                    temporal_node_ids = [str(node_mapping.get(f"keyframe_node_{i}") or "") for i in range(1, 9)]
                    for anchor in temporal_manifest.get("anchors", []):
                        node_id = temporal_node_ids[int(anchor["slot"]) - 1]
                        node = submitted_workflow.get(node_id) if node_id else None
                        anchor["binding"] = {
                            "workflow_node_id": node_id or None,
                            "uploaded_filename": node.get("inputs", {}).get("image") if isinstance(node, dict) else None,
                        }
                    metadata = safe_json_dict(task.metadata_json)
                    contract = metadata.get("execution_contract") or {}
                    contract["temporal_anchor_manifest"] = temporal_manifest
                    metadata["execution_contract"] = contract
                    task.metadata_json = json.dumps(metadata, ensure_ascii=False)
            if selected_mode == "MULTI_KEYFRAME" and clip.get("clip_index"):
                fields = {"status": "RUNNING", "prompt_id": prompt_id}
                if submitted_workflow:
                    fields["workflow_json"] = submitted_workflow
                _update_window_plan(shot, int(clip.get("clip_index") or 1), fields, db, task=task)
            db.commit()
            print(f"[VideoTask {task_id}] Saved ComfyUI prompt_id: {prompt_id}")

        effective_node_mapping = dict(node_mapping)
        if workflow.type == "first_last_video":
            effective_node_mapping["reference_image_node_id"] = node_mapping.get("first_image_node_id")
            effective_node_mapping["keyframe_node_1"] = node_mapping.get("last_image_node_id")
        task_metadata = safe_json_dict(task.metadata_json)
        task_metadata.update({
            "megapixels_node_id": effective_node_mapping.get("megapixels_node_id"),
            "video_save_node_id": effective_node_mapping.get("video_save_node_id"),
        })
        task.metadata_json = json.dumps(task_metadata, ensure_ascii=False)
        db.commit()

        previous_video_path = url_to_local_path((clip_metadata or {}).get("previous_approved_video_url")) if clip_metadata else None
        if clip_metadata and clip_metadata.get("capability") in {"EXTEND", "VIDEO_CONTINUATION", "TEMPORAL_EXTEND"}:
            if clip_metadata.get("capability") in {"EXTEND", "TEMPORAL_EXTEND"}:
                semantic_clip = next((item for item in safe_json_dict(shot.video_director_plan).get("clip_plan", []) if int(item.get("clip_index") or 0) == int(clip_metadata.get("clip_index") or 0)), None)
                previous_provenance = (clip_metadata.get("execution_contract") or {}).get("previous_clip") or {}
                previous_provenance = resolve_extend_previous_av(
                    db, novel_id, chapter_id, shot, semantic_clip or {}, previous_provenance,
                )
                previous_video_path = previous_provenance["local_path"]
                clip_metadata["previous_approved_video_url"] = previous_provenance["result_url"]
            if not previous_video_path or not Path(previous_video_path).is_file():
                raise ValueError("PREVIOUS_AV_UNAVAILABLE" if clip_metadata.get("capability") in {"EXTEND", "TEMPORAL_EXTEND"} else "Clip continuation 缺少上一 Clip approved MP4")
            temporal_anchors = []
            if clip_metadata.get("capability") == "TEMPORAL_EXTEND":
                if not temporal_manifest or not temporal_image_paths:
                    raise ValueError("TEMPORAL_ANCHOR_UNAVAILABLE")
                temporal_anchors = [
                    {
                        "image_path": anchor["local_path"],
                        "position": anchor["frame_position"],
                    }
                    for anchor in temporal_manifest.get("anchors", [])
                ]
            result = await comfyui_service.generate_video_continuation_with_workflow(
                prompt=shot_prompt,
                workflow_json=workflow.workflow_json,
                node_mapping=node_mapping,
                previous_video_path=previous_video_path,
                duration_seconds=duration,
                filename_prefix=f"story_{novel_id}/chapter_{chapter_id[:8]}/clips/{task.id}",
                capability="VIDEO_CONTINUATION" if clip_metadata.get("capability") == "EXTEND" else clip_metadata.get("capability"),
                anchors=temporal_anchors if clip_metadata.get("capability") == "TEMPORAL_EXTEND" else [
                    anchor for anchor in safe_json_dict(shot.video_director_plan).get("temporal_anchors", [])
                    if str(anchor.get("id")) in {str(anchor_id) for anchor_id in clip_metadata.get("temporal_anchor_ids", [])}
                ],
                on_prompt_queued=save_prompt_id,
                reference_image_paths=reference_image_paths or [],
                require_native_output=(task_metadata.get("execution_contract") or {}).get("artifact_kind") == NATIVE_CONTINUITY_OUTPUT,
            )
        else:
            result = await comfyui_service.generate_shot_video_with_workflow(
            prompt=shot_prompt,
            workflow_json=workflow.workflow_json,
            node_mapping=effective_node_mapping,
            aspect_ratio=novel.aspect_ratio or "16:9",
            character_reference_path=character_reference_path,
            frame_count=frame_count,
            duration_seconds=duration,
            style=style,
            character_appearances=character_appearances,
            scene_setting=scene_setting,
                prop_appearances=prop_appearances,
                reference_audio_path=reference_audio_path,
                keyframe_paths=keyframe_paths,
                reference_image_paths=reference_image_paths,
                strict_reference_image=bool(
                    clip_metadata
                    and clip_metadata.get("execution_scope") == "CLIP"
                    and clip_metadata.get("capability") == "SINGLE_FRAME"
                ),
                seed=seed,
                on_prompt_queued=save_prompt_id
            )
        if _is_task_cancelled(db, task):
            _cleanup_task_generated_clip_videos(db, task, shot)
            _mark_shot_video_failed(shot, shot_repo, "视频任务已取消")
            db.commit()
            return

        print(f"[VideoTask {task_id}] Generation result: {json.dumps(result, ensure_ascii=True)}")

        if result.get("prompt_id"):
            task.comfyui_prompt_id = result["prompt_id"]
            print(f"[VideoTask {task_id}] Saved ComfyUI prompt_id: {result['prompt_id']}")

        if result.get("submitted_workflow"):
            task.workflow_json = json.dumps(result["submitted_workflow"], ensure_ascii=False, indent=2)
            if clip_only_execution and phase_b_manifest is not None:
                manifest_metadata = safe_json_dict(task.metadata_json)
                binding_mapping = node_mapping
                submitted = result["submitted_workflow"]
                for reference in phase_b_manifest.get("references", []):
                    node_id = binding_mapping.get(f"load_image_node_{reference['slot']}")
                    node = submitted.get(str(node_id)) if node_id is not None else None
                    filename = node.get("inputs", {}).get("image") if isinstance(node, dict) else None
                    reference["binding"] = {
                        "uploaded_filename": filename,
                        "workflow_node_id": str(node_id) if node_id is not None else None,
                    }
                manifest_metadata["video_reference_manifest"] = phase_b_manifest
                task.metadata_json = json.dumps(manifest_metadata, ensure_ascii=False)
            db.commit()
            print(f"[VideoTask {task_id}] Saved submitted workflow to task")

        if not result.get("success"):
            task.status = "failed"
            persist_task_comfyui_error(task, result)
            task.error_message = result.get("message", "生成失败")
            task.current_step = "生成失败"
            if selected_mode == "MULTI_KEYFRAME" and clip.get("clip_index"):
                _update_window_plan_status(shot, int(clip.get("clip_index") or 1), "FAILED", db, task=task)
            if not clip_only_execution:
                _mark_shot_video_failed(shot, shot_repo, task.error_message)
            if clip_metadata and clip_metadata.get("execution_scope") == "CLIP":
                failed_plan = safe_json_dict(shot.video_director_plan)
                for semantic_clip in failed_plan.get("clip_plan", []):
                    if int(semantic_clip.get("clip_index") or 0) == int(clip_metadata.get("clip_index") or 0):
                        semantic_clip["execution_status"] = "FAILED"
                        semantic_clip["error_message"] = task.error_message
                        break
                shot.video_director_plan = json.dumps(failed_plan, ensure_ascii=False)
            db.commit()
            return

        # 下载并保存视频
        await _save_generated_video(
            result, task, novel_id, chapter_id, shot_index, db, task_id, shot_repo,
            clip=clip, clip_metadata=clip_metadata,
            update_shot_result=not bool(clip_metadata),
            artifact_suffix=(f"clip_{clip_metadata.get('clip_index')}_{task.id[:8]}" if clip_only_execution else ""),
        )
        if clip_metadata and task.status == "completed" and not clip_only_execution and clip_metadata.get("approval_mode", "AUTO_APPROVE") == "AUTO_APPROVE":
            if clip_metadata.get("is_clip_regeneration") and clip_metadata.get("auto_merge", True):
                assembly_result = await merge_video_director_clip_videos(
                    db, shot, shot_repo, novel_id, chapter_id, shot_index,
                )
                if not assembly_result.get("success"):
                    task.status = "failed"
                    task.error_message = assembly_result.get("message") or "Clip 累计成片 Assembly 失败"
                    task.current_step = "Assembly 失败"
                    if not clip_only_execution:
                        _mark_shot_video_failed(shot, shot_repo, task.error_message)
                    db.commit()
            elif not clip_metadata.get("is_clip_regeneration") and not clip_only_execution:
                await _enqueue_next_clip_if_needed(db, task, shot, novel, clip_metadata)
        if selected_mode == "MULTI_KEYFRAME" and clip.get("clip_index") and not clip_only_execution:
            _update_window_plan_status(shot, int(clip.get("clip_index") or 1), "SUCCEEDED", db, task=task)

    except Exception as e:
        print(f"[VideoTask {task_id}] Error: {e}")
        import traceback
        traceback.print_exc()

        try:
            task.status = "failed"
            task.error_message = str(e)
            task.current_step = "任务异常"
            if 'shot' in locals() and shot:
                if not clip_only_execution:
                    _mark_shot_video_failed(shot, shot_repo, task.error_message)
                if clip_metadata and clip_metadata.get("execution_scope") == "CLIP":
                    failed_plan = safe_json_dict(shot.video_director_plan)
                    for semantic_clip in failed_plan.get("clip_plan", []):
                        if int(semantic_clip.get("clip_index") or 0) == int(clip_metadata.get("clip_index") or 0):
                            semantic_clip["execution_status"] = "FAILED"
                            semantic_clip["error_message"] = task.error_message
                            break
                    shot.video_director_plan = json.dumps(failed_plan, ensure_ascii=False)
            db.commit()
        except Exception:
            pass
    finally:
        db.close()


async def _generate_multi_clip_video_task(
    db,
    task,
    novel,
    shot,
    shot_repo: ShotRepository,
    novel_id: str,
    chapter_id: str,
    shot_index: int,
    shot_image_url: str,
    shot_image_path: str,
    plan_keyframes_by_index: dict,
    window_plans: list,
    video_director_plan: dict,
    style: str,
    character_appearances: dict,
    scene_setting,
    prop_appearances: dict,
    reference_audio_path: str,
    task_id: str,
    only_window_index: int | None = None,
    auto_merge_clips: bool = False,
    skip_llm_when_prompt_exists: bool = False,
):
    fps = 25
    clip_video_paths = []
    comfyui_service = ComfyUIService()
    transitions_for_prompt = video_director_plan.get("transitions") if isinstance(video_director_plan.get("transitions"), list) else []
    all_dialogues = safe_json_list(shot.dialogues)
    generated_any = False

    for clip_position, window_plan in enumerate(window_plans, 1):
        if _is_task_cancelled(db, task):
            _cleanup_task_generated_clip_videos(db, task, shot)
            _mark_shot_video_failed(shot, shot_repo, "视频任务已取消")
            db.commit()
            return
        window_index = int(window_plan.get("window_index") or clip_position)
        if only_window_index is not None and window_index != int(only_window_index):
            continue
        frame_count_setting = int(window_plan.get("selected_frame_count") or 0)
        workflow_type = "three_frame_video" if frame_count_setting == 3 else "four_frame_video"
        workflow = db.query(Workflow).filter(Workflow.type == workflow_type, Workflow.is_active == True).first()
        if not workflow:
            _update_window_plan(shot, window_index, {"status": "FAILED", "error_message": f"未配置 {workflow_type} 视频生成工作流"}, db, task=task)
            task.status = "failed"
            task.error_message = f"未配置 {workflow_type} 视频生成工作流"
            task.current_step = "缺少视频工作流"
            _mark_shot_video_failed(shot, shot_repo, task.error_message)
            db.commit()
            return
        node_mapping = json.loads(workflow.node_mapping) if workflow.node_mapping else {}

        keyframe_indexes = [int(index) for index in (window_plan.get("keyframe_indexes") or [])]
        start_keyframe = plan_keyframes_by_index.get(keyframe_indexes[0]) if keyframe_indexes else None
        if keyframe_indexes and keyframe_indexes[0] == 1 and start_keyframe and start_keyframe.get("role") == "START":
            start_image_path = shot_image_path
            start_image_url = shot_image_url
        else:
            start_image_url = start_keyframe.get("image_url") if start_keyframe else None
            start_image_path = url_to_local_path(start_image_url) if start_image_url else None
        if not start_image_path:
            _update_window_plan(shot, window_index, {"status": "FAILED", "error_message": f"Clip {window_index} 缺少起始关键帧图片"}, db, task=task)
            task.status = "failed"
            task.error_message = f"Clip {window_index} 缺少起始关键帧图片"
            task.current_step = "缺少关键帧图片"
            _mark_shot_video_failed(shot, shot_repo, task.error_message)
            db.commit()
            return

        keyframe_paths = []
        for keyframe_index in keyframe_indexes[1:]:
            keyframe = plan_keyframes_by_index.get(keyframe_index)
            image_url = keyframe.get("image_url") if keyframe else None
            keyframe_path = url_to_local_path(image_url) if image_url else None
            if not keyframe_path:
                _update_window_plan(shot, window_index, {"status": "FAILED", "error_message": f"Clip {window_index} 缺少 Keyframe {keyframe_index} 图片"}, db, task=task)
                task.status = "failed"
                task.error_message = f"Clip {window_index} 缺少 Keyframe {keyframe_index} 图片"
                task.current_step = "缺少关键帧图片"
                _mark_shot_video_failed(shot, shot_repo, task.error_message)
                db.commit()
                return
            keyframe_paths.append(keyframe_path)

        reference_images = [{"label": f"C{window_index} · KF{keyframe_indexes[0]}", "url": start_image_url}]
        for offset, keyframe_path in enumerate(keyframe_paths, 1):
            reference_images.append({"label": f"C{window_index} · KF{keyframe_indexes[offset]}", "url": _local_url_from_path(keyframe_path)})

        extension = safe_json_dict(workflow.extension)
        workflow_capability = {
            "max_clip_duration": int(extension.get("max_clip_duration") or extension.get("max_seconds") or 15),
            "frame_count": extension.get("frame_count"),
            "workflow_name": workflow.name,
        }
        clip = {
            "clip_index": window_index,
            "start_time": window_plan.get("start_time") or 0,
            "end_time": window_plan.get("end_time") or 0,
            "selected_frame_count": frame_count_setting,
            "workflow_key": window_plan.get("workflow_key"),
            "workflow_type": workflow_type,
            "keyframe_indexes": keyframe_indexes,
        }
        selected_indexes = set(keyframe_indexes)
        keyframes_for_prompt = [
            keyframe for keyframe in (video_director_plan.get("keyframes") or [])
            if isinstance(keyframe, dict) and int(keyframe.get("index") or -1) in selected_indexes
        ]
        clip_transitions_for_prompt = _filter_transitions_for_keyframe_indexes(transitions_for_prompt, keyframe_indexes)
        clip_dialogues = _clip_dialogues_for_prompt(
            all_dialogues,
            clip,
            float(shot.duration or 0),
            video_director_plan.get("dialogue_timeline_source"),
        )

        reusable_clip_prompt = (window_plan.get("prompt_text") or "").strip() if skip_llm_when_prompt_exists else ""
        if skip_llm_when_prompt_exists and not reusable_clip_prompt:
            _update_window_plan(shot, window_index, {"status": "FAILED", "error_message": "缺少可复用的 Clip 视频最终 Prompt"}, db, task=task)
            task.status = "failed"
            task.error_message = f"Clip {window_index} 没有可复用的视频最终 Prompt，请先使用 LLM+生成当前Shot视频。"
            task.current_step = "缺少视频最终 Prompt"
            _mark_shot_video_failed(shot, shot_repo, task.error_message)
            db.commit()
            return

        task.current_step = f"{'复用已有' if reusable_clip_prompt else '正在构建'} Clip {clip_position}/{len(window_plans)} H3 提示词..."
        task.progress = int(10 + ((clip_position - 1) / len(window_plans)) * 70)
        task.reference_images = json.dumps(reference_images, ensure_ascii=False)
        _update_window_plan(shot, window_index, {
            "status": "RUNNING" if reusable_clip_prompt else "PROMPT_BUILDING",
            "workflow_type": workflow_type,
            "workflow_name": workflow.name,
            "workflow_id": workflow.id,
            "megapixels_node_id": node_mapping.get("megapixels_node_id"),
            "video_save_node_id": node_mapping.get("video_save_node_id"),
            "reference_images": reference_images,
            "clip_dialogues": clip_dialogues,
            "dialogue_assignment_source": _dialogue_assignment_source(
                video_director_plan.get("dialogue_timeline_source")
            ),
            "error_message": None,
        }, db, task=task)
        db.commit()
        if reusable_clip_prompt:
            clip_prompt = reusable_clip_prompt
        else:
            try:
                clip_prompt = await build_h3_video_prompt(
                    db=db,
                    novel=novel,
                    shot=shot,
                    selected_mode="MULTI_KEYFRAME",
                    clip=clip,
                    workflow_capability=workflow_capability,
                    workflow_type=workflow_type,
                    workflow_name=workflow.name,
                    start_image_url=start_image_url,
                    keyframes=keyframes_for_prompt,
                    transitions=clip_transitions_for_prompt,
                    clip_dialogues=clip_dialogues,
                    reference_images=reference_images,
                    character_appearances=character_appearances,
                )
            except Exception as exc:
                task.status = "failed"
                task.error_message = str(exc) or "Clip H3 提示词构建失败"
                task.current_step = f"Clip {clip_position} H3 提示词构建失败"
                _update_window_plan(shot, window_index, {"status": "FAILED", "error_message": task.error_message}, db, task=task)
                _mark_shot_video_failed(shot, shot_repo, task.error_message)
                db.commit()
                return
        if _is_task_cancelled(db, task):
            _cleanup_task_generated_clip_videos(db, task, shot)
            _mark_shot_video_failed(shot, shot_repo, "视频任务已取消")
            db.commit()
            return
        task.prompt_text = clip_prompt
        _update_window_plan(shot, window_index, {"prompt_text": clip_prompt}, db, task=task)

        clip_duration = max(1, float(clip["end_time"]) - float(clip["start_time"]))
        raw_frame_count = int(fps * clip_duration)
        clip_frame_count = ((raw_frame_count // 8) * 8) + 1
        seed = random.randint(1, 2**32)

        def save_prompt_id(prompt_id: str, submitted_workflow: dict = None):
            task.comfyui_prompt_id = prompt_id
            fields = {"status": "RUNNING", "prompt_id": prompt_id}
            if submitted_workflow:
                task.workflow_json = json.dumps(submitted_workflow, ensure_ascii=False, indent=2)
                fields["workflow_json"] = submitted_workflow
                actual_seed = extract_workflow_seed(submitted_workflow)
                if actual_seed is not None:
                    fields["seed"] = actual_seed
            _update_window_plan(shot, window_index, fields, db, task=task)
            db.commit()
            print(f"[VideoTask {task_id}] Clip {clip_position} ComfyUI prompt_id: {prompt_id}")

        task.current_step = f"正在生成 Clip {clip_position}/{len(window_plans)}..."
        _update_window_plan_status(shot, window_index, "RUNNING", db, task=task)
        db.commit()
        result = await comfyui_service.generate_shot_video_with_workflow(
            prompt=clip_prompt,
            workflow_json=workflow.workflow_json,
            node_mapping=node_mapping,
            aspect_ratio=novel.aspect_ratio or "16:9",
            character_reference_path=start_image_path,
            frame_count=clip_frame_count,
            duration_seconds=clip_duration,
            style=style,
            character_appearances=character_appearances,
            scene_setting=scene_setting,
            prop_appearances=prop_appearances,
            reference_audio_path=reference_audio_path,
            keyframe_paths=keyframe_paths,
            seed=seed,
            on_prompt_queued=save_prompt_id,
        )
        if _is_task_cancelled(db, task):
            _cleanup_task_generated_clip_videos(db, task, shot)
            _mark_shot_video_failed(shot, shot_repo, "视频任务已取消")
            db.commit()
            return
        if result.get("submitted_workflow"):
            task.workflow_json = json.dumps(result["submitted_workflow"], ensure_ascii=False, indent=2)
            _update_window_plan(shot, window_index, {"workflow_json": result["submitted_workflow"]}, db, task=task)
            db.commit()
        if not result.get("success") or not result.get("video_url"):
            task.status = "failed"
            persist_task_comfyui_error(task, result)
            task.error_message = result.get("message") or "Clip 生成失败"
            task.current_step = f"Clip {clip_position} 生成失败"
            _update_window_plan(shot, window_index, {"status": "FAILED", "error_message": task.error_message}, db, task=task)
            _mark_shot_video_failed(shot, shot_repo, task.error_message)
            db.commit()
            return

        task.current_step = f"正在下载 Clip {clip_position}/{len(window_plans)}..."
        db.commit()
        local_path = await file_storage.download_video(
            url=result["video_url"],
            novel_id=novel_id,
            chapter_id=chapter_id,
            shot_number=(shot_index * 1000) + clip_position,
        )
        if _is_task_cancelled(db, task):
            if local_path:
                try:
                    path = Path(local_path)
                    if path.exists() and path.is_file():
                        path.unlink()
                except Exception as exc:
                    print(f"[VideoTask {task_id}] Failed to delete cancelled downloaded clip {local_path}: {exc}")
            _cleanup_task_generated_clip_videos(db, task, shot)
            _mark_shot_video_failed(shot, shot_repo, "视频任务已取消")
            db.commit()
            return
        if not local_path:
            task.status = "failed"
            task.error_message = f"Clip {clip_position} 下载失败"
            task.current_step = "下载失败"
            _update_window_plan(shot, window_index, {"status": "FAILED", "error_message": task.error_message}, db, task=task)
            _mark_shot_video_failed(shot, shot_repo, task.error_message)
            db.commit()
            return
        clip_video_paths.append(local_path)
        generated_any = True
        _update_window_plan(shot, window_index, {
            "status": "SUCCEEDED",
            "video_url": _local_url_from_path(local_path),
            "local_path": local_path,
            "source_video_url": result.get("video_url"),
            "error_message": None,
            "generated_at": datetime.utcnow().isoformat(),
            "generated_by_task_id": task.id,
        }, db, task=task)

    if only_window_index is not None:
        if not generated_any:
            task.status = "failed"
            task.error_message = f"未找到 Clip {only_window_index}"
            task.current_step = "执行计划无效"
            _mark_shot_video_failed(shot, shot_repo, task.error_message)
            db.commit()
            return
        if auto_merge_clips:
            merge_result = await merge_video_director_clip_videos(db, shot, shot_repo, novel_id, chapter_id, shot_index)
            if not merge_result.get("success"):
                task.status = "failed"
                task.error_message = merge_result.get("message") or "多 Clip 拼接失败"
                task.current_step = "拼接失败"
                _mark_shot_video_failed(shot, shot_repo, task.error_message)
                db.commit()
                return
            task.result_url = merge_result.get("video_url")
            _clear_shot_video_error(shot, shot_repo, video_url=merge_result.get("video_url"), video_status="completed", video_task_id=task.id)
        task.status = "completed"
        task.progress = 100
        task.current_step = "生成完成"
        task.completed_at = datetime.utcnow()
        db.commit()
        return

    task.current_step = "正在拼接多 Clip 视频..."
    task.progress = 85
    db.commit()
    if _is_task_cancelled(db, task):
        _cleanup_task_generated_clip_videos(db, task, shot)
        _mark_shot_video_failed(shot, shot_repo, "视频任务已取消")
        db.commit()
        return
    story_dir = file_storage._get_story_dir(novel_id)
    chapter_short = chapter_id[:8] if chapter_id else "unknown"
    output_dir = story_dir / f"chapter_{chapter_short}" / "videos"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = str(output_dir / f"shot_{shot_index:03d}_{timestamp}.mp4")
    merge_result = await file_storage.merge_videos(clip_video_paths, output_path)
    if _is_task_cancelled(db, task):
        try:
            output_file = Path(output_path)
            if output_file.exists() and output_file.is_file():
                output_file.unlink()
        except Exception as exc:
            print(f"[VideoTask {task_id}] Failed to delete cancelled merged video {output_path}: {exc}")
        _cleanup_task_generated_clip_videos(db, task, shot)
        _mark_shot_video_failed(shot, shot_repo, "视频任务已取消")
        db.commit()
        return
    if not merge_result.get("success"):
        task.status = "failed"
        task.error_message = merge_result.get("message") or "多 Clip 拼接失败"
        task.current_step = "拼接失败"
        _mark_shot_video_failed(shot, shot_repo, task.error_message)
        db.commit()
        return

    local_url = _local_url_from_path(output_path)
    plan = safe_json_dict(shot.video_director_plan)
    plan["merged_video_url"] = local_url
    plan["merged_at"] = datetime.utcnow().isoformat()
    shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
    _clear_shot_video_error(shot, shot_repo, video_url=local_url, video_status="completed", video_task_id=task.id)
    task.status = "completed"
    task.progress = 100
    task.result_url = local_url
    task.current_step = "生成完成"
    task.completed_at = datetime.utcnow()
    db.commit()


def _resolve_semantic_clip_assembly_units(
    db,
    shot,
    semantic_clips: list[dict],
    revision: int,
    novel_id: str,
    chapter_id: str,
) -> list[tuple[dict, Task, dict, str]]:
    """Resolve new-contract assembly inputs by exact Clip-owned provenance."""
    units = []
    seen_task_ids = set()
    for semantic_clip in sorted(semantic_clips, key=lambda item: int(item.get("clip_index") or 0)):
        clip_index = int(semantic_clip.get("clip_index") or 0)
        task_id = str(semantic_clip.get("generated_by_task_id") or "")
        result_url = str(semantic_clip.get("video_url") or "")
        if not task_id or not result_url:
            raise ValueError(f"缺少 Clip {clip_index} 的冻结执行 provenance")
        if task_id in seen_task_ids:
            raise ValueError(f"Clip {clip_index} 与其他 Clip 重复使用 Task {task_id}")
        seen_task_ids.add(task_id)
        task, metadata, local_path = validate_semantic_clip_artifact(
            db, shot, semantic_clip, revision, novel_id, chapter_id,
        )
        units.append((semantic_clip, task, metadata, local_path))
    if not units:
        raise ValueError("semantic Clip Plan 没有可合并的视频")
    return units


def validate_semantic_clip_artifact(
    db,
    shot,
    semantic_clip: dict,
    revision: int,
    novel_id: str,
    chapter_id: str,
) -> tuple[Task, dict, str]:
    """Validate one reusable semantic Clip artifact for assembly or Batch reuse."""
    clip_index = int(semantic_clip.get("clip_index") or 0)
    task_id = str(semantic_clip.get("generated_by_task_id") or "")
    result_url = str(semantic_clip.get("video_url") or "")
    task = db.query(Task).filter(Task.id == task_id).first() if task_id else None
    metadata = safe_json_dict(task.metadata_json) if task else {}
    contract = metadata.get("execution_contract") or {}
    contract_clip = contract.get("clip") or {}
    valid = (
        task
        and task.type == "shot_video"
        and task.status == "completed"
        and task.novel_id == novel_id
        and task.chapter_id == chapter_id
        and task.shot_id == shot.id
        and task.result_url == result_url
        and metadata.get("execution_scope") == "CLIP"
        and is_clip_execution_contract(contract)
        and contract.get("capability") == semantic_clip.get("capability")
        and metadata.get("approval_status") == "APPROVED"
        and str(metadata.get("clip_id") or "") == f"{shot.id}:clip:{clip_index}"
        and int(metadata.get("clip_index") or 0) == clip_index
        and int(metadata.get("clip_plan_revision") or 0) == int(revision)
        and str(contract_clip.get("clip_id") or "") == f"{shot.id}:clip:{clip_index}"
        and int(contract_clip.get("clip_index") or 0) == clip_index
        and int(contract_clip.get("clip_plan_revision") or 0) == int(revision)
        and str(semantic_clip.get("execution_status") or "").upper() in {"APPROVED", "SUCCEEDED"}
    )
    if not valid:
        raise ValueError(f"Clip {clip_index} 的 Task provenance 与 semantic Clip 不匹配")
    local_path = url_to_local_path(result_url)
    if not local_path or not Path(local_path).is_file() or not os.access(local_path, os.R_OK):
        raise ValueError(f"Clip {clip_index} 的 artifact 不可读取")
    if contract.get("capability") in CONTINUOUS_CAPABILITIES:
        physical = validate_native_output(metadata, result_url, local_path)
        if semantic_clip.get("physical_output") != physical:
            raise ValueError("NATIVE_CONTINUITY_OUTPUT_INVALID")
    return task, metadata, local_path


def _continuous_assembly_projection(db, shot, units, novel_id, chapter_id) -> dict:
    projected = []
    for clip, task, metadata, path in units:
        contract = metadata.get("execution_contract") or {}
        capability = contract.get("capability")
        if capability in CONTINUOUS_CAPABILITIES:
            # Revalidate the frozen Previous against its current approved Task;
            # old raw files, changed bytes and stale predecessors cannot assemble.
            resolve_extend_previous_av(db, novel_id, chapter_id, shot, clip, contract.get("previous_clip"))
            physical = validate_native_output(metadata, task.result_url, path)
        else:
            physical = probe_clip_av(path)
        projected.append({"task_id": task.id, "path": path, "capability": capability,
                          "physical_output": physical})
    return continuous_assembly_spans(projected)


async def merge_video_director_clip_videos(db, shot, shot_repo: ShotRepository, novel_id: str, chapter_id: str, shot_index: int) -> dict:
    plan = safe_json_dict(shot.video_director_plan)
    semantic_clips = plan.get("clip_plan") if isinstance(plan.get("clip_plan"), list) else []
    if semantic_clips:
        revision = int(plan.get("clip_plan_revision") or 0)
        semantic_provenance = bool(plan.get("canonical_visual_plan")) or any(
            item.get("generated_by_task_id") or item.get("capability") in CONTINUOUS_CAPABILITIES
            for item in semantic_clips if isinstance(item, dict)
        )
        if semantic_provenance:
            try:
                assembly_units = _resolve_semantic_clip_assembly_units(
                    db, shot, semantic_clips, revision, novel_id, chapter_id,
                )
            except ValueError as exc:
                return {"success": False, "message": str(exc)}
            approved_clips = list(assembly_units)
            exact_semantic_sources = True
        else:
            approved_clips = []
            missing_clips = []
            for semantic_clip in sorted(semantic_clips, key=lambda item: int(item.get("clip_index") or 0)):
                clip_index = int(semantic_clip.get("clip_index") or 0)
                task = db.query(Task).filter(
                    Task.type == "shot_video",
                    Task.shot_id == shot.id,
                    Task.metadata_json.like(f'%%"clip_index": {clip_index}%%'),
                    Task.metadata_json.like(f'%%"clip_plan_revision": {revision}%%'),
                    Task.status == "completed",
                ).order_by(Task.created_at.desc()).first()
                metadata = safe_json_dict(task.metadata_json) if task else {}
                if not task or metadata.get("approval_status") != "APPROVED" or not task.result_url:
                    missing_clips.append(f"C{clip_index}")
                    continue
                local_path = url_to_local_path(task.result_url)
                if not local_path or not Path(local_path).is_file():
                    missing_clips.append(f"C{clip_index}")
                    continue
                approved_clips.append((semantic_clip, task, metadata, local_path))

            if missing_clips:
                return {"success": False, "message": f"缺少已批准的 semantic Clip 视频：{', '.join(missing_clips)}"}
            if not approved_clips:
                return {"success": False, "message": "semantic Clip Plan 没有可合并的视频"}

            # Historical plans without frozen Clip provenance retain the old
            # continuation-collapse behavior as a small local compatibility path.
            continuation_capabilities = {"VIDEO_CONTINUATION", "TEMPORAL_EXTEND"}
            assembly_units = []
            pending_base = None
            continuation_run = []
            for approved_clip in approved_clips:
                if approved_clip[2].get("capability") in continuation_capabilities:
                    if pending_base:
                        continuation_run.append(pending_base)
                        pending_base = None
                    continuation_run.append(approved_clip)
                    continue
                if continuation_run:
                    assembly_units.append(continuation_run[-1])
                    continuation_run = []
                if pending_base:
                    assembly_units.append(pending_base)
                pending_base = approved_clip
            if continuation_run:
                assembly_units.append(continuation_run[-1])
            elif pending_base:
                assembly_units.append(pending_base)
            exact_semantic_sources = False
        clip_video_paths = [item[3] for item in assembly_units]
        continuity_projection = None
        if exact_semantic_sources and any(
            (item[2].get("execution_contract") or {}).get("capability") in CONTINUOUS_CAPABILITIES
            for item in assembly_units
        ):
            try:
                continuity_projection = _continuous_assembly_projection(db, shot, assembly_units, novel_id, chapter_id)
            except ValueError as exc:
                return {"success": False, "message": str(exc)}

        story_dir = file_storage._get_story_dir(novel_id)
        chapter_short = chapter_id[:8] if chapter_id else "unknown"
        output_dir = story_dir / f"chapter_{chapter_short}" / "videos"
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        final_unit = assembly_units[-1]
        direct_continuation_result = (
            not exact_semantic_sources
            and len(assembly_units) == 1
            and final_unit[2].get("capability") in {"VIDEO_CONTINUATION", "TEMPORAL_EXTEND"}
        )
        if direct_continuation_result:
            local_url = final_unit[1].result_url
            assembled_media_duration = _probe_video_duration(final_unit[3])
            final_metadata = dict(final_unit[2])
            final_metadata.update({
                "assembled_result": {
                    "status": "APPROVED",
                    "url": local_url,
                    "assembled_media_duration": assembled_media_duration,
                    "clip_plan_revision": revision,
                    "clip_index": int(final_unit[0].get("clip_index") or 0),
                    "task_id": final_unit[1].id,
                    "assembled_at": datetime.utcnow().isoformat(),
                },
                "assembled_media_duration": assembled_media_duration,
                "actual_duration": None,
            })
            final_unit[1].metadata_json = json.dumps(final_metadata, ensure_ascii=False)
        else:
            output_path = Path(output_dir / f"shot_{shot_index:03d}_assembled_{timestamp}.mp4")
            temporary_output = output_path.with_suffix(".assembling.mp4")
            if continuity_projection:
                merge_result = await file_storage.merge_continuous_clip_spans(continuity_projection, str(temporary_output))
            else:
                merge_result = await file_storage.merge_videos(clip_video_paths, str(temporary_output))
            if not merge_result.get("success") or not temporary_output.is_file():
                if temporary_output.exists():
                    temporary_output.unlink()
                return {"success": False, "message": merge_result.get("message") or "semantic Clip 拼接失败"}
            os.replace(temporary_output, output_path)
            local_url = _local_url_from_path(str(output_path))
            assembled_media_duration = _probe_video_duration(str(output_path))
        plan.update({
            "merged_video_url": local_url,
            "merged_at": datetime.utcnow().isoformat(),
            "assembly_status": "COMPLETED",
            "assembly_clip_plan_revision": revision,
            "assembly_task_ids": [item[1].id for item in assembly_units],
            "assembly_mode": "NATIVE_OVERLAP_REPLACEMENT" if continuity_projection else "CONTINUATION_COLLAPSED" if len(assembly_units) < len(approved_clips) else "CONCAT",
            "assembled_result": {
                "status": "COMPLETED",
                "url": local_url,
                "clip_plan_revision": revision,
                "clip_indexes": [int(item[0].get("clip_index") or 0) for item in assembly_units],
                "task_ids": [item[1].id for item in assembly_units],
                "assembled_media_duration": assembled_media_duration,
                "assembled_at": datetime.utcnow().isoformat(),
            },
        })
        if continuity_projection:
            plan["assembly_spans"] = {
                "frame_count": continuity_projection["frame_count"],
                "duration": continuity_projection["duration"],
                "boundaries": continuity_projection["boundaries"],
                "spans": [{k: v for k, v in span.items() if k != "physical_output"}
                          for span in continuity_projection["spans"]],
            }
        if direct_continuation_result:
            plan["assembled_result"].update({
                "clip_indexes": [int(final_unit[0].get("clip_index") or 0)],
                "task_ids": [final_unit[1].id],
            })
            for semantic_clip in plan.get("clip_plan", []):
                if int(semantic_clip.get("clip_index") or 0) == int(final_unit[0].get("clip_index") or 0):
                    semantic_clip["assembled_result"] = plan["assembled_result"]
                    semantic_clip["assembled_media_duration"] = assembled_media_duration
                    semantic_clip["actual_duration"] = None
                    break
        shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
        _clear_shot_video_error(shot, shot_repo, video_url=local_url, video_status="completed", video_task_id=None)
        db.commit()
        return {"success": True, "video_url": local_url, "plan": plan}

    window_plans = plan.get("window_plans") if isinstance(plan.get("window_plans"), list) else []
    if not window_plans:
        return {"success": False, "message": "缺少 Clip 执行计划"}

    clip_video_paths = []
    missing_clips = []
    for position, window_plan in enumerate(sorted(window_plans, key=lambda item: int(item.get("window_index") or 0)), 1):
        window_index = int(window_plan.get("window_index") or position)
        local_path = window_plan.get("local_path")
        if not local_path and window_plan.get("video_url"):
            local_path = url_to_local_path(window_plan.get("video_url"))
        if not local_path:
            missing_clips.append(f"C{window_index}")
            continue
        clip_video_paths.append(local_path)

    if missing_clips:
        return {"success": False, "message": f"缺少 Clip 视频：{', '.join(missing_clips)}"}

    merged_at = _parse_iso_datetime(plan.get("merged_at"))
    latest_clip_generated_at = max(
        (_parse_iso_datetime(window_plan.get("generated_at")) for window_plan in window_plans if isinstance(window_plan, dict)),
        default=None,
    )
    existing_video_url = plan.get("merged_video_url") or shot.video_url
    if existing_video_url and merged_at and (not latest_clip_generated_at or latest_clip_generated_at <= merged_at):
        return {"success": True, "video_url": existing_video_url, "plan": plan, "skipped": True}

    story_dir = file_storage._get_story_dir(novel_id)
    chapter_short = chapter_id[:8] if chapter_id else "unknown"
    output_dir = story_dir / f"chapter_{chapter_short}" / "videos"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = str(output_dir / f"shot_{shot_index:03d}_{timestamp}.mp4")
    merge_result = await file_storage.merge_videos(clip_video_paths, output_path)
    if not merge_result.get("success"):
        return merge_result

    local_url = _local_url_from_path(output_path)
    plan["merged_video_url"] = local_url
    plan["merged_at"] = datetime.utcnow().isoformat()
    shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
    _clear_shot_video_error(shot, shot_repo, video_url=local_url, video_status="completed", video_task_id=None)
    db.commit()
    return {"success": True, "video_url": local_url, "plan": plan}


async def _enqueue_next_clip_if_needed(db, completed_task, shot, novel, clip_metadata: dict) -> None:
    clips = safe_json_dict(shot.video_director_plan).get("clip_plan") or []
    current_index = int(clip_metadata.get("clip_index") or 0)
    next_clip = next((clip for clip in clips if int(clip.get("clip_index") or 0) == current_index + 1), None)
    if not next_clip:
        if clip_metadata.get("auto_merge", True):
            assembly_result = await merge_video_director_clip_videos(
                db, shot, ShotRepository(db), completed_task.novel_id,
                completed_task.chapter_id, int(shot.index or 0),
            )
            if not assembly_result.get("success"):
                completed_task.status = "failed"
                completed_task.error_message = assembly_result.get("message") or "Semantic Shot Final Assembly 失败"
                completed_task.current_step = "Assembly 失败"
                _mark_shot_video_failed(shot, ShotRepository(db), completed_task.error_message)
                failed_metadata = safe_json_dict(completed_task.metadata_json)
                failed_metadata["approval_status"] = "FAILED"
                completed_task.metadata_json = json.dumps(failed_metadata, ensure_ascii=False)
                db.commit()
        return
    next_capability = next_clip.get("capability") or "VIDEO_CONTINUATION"
    workflow_type = "video"
    if next_capability in {"VIDEO_CONTINUATION", "TEMPORAL_EXTEND"}:
        workflow_type = next_capability
    workflow = db.query(Workflow).filter(Workflow.type == workflow_type, Workflow.is_active == True).first()
    if not workflow:
        completed_task.error_message = f"下一 Clip 缺少 {workflow_type} Workflow"
        db.commit()
        return
    existing = db.query(Task).filter(
        Task.type == "shot_video",
        Task.shot_id == shot.id,
        Task.metadata_json.like(f'%"clip_id": "{shot.id}:clip:{next_clip.get("clip_index")}"%'),
        Task.metadata_json.like(f'%"clip_plan_revision": {safe_json_dict(shot.video_director_plan).get("clip_plan_revision", 1)}%'),
        Task.status.in_(["pending", "running", "completed"]),
    )
    # A forced batch rerun must not reuse a completed Clip from an older run.
    # The current batch parent identifies the execution chain being rebuilt.
    batch_parent_task_id = clip_metadata.get("batch_parent_task_id")
    if batch_parent_task_id:
        existing = existing.filter(
            Task.metadata_json.like(f'%"batch_parent_task_id": "{batch_parent_task_id}"%')
        )
    existing = existing.first()
    if existing:
        return
    metadata = {
        "execution_scope": "CLIP",
        "clip_id": f"{shot.id}:clip:{next_clip.get('clip_index')}",
        "clip_index": next_clip.get("clip_index"),
        "clip_plan_revision": safe_json_dict(shot.video_director_plan).get("clip_plan_revision", 1),
        "capability": next_capability,
        "planned_duration": next_clip.get("planned_duration"),
        "requested_duration": next_clip.get("planned_duration"),
        "previous_approved_task_id": completed_task.id,
        "previous_approved_video_url": (
            safe_json_dict(completed_task.metadata_json).get("assembled_result", {}).get("url")
            or completed_task.result_url
        ),
        "previous_approved_video_source": (
            "approved_assembled_result"
            if safe_json_dict(completed_task.metadata_json).get("assembled_result", {}).get("url")
            else "approved_clip_result"
        ),
        "batch_parent_task_id": clip_metadata.get("batch_parent_task_id"),
        "approval_mode": "AUTO_APPROVE",
        "approval_status": "GENERATING",
        "prompt_text": next_clip.get("prompt_text") or "",
        "dialogue_assignment": next_clip.get("dialogue_assignment") or [],
        "temporal_anchor_ids": next_clip.get("temporal_anchor_ids") or [],
    }
    next_task = Task(
        type="shot_video",
        status="pending",
        name=f"生成视频 Clip: 镜{shot.index} · C{next_clip.get('clip_index')}",
        description=f"自动生成 Shot {shot.index} 的下一 Clip",
        novel_id=completed_task.novel_id,
        chapter_id=completed_task.chapter_id,
        shot_id=shot.id,
        parent_task_id=clip_metadata.get("batch_parent_task_id"),
        workflow_id=workflow.id,
        workflow_name=workflow.name,
        metadata_json=json.dumps(metadata, ensure_ascii=False),
        prompt_text=metadata["prompt_text"] or None,
    )
    db.add(next_task)
    db.commit()
    enqueue_shot_video_task(
        next_task.id,
        completed_task.novel_id,
        completed_task.chapter_id,
        shot.index,
        workflow.id,
        shot.image_url or "",
        selected_mode="SINGLE_FRAME",
        clip_metadata=metadata,
    )


async def _save_generated_video(
    result: dict, task, novel_id: str, chapter_id: str,
    shot_index: int, db, task_id: str, shot_repo: ShotRepository, clip: dict | None = None,
    clip_metadata: dict | None = None,
    update_shot_result: bool = True,
    artifact_suffix: str = "",
):
    """下载并保存生成的视频"""
    task.current_step = "正在下载生成的视频..."
    task.progress = 80
    db.commit()

    video_url = result.get("video_url")
    contract = (safe_json_dict(task.metadata_json).get("execution_contract") or {})
    native_clip = bool(safe_json_dict(task.metadata_json).get("execution_scope") == "CLIP" and contract.get("capability") in CONTINUOUS_CAPABILITIES)
    if native_clip and (result.get("physical_output_role") != NATIVE_CONTINUITY_OUTPUT or result.get("output_node_id") != "65"):
        task.status = "failed"
        task.error_message = "NATIVE_CONTINUITY_OUTPUT_UNAVAILABLE"
        task.current_step = "Clip native output missing"
        metadata = safe_json_dict(task.metadata_json)
        metadata["approval_status"] = "FAILED"
        task.metadata_json = json.dumps(metadata, ensure_ascii=False)
        db.commit()
        return
    if not video_url:
        task.status = "failed"
        task.error_message = "未获取到视频URL"
        task.current_step = "生成失败"
        shot = shot_repo.get_by_chapter_and_index(chapter_id, shot_index)
        if shot and update_shot_result:
            _mark_shot_video_failed(shot, shot_repo, task.error_message)
        db.commit()
        return

    local_path = await file_storage.download_video(
        url=video_url,
        novel_id=novel_id,
        chapter_id=chapter_id,
        shot_number=shot_index,
        filename_suffix=artifact_suffix,
    )
    db.refresh(task)
    if task.status == "cancelled":
        if local_path:
            try:
                path = Path(local_path)
                if path.exists() and path.is_file():
                    path.unlink()
            except Exception as exc:
                print(f"[VideoTask {task_id}] Failed to delete cancelled downloaded video {local_path}: {exc}")
        shot = shot_repo.get_by_chapter_and_index(chapter_id, shot_index)
        if shot and update_shot_result:
            _mark_shot_video_failed(shot, shot_repo, "视频任务已取消")
        db.commit()
        return

    if local_path:
        relative_path = local_path.replace(str(file_storage.base_dir), "").replace("\\", "/")
        local_url = f"/api/files/{relative_path.lstrip('/')}"

        physical_output = None
        if native_clip:
            try:
                mux_evidence = await preserve_native_av(result, local_path)
                db.refresh(task)
                if task.status == "cancelled":
                    Path(local_path).unlink(missing_ok=True)
                    return
                physical_output = continuity_output_metadata(result, contract, local_path, local_url)
            except ValueError as exc:
                Path(local_path).unlink(missing_ok=True)
                db.refresh(task)
                if task.status == "cancelled":
                    return
                task.status = "failed"
                task.error_message = str(exc)
                task.current_step = "Clip native output invalid"
                metadata = safe_json_dict(task.metadata_json)
                metadata["approval_status"] = "FAILED"
                task.metadata_json = json.dumps(metadata, ensure_ascii=False)
                db.commit()
                return
            metadata = safe_json_dict(task.metadata_json)
            metadata["native_av_mux"] = mux_evidence
            metadata["physical_output"] = physical_output
            metadata["artifact_kind"] = NATIVE_CONTINUITY_OUTPUT
            task.metadata_json = json.dumps(metadata, ensure_ascii=False)

        # 更新 Shot 记录中的视频数据
        shot = shot_repo.get_by_chapter_and_index(chapter_id, shot_index)
        if shot:
            result_fields = {
                "status": "SUCCEEDED",
                "video_url": local_url,
                "local_path": local_path,
                "source_video_url": video_url,
                "generated_at": datetime.utcnow().isoformat(),
                "generated_by_task_id": task.id,
            }
            if physical_output:
                result_fields["physical_output"] = physical_output
            if clip_metadata:
                plan = safe_json_dict(shot.video_director_plan)
                semantic_clips = plan.get("clip_plan") if isinstance(plan.get("clip_plan"), list) else []
                semantic_clip = next((
                    item for item in semantic_clips
                    if int(item.get("clip_index") or 0) == int(clip_metadata.get("clip_index") or 0)
                ), None)
                if (
                    int(plan.get("clip_plan_revision") or 0) != int(clip_metadata.get("clip_plan_revision") or 0)
                    or not semantic_clip
                ):
                    try:
                        Path(local_path).unlink(missing_ok=True)
                    except Exception:
                        pass
                    task.status = "failed"
                    task.error_message = "Clip 计划 revision 已变化，生成结果未写入新的 Clip Plan"
                    task.current_step = "Clip 计划已变化"
                    metadata = safe_json_dict(task.metadata_json)
                    metadata["approval_status"] = "FAILED"
                    task.metadata_json = json.dumps(metadata, ensure_ascii=False)
                    db.commit()
                    return
                canonical_replacement = (
                    plan.get("canonical_visual_plan") is True
                    and is_clip_execution_contract(safe_json_dict(task.metadata_json).get("execution_contract") or {})
                )
                if canonical_replacement:
                    clip_index = int(clip_metadata.get("clip_index") or 0)
                    affected = canonical_clip_dependency_closure(plan, {clip_index})
                    try:
                        ensure_no_active_canonical_clip_tasks(
                            db, shot.id, plan, affected, exclude_task_ids={task.id},
                        )
                    except CanonicalExecutionConflict as exc:
                        try:
                            Path(local_path).unlink(missing_ok=True)
                        except Exception:
                            pass
                        task.status = "failed"
                        task.error_message = str(exc)
                        task.current_step = "Clip recovery conflict"
                        metadata = safe_json_dict(task.metadata_json)
                        metadata["approval_status"] = "FAILED"
                        task.metadata_json = json.dumps(metadata, ensure_ascii=False)
                        db.commit()
                        return
                semantic_clip.update(result_fields)
                semantic_clip["execution_status"] = "APPROVED"
                shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
                if canonical_replacement:
                    invalidate_current_canonical_execution(
                        shot, {int(clip_metadata.get("clip_index") or 0)},
                        preserve_clip_indexes={int(clip_metadata.get("clip_index") or 0)},
                    )
                else:
                    db.commit()
            else:
                _update_clip_result(shot, clip or {}, result_fields, db)
            if update_shot_result:
                _clear_shot_video_error(shot, shot_repo, video_url=local_url, video_status="completed")
            print(f"[VideoTask {task_id}] Shot video updated: {local_url}")

        task.status = "completed"
        task.progress = 100
        task.result_url = local_url
        task.current_step = "生成完成"
        task.completed_at = datetime.utcnow()
        metadata = safe_json_dict(task.metadata_json)
        if metadata.get("execution_scope") == "CLIP":
            media_duration = _probe_video_duration(local_path)
            semantic_clip_only = (
                metadata.get("execution_scope") == "CLIP"
                and (metadata.get("execution_contract") or {}).get("artifact_kind") == "CLIP_ONLY"
            )
            if metadata.get("capability") in {"VIDEO_CONTINUATION", "TEMPORAL_EXTEND"} and not semantic_clip_only and not native_clip:
                metadata["assembled_result"] = {
                    "status": "APPROVED",
                    "url": local_url,
                    "assembled_media_duration": media_duration,
                    "clip_plan_revision": metadata.get("clip_plan_revision"),
                    "clip_index": metadata.get("clip_index"),
                    "task_id": task.id,
                    "assembled_at": datetime.utcnow().isoformat(),
                }
            metadata.update({
                "requested_duration": metadata.get("requested_duration"),
                "actual_duration": None if native_clip else media_duration if metadata.get("capability") not in {"VIDEO_CONTINUATION", "TEMPORAL_EXTEND"} or semantic_clip_only else None,
                "assembled_media_duration": media_duration if metadata.get("assembled_result") else None,
                "actual_fps": 24,
                "approval_status": "APPROVED",
            })
            task.metadata_json = json.dumps(metadata, ensure_ascii=False)
            if metadata.get("assembled_result"):
                shot = shot_repo.get_by_chapter_and_index(chapter_id, shot_index)
                if shot:
                    plan = safe_json_dict(shot.video_director_plan)
                    for semantic_clip in plan.get("clip_plan", []):
                        if int(semantic_clip.get("clip_index") or 0) == int(metadata.get("clip_index") or 0):
                            semantic_clip["assembled_result"] = metadata["assembled_result"]
                            semantic_clip["assembled_media_duration"] = metadata["assembled_media_duration"]
                            semantic_clip["actual_duration"] = metadata["actual_duration"]
                            break
                    shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
        db.commit()

        print(f"[VideoTask {task_id}] Video saved: {local_url}")
    else:
        task.status = "failed"
        task.error_message = "下载视频失败"
        task.current_step = "下载失败"
        shot = shot_repo.get_by_chapter_and_index(chapter_id, shot_index)
        if shot and update_shot_result:
            _mark_shot_video_failed(shot, shot_repo, task.error_message)
        db.commit()
