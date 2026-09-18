"""
分镜视频生成服务

封装分镜视频生成的后台任务逻辑
"""
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.models.novel import Novel, Chapter
from app.models.task import Task
from app.models.workflow import Workflow
from app.core.database import SessionLocal
from app.services.comfyui import ComfyUIService
from app.services.comfyui.service import is_h3_workflow
from app.services.duration_contract import audio_required_duration as contract_audio_required_duration, clip_duration as contract_clip_duration, legal_h3_frame_count, visual_required_duration
from app.services.file_storage import file_storage
from app.services.video_director_plan_service import VideoDirectorPlanService
from app.utils.path_utils import local_path_to_url, url_to_local_path
from app.repositories.shot_repository import ShotRepository
from app.services.background_workers import worker_manager
from app.services.video_director_ai import (
    build_h3_video_prompt, prepare_h3_prompt, resolve_h3_prompt_subjects, safe_json_dict, safe_json_list,
)
from app.services.h3_prompt_validation import H3PromptValidationError, prompt_digest


def _filter_transitions_for_keyframe_indexes(transitions: list, keyframe_indexes: list) -> list:
    index_set = {int(index) for index in keyframe_indexes or []}
    return [
        transition for transition in transitions or []
        if isinstance(transition, dict)
        and int(transition.get("from_keyframe_index") or -1) in index_set
        and int(transition.get("to_keyframe_index") or -1) in index_set
    ]


def _to_float_or_none(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _resolved_duration_from_plan(shot, video_director_plan: dict) -> float:
    visual = visual_required_duration(shot)
    audio_timeline = video_director_plan.get("audio_timeline") if isinstance(video_director_plan.get("audio_timeline"), dict) else {}
    audio = contract_audio_required_duration(audio_timeline.get("audio_required_duration"))
    if audio > 0:
        return round(max(visual, audio), 3)
    if audio_timeline.get("resolved_duration") is not None:
        return round(max(visual, float(audio_timeline.get("resolved_duration") or 0)), 3)
    return visual


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


def _clip_dialogues_for_prompt(dialogues: list, clip: dict, shot_duration: float) -> list:
    if not dialogues:
        return []
    clip_start = _to_float_or_none(clip.get("start_time")) or 0
    clip_end = _to_float_or_none(clip.get("end_time")) or shot_duration or clip_start
    if clip_end <= clip_start:
        return dialogues

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


def _sync_task_video_director_clips(task, window_plans: list) -> None:
    if task is not None and not hasattr(task, "_video_execution"):
        task.video_director_clips = json.dumps(window_plans, ensure_ascii=False)


def _mutate_video_plan(db, shot, mutator):
    if hasattr(shot, "_execution_task_id"):
        from app.services.shot_video_execution import mutate_private_plan
        return mutate_private_plan(db, shot, mutator)
    return VideoDirectorPlanService(db).mutate(shot.id, mutator)


def _refresh_video_shot(db, shot):
    if hasattr(shot, "_execution_task_id"):
        from app.services.shot_video_execution import refresh_private_shot
        refresh_private_shot(db, shot)
    else:
        db.refresh(shot)


def _update_window_plan(shot, window_index: int, fields: dict, db, task=None) -> None:
    def mutate(plan: dict) -> dict:
        window_plans = plan.get("window_plans") if isinstance(plan.get("window_plans"), list) else []
        for window_plan in window_plans:
            if isinstance(window_plan, dict) and int(window_plan.get("window_index") or 0) == int(window_index):
                window_plan.update(fields)
                if fields.get("status") == "SUCCEEDED":
                    window_plan.pop("h3_prompt_gate_failed", None)
                break
        plan["window_plans"] = window_plans
        _sync_task_video_director_clips(task, window_plans)
        return plan

    _mutate_video_plan(db, shot, mutate)


def _update_window_plan_status(shot, window_index: int, status: str, db, task=None) -> None:
    _update_window_plan(shot, window_index, {"status": status}, db, task=task)


def _update_clip_prompt(shot, clip: dict, prompt_text: str, db) -> None:
    if hasattr(shot, "_execution_task_id"):
        _update_clip_result(shot, clip, {"prompt_text": prompt_text}, db)
        return
    VideoDirectorPlanService(db).patch_clip_prompt(shot.id, "clips", int((clip or {}).get("clip_index") or 1), prompt_text)


def _update_clip_result(shot, clip: dict, fields: dict, db) -> None:
    def mutate(plan: dict) -> dict:
        clips = plan.get("clips") if isinstance(plan.get("clips"), list) else []
        clip_index = int((clip or {}).get("clip_index") or 1)
        clip_start = (clip or {}).get("start_time", 0)
        clip_end = (clip or {}).get("end_time")
        for index, existing_clip in enumerate(clips):
            if isinstance(existing_clip, dict) and int(existing_clip.get("clip_index") or index + 1) == clip_index:
                existing_clip.update(fields)
                break
        else:
            clips.append({"clip_index": clip_index, "start_time": clip_start, "end_time": clip_end, **fields})
        plan["clips"] = clips
        return plan

    _mutate_video_plan(db, shot, mutate)


def _mark_shot_video_failed(shot, shot_repo: ShotRepository, message: str):
    if hasattr(shot, "_execution_task_id"):
        from app.services.shot_video_execution import fail_execution
        fail_execution(shot_repo.db, shot._video_execution, message)
        return shot
    VideoDirectorPlanService(shot_repo.db).mutate(
        shot.id,
        lambda plan: {**plan, "task_error_message": message, "error_message": message},
    )
    return shot_repo.update(shot, video_status="failed")


def _clear_shot_video_error(shot, shot_repo: ShotRepository, **fields):
    if hasattr(shot, "_execution_task_id"):
        raise RuntimeError("Private video results require the execution publication CAS")
    def mutate(plan: dict) -> dict:
        plan.pop("task_error_message", None)
        plan.pop("error_message", None)
        return plan

    VideoDirectorPlanService(shot_repo.db).mutate(shot.id, mutate)
    return shot_repo.update(shot, **fields)


def _is_task_cancelled(db, task) -> bool:
    db.refresh(task)
    return task.status == "cancelled"


def _cleanup_task_generated_clip_videos(db, task, shot) -> None:
    if hasattr(shot, "_execution_task_id"):
        return
    def mutate(plan: dict) -> dict:
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
            plan["window_plans"] = window_plans
            _sync_task_video_director_clips(task, window_plans)
        return plan

    _mutate_video_plan(db, shot, mutate)


def _reset_multi_clip_window_plans_for_task(db, task, shot, only_window_index: int | None = None, preserve_prompt_text: bool = False) -> list:
    latest_window_plans = []
    reset_keys = [
        "prompt_id",
        "workflow_json",
        "video_url",
        "local_path",
        "source_video_url",
        "generated_at",
        "generated_by_task_id",
        "error_message",
    ]
    if not preserve_prompt_text:
        reset_keys.insert(1, "prompt_text")
    def mutate(plan: dict) -> dict:
        nonlocal latest_window_plans
        window_plans = plan.get("window_plans") if isinstance(plan.get("window_plans"), list) else []
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
        latest_window_plans = window_plans
        plan["window_plans"] = window_plans
        _sync_task_video_director_clips(task, window_plans)
        return plan

    _mutate_video_plan(db, shot, mutate)
    return latest_window_plans


def _local_url_from_path(path: str) -> str:
    relative_path = path.replace(str(file_storage.base_dir), "").replace("\\", "/")
    return f"/api/files/{relative_path.lstrip('/')}"


def _find_window_plan_for_clip(video_director_plan: dict, clip: dict) -> dict | None:
    window_index = int((clip or {}).get("clip_index") or 1)
    for key in ("window_plans", "execution_windows", "clips"):
        windows = video_director_plan.get(key) if isinstance(video_director_plan.get(key), list) else []
        for window_plan in windows:
            if not isinstance(window_plan, dict):
                continue
            plan_index = int(window_plan.get("window_index") or window_plan.get("clip_index") or 0)
            if plan_index == window_index:
                return window_plan
    return None


def _clip_audio_matches_plan_timeline(window_plan: dict, video_director_plan: dict) -> bool:
    audio_timeline = video_director_plan.get("audio_timeline") if isinstance(video_director_plan.get("audio_timeline"), dict) else {}
    if not audio_timeline:
        return False
    bound_id = window_plan.get("audio_timeline_id") or window_plan.get("audioTimelineId")
    bound_revision = window_plan.get("audio_timeline_revision") or window_plan.get("audioTimelineRevision")
    bound_hash = window_plan.get("audio_timeline_hash") or window_plan.get("audioTimelineHash")
    timeline_hash = audio_timeline.get("source_hash") or audio_timeline.get("generated_from_hash") or audio_timeline.get("generatedFromHash")
    if bound_id != audio_timeline.get("id"):
        return False
    if int(bound_revision or 0) != int(audio_timeline.get("revision") or 0):
        return False
    if timeline_hash and bound_hash != timeline_hash:
        return False
    return True


def _resolve_audio_drive_for_h3(video_director_plan: dict, clip: dict, node_mapping: dict) -> dict:
    requires_audio_drive = bool(node_mapping.get("drive_audio_node_id") or node_mapping.get("final_audio_node_id"))
    if not requires_audio_drive:
        return {"enabled": False, "speaker_timeline": [], "audio_drive_context": {}}

    window_plan = _find_window_plan_for_clip(video_director_plan, clip)
    if not window_plan:
        raise RuntimeError("当前 Clip 缺少 AudioDrive window_plan，请先构建 Execution Windows 和 Clip Audio。")
    if str(window_plan.get("audio_status") or window_plan.get("audioStatus") or "").upper() != "READY":
        raise RuntimeError(f"Clip {window_plan.get('window_index')} Audio 未 READY，请先在音频生成页构建 Clip Audio。")
    if not _clip_audio_matches_plan_timeline(window_plan, video_director_plan):
        raise RuntimeError(f"Clip {window_plan.get('window_index') or window_plan.get('clip_index')} Audio 与当前 Audio Timeline 不匹配，请重建 Clip Audio。")

    drive_audio_path = window_plan.get("drive_audio_path") or window_plan.get("driveAudioPath") or url_to_local_path(window_plan.get("drive_audio_url") or window_plan.get("driveAudioUrl") or "")
    final_audio_path = window_plan.get("final_audio_path") or window_plan.get("finalAudioPath") or url_to_local_path(window_plan.get("final_audio_url") or window_plan.get("finalAudioUrl") or "")
    if not drive_audio_path or not Path(drive_audio_path).is_file():
        raise RuntimeError(f"Clip {window_plan.get('window_index')} drive_audio 文件不存在，请重建 Clip Audio。")
    if not final_audio_path or not Path(final_audio_path).is_file():
        raise RuntimeError(f"Clip {window_plan.get('window_index')} final_audio 文件不存在，请重建 Clip Audio。")

    clip_duration = float(window_plan.get("clip_audio_duration") or window_plan.get("clipAudioDuration") or max(0.0, float((clip or {}).get("end_time") or 0) - float((clip or {}).get("start_time") or 0)))
    from app.services.rendered_subtitles import load
    clip["subtitle_audio_path"] = final_audio_path
    clip["subtitle_snapshot"] = load(final_audio_path)
    snapshot = clip["subtitle_snapshot"]
    if snapshot and (snapshot["lineage"].get("timeline_id") != window_plan.get("audio_timeline_id")
                     or snapshot["lineage"].get("timeline_revision") != int(window_plan.get("audio_timeline_revision") or 0)
                     or snapshot["lineage"].get("timeline_hash") != window_plan.get("audio_timeline_hash")
                     or snapshot["lineage"].get("clip_start") != float(clip.get("start_time") or 0)
                     or snapshot["lineage"].get("clip_end") != float(clip.get("end_time") or 0)):
        clip["subtitle_snapshot"] = None
    speaker_timeline = window_plan.get("speaker_timeline") if isinstance(window_plan.get("speaker_timeline"), list) else window_plan.get("speakerTimeline") if isinstance(window_plan.get("speakerTimeline"), list) else []
    return {
        "enabled": True,
        "drive_audio_path": drive_audio_path,
        "final_audio_path": final_audio_path,
        "speaker_timeline": speaker_timeline,
        "audio_drive_context": {
            "audio_mode": "lock_source",
            "drive_audio": Path(drive_audio_path).name,
            "final_audio": Path(final_audio_path).name,
            "duration": round(clip_duration, 3),
            "rule": "drive_audio controls visible lipsync; final_audio is the complete audience-facing audio. Do not invent dialogue or subtitles.",
        },
    }


def _parse_iso_datetime(value: str):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _hydrate_plan_keyframes_from_legacy(shot, plan_keyframes: list) -> list:
    raise RuntimeError('LEGACY_KEYFRAME_HYDRATION_RETIRED: 使用显式生产者lineage')


def _h3_prompt_clip(plan: dict, selected_mode: str, clip: dict) -> dict:
    """Editable prompt owner, not necessarily the execution or audio source."""
    collection = "window_plans" if selected_mode == "MULTI_KEYFRAME" else "clips"
    index = int(clip.get("clip_index") or 1)
    matches = [
        item for position, item in enumerate(safe_json_list(plan.get(collection)), 1)
        if isinstance(item, dict) and int(item.get("window_index") or item.get("clip_index") or position) == index
    ]
    if len(matches) > 1:
        raise H3PromptValidationError("AMBIGUOUS_CLIP", index)
    return matches[0] if matches else {}


def _h3_clip_structure(shot, plan: dict, selected_mode: str, clip: dict) -> dict | None:
    """Failure ownership excludes editable prompt text, descriptions and media facts."""
    try:
        owner = _h3_prompt_clip(plan, selected_mode, clip)
        windows = safe_json_list(plan.get("window_plans"))
        multi_executor = selected_mode == "MULTI_KEYFRAME" and len(windows) > 1
        first_window = windows[0] if windows and not multi_executor else None
        source = owner if multi_executor else first_window if first_window is not None else (safe_json_list(plan.get("clips")) or [{}])[0]
        fields = ("clip_index", "window_index", "start_time", "end_time", "keyframe_indexes",
                  "selected_frame_count", "workflow_key", "workflow_type", "role")
        indexes = {int(index) for index in ((first_window or owner).get("keyframe_indexes") or [])}
        return deepcopy({
            "mode": plan.get("selected_mode") or selected_mode,
            "range": [int(source.get("window_index" if multi_executor or first_window is not None else "clip_index") or 1),
                      float(source.get("start_time") or 0),
                      float(source.get("end_time") or (0 if multi_executor else _resolved_duration_from_plan(shot, plan)))],
            "owner": {field: owner.get(field) for field in fields} if owner else None,
            "first_window": {field: first_window.get(field) for field in fields} if first_window else None,
            "keyframes": [{field: frame.get(field) for field in ("index", "role", "time_seconds")}
                          for frame in safe_json_list(plan.get("keyframes")) if isinstance(frame, dict)
                          and (selected_mode != "MULTI_KEYFRAME" or int(frame.get("index") or -1) in indexes)],
        })
    except (H3PromptValidationError, TypeError, ValueError, AttributeError):
        return None


def _get_reusable_video_prompt(video_director_plan: dict, *, selected_mode: str, clip: dict,
                               workflow_type: str, context: dict) -> str | None:
    if video_director_plan.get("selected_mode", selected_mode) != selected_mode:
        return None
    current = _h3_prompt_clip(video_director_plan, selected_mode, clip)
    if current.get("workflow_type") not in (None, workflow_type):
        raise H3PromptValidationError("REUSE_WORKFLOW_CHANGED")
    # Even empty/invalid current edits are authoritative; never search past them.
    if "prompt_text" in current:
        if not isinstance(current["prompt_text"], str):
            raise H3PromptValidationError("INVALID_CURRENT_PROMPT")
        return current["prompt_text"]

    step, task_type = {
        "SINGLE_FRAME": ("11", "h3_single_frame_prompt"),
        "FIRST_LAST_FRAME": ("12", "h3_first_last_frame_prompt"),
        "MULTI_KEYFRAME": ("13", "h3_multi_keyframe_prompt"),
    }[selected_mode]
    for call in reversed(safe_json_list(video_director_plan.get("ai_calls"))):
        if not isinstance(call, dict):
            continue
        if str(call.get("step")) in {"07", "08", "10"}:
            break
        if not (str(call.get("step")) == step and call.get("task_type") == task_type
                and call.get("status") == "success" and call.get("clip_index") == clip.get("clip_index")
                and call.get("workflow_type") == workflow_type):
            continue
        saved = safe_json_dict(call.get("parsed_result"))
        if "context" in saved:
            if saved["context"] != context:
                return None
        elif (video_director_plan.get("invalidation_reason") or video_director_plan.get("invalidation_level")
              or video_director_plan.get("keyframe_planning_status") == "STALE"):
            return None
        # Legacy one-window MULTI stored only ai_calls. CoreGate still validates
        # this exact candidate, including independently saved fallback markers.
        prompt = call.get("final_prompt")
        if not isinstance(prompt, str):
            raise H3PromptValidationError("INVALID_SAVED_PROMPT")
        return prompt
    return None


def _h3_prompt_context(db, shot, selected_mode: str, clip: dict, audio_drive_enabled: bool, *, plan=None, effective_context=None) -> dict:
    plan = safe_json_dict(shot.video_director_plan) if plan is None else plan
    owner = _h3_prompt_clip(plan, selected_mode, clip)
    windows = safe_json_list(plan.get("window_plans"))
    if selected_mode == "MULTI_KEYFRAME" and not owner:
        raise H3PromptValidationError("CLIP_REMOVED", clip.get("clip_index"))
    multi_executor = selected_mode == "MULTI_KEYFRAME" and len(windows) > 1
    if multi_executor:
        effective = owner
    else:
        effective = (safe_json_list(plan.get("clips")) or [{}])[0]
        # The single-call executor overlays its first window in every mode.
        if windows:
            window = windows[0]
            effective = {
                **effective, "clip_index": window.get("window_index") or 1,
                "start_time": window.get("start_time") or 0,
                "end_time": window.get("end_time") or _resolved_duration_from_plan(shot, plan),
                **{field: window.get(field) for field in ("selected_frame_count", "workflow_key")},
                "keyframe_indexes": window.get("keyframe_indexes") or [],
            }
        if not effective:
            effective = {"clip_index": 1, "start_time": 0, "end_time": _resolved_duration_from_plan(shot, plan)}
    current_clip = {
        "clip_index": int((effective.get("window_index") if multi_executor else effective.get("clip_index")) or 1),
        "start_time": float(effective.get("start_time") or 0),
        "end_time": float(effective.get("end_time") or (0 if multi_executor else _resolved_duration_from_plan(shot, plan))),
        **{field: effective.get(field) for field in ("selected_frame_count", "workflow_key", "workflow_type")},
        "keyframe_indexes": effective.get("keyframe_indexes") or [],
    }
    keyframes = safe_json_list(plan.get("keyframes"))
    transitions = safe_json_list(plan.get("transitions"))
    if selected_mode == "MULTI_KEYFRAME":
        indexes = {int(index) for index in current_clip["keyframe_indexes"]}
        keyframes = [item for item in keyframes if isinstance(item, dict) and int(item.get("index") or -1) in indexes]
        transitions = _filter_transitions_for_keyframe_indexes(transitions, current_clip["keyframe_indexes"])
    context = {
        "selected_mode": selected_mode, "plan_selected_mode": plan.get("selected_mode") or selected_mode,
        "clip": current_clip,
        "shot": {field: getattr(shot, field, None) for field in (
            "id", "chapter_id", "index", "description", "video_description", "duration", "estimated_duration", "continuity_mode", "scene",
        )},
        "characters": safe_json_list(shot.characters), "props": safe_json_list(shot.props),
        "keyframes": [{field: item.get(field) for field in (
            "index", "role", "time_seconds", "description", "image_url",
        )} for item in keyframes if isinstance(item, dict)],
        "transitions": [{field: item.get(field) for field in (
            "from_keyframe_index", "to_keyframe_index", "transition_description",
        )} for item in transitions if isinstance(item, dict)],
        "invalidation": {field: plan.get(field) for field in ("invalidation_reason", "invalidation_level")},
        "planning_stale": plan.get("keyframe_planning_status") == "STALE",
    }
    from app.services.runtime_gate import require_rsa
    rsa = require_rsa(db, shot.id)
    context["resolved_shot_assets"] = {"id": rsa.id, "hash": rsa.result_hash}
    first_index = (current_clip["keyframe_indexes"] or [None])[0]
    first_keyframe = next((item for item in keyframes if isinstance(item, dict) and item.get("index") == first_index), {})
    uses_shot_image = (not multi_executor
                       or (first_index == 1 and first_keyframe.get("role") == "START"))
    context["start_image_url"] = shot.image_url if uses_shot_image else first_keyframe.get("image_url")
    if audio_drive_enabled:
        from app.models.audio_drive import ShotAudioTimeline
        audio_window = _find_window_plan_for_clip(plan, current_clip)
        latest = db.query(ShotAudioTimeline).filter(ShotAudioTimeline.shot_id == shot.id).order_by(
            ShotAudioTimeline.revision.desc(),
        ).populate_existing().first()
        if (not audio_window or getattr(shot, "audio_status", None) != "READY" or not latest or latest.status != "READY"
                or str(audio_window.get("audio_status") or audio_window.get("audioStatus") or "").upper() != "READY"
                or not _clip_audio_matches_plan_timeline(audio_window, plan)
                or not _clip_audio_matches_plan_timeline(audio_window, {"audio_timeline": {
                    "id": latest.id, "revision": latest.revision, "source_hash": latest.generated_from_hash,
                }})):
            raise H3PromptValidationError("AUDIO_BINDING_NOT_READY")
        speaker_timeline = audio_window.get("speaker_timeline") if isinstance(audio_window.get("speaker_timeline"), list) else audio_window.get("speakerTimeline") if isinstance(audio_window.get("speakerTimeline"), list) else []
        audio = {"id": latest.id, "revision": latest.revision, "hash": latest.generated_from_hash, "status": latest.status,
                 "bound_hash": audio_window.get("audio_timeline_hash") or audio_window.get("audioTimelineHash"),
                 "speaker_timeline": speaker_timeline,
                 "duration": round(float(audio_window.get("clip_audio_duration") or audio_window.get("clipAudioDuration")
                                         or max(0.0, float(effective.get("end_time") or 0) - float(effective.get("start_time") or 0))), 3)}
        for field, camel in (("drive_audio", "driveAudio"), ("final_audio", "finalAudio")):
            path = audio_window.get(f"{field}_path") or audio_window.get(f"{camel}Path") or url_to_local_path(
                audio_window.get(f"{field}_url") or audio_window.get(f"{camel}Url") or "",
            )
            if not path or not Path(path).is_file():
                raise H3PromptValidationError("AUDIO_FILE_NOT_READY", field)
            audio[field] = {"path": str(path)}
        context["audio"] = audio
    if effective_context is not None:
        context["planned_context_hash"] = prompt_digest(context)
        context.update({field: effective_context[field] for field in ("start_image_url", "keyframes", "transitions")})
        context["actual_state_handoff"] = {
            field: effective_context[field] for field in (
                "version", "source", "run_id", "from_clip", "to_clip", "clip_attempt_id",
                "planned_context_hash", "start_image_sha256", "trusted_state", "canonical_state", "evidence_hash",
            )
        }
        context["actual_state_handoff"]["effective_context_hash"] = prompt_digest(effective_context)
    return deepcopy(context)


def _save_h3_prompt_gate(db, task, record: dict, *, prompt_id=None, error=None, failure_kind=None) -> None:
    if record.get("applicable") is False:
        return
    if prompt_id:
        record.update({"prompt_id": prompt_id, "submission_state": "submitted"})
    if failure_kind == "H3_PROMPT_SUBMISSION_REJECTED":
        record["submission_failure_kind"] = failure_kind
        prequeue = record.setdefault("prequeue_validation", {})
        prequeue.update({"passed": False, "failure_kind": failure_kind})
        prequeue.setdefault("errors", [{"code": failure_kind, "details": str(error or "")}])
    if error:
        record["submission_error"] = str(error)
        if not record.get("prompt_id"):
            record["submission_state"] = "unknown" if record.get("prequeue_validation", {}).get("passed") else "not_submitted"
    if hasattr(task, "_video_execution"):
        from app.services.shot_video_execution import save_gate_record
        save_gate_record(db, task, record)
        return
    # Merge into the latest metadata, not a task-wide prompt/prompt_id snapshot.
    db.flush()
    db.refresh(task)
    metadata = safe_json_dict(task.metadata_json)
    gate = metadata.setdefault("h3_prompt_gate", {"version": 1, "clips": {}})
    attempts = gate["clips"].setdefault(str(record["clip_index"]), [])
    for index, previous in enumerate(attempts):
        if previous.get("attempt_id") == record["attempt_id"]:
            attempts[index] = deepcopy(record)
            break
    else:
        attempts.append(deepcopy(record))
    task.metadata_json = json.dumps(metadata, ensure_ascii=False)
    db.commit()


def _fail_h3_video_clip(db, task, shot, clip: dict, selected_mode: str, message: str, *, target, gate_failed=False) -> None:
    if hasattr(shot, "_execution_task_id"):
        from app.services.shot_video_execution import fail_execution
        fail_execution(db, shot._video_execution, message, clip_index=int(clip.get("clip_index") or 1), gate_failed=gate_failed)
        return
    db.refresh(task)
    db.refresh(shot)
    if any(
        getattr(task, field, None) != value for field, value in target.items()
        if field not in {"shot_video_task_id", "clip_structure"}
    ):
        return
    owned = False

    def fail_owned_clip(plan):
        nonlocal owned
        owned = False
        frozen = target.get("clip_structure")
        if not frozen or _h3_clip_structure(shot, plan, selected_mode, clip) != frozen:
            return plan
        current = _h3_prompt_clip(plan, selected_mode, clip)
        if not current:
            if selected_mode == "SINGLE_FRAME" and frozen["owner"] is None:
                plan.update({"task_error_message": message, "error_message": message})
                owned = True
            return plan
        current.update({"status": "FAILED", "error_message": message})
        if selected_mode == "MULTI_KEYFRAME":
            if gate_failed:
                current["h3_prompt_gate_failed"] = True
            _sync_task_video_director_clips(task, plan.get("window_plans") or [])
        plan.update({"task_error_message": message, "error_message": message})
        owned = True
        return plan

    if task.shot_id == shot.id and shot.video_task_id == target["shot_video_task_id"]:
        VideoDirectorPlanService(db).mutate(shot.id, fail_owned_clip)
        if owned:
            ShotRepository(db).update(shot, video_status="failed")
    if task.status != "cancelled":
        task.status = "failed"
        task.error_message = message
        task.current_step = "生成失败"
    db.commit()


async def _build_h3_prompt_for_worker(*, db, task, novel, shot, selected_mode, clip, workflow,
                                     workflow_capability, start_image_url, keyframes, transitions,
                                     reference_images, character_appearances, audio_drive,
                                     skip_llm_when_prompt_exists=False, effective_context=None):
    """Return (prompt, read-only graph callback); evidence belongs to this attempt."""
    if effective_context is not None and skip_llm_when_prompt_exists:
        raise H3PromptValidationError("HANDOFF_REQUIRES_FRESH_PROMPT")
    enabled = bool(audio_drive.get("enabled"))
    graph = safe_json_dict(workflow.workflow_json)
    handoff_kwargs = {"effective_context": effective_context} if effective_context is not None else {}
    handoff_handle = deepcopy(getattr(task, "_video_execution", None) or getattr(shot, "_video_execution", None)) if handoff_kwargs else None
    handoff_hash = prompt_digest(effective_context) if handoff_kwargs else None
    if handoff_kwargs and (not is_h3_workflow(graph) or selected_mode != "MULTI_KEYFRAME" or clip.get("clip_index") != 2):
        raise H3PromptValidationError("HANDOFF_REQUIRES_C2_H3")
    target = {field: getattr(task, field, None) for field in (
        "id", "shot_id", "chapter_id", "novel_id", "workflow_id", "claim_token", "attempt",
    )}
    target["shot_video_task_id"] = shot.video_task_id
    target["clip_structure"] = _h3_clip_structure(shot, safe_json_dict(shot.video_director_plan), selected_mode, clip)

    if not is_h3_workflow(graph):
        plan = safe_json_dict(shot.video_director_plan)
        try:
            prompt = ""
            if skip_llm_when_prompt_exists:
                if selected_mode == "MULTI_KEYFRAME" and len(safe_json_list(plan.get("window_plans"))) > 1:
                    sources = (([_h3_prompt_clip(plan, selected_mode, clip)], "prompt_text"),)
                else:
                    sources = ((safe_json_list(plan.get("clips")), "prompt_text"),
                               (reversed(safe_json_list(plan.get("ai_calls"))), "final_prompt"))
                for items, field in sources:
                    for item in items:
                        candidate = item.get(field) if isinstance(item, dict) else None
                        if isinstance(candidate, str) and candidate.strip():
                            prompt = candidate.strip()
                            break
                    if prompt:
                        break
                if not prompt:
                    raise RuntimeError("No reusable video prompt is available")
            else:
                prompt = await build_h3_video_prompt(
                    db=db, novel=novel, shot=shot, selected_mode=selected_mode, clip=clip,
                    workflow_capability=workflow_capability, workflow_type=workflow.type, workflow_name=workflow.name,
                    start_image_url=start_image_url, keyframes=keyframes, transitions=transitions, clip_dialogues=[],
                    reference_images=reference_images, character_appearances=character_appearances,
                    speaker_timeline=audio_drive.get("speaker_timeline") or [],
                    audio_drive_context=audio_drive.get("audio_drive_context") or {}, workflow_graph=graph,
                )
            if selected_mode != "MULTI_KEYFRAME":
                _update_clip_prompt(shot, clip, prompt, db)
            elif len(safe_json_list(plan.get("window_plans"))) > 1:
                _update_window_plan(shot, int(clip.get("clip_index") or 1), {"prompt_text": prompt}, db, task=task)
            if target["clip_structure"] and target["clip_structure"]["owner"] is None:
                target["clip_structure"] = _h3_clip_structure(shot, safe_json_dict(shot.video_director_plan), selected_mode, clip)
        except Exception as exc:
            _fail_h3_video_clip(db, task, shot, clip, selected_mode, str(exc), target=target)
            raise

        def on_before_submit_non_h3(submitted_workflow):
            if is_h3_workflow(submitted_workflow):
                error = H3PromptValidationError("H3_GRAPH_REQUIRES_PROMPT_GATE")
                _fail_h3_video_clip(db, task, shot, clip, selected_mode, str(error), target=target, gate_failed=True)
                raise error

        on_before_submit_non_h3.validation_record = {"applicable": False, "target": target}
        return prompt, on_before_submit_non_h3

    record = {"version": 1, "attempt_id": getattr(shot, "_video_clip_attempt_id", None) or uuid4().hex, "clip_index": int(clip.get("clip_index") or 1),
              "selected_mode": selected_mode, "workflow_type": workflow.type, "passed": False,
              "stage": "candidate", "raw_candidate": None, "submission_state": "not_submitted", "target": target}

    def fail(exc, *, prequeue=False):
        error = exc if isinstance(exc, H3PromptValidationError) else H3PromptValidationError("WORKER_GATE_ERROR", str(exc))
        record.update({"passed": False, "errors": [{"code": error.code, "details": error.details}]})
        if prequeue:
            record["prequeue_validation"] = {**record.get("prequeue_validation", {}), "passed": False, "errors": record["errors"]}
        _save_h3_prompt_gate(db, task, record, error=error)
        _fail_h3_video_clip(db, task, shot, clip, selected_mode, str(error), target=target, gate_failed=True)
        return error

    def check_handoff(context):
        if effective_context is None:
            return
        db.refresh(task)
        metadata = safe_json_dict(task.metadata_json)
        root = safe_json_dict(metadata.get("actual_state_handoff"))
        run = safe_json_dict(metadata.get("video_run"))
        slot = safe_json_dict(safe_json_dict(run.get("clips")).get("2"))
        handle = handoff_handle or {}
        if (root.get("decision") not in {"CONTINUE", "WARN"} or root.get("can_submit_c2") is not True
                or root.get("effective_context") != effective_context
                or root.get("effective_context_hash") != handoff_hash
                or prompt_digest(root.get("effective_context")) != handoff_hash
                or prompt_digest(effective_context) != handoff_hash):
            raise H3PromptValidationError("HANDOFF_CONTEXT_NOT_AUTHORIZED")
        if (not handle.get("run_id") or not handle.get("claim_token")
                or handle.get("task_id") != task.id or task.type != "shot_video" or task.status != "running"
                or handle.get("claim_token") != task.claim_token or handle.get("attempt") != task.attempt
                or any(getattr(owner, "_video_execution") != handle for owner in (task, shot) if hasattr(owner, "_video_execution"))
                or not any(hasattr(owner, "_video_execution") for owner in (task, shot))
                or run.get("run_id") != handle["run_id"] or run.get("phase") != "running" or run.get("superseded_by")
                or safe_json_dict(metadata.get("execution")).get("attempt_id") != handle["run_id"]
                or effective_context["run_id"] != handle["run_id"]
                or not slot.get("attempt_id") or safe_json_dict(slot.get("spec")).get("clip_index") != 2
                or safe_json_dict(handle.get("attempts")).get("2") != slot["attempt_id"]
                or effective_context["clip_attempt_id"] != slot["attempt_id"]
                or getattr(shot, "_video_clip_attempt_id", None) != slot["attempt_id"]
                or record["attempt_id"] != slot["attempt_id"] or context["clip"]["clip_index"] != 2):
            raise H3PromptValidationError("HANDOFF_EXECUTION_CHANGED")
        if context["planned_context_hash"] != effective_context["planned_context_hash"]:
            raise H3PromptValidationError("HANDOFF_PLANNED_CONTEXT_CHANGED")
        # Effective inputs must match the bundle, not become a substitute baseline plan.
        if keyframes != effective_context["keyframes"] or transitions != effective_context["transitions"]:
            raise H3PromptValidationError("VISUAL_INPUTS_CHANGED")

    def check_current():
        db.refresh(task)
        _refresh_video_shot(db, shot)
        if task.status == "cancelled":
            raise H3PromptValidationError("TASK_CANCELLED")
        if (task.status != "running" or task.shot_id != shot.id
                or any(getattr(task, field, None) != value for field, value in target.items()
                       if field not in {"shot_video_task_id", "clip_structure"})
                or shot.video_task_id != target["shot_video_task_id"]):
            raise H3PromptValidationError("TASK_TARGET_REPLACED")
        current = _h3_prompt_context(db, shot, selected_mode, clip, enabled, **handoff_kwargs)
        check_handoff(current)
        if current != record["context"]:
            raise H3PromptValidationError("SEMANTIC_CONTEXT_CHANGED", [
                field for field in current if current[field] != record["context"].get(field)
            ])
        if _h3_clip_structure(shot, safe_json_dict(shot.video_director_plan), selected_mode, clip) != target["clip_structure"]:
            raise H3PromptValidationError("CLIP_TARGET_REPLACED")
        current_prompt = _h3_prompt_clip(safe_json_dict(shot.video_director_plan), selected_mode, clip)
        if ("prompt_text" in current_prompt, current_prompt.get("prompt_text")) != prompt_source:
            raise H3PromptValidationError("MANUAL_PROMPT_CHANGED")
        return current

    try:
        db.refresh(task)
        _refresh_video_shot(db, shot)
        if effective_context is not None:
            if (not isinstance(effective_context, dict) or type(effective_context.get("version")) is not int
                    or effective_context["version"] != 1 or effective_context.get("source") != "actual_state_handoff"
                    or type(effective_context.get("from_clip")) is not int or effective_context["from_clip"] != 1
                    or type(effective_context.get("to_clip")) is not int or effective_context["to_clip"] != 2
                    or any(not isinstance(effective_context.get(field), str) or not effective_context[field] for field in (
                        "run_id", "clip_attempt_id", "planned_context_hash", "start_image_url", "start_image_sha256", "evidence_hash",
                    ))
                    or any(not isinstance(effective_context.get(field), list)
                           or any(not isinstance(item, dict) for item in effective_context[field])
                           for field in ("keyframes", "transitions", "trusted_state", "canonical_state"))
                    or len(effective_context["keyframes"]) not in {3, 4}
                    or effective_context["keyframes"][0].get("image_url") != effective_context["start_image_url"]
                    or not isinstance(effective_context["keyframes"][0].get("description"), str)
                    or not effective_context["keyframes"][0]["description"].strip()):
                raise H3PromptValidationError("INVALID_HANDOFF_CONTEXT")
        if any(isinstance(node, dict) and node.get("class_type") == "MiniMaxH3AudioConditioningT8" for node in graph.values()) and not enabled:
            raise H3PromptValidationError("AUDIODRIVE_REQUIRED_BY_GRAPH")
        record["context"] = _h3_prompt_context(db, shot, selected_mode, clip, enabled, **handoff_kwargs)
        record["context_hash"] = prompt_digest(record["context"])
        current = _h3_prompt_clip(safe_json_dict(shot.video_director_plan), selected_mode, clip)
        prompt_source = ("prompt_text" in current, current.get("prompt_text"))
        check_current()
        expected = record["context"]["clip"]
        if any(clip.get(field) != value for field, value in expected.items() if field in clip):
            raise H3PromptValidationError("CLIP_CONTEXT_CHANGED")
        if start_image_url != record["context"]["start_image_url"]:
            raise H3PromptValidationError("START_IMAGE_CHANGED")
        if effective_context is None:
            supplied = _h3_prompt_context(db, shot, selected_mode, clip, enabled, plan={
                **safe_json_dict(shot.video_director_plan), "keyframes": keyframes, "transitions": transitions,
            })
            if any(supplied[field] != record["context"][field] for field in ("keyframes", "transitions")):
                raise H3PromptValidationError("VISUAL_INPUTS_CHANGED")
        if enabled:
            if (audio_drive.get("speaker_timeline") or []) != record["context"]["audio"]["speaker_timeline"]:
                raise H3PromptValidationError("SPEAKER_TIMELINE_CHANGED")
            for field in ("drive_audio", "final_audio"):
                if str(audio_drive.get(f"{field}_path") or "") != record["context"]["audio"][field]["path"]:
                    raise H3PromptValidationError("AUDIO_INPUT_CHANGED", field)
        reusable_prompt = None
        if skip_llm_when_prompt_exists:
            reusable_prompt = _get_reusable_video_prompt(
                safe_json_dict(shot.video_director_plan), selected_mode=selected_mode, clip=clip,
                workflow_type=workflow.type, context=record["context"],
            )
            if reusable_prompt is None:
                raise H3PromptValidationError("REUSABLE_PROMPT_MISSING")
        record["raw_candidate"] = reusable_prompt
        _save_h3_prompt_gate(db, task, record)
        if reusable_prompt is None and hasattr(task, "_video_execution"):
            from app.services.shot_video_execution import invalidate_binding_proof
            invalidate_binding_proof(task, "h3-llm-await")
        prompt = await build_h3_video_prompt(
            db=db, novel=novel, shot=shot, selected_mode=selected_mode, clip=clip,
            workflow_capability=workflow_capability, workflow_type=workflow.type, workflow_name=workflow.name,
            start_image_url=start_image_url, keyframes=keyframes, transitions=transitions, clip_dialogues=[],
            reference_images=reference_images, character_appearances=character_appearances,
            speaker_timeline=audio_drive.get("speaker_timeline") or [],
            audio_drive_context=audio_drive.get("audio_drive_context") or {},
            reusable_prompt=reusable_prompt, validation_record=record, audio_drive_enabled=enabled,
            **handoff_kwargs,
        )
        if not record.get("passed") or record.get("final_prompt") != prompt or record.get("final_hash") != prompt_digest(prompt):
            raise H3PromptValidationError("BUILDER_RECORD_MISMATCH")
        check_current()

        def save_prompt(plan):
            current = _h3_prompt_clip(plan, selected_mode, clip)
            if ("prompt_text" in current, current.get("prompt_text")) != prompt_source:
                raise H3PromptValidationError("MANUAL_PROMPT_CHANGED")
            context = _h3_prompt_context(db, shot, selected_mode, clip, enabled, plan=plan, **handoff_kwargs)
            check_handoff(context)
            if context != record["context"]:
                raise H3PromptValidationError("SEMANTIC_CONTEXT_CHANGED")
            if _h3_clip_structure(shot, plan, selected_mode, clip) != target["clip_structure"]:
                raise H3PromptValidationError("CLIP_TARGET_REPLACED")
            if not current:
                current = dict(record["context"]["clip"])
                plan.setdefault("clips", []).append(current)
            current["prompt_text"] = prompt
            return plan

        _mutate_video_plan(db, shot, save_prompt)
        if target["clip_structure"] and target["clip_structure"]["owner"] is None:
            target["clip_structure"] = _h3_clip_structure(shot, safe_json_dict(shot.video_director_plan), selected_mode, clip)
        prompt_source = (True, prompt)
        _save_h3_prompt_gate(db, task, record)
    except Exception as exc:
        raise fail(exc) from exc

    def on_before_submit(submitted_workflow):
        try:
            if not is_h3_workflow(submitted_workflow):
                raise H3PromptValidationError("H3_GRAPH_REMOVED")
            if any(isinstance(node, dict) and node.get("class_type") == "MiniMaxH3AudioConditioningT8"
                   for node in submitted_workflow.values()) and not enabled:
                raise H3PromptValidationError("AUDIODRIVE_REQUIRED_BY_GRAPH")
            current = check_current()
            from app.services.runtime_gate import require_rsa, resolved_text_context
            appearances = resolved_text_context(require_rsa(db, shot.id))["character_appearances"]
            manifest, timeline, issues = resolve_h3_prompt_subjects(
                db, novel.id, shot, clip, current.get("audio", {}).get("speaker_timeline", []), appearances,
            )
            if issues:
                raise H3PromptValidationError("SUBJECT_RESOLUTION_FAILED", issues)
            prepared = prepare_h3_prompt(
                record["raw_candidate"], constraint=record["constraint"], continuity_lock=record["continuity_lock"],
                subject_manifest=manifest, speaker_timeline=timeline, audio_drive_enabled=enabled,
                fallback_context=record.get("fallback_context"),
            )
            record["prequeue_validation"] = prepared
            if (prepared["final_prompt"] != prompt or prepared["final_hash"] != record["final_hash"]
                    or manifest != record["subject_manifest"] or timeline != record["speaker_timeline"]):
                raise H3PromptValidationError("PREQUEUE_PROMPT_CHANGED")
            if selected_mode == "MULTI_KEYFRAME" and len(safe_json_list(safe_json_dict(shot.video_director_plan).get("window_plans"))) > 1:
                # Keep old facts through rejection, but never submit a new attempt
                # with the preceding attempt's window prompt_id/video metadata.
                _reset_multi_clip_window_plans_for_task(
                    db, task, shot, only_window_index=int(clip.get("clip_index") or 1), preserve_prompt_text=True,
                )
            record["submission_state"] = "prepared"
            _save_h3_prompt_gate(db, task, record)
        except Exception as exc:
            raise fail(exc, prequeue=True) from exc

    on_before_submit.validation_record = record
    return prompt, on_before_submit


def enqueue_shot_video_task(
    task_id: str,
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    shot_index: int,
    workflow_id: str,
    shot_image_url: str,
    use_keyframes: bool = True,
    use_reference_audio: bool = True,
    selected_mode: str = "SINGLE_FRAME",
    only_window_index: int | None = None,
    auto_merge_clips: bool = False,
    skip_llm_when_prompt_exists: bool = False,
) -> None:
    """Queue shot video generation in its dedicated serial worker."""
    # Admission already persisted the complete execution request. The DB-backed
    # worker is the sole queue owner, including after process restarts.
    return None


async def generate_shot_video_task(
    task_id: str,
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    shot_index: int,
    workflow_id: str,
    shot_image_url: str,
    use_keyframes: bool = True,
    use_reference_audio: bool = True,
    selected_mode: str = "SINGLE_FRAME",
    only_window_index: int | None = None,
    auto_merge_clips: bool = False,
    skip_llm_when_prompt_exists: bool = False,
):
    """
    后台任务：生成分镜视频

    Args:
        task_id: 任务ID
        novel_id: 小说ID
        chapter_id: 章节ID
        shot_index: 分镜索引（仅展示/文件命名元数据，不作为业务身份）
        workflow_id: 工作流ID
        shot_image_url: 分镜图片URL
        use_keyframes: 是否使用关键帧（如果存在），默认 True
        use_reference_audio: 是否使用参考音频（如果存在），默认 True
    """
    db = SessionLocal()
    strict_execution = False
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            return
        if task.status not in {"pending", "running"}:
            return
        from app.services.shot_video_execution import run_video_execution
        strict_execution=True
        await run_video_execution(db,task_id)
        from app.services.external_failure_observation_service import record_task_external_failures_best_effort
        record_task_external_failures_best_effort(task_id)
        return

        try:
            execution_metadata = json.loads(task.metadata_json) if task.metadata_json else {}
        except (TypeError, ValueError):
            execution_metadata = None
        if (not isinstance(execution_metadata, dict) or "execution" in execution_metadata or "video_run" in execution_metadata
                or execution_metadata.get("execution_purpose", "production") != "production"):
            from app.services.shot_video_execution import run_video_execution
            strict_execution = True
            await run_video_execution(db, task_id)
            from app.services.external_failure_observation_service import record_task_external_failures_best_effort
            record_task_external_failures_best_effort(task_id)
            return

        started = db.query(Task).filter(Task.id == task_id, Task.status == task.status).update({
            "status": "running", "started_at": datetime.utcnow(), "current_step": "准备生成视频...",
        }, synchronize_session=False)
        if started != 1:
            db.rollback()
            return
        db.commit()
        db.refresh(task)

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

        shot_repo = ShotRepository(db)
        if not task.shot_id:
            task.status = "failed"
            task.error_message = "视频任务缺少稳定 shot_id"
            task.current_step = "分镜身份无效"
            db.commit()
            return

        shot = shot_repo.get_by_id(task.shot_id)

        if not shot or shot.chapter_id != chapter_id:
            task.status = "failed"
            task.error_message = "分镜不存在"
            task.current_step = "分镜不存在"
            db.commit()
            return

        shot_index = int(shot.index or 0)

        # 视频生成优先由 11/12/13 Prompt Builder 产出最终 H3 prompt。
        shot_prompt = (shot.video_description or "").strip() or (shot.description or "")
        video_director_plan = safe_json_dict(shot.video_director_plan)
        selected_mode = selected_mode or video_director_plan.get("selected_mode") or "SINGLE_FRAME"

        task.prompt_text = shot_prompt
        task.description = f"{task.description}；视频模式：{selected_mode}"
        db.commit()

        duration = _resolved_duration_from_plan(shot, video_director_plan)
        fps = 25
        raw_frame_count = int(fps * duration)
        frame_count = legal_h3_frame_count(duration, fps)
        print(f"[VideoTask {task_id}] Duration: {duration}s, FPS: {fps}, Raw frames: {raw_frame_count}, Adjusted frames: {frame_count}")

        character_reference_path = None
        if shot_image_url:
            full_path = url_to_local_path(shot_image_url)
            if full_path:
                character_reference_path = full_path
                print(f"[VideoTask {task_id}] Found shot image: {full_path}")
            else:
                print(f"[VideoTask {task_id}] Shot image not found at: {shot_image_url}")

        # 获取占位符替换所需的资源数据
        # 从 Shot 模型直接获取角色、场景、道具
        shot_characters = json.loads(shot.characters) if shot.characters else []
        shot_scene = shot.scene or ""
        shot_props = json.loads(shot.props) if shot.props else []

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
                    Prop.name == prop_name
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

        window_plans = video_director_plan.get("window_plans") if isinstance(video_director_plan.get("window_plans"), list) else []
        if selected_mode == "MULTI_KEYFRAME" and len(window_plans) > 1:
            # Legacy graphs reset before execution; H3 keeps its delayed gate reset.
            selected_count = 0
            non_h3_windows = []
            non_h3_by_type = {}
            for position, window in enumerate(window_plans, 1):
                window_index = int(window.get("window_index") or position)
                if only_window_index is not None and window_index != int(only_window_index):
                    continue
                selected_count += 1
                clip_workflow_type = "three_frame_video" if int(window.get("selected_frame_count") or 0) == 3 else "four_frame_video"
                if clip_workflow_type not in non_h3_by_type:
                    clip_workflow = db.query(Workflow).filter(Workflow.type == clip_workflow_type, Workflow.is_active == True).first()
                    non_h3_by_type[clip_workflow_type] = bool(
                        clip_workflow and not is_h3_workflow(safe_json_dict(clip_workflow.workflow_json))
                    )
                if non_h3_by_type[clip_workflow_type]:
                    non_h3_windows.append(window_index)
            if non_h3_windows:
                reset_indexes = [only_window_index] if len(non_h3_windows) == selected_count else non_h3_windows
                for reset_index in reset_indexes:
                    window_plans = _reset_multi_clip_window_plans_for_task(
                        db, task, shot, only_window_index=reset_index, preserve_prompt_text=skip_llm_when_prompt_exists,
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

        if selected_mode == "SINGLE_FRAME":
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
        if character_reference_path:
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
        window_plans = video_director_plan.get("window_plans") if isinstance(video_director_plan.get("window_plans"), list) else []
        clip = (video_director_plan.get("clips") or [{}])[0] if isinstance(video_director_plan.get("clips"), list) else {}
        if window_plans:
            window_plan = window_plans[0]
            if only_window_index is not None and int(window_plan.get("window_index") or 1) != int(only_window_index):
                clip = {"clip_index": int(only_window_index)}
                raise RuntimeError(f"Clip {only_window_index} does not exist in the current plan")
            clip = {
                **(clip if isinstance(clip, dict) else {}),
                "clip_index": window_plan.get("window_index") or 1,
                "start_time": window_plan.get("start_time") or 0,
                "end_time": window_plan.get("end_time") or duration,
                "selected_frame_count": window_plan.get("selected_frame_count"),
                "workflow_key": window_plan.get("workflow_key"),
                "keyframe_indexes": window_plan.get("keyframe_indexes") or [],
            }
        if not clip:
            clip = {"clip_index": 1, "start_time": 0, "end_time": duration, "status": "PENDING"}
        duration = contract_clip_duration(clip.get("start_time") or 0, clip.get("end_time") or duration) or duration
        raw_frame_count = int(fps * duration)
        frame_count = legal_h3_frame_count(duration, fps)
        effective_node_mapping = dict(node_mapping)
        if workflow.type == "first_last_video":
            effective_node_mapping["reference_image_node_id"] = node_mapping.get("first_image_node_id")
            effective_node_mapping["keyframe_node_1"] = node_mapping.get("last_image_node_id")
        try:
            audio_drive = _resolve_audio_drive_for_h3(video_director_plan, clip, effective_node_mapping)
        except RuntimeError as exc:
            task.status = "failed"
            task.error_message = str(exc)
            task.current_step = "Clip Audio 未 READY"
            _mark_shot_video_failed(shot, shot_repo, task.error_message)
            db.commit()
            return
        keyframes_for_prompt = video_director_plan.get("keyframes") if isinstance(video_director_plan.get("keyframes"), list) else []
        if selected_mode == "MULTI_KEYFRAME" and clip.get("keyframe_indexes"):
            selected_indexes = {int(index) for index in clip.get("keyframe_indexes") or []}
            keyframes_for_prompt = [
                keyframe for keyframe in keyframes_for_prompt
                if isinstance(keyframe, dict) and int(keyframe.get("index") or -1) in selected_indexes
            ]
        transitions_for_prompt = video_director_plan.get("transitions") if isinstance(video_director_plan.get("transitions"), list) else []
        if selected_mode == "MULTI_KEYFRAME" and clip.get("keyframe_indexes"):
            transitions_for_prompt = _filter_transitions_for_keyframe_indexes(transitions_for_prompt, clip.get("keyframe_indexes") or [])
        task.current_step = "复用已有 H3 视频提示词..." if skip_llm_when_prompt_exists else "正在构建 H3 视频提示词..."
        if selected_mode == "MULTI_KEYFRAME":
            _update_window_plan_status(shot, int(clip.get("clip_index") or 1), "PROMPT_BUILDING", db, task=task)
        db.commit()
        shot_prompt, on_before_submit = await _build_h3_prompt_for_worker(
            db=db, task=task, novel=novel, shot=shot, selected_mode=selected_mode, clip=clip, workflow=workflow,
            workflow_capability=workflow_capability, start_image_url=shot_image_url,
            keyframes=keyframes_for_prompt, transitions=transitions_for_prompt, reference_images=reference_images,
            character_appearances=character_appearances, audio_drive=audio_drive,
            skip_llm_when_prompt_exists=skip_llm_when_prompt_exists,
        )
        if _is_task_cancelled(db, task):
            _cleanup_task_generated_clip_videos(db, task, shot)
            _mark_shot_video_failed(shot, shot_repo, "视频任务已取消")
            db.commit()
            return
        task.prompt_text = shot_prompt
        db.commit()

        task.current_step = "正在调用 ComfyUI 生成视频..."
        task.progress = 30
        if selected_mode == "MULTI_KEYFRAME" and clip.get("clip_index"):
            _update_window_plan_status(shot, int(clip.get("clip_index") or 1), "RUNNING", db, task=task)
        db.commit()

        comfyui_service = ComfyUIService()

        def save_prompt_id(prompt_id: str, submitted_workflow: dict = None):
            task.comfyui_prompt_id = prompt_id
            if submitted_workflow:
                task.workflow_json = json.dumps(submitted_workflow, ensure_ascii=False, indent=2)
            if selected_mode == "MULTI_KEYFRAME" and clip.get("clip_index"):
                fields = {"status": "RUNNING", "prompt_id": prompt_id}
                if submitted_workflow:
                    fields["workflow_json"] = submitted_workflow
                _update_window_plan(shot, int(clip.get("clip_index") or 1), fields, db, task=task)
            db.commit()
            _save_h3_prompt_gate(db, task, on_before_submit.validation_record, prompt_id=prompt_id)
            print(f"[VideoTask {task_id}] Saved ComfyUI prompt_id: {prompt_id}")

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
            reference_audio_path=None if audio_drive.get("enabled") else reference_audio_path,
            drive_audio_path=audio_drive.get("drive_audio_path"),
            final_audio_path=audio_drive.get("final_audio_path"),
            keyframe_paths=keyframe_paths,
            on_prompt_queued=save_prompt_id,
            on_before_submit=on_before_submit,
        )
        if result.get("prompt_id"):
            _save_h3_prompt_gate(db, task, on_before_submit.validation_record, prompt_id=result["prompt_id"])
        if not result.get("success"):
            _save_h3_prompt_gate(db, task, on_before_submit.validation_record, error=result.get("message") or "Generation failed",
                                 failure_kind=result.get("failure_kind"))
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
            db.commit()
            print(f"[VideoTask {task_id}] Saved submitted workflow to task")

        if not result.get("success"):
            _fail_h3_video_clip(db, task, shot, clip, selected_mode, result.get("message") or "Generation failed",
                                target=on_before_submit.validation_record["target"],
                                gate_failed=result.get("failure_kind") == "H3_PROMPT_SUBMISSION_REJECTED")
            return

        # 下载并保存视频
        await _save_generated_video(result, task, novel_id, chapter_id, shot_index, db, task_id, shot_repo, clip=clip)
        if task.status == "failed":
            _fail_h3_video_clip(db, task, shot, clip, selected_mode, task.error_message,
                                target=on_before_submit.validation_record["target"])
        elif task.status == "completed" and selected_mode == "MULTI_KEYFRAME" and clip.get("clip_index"):
            _update_window_plan_status(shot, int(clip.get("clip_index") or 1), "SUCCEEDED", db, task=task)

    except Exception as e:
        print(f"[VideoTask {task_id}] Error: {e}")
        import traceback
        traceback.print_exc()

        if strict_execution:
            # A failed claim/CAS must never fall into unfenced legacy writeback.
            return
        try:
            if not isinstance(e, H3PromptValidationError):
                record = on_before_submit.validation_record if 'on_before_submit' in locals() else None
                if record:
                    _save_h3_prompt_gate(db, task, record, error=e)
                if record and 'shot' in locals() and shot and 'clip' in locals():
                    _fail_h3_video_clip(db, task, shot, clip, selected_mode, str(e), target=record["target"])
                else:
                    if task.status != "cancelled":
                        task.status = "failed"
                        task.error_message = str(e)
                        task.current_step = "任务异常"
                    if 'shot' in locals() and shot:
                        _mark_shot_video_failed(shot, shot_repo, str(e))
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
        node_mapping = json.loads(workflow.node_mapping) if workflow.node_mapping else {}
        try:
            audio_drive = _resolve_audio_drive_for_h3(safe_json_dict(shot.video_director_plan), clip, node_mapping)
        except RuntimeError as exc:
            _update_window_plan(shot, window_index, {"status": "FAILED", "error_message": str(exc)}, db, task=task)
            task.status = "failed"
            task.error_message = str(exc)
            task.current_step = f"Clip {clip_position} Audio 未 READY"
            _mark_shot_video_failed(shot, shot_repo, task.error_message)
            db.commit()
            return

        task.current_step = f"{'复用已有' if skip_llm_when_prompt_exists else '正在构建'} Clip {clip_position}/{len(window_plans)} H3 提示词..."
        task.progress = int(10 + ((clip_position - 1) / len(window_plans)) * 70)
        task.reference_images = json.dumps(reference_images, ensure_ascii=False)
        _update_window_plan(shot, window_index, {
            "status": "PROMPT_BUILDING",
            "workflow_type": workflow_type,
            "workflow_name": workflow.name,
            "reference_images": reference_images,
            "speaker_timeline": audio_drive.get("speaker_timeline") or [],
            "audio_drive_context": audio_drive.get("audio_drive_context") or {},
            "error_message": None,
        }, db, task=task)
        db.commit()
        try:
            clip_prompt, on_before_submit = await _build_h3_prompt_for_worker(
                db=db, task=task, novel=novel, shot=shot, selected_mode="MULTI_KEYFRAME", clip=clip, workflow=workflow,
                workflow_capability=workflow_capability, start_image_url=start_image_url,
                keyframes=keyframes_for_prompt, transitions=clip_transitions_for_prompt, reference_images=reference_images,
                character_appearances=character_appearances, audio_drive=audio_drive,
                skip_llm_when_prompt_exists=skip_llm_when_prompt_exists,
            )
        except H3PromptValidationError:
            return
        if _is_task_cancelled(db, task):
            _cleanup_task_generated_clip_videos(db, task, shot)
            _mark_shot_video_failed(shot, shot_repo, "视频任务已取消")
            db.commit()
            return
        task.prompt_text = clip_prompt

        clip_duration = contract_clip_duration(clip["start_time"], clip["end_time"])
        raw_frame_count = int(fps * clip_duration)
        clip_frame_count = legal_h3_frame_count(clip_duration, fps)

        def save_prompt_id(prompt_id: str, submitted_workflow: dict = None):
            task.comfyui_prompt_id = prompt_id
            fields = {"status": "RUNNING", "prompt_id": prompt_id}
            if submitted_workflow:
                task.workflow_json = json.dumps(submitted_workflow, ensure_ascii=False, indent=2)
                fields["workflow_json"] = submitted_workflow
            _update_window_plan(shot, window_index, fields, db, task=task)
            db.commit()
            _save_h3_prompt_gate(db, task, on_before_submit.validation_record, prompt_id=prompt_id)
            print(f"[VideoTask {task_id}] Clip {clip_position} ComfyUI prompt_id: {prompt_id}")

        task.current_step = f"正在生成 Clip {clip_position}/{len(window_plans)}..."
        _update_window_plan_status(shot, window_index, "RUNNING", db, task=task)
        db.commit()
        try:
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
                reference_audio_path=None if audio_drive.get("enabled") else reference_audio_path,
                drive_audio_path=audio_drive.get("drive_audio_path"),
                final_audio_path=audio_drive.get("final_audio_path"),
                keyframe_paths=keyframe_paths,
                on_prompt_queued=save_prompt_id,
                on_before_submit=on_before_submit,
            )
        except Exception as exc:
            _save_h3_prompt_gate(db, task, on_before_submit.validation_record, error=exc)
            _fail_h3_video_clip(db, task, shot, clip, "MULTI_KEYFRAME", str(exc), target=on_before_submit.validation_record["target"])
            return
        if result.get("prompt_id"):
            _save_h3_prompt_gate(db, task, on_before_submit.validation_record, prompt_id=result["prompt_id"])
        if not result.get("success") or not result.get("video_url"):
            _save_h3_prompt_gate(db, task, on_before_submit.validation_record, error=result.get("message") or "Clip generation failed",
                                 failure_kind=result.get("failure_kind"))
        if _is_task_cancelled(db, task):
            _cleanup_task_generated_clip_videos(db, task, shot)
            _mark_shot_video_failed(shot, shot_repo, "视频任务已取消")
            db.commit()
            return
        if result.get("submitted_workflow"):
            task.workflow_json = json.dumps(result["submitted_workflow"], ensure_ascii=False, indent=2)
            db.commit()
        if not result.get("success") or not result.get("video_url"):
            _fail_h3_video_clip(db, task, shot, clip, "MULTI_KEYFRAME", result.get("message") or "Clip generation failed",
                                target=on_before_submit.validation_record["target"],
                                gate_failed=result.get("failure_kind") == "H3_PROMPT_SUBMISSION_REJECTED")
            return
        if result.get("submitted_workflow"):
            _update_window_plan(shot, window_index, {"workflow_json": result["submitted_workflow"]}, db, task=task)

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
        from app.services.rendered_subtitles import lock_generated_audio
        await lock_generated_audio(file_storage, local_path, clip.get("subtitle_audio_path"), clip.get("subtitle_snapshot"))
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
    VideoDirectorPlanService(db).mutate(
        shot.id,
        lambda plan: {**plan, "merged_video_url": local_url, "merged_at": datetime.utcnow().isoformat()},
    )
    _clear_shot_video_error(shot, shot_repo, video_url=local_url, video_status="completed", video_task_id=task.id)
    task.status = "completed"
    task.progress = 100
    task.result_url = local_url
    task.current_step = "生成完成"
    task.completed_at = datetime.utcnow()
    db.commit()


async def merge_video_director_clip_videos(db, shot, shot_repo: ShotRepository, novel_id: str, chapter_id: str, shot_index: int) -> dict:
    if hasattr(shot, "_execution_task_id"):
        return {"success": False, "message": "Strict video runs merge only their verified receipt manifest"}
    db.refresh(shot)
    plan = safe_json_dict(shot.video_director_plan)
    execution_task_id = plan.get("video_execution_task_id") or shot.video_task_id
    owner = db.query(Task).filter(Task.id == execution_task_id).first() if execution_task_id else None
    if plan.get("video_execution_task_id") or (owner and ("execution" in safe_json_dict(owner.metadata_json) or "video_run" in safe_json_dict(owner.metadata_json))):
        from app.services.shot_video_execution import completed_video_artifact
        return completed_video_artifact(db, execution_task_id, shot_id=shot.id)
    window_plans = plan.get("window_plans") if isinstance(plan.get("window_plans"), list) else []
    if not window_plans:
        return {"success": False, "message": "缺少 Clip 执行计划"}
    gate_failed_clips = [
        f"C{window.get('window_index') or position}" for position, window in enumerate(window_plans, 1)
        if isinstance(window, dict) and window.get("h3_prompt_gate_failed")
    ]
    if gate_failed_clips:
        return {"success": False, "message": f"H3_PROMPT_GATE_FAILED: {', '.join(gate_failed_clips)}; regenerate before merging"}

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
    from app.services.rendered_subtitles import matches_sources
    if existing_video_url and merged_at and (not latest_clip_generated_at or latest_clip_generated_at <= merged_at) and matches_sources(url_to_local_path(existing_video_url), clip_video_paths):
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
    plan, _revision = VideoDirectorPlanService(db).mutate(
        shot.id,
        lambda latest: {**latest, "merged_video_url": local_url, "merged_at": datetime.utcnow().isoformat()},
    )
    _clear_shot_video_error(shot, shot_repo, video_url=local_url, video_status="completed", video_task_id=None)
    return {"success": True, "video_url": local_url, "plan": plan}


async def _save_generated_video(
    result: dict, task, novel_id: str, chapter_id: str,
    shot_index: int, db, task_id: str, shot_repo: ShotRepository, clip: dict | None = None
):
    """下载并保存生成的视频"""
    task.current_step = "正在下载生成的视频..."
    task.progress = 80
    db.commit()

    video_url = result.get("video_url")
    if not video_url:
        task.status = "failed"
        task.error_message = "未获取到视频URL"
        task.current_step = "生成失败"
        shot = shot_repo.get_by_id(task.shot_id) if task.shot_id else None
        if shot:
            _mark_shot_video_failed(shot, shot_repo, task.error_message)
        db.commit()
        return

    local_path = await file_storage.download_video(
        url=video_url,
        novel_id=novel_id,
        chapter_id=chapter_id,
        shot_number=shot_index
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
        shot = shot_repo.get_by_id(task.shot_id) if task.shot_id else None
        if shot:
            _mark_shot_video_failed(shot, shot_repo, "视频任务已取消")
        db.commit()
        return

    if local_path:
        from app.services.rendered_subtitles import lock_generated_audio
        await lock_generated_audio(file_storage, local_path, (clip or {}).get("subtitle_audio_path"), (clip or {}).get("subtitle_snapshot"))
        relative_path = local_path.replace(str(file_storage.base_dir), "").replace("\\", "/")
        local_url = f"/api/files/{relative_path.lstrip('/')}"

        # 更新 Shot 记录中的视频数据
        shot = shot_repo.get_by_id(task.shot_id) if task.shot_id else None
        if shot:
            _update_clip_result(shot, clip or {}, {
                "status": "SUCCEEDED",
                "video_url": local_url,
                "local_path": local_path,
                "source_video_url": video_url,
                "generated_at": datetime.utcnow().isoformat(),
                "generated_by_task_id": task.id,
            }, db)
            _clear_shot_video_error(shot, shot_repo, video_url=local_url, video_status="completed")
            print(f"[VideoTask {task_id}] Shot video updated: {local_url}")

        task.status = "completed"
        task.progress = 100
        task.result_url = local_url
        task.current_step = "生成完成"
        task.completed_at = datetime.utcnow()
        db.commit()

        print(f"[VideoTask {task_id}] Video saved: {local_url}")
    else:
        task.status = "failed"
        task.error_message = "下载视频失败"
        task.current_step = "下载失败"
        shot = shot_repo.get_by_id(task.shot_id) if task.shot_id else None
        if shot:
            _mark_shot_video_failed(shot, shot_repo, task.error_message)
        db.commit()
