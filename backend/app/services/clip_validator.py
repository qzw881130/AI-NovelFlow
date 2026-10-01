"""Deterministic validation for semantic Clip Planner output."""
from typing import Any

from app.constants.capability import VIDEO_CAPABILITY_CONTRACTS


def validate_clip_plan(
    shot_duration: float,
    clips: list[dict],
    anchors: list[dict],
    capabilities: dict | None = None,
    available_inputs: dict | None = None,
    visual_state_candidates: list[dict] | None = None,
) -> dict:
    findings: list[dict] = []
    blocking: list[dict] = []
    capabilities = capabilities or VIDEO_CAPABILITY_CONTRACTS
    validate_required_inputs = available_inputs is not None
    available_inputs = available_inputs or {}
    visual_state_candidates = visual_state_candidates or []
    state_by_index = {
        int(item.get("keyframe_index")): item
        for item in visual_state_candidates
        if isinstance(item, dict) and item.get("keyframe_index") is not None
    }
    ordered = sorted(clips or [], key=lambda item: float(item.get("start_time", 0)))

    def add(code: str, severity: str, message: str) -> None:
        finding = {"code": code, "severity": severity, "message": message}
        findings.append(finding)
        if severity == "BLOCKING":
            blocking.append(finding)

    if not ordered:
        add("CLIP_PLAN_EMPTY", "BLOCKING", "Clip plan must contain at least one clip.")
    else:
        if abs(float(ordered[0].get("start_time", -1))) > 0.05:
            add("SHOT_COVERAGE_START", "BLOCKING", "The first clip must start at 0.")
        if abs(float(ordered[-1].get("end_time", -1)) - float(shot_duration)) > 0.05:
            add("SHOT_COVERAGE_END", "BLOCKING", "The last clip must end at Shot duration.")
        previous_end = None
        for clip in ordered:
            start = float(clip.get("start_time", 0))
            end = float(clip.get("end_time", 0))
            planned = float(clip.get("planned_duration", end - start))
            if end <= start or abs(planned - (end - start)) > 0.05:
                add("CLIP_DURATION_MISMATCH", "BLOCKING", f"Clip {clip.get('clip_index')} has invalid duration.")
            capability = str(clip.get("capability") or "")
            owned = clip.get("visual_state_indexes") or []
            if len(owned) != len(set(owned)):
                add("VISUAL_STATE_DUPLICATE", "BLOCKING", f"Clip {clip.get('clip_index')} contains duplicate owned visual states.")
            for raw_index in owned:
                try:
                    state_index = int(raw_index)
                except (TypeError, ValueError):
                    add("VISUAL_STATE_INVALID", "BLOCKING", f"Clip {clip.get('clip_index')} contains an invalid visual state index.")
                    continue
                state = state_by_index.get(state_index)
                if not state:
                    add("VISUAL_STATE_MISSING", "BLOCKING", f"Clip {clip.get('clip_index')} references missing visual state {state_index}.")
                    continue
                time_seconds = float(state.get("time_seconds"))
                is_start = state_index == 1 and str(state.get("role") or "").upper() == "START"
                if not (clip.get("clip_index") == 1 and is_start) and not (time_seconds > start + 0.05 and time_seconds <= end + 0.05):
                    add("VISUAL_STATE_OWNERSHIP_INVALID", "BLOCKING", f"Clip {clip.get('clip_index')} does not own visual state {state_index} at its time.")
            carry_in = clip.get("carry_in_state_index")
            if carry_in is not None:
                try:
                    carry_state = state_by_index[int(carry_in)]
                except (TypeError, ValueError, KeyError):
                    carry_state = None
                if not carry_state or float(carry_state.get("time_seconds")) > start + 0.05:
                    add("CARRY_IN_INVALID", "BLOCKING", f"Clip {clip.get('clip_index')} has an invalid carry-in visual state.")
            contract = capabilities.get(capability)
            if not contract or not contract.get("enabled"):
                add("CAPABILITY_UNAVAILABLE", "BLOCKING", f"Capability {capability or '<missing>'} is unavailable.")
            elif planned < contract["min_duration"] or planned > contract["max_duration"]:
                add("PROVIDER_DURATION_LIMIT", "BLOCKING", f"Clip {clip.get('clip_index')} is outside the 4-15 second H3 contract.")
            if capability == "TEMPORAL_EXTEND":
                anchor_ids = set(clip.get("temporal_anchor_ids") or [])
                image_anchor_ids = set(available_inputs.get("temporal_anchor_images") or []) if available_inputs else set()
                if str(clip.get("continuity_to_previous") or "").upper() != "CONTINUOUS":
                    add("TEMPORAL_EXTEND_CONTINUITY_REQUIRED", "BLOCKING", f"TEMPORAL_EXTEND Clip {clip.get('clip_index')} must be CONTINUOUS.")
                if clip.get("requires_temporal_control") is not True:
                    add("TEMPORAL_CONTROL_REQUIRED", "BLOCKING", f"TEMPORAL_EXTEND Clip {clip.get('clip_index')} requires explicit temporal control intent.")
                if not clip.get("previous_clip_index"):
                    add("PREVIOUS_CLIP_MISSING", "BLOCKING", f"TEMPORAL_EXTEND Clip {clip.get('clip_index')} has no previous dependency.")
                if len(anchor_ids) < int((contract or {}).get("min_temporal_anchors") or 0):
                    add("TEMPORAL_ANCHORS_REQUIRED", "BLOCKING", f"Clip {clip.get('clip_index')} requires temporal anchors.")
                if len(anchor_ids) > int((contract or {}).get("max_temporal_anchors") or 8):
                    add("TEMPORAL_ANCHOR_LIMIT", "BLOCKING", f"Clip {clip.get('clip_index')} exceeds 8 temporal anchors.")
                if validate_required_inputs and not anchor_ids.issubset(image_anchor_ids):
                    add("TEMPORAL_ANCHOR_IMAGE_MISSING", "BLOCKING", f"Clip {clip.get('clip_index')} references unavailable temporal-anchor images.")
            if capability == "EXTEND":
                if str(clip.get("continuity_to_previous") or "").upper() != "CONTINUOUS":
                    add("EXTEND_CONTINUITY_REQUIRED", "BLOCKING", f"EXTEND Clip {clip.get('clip_index')} must be CONTINUOUS.")
                if bool(clip.get("requires_temporal_control")):
                    add("TEMPORAL_EXTEND_DEFERRED", "BLOCKING", f"Clip {clip.get('clip_index')} requires deferred temporal control.")
                if not clip.get("previous_clip_index"):
                    add("PREVIOUS_CLIP_MISSING", "BLOCKING", f"EXTEND Clip {clip.get('clip_index')} has no previous dependency.")
            if previous_end is not None and abs(start - previous_end) > 0.05:
                add("SHOT_COVERAGE_GAP", "BLOCKING", f"Clip {clip.get('clip_index')} is not contiguous with the previous clip.")
            if previous_end is not None and start < previous_end - 0.05:
                add("SHOT_COVERAGE_OVERLAP", "BLOCKING", f"Clip {clip.get('clip_index')} overlaps the previous clip.")
            anchor_ids = set(clip.get("temporal_anchor_ids") or [])
            for anchor in anchors or []:
                if anchor.get("anchor_id") in anchor_ids:
                    time = float(anchor.get("time_seconds", 0))
                    # Semantic TEMPORAL_EXTEND anchors are persisted Clip-local;
                    # ordinary legacy anchor payloads remain Shot-global.
                    lower_bound = 0.0 if capability == "TEMPORAL_EXTEND" else start
                    upper_bound = planned if capability == "TEMPORAL_EXTEND" else end
                    if time < lower_bound - 0.05 or time > upper_bound + 0.05:
                        add("ANCHOR_OUTSIDE_CLIP", "BLOCKING", f"Anchor {anchor.get('anchor_id')} is outside its clip.")
            if capability in {"VIDEO_CONTINUATION", "TEMPORAL_EXTEND"} and not clip.get("previous_clip_index"):
                add("PREVIOUS_CLIP_MISSING", "BLOCKING", f"Continuation Clip {clip.get('clip_index')} has no previous dependency.")
            if planned != round(planned, 1):
                add("NATURAL_DURATION_ROUNDING", "WARNING", f"Clip {clip.get('clip_index')} has a non-rounded planned duration.")
            previous_end = end

    return {"passed": not blocking, "findings": findings, "blocking": blocking, "review_required": [], "warnings": [item for item in findings if item["severity"] == "WARNING"]}
