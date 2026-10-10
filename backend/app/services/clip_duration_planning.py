"""Read-only planning budgets and observations; no boundary or timeline edits."""
import json

from app.constants.capability import (
    CLIP_MAX_DURATION, CLIP_PREFERRED_MAX_DURATION, EXTEND_WORKFLOW_ID,
    TEMPORAL_EXTEND_WORKFLOW_ID, clip_duration_maximum,
)
from app.repositories.workflow_repository import WorkflowRepository


def workflow_planning_budget(workflow):
    """Inspect configured context, without claiming a future source is bound."""
    continuation = workflow.type in {"VIDEO_CONTINUATION", "TEMPORAL_EXTEND"}
    budget = {
        "workflow_id": workflow.id, "workflow_type": workflow.type,
        "mode": "VIDEO_CONTINUATION" if continuation else "STANDARD_GENERATION",
        "max_duration": clip_duration_maximum(json.loads(workflow.extension or "{}")),
        "overlap_duration": None if continuation else 0.0,
        "evidence": "WORKFLOW_CONFIGURATION_ONLY; worker must verify actual source binding",
    }
    # Only the existing physical VIDEO_CONTINUATION path establishes this budget.
    # Other continuation workflows must not inherit its 39-frame assumption.
    if workflow.type != "VIDEO_CONTINUATION":
        return budget
    try:
        graph = json.loads(workflow.workflow_json)
        masked, = [n["inputs"] for n in graph.values() if n.get("class_type") == "MiniMaxH3StartMaskedContext"]
        native, = [n["inputs"] for n in graph.values() if n.get("class_type") == "MiniMaxH3StreamLiveExtensionAVToVHS"]
        context_link = masked["context_length"]
        context = graph[str(context_link[0])]
        start_link = masked["start_mode"]
        start = graph[str(start_link[0])]
        frames, fps = context["inputs"]["value"], masked["source_fps"]
        if (context_link[1] == start_link[1] == 0 and context["class_type"] == "PrimitiveInt"
                and start["class_type"] == "MiniMaxH3AVStartModeParam"
                and start["inputs"]["start"] == "Existing Video"
                and frames == native["context_frames"] == native["video_overlap_frames"] == 39
                and fps == native["source_fps"] == 24
                and masked["source_frames"] == native["source_frames"]):
            budget.update(overlap_frames=frames, fps=fps, overlap_duration=frames / fps)
    except (ValueError, KeyError, TypeError, IndexError):
        pass  # Unknown is observable, never silently replaced with 39 frames.
    return budget


def load_planning_budgets(db):
    if db is None:
        return {}
    repo = WorkflowRepository(db)
    workflows = {
        "GENERATE": repo.get_active_by_type("multi_reference_video"),
        "EXTEND": repo.get_by_id(EXTEND_WORKFLOW_ID),
        "TEMPORAL_EXTEND": repo.get_by_id(TEMPORAL_EXTEND_WORKFLOW_ID),
    }
    for capability in ("SINGLE_FRAME", "FIRST_LAST_FRAME", "MULTI_KEYFRAME", "VIDEO_CONTINUATION"):
        workflows[capability] = repo.get_active_by_type(capability)
    expected_types = {"GENERATE": "multi_reference_video", "EXTEND": "VIDEO_CONTINUATION"}
    return {capability: workflow_planning_budget(workflow) for capability, workflow in workflows.items()
            if workflow and workflow.is_active
            and workflow.type == expected_types.get(capability, capability)}


def observe_duration_plan(clip, speech_intervals, budgets):
    """Persist only on newly planned Clips. Exceeding 15 never blocks a plan."""
    capability = clip.get("capability") or "GENERATE"
    budget = budgets.get(capability) or {}
    continuation = capability in {"EXTEND", "VIDEO_CONTINUATION", "TEMPORAL_EXTEND"}
    overlap = budget.get("overlap_duration") if continuation else 0.0
    start, end = float(clip["start_time"]), float(clip["end_time"])
    events = [e for e in speech_intervals if start <= e["start_time"] and e["end_time"] <= end]
    durations = [e["end_time"] - e["start_time"] for e in events]
    fixed = sum(durations)
    # Permitted simultaneous speech must not be mistaken for sequential cost.
    has_overlap = any(a["start_time"] < b["end_time"] and b["start_time"] < a["end_time"]
                      for i, a in enumerate(events) for b in events[i + 1:])
    minimum_speech = max(durations, default=0) if has_overlap else fixed
    lower_bound = round(minimum_speech + overlap, 6) if overlap is not None else None
    maximum = budget.get("max_duration", CLIP_MAX_DURATION)
    exceeds = end - start > CLIP_PREFERRED_MAX_DURATION or (
        lower_bound is not None and lower_bound > CLIP_PREFERRED_MAX_DURATION)
    infeasible = end - start > maximum or (lower_bound is not None and lower_bound > maximum)
    return {
        "preferred_max_duration": CLIP_PREFERRED_MAX_DURATION,
        "effective_max_duration": maximum,
        "planned_story_duration": round(end - start, 6),
        "fixed_dialogue_duration": round(fixed, 6),
        "overlap_duration": overlap, "minimum_execution_duration": lower_bound,
        "workflow_budget": budget, "exceeds_preferred": exceeds,
        "reason": str(clip.get("reason") or "").strip() if exceeds else None,
        "reason_missing": exceeds and not bool(str(clip.get("reason") or "").strip()),
        "status": "DURATION_INFEASIBLE" if infeasible else "ABOVE_PREFERRED" if exceeds else "WITHIN_PREFERRED",
        "scope": "PLANNING_ONLY; no execution-time shift or fixed camera surcharge",
    }
