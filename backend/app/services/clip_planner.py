"""Minimal semantic Clip Planner entry point for Flow First V1."""
import json
import math
import os
from copy import deepcopy

from sqlalchemy.orm import Session

from app.constants.capability import VIDEO_CAPABILITY_CONTRACTS
from app.services.llm_service import LLMService
from app.services.prompt_template_service import PromptTemplateService
from app.services.clip_validator import validate_clip_plan
from app.services.clip_execution_compiler import (
    TEMPORAL_DECISION_CONTRACT, EARLY_COMPOSITION_CONTRACT, execution_temporal_state_ids,
)
from app.services.dialogue_ownership import assign_dialogues_to_clips
from app.services.video_director_ai import align_clip_boundaries_to_dialogue_gaps, build_dialogue_timeline
from app.utils.path_utils import local_path_to_url, url_to_local_path
from app.utils.time_utils import clip_time_seconds, CLIP_OWNERSHIP_TOLERANCE


def _project_speech_timing_intervals(shot, video_plan: dict) -> list[dict]:
    """Expose dialogue timing to #10A without text, speaker, or speech semantics."""
    try:
        shot_dialogues = json.loads(getattr(shot, "dialogues", None) or "[]")
    except Exception:
        shot_dialogues = []
    timeline = video_plan.get("dialogue_timeline_source")
    generated, _, status = build_dialogue_timeline(
        {"start_time": 0, "end_time": getattr(shot, "duration", None) or 4},
        shot_dialogues,
        json.loads(getattr(shot, "characters", None) or "[]"),
    )
    if status.get("status") == "ok" and generated:
        timeline = generated
    if not isinstance(timeline, list):
        return []

    intervals = []
    for position, item in enumerate(timeline, 1):
        if not isinstance(item, dict):
            continue
        try:
            start = float(item.get("shot_start_time", item.get("start_time")))
            end = float(item.get("shot_end_time", item.get("end_time")))
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        intervals.append({
            "event_id": str(item.get("dialogue_id") or item.get("id") or f"D{position}"),
            "start_time": round(start, 2),
            "end_time": round(end, 2),
        })
    return intervals


def build_clip_planner_input(shot, temporal_anchors: list[dict], planning_policy: dict | None = None) -> dict:
    image_url = getattr(shot, "image_url", None)
    image_path = getattr(shot, "image_path", None)
    shot_image_path = (url_to_local_path(image_url) if image_url else None) or image_path
    if shot_image_path and not os.path.isfile(shot_image_path):
        shot_image_path = None
    try:
        video_plan = json.loads(getattr(shot, "video_director_plan", None) or "{}")
    except Exception:
        video_plan = {}
    keyframes = video_plan.get("keyframes") or []
    try:
        legacy_keyframes = json.loads(getattr(shot, "keyframes", None) or "[]")
    except Exception:
        legacy_keyframes = []
    def resolve_image(image_url: str | None) -> str | None:
        if not image_url:
            return None
        path = url_to_local_path(image_url) or image_url
        return path if path and os.path.isfile(path) else None

    canonical_by_index = {}
    for keyframe in keyframes:
        if not isinstance(keyframe, dict) or keyframe.get("index") is None:
            continue
        try:
            index = int(keyframe["index"])
        except (TypeError, ValueError):
            continue
        if index in canonical_by_index:
            raise ValueError(f"Duplicate canonical visual-state identity: KF{index}")
        canonical_by_index[index] = keyframe

    compatibility_by_index = {}
    for keyframe in legacy_keyframes:
        if not isinstance(keyframe, dict) or keyframe.get("plan_keyframe_index") is None:
            continue
        try:
            index = int(keyframe["plan_keyframe_index"])
        except (TypeError, ValueError):
            continue
        compatibility_by_index[index] = keyframe

    # Shot.image is the canonical START/KF1 visual asset.
    keyframe_images_by_index = {}
    shot_image_source = image_url or (local_path_to_url(shot_image_path) if shot_image_path else None)
    if shot_image_path and os.path.isfile(shot_image_path):
        keyframe_images_by_index[1] = {"index": 1, "url": shot_image_source}

    for index, keyframe in canonical_by_index.items():
        if index == 1 and 1 in keyframe_images_by_index:
            continue
        image_value = keyframe.get("image_url") or keyframe.get("imageUrl")
        if resolve_image(image_value):
            keyframe_images_by_index[index] = {"index": index, "url": image_value}
            continue
        compatibility = compatibility_by_index.get(index)
        compatibility_value = (compatibility or {}).get("image_url") or (compatibility or {}).get("imageUrl")
        if resolve_image(compatibility_value):
            keyframe_images_by_index[index] = {"index": index, "url": compatibility_value}

    # Preserve compatibility-only indexes when no canonical record exists.
    for index, keyframe in compatibility_by_index.items():
        if index in keyframe_images_by_index or index in canonical_by_index:
            continue
        image_value = keyframe.get("image_url") or keyframe.get("imageUrl")
        if resolve_image(image_value):
            keyframe_images_by_index[index] = {"index": index, "url": image_value}

    keyframe_images = [keyframe_images_by_index[index] for index in sorted(keyframe_images_by_index)]
    visual_state_candidates = []
    for index in sorted(canonical_by_index):
        keyframe = canonical_by_index[index]
        image_value = (keyframe_images_by_index.get(index) or {}).get("url")
        compatibility = compatibility_by_index.get(index) or {}
        visual_state_candidates.append({
            "visual_state_id": f"KF{index}",
            "keyframe_index": index,
            "time_seconds": keyframe.get("time_seconds"),
            "role": keyframe.get("role") or "INTERMEDIATE",
            "description": keyframe.get("description") or "",
            "timed_visual_target": keyframe.get("timed_visual_target") is True,
            "image_available": bool(image_value),
            "image_url": image_value,
            "source": {
                "type": "KEYFRAME",
                "id": f"KF{index}",
                "keyframe_index": index,
                "image_task_id": keyframe.get("image_task_id") or compatibility.get("image_task_id"),
            },
        })
    transition_context = []
    try:
        transition_items = json.loads(getattr(shot, "video_director_plan", None) or "{}").get("transitions") or []
    except Exception:
        transition_items = []
    for transition in transition_items:
        if not isinstance(transition, dict):
            continue
        transition_context.append({
            "from_keyframe_index": transition.get("from_keyframe_index"),
            "to_keyframe_index": transition.get("to_keyframe_index"),
            "start_time": transition.get("start_time"),
            "end_time": transition.get("end_time"),
            "transition_description": transition.get("transition_description") or "",
        })
    canonical_visual_plan = video_plan.get("canonical_visual_plan") is True
    end_keyframe_image = False
    for keyframe in keyframes + legacy_keyframes:
        if not isinstance(keyframe, dict):
            continue
        if str(keyframe.get("role") or "").upper() == "END":
            image_url = keyframe.get("image_url") or keyframe.get("imageUrl")
            path = url_to_local_path(image_url) if image_url else None
            path = path or image_url
            end_keyframe_image = bool(path and os.path.isfile(path))
        if keyframe.get("plan_keyframe_index") is not None:
            plan_keyframe = next((item for item in keyframes if int(item.get("index") or -1) == int(keyframe["plan_keyframe_index"])), None)
            if plan_keyframe and str(plan_keyframe.get("role") or "").upper() == "END":
                image_url = keyframe.get("image_url") or keyframe.get("imageUrl")
                path = url_to_local_path(image_url) if image_url else None
                path = path or image_url
                end_keyframe_image = bool(path and os.path.isfile(path))
    anchor_images = []
    for anchor in temporal_anchors or []:
        image_value = anchor.get("image_path") or anchor.get("image") or anchor.get("image_url")
        path = url_to_local_path(image_value) if image_value else None
        path = path or (image_value if image_value and os.path.isfile(image_value) else None)
        if path and os.path.isfile(path):
            anchor_images.append(anchor.get("anchor_id") or anchor.get("id"))
    available_inputs = {
        "shot_image": bool(shot_image_path and os.path.isfile(shot_image_path)),
        "keyframe_images": keyframe_images,
        "end_keyframe_image": end_keyframe_image,
        "temporal_anchor_images": anchor_images,
        "previous_approved_video": False,
    }
    return {
        "shot": {
            "id": shot.id,
            "duration": shot.duration or 4,
            "continuity_mode": shot.continuity_mode or "NORMAL",
            "characters": json.loads(getattr(shot, "characters", None) or "[]"),
            "scene": getattr(shot, "scene", None) or "",
            "props": json.loads(getattr(shot, "props", None) or "[]"),
        },
        "available_generation_inputs": available_inputs,
        # Historical mode remains readable for old plans, but canonical plans
        # must not expose it as #10A planning authority.
        "canonical_visual_plan": canonical_visual_plan,
        "speech_timing_intervals": _project_speech_timing_intervals(shot, video_plan),
        "visual_state_candidates": visual_state_candidates,
        "transition_context": transition_context,
        "planning_policy": {
            "approval_mode": (planning_policy or {}).get("approval_mode", "AUTO_APPROVE"),
            "min_story_clip_duration": max(
                float((planning_policy or {}).get("min_story_clip_duration") or 0),
                min(contract["min_duration"] for contract in VIDEO_CAPABILITY_CONTRACTS.values() if contract.get("enabled")),
            ),
            "max_story_clip_duration": float(VIDEO_CAPABILITY_CONTRACTS["GENERATE"]["max_duration"]),
        },
    }


def _project_clip_visual_states(clips: list[dict], candidates: list[dict]) -> None:
    """Project canonical Director states into semantic Clip ownership fields."""
    ordered = []
    for item in candidates or []:
        if not isinstance(item, dict):
            continue
        try:
            ordered.append((clip_time_seconds(item.get("time_seconds")), int(item.get("keyframe_index")), item))
        except (TypeError, ValueError):
            continue
    ordered.sort(key=lambda value: (value[0], value[1]))
    for position, clip in enumerate(clips, 1):
        try:
            clip_index = int(clip.get("clip_index") or position)
            start = clip_time_seconds(clip.get("start_time"))
            end = clip_time_seconds(clip.get("end_time"))
        except (TypeError, ValueError):
            continue
        owned = []
        for time_seconds, index, item in ordered:
            if clip_index == 1 and index == 1 and str(item.get("role") or "").upper() == "START":
                owned.append(index)
            elif time_seconds > start + CLIP_OWNERSHIP_TOLERANCE and time_seconds <= end + CLIP_OWNERSHIP_TOLERANCE:
                owned.append(index)
        carry_in = None
        if clip_index > 1:
            predecessors = [index for time_seconds, index, _ in ordered if time_seconds <= start + CLIP_OWNERSHIP_TOLERANCE]
            if predecessors:
                carry_in = predecessors[-1]
        clip["visual_state_indexes"] = list(dict.fromkeys(owned))
        clip["carry_in_state_index"] = carry_in


def _normalize_provider_boundaries(
    clips: list[dict],
    shot_duration: float,
    minimum: float,
    maximum: float,
    dialogue_timeline: list[dict] | None = None,
) -> bool:
    """Keep contiguous planner boundaries inside the provider duration contract."""
    ordered = sorted(clips or [], key=lambda item: float(item.get("start_time") or 0))
    if not ordered:
        return False
    dialogue_intervals = []
    for item in dialogue_timeline or []:
        try:
            start = float(item.get("start_time"))
            end = float(item.get("end_time"))
        except (AttributeError, TypeError, ValueError):
            continue
        if end > start:
            dialogue_intervals.append((start, end))

    def boundary_is_legal(value: float) -> bool:
        return not any(start < value < end for start, end in dialogue_intervals)

    for clip in ordered:
        clip["start_time"] = round(float(clip.get("start_time") or 0), 2)
        clip["end_time"] = round(float(clip.get("end_time") or 0), 2)
    for left, right in zip(ordered, ordered[1:]):
        boundary = float(left["end_time"])
        right_end = float(right["end_time"])
        left_start = float(left["start_time"])
        # Prefer moving a short tail boundary backwards (18s -> 14s + 4s).
        if right_end - boundary < minimum - 1e-6:
            candidate = right_end - minimum
            if candidate - left_start >= minimum - 1e-6 and boundary_is_legal(candidate):
                boundary = candidate
        # Also repair a short left side when the right side can absorb it.
        if boundary - left_start < minimum - 1e-6:
            candidate = left_start + minimum
            if right_end - candidate >= minimum - 1e-6 and boundary_is_legal(candidate):
                boundary = candidate
        # Keep an oversized left side within the provider maximum where possible.
        if boundary - left_start > maximum + 1e-6:
            candidate = left_start + maximum
            if right_end - candidate >= minimum - 1e-6 and boundary_is_legal(candidate):
                boundary = candidate
        left["end_time"] = round(boundary, 2)
        right["start_time"] = round(boundary, 2)
    # A final tail can only be repaired by shifting its preceding boundary.
    tail = ordered[-1]
    tail_start = float(tail["start_time"])
    tail_end = float(tail["end_time"])
    if tail_end - tail_start < minimum - 1e-6 and len(ordered) > 1:
        previous = ordered[-2]
        candidate = tail_end - minimum
        if candidate - float(previous["start_time"]) >= minimum - 1e-6 and boundary_is_legal(candidate):
            previous["end_time"] = round(candidate, 2)
            tail["start_time"] = round(candidate, 2)
    return all(
        minimum - 1e-6 <= float(item.get("end_time")) - float(item.get("start_time")) <= maximum + 1e-6
        for item in ordered
    ) and abs(float(ordered[0].get("start_time") or 0)) <= 0.05 and abs(float(ordered[-1].get("end_time") or 0) - float(shot_duration)) <= 0.05


def _project_temporal_targets(clips: list[dict], candidates: list[dict], shot_duration: float) -> None:
    """Validate #10A's owned eligible subset; derive execution, never select for it."""
    by_id: dict[str, dict] = {}
    for item in candidates:
        if not isinstance(item, dict) or item.get("timed_visual_target") is not True:
            continue
        state_id = str(item.get("visual_state_id") or "")
        if not state_id or state_id in by_id:
            raise ValueError(f"Duplicate or invalid timed visual target identity: {state_id or '<missing>'}")
        try:
            time_seconds = float(item.get("time_seconds"))
        except (TypeError, ValueError):
            raise ValueError(f"Timed visual target {state_id} has invalid time")
        if not math.isfinite(time_seconds) or time_seconds < -0.05 or time_seconds > float(shot_duration) + 0.05:
            raise ValueError(f"Timed visual target {state_id} is outside Shot timeline or has invalid time")
        by_id[state_id] = item

    max_targets = int((VIDEO_CAPABILITY_CONTRACTS.get("TEMPORAL_EXTEND") or {}).get("max_temporal_anchors") or 8)
    for clip in clips:
        continuity = str(clip.get("continuity_to_previous") or "").upper()
        start = float(clip.get("start_time"))
        end = float(clip.get("end_time"))
        selected = clip.get("selected_temporal_target_ids")
        if not isinstance(selected, list) or any(not isinstance(item, str) for item in selected):
            raise ValueError("TEMPORAL_SELECTION_INVALID: selected_temporal_target_ids must be a list")
        if len(selected) != len(set(selected)):
            raise ValueError("TEMPORAL_SELECTION_INVALID: duplicate selected ID")
        if continuity != "CONTINUOUS" and selected:
            raise ValueError("TEMPORAL_SELECTION_INVALID: NONE/CUT cannot select temporal targets")
        if continuity == "CONTINUOUS":
            if int(clip.get("previous_clip_index") or 0) != int(clip.get("clip_index")) - 1:
                raise ValueError("TEMPORAL_SELECTION_INVALID: previous Clip dependency missing")
            owned = clip.get("visual_state_indexes") or []
            for state_id in selected:
                state = by_id.get(state_id)
                if not state or state.get("keyframe_index") not in owned:
                    raise ValueError(f"TEMPORAL_SELECTION_INVALID: {state_id} is not an owned eligible state")
                shot_time = float(state["time_seconds"])
                if not (clip_time_seconds(start) + CLIP_OWNERSHIP_TOLERANCE < clip_time_seconds(shot_time) <= clip_time_seconds(end)):
                    raise ValueError(f"TEMPORAL_SELECTION_INVALID: {state_id} outside Clip")
            selected.sort(key=lambda state_id: (float(by_id[state_id]["time_seconds"]), state_id))
            if len(selected) > max_targets:
                raise ValueError(f"TEMPORAL_ANCHOR_LIMIT: Clip {clip.get('clip_index')} exceeds {max_targets} required temporal targets")
            seen_times = set()
            for state_id in selected:
                state = by_id[state_id]
                local_time = round(float(state["time_seconds"]) - start, 2)
                if local_time in seen_times:
                    raise ValueError(f"Clip {clip.get('clip_index')} has duplicate temporal target time")
                seen_times.add(local_time)

        requires_temporal = continuity == "CONTINUOUS" and bool(selected)
        clip["requires_temporal_control"] = requires_temporal
        clip["selected_temporal_target_ids"] = selected
        clip["capability"] = "TEMPORAL_EXTEND" if requires_temporal else ("EXTEND" if continuity == "CONTINUOUS" else "GENERATE")


def _validate_inherited_start_composition(clip: dict, candidates: list[dict], transitions: list[dict]) -> None:
    """Check the scope of a director conclusion, never infer it from prose."""
    inherited = clip.get("inherited_start_composition")
    if (
        not isinstance(inherited, dict)
        or set(inherited) != {"state_id", "transition_to_state_id", "premise_preserved"}
        or not isinstance(inherited.get("state_id"), str)
        or not isinstance(inherited.get("transition_to_state_id"), str)
        or inherited.get("premise_preserved") is not True
        or not isinstance(clip.get("reason"), str) or not clip["reason"].strip()
    ):
        raise ValueError("INHERITED_COMPOSITION_INVALID: affirmative canonical premise and reason required")
    by_id = {item["visual_state_id"]: item for item in candidates}
    state = by_id.get(inherited["state_id"])
    target = by_id.get(inherited["transition_to_state_id"])
    start = clip_time_seconds(clip["start_time"])
    predecessors = sorted(
        (clip_time_seconds(item["time_seconds"]), item["keyframe_index"])
        for item in candidates
        if clip_time_seconds(item["time_seconds"]) <= start + CLIP_OWNERSHIP_TOLERANCE
    )
    if (
        clip.get("continuity_to_previous") != "CONTINUOUS"
        or int(clip.get("previous_clip_index") or 0) != int(clip["clip_index"]) - 1
        or clip.get("early_composition_state_id") is not None
        or not state or not target or not predecessors
        or state["keyframe_index"] != predecessors[-1][1]
        or state["keyframe_index"] != clip.get("carry_in_state_index")
        or state["keyframe_index"] in (clip.get("visual_state_indexes") or [])
        or not clip_time_seconds(state["time_seconds"]) < start < clip_time_seconds(target["time_seconds"])
        or not str(state.get("description") or "").strip()
        or any(clip_time_seconds(state["time_seconds"]) < clip_time_seconds(item["time_seconds"]) < clip_time_seconds(target["time_seconds"])
               for item in candidates)
    ):
        raise ValueError("INHERITED_COMPOSITION_INVALID: expected current carry-in and adjacent boundary transition")
    matching = [item for item in transitions
                if item.get("from_keyframe_index") == state["keyframe_index"]
                and item.get("to_keyframe_index") == target["keyframe_index"]]
    if len(matching) != 1 or not str(matching[0].get("transition_description") or "").strip():
        raise ValueError("INHERITED_COMPOSITION_INVALID: canonical transition evidence missing")
    transition = matching[0]
    if (
        clip_time_seconds(transition.get("start_time")) != clip_time_seconds(state["time_seconds"])
        or clip_time_seconds(transition.get("end_time")) != clip_time_seconds(target["time_seconds"])
    ):
        raise ValueError("INHERITED_COMPOSITION_INVALID: transition time scope mismatch")


def _project_early_composition_states(
    clips: list[dict], candidates: list[dict], speech_intervals: list[dict],
    transition_context: list[dict] | None = None,
) -> None:
    """Validate in-Clip coverage or a scoped inherited-start director conclusion."""
    by_id = {item["visual_state_id"]: item for item in candidates}
    for clip in clips:
        continuous = clip.get("continuity_to_previous") == "CONTINUOUS"
        if "early_composition_state_id" not in clip:
            raise ValueError("COMPOSITION_SELECTION_INVALID: early_composition_state_id is required")
        selected = clip["early_composition_state_id"]
        inherited = clip.get("inherited_start_composition")
        if inherited is not None:
            _validate_inherited_start_composition(clip, candidates, transition_context or [])
        if selected is not None and (not isinstance(selected, str) or not selected):
            raise ValueError("COMPOSITION_SELECTION_INVALID: expected one state ID or null")
        if not continuous:
            if selected is not None:
                raise ValueError("COMPOSITION_SELECTION_INVALID: NONE/CUT cannot select composition")
            continue
        start, end = clip_time_seconds(clip["start_time"]), clip_time_seconds(clip["end_time"])
        first_speech = min((max(start, clip_time_seconds(event["start_time"])) for event in speech_intervals
                            if clip_time_seconds(event["end_time"]) > start and clip_time_seconds(event["start_time"]) < end), default=None)

        def is_early(state_id):
            state = by_id.get(state_id)
            if not state or state.get("keyframe_index") not in (clip.get("visual_state_indexes") or []):
                return False
            time = clip_time_seconds(state["time_seconds"])
            return start + CLIP_OWNERSHIP_TOLERANCE < time < end and (first_speech is None or time < first_speech)

        if selected is not None and not is_early(selected):
            raise ValueError(f"COMPOSITION_SELECTION_INVALID: {selected} is not an early owned interior state before speech")
        if inherited is None and selected is None and not any(is_early(sid) for sid in clip.get("selected_temporal_target_ids") or []):
            raise ValueError(f"EARLY_COMPOSITION_COVERAGE_INVALID: Clip {clip['clip_index']} has no early execution anchor")
        merged = execution_temporal_state_ids(clip)
        if len(merged) > int(VIDEO_CAPABILITY_CONTRACTS["TEMPORAL_EXTEND"]["max_temporal_anchors"]):
            raise ValueError("TEMPORAL_ANCHOR_LIMIT: timed and composition anchors exceed 8")
        clip["requires_temporal_control"] = bool(merged)
        clip["capability"] = "TEMPORAL_EXTEND" if merged else "EXTEND"


def _build_temporal_anchors(clips: list[dict], candidates: list[dict]) -> list[dict]:
    """Build Clip-local anchors from deterministically projected target IDs."""
    by_id = {str(item.get("visual_state_id")): item for item in candidates if isinstance(item, dict)}
    anchors = []
    for clip in clips:
        selected = sorted(execution_temporal_state_ids(clip), key=lambda sid: float(by_id[sid]["time_seconds"]))
        intent = clip.get("requires_temporal_control") is True
        if not intent:
            clip["temporal_anchor_ids"] = []
            continue
        if str(clip.get("continuity_to_previous") or "").upper() != "CONTINUOUS":
            raise ValueError(f"Clip {clip.get('clip_index')} requests temporal control without CONTINUOUS continuity")
        start = float(clip.get("start_time"))
        end = float(clip.get("end_time"))
        seen_times = set()
        anchor_ids = []
        for visual_state_id in selected:
            state_id = str(visual_state_id)
            state = by_id.get(state_id)
            if not state:
                raise ValueError(f"Clip {clip.get('clip_index')} selected unknown temporal target {state_id}")
            try:
                shot_time = float(state.get("time_seconds"))
            except (TypeError, ValueError):
                raise ValueError(f"Temporal target {state_id} has invalid time")
            if clip_time_seconds(shot_time) <= clip_time_seconds(start) + CLIP_OWNERSHIP_TOLERANCE or clip_time_seconds(shot_time) > clip_time_seconds(end) + CLIP_OWNERSHIP_TOLERANCE:
                raise ValueError(f"Temporal target {state_id} is outside Clip {clip.get('clip_index')}")
            local_time = round(shot_time - start, 2)
            if local_time in seen_times:
                raise ValueError(f"Clip {clip.get('clip_index')} has duplicate temporal target time")
            seen_times.add(local_time)
            anchor_id = f"clip-{int(clip.get('clip_index'))}-{state_id}"
            anchor_ids.append(anchor_id)
            anchors.append({
                "anchor_id": anchor_id,
                "time_seconds": local_time,
                "image_url": state.get("image_url"),
                "source": state.get("source") or {"type": "KEYFRAME", "id": state_id},
                "description": state.get("description") or "",
            })
        clip["temporal_anchor_ids"] = anchor_ids
        clip["capability"] = "TEMPORAL_EXTEND"
    return anchors


def _normalize_continuity_contract(
    clips: list[dict],
    shot_continuity_mode: str | None = None,
    *,
    project_capability: bool = True,
) -> None:
    """Normalize new planner semantics without rewriting historical persisted plans."""
    for position, clip in enumerate(clips, 1):
        if not isinstance(clip, dict):
            continue
        try:
            clip_index = int(clip.get("clip_index") or position)
        except (TypeError, ValueError):
            clip_index = position
        raw_continuity = clip.get("continuity_to_previous")
        if raw_continuity in (None, ""):
            raise ValueError(f"Clip {clip_index} 缺少 continuity_to_previous")
        continuity = str(raw_continuity).upper()
        if continuity not in {"NONE", "CUT", "CONTINUOUS"}:
            raise ValueError(f"Clip {clip_index} continuity_to_previous 无效")
        # #10A owns continuity and selection. Program derives execution only.
        if clip_index == 1:
            if continuity != "NONE":
                raise ValueError("First Clip continuity_to_previous 必须为 NONE")
            if project_capability:
                clip["capability"] = "GENERATE"
        elif continuity == "NONE":
            raise ValueError(f"Later Clip {clip_index} continuity_to_previous 不能为 NONE")
        elif continuity == "CUT":
            if project_capability:
                clip["capability"] = "GENERATE"
        elif continuity == "CONTINUOUS":
            if project_capability:
                clip["capability"] = "EXTEND"
        clip["continuity_to_previous"] = continuity
        if not project_capability:
            clip.pop("capability", None)
        clip["requires_temporal_control"] = False


def _canonical_continuity_structure(clips: list[dict], candidates: list[dict]) -> list[dict]:
    """Project raw and normalized boundaries using the same ownership rule."""
    projected = deepcopy(clips)
    _project_clip_visual_states(projected, candidates)
    structure = []
    for position, clip in enumerate(projected):
        owned = clip.get("visual_state_indexes") or []
        previous_owned = (projected[position - 1].get("visual_state_indexes") or []) if position else []
        structure.append({
            "clip_index": clip["clip_index"],
            "start_time": float(clip["start_time"]),
            "end_time": float(clip["end_time"]),
            "continuity_to_previous": clip.get("continuity_to_previous"),
            "visual_state_indexes": owned,
            "carry_in_state_index": clip.get("carry_in_state_index"),
            "inherited_start_composition": clip.get("inherited_start_composition"),
            "previous_ending_state_index": previous_owned[-1] if previous_owned else None,
            "first_owned_state_index": owned[0] if owned else None,
            "eligible_temporal_targets": [
                {"visual_state_id": item["visual_state_id"],
                 "keyframe_index": item["keyframe_index"],
                 "time_seconds": item["time_seconds"],
                 "clip_local_time": round(float(item["time_seconds"]) - float(clip["start_time"]), 2),
                 "description": item.get("description") or ""}
                for item in candidates
                if item.get("timed_visual_target") is True and item["keyframe_index"] in owned
            ],
            "composition_candidates": [
                {"visual_state_id": item["visual_state_id"], "time_seconds": item["time_seconds"],
                 "clip_local_time": round(float(item["time_seconds"]) - float(clip["start_time"]), 2),
                 "description": item.get("description") or ""}
                for item in candidates if item["keyframe_index"] in owned
            ],
        })
    return structure


def _continuity_premise_changed(raw: list[dict], normalized: list[dict], candidates: list[dict]) -> bool:
    """Compare structural facts, never the model's reason or continuity label."""
    if [item["clip_index"] for item in raw] != [item["clip_index"] for item in normalized]:
        return True
    timed_indexes = {int(item["keyframe_index"]) for item in candidates if item.get("timed_visual_target") is True}
    for before, after in zip(raw[1:], normalized[1:]):
        # An inherited conclusion describes this exact transition phase, even
        # when a moved boundary retains the same state identities.
        if before.get("inherited_start_composition") is not None and clip_time_seconds(before["start_time"]) != clip_time_seconds(after["start_time"]):
            return True
        for key in (
            "visual_state_indexes", "previous_ending_state_index",
            "first_owned_state_index", "carry_in_state_index",
        ):
            if before[key] != after[key]:
                return True
        # Same identities usually make a numerical move harmless. An owned
        # composition candidate's local position also changes selection meaning.
        if timed_indexes.intersection(after["visual_state_indexes"]) or (
            before.get("continuity_to_previous") == "CONTINUOUS" and after["visual_state_indexes"]
        ):
            if abs(before["start_time"] - after["start_time"]) > 0.05:
                return True
    return False


def _retry_structure_matches(expected: list[dict], actual: list[dict], candidates: list[dict]) -> bool:
    """A repair call cannot become an unconstrained second boundary search."""
    return not _continuity_premise_changed(expected, actual, candidates) and all(
        abs(left[key] - right[key]) <= 0.05
        for left, right in zip(expected, actual)
        for key in ("start_time", "end_time")
    )


def merge_dialogue_ownership_validation(validation: dict, dialogue_validation: dict) -> None:
    """Dialogue ownership is a blocking part of the existing Clip validation."""
    validation["dialogue_ownership"] = dialogue_validation
    validation["passed"] = validation.get("passed") is True and dialogue_validation["passed"] is True
    if dialogue_validation["passed"]:
        return
    validation.pop("temporal_contract", None)
    validation.pop("composition_contract", None)
    for code in dialogue_validation["findings"] or ["DIALOGUE_OWNERSHIP_INVALID"]:
        if any(item["code"] == code for item in validation.setdefault("blocking", [])):
            continue
        finding = {"code": code, "severity": "BLOCKING", "message": "Canonical dialogue ownership validation failed."}
        validation["blocking"].append(finding)
        validation.setdefault("findings", []).append(finding)


async def plan_clips(db: Session, novel, shot, temporal_anchors: list[dict], planning_policy: dict | None = None) -> tuple[list[dict], dict]:
    template = PromptTemplateService(db).get_default_system_template("clip_execution_planner")
    if not template:
        raise RuntimeError("未配置 Clip Execution Planner 提示词模板")
    payload = build_clip_planner_input(shot, temporal_anchors, planning_policy)
    llm_payload = {
        key: value
        for key, value in payload.items()
        if key != "available_generation_inputs"
    }
    # Selection evaluates planned visual value, not whether an asset happens to
    # exist yet. Keep physical image metadata only for the program's projection.
    llm_payload["visual_state_candidates"] = [
        {key: value for key, value in state.items() if key not in {"image_available", "image_url", "source"}}
        for state in payload["visual_state_candidates"]
    ]
    video_plan = json.loads(shot.video_director_plan or "{}")
    shot_dialogues = json.loads(shot.dialogues or "[]")
    dialogue_timeline_source = video_plan.get("dialogue_timeline_source")
    generated_timeline, _, timeline_status = build_dialogue_timeline(
        {"start_time": 0, "end_time": shot.duration or 4},
        shot_dialogues,
        json.loads(getattr(shot, "characters", "[]") or "[]"),
    )
    if timeline_status.get("status") == "ok" and generated_timeline:
        dialogue_timeline_source = generated_timeline
    elif not isinstance(dialogue_timeline_source, list):
        dialogue_timeline_source = []
    if shot_dialogues and not dialogue_timeline_source:
        raise RuntimeError("DIALOGUE_TIMELINE_UNAVAILABLE: 有对白的 Shot 缺少合法 official dialogue timeline，不能静默降级生成视频。")
    max_clip_duration = float(VIDEO_CAPABILITY_CONTRACTS["GENERATE"]["max_duration"])
    min_clip_duration = float(VIDEO_CAPABILITY_CONTRACTS["GENERATE"]["min_duration"])
    candidates = payload.get("visual_state_candidates") or []
    canonical = payload.get("canonical_visual_plan") is True
    retry_structure = None
    for attempt in range(2):
        result = await LLMService().chat_completion(
            system_prompt=template.template,
            user_content=json.dumps(llm_payload, ensure_ascii=False, indent=2),
            temperature=0.2,
            max_tokens=2200,
            response_format="json_object",
            task_type="clip_execution_planner",
            prompt_template_name=template.name,
            novel_id=novel.id,
            chapter_id=shot.chapter_id,
        )
        if not result.get("success"):
            raise RuntimeError(result.get("error") or "Clip Planner 调用失败")
        parsed = json.loads(result.get("content") or "{}")
        clips = parsed.get("clips") if isinstance(parsed.get("clips"), list) else []
        for index, clip in enumerate(clips, 1):
            clip["clip_index"] = int(clip.get("clip_index") or index)
            clip["planned_duration"] = round(float(clip.get("end_time", 0)) - float(clip.get("start_time", 0)), 2)
            clip.setdefault("execution_status", "PLANNED")
            clip.setdefault("approval_mode", (planning_policy or {}).get("approval_mode", "AUTO_APPROVE"))
        _normalize_continuity_contract(clips, shot.continuity_mode, project_capability=not canonical)
        for index, clip in enumerate(clips, 1):
            clip.setdefault("previous_clip_index", None)
            if clip.get("continuity_to_previous") == "CONTINUOUS" and index > 1:
                expected_previous = int(clips[index - 2].get("clip_index") or index - 1)
                if not clip.get("previous_clip_index"):
                    clip["previous_clip_index"] = expected_previous
                if int(clip["previous_clip_index"]) != expected_previous:
                    raise ValueError(f"Clip {clip.get('clip_index')} previous_clip_index 与 CONTINUOUS continuity 不一致")
        raw_structure = _canonical_continuity_structure(clips, candidates) if canonical else []
        clips = align_clip_boundaries_to_dialogue_gaps(
            clips, dialogue_timeline_source, max_clip_duration, min_clip_duration
        )
        _normalize_provider_boundaries(
            clips, shot.duration or 4, min_clip_duration, max_clip_duration, dialogue_timeline_source
        )
        _project_clip_visual_states(clips, candidates)
        normalized_structure = _canonical_continuity_structure(clips, candidates) if canonical else []
        changed = canonical and _continuity_premise_changed(raw_structure, normalized_structure, candidates)
        if retry_structure is not None:
            if (
                changed
                or not _retry_structure_matches(retry_structure, raw_structure, candidates)
                or not _retry_structure_matches(retry_structure, normalized_structure, candidates)
            ):
                raise ValueError("CLIP_CONTINUITY_PREMISE_INVALIDATED")
            if any(not str(clip.get("reason") or "").strip() for clip in clips[1:]):
                raise ValueError("CLIP_CONTINUITY_PREMISE_INVALIDATED: retry reason missing")
        if not changed:
            break
        retry_structure = normalized_structure
        llm_payload = {
            **llm_payload,
            "continuity_revalidation": {
                "normalized_clips": retry_structure,
                "instruction": (
                    "Deterministic canonical normalization changed the previous candidate's continuity premise. "
                    "Return a fresh whole Clip Plan using exactly these normalized Clip boundaries and projected "
                    "ownership/carry-in constraints; do not search for new boundaries. Re-evaluate each later Clip's "
                    "CUT/CONTINUOUS and reason against its previous_ending_state_index and first_owned_state_index. "
                    "CONTINUOUS requires actual Previous Clip ending visual dependency; CUT means independent "
                    "first-owned visual grounding. Carry-in is semantic context only. Do not infer continuity from "
                    "scene/characters/story/dialogue continuation or ordinary visual progression."
                    " Classify continuity from canonical visual/action/camera facts before considering composition "
                    "or timed coverage. Missing early coverage must not justify changing CONTINUOUS to CUT; "
                    "retain the semantic classification and explain the coverage conflict in reason."
                    " Re-evaluate selected_temporal_target_ids against ALL eligible_temporal_targets (including "
                    "previously unselected ones) and their normalized local times. Selection is optional, owned-only, "
                    "and based on planned context, never actual Previous AV tail pixels."
                    " Re-evaluate early_composition_state_id against ALL owned composition_candidates, including "
                    "false states, their local times and first overlapping speech interval. Require early coverage."
                    " Re-evaluate inherited_start_composition separately at the fixed normalized boundary: "
                    "use only the current carry-in and adjacent canonical transition if its established opening "
                    "premise is preserved; explain concrete evidence in reason. Otherwise use null. "
                    "Inheritance must not populate in-Clip composition/timed selections or invent an image anchor."
                ),
            },
        }
    for clip in clips:
        clip["planned_duration"] = round(
            float(clip.get("end_time", 0)) - float(clip.get("start_time", 0)),
            2,
        )
        clip["dialogue_scope"] = {
            "start_time": float(clip.get("start_time", 0)),
            "end_time": float(clip.get("end_time", 0)),
        }
    _project_temporal_targets(
        clips,
        payload.get("visual_state_candidates") or [],
        float(shot.duration or 4),
    )
    if canonical:
        _project_early_composition_states(clips, candidates, payload["speech_timing_intervals"], payload["transition_context"])
    derived_temporal_anchors = _build_temporal_anchors(
        clips, payload.get("visual_state_candidates") or []
    )
    temporal_anchors.clear()
    temporal_anchors.extend(derived_temporal_anchors)
    payload["available_generation_inputs"]["temporal_anchor_images"] = [
        item["anchor_id"] for item in derived_temporal_anchors
    ]
    assignments, dialogue_validation = assign_dialogues_to_clips(
        shot_dialogues, clips, dialogue_timeline_source
    )
    assignments_by_index = {item["clip_index"]: item["dialogues"] for item in assignments}
    for clip in clips:
        clip["dialogue_assignment"] = assignments_by_index.get(clip["clip_index"], [])
    validation = validate_clip_plan(
        shot.duration or 4,
        clips,
        temporal_anchors,
        # Missing physical images affect execution readiness, not plan validity.
        available_inputs=None if canonical else payload["available_generation_inputs"],
        visual_state_candidates=payload.get("visual_state_candidates") or [],
    )
    merge_dialogue_ownership_validation(validation, dialogue_validation)
    if canonical and validation["passed"]:
        validation["temporal_contract"] = TEMPORAL_DECISION_CONTRACT
        validation["composition_contract"] = EARLY_COMPOSITION_CONTRACT
    return clips, validation
