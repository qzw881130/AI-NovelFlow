"""Chapter subtitles: final-audio ASR, editable cue timeline, SRT and burned MP4."""

import ast
import asyncio
import json
import math
import re
import subprocess
import tempfile
import textwrap
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from app.repositories import WorkflowRepository
from app.services.comfyui.client import ComfyUIClient
from app.services.comfyui.workflows import WorkflowBuilder
from app.services.file_storage import file_storage
from app.services.prompt_template_service import PromptTemplateService
from app.services.workflow_service import WorkflowService
from app.services.llm_service import LLMService
from app.utils.json_parser import safe_parse_llm_json


def _run_media(args: list[str], timeout: int = 1800) -> None:
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError((result.stderr or "FFmpeg 处理失败")[-2000:])


def _duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, timeout=45, check=True,
    )
    value = float(result.stdout.strip())
    if not math.isfinite(value) or value <= 0:
        raise ValueError("媒体时长无效")
    return value


def _lines(value: str) -> list[str]:
    value = str(value or "").strip()
    try:
        parsed = ast.literal_eval(value)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    except (SyntaxError, ValueError):
        pass
    return [line.strip() for line in value.replace("\r", "").split("\n") if line.strip()]


def _aligned_cues(
    outputs: dict, mapping: dict, offset: float, max_end: float,
    *, chunk_duration: float | None = None, diagnostics: dict | None = None,
) -> list[dict]:
    texts = _lines(outputs.get(str(mapping["text_list_output_node_id"]), ""))
    starts = _lines(outputs.get(str(mapping["start_times_output_node_id"]), ""))
    ends = _lines(outputs.get(str(mapping["end_times_output_node_id"]), ""))
    if not (texts and starts and ends) and mapping.get("timestamps_output_node_id"):
        texts, starts, ends = [], [], []
        for line in _lines(outputs.get(str(mapping["timestamps_output_node_id"]), "")):
            parts = line.rsplit("\t", 2)
            if len(parts) == 3:
                texts.append(parts[0])
                starts.append(parts[1])
                ends.append(parts[2])
    if not (len(texts) == len(starts) == len(ends)):
        raise ValueError("字幕工作流返回的文本和时间数量不一致")
    cues = []
    for index, (content, raw_start, raw_end) in enumerate(zip(texts, starts, ends), 1):
        try:
            local_start, local_end = float(raw_start), float(raw_end)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"字幕工作流第 {index} 条时间不是数字") from exc
        if not (math.isfinite(local_start) and math.isfinite(local_end)
                and 0 <= local_start and 0 <= local_end and local_end >= local_start):
            raise ValueError(f"字幕工作流第 {index} 条时间无效：{raw_start} → {raw_end}")
        if chunk_duration is not None:
            if local_start > chunk_duration + 0.3 or local_end > chunk_duration + 0.3:
                raise ValueError(f"字幕工作流第 {index} 条超出音频分片：{raw_start} → {raw_end}")
            local_end = min(local_end, chunk_duration)
        start, end = offset + local_start, min(offset + local_end, max_end)
        # The aligner may emit a zero-length token exactly at a 60s split.
        # Its audio belongs to the next chunk, so never invent a timestamp.
        if end <= start:
            if (chunk_duration is None or local_start <= chunk_duration + 0.3) and start <= max_end + 0.3:
                if diagnostics is not None:
                    diagnostics["skipped_cue_count"] = diagnostics.get("skipped_cue_count", 0) + 1
                continue
            raise ValueError(f"字幕工作流第 {index} 条时间超出成片范围")
        if not (0 <= start < end <= max_end):
            raise ValueError(f"字幕工作流第 {index} 条时间超出成片范围")
        if content:
            cues.append({"start": round(start, 3), "end": round(end, 3), "text": content})
    return cues


def validate_cues(raw: object, duration: float) -> list[dict]:
    if not isinstance(raw, list) or len(raw) > 100000:
        raise ValueError("字幕必须是最多 100000 条的列表")
    cues = []
    previous_start = -1.0
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("字幕条目格式无效")
        start, end, content = item.get("start"), item.get("end"), item.get("text")
        if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            raise ValueError("字幕时间必须为数字")
        if not all(map(math.isfinite, (start, end))) or not 0 <= start < end <= duration + 0.05 or start < previous_start:
            raise ValueError("字幕时间必须有序且落在成片范围内")
        if not isinstance(content, str) or not content.strip() or len(content) > 400:
            raise ValueError("字幕文本不能为空且不能超过 400 字")
        if any(char in content for char in ("\x00", "\r")):
            raise ValueError("字幕含无效字符")
        cue = {"start": round(float(start), 3), "end": round(float(end), 3), "text": content.strip()}
        if "en_text" in item:
            english = item["en_text"]
            if not isinstance(english, str) or len(english) > 400 or any(char in english for char in ("\x00", "\r")):
                raise ValueError("英文字幕格式无效或超过 400 字")
            cue["en_text"] = english.strip()
        cues.append(cue)
        previous_start = start
    return cues


def _srt_time(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    whole, milli = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole:02d},{milli:03d}"


def write_srt(cues: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n\n".join(
        f"{index}\n{_srt_time(cue['start'])} --> {_srt_time(cue['end'])}\n{cue['text']}"
        for index, cue in enumerate(cues, 1)
    ) + "\n"
    temp = path.with_suffix(".srt.tmp")
    temp.write_text(content, encoding="utf-8")
    temp.replace(path)


def english_cues(cues: list[dict]) -> list[dict]:
    if any(not cue.get("en_text") for cue in cues):
        raise ValueError("双语字幕缺少英文台词")
    return [{"start": cue["start"], "end": cue["end"], "text": cue["en_text"]} for cue in cues]


def write_cues(cues: list[dict], path: Path) -> None:
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(cues, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temp.replace(path)


def read_cues(subtitle: dict) -> list[dict]:
    from app.utils.path_utils import url_to_local_path
    if subtitle.get("cues_url"):
        path = url_to_local_path(subtitle["cues_url"])
        if not path:
            raise FileNotFoundError("字幕时间轴文件不存在")
        cues = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(cues, list):
            raise ValueError("字幕时间轴格式无效")
        return cues
    return subtitle.get("cues") or []


def _ass_time(seconds: float) -> str:
    centiseconds = round(seconds * 100)
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    whole, centi = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{whole:02d}.{centi:02d}"


def burn_subtitles(source: Path, cues: list[dict], output_dir: Path) -> Path:
    """Burn the same validated cues used for the SRT into a separate MP4."""
    bilingual = any(cue.get("en_text") for cue in cues)
    if bilingual and any(not cue.get("en_text") for cue in cues):
        raise ValueError("双语字幕缺少英文台词")
    digest = sha256(("ass-v3-58-38:" + json.dumps(cues, ensure_ascii=False, sort_keys=True)).encode()).hexdigest()[:16]
    target = output_dir / f"{source.stem}-sub-{digest}.mp4"
    if target.is_file() and target.stat().st_size:
        return target
    with tempfile.TemporaryDirectory(prefix="novelflow-sub-") as temporary:
        ass_path = Path(temporary) / "subtitles.ass"
        lines = [
            "[Script Info]", "ScriptType: v4.00+", "PlayResX: 1920", "PlayResY: 1080", "WrapStyle: 2",
            "[V4+ Styles]", "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            "Style: Default,Noto Sans CJK SC,55,&H00FFFFFF,&H00FFFFFF,&H90000000,&H90000000,0,0,0,0,100,100,0,0,1,3,1,2,90,90,48,1",
            "Style: Bilingual,Noto Sans CJK SC,58,&H00FFFFFF,&H00FFFFFF,&H90000000,&H90000000,0,0,0,0,100,100,0,0,1,3,1,2,90,90,52,1",
            "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]
        for cue in cues:
            chinese = re.sub(r"[{}]", "", cue["text"]).replace("\\", "\\\\")
            chinese_lines = [part for line in chinese.splitlines() for part in textwrap.wrap(line, 27, break_long_words=True)]
            content = r"\N".join(chinese_lines)
            style = "Default"
            if bilingual:
                english = re.sub(r"[{}]", "", cue["en_text"]).replace("\\", "\\\\")
                english_lines = [part for line in english.splitlines() for part in textwrap.wrap(line, 56, break_long_words=True)]
                content += r"\N{\fs38}" + r"\N".join(english_lines)
                style = "Bilingual"
            lines.append(f"Dialogue: 0,{_ass_time(cue['start'])},{_ass_time(cue['end'])},{style},,0,0,0,,{content}")
        ass_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        temp_output = output_dir / f".{target.stem}.tmp.mp4"
        try:
            filter_path = str(ass_path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
            _run_media(["ffmpeg", "-y", "-i", str(source), "-vf", f"ass='{filter_path}'",
                        "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "medium",
                        "-crf", "18", "-c:a", "copy", "-movflags", "+faststart", str(temp_output)])
            temp_output.replace(target)
        finally:
            temp_output.unlink(missing_ok=True)
    return target


def file_url(path: Path) -> str:
    return f"/api/files/{path.relative_to(file_storage.base_dir).as_posix()}"


def _reference_for_cues(cues: list[dict], references: list[dict]) -> list[dict]:
    """Keep each LLM batch near the matching chapter, without changing cue timing."""
    start, end = cues[0]["start"], cues[-1]["end"]
    selected = [item for item in references if item["start"] < end + 1 and item["end"] > start - 1]
    if not selected:
        selected = sorted(references, key=lambda item: abs((item["start"] + item["end"]) / 2 - start))[:1]
    result = []
    remaining = 18000
    for item in selected:
        if remaining <= 0:
            break
        content = str(item.get("text") or "").strip()
        if not content:
            continue
        if len(content) > 8000:
            midpoint = (start + end) / 2
            fraction = (midpoint - item["start"]) / max(item["end"] - item["start"], 0.001)
            center = round(max(0, min(1, fraction)) * len(content))
            begin = max(0, min(len(content) - 8000, center - 4000))
            content = content[begin:begin + 8000]
        content = content[:remaining]
        remaining -= len(content)
        result.append({"chapter": item.get("label") or "", "text": content})
    return result


async def correct_cue_text(db, cues: list[dict], references: list[dict],
                           novel_id: str, chapter_id: str) -> list[dict]:
    """Only accept indexed text replacements; the original cue times stay server-owned."""
    template = PromptTemplateService(db).get_default_system_template("subtitle_correction")
    if not template or not template.template:
        raise ValueError("请先在提示词管理中配置字幕文本校对提示词")
    if not references:
        raise ValueError("没有可供校正的小说正文或台词参考")
    corrected = [dict(cue) for cue in cues]
    llm = LLMService()
    for begin in range(0, len(cues), 40):
        group = cues[begin:begin + 40]
        reference = _reference_for_cues(group, references)
        if not reference:
            raise ValueError("当前字幕段没有可供校正的正文参考")
        response = await llm.chat_completion(
            system_prompt=template.template,
            user_content=json.dumps({"dialogues": reference, "cues": [
                {"index": begin + i + 1, "text": cue["text"]} for i, cue in enumerate(group)
            ]}, ensure_ascii=False),
            response_format="json_object", task_type="subtitle_correction",
            prompt_template_name=template.name, novel_id=novel_id, chapter_id=chapter_id,
        )
        if not response.get("success"):
            raise RuntimeError(response.get("error") or "字幕自动校正请求失败")
        rows = safe_parse_llm_json(response.get("content") or "").get("segments")
        if not isinstance(rows, list) or len(rows) != len(group):
            raise ValueError(f"字幕自动校正第 {begin // 40 + 1} 批返回的段数不一致")
        for i, row in enumerate(rows):
            index = begin + i + 1
            if (not isinstance(row, dict) or type(row.get("index")) is not int
                    or row["index"] != index or not isinstance(row.get("text"), str)
                    or not row["text"].strip() or set(row) != {"index", "text"}):
                raise ValueError(f"字幕自动校正第 {index} 条格式无效，时间轴未修改")
            corrected[begin + i]["text"] = row["text"].strip()
    # Validate the proposed text, then return the untouched input times rather
    # than validate_cues' millisecond-rounded copy.
    validate_cues(corrected, max(cue["end"] for cue in cues) + 0.05)
    return corrected


async def translate_cues(db, cues: list[dict], novel_id: str, chapter_id: str) -> list[dict]:
    """Translate only missing English text. Cue boundaries never enter the LLM request."""
    template = PromptTemplateService(db).get_default_system_template("subtitle_translation")
    if not template or not template.template:
        raise ValueError("请先在提示词管理中配置字幕英文翻译提示词")
    translated = [dict(cue) for cue in cues]
    missing = [(index, cue) for index, cue in enumerate(translated) if not cue.get("en_text")]
    llm = LLMService()
    for begin in range(0, len(missing), 30):
        group = missing[begin:begin + 30]
        response = await llm.chat_completion(
            system_prompt=template.template,
            user_content=json.dumps({"segments": [
                {"index": index + 1, "text": cue["text"]} for index, cue in group
            ]}, ensure_ascii=False),
            response_format="json_object", task_type="subtitle_translation",
            prompt_template_name=template.name, novel_id=novel_id, chapter_id=chapter_id,
        )
        if not response.get("success"):
            raise RuntimeError(response.get("error") or "字幕英文翻译失败")
        parsed = safe_parse_llm_json(response.get("content") or "")
        rows = parsed.get("segments") if isinstance(parsed, dict) else None
        if not isinstance(rows, list) or len(rows) != len(group):
            raise ValueError("字幕英文翻译返回的条数不一致")
        for (index, _), row in zip(group, rows):
            if (not isinstance(row, dict) or set(row) != {"index", "text"}
                    or type(row["index"]) is not int or row["index"] != index + 1
                    or not isinstance(row["text"], str) or not row["text"].strip()):
                raise ValueError(f"字幕英文翻译第 {index + 1} 条格式无效")
            translated[index]["en_text"] = row["text"].strip()
    validate_cues(translated, max(cue["end"] for cue in cues) + 0.05)
    return translated


async def _correct_text(db, cues: list[dict], dialogues: list, novel_id: str, chapter_id: str,
                        references: list[dict] | None = None) -> tuple[list[dict], str]:
    if references is None:
        references = ([{"start": 0, "end": max(cue["end"] for cue in cues),
                        "label": "分镜台词", "text": json.dumps(dialogues, ensure_ascii=False)}]
                      if dialogues else [])
    if not references:
        return cues, "skipped"
    try:
        return await correct_cue_text(db, cues, references, novel_id, chapter_id), "applied"
    except Exception:
        return cues, "failed"


async def _task_references(db, task, metadata: dict, duration: float) -> list[dict]:
    from app.models.novel import Chapter
    from app.utils.path_utils import url_to_local_path

    snapshots = metadata.get("chapters") if task.type == "novel_video" else None
    if not isinstance(snapshots, list) or not snapshots:
        chapter = db.query(Chapter).filter(Chapter.id == task.chapter_id,
                                           Chapter.novel_id == task.novel_id).first()
        return ([{"start": 0, "end": duration, "label": f"第 {chapter.number} 章",
                  "text": chapter.content}] if chapter and (chapter.content or "").strip() else [])
    ids = [item.get("id") for item in snapshots if isinstance(item, dict) and item.get("id")]
    chapters = {item.id: item for item in db.query(Chapter).filter(
        Chapter.novel_id == task.novel_id, Chapter.id.in_(ids)).all()}
    def probe_lengths() -> list[float]:
        lengths = []
        for snapshot in snapshots:
            path = url_to_local_path(snapshot.get("videoUrl") or "") if isinstance(snapshot, dict) else None
            try:
                lengths.append(_duration(Path(path)) if path and Path(path).is_file() else 0)
            except (OSError, ValueError, subprocess.SubprocessError):
                lengths.append(0)
        return lengths

    lengths = await asyncio.to_thread(probe_lengths)
    fallback = duration / len(snapshots)
    lengths = [value or fallback for value in lengths]
    scale = duration / sum(lengths)
    offset = 0.0
    references = []
    for snapshot, length in zip(snapshots, lengths):
        span = length * scale
        chapter = chapters.get(snapshot.get("id")) if isinstance(snapshot, dict) else None
        if chapter and (chapter.content or "").strip():
            references.append({"start": offset, "end": offset + span,
                               "label": f"第 {chapter.number} 章《{chapter.title}》", "text": chapter.content})
        offset += span
    return references


async def preview_subtitle_correction(db, task, raw_cues: list[dict]) -> dict:
    from app.utils.path_utils import url_to_local_path

    metadata = json.loads(task.metadata_json or "{}")
    subtitle = metadata.get("subtitle")
    if not isinstance(subtitle, dict) or not subtitle.get("source_url"):
        raise FileNotFoundError("该任务没有可校正的字幕")
    source = url_to_local_path(subtitle["source_url"])
    if not source or not Path(source).is_file():
        raise FileNotFoundError("字幕对应的原视频不存在")
    duration = await asyncio.to_thread(_duration, Path(source))
    validated = validate_cues(raw_cues, duration)
    cues = [{**cue, "start": original["start"], "end": original["end"]}
            for cue, original in zip(validated, raw_cues)]
    if not cues:
        raise ValueError("字幕不能为空")
    references = await _task_references(db, task, metadata, duration)
    corrected = await correct_cue_text(db, cues, references, task.novel_id, task.chapter_id or "")
    return {"cues": corrected, "changed_count": sum(a["text"] != b["text"] for a, b in zip(cues, corrected))}


async def generate_subtitles(db, video_path: Path, output_dir: Path, *, novel_id: str,
                             chapter_id: str, task_id: str, dialogues: list, progress=None,
                             subtitle_mode: str = "zh", references: list[dict] | None = None) -> dict:
    """Recognize the final mixed audio so transition and normalization timing is exact."""
    WorkflowService(db).load_default_workflows()
    workflow = WorkflowRepository(db).get_active_by_type("subtitle_asr")
    if not workflow:
        raise ValueError("请先在 ComfyUI 工作流管理中启用字幕语音识别工作流")
    graph = WorkflowBuilder().convert_ui_to_api(json.loads(workflow.workflow_json))
    mapping = json.loads(workflow.node_mapping or "{}")
    required = ("load_audio_node_id", "text_list_output_node_id", "start_times_output_node_id", "end_times_output_node_id")
    if any(not mapping.get(key) for key in required):
        raise ValueError("字幕工作流的音频输入和文本/时间输出节点映射不完整")
    input_node = graph.get(str(mapping["load_audio_node_id"]))
    if not input_node or input_node.get("class_type") != "LoadAudio":
        raise ValueError("字幕工作流音频输入必须映射 LoadAudio 节点")
    output_keys = list(required[1:])
    if mapping.get("timestamps_output_node_id"):
        output_keys.append("timestamps_output_node_id")
    for key in output_keys:
        node = graph.get(str(mapping[key]))
        if not node or not str(node.get("class_type") or "").startswith("ShowText"):
            raise ValueError(f"字幕工作流的 {key} 必须映射 ShowText 输出节点")
    if len({str(mapping[key]) for key in [required[0], *output_keys]}) != 1 + len(output_keys):
        raise ValueError("字幕工作流输入和输出节点映射不能重复")
    total_duration = await asyncio.to_thread(_duration, video_path)
    client = ComfyUIClient.for_product_runtime(db)
    cues = []
    alignment_diagnostics: dict[str, int] = {}
    with tempfile.TemporaryDirectory(prefix="novelflow-asr-") as temporary:
        pattern = Path(temporary) / f"chunk_{uuid4().hex}_%04d.wav"
        await asyncio.to_thread(_run_media, [
            "ffmpeg", "-y", "-i", str(video_path), "-vn", "-ac", "1", "-ar", "16000",
            "-c:a", "pcm_s16le", "-f", "segment", "-segment_time", "60", str(pattern),
        ])
        chunks = sorted(Path(temporary).glob("chunk_*.wav"))
        if not chunks:
            raise ValueError("视频没有可识别的音轨")
        offset = 0.0
        for number, chunk in enumerate(chunks, 1):
            chunk_duration = await asyncio.to_thread(_duration, chunk)
            if chunk_duration < 0.5:
                offset += chunk_duration
                continue
            if progress:
                progress(87 + round(7 * (number - 1) / len(chunks)), f"字幕识别 {number}/{len(chunks)}")
            # The source video never leaves this machine. Lossless FLAC makes
            # each uploaded speech chunk smaller than its temporary PCM WAV.
            compressed = chunk.with_suffix(".flac")
            await asyncio.to_thread(_run_media, [
                "ffmpeg", "-y", "-i", str(chunk), "-c:a", "flac", str(compressed),
            ])
            upload = await client.upload_audio(str(compressed))
            compressed.unlink(missing_ok=True)
            chunk.unlink(missing_ok=True)
            if not upload.get("success"):
                raise RuntimeError(upload.get("message") or "字幕音频上传失败")
            current = json.loads(json.dumps(graph))
            current[str(mapping["load_audio_node_id"])]["inputs"]["audio"] = upload["filename"]
            if "audioUI" in current[str(mapping["load_audio_node_id"])]["inputs"]:
                current[str(mapping["load_audio_node_id"])]["inputs"]["audioUI"] = f"/api/view?filename={upload['filename']}&type=input&subfolder="
            queued = await client.queue_prompt(current)
            if not queued.get("success"):
                raise RuntimeError(queued.get("message") or "字幕工作流提交失败")
            result = await client.wait_for_text_outputs(
                queued["prompt_id"], [str(mapping[key]) for key in output_keys],
                timeout=1800, allow_empty=True,
            )
            if not result.get("success"):
                raise RuntimeError(result.get("message") or "字幕工作流执行失败")
            cues.extend(_aligned_cues(
                result["outputs"], mapping, offset, total_duration,
                chunk_duration=chunk_duration, diagnostics=alignment_diagnostics,
            ))
            offset += chunk_duration
    cues = validate_cues(cues, total_duration)
    if not cues:
        raise ValueError("音轨中未识别到可生成的字幕")
    if progress:
        progress(95, "正在校对字幕文本...")
    cues, correction = await _correct_text(db, cues, dialogues, novel_id, chapter_id, references)
    if subtitle_mode == "bilingual":
        if progress:
            progress(96, "正在翻译英文字幕...")
        cues = await translate_cues(db, cues, novel_id, chapter_id)
    srt_path = output_dir / f"{video_path.stem}-subtitles-{task_id}.srt"
    cues_path = output_dir / f"{video_path.stem}-subtitles-{task_id}.json"
    await asyncio.to_thread(write_srt, cues, srt_path)
    en_srt_url = None
    if subtitle_mode == "bilingual":
        en_srt_path = output_dir / f"{video_path.stem}-subtitles-{task_id}-en.srt"
        await asyncio.to_thread(write_srt, english_cues(cues), en_srt_path)
        en_srt_url = file_url(en_srt_path)
    await asyncio.to_thread(write_cues, cues, cues_path)
    return {"cues": cues, "cues_url": file_url(cues_path), "count": len(cues),
            "srt_url": file_url(srt_path), "en_srt_url": en_srt_url,
            "mode": subtitle_mode, "workflow_id": workflow.id,
            "correction": correction, "source_url": file_url(video_path),
            "skipped_cue_count": alignment_diagnostics.get("skipped_cue_count", 0)}
