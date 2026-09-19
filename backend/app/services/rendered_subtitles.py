"""Content-bound cue snapshots. Cue times are absolute media presentation times.

Sidecars are local trusted artifacts, not evidence recoverable from arbitrary video.
No business rows are consulted when composing or exporting an existing artifact.
"""

import hashlib
import json
import os
from pathlib import Path
import tempfile
from fractions import Fraction

VERSION = 1


def fingerprint(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sidecar(path):
    return Path(str(path) + ".subtitles.json")


def _digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def snapshot_digest(data):
    return _digest(data)


def publish(path, cues, lineage, *, unavailable=None):
    data = {"version": VERSION, "media_sha256": fingerprint(path),
            "cues": cues, "lineage": lineage, "unavailable": unavailable}
    envelope = {"snapshot": data, "sha256": _digest(data)}
    target = sidecar(path)
    fd, temporary = tempfile.mkstemp(prefix=".subtitles-", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(envelope, stream, ensure_ascii=True, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return data


def load_against_receipt(path, expected_media_sha256, *, require_ready=True):
    try:
        envelope = json.loads(sidecar(path).read_text(encoding="utf-8"))
        data = envelope["snapshot"]
        if (data["version"] != VERSION or envelope["sha256"] != _digest(data)
                or data["media_sha256"] != expected_media_sha256
                or not isinstance(data["lineage"], dict)):
            return None
        previous = Fraction(0)
        for cue in data["cues"]:
            start, end = Fraction(cue["start"]), Fraction(cue["end"])
            if start < previous or end <= start or not isinstance(cue["text"], str):
                return None
            previous = start
        if require_ready and data.get("unavailable"):
            return None
        return data
    except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError):
        return None


def load(path, *, require_ready=True):
    try:
        return load_against_receipt(path, fingerprint(path), require_ready=require_ready)
    except OSError:
        return None


def compose(segments, snapshots):
    if len(segments) != len(snapshots):
        raise ValueError("Incomplete merge source mapping")
    cues = []
    unavailable = None
    for segment, snapshot in zip(segments, snapshots):
        if snapshot is None or snapshot.get("unavailable"):
            unavailable = "Source has no verified rendered subtitle snapshot; regenerate Clip Audio and video, then merge again."
            continue
        origin = Fraction(segment["origin"])
        offset = Fraction(segment["offset_samples"], 48000)
        end = Fraction(segment["target_samples"], 48000)
        for cue in snapshot["cues"]:
            start = max(Fraction(0), Fraction(cue["start"]) - origin)
            stop = min(end, Fraction(cue["end"]) - origin)
            if stop > start:
                cues.append({**cue, "start": str(offset + start), "end": str(offset + stop)})
    return sorted(cues, key=lambda cue: Fraction(cue["start"])), unavailable


def matches_sources(path, sources):
    snapshot = load(path, require_ready=False)
    if not snapshot or snapshot["lineage"].get("kind") != "merge":
        return False
    segments = snapshot["lineage"].get("segments", [])
    if len(segments) != len(sources):
        return False
    try:
        if len(snapshot["lineage"]["sources"]) != len(sources):
            return False
        return all(segment["source_sha256"] == fingerprint(source)
                   and (stored == load(source) or (stored is not None
                        and stored["lineage"].get("kind") == "probed_no_audio"))
                   for segment, stored, source in zip(segments, snapshot["lineage"]["sources"], sources))
    except (OSError, KeyError, TypeError):
        return False


async def lock_generated_audio(storage, video_path, audio_path, snapshot):
    """Enforce lock_source locally; a remote workflow input is not output proof."""
    if not snapshot or snapshot["media_sha256"] != fingerprint(audio_path):
        return
    with tempfile.TemporaryDirectory(prefix=".subtitle-lock-", dir=Path(video_path).parent) as directory:
        # Freeze the exact supplied bytes before invoking ffmpeg.
        import shutil
        frozen = Path(directory) / "source.wav"
        shutil.copyfile(audio_path, frozen)
        if fingerprint(frozen) != snapshot["media_sha256"]:
            return
        candidate = Path(directory) / "locked.mp4"
        result = await storage._run_merge_process([
            "ffmpeg", "-v", "error", "-xerror", "-i", str(video_path), "-i", str(frozen),
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
            "-af", "asetpts=PTS-STARTPTS", "-c:a", "aac", "-movflags", "+faststart",
            "-y", str(candidate),
        ])
        if result.returncode:
            raise RuntimeError("Could not lock generated video to its subtitle audio: " + result.stderr[:200])
        os.replace(candidate, video_path)
        publish(video_path, snapshot["cues"], {"kind": "locked_audio", "audio": snapshot})
