"""Offline tail evidence; the parent must validate the same-run receipt first.

No source editing, app state, or semantic judgement. The window is the final 0.5s
of decoded display time, including a true last frame already held on screen.
Only up to five sampled indices are compared, not every frame or the full video.
An earlier reference requires small grayscale differences in its sampled suffix;
this is NOT proof of story geometry. The parent must also check coarse semantic
facts against the true last frame. Blink/mouth changes are not semantic errors.
"""

import asyncio
import hashlib
import json
import math
import os
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter, ImageStat

_TIMEOUT = 30
_INPUT_OPTIONS = ("-protocol_whitelist", "file,pipe", "-format_whitelist",
                  "mov,matroska,webm,avi,mpegts,mpeg,flv,ogg,nut", "-err_detect", "explode")
_RECIPE = {
    "version": "actual-tail-v1", "window_seconds": 0.5, "max_candidates": 5,
    "window_anchor": "last_best_effort_pts_plus_frame_duration; include_held_last",
    "sampling": "evenly_spread_decoded_indices_in_window_including_true_last",
    "sharpness": "mean_abs_gray_minus_gaussian_radius_1_at_max_256px / 255",
    "reference_min_best_ratio": 0.65, "selection": "latest_reference_usable",
    "unusable": "max_rgb_stddev<=1 or (gray_mean<=12 and gray_stddev<=4)",
    "tail_difference": "64x64_bilinear_grayscale_mean_absolute_difference / 255",
    "tail_difference_limit": 0.12,
    "fade": "sampled_contrast_halved_and_mean_changed_over_0.12",
    "semantic_proof": False, "parent_semantic_check_required": True,
    "decode": "first_video_stream_no_autorotate_rgb24_lossless_png",
    "subprocess_timeout_seconds": _TIMEOUT,
}


def _fingerprint(path):
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
        return digest, os.fstat(source.fileno()).st_size


async def _run(*args):
    # Shield spawning too: cancellation must not orphan a just-created child.
    spawn = asyncio.create_task(asyncio.create_subprocess_exec(
        *args, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={key: value for key, value in os.environ.items() if key != "FFREPORT"},
    ))
    communication = None
    try:
        process = await asyncio.shield(spawn)
        communication = asyncio.create_task(process.communicate())
        stdout, stderr = await asyncio.wait_for(asyncio.shield(communication), _TIMEOUT)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        process = await asyncio.shield(spawn)
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await asyncio.shield(communication or asyncio.create_task(process.communicate()))
        raise
    if process.returncode or stderr.strip():
        raise ValueError(f"{Path(args[0]).name} exit={process.returncode}: "
                         f"{stderr.decode(errors='replace').strip()}")
    return stdout


def _select(result, images):
    """Mutate the transparent result, retaining selection even when the tail fails."""
    candidates, grays, stats = result["candidates"], {}, {}
    for candidate, image in zip(candidates, images):
        gray = image.convert("L")
        gray.thumbnail((256, 256), Image.Resampling.BILINEAR)
        stat = ImageStat.Stat(gray)
        mean, contrast = stat.mean[0], stat.stddev[0]
        uniform = max(ImageStat.Stat(image).stddev) <= 1
        usable = not (uniform or (mean <= 12 and contrast <= 4))
        sharpness = ImageStat.Stat(ImageChops.difference(
            gray, gray.filter(ImageFilter.GaussianBlur(1)))).mean[0] / 255
        candidate.update(usable=usable, sharpness=sharpness,
                         reason="ok" if usable else "uniform_or_near_black")
        grays[candidate["frame_index"]] = gray.resize((64, 64), Image.Resampling.BILINEAR)
        stats[candidate["frame_index"]] = (mean / 255, contrast / 255)
    best = max((c["sharpness"] for c in candidates if c["usable"]), default=0)
    for candidate in candidates:
        candidate["reference_usable"] = candidate["usable"] and candidate["sharpness"] >= best * 0.65
        if candidate["usable"] and not candidate["reference_usable"]:
            candidate["reason"] = "relative_blur"
    selected = next((c for c in reversed(candidates) if c["reference_usable"]), None)
    result["selected"] = selected
    position = candidates.index(selected) if selected else len(candidates) - 1
    neighbor = candidates[min(position + 1, len(candidates) - 1) if position < len(candidates) - 1
                          else max(0, position - 1)]
    result["observation_candidates"] = list({c["frame_index"]: c for c in
        (selected, candidates[-1], neighbor) if c is not None}.values())
    if selected:
        scores = [{"frame_index": c["frame_index"], "difference": ImageStat.Stat(
            ImageChops.difference(grays[selected["frame_index"]], grays[c["frame_index"]])
        ).mean[0] / 255} for c in candidates[position:]]
        result["tail_difference"].update(scores=scores, maximum=max(s["difference"] for s in scores))
        result["technical_tail_compatible"] = (
            all(c["usable"] for c in candidates[position:])
            and result["tail_difference"]["maximum"] <= 0.12)
    # Obvious sampled fade in either direction is unsupported, not a story fact.
    fade = any(abs(a[0] - b[0]) > 0.12 and min(a[1], b[1]) < max(a[1], b[1]) * 0.5
               for a in stats.values() for b in stats.values())
    if fade:
        result["technical_tail_compatible"] = False
    reason = ("no_reference_usable_candidate" if selected is None else
              "observation_candidate_unusable_requires_human" if not all(
                  c["usable"] for c in result["observation_candidates"]) else
              "unusable_tail_frame_requires_human" if not all(c["usable"] for c in candidates) else
              "fade_unsupported_requires_human" if fade else
              "tail_appearance_change_requires_human" if not result["technical_tail_compatible"] else "ok")
    result.update(can_use=reason == "ok", reason=reason)


async def extract_tail_window(video_path, directory, *, expected_sha256) -> dict:
    """Write exclusive PNGs in a NEW private directory (its parent must exist).

    Returns JSON-compatible evidence, never an authorization or semantic verdict.
    Source/hash changes raise ValueError; probe/decode/EOF failures return can_use
    False with the actual error and any known frame metadata. Directory collisions
    raise FileExistsError. Offsets are nonnegative seconds backwards from their
    named endpoints; video_end_seconds is last PTS plus its decoded duration.
    Frame indices are zero-based decoded display order; PTS are stream seconds.
    """
    try:
        source = Path(video_path).resolve(strict=True)
        if not source.is_file():
            raise ValueError("not a regular source file")
        before, size = _fingerprint(source)
    except (OSError, ValueError) as error:
        raise ValueError(f"source_integrity: {error}") from error
    if not isinstance(expected_sha256, str) or before != expected_sha256.lower():
        raise ValueError("source_integrity: expected_sha256 mismatch")
    output = Path(directory).absolute()
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    result = {
        "can_use": False, "reason": "source_integrity", "error": None,
        "selected": None, "observation_candidates": [], "candidates": [],
        "last_frame_index": None, "last_frame_pts": None, "video_end_seconds": None,
        "window_start_pts": None, "source_path": str(source), "source_sha256": before,
        "expected_sha256": expected_sha256.lower(), "source_size_bytes": size,
        "source_sha256_after": None, "source_size_bytes_after": None,
        "technical_tail_compatible": False, "recipe": dict(_RECIPE),
        "tail_difference": {"scores": [], "maximum": None, "limit": 0.12, "semantic_proof": False},
    }
    try:
        probe = json.loads(await _run(
            "ffprobe", "-v", "error", *_INPUT_OPTIONS, "-select_streams", "v:0",
            "-show_frames", "-show_streams", "-show_entries",
            "frame=best_effort_timestamp_time,duration_time,pkt_duration_time,width,height,decode_error_flags:"
            "stream=width,height,start_time,duration,nb_frames", "-of", "json", str(source)))
        frames, stream = probe["frames"], probe["streams"][0]
        pts = [float(f["best_effort_timestamp_time"]) for f in frames]
        if not pts or any(not math.isfinite(p) for p in pts) or pts != sorted(pts):
            raise ValueError("missing/nonmonotonic decoded timestamps")
        last = len(frames) - 1
        result.update(last_frame_index=last, last_frame_pts=pts[-1])
        duration = float(frames[-1].get("duration_time", frames[-1].get("pkt_duration_time", 0)))
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("unknown true-last-frame duration/EOF")
        end = pts[-1] + duration
        start = max(pts[0], end - 0.5)
        result.update(video_end_seconds=end, window_start_pts=start)
        indices = [i for i, p in enumerate(pts) if p >= start or i == last]
        count = min(5, len(indices))
        indices = [indices[round(i * (len(indices) - 1) / max(1, count - 1))] for i in range(count)]
        result["candidates"] = [{
            "path": str(output / f"frame_{i:08d}.png"), "sha256": None,
            "frame_index": i, "pts": pts[i], "offset_from_last_frame_seconds": pts[-1] - pts[i],
            "offset_from_video_end_seconds": end - pts[i], "usable": False,
            "reference_usable": False, "sharpness": None, "reason": "not_decoded",
        } for i in indices]
        if any(int(f.get("decode_error_flags", 0)) for f in frames):
            raise ValueError("decoded frame error flags; EOF untrusted")
        if stream.get("nb_frames", "N/A") != "N/A" and int(stream["nb_frames"]) != len(frames):
            raise ValueError("decoded frame count disagrees with source; EOF untrusted")
        if stream.get("duration", "N/A") != "N/A":
            declared_end = float(stream.get("start_time", pts[0])) + float(stream["duration"])
            if not math.isfinite(declared_end) or abs(declared_end - end) > 0.002:
                raise ValueError("decoded video end disagrees with source; EOF untrusted")
        width, height = int(stream["width"]), int(stream["height"])
        if width <= 0 or height <= 0 or any((f["width"], f["height"]) != (width, height) for f in frames):
            raise ValueError("unsupported changing/invalid decoded dimensions")
        raw = await _run(
            "ffmpeg", "-v", "error", "-nostdin", "-xerror", *_INPUT_OPTIONS, "-noautorotate",
            "-i", str(source), "-map", "0:v:0", "-an", "-sn", "-dn", "-vf",
            "select=" + "+".join(f"eq(n\\,{i})" for i in indices), "-fps_mode", "passthrough",
            "-c:v", "rawvideo", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1")
        frame_size = width * height * 3
        if len(raw) != frame_size * count:
            raise ValueError("decoded candidate count/size mismatch; EOF untrusted")
        images = []
        for ordinal, candidate in enumerate(result["candidates"]):
            image = Image.frombytes("RGB", (width, height), raw[ordinal * frame_size:(ordinal + 1) * frame_size])
            path = Path(candidate["path"])
            with path.open("xb") as target:
                image.save(target, format="PNG")
            candidate["sha256"] = _fingerprint(path)[0]
            images.append(image)
        _select(result, images)
    except (ValueError, KeyError, IndexError, OSError, asyncio.TimeoutError) as error:
        result.update(can_use=False, reason="source_integrity", error=f"{type(error).__name__}: {error}",
                      technical_tail_compatible=False)
    finally:
        try:
            after, after_size = _fingerprint(source)
        except OSError as error:
            raise ValueError(f"source_integrity: source unavailable after decode: {error}") from error
        result.update(source_sha256_after=after, source_size_bytes_after=after_size)
        if (after, after_size) != (before, size):
            raise ValueError("source_integrity: source changed during extraction")
    return result
