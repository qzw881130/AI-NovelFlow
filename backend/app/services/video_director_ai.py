"""Helpers for Video Director prompt call records and prompt builders."""
import json
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
    payload = {
        "shot": {
            "id": shot.id,
            "index": shot.index,
            "description": shot.description or "",
            "video_description": shot.video_description or "",
            "duration": shot.duration or 4,
            "continuity_mode": shot.continuity_mode or "NORMAL",
            "characters": safe_json_list(shot.characters),
            "scene": shot.scene or "",
            "props": safe_json_list(shot.props),
            "dialogues": safe_json_list(shot.dialogues),
        },
        "selected_mode": selected_mode,
        "clip": clip,
        "motion_directive": shot.video_description or shot.description or "",
        "clip_dialogues": clip_dialogues,
        "frames": frames,
        "keyframes": sanitized_keyframes,
        "transitions": strip_media_refs(transitions),
        "workflow_capability": strip_media_refs(workflow_capability),
        "workflow_type": workflow_type,
        "workflow_name": workflow_name,
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
    append_video_ai_call(shot, {
        "step": step,
        "task_type": template_type,
        "prompt_template_name": template.name,
        "status": "success",
        "input_summary": f"Shot {shot.index} Clip {clip.get('clip_index')} {selected_mode}",
        "response": result.get("content") or "",
        "final_prompt": final_prompt,
        "clip_index": clip.get("clip_index"),
        "workflow_type": workflow_type,
        "workflow_name": workflow_name,
        "reference_images": reference_images,
    })
    db.commit()
    return final_prompt
