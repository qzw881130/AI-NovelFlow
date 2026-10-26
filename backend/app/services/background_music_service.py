"""Chapter background-music planning, rendering and preview assembly."""
import asyncio
import json
import math
import os
import subprocess
import uuid
from datetime import datetime
from pathlib import Path

import httpx

from app.core.database import SessionLocal
from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.task import Task
from app.repositories.workflow import WorkflowRepository
from app.services.background_workers import persistent_job, worker_manager
from app.services.comfyui.client import ComfyUIClient
from app.services.file_storage import file_storage
from app.services.llm_service import LLMService
from app.services.prompt_template_service import PromptTemplateService
from app.services.workflow_service import WorkflowService
from app.utils.json_parser import safe_parse_llm_json
from app.utils.path_utils import local_path_to_url, url_to_local_path
from app.utils.time_utils import format_datetime


TASK_TYPE = "chapter_background_music"
QUEUE_NAME = "background_music"
PARTIAL_MUSIC = "partial"
FULL_CHAPTER_MUSIC = "full"
ACE_STEP_1_5_KEYS = {
    f"{note} {mode}"
    for note in ("C", "C#", "Db", "D", "D#", "Eb", "E", "F", "F#", "Gb",
                 "G", "G#", "Ab", "A", "A#", "Bb", "B")
    for mode in ("major", "minor")
}


def _metadata(task: Task) -> dict:
    try:
        value = json.loads(task.metadata_json or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def format_background_music_prompt(metadata: dict) -> str | None:
    """Show the music director's plan and the actual ComfyUI text for each cue."""
    cues = metadata.get("cues")
    if not isinstance(cues, list) or not cues:
        return None
    parts = []
    for cue in cues:
        if not isinstance(cue, dict):
            continue
        lines = [f"配乐片段 {cue.get('index', len(parts) + 1)} · Shot {cue.get('startShot', '?')}–{cue.get('endShot', '?')}"]
        for label, key in (("导演风格", "style"), ("旋律", "melody"), ("声音优先", "soundPriority"),
                           ("生成标签 tags", "generationStyle"), ("纯器乐标记 lyrics", "lyrics"),
                           ("速度 BPM", "bpm"), ("调式", "keyscale"), ("拍号", "timesignature")):
            if cue.get(key):
                lines.append(f"{label}: {cue[key]}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts) or None


def format_background_music(task: Task, chapter: Chapter | None = None) -> dict:
    metadata = _metadata(task)
    source_video_url = metadata.get("source_video_url")
    stale = bool(chapter and source_video_url and chapter.final_video != source_video_url)
    return {
        "id": task.id, "chapterId": task.chapter_id, "status": task.status,
        "mode": metadata.get("music_mode") if metadata.get("music_mode") == FULL_CHAPTER_MUSIC else PARTIAL_MUSIC,
        "progress": task.progress or 0, "currentStep": task.current_step,
        "errorMessage": task.error_message, "audioUrl": task.result_url if not stale else None,
        "stale": stale, "noMusicReason": metadata.get("no_music_reason"),
        "cues": metadata.get("cues") or [], "createdAt": format_datetime(task.created_at),
        "completedAt": format_datetime(task.completed_at),
    }


def enqueue_background_music_task(task_id: str) -> None:
    payload = {"task_id": task_id}
    worker_manager.worker(QUEUE_NAME).enqueue(persistent_job(
        task_id, "app.services.background_music_service:run_background_music_task", payload,
        lambda: run_background_music_task(**payload),
    ))


def _probe_seconds(path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, timeout=45, check=True,
    )
    seconds = float(result.stdout.strip())
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError(f"媒体时长无效：{path}")
    return seconds


def _shot_spans(db, chapter: Chapter, video_seconds: float) -> list[dict]:
    shots = db.query(Shot).filter(Shot.chapter_id == chapter.id).order_by(Shot.index).all()
    if not shots:
        raise ValueError("章回没有分镜，无法按 Shot 边界规划配乐")
    spans = []
    cursor = 0.0
    for shot in shots:
        path = url_to_local_path(shot.video_url) if shot.video_url else None
        if not path or not Path(path).is_file():
            raise ValueError(f"Shot #{shot.index} 缺少可用的视频，无法确定音乐入点")
        length = _probe_seconds(path)
        spans.append({
            "index": shot.index, "start_seconds": cursor, "end_seconds": cursor + length,
            "scene": shot.scene, "description": shot.description,
            "video_description": shot.video_description,
            "dialogues": json.loads(shot.dialogues or "[]"),
        })
        cursor += length
    if abs(cursor - video_seconds) > 0.25:
        raise ValueError(f"Shot 视频累计时长与章回成片相差 {cursor - video_seconds:.2f} 秒，需先核对成片")
    spans[-1]["end_seconds"] = video_seconds
    return spans


def _validate_plan(parsed: object, chapter: Chapter, spans: list[dict],
                   mode: str = PARTIAL_MUSIC) -> tuple[str, list[dict]]:
    if not isinstance(parsed, dict) or not isinstance(parsed.get("chapters"), list) or len(parsed["chapters"]) != 1:
        raise ValueError("音乐导演输出的章节数量无效")
    section = parsed["chapters"][0]
    if not isinstance(section, dict) or section.get("chapter_number") != chapter.number:
        raise ValueError("音乐导演输出的章回编号不匹配")
    raw_cues = section.get("cues")
    max_cues = 12 if mode == FULL_CHAPTER_MUSIC else 6
    if not isinstance(raw_cues, list) or len(raw_cues) > max_cues or (mode == FULL_CHAPTER_MUSIC and not raw_cues):
        raise ValueError("音乐导演输出的配乐段数无效")
    by_index = {span["index"]: span for span in spans}
    result = []
    last_end = -1
    for number, raw in enumerate(raw_cues, 1):
        if not isinstance(raw, dict):
            raise ValueError("配乐 Cue 格式无效")
        start, end = raw.get("start_shot"), raw.get("end_shot")
        if not isinstance(start, int) or not isinstance(end, int) or start > end or start <= last_end:
            raise ValueError("配乐 Cue 顺序重叠或范围无效")
        if mode == FULL_CHAPTER_MUSIC and start != (spans[0]["index"] if number == 1 else last_end + 1):
            raise ValueError("全章音乐配乐区间必须从首个 Shot 起连续覆盖，不得留白")
        if any(index not in by_index for index in range(start, end + 1)):
            raise ValueError("配乐 Cue 引用了不存在的 Shot")
        evidence = str(raw.get("evidence_quote") or "").strip()
        style = str(raw.get("style") or "").strip()
        melody = str(raw.get("melody") or "").strip()
        if len(evidence) < 4 or evidence not in (chapter.content or ""):
            raise ValueError("配乐 Cue 缺少可在章节原文中定位的证据")
        if not style or not melody:
            raise ValueError("配乐 Cue 缺少风格或旋律意图")
        selected = [by_index[index] for index in range(start, end + 1)]
        start_seconds = selected[0]["start_seconds"]
        end_seconds = selected[-1]["end_seconds"]
        if end_seconds - start_seconds < 1:
            raise ValueError("配乐 Cue 时长过短")
        has_dialogue = any(span["dialogues"] for span in selected)
        result.append({
            "index": number, "startShot": start, "endShot": end,
            "startSeconds": round(start_seconds, 3), "endSeconds": round(end_seconds, 3),
            "durationSeconds": round(end_seconds - start_seconds, 3),
            "reason": str(raw.get("reason") or ""), "evidenceQuote": evidence,
            "soundPriority": str(raw.get("sound_priority") or ""),
            "style": style, "melody": melody, "gainDb": -27 if has_dialogue else -23,
        })
        last_end = end
    if mode == FULL_CHAPTER_MUSIC and last_end != spans[-1]["index"]:
        raise ValueError("全章音乐配乐区间必须覆盖到最后一个 Shot")
    if mode == FULL_CHAPTER_MUSIC and str(section.get("no_music_reason") or "").strip():
        raise ValueError("全章音乐不能包含不配乐原因")
    return str(section.get("no_music_reason") or ""), result


def _read_template(db, template_type: str) -> str:
    template = PromptTemplateService(db).get_default_system_template(template_type)
    if not template:
        raise ValueError(f"缺少背景音乐系统提示词：{template_type}")
    return template.template


async def _prepare_generation_text(llm: LLMService, db, chapter: Chapter, cue: dict,
                                   legacy_yue2: bool = False) -> tuple[str, str, int | None, str | None, str | None]:
    system_prompt = (_read_template(db, "background_music_generation") if not legacy_yue2 else
        (Path(__file__).resolve().parents[2] / "prompt_templates" /
         "background_music_generation_yue2_legacy_v1.txt").read_text(encoding="utf-8"))
    response = await llm.chat_completion(
        system_prompt=system_prompt,
        user_content=json.dumps({"style": cue["style"], "melody": cue["melody"],
                                 "sound_priority": cue["soundPriority"],
                                 "duration_seconds": cue["durationSeconds"]}, ensure_ascii=False),
        temperature=0.2, max_tokens=600, response_format="json_object",
        task_type="background_music_generation", prompt_template_name=(
            "YuE2 纯器乐生成约束 V1" if legacy_yue2 else "ACE-Step1.5 纯器乐标签 V1"),
        novel_id=chapter.novel_id, chapter_id=chapter.id,
    )
    if not response.get("success"):
        raise ValueError(response.get("error") or "ACE-Step 标签解析失败")
    parsed = safe_parse_llm_json(response.get("content") or "", default=None)
    marker = "[instrumental]" if legacy_yue2 else "[inst]"
    text_key = "style" if legacy_yue2 else "tags"
    if not isinstance(parsed, dict) or parsed.get("lyrics") != marker or not isinstance(parsed.get(text_key), str):
        raise ValueError("纯器乐提示词输出无效")
    tags = parsed[text_key].strip()
    if not tags:
        raise ValueError("纯器乐提示词缺少音乐标签")
    if "instrumental" not in tags.lower():
        tags = f"instrumental, {tags}"
    if "no vocals" not in tags.lower():
        tags = f"{tags.rstrip(', ')}, no vocals"
    if "no sound effects" not in tags.lower():
        tags = f"{tags.rstrip(', ')}, no sound effects or environmental ambience"
    bpm = parsed.get("bpm")
    bpm = int(bpm) if isinstance(bpm, (int, float)) and not isinstance(bpm, bool) and 10 <= bpm <= 300 else None
    keyscale = parsed.get("keyscale")
    if keyscale not in ACE_STEP_1_5_KEYS:
        keyscale = None
    timesignature = parsed.get("timesignature")
    if timesignature not in {"2", "3", "4", "6"}:
        timesignature = None
    return tags, marker, bpm, keyscale, timesignature


def _workflow(db, workflow_id: str | None = None) -> tuple[dict, dict, str]:
    WorkflowService(db).load_default_workflows()
    repository = WorkflowRepository(db)
    workflow = repository.get_by_id(workflow_id) if workflow_id else repository.get_active_by_type("background_music")
    if not workflow:
        raise ValueError("没有启用的背景音乐工作流")
    graph = json.loads(workflow.workflow_json)
    mapping = json.loads(workflow.node_mapping or "{}")
    for key in ("music_style_node_id", "music_lyrics_node_id"):
        node = graph.get(str(mapping.get(key)))
        if not node or node.get("class_type") != "CR Prompt Text" or not isinstance(node.get("inputs"), dict):
            raise ValueError(f"背景音乐工作流的 {key} 必须映射 CR Prompt Text 节点")
    save = graph.get(str(mapping.get("save_audio_node_id")))
    if not save or save.get("class_type") != "SaveAudio":
        raise ValueError("背景音乐工作流必须映射 SaveAudio 节点")
    if any(node.get("class_type") == "EmptyAceStep1.5LatentAudio" for node in graph.values()):
        duration_node = graph.get(str(mapping.get("music_duration_node_id")))
        conditioning_node = graph.get(str(mapping.get("music_conditioning_node_id")))
        if not duration_node or duration_node.get("class_type") != "EmptyAceStep1.5LatentAudio":
            raise ValueError("ACE-Step1.5 背景音乐工作流必须映射 EmptyAceStep1.5LatentAudio 时长节点")
        if not conditioning_node or conditioning_node.get("class_type") != "TextEncodeAceStepAudio1.5":
            raise ValueError("ACE-Step1.5 背景音乐工作流必须映射 TextEncodeAceStepAudio1.5 提示词节点")
        if not isinstance(duration_node.get("inputs", {}).get("seconds"), (int, float)):
            raise ValueError("ACE-Step1.5 时长节点的 seconds 必须为数字")
    return graph, mapping, workflow.id


def _set_cue_duration(graph: dict, mapping: dict, duration: float) -> None:
    node_id = mapping.get("music_duration_node_id")
    if not node_id:
        return  # 历史工作流没有可控时长输入。
    if not math.isfinite(duration) or not 1 <= duration <= 1000:
        raise ValueError(f"ACE-Step 配乐时长必须在 1～1000 秒之间，当前为 {duration} 秒")
    node = graph.get(str(node_id))
    if not node or node.get("class_type") not in {"EmptyAceStepLatentAudio", "EmptyAceStep1.5LatentAudio"}:
        raise ValueError("背景音乐时长映射节点无效")
    node["inputs"]["seconds"] = float(duration)
    conditioning_id = mapping.get("music_conditioning_node_id")
    if conditioning_id:
        conditioning = graph.get(str(conditioning_id))
        if not conditioning or conditioning.get("class_type") != "TextEncodeAceStepAudio1.5":
            raise ValueError("ACE-Step1.5 提示词映射节点无效")
        conditioning["inputs"]["duration"] = float(duration)


async def _download_audio(url: str, host: str, target: Path) -> None:
    if not url.startswith(host.rstrip("/") + "/view?"):
        raise ValueError("ComfyUI 音频地址无效")
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=180) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                with temporary.open("wb") as out:
                    async for chunk in response.aiter_bytes():
                        out.write(chunk)
        if temporary.stat().st_size == 0:
            raise ValueError("ComfyUI 返回空音频")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _render_cue_preview(source: Path, output: Path, duration: float,
                        mode: str = PARTIAL_MUSIC) -> float:
    """Expose exactly the portion of generated audio that belongs to this cue."""
    source_seconds = _probe_seconds(str(source))
    if source_seconds + 0.5 < duration:
        raise ValueError(f"音乐短于目标区间（{source_seconds:.2f} < {duration:.2f} 秒），不能安全混音")
    fade = min(1.0, duration / 3) if mode == PARTIAL_MUSIC else min(0.02, duration / 3)
    tempo = f"atempo={source_seconds / duration:.6f}," if mode == FULL_CHAPTER_MUSIC and source_seconds < duration else ""
    temporary = output.with_name(f".{output.stem}.{uuid.uuid4().hex}.tmp.m4a")
    filter_graph = (
        f"aresample=48000,aformat=channel_layouts=stereo,{tempo}atrim=duration={duration:.3f},"
        f"asetpts=PTS-STARTPTS,afade=t=in:st=0:d={fade:.3f},"
        f"afade=t=out:st={duration-fade:.3f}:d={fade:.3f},"
        f"apad=whole_dur={duration:.3f}"
    )
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-xerror",
               "-i", str(source), "-af", filter_graph, "-t", f"{duration:.3f}",
               "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-y", str(temporary)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=1800)
        if result.returncode:
            raise ValueError(f"配乐片段裁切失败：{result.stderr[-500:]}")
        if abs(_probe_seconds(str(temporary)) - duration) > 0.1:
            raise ValueError("配乐片段裁切后的时长与目标区间不匹配")
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return source_seconds


def _ensure_cue_preview(cue: dict, source: Path, preview: Path,
                        mode: str = PARTIAL_MUSIC) -> None:
    """Idempotent after a worker restart and compatible with old raw-audio metadata."""
    if not preview.is_file() or abs(_probe_seconds(str(preview)) - cue["durationSeconds"]) > 0.1:
        raw_seconds = _render_cue_preview(source, preview, cue["durationSeconds"], mode)
    else:
        raw_seconds = _probe_seconds(str(source))
    cue["rawAudioUrl"] = local_path_to_url(str(source))
    cue["rawAudioSeconds"] = round(raw_seconds, 3)
    cue["audioUrl"] = local_path_to_url(str(preview))
    cue["audioSeconds"] = round(_probe_seconds(str(preview)), 3)


def _assemble_preview(cues: list[dict], output: Path, duration: float,
                      mode: str = PARTIAL_MUSIC) -> None:
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-xerror", "-f", "lavfi", "-t", f"{duration:.3f}",
               "-i", "anullsrc=r=48000:cl=stereo"]
    filters = []
    labels = ["[0:a]"]
    for index, cue in enumerate(cues, 1):
        path = url_to_local_path(cue.get("rawAudioUrl") or cue["audioUrl"])
        if not path:
            raise ValueError("配乐片段文件已丢失")
        command += ["-i", path]
        length = cue["durationSeconds"]
        source_seconds = float(cue.get("rawAudioSeconds") or _probe_seconds(str(path)))
        tempo = f"atempo={source_seconds / length:.6f}," if mode == FULL_CHAPTER_MUSIC and source_seconds < length else ""
        fade = min(1.0, length / 3) if mode == PARTIAL_MUSIC else min(0.02, length / 3)
        delay = round(cue["startSeconds"] * 1000)
        relative_gain = cue["gainDb"] + 23
        filters.append(
            f"[{index}:a]aresample=48000,aformat=channel_layouts=stereo,{tempo}atrim=duration={length:.3f},"
            f"asetpts=PTS-STARTPTS,afade=t=in:st=0:d={fade:.3f},"
            f"afade=t=out:st={length-fade:.3f}:d={fade:.3f},volume={relative_gain}dB,"
            f"adelay={delay}|{delay}[cue{index}]"
        )
        labels.append(f"[cue{index}]")
    filters.append("".join(labels) + f"amix=inputs={len(labels)}:duration=first:normalize=0[out]")
    temporary = output.with_name(f".{output.stem}.{uuid.uuid4().hex}.tmp.m4a")
    command += ["-filter_complex", ";".join(filters), "-map", "[out]", "-t", f"{duration:.3f}",
                "-c:a", "aac", "-b:a", "192k", "-y", str(temporary)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=1800)
        if result.returncode:
            raise ValueError(f"背景音乐试听轨合成失败：{result.stderr[-500:]}")
        if abs(_probe_seconds(str(temporary)) - duration) > 0.25:
            raise ValueError("背景音乐试听轨时长与章回不匹配")
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


async def run_background_music_task(task_id: str) -> None:
    db = SessionLocal()
    task = None
    try:
        task = db.get(Task, task_id)
        if not task or task.status not in {"pending", "running"}:
            return
        chapter = db.query(Chapter).filter(Chapter.id == task.chapter_id, Chapter.novel_id == task.novel_id).one()
        novel = db.get(Novel, task.novel_id)
        metadata = _metadata(task)
        mode = FULL_CHAPTER_MUSIC if metadata.get("music_mode") == FULL_CHAPTER_MUSIC else PARTIAL_MUSIC
        if chapter.final_video != metadata.get("source_video_url"):
            raise ValueError("章回视频已变化，请重新提交背景音乐生成")
        source = url_to_local_path(chapter.final_video)
        if not source:
            raise ValueError("章回视频文件不存在")
        task.status = "running"
        task.started_at = task.started_at or datetime.utcnow()
        task.current_step = "正在解析剧情与分镜..."
        task.progress = 5
        db.commit()
        duration = await asyncio.to_thread(_probe_seconds, source)
        spans = await asyncio.to_thread(_shot_spans, db, chapter, duration)
        llm = LLMService()
        if "cues" not in metadata:
            director_type = ("background_music_director_full" if mode == FULL_CHAPTER_MUSIC
                             else "background_music_director")
            director_name = ("全章背景音乐导演规划 V1" if mode == FULL_CHAPTER_MUSIC
                             else "背景音乐导演规划 V1")
            response = await llm.chat_completion(
                system_prompt=_read_template(db, director_type),
                user_content=json.dumps({"title": novel.title, "chapter_number": chapter.number,
                    "chapter_title": chapter.title, "content": chapter.content,
                    "shots": [{**{key: value for key, value in span.items()
                                   if key not in {"start_seconds", "end_seconds"}},
                               "duration_seconds": round(span["end_seconds"] - span["start_seconds"], 3)}
                              for span in spans]}, ensure_ascii=False),
                temperature=0.2, max_tokens=5000, response_format="json_object",
                task_type=director_type, prompt_template_name=director_name,
                novel_id=task.novel_id, chapter_id=chapter.id,
            )
            if not response.get("success"):
                raise ValueError(response.get("error") or "背景音乐 LLM 解析失败")
            parsed = safe_parse_llm_json(response.get("content") or "", default=None)
            no_music_reason, cues = _validate_plan(parsed, chapter, spans, mode)
            metadata.update({"cues": cues, "no_music_reason": no_music_reason, "duration_seconds": duration})
            task.metadata_json = json.dumps(metadata, ensure_ascii=False)
            task.prompt_text = format_background_music_prompt(metadata)
            task.progress = 25
            task.current_step = "已完成配乐规划"
            db.commit()
        cues = metadata["cues"]
        if cues and not task.prompt_text:
            task.prompt_text = format_background_music_prompt(metadata)
            db.commit()
        if not cues:
            task.status = "completed"
            task.progress = 100
            task.current_step = "本章无需背景音乐"
            task.completed_at = datetime.utcnow()
            db.commit()
            return
        graph, mapping, workflow_id = _workflow(db, task.workflow_id)
        legacy_yue2 = any(node.get("class_type") == "YuE2GenerateSong" for node in graph.values())
        task.workflow_id = workflow_id
        db.commit()
        output_dir = file_storage._get_story_dir(task.novel_id) / "background-music" / chapter.id / task.id
        output_dir.mkdir(parents=True, exist_ok=True)
        client = ComfyUIClient.for_product_runtime(db)
        for cue in cues:
            target = output_dir / f"cue-{cue['index']:02d}.flac"
            cue_preview = output_dir / f"cue-{cue['index']:02d}-preview.m4a"
            if target.is_file():
                await asyncio.to_thread(_ensure_cue_preview, cue, target, cue_preview, mode)
                task.metadata_json = json.dumps(metadata, ensure_ascii=False)
                db.commit()
                continue
            if not cue.get("generationStyle"):
                style, lyrics, bpm, keyscale, timesignature = await _prepare_generation_text(llm, db, chapter, cue, legacy_yue2)
                cue.update({"generationStyle": style, "lyrics": lyrics})
                if bpm is not None:
                    cue["bpm"] = bpm
                if keyscale is not None:
                    cue["keyscale"] = keyscale
                if timesignature is not None:
                    cue["timesignature"] = timesignature
                task.metadata_json = json.dumps(metadata, ensure_ascii=False)
                task.prompt_text = format_background_music_prompt(metadata)
                db.commit()
            task.current_step = f"生成第 {cue['index']}/{len(cues)} 段纯器乐..."
            task.progress = 25 + int(60 * (cue["index"] - 1) / len(cues))
            db.commit()
            submitted = json.loads(json.dumps(graph))
            submitted[str(mapping["music_style_node_id"])]["inputs"]["prompt"] = cue["generationStyle"]
            submitted[str(mapping["music_lyrics_node_id"])]["inputs"]["prompt"] = cue["lyrics"]
            _set_cue_duration(submitted, mapping, cue["durationSeconds"])
            conditioning_id = mapping.get("music_conditioning_node_id")
            if conditioning_id:
                conditioning_inputs = submitted[str(conditioning_id)]["inputs"]
                if isinstance(cue.get("bpm"), int) and 10 <= cue["bpm"] <= 300:
                    conditioning_inputs["bpm"] = cue["bpm"]
                if cue.get("keyscale") in ACE_STEP_1_5_KEYS:
                    conditioning_inputs["keyscale"] = cue["keyscale"]
                if cue.get("timesignature") in {"2", "3", "4", "6"}:
                    conditioning_inputs["timesignature"] = cue["timesignature"]
            submitted[str(mapping["save_audio_node_id"])]["inputs"]["filename_prefix"] = f"audio/novelflow_bgm_{task.id[:8]}_{cue['index']}_{uuid.uuid4().hex[:6]}"
            task.workflow_json = json.dumps(submitted, ensure_ascii=False)
            if not cue.get("promptId"):
                queued = await client.queue_prompt(submitted)
                if not queued.get("success") or not queued.get("prompt_id"):
                    raise ValueError(queued.get("message") or queued.get("error") or "背景音乐工作流提交失败")
                cue["promptId"] = queued["prompt_id"]
                task.comfyui_prompt_id = cue["promptId"]
                task.metadata_json = json.dumps(metadata, ensure_ascii=False)
                db.commit()
            result = await client.wait_for_audio_result(cue["promptId"], submitted,
                str(mapping["save_audio_node_id"]), timeout=3600, poll_interval=3)
            if not result.get("success") or not result.get("audio_url"):
                raise ValueError(result.get("message") or "背景音乐工作流未返回音频")
            await _download_audio(result["audio_url"], client.base_url, target)
            await asyncio.to_thread(_ensure_cue_preview, cue, target, cue_preview, mode)
            task.metadata_json = json.dumps(metadata, ensure_ascii=False)
            db.commit()
        if chapter.final_video != metadata.get("source_video_url"):
            raise ValueError("生成期间章回视频已变化，请重新生成背景音乐")
        task.current_step = "正在合成章回试听轨..."
        task.progress = 90
        db.commit()
        preview = output_dir / "chapter-background-music.m4a"
        await asyncio.to_thread(_assemble_preview, cues, preview, duration, mode)
        task.result_url = local_path_to_url(str(preview))
        task.status = "completed"
        task.progress = 100
        task.current_step = "背景音乐已生成，可试听"
        task.completed_at = datetime.utcnow()
        task.metadata_json = json.dumps(metadata, ensure_ascii=False)
        db.commit()
    except Exception as exc:
        if task:
            task.status = "failed"
            task.current_step = "背景音乐生成失败"
            task.error_message = str(exc)
            task.completed_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()
