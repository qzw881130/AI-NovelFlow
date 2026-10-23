"""Preserve node65's complete continuation video when its VHS audio mux trims it."""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from app.services.continuous_clip_av import NATIVE_CONTINUITY_OUTPUT, FPS, probe_clip_av


def native_video_only_url(result: dict) -> str:
    """Use the paired filename contract of deployed VHS, never a raw39 preview."""
    if result.get("physical_output_role") != NATIVE_CONTINUITY_OUTPUT or result.get("output_node_id") != "65":
        raise ValueError("NATIVE_AV_MUX_INPUT_UNAVAILABLE")
    url = urlsplit(result.get("video_url") or "")
    pairs = parse_qsl(url.query, keep_blank_values=True)
    filenames = [value for key, value in pairs if key == "filename"]
    types = [value for key, value in pairs if key == "type"]
    if (url.scheme not in {"http", "https"} or not url.netloc or not url.path.endswith("/view") or types != ["output"]
            or len(filenames) != 1 or not filenames[0].endswith("-audio.mp4")):
        raise ValueError("NATIVE_AV_MUX_INPUT_UNAVAILABLE")
    # VHS nodes.py allocates <filename>_<counter>.mp4 and the paired
    # <filename>_<counter>-audio.mp4 in the very same output subfolder.
    pairs = [(key, value[:-len("-audio.mp4")] + ".mp4" if key == "filename" else value)
             for key, value in pairs]
    return urlunsplit(url._replace(query=urlencode(pairs)))


def _packets(path: str, stream: str) -> list:
    process = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", stream, "-show_packets",
         "-show_data_hash", "sha256", "-show_entries",
         "packet=pts_time,dts_time,duration_time,flags,data_hash", "-of", "json", path],
        capture_output=True, text=True, timeout=120,
    )
    if process.returncode:
        raise ValueError("NATIVE_AV_MUX_INPUT_UNREADABLE")
    return json.loads(process.stdout).get("packets") or []


def remux_native_av(video_only_path: str, av_path: str) -> dict:
    """Copy complete video plus the existing AAC timeline, without -shortest."""
    video = probe_clip_av(video_only_path)
    before = probe_clip_av(av_path)
    if video["has_audio"] or not before["has_audio"] or before["audio_start_time"] != 0:
        raise ValueError("NATIVE_AV_MUX_INPUT_INVALID")
    if before["audio_duration"] <= 0 or abs(video["video_duration"] - before["audio_duration"]) > 1 / FPS:
        raise ValueError("NATIVE_AV_MUX_AUDIO_TIMEBASE_INVALID")
    expected_packets = _packets(video_only_path, "v:0")
    existing_packets = _packets(av_path, "v:0")
    audio_packets = _packets(av_path, "a:0")
    if (not expected_packets or not audio_packets or len(existing_packets) > len(expected_packets)
            or existing_packets != expected_packets[:len(existing_packets)]):
        raise ValueError("NATIVE_AV_MUX_VIDEO_PROVENANCE_INVALID")
    with tempfile.TemporaryDirectory(prefix="native-av-mux-", dir=Path(av_path).parent) as folder:
        output = str(Path(folder) / "native.mp4")
        process = subprocess.run(
            ["ffmpeg", "-v", "error", "-n", "-i", video_only_path, "-i", av_path,
             "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", "-map_metadata", "1", output],
            capture_output=True, text=True, timeout=120,
        )
        if process.returncode:
            raise ValueError("NATIVE_AV_MUX_FAILED")
        after = probe_clip_av(output)
        if (after["frame_count"] != video["frame_count"] or _packets(output, "v:0") != expected_packets
                or _packets(output, "a:0") != audio_packets or not after["has_audio"]
                or after["audio_start_time"] != 0
                or abs(after["video_duration"] - after["audio_duration"]) > 1 / FPS):
            raise ValueError("NATIVE_AV_MUX_FRAME_PRESERVATION_FAILED")
        decode = subprocess.run(
            ["ffmpeg", "-v", "error", "-xerror", "-i", output, "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"],
            capture_output=True, text=True, timeout=120,
        )
        if decode.returncode:
            raise ValueError("NATIVE_AV_MUX_DECODE_FAILED")
        os.replace(output, av_path)
    return {"policy": "CONTINUATION_VIDEO_AUTHORITATIVE_STREAM_COPY", "video_only_sha256": video["sha256"],
            "source_av_sha256": before["sha256"], "frames_before": before["frame_count"],
            "frames_after": after["frame_count"], "video_packets_timestamps_preserved": True,
            "audio_packets_timestamps_preserved": True}


async def preserve_native_av(result: dict, av_path: str) -> dict:
    """Fetch only the same node65 mux input; missing input fails, no fallback."""
    source_url = native_video_only_url(result)
    with tempfile.TemporaryDirectory(prefix="native-av-input-", dir=Path(av_path).parent) as folder:
        video_only = str(Path(folder) / "video-only.mp4")
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(source_url, timeout=120)
                response.raise_for_status()
                Path(video_only).write_bytes(response.content)
        except (httpx.HTTPError, OSError) as exc:
            raise ValueError("NATIVE_AV_MUX_INPUT_UNAVAILABLE") from exc
        evidence = await asyncio.to_thread(remux_native_av, video_only, av_path)
    return {**evidence, "video_only_source_url": source_url}
