"""Generic read-only media probing and lazy Native-index extraction for Inspector."""
import bisect
import hashlib
import json
import math
import re
import statistics
import subprocess
import tempfile
import threading
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction
from pathlib import Path
from urllib.parse import unquote

from app.services.inspector_store import InspectorError, InspectorStore, atomic_json, digest, read_json, safe_token

RENDER_VERSION = "frame-v1"
PRESETS = {"thumb": 320, "detail": 960}
_DECODE_LOCK = threading.Lock()
_HASH_LOCK = threading.Lock()
_HASH_CACHE = {}


def file_hash(path):
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    with _HASH_LOCK:
        if key not in _HASH_CACHE:
            h = hashlib.sha256()
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    h.update(chunk)
            _HASH_CACHE[key] = h.hexdigest()
        return _HASH_CACHE[key]


def fraction(value, default="0"):
    try:
        return Fraction(str(value if value is not None else default))
    except (ValueError, ZeroDivisionError):
        return Fraction(default)


def finite(value):
    try:
        f = float(value)
        return f if math.isfinite(f) else None
    except (ValueError, TypeError):
        return None


def build_mapping(media, contract, physical, planned_duration):
    result = {"mapping_version": 1, "mode": "UNKNOWN", "status": "DEGRADED", "time_domain": "NATIVE",
              "planned_duration": planned_duration, "axis_duration": float(fraction(media["end_pts_exact"])) if media.get("end_pts_exact") else None,
              "origin_frame_index0": None, "origin_native_pts": None, "warnings": []}
    if media.get("status") != "EXPLICIT" or not media.get("pts_monotonic"):
        result["warnings"].append("MEDIA_OR_PTS_UNAVAILABLE")
        return result
    count = media["frame_count"]
    capability = contract.get("capability")
    origin = None
    if capability == "GENERATE" and contract.get("artifact_kind") == "CLIP_ONLY":
        origin = 0
    elif capability in ("EXTEND", "TEMPORAL_EXTEND"):
        span = physical.get("assembly_span") or {}
        previous = (contract.get("previous_clip") or {}).get("physical_output") or {}
        p, overlap, start, end = (previous.get("frame_count"), physical.get("overlap_frames"),
                                  span.get("start_frame"), span.get("end_frame"))
        if (all(isinstance(x, int) and not isinstance(x, bool) for x in (p, overlap, start, end))
                and 0 <= overlap <= p and start == p - overlap and 0 <= start < end == count
                and physical.get("physical_output_role") == "NATIVE_CONTINUITY_OUTPUT"
                and physical.get("frame_count") == count):
            origin = start
            result.update(previous_frame_count=p, overlap_frames=overlap,
                          net_new_frames=count - p, replacement_frames=count - start,
                          assembly_span={"start_frame": start, "end_frame": end})
        else:
            result["warnings"].append("REPLACEMENT_SPAN_UNCONFIRMED")
    if origin is None:
        result["warnings"].append("CLIP_ORIGIN_UNKNOWN_USE_NATIVE_TIME")
        return result
    # Continuity frame positions require the recorded grid to agree with measured CFR.
    if capability != "GENERATE" and (not media["is_cfr"] or fraction(physical.get("fps")) != fraction(media["fps"])):
        result["warnings"].append("EXECUTION_GRID_DIFFERS_FROM_MEDIA_USE_NATIVE_TIME")
        return result
    pts = media["pts"]
    duration = float(fraction(media["end_pts_exact"]) - fraction(media["pts_exact"][origin]))
    result.update(mode="FRAME_INDEX_CFR" if media["is_cfr"] else "PTS_VFR", status="EXPLICIT",
                  time_domain="CLIP_LOCAL", origin_frame_index0=origin, origin_native_pts=pts[origin],
                  origin_pts_exact=media["pts_exact"][origin], window_duration=duration,
                  replacement_frames=count - origin, axis_duration=max(planned_duration or 0, duration),
                  fps=media["fps"], evidence="Task execution contract + measured Native frame PTS")
    return result


def resolve_sample(media, mapping, requested, native_index=None, boundary=False):
    requested = finite(requested)
    result = {"requested_time": requested, "status": "SOURCE_NOT_AVAILABLE"}
    if requested is None or requested < 0:
        return {**result, "status": "OUT_OF_VIDEO"}
    if media.get("status") != "EXPLICIT" or not media.get("pts_monotonic"):
        return result
    pts = media["pts"]
    clip = mapping["time_domain"] == "CLIP_LOCAL"
    origin = mapping["origin_frame_index0"] if clip else 0
    duration = mapping.get("window_duration") if clip else float(fraction(media["end_pts_exact"]))
    if not clip and requested < pts[0]:
        return {**result, "status": "OUT_OF_VIDEO"}
    if requested > duration + 1e-7 or (requested >= duration and not boundary):
        return {**result, "status": "OUT_OF_VIDEO"}
    n = native_index
    if n is None:
        if boundary and abs(requested - duration) <= 1e-7:
            n = len(pts) - 1
        elif clip and mapping["mode"] == "FRAME_INDEX_CFR":
            rate = fraction(media["fps"])
            k = int((Decimal(str(requested)) * Decimal(rate.numerator) / Decimal(rate.denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            n = origin + k
        else:
            target = fraction(str(requested)) + (fraction(mapping["origin_pts_exact"]) if clip else Fraction(0))
            exact = [fraction(p) for p in media["pts_exact"]]
            i = bisect.bisect_left(exact, target, lo=origin)
            candidates = [j for j in (i - 1, i) if origin <= j < len(pts)]
            n = min(candidates, key=lambda j: (abs(exact[j] - target), -j)) if candidates else None
    # A request inside the last frame's presentation interval selects that last frame.
    if n == len(pts) and requested < duration:
        n = len(pts) - 1
    if n is None or n < origin or n >= len(pts):
        return {**result, "status": "OUT_OF_VIDEO"}
    sample_time = float(fraction(media["pts_exact"][n]) - (fraction(media["pts_exact"][origin]) if clip else 0))
    return {**result, "status": "EXPLICIT", "native_frame_index0": n, "native_pts": pts[n],
            "sample_clip_time": sample_time if clip else None, "sample_time": sample_time,
            "local_frame_index0": n - origin if clip else None,
            "h3_position1": n - origin + 1 if clip and mapping["mode"] == "FRAME_INDEX_CFR" else None,
            "quantization_error": sample_time - requested,
            "boundary_behavior": "LAST_VALID_FRAME" if boundary and abs(requested - duration) <= 1e-7 else "NEAREST_PTS"}


def sampling_manifest(projection, spec, observations=()):
    interval = spec.get("uniform_interval_seconds", 1)
    if interval not in (.5, 1, 2):
        raise InspectorError("INVALID_SAMPLING", "采样间隔必须是 0.5、1 或 2 秒")
    enhanced = bool(spec.get("event_enhanced", True))
    neighbors = bool(spec.get("event_neighbors", True))
    mapping, media = projection["time_mapping"], projection["media"]
    clip = mapping["time_domain"] == "CLIP_LOCAL"
    duration = mapping.get("window_duration") if clip else (float(fraction(media["end_pts_exact"])) if media.get("end_pts_exact") else None)
    window_start = 0 if clip else media.get("start_pts", 0)
    requests = []
    def add(t, reason, event_id=None, native_index=None, boundary=False):
        if finite(t) is not None:
            requests.append({"time": float(t), "reason": reason, "event_id": event_id,
                             "native_index": native_index, "boundary": boundary})
    if duration is not None:
        if duration / interval > 20000:
            raise InspectorError("SAMPLING_WINDOW_TOO_LARGE", "视频过长，请缩小采样范围")
        if spec.get("include_uniform", True):
            for i in range(math.ceil(duration / interval)):
                if i * interval >= window_start:
                    add(i * interval, "UNIFORM")
        add(window_start, "WINDOW_START", boundary=True)
        add(duration, "WINDOW_END", boundary=True)
    if clip:
        add(0, "CLIP_START", boundary=True)
        add(mapping.get("planned_duration"), "PLANNED_CLIP_END", boundary=True)
        if enhanced and neighbors and duration is not None:
            for t, name in ((0, "CLIP_START"), (mapping.get("planned_duration"), "PLANNED_CLIP_END"), (duration, "WINDOW_END")):
                if t is not None:
                    for delta in (-.25, .25):
                        if 0 <= t + delta < duration:
                            add(t + delta, f"{name}:NEIGHBOR:{delta:+}")
        if enhanced:
            for event in projection["events"]:
                for name in ("start", "end"):
                    t = event.get(name)
                    if t is None or (name == "end" and t == event.get("start")):
                        continue
                    reason = f"{event['type']}:{name.upper()}" + (":SCOPE_BOUNDARY" if event["timing_kind"] == "CLIP_SCOPE" else "")
                    native = event.get("native_frame_index0") if event["type"] == "PHYSICAL_ANCHOR" else None
                    add(t, reason, event["id"], native, boundary=True)
                    if neighbors and duration is not None:
                        for delta in (-.25, .25):
                            if 0 <= t + delta < duration:
                                add(t + delta, f"{reason}:NEIGHBOR:{delta:+}", event["id"])
        for note in observations:
            for t in (note["time_seconds"], note.get("end_time_seconds")):
                add(t, "HUMAN_MARKER", note["observation_id"], boundary=True)
    extra = spec.get("requested_times", [])
    if not isinstance(extra, list) or len(extra) > 200:
        raise InspectorError("INVALID_SAMPLING", "额外采样点过多")
    for t in extra:
        if finite(t) is None or isinstance(t, bool) or float(t) < 0:
            raise InspectorError("INVALID_TIME", "采样时间必须是有效非负秒数")
        add(t, "MANUAL_REQUEST", boundary=True)
    samples, unresolved = {}, []
    for request in requests:
        frame = resolve_sample(media, mapping, request["time"], request["native_index"], request["boundary"])
        entry = {"time": request["time"], "reason": request["reason"], "event_id": request["event_id"],
                 "quantization_error": frame.get("quantization_error"), "boundary_behavior": frame.get("boundary_behavior")}
        if frame["status"] != "EXPLICIT":
            unresolved.append({**entry, "status": frame["status"]})
            continue
        n = frame["native_frame_index0"]
        sample = samples.setdefault(n, {**frame, "sample_id": f"{projection['artifact']['video_sha256']}:{n}",
                                       "artifact_id": projection["artifact"]["artifact_id"],
                                       "requested_times": [], "reasons": [], "event_refs": []})
        if entry not in sample["requested_times"]:
            sample["requested_times"].append(entry)
        for key, value in (("reasons", request["reason"]), ("event_refs", request["event_id"])):
            if value is not None and value not in sample[key]:
                sample[key].append(value)
    normalized = {"sampling_version": 1, "uniform_interval_seconds": interval, "event_enhanced": enhanced,
                  "event_neighbors": neighbors, "include_uniform": bool(spec.get("include_uniform", True)),
                  "requested_times": extra, "frame_selection": "NEAREST_PTS"}
    # Read timestamps are provenance, not changes to the event set.
    stable_events = [{**e, "source_refs": [{k: v for k, v in ref.items() if k != "observed_at"}
                                         for ref in e.get("source_refs", [])]} for e in projection["events"]]
    events_hash = digest({"events": stable_events, "observations": list(observations)})
    manifest_id = digest({"spec": normalized, "events": events_hash, "artifact": projection["artifact"]["artifact_id"],
                          "mapping": mapping, "projection_version": 1})
    ordered = sorted(samples.values(), key=lambda s: s["native_frame_index0"])
    video_hash = projection["artifact"].get("video_sha256")
    for sample in ordered:
        sample["image_url"] = f"/api/clip-execution-inspector/frames/{video_hash}/{RENDER_VERSION}/thumb/{sample['native_frame_index0']}"
        sample["detail_url"] = sample["image_url"].replace("/thumb/", "/detail/")
    return {"manifest_id": manifest_id, "sampling_version": 1, "render_version": RENDER_VERSION,
            "mapping_version": 1, "projection_version": 1, "spec": normalized, "event_set_hash": events_hash,
            "task_id": projection["execution"]["task_id"], "artifact_id": projection["artifact"]["artifact_id"],
            "video_sha256": video_hash, "clip_ref": projection["clip_ref"], "time_domain": mapping["time_domain"],
            "requested_count": len(requests), "unique_frame_count": len(ordered),
            "deduplicated_count": len(requests) - len(unresolved) - len(ordered),
            "samples": ordered, "unresolved": unresolved}


class InspectorFrameService:
    def __init__(self, store=None):
        self.store = store or InspectorStore()
        self.extractions = 0

    def resolve_path(self, result_url):
        if not isinstance(result_url, str) or not result_url.startswith("/api/files/"):
            raise InspectorError("MEDIA_UNAVAILABLE", "没有受控本地视频", 404)
        suffix = unquote(result_url[len("/api/files/"):])
        if "\\" in suffix or "\0" in suffix or "?" in suffix or "#" in suffix:
            raise InspectorError("UNSAFE_PATH", "媒体路径无效", 403)
        path = self.store.controlled(self.store.media_root / suffix)
        if not path.is_file():
            raise InspectorError("MEDIA_UNAVAILABLE", "源视频文件不可用", 404)
        return path

    def probe(self, result_url, novel_id, task_id):
        path = self.resolve_path(result_url)
        sha = file_hash(path)
        cache = self.store.story_root(novel_id) / "cache" / sha
        with _DECODE_LOCK:
            probe_path = cache / "probe-v1.json"
            if probe_path.is_file():
                media = read_json(probe_path)
            else:
                try:
                    process = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-show_frames",
                                              "-show_entries", "frame=media_type,best_effort_timestamp,best_effort_timestamp_time,pkt_duration,pkt_duration_time:stream=index,codec_type,avg_frame_rate,r_frame_rate,time_base,start_time,duration,nb_frames,width,height:format=duration",
                                              "-of", "json", str(path)], capture_output=True, text=True, check=True, timeout=60)
                    data = json.loads(process.stdout)
                    video = next(s for s in data["streams"] if s["codec_type"] == "video")
                    audio = next((s for s in data["streams"] if s["codec_type"] == "audio"), {})
                    frames = [f for f in data["frames"] if f.get("media_type") == "video"]
                    base = fraction(video["time_base"])
                    exact = [str(int(f["best_effort_timestamp"]) * base) if "best_effort_timestamp" in f
                             else str(fraction(f["best_effort_timestamp_time"])) for f in frames]
                    pts = [float(fraction(p)) for p in exact]
                    if not pts:
                        raise ValueError("No video frames")
                    rate = fraction(video.get("avg_frame_rate"))
                    steps = [fraction(b) - fraction(a) for a, b in zip(exact, exact[1:])]
                    monotonic = all(step > 0 for step in steps)
                    cfr = bool(rate > 0 and monotonic and all(abs(step - 1 / rate) <= base for step in steps))
                    last_duration = fraction(frames[-1].get("pkt_duration")) * base
                    if last_duration <= 0:
                        last_duration = statistics.median(steps) if steps else (1 / rate if rate > 0 else Fraction(0))
                    end = fraction(exact[-1]) + last_duration
                    media = {"status": "EXPLICIT", "video_sha256": sha, "frame_count": len(frames),
                             "fps": str(rate), "fps_numerator": rate.numerator, "fps_denominator": rate.denominator,
                             "r_frame_rate": video.get("r_frame_rate"), "is_cfr": cfr, "pts_monotonic": monotonic,
                             "stream_time_base": video["time_base"], "start_pts": pts[0], "pts": pts, "pts_exact": exact,
                             "end_pts_exact": str(end), "video_duration": float(end - fraction(exact[0])),
                             "video_stream_duration": finite(video.get("duration")),
                             "container_duration": finite(data.get("format", {}).get("duration")),
                             "audio_duration": finite(audio.get("duration")), "audio_start_time": finite(audio.get("start_time")),
                             "width": video["width"], "height": video["height"], "warnings": []}
                    if not cfr:
                        media["warnings"].append("VFR_USE_ACTUAL_PTS")
                    if rate != 24:
                        media["warnings"].append("NON_24_FPS")
                    if not monotonic:
                        media["warnings"].append("NON_MONOTONIC_PTS")
                    if file_hash(path) != sha:
                        raise InspectorError("SOURCE_CHANGED", "探测期间源视频发生改变，请重新读取", 409)
                    atomic_json(cache / "pts-v1.json", {"pts": pts, "pts_exact": exact, "video_sha256": sha})
                    atomic_json(probe_path, media)
                except (OSError, subprocess.SubprocessError, ValueError, KeyError, StopIteration) as exc:
                    raise InspectorError("PROBE_FAILED", "视频探测失败，计划证据仍可查看", 422) from exc
            atomic_json(cache / "locator.json", {"video_sha256": sha, "result_url": result_url, "task_id": task_id,
                                                 "novel_id": novel_id})
        return media

    def cache_dir(self, video_hash):
        safe_token(video_hash, r"[0-9a-f]{64}")
        matches = list(self.store.media_root.glob(f"story_*/inspector/cache/{video_hash}/locator.json"))
        if not matches:
            raise InspectorError("ARTIFACT_NOT_REGISTERED", "请先读取执行结果以核验媒体身份", 404)
        return self.store.controlled(sorted(matches)[0].parent)

    def frame_metadata(self, video_hash, native_index):
        cache = self.cache_dir(video_hash)
        media = read_json(cache / "probe-v1.json")
        if not 0 <= native_index < media["frame_count"]:
            raise InspectorError("OUT_OF_VIDEO", "帧索引超出视频范围", 422)
        return {"video_sha256": video_hash, "native_frame_index0": native_index,
                "native_pts": media["pts"][native_index], "native_pts_exact": media["pts_exact"][native_index],
                "stream_time_base": media["stream_time_base"], "render_version": RENDER_VERSION}

    def extract(self, video_hash, indices, preset="thumb", render_version=RENDER_VERSION):
        if render_version != RENDER_VERSION or preset not in PRESETS or not 1 <= len(indices) <= 48:
            raise InspectorError("INVALID_FRAME_REQUEST", "帧提取规格无效")
        cache = self.cache_dir(video_hash)
        indices = sorted(set(indices))
        for n in indices:
            self.frame_metadata(video_hash, n)
        directory = self.store.controlled(cache / "frames" / render_version / preset)
        paths = {n: directory / f"{n}.jpg" for n in indices}
        with _DECODE_LOCK:
            missing = [n for n in indices if not paths[n].is_file()]
            if not missing:
                return paths
            locator = read_json(cache / "locator.json")
            path = self.resolve_path(locator["result_url"])
            if file_hash(path) != video_hash:
                raise InspectorError("SOURCE_CHANGED", "源视频内容已改变，已有分析和缓存保留", 409)
            directory.mkdir(parents=True, exist_ok=True)
            select = "+".join(f"eq(n\\,{n})" for n in missing)
            with tempfile.TemporaryDirectory(prefix=".extract-", dir=directory) as tmp:
                try:
                    # showinfo independently records the actual decoded n and source PTS.
                    process = subprocess.run(["ffmpeg", "-v", "info", "-nostdin", "-threads", "1", "-i", str(path),
                                              "-map", "0:v:0", "-an", "-vf",
                                              f"showinfo,select={select},scale='min({PRESETS[preset]},iw)':-2",
                                              "-filter_threads", "1", "-fps_mode", "passthrough", "-frames:v", str(len(missing)),
                                              "-threads", "1", "-q:v", "2", f"{tmp}/%06d.jpg"],
                                             capture_output=True, text=True, check=True, timeout=60)
                    decoded = {int(n): float(pts) for n, pts in re.findall(r"\bn:\s*(\d+)\s+pts:\s*\S+\s+pts_time:([\d.eE+-]+)", process.stderr)}
                    if file_hash(path) != video_hash:
                        raise InspectorError("SOURCE_CHANGED", "抽帧期间源视频发生改变，请重新读取", 409)
                    records = []
                    for i, n in enumerate(missing, 1):
                        metadata = self.frame_metadata(video_hash, n)
                        if n not in decoded or abs(decoded[n] - metadata["native_pts"]) > 0.0001:
                            raise InspectorError("FRAME_PTS_MISMATCH", "抽取帧与源视频时间证据不一致", 422)
                        image = Path(tmp) / f"{i:06d}.jpg"
                        if not image.is_file() or image.stat().st_size == 0:
                            raise InspectorError("FRAME_EXTRACTION_FAILED", "抽帧输出不完整", 422)
                        records.append((image, n, {**metadata, "decoded_native_pts": decoded[n],
                                                 "selection": f"select n={n} from source beginning", "preset": preset,
                                                 "image_sha256": file_hash(image)}))
                    for image, n, metadata in records:
                        image.replace(paths[n])
                        atomic_json(paths[n].with_suffix(".json"), metadata)
                        self.extractions += 1
                except (OSError, subprocess.SubprocessError) as exc:
                    raise InspectorError("FRAME_EXTRACTION_FAILED", "此帧抽取失败，可重试", 422) from exc
        return paths

    def save_sampling(self, manifest):
        if manifest.get("video_sha256"):
            cache = self.cache_dir(manifest["video_sha256"])
            atomic_json(cache / "sampling" / f"{manifest['manifest_id']}.json", manifest)
