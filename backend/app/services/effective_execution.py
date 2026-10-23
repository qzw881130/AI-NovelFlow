"""Read-only execution policy projection. Canonical plans are never rewritten."""
from copy import deepcopy
from typing import Literal

ContinuationMode = Literal["AUTO", "EXTEND_ONLY"]


def continuation_mode(metadata=None):
    mode = (metadata or {}).get("continuation_mode", "AUTO")
    if mode not in ("AUTO", "EXTEND_ONLY"):
        raise ValueError("CONTINUATION_MODE_INVALID")
    return mode


def project_effective_execution(plan, clip, mode="AUTO"):
    """Resolve one physical view from the original semantic Clip and policy."""
    mode = continuation_mode({"continuation_mode": mode})
    planned = clip.get("capability")
    anchor_ids = list(clip.get("temporal_anchor_ids") or [])
    by_id = {a.get("anchor_id"): a for a in plan.get("temporal_anchors") or [] if isinstance(a, dict)}
    anchors = [deepcopy(by_id[a]) for a in anchor_ids if a in by_id]
    suppressed, state_indexes, image_urls = [], [], []
    effective = planned
    if mode == "EXTEND_ONLY":
        continuity = clip.get("continuity_to_previous")
        if planned not in {"GENERATE", "EXTEND", "TEMPORAL_EXTEND"}:
            raise ValueError("CONTINUATION_POLICY_REQUIRES_SEMANTIC_CLIP")
        if continuity in {"NONE", "CUT"}:
            if planned != "GENERATE":
                raise ValueError("CONTINUATION_PLAN_MODE_MISMATCH")
        elif continuity != "CONTINUOUS" or planned == "GENERATE":
            raise ValueError("CONTINUATION_PLAN_MODE_MISMATCH")
        if planned == "TEMPORAL_EXTEND":
            # Verify the original selection; suppression is not a way to accept
            # missing/foreign state identities or a broken planning contract.
            selected = list(dict.fromkeys([
                *(clip.get("selected_temporal_target_ids") or []),
                *([clip["early_composition_state_id"]] if clip.get("early_composition_state_id") else []),
            ]))
            states = {f"KF{s['index']}": s for s in plan.get("keyframes") or []}
            expected_ids = {f"clip-{clip['clip_index']}-{s}" for s in selected}
            if (not selected or not clip.get("requires_temporal_control")
                    or len(anchor_ids) != len(set(anchor_ids)) or set(anchor_ids) != expected_ids
                    or len(anchors) != len(anchor_ids)):
                raise ValueError("CONTINUATION_TEMPORAL_SELECTION_MISMATCH")
            for sid in selected:
                state = states.get(sid)
                if not state or state["index"] not in (clip.get("visual_state_indexes") or []):
                    raise ValueError("CONTINUATION_TEMPORAL_STATE_MISMATCH")
                anchor = by_id[f"clip-{clip['clip_index']}-{sid}"]
                source = anchor.get("source") or anchor.get("provenance") or {}
                if source.get("id", sid) != sid or source.get("keyframe_index", state["index"]) != state["index"]:
                    raise ValueError("CONTINUATION_TEMPORAL_STATE_MISMATCH")
                state_indexes.append(state["index"])
                image_urls.extend(u for u in (state.get("image_url"), state.get("imageUrl"),
                                               anchor.get("image_url")) if u)
            suppressed, effective = anchor_ids, "EXTEND"
    record = {
        "continuation_mode": mode, "planned_capability": planned,
        "effective_capability": effective,
        "effective_temporal_anchors": [] if suppressed else anchors,
        "suppressed_temporal_anchor_ids": suppressed,
        "suppressed_state_indexes": state_indexes,
        "suppressed_image_urls": sorted(set(image_urls)),
        "planned_clip": {k: deepcopy(clip.get(k)) for k in (
            "clip_index", "start_time", "end_time", "visual_state_indexes", "carry_in_state_index",
            "continuity_to_previous", "previous_clip_index", "requires_temporal_control",
            "selected_temporal_target_ids", "early_composition_state_id", "inherited_start_composition",
            "temporal_anchor_ids")},
    }
    view = deepcopy(clip)
    if suppressed:
        view.update(capability=effective, requires_temporal_control=False, temporal_anchor_ids=[])
    if mode != "AUTO":
        # Physical projection and cache identity; semantic states stay intact.
        view["execution_projection"] = deepcopy(record)
    return {**record, "effective_clip": view}


def projection_record(projection):
    return {k: deepcopy(v) for k, v in projection.items() if k != "effective_clip"}


def task_execution_projection(plan, clip, metadata):
    """Recover the frozen policy; a missing historical field means AUTO only."""
    result = project_effective_execution(plan, clip, continuation_mode(metadata))
    saved = metadata.get("execution_projection")
    if saved is not None and saved != projection_record(result):
        raise ValueError("EXECUTION_PROJECTION_CHANGED")
    if saved is None and result["continuation_mode"] != "AUTO":
        raise ValueError("EXECUTION_PROJECTION_MISSING")
    if saved is not None and metadata.get("capability", result["effective_capability"]) != result["effective_capability"]:
        raise ValueError("EXECUTION_PROJECTION_MODE_MISMATCH")
    return result
