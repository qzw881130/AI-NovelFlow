"""Cached, unenhanced LLM image proxies and previous-video frame context."""
import base64
import hashlib
import json
import subprocess
from pathlib import Path

from PIL import Image

from app.services.file_storage import file_storage
from app.utils.path_utils import url_to_local_path, local_path_to_url
from app.services.continuous_clip_av import probe_clip_av


def vision_proxy(source, **metadata):
    path = Path(url_to_local_path(str(source)) or str(source))
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    cache = Path(file_storage.base_dir) / "_vision_proxy" / "v1_1024_q85"
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / f"{digest}.jpg"
    with Image.open(path) as image:
        source_size = list(image.size)
        if not destination.exists():
            proxy = image.convert("RGB")
            proxy.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
            proxy.save(destination, format="JPEG", quality=85)
    submitted = destination.read_bytes()
    with Image.open(destination) as image:
        submitted_size = list(image.size)
    return {**metadata, "url": "data:image/jpeg;base64," + base64.b64encode(submitted).decode(),
            "source_path": str(path), "source_dimensions": source_size, "source_sha256": digest,
            "submitted_dimensions": submitted_size, "mime_type": "image/jpeg", "is_proxy": True,
            "size_bytes": len(submitted), "sha256": hashlib.sha256(submitted).hexdigest(),
            "proxy_url": local_path_to_url(str(destination))}


def previous_video_frames(video_path, context_frames=None):
    if not video_path:
        return []
    if not isinstance(context_frames, int) or context_frames <= 0:
        raise ValueError("PREVIOUS_AV_CONTEXT_UNVERIFIED: read context length from the actual workflow")
    path = Path(url_to_local_path(str(video_path)) or str(video_path))
    # Diagnostic LLM previews of the existing masked AV context, not new H3
    # Pictures or a replacement for the native 39-frame conditioning path.
    probe = probe_clip_av(str(path))
    digest = probe["sha256"]
    last = probe["frame_count"] - 1
    first = probe["frame_count"] - context_frames
    if first < 0:
        raise ValueError(f"PREVIOUS_AV_CONTEXT_TOO_SHORT: requires {context_frames} frames")
    indexes = [first + round((last - first) * i / 4) for i in range(5)]
    cache = Path(file_storage.base_dir) / "_vision_proxy" / "previous" / digest
    cache.mkdir(parents=True, exist_ok=True)
    result = []
    for i, index in enumerate(indexes, 1):
        time = index / probe["fps"]
        destination = cache / f"context{context_frames}_frame_{index}.png"
        if not destination.exists():
            subprocess.run(["ffmpeg", "-v", "error", "-ss", str(time), "-i", str(path),
                            "-frames:v", "1", "-threads", "1", str(destination)], check=True, timeout=45)
        item = vision_proxy(destination, logical_id=f"PreviousFrame{i}", name=f"PreviousFrame{i}",
                            reference_type="PREVIOUS_VIDEO_FRAME", role="incoming_continuity", binding=None,
                            time=time, source_video_path=str(path), source_video_sha256=digest,
                            source_frame_index=index, context_start_frame=first, context_end_frame=last,
                            context_frames=context_frames, source_fps=probe["fps"], llm_preview_only=True,
                            authority="Previous Clip Continuity Reference: incoming pose, costume, spatial relations, motion and camera; current canonical dialogue, speakers, actions and outcomes remain authoritative; optional KFs do not force a discontinuous reset")
        result.append(item)
    return result
