"""Deterministic validation for semantic Clip Planner output."""
from typing import Any

from app.constants.capability import VIDEO_CAPABILITY_CONTRACTS


def validate_clip_plan(
    shot_duration: float,
    clips: list[dict],
    anchors: list[dict],
    capabilities: dict | None = None,
    available_inputs: dict | None = None,
) -> dict:
    findings: list[dict] = []
    blocking: list[dict] = []
    capabilities = capabilities or VIDEO_CAPABILITY_CONTRACTS
    validate_required_inputs = available_inputs is not None
    available_inputs = available_inputs or {}
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
            contract = capabilities.get(capability)
            if not contract or not contract.get("enabled"):
                add("CAPABILITY_UNAVAILABLE", "BLOCKING", f"Capability {capability or '<missing>'} is unavailable.")
            elif planned < contract["min_duration"] or planned > contract["max_duration"]:
                add("PROVIDER_DURATION_LIMIT", "BLOCKING", f"Clip {clip.get('clip_index')} is outside the 4-15 second H3 contract.")
            elif validate_required_inputs:
                if capability == "SINGLE_FRAME" and not available_inputs.get("shot_image"):
                    add("SHOT_IMAGE_REQUIRED", "BLOCKING", f"Clip {clip.get('clip_index')} requires a valid Shot Image.")
                if capability == "FIRST_LAST_FRAME":
                    if not available_inputs.get("shot_image"):
                        add("SHOT_IMAGE_REQUIRED", "BLOCKING", f"Clip {clip.get('clip_index')} requires a valid Shot Image.")
                    if not available_inputs.get("end_keyframe_image"):
                        add("END_KEYFRAME_IMAGE_REQUIRED", "BLOCKING", f"Clip {clip.get('clip_index')} requires a valid end-keyframe image.")
            if capability == "MULTI_KEYFRAME":
                indexes = clip.get("keyframe_indexes") or clip.get("keyframe_indices") or []
                contract = capabilities.get(capability) or {}
                minimum = int(contract.get("min_keyframes") or 0)
                maximum = int(contract.get("max_keyframes") or 0)
                if len(indexes) < minimum or (maximum and len(indexes) > maximum):
                    add("KEYFRAME_INPUTS_REQUIRED", "BLOCKING", f"Clip {clip.get('clip_index')} requires {minimum}-{maximum} keyframe indexes.")
                if validate_required_inputs:
                    image_indexes = {item.get("index") for item in available_inputs.get("keyframe_images", [])}
                    if any(index not in image_indexes for index in indexes):
                        add("KEYFRAME_IMAGE_MISSING", "BLOCKING", f"Clip {clip.get('clip_index')} references keyframes without available images.")
            if capability == "TEMPORAL_EXTEND":
                anchor_ids = set(clip.get("temporal_anchor_ids") or [])
                image_anchor_ids = set(available_inputs.get("temporal_anchor_images") or []) if available_inputs else set()
                if len(anchor_ids) < int((contract or {}).get("min_temporal_anchors") or 0):
                    add("TEMPORAL_ANCHORS_REQUIRED", "BLOCKING", f"Clip {clip.get('clip_index')} requires temporal anchors.")
                if validate_required_inputs and not anchor_ids.issubset(image_anchor_ids):
                    add("TEMPORAL_ANCHOR_IMAGE_MISSING", "BLOCKING", f"Clip {clip.get('clip_index')} references unavailable temporal-anchor images.")
            if previous_end is not None and abs(start - previous_end) > 0.05:
                add("SHOT_COVERAGE_GAP", "BLOCKING", f"Clip {clip.get('clip_index')} is not contiguous with the previous clip.")
            if previous_end is not None and start < previous_end - 0.05:
                add("SHOT_COVERAGE_OVERLAP", "BLOCKING", f"Clip {clip.get('clip_index')} overlaps the previous clip.")
            anchor_ids = set(clip.get("temporal_anchor_ids") or [])
            for anchor in anchors or []:
                if anchor.get("anchor_id") in anchor_ids:
                    time = float(anchor.get("time_seconds", 0))
                    if time < start - 0.05 or time > end + 0.05:
                        add("ANCHOR_OUTSIDE_CLIP", "BLOCKING", f"Anchor {anchor.get('anchor_id')} is outside its clip.")
            if capability in {"VIDEO_CONTINUATION", "TEMPORAL_EXTEND"} and not clip.get("previous_clip_index"):
                add("PREVIOUS_CLIP_MISSING", "BLOCKING", f"Continuation Clip {clip.get('clip_index')} has no previous dependency.")
            if planned != round(planned, 1):
                add("NATURAL_DURATION_ROUNDING", "WARNING", f"Clip {clip.get('clip_index')} has a non-rounded planned duration.")
            previous_end = end

    return {"passed": not blocking, "findings": findings, "blocking": blocking, "review_required": [], "warnings": [item for item in findings if item["severity"] == "WARNING"]}
