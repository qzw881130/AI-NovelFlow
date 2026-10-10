"""Physical AV provenance and overlap spans for H3 continuous Clips."""

import hashlib
import json
import subprocess
from fractions import Fraction
from pathlib import Path
from contextvars import ContextVar
from functools import wraps


CONTINUOUS_CAPABILITIES = {"EXTEND", "TEMPORAL_EXTEND"}
NATIVE_CONTINUITY_OUTPUT = "NATIVE_CONTINUITY_OUTPUT"
OVERLAP_FRAMES = 39
FPS = 24
_export_probe_cache = ContextVar("export_probe_cache", default=None)


def cache_export_av_probes(function):
    """Reuse identical physical reads only within one export, never across jobs."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        token = _export_probe_cache.set({})
        try:
            return function(*args, **kwargs)
        finally:
            _export_probe_cache.reset(token)
    return wrapped


def is_clip_execution_contract(contract: dict) -> bool:
    return contract.get("artifact_kind") in {"CLIP_ONLY", NATIVE_CONTINUITY_OUTPUT}


def probe_clip_av(path: str) -> dict:
    cache = _export_probe_cache.get()
    if cache is None:
        return _probe_clip_av(path)
    source = Path(path).resolve()
    stat = source.stat()
    key = (str(source), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    if key not in cache:
        result = _probe_clip_av(path)
        # A file changed while probing must not supply cached provenance.
        after = source.stat()
        if (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns):
            raise ValueError("CLIP_AV_SOURCE_CHANGED")
        cache[key] = result
    return dict(cache[key])


def _probe_clip_av(path: str) -> dict:
    exporting = _export_probe_cache.get() is not None
    result = subprocess.run(
        ["ffprobe", "-v", "error", *([] if exporting else ["-count_frames"]), "-show_streams", "-of", "json", path],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode:
        raise ValueError("CLIP_AV_UNREADABLE")
    streams = json.loads(result.stdout).get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not video:
        raise ValueError("CLIP_AV_UNREADABLE")
    if exporting and not str(video.get("nb_frames") or "").isdigit():
        # MP4 supplies its stored frame count immediately. Other containers
        # may need decoding; that fallback belongs to the background export.
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-count_frames", "-show_streams", "-of", "json", path],
            capture_output=True, text=True, timeout=600,
        )
        if result.returncode:
            raise ValueError("CLIP_AV_UNREADABLE")
        streams = json.loads(result.stdout).get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        if not video:
            raise ValueError("CLIP_AV_UNREADABLE")
    fps = Fraction(video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1")
    count = int(video.get("nb_read_frames") or video.get("nb_frames") or 0)
    if fps != FPS or Fraction(video.get("r_frame_rate") or "0/1") != FPS or count <= 0 or float(video.get("start_time") or 0) != 0:
        raise ValueError(f"CLIP_AV_TIMEBASE_INVALID: fps={fps}, r_frame_rate={video.get('r_frame_rate')}, frames={count}, start={video.get('start_time')}")
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return {
        "frame_count": count, "fps": FPS, "timebase": "1/24",
        "video_duration": count / FPS, "has_audio": audio is not None,
        "audio_duration": float(audio.get("duration") or 0) if audio else 0,
        "audio_start_time": float(audio.get("start_time") or 0) if audio else 0,
        "width": int(video["width"]), "height": int(video["height"]),
        "sha256": digest.hexdigest(),
    }


def validate_native_output(metadata: dict, result_url: str, path: str) -> dict:
    output = metadata.get("physical_output") or {}
    contract = metadata.get("execution_contract") or {}
    if (
        contract.get("artifact_kind") != NATIVE_CONTINUITY_OUTPUT
        or output.get("physical_output_role") != NATIVE_CONTINUITY_OUTPUT
        or output.get("result_url") != result_url
        or output.get("output_node_id") != "65"
        or output.get("capability") != contract.get("capability")
        or output.get("overlap_frames") != OVERLAP_FRAMES
        or output.get("overlap_duration") != OVERLAP_FRAMES / FPS
        or output.get("previous") != contract.get("previous_clip")
    ):
        raise ValueError("NATIVE_CONTINUITY_OUTPUT_UNAVAILABLE")
    actual = probe_clip_av(path)
    if (any(actual.get(key) != output.get(key) for key in actual) or not actual["has_audio"]
            or actual["audio_start_time"] != 0 or actual["audio_duration"] <= 0
            or actual["video_duration"] - actual["audio_duration"] > 1 / FPS):
        raise ValueError("NATIVE_CONTINUITY_OUTPUT_INVALID")
    validate_temporal_anchor_output_bound(contract, actual["frame_count"])
    return output


def validate_temporal_anchor_output_bound(contract: dict, final_frames: int) -> None:
    """Reject an anchor absent from the finalized replacement; never move it."""
    previous = (contract.get("previous_clip") or {}).get("physical_output") or {}
    start = int(previous.get("frame_count") or 0) - OVERLAP_FRAMES
    replacement_frames = final_frames - start
    for anchor in (contract.get("temporal_anchor_manifest") or {}).get("anchors") or []:
        position = anchor.get("frame_position")
        if not isinstance(position, int) or isinstance(position, bool) or not 1 <= position <= replacement_frames:
            details = {"anchor_id": (anchor.get("source") or {}).get("id"),
                       "effective_anchor_frame": position, "replacement_frames": replacement_frames,
                       "final_native_frames": final_frames, "previous_frames": previous.get("frame_count"),
                       "overlap_frames": OVERLAP_FRAMES}
            raise ValueError("NATIVE_TEMPORAL_ANCHOR_OUTPUT_BOUND_VIOLATION: " + json.dumps(details, sort_keys=True))


def continuity_output_metadata(result: dict, contract: dict, path: str, result_url: str) -> dict:
    """Accept only the strict finalized native output; never relabel raw39."""
    if contract.get("artifact_kind") != NATIVE_CONTINUITY_OUTPUT or result.get("physical_output_role") != NATIVE_CONTINUITY_OUTPUT or result.get("output_node_id") != "65":
        raise ValueError("NATIVE_CONTINUITY_OUTPUT_UNAVAILABLE")
    previous = contract.get("previous_clip") or {}
    source = previous.get("physical_output") or {}
    if not previous.get("generated_by_task_id") or source.get("fps") != FPS or source.get("timebase") != "1/24":
        raise ValueError("PREVIOUS_AV_UNAVAILABLE")
    count = int(source.get("frame_count") or 0)
    actual = probe_clip_av(path)
    if (count < OVERLAP_FRAMES or actual["frame_count"] <= count or not actual["has_audio"]
            or actual["audio_duration"] <= 0 or actual["audio_start_time"] != 0
            or actual["video_duration"] - actual["audio_duration"] > 1 / FPS):
        raise ValueError("NATIVE_CONTINUITY_OUTPUT_INVALID")
    validate_temporal_anchor_output_bound(contract, actual["frame_count"])
    return {
        **actual, "physical_output_role": NATIVE_CONTINUITY_OUTPUT,
        "output_node_id": "65", "source_video_url": result["video_url"], "result_url": result_url,
        "capability": contract["capability"], "previous": previous,
        "overlap_frames": OVERLAP_FRAMES, "overlap_duration": OVERLAP_FRAMES / FPS,
        "planned_semantic_duration": (contract.get("clip") or {}).get("duration_seconds"),
        "native_cumulative_duration": actual["video_duration"],
        "assembly_span": {"start_frame": count - OVERLAP_FRAMES, "end_frame": actual["frame_count"],
                          "replacement_frames": OVERLAP_FRAMES,
                          "net_new_frames": actual["frame_count"] - count,
                          "net_new_duration": (actual["frame_count"] - count) / FPS},
        "next_conditioning_role": NATIVE_CONTINUITY_OUTPUT,
        "raw_context_output": {"physical_output_role": "RAW_CONTEXT_OUTPUT", "output_node_id": "39",
                               "physical_duration": None},
    }


def continuous_assembly_spans(units: list[dict]) -> dict:
    """Map exact Previous terminal ranges and replace their AV overlap in T.

    Callers validate Task ownership/artifact hashes before this physical projection.
    source_frame_start is zero for production native conditioning. An explicitly
    verified terminal range can also be projected by offline fixture validation.
    """
    spans = []
    mappings = {}
    total = 0
    boundaries = []
    last_task = None
    for unit in units:
        media = unit["physical_output"]
        count = int(media["frame_count"])
        if media.get("fps") != FPS or media.get("timebase") != "1/24" or count <= 0:
            raise ValueError("CONTINUOUS_ASSEMBLY_TIMEBASE_INVALID")
        start = 0
        origin = total
        if unit["capability"] in CONTINUOUS_CAPABILITIES:
            previous = media.get("previous") or {}
            previous_id = previous.get("generated_by_task_id")
            source = previous.get("physical_output") or {}
            previous_count = int(source.get("frame_count") or 0)
            source_start = int(previous.get("source_frame_start") or 0)
            mapping = mappings.get(previous_id)
            if (
                media.get("physical_output_role") != NATIVE_CONTINUITY_OUTPUT
                or media.get("overlap_frames") != OVERLAP_FRAMES
                or media.get("overlap_duration") != OVERLAP_FRAMES / FPS
                or not media.get("has_audio")
                or previous_id != last_task or not mapping
                or source.get("fps") != FPS or source.get("timebase") != "1/24"
                or source_start < 0 or previous_count < OVERLAP_FRAMES
                or source_start + previous_count != mapping["frame_count"]
                or mapping["global_end"] != total or count <= previous_count
            ):
                raise ValueError("CONTINUOUS_ASSEMBLY_PREVIOUS_MAPPING_INVALID")
            start = previous_count - OVERLAP_FRAMES
            origin = mapping["global_origin"] + source_start
            boundary = origin + start
            kept = []
            for span in spans:
                if span["global_start"] >= boundary:
                    continue
                span = dict(span)
                if span["global_end"] > boundary:
                    span["end_frame"] -= span["global_end"] - boundary
                    span["global_end"] = boundary
                kept.append(span)
            spans = kept
            boundaries.append({"task_id": unit["task_id"], "previous_task_id": previous_id,
                               "local_overlap_start": start, "global_overlap_start": boundary,
                               "overlap_frames": OVERLAP_FRAMES})
            total = boundary
        spans.append({"path": unit["path"], "task_id": unit["task_id"],
                      "start_frame": start, "end_frame": count, "physical_output": media,
                      "global_start": total, "global_end": total + count - start})
        total += count - start
        mappings[unit["task_id"]] = {"global_origin": origin, "global_end": total, "frame_count": count}
        last_task = unit["task_id"]
    return {"spans": spans, "frame_count": total, "duration": total / FPS, "boundaries": boundaries}


def continuous_assembly_filter(spans: list[dict], width: int, height: int) -> str:
    """Video trims and audio trims share exactly the same24fps AV boundaries."""
    filters = []
    for i, span in enumerate(spans):
        start, end = span["start_frame"], span["end_frame"]
        media = span["physical_output"]
        seconds = (end - start) / FPS
        filters.append(f"[{i}:v:0]trim=start_frame={start}:end_frame={end},setpts=PTS-STARTPTS,"
                       f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                       f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,format=yuv420p[v{i}]")
        if media.get("has_audio"):
            # Keep the actual native final stream duration, including its suffix
            # absent from raw. Do not expose AAC decoder padding as new content.
            audio_end = end / FPS
            if i == len(spans) - 1 and end == media["frame_count"]:
                audio_end = max(audio_end, media.get("audio_duration") or 0)
            filters.append(f"[{i}:a:0]aresample=48000,atrim=start={start/FPS:.12f}:end={audio_end:.12f},"
                           f"asetpts=PTS-STARTPTS,"
                           f"apad=whole_dur={seconds:.12f}[a{i}]")
        else:
            filters.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={seconds:.12f}[a{i}]")
    joined = ''.join(f'[v{i}][a{i}]' for i in range(len(spans)))
    filters.append(f"{joined}concat=n={len(spans)}:v=1:a=1[v_joined][a]")
    filters.append("[v_joined]setpts=N/(24*TB)[v]")
    return ';'.join(filters)
