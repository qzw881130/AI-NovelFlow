"""Physical AV timing for an explicitly configured continuation workflow.

The workflow's internal nodes and links belong to ComfyUI and may change. This
contract uses only the declared capability, input/output mapping and the saved
previous video; it does not infer a pipeline from the workflow graph.
"""
import json
from pathlib import Path

from app.services.continuous_clip_av import FPS, OVERLAP_FRAMES, probe_clip_av
from app.utils.path_utils import url_to_local_path


CAPABILITIES = {"EXTEND", "VIDEO_CONTINUATION", "TEMPORAL_EXTEND"}
FRAME_EXPRESSION = "max(5, round(a * 24)) + (5 - (max(5, round(a * 24)) % 17)) % 17"


def target_frames(duration):
    """Calculate the frame budget of the current H3 AV contract."""
    raw = max(5, round(float(duration) * 24))
    return raw + (5 - raw % 17) % 17


def continuation_contract(workflow, capability, previous_path, context):
    family = getattr(workflow, "type", None)
    declared = capability in CAPABILITIES or family in CAPABILITIES
    if not declared:
        if previous_path:
            raise ValueError("PREVIOUS_AV_MODE_MISMATCH: source supplied without continuation capability")
        return None
    if not previous_path or capability not in CAPABILITIES or family not in {"VIDEO_CONTINUATION", "TEMPORAL_EXTEND"}:
        raise ValueError("PREVIOUS_AV_BINDING_MISSING: continuation requires its actual workflow and source")
    graph = json.loads(workflow.workflow_json or "{}")
    mapping = json.loads(workflow.node_mapping or "{}")
    if not isinstance(graph, dict):
        raise ValueError("PREVIOUS_AV_BINDING_MISSING: invalid workflow")
    nodes = ({str(node.get("id")): node for node in graph["nodes"] if isinstance(node, dict)}
             if isinstance(graph.get("nodes"), list) else graph)
    if not isinstance(mapping, dict) or any(
        not mapping.get(key) or str(mapping[key]) not in nodes
        for key in ("load_video_node_id", "video_save_node_id")
    ):
        raise ValueError("PREVIOUS_AV_BINDING_MISSING: video input/output mapping is incomplete")
    frames, fps, feather = OVERLAP_FRAMES, FPS, 8
    source = context.get("previous_clip") or {}
    physical = source.get("physical_output") or {}
    path = Path(url_to_local_path(str(previous_path)) or str(previous_path)).resolve()
    source_path = url_to_local_path(source.get("result_url") or "")
    if not source_path or path != Path(source_path).resolve() or not source.get("generated_by_task_id"):
        raise ValueError("PREVIOUS_AV_SOURCE_MISMATCH")
    actual = probe_clip_av(str(path))
    if (not actual["has_audio"] or actual["frame_count"] < frames or actual["fps"] != fps
            or any(actual[k] != physical.get(k) for k in ("sha256", "frame_count", "fps", "timebase"))):
        raise ValueError("PREVIOUS_AV_SOURCE_MISMATCH")
    audio_ticks = frames / fps * 40
    feather = max(0, min(feather, audio_ticks))
    return {
        "mode": "VIDEO_CONTINUATION", "binding_verified": True,
        "workflow_id": getattr(workflow, "id", None), "source_sha256": actual["sha256"],
        "previous_frames": actual["frame_count"], "fps": fps,
        "context_frames": frames, "overlap_frames": frames,
        "overlap_seconds": frames / fps,
        "source_start_frame": actual["frame_count"] - frames,
        "source_end_frame_exclusive": actual["frame_count"],
        "clip_local_time_origin": "TARGET_AV_FRAME_0_INCLUDES_SHARED_CONTEXT",
        "masked_time_origin": "SAME_AS_CLIP_LOCAL_NO_ADDITIONAL_SHIFT",
        "cumulative_start_frame": actual["frame_count"] - frames,
        "earliest_new_dialogue": frames / fps,
        "audio_hard_preserve_until": (audio_ticks - feather) / 40,
        "audio_feather_until": frames / fps,
        "audio_feather_ticks": feather,
        "duration_semantics": "TOTAL_C2_INCLUDING_CONTEXT; no worker overlap addition",
        "frame_expression": FRAME_EXPRESSION,
        "assembly": "previous_frames + target_frames - context_frames",
        "video_overlap": "blend source tail with decoded preserved prefix",
        "audio_overlap": "decoded extension audio replaces source tail; feather is not new-speech budget",
    }


def check_continuation_timing(contract, events, duration):
    """The compiler has already established binding; check physical AV feasibility."""
    if not contract:
        return {}
    start = contract["earliest_new_dialogue"]
    valid_duration = isinstance(duration, (int, float)) and duration > start
    valid_events = all(isinstance(e.get("start_time"), (int, float))
                       and isinstance(e.get("end_time"), (int, float)) for e in events)
    return {
        "previous_av_binding_verified": contract.get("binding_verified") is True,
        "continuation_dialogue_after_context": valid_events and all(e["start_time"] >= start - 1e-6 for e in events),
        "continuation_new_speech_budget": valid_duration and valid_events
            and sum(e["end_time"] - e["start_time"] for e in events) <= duration - start + 1e-6,
        "continuation_physical_frame_budget": valid_duration and valid_events
            and target_frames(duration) > contract["context_frames"]
            and all(e["end_time"] <= target_frames(duration) / contract["fps"] + 1e-6 for e in events),
    }
