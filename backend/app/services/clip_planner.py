"""Minimal semantic Clip Planner entry point for Flow First V1."""
import json
import os

from sqlalchemy.orm import Session

from app.constants.capability import VIDEO_CAPABILITY_CONTRACTS
from app.services.llm_service import LLMService
from app.services.prompt_template_service import PromptTemplateService
from app.services.clip_validator import validate_clip_plan
from app.services.dialogue_ownership import assign_dialogues_to_clips
from app.services.video_director_ai import align_clip_boundaries_to_dialogue_gaps, build_dialogue_timeline
from app.utils.path_utils import local_path_to_url, url_to_local_path


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
    def resolve_image(image_url: str | None) -> str | None:
        if not image_url:
            return None
        path = url_to_local_path(image_url) or image_url
        return path if path and os.path.isfile(path) else None

    canonical_by_index = {}
    for keyframe in keyframes:
        if not isinstance(keyframe, dict) or keyframe.get("index") is None:
            continue
        try:
            index = int(keyframe["index"])
        except (TypeError, ValueError):
            continue
        canonical_by_index[index] = keyframe

    compatibility_by_index = {}
    for keyframe in legacy_keyframes:
        if not isinstance(keyframe, dict) or keyframe.get("plan_keyframe_index") is None:
            continue
        try:
            index = int(keyframe["plan_keyframe_index"])
        except (TypeError, ValueError):
            continue
        compatibility_by_index[index] = keyframe

    # The legacy visual contract treats Shot.image as START/KF1. Keep it in
    # the planner's keyframe availability so MULTI_KEYFRAME can validate the
    # declared [1, 2, 3] sequence without duplicating compatibility assets.
    keyframe_images_by_index = {}
    shot_image_source = image_url or (local_path_to_url(shot_image_path) if shot_image_path else None)
    if shot_image_path and os.path.isfile(shot_image_path):
        keyframe_images_by_index[1] = {"index": 1, "url": shot_image_source}

    for index, keyframe in canonical_by_index.items():
        if index == 1 and 1 in keyframe_images_by_index:
            continue
        image_value = keyframe.get("image_url") or keyframe.get("imageUrl")
        if resolve_image(image_value):
            keyframe_images_by_index[index] = {"index": index, "url": image_value}
            continue
        compatibility = compatibility_by_index.get(index)
        compatibility_value = (compatibility or {}).get("image_url") or (compatibility or {}).get("imageUrl")
        if resolve_image(compatibility_value):
            keyframe_images_by_index[index] = {"index": index, "url": compatibility_value}

    # Preserve compatibility-only indexes when no canonical record exists.
    for index, keyframe in compatibility_by_index.items():
        if index in keyframe_images_by_index or index in canonical_by_index:
            continue
        image_value = keyframe.get("image_url") or keyframe.get("imageUrl")
        if resolve_image(image_value):
            keyframe_images_by_index[index] = {"index": index, "url": image_value}

    keyframe_images = [keyframe_images_by_index[index] for index in sorted(keyframe_images_by_index)]
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
        "official_dialogue_timeline": (json.loads(getattr(shot, "video_director_plan", None) or "{}").get("dialogue_timeline_source") or []),
        "temporal_anchors": temporal_anchors,
        "capabilities": VIDEO_CAPABILITY_CONTRACTS,
        "planning_policy": planning_policy or {"min_story_clip_duration": 2.0, "approval_mode": "AUTO_APPROVE"},
    }


def _align_multi_keyframe_references(clips: list[dict], plan: dict, available_inputs: dict) -> None:
    """Attach Clip-local MULTI_KEYFRAME refs without changing execution capability."""
    if plan.get("selected_mode") != "MULTI_KEYFRAME":
        return
    keyframes = [item for item in plan.get("keyframes") or [] if isinstance(item, dict)]
    available_indexes = {
        int(item.get("index"))
        for item in available_inputs.get("keyframe_images") or []
        if isinstance(item, dict) and item.get("index") is not None
    }
    ordered_keyframes = []
    for keyframe in keyframes:
        try:
            index = int(keyframe.get("index"))
            time_seconds = float(keyframe.get("time_seconds"))
        except (TypeError, ValueError):
            continue
        if index in available_indexes:
            ordered_keyframes.append((time_seconds, index))

    for clip in clips:
        try:
            start = float(clip.get("start_time"))
            end = float(clip.get("end_time"))
        except (TypeError, ValueError):
            continue
        indexes = [
            index for time_seconds, index in ordered_keyframes
            if start - 0.05 <= time_seconds <= end + 0.05
        ]
        if 3 <= len(indexes) <= 4:
            clip["planning_mode"] = "MULTI_KEYFRAME"
            clip["keyframe_indexes"] = indexes


def _normalize_continuity_contract(clips: list[dict]) -> None:
    """Normalize new planner semantics without rewriting historical persisted plans."""
    for position, clip in enumerate(clips, 1):
        if not isinstance(clip, dict):
            continue
        try:
            clip_index = int(clip.get("clip_index") or position)
        except (TypeError, ValueError):
            clip_index = position
        legacy_capability = str(clip.get("capability") or "")
        if legacy_capability in {"SINGLE_FRAME", "FIRST_LAST_FRAME", "MULTI_KEYFRAME"}:
            clip.setdefault("planning_mode", legacy_capability)
        continuity = str(clip.get("continuity_to_previous") or "").upper()
        if continuity not in {"NONE", "CUT", "CONTINUOUS"}:
            if clip_index == 1:
                continuity = "NONE"
            elif legacy_capability in {"VIDEO_CONTINUATION", "TEMPORAL_EXTEND", "EXTEND"}:
                continuity = "CONTINUOUS"
            else:
                continuity = "CUT"
        requires_temporal = bool(clip.get("requires_temporal_control", legacy_capability == "TEMPORAL_EXTEND"))
        if clip_index == 1:
            continuity = "NONE"
            requires_temporal = False
            clip["capability"] = "GENERATE"
        elif continuity == "CUT":
            requires_temporal = False
            clip["capability"] = "GENERATE"
        elif continuity == "CONTINUOUS":
            clip["capability"] = "TEMPORAL_EXTEND" if requires_temporal else "EXTEND"
        clip["continuity_to_previous"] = continuity
        clip["requires_temporal_control"] = requires_temporal


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
    _normalize_continuity_contract(clips)
    plan_payload = payload.get("available_generation_inputs", {})
    video_plan = json.loads(shot.video_director_plan or "{}")
    _align_multi_keyframe_references(clips, video_plan, plan_payload)
    for index, clip in enumerate(clips, 1):
        clip.setdefault("previous_clip_index", None)
        capability = str(clip.get("capability") or "")
        contract = VIDEO_CAPABILITY_CONTRACTS.get(capability) or {}
        visual_mode = str(clip.get("planning_mode") or video_plan.get("selected_mode") or "")
        if visual_mode == "MULTI_KEYFRAME":
            selected_keyframes = clip.get("keyframe_indexes") or clip.get("keyframe_indices") or []
            available_indexes = {int(item["index"]) for item in plan_payload.get("keyframe_images", []) if item.get("index") is not None}
            has_required_images = len(selected_keyframes) >= 3 and all(int(keyframe_index) in available_indexes for keyframe_index in selected_keyframes)
            if capability == "GENERATE" and not has_required_images and plan_payload.get("shot_image"):
                clip["planning_mode"] = "SINGLE_FRAME"
                clip.pop("keyframe_indexes", None)
        elif visual_mode == "FIRST_LAST_FRAME" and (not plan_payload.get("shot_image") or not plan_payload.get("end_keyframe_image")):
            if plan_payload.get("shot_image"):
                clip["planning_mode"] = "SINGLE_FRAME"
        elif capability == "TEMPORAL_EXTEND" and (
            not clip.get("temporal_anchor_ids")
            or not set(clip.get("temporal_anchor_ids") or []).issubset(set(plan_payload.get("temporal_anchor_images") or []))
        ):
            clip["capability"] = "TEMPORAL_EXTEND" if index > 1 and clip.get("requires_temporal_control") else ("EXTEND" if index > 1 else ("SINGLE_FRAME" if plan_payload.get("shot_image") else ""))
        if clip.get("capability") in {"EXTEND", "VIDEO_CONTINUATION", "TEMPORAL_EXTEND"} and index > 1 and not clip.get("previous_clip_index"):
            clip["previous_clip_index"] = int(clips[index - 2].get("clip_index") or index - 1)
    shot_dialogues = json.loads(shot.dialogues or "[]")
    dialogue_timeline_source = video_plan.get("dialogue_timeline_source")
    generated_timeline, _, timeline_status = build_dialogue_timeline(
        {"start_time": 0, "end_time": shot.duration or 4},
        shot_dialogues,
        json.loads(getattr(shot, "characters", "[]") or "[]"),
    )
    if timeline_status.get("status") == "ok" and generated_timeline:
        dialogue_timeline_source = generated_timeline
    elif not isinstance(dialogue_timeline_source, list):
        dialogue_timeline_source = []
    if shot_dialogues and not dialogue_timeline_source:
        raise RuntimeError("DIALOGUE_TIMELINE_UNAVAILABLE: 有对白的 Shot 缺少合法 official dialogue timeline，不能静默降级生成视频。")
    max_clip_duration = 15.0
    clips = align_clip_boundaries_to_dialogue_gaps(clips, dialogue_timeline_source, max_clip_duration)
    for clip in clips:
        clip["planned_duration"] = round(
            float(clip.get("end_time", 0)) - float(clip.get("start_time", 0)),
            2,
        )
    assignments, dialogue_validation = assign_dialogues_to_clips(
        shot_dialogues, clips, dialogue_timeline_source
    )
    assignments_by_index = {item["clip_index"]: item["dialogues"] for item in assignments}
    for clip in clips:
        clip["dialogue_assignment"] = assignments_by_index.get(clip["clip_index"], [])
    validation = validate_clip_plan(
        shot.duration or 4,
        clips,
        temporal_anchors,
        available_inputs=payload["available_generation_inputs"],
        planning_mode=video_plan.get("selected_mode") or payload.get("director_mode"),
    )
    validation["dialogue_ownership"] = dialogue_validation
    return clips, validation
