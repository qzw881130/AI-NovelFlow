"""Small, deterministic, I/O-free compilers for semantic Clip execution."""

from __future__ import annotations

from typing import Any

from app.utils.path_utils import local_path_to_url


class ClipExecutionCompileError(ValueError):
    """Raised when a semantic Clip cannot be compiled."""


_PLANNING_MODES = {"SINGLE_FRAME", "FIRST_LAST_FRAME", "MULTI_KEYFRAME"}


def _json_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _number(value: Any, field: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ClipExecutionCompileError(f"Clip {field} 无效")


def _legacy_keyframes(shot) -> list[dict]:
    import json

    try:
        value = json.loads(getattr(shot, "keyframes", None) or "[]")
    except (TypeError, ValueError):
        value = []
    return [item for item in value if isinstance(item, dict)]


def _keyframe_by_index(keyframes: list[dict], legacy: list[dict], index: int) -> dict | None:
    canonical = None
    for keyframe in keyframes:
        try:
            if int(keyframe.get("index")) == index:
                canonical = dict(keyframe)
                if canonical.get("image_url") or canonical.get("imageUrl"):
                    return canonical
                break
        except (TypeError, ValueError):
            continue
    for keyframe in legacy:
        try:
            if int(keyframe.get("plan_keyframe_index")) == index:
                fallback = {
                    "index": index,
                    "role": keyframe.get("role"),
                    "time_seconds": keyframe.get("time_seconds"),
                    "image_url": keyframe.get("image_url") or keyframe.get("imageUrl"),
                }
                return {**(canonical or {}), **fallback}
        except (TypeError, ValueError):
            continue
    return canonical


def _source_reference(slot: int, image_url: str | None, source_type: str, *, index=None, keyframe=None) -> dict:
    if not image_url:
        raise ClipExecutionCompileError(f"参考图 {slot} 缺少 image_url")
    return {
        "slot": slot,
        "kind": "DIRECTOR_VISUAL_ANCHOR",
        "source_type": source_type,
        "image_url": image_url,
        "source_keyframe_index": index,
        "source_role": keyframe.get("role") if keyframe else None,
        "source_time_seconds": keyframe.get("time_seconds") if keyframe else None,
    }


def compile_generate_clip(
    shot,
    plan: dict,
    clip: dict,
    planning_mode: str,
    clip_plan_revision: int,
    *,
    allow_empty_visual_references: bool = False,
) -> dict:
    """Compile one already-selected semantic Clip without performing I/O."""
    if planning_mode not in _PLANNING_MODES:
        raise ClipExecutionCompileError(f"不支持的视频规划模式: {planning_mode}")
    if not isinstance(clip, dict):
        raise ClipExecutionCompileError("Clip 计划无效")
    try:
        clip_index = int(clip.get("clip_index"))
    except (TypeError, ValueError):
        raise ClipExecutionCompileError("Clip index 无效")

    try:
        revision = int(clip_plan_revision)
        current_revision = int(plan.get("clip_plan_revision"))
    except (TypeError, ValueError):
        raise ClipExecutionCompileError("clip_plan_revision 无效")
    if revision != current_revision:
        raise ClipExecutionCompileError("Clip 计划 revision 已变化")

    start = _number(clip.get("start_time"), "start_time")
    end = _number(clip.get("end_time"), "end_time")
    duration = end - start
    shot_duration = _number(getattr(shot, "duration", None) or end, "shot duration")
    if start < 0 or end <= start or end > shot_duration + 0.05:
        raise ClipExecutionCompileError("Clip 时间范围无效")

    keyframes = _json_list(plan.get("keyframes"))
    legacy = _legacy_keyframes(shot)
    references: list[dict] = []
    shot_image_url = getattr(shot, "image_url", None)
    if not shot_image_url and getattr(shot, "image_path", None):
        shot_image_url = local_path_to_url(shot.image_path)

    if planning_mode == "SINGLE_FRAME":
        if shot_image_url:
            references.append(_source_reference(1, shot_image_url, "SHOT_IMAGE"))
    elif planning_mode == "FIRST_LAST_FRAME":
        if not shot_image_url:
            raise ClipExecutionCompileError("FIRST_LAST_FRAME 缺少 START/Shot image")
        start_keyframe = next((item for item in keyframes if str(item.get("role") or "").upper() == "START"), None) or {"index": 1, "role": "START", "time_seconds": 0.0}
        references.append(_source_reference(1, shot_image_url, "SHOT_IMAGE", index=start_keyframe.get("index") or 1, keyframe=start_keyframe))
        end_keyframe = next((item for item in keyframes if str(item.get("role") or "").upper() == "END"), None)
        if not end_keyframe:
            end_keyframe = next((item for item in legacy if str(item.get("role") or "").upper() == "END"), None)
        if not end_keyframe:
            raise ClipExecutionCompileError("FIRST_LAST_FRAME 缺少 END keyframe")
        end_index = end_keyframe.get("index") or end_keyframe.get("plan_keyframe_index")
        resolved = _keyframe_by_index(keyframes, legacy, int(end_index)) if end_index is not None else end_keyframe
        image_url = (resolved or {}).get("image_url") or (resolved or {}).get("imageUrl")
        if not image_url:
            raise ClipExecutionCompileError("FIRST_LAST_FRAME 缺少 END keyframe image")
        references.append(_source_reference(2, image_url, "KEYFRAME_IMAGE", index=end_index, keyframe=resolved or end_keyframe))
    else:
        indexes = clip.get("keyframe_indexes") or clip.get("keyframe_indices") or []
        for slot, raw_index in enumerate(indexes, 1):
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                raise ClipExecutionCompileError("Clip keyframe index 无效")
            keyframe = _keyframe_by_index(keyframes, legacy, index) or {}
            image_url = keyframe.get("image_url") or keyframe.get("imageUrl")
            if not image_url and index == 1 and str(keyframe.get("role") or "").upper() == "START":
                image_url = shot_image_url
                keyframe = {**keyframe, "role": "START", "time_seconds": keyframe.get("time_seconds", 0.0)}
            if not image_url:
                raise ClipExecutionCompileError(f"MULTI_KEYFRAME 缺少 Keyframe {index} image")
            references.append(_source_reference(slot, image_url, "KEYFRAME_IMAGE", index=index, keyframe=keyframe))

    if len(references) > 9:
        raise ClipExecutionCompileError("GENERATE 最多支持 9 张参考图")
    if planning_mode in {"FIRST_LAST_FRAME", "MULTI_KEYFRAME"} and not references and not allow_empty_visual_references:
        raise ClipExecutionCompileError("Clip 缺少可用的视觉参考图")

    contract = {
        "version": 1,
        "capability": "GENERATE",
        "artifact_kind": "CLIP_ONLY",
        "clip": {
            "clip_id": f"{shot.id}:clip:{clip_index}",
            "clip_index": clip_index,
            "clip_plan_revision": revision,
            "start_seconds": start,
            "end_seconds": end,
            "duration_seconds": duration,
        },
    }
    return {
        "execution_contract": contract,
        "video_reference_manifest": {"version": 1, "references": references},
    }


def compile_extend_clip(
    shot,
    plan: dict,
    clip: dict,
    planning_mode: str,
    clip_plan_revision: int,
    previous_provenance: dict | None,
) -> dict:
    """Compile an EXTEND Clip while keeping all physical resolution outside the compiler."""
    if not isinstance(clip, dict) or clip.get("capability") != "EXTEND":
        raise ClipExecutionCompileError("EXTEND Clip capability 无效")
    if str(clip.get("continuity_to_previous") or "").upper() != "CONTINUOUS":
        raise ClipExecutionCompileError("EXTEND 需要 CONTINUOUS continuity_to_previous")
    if bool(clip.get("requires_temporal_control")):
        raise ClipExecutionCompileError("TEMPORAL_EXTEND 尚未在 Phase C 实现")
    try:
        previous_index = int(clip.get("previous_clip_index"))
    except (TypeError, ValueError):
        raise ClipExecutionCompileError("EXTEND 缺少 previous_clip_index")
    if not isinstance(previous_provenance, dict):
        raise ClipExecutionCompileError("EXTEND 缺少 Previous AV provenance")
    required = ("clip_index", "clip_plan_revision", "generated_by_task_id", "result_url")
    if any(previous_provenance.get(key) in (None, "") for key in required):
        raise ClipExecutionCompileError("EXTEND Previous AV provenance 不完整")
    try:
        previous_revision = int(previous_provenance["clip_plan_revision"])
        revision = int(clip_plan_revision)
        previous_clip_index = int(previous_provenance["clip_index"])
    except (TypeError, ValueError):
        raise ClipExecutionCompileError("EXTEND Previous AV provenance 无效")
    if previous_revision != revision or previous_clip_index != previous_index:
        raise ClipExecutionCompileError("EXTEND Previous AV provenance 与 Clip 不匹配")

    # Reuse the proven visual projection.  It remains a logical manifest and
    # never resolves or uploads the resulting local paths.
    compiled = compile_generate_clip(
        shot, plan, {**clip, "capability": "GENERATE"}, planning_mode, revision,
        allow_empty_visual_references=True,
    )
    contract = dict(compiled["execution_contract"])
    contract["capability"] = "EXTEND"
    contract["previous_clip"] = {
        "clip_index": previous_clip_index,
        "clip_plan_revision": previous_revision,
        "generated_by_task_id": str(previous_provenance["generated_by_task_id"]),
        "result_url": str(previous_provenance["result_url"]),
    }
    return {
        "execution_contract": contract,
        "video_reference_manifest": compiled["video_reference_manifest"],
    }
