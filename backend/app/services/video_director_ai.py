"""Helpers for Video Director prompt call records and prompt builders."""
import json
import re
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.novel import Novel
from app.repositories.prompt_template import PromptTemplateRepository
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


def _build_clip_motion_directive(shot, clip: dict, transitions: list, clip_dialogues: list) -> str:
    clip_label = f"Clip {clip.get('clip_index') or '-'} {clip.get('start_time', '-')}-{clip.get('end_time', '-')}s"
    transition_text = "\n".join(
        f"- {transition.get('transition_description')}"
        for transition in transitions or []
        if isinstance(transition, dict) and transition.get("transition_description")
    )
    dialogue_rule = "本 Clip 允许的人物语音只来自 clip_dialogues。"
    if not clip_dialogues:
        dialogue_rule = "本 Clip 所有人物保持沉默，不说话、不低语、不发出人物语音。"
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
    return {
        "source_dialogue_count": len(assigned_dialogues),
        "assigned_dialogue_count": len(assigned_dialogues),
        "issues": sorted(set(issues)),
        "passed": not issues,
    }


def _render_character_identity_lock(characters: list, character_appearances: dict) -> str:
    lines = []
    for character in characters or []:
        appearance = character_appearances.get(character) if isinstance(character_appearances, dict) else None
        if appearance:
            lines.append(f"- {character}: {appearance}")
    if not lines:
        return ""
    return (
        "official_character_identity_lock:\n"
        "The following official character appearance is mandatory. Preserve exact face, age, hair, beard, clothing colors, robes, accessories, and identity across every Picture and every frame. Do not reinterpret dark lighting as dark clothing. Do not change robe color.\n"
        + "\n".join(lines)
    )


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
    assigned_dialogues, silent_characters = _build_dialogue_timeline(clip, clip_dialogues) if is_multi_clip else ([], [])
    dialogue_payload = [
        {key: value for key, value in item.items() if key != "text"}
        for item in assigned_dialogues
    ]
    shot_characters = safe_json_list(shot.characters)
    character_appearances = character_appearances or {}
    clip_motion_directive = _build_clip_motion_directive(shot, clip, transitions, clip_dialogues) if is_multi_clip else (shot.video_description or shot.description or "")
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
            "dialogues": dialogue_payload if is_multi_clip else safe_json_list(shot.dialogues),
        },
        "selected_mode": selected_mode,
        "clip": clip,
        "motion_directive": clip_motion_directive,
        "clip_dialogues": dialogue_payload if is_multi_clip else clip_dialogues,
        "dialogue_timeline_source": assigned_dialogues if is_multi_clip else [],
        "silent_characters": silent_characters,
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
    result = await LLMService().chat_completion(
        system_prompt=template.template,
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
    continuity_lock = _render_continuity_lock(shot, selected_mode, clip)
    if continuity_lock:
        final_prompt = f"{continuity_lock}\n\n{final_prompt}"
    identity_lock = _render_character_identity_lock(shot_characters, character_appearances)
    if identity_lock:
        final_prompt = f"{identity_lock}\n\n{final_prompt}"
    dialogue_audit = None
    if is_multi_clip:
        timeline_block = _render_dialogue_timeline_block(assigned_dialogues, silent_characters)
        final_prompt = _remove_dialogue_text_outside_single_block(final_prompt, assigned_dialogues, timeline_block)
        dialogue_audit = _audit_final_h3_prompt(final_prompt, assigned_dialogues, silent_characters)
        if not dialogue_audit.get("passed"):
            append_video_ai_call(shot, {
                "step": step,
                "task_type": template_type,
                "prompt_template_name": template.name,
                "status": "error",
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
        "parsed_result": dialogue_audit,
        "final_prompt": final_prompt,
        "clip_index": clip.get("clip_index"),
        "workflow_type": workflow_type,
        "workflow_name": workflow_name,
        "reference_images": reference_images,
    })
    db.commit()
    return final_prompt
