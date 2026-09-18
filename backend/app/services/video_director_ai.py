"""Helpers for Video Director prompt call records and prompt builders."""
import asyncio
from copy import deepcopy
import json
import re
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.novel import Novel
from app.repositories.prompt_template import PromptTemplateRepository
from app.services.llm.base import mark_matching_pending_llm_logs_error
from app.services.llm_service import LLMService
from app.services.h3_prompt_validation import (
    H3PromptValidationError, prompt_digest, strip_h3_managed_layers, validate_h3_prompt_core,
)


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


def build_visual_identity_context(db, novel_id, character_names, prop_names, visual_style) -> dict:
    """Read only named saved facts; appearances never imply additional image bindings."""
    from app.models.novel import Character, Prop

    characters, appearances, props = [], {}, {}
    for name in dict.fromkeys(character_names):
        if not isinstance(name, str) or not name.strip() or name.casefold() in {"narrator", "旁白"}:
            continue
        character = db.query(Character).filter(Character.novel_id == novel_id, Character.name == name).first()
        if character and getattr(character, "is_narrator", False):
            continue
        characters.append(name)
        if character and isinstance(character.appearance, str) and character.appearance.strip():
            appearances[name] = character.appearance
    for name in dict.fromkeys(prop_names):
        if not isinstance(name, str) or not name.strip():
            continue
        prop = db.query(Prop).filter(Prop.novel_id == novel_id, Prop.name == name).first()
        if prop and isinstance(prop.appearance, str) and prop.appearance.strip():
            props[name] = prop.appearance
    return {
        "characters": characters,
        "character_appearances": appearances,
        "prop_appearances": props,
        "visual_style": visual_style,
        "preservation_rule": (
            "Bind each appearance only to its exact saved name. These are text facts, not extra reference pictures "
            "or evidence that a prop is visible. Actually bound images are the primary visible identity, design and style authority; "
            "saved facts and visual_style supplement unknown stable features, never override visible age, face, costume, colors or prop design. "
            "Preserve stable features across shots; lighting, blur and pose do not imply a redesign. "
            "Current authored shot/keyframe/clip states govern pose, expression, position, held/dropped/absent props, damage "
            "and explicit costume or age changes. Do not restore baseline clothes, heal damage, re-equip dropped props "
            "or invent props from appearance text. Only the named visual cast and currently authored visible props may appear; "
            "narrator is audio-only. With no bound image, use these text facts and style without claiming image inheritance."
        ),
    }


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
        "llm_log_id": call.get("llm_log_id"),
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


def _extract_audio_text_rendering_constraint(template_text: str) -> str:
    match = re.search(
        r"【Audio Drive 文本渲染禁令】\s*\n(?:━{5,}\s*\n)?(?P<body>.*?)(?=\n━{5,}|\Z)",
        template_text or "",
        re.DOTALL,
    )
    return (match.group("body") if match else "").strip()


def _apply_audio_text_rendering_constraint(final_prompt: str, constraint: str) -> str:
    prompt = (final_prompt or "").strip()
    constraint = (constraint or "").strip()
    if not constraint or constraint in prompt:
        return prompt
    return f"{prompt}\n\ntext_rendering_constraint:\n{constraint}".strip()


def build_clip_subject_manifest(shot, speaker_timeline: list, character_appearances: Optional[dict] = None, character_refs: Optional[dict] = None) -> dict:
    characters = safe_json_list(shot.characters)
    appearances = character_appearances or {}
    visible_names = []
    for name in characters:
        name = _speaker_name(name)
        if (name and name.casefold() not in {"narrator", "旁白"}
                and not ((character_refs or {}).get(name) or {}).get("is_narrator") and name not in visible_names):
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


def _audiodrive_speech_audit_view(prompt: str) -> str:
    """Decode valid director JSON for speech scoping, without rewriting the prompt."""
    offset = 0
    if prompt.startswith("shot_continuity_lock:\n"):
        boundary = prompt.find("\n\n")
        if boundary < 0:
            return prompt
        offset = boundary + 2
    body = prompt[offset:]
    if not body.startswith("{"):
        return prompt
    try:
        document, end = json.JSONDecoder().raw_decode(body)
        validate_h3_prompt_core(body[:end], allow_empty_subjects=True)
    except (ValueError, H3PromptValidationError):
        return prompt
    suffix = body[end:]
    if suffix.strip() and not suffix.lstrip().startswith("text_rendering_constraint:"):
        return prompt
    # Keep every field, but do not let compact JSON join unrelated field scopes.
    view = "\n\n".join(
        f"{name}:\n" + (value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2))
        for name, value in document.items()
    )
    return prompt[:offset] + view + suffix


def audit_audiodrive_h3_prompt(final_prompt: str, speaker_timeline: list, subject_manifest: dict, resolution_issues: Optional[list] = None, dialogue_texts: Optional[list[str]] = None) -> dict:
    issues = list(resolution_issues or [])
    prompt = final_prompt or ""
    known_subjects = {
        subject.get("subject_ref")
        for subject in (subject_manifest or {}).get("subjects") or []
        if isinstance(subject, dict) and subject.get("subject_ref")
    }
    subtitle_constraints = [
        ("drive_audio", r"drive_audio"),
        ("lipsync_only", r"lip-sync|lipsync"),
        ("never_transcribe", r"never\s+transcribe"),
        ("audio_not_text", r"audio[^\n]*(text|visible text)|spoken audio must remain audio only|render[^\n]*audio[^\n]*text"),
        ("no_subtitles", r"no subtitles|subtitles"),
        ("no_captions", r"no captions|captions"),
        ("no_transcription", r"no audio transcription|transcription"),
    ]
    missing_constraints = [name for name, pattern in subtitle_constraints if not re.search(pattern, prompt, re.IGNORECASE)]
    if missing_constraints:
        issues.append({"code": "MISSING_AUDIO_TEXT_RENDERING_CONSTRAINT", "missing": missing_constraints, "blocking": True})
    for subject_ref in sorted(set(re.findall(r"<Subject\s+\d+>", prompt))):
        if subject_ref not in known_subjects:
            issues.append({"code": "UNKNOWN_SUBJECT_REFERENCE", "subject_ref": subject_ref, "blocking": True})
    speech_prompt = _audiodrive_speech_audit_view(prompt)
    for segment in speaker_timeline or []:
        if not isinstance(segment, dict):
            continue
        speaker = segment.get("visible_speaker") or "NONE"
        if speaker != "NONE" and speaker not in known_subjects:
            issues.append({"code": "UNKNOWN_SUBJECT_REFERENCE", "subject_ref": speaker, "blocking": True})
        if speaker != "NONE" and speaker in known_subjects and speaker not in prompt:
            issues.append({"code": "MISSING_SUBJECT_REFERENCE_IN_PROMPT", "subject_ref": speaker, "blocking": True})
    from app.services.h3_speech_scope import speech_conflicts
    issues.extend(speech_conflicts(speech_prompt,speaker_timeline,subject_manifest))
    speech_verbs = r"(speak|speaks|say|says|read|reads|朗读|说出|说：|台词|念出)"
    for text in dialogue_texts or []:
        text = str(text or "").strip()
        if text and text in prompt and re.search(speech_verbs, prompt, re.IGNORECASE):
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


def _handoff_prompt_payload(effective_context: dict) -> dict:
    """Only approved state fields and opaque provenance, never the observation report or media locators."""
    return strip_media_refs({
        **{field: effective_context[field] for field in (
            "version", "source", "run_id", "from_clip", "to_clip", "clip_attempt_id",
            "planned_context_hash", "start_image_sha256", "evidence_hash",
        )},
        "effective_context_hash": prompt_digest(effective_context),
        "picture_1_role": "Picture 1 is the validated actual C1 tail for this same-run C2 handoff, not the original planned keyframe.",
        "picture_1_description": effective_context["keyframes"][0]["description"],
        "trust_scope": "At the C2 start, inherit only the confirmed coarse facts in trusted_state. Validation does not certify all pixels, "
        "hidden details, or unknown facts; do not promote them into canon.",
        "preservation_rule": "Preserve canonical_state as the original P0 invariant requirements, not newly observed facts. "
        "Keep later planned keyframes and transitions; do not rewrite the plan to excuse a canonical violation.",
        "audio_rule": "Keep declared AudioDrive speakers and timing unchanged; speaker_timeline and drive_audio remain the authority for visible lip-sync.",
        "trusted_state": [{field: fact[field] for field in ("predicate", "subject", "value", "state") if field in fact}
                          for fact in effective_context["trusted_state"]
                          if fact.get("state") in {"PRESENT", "ABSENT"}
                          and fact.get("confidence") in {None, "HIGH"} and not fact.get("known_unknown")],
        "canonical_state": [{field: requirement[field] for field in (
            "predicate", "subject", "value", "expected", "critical", "protected", "known_unknown",
        ) if field in requirement} for requirement in effective_context["canonical_state"]],
    })


def build_handoff_continuity_layer(effective_context: dict | None) -> str:
    if effective_context is None:
        return ""
    payload = _handoff_prompt_payload(effective_context)
    return "\n".join([
        "actual_state_handoff: source=actual_state_handoff; version=1; C1->C2; "
        f"effective_context_hash={payload['effective_context_hash']}; evidence_hash={payload['evidence_hash']}; "
        f"start_image_sha256={payload['start_image_sha256']}",
        payload["picture_1_role"], payload["trust_scope"], payload["preservation_rule"], payload["audio_rule"],
        "Picture 1 description: " + json.dumps(payload["picture_1_description"], ensure_ascii=False),
        "trusted_state: " + json.dumps(payload["trusted_state"], ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        "canonical_state: " + json.dumps(payload["canonical_state"], ensure_ascii=False, sort_keys=True, separators=(",", ":")),
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
    audio_text_rendering_constraint: str = "",
    visual_identity: Optional[dict] = None,
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
    if visual_identity is not None:
        lines.extend(["", "official_character_identity_lock:", json.dumps(visual_identity, ensure_ascii=False)])
    if audio_text_rendering_constraint:
        lines.extend(["", "text_rendering_constraint:", audio_text_rendering_constraint])
    return "\n".join(lines).strip()


def resolve_h3_prompt_subjects(db, novel_id, shot, clip, speaker_timeline, character_appearances):
    from app.services.runtime_gate import require_rsa
    rsa=require_rsa(db,shot.id)
    character_refs={c['definition']['name']:{'id':c['character_id'],'name':c['definition']['name'],'is_narrator':False}
                    for c in rsa.inputs['logical']['characters']}
    manifest = build_clip_subject_manifest(shot, speaker_timeline, character_appearances, character_refs)
    timeline, issues = resolve_speaker_timeline_for_h3(speaker_timeline, manifest, clip)
    return manifest, timeline, issues


def prepare_h3_prompt(value, *, constraint, continuity_lock, subject_manifest, speaker_timeline,
                      audio_drive_enabled=True, fallback_context=None):
    core = strip_h3_managed_layers(value, constraint, continuity_lock)
    validation = validate_h3_prompt_core(
        core, allow_empty_subjects=not subject_manifest.get("subjects"), fallback_context=fallback_context,
    )
    final_prompt = _apply_audio_text_rendering_constraint(validation["core"], constraint)
    if continuity_lock:
        final_prompt = f"{continuity_lock}\n\n{final_prompt}"
    audit = audit_audiodrive_h3_prompt(final_prompt, speaker_timeline, subject_manifest) if audio_drive_enabled else {"passed": True, "applicable": False, "issues": []}
    if not audit["passed"]:
        raise H3PromptValidationError("AUDIODRIVE_AUDIT_FAILED", audit["issues"])
    return {
        **validation, "passed": True, "final_prompt": final_prompt, "final_hash": prompt_digest(final_prompt),
        "constraint": constraint, "continuity_lock": continuity_lock, "audio_drive_enabled": audio_drive_enabled,
        "subject_manifest": subject_manifest, "speaker_timeline": speaker_timeline, "audio_audit": audit,
        "fallback_context": fallback_context,
    }


def _record_h3_prompt_call(db, shot, call):
    from types import SimpleNamespace
    from app.services.video_director_plan_service import VideoDirectorPlanService
    if call.get("response") is not None and not isinstance(call["response"], str):
        call = {**call, "response": json.dumps(call["response"], ensure_ascii=False)}
    if hasattr(shot, "_execution_task_id"):
        from app.services.shot_video_execution import mutate_private_plan
        mutate_private_plan(db, shot, lambda plan: append_video_ai_call(SimpleNamespace(video_director_plan=plan), call))
        return
    VideoDirectorPlanService(db).mutate(
        shot.id, lambda plan: append_video_ai_call(SimpleNamespace(video_director_plan=plan), call),
    )


def _has_recorded_h3_fallback(db, shot, clip, candidate, record):
    """A user-editable plan/ai_calls marker cannot establish fallback provenance."""
    from app.models.task import Task
    from app.services.comfyui.service import is_h3_workflow, resolve_h3_consumed_prompt
    current_task_id = (record.get("target") or {}).get("id")
    clip_index = int(clip.get("clip_index") or 1)
    for previous in db.query(Task).filter(Task.shot_id == shot.id, Task.type == "shot_video").all():
        if previous.id == current_task_id:
            continue
        metadata = safe_json_dict(previous.metadata_json)
        if "h3_prompt_gate" in metadata:
            attempts = safe_json_dict(metadata["h3_prompt_gate"]).get("clips", {}).get(str(clip_index), [])
            for attempt in attempts:
                if (isinstance(attempt, dict) and attempt.get("passed") is True
                        and attempt.get("origin") in {"fallback", "reused_fallback"}
                        and attempt.get("profile") == "deterministic_fallback"
                        and attempt.get("final_prompt") == candidate
                        and attempt.get("final_hash") == prompt_digest(candidate)):
                    record["fallback_source_task_id"] = previous.id
                    return True
            continue
        # Older tasks have no gate record. Require an independent, submitted H3
        # graph; copied plan text or a success flag alone is not evidence.
        if not previous.comfyui_prompt_id or not is_h3_workflow(safe_json_dict(previous.workflow_json)):
            continue
        documents = safe_json_list(previous.video_director_clips)
        if not documents and clip_index == 1:
            documents = [{"clip_index": 1, "prompt_id": previous.comfyui_prompt_id,
                          "prompt_text": previous.prompt_text, "workflow_json": previous.workflow_json}]
        for document in documents:
            if (not isinstance(document, dict) or document.get("prompt_text") != candidate
                    or int(document.get("clip_index") or document.get("window_index") or 0) != clip_index
                    or not document.get("prompt_id")):
                continue
            graph = safe_json_dict(document.get("workflow_json"))
            for node_id, node in graph.items():
                if not isinstance(node, dict) or node.get("class_type") not in {"MiniMaxH3AudioConditioningT8", "MiniMaxH3ReferenceToVideo"}:
                    continue
                reference = node.get("inputs", {}).get("prompt")
                source_id = reference[0] if isinstance(reference, list) and len(reference) == 2 else node_id
                try:
                    if resolve_h3_consumed_prompt(graph, {"prompt_node_id": source_id}) == candidate:
                        record["fallback_source_task_id"] = previous.id
                        return True
                except ValueError:
                    continue
    return False


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
    reusable_prompt: Optional[str] = None,
    validation_record: Optional[dict] = None,
    audio_drive_enabled: bool = True,
    workflow_graph: Optional[dict] = None,
    effective_context: Optional[dict] = None,
) -> str:
    core_gate_required = workflow_graph is None or any(
        isinstance(node, dict) and str(node.get("class_type", "")).startswith("MiniMaxH3")
        for node in workflow_graph.values()
    )
    if effective_context is not None:
        if reusable_prompt is not None:
            raise H3PromptValidationError("HANDOFF_REQUIRES_FRESH_PROMPT")
        if not core_gate_required or selected_mode != "MULTI_KEYFRAME" or clip.get("clip_index") != 2:
            raise H3PromptValidationError("HANDOFF_REQUIRES_C2_H3")
        effective_context = deepcopy(effective_context)
        start_image_url = effective_context["start_image_url"]
        keyframes = effective_context["keyframes"]
        transitions = effective_context["transitions"]
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
    audio_text_rendering_constraint = _extract_audio_text_rendering_constraint(template.template)
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
    visual_identity = None
    if reusable_prompt is None:
        from app.services.prompt_builder import get_style
        visual_style, _ = get_style(db, novel, "character")
        from app.services.runtime_gate import require_rsa,resolved_text_context
        visual_identity={**resolved_text_context(require_rsa(db,shot.id)),"visual_style":visual_style}
        shot_characters = visual_identity["characters"]
        character_appearances = visual_identity["character_appearances"]
    subject_manifest, h3_speaker_timeline, resolution_issues = resolve_h3_prompt_subjects(
        db, novel.id, shot, clip, speaker_timeline, character_appearances,
    )
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
        "audio_drive_text_rendering_constraint": audio_text_rendering_constraint,
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
    if visual_identity is not None:
        payload["visual_identity"] = visual_identity
    if effective_context is not None:
        payload["actual_state_handoff"] = _handoff_prompt_payload(effective_context)
        # One managed prefix keeps JSON speech scoping and prequeue reconstruction unchanged.
        handoff_continuity_lock = (_render_continuity_lock(shot, selected_mode, clip) or "shot_continuity_lock:") + "\n" + build_handoff_continuity_layer(effective_context)
    user_content = (
        "请基于以下 Video Director 规划数据，生成可直接用于 MiniMax H3 的最终视频提示词。\n"
        "subject_manifest.subjects 是合法 <Subject N> 标记的穷尽清单；必须原样保持每个 subject_ref 与角色的映射，且只能使用清单中的标记。"
        "场景和道具必须按名称引用，绝不能为其创建或分配 <Subject N>。\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )
    record = validation_record if validation_record is not None else {}
    record.update({"version": 1, "passed": False, "stage": "candidate", "origin": "reuse" if reusable_prompt is not None else "llm",
                   "llm_invoked": reusable_prompt is None, "clip_index": clip.get("clip_index"), "selected_mode": selected_mode})
    if visual_identity is not None:
        record["visual_identity"] = deepcopy(visual_identity)
        record["input_hash"] = prompt_digest(payload)
    call = {"step": step, "task_type": template_type, "prompt_template_name": template.name,
            "input_summary": f"Shot {shot.index} Clip {clip.get('clip_index')} {selected_mode}",
            "clip_index": clip.get("clip_index"), "workflow_type": workflow_type,
            "workflow_name": workflow_name, "reference_images": reference_images}
    error = ""
    fallback_context = None
    try:
        if reusable_prompt is not None:
            candidate = reusable_prompt
            previous_calls = safe_json_dict(shot.video_director_plan).get("ai_calls") or []
            prior_identity = None
            if record.get("target"):
                from app.models.task import Task
                for previous in db.query(Task).filter(Task.shot_id == shot.id, Task.type == "shot_video").order_by(Task.created_at.desc()).all():
                    gate = safe_json_dict(safe_json_dict(previous.metadata_json).get("h3_prompt_gate"))
                    attempts = safe_json_list(safe_json_dict(gate.get("clips")).get(str(clip.get("clip_index") or 1)))
                    prior_identity = next((item["visual_identity"] for item in reversed(attempts)
                                           if isinstance(item, dict) and item.get("passed") is True and item.get("final_prompt") == candidate
                                           and item.get("final_hash") == prompt_digest(candidate) and isinstance(item.get("visual_identity"), dict)), None)
                    if prior_identity is not None:
                        break
            if prior_identity is None:
                prior_identity = next((item["parsed_result"]["visual_identity"] for item in reversed(previous_calls)
                                       if isinstance(item, dict) and item.get("final_prompt") == candidate and item.get("step") == step
                                       and item.get("status") == "success" and isinstance(item.get("parsed_result"), dict)
                                       and isinstance(item["parsed_result"].get("visual_identity"), dict)), None)
            if prior_identity is not None:
                from app.services.prompt_builder import get_style
                visual_style, _ = get_style(db, novel, "character")
                from app.services.runtime_gate import require_rsa,resolved_text_context
                current_identity={**resolved_text_context(require_rsa(db,shot.id)),"visual_style":visual_style}
                if current_identity != prior_identity:
                    raise H3PromptValidationError("VISUAL_IDENTITY_CHANGED", "Saved appearance/style facts changed; use LLM+ to request a new prompt.")
                record["visual_identity"] = deepcopy(prior_identity)
            if not any(item.get("final_prompt") == candidate and item.get("step") == step
                       and item.get("status") == "success" for item in previous_calls if isinstance(item, dict)):
                record["origin"] = "manual"
            fallback_shaped = strip_h3_managed_layers(
                reusable_prompt, audio_text_rendering_constraint, _render_continuity_lock(shot, selected_mode, clip),
            ).startswith("Generate Shot ") if core_gate_required else False
            legacy_fallback = fallback_shaped and _has_recorded_h3_fallback(db, shot, clip, reusable_prompt, record)
            if legacy_fallback:
                record["origin"] = "reused_fallback"
                fallback_context = {"shot_index": shot.index, "selected_mode": selected_mode,
                                    "start_time": clip.get("start_time") or 0, "end_time": clip.get("end_time") or shot.duration or 0}
        else:
            try:
                llm_timeout = max(1, int(getattr(get_settings(), "LLM_TIMEOUT", 600) or 600))
                result = await asyncio.wait_for(
                    LLMService().chat_completion(
                        system_prompt=template.template, user_content=user_content, temperature=0.3, max_tokens=1800,
                        task_type=template_type, prompt_template_name=template.name, novel_id=novel.id, chapter_id=shot.chapter_id,
                    ), timeout=llm_timeout,
                )
            except asyncio.TimeoutError:
                mark_matching_pending_llm_logs_error(
                    task_type=template_type, novel_id=novel.id, chapter_id=shot.chapter_id,
                    prompt_template_name=template.name, user_prompt=user_content,
                    error_message="H3 视频提示词生成超时，已使用 deterministic fallback 继续生成视频",
                )
                result = {"success": False, "failure_kind": "TIMEOUT", "error": "H3 视频提示词生成超时"}
            record["llm_failure_kind"] = result.get("failure_kind")
            record['llm_log_id'] = call['llm_log_id'] = result.get('llm_log_id')
            record['prompt_snapshot'] = {'id':template.id,'name':template.name,'hash':prompt_digest(template.template)}
            if not result.get("success"):
                error = result.get("error") or "H3 视频提示词生成失败"
                record["diagnostic_content"] = result.get("diagnostic_content")
                record["diagnostic_type"] = result.get("diagnostic_type")
                if core_gate_required and result.get("failure_kind") not in {"TIMEOUT", "SERVICE_ERROR"}:
                    raise H3PromptValidationError(result.get("failure_kind") or "UNKNOWN_ERROR", error)
                record["origin"] = "fallback"
                candidate = _build_deterministic_h3_prompt(
                    shot=shot, selected_mode=selected_mode, clip=clip, keyframes=keyframes, transitions=transitions,
                    speaker_timeline=h3_speaker_timeline, audio_drive_context=audio_drive_context, subject_manifest=subject_manifest,
                    visual_identity=visual_identity,
                )
                fallback_context = {"shot_index": shot.index, "selected_mode": selected_mode,
                                    "start_time": clip.get("start_time") or 0, "end_time": clip.get("end_time") or shot.duration or 0}
            else:
                candidate = result.get("content")
        record["raw_candidate"] = candidate
        record["stage"] = "core"
        if core_gate_required:
            prepared = prepare_h3_prompt(
                candidate, constraint=audio_text_rendering_constraint,
                continuity_lock=handoff_continuity_lock if effective_context is not None else _render_continuity_lock(shot, selected_mode, clip),
                subject_manifest=subject_manifest, speaker_timeline=h3_speaker_timeline,
                audio_drive_enabled=audio_drive_enabled, fallback_context=fallback_context,
            )
        else:
            # This builder was already shared with non-H3 video workflows. Keep
            # their existing composition/audit behavior outside the new gate.
            final_prompt = _apply_audio_text_rendering_constraint(candidate, audio_text_rendering_constraint)
            continuity_lock = _render_continuity_lock(shot, selected_mode, clip)
            if continuity_lock:
                final_prompt = f"{continuity_lock}\n\n{final_prompt}"
            audit = audit_audiodrive_h3_prompt(final_prompt, h3_speaker_timeline, subject_manifest, resolution_issues)
            if not audit["passed"]:
                raise RuntimeError(json.dumps(audit, ensure_ascii=False))
            prepared = {"passed": True, "core_gate_applicable": False, "final_prompt": final_prompt,
                        "final_hash": prompt_digest(final_prompt), "audio_audit": audit}
        record.update(prepared)
        record["stage"] = "prepared"
        if fallback_context:
            record["fallback"] = "deterministic_prompt"
            record["fallback_error"] = error
        _record_h3_prompt_call(db, shot, {
            **call, "status": "success", "error_message": error,
            "response": candidate if record["origin"] == "llm" else error,
            "parsed_result": dict(record), "final_prompt": prepared["final_prompt"],
        })
        db.commit()
        return prepared["final_prompt"]
    except H3PromptValidationError as exc:
        record.update({"passed": False, "failure_kind": exc.code if exc.code in {"INVALID_OUTPUT", "UNKNOWN_ERROR", "SERVICE_ERROR", "TIMEOUT"} else "INVALID_OUTPUT",
                       "issues": [{"code": exc.code, "details": exc.details}]})
        _record_h3_prompt_call(db, shot, {
            **call, "status": "error", "error_message": str(exc),
            "response": record.get("raw_candidate") or record.get("diagnostic_content"), "parsed_result": dict(record),
        })
        db.commit()
        raise
