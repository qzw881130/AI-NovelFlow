"""Minimal semantic Clip Planner entry point for Flow First V1."""
import json
import os

from sqlalchemy.orm import Session

from app.constants.capability import VIDEO_CAPABILITY_CONTRACTS
from app.services.llm_service import LLMService
from app.services.prompt_template_service import PromptTemplateService
from app.services.clip_validator import validate_clip_plan
from app.services.dialogue_ownership import assign_dialogues_to_clips
from app.utils.path_utils import url_to_local_path


def build_clip_planner_input(shot, temporal_anchors: list[dict], planning_policy: dict | None = None) -> dict:
    image_url = getattr(shot, "image_url", None)
    image_path = getattr(shot, "image_path", None)
    shot_image_path = (url_to_local_path(image_url) if image_url else None) or image_path
    if shot_image_path and not os.path.isfile(shot_image_path):
        shot_image_path = None
    try:
        keyframes = json.loads(getattr(shot, "video_director_plan", None) or "{}").get("keyframes") or []
    except Exception:
        keyframes = []
    try:
        legacy_keyframes = json.loads(getattr(shot, "keyframes", None) or "[]")
    except Exception:
        legacy_keyframes = []
    keyframe_images = []
    for keyframe in keyframes:
        if isinstance(keyframe, dict) and keyframe.get("image_url"):
            path = url_to_local_path(keyframe["image_url"]) or keyframe["image_url"]
            if path and os.path.isfile(path):
                keyframe_images.append({"index": keyframe.get("index"), "url": keyframe["image_url"]})
    for keyframe in legacy_keyframes:
        if not isinstance(keyframe, dict):
            continue
        image_url = keyframe.get("image_url") or keyframe.get("imageUrl")
        path = url_to_local_path(image_url) if image_url else None
        path = path or image_url
        if path and os.path.isfile(path):
            keyframe_images.append({"index": keyframe.get("plan_keyframe_index"), "url": image_url})
    end_keyframe_image = False
    for keyframe in keyframes + legacy_keyframes:
        if not isinstance(keyframe, dict):
            continue
        if str(keyframe.get("role") or "").upper() == "END":
            image_url = keyframe.get("image_url") or keyframe.get("imageUrl")
            path = url_to_local_path(image_url) if image_url else None
            path = path or image_url
            end_keyframe_image = bool(path and os.path.isfile(path))
        if keyframe.get("plan_keyframe_index") is not None:
            plan_keyframe = next((item for item in keyframes if int(item.get("index") or -1) == int(keyframe["plan_keyframe_index"])), None)
            if plan_keyframe and str(plan_keyframe.get("role") or "").upper() == "END":
                image_url = keyframe.get("image_url") or keyframe.get("imageUrl")
                path = url_to_local_path(image_url) if image_url else None
                path = path or image_url
                end_keyframe_image = bool(path and os.path.isfile(path))
    anchor_images = []
    for anchor in temporal_anchors or []:
        image_value = anchor.get("image_path") or anchor.get("image") or anchor.get("image_url")
        path = url_to_local_path(image_value) if image_value else None
        path = path or (image_value if image_value and os.path.isfile(image_value) else None)
        if path and os.path.isfile(path):
            anchor_images.append(anchor.get("anchor_id"))
    available_inputs = {
        "shot_image": bool(shot_image_path and os.path.isfile(shot_image_path)),
        "keyframe_images": keyframe_images,
        "end_keyframe_image": end_keyframe_image,
        "temporal_anchor_images": anchor_images,
        "previous_approved_video": False,
    }
    return {
        "shot": {
            "id": shot.id,
            "duration": shot.duration or 4,
            "continuity_mode": shot.continuity_mode or "NORMAL",
            "description": shot.description or "",
            "video_description": shot.video_description or "",
            "dialogues": json.loads(shot.dialogues or "[]"),
        },
        "available_generation_inputs": available_inputs,
        "director_mode": (json.loads(getattr(shot, "video_director_plan", None) or "{}").get("selected_mode") or "SINGLE_FRAME"),
        "temporal_anchors": temporal_anchors,
        "capabilities": VIDEO_CAPABILITY_CONTRACTS,
        "planning_policy": planning_policy or {"min_story_clip_duration": 2.0, "approval_mode": "AUTO_APPROVE"},
    }


async def plan_clips(db: Session, novel, shot, temporal_anchors: list[dict], planning_policy: dict | None = None) -> tuple[list[dict], dict]:
    template = PromptTemplateService(db).get_default_system_template("clip_execution_planner")
    if not template:
        raise RuntimeError("未配置 Clip Execution Planner 提示词模板")
    payload = build_clip_planner_input(shot, temporal_anchors, planning_policy)
    result = await LLMService().chat_completion(
        system_prompt=template.template,
        user_content=json.dumps(payload, ensure_ascii=False, indent=2),
        temperature=0.2,
        max_tokens=2200,
        response_format="json_object",
        task_type="clip_execution_planner",
        prompt_template_name=template.name,
        novel_id=novel.id,
        chapter_id=shot.chapter_id,
    )
    if not result.get("success"):
        raise RuntimeError(result.get("error") or "Clip Planner 调用失败")
    parsed = json.loads(result.get("content") or "{}")
    clips = parsed.get("clips") if isinstance(parsed.get("clips"), list) else []
    for index, clip in enumerate(clips, 1):
        clip["clip_index"] = int(clip.get("clip_index") or index)
        clip["planned_duration"] = round(float(clip.get("end_time", 0)) - float(clip.get("start_time", 0)), 2)
        clip.setdefault("execution_status", "PLANNED")
        clip.setdefault("approval_mode", (planning_policy or {}).get("approval_mode", "AUTO_APPROVE"))
    plan_payload = payload.get("available_generation_inputs", {})
    for index, clip in enumerate(clips, 1):
        clip.setdefault("previous_clip_index", None)
        capability = str(clip.get("capability") or "")
        contract = VIDEO_CAPABILITY_CONTRACTS.get(capability) or {}
        if capability == "MULTI_KEYFRAME":
            selected_keyframes = clip.get("keyframe_indexes") or clip.get("keyframe_indices") or []
            available_indexes = {int(item["index"]) for item in plan_payload.get("keyframe_images", []) if item.get("index") is not None}
            has_required_images = len(selected_keyframes) >= contract.get("min_keyframes", 3) and all(int(keyframe_index) in available_indexes for keyframe_index in selected_keyframes)
            selected_anchors = set(clip.get("temporal_anchor_ids") or [])
            has_anchor_inputs = len(selected_anchors) >= contract["min_temporal_anchors"] and selected_anchors.issubset(set(plan_payload.get("temporal_anchor_images") or []))
            if not has_required_images or not has_anchor_inputs:
                if index == 1 and plan_payload.get("shot_image"):
                    clip["capability"] = "SINGLE_FRAME"
                elif index > 1 and clips[index - 2].get("capability") in {"SINGLE_FRAME", "FIRST_LAST_FRAME", "MULTI_KEYFRAME", "VIDEO_CONTINUATION", "TEMPORAL_EXTEND"}:
                    clip["capability"] = "VIDEO_CONTINUATION"
        elif capability == "FIRST_LAST_FRAME" and (not plan_payload.get("shot_image") or not plan_payload.get("end_keyframe_image")):
            if index == 1 and plan_payload.get("shot_image"):
                clip["capability"] = "SINGLE_FRAME"
            elif index > 1:
                clip["capability"] = "VIDEO_CONTINUATION"
        elif capability == "TEMPORAL_EXTEND" and (
            not clip.get("temporal_anchor_ids")
            or not set(clip.get("temporal_anchor_ids") or []).issubset(set(plan_payload.get("temporal_anchor_images") or []))
        ):
            clip["capability"] = "VIDEO_CONTINUATION" if index > 1 else ("SINGLE_FRAME" if plan_payload.get("shot_image") else "")
        if clip.get("capability") in {"VIDEO_CONTINUATION", "TEMPORAL_EXTEND"} and index > 1 and not clip.get("previous_clip_index"):
            clip["previous_clip_index"] = int(clips[index - 2].get("clip_index") or index - 1)
    assignments, dialogue_validation = assign_dialogues_to_clips(json.loads(shot.dialogues or "[]"), clips)
    assignments_by_index = {item["clip_index"]: item["dialogues"] for item in assignments}
    for clip in clips:
        clip["dialogue_assignment"] = assignments_by_index.get(clip["clip_index"], [])
    validation = validate_clip_plan(
        shot.duration or 4,
        clips,
        temporal_anchors,
        available_inputs=payload["available_generation_inputs"],
    )
    validation["dialogue_ownership"] = dialogue_validation
    return clips, validation
