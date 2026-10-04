"""Small, deterministic, I/O-free compilers for semantic Clip execution."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from app.utils.path_utils import local_path_to_url, url_to_local_path


class ClipExecutionCompileError(ValueError):
    """Raised when a semantic Clip cannot be compiled."""

    def __init__(self, message: str, *, detail: dict | None = None):
        super().__init__(message)
        self.detail = detail


_TEMPORAL_ANCHOR_LIMIT = 8
TEMPORAL_DECISION_CONTRACT = "ELIGIBLE_THEN_SELECTED_V1"


def temporal_extend_frame_count(duration_seconds: float) -> int:
    """Match frozen temporal workflow #126's H3 latent-frame expression."""
    try:
        duration = Decimal(str(duration_seconds))
    except (InvalidOperation, TypeError, ValueError):
        raise ClipExecutionCompileError("TEMPORAL_EXTEND 时长无效")
    if not duration.is_finite() or duration <= 0:
        raise ClipExecutionCompileError("TEMPORAL_EXTEND 时长无效")
    raw_frames = int((duration * Decimal(24)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    raw_frames = max(5, raw_frames)
    return raw_frames + (5 - raw_frames % 17) % 17


def project_temporal_anchor_positions(anchors: list[dict], duration_seconds: float) -> list[dict]:
    """Sort Clip-local anchors and project them to frozen 1-based H3 frames."""
    if not isinstance(anchors, list) or not anchors:
        raise ClipExecutionCompileError("TEMPORAL_ANCHOR_UNAVAILABLE")
    if len(anchors) > _TEMPORAL_ANCHOR_LIMIT:
        raise ClipExecutionCompileError("TEMPORAL_EXTEND 最多支持 8 个 Temporal Anchor")
    try:
        duration = Decimal(str(duration_seconds))
    except (InvalidOperation, TypeError, ValueError):
        raise ClipExecutionCompileError("TEMPORAL_EXTEND 时长无效")
    frame_count = temporal_extend_frame_count(duration_seconds)
    ordered = []
    seen_ids = set()
    seen_times = set()
    for anchor in anchors:
        if not isinstance(anchor, dict):
            raise ClipExecutionCompileError("TEMPORAL_ANCHOR_UNAVAILABLE")
        anchor_id = str(anchor.get("anchor_id") or anchor.get("id") or "").strip()
        image_url = anchor.get("image_url") or anchor.get("image") or anchor.get("image_path")
        source = anchor.get("source") or anchor.get("provenance")
        if not anchor_id or not image_url or not isinstance(source, dict):
            raise ClipExecutionCompileError("TEMPORAL_ANCHOR_UNAVAILABLE")
        if anchor_id in seen_ids:
            raise ClipExecutionCompileError("TEMPORAL_ANCHOR_UNAVAILABLE: duplicate anchor_id")
        try:
            time = Decimal(str(anchor.get("time_seconds")))
        except (InvalidOperation, TypeError, ValueError):
            raise ClipExecutionCompileError("TEMPORAL_ANCHOR_UNAVAILABLE")
        if not time.is_finite() or time < 0 or time > duration:
            raise ClipExecutionCompileError("TEMPORAL_ANCHOR_UNAVAILABLE: anchor outside Clip")
        if time in seen_times:
            raise ClipExecutionCompileError("TEMPORAL_ANCHOR_UNAVAILABLE: duplicate anchor time")
        seen_ids.add(anchor_id)
        seen_times.add(time)
        ordered.append((time, anchor_id, anchor, image_url, source))
    ordered.sort(key=lambda item: (item[0], item[1]))

    result = []
    seen_positions = set()
    for slot, (time, anchor_id, anchor, image_url, source) in enumerate(ordered, 1):
        scaled = (time / duration) * Decimal(frame_count - 1)
        position = 1 + int(scaled.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if position < 1 or position > frame_count:
            raise ClipExecutionCompileError("TEMPORAL_ANCHOR_UNAVAILABLE: projected frame out of bounds")
        if position in seen_positions:
            raise ClipExecutionCompileError("TEMPORAL_ANCHOR_UNAVAILABLE: duplicate projected frame")
        seen_positions.add(position)
        result.append({
            "slot": slot,
            "anchor_id": anchor_id,
            "time_seconds": float(time),
            "frame_position": position,
            "image_url": str(image_url),
            "description": anchor.get("description"),
            "source": dict(source),
        })
    return result


def _json_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _number(value: Any, field: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ClipExecutionCompileError(f"Clip {field} 无效")


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
        "source_image_task_id": keyframe.get("image_task_id") if keyframe else None,
    }


def _shot_image_url(shot) -> str | None:
    image_url = getattr(shot, "image_url", None)
    if not image_url and getattr(shot, "image_path", None):
        image_url = local_path_to_url(shot.image_path)
    return image_url


def get_generate_visual_start_readiness(shot, plan: dict, clip: dict) -> dict:
    """Resolve the physical authority for a GENERATE Clip's first-owned state."""
    clip_index = clip.get("clip_index") if isinstance(clip, dict) else None
    result = {
        "ready": True,
        "applicable": False,
        "code": "NOT_APPLICABLE",
        "message": None,
        "clip_index": clip_index,
        "visual_state_index": None,
        "time_seconds": None,
        "grounding_source": None,
        "image_url": None,
    }
    if not isinstance(clip, dict) or str(clip.get("capability") or "").upper() != "GENERATE":
        return result

    result["applicable"] = True
    owned = clip.get("visual_state_indexes")
    first_raw = owned[0] if isinstance(owned, list) and owned else None
    try:
        first_index = int(first_raw)
    except (TypeError, ValueError):
        first_index = None

    states = {
        int(item.get("index")): item
        for item in _json_list(plan.get("keyframes"))
        if isinstance(item, dict) and item.get("index") is not None
    }
    first_state = states.get(first_index) if first_index is not None else None
    time_seconds = first_state.get("time_seconds") if first_state else None
    result.update({
        "visual_state_index": first_index,
        "time_seconds": time_seconds,
    })

    image_url = first_state.get("image_url") or first_state.get("imageUrl") if first_state else None
    grounding_source = "KEYFRAME_IMAGE" if image_url else None
    if (
        not image_url
        and first_state
        and first_index == 1
        and str(first_state.get("role") or "").upper() == "START"
    ):
        image_url = _shot_image_url(shot)
        grounding_source = "SHOT_IMAGE" if image_url else None
    if image_url:
        result.update({
            "code": "READY",
            "grounding_source": grounding_source,
            "image_url": image_url,
        })
        return result

    state_label = f"视觉状态 {first_index}" if first_index is not None else "首个 owned 视觉状态"
    if time_seconds is not None:
        state_label += f"（{time_seconds}s）"
    message = f"缺少片段起始视觉图：Clip {clip_index} · {state_label}"
    result.update({
        "ready": False,
        "code": "GENERATE_VISUAL_START_GROUNDING_MISSING",
        "message": message,
    })
    return result


def get_canonical_execution_readiness(shot, plan: dict, clips: list[dict] | None = None) -> dict:
    """Project execution blockers without reinterpreting historical temporal plans."""
    blockers = []
    plan_clips = plan.get("clip_plan") if isinstance(plan, dict) else None
    if plan.get("canonical_visual_plan") is True and plan_clips and (
        (plan.get("clip_plan_validation") or {}).get("temporal_contract") != TEMPORAL_DECISION_CONTRACT
    ):
        blocker = {"ready": False, "code": "TEMPORAL_CONTRACT_REPLAN_REQUIRED",
                   "message": "历史片段计划需重新规划，以确认定时目标选择", "clip_index": None,
                   "visual_state_index": None, "time_seconds": None}
        return {"ready": False, "code": blocker["code"], "message": blocker["message"], "blocking_clips": [blocker]}
    clips = plan_clips if clips is None else clips
    states = {f"KF{item['index']}": item for item in plan.get("keyframes") or [] if isinstance(item, dict) and "index" in item}
    anchors = {str(item.get("anchor_id")): item for item in plan.get("temporal_anchors") or [] if isinstance(item, dict)}
    for clip in clips if isinstance(clips, list) else []:
        readiness = get_generate_visual_start_readiness(shot, plan, clip)
        if readiness["applicable"] and not readiness["ready"]:
            blockers.append(readiness)
        if clip.get("capability") == "TEMPORAL_EXTEND":
            for state_id in clip.get("selected_temporal_target_ids") or []:
                state = states.get(state_id) or {}
                anchor = anchors.get(f"clip-{clip.get('clip_index')}-{state_id}") or {}
                image_url = anchor.get("image_url")
                image_path = (url_to_local_path(image_url) or image_url) if image_url else None
                if not image_path or not Path(image_path).is_file():
                    blockers.append({"ready": False, "code": "TEMPORAL_ANCHOR_UNAVAILABLE",
                                     "message": f"缺少已选定时目标图片：Clip {clip.get('clip_index')} · {state_id}",
                                     "clip_index": clip.get("clip_index"), "visual_state_index": state.get("index"),
                                     "time_seconds": state.get("time_seconds"), "grounding_source": "KEYFRAME_IMAGE"})
    first = blockers[0] if blockers else None
    return {
        "ready": not blockers,
        "code": first["code"] if first else "READY",
        "message": first["message"] if first else None,
        "blocking_clips": blockers,
    }


def project_canonical_visual_references(shot, plan: dict, clip: dict, temporal_anchors: list[dict] | None = None) -> dict:
    """Purely project owned canonical states into the ordinary H3 manifest."""
    states = {
        int(item.get("index")): item
        for item in _json_list(plan.get("keyframes"))
        if isinstance(item, dict) and item.get("index") is not None
    }
    temporal_indexes = set()
    for anchor in temporal_anchors or []:
        source = anchor.get("source") or anchor.get("provenance") if isinstance(anchor, dict) else None
        if not isinstance(source, dict):
            continue
        raw_index = source.get("keyframe_index")
        if raw_index is None:
            source_id = str(source.get("id") or "")
            raw_index = source_id[2:] if source_id.upper().startswith("KF") else None
        try:
            if raw_index is not None:
                temporal_indexes.add(int(raw_index))
        except (TypeError, ValueError):
            continue

    shot_image_url = _shot_image_url(shot)
    ordered = []
    for raw_index in clip.get("visual_state_indexes") or []:
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            raise ClipExecutionCompileError("视觉状态 index 无效")
        state = states.get(index)
        if not state:
            raise ClipExecutionCompileError(f"视觉状态 KF{index} 不存在")
        if index in temporal_indexes:
            continue
        image_url = state.get("image_url") or state.get("imageUrl")
        source_type = "KEYFRAME_IMAGE"
        resolved_state = dict(state)
        if not image_url and index == 1 and str(state.get("role") or "").upper() == "START":
            image_url = shot_image_url
            source_type = "SHOT_IMAGE"
            resolved_state["image_url"] = image_url
        if not image_url:
            continue
        try:
            time_seconds = float(state.get("time_seconds"))
        except (TypeError, ValueError):
            raise ClipExecutionCompileError(f"视觉状态 KF{index} time_seconds 无效")
        ordered.append((time_seconds, index, source_type, image_url, resolved_state))
    ordered.sort(key=lambda item: (item[0], item[1]))
    if len(ordered) > 9:
        raise ClipExecutionCompileError(
            f"ORDINARY_REFERENCE_BUDGET_EXCEEDED: Clip {clip.get('clip_index')} projects {len(ordered)} ordinary refs (maximum=9)"
        )
    references = [
        _source_reference(slot, image_url, source_type, index=index, keyframe=state)
        for slot, (_, index, source_type, image_url, state) in enumerate(ordered, 1)
    ]
    return {"version": 1, "references": references}


def compile_generate_clip(
    shot,
    plan: dict,
    clip: dict,
    clip_plan_revision: int,
) -> dict:
    """Compile one already-selected semantic Clip without performing I/O."""
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

    readiness = get_generate_visual_start_readiness(shot, plan, clip)
    if not readiness["ready"]:
        raise ClipExecutionCompileError(readiness["message"], detail=readiness)

    manifest = project_canonical_visual_references(shot, plan, clip)

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
        "video_reference_manifest": manifest,
    }


def compile_extend_clip(
    shot,
    plan: dict,
    clip: dict,
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
    compiled = compile_generate_clip(shot, plan, clip, revision)
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


def compile_temporal_extend_clip(
    shot,
    plan: dict,
    clip: dict,
    clip_plan_revision: int,
    previous_provenance: dict | None,
    temporal_anchors: list[dict],
) -> dict:
    """Compile a semantic TEMPORAL_EXTEND Clip using pre-resolved pure inputs."""
    if not isinstance(clip, dict) or clip.get("capability") != "TEMPORAL_EXTEND":
        raise ClipExecutionCompileError("TEMPORAL_EXTEND Clip capability 无效")
    if str(clip.get("continuity_to_previous") or "").upper() != "CONTINUOUS":
        raise ClipExecutionCompileError("TEMPORAL_EXTEND 需要 CONTINUOUS continuity_to_previous")
    if clip.get("requires_temporal_control") is not True:
        raise ClipExecutionCompileError("TEMPORAL_EXTEND requires_temporal_control 必须为 true")
    try:
        previous_index = int(clip.get("previous_clip_index"))
    except (TypeError, ValueError):
        raise ClipExecutionCompileError("TEMPORAL_EXTEND 缺少 previous_clip_index")
    if previous_index < 1:
        raise ClipExecutionCompileError("TEMPORAL_EXTEND 缺少 previous_clip_index")
    if not isinstance(previous_provenance, dict):
        raise ClipExecutionCompileError("PREVIOUS_AV_UNAVAILABLE")
    required = ("clip_index", "clip_plan_revision", "generated_by_task_id", "result_url")
    if any(previous_provenance.get(key) in (None, "") for key in required):
        raise ClipExecutionCompileError("PREVIOUS_AV_UNAVAILABLE")
    try:
        revision = int(clip_plan_revision)
        previous_revision = int(previous_provenance["clip_plan_revision"])
        previous_clip_index = int(previous_provenance["clip_index"])
    except (TypeError, ValueError):
        raise ClipExecutionCompileError("PREVIOUS_AV_UNAVAILABLE")
    if previous_revision != revision or previous_clip_index != previous_index:
        raise ClipExecutionCompileError("PREVIOUS_AV_UNAVAILABLE")

    compiled = {
        "execution_contract": {
            "version": 1,
            "capability": "GENERATE",
            "artifact_kind": "CLIP_ONLY",
            "clip": {
                "clip_id": f"{shot.id}:clip:{int(clip.get('clip_index'))}",
                "clip_index": int(clip.get("clip_index")),
                "clip_plan_revision": revision,
                "start_seconds": _number(clip.get("start_time"), "start_time"),
                "end_seconds": _number(clip.get("end_time"), "end_time"),
                "duration_seconds": _number(clip.get("end_time"), "end_time") - _number(clip.get("start_time"), "start_time"),
            },
        },
        "video_reference_manifest": project_canonical_visual_references(shot, plan, clip, temporal_anchors),
    }
    temporal_manifest = project_temporal_anchor_positions(
        temporal_anchors, float(compiled["execution_contract"]["clip"]["duration_seconds"]),
    )
    contract = dict(compiled["execution_contract"])
    contract["capability"] = "TEMPORAL_EXTEND"
    contract["previous_clip"] = {
        "clip_index": previous_clip_index,
        "clip_plan_revision": previous_revision,
        "generated_by_task_id": str(previous_provenance["generated_by_task_id"]),
        "result_url": str(previous_provenance["result_url"]),
    }
    contract["temporal_anchor_manifest"] = {"manifest_version": "1.0", "anchors": temporal_manifest}
    return {
        "execution_contract": contract,
        "video_reference_manifest": compiled["video_reference_manifest"],
    }
