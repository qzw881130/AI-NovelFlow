"""Export only the immutable snapshot bound to the selected rendered chapter."""

import html
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

from app.models.novel import Chapter
from app.services.rendered_subtitles import load
from app.utils.path_utils import url_to_local_path


class SubtitleNotReady(ValueError):
    pass


def timestamp(value: Decimal, format: str) -> str:
    scale = 1000 if format == "srt" else 100
    ticks = int((value * scale).to_integral_value(rounding=ROUND_HALF_UP))
    seconds, fraction = divmod(ticks, scale)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if format == "srt":
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{fraction:03d}"
    return f"{hours}:{minutes:02d}:{seconds:02d}.{fraction:02d}"


def subtitle_text(text: str, format: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(c for c in text if c in "\n\t" or ord(c) >= 32)
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if format == "srt":
        return html.escape(text, quote=False)
    return text.translate(str.maketrans({"\\": "\uff3c", "{": "\uff5b", "}": "\uff5d"})).replace("\n", r"\N")


def chapter_subtitles(db, chapter_id: str, format: str) -> str:
    if format not in {"srt", "ass"}:
        raise ValueError("Unsupported subtitle format")
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    path = url_to_local_path(chapter.final_video) if chapter and chapter.final_video else None
    snapshot = load(path) if path else None
    if not snapshot or snapshot["lineage"].get("kind") != "merge":
        raise SubtitleNotReady("当前章节成片缺少可验证的渲染字幕快照，或媒体文件已改变。请重新生成 TTS、Clip Audio 和分镜视频，再合并章节；旧视频仍可合并，但不能使用当前配音推测旧视频字幕。")
    return render_subtitles(snapshot["cues"], format)


def render_subtitles(cues, format):
    lines = []
    if format == "ass":
        lines.extend([
            "[Script Info]", "ScriptType: v4.00+", "PlayResX: 1920", "PlayResY: 1080", "WrapStyle: 0", "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            "Style: Default,Arial,48,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,1,2,60,60,50,1", "",
            "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ])
    index = 0
    for cue in cues:
        text = subtitle_text(cue["text"], format)
        if not text:
            continue
        index += 1
        times = [Fraction(cue[key]) for key in ("start", "end")]
        start_text, end_text = [timestamp(Decimal(t.numerator) / Decimal(t.denominator), format) for t in times]
        if start_text == end_text:
            raise SubtitleNotReady(f"Cue {index} is too short for {format.upper()} precision.")
        if format == "srt":
            lines.extend([str(index), f"{start_text} --> {end_text}", text, ""])
        else:
            lines.append(f"Dialogue: 0,{start_text},{end_text},Default,,0,0,0,,{text}")
    return "\n".join(lines) + ("\n" if lines else "")
