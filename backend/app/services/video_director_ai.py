"""Helpers for Video Director prompt call records and prompt builders."""
import json
import re
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.novel import Novel
from app.repositories.prompt_template import PromptTemplateRepository
from app.services.llm_service import LLMService
from app.services.prop_policy import get_visual_prop_names


VIDEO_AI_STEP_LABELS = {
    "07": "视频模式推荐",
    "08": "视频关键帧规划",
    "09": "关键帧生图提示词构建",
    "10": "关键帧过渡规划",
    "11": "H3 单帧视频提示词构建",
    "12": "H3 首尾帧视频提示词构建",
    "13": "H3 多关键帧视频提示词构建",
}


def safe_json_dict(value: Any) -> dict:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def safe_json_list(value: Any) -> list:
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


MEDIA_REF_KEYS = {"image_url", "image_path", "image_task_id", "reference_image_url", "reference_url", "url", "path"}
CLIP_LLM_EXCLUDED_KEYS = {
    "prompt_text",
    "video_url",
    "local_path",
    "source_video_url",
    "generated_at",
    "generated_by_task_id",
}

_PICTURE_TOKEN_RE = re.compile(r"(?i)(?:<\s*)?Picture\s+(\d+)(?:\s*>)?")
_PICTURE_TIMELINE_RE = re.compile(
    r"(?im)(?:<\s*)?Picture\s+(\d+)(?:\s*>)?\s*=\s*[^\n]*?\bt\s*=\s*(-?\d+(?:\.\d+)?)\s*s?"
)


def build_physical_picture_mapping(video_reference_manifest: Optional[dict]) -> list[dict]:
    """Expose the final ordinary-reference manifest as the only Picture authority."""
    manifest = video_reference_manifest if isinstance(video_reference_manifest, dict) else {}
    references = manifest.get("references") if isinstance(manifest.get("references"), list) else []
    mapping = []
    for expected_index, reference in enumerate(references, 1):
        if not isinstance(reference, dict):
            raise ValueError("PHYSICAL_PICTURE_MANIFEST_INVALID")
        try:
            picture_index = int(reference.get("slot"))
        except (TypeError, ValueError):
            raise ValueError("PHYSICAL_PICTURE_MANIFEST_INVALID")
        if picture_index != expected_index:
            raise ValueError("PHYSICAL_PICTURE_MANIFEST_NOT_DENSE")
        mapping.append({
            "picture_index": picture_index,
            "picture": f"<Picture {picture_index}>",
            "kind": reference.get("kind"),
            "source_type": reference.get("source_type"),
            "source_keyframe_index": reference.get("source_keyframe_index"),
            "source_role": reference.get("source_role"),
            "source_time_seconds": reference.get("source_time_seconds"),
            "source_image_task_id": reference.get("source_image_task_id"),
            "source_identity": reference.get("source_identity") or reference.get("source_id"),
        })
    return mapping


def attach_physical_picture_mapping(states: list, picture_mapping: list[dict]) -> list[dict]:
    """Attach manifest-derived Picture identity without dropping image-less semantics."""
    by_state_index = {}
    for item in picture_mapping:
        raw_index = item.get("source_keyframe_index")
        if raw_index is None:
            continue
        try:
            state_index = int(raw_index)
        except (TypeError, ValueError):
            raise ValueError("PHYSICAL_PICTURE_SOURCE_IDENTITY_INVALID")
        if state_index in by_state_index:
            raise ValueError("PHYSICAL_PICTURE_SOURCE_IDENTITY_DUPLICATE")
        by_state_index[state_index] = item

    result = []
    for state in states or []:
        if not isinstance(state, dict):
            continue
        projected = dict(state)
        raw_index = projected.get("index")
        try:
            state_index = int(raw_index) if raw_index is not None else None
        except (TypeError, ValueError):
            state_index = None
        if state_index is None:
            result.append(projected)
            continue
        physical = by_state_index.get(state_index)
        projected["semantic_state_label"] = f"KF{state_index}"
        projected["physical_picture_index"] = physical.get("picture_index") if physical else None
        projected["physical_picture"] = physical.get("picture") if physical else None
        projected["physical_reference_status"] = "IMAGE_BACKED" if physical else "TEXT_ONLY"
        result.append(projected)
    return result


def audit_physical_picture_references(final_prompt: str, picture_mapping: list[dict]) -> dict:
    """Reject phantom/missing state Pictures and manifest-time mismatches."""
    allowed = {int(item["picture_index"]) for item in picture_mapping}
    emitted = [int(match.group(1)) for match in _PICTURE_TOKEN_RE.finditer(final_prompt or "")]
    emitted_set = set(emitted)
    invalid = sorted(emitted_set - allowed)
    required_state_pictures = {
        int(item["picture_index"])
        for item in picture_mapping
        if item.get("source_keyframe_index") is not None
    }
    missing = sorted(required_state_pictures - emitted_set)
    expected_times = {
        int(item["picture_index"]): float(
            item.get("prompt_time_seconds", item["source_time_seconds"])
        )
        for item in picture_mapping
        if item.get("source_time_seconds") is not None
    }
    time_mismatches = []
    for match in _PICTURE_TIMELINE_RE.finditer(final_prompt or ""):
        picture_index = int(match.group(1))
        if picture_index not in expected_times:
            continue
        actual_time = float(match.group(2))
        if abs(actual_time - expected_times[picture_index]) > 0.01:
            time_mismatches.append({
                "picture_index": picture_index,
                "expected_time_seconds": expected_times[picture_index],
                "actual_time_seconds": actual_time,
            })
    issues = []
    if invalid:
        issues.append("PHANTOM_PICTURE_REFERENCE")
    if missing:
        issues.append("PHYSICAL_PICTURE_REFERENCE_MISSING")
    if time_mismatches:
        issues.append("PHYSICAL_PICTURE_TIME_MISMATCH")
    return {
        "passed": not issues,
        "issues": issues,
        "physical_picture_count": len(picture_mapping),
        "emitted_picture_indexes": sorted(emitted_set),
        "invalid_picture_indexes": invalid,
        "missing_state_picture_indexes": missing,
        "time_mismatches": time_mismatches,
    }


def _canonical_picture_mapping_contract() -> str:
    return """
CANONICAL PHYSICAL PICTURE MAPPING CONTRACT (highest priority for Picture labels):
- physical_picture_manifest in the user payload is the only authority for <Picture N>.
- Picture numbering is dense, 1-based, and exactly follows physical_picture_manifest order.
- Use each semantic state's physical_picture field exactly. If it is null, describe that state textually by semantic_state_label (for example KF2) and never assign it a Picture number.
- Never derive a Picture number from a canonical state index, array position, role, or time.
- Real non-state resource references also occupy their physical_picture_manifest positions.
- temporal_anchors are separate and never consume ordinary Picture numbers.
- Every Picture reference in the final answer must resolve to physical_picture_manifest; do not emit phantom or out-of-range Picture labels.
""".strip()


def _canonical_speech_contract() -> str:
    return """
CANONICAL SINGLE SPEECH AUTHORITY (highest priority, including Novel overrides):
- dialogue_timeline_source is the sole Clip-local speaker, exact text, language,
  timing and speech-related mouth/lip authority. The program injects it once.
- Output visual direction and non-human environmental/action sound only. Do not
  output dialogue_timeline, exact dialogue, speaker assignments, human vocalization
  permissions or speech-related mouth/lip rules. Outside the injected block only
  assigned dialogue IDs may be referenced as visual event markers.
- Pictures, temporal targets, Previous AV and visual prominence never assign speakers.
- With no assigned dialogue the program injects NO_VOICE: no human speech,
  vocalization or invented dialogue, NOT SILENT_AUDIO. Preserve ambience, Foley,
  movement/object sounds and appropriate non-human sound; never mute the audio track.
- Smiles, frowns, mouth-corner changes, clenched teeth, gaze, posture and gestures
  remain legitimate visual facts, not speech permission.
""".strip()


def _canonical_temporal_controls(anchors: list, states: list) -> list[dict]:
    """Project semantic targets, not physical slots, paths or Task provenance."""
    by_index = {int(state["index"]): state for state in states}
    result = []
    for anchor in anchors or []:
        source = anchor.get("source") or {}
        raw_index = source.get("keyframe_index")
        if raw_index is None and str(source.get("id") or "").startswith("KF"):
            raw_index = str(source["id"])[2:]
        state = by_index.get(int(raw_index)) if raw_index is not None else None
        result.append({
            "anchor_id": anchor.get("anchor_id") or anchor.get("id"),
            # The compiled temporal manifest already uses Clip-local time.
            "time_seconds": anchor.get("time_seconds"),
            "source_keyframe_index": int(raw_index) if raw_index is not None else None,
            "description": state.get("description") if state else anchor.get("description"),
        })
    return result


def strip_media_refs(value: Any) -> Any:
    """Remove concrete media locators before sending data to LLM prompt builders."""
    if isinstance(value, list):
        return [strip_media_refs(item) for item in value]
    if isinstance(value, dict):
        return {
            key: strip_media_refs(item)
            for key, item in value.items()
            if key not in MEDIA_REF_KEYS
        }
    return value


def _strip_keyframe_generation_prompt(value: Any) -> Any:
    """Do not feed an old #09 image prompt back into H3 planning."""
    if isinstance(value, list):
        return [_strip_keyframe_generation_prompt(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _strip_keyframe_generation_prompt(item)
            for key, item in value.items()
            if key != "prompt_text"
        }
    return value


def strip_clip_generation_data(clip: dict) -> dict:
    """Remove generated Clip artifacts before serializing an LLM request."""
    return {
        key: value
        for key, value in (clip or {}).items()
        if key not in CLIP_LLM_EXCLUDED_KEYS
    }


def append_video_ai_call(shot, call: dict) -> dict:
    """Append an AI prompt call snapshot into shot.video_director_plan."""
    plan = safe_json_dict(shot.video_director_plan)
    calls = plan.get("ai_calls") if isinstance(plan.get("ai_calls"), list) else []
    step = str(call.get("step") or "")
    calls.append({
        "step": step,
        "title": call.get("title") or VIDEO_AI_STEP_LABELS.get(step, "AI 调用"),
        "task_type": call.get("task_type"),
        "prompt_template_name": call.get("prompt_template_name"),
        "status": call.get("status") or "success",
        "error_message": call.get("error_message") or call.get("error") or "",
        "input_summary": call.get("input_summary") or "",
        "response": call.get("response") or "",
        "parsed_result": call.get("parsed_result"),
        "final_prompt": call.get("final_prompt"),
        "clip_index": call.get("clip_index"),
        "workflow_type": call.get("workflow_type"),
        "workflow_name": call.get("workflow_name"),
        "reference_images": call.get("reference_images"),
        "created_at": call.get("created_at") or datetime.utcnow().isoformat(),
    })
    plan["ai_calls"] = calls[-80:]
    shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
    return plan


def resolve_prompt_template(db: Session, novel: Novel, template_attr: str, template_type: str):
    repo = PromptTemplateRepository(db)
    template = None
    template_id = getattr(novel, template_attr, None)
    if template_id:
        template = repo.get_by_id(template_id)
    if not template:
        template = repo.get_default_system_template(template_type)
    if not template:
        raise RuntimeError(f"未配置 {template_type} 提示词模板")
    return template


def _strip_voice_rules_from_text(value: Any) -> str:
    """Keep visual direction while removing dialogue authority from motion text."""
    clauses = re.split(r"[，,。！？；;\n]+", str(value or ""))
    voice_rule_patterns = (
        r"(?:所有|全部|其他|其余)?(?:可见)?人物.*保持沉默",
        r"(?:所有|全部|其他|其余)?(?:可见)?角色.*保持沉默",
        r"不说话",
        r"不低语",
        r"不发出(?:任何)?人物语音",
        r"只保留(?:必要的|同步)?环境声",
        r"(?:all|other) characters?.*remain silent",
        r"do not speak",
        r"no (?:dialogue|human voice|voices)",
        r"environmental sounds? only",
    )
    visual_clauses = [
        clause.strip()
        for clause in clauses
        if clause.strip() and not any(re.search(pattern, clause, re.IGNORECASE) for pattern in voice_rule_patterns)
    ]
    visual_text = "；".join(visual_clauses)
    return visual_text.replace("低声说话", "嘴巴微张，表现低声交谈的视觉状态")


def _sanitize_transitions_for_h3(transitions: list) -> list:
    sanitized = strip_media_refs(transitions) or []
    for transition in sanitized:
        if isinstance(transition, dict) and "transition_description" in transition:
            transition["transition_description"] = _strip_voice_rules_from_text(transition.get("transition_description"))
    return sanitized


def _build_clip_motion_directive(shot, clip: dict, transitions: list) -> str:
    clip_label = f"Clip {clip.get('clip_index') or '-'} {clip.get('start_time', '-')}-{clip.get('end_time', '-')}s"
    transition_text = "\n".join(
        f"- {transition.get('transition_description')}"
        for transition in transitions or []
        if isinstance(transition, dict) and transition.get("transition_description")
    )
    return "\n".join([
        f"当前只生成 {clip_label}，不要引入 Clip 时间窗之外的 Shot 级台词或未来状态。",
        "这里只描述视觉动作与镜头运动，以当前 Clip 的关键帧和相邻 transition 为准。",
        transition_text or "无额外 transition 描述。",
    ])


def _dialogue_text(dialogue: dict) -> str:
    return str(dialogue.get("text") or dialogue.get("dialogue") or "").strip()


def _dialogue_speaker(dialogue: dict) -> str:
    return str(dialogue.get("character_name") or dialogue.get("speaker") or dialogue.get("character") or "").strip()


def align_clip_boundaries_to_dialogue_gaps(
    clips: list,
    dialogue_timeline: list,
    max_clip_duration: float | None = None,
    min_clip_duration: float | None = None,
) -> list:
    """Move generation boundaries out of active speech intervals when possible."""
    if not isinstance(clips, list) or len(clips) < 2 or not dialogue_timeline:
        return clips
    intervals = []
    for item in dialogue_timeline:
        if not isinstance(item, dict):
            continue
        try:
            start = float(item.get("start_time"))
            end = float(item.get("end_time"))
        except (TypeError, ValueError):
            continue
        if end > start:
            intervals.append((start, end))
    if not intervals:
        return clips
    intervals.sort()
    ordered = sorted(clips, key=lambda item: float(item.get("start_time") or 0))
    for left, right in zip(ordered, ordered[1:]):
        boundary = float(left.get("end_time") or 0)
        if not any(start < boundary < end for start, end in intervals):
            continue
        previous_start = float(left.get("start_time") or 0)
        next_end = float(right.get("end_time") or boundary)
        candidates = sorted({
            endpoint
            for start, end in intervals
            for endpoint in (start, end)
            if previous_start < endpoint < next_end
        }, key=lambda endpoint: abs(endpoint - boundary))
        for candidate in candidates:
            left_duration = candidate - previous_start
            right_duration = next_end - candidate
            if max_clip_duration is not None and (left_duration > max_clip_duration + 1e-6 or right_duration > max_clip_duration + 1e-6):
                continue
            if min_clip_duration is not None and (left_duration < min_clip_duration - 1e-6 or right_duration < min_clip_duration - 1e-6):
                continue
            left["end_time"] = round(candidate, 2)
            right["start_time"] = round(candidate, 2)
            break
    return clips


def _estimate_dialogue_seconds(text: str, emotion_prompt: str = "") -> float:
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text or ""))
    other_words = len(re.findall(r"[A-Za-z0-9]+", text or ""))
    units = chinese_chars + other_words
    if units <= 0:
        return 0
    # This is a speech-only heuristic, calibrated against Qwen3-TTS samples.
    # Reaction time and turn-taking gaps belong to timeline allocation.
    return max(0.5, units / 4.0)


def _float_or_none(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _clip_visible_characters(keyframes: list, shot_characters: list) -> list:
    visible = []
    for keyframe in keyframes or []:
        description = str(keyframe.get("description") or "") if isinstance(keyframe, dict) else ""
        match = re.search(r"(?:^|\n)Characters:\s*\n((?:[ \t]*-[^\n]+\n?)*)", description)
        if not match:
            continue
        for character in re.findall(r"(?m)^\s*-\s*([^:\n]+):", match.group(1)):
            name = character.strip()
            if name and name not in visible:
                visible.append(name)
    return visible or shot_characters


def build_dialogue_timeline(clip: dict, clip_dialogues: list, shot_characters: list) -> tuple[list, list, dict]:
    clip_start = float(clip.get("start_time") or 0)
    clip_end = float(clip.get("end_time") or clip_start)
    if clip_end <= clip_start:
        clip_end = clip_start + max(1, float(clip.get("duration") or 1))
    clip_duration = max(0.1, clip_end - clip_start)

    projected_dialogues = [
        item for item in clip_dialogues or []
        if isinstance(item, dict) and (item.get("projection_mode") == "intersection" or item.get("dialogue_timing_source") == "official_projection")
    ]
    if projected_dialogues:
        assigned = []
        for index, dialogue in enumerate(projected_dialogues, 1):
            try:
                shot_start = max(clip_start, float(dialogue.get("start_time")))
                shot_end = min(clip_end, float(dialogue.get("end_time")))
            except (TypeError, ValueError):
                continue
            if shot_end <= shot_start:
                continue
            start = float(dialogue.get("local_start_time")) if dialogue.get("local_start_time") is not None else shot_start - clip_start
            end = float(dialogue.get("local_end_time")) if dialogue.get("local_end_time") is not None else shot_end - clip_start
            speaker = _dialogue_speaker(dialogue)
            text = _dialogue_text(dialogue)
            if not speaker or not text:
                continue
            duration = round(end - start, 2)
            assigned.append({
                "id": str(dialogue.get("dialogue_id") or dialogue.get("id") or f"D{index}"),
                "speaker": speaker,
                "text": text,
                "start_time": round(start, 2),
                "end_time": round(end, 2),
                "shot_start_time": round(shot_start, 2),
                "shot_end_time": round(shot_end, 2),
                "duration": duration,
                "estimated_speech_duration": duration,
                "min_required_duration": duration,
                "duration_sufficient": True,
                "emotion_prompt": str(dialogue.get("emotion_prompt") or dialogue.get("emotion") or ""),
                "segment_index": int(dialogue.get("segment_index") or 1),
                "is_continuation": bool(dialogue.get("is_continuation")),
                "continues_in_next_clip": bool(dialogue.get("continues_in_next_clip")),
            })
        authorized_speakers = {item["speaker"] for item in assigned if item["speaker"] != "旁白"}
        silent_characters = [character for character in shot_characters if character not in authorized_speakers]
        return assigned, silent_characters, {
            "status": "ok",
            "source": "official_projection",
            "estimated_speech_duration": round(sum(item["duration"] for item in assigned), 2),
            "dialogue_gap_duration": 0.0,
            "lead_in_duration": 0.0,
            "overflow_seconds": 0.0,
        }

    assigned = []
    lead_in = min(1.0, clip_duration * 0.1)
    cursor = clip_start + lead_in
    overflow = False
    overflow_seconds = 0.0
    estimated_speech_total = 0.0
    dialogue_count = 0
    for index, dialogue in enumerate(clip_dialogues or [], 1):
        if not isinstance(dialogue, dict):
            continue
        text = (
            str(dialogue.get("text") or dialogue.get("dialogue") or "")
            if dialogue.get("dialogue_id")
            else _dialogue_text(dialogue)
        )
        speaker = _dialogue_speaker(dialogue)
        if not text or not speaker:
            continue
        emotion_prompt = str(dialogue.get("emotion_prompt") or dialogue.get("emotion") or "")
        min_duration = _estimate_dialogue_seconds(text, emotion_prompt)
        estimated_speech_total += min_duration
        dialogue_count += 1
        raw_start = next((
            parsed
            for key in ("start_time", "start", "time", "timestamp")
            if (parsed := _float_or_none(dialogue.get(key))) is not None
        ), None)
        raw_end = next((
            parsed
            for key in ("end_time", "end")
            if (parsed := _float_or_none(dialogue.get(key))) is not None
        ), None)
        raw_duration = _float_or_none(dialogue.get("duration"))
        # Honor explicit times only when they do not overlap the preceding
        # allocated dialogue (including its turn-taking gap).
        start = max(cursor, raw_start) if raw_start is not None else cursor
        if start < clip_start:
            start = clip_start
        if start > clip_end:
            overflow = True
            overflow_seconds = max(overflow_seconds, start + min_duration - clip_end)
            continue
        has_authoritative_end = raw_end is not None and raw_end > start
        has_authoritative_duration = raw_duration is not None and raw_duration > 0
        if has_authoritative_end:
            end = raw_end
        elif has_authoritative_duration:
            end = start + raw_duration
        else:
            end = start + min_duration
        if not has_authoritative_end and not has_authoritative_duration and end - start < min_duration:
            end = start + min_duration
        if end > clip_end:
            overflow = True
            overflow_seconds = max(overflow_seconds, end - clip_end)
            continue
        if end <= start:
            start = clip_start
            end = clip_end

        actual_duration = max(0, end - start)
        timeline_item = {
            "id": str(dialogue.get("dialogue_id") or f"D{index}"),
            "speaker": speaker,
            "text": text,
            "start_time": round(start, 2),
            "end_time": round(end, 2),
            "duration": round(actual_duration, 2),
            "estimated_speech_duration": round(min_duration, 2),
            # Backward-compatible field for existing planner consumers.
            "min_required_duration": round(min_duration, 2),
            "duration_sufficient": actual_duration + 0.05 >= min_duration,
            "emotion_prompt": emotion_prompt,
        }
        if dialogue.get("dialogue_id"):
            timeline_item["segment_index"] = int(dialogue.get("segment_index") or 1)
            timeline_item["is_continuation"] = bool(dialogue.get("is_continuation"))
            timeline_item["continues_in_next_clip"] = bool(dialogue.get("continues_in_next_clip"))
        assigned.append(timeline_item)
        cursor = end + 0.2

    # Never return a partial or clamped timeline as an official speaking-state
    # authority. Callers receive an explicit warning and an empty authority.
    timeline_status = {
        "status": "overflow" if overflow else "ok",
        "estimated_speech_duration": round(estimated_speech_total, 2),
        "dialogue_gap_duration": round(max(0, dialogue_count - 1) * 0.2, 2),
        "lead_in_duration": round(lead_in, 2),
        "overflow_seconds": round(overflow_seconds, 2),
    }
    if overflow:
        assigned = []

    authorized_speakers = {
        item["speaker"]
        for item in assigned
        if item.get("speaker") and item["speaker"] != "旁白"
    }
    silent_characters = [
        character
        for character in shot_characters
        if character not in authorized_speakers
    ]
    return assigned, silent_characters, timeline_status


def _exact_spoken_text(value: str) -> str:
    """Remove punctuation used to quote a whole utterance, not its spoken content."""
    text = str(value or "").strip()
    while len(text) >= 2 and (text[0], text[-1]) in {("“", "”"), ('"', '"')}:
        text = text[1:-1].strip()
    return text


def _subject_bindings(prompt: str, visible_characters: list) -> dict:
    """Bind the injected speech timeline to the same visible Subject order as #13."""
    bindings = {name: f"<Subject {index}>" for index, name in enumerate(visible_characters, 1)}
    for subject, name in re.findall(r"(<Subject\s+\d+>)\s+is\s+([^,\n.;—]+)", prompt):
        name = name.strip()
        if name in bindings and subject != bindings[name]:
            raise ValueError(f"#13 Subject mapping conflicts with clip_visible_characters: {name}")
    return bindings


def _render_dialogue_timeline_block(assigned_dialogues: list, silent_characters: list, subject_bindings: dict | None = None) -> str:
    subject_bindings = subject_bindings or {}
    if not assigned_dialogues:
        lines = [
            "dialogue_timeline:",
            "No assigned dialogue. No character is authorized to speak throughout this clip.",
            "NO_VOICE: no human speech, no human vocalization, no invented dialogue.",
        ]
        if silent_characters:
            lines.append("silent_characters: " + ", ".join(subject_bindings.get(name, name) for name in silent_characters))
        lines.append("NO_VOICE is not SILENT_AUDIO. This human-voice restriction does not mute the audio track; environmental ambience and synchronized Foley remain audible, including movement, object interaction and appropriate non-human sounds.")
        return "\n".join(lines)
    lines = [
        "dialogue_timeline:",
        "This is the only source of exact spoken text in this prompt.",
        "Speak only the exact text spans assigned to this Clip; never repeat dialogue completed in a Previous AV.",
        "All assigned dialogue is Mandarin Chinese only. Do not translate, paraphrase, repeat, prepend or append words, invent syllables or produce other languages or extra human voices.",
        "Human vocalization and dialogue-related lip synchronization begin with the first authorized character and end with the last; no lead-in or trailing vocalization. Between assigned events no Subject has speech permission. Environmental ambience and synchronized Foley remain audible.",
    ]
    for item in assigned_dialogues:
        subject = subject_bindings.get(item["speaker"])
        if not subject:
            raise ValueError(f"No visible Subject mapping for dialogue speaker: {item['speaker']}")
        continuation = " This is a continuation of the same utterance; do not restart or repeat its earlier part." if item.get("is_continuation") else ""
        next_continuation = " This utterance continues into the next Clip." if item.get("continues_in_next_clip") else ""
        lines.extend([
            f"{item['id']}:",
            f"  speaker: {subject}",
            f"  start_time: {item['start_time']}s",
            f"  end_time: {item['end_time']}s",
            f"  exact_dialogue: {_exact_spoken_text(item['text'])}",
            f"  segment: {item.get('segment_index', 1)}; {continuation.strip()}{next_continuation}" if item.get("segment_index", 1) > 1 or item.get("continues_in_next_clip") else "  segment: complete assigned span.",
            "  Only this Subject may produce human vocalization during this event; all other Subjects remain non-vocal. Do not speak metadata labels. No subtitles, captions, or on-screen text.",
        ])
    if silent_characters:
        lines.append("silent_characters: " + ", ".join(subject_bindings.get(name, name) for name in silent_characters))
    lines.append("All non-assigned characters remain silent; only refer to assigned dialogue IDs outside this block.")
    return "\n".join(lines)


def _remove_generated_dialogue_timeline(prompt: str) -> str:
    """The LLM supplies visual direction; only the assembly supplies speech."""
    return re.sub(
        r"(?ims)^dialogue_timeline:\s*\n.*?(?=^(?:subject_definitions|official_character_identity_lock|keyframe_timeline|summary|detailed_description|overall_soundscape|shot_continuity_lock):|\Z)",
        "",
        prompt or "",
    ).strip()


def _remove_dialogue_text_outside_single_block(prompt: str, assigned_dialogues: list, timeline_block: str) -> str:
    body = prompt or ""
    for item in assigned_dialogues:
        text = _exact_spoken_text(item.get("text"))
        for variant in (item.get("text") or "", text):
            if variant:
                body = body.replace(f"“{variant}”", f"assigned dialogue {item['id']}")
                body = body.replace(f"\"{variant}\"", f"assigned dialogue {item['id']}")
                body = body.replace(variant, f"assigned dialogue {item['id']}")
    return f"{timeline_block}\n\n{body}".strip()


def _canonical_visual_body_speech_issues(body: str, subject_bindings: dict | None = None) -> list[str]:
    """Narrow explicit speech assertions only; not a visual-expression/NLP filter."""
    speech = re.compile(
        r"\b(?:speaks?|speaking|talks?|talking|says?|answers?|replies?|whispers?|whispering|"
        r"shouts?|shouting|laughs?|laughing|laughter|"
        r"mumbles?|mumbling|murmuring|crowd\s+chatter|background\s+voices|"
        r"lip[ -]?sync(?:s|ing|hronization)?|vocalizes?|vocalizing|"
        r"(?:assigned|authorized|only)\s+speaker)\b|"
        r"<Subject\s+\d+>\s+is\s+(?:the\s+|a\s+)?speaker\b|"
        r"\b(?:allow|enable|generate|produce|add|include)\s+(?:extra\s+)?human\s+(?:speech|voices?|vocalization)\b|"
        r"\bhuman\s+(?:speech|voices?|vocalization)\s+(?:(?:is|are)\s+)?(?:allowed|enabled)\b|"
        r"说话|讲话|低声交谈|低语|喊叫|笑声|口型|发声|人声|唇形",
        re.IGNORECASE,
    )
    muted_audio = re.compile(
        r"\b(?:silent\s+audio|complete\s+silence|(?:entire\s+clip|audio\s+track|"
        r"soundtrack|all\s+sound)\s+(?:(?:is|must\s+be|remains?|becomes?)\s+)?"
        r"(?:silent|muted)|mute\s+(?:the\s+)?(?:audio|soundtrack))\b|"
        r"音轨静音|关闭(?:整个)?音轨|所有声音消失", re.IGNORECASE,
    )
    issues = []
    human_identity = r"(?:<Subject\s+\d+>|\bhuman\b|\bperson\b|\bman\b|\bwoman\b|\bcrowd\b"
    for name in subject_bindings or {}:
        human_identity += "|" + re.escape(name)
    human_identity += ")"
    human_vocalization = re.compile(
        human_identity + r"[^.!?;,\n]{0,40}\b(?:screams?|screaming|grunts?|grunting|gasps?|gasping|sobs?|sobbing|sings?|singing|hums?|humming)\b",
        re.IGNORECASE,
    )
    human_silence = re.compile(
        r"(?:" + human_identity + r"|all\s+characters)\s+(?:is|are|remains?|stays?|must\s+remain)\s+(?:silent|non-vocal|mute)\b",
        re.IGNORECASE,
    )
    # Do not let a negation in another clause authorize affirmative speech.
    for clause in re.split(r"[\n.!?;,，。！？；]|\bbut\b", body, flags=re.IGNORECASE):
        for pattern, code in ((speech, "CANONICAL_SPEECH_AUTHORITY_OUTSIDE_TIMELINE"),
                              (human_vocalization, "CANONICAL_SPEECH_AUTHORITY_OUTSIDE_TIMELINE"),
                              (human_silence, "CANONICAL_SPEECH_AUTHORITY_OUTSIDE_TIMELINE"),
                              (muted_audio, "NO_VOICE_AUDIO_MUTED")):
            for match in pattern.finditer(clause):
                prefix = clause[:match.start()]
                if re.search(r"(?:\b(?:no|not|never|without|forbid|forbidden)\b|禁止|不得|没有|不允许)[\w\s-]{0,40}$", prefix, re.IGNORECASE):
                    continue
                issues.append(code)
    if re.search(r"(?i)\b(?:speaker|exact_dialogue|dialogue_timeline)\s*[:=]", body):
        issues.append("CANONICAL_SPEECH_AUTHORITY_OUTSIDE_TIMELINE")
    return sorted(set(issues))


def _audit_final_h3_prompt(final_prompt: str, assigned_dialogues: list, silent_characters: list, subject_bindings: dict | None = None, *, canonical_visual_body: str | None = None) -> dict:
    issues = []
    subject_mappings = {
        name.strip(): subject
        for subject, name in re.findall(r"(<Subject\s+\d+>)\s+is\s+([^,\n.;]+)", final_prompt)
        if name.strip()
    }
    for item in assigned_dialogues:
        text = _exact_spoken_text(item.get("text"))
        speaker = item.get("speaker") or ""
        occurrence_count = final_prompt.count(text) if text else 0
        if occurrence_count > 1:
            issues.append("DIALOGUE_DUPLICATED_IN_PROMPT")
        if occurrence_count != 1:
            issues.append("DIALOGUE_EXACT_TEXT_OCCURRENCE_INVALID")
        if not speaker or not re.search(rf"(?m)^\s*speaker: <Subject \d+>\s*$", final_prompt):
            issues.append("DIALOGUE_SPEAKER_MISSING")
        if canonical_visual_body is not None:
            subject = (subject_bindings or {}).get(speaker)
            expected = f"{item['id']}:\n  speaker: {subject}\n  start_time: {item['start_time']}s\n  end_time: {item['end_time']}s\n  exact_dialogue: {text}"
            if not subject or expected not in final_prompt:
                issues.append("DIALOGUE_SPEAKER_TIMING_AUTHORITY_INVALID")
        if not item.get("duration_sufficient"):
            issues.append("DIALOGUE_DURATION_INSUFFICIENT")
    for character in silent_characters:
        subject = (subject_bindings or {}).get(character) or subject_mappings.get(character)
        subject_is_silent = bool(subject and re.search(
            rf"{re.escape(subject)}[^.!?\n]*\b(?:remain|remains|stay|stays)\s+(?:non-vocal|silent)\b",
            final_prompt,
            re.IGNORECASE,
        ))
        subject_is_silent = subject_is_silent or bool(subject and re.search(
            rf"(?m)^silent_characters: [^\n]*{re.escape(subject)}", final_prompt
        ))
        if character and character not in final_prompt and not subject_is_silent:
            issues.append("SILENT_CHARACTER_CONSTRAINT_MISSING")
    if canonical_visual_body is not None:
        issues.extend(_canonical_visual_body_speech_issues(canonical_visual_body, subject_bindings))
        if not assigned_dialogues and "NO_VOICE: no human speech, no human vocalization, no invented dialogue." not in final_prompt:
            issues.append("CANONICAL_NO_VOICE_MISSING")
    blocking_issues = [issue for issue in sorted(set(issues)) if issue != "DIALOGUE_DURATION_INSUFFICIENT"]
    return {
        "source_dialogue_count": len(assigned_dialogues),
        "assigned_dialogue_count": len(assigned_dialogues),
        "issues": sorted(set(issues)),
        "blocking_issues": blocking_issues,
        "passed": not blocking_issues,
    }


def _render_continuity_lock(shot, selected_mode: str, clip: dict | None) -> str:
    if (shot.continuity_mode or "NORMAL") != "CONTINUOUS_TAKE":
        return ""
    clip = clip or {}
    clip_label = ""
    if clip.get("clip_index") is not None:
        clip_label = f" Clip {clip.get('clip_index')} ({clip.get('start_time', 0)}s-{clip.get('end_time', shot.duration or 0)}s)."
    return "\n".join([
        "shot_continuity_lock:",
        "continuity_mode = CONTINUOUS_TAKE. This is a shot-level editing constraint, not a video generation mode.",
        f"Generate this as part of one uninterrupted continuous take.{clip_label}",
        "No cuts, no hidden edits, no jump cuts, no shot/reverse-shot grammar, no abrupt camera teleport, no sudden lens/framing reset.",
        "All camera movement must be physically continuous and motivated by the previous visual state.",
        "Preserve spatial geography, screen direction, subject blocking, eyelines, action state, lighting continuity, and environment continuity.",
        "If this Shot is split into multiple generation clips, the start of this clip must visually inherit the previous clip ending state and continue the same camera path.",
        "Keyframes are chronological states along one continuous camera trajectory, not separate edited shots.",
        *([] if not selected_mode else [f"selected_video_generation_mode = {selected_mode}; do not treat CONTINUOUS_TAKE as SINGLE_FRAME."]),
    ])


async def build_h3_video_prompt(
    db: Session,
    novel: Novel,
    shot,
    selected_mode: str,
    clip: dict,
    workflow_capability: dict,
    workflow_type: str,
    workflow_name: str,
    start_image_url: Optional[str],
    keyframes: list,
    transitions: list,
    clip_dialogues: list,
    reference_images: list,
    character_appearances: Optional[dict] = None,
    temporal_anchors: Optional[list] = None,
    video_reference_manifest: Optional[dict] = None,
    previous_av_present: bool = False,
) -> str:
    canonical_path = isinstance(clip, dict) and "visual_state_indexes" in clip
    semantic_controls = []
    if canonical_path:
        state_map = {
            int(item.get("index")): item
            for item in (keyframes or [])
            if isinstance(item, dict) and item.get("index") is not None
        }
        owned_indexes = [int(item) for item in clip.get("visual_state_indexes") or []]
        semantic_controls = [state_map[index] for index in owned_indexes if index in state_map]
        roles = {str(item.get("role") or "").upper() for item in semantic_controls if item.get("index") is not None}
        if len(semantic_controls) == 2 and roles == {"START", "END"}:
            route = "endpoint"
        elif len(semantic_controls) == 1:
            route = "single"
        else:
            route = "multi" if semantic_controls else "single"
        if route == "endpoint":
            step = "12"
            template_attr = "h3_first_last_frame_prompt_template_id"
            template_type = "h3_first_last_frame_prompt"
        elif route == "multi":
            step = "13"
            template_attr = "h3_multi_keyframe_prompt_template_id"
            template_type = "h3_multi_keyframe_prompt"
        else:
            step = "11"
            template_attr = "h3_single_frame_prompt_template_id"
            template_type = "h3_single_frame_prompt"
    elif selected_mode == "FIRST_LAST_FRAME":
        route = "endpoint"
        step = "12"
        template_attr = "h3_first_last_frame_prompt_template_id"
        template_type = "h3_first_last_frame_prompt"
    elif selected_mode == "MULTI_KEYFRAME":
        route = "multi"
        step = "13"
        template_attr = "h3_multi_keyframe_prompt_template_id"
        template_type = "h3_multi_keyframe_prompt"
    else:
        route = "single"
        step = "11"
        template_attr = "h3_single_frame_prompt_template_id"
        template_type = "h3_single_frame_prompt"

    template = resolve_prompt_template(db, novel, template_attr, template_type)
    sanitized_keyframes = (
        [{key: item[key] for key in (
            "index", "role", "time_seconds", "description", "required", "requirement", "timed_visual_target",
        ) if key in item} for item in semantic_controls]
        if canonical_path else _strip_keyframe_generation_prompt(strip_media_refs(keyframes))
    )
    clip_start_time = float(clip.get("start_time") or 0)
    for keyframe in sanitized_keyframes:
        if isinstance(keyframe, dict) and keyframe.get("time_seconds") is not None:
            try:
                keyframe["time_seconds"] = round(float(keyframe["time_seconds"]) - clip_start_time, 2)
            except (TypeError, ValueError):
                pass
    frames = sanitized_keyframes if canonical_path else sanitized_keyframes or [
        {
            "index": 1,
            "role": "START",
            "time_seconds": 0,
            "description": shot.description or "",
        }
    ]
    physical_picture_mapping = (
        build_physical_picture_mapping(video_reference_manifest)
        if canonical_path else []
    )
    for item in physical_picture_mapping:
        if item.get("source_time_seconds") is not None:
            item["prompt_time_seconds"] = round(
                float(item["source_time_seconds"]) - clip_start_time,
                2,
            )
    mapped_frames = (
        attach_physical_picture_mapping(frames, physical_picture_mapping)
        if canonical_path else frames
    )
    mapped_keyframes = (
        attach_physical_picture_mapping(sanitized_keyframes, physical_picture_mapping)
        if canonical_path else sanitized_keyframes
    )
    mapped_semantic_controls = (
        attach_physical_picture_mapping(
            sanitized_keyframes,
            physical_picture_mapping,
        )
        if canonical_path else []
    )
    is_multi_clip = route in {"endpoint", "multi"}
    is_semantic_clip = bool(clip_dialogues and any(isinstance(item, dict) and item.get("dialogue_id") for item in clip_dialogues))
    shot_characters = safe_json_list(shot.characters)
    clip_visible_characters = _clip_visible_characters(sanitized_keyframes, shot_characters)
    assigned_dialogues, silent_characters, dialogue_timeline_status = build_dialogue_timeline(clip, clip_dialogues, clip_visible_characters)
    if canonical_path and clip_dialogues and (
        not assigned_dialogues or dialogue_timeline_status.get("status") != "ok"
    ):
        raise ValueError("CANONICAL_DIALOGUE_TIMELINE_UNAVAILABLE")
    dialogue_payload = [
        {key: value for key, value in item.items() if key not in {"text", "source_order"}}
        for item in assigned_dialogues
    ]
    character_appearances = character_appearances or {}
    sanitized_transitions = (
        [{key: item[key] for key in (
            "from_keyframe_index", "to_keyframe_index", "start_time", "end_time",
            "duration", "transition_description",
        ) if key in item} for item in transitions or [] if isinstance(item, dict)]
        if canonical_path else _sanitize_transitions_for_h3(transitions)
    )
    clip_motion_directive = (
        _build_clip_motion_directive(shot, clip, sanitized_transitions)
        if canonical_path or is_multi_clip or is_semantic_clip
        else _strip_voice_rules_from_text(shot.video_description or shot.description or "")
    )
    payload = {
        "shot": {
            "id": shot.id,
            "index": shot.index,
            **({} if canonical_path else {
                "description": shot.description or "",
                "video_description": "" if is_multi_clip or is_semantic_clip else _strip_voice_rules_from_text(shot.video_description or ""),
            }),
            "duration": shot.duration or 4,
            "continuity_mode": shot.continuity_mode or "NORMAL",
            "characters": shot_characters,
            "official_character_appearances": character_appearances,
            "scene": shot.scene or "",
            "props": get_visual_prop_names(db, novel.id, safe_json_list(shot.props)),
            **({} if canonical_path else {
                "dialogues": dialogue_payload if is_multi_clip or is_semantic_clip else safe_json_list(shot.dialogues),
            }),
        },
        **({} if canonical_path else {"selected_mode": selected_mode}),
        "visual_control_route": route if canonical_path else None,
        "visual_controls": mapped_semantic_controls if canonical_path else None,
        "physical_picture_manifest": physical_picture_mapping if canonical_path else None,
        "picture_mapping_contract": {
            "authority": "physical_picture_manifest",
            "numbering": "dense_1_based_manifest_order",
            "image_less_visual_states": "text_only_no_picture_number",
            "temporal_anchor_domain": "separate_from_ordinary_pictures",
        } if canonical_path else None,
        "clip": {key: clip[key] for key in (
            "clip_index", "start_time", "end_time", "duration", "planned_duration",
            "capability", "continuity_to_previous", "visual_state_indexes", "carry_in_state_index",
        ) if key in clip} if canonical_path else strip_clip_generation_data(clip),
        "motion_directive": clip_motion_directive,
        **({} if canonical_path else {
            "clip_dialogues": dialogue_payload if is_multi_clip or is_semantic_clip else clip_dialogues,
        }),
        "clip_visible_characters": clip_visible_characters,
        "dialogue_timeline_source": assigned_dialogues,
        "dialogue_timeline_status": dialogue_timeline_status,
        "silent_characters": silent_characters,
        "frames": mapped_frames,
        "ordered_keyframes": mapped_keyframes if canonical_path else None,
        "keyframes": mapped_keyframes,
        "temporal_anchors": _canonical_temporal_controls(temporal_anchors or [], sanitized_keyframes) if canonical_path else strip_media_refs(temporal_anchors or []),
        **({
            "conditioning": {
                "previous_av_present": bool(previous_av_present),
                "previous_av": "Continue from the ending visual state of the provided previous video; it has no Picture number." if previous_av_present else None,
                "temporal_domain": "separate_timed_conditioning_no_ordinary_picture",
            },
            "control_counts": {
                "semantic_control_count": len(semantic_controls),
                "owned_state_count": len(owned_indexes),
                "ordinary_reference_count": len(physical_picture_mapping),
                "temporal_anchor_count": len(temporal_anchors or []),
                "previous_av_present": bool(previous_av_present),
            },
        } if canonical_path else {}),
        "transitions": sanitized_transitions,
        "workflow_capability": strip_media_refs(workflow_capability),
        "workflow_type": workflow_type,
        "workflow_name": workflow_name,
        "continuity_requirements": {
            "continuity_to_previous": clip.get("continuity_to_previous"),
            "rule": "Use the semantic Clip continuity; Previous AV is a separate conditioning channel only when provided. Do not infer speech from continuity.",
        } if canonical_path else {
            "mode": shot.continuity_mode or "NORMAL",
            "is_continuous_take": (shot.continuity_mode or "NORMAL") == "CONTINUOUS_TAKE",
            "rule": "CONTINUOUS_TAKE forbids cuts and hidden edits; visual controls remain chronological states along one continuous trajectory.",
        },
    }
    user_content = "请基于以下 Video Director 规划数据，生成可直接用于 MiniMax H3 的最终视频提示词。\n\n" + json.dumps(payload, ensure_ascii=False, indent=2)
    result = await LLMService().chat_completion(
        system_prompt=(
            f"{template.template}\n\n{_canonical_picture_mapping_contract()}\n\n{_canonical_speech_contract()}"
            if canonical_path else template.template
        ),
        user_content=user_content,
        temperature=0.3,
        max_tokens=1800,
        task_type=template_type,
        prompt_template_name=template.name,
        novel_id=novel.id,
        chapter_id=shot.chapter_id,
    )
    if not result.get("success"):
        append_video_ai_call(shot, {
            "step": step,
            "task_type": template_type,
            "prompt_template_name": template.name,
            "status": "error",
            "error_message": result.get("error") or "H3 视频提示词生成失败",
            "input_summary": f"Shot {shot.index} Clip {clip.get('clip_index')} {selected_mode}",
            "response": result.get("error") or "",
            "clip_index": clip.get("clip_index"),
            "workflow_type": workflow_type,
            "workflow_name": workflow_name,
            "reference_images": reference_images,
        })
        db.commit()
        raise RuntimeError(result.get("error") or "H3 视频提示词生成失败")

    final_prompt = (result.get("content") or "").strip()
    if canonical_path or route == "multi":
        final_prompt = _remove_generated_dialogue_timeline(final_prompt)
    continuity_lock = "" if canonical_path else _render_continuity_lock(shot, selected_mode, clip)
    if continuity_lock:
        final_prompt = f"{continuity_lock}\n\n{final_prompt}"
    physical_picture_audit = None
    if canonical_path:
        physical_picture_audit = audit_physical_picture_references(final_prompt, physical_picture_mapping)
        if not physical_picture_audit.get("passed"):
            append_video_ai_call(shot, {
                "step": step,
                "task_type": template_type,
                "prompt_template_name": template.name,
                "status": "error",
                "error_message": ",".join(physical_picture_audit.get("issues") or ["PICTURE_MAPPING_AUDIT_FAILED"]),
                "input_summary": f"Shot {shot.index} Clip {clip.get('clip_index')} {selected_mode}",
                "response": result.get("content") or "",
                "parsed_result": physical_picture_audit,
                "final_prompt": final_prompt,
                "clip_index": clip.get("clip_index"),
                "workflow_type": workflow_type,
                "workflow_name": workflow_name,
                "reference_images": reference_images,
            })
            db.commit()
            raise RuntimeError(",".join(physical_picture_audit.get("issues") or ["PICTURE_MAPPING_AUDIT_FAILED"]))
    dialogue_audit = None
    if canonical_path or is_multi_clip or is_semantic_clip:
        subject_bindings = _subject_bindings(final_prompt, clip_visible_characters)
        timeline_block = _render_dialogue_timeline_block(assigned_dialogues, silent_characters, subject_bindings)
        final_prompt = _remove_dialogue_text_outside_single_block(final_prompt, assigned_dialogues, timeline_block)
        dialogue_audit = _audit_final_h3_prompt(
            final_prompt, assigned_dialogues, silent_characters, subject_bindings,
            canonical_visual_body=final_prompt[len(timeline_block):].strip() if canonical_path else None,
        )
        if not dialogue_audit.get("passed"):
            append_video_ai_call(shot, {
                "step": step,
                "task_type": template_type,
                "prompt_template_name": template.name,
                "status": "error",
                "error_message": ",".join(dialogue_audit.get("issues") or ["DIALOGUE_PROMPT_AUDIT_FAILED"]),
                "input_summary": f"Shot {shot.index} Clip {clip.get('clip_index')} {selected_mode}",
                "response": result.get("content") or "",
                "parsed_result": dialogue_audit,
                "final_prompt": final_prompt,
                "clip_index": clip.get("clip_index"),
                "workflow_type": workflow_type,
                "workflow_name": workflow_name,
                "reference_images": reference_images,
            })
            db.commit()
            raise RuntimeError(",".join(dialogue_audit.get("issues") or ["DIALOGUE_PROMPT_AUDIT_FAILED"]))
    append_video_ai_call(shot, {
        "step": step,
        "task_type": template_type,
        "prompt_template_name": template.name,
        "status": "success",
        "input_summary": f"Shot {shot.index} Clip {clip.get('clip_index')} {selected_mode}",
        "response": result.get("content") or "",
        "parsed_result": {
            "dialogue": dialogue_audit,
            "physical_picture": physical_picture_audit,
        } if canonical_path else dialogue_audit,
        "final_prompt": final_prompt,
        "clip_index": clip.get("clip_index"),
        "workflow_type": workflow_type,
        "workflow_name": workflow_name,
        "reference_images": reference_images,
    })
    db.commit()
    return final_prompt
