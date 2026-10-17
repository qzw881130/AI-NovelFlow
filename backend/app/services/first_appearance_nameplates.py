"""Render first-appearance character nameplates on a finished chapter video.

Raw Shot and Clip files stay untouched so they remain valid generation inputs.
"""

import asyncio
import json
import math
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

from app.models.novel import Chapter, Character
from app.models.shot import Shot
from app.utils.image_utils import load_chinese_font


NAMEPLATE_SECONDS = 2.8
RENDER_VERSION = 1


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
    """Use story order, not task completion order, to identify first appearances."""
    character_rows = db.query(Character.name, Character.is_narrator).filter(Character.novel_id == novel_id).all()
    narrators = {name for name, is_narrator in character_rows if is_narrator}
    rows = (
        db.query(Shot)
        .join(Chapter, Shot.chapter_id == Chapter.id)
        .filter(Chapter.novel_id == novel_id)
        .order_by(Chapter.number, Chapter.id, Shot.index, Shot.id)
        .all()
    )
    seen: set[str] = set()
    result: dict[str, list[str]] = {}
    for shot in rows:
        shot_names = _shot_character_names(shot)
        names = [name for name in shot_names if name not in narrators and name not in seen]
        seen.update(shot_names)
        if names:
            result[shot.id] = names
    return result


def _probe_video(path: str | Path) -> tuple[int, int, float]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height:format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(f"无法读取视频参数：{result.stderr.strip()}")
    data = json.loads(result.stdout)
    stream = (data.get("streams") or [{}])[0]
    width, height = int(stream.get("width") or 0), int(stream.get("height") or 0)
    duration = float((data.get("format") or {}).get("duration") or 0)
    if width < 1 or height < 1 or not math.isfinite(duration) or duration <= 0:
        raise RuntimeError("视频尺寸或时长无效")
    return width, height, duration


def build_nameplate_events(db, novel_id: str, chapter_id: str, segments: list[dict]) -> list[dict]:
    """Map first appearances to timestamps in the exact chapter merge order."""
    first_by_shot = first_appearance_names_by_shot(db, novel_id)
    current_shots = {
        shot.index: shot for shot in db.query(Shot).filter(Shot.chapter_id == chapter_id).all()
    }
    events = []
    offset = 0.0
    for segment in segments:
        _, _, duration = _probe_video(segment["path"])
        if segment["kind"] == "shot":
            shot = current_shots.get(int(segment["key"]))
            names = first_by_shot.get(shot.id, []) if shot else []
            if names:
                events.append({
                    "start": round(offset, 3),
                    "end": round(offset + min(NAMEPLATE_SECONDS, duration), 3),
                    "names": names,
                })
        offset += duration
    return events


def _draw_nameplates(names: list[str], width: int, height: int, output: Path) -> None:
    columns = min(len(names), 6)
    rows = math.ceil(len(names) / columns)
    longest = max(len(name) for name in names)
    font_size = max(17, min(int(height * 0.044), int(width / (columns * 2.3)), int(height * 0.45 / (longest + 1))))
    font = load_chinese_font(font_size)
    padding = max(6, font_size // 4)
    cell_width = font_size + padding * 2
    cell_height = (longest * (font_size + 2)) + padding * 2
    gap = max(8, font_size // 3)
    canvas = Image.new("RGBA", (columns * (cell_width + gap), rows * (cell_height + gap)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    for index, name in enumerate(names):
        x = (index % columns) * (cell_width + gap)
        y = (index // columns) * (cell_height + gap)
        badge_height = len(name) * (font_size + 2) + padding * 2
        draw.rounded_rectangle((x, y, x + cell_width - 1, y + badge_height - 1), radius=padding,
                               fill=(210, 24, 31, 235))
        for line, character in enumerate(name):
            bbox = draw.textbbox((0, 0), character, font=font)
            character_width = bbox[2] - bbox[0]
            draw.text((x + (cell_width - character_width) / 2 - bbox[0],
                       y + padding + line * (font_size + 2) - bbox[1]),
                      character, font=font, fill="white")
    canvas.save(output)


def _render(input_path: Path, output_path: Path, events: list[dict]) -> None:
    width, height, _ = _probe_video(input_path)
    asset_paths = []
    try:
        for index, event in enumerate(events, 1):
            asset = output_path.with_name(f".{output_path.stem}-badge-{index}.png")
            _draw_nameplates(event["names"], width, height, asset)
            asset_paths.append(asset)
        command = ["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(input_path)]
        for asset in asset_paths:
            command.extend(["-loop", "1", "-i", str(asset)])
        filters = []
        previous = "[0:v]"
        for index, event in enumerate(events, 1):
            current = f"[named{index}]"
            x, y = max(8, int(width * 0.04)), max(8, int(height * 0.08))
            enable = f"gte(t,{event['start']})*lt(t,{event['end']})"
            filters.append(f"{previous}[{index}:v]overlay={x}:{y}:shortest=1:enable='{enable}'{current}")
            previous = current
        command.extend([
            "-filter_complex", ";".join(filters), "-map", previous, "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "copy", "-movflags", "+faststart", "-shortest", str(output_path),
        ])
        result = subprocess.run(command, capture_output=True, text=True, timeout=600)
        if result.returncode != 0 or not output_path.is_file() or output_path.stat().st_size == 0:
            raise RuntimeError(f"角色姓名牌合成失败：{result.stderr[-1200:]}")
    finally:
        for asset in asset_paths:
            asset.unlink(missing_ok=True)


async def render_first_appearance_nameplates(input_path: Path, output_path: Path, events: list[dict]) -> None:
    """Encode a separate presentation file while preserving the raw merged video."""
    await asyncio.to_thread(_render, input_path, output_path, events)
