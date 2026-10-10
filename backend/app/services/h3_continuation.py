"""Timing of the existing H3 masked-context workflow; no graph or prompt rewriting.

Only a real continuation capability plus the native source binding enables this
contract. Ordinary generation has no overlap or shifted time origin.
"""
import json
from pathlib import Path

from app.services.continuous_clip_av import probe_clip_av
from app.utils.path_utils import url_to_local_path


CAPABILITIES = {"EXTEND", "VIDEO_CONTINUATION", "TEMPORAL_EXTEND"}
FRAME_EXPRESSION = "max(5, round(a * 24)) + (5 - (max(5, round(a * 24)) % 17)) % 17"


def target_frames(duration):
    """Evaluate the verified ComfyMathExpression, including its rounding rule."""
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
    graph = json.loads(workflow.workflow_json)
    mapping = json.loads(workflow.node_mapping)

    def unique(kind):
        found = [(k, n.get("inputs", {})) for k, n in graph.items() if n.get("class_type") == kind]
        if len(found) != 1:
            raise ValueError("PREVIOUS_AV_BINDING_UNVERIFIED: " + kind)
        return found[0]

    def literal(link, kind, key):
        if not isinstance(link, list) or len(link) != 2 or link[1] != 0:
            raise ValueError("PREVIOUS_AV_BINDING_UNVERIFIED: expected literal parameter link")
        node = graph.get(str(link[0]), {})
        if node.get("class_type") != kind:
            raise ValueError("PREVIOUS_AV_BINDING_UNVERIFIED: " + kind)
        return node["inputs"][key]

    masked_id, masked = unique("MiniMaxH3StartMaskedContext")
    _, native = unique("MiniMaxH3StreamLiveExtensionAVToVHS")
    _, sampler = unique("SamplerCustomAdvanced")
    _, crop = unique("MiniMaxH3CropTo32")
    validate_id, validate = unique("MiniMaxH3Validate24FPSVideo")
    load_id = str(mapping["load_video_node_id"])
    load = graph[load_id]
    _, audio = unique("MiniMaxH3SourceAudioPolicy")
    reference_id = str(mapping["reference_to_video_node_id"])
    _, math = unique("ComfyMathExpression")
    frames = literal(masked["context_length"], "PrimitiveInt", "value")
    feather = literal(masked["audio_feather_ticks"], "PrimitiveInt", "value")
    fps = masked["source_fps"]
    # Recognize the existing physical path. Do not guess unverified alternatives.
    valid = (
        literal(masked["start_mode"], "MiniMaxH3AVStartModeParam", "start") == "Existing Video"
        and literal(audio["mode"], "MiniMaxH3AVSourceAudioModeParam", "source_audio") == "Keep source audio"
        and sampler["latent_image"] == [masked_id, 0]
        and masked["latent"] == [reference_id, 1]
        and graph[reference_id]["class_type"] == "MiniMaxH3ReferenceToVideo"
        and masked["source_frames"] == native["source_frames"] == audio["source_frames"]
        and graph[masked["source_frames"][0]]["class_type"] == "MiniMaxH3CropTo32"
        and crop["images"] == [validate_id, 0]
        and validate["images"] == [load_id, 0] and validate["video_info"] == [load_id, 3]
        and load["class_type"] == "VHS_LoadVideoFFmpeg"
        and load["inputs"]["force_rate"] == fps == native["source_fps"] == audio["source_fps"] == 24
        and load["inputs"]["frame_load_cap"] == 0 and load["inputs"]["start_time"] == 0
        and masked["source_audio"] == native["source_audio"]
        and graph[masked["source_audio"][0]]["class_type"] == "MiniMaxH3SourceAudioPolicy"
        and native["context_frames"] == native["video_overlap_frames"] == frames
        and math["expression"] == FRAME_EXPRESSION
        and math["values.a"] == [str(mapping["duration_seconds_node_id"]), 0]
        and isinstance(frames, int) and frames >= 39 and (frames - 39) % 51 == 0
    )
    if not valid:
        raise ValueError("PREVIOUS_AV_BINDING_UNVERIFIED: native masked-context path changed")
    source = context.get("previous_clip") or {}
    physical = source.get("physical_output") or {}
    path = Path(url_to_local_path(str(previous_path)) or str(previous_path)).resolve()
    source_path = url_to_local_path(source.get("result_url") or "")
    if not source_path or path != Path(source_path).resolve() or not source.get("generated_by_task_id"):
        raise ValueError("PREVIOUS_AV_SOURCE_MISMATCH")
    actual = probe_clip_av(str(path))
    if (not actual["has_audio"] or actual["frame_count"] < frames
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
