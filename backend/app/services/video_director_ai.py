"""Helpers for Video Director prompt call records and prompt builders."""
import asyncio
import json
import re
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.novel import Novel
from app.repositories.prompt_template import PromptTemplateRepository
from app.services.llm.base import mark_matching_pending_llm_logs_error
from app.services.llm_service import LLMService


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


def _build_clip_motion_directive(shot, clip: dict, transitions: list, speaker_timeline: list) -> str:
    clip_label = f"Clip {clip.get('clip_index') or '-'} {clip.get('start_time', '-')}-{clip.get('end_time', '-')}s"
    transition_text = "\n".join(
        f"- {transition.get('transition_description')}"
        for transition in transitions or []
        if isinstance(transition, dict) and transition.get("transition_description")
    )
    has_visible_speech = any(
        isinstance(item, dict) and item.get("visible_speaker") and item.get("visible_speaker") != "NONE"
        for item in speaker_timeline or []
    )
    dialogue_rule = "本 Clip 的可见口型只遵守 speaker_timeline；不要生成任何新台词、字幕或屏幕文字。"
    if not has_visible_speech:
        dialogue_rule = "speaker_timeline 全程无可见说话人；所有可见人物保持闭嘴，不说话、不低语。"
    return "\n".join([
        f"当前只生成 {clip_label}，不要引入 Clip 时间窗之外的 Shot 级台词或未来状态。",
        dialogue_rule,
        "视觉动作与镜头运动以当前 Clip 的关键帧和相邻 transition 为准。",
        transition_text or "无额外 transition 描述。",
    ])


def _dialogue_text(dialogue: dict) -> str:
    return str(dialogue.get("text") or dialogue.get("dialogue") or "").strip()


def _dialogue_speaker(dialogue: dict) -> str:
    return str(dialogue.get("character_name") or dialogue.get("speaker") or dialogue.get("character") or "").strip()


def _speaker_name(value: Any) -> str:
    return str(value or "").strip()


def build_clip_subject_manifest(shot, speaker_timeline: list, character_appearances: Optional[dict] = None, character_refs: Optional[dict] = None) -> dict:
    characters = safe_json_list(shot.characters)
    appearances = character_appearances or {}
    visible_names = []
    for name in characters:
        name = _speaker_name(name)
        if name and name not in visible_names:
            visible_names.append(name)
    subjects = []
    for index, name in enumerate(visible_names, 1):
        character_ref = (character_refs or {}).get(name) or {}
        subjects.append({
            "subject_ref": f"<Subject {index}>",
            "character_id": character_ref.get("id"),
            "character_name": name,
            "debug_source": "shot.characters",
            "appearance": appearances.get(name),
        })
    return {"subjects": subjects}


def resolve_speaker_timeline_for_h3(speaker_timeline: list, subject_manifest: dict, clip: dict) -> tuple[list, list]:
    issues = []
    clip_start = float((clip or {}).get("start_time") or 0)
    clip_end = float((clip or {}).get("end_time") or clip_start)
    clip_duration = max(0.0, clip_end - clip_start)
    by_id = {
        str(subject.get("character_id")): subject
        for subject in (subject_manifest or {}).get("subjects") or []
        if isinstance(subject, dict) and subject.get("character_id")
    }
    by_name = {
        _speaker_name(subject.get("character_name")): subject
        for subject in (subject_manifest or {}).get("subjects") or []
        if isinstance(subject, dict) and subject.get("character_name")
    }
    resolved = []
    last_end = 0.0
    for segment in speaker_timeline or []:
        if not isinstance(segment, dict):
            continue
        try:
            start = float(segment.get("start_time") if segment.get("start_time") is not None else segment.get("startTime") or 0)
            end = float(segment.get("end_time") if segment.get("end_time") is not None else segment.get("endTime") or 0)
        except (TypeError, ValueError):
            issues.append({"code": "INVALID_SPEAKER_TIMELINE", "segment": segment, "blocking": True})
            continue
        speaker = _speaker_name(segment.get("visible_speaker") or segment.get("visibleSpeaker") or "NONE") or "NONE"
        speaker_character_id = segment.get("visible_speaker_character_id") or segment.get("visibleSpeakerCharacterId")
        if start < -0.001 or end <= start or end > clip_duration + 0.001 or start < last_end - 0.001:
            issues.append({"code": "INVALID_SPEAKER_TIMELINE", "speaker": speaker, "start": start, "end": end, "blocking": True})
        last_end = max(last_end, end)
        event_type = str(segment.get("event_type") or segment.get("type") or "").upper()
        if event_type in {"NARRATION", "INNER_MONOLOGUE", "OFFSCREEN_DIALOGUE"} and speaker != "NONE":
            issues.append({"code": "INVALID_AUDIO_SPEAKER_SEMANTICS", "speaker": speaker, "start": start, "end": end, "blocking": True})
            speaker_ref = "NONE"
        elif speaker == "NONE":
            speaker_ref = "NONE"
        else:
            subject = by_id.get(str(speaker_character_id)) if speaker_character_id else None
            subject = subject or by_name.get(speaker)
            if not subject:
                issues.append({"code": "UNRESOLVED_VISIBLE_SPEAKER", "speaker": speaker, "start": start, "end": end, "blocking": True})
                speaker_ref = speaker
            else:
                speaker_ref = subject["subject_ref"]
        resolved.append({"start_time": round(start, 3), "end_time": round(end, 3), "visible_speaker": speaker_ref, "source_speaker": speaker})
    return resolved, issues


def _estimate_dialogue_seconds(text: str, emotion_prompt: str = "") -> float:
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text or ""))
    other_words = len(re.findall(r"[A-Za-z0-9]+", text or ""))
    units = chinese_chars + other_words
    if units <= 0:
        return 0
    chars_per_second = 3.2
    if any(keyword in str(emotion_prompt or "") for keyword in ["庄严", "缓慢", "沉稳", "郑重", "肃穆", "solemn", "slow", "measured"]):
        chars_per_second = 2.8
    return max(1.5, (units / chars_per_second) + 0.8)


def _float_or_none(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_dialogue_timeline(clip: dict, clip_dialogues: list) -> tuple[list, list]:
    clip_start = float(clip.get("start_time") or 0)
    clip_end = float(clip.get("end_time") or clip_start)
    if clip_end <= clip_start:
        clip_end = clip_start + max(1, float(clip.get("duration") or 1))
    clip_duration = max(0.1, clip_end - clip_start)

    assigned = []
    cursor = clip_start + min(1.0, clip_duration * 0.1)
    for index, dialogue in enumerate(clip_dialogues or [], 1):
        if not isinstance(dialogue, dict):
            continue
        text = _dialogue_text(dialogue)
        speaker = _dialogue_speaker(dialogue)
        if not text or not speaker:
            continue
        emotion_prompt = str(dialogue.get("emotion_prompt") or dialogue.get("emotion") or "")
        min_duration = _estimate_dialogue_seconds(text, emotion_prompt)
        raw_start = _float_or_none(dialogue.get("start_time") or dialogue.get("start") or dialogue.get("time") or dialogue.get("timestamp"))
        raw_end = _float_or_none(dialogue.get("end_time") or dialogue.get("end"))
        start = raw_start if raw_start is not None else cursor
        if start < clip_start:
            start = clip_start
        if start > clip_end:
            start = max(clip_start, clip_end - min_duration)
        end = raw_end if raw_end is not None and raw_end > start else start + min_duration
        if end - start < min_duration:
            end = start + min_duration
        if end > clip_end:
            end = clip_end
            start = max(clip_start, end - min_duration)
        if end <= start:
            start = clip_start
            end = clip_end

        actual_duration = max(0, end - start)
        assigned.append({
            "id": f"D{index}",
            "speaker": speaker,
            "text": text,
            "start_time": round(start, 2),
            "end_time": round(end, 2),
            "duration": round(actual_duration, 2),
            "min_required_duration": round(min_duration, 2),
            "duration_sufficient": actual_duration + 0.05 >= min_duration,
            "emotion_prompt": emotion_prompt,
        })
        cursor = min(clip_end, end + 0.4)

    speakers = {item["speaker"] for item in assigned}
    visible_characters = safe_json_list(getattr(clip, "characters", None)) if not isinstance(clip, dict) else []
    silent_characters = [name for name in visible_characters if name not in speakers]
    return assigned, silent_characters


def _render_dialogue_timeline_block(assigned_dialogues: list, silent_characters: list) -> str:
    if not assigned_dialogues:
        return "dialogue_timeline:\nNo assigned dialogue. All characters remain silent throughout the entire clip."
    lines = ["dialogue_timeline:", "This is the only source of exact spoken text in this prompt."]
    for item in assigned_dialogues:
        lines.extend([
            f"- {item['id']}: {item['speaker']} speaks from {item['start_time']}s to {item['end_time']}s ({item['duration']}s).",
            f"  exact_dialogue: \"{item['text']}\"",
            "  Speak only the exact_dialogue text. Do not speak the character name. No subtitles, captions, or on-screen text.",
        ])
    if silent_characters:
        lines.append("silent_characters: " + ", ".join(silent_characters))
    lines.append("All non-assigned characters remain silent; only refer to assigned dialogue IDs outside this block.")
    return "\n".join(lines)


def _remove_dialogue_text_outside_single_block(prompt: str, assigned_dialogues: list, timeline_block: str) -> str:
    body = prompt or ""
    for item in assigned_dialogues:
        text = item.get("text") or ""
        if text:
            body = body.replace(f"“{text}”", f"assigned dialogue {item['id']}")
            body = body.replace(f"\"{text}\"", f"assigned dialogue {item['id']}")
            body = body.replace(text, f"assigned dialogue {item['id']}")
    return f"{timeline_block}\n\n{body}".strip()


def _audit_final_h3_prompt(final_prompt: str, assigned_dialogues: list, silent_characters: list) -> dict:
    issues = []
    for item in assigned_dialogues:
        text = item.get("text") or ""
        speaker = item.get("speaker") or ""
        occurrence_count = final_prompt.count(text) if text else 0
        if occurrence_count > 1:
            issues.append("DIALOGUE_DUPLICATED_IN_PROMPT")
        if occurrence_count != 1:
            issues.append("DIALOGUE_EXACT_TEXT_OCCURRENCE_INVALID")
        if not speaker or speaker not in final_prompt:
            issues.append("DIALOGUE_SPEAKER_MISSING")
        if not item.get("duration_sufficient"):
            issues.append("DIALOGUE_DURATION_INSUFFICIENT")
    for character in silent_characters:
        if character and character not in final_prompt:
            issues.append("SILENT_CHARACTER_CONSTRAINT_MISSING")
    blocking_issues = [issue for issue in sorted(set(issues)) if issue != "DIALOGUE_DURATION_INSUFFICIENT"]
    return {
        "source_dialogue_count": len(assigned_dialogues),
        "assigned_dialogue_count": len(assigned_dialogues),
        "issues": sorted(set(issues)),
        "blocking_issues": blocking_issues,
        "passed": not blocking_issues,
    }


def audit_audiodrive_h3_prompt(final_prompt: str, speaker_timeline: list, subject_manifest: dict, resolution_issues: Optional[list] = None, dialogue_texts: Optional[list[str]] = None) -> dict:
    issues = list(resolution_issues or [])
    known_subjects = {
        subject.get("subject_ref")
        for subject in (subject_manifest or {}).get("subjects") or []
        if isinstance(subject, dict) and subject.get("subject_ref")
    }
    for subject_ref in sorted(set(re.findall(r"<Subject\s+\d+>", final_prompt or ""))):
        if subject_ref not in known_subjects:
            issues.append({"code": "UNKNOWN_SUBJECT_REFERENCE", "subject_ref": subject_ref, "blocking": True})
    for segment in speaker_timeline or []:
        if not isinstance(segment, dict):
            continue
        speaker = segment.get("visible_speaker") or "NONE"
        if speaker != "NONE" and speaker not in known_subjects:
            issues.append({"code": "UNKNOWN_SUBJECT_REFERENCE", "subject_ref": speaker, "blocking": True})
        if speaker != "NONE" and speaker in known_subjects and speaker not in (final_prompt or ""):
            issues.append({"code": "MISSING_SUBJECT_REFERENCE_IN_PROMPT", "subject_ref": speaker, "blocking": True})
        if speaker == "NONE" and re.search(r"NONE[^\n。；;]*(<Subject\s+\d+>|张嘴|说话|口型|lip-sync|lip sync|mouth)", final_prompt or "", re.IGNORECASE):
            issues.append({"code": "NONE_SEGMENT_LIPSYNC_CONTRADICTION", "blocking": True})
    speech_verbs = r"(speak|speaks|say|says|read|reads|朗读|说出|说：|台词|念出)"
    for text in dialogue_texts or []:
        text = str(text or "").strip()
        if text and text in (final_prompt or "") and re.search(speech_verbs, final_prompt or "", re.IGNORECASE):
            issues.append({"code": "DIALOGUE_TEXT_LEAKAGE", "text": text, "blocking": True})
    blocking = [issue for issue in issues if issue.get("blocking")]
    return {
        "source": "AudioDrive",
        "subject_manifest": subject_manifest,
        "speaker_timeline_segments": len(speaker_timeline or []),
        "issues": issues,
        "blocking_issues": blocking,
        "passed": not blocking,
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
        f"selected_video_generation_mode = {selected_mode}; do not treat CONTINUOUS_TAKE as SINGLE_FRAME.",
    ])


def _build_deterministic_h3_prompt(
    shot,
    selected_mode: str,
    clip: dict,
    keyframes: list,
    transitions: list,
    speaker_timeline: list,
    audio_drive_context: dict,
    subject_manifest: Optional[dict] = None,
) -> str:
    clip_start = float(clip.get("start_time") or 0)
    clip_end = float(clip.get("end_time") or shot.duration or 0)
    lines = [
        f"Generate Shot {shot.index} as {selected_mode}.",
        f"Clip range: {clip_start:.3f}s to {clip_end:.3f}s in shot time.",
        "Use the provided reference pictures as chronological visual anchors in exact order.",
        "Preserve character identity, proportions, colors, markings, clothing/accessories, scene geography, lighting continuity, and camera continuity.",
        "Do not add subtitles, captions, new dialogue, new characters, or unplanned actions.",
        "",
        "shot_description:",
        shot.video_description or shot.description or "",
    ]
    if keyframes:
        lines.extend(["", "keyframe_timeline:"])
        for index, keyframe in enumerate(keyframes, 1):
            if not isinstance(keyframe, dict):
                continue
            lines.append(
                f"Picture {index}: t={float(keyframe.get('time_seconds') or 0) - clip_start:.3f}s clip time, "
                f"role={keyframe.get('role') or 'INTERMEDIATE'}, description={keyframe.get('description') or shot.description or ''}"
            )
    if transitions:
        lines.extend(["", "motion_between_pictures:"])
        for transition in transitions:
            if isinstance(transition, dict):
                lines.append(transition.get("transition_description") or "Maintain smooth continuous motion between adjacent pictures.")
    subjects = (subject_manifest or {}).get("subjects") or []
    if subjects:
        lines.extend(["", "subject_manifest:"])
        for subject in subjects:
            if isinstance(subject, dict):
                lines.append(f"{subject.get('subject_ref')}: character={subject.get('character_name') or 'UNKNOWN'}")
    if speaker_timeline:
        lines.extend(["", "speaker_timeline:"])
        for segment in speaker_timeline:
            if not isinstance(segment, dict):
                continue
            speaker = segment.get("visible_speaker") or segment.get("visibleSpeaker") or "NONE"
            lines.append(f"{segment.get('start_time', 0)}s-{segment.get('end_time', 0)}s: visible_speaker={speaker}")
    lines.extend([
        "",
        "audio_drive:",
        f"audio_mode={audio_drive_context.get('audio_mode') or 'lock_source'}",
        f"drive_audio={audio_drive_context.get('drive_audio') or 'provided drive audio'}",
        f"final_audio={audio_drive_context.get('final_audio') or 'provided final audio'}",
        "drive_audio controls visible lip-sync only; final_audio is the complete audience-facing audio.",
    ])
    return "\n".join(lines).strip()


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
    speaker_timeline: Optional[list] = None,
    audio_drive_context: Optional[dict] = None,
) -> str:
    if selected_mode == "FIRST_LAST_FRAME":
        step = "12"
        template_attr = "h3_first_last_frame_prompt_template_id"
        template_type = "h3_first_last_frame_prompt"
    elif selected_mode == "MULTI_KEYFRAME":
        step = "13"
        template_attr = "h3_multi_keyframe_prompt_template_id"
        template_type = "h3_multi_keyframe_prompt"
    else:
        step = "11"
        template_attr = "h3_single_frame_prompt_template_id"
        template_type = "h3_single_frame_prompt"

    template = resolve_prompt_template(db, novel, template_attr, template_type)
    sanitized_keyframes = strip_media_refs(keyframes)
    frames = sanitized_keyframes or [
        {
            "index": 1,
            "role": "START",
            "time_seconds": 0,
            "description": shot.description or "",
        }
    ]
    is_multi_clip = selected_mode == "MULTI_KEYFRAME"
    speaker_timeline = speaker_timeline or []
    audio_drive_context = audio_drive_context or {}
    shot_characters = safe_json_list(shot.characters)
    character_appearances = character_appearances or {}
    character_refs = {}
    if shot_characters:
        try:
            from app.models.novel import Character
            for character in db.query(Character).filter(Character.novel_id == novel.id, Character.name.in_(shot_characters)).all():
                character_refs[character.name] = {"id": character.id, "name": character.name}
        except Exception:
            character_refs = {}
    subject_manifest = build_clip_subject_manifest(shot, speaker_timeline, character_appearances, character_refs)
    h3_speaker_timeline, resolution_issues = resolve_speaker_timeline_for_h3(speaker_timeline, subject_manifest, clip)
    if resolution_issues:
        audit = audit_audiodrive_h3_prompt("", h3_speaker_timeline, subject_manifest, resolution_issues)
        raise RuntimeError(json.dumps(audit, ensure_ascii=False))
    clip_motion_directive = _build_clip_motion_directive(shot, clip, transitions, h3_speaker_timeline) if is_multi_clip else (shot.video_description or shot.description or "")
    payload = {
        "shot": {
            "id": shot.id,
            "index": shot.index,
            "description": shot.description or "",
            "video_description": "" if is_multi_clip else (shot.video_description or ""),
            "duration": shot.duration or 4,
            "continuity_mode": shot.continuity_mode or "NORMAL",
            "characters": shot_characters,
            "official_character_appearances": character_appearances,
            "scene": shot.scene or "",
            "props": safe_json_list(shot.props),
        },
        "selected_mode": selected_mode,
        "clip": clip,
        "motion_directive": clip_motion_directive,
        "speaker_timeline": h3_speaker_timeline,
        "subject_manifest": subject_manifest,
        "audio_drive_context": audio_drive_context,
        "frames": frames,
        "keyframes": sanitized_keyframes,
        "transitions": strip_media_refs(transitions),
        "workflow_capability": strip_media_refs(workflow_capability),
        "workflow_type": workflow_type,
        "workflow_name": workflow_name,
        "continuity_requirements": {
            "mode": shot.continuity_mode or "NORMAL",
            "is_continuous_take": (shot.continuity_mode or "NORMAL") == "CONTINUOUS_TAKE",
            "rule": "CONTINUOUS_TAKE forbids cuts and hidden edits while still allowing SINGLE_FRAME, FIRST_LAST_FRAME, or MULTI_KEYFRAME according to selected_mode.",
        },
    }
    user_content = "请基于以下 Video Director 规划数据，生成可直接用于 MiniMax H3 的最终视频提示词。\n\n" + json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        result = await asyncio.wait_for(
            LLMService().chat_completion(
                system_prompt=template.template,
                user_content=user_content,
                temperature=0.3,
                max_tokens=1800,
                task_type=template_type,
                prompt_template_name=template.name,
                novel_id=novel.id,
                chapter_id=shot.chapter_id,
            ),
            timeout=45,
        )
    except asyncio.TimeoutError:
        mark_matching_pending_llm_logs_error(
            task_type=template_type,
            novel_id=novel.id,
            chapter_id=shot.chapter_id,
            prompt_template_name=template.name,
            user_prompt=user_content,
            error_message="H3 视频提示词生成超时，已使用 deterministic fallback 继续生成视频",
        )
        result = {"success": False, "error": "H3 视频提示词生成超时"}
    if not result.get("success"):
        error = result.get("error") or "H3 视频提示词生成失败"
        final_prompt = _build_deterministic_h3_prompt(
            shot=shot,
            selected_mode=selected_mode,
            clip=clip,
            keyframes=keyframes,
            transitions=transitions,
            speaker_timeline=h3_speaker_timeline,
            audio_drive_context=audio_drive_context,
            subject_manifest=subject_manifest,
        )
        continuity_lock = _render_continuity_lock(shot, selected_mode, clip)
        if continuity_lock:
            final_prompt = f"{continuity_lock}\n\n{final_prompt}"
        dialogue_audit = audit_audiodrive_h3_prompt(final_prompt, h3_speaker_timeline, subject_manifest, resolution_issues)
        dialogue_audit.update({
            "fallback": "deterministic_prompt",
            "fallback_error": error,
            "audio_drive_context": audio_drive_context,
            "audio_mode": audio_drive_context.get("audio_mode"),
        })
        if not dialogue_audit.get("passed"):
            raise RuntimeError(json.dumps(dialogue_audit, ensure_ascii=False))
        append_video_ai_call(shot, {
            "step": step,
            "task_type": template_type,
            "prompt_template_name": template.name,
            "status": "success",
            "error_message": error,
            "input_summary": f"Shot {shot.index} Clip {clip.get('clip_index')} {selected_mode}",
            "response": error,
            "parsed_result": dialogue_audit,
            "final_prompt": final_prompt,
            "clip_index": clip.get("clip_index"),
            "workflow_type": workflow_type,
            "workflow_name": workflow_name,
            "reference_images": reference_images,
        })
        db.commit()
        return final_prompt

    final_prompt = (result.get("content") or "").strip()
    continuity_lock = _render_continuity_lock(shot, selected_mode, clip)
    if continuity_lock:
        final_prompt = f"{continuity_lock}\n\n{final_prompt}"
    dialogue_audit = audit_audiodrive_h3_prompt(final_prompt, h3_speaker_timeline, subject_manifest, resolution_issues)
    dialogue_audit.update({
        "audio_drive_context": audio_drive_context,
        "audio_mode": audio_drive_context.get("audio_mode"),
    })
    if not dialogue_audit.get("passed"):
        raise RuntimeError(json.dumps(dialogue_audit, ensure_ascii=False))
    append_video_ai_call(shot, {
        "step": step,
        "task_type": template_type,
        "prompt_template_name": template.name,
        "status": "success",
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
    return final_prompt
