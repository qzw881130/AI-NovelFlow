"""Preview protagonist nameplates separately from raw Chapter, Shot and Clip videos."""

import asyncio
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import uuid
from pathlib import Path

from PIL import Image, ImageDraw

from app.models.novel import Chapter, Character
from app.models.shot import Shot
from app.services.llm_service import LLMService
from app.services.file_storage import file_storage
from app.services.vision_inputs import vision_proxy
from app.utils.image_utils import load_chinese_font
from app.utils.path_utils import url_to_local_path


NAMEPLATE_SECONDS = 2.8
RENDER_VERSION = 2
MIN_CONFIDENCE = 0.72


def _shot_character_names(shot: Shot) -> list[str]:
    try:
        items = json.loads(shot.characters or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(items, list):
        return []
    names = []
    for item in items:
        name = item if isinstance(item, str) else item.get("name") if isinstance(item, dict) else None
        if isinstance(name, str) and name.strip() and name.strip() not in names:
            names.append(name.strip())
    return names


def first_appearance_names_by_shot(db, novel_id: str) -> dict[str, list[str]]:
    """Find each manually selected protagonist's first candidate in story order."""
    protagonists = {name for name, narrator, selected in db.query(
        Character.name, Character.is_narrator, Character.is_protagonist,
    ).filter(Character.novel_id == novel_id).all() if selected and not narrator}
    shots = (db.query(Shot).join(Chapter, Shot.chapter_id == Chapter.id)
             .filter(Chapter.novel_id == novel_id)
             .order_by(Chapter.number, Chapter.id, Shot.index, Shot.id).all())
    seen: set[str] = set()
    result: dict[str, list[str]] = {}
    for shot in shots:
        names = [name for name in _shot_character_names(shot) if name in protagonists and name not in seen]
        seen.update(names)
        if names:
            result[shot.id] = names
    return result


def _probe_video(path: str | Path) -> tuple[int, int, float]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height:format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode:
        raise RuntimeError(f"无法读取视频参数：{result.stderr.strip()}")
    data = json.loads(result.stdout)
    stream = (data.get("streams") or [{}])[0]
    width, height = int(stream.get("width") or 0), int(stream.get("height") or 0)
    duration = float((data.get("format") or {}).get("duration") or 0)
    if width < 1 or height < 1 or not math.isfinite(duration) or duration <= 0:
        raise RuntimeError("视频尺寸或时长无效")
    return width, height, duration


def _extract_frame(video: Path, second: float, destination: Path) -> None:
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-y", "-ss", str(second),
         "-i", str(video), "-frames:v", "1", "-q:v", "3", str(destination)],
        capture_output=True, text=True, timeout=45,
    )
    if result.returncode or not destination.is_file():
        raise RuntimeError(f"无法抽取角色出镜帧：{result.stderr[-500:]}")


def _parse_detection(content: str, count: int) -> list[dict]:
    try:
        data = json.loads(content)
    except (TypeError, ValueError):
        return []
    frames = data.get("frames") if isinstance(data, dict) else None
    if not isinstance(frames, list):
        return []
    detections = []
    for item in frames:
        if not isinstance(item, dict) or item.get("visible") is not True:
            continue
        try:
            index, confidence = int(item["index"]), float(item["confidence"])
            box = [float(value) for value in item["bbox"]]
        except (KeyError, TypeError, ValueError):
            continue
        if len(box) != 4 or not all(math.isfinite(value) for value in box):
            continue
        if max(box) <= 1:
            box = [value * 1000 for value in box]
        x1, y1, x2, y2 = box
        if (not 1 <= index <= count or confidence < MIN_CONFIDENCE
                or not (0 <= x1 < x2 <= 1000 and 0 <= y1 < y2 <= 1000)
                or x2 - x1 < 35 or y2 - y1 < 80):
            continue
        detections.append({"index": index, "bbox": box, "confidence": confidence})
    return detections


def _position_hint(shot: Shot, name: str) -> str | None:
    description = shot.description or ""
    match = re.search(rf"(?:^|\n)\s*[-•]?\s*{re.escape(name)}\s*[：:]([^\n]+)", description)
    text = match.group(1) if match else ""
    # Direction of gaze is not the character's location. Inspect the
    # positioning clause before movement/gaze clauses.
    text = re.split(r"身体|视线|朝向|面向|保持|镜头", text, maxsplit=1)[0]
    if re.search(r"(?:画面|镜头)?左(?:侧|边|方)|位于左边", text):
        return "left"
    if re.search(r"(?:画面|镜头)?右(?:侧|边|方)|位于右边", text):
        return "right"
    if re.search(r"画面中央|画面中间|居中|正中央", text):
        return "center"
    return None


def _locate_protagonist_local(video: Path, shot: Shot, character: Character,
                               duration: float) -> list[dict]:
    """Use scene direction and local person detection when the LLM is unavailable.

    Only deterministic left/right/center assignments, or a sole-person Shot,
    are accepted. Ambiguous multi-person frames are left for vision matching.
    """
    import cv2

    expected = _shot_character_names(shot)
    hint = _position_hint(shot, character.name)
    if not hint and expected != [character.name]:
        return []
    hog = cv2.HOGDescriptor()
    hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        return []
    positions = []
    try:
        interval = max(0.65, duration / 18)
        times = [min(duration - 0.05, 0.25 + index * interval)
                 for index in range(max(1, math.ceil(duration / interval)))]
        for second in sorted(set(round(max(0, time), 3) for time in times)):
            if positions and second > positions[0]["time"] + NAMEPLATE_SECONDS:
                break
            cap.set(cv2.CAP_PROP_POS_MSEC, second * 1000)
            ok, frame = cap.read()
            if not ok:
                continue
            height, width = frame.shape[:2]
            boxes, weights = hog.detectMultiScale(
                frame, winStride=(8, 8), padding=(8, 8), scale=1.05)
            people = [(tuple(map(int, box)), float(weight))
                      for box, weight in zip(boxes, weights)
                      if float(weight) >= 0.3 and box[2] >= 40 and box[3] >= 90]
            if len(people) < len(expected) or not people:
                continue
            if len(people) > len(expected) and hint in {"left", "right"}:
                continue
            people.sort(key=lambda item: item[0][0] + item[0][2] / 2)
            if hint == "left":
                box, _ = people[0]
            elif hint == "right":
                box, _ = people[-1]
            elif hint == "center":
                box, _ = min(people, key=lambda item:
                             abs(item[0][0] + item[0][2] / 2 - width / 2))
            elif len(people) == 1:
                box, _ = people[0]
            else:
                continue
            x, y, w, h = box
            # HOG sometimes sees only the lower body. Extend the box upward
            # before placing the badge so it remains near the person's head.
            if y > height * 0.35 and h < height * 0.55:
                y = max(0, round(y - h * 0.8))
                h = min(height - y, round(h * 1.8))
            if positions:
                previous = positions[-1]
                previous_center = (previous["bbox"][0] + previous["bbox"][2]) / 2
                current_center = (x + w / 2) / width * 1000
                elapsed = max(0.1, second - previous["time"])
                if abs(current_center - previous_center) > 70 + 80 * elapsed:
                    continue
            positions.append({"time": second, "bbox": [
                max(0, x / width * 1000), max(0, y / height * 1000),
                min(1000, (x + w) / width * 1000), min(1000, (y + h) / height * 1000),
            ]})
    finally:
        cap.release()
    return positions


async def _locate_protagonist(video: Path, character: Character, duration: float) -> list[dict]:
    """Compare character reference with sampled frames; skip uncertain identity."""
    reference_path = url_to_local_path(character.image_url or "")
    if not reference_path or not Path(reference_path).is_file():
        return []
    interval = max(1.0, duration / 24)
    times = [min(duration - 0.05, 0.25 + index * interval)
             for index in range(max(1, math.ceil(duration / interval)))]
    times = sorted(set(round(max(0, value), 3) for value in times))
    reference = await asyncio.to_thread(vision_proxy, reference_path,
                                        logical_id="REFERENCE_CHARACTER", name=character.name)
    llm = LLMService()
    video_stat = video.stat()
    cache_key = hashlib.sha256(json.dumps({
        "version": RENDER_VERSION, "character_id": character.id,
        "reference_sha256": reference["source_sha256"], "video": str(video.resolve()),
        "video_size": video_stat.st_size, "video_mtime_ns": video_stat.st_mtime_ns,
        "provider": llm.provider, "model": llm.model,
    }, sort_keys=True).encode()).hexdigest()
    cache_dir = Path(file_storage.base_dir) / "_vision_proxy" / "nameplate_detection"
    cache_path = cache_dir / f"{cache_key}.json"
    if cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(cached, list) and cached:
                return cached
        except (OSError, ValueError):
            pass
    with tempfile.TemporaryDirectory(prefix="nameplate-frames-") as tmp:
        for start in range(0, len(times), 4):
            frame_times = times[start:start + 4]
            images = [reference]
            for index, second in enumerate(frame_times, 1):
                frame = Path(tmp) / f"frame-{start + index}.jpg"
                await asyncio.to_thread(_extract_frame, video, second, frame)
                images.append(await asyncio.to_thread(
                    vision_proxy, frame, logical_id=f"FRAME_{index}", name=f"视频帧 {index}"))
            response = await llm.chat_completion(
                system_prompt=(
                    "你是视频画面中的角色定位器。第1张图是角色参考形象（可能是四视图），后续是按时间顺序抽取的视频帧。"
                    "只有明确确认同一角色才标记 visible=true；不同角色或无法确认时标记 false。"
                    "对每帧返回人物可见身体的包围框，坐标范围0到1000。只输出 JSON："
                    '{"frames":[{"index":1,"visible":true,"confidence":0.9,"bbox":[x1,y1,x2,y2]}]}。'
                    "index 从1开始对应本次输入的视频帧。不要根据人物数量猜测身份。"
                ),
                user_content=f"定位角色《{character.name}》；参考图与每帧逐一比对。",
                response_format="json_object", task_type="first_appearance_nameplate", images=images,
            )
            if not response.get("success"):
                raise RuntimeError(response.get("error") or "角色定位模型调用失败")
            detections = _parse_detection(response.get("content") or "", len(frame_times))
            if detections:
                positions = [{"time": frame_times[item["index"] - 1], "bbox": item["bbox"]}
                             for item in sorted(detections, key=lambda entry: entry["index"])]
                cache_dir.mkdir(parents=True, exist_ok=True)
                temp_cache = cache_dir / f".{cache_key}-{uuid.uuid4().hex}.tmp"
                try:
                    temp_cache.write_text(json.dumps(positions), encoding="utf-8")
                    os.replace(temp_cache, cache_path)
                finally:
                    temp_cache.unlink(missing_ok=True)
                return positions
    return []


def _badge_size(name: str, width: int, height: int) -> tuple[int, int, int, int]:
    font_size = max(16, min(int(height * 0.05), int(width * 0.035)))
    padding = max(5, font_size // 4)
    return font_size + 2 * padding, len(name) * (font_size + 2) + 2 * padding, font_size, padding


def _badge_position(box: list[float], name: str, width: int, height: int,
                    output_size: tuple[int, int] | None = None) -> tuple[int, int]:
    output_width, output_height = output_size or (width, height)
    # Chapter merging scales each input to fit the first video's frame and
    # centers it with black padding. Apply the same transform to detections.
    scale = min(output_width / width, output_height / height)
    pad_x = (output_width - width * scale) / 2
    pad_y = (output_height - height * scale) / 2
    badge_width, badge_height, _, _ = _badge_size(name, output_width, output_height)
    x1, y1, x2, _ = box
    margin = max(8, int(output_width * 0.016))
    right = round(pad_x + x2 * width / 1000 * scale) + margin
    left = round(pad_x + x1 * width / 1000 * scale) - badge_width - margin
    x = right if right + badge_width <= output_width - margin else left
    x = max(margin, min(x, output_width - badge_width - margin))
    y = round(pad_y + y1 * height / 1000 * scale) - badge_height // 5
    y = max(margin, min(y, output_height - badge_height - margin))
    return x, y


async def build_nameplate_events(db, novel_id: str, chapter_id: str,
                                 segments: list[dict],
                                 output_size: tuple[int, int] | None = None) -> tuple[list[dict], list[str]]:
    first_by_shot = first_appearance_names_by_shot(db, novel_id)
    characters = {character.name: character for character in db.query(Character).filter(
        Character.novel_id == novel_id, Character.is_protagonist.is_(True),
        Character.is_narrator.is_(False)).all()}
    shots = {shot.index: shot for shot in db.query(Shot).filter(Shot.chapter_id == chapter_id).all()}
    events, warnings = [], []
    offset = 0.0
    for segment in segments:
        width, height, duration = await asyncio.to_thread(_probe_video, segment["path"])
        if segment["kind"] == "shot":
            shot = shots.get(int(segment["key"]))
            for name in first_by_shot.get(shot.id, []) if shot else []:
                character = characters.get(name)
                if not character:
                    continue
                try:
                    positions = await asyncio.to_thread(
                        _locate_protagonist_local, Path(segment["path"]), shot, character, duration)
                    if not positions:
                        positions = await _locate_protagonist(Path(segment["path"]), character, duration)
                except Exception as exc:
                    warnings.append(f"{name}：{exc}")
                    continue
                if not positions:
                    warnings.append(f"{name}：未能确认首次出镜位置，未添加姓名牌")
                    continue
                first = positions[0]["time"]
                end = min(duration, first + NAMEPLATE_SECONDS)
                track = [{"time": round(offset + point["time"], 3),
                          "xy": _badge_position(point["bbox"], name, width, height, output_size)}
                         for point in positions if point["time"] < end]
                if track and end - first >= 0.4:
                    events.append({"start": round(offset + first, 3), "end": round(offset + end, 3),
                                   "name": name, "character_id": character.id, "track": track})
        offset += duration
    return events, warnings


def _draw_badge(name: str, width: int, height: int, output: Path) -> None:
    badge_width, badge_height, font_size, padding = _badge_size(name, width, height)
    canvas = Image.new("RGBA", (badge_width, badge_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((0, 0, badge_width - 1, badge_height - 1), radius=padding,
                           fill=(210, 24, 31, 235))
    font = load_chinese_font(font_size)
    for line, character in enumerate(name):
        bounds = draw.textbbox((0, 0), character, font=font)
        draw.text(((badge_width - (bounds[2] - bounds[0])) / 2 - bounds[0],
                   padding + line * (font_size + 2) - bounds[1]),
                  character, font=font, fill="white")
    canvas.save(output)


def _coordinate_expr(track: list[dict], coordinate: int) -> str:
    expression = str(track[-1]["xy"][coordinate])
    for left, right in reversed(list(zip(track, track[1:]))):
        t0, t1 = left["time"], right["time"]
        start, finish = left["xy"][coordinate], right["xy"][coordinate]
        if t1 > t0:
            interpolated = f"{start}+({finish}-{start})*(t-{t0})/{round(t1-t0, 3)}"
            expression = f"if(lt(t,{t1}),{interpolated},{expression})"
    return f"if(lt(t,{track[0]['time']}),{track[0]['xy'][coordinate]},{expression})"


def _render(input_path: Path, output_path: Path, events: list[dict]) -> None:
    width, height, _ = _probe_video(input_path)
    assets = []
    try:
        for index, event in enumerate(events, 1):
            asset = output_path.with_name(f".{output_path.stem}-badge-{index}.png")
            _draw_badge(event["name"], width, height, asset)
            assets.append(asset)
        command = ["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(input_path)]
        for asset in assets:
            command.extend(["-loop", "1", "-i", str(asset)])
        filters = []
        previous = "[0:v]"
        for index, event in enumerate(events, 1):
            current = f"[named{index}]"
            x = _coordinate_expr(event["track"], 0)
            y = _coordinate_expr(event["track"], 1)
            enable = f"gte(t,{event['start']})*lt(t,{event['end']})"
            filters.append(f"{previous}[{index}:v]overlay=x='{x}':y='{y}':eval=frame:shortest=1:enable='{enable}'{current}")
            previous = current
        command.extend(["-filter_complex", ";".join(filters), "-map", previous, "-map", "0:a?",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
                        "-c:a", "copy", "-movflags", "+faststart", "-shortest", str(output_path)])
        result = subprocess.run(command, capture_output=True, text=True, timeout=600)
        if result.returncode or not output_path.is_file() or output_path.stat().st_size == 0:
            raise RuntimeError(f"角色姓名牌预览合成失败：{result.stderr[-1200:]}")
    finally:
        for asset in assets:
            asset.unlink(missing_ok=True)


async def render_first_appearance_nameplates(input_path: Path, output_path: Path, events: list[dict]) -> None:
    await asyncio.to_thread(_render, input_path, output_path, events)
