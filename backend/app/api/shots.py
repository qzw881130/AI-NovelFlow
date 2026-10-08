"""
分镜路由 - 分镜图/视频/转场生成相关接口
"""

import json
import math
import asyncio
import os
import subprocess
import tempfile
import uuid
import zipfile
from copy import deepcopy
from types import SimpleNamespace
from hashlib import sha256
from io import BytesIO
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import FileResponse, StreamingResponse
from starlette.background import BackgroundTask
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.core.database import get_db
from app.models.novel import Novel, Chapter, Character, Scene, Prop
from app.models.shot import Shot
from app.models.task import Task
from app.services.visual_attention import (
    character_catalog, normalize_visual_attention, project_visual_attention,
    normalize_attention_replan_response, attention_source_sha256,
    canonical_transition_edges, stale_attention_edges, changed_attention_edges,
    attention_edge_records, merge_attention_update, clip_attention_transition_edges,
    require_current_attention_transitions, effective_transition_attention,
)
from app.repositories.character_repository import CharacterRepository
from app.services.required_visual_state_images import (
    task_provenance, validate_image_provenance, state_provenance,
    commit_visual_state_image, project_required_execution_images,
)
from app.services.required_visual_state_images import prepare_required_images
from app.models.workflow import Workflow
from app.models.llm_log import LLMLog
from app.services.comfyui import ComfyUIService
from app.services.file_storage import file_storage
from app.services.novel_service import (
    NovelService,
)
from app.services.transition_service import enqueue_transition_video_task
from app.services.shot_image_service import enqueue_shot_image_task
from app.services.shot_video_service import _clip_dialogues_for_prompt, _dialogue_assignment_source, enqueue_shot_video_task, merge_video_director_clip_videos, resolve_extend_previous_av, validate_semantic_clip_artifact, resolve_clip_reference_resources, get_semantic_clip_prompt
from app.services.canonical_execution_invalidation import (
    CanonicalExecutionConflict,
    canonical_clip_dependency_closure,
    current_visual_state_consumers,
    ensure_no_active_canonical_clip_tasks,
    invalidate_downstream_for_canonical_visual_plan_replacement,
)
from app.services.canonical_export import (
    build_chapter_archive_package,
    build_shot_production_package,
)
from app.services.shot_export_selection import SHOT_EXPORT_SECTIONS, SelectedShotArchive

generate_shot_task = enqueue_shot_image_task
generate_shot_video_task = enqueue_shot_video_task
from app.repositories.shot_repository import ShotRepository
from app.services.task_service import TaskService
from app.repositories import (
    NovelRepository,
    ChapterRepository,
    TaskRepository,
    WorkflowRepository,
    ShotRepository,
)
from app.services.shot_service import ShotService
from app.services.shot_keyframe_service import ShotKeyframeService, sync_planned_keyframe_states
from app.services.audio_reference_service import AudioReferenceService
from app.services.single_image_edit_service import SingleImageEditService
from app.schemas.shot import (
    TransitionVideoRequest,
    BatchTransitionRequest,
    MergeVideosRequest,
    ShotUpdate,
    ShotResponse,
    ShotAudioRequest,
    PatchChapterResourcesRequest,
    BatchShotsUpdateRequest,
    SetReferenceAudioRequest,
    SetReferenceImageRequest,
    GenerateKeyframeDescriptionsRequest,
    GenerateKeyframeImageRequest,
    PlanClipsRequest,
    GenerateShotImageRequest,
    ShotImageEditRequest,
    ShotImageReplaceRequest,
    GenerateVideoRequest,
    GenerateVideoDirectorClipRequest,
    RecommendVideoModeRequest,
    PlanVideoKeyframesRequest,
    PlanVideoTransitionsRequest,
    SaveVideoDirectorPlanRequest,
)
from app.api.deps import (
    get_novel_repo,
    get_chapter_repo,
    get_task_repo,
    get_workflow_repo,
    get_shot_repo,
    get_prompt_template_repo,
    get_llm_service,
)
from app.utils.path_utils import url_to_local_path, local_path_to_url
from app.utils.time_utils import format_datetime
from app.services.prompt_builder import get_style
from app.services.visual_style_authority import strip_embedded_visual_style
from app.services.canonical_visual_speech_authority import (
    CanonicalVisualSpeechAuthorityViolation,
    require_speech_neutral_visual_text,
)
from app.services.llm_service import LLMService
from app.repositories import PromptTemplateRepository
from app.services.video_director_ai import append_video_ai_call, build_dialogue_timeline, strip_media_refs
from app.services.clip_planner import plan_clips, merge_dialogue_ownership_validation
from app.services.clip_execution_compiler import (
    ClipExecutionCompileError,
    compile_extend_clip,
    compile_generate_clip,
    compile_temporal_extend_clip,
    get_canonical_execution_readiness,
)
from app.constants.capability import EXTEND_PHYSICAL_WORKFLOW_TYPE, EXTEND_WORKFLOW_ID, TEMPORAL_EXTEND_WORKFLOW_ID
from app.services.dialogue_ownership import assign_dialogues_to_clips
from app.services.prop_policy import PROP_EXISTENCE_REAL, get_visual_prop_names
from app.core.database import SessionLocal
from app.services.background_workers import persistent_job, worker_manager

router = APIRouter()


def _probe_video_duration(video_path: Path) -> Optional[float]:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        return float(result.stdout.strip())
    except Exception:
        return None
comfyui_service = ComfyUIService()
merge_video_locks = {}
shot_image_batch_locks = set()
shot_video_batch_locks = set()


async def run_chapter_video_merge_task(task_id: str) -> None:
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            return

        task.status = "running"
        task.progress = 5
        task.current_step = "准备合并章节视频..."
        task.started_at = datetime.utcnow()
        db.commit()

        try:
            metadata = json.loads(task.metadata_json or "{}")
        except Exception:
            metadata = {}

        novel_id = task.novel_id
        chapter_id = task.chapter_id
        mode = metadata.get("mode") or "shots_only"
        video_variant = metadata.get("video_variant") or "draft"
        target_megapixels = metadata.get("target_megapixels")
        include_transitions = mode == "shots_with_transitions"
        selected_shot_ids = set(metadata.get("shot_ids") or [])

        chapter = db.query(Chapter).filter(Chapter.id == chapter_id, Chapter.novel_id == novel_id).first()
        if not chapter:
            raise RuntimeError("章节不存在")

        shots = ShotRepository(db).get_by_chapter(chapter_id)
        if selected_shot_ids:
            selected_chapter_shot_ids = {shot.id for shot in shots}
            invalid_shot_ids = selected_shot_ids - selected_chapter_shot_ids
            if invalid_shot_ids:
                raise RuntimeError("选择的分镜不属于当前章节")

        frozen_inputs = metadata.get("inputs") if isinstance(metadata.get("inputs"), list) else []
        generated_shots = (
            [
                (int(item["shot_index"]), item.get("video_url"))
                for item in sorted(frozen_inputs, key=lambda item: int(item["shot_index"]))
                if item.get("video_url")
            ]
            if frozen_inputs else
            [
                (shot.index, shot.hd_video_url if video_variant == "hd" else shot.video_url)
                for shot in shots
                if (shot.hd_video_url if video_variant == "hd" else shot.video_url) and (not selected_shot_ids or shot.id in selected_shot_ids)
            ]
        )
        if not generated_shots:
            raise RuntimeError("没有选中的分镜视频可以合并" if selected_shot_ids else "没有分镜视频可以合并")

        parsed_data = json.loads(chapter.parsed_data) if chapter.parsed_data else {}
        transition_videos = parsed_data.get("transition_videos") or {}
        valid_shots = []
        for shot_index, video_url in generated_shots:
            if video_url and video_url.startswith("/api/files/"):
                full_path = url_to_local_path(video_url)
                if full_path and Path(full_path).is_file():
                    valid_shots.append((shot_index, full_path))

        if not valid_shots:
            raise RuntimeError("视频文件不存在")

        task.progress = 20
        task.current_step = f"已找到 {len(valid_shots)} 个分镜视频，正在计算缓存签名..."
        db.commit()

        video_paths = [path for _, path in valid_shots]
        segments = []
        trans_paths = []
        for i, (shot_index, shot_path) in enumerate(valid_shots):
            segments.append({"kind": "shot", "key": str(shot_index), "path": shot_path})
            if include_transitions and i < len(valid_shots) - 1:
                from_index = shot_index
                to_index = valid_shots[i + 1][0]
                key = f"{from_index}-{to_index}"
                trans_url = transition_videos.get(key)
                trans_path = None
                if trans_url and trans_url.startswith("/api/files/"):
                    full_path = url_to_local_path(trans_url)
                    if full_path and Path(full_path).is_file():
                        trans_path = full_path
                        segments.append({"kind": "transition", "key": key, "path": full_path})
                trans_paths.append(trans_path)

        profile_key = f"{video_variant}:{target_megapixels}" if video_variant == "hd" else "draft"
        signature = await asyncio.to_thread(file_storage.get_video_merge_signature, f"{mode}:{profile_key}", segments)
        story_dir = file_storage._get_story_dir(novel_id)
        chapter_short = chapter_id[:8] if chapter_id else "unknown"
        output_dir = story_dir / f"chapter_{chapter_short}" / ("hd-merged-videos" if video_variant == "hd" else "merged-videos")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{mode}-{signature}.mp4"

        lock = merge_video_locks.setdefault(str(output_path), asyncio.Lock())
        async with lock:
            if output_path.is_file() and output_path.stat().st_size > 0:
                result = {"success": True, "message": f"使用上次合并结果，共 {len(segments)} 个视频片段"}
                cache_hit = True
            else:
                task.progress = 35
                task.current_step = f"正在合并 {len(segments)} 个视频片段..."
                db.commit()
                temp_path = output_dir / f".{mode}-{uuid.uuid4().hex}.tmp.mp4"
                try:
                    result = await file_storage.merge_videos(
                        video_paths,
                        str(temp_path),
                        trans_paths if include_transitions else None,
                    )
                    if result.get("success"):
                        os.replace(temp_path, output_path)
                finally:
                    if temp_path.exists():
                        temp_path.unlink()
                cache_hit = False

        if not result.get("success"):
            raise RuntimeError(result.get("message", "合并失败"))

        relative_path = str(output_path).replace(str(file_storage.base_dir), "").replace("\\", "/")
        video_url = f"/api/files/{relative_path.lstrip('/')}"
        all_shot_ids = {shot.id for shot in shots}
        valid_shot_ids = ({item.get("shot_id") for item in frozen_inputs} if frozen_inputs else {
            shot.id for shot in shots
            if (shot.hd_video_url if video_variant == "hd" else shot.video_url)
            and (not selected_shot_ids or shot.id in selected_shot_ids)
        })
        is_final_video = bool(all_shot_ids) and valid_shot_ids == all_shot_ids and len(valid_shots) == len(all_shot_ids)
        metadata.update({
            "cache_hit": cache_hit,
            "mode": mode,
            "video_variant": video_variant,
            "target_megapixels": target_megapixels,
            "video_url": video_url,
            "segments_count": len(segments),
            "shots_count": len(valid_shots),
            "total_shots_count": len(all_shot_ids),
            "is_final_video": is_final_video,
            "file_size": output_path.stat().st_size if output_path.exists() else None,
            "duration": _probe_video_duration(output_path),
        })
        if is_final_video:
            if video_variant == "hd":
                chapter.hd_final_video = video_url
            else:
                chapter.final_video = video_url
        task.status = "completed"
        task.progress = 100
        task.result_url = video_url
        task.error_message = None
        task.current_step = "合并完成（使用缓存）" if cache_hit else "合并完成"
        task.completed_at = datetime.utcnow()
        task.metadata_json = json.dumps(metadata, ensure_ascii=False)
        db.commit()
    except Exception as exc:
        print(f"[ChapterVideoMergeTask {task_id}] Error: {exc}")
        task = db.query(Task).filter(Task.id == task_id).first()
        if task:
            task.status = "failed"
            task.error_message = str(exc)
            task.current_step = "合并失败"
            task.completed_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


def enqueue_chapter_video_merge_task(task_id: str) -> None:
    payload = {"task_id": task_id}
    worker_manager.worker("chapter_video").enqueue(persistent_job(
        task_id,
        "app.api.shots:run_chapter_video_merge_task",
        payload,
        lambda: run_chapter_video_merge_task(**payload),
    ))


def resume_active_chapter_video_merges() -> None:
    db = SessionLocal()
    try:
        tasks = db.query(Task).filter(
            Task.type == "chapter_video",
            Task.status.in_(["pending", "running"]),
        ).order_by(Task.created_at.asc()).all()
        for task in tasks:
            enqueue_chapter_video_merge_task(task.id)
    finally:
        db.close()


class BatchShotImageRequest(BaseModel):
    shot_ids: list[str]
    skip_llm_when_prompt_exists: bool = True


class BatchShotVideoRequest(BaseModel):
    shot_ids: list[str]
    auto_complete_details: bool = True
    use_reference_audio: bool = True
    skip_llm_when_prompt_exists: bool = False
    force_rerun: bool = True
    auto_assemble: bool = True


class SemanticClipGenerateRequest(BaseModel):
    use_reference_audio: bool = True
    auto_merge: bool = True
    skip_llm_when_prompt_exists: bool = False
    clip_plan_revision: Optional[int] = None


def _safe_filename_part(value: str) -> str:
    value = str(value or "").strip()
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in value).strip("_") or "item"


def _parse_call_datetime(value: str):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _format_shanghai_filename_time(value) -> str:
    if not value:
        return "unknown_time"
    dt = value
    if isinstance(dt, str):
        dt = _parse_call_datetime(dt)
    if not dt:
        return "unknown_time"
    # Stored datetimes are UTC-naive in SQLite; filenames use local Shanghai time.
    return (dt + timedelta(hours=8)).strftime("%Y%m%d_%H%M%S")


def _format_llm_log_text(call: dict, log: Optional[LLMLog]) -> str:
    created_at = log.created_at if log else _parse_call_datetime(call.get("created_at"))
    request_info = log.request_info if log else None
    response = log.response if log else call.get("response") or ""
    system_prompt = log.system_prompt if log else ""
    user_prompt = log.user_prompt if log else ""
    error_message = log.error_message if log else ""
    lines = [
        "LLM 调用数据",
        "= " * 30,
        f"调用时间: {_format_shanghai_filename_time(created_at)}",
        f"步骤: #{call.get('step') or '-'} {call.get('title') or ''}".strip(),
        f"任务类型: {(log.task_type if log else call.get('task_type')) or '-'}",
        f"模板名称: {(log.prompt_template_name if log else call.get('prompt_template_name')) or '-'}",
        f"Provider: {(log.provider if log else '-')}",
        f"Model: {(log.model if log else '-')}",
        f"Status: {(log.status if log else call.get('status')) or '-'}",
        f"Used Proxy: {(log.used_proxy if log else '-')}",
        f"Duration: {(str(log.duration) + 's') if log and log.duration is not None else '-'}",
        f"Clip: {call.get('clip_index') or '-'}",
        f"Workflow Type: {call.get('workflow_type') or '-'}",
        f"Workflow Name: {call.get('workflow_name') or '-'}",
        f"匹配完整日志: {'yes' if log else 'no'}",
        "",
        "LLM参数",
        "-" * 40,
        request_info or "未找到完整 LLM 参数；该条仅来自当前分镜 video_director_plan.ai_calls 快照。",
        "",
        "System Prompt",
        "-" * 40,
        system_prompt or "-",
        "",
        "User Prompt",
        "-" * 40,
        user_prompt or "-",
        "",
        "LLM响应",
        "-" * 40,
        response or "-",
    ]
    if call.get("final_prompt"):
        lines.extend(["", "最终 Prompt", "-" * 40, call.get("final_prompt") or "-"])
    if error_message:
        lines.extend(["", "错误信息", "-" * 40, error_message])
    return "\n".join(lines) + "\n"


def _match_full_llm_log(db: Session, novel_id: str, chapter_id: str, call: dict, used_log_ids: set) -> Optional[LLMLog]:
    task_type = call.get("task_type")
    query = db.query(LLMLog).filter(LLMLog.novel_id == novel_id, LLMLog.chapter_id == chapter_id)
    if task_type:
        query = query.filter(LLMLog.task_type == task_type)
    if call.get("prompt_template_name"):
        query = query.filter(LLMLog.prompt_template_name == call.get("prompt_template_name"))
    candidates = query.order_by(LLMLog.created_at.asc()).all()
    candidates = [log for log in candidates if log.id not in used_log_ids]
    if not candidates:
        return None

    call_dt = _parse_call_datetime(call.get("created_at"))
    call_response = (call.get("response") or "").strip()
    if call_response:
        exact_matches = [log for log in candidates if (log.response or "").strip() == call_response]
        if exact_matches:
            candidates = exact_matches
    if call_dt:
        candidates.sort(key=lambda log: abs(((log.created_at or call_dt) - call_dt).total_seconds()))
    return candidates[0]
shot_image_generation_locks = {}


# ==================== 分镜图生成 ====================


def _safe_json_list(value):
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _get_shot_image_prompt_template(novel: Novel, template_repo: PromptTemplateRepository):
    template = None
    if novel.shot_image_prompt_template_id:
        template = template_repo.get_by_id(novel.shot_image_prompt_template_id)
    if not template:
        template = template_repo.get_default_system_template("shot_image_prompt")
    if not template:
        raise HTTPException(status_code=400, detail="未配置主分镜图提示词模板")
    return template


def _build_shot_image_reference_readiness(db: Session, novel: Novel, shot):
    shot_characters = _safe_json_list(shot.characters)
    shot_props = get_visual_prop_names(db, novel.id, _safe_json_list(shot.props))

    manifest = []
    picture_index = 1

    character_members = []
    missing_characters = []
    for name in shot_characters:
        character = (
            db.query(Character)
            .filter(Character.novel_id == novel.id, Character.name == name)
            .first()
        )
        if character and character.image_url and url_to_local_path(character.image_url):
            character_members.append(name)
        else:
            missing_characters.append(name)
    if character_members:
        manifest.append(
            {
                "picture_index": picture_index,
                "type": "MERGED_CHARACTER",
                "members": character_members,
            }
        )
        picture_index += 1

    missing_scenes = []
    if shot.scene:
        scene = (
            db.query(Scene)
            .filter(Scene.novel_id == novel.id, Scene.name == shot.scene)
            .first()
        )
        if scene and scene.image_url and url_to_local_path(scene.image_url):
            manifest.append(
                {
                    "picture_index": picture_index,
                    "type": "SCENE",
                    "name": shot.scene,
                }
            )
            picture_index += 1
        else:
            missing_scenes.append(shot.scene)

    prop_members = []
    missing_props = []
    for name in shot_props:
        prop = (
            db.query(Prop)
            .filter(Prop.novel_id == novel.id, Prop.name == name, Prop.existence == PROP_EXISTENCE_REAL)
            .first()
        )
        if prop and prop.image_url and url_to_local_path(prop.image_url):
            prop_members.append(name)
        else:
            missing_props.append(name)
    if prop_members:
        manifest.append(
            {
                "picture_index": picture_index,
                "type": "MERGED_PROP",
                "members": prop_members,
            }
        )

    return {
        "manifest": manifest,
        "available_reference_count": len(manifest),
        "available": {
            "characters": character_members,
            "scenes": [shot.scene] if shot.scene and not missing_scenes else [],
            "props": prop_members,
        },
        "missing": {
            "characters": missing_characters,
            "scenes": missing_scenes,
            "props": missing_props,
        },
    }


def _build_shot_image_reference_manifest(db: Session, novel: Novel, shot):
    return _build_shot_image_reference_readiness(db, novel, shot)["manifest"]


def _resolve_shot_image_workflow_type(db: Session, novel: Novel, shot, manifest=None) -> str:
    manifest = manifest if manifest is not None else _build_shot_image_reference_manifest(db, novel, shot)
    has_character = any(item.get("type") == "MERGED_CHARACTER" for item in manifest)
    has_scene = any(item.get("type") == "SCENE" for item in manifest)
    has_prop = any(item.get("type") == "MERGED_PROP" for item in manifest)

    if has_character and has_scene and has_prop:
        return "shot"
    if has_character and has_scene:
        return "shot_character_scene"
    if has_scene and has_prop:
        return "shot_scene_prop"
    if has_scene:
        return "shot_scene"
    return "shot"


def _build_shot_image_reference_bundle(db: Session, novel: Novel, shot):
    readiness = _build_shot_image_reference_readiness(db, novel, shot)
    available = readiness["available"]
    character_members = available["characters"]
    scene_names = available["scenes"]
    prop_members = available["props"]
    scene_name = shot.scene or ""
    scene_empty = len(scene_names) == 0

    return {
        "picture_1": {
            "type": "MERGED_CHARACTER",
            "members": character_members,
            "empty": len(character_members) == 0,
        },
        "picture_2": {"type": "SCENE", "name": scene_name, "empty": scene_empty},
        "picture_3": {
            "type": "MERGED_PROP",
            "members": prop_members,
            "empty": len(prop_members) == 0,
        },
    }


def _build_shot_image_prompt_input(db: Session, novel: Novel, shot, template_body: str) -> str:
    shot_characters = _safe_json_list(shot.characters)
    shot_props = get_visual_prop_names(db, novel.id, _safe_json_list(shot.props))
    shot_dialogues = _safe_json_list(shot.dialogues)
    visual_style, _ = get_style(db, novel, "character")

    payload = {
        "shot": {
            "id": shot.id,
            "index": shot.index,
            "description": shot.description or "",
            "video_description": shot.video_description or "",
            "characters": shot_characters,
            "scene": shot.scene or "",
            "props": shot_props,
            "dialogues": shot_dialogues,
        },
        "visual_style": visual_style,
    }

    if "reference_image_manifest" in template_body:
        payload["reference_image_manifest"] = _build_shot_image_reference_manifest(
            db, novel, shot
        )
    elif "reference_bundle" in template_body:
        payload["reference_bundle"] = _build_shot_image_reference_bundle(db, novel, shot)
    else:
        payload["reference_image_manifest"] = _build_shot_image_reference_manifest(db, novel, shot)

    return (
        "请基于以下已保存的 Shot 数据、正式视觉风格和参考图清单，"
        "生成可直接用于 Qwen-Image-Edit-2511 的主分镜图最终提示词。\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


async def _resolve_shot_image_prompt_text(
    db: Session,
    novel: Novel,
    shot,
    template_repo: PromptTemplateRepository,
    llm_service: LLMService,
    prompt_text: Optional[str],
):
    if prompt_text and prompt_text.strip():
        return prompt_text.strip(), "用户编辑的主分镜图提示词"

    template = _get_shot_image_prompt_template(novel, template_repo)
    visual_style, _ = get_style(db, novel, "character")
    fallback_prompt = f"{shot.description or '主分镜图'}\n{visual_style}"
    template_name = template.name
    user_content = _build_shot_image_prompt_input(db, novel, shot, template.template)
    result = await llm_service.chat_completion(
        system_prompt=template.template,
        user_content=user_content,
        temperature=0.3,
        max_tokens=4096,
        task_type="shot_image_prompt",
        prompt_template_name=template.name,
        novel_id=novel.id,
        chapter_id=shot.chapter_id,
    )
    if not result.get("success"):
        print(f"[GenerateShot] Prompt builder failed, fallback to shot description: {result.get('error') or result.get('message')}")
        return fallback_prompt, f"{template_name}（fallback）"
    final_prompt = (result.get("content") or "").strip()
    if not final_prompt:
        return fallback_prompt, f"{template_name}（fallback）"
    return final_prompt, template_name


@router.post(
    "/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/generate", response_model=dict
)
async def generate_shot_image(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    request: Optional[GenerateShotImageRequest] = None,
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    task_repo: TaskRepository = Depends(get_task_repo),
    workflow_repo: WorkflowRepository = Depends(get_workflow_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
    template_repo: PromptTemplateRepository = Depends(get_prompt_template_repo),
    llm_service: LLMService = Depends(get_llm_service),
):
    """为指定分镜生成图片（创建后台任务）"""
    lock_key = f"{novel_id}:{chapter_id}:{shot_id}"
    lock = shot_image_generation_locks.setdefault(lock_key, asyncio.Lock())
    if lock.locked():
        return {
            "success": True,
            "message": "该分镜正在解析提示词或创建生图任务",
            "data": {"taskId": None, "status": "generating", "promptText": None},
        }

    async with lock:
        try:
            return await _generate_shot_image_locked(
                novel_id=novel_id,
                chapter_id=chapter_id,
                shot_id=shot_id,
                request=request,
                db=db,
                novel_repo=novel_repo,
                chapter_repo=chapter_repo,
                task_repo=task_repo,
                workflow_repo=workflow_repo,
                shot_repo=shot_repo,
                template_repo=template_repo,
                llm_service=llm_service,
            )
        except CanonicalExecutionConflict as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail=str(exc))


async def _generate_shot_image_locked(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    request: Optional[GenerateShotImageRequest],
    db: Session,
    novel_repo: NovelRepository,
    chapter_repo: ChapterRepository,
    task_repo: TaskRepository,
    workflow_repo: WorkflowRepository,
    shot_repo: ShotRepository,
    template_repo: PromptTemplateRepository,
    llm_service: LLMService,
):
    return await _prepare_and_enqueue_shot_image_generation(
        novel_id=novel_id,
        chapter_id=chapter_id,
        shot_id=shot_id,
        request=request,
        db=db,
        novel_repo=novel_repo,
        chapter_repo=chapter_repo,
        task_repo=task_repo,
        workflow_repo=workflow_repo,
        shot_repo=shot_repo,
        template_repo=template_repo,
        llm_service=llm_service,
    )


async def _prepare_and_enqueue_shot_image_generation(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    request: Optional[GenerateShotImageRequest],
    db: Session,
    novel_repo: NovelRepository,
    chapter_repo: ChapterRepository,
    task_repo: TaskRepository,
    workflow_repo: WorkflowRepository,
    shot_repo: ShotRepository,
    template_repo: PromptTemplateRepository,
    llm_service: LLMService,
    existing_task: Optional[Task] = None,
    canonical_image_provenance: dict | None = None,
):
    # 获取章节
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)

    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    chapter_title = chapter.title

    # 获取小说
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    if not chapter.parsed_data and str(shot_id).isdigit():
        raise HTTPException(status_code=400, detail="章节未拆分分镜，请先完成章节拆分")

    # 从 shots 表查询分镜；兼容旧 API 按分镜序号传参。
    shot = _resolve_shot_by_id_or_index(shot_repo, chapter_id, shot_id)

    if not shot:
        if str(shot_id).isdigit():
            raise HTTPException(status_code=400, detail=f"分镜索引 {shot_id} 超出范围")
        raise HTTPException(status_code=404, detail=f"分镜 {shot_id} 不存在")

    shot_index = shot.index
    shot_description = shot.description
    resolved_shot_id = shot.id

    # The ordinary entry point shares the same START provenance as preparation.
    # Legacy main-image generation retains its existing behavior.
    canonical_image_provenance = canonical_image_provenance or state_provenance(shot, 1)

    # 检查是否已有进行中的任务
    active_task = task_repo.get_active_shot_task(novel_id, chapter_id, shot_index, "shot_image")
    if active_task and (not existing_task or active_task.id != existing_task.id):
        if canonical_image_provenance and (task_provenance(active_task) != canonical_image_provenance or shot.image_task_id != active_task.id):
            raise CanonicalExecutionConflict("CANONICAL_IMAGE_TASK_CONFLICT")
        return {
            "success": True,
            "message": "已有进行中的生成任务",
            "data": {"taskId": active_task.id, "status": active_task.status, "promptText": active_task.prompt_text},
        }

    reference_readiness = _build_shot_image_reference_readiness(db, novel, shot)
    if reference_readiness["available_reference_count"] == 0:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "SHOT_IMAGE_REFERENCES_NOT_READY",
                "message": "主分镜参考素材未准备，请先准备至少一个角色、场景或道具参考图片。",
                "available_reference_count": 0,
                "missing": reference_readiness["missing"],
            },
        )

    # 获取激活的分镜生图工作流
    shot_workflow_type = request.workflow_type if request and request.workflow_type else _resolve_shot_image_workflow_type(
        db, novel, shot, reference_readiness["manifest"]
    )
    workflow = workflow_repo.get_active_by_type(shot_workflow_type)

    if not workflow:
        raise HTTPException(status_code=400, detail=f"未配置{shot_workflow_type}分镜生图工作流")

    # 验证工作流节点映射配置
    is_valid, error_msg = TaskService.validate_workflow_node_mapping(workflow, shot_workflow_type)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    final_prompt, prompt_template_name = await _resolve_shot_image_prompt_text(
        db,
        novel,
        shot,
        template_repo,
        llm_service,
        request.prompt_text if request else None,
    )
    if canonical_image_provenance:
        db.refresh(shot)
        validate_image_provenance(shot, canonical_image_provenance)
        current_active = task_repo.get_active_shot_task(novel_id, chapter_id, shot_index, "shot_image")
        if current_active and (not existing_task or current_active.id != existing_task.id):
            if task_provenance(current_active) != canonical_image_provenance or shot.image_task_id != current_active.id:
                raise CanonicalExecutionConflict("CANONICAL_IMAGE_TASK_CONFLICT")
            return {"success": True, "data": {"taskId": current_active.id, "status": current_active.status}}
    # 使用 Repository 创建任务记录，或启动批量预创建的子任务。
    task = existing_task or task_repo.create_shot_image_task(
        novel_id=novel_id,
        chapter_id=chapter_id,
        shot_index=shot_index,
        chapter_title=chapter_title,
        workflow_id=workflow.id,
        workflow_name=workflow.name,
        shot_id=resolved_shot_id,
    )
    task.status = "pending"
    task.progress = 0
    task.current_step = "等待处理"
    task.workflow_id = workflow.id
    task.workflow_name = workflow.name
    task.shot_id = resolved_shot_id
    task.prompt_text = final_prompt
    if canonical_image_provenance:
        metadata = _safe_json_dict(task.metadata_json)
        metadata["canonical_image_provenance"] = canonical_image_provenance
        previous_image_task = db.query(Task).filter(Task.id == shot.image_task_id).first() if shot.image_task_id else None
        previous_url = _safe_json_dict(previous_image_task.metadata_json).get("canonical_image_previous_url") if previous_image_task and task_provenance(previous_image_task) == canonical_image_provenance else None
        metadata["canonical_image_previous_url"] = shot.image_url or local_path_to_url(shot.image_path) or previous_url
        task.metadata_json = json.dumps(metadata, ensure_ascii=False)
    task.description = f"{task.description}；提示词模板：{prompt_template_name}"
    shot = db.merge(shot)

    # 只有在物理参考校验和提示词解析成功后，才替换当前主分镜生成尝试。
    if not canonical_image_provenance:
        file_storage.delete_shot_image(novel_id, chapter_id, shot_index, shot_id=resolved_shot_id)
    shot.image_url = None
    shot.image_path = None
    shot.image_status = "generating"
    shot.image_task_id = task.id
    shot.shot_image_prompt = final_prompt
    db.commit()

    print(f"[GenerateShot] Created task {task.id} for shot {resolved_shot_id}")

    # 加入分镜图片专用 worker，避免批量生成时并发打 ComfyUI。
    generate_shot_task(
        task.id,
        novel_id,
        chapter_id,
        shot_index,
        final_prompt,
        workflow.id,
    )

    return {
        "success": True,
        "message": "分镜图生成任务已创建",
        "data": {"taskId": task.id, "status": "pending", "promptText": final_prompt},
    }


def enqueue_shot_image_batch_task(batch_task_id: str) -> None:
    if batch_task_id in shot_image_batch_locks:
        return
    shot_image_batch_locks.add(batch_task_id)
    payload = {"batch_task_id": batch_task_id}
    worker_manager.worker("shot_image_batch").enqueue(persistent_job(
        batch_task_id,
        "app.api.shots:run_shot_image_batch_task",
        payload,
        lambda: run_shot_image_batch_task(**payload),
    ))


async def _wait_for_shot_image_child_task(db: Session, child_task_id: str) -> str:
    for _ in range(720):
        db.expire_all()
        task = db.query(Task).filter(Task.id == child_task_id).first()
        if not task:
            return "failed"
        if task.status in {"completed", "failed", "cancelled"}:
            return task.status
        await asyncio.sleep(5)
    task = db.query(Task).filter(Task.id == child_task_id).first()
    if task and task.status in {"pending", "running"}:
        task.status = "failed"
        task.error_message = "等待分镜图生成完成超时"
        task.current_step = "任务超时"
        db.commit()
    return "failed"


async def run_shot_image_batch_task(batch_task_id: str) -> None:
    db = SessionLocal()
    try:
        batch_task = db.query(Task).filter(Task.id == batch_task_id).first()
        if not batch_task or batch_task.status == "cancelled":
            return

        metadata = _safe_json_dict(batch_task.metadata_json)
        skip_llm_when_prompt_exists = bool(metadata.get("skip_llm_when_prompt_exists", True))

        batch_task.status = "running"
        batch_task.started_at = batch_task.started_at or datetime.utcnow()
        batch_task.current_step = "批量分镜图生成中"
        db.commit()

        child_tasks = (
            db.query(Task)
            .filter(Task.parent_task_id == batch_task.id, Task.type == "shot_image")
            .order_by(Task.batch_order.asc(), Task.created_at.asc())
            .all()
        )
        total = len(child_tasks)
        completed = 0
        failed = 0
        cancelled = 0

        for index, child_task in enumerate(child_tasks, start=1):
            db.expire_all()
            batch_task = db.query(Task).filter(Task.id == batch_task_id).first()
            child_task = db.query(Task).filter(Task.id == child_task.id).first()
            if not batch_task or batch_task.status == "cancelled":
                remaining = db.query(Task).filter(
                    Task.parent_task_id == batch_task_id,
                    Task.type == "shot_image",
                    Task.status == "pending",
                ).all()
                for task in remaining:
                    task.status = "cancelled"
                    task.current_step = "批量任务已取消"
                    task.error_message = "批量任务已取消"
                db.commit()
                return
            if not child_task or child_task.status in {"completed", "cancelled"}:
                if child_task and child_task.status == "completed":
                    completed += 1
                elif child_task and child_task.status == "cancelled":
                    cancelled += 1
                continue
            if child_task.status == "failed":
                failed += 1
                continue
            if child_task.status == "running" and not child_task.comfyui_prompt_id:
                child_task.status = "pending"
                child_task.started_at = None
                child_task.current_step = "等待重新处理"
                db.commit()
            if child_task.status == "pending":
                shot = db.query(Shot).filter(Shot.id == child_task.shot_id).first()
                prompt_text = (shot.shot_image_prompt or "").strip() if shot and skip_llm_when_prompt_exists else None
                child_task.status = "running"
                child_task.started_at = child_task.started_at or datetime.utcnow()
                child_task.current_step = "准备提交分镜图工作流" if prompt_text else "正在生成分镜图提示词"
                batch_task.current_step = f"正在处理 {index}/{total}：{child_task.current_step}"
                db.commit()
                await _prepare_and_enqueue_shot_image_generation(
                    novel_id=child_task.novel_id,
                    chapter_id=child_task.chapter_id,
                    shot_id=child_task.shot_id,
                    request=GenerateShotImageRequest(prompt_text=prompt_text) if prompt_text else None,
                    db=db,
                    novel_repo=NovelRepository(db),
                    chapter_repo=ChapterRepository(db),
                    task_repo=TaskRepository(db),
                    workflow_repo=WorkflowRepository(db),
                    shot_repo=ShotRepository(db),
                    template_repo=PromptTemplateRepository(db),
                    llm_service=LLMService(),
                    existing_task=child_task,
                )

            status = await _wait_for_shot_image_child_task(db, child_task.id)
            if status == "completed":
                completed += 1
            elif status == "cancelled":
                cancelled += 1
            else:
                failed += 1
            batch_task = db.query(Task).filter(Task.id == batch_task_id).first()
            if batch_task:
                batch_task.progress = int(index / total * 100) if total else 100
                batch_task.current_step = f"已处理 {index}/{total} 个分镜"
                db.commit()

        batch_task = db.query(Task).filter(Task.id == batch_task_id).first()
        if batch_task:
            batch_task.status = "completed" if failed == 0 and cancelled == 0 else "failed"
            batch_task.progress = 100
            batch_task.completed_at = datetime.utcnow()
            batch_task.current_step = f"完成：成功 {completed}，失败 {failed}，取消 {cancelled}"
            batch_task.error_message = None if failed == 0 and cancelled == 0 else batch_task.current_step
            db.commit()
    except Exception as exc:
        batch_task = db.query(Task).filter(Task.id == batch_task_id).first()
        if batch_task:
            batch_task.status = "failed"
            batch_task.error_message = str(exc)
            batch_task.current_step = "批量生成失败"
            batch_task.completed_at = datetime.utcnow()
            db.commit()
        print(f"[ShotImageBatch] task {batch_task_id} failed: {exc}")
    finally:
        shot_image_batch_locks.discard(batch_task_id)
        db.close()


def resume_active_shot_image_batches() -> None:
    db = SessionLocal()
    try:
        active_batches = db.query(Task).filter(
            Task.type == "shot_image_batch",
            Task.status.in_(["pending", "running"]),
        ).all()
        for batch_task in active_batches:
            enqueue_shot_image_batch_task(batch_task.id)
    finally:
        db.close()


@router.post("/{novel_id}/chapters/{chapter_id}/shot-images/batch", response_model=dict)
async def generate_shot_images_batch(
    novel_id: str,
    chapter_id: str,
    data: BatchShotImageRequest,
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    task_repo: TaskRepository = Depends(get_task_repo),
    workflow_repo: WorkflowRepository = Depends(get_workflow_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
):
    """创建可在页面关闭后继续执行的分镜图批量生成任务。"""
    if not data.shot_ids:
        raise HTTPException(status_code=400, detail="请选择要生成的分镜")
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    validated_items = []
    for order, shot_id in enumerate(data.shot_ids, start=1):
        shot = shot_repo.get_by_id(shot_id)
        if not shot or shot.chapter_id != chapter_id:
            raise HTTPException(status_code=404, detail=f"分镜不存在：{shot_id}")

        existing_task = task_repo.get_active_shot_task(novel_id, chapter_id, shot.index, "shot_image")
        if existing_task and existing_task.parent_task_id:
            raise HTTPException(status_code=400, detail=f"分镜 {shot.index} 已在批量生成队列中")

        workflow = None
        if not existing_task:
            reference_readiness = _build_shot_image_reference_readiness(db, novel, shot)
            if reference_readiness["available_reference_count"] == 0:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "SHOT_IMAGE_REFERENCES_NOT_READY",
                        "message": f"分镜 {shot.index} 的主分镜参考素材未准备，请先准备至少一个角色、场景或道具参考图片。",
                        "shot_id": shot.id,
                        "available_reference_count": 0,
                        "missing": reference_readiness["missing"],
                    },
                )
            shot_workflow_type = _resolve_shot_image_workflow_type(
                db, novel, shot, reference_readiness["manifest"]
            )
            workflow = workflow_repo.get_active_by_type(shot_workflow_type)
            if not workflow:
                raise HTTPException(status_code=400, detail=f"未配置{shot_workflow_type}分镜生图工作流")
            is_valid, error_msg = TaskService.validate_workflow_node_mapping(workflow, shot_workflow_type)
            if not is_valid:
                raise HTTPException(status_code=400, detail=error_msg)

        validated_items.append({
            "order": order,
            "shot": shot,
            "existing_task": existing_task,
            "workflow": workflow,
        })

    batch_task = Task(
        type="shot_image_batch",
        status="pending",
        name="批量生成分镜图",
        description=f"为章节 '{chapter.title}' 批量生成 {len(data.shot_ids)} 个分镜图",
        novel_id=novel_id,
        chapter_id=chapter_id,
        progress=0,
        current_step="等待处理",
        metadata_json=json.dumps({
            "shot_ids": data.shot_ids,
            "skip_llm_when_prompt_exists": data.skip_llm_when_prompt_exists,
        }, ensure_ascii=False),
    )
    db.add(batch_task)
    db.flush()

    child_tasks = []
    for item in validated_items:
        order = item["order"]
        shot = item["shot"]
        existing_task = item["existing_task"]
        if existing_task:
            existing_task.parent_task_id = batch_task.id
            existing_task.batch_order = order
            child_tasks.append(existing_task)
            continue

        workflow = item["workflow"]
        task = Task(
            type="shot_image",
            name=f"生成分镜图: 镜{shot.index}",
            description=f"为章节 '{chapter.title}' 的分镜 {shot.index} 生成图片",
            novel_id=novel_id,
            chapter_id=chapter_id,
            shot_id=shot.id,
            status="pending",
            workflow_id=workflow.id,
            workflow_name=workflow.name,
            parent_task_id=batch_task.id,
            batch_order=order,
            current_step="等待批量处理",
        )
        db.add(task)
        child_tasks.append(task)

    db.flush()
    db.commit()
    enqueue_shot_image_batch_task(batch_task.id)
    return {
        "success": True,
        "message": f"已创建 {len(child_tasks)} 个分镜图生成任务",
        "data": {
            "batchTaskId": batch_task.id,
            "tasks": [{"taskId": task.id, "shotId": task.shot_id, "status": task.status} for task in child_tasks],
        },
    }


# ==================== 分镜视频生成 ====================


VIDEO_MODE_LABELS = {
    "SINGLE_FRAME": "单帧",
    "FIRST_LAST_FRAME": "首尾帧",
    "MULTI_KEYFRAME": "多关键帧",
}


def _safe_json_dict(value):
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _reject_legacy_video_execution_for_canonical(plan: dict) -> None:
    """Keep canonical Shots on the semantic Clip execution authority."""
    if plan.get("canonical_visual_plan") is True:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CANONICAL_SEMANTIC_LEGACY_EXECUTION_FORBIDDEN",
                "message": (
                    "Canonical semantic execution cannot use the legacy video generation endpoint; "
                    "replan historical Clip plans when required, then use semantic Clip execution."
                ),
            },
        )


def _resolve_shot_by_id_or_index(shot_repo: ShotRepository, chapter_id: str, shot_id_or_index: str):
    shot = shot_repo.get_by_id(shot_id_or_index)
    if shot and shot.chapter_id == chapter_id:
        return shot
    try:
        shot_index = int(shot_id_or_index)
    except (TypeError, ValueError):
        return None
    return shot_repo.get_by_chapter_and_index(chapter_id, shot_index)


def _get_video_workflow_capability(workflow: Optional[Workflow]) -> dict:
    extension = _safe_json_dict(workflow.extension if workflow else None)
    max_clip_duration = int(extension.get("max_clip_duration") or extension.get("max_seconds") or 15)
    workflow_mode = str(extension.get("mode") or extension.get("video_mode") or "").lower()
    return {
        "single_frame": extension.get("single_frame", True),
        "first_last_frame": extension.get("first_last_frame", True),
        "multi_keyframe": extension.get("multi_keyframe", True),
        "max_clip_duration": max_clip_duration,
        "max_keyframes_per_generation": int(extension.get("max_keyframes_per_generation") or 2),
        "first_last_frame_capability": {
            "enabled": True,
            "max_clip_duration": max_clip_duration,
            "frame_count": 2,
        },
        "multi_keyframe_capability": {
            "enabled": True,
            "max_clip_duration": max_clip_duration,
            "supported_frame_counts": [3, 4],
            "available_workflows": [
                {"frame_count": 3, "workflow_key": "MINIMAX_H3_3FRAME", "workflow_type": "three_frame_video"},
                {"frame_count": 4, "workflow_key": "MINIMAX_H3_4FRAME", "workflow_type": "four_frame_video"},
            ],
        },
        "workflow_name": workflow.name if workflow else "",
        "workflow_mode": workflow_mode,
    }


def _get_video_mode_template(novel: Novel, template_repo: PromptTemplateRepository):
    template = None
    if novel.video_mode_recommender_prompt_template_id:
        template = template_repo.get_by_id(novel.video_mode_recommender_prompt_template_id)
    if not template:
        template = template_repo.get_default_system_template("video_mode_recommender")
    if not template:
        raise HTTPException(status_code=400, detail="未配置视频生成模式推荐提示词模板")
    return template


def _build_video_mode_user_content(shot, workflow_capability: dict) -> str:
    continuity_requirements = _build_continuity_requirements(shot)
    payload = {
        "shot": {
            "id": shot.id,
            "index": shot.index,
            "description": shot.description or "",
            "video_description": shot.video_description or "",
            "characters": _safe_json_list(shot.characters),
            "scene": shot.scene or "",
            "props": _safe_json_list(shot.props),
            "duration": shot.duration or 4,
            "continuity_mode": shot.continuity_mode or "NORMAL",
            "dialogues": _safe_json_list(shot.dialogues),
        },
        "workflow_capability": workflow_capability,
        "continuity_requirements": continuity_requirements,
    }
    return "请根据以下正式保存的 Shot 与 Workflow 能力推荐视频生成模式。\n\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def _build_continuity_requirements(shot) -> dict:
    is_continuous_take = (shot.continuity_mode or "NORMAL") == "CONTINUOUS_TAKE"
    if is_continuous_take:
        return {
            "mode": "CONTINUOUS_TAKE",
            "label": "一镜到底（禁止切镜）",
            "meaning": "This is a shot-level editing constraint, not a video generation mode.",
            "requirements": [
                "The entire Shot must read as one uninterrupted continuous take.",
                "No cuts, no hidden edits, no abrupt camera repositioning, no jump cuts, no shot/reverse-shot grammar.",
                "Camera movement, subject blocking, eyelines, light, environment, and action state must remain physically continuous.",
                "If the Shot is split into multiple generation clips, each Clip boundary must preserve the previous Clip ending state as the next Clip starting state.",
                "Keyframes must be states along one continuous camera path, not independent compositions.",
                "Transitions must describe physically plausible movement from one keyframe to the next.",
            ],
        }
    return {
        "mode": "NORMAL",
        "label": "普通镜头（允许切镜）",
        "meaning": "Cuts or composition changes are allowed when they serve the Shot, but identity, space, and story continuity still matter.",
        "requirements": [
            "Visible changes may use normal cinematic shot grammar when justified by the Shot.",
            "Do not confuse NORMAL with permission to break character identity, geography, props, or dialogue continuity.",
        ],
    }


def _parse_recommended_mode(content: str, duration: int, workflow_capability: dict) -> str:
    try:
        parsed = json.loads(content.strip())
    except Exception:
        start = content.find("{")
        end = content.rfind("}")
        parsed = json.loads(content[start:end + 1]) if start >= 0 and end > start else {}
    mode = parsed.get("recommended_mode")
    if mode not in VIDEO_MODE_LABELS:
        mode = "MULTI_KEYFRAME" if duration > workflow_capability["max_clip_duration"] else "SINGLE_FRAME"
    if mode == "FIRST_LAST_FRAME" and duration > workflow_capability["max_clip_duration"]:
        mode = "MULTI_KEYFRAME"
    return mode


def _build_video_mode_reason(shot, mode: str, workflow_capability: dict) -> str:
    duration = shot.duration or 4
    max_clip_duration = workflow_capability["max_clip_duration"]
    if duration > max_clip_duration:
        return f"{duration} 秒超过当前 Workflow 单次最大 {max_clip_duration} 秒，V1 请使用多关键帧拆分为多个 Clip。"
    if mode == "SINGLE_FRAME":
        return f"{duration} 秒不超过当前 Workflow 单次最大 {max_clip_duration} 秒，适合由主分镜图驱动的简单 Shot。"
    if mode == "FIRST_LAST_FRAME":
        return f"{duration} 秒不超过当前 Workflow 单次最大 {max_clip_duration} 秒，适合用起点与终点共同约束画面变化。"
    return "该 Shot 存在较强连续性或多阶段视觉变化，建议使用多关键帧保持画面稳定。"


def _build_clip_plan(duration: int, max_clip_duration: int) -> list:
    clips = []
    start = 0
    index = 1
    while start < duration:
        end = min(duration, start + max_clip_duration)
        clips.append({
            "clip_index": index,
            "start_time": start,
            "end_time": end,
            "status": "PENDING",
        })
        start = end
        index += 1
    return clips


def _build_execution_windows(duration: int, max_clip_duration: int) -> list:
    return [
        {
            "window_index": clip["clip_index"],
            "start_time": clip["start_time"],
            "end_time": clip["end_time"],
        }
        for clip in _build_clip_plan(duration, max_clip_duration)
    ]


def _execution_windows_match_duration(execution_windows: list, duration: int, max_clip_duration: int) -> bool:
    if not execution_windows:
        return False
    expected_windows = _build_execution_windows(duration, max_clip_duration)
    if len(execution_windows) != len(expected_windows):
        return False
    previous_end = 0.0
    for index, current in enumerate(execution_windows, 1):
        if int(current.get("window_index") or 0) != index:
            return False
        start = float(current.get("start_time") or 0)
        end = float(current.get("end_time") or 0)
        if abs(start - previous_end) > 1e-6:
            return False
        if end <= start or end - start > max_clip_duration + 1e-6:
            return False
        previous_end = end
    if abs(previous_end - float(duration)) > 1e-6:
        return False
    return True


def _build_first_last_clip_plan(duration: int) -> list:
    return [{
        "clip_index": 1,
        "start_time": 0,
        "end_time": duration,
        "frame_count": 2,
        "selected_frame_count": 2,
        "workflow_key": "MINIMAX_H3_FIRST_LAST_FRAME",
        "workflow_type": "first_last_video",
        "keyframe_indexes": [1, 2],
        "status": "PENDING",
    }]


def _build_legacy_keyframes_from_plan(shot, keyframes: list) -> list:
    return [
        {
            "frame_index": position,
            "plan_keyframe_index": keyframe.get("index"),
            "time_seconds": keyframe.get("time_seconds"),
            "description": keyframe.get("description") or shot.description or "",
            "image_url": keyframe.get("image_url"),
            "image_task_id": keyframe.get("image_task_id"),
            "reference_image_url": None,
            "reference_mode": "auto_select",
        }
        for position, keyframe in enumerate([keyframe for keyframe in keyframes if keyframe.get("role") != "START"])
    ]


def _get_video_director_keyframe_image_url(shot, keyframe: dict) -> Optional[str]:
    if not isinstance(keyframe, dict):
        return None
    if keyframe.get("role") == "START":
        return shot.image_url
    if keyframe.get("image_url"):
        return keyframe.get("image_url")

    try:
        legacy_keyframes = json.loads(shot.keyframes) if shot.keyframes else []
    except Exception:
        legacy_keyframes = []
    for legacy_keyframe in legacy_keyframes:
        if not isinstance(legacy_keyframe, dict):
            continue
        plan_keyframe_index = legacy_keyframe.get("plan_keyframe_index")
        if plan_keyframe_index is None:
            continue
        try:
            if int(plan_keyframe_index) == int(keyframe.get("index") or -1):
                return legacy_keyframe.get("image_url")
        except Exception:
            continue
    return None


def _build_minimal_keyframes(shot, mode: str, max_clip_duration: int) -> list:
    duration = shot.duration or 4
    if mode == "SINGLE_FRAME":
        return []
    if mode == "FIRST_LAST_FRAME":
        return [
            {"index": 1, "time_seconds": 0, "role": "START", "description": None},
            {"index": 2, "time_seconds": duration, "role": "END", "description": shot.video_description or shot.description or ""},
        ]
    keyframes = []
    time_seconds = 0
    index = 1
    while time_seconds < duration:
        keyframes.append({
            "index": index,
            "time_seconds": time_seconds,
            "role": "START" if time_seconds == 0 else "INTERMEDIATE",
            "description": None if time_seconds == 0 else shot.video_description or shot.description or "",
        })
        time_seconds = min(duration, time_seconds + max_clip_duration)
        index += 1
    keyframes.append({
        "index": index,
        "time_seconds": duration,
        "role": "END",
        "description": shot.video_description or shot.description or "",
    })
    return keyframes


def _merge_video_director_plan(shot, plan_updates: dict) -> dict:
    plan = _safe_json_dict(shot.video_director_plan)
    plan.update({key: value for key, value in plan_updates.items() if value is not None})
    return plan


def _validate_multi_keyframe_plan_for_execution(shot, plan: dict) -> tuple[bool, str, Optional[int]]:
    window_plans = plan.get("window_plans") if isinstance(plan.get("window_plans"), list) else []
    execution_windows = plan.get("execution_windows") if isinstance(plan.get("execution_windows"), list) else []
    keyframes = plan.get("keyframes") if isinstance(plan.get("keyframes"), list) else []
    workflow_capability = plan.get("workflow_capability") if isinstance(plan.get("workflow_capability"), dict) else {}
    max_clip_duration = int(workflow_capability.get("max_clip_duration") or 15)
    duration = int(shot.duration or 4)

    if not execution_windows:
        return False, "多关键帧模式缺少 execution_windows，请先完成 #08 关键帧时间轴规划。", None
    if not window_plans:
        return False, "多关键帧模式缺少 window_plans，请先完成 #08 关键帧时间轴规划。", None
    if len(window_plans) != len(execution_windows):
        return False, "window_plans 数量与 execution_windows 不一致，请重新规划关键帧时间轴。", None
    if not _execution_windows_match_duration(execution_windows, duration, max_clip_duration):
        return False, f"execution_windows 与当前 Shot 时长 {duration}s 不一致，请重新规划关键帧时间轴。", None

    keyframes_by_index = {
        int(kf.get("index")): kf
        for kf in keyframes
        if isinstance(kf, dict) and kf.get("index") is not None
    }

    first_frame_count = None
    for plan_item in window_plans:
        frame_count = int(plan_item.get("selected_frame_count") or 0)
        if frame_count not in {3, 4}:
            return False, "每个执行 Clip 必须选择 3 帧或 4 帧 Workflow。", None
        if first_frame_count is None:
            first_frame_count = frame_count

        keyframe_indexes = plan_item.get("keyframe_indexes") if isinstance(plan_item.get("keyframe_indexes"), list) else []
        if len(keyframe_indexes) != frame_count:
            return False, f"Clip {plan_item.get('window_index')} 的 keyframe_indexes 数量与 selected_frame_count 不一致。", None
        for keyframe_index in keyframe_indexes:
            try:
                numeric_index = int(keyframe_index)
            except Exception:
                return False, f"Clip {plan_item.get('window_index')} 包含无效 Keyframe index。", None
            keyframe = keyframes_by_index.get(numeric_index)
            if not keyframe:
                return False, f"Clip {plan_item.get('window_index')} 引用了不存在的 Keyframe {numeric_index}。", None
            if numeric_index == 1 and keyframe.get("role") == "START":
                continue
            if not keyframe.get("image_url"):
                return False, f"Keyframe {numeric_index} 尚未生成图片，请先生成缺失关键帧图。", None

    return True, "", first_frame_count


def _get_keyframe_planner_template(novel: Novel, template_repo: PromptTemplateRepository):
    template = None
    if novel.keyframe_planner_prompt_template_id:
        template = template_repo.get_by_id(novel.keyframe_planner_prompt_template_id)
    if not template:
        template = template_repo.get_default_system_template("keyframe_planner")
    if not template:
        raise HTTPException(status_code=400, detail="未配置关键帧规划提示词模板")
    return template


def _build_keyframe_planner_user_content(shot, plan: dict, workflow_capability: dict | None = None, previous_failures: list = None, *, attention_catalog: list | None = None) -> str:
    shot_dialogues = _safe_json_list(shot.dialogues)
    dialogue_timeline_source, _, dialogue_timeline_status = build_dialogue_timeline(
        {"start_time": 0, "end_time": shot.duration or 4},
        shot_dialogues,
        _safe_json_list(shot.characters),
    )
    existing_keyframes = [
        {
            "index": keyframe.get("index"),
            "role": keyframe.get("role"),
            "time_seconds": keyframe.get("time_seconds"),
        }
        for keyframe in (plan.get("keyframes") or [])
        if isinstance(keyframe, dict)
    ]
    payload = {
        "shot": {
            "id": shot.id,
            "index": shot.index,
            "description": shot.description or "",
            "video_description": shot.video_description or "",
            "characters": _safe_json_list(shot.characters),
            "scene": shot.scene or "",
            "props": _safe_json_list(shot.props),
            "duration": shot.duration or 4,
            "continuity_mode": shot.continuity_mode or "NORMAL",
            "dialogues": shot_dialogues,
        },
        "dialogue_timeline_source": dialogue_timeline_source,
        "dialogue_timeline_status": dialogue_timeline_status,
        "visual_intent": plan.get("visual_intent") or "",
        "existing_keyframes": existing_keyframes,
        "existing_keyframes_policy": "旧规划仅作为非权威 index/role/time_seconds 结构参考；旧 description 不得覆盖 dialogue_timeline_source 或约束新的视觉状态。",
        "continuity_requirements": _build_continuity_requirements(shot),
        "requirements": {
            "output_top_level_keys": ["keyframes", "visual_attention"],
            "canonical_planner_rule": "规划 Shot 级 canonical visual states；不得规划 Clip/window、workflow 或物理参考槽。",
        },
        "character_catalog": attention_catalog or [],
    }
    if previous_failures:
        payload["previous_failed_attempts"] = previous_failures
        payload["retry_instruction"] = (
            "上一次 #08 输出未通过程序校验。previous_failed_attempts 中的 violations 是已发现问题，"
            "不是完整错误列表。请先修复所有已报告 violations，再重新审查整个 candidate plan，"
            "逐个检查所有 Visual States，并主动修复任何未被 previous failure 明确列出的 "
            "speech-authority 或 speech-event narrative contamination；返回一份完整、整体重新验证后的 "
            "canonical plan。不要补造窗口、Clip 或 workflow 字段。"
        )
    return "请根据 Shot 的叙事和有意义的视觉节拍，规划 canonical Director visual states。时长仅作上下文，不得换算为固定帧数。\n\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def _get_official_dialogue_timeline(db: Session, shot, fallback: list) -> list:
    if not fallback:
        return []
    plan = _safe_json_dict(shot.video_director_plan)
    persisted = plan.get("dialogue_timeline_source")
    if isinstance(persisted, list) and _timeline_matches_shot_dialogues(persisted, fallback) and _timeline_is_non_overlapping(persisted):
        return persisted
    logs = db.query(LLMLog).filter(
        LLMLog.chapter_id == shot.chapter_id,
        LLMLog.task_type == "keyframe_planner",
    ).order_by(LLMLog.created_at.desc()).all()
    for log in logs:
        try:
            payload = json.loads((log.user_prompt or "").split("\n\n", 1)[-1])
        except (TypeError, json.JSONDecodeError):
            continue
        if payload.get("shot", {}).get("id") != shot.id:
            continue
        timeline = payload.get("dialogue_timeline_source")
        if isinstance(timeline, list) and _timeline_matches_shot_dialogues(timeline, fallback) and _timeline_is_non_overlapping(timeline):
            return timeline
    return fallback


def _attention_replan_source(db, novel, shot, template_repo):
    """Read semantic authority only; no FULL timeline persistence or physical slots."""
    plan = _safe_json_dict(shot.video_director_plan)
    if plan.get("canonical_visual_plan") is not True or not plan.get("keyframes"):
        raise HTTPException(status_code=400, detail="ATTENTION_REPLAN_REQUIRES_CANONICAL_VISUAL_STATES")
    template = template_repo.get_default_system_template("visual_attention_replan")
    if not template:
        raise HTTPException(status_code=400, detail="未配置视觉关注重规划提示词模板")
    catalog, findings = character_catalog(
        _safe_json_list(shot.characters), CharacterRepository(db).list_by_novel(novel.id),
    )
    fallback, _, timeline_status = build_dialogue_timeline(
        {"start_time": 0, "end_time": shot.duration or 4},
        _safe_json_list(shot.dialogues), _safe_json_list(shot.characters),
    )
    timeline = _get_official_dialogue_timeline(db, shot, fallback)
    physical_fields = {
        "image_url", "imageUrl", "image_path", "image_task_id", "prompt_text", "source",
        "provenance", "reference_image_url", "reference_mode", "generated_by_task_id",
    }
    payload = {
        "operation": "ATTENTION_REPLAN",
        "shot": {
            "id": shot.id, "index": shot.index, "description": shot.description or "",
            "video_description": shot.video_description or "", "duration": shot.duration or 4,
            "characters": _safe_json_list(shot.characters), "scene": shot.scene or "",
            "props": _safe_json_list(shot.props), "continuity_mode": shot.continuity_mode or "NORMAL",
            "dialogues": _safe_json_list(shot.dialogues),
        },
        "visual_intent": plan.get("visual_intent") or "",
        "existing_canonical_visual_states": [
            {key: deepcopy(value) for key, value in state.items() if key not in physical_fields}
            for state in plan["keyframes"]
        ],
        "existing_canonical_transitions": [
            {key: deepcopy(value) for key, value in transition.items() if key not in physical_fields}
            for transition in plan.get("transitions") or []
        ],
        "canonical_state_policy": "authoritative read-only; plan visual_attention only; no replacement keyframes",
        "dialogue_timeline_source": timeline,
        "dialogue_timeline_status": plan.get("dialogue_timeline_status") or timeline_status,
        "speaker_bindings": [{
            "dialogue_id": item.get("id") or item.get("dialogue_id"), "speaker": item.get("speaker"),
            "character_id": next((entry["character_id"] for entry in catalog
                                   if entry["character_name"] == item.get("speaker")), None),
        } for item in timeline],
        "character_catalog": catalog,
        "continuity_requirements": _build_continuity_requirements(shot),
        "requirements": {"output_top_level_keys": ["visual_attention"]},
    }
    template_sha = sha256(template.template.encode()).hexdigest()
    source_sha = attention_source_sha256({
        "input": payload, "template_id": template.id, "template_sha256": template_sha,
        "prior_attention": plan.get("visual_attention"),
    })
    return plan, template, payload, source_sha, template_sha, findings


def _commit_attention_plan(db, shot, plan):
    """Compare-and-swap the fresh JSON; never overwrite another request's plan."""
    source_fields = ("chapter_id", "index", "description", "video_description", "characters",
                     "scene", "props", "duration", "continuity_mode", "dialogues", "video_director_plan")
    filters = [getattr(Shot, field) == getattr(shot, field) for field in source_fields]
    with db.no_autoflush:
        count = db.query(Shot).filter(Shot.id == shot.id, *filters).update(
            {Shot.video_director_plan: json.dumps(plan, ensure_ascii=False)}, synchronize_session=False,
        )
    if count != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="ATTENTION_SOURCE_CHANGED")
    db.commit()
    db.refresh(shot)


def _attention_plan_with_call(plan, call):
    # Reuse the established log shape without dirtying the ORM object before CAS.
    return append_video_ai_call(SimpleNamespace(video_director_plan=json.dumps(plan, ensure_ascii=False)), call)


def _record_attention_failure(db, shot, call):
    db.rollback()
    db.refresh(shot)
    plan = _safe_json_dict(shot.video_director_plan)
    try:
        _commit_attention_plan(db, shot, _attention_plan_with_call(plan, {**call, "status": call.get("status") or "error"}))
    except HTTPException as exc:
        if exc.status_code != 409:
            raise
        # A competing writer takes precedence; the underlying LLM log remains available.
        db.rollback()


def _check_active_attention_consumers(db, shot, plan, edges, new_authority=None):
    affected = {clip["clip_index"] for clip in plan.get("clip_plan") or []
                if clip_attention_transition_edges(plan, clip) & edges or (
                    new_authority is not None and effective_transition_attention(
                        plan.get("visual_attention"), clip["start_time"], clip["end_time"], shot.duration or 4,
                    ) != effective_transition_attention(
                        new_authority, clip["start_time"], clip["end_time"], shot.duration or 4,
                    )
                )}
    try:
        ensure_no_active_canonical_clip_tasks(db, shot.id, plan, affected)
    except CanonicalExecutionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))


def _require_attention_execution_freshness(plan, clip=None):
    try:
        require_current_attention_transitions(plan, clip)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


async def _replan_visual_attention(db, novel, chapter, shot, template_repo, llm_service):
    plan, template, payload, source_sha, template_sha, findings = _attention_replan_source(
        db, novel, shot, template_repo,
    )
    call = {
        "step": "08", "task_type": "keyframe_planner", "prompt_template_name": template.name,
        "input_summary": f"Shot {shot.index} · ATTENTION_REPLAN",
        "parsed_result": {"operation": "ATTENTION_REPLAN", "source_input_sha256": source_sha,
                          "template_id": template.id, "template_sha256": template_sha},
    }
    try:
        result = await llm_service.chat_completion(
            system_prompt=template.template,
            user_content="请基于以下只读 canonical authority 重新规划 visual_attention。\n\n" + json.dumps(payload, ensure_ascii=False, indent=2),
            temperature=0.3, max_tokens=2500, response_format="json_object",
            task_type="keyframe_planner", prompt_template_name=template.name,
            novel_id=novel.id, chapter_id=chapter.id,
        )
    except Exception as exc:
        _record_attention_failure(db, shot, {**call, "response": str(exc), "error_message": str(exc)})
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    call["response"] = result.get("content") or result.get("error") or ""
    if not result.get("success"):
        _record_attention_failure(db, shot, {**call, "error_message": result.get("error") or "Attention planning failed"})
        raise HTTPException(status_code=500, detail=result.get("error") or "Attention planning failed")
    try:
        normalized = normalize_attention_replan_response(
            _parse_keyframe_planner_content(result.get("content") or "{}"), payload["character_catalog"], payload["shot"]["duration"],
        )
    except (ValueError, TypeError) as exc:
        _record_attention_failure(db, shot, {**call, "error_message": str(exc)})
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # End the read transaction held during await and reload all source identities.
    db.rollback()
    db.expire_all()
    db.refresh(shot)
    db.refresh(novel)
    try:
        fresh, _, _, current_sha, _, _ = _attention_replan_source(db, novel, shot, template_repo)
    except HTTPException as exc:
        raise HTTPException(status_code=409, detail="ATTENTION_SOURCE_CHANGED") from exc
    if current_sha != source_sha:
        _record_attention_failure(db, shot, {**call, "error_message": "ATTENTION_SOURCE_CHANGED"})
        raise HTTPException(status_code=409, detail="ATTENTION_SOURCE_CHANGED")
    edges = changed_attention_edges(fresh, normalized["authority"], shot.duration or 4)
    _check_active_attention_consumers(db, shot, fresh, edges, normalized["authority"])
    updated = merge_attention_update(fresh, normalized, shot.duration or 4, findings)
    call["parsed_result"].update(status=normalized["status"], visual_attention=normalized["authority"])
    _commit_attention_plan(db, shot, _attention_plan_with_call(updated, call))
    return {"success": True, "data": _safe_json_dict(shot.video_director_plan)}


def _timeline_is_non_overlapping(timeline: list) -> bool:
    ordered = sorted(
        (item for item in timeline if isinstance(item, dict)),
        key=lambda item: float(item.get("start_time") or 0),
    )
    previous_end = None
    for item in ordered:
        try:
            start = float(item.get("start_time"))
            end = float(item.get("end_time"))
        except (TypeError, ValueError):
            return False
        if end <= start or (previous_end is not None and start < previous_end):
            return False
        previous_end = end
    return bool(ordered)


def _timeline_matches_shot_dialogues(timeline: list, shot_timeline: list) -> bool:
    if not isinstance(timeline, list) or not timeline:
        return False
    official_by_id = {
        str(item.get("id")): item
        for item in timeline
        if isinstance(item, dict) and item.get("id") is not None
    }
    for expected in shot_timeline:
        official = official_by_id.get(str(expected.get("id")))
        if not official or str(official.get("text") or "").strip() != str(expected.get("text") or "").strip():
            return False
        try:
            if float(official["end_time"]) <= float(official["start_time"]):
                return False
        except (KeyError, TypeError, ValueError):
            return False
    return True


def _mark_video_director_planning_failed(shot, shot_repo: ShotRepository, plan: dict, message: str) -> None:
    plan["task_error_message"] = message
    plan["error_message"] = message
    shot_repo.update(shot, video_director_plan=plan, video_status="failed", video_task_id=None)


def _parse_keyframe_planner_content(content: str) -> dict:
    try:
        return json.loads(content.strip())
    except Exception:
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            return json.loads(content[start:end + 1])
        raise


def _normalize_keyframe_planner_result(parsed: dict, execution_windows: list | None, duration: int, visual_style: str = "") -> tuple[list, list, dict]:
    """Normalize canonical Shot-level Director states; legacy windows are ignored."""
    if not isinstance(parsed, dict):
        raise ValueError("#08 返回必须是 JSON Object")
    raw_keyframes = parsed.get("keyframes") if isinstance(parsed.get("keyframes"), list) else []
    if not raw_keyframes:
        raise ValueError("#08 返回缺少 keyframes")

    normalized_keyframes = []
    seen_keyframe_indexes = set()
    seen_times = set()
    previous_time = None
    start_count = 0
    start_time = None
    end_count = 0
    for idx, keyframe in enumerate(raw_keyframes, 1):
        if not isinstance(keyframe, dict):
            raise ValueError("keyframes 中存在无效对象")
        raw_index = keyframe.get("index")
        if isinstance(raw_index, bool) or not isinstance(raw_index, int):
            raise ValueError(f"Keyframe {idx} index 无效")
        keyframe_index = raw_index
        if keyframe_index < 1:
            raise ValueError(f"Keyframe {keyframe_index} index 必须为正整数")
        if keyframe_index in seen_keyframe_indexes:
            raise ValueError(f"keyframes 包含重复 index {keyframe_index}")
        seen_keyframe_indexes.add(keyframe_index)
        try:
            time_seconds = float(keyframe.get("time_seconds"))
        except (TypeError, ValueError):
            raise ValueError(f"Keyframe {keyframe_index} time_seconds 无效")
        if not math.isfinite(time_seconds) or time_seconds < 0 or time_seconds > float(duration):
            raise ValueError(f"Keyframe {keyframe_index} time_seconds 无效或超出 Shot 时长")
        if time_seconds in seen_times:
            raise ValueError(f"keyframes 包含重复 time_seconds {time_seconds}")
        if previous_time is not None and time_seconds <= previous_time:
            raise ValueError("keyframes time_seconds 必须严格递增")
        seen_times.add(time_seconds)
        previous_time = time_seconds
        role = keyframe.get("role")
        if role not in {"START", "INTERMEDIATE", "END"}:
            raise ValueError(f"Keyframe {keyframe_index} role 无效")
        if role == "START":
            start_count += 1
            start_time = time_seconds
        if role == "END":
            end_count += 1
            if time_seconds != float(duration):
                raise ValueError("END keyframe time_seconds 必须等于 Shot duration")
        if not isinstance(keyframe.get("timed_visual_target"), bool):
            raise ValueError(f"Keyframe {keyframe_index} timed_visual_target 必须是 boolean")
        if role == "START" and keyframe["timed_visual_target"] is True:
            raise ValueError("START keyframe timed_visual_target 必须为 false")
        normalized_keyframes.append({
            "index": keyframe_index,
            "time_seconds": time_seconds,
            "role": role,
            "description": strip_embedded_visual_style(keyframe.get("description") or keyframe.get("visual_description") or "", visual_style),
            "timed_visual_target": keyframe["timed_visual_target"],
            **{field: keyframe[field] for field in ("image_url", "image_task_id", "prompt_text") if keyframe.get(field) is not None},
        })
    if start_count != 1:
        raise ValueError("canonical keyframes 必须且只能包含一个 START")
    if start_time != 0:
        raise ValueError("START keyframe time_seconds 必须为 0")
    if end_count > 1:
        raise ValueError("canonical keyframes 最多包含一个 END")

    for keyframe in normalized_keyframes:
        require_speech_neutral_visual_text(
            keyframe.get("description"),
            code="VISUAL_STATE_SPEECH_AUTHORITY_VIOLATION",
            field="description",
            state_index=keyframe.get("index"),
        )

    validation = {"passed": True, "blocking": []}
    return normalized_keyframes, [], validation


def _preserve_matching_keyframe_assets(keyframes: list[dict], existing_plan: dict, legacy_keyframes: list[dict]) -> list[dict]:
    """Carry image provenance only when a replanned indexed state is unchanged."""
    canonical = {
        int(item["index"]): item for item in existing_plan.get("keyframes", [])
        if isinstance(item, dict) and item.get("index") is not None
    }
    legacy = {
        int(item.get("plan_keyframe_index")): item for item in legacy_keyframes
        if isinstance(item, dict) and item.get("plan_keyframe_index") is not None
    }
    result = []
    for keyframe in keyframes:
        old = canonical.get(int(keyframe["index"]))
        old_legacy = legacy.get(int(keyframe["index"]))
        if old and (
            old.get("role") == keyframe.get("role")
            and old.get("time_seconds") == keyframe.get("time_seconds")
            and (old.get("description") or "") == (keyframe.get("description") or "")
        ):
            for field in ("image_url", "image_task_id", "prompt_text", "source", "provenance"):
                if keyframe.get(field) is None and old.get(field) is not None:
                    keyframe[field] = old[field]
        elif old_legacy and (
            old_legacy.get("time_seconds") == keyframe.get("time_seconds")
            and (old_legacy.get("description") or "") == (keyframe.get("description") or "")
        ):
            for target, source in (("image_url", "image_url"), ("image_task_id", "image_task_id"), ("prompt_text", "prompt_text")):
                if keyframe.get(target) is None and old_legacy.get(source) is not None:
                    keyframe[target] = old_legacy[source]
        result.append(keyframe)
    return result


def _get_keyframe_transition_template(novel: Novel, template_repo: PromptTemplateRepository):
    template = None
    if novel.keyframe_transition_prompt_template_id:
        template = template_repo.get_by_id(novel.keyframe_transition_prompt_template_id)
    if not template:
        template = template_repo.get_default_system_template("keyframe_transition")
    if not template:
        raise HTTPException(status_code=400, detail="未配置关键帧过渡规划提示词模板")
    return template


def _transition_keyframe_payload(shot, keyframe: dict) -> dict:
    description = keyframe.get("description")
    require_speech_neutral_visual_text(
        description,
        code="VISUAL_STATE_SPEECH_AUTHORITY_VIOLATION",
        field="description",
        state_index=keyframe.get("index"),
    )
    return strip_media_refs({
        "index": keyframe.get("index"),
        "role": keyframe.get("role"),
        "time_seconds": keyframe.get("time_seconds"),
        "description": description or "",
    })


def _build_segment_dialogue_state(shot, from_keyframe: dict, to_keyframe: dict, dialogue_timeline_source: list) -> dict:
    segment = {
        "start_time": from_keyframe.get("time_seconds") or 0,
        "end_time": to_keyframe.get("time_seconds") or shot.duration or 0,
    }
    segment_dialogues = [
        dialogue
        for dialogue in dialogue_timeline_source
        if float(dialogue.get("start_time") or 0) < float(segment["end_time"])
        and float(dialogue.get("end_time") or 0) > float(segment["start_time"])
    ]
    return {
        "start_time": segment["start_time"],
        "end_time": segment["end_time"],
        "has_dialogue": bool(segment_dialogues),
        "overlapping_dialogue_ids": [dialogue.get("id") for dialogue in segment_dialogues],
        "dialogue_timeline_source": segment_dialogues,
    }


def _build_keyframe_transition_user_content(
    shot,
    from_keyframe: dict,
    to_keyframe: dict,
    segment_index: int,
    previous_validation_failure: dict | None = None,
    *, visual_attention: dict | None = None,
) -> str:
    from_payload = _transition_keyframe_payload(shot, from_keyframe)
    to_payload = _transition_keyframe_payload(shot, to_keyframe)
    payload = {
        "shot": {
            "id": shot.id,
            "index": shot.index,
            "characters": _safe_json_list(shot.characters),
            "scene": shot.scene or "",
            "props": _safe_json_list(shot.props),
            "duration": shot.duration or 4,
            "continuity_mode": shot.continuity_mode or "NORMAL",
        },
        "segment_index": segment_index,
        "continuity_requirements": _build_continuity_requirements(shot),
        "from_keyframe": from_payload,
        "to_keyframe": to_payload,
    }
    if visual_attention and visual_attention.get("status") == "VALID":
        payload["visual_attention"] = visual_attention
    if previous_validation_failure:
        payload["previous_validation_failure"] = previous_validation_failure
        payload["retry_instruction"] = (
            "上一次 transition_description 违反 canonical visual speech-authority contract。"
            "只输出身体动作、走位、视线、姿态、表情、道具、摄影机和场景变化；"
            "不得输出 speaker、speaking/listening 或 mouth/lip speech state。"
        )
    return "请基于以下相邻关键帧规划，生成这两个关键帧之间的动态过渡导演描述。\n\n" + json.dumps(payload, ensure_ascii=False, indent=2)


async def _plan_keyframe_transitions(
    db: Session,
    novel: Novel,
    chapter: Chapter,
    shot,
    keyframes: list,
    template_repo: PromptTemplateRepository,
    llm_service: LLMService,
    *, selected_edges: set[tuple[int, int]] | None = None, call_records: list | None = None,
) -> list:
    if len(keyframes) < 2:
        return []
    template = _get_keyframe_transition_template(novel, template_repo)
    transitions = []

    def record_call(call):
        if call_records is None:
            append_video_ai_call(shot, call)
            db.commit()
        else:
            # Explicit refresh publishes logs and selected edges together after source revalidation.
            call_records.append(call)

    for index in range(len(keyframes) - 1):
        from_keyframe = keyframes[index]
        to_keyframe = keyframes[index + 1]
        if selected_edges is not None and (from_keyframe["index"], to_keyframe["index"]) not in selected_edges:
            continue
        segment_index = index + 1
        previous_validation_failure = None
        for attempt in range(1, 3):
            try:
                user_content = _build_keyframe_transition_user_content(
                    shot,
                    from_keyframe,
                    to_keyframe,
                    segment_index,
                    previous_validation_failure=previous_validation_failure,
                    visual_attention=project_visual_attention(
                        _safe_json_dict(shot.video_director_plan).get("visual_attention"),
                        from_keyframe["time_seconds"], to_keyframe["time_seconds"],
                        clip_local=False, duration=shot.duration or 4,
                    ),
                )
            except CanonicalVisualSpeechAuthorityViolation as exc:
                record_call({
                    "step": "10",
                    "task_type": "keyframe_transition",
                    "prompt_template_name": template.name,
                    "status": "error",
                    "input_summary": (
                        f"Shot {shot.index} KF{from_keyframe.get('index')} -> "
                        f"KF{to_keyframe.get('index')} · input validation"
                    ),
                    "response": "",
                    "parsed_result": {
                        "error": str(exc),
                        "code": exc.code,
                        "field": exc.field,
                        "category": exc.match.category,
                        "phrase": exc.match.phrase,
                    },
                })
                raise HTTPException(status_code=400, detail=str(exc))
            result = await llm_service.chat_completion(
                system_prompt=template.template,
                user_content=user_content,
                temperature=0.3,
                max_tokens=1600,
                response_format="json_object",
                task_type="keyframe_transition",
                prompt_template_name=template.name,
                novel_id=novel.id,
                chapter_id=chapter.id,
            )
            if not result.get("success"):
                record_call({
                    "step": "10",
                    "task_type": "keyframe_transition",
                    "prompt_template_name": template.name,
                    "status": "error",
                    "input_summary": f"Shot {shot.index} KF{from_keyframe.get('index')} -> KF{to_keyframe.get('index')}",
                    "response": result.get("error") or "",
                })
                raise HTTPException(status_code=500, detail=result.get("error") or "关键帧过渡规划失败")
            try:
                parsed = _parse_keyframe_planner_content(result.get("content") or "{}")
            except Exception as exc:
                record_call({
                    "step": "10",
                    "task_type": "keyframe_transition",
                    "prompt_template_name": template.name,
                    "status": "error",
                    "input_summary": f"Shot {shot.index} KF{from_keyframe.get('index')} -> KF{to_keyframe.get('index')}",
                    "response": result.get("content") or "",
                    "parsed_result": {"error": str(exc)},
                })
                raise HTTPException(status_code=400, detail=f"#10 返回格式无效：{exc}")

            transition = {
                "segment_index": int(parsed.get("segment_index") or segment_index),
                "from_keyframe_index": int(parsed.get("from_keyframe_index") or from_keyframe.get("index")),
                "to_keyframe_index": int(parsed.get("to_keyframe_index") or to_keyframe.get("index")),
                "start_time": parsed.get("start_time") if parsed.get("start_time") is not None else from_keyframe.get("time_seconds"),
                "end_time": parsed.get("end_time") if parsed.get("end_time") is not None else to_keyframe.get("time_seconds"),
                "transition_description": strip_embedded_visual_style(parsed.get("transition_description") or "", get_style(db, novel, "character")[0]),
            }
            try:
                require_speech_neutral_visual_text(
                    transition["transition_description"],
                    code="TRANSITION_SPEECH_AUTHORITY_VIOLATION",
                    field="transition_description",
                    state_index=f"{from_keyframe.get('index')}->{to_keyframe.get('index')}",
                )
            except CanonicalVisualSpeechAuthorityViolation as exc:
                previous_validation_failure = {
                    "code": exc.code,
                    "field": exc.field,
                    "category": exc.match.category,
                    "phrase": exc.match.phrase,
                    "attempt": attempt,
                }
                record_call({
                    "step": "10",
                    "task_type": "keyframe_transition",
                    "prompt_template_name": template.name,
                    "status": "error",
                    "input_summary": (
                        f"Shot {shot.index} KF{from_keyframe.get('index')} -> "
                        f"KF{to_keyframe.get('index')} · attempt {attempt}/2"
                    ),
                    "response": result.get("content") or "",
                    "parsed_result": {"error": str(exc), **previous_validation_failure},
                })
                if attempt == 2:
                    raise HTTPException(status_code=400, detail=str(exc))
                continue

            transitions.append(transition)
            record_call({
                "step": "10",
                "task_type": "keyframe_transition",
                "prompt_template_name": template.name,
                "status": "success",
                "input_summary": f"Shot {shot.index} KF{from_keyframe.get('index')} -> KF{to_keyframe.get('index')}",
                "response": result.get("content") or "",
                "parsed_result": {**transition, "visual_attention_consumed": project_visual_attention(
                    _safe_json_dict(shot.video_director_plan).get("visual_attention"),
                    from_keyframe["time_seconds"], to_keyframe["time_seconds"],
                    clip_local=False, duration=shot.duration or 4,
                )},
            })
            break
    return transitions


@router.post(
    "/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/video-director/recommend",
    response_model=dict,
)
async def recommend_video_mode(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    request: RecommendVideoModeRequest = RecommendVideoModeRequest(),
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
    workflow_repo: WorkflowRepository = Depends(get_workflow_repo),
    template_repo: PromptTemplateRepository = Depends(get_prompt_template_repo),
    llm_service: LLMService = Depends(get_llm_service),
):
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    shot = shot_repo.get_by_id(shot_id)
    if not shot or shot.chapter_id != chapter_id:
        raise HTTPException(status_code=404, detail="分镜不存在")

    existing_plan = _safe_json_dict(shot.video_director_plan)
    if existing_plan.get("canonical_visual_plan") is True:
        return {"success": True, "data": existing_plan}
    if existing_plan.get("recommended_mode") and not request.force:
        return {"success": True, "data": existing_plan}

    workflow = workflow_repo.get_active_by_type("video")
    workflow_capability = _get_video_workflow_capability(workflow)
    template = _get_video_mode_template(novel, template_repo)
    result = await llm_service.chat_completion(
        system_prompt=template.template,
        user_content=_build_video_mode_user_content(shot, workflow_capability),
        temperature=0.2,
        max_tokens=512,
        response_format="json_object",
        task_type="video_mode_recommender",
        prompt_template_name=template.name,
        novel_id=novel.id,
        chapter_id=chapter.id,
    )
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error") or "视频生成模式推荐失败")

    duration = shot.duration or 4
    selected_mode = _parse_recommended_mode(result.get("content") or "{}", duration, workflow_capability)
    max_clip_duration = workflow_capability["max_clip_duration"]
    parsed_result = {"recommended_mode": selected_mode}
    execution_windows = _build_execution_windows(duration, max_clip_duration) if selected_mode == "MULTI_KEYFRAME" else []
    if selected_mode == "FIRST_LAST_FRAME":
        clips = _build_first_last_clip_plan(duration)
    else:
        clips = [] if selected_mode == "MULTI_KEYFRAME" else _build_clip_plan(duration, max_clip_duration)
    keyframes = _build_minimal_keyframes(shot, selected_mode, max_clip_duration)
    plan = _merge_video_director_plan(shot, {
        "selected_mode": selected_mode,
        "recommended_mode": selected_mode,
        "recommended_label": VIDEO_MODE_LABELS[selected_mode],
        "recommendation_reason": _build_video_mode_reason(shot, selected_mode, workflow_capability),
        "workflow_capability": workflow_capability,
        "first_last_available": duration <= max_clip_duration,
        "notice": f"V1: {duration}s > {max_clip_duration}s，FIRST_LAST_FRAME 不可执行；请使用多关键帧" if duration > max_clip_duration else "",
        "execution_windows": execution_windows,
        "clips": clips,
        "keyframes": keyframes,
        "window_plans": [],
    })
    shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
    plan = append_video_ai_call(shot, {
        "step": "07",
        "task_type": "video_mode_recommender",
        "prompt_template_name": template.name,
        "status": "success",
        "input_summary": f"Shot {shot.index} · duration {duration}s · max {max_clip_duration}s",
        "response": result.get("content") or "",
        "parsed_result": parsed_result,
    })
    updates = {"video_director_plan": plan}
    if selected_mode == "FIRST_LAST_FRAME":
        updates["keyframes"] = _build_legacy_keyframes_from_plan(shot, keyframes)
    shot_repo.update(shot, **updates)
    return {"success": True, "data": plan}


@router.post(
    "/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/video-director/plan-clips",
    response_model=dict,
)
async def plan_shot_clips(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    request: PlanClipsRequest = PlanClipsRequest(),
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
):
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    shot = shot_repo.get_by_id(shot_id)
    if not shot or shot.chapter_id != chapter_id:
        raise HTTPException(status_code=404, detail="分镜不存在")
    current_plan = _safe_json_dict(shot.video_director_plan)
    if current_plan.get("clip_plan") and not request.force:
        clips = current_plan["clip_plan"]
        dialogue_timeline_source = current_plan.get("dialogue_timeline_source")
        fallback_timeline, _, timeline_status = build_dialogue_timeline(
            {"start_time": 0, "end_time": shot.duration or 4},
            _safe_json_list(shot.dialogues),
            _safe_json_list(shot.characters),
        )
        if timeline_status.get("status") == "overflow":
            dialogue_timeline_source = []
            current_plan["dialogue_timeline_source"] = []
            current_plan["dialogue_timeline_status"] = timeline_status
        elif not isinstance(dialogue_timeline_source, list):
            dialogue_timeline_source = fallback_timeline
        dialogue_assignments, dialogue_validation = assign_dialogues_to_clips(
            _safe_json_list(shot.dialogues), clips, dialogue_timeline_source
        )
        assignments_by_index = {item["clip_index"]: item["dialogues"] for item in dialogue_assignments}
        for clip in clips:
            clip["dialogue_assignment"] = assignments_by_index.get(int(clip.get("clip_index") or 0), [])
        validation = current_plan.get("clip_plan_validation", {})
        merge_dialogue_ownership_validation(validation, dialogue_validation)
        if not validation["passed"]:
            return {"success": True, "data": {"clips": clips, "validation": validation}}
        current_plan["clip_plan"] = clips
        current_plan["clip_plan_validation"] = validation
        shot.video_director_plan = json.dumps(current_plan, ensure_ascii=False)
        db.commit()
        return {"success": True, "data": {"clips": clips, "validation": validation}}
    try:
        clips, validation = await plan_clips(
            db,
            novel,
            shot,
            request.temporal_anchors,
            {"min_story_clip_duration": 2.0, "approval_mode": request.approval_mode},
        )
    except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not validation["passed"]:
        # Return the failed candidate for review without replacing the current
        # canonical plan or advancing its revision.
        return {"success": True, "data": {"clips": clips, "validation": validation}}
    current_plan.update({
        "clip_plan": clips,
        "temporal_anchors": request.temporal_anchors,
        "clip_plan_validation": validation,
        "clip_plan_findings": validation["findings"],
        "clip_plan_revision": int(current_plan.get("clip_plan_revision") or 0) + 1,
        "clip_plan_approval_mode": request.approval_mode,
    })
    shot.video_director_plan = json.dumps(current_plan, ensure_ascii=False)
    db.commit()
    return {"success": True, "data": {"clips": clips, "validation": validation, "revision": current_plan["clip_plan_revision"],
                                     "temporal_anchors": request.temporal_anchors,
                                     "execution_readiness": get_canonical_execution_readiness(shot, current_plan)}}


@router.post("/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/video-director/clip-plan/generate", response_model=dict)
async def generate_clip_plan_video(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
    batch_parent_task_id: str | None = None,
    force_rerun: bool = False,
):
    """Start the first validated semantic Clip through the existing Task pipeline."""
    novel = novel_repo.get_by_id(novel_id)
    shot = shot_repo.get_by_id(shot_id)
    if not novel or not shot or shot.chapter_id != chapter_id:
        raise HTTPException(status_code=404, detail="小说、章节或分镜不存在")
    plan = _safe_json_dict(shot.video_director_plan)
    _reject_legacy_video_execution_for_canonical(plan)
    clips = plan.get("clip_plan") if isinstance(plan.get("clip_plan"), list) else []
    if not clips:
        raise HTTPException(status_code=400, detail="当前 Shot 没有 Clip Plan")
    validation = plan.get("clip_plan_validation") or {}
    if not validation.get("passed"):
        raise HTTPException(status_code=400, detail="Clip Plan 未通过确定性校验")
    clip = next((item for item in clips if item.get("execution_status") in {"PLANNED", "GENERATING"}), clips[0])
    _require_attention_execution_freshness(plan, clip)
    if clip.get("capability") == "SINGLE_FRAME":
        image_path = url_to_local_path(shot.image_url) if shot.image_url else shot.image_path
        if not image_path or not Path(image_path).is_file():
            raise HTTPException(status_code=400, detail="semantic SINGLE_FRAME Clip 需要当前 Shot 已生成的有效分镜图。")
    task_repo = TaskRepository(db)
    workflow = WorkflowRepository(db).get_active_by_type("video")
    if not workflow:
        raise HTTPException(status_code=400, detail="未配置视频生成工作流")
    task = task_repo.create_shot_video_task(
        novel_id=novel_id,
        chapter_id=chapter_id,
        shot_index=shot.index,
        shot_duration=shot.duration or 4,
        chapter_title="Clip Planner",
        workflow_id=workflow.id,
        workflow_name=workflow.name,
        shot_id=shot.id,
    )
    clip_metadata = {
        "execution_scope": "CLIP",
        "clip_id": f"{shot.id}:clip:{clip.get('clip_index')}",
        "clip_index": clip.get("clip_index"),
        "clip_plan_revision": plan.get("clip_plan_revision", 1),
        "capability": clip.get("capability"),
        "planned_duration": clip.get("planned_duration"),
        "requested_duration": clip.get("planned_duration"),
        "previous_approved_task_id": None,
        "previous_approved_video_url": None,
        "approval_status": "GENERATING",
        "approval_mode": clip.get("approval_mode") or plan.get("clip_plan_approval_mode", "AUTO_APPROVE"),
        "prompt_text": clip.get("prompt_text") or "",
        "reference_asset": {
            "source": "SHOT_IMAGE",
            "shot_id": shot.id,
            "url": shot.image_url or (url_to_local_path(shot.image_path) if shot.image_path else None),
            "path": url_to_local_path(shot.image_url) if shot.image_url else shot.image_path,
        } if clip.get("capability") == "SINGLE_FRAME" else None,
        "batch_parent_task_id": batch_parent_task_id,
        "batch_force_rerun": force_rerun,
    }
    task.metadata_json = json.dumps(clip_metadata, ensure_ascii=False)
    task.parent_task_id = batch_parent_task_id
    db.commit()
    from app.services.shot_video_service import enqueue_shot_video_task
    enqueue_shot_video_task(task.id, novel_id, chapter_id, shot.index, workflow.id, shot.image_url or "", selected_mode="SINGLE_FRAME", clip_metadata=clip_metadata)
    return {"success": True, "data": {"taskId": task.id, "clipIndex": clip.get("clip_index"), "status": task.status}}


@router.post(
    "/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/video-director/plan-keyframes",
    response_model=dict,
)
async def plan_video_keyframes(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    request: PlanVideoKeyframesRequest = PlanVideoKeyframesRequest(),
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
    template_repo: PromptTemplateRepository = Depends(get_prompt_template_repo),
    llm_service: LLMService = Depends(get_llm_service),
):
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    shot = shot_repo.get_by_id(shot_id)
    if not shot or shot.chapter_id != chapter_id:
        raise HTTPException(status_code=404, detail="分镜不存在")

    if request.operation == "ATTENTION_REPLAN":
        return await _replan_visual_attention(db, novel, chapter, shot, template_repo, llm_service)

    plan = _safe_json_dict(shot.video_director_plan)

    fallback_dialogue_timeline, _, fallback_timeline_status = build_dialogue_timeline(
        {"start_time": 0, "end_time": shot.duration or 4},
        _safe_json_list(shot.dialogues),
        _safe_json_list(shot.characters),
    )
    dialogue_timeline_source = _get_official_dialogue_timeline(
        db, shot, fallback_dialogue_timeline
    )
    plan["dialogue_timeline_status"] = fallback_timeline_status
    if fallback_timeline_status.get("status") == "overflow":
        dialogue_timeline_source = []
        plan["dialogue_timeline_status"] = fallback_timeline_status
    if (
        plan.get("dialogue_timeline_source") != dialogue_timeline_source
        or plan.get("dialogue_timeline_status") != fallback_timeline_status
    ):
        plan["dialogue_timeline_source"] = dialogue_timeline_source
        plan["dialogue_timeline_status"] = fallback_timeline_status
        shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
        db.commit()

    if plan.get("canonical_visual_plan") is True and plan.get("keyframes") and not request.force:
        return {"success": True, "data": plan}

    duration = shot.duration or 4
    plan["dialogue_timeline_source"] = dialogue_timeline_source
    plan["dialogue_timeline_status"] = fallback_timeline_status

    template = _get_keyframe_planner_template(novel, template_repo)
    attention_catalog, catalog_findings = character_catalog(
        _safe_json_list(shot.characters), CharacterRepository(db).list_by_novel(novel.id),
    )
    previous_failures = []
    result = None
    keyframes = []
    validation = {}
    max_attempts = 2
    for attempt in range(1, max_attempts + 1):
        plan["dialogue_timeline_source"] = dialogue_timeline_source
        user_content = _build_keyframe_planner_user_content(shot, plan, previous_failures=previous_failures, attention_catalog=attention_catalog)
        result = await llm_service.chat_completion(
            system_prompt=template.template,
            user_content=user_content,
            temperature=0.3,
            max_tokens=2500,
            response_format="json_object",
            task_type="keyframe_planner",
            prompt_template_name=template.name,
            novel_id=novel.id,
            chapter_id=chapter.id,
        )
        input_summary = f"Shot {shot.index} · canonical Director visual planning · attempt {attempt}/{max_attempts}"
        if not result.get("success"):
            error = result.get("error") or "关键帧时间轴规划失败"
            plan = append_video_ai_call(shot, {
                "step": "08",
                "task_type": "keyframe_planner",
                "prompt_template_name": template.name,
                "status": "error",
                "input_summary": input_summary,
                "response": error,
                "parsed_result": {"error": error, "attempt": attempt},
            })
            shot_repo.update(shot, video_director_plan=plan)
            previous_failures.append({"attempt": attempt, "error": error})
            if attempt == max_attempts:
                final_error = f"关键帧规划调用失败：{error}"
                _mark_video_director_planning_failed(shot, shot_repo, plan, final_error)
                raise HTTPException(status_code=500, detail=final_error)
            continue

        try:
            parsed = _parse_keyframe_planner_content(result.get("content") or "{}")
            keyframes, _, validation = _normalize_keyframe_planner_result(parsed, None, duration, get_style(db, novel, "character")[0])
            attention_result = normalize_visual_attention(parsed.get("visual_attention"), attention_catalog, duration)
            validation["visual_attention"] = {"status": attention_result["status"],
                                               "findings": catalog_findings + attention_result["findings"]}
            break
        except Exception as exc:
            error = str(exc)
            plan = append_video_ai_call(shot, {
                "step": "08",
                "task_type": "keyframe_planner",
                "prompt_template_name": template.name,
                "status": "error",
                "input_summary": input_summary,
                "response": result.get("content") or "",
                "parsed_result": {"error": error, "attempt": attempt},
            })
            shot_repo.update(shot, video_director_plan=plan)
            previous_failures.append({"attempt": attempt, "error": error, "response": result.get("content") or ""})
            if attempt == max_attempts:
                final_error = f"关键帧规划不符合要求：{error}"
                _mark_video_director_planning_failed(shot, shot_repo, plan, final_error)
                raise HTTPException(status_code=400, detail=final_error)

    keyframes = _preserve_matching_keyframe_assets(keyframes, plan, _safe_json_list(shot.keyframes))
    current_clip_indexes = {
        int(item.get("clip_index"))
        for item in plan.get("clip_plan") or []
        if isinstance(item, dict) and item.get("clip_index") is not None
    }
    if current_clip_indexes:
        try:
            ensure_no_active_canonical_clip_tasks(
                db, shot.id, plan, current_clip_indexes,
            )
        except CanonicalExecutionConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc))
    plan = invalidate_downstream_for_canonical_visual_plan_replacement(shot, plan)
    for obsolete in ("selected_mode", "recommended_mode", "recommended_label", "recommendation_reason", "workflow_capability", "first_last_available", "notice", "execution_windows", "window_plans", "clips"):
        plan.pop(obsolete, None)
    plan.update({
        "canonical_visual_plan": True,
        "keyframes": keyframes,
        "transitions": [],
        "validation": validation,
        "dialogue_timeline_source": dialogue_timeline_source,
        "dialogue_timeline_status": fallback_timeline_status,
        "visual_attention": attention_result["authority"],
    })
    plan.pop("task_error_message", None)
    plan.pop("error_message", None)
    plan.pop("merged_video_url", None)
    plan.pop("merged_at", None)
    old_legacy_by_index = {
        int(item.get("plan_keyframe_index")): item for item in _safe_json_list(shot.keyframes)
        if isinstance(item, dict) and item.get("plan_keyframe_index") is not None
    }
    legacy_keyframes = []
    for position, keyframe in enumerate([item for item in keyframes if item.get("role") != "START"]):
        old = old_legacy_by_index.get(int(keyframe["index"]), {})
        legacy_keyframes.append({
            **old,
            "frame_index": position,
            "plan_keyframe_index": keyframe.get("index"),
            "time_seconds": keyframe.get("time_seconds"),
            "description": keyframe.get("description") or shot.description or "",
            "image_url": keyframe.get("image_url"),
            "image_task_id": keyframe.get("image_task_id"),
            "prompt_text": keyframe.get("prompt_text"),
            "source": keyframe.get("source"),
            "provenance": keyframe.get("provenance"),
            "reference_image_url": old.get("reference_image_url"),
            "reference_mode": old.get("reference_mode") or "auto_select",
        })
    shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
    plan = append_video_ai_call(shot, {
        "step": "08",
        "task_type": "keyframe_planner",
        "prompt_template_name": template.name,
        "status": "success",
        "input_summary": f"Shot {shot.index} · canonical Director visual planning",
        "response": result.get("content") or "",
        "parsed_result": {"keyframes": keyframes, "validation": validation, "visual_attention": attention_result["authority"]},
    })
    shot_repo.update(
        shot,
        video_director_plan=plan,
        keyframes=legacy_keyframes,
    )

    transitions = await _plan_keyframe_transitions(
        db=db,
        novel=novel,
        chapter=chapter,
        shot=shot,
        keyframes=keyframes,
        template_repo=template_repo,
        llm_service=llm_service,
    )
    plan = _safe_json_dict(shot.video_director_plan)
    plan["transitions"] = transitions
    shot_repo.update(shot, video_director_plan=plan)
    return {"success": True, "data": plan}


@router.post(
    "/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/video-director/plan-transitions",
    response_model=dict,
)
async def refresh_attention_transitions(
    novel_id: str, chapter_id: str, shot_id: str,
    request: PlanVideoTransitionsRequest = PlanVideoTransitionsRequest(),
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
    template_repo: PromptTemplateRepository = Depends(get_prompt_template_repo),
    llm_service: LLMService = Depends(get_llm_service),
):
    """Refresh only explicitly selected attention-stale edges, never the owner."""
    novel = novel_repo.get_by_id(novel_id)
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    shot = shot_repo.get_by_id(shot_id)
    if not novel or not chapter or not shot or shot.chapter_id != chapter_id:
        raise HTTPException(status_code=404, detail="小说、章节或分镜不存在")
    plan, _, _, source_sha, _, _ = _attention_replan_source(db, novel, shot, template_repo)
    stale = stale_attention_edges(plan)
    selected = set(request.transition_edges) if request.transition_edges is not None else stale
    if not selected <= stale or not selected <= canonical_transition_edges(plan):
        raise HTTPException(status_code=400, detail="只能刷新当前 attention-stale canonical transition edges")
    if not selected:
        return {"success": True, "data": plan}
    _check_active_attention_consumers(db, shot, plan, selected)
    template = _get_keyframe_transition_template(novel, template_repo)
    transition_template_sha = attention_source_sha256({"id": template.id, "template": template.template})
    records = []
    try:
        transitions = await _plan_keyframe_transitions(
            db, novel, chapter, shot, deepcopy(plan["keyframes"]), template_repo, llm_service,
            selected_edges=selected, call_records=records,
        )
    except Exception:
        for call in records:
            _record_attention_failure(db, shot, call)
        raise
    expected = {
        (a["index"], b["index"]): (i + 1, a["time_seconds"], b["time_seconds"])
        for i, (a, b) in enumerate(zip(plan["keyframes"], plan["keyframes"][1:]))
    }
    returned = {(t["from_keyframe_index"], t["to_keyframe_index"]): t for t in transitions}
    if set(returned) != selected or len(transitions) != len(selected) or any(
        (t["segment_index"], t["start_time"], t["end_time"]) != expected[edge]
        for edge, t in returned.items()
    ):
        raise HTTPException(status_code=400, detail="#10 必须保持所选 canonical edge identity / timing")
    db.rollback()
    db.expire_all()
    db.refresh(shot)
    db.refresh(novel)
    try:
        fresh, _, _, current_sha, _, _ = _attention_replan_source(db, novel, shot, template_repo)
        template = _get_keyframe_transition_template(novel, template_repo)
    except HTTPException as exc:
        raise HTTPException(status_code=409, detail="ATTENTION_SOURCE_CHANGED") from exc
    if (current_sha != source_sha or not selected <= stale_attention_edges(fresh)
            or attention_source_sha256({"id": template.id, "template": template.template}) != transition_template_sha):
        raise HTTPException(status_code=409, detail="ATTENTION_SOURCE_CHANGED")
    _check_active_attention_consumers(db, shot, fresh, selected)
    # Preserve unrelated edges and their order; insert a formerly missing edge at its canonical segment.
    merged = deepcopy(fresh)
    merged["transitions"] = [returned.pop((t["from_keyframe_index"], t["to_keyframe_index"]), t)
                             for t in fresh.get("transitions") or []]
    for transition in sorted(returned.values(), key=lambda t: t["segment_index"]):
        position = next((i for i, item in enumerate(merged["transitions"])
                         if item["segment_index"] > transition["segment_index"]), len(merged["transitions"]))
        merged["transitions"].insert(position, transition)
    merged["validation"]["visual_attention"]["stale_transition_edges"] = attention_edge_records(
        stale_attention_edges(fresh) - selected,
    )
    for call in records:
        merged = _attention_plan_with_call(merged, call)
    _commit_attention_plan(db, shot, merged)
    return {"success": True, "data": _safe_json_dict(shot.video_director_plan)}


class UpdateVisualStateDescriptionRequest(BaseModel):
    description: str
    expected_description: str
    expected_plan_revision: int


@router.patch(
    "/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/video-director/states/{state_index}/description",
    response_model=dict,
)
def update_visual_state_description(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    state_index: int,
    request: UpdateVisualStateDescriptionRequest,
    db: Session = Depends(get_db),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
):
    if not chapter_repo.get_by_id(chapter_id, novel_id):
        raise HTTPException(status_code=404, detail="章节不存在")
    shot = shot_repo.get_by_id(shot_id)
    if not shot or shot.chapter_id != chapter_id:
        raise HTTPException(status_code=404, detail="分镜不存在")
    plan = deepcopy(_safe_json_dict(shot.video_director_plan))
    state = next((item for item in plan.get("keyframes") or []
                  if isinstance(item, dict) and item.get("index") == state_index), None)
    if state is None:
        raise HTTPException(status_code=404, detail="视觉状态不存在")
    description = request.description.strip()
    if not description:
        raise HTTPException(status_code=400, detail="视觉状态描述不能为空")
    current_description = (shot.description if state.get("role") == "START" else state.get("description")) or ""
    if (current_description != request.expected_description
            or int(plan.get("clip_plan_revision") or 0) != request.expected_plan_revision):
        raise HTTPException(status_code=409, detail="视觉状态已更新，请取消编辑后重试")
    if plan.get("canonical_visual_plan") is True:
        try:
            require_speech_neutral_visual_text(description, code="VISUAL_STATE_SPEECH_AUTHORITY_VIOLATION",
                                             field="description", state_index=state_index)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    legacy = deepcopy(_safe_json_list(shot.keyframes))
    image_task_ids = {item.get("image_task_id") for item in legacy
                      if isinstance(item, dict) and item.get("plan_keyframe_index") == state_index}
    image_task_ids.add(state.get("image_task_id"))
    if state.get("role") == "START":
        image_task_ids.add(shot.image_task_id)
    active = db.query(Task).filter(
        Task.shot_id == shot.id, Task.status.in_(["pending", "queued", "processing", "running"]),
    ).all()
    if shot.video_status == "generating" or any(task.type == "shot_video" or task.id in image_task_ids for task in active):
        raise HTTPException(status_code=409, detail="当前状态图片或 Shot 视频生成中，请等待完成后编辑")
    state["description"] = description
    if description != current_description:
        # Empty explicitly prevents fallback to an old task's generated prompt.
        state["prompt_text"] = ""
    for item in legacy:
        if isinstance(item, dict) and item.get("plan_keyframe_index") == state_index:
            item["description"] = description
            if description != current_description:
                item["prompt_text"] = ""
    shot_description = description if state.get("role") == "START" else shot.description
    # Compare the read snapshot before committing, so workers cannot lose their
    # latest image URLs, AI logs or Clip progress to a description-only edit.
    with db.no_autoflush:
        count = db.query(Shot).filter(
            Shot.id == shot.id, Shot.video_director_plan == shot.video_director_plan,
            Shot.keyframes == shot.keyframes, Shot.description == shot.description,
        ).update({
            Shot.video_director_plan: json.dumps(plan, ensure_ascii=False),
            Shot.keyframes: json.dumps(legacy, ensure_ascii=False),
            Shot.description: shot_description,
        }, synchronize_session=False)
    if count != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="分镜数据已更新，请取消编辑后重试")
    db.commit()
    db.refresh(shot)
    response = shot_repo.to_response(shot)
    return {"success": True, "data": {
        "description": description, "shotDescription": shot.description,
        "videoDirectorPlan": response["videoDirectorPlan"], "keyframes": response["keyframes"],
    }}


@router.patch(
    "/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/video-director",
    response_model=dict,
)
async def save_video_director_plan(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    request: SaveVideoDirectorPlanRequest,
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
):
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    shot = shot_repo.get_by_id(shot_id)
    if not shot or shot.chapter_id != chapter_id:
        raise HTTPException(status_code=404, detail="分镜不存在")

    updates = request.model_dump(exclude_unset=True)
    plan = _merge_video_director_plan(shot, updates)
    duration = shot.duration or 4
    max_clip_duration = _safe_json_dict(plan.get("workflow_capability")).get("max_clip_duration", 15)
    if updates.get("selected_mode"):
        plan["first_last_available"] = duration <= max_clip_duration
        if updates["selected_mode"] == "MULTI_KEYFRAME":
            if not plan.get("execution_windows"):
                plan["execution_windows"] = _build_execution_windows(duration, max_clip_duration)
            if not plan.get("window_plans"):
                plan["window_plans"] = []
            plan["clips"] = []
        elif updates["selected_mode"] == "FIRST_LAST_FRAME":
            plan["execution_windows"] = []
            plan["window_plans"] = []
            plan["clips"] = _build_first_last_clip_plan(duration)
        if updates["selected_mode"] in {"FIRST_LAST_FRAME", "MULTI_KEYFRAME"} and not plan.get("keyframes"):
            plan["keyframes"] = _build_minimal_keyframes(shot, updates["selected_mode"], max_clip_duration)
    repo_updates = {"video_director_plan": plan}
    if updates.get("selected_mode") == "FIRST_LAST_FRAME":
        repo_updates["keyframes"] = _build_legacy_keyframes_from_plan(shot, plan.get("keyframes") or [])
    shot_repo.update(shot, **repo_updates)
    return {"success": True, "data": plan}


@router.post(
    "/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/video-director/clips/{window_index}/generate",
    response_model=dict,
)
async def generate_video_director_clip(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    window_index: int,
    request: GenerateVideoDirectorClipRequest = GenerateVideoDirectorClipRequest(),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    task_repo: TaskRepository = Depends(get_task_repo),
    workflow_repo: WorkflowRepository = Depends(get_workflow_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
):
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    shot = shot_repo.get_by_id(shot_id)
    if not shot or shot.chapter_id != chapter_id:
        raise HTTPException(status_code=404, detail="分镜不存在")
    semantic_clips = _safe_json_dict(shot.video_director_plan).get("clip_plan") or []
    if any(int(item.get("clip_index") or 0) == int(window_index) for item in semantic_clips if isinstance(item, dict)):
        if request.clip_plan_revision is None:
            raise HTTPException(status_code=400, detail="semantic Clip 需要显式提供 clip_plan_revision")
        plan = _safe_json_dict(shot.video_director_plan)
        if plan.get("canonical_visual_plan") is True:
            affected = canonical_clip_dependency_closure(plan, {window_index})
            try:
                ensure_no_active_canonical_clip_tasks(shot_repo.db, shot.id, plan, affected)
            except CanonicalExecutionConflict as exc:
                raise HTTPException(status_code=409, detail=str(exc))
        return await execute_semantic_clip(
            novel_id, chapter_id, shot_id, window_index,
            SemanticClipGenerateRequest(
                use_reference_audio=request.use_reference_audio,
                auto_merge=request.auto_merge,
                skip_llm_when_prompt_exists=request.skip_llm_when_prompt_exists,
                clip_plan_revision=request.clip_plan_revision,
            ),
            shot_repo.db, novel_repo, chapter_repo, task_repo, shot_repo,
        )
    if request.clip_plan_revision is not None:
        raise HTTPException(status_code=404, detail=f"Clip {window_index} 不存在于当前 semantic Clip Plan")
    if not shot.image_url:
        raise HTTPException(status_code=400, detail="该分镜尚未生成图片，请先生成分镜图片")

    plan = _safe_json_dict(shot.video_director_plan)
    valid_plan, plan_error, _ = _validate_multi_keyframe_plan_for_execution(shot, plan)
    if not valid_plan:
        raise HTTPException(status_code=400, detail=plan_error)
    window_plans = plan.get("window_plans") if isinstance(plan.get("window_plans"), list) else []
    window_plan = next((item for item in window_plans if isinstance(item, dict) and int(item.get("window_index") or 0) == int(window_index)), None)
    if not window_plan:
        raise HTTPException(status_code=404, detail=f"Clip {window_index} 不存在")

    _require_attention_execution_freshness(plan, window_plan)
    frame_count = int(window_plan.get("selected_frame_count") or 0)
    workflow_type = "three_frame_video" if frame_count == 3 else "four_frame_video"
    workflow = workflow_repo.get_active_by_type(workflow_type)
    if not workflow:
        raise HTTPException(status_code=400, detail=f"未配置 {workflow_type} 视频生成工作流，请在系统设置中配置")
    is_valid, error_msg = TaskService.validate_workflow_node_mapping(workflow, workflow_type)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    existing_task = task_repo.get_active_shot_task(novel_id, chapter_id, shot.index, "shot_video")
    if existing_task:
        return {
            "success": True,
            "message": "已有进行中的视频生成任务",
            "data": {"taskId": existing_task.id, "status": existing_task.status},
        }

    task = task_repo.create_shot_video_task(
        novel_id=novel_id,
        chapter_id=chapter_id,
        shot_index=shot.index,
        shot_duration=shot.duration or 4,
        chapter_title=chapter.title,
        workflow_id=workflow.id,
        workflow_name=workflow.name,
        shot_id=shot.id,
    )
    task.name = f"重新生成视频 Clip: 镜{shot.index} · C{window_index}"
    task.description = f"为章节 '{chapter.title}' 的分镜 {shot.index} 重新生成 Clip {window_index}"
    db = shot_repo.db
    if request.auto_merge:
        shot_repo.update_video_status(shot, "generating", task_id=task.id)
    db.commit()

    generate_shot_video_task(
        task.id,
        novel_id,
        chapter_id,
        shot.index,
        workflow.id,
        shot.image_url,
        use_keyframes=True,
        use_reference_audio=request.use_reference_audio,
        selected_mode="MULTI_KEYFRAME",
        only_window_index=window_index,
        auto_merge_clips=request.auto_merge,
        skip_llm_when_prompt_exists=request.skip_llm_when_prompt_exists,
    )
    return {"success": True, "message": "Clip 重新生成任务已创建", "data": {"taskId": task.id, "status": "pending"}}


def _ensure_required_physical_images(shot, plan, clip_indexes=None):
    missing = [item for item in project_required_execution_images(shot, plan, clip_indexes=clip_indexes)
               if not item["ready"]]
    if missing:
        raise HTTPException(status_code=409, detail={
            "code": "REQUIRED_IMAGES_MISSING",
            "message": "执行所需视觉状态图片的物理文件尚未准备",
            "shot_id": shot.id, "shot_index": shot.index,
            "missing": [{"state_id": item["state_id"], "state_index": item["state_index"],
                         "consumer_clip_indexes": [c["consumer_clip_index"] for c in item["consumers"] if not c["ready"]]}
                        for item in missing],
        })


async def _execute_phase_b_semantic_clip(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    window_index: int,
    request: SemanticClipGenerateRequest,
    db: Session,
    novel_repo: NovelRepository,
    chapter_repo: ChapterRepository,
    task_repo: TaskRepository,
    shot_repo: ShotRepository,
):
    """Execute one explicit semantic Clip through the Phase B GENERATE path."""
    novel = novel_repo.get_by_id(novel_id)
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    shot = shot_repo.get_by_id(shot_id)
    if not novel or not chapter or not shot or shot.chapter_id != chapter_id:
        raise HTTPException(status_code=404, detail="小说、章节或分镜不存在")
    if request.clip_plan_revision is None:
        raise HTTPException(status_code=400, detail="semantic Clip 需要显式提供 clip_plan_revision")

    plan = _safe_json_dict(shot.video_director_plan)
    clips = plan.get("clip_plan") if isinstance(plan.get("clip_plan"), list) else []
    clip = next((item for item in clips if int(item.get("clip_index") or 0) == window_index), None)
    if not clip:
        raise HTTPException(status_code=404, detail=f"Clip {window_index} 不存在")
    if int(plan.get("clip_plan_revision") or 0) != int(request.clip_plan_revision):
        raise HTTPException(status_code=409, detail="Clip 计划 revision 已变化，请重新加载并重试")

    _require_attention_execution_freshness(plan, clip)
    if plan.get("canonical_visual_plan") is True:
        readiness = get_canonical_execution_readiness(shot, plan, [clip])
        if not readiness["ready"]:
            raise HTTPException(status_code=409, detail=readiness["blocking_clips"][0])
        _ensure_required_physical_images(shot, plan, [window_index])

    raw_capability = str(clip.get("capability") or "")
    capability = raw_capability
    if capability == "VIDEO_CONTINUATION":
        raise HTTPException(status_code=400, detail="历史 continuation Clip 不能通过新的 semantic execution contract 执行")
    if capability == "TEMPORAL_EXTEND" and (
        str(clip.get("continuity_to_previous") or "").upper() != "CONTINUOUS"
        or clip.get("requires_temporal_control") is not True
    ):
        raise HTTPException(status_code=400, detail="TEMPORAL_EXTEND 需要 CONTINUOUS 和显式 requires_temporal_control=true")
    previous_provenance = None
    resolved_temporal_anchors = []
    try:
        resource_references = resolve_clip_reference_resources(db, novel_id, shot, plan, clip)
        if capability in {"EXTEND", "TEMPORAL_EXTEND"}:
            previous_index = int(clip.get("previous_clip_index"))
            previous_clip = next((item for item in clips if int(item.get("clip_index") or 0) == previous_index), None)
            previous_provenance = {
                "clip_index": previous_index,
                "clip_plan_revision": int(request.clip_plan_revision),
                "generated_by_task_id": previous_clip.get("generated_by_task_id") if previous_clip else None,
                "result_url": previous_clip.get("video_url") if previous_clip else None,
            }
            previous_provenance = resolve_extend_previous_av(
                db, novel_id, chapter_id, shot,
                {**clip, "clip_plan_revision": int(request.clip_plan_revision)},
                previous_provenance,
            )
            if capability == "EXTEND":
                compiled = compile_extend_clip(
                    shot, plan, clip, int(request.clip_plan_revision), previous_provenance,
                    resource_references=resource_references,
                )
            else:
                anchor_ids = clip.get("temporal_anchor_ids") or []
                if not 1 <= len(anchor_ids) <= 8 or len({str(item) for item in anchor_ids}) != len(anchor_ids):
                    raise ClipExecutionCompileError("TEMPORAL_ANCHOR_UNAVAILABLE")
                plan_anchors = plan.get("temporal_anchors") if isinstance(plan.get("temporal_anchors"), list) else []
                by_id = {str(item.get("anchor_id") or item.get("id")): item for item in plan_anchors if isinstance(item, dict) and (item.get("anchor_id") or item.get("id"))}
                for anchor_id in anchor_ids:
                    anchor = by_id.get(str(anchor_id))
                    if not anchor:
                        raise ClipExecutionCompileError("TEMPORAL_ANCHOR_UNAVAILABLE")
                    image_url = anchor.get("image_url") or anchor.get("image") or anchor.get("image_path")
                    source = anchor.get("source") or anchor.get("provenance")
                    if not image_url or not isinstance(source, dict):
                        raise ClipExecutionCompileError("TEMPORAL_ANCHOR_UNAVAILABLE")
                    resolved_temporal_anchors.append({
                        "anchor_id": str(anchor_id),
                        "time_seconds": anchor.get("time_seconds"),
                        "image_url": image_url,
                        "source": source,
                    })
                compiled = compile_temporal_extend_clip(
                    shot, plan, clip, int(request.clip_plan_revision),
                    previous_provenance, resolved_temporal_anchors,
                    resource_references=resource_references,
                )
        elif capability == "GENERATE":
                compiled = compile_generate_clip(shot, plan, clip, int(request.clip_plan_revision), resource_references=resource_references)
        else:
            raise ClipExecutionCompileError("当前 Clip capability 不支持 Phase C 执行")
    except ClipExecutionCompileError as exc:
        if exc.detail and exc.detail.get("code") == "GENERATE_VISUAL_START_GROUNDING_MISSING":
            raise HTTPException(status_code=409, detail=exc.detail)
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        if str(exc) == "PREVIOUS_AV_UNAVAILABLE":
            raise HTTPException(status_code=400, detail="PREVIOUS_AV_UNAVAILABLE")
        raise HTTPException(status_code=400, detail=str(exc))

    if capability == "EXTEND":
        workflow = WorkflowRepository(db).get_by_id(EXTEND_WORKFLOW_ID)
        if not workflow or not workflow.is_active or workflow.type != EXTEND_PHYSICAL_WORKFLOW_TYPE:
            raise HTTPException(status_code=400, detail="EXTEND physical workflow unavailable")
    elif capability == "TEMPORAL_EXTEND":
        workflow = WorkflowRepository(db).get_by_id(TEMPORAL_EXTEND_WORKFLOW_ID)
        if not workflow or not workflow.is_active or workflow.type != "TEMPORAL_EXTEND":
            raise HTTPException(status_code=400, detail="TEMPORAL_EXTEND workflow unavailable")
    else:
        workflow = WorkflowRepository(db).get_active_by_type("multi_reference_video")
    if not workflow:
        raise HTTPException(status_code=400, detail="未配置 multi_reference_video 视频生成工作流")
    physical_workflow_type = EXTEND_PHYSICAL_WORKFLOW_TYPE if capability == "EXTEND" else "TEMPORAL_EXTEND" if capability == "TEMPORAL_EXTEND" else "multi_reference_video"
    is_valid, error_msg = TaskService.validate_workflow_node_mapping(workflow, physical_workflow_type)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    for active in db.query(Task).filter(
        Task.type == "shot_video",
        Task.shot_id == shot.id,
        Task.status.in_(["pending", "running"]),
    ).all():
        active_metadata = _safe_json_dict(active.metadata_json)
        if (
            active_metadata.get("execution_scope") == "CLIP"
            and int(active_metadata.get("clip_index") or 0) == window_index
            and int(active_metadata.get("clip_plan_revision") or 0) == int(request.clip_plan_revision)
        ):
            return {"success": True, "message": "该 Clip 已有进行中的生成任务", "data": {"taskId": active.id, "status": active.status}}

    task = task_repo.create_shot_video_task(
        novel_id=novel_id,
        chapter_id=chapter_id,
        shot_index=shot.index,
        shot_duration=shot.duration or 4,
        chapter_title=chapter.title,
        workflow_id=workflow.id,
        workflow_name=workflow.name,
        shot_id=shot.id,
    )
    task.name = f"生成视频 Clip: 镜{shot.index} · C{window_index}"
    task.description = f"为章节 '{chapter.title}' 的分镜 {shot.index} 生成 Clip {window_index}"
    metadata = {
        "execution_scope": "CLIP",
        "phase_b_generate": capability == "GENERATE",
        "clip_id": f"{shot.id}:clip:{window_index}",
        "clip_index": window_index,
        "clip_plan_revision": int(request.clip_plan_revision),
        "capability": capability,
        "artifact_kind": compiled["execution_contract"]["artifact_kind"],
        "planned_duration": clip.get("planned_duration"),
        "requested_duration": clip.get("planned_duration"),
        "dialogue_assignment": clip.get("dialogue_assignment") or [],
        "approval_mode": clip.get("approval_mode") or plan.get("clip_plan_approval_mode", "AUTO_APPROVE"),
        "approval_status": "GENERATING",
        "auto_merge": False,
        "skip_llm_when_prompt_exists": request.skip_llm_when_prompt_exists,
        **compiled,
    }
    if capability in {"EXTEND", "TEMPORAL_EXTEND"}:
        metadata["previous_approved_task_id"] = previous_provenance["generated_by_task_id"]
        metadata["previous_approved_video_url"] = previous_provenance["result_url"]
        metadata["previous_approved_video_source"] = "approved_clip_result"
        metadata["continuity_to_previous"] = clip.get("continuity_to_previous")
        metadata["requires_temporal_control"] = bool(clip.get("requires_temporal_control"))
    if capability == "TEMPORAL_EXTEND":
        metadata["temporal_anchor_ids"] = [item["anchor_id"] for item in resolved_temporal_anchors]
    reusable_prompt = get_semantic_clip_prompt(plan, clip, compiled["video_reference_manifest"]) if request.skip_llm_when_prompt_exists else ""
    if request.skip_llm_when_prompt_exists and not reusable_prompt.strip():
        raise HTTPException(status_code=400, detail="当前 Clip 没有可复用的视频最终 Prompt，请先使用 LLM+生成Clip视频")
    metadata["prompt_text"] = reusable_prompt
    task.metadata_json = json.dumps(metadata, ensure_ascii=False)
    db.commit()
    enqueue_shot_video_task(
        task.id, novel_id, chapter_id, shot.index, workflow.id, shot.image_url or "",
        clip_metadata=metadata,
        use_reference_audio=request.use_reference_audio,
        skip_llm_when_prompt_exists=request.skip_llm_when_prompt_exists,
    )
    return {"success": True, "message": f"semantic Clip {capability} 任务已创建", "data": {"taskId": task.id, "status": "pending"}}


async def execute_semantic_clip(*args, **kwargs):
    """Shared semantic Clip entrypoint for API and Batch orchestration."""
    return await _execute_phase_b_semantic_clip(*args, **kwargs)


async def _regenerate_semantic_video_director_clip(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    window_index: int,
    request: SemanticClipGenerateRequest = SemanticClipGenerateRequest(),
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    task_repo: TaskRepository = Depends(get_task_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
):
    """Regenerate one semantic Clip without changing its plan identity or assignment."""
    novel = novel_repo.get_by_id(novel_id)
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    shot = shot_repo.get_by_id(shot_id)
    if not novel or not chapter or not shot or shot.chapter_id != chapter_id:
        raise HTTPException(status_code=404, detail="小说、章节或分镜不存在")

    plan = _safe_json_dict(shot.video_director_plan)
    clips = plan.get("clip_plan") if isinstance(plan.get("clip_plan"), list) else []
    clip = next((item for item in clips if int(item.get("clip_index") or 0) == window_index), None)
    if not clip:
        raise HTTPException(status_code=404, detail=f"Clip {window_index} 不存在")
    _require_attention_execution_freshness(plan, clip)
    if window_index > 1 and clip.get("capability") in {"VIDEO_CONTINUATION", "TEMPORAL_EXTEND"}:
        previous = task_repo.db.query(Task).filter(
            Task.type == "shot_video",
            Task.shot_id == shot.id,
            Task.metadata_json.like(f'%"clip_index": {window_index - 1}%'),
            Task.metadata_json.like(f'%"clip_plan_revision": {int(plan.get("clip_plan_revision") or 0)}%'),
            Task.status == "completed",
        ).order_by(Task.completed_at.desc()).first()
        previous_metadata = _safe_json_dict(previous.metadata_json) if previous else {}
        previous_url = (previous_metadata.get("assembled_result") or {}).get("url") or (previous.result_url if previous else None)
        previous_path = url_to_local_path(previous_url) if previous_url else None
        if not previous or previous_metadata.get("approval_status") != "APPROVED" or not previous_path or not Path(previous_path).is_file():
            raise HTTPException(status_code=400, detail="缺少上一 Clip 的有效 approved Previous AV")
        previous_task_id = previous.id
    else:
        previous_task_id = None
        previous_url = None

    capability = clip.get("capability") or "SINGLE_FRAME"
    workflow = WorkflowRepository(db).get_active_by_type(capability)
    if not workflow:
        raise HTTPException(status_code=400, detail=f"未配置 {capability} 视频生成工作流")
    active = task_repo.get_active_shot_task(novel_id, chapter_id, shot.index, "shot_video")
    if active:
        return {"success": True, "message": "已有进行中的视频生成任务", "data": {"taskId": active.id, "status": active.status}}

    task = task_repo.create_shot_video_task(
        novel_id=novel_id,
        chapter_id=chapter_id,
        shot_index=shot.index,
        shot_duration=shot.duration or 4,
        chapter_title=chapter.title,
        workflow_id=workflow.id,
        workflow_name=workflow.name,
        shot_id=shot.id,
    )
    metadata = {
        "execution_scope": "CLIP",
        "clip_id": f"{shot.id}:clip:{window_index}",
        "clip_index": window_index,
        "clip_plan_revision": plan.get("clip_plan_revision", 1),
        "capability": capability,
        "planned_duration": clip.get("planned_duration"),
        "requested_duration": clip.get("planned_duration"),
        "dialogue_assignment": clip.get("dialogue_assignment") or [],
        "temporal_anchor_ids": clip.get("temporal_anchor_ids") or [],
        "previous_approved_task_id": previous_task_id,
        "previous_approved_video_url": previous_url,
        "previous_approved_video_source": "approved_assembled_result" if previous_task_id and previous_metadata.get("assembled_result", {}).get("url") else "approved_clip_result" if previous_task_id else None,
        "prompt_text": "" if not request.skip_llm_when_prompt_exists else get_semantic_clip_prompt(plan, clip),
        "approval_mode": clip.get("approval_mode") or plan.get("clip_plan_approval_mode", "AUTO_APPROVE"),
        "approval_status": "GENERATING",
        "use_reference_audio": request.use_reference_audio,
        "auto_merge": request.auto_merge,
        "skip_llm_when_prompt_exists": request.skip_llm_when_prompt_exists,
        "is_clip_regeneration": True,
    }
    if request.skip_llm_when_prompt_exists and not metadata["prompt_text"]:
        raise HTTPException(status_code=400, detail="当前 Clip 没有可复用的视频最终 Prompt，请先使用 LLM+生成Clip视频")
    task.metadata_json = json.dumps(metadata, ensure_ascii=False)
    shot_repo.update_video_status(shot, "generating", task_id=task.id)
    db.commit()
    enqueue_shot_video_task(
        task.id, novel_id, chapter_id, shot.index, workflow.id, shot.image_url or "",
        selected_mode="SINGLE_FRAME", clip_metadata=metadata,
        use_reference_audio=request.use_reference_audio,
        skip_llm_when_prompt_exists=request.skip_llm_when_prompt_exists,
    )
    return {"success": True, "message": "semantic Clip 重新生成任务已创建", "data": {"taskId": task.id, "status": "pending"}}


@router.post(
    "/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/video-director/clips/merge",
    response_model=dict,
)
async def merge_video_director_clips(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
):
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    shot = shot_repo.get_by_id(shot_id)
    if not shot or shot.chapter_id != chapter_id:
        raise HTTPException(status_code=404, detail="分镜不存在")

    result = await merge_video_director_clip_videos(shot_repo.db, shot, shot_repo, novel_id, chapter_id, shot.index)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message") or "多 Clip 拼接失败")
    return {"success": True, "data": {"videoUrl": result.get("video_url"), "videoDirectorPlan": result.get("plan"), "skipped": result.get("skipped", False)}}




async def _wait_for_persistent_task(db: Session, task_id: str, timeout_iterations: int = 720) -> str:
    for _ in range(timeout_iterations):
        db.expire_all()
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            return "failed"
        if task.status in {"completed", "failed", "cancelled"}:
            return task.status
        await asyncio.sleep(5)
    task = db.query(Task).filter(Task.id == task_id).first()
    if task and task.status in {"pending", "running"}:
        task.status = "failed"
        task.error_message = "等待任务完成超时"
        task.current_step = "任务超时"
        db.commit()
    return "failed"


async def _prepare_batch_video_details(db: Session, batch_task: Task, child_task: Task) -> str:
    novel_repo = NovelRepository(db)
    chapter_repo = ChapterRepository(db)
    shot_repo = ShotRepository(db)
    workflow_repo = WorkflowRepository(db)
    template_repo = PromptTemplateRepository(db)
    llm_service = LLMService()
    shot = shot_repo.get_by_id(child_task.shot_id)
    if not shot or shot.chapter_id != child_task.chapter_id:
        raise ValueError("批量任务对应的分镜不存在")

    plan = _safe_json_dict(shot.video_director_plan)
    selected_mode = plan.get("selected_mode") or plan.get("recommended_mode")
    if not selected_mode:
        await recommend_video_mode(
            child_task.novel_id,
            child_task.chapter_id,
            child_task.shot_id,
            RecommendVideoModeRequest(force=False),
            db,
            novel_repo,
            chapter_repo,
            shot_repo,
            workflow_repo,
            template_repo,
            llm_service,
        )
        db.expire_all()
        shot = shot_repo.get_by_id(child_task.shot_id)
        plan = _safe_json_dict(shot.video_director_plan)
        selected_mode = plan.get("selected_mode") or plan.get("recommended_mode")

    if selected_mode == "FIRST_LAST_FRAME":
        capability = plan.get("workflow_capability") if isinstance(plan.get("workflow_capability"), dict) else {}
        max_clip_duration = int(capability.get("max_clip_duration") or 15)
        if (shot.duration or 4) > max_clip_duration:
            await recommend_video_mode(
                child_task.novel_id,
                child_task.chapter_id,
                child_task.shot_id,
                RecommendVideoModeRequest(force=True),
                db,
                novel_repo,
                chapter_repo,
                shot_repo,
                workflow_repo,
                template_repo,
                llm_service,
            )
            db.expire_all()
            shot = shot_repo.get_by_id(child_task.shot_id)
            plan = _safe_json_dict(shot.video_director_plan)
            selected_mode = plan.get("selected_mode") or plan.get("recommended_mode")

    if selected_mode in {"FIRST_LAST_FRAME", "MULTI_KEYFRAME"}:
        needs_plan = (
            selected_mode == "MULTI_KEYFRAME" and not plan.get("window_plans")
        ) or (
            selected_mode == "FIRST_LAST_FRAME" and (not plan.get("keyframes") or not plan.get("transitions"))
        )
        if needs_plan:
            await plan_video_keyframes(
                child_task.novel_id,
                child_task.chapter_id,
                child_task.shot_id,
                PlanVideoKeyframesRequest(force=False),
                db,
                novel_repo,
                chapter_repo,
                shot_repo,
                workflow_repo,
                template_repo,
                llm_service,
            )
            db.expire_all()
            shot = shot_repo.get_by_id(child_task.shot_id)

        keyframes = _safe_json_list(shot.keyframes)
        keyframe_service = ShotKeyframeService()
        for frame_index, keyframe in enumerate(keyframes):
            image_url = keyframe.get("image_url") if isinstance(keyframe, dict) else None
            if image_url and url_to_local_path(image_url):
                continue

            task_name = f"生成关键帧图片: {shot.id}-{frame_index}"
            active_keyframe_task = db.query(Task).filter(
                Task.type == "keyframe_image",
                Task.name == task_name,
                Task.status.in_(["pending", "running"]),
            ).order_by(Task.created_at.desc()).first()
            if active_keyframe_task and not active_keyframe_task.comfyui_prompt_id:
                active_keyframe_task.status = "failed"
                active_keyframe_task.error_message = "批量视频恢复时重新提交未启动的关键帧任务"
                active_keyframe_task.current_step = "等待重新提交"
                db.commit()

            reusable_prompt = keyframe_service._get_reusable_keyframe_prompt(
                db,
                shot.id,
                frame_index,
                keyframe,
            )
            success, keyframe_task_id, message = await keyframe_service.generate_keyframe_image(
                db,
                shot.id,
                frame_index,
                skip_llm_when_prompt_exists=bool(reusable_prompt),
            )
            if not success or not keyframe_task_id:
                raise ValueError(message or f"关键帧 {frame_index} 生成任务创建失败")
            keyframe_task = db.query(Task).filter(Task.id == keyframe_task_id).first()
            if keyframe_task and not keyframe_task.parent_task_id:
                keyframe_task.parent_task_id = batch_task.id
                db.commit()
            status = await _wait_for_persistent_task(db, keyframe_task_id)
            if status != "completed":
                raise ValueError(f"关键帧 {frame_index} 生成{status}")
            db.expire_all()
            shot = shot_repo.get_by_id(child_task.shot_id)

    return selected_mode or "SINGLE_FRAME"


def _prepare_and_enqueue_batch_video_child(
    db: Session,
    child_task: Task,
    selected_mode: str,
    use_reference_audio: bool,
    skip_llm_when_prompt_exists: bool,
) -> None:
    novel_repo = NovelRepository(db)
    chapter_repo = ChapterRepository(db)
    shot_repo = ShotRepository(db)
    workflow_repo = WorkflowRepository(db)
    novel = novel_repo.get_by_id(child_task.novel_id)
    chapter = chapter_repo.get_by_id(child_task.chapter_id, child_task.novel_id)
    shot = shot_repo.get_by_id(child_task.shot_id)
    if not novel or not chapter or not shot or shot.chapter_id != chapter.id:
        raise ValueError("批量任务对应的小说、章节或分镜不存在")
    if not shot.image_url:
        raise ValueError("该分镜尚未生成图片，请先生成分镜图片")

    plan = _safe_json_dict(shot.video_director_plan)
    workflow_type = "video"
    if selected_mode == "FIRST_LAST_FRAME":
        workflow_type = "first_last_video"
    elif selected_mode == "MULTI_KEYFRAME":
        valid_plan, plan_error, first_frame_count = _validate_multi_keyframe_plan_for_execution(shot, plan)
        if not valid_plan:
            raise ValueError(f"视频生成前置检查失败：{plan_error}")
        needed_types = {
            "three_frame_video" if int(window.get("selected_frame_count") or 0) == 3 else "four_frame_video"
            for window in (plan.get("window_plans") or [])
        }
        for needed_type in needed_types:
            needed_workflow = workflow_repo.get_active_by_type(needed_type)
            if not needed_workflow:
                raise ValueError(f"未配置 {needed_type} 视频生成工作流")
            valid, error = TaskService.validate_workflow_node_mapping(needed_workflow, needed_type)
            if not valid:
                raise ValueError(error)
        workflow_type = "three_frame_video" if first_frame_count == 3 else "four_frame_video"

    workflow = workflow_repo.get_active_by_type(workflow_type)
    if not workflow:
        raise ValueError(f"未配置 {workflow_type} 视频生成工作流")
    valid, error = TaskService.validate_workflow_node_mapping(workflow, workflow_type)
    if not valid:
        raise ValueError(error)
    if selected_mode == "FIRST_LAST_FRAME":
        max_duration = _get_video_workflow_capability(workflow)["max_clip_duration"]
        if (shot.duration or 4) > max_duration:
            raise ValueError(f"首尾帧模式当前仅支持不超过 {max_duration}s 的 Shot")
        end_keyframe = next((item for item in (plan.get("keyframes") or []) if item.get("role") == "END"), None)
        end_image_url = _get_video_director_keyframe_image_url(shot, end_keyframe)
        if not end_image_url or not url_to_local_path(end_image_url):
            raise ValueError("首尾帧模式需要先生成 END 关键帧图片")

    file_storage.delete_shot_video(child_task.novel_id, child_task.chapter_id, shot.index)
    shot.video_url = None
    child_task.workflow_id = workflow.id
    child_task.workflow_name = workflow.name
    child_task.status = "pending"
    child_task.started_at = None
    child_task.current_step = "等待视频生成 Worker"
    child_task.description = (
        f"为章节 '{chapter.title}' 的分镜 {shot.index} 生成视频 (时长: {shot.duration or 4}s)；"
        f"视频模式：{VIDEO_MODE_LABELS.get(selected_mode, selected_mode)}"
    )
    shot_repo.update_video_status(shot, "generating", task_id=child_task.id)
    db.commit()
    generate_shot_video_task(
        child_task.id,
        child_task.novel_id,
        child_task.chapter_id,
        shot.index,
        workflow.id,
        shot.image_url,
        use_keyframes=True,
        use_reference_audio=use_reference_audio,
        selected_mode=selected_mode,
        skip_llm_when_prompt_exists=skip_llm_when_prompt_exists,
    )


def enqueue_shot_video_batch_task(batch_task_id: str) -> None:
    if batch_task_id in shot_video_batch_locks:
        return
    shot_video_batch_locks.add(batch_task_id)
    payload = {"batch_task_id": batch_task_id}
    worker_manager.worker("shot_video_batch").enqueue(persistent_job(
        batch_task_id,
        "app.api.shots:run_shot_video_batch_task",
        payload,
        lambda: run_shot_video_batch_task(**payload),
    ))


async def _wait_for_semantic_shot_final(db, batch_child: Task, shot: Shot, initial_plan: dict, timeout_iterations: int = 720) -> str:
    for _ in range(timeout_iterations):
        db.expire_all()
        batch = db.query(Task).filter(Task.id == batch_child.parent_task_id).first()
        if not batch or batch.status == "cancelled":
            return "cancelled"

        shot = db.query(Shot).filter(Shot.id == batch_child.shot_id).first()
        plan = _safe_json_dict(shot.video_director_plan) if shot else {}
        revision = int(initial_plan.get("clip_plan_revision") or 0)
        if not shot or int(plan.get("clip_plan_revision") or 0) != revision:
            return "failed"
        if plan.get("clip_plan_approval_mode") == "REVIEW_REQUIRED":
            return "failed"
        clips = plan.get("clip_plan") if isinstance(plan.get("clip_plan"), list) else []
        semantic_tasks = db.query(Task).filter(
            Task.shot_id == shot.id,
            Task.type == "shot_video",
            Task.metadata_json.like(f'%"execution_scope": "CLIP"%'),
            Task.metadata_json.like(f'%"clip_plan_revision": {revision}%'),
        ).all()
        latest_by_index = {}
        for task in semantic_tasks:
            metadata = _safe_json_dict(task.metadata_json)
            index = int(metadata.get("clip_index") or 0)
            if index and (index not in latest_by_index or (task.created_at or datetime.min) > (latest_by_index[index].created_at or datetime.min)):
                latest_by_index[index] = task

        failed_clip = next((clip for clip in clips if clip.get("execution_status") == "FAILED"), None)
        failed_task = next((latest_by_index.get(int(clip.get("clip_index") or 0)) for clip in clips if latest_by_index.get(int(clip.get("clip_index") or 0)) and latest_by_index[int(clip.get("clip_index") or 0)].status in {"failed", "cancelled"}), None)
        if failed_clip or failed_task:
            shot.video_status = "failed"
            batch_child.error_message = (
                (failed_clip or {}).get("error_message")
                or (failed_task.error_message if failed_task else None)
                or "Semantic Clip execution failed"
            )
            db.commit()
            return "failed"
        if (
            plan.get("assembly_status") == "COMPLETED"
            and int(plan.get("assembly_clip_plan_revision") or 0) == revision
            and shot.video_status == "completed"
            and shot.video_url
        ):
            return "completed"
        if plan.get("clip_plan_approval_mode") == "REVIEW_REQUIRED" and all(
            (clip.get("execution_status") or "").upper() == "APPROVED" for clip in clips
        ):
            return "pending"
        await asyncio.sleep(5)
    return "failed"


async def _run_semantic_shot_for_batch(db, batch_task: Task, batch_child: Task, shot: Shot) -> str:
    plan = _safe_json_dict(shot.video_director_plan)
    clips = plan.get("clip_plan") if isinstance(plan.get("clip_plan"), list) else []
    if not clips or not (plan.get("clip_plan_validation") or {}).get("passed"):
        raise RuntimeError("Semantic Clip Plan 缺失或未通过校验")
    if plan.get("clip_plan_approval_mode") == "REVIEW_REQUIRED":
        raise RuntimeError("REVIEW_REQUIRED 尚未实现 Batch approval gate")

    revision = int(plan.get("clip_plan_revision") or 0)
    batch_metadata = _safe_json_dict(batch_child.metadata_json)
    force_rerun = bool(batch_metadata.get("batch_force_rerun"))

    if force_rerun:
        # A batch rerun starts a fresh execution of the existing plan. Keep the
        # planning contract, but remove every prior execution artifact so the
        # UI and the final waiter cannot observe stale Clip results.
        semantic_tasks = db.query(Task).filter(
            Task.shot_id == shot.id,
            Task.type == "shot_video",
            Task.metadata_json.like('%%"execution_scope": "CLIP"%%'),
        ).all()
        for task in semantic_tasks:
            metadata = _safe_json_dict(task.metadata_json)
            for media_url in (
                task.result_url,
                metadata.get("previous_approved_video_url"),
                (metadata.get("assembled_result") or {}).get("url"),
            ):
                media_path = url_to_local_path(media_url) if media_url else None
                if media_path:
                    try:
                        path = Path(media_path)
                        if path.is_file():
                            path.unlink()
                    except OSError:
                        pass
            if task.status in {"pending", "running", "queued"}:
                task.status = "cancelled"
                task.error_message = "被新的批量视频重跑取代"
                task.current_step = "批量重跑已清除旧 Clip"
            else:
                db.delete(task)
        for clip in plan.get("clip_plan", []):
            if not isinstance(clip, dict):
                continue
            for key in (
                "execution_status", "status", "video_url", "local_path",
                "source_video_url", "generated_at", "generated_by_task_id",
                "assembled_result", "assembled_media_duration", "actual_duration",
                "error_message", "seed", "workflow_json", "prompt_id",
            ):
                clip.pop(key, None)
            clip["execution_status"] = "PLANNED"
        for key in (
            "assembly_status", "assembly_clip_plan_revision", "assembly_task_ids",
            "assembly_mode", "assembled_result", "merged_video_url", "merged_at",
        ):
            plan.pop(key, None)
        shot.video_url = None
        shot.video_status = "pending"
        shot.video_task_id = batch_child.id
        shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
        db.flush()

    tasks = db.query(Task).filter(
        Task.shot_id == shot.id,
        Task.type == "shot_video",
        Task.metadata_json.like('%"execution_scope": "CLIP"%'),
        Task.metadata_json.like(f'%"clip_plan_revision": {revision}%'),
    ).order_by(Task.created_at.asc()).all()
    if force_rerun:
        tasks = [
            task for task in tasks
            if _safe_json_dict(task.metadata_json).get("batch_parent_task_id") == batch_task.id
        ]
    latest_by_index = {}
    for clip_task in tasks:
        index = int(_safe_json_dict(clip_task.metadata_json).get("clip_index") or 0)
        if index:
            latest_by_index[index] = clip_task

    missing_assembled_task = None
    for clip in clips:
        if clip.get("capability") not in {"VIDEO_CONTINUATION", "TEMPORAL_EXTEND"}:
            continue
        clip_index = int(clip.get("clip_index") or 0)
        continuation_task = latest_by_index.get(clip_index)
        if not continuation_task:
            continue
        continuation_metadata = _safe_json_dict(continuation_task.metadata_json)
        assembled = continuation_metadata.get("assembled_result") or {}
        assembled_duration = assembled.get("assembled_media_duration") or continuation_metadata.get("assembled_media_duration")
        continuation_result_path = url_to_local_path(continuation_task.result_url) if continuation_task.result_url else None
        if continuation_task.status == "completed" and continuation_result_path and Path(continuation_result_path).is_file():
            continue
        previous_task = latest_by_index.get(clip_index - 1)
        previous_metadata = _safe_json_dict(previous_task.metadata_json) if previous_task else {}
        previous_duration = (
            (previous_metadata.get("assembled_result") or {}).get("assembled_media_duration")
            or previous_metadata.get("assembled_media_duration")
            or previous_metadata.get("actual_duration")
        )
        if not assembled or not assembled_duration or (previous_duration and float(assembled_duration) <= float(previous_duration) + 0.01):
            missing_assembled_task = continuation_task
            break
    if missing_assembled_task:
        continuation_indexes = [
            int(clip.get("clip_index") or 0)
            for clip in clips
            if clip.get("capability") in {"VIDEO_CONTINUATION", "TEMPORAL_EXTEND"}
        ]
        if int(_safe_json_dict(missing_assembled_task.metadata_json).get("clip_index") or 0) != max(continuation_indexes):
            raise RuntimeError("Semantic continuation chain contains an older Clip without assembled_result; Batch will not use stale downstream output")
        retry_metadata = _safe_json_dict(missing_assembled_task.metadata_json)
        clip_definition = next(
            (clip for clip in clips if int(clip.get("clip_index") or 0) == int(retry_metadata.get("clip_index") or 0)),
            {},
        )
        retry_metadata.update({
            "clip_id": retry_metadata.get("clip_id") or f"{shot.id}:clip:{retry_metadata.get('clip_index')}",
            "clip_plan_revision": revision,
            "capability": retry_metadata.get("capability") or clip_definition.get("capability"),
            "planned_duration": retry_metadata.get("planned_duration") or clip_definition.get("planned_duration"),
            "requested_duration": retry_metadata.get("requested_duration") or clip_definition.get("planned_duration"),
            "dialogue_assignment": retry_metadata.get("dialogue_assignment") or clip_definition.get("dialogue_assignment") or [],
            "temporal_anchor_ids": retry_metadata.get("temporal_anchor_ids") or clip_definition.get("temporal_anchor_ids") or [],
            "approval_mode": retry_metadata.get("approval_mode") or clip_definition.get("approval_mode") or plan.get("clip_plan_approval_mode", "AUTO_APPROVE"),
        })
        previous_clip_task = latest_by_index.get(int(retry_metadata.get("clip_index") or 0) - 1)
        previous_clip_metadata = _safe_json_dict(previous_clip_task.metadata_json) if previous_clip_task else {}
        retry_metadata["previous_approved_task_id"] = previous_clip_task.id if previous_clip_task else retry_metadata.get("previous_approved_task_id")
        retry_metadata["previous_approved_video_url"] = (
            (previous_clip_metadata.get("assembled_result") or {}).get("url")
            or (previous_clip_task.result_url if previous_clip_task else None)
            or retry_metadata.get("previous_approved_video_url")
        )
        retry_metadata["previous_approved_video_source"] = (
            "approved_assembled_result"
            if previous_clip_metadata.get("assembled_result")
            else "approved_clip_result"
            if previous_clip_task
            else retry_metadata.get("previous_approved_video_source")
        )
        retry_metadata["batch_parent_task_id"] = batch_task.id
        missing_assembled_task.parent_task_id = batch_task.id
        missing_assembled_task.metadata_json = json.dumps(retry_metadata, ensure_ascii=False)
        db.commit()
        retry_result = TaskService(db).retry_task(missing_assembled_task.id)
        if not retry_result.get("success"):
            raise RuntimeError(retry_result.get("message") or "无法重新生成缺少 assembled_result 的 continuation Clip")
        batch_task.current_step = f"正在修复 Shot {shot.index} 的累计续生成结果"
        batch_child.current_step = "等待 Semantic Shot Final"
        batch_child.status = "running"
        batch_child.started_at = batch_child.started_at or datetime.utcnow()
        shot.video_status = "generating"
        db.commit()
        return await _wait_for_semantic_shot_final(db, batch_child, shot, plan)

    if all(
        (clip_task := latest_by_index.get(int(clip.get("clip_index") or 0)))
        and clip_task.status == "completed"
        and _safe_json_dict(clip_task.metadata_json).get("approval_status") == "APPROVED"
        for clip in clips
    ):
        has_continuation = any(clip.get("capability") in {"VIDEO_CONTINUATION", "TEMPORAL_EXTEND"} for clip in clips)
        if (
            plan.get("assembly_status") != "COMPLETED"
            or int(plan.get("assembly_clip_plan_revision") or 0) != revision
            or (has_continuation and (plan.get("assembly_mode") != "CONTINUATION_COLLAPSED" or not plan.get("assembled_result")))
            or shot.video_status != "completed"
            or not shot.video_url
        ):
            result = await merge_video_director_clip_videos(
                db, shot, ShotRepository(db), batch_child.novel_id,
                batch_child.chapter_id, int(shot.index or 0),
            )
            if not result.get("success"):
                raise RuntimeError(result.get("message") or "Semantic Shot Final Assembly 失败")
        return "completed"

    # Older continuation tasks can be completed with a valid result URL while
    # their assembled_result metadata was not persisted. Rebuild Final Assembly
    # from the completed Clip results instead of waiting forever or retrying.
    completed_clip_results = all(
        (clip_task := latest_by_index.get(int(clip.get("clip_index") or 0)))
        and clip_task.status == "completed"
        and clip_task.result_url
        and (result_path := url_to_local_path(clip_task.result_url))
        and Path(result_path).is_file()
        for clip in clips
    )
    if completed_clip_results:
        for clip in clips:
            clip_task = latest_by_index.get(int(clip.get("clip_index") or 0))
            if not clip_task or clip_task.status != "completed":
                continue
            metadata = _safe_json_dict(clip_task.metadata_json)
            if metadata.get("approval_status") != "APPROVED":
                metadata["approval_status"] = "APPROVED"
                clip_task.metadata_json = json.dumps(metadata, ensure_ascii=False)
        db.commit()
        result = await merge_video_director_clip_videos(
            db, shot, ShotRepository(db), batch_child.novel_id,
            batch_child.chapter_id, int(shot.index or 0),
        )
        if not result.get("success"):
            raise RuntimeError(result.get("message") or "Semantic Shot Final Assembly 失败")
        return "completed"

    active = any(task.status in {"pending", "running"} for task in latest_by_index.values())
    if active:
        return await _wait_for_semantic_shot_final(db, batch_child, shot, plan)

    first_index = int(clips[0].get("clip_index") or 0)
    if first_index != 1 or first_index in latest_by_index:
        raise RuntimeError("Semantic Clip chain 不完整；为避免绕过 Previous AV dependency，Batch 已停止该 Shot")

    batch_task.current_step = f"正在执行 Shot {shot.index} 的 Semantic Clip Plan"
    batch_child.current_step = "等待 Semantic Shot Final"
    batch_child.status = "running"
    batch_child.started_at = batch_child.started_at or datetime.utcnow()
    shot.video_status = "generating"
    if force_rerun:
        # Prevent the final waiter from treating the previous assembled Shot
        # as the result of this new batch run.
        plan.pop("assembly_status", None)
        plan.pop("assembly_clip_plan_revision", None)
        plan.pop("assembled_result", None)
        plan.pop("merged_video_url", None)
        plan.pop("merged_at", None)
        shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
    db.commit()
    await generate_clip_plan_video(
        novel_id=batch_child.novel_id,
        chapter_id=batch_child.chapter_id,
        shot_id=batch_child.shot_id,
        db=db,
        novel_repo=NovelRepository(db),
        shot_repo=ShotRepository(db),
        batch_parent_task_id=batch_task.id,
        force_rerun=force_rerun,
    )
    return await _wait_for_semantic_shot_final(db, batch_child, shot, plan)


def _semantic_batch_clips(shot: Shot, revision: int) -> list[dict]:
    plan = _safe_json_dict(shot.video_director_plan)
    if int(plan.get("clip_plan_revision") or 0) != int(revision):
        raise RuntimeError("BATCH_CLIP_PLAN_REVISION_STALE")
    clips = plan.get("clip_plan") if isinstance(plan.get("clip_plan"), list) else []
    if not clips or not (plan.get("clip_plan_validation") or {}).get("passed"):
        raise RuntimeError("Semantic Clip Plan 缺失或未通过校验")
    if plan.get("canonical_visual_plan") is True:
        readiness = get_canonical_execution_readiness(shot, plan)
        if not readiness["ready"]:
            raise RuntimeError(readiness["code"])
    ordered = sorted(clips, key=lambda item: int(item.get("clip_index") or 0))
    indexes = [int(item.get("clip_index") or 0) for item in ordered]
    if not indexes or len(indexes) != len(set(indexes)) or any(index <= 0 for index in indexes):
        raise RuntimeError("BATCH_CLIP_PLAN_INVALID")
    for clip, index in zip(ordered, indexes):
        clip.setdefault("clip_id", f"{shot.id}:clip:{index}")
        if int(clip.get("clip_plan_revision") or revision) != int(revision):
            raise RuntimeError("BATCH_CLIP_PLAN_REVISION_STALE")
    return ordered


def _semantic_clip_tasks(db: Session, shot: Shot, revision: int) -> list[Task]:
    tasks = []
    for task in db.query(Task).filter(Task.shot_id == shot.id, Task.type == "shot_video").all():
        metadata = _safe_json_dict(task.metadata_json)
        if metadata.get("execution_scope") == "CLIP" and int(metadata.get("clip_plan_revision") or 0) == int(revision):
            tasks.append(task)
    return tasks


def _latest_semantic_task(tasks: list[Task], clip_index: int) -> Task | None:
    matching = [task for task in tasks if int(_safe_json_dict(task.metadata_json).get("clip_index") or 0) == int(clip_index)]
    return max(matching, key=lambda task: task.created_at or datetime.min, default=None)


def _batch_child_state(batch_child: Task, state: str, **fields) -> None:
    metadata = _safe_json_dict(batch_child.metadata_json)
    metadata.update({"batch_mode": "SEMANTIC_CLIP", "batch_state": state, **fields})
    batch_child.metadata_json = json.dumps(metadata, ensure_ascii=False)
    batch_child.current_step = state


async def _wait_for_semantic_clip_task(db: Session, task_id: str, timeout_iterations: int = 720) -> Task | None:
    for _ in range(timeout_iterations):
        db.expire_all()
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task or task.status in {"completed", "failed", "cancelled"}:
            return task
        await asyncio.sleep(5)
    task = db.query(Task).filter(Task.id == task_id).first()
    if task and task.status in {"pending", "running"}:
        task.status = "failed"
        task.error_message = "等待 semantic Clip 完成超时"
        db.commit()
    return task


async def _run_semantic_shot_for_batch(db: Session, batch_task: Task, batch_child: Task, shot: Shot) -> str:
    batch_metadata = _safe_json_dict(batch_child.metadata_json)
    revision = int(batch_metadata.get("clip_plan_revision") or 0)
    auto_assemble = bool(batch_metadata.get("auto_assemble", True))
    clips = _semantic_batch_clips(shot, revision)
    tasks = _semantic_clip_tasks(db, shot, revision)

    for clip in clips:
        index = int(clip.get("clip_index") or 0)
        try:
            validate_semantic_clip_artifact(db, shot, clip, revision, batch_child.novel_id, batch_child.chapter_id)
            _batch_child_state(batch_child, "RUNNING", current_clip_index=index)
            db.commit()
            continue
        except ValueError:
            existing_task = _latest_semantic_task(tasks, index)
            if existing_task and existing_task.status == "completed":
                existing_metadata = _safe_json_dict(existing_task.metadata_json)
                if existing_metadata.get("approval_status") not in {None, "APPROVED"}:
                    _batch_child_state(batch_child, "WAITING_REVIEW", current_clip_index=index)
                    db.commit()
                    return "waiting_review"

        if str(clip.get("continuity_to_previous") or "").upper() == "CONTINUOUS":
            previous_index = int(clip.get("previous_clip_index") or index - 1)
            previous = next((item for item in clips if int(item.get("clip_index") or 0) == previous_index), None)
            if not previous:
                raise RuntimeError("BATCH_PREVIOUS_CLIP_MISSING")
            try:
                validate_semantic_clip_artifact(db, shot, previous, revision, batch_child.novel_id, batch_child.chapter_id)
            except ValueError:
                previous_task = _latest_semantic_task(tasks, previous_index)
                if previous_task and previous_task.status in {"pending", "running"}:
                    _batch_child_state(batch_child, "WAITING_DEPENDENCY", current_clip_index=index)
                    db.commit()
                    return "waiting_dependency"
                if previous_task and _safe_json_dict(previous_task.metadata_json).get("approval_status") not in {None, "APPROVED"}:
                    _batch_child_state(batch_child, "WAITING_REVIEW", current_clip_index=index)
                    db.commit()
                    return "waiting_review"
                raise RuntimeError(f"BATCH_PREVIOUS_CLIP_UNAVAILABLE:{previous_index}")

        task = _latest_semantic_task(tasks, index)
        if task and task.status in {"pending", "running"}:
            _batch_child_state(batch_child, "RUNNING", current_clip_index=index)
            db.commit()
            task = await _wait_for_semantic_clip_task(db, task.id)
        elif task and task.status in {"failed", "cancelled"}:
            retry = TaskService(db).retry_task(task.id)
            if not retry.get("success"):
                _batch_child_state(batch_child, "FAILED", failed_clip_index=index)
                batch_child.error_message = retry.get("message") or task.error_message
                db.commit()
                return "failed"
            task = await _wait_for_semantic_clip_task(db, task.id)
        else:
            _batch_child_state(batch_child, "RUNNING", current_clip_index=index)
            batch_task.current_step = f"正在执行 Shot {shot.index} Clip {index}"
            db.commit()
            try:
                execution_result = await execute_semantic_clip(
                    batch_child.novel_id,
                    batch_child.chapter_id,
                    shot.id,
                    index,
                    SemanticClipGenerateRequest(
                        use_reference_audio=bool(batch_metadata.get("use_reference_audio", True)),
                        auto_merge=False,
                        skip_llm_when_prompt_exists=bool(batch_metadata.get("skip_llm_when_prompt_exists", False)),
                        clip_plan_revision=revision,
                    ),
                    db,
                    NovelRepository(db),
                    ChapterRepository(db),
                    TaskRepository(db),
                    ShotRepository(db),
                )
                execution_task_id = ((execution_result or {}).get("data") or {}).get("taskId")
                execution_task = db.query(Task).filter(Task.id == execution_task_id).first() if execution_task_id else None
                if execution_task:
                    execution_metadata = _safe_json_dict(execution_task.metadata_json)
                    execution_metadata["batch_parent_task_id"] = batch_task.id
                    execution_task.parent_task_id = batch_task.id
                    execution_task.metadata_json = json.dumps(execution_metadata, ensure_ascii=False)
                    db.commit()
            except HTTPException as exc:
                _batch_child_state(batch_child, "FAILED", failed_clip_index=index)
                batch_child.error_message = str(exc.detail)
                db.commit()
                return "failed"
            tasks = _semantic_clip_tasks(db, shot, revision)
            task = _latest_semantic_task(tasks, index)
            task = await _wait_for_semantic_clip_task(db, task.id) if task else None

        db.expire_all()
        shot = db.query(Shot).filter(Shot.id == batch_child.shot_id).first()
        clips = _semantic_batch_clips(shot, revision)
        current = next(item for item in clips if int(item.get("clip_index") or 0) == index)
        try:
            validate_semantic_clip_artifact(db, shot, current, revision, batch_child.novel_id, batch_child.chapter_id)
        except ValueError as exc:
            _batch_child_state(batch_child, "FAILED", failed_clip_index=index)
            batch_child.error_message = (task.error_message if task else None) or str(exc)
            db.commit()
            return "failed"
        tasks = _semantic_clip_tasks(db, shot, revision)

    if not auto_assemble:
        _batch_child_state(batch_child, "COMPLETED_CLIPS")
        db.commit()
        return "completed"

    plan = _safe_json_dict(shot.video_director_plan)
    expected_task_ids = [str(clip.get("generated_by_task_id")) for clip in clips]
    existing_assembly_url = plan.get("merged_video_url") or shot.video_url
    reusable_assembly = (
        plan.get("assembly_status") == "COMPLETED"
        and int(plan.get("assembly_clip_plan_revision") or 0) == revision
        and shot.video_url
        and shot.video_url == existing_assembly_url
        and plan.get("assembly_task_ids") == expected_task_ids
        and bool(url_to_local_path(existing_assembly_url) and Path(url_to_local_path(existing_assembly_url)).is_file())
    )
    if not reusable_assembly:
        _batch_child_state(batch_child, "ASSEMBLING")
        db.commit()
        result = await merge_video_director_clip_videos(
            db, shot, ShotRepository(db), batch_child.novel_id, batch_child.chapter_id, int(shot.index or 0),
        )
        if not result.get("success"):
            _batch_child_state(batch_child, "FAILED")
            batch_child.error_message = result.get("message") or "Semantic Shot Final Assembly 失败"
            db.commit()
            return "failed"
    _batch_child_state(batch_child, "COMPLETED")
    db.commit()
    return "completed"


async def run_shot_video_batch_task(batch_task_id: str) -> None:
    db = SessionLocal()
    try:
        batch_task = db.query(Task).filter(Task.id == batch_task_id).first()
        if not batch_task or batch_task.status == "cancelled":
            return
        metadata = _safe_json_dict(batch_task.metadata_json)
        auto_complete = bool(metadata.get("auto_complete_details", True))
        use_reference_audio = bool(metadata.get("use_reference_audio", True))
        skip_llm = bool(metadata.get("skip_llm_when_prompt_exists", False))
        force_rerun = bool(metadata.get("force_rerun", True))
        batch_task.status = "running"
        batch_task.started_at = batch_task.started_at or datetime.utcnow()
        batch_task.current_step = "批量分镜视频生成中"
        db.commit()

        child_ids = [row[0] for row in db.query(Task.id).filter(
            Task.parent_task_id == batch_task_id,
            Task.type == "shot_video",
            Task.batch_order.isnot(None),
        ).order_by(Task.batch_order.asc(), Task.created_at.asc()).all()]
        total = len(child_ids)
        completed = failed = cancelled = 0
        for index, child_id in enumerate(child_ids, start=1):
            db.expire_all()
            batch_task = db.query(Task).filter(Task.id == batch_task_id).first()
            child = db.query(Task).filter(Task.id == child_id).first()
            if not batch_task or batch_task.status == "cancelled":
                for remaining in db.query(Task).filter(
                    Task.parent_task_id == batch_task_id,
                    Task.type == "shot_video",
                    Task.status == "pending",
                ).all():
                    remaining.status = "cancelled"
                    remaining.current_step = "批量任务已取消"
                db.commit()
                return
            if not child:
                failed += 1
                continue
            if child.status == "completed":
                completed += 1
                continue
            if child.status == "failed":
                failed += 1
                continue
            if child.status == "cancelled":
                cancelled += 1
                continue
            shot = db.query(Shot).filter(Shot.id == child.shot_id).first()
            shot_plan = _safe_json_dict(shot.video_director_plan) if shot else {}
            child_metadata = _safe_json_dict(child.metadata_json)
            semantic_batch = child_metadata.get("batch_mode") == "SEMANTIC_CLIP"
            semantic_clips = shot_plan.get("clip_plan") if isinstance(shot_plan.get("clip_plan"), list) else []
            if semantic_batch and not semantic_clips:
                semantic_clips = [{}]
            if child.status == "running" and child.comfyui_prompt_id and not semantic_clips:
                status = await _wait_for_persistent_task(db, child.id)
            else:
                if child.status == "running":
                    child.status = "pending"
                    child.started_at = None
                child.status = "running"
                child.started_at = datetime.utcnow()
                child.current_step = "自动补齐视频生成细节" if auto_complete else "检查视频生成条件"
                batch_task.current_step = f"正在处理 {index}/{total}：镜{db.query(Shot).filter(Shot.id == child.shot_id).first().index}"
                db.commit()
                try:
                    shot = db.query(Shot).filter(Shot.id == child.shot_id).first()
                    plan = _safe_json_dict(shot.video_director_plan) if shot else {}
                    child_metadata = _safe_json_dict(child.metadata_json)
                    semantic_batch = child_metadata.get("batch_mode") == "SEMANTIC_CLIP"
                    semantic_clips = plan.get("clip_plan") if isinstance(plan.get("clip_plan"), list) else []
                    if semantic_batch and not semantic_clips:
                        semantic_clips = [{}]
                    if semantic_clips:
                        conflicting_legacy_children = db.query(Task).filter(
                            Task.parent_task_id == batch_task_id,
                            Task.shot_id == shot.id,
                            Task.type == "shot_video",
                            Task.batch_order.is_(None),
                        ).count()
                        if conflicting_legacy_children:
                            raise RuntimeError("Batch child 结构已包含旧 Shot-level Task；拒绝与 Semantic Clip Tasks 混合完成")
                        batch_task = db.query(Task).filter(Task.id == batch_task_id).first()
                        status = await _run_semantic_shot_for_batch(db, batch_task, child, shot)
                        if status in {"waiting_review", "waiting_dependency"}:
                            child.status = "pending"
                            child.completed_at = None
                            child.error_message = None
                            batch_task.status = "pending"
                            batch_task.current_step = f"Shot {shot.index} {status}"
                            db.commit()
                            return
                        child.status = status
                        child.progress = 100 if status in {"completed", "failed", "cancelled"} else child.progress
                        child.completed_at = datetime.utcnow() if status in {"completed", "failed", "cancelled"} else child.completed_at
                        if status != "completed":
                            child.error_message = child.error_message or f"Semantic Shot Final {status}"
                        db.commit()
                    else:
                        selected_mode = (
                            await _prepare_batch_video_details(db, batch_task, child)
                            if auto_complete
                            else (plan.get("selected_mode") or plan.get("recommended_mode") or "SINGLE_FRAME")
                        )
                        db.expire_all()
                        child = db.query(Task).filter(Task.id == child_id).first()
                        _prepare_and_enqueue_batch_video_child(db, child, selected_mode, use_reference_audio, skip_llm)
                        status = await _wait_for_persistent_task(db, child.id)
                except Exception as exc:
                    child = db.query(Task).filter(Task.id == child_id).first()
                    if child:
                        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
                        child.status = "failed"
                        child.error_message = str(detail)
                        child.current_step = "批量视频子任务失败"
                        child.completed_at = datetime.utcnow()
                        shot = db.query(Shot).filter(Shot.id == child.shot_id).first()
                        if shot:
                            shot.video_status = "failed"
                        db.commit()
                    status = "failed"
            if status == "completed":
                completed += 1
            elif status == "cancelled":
                cancelled += 1
            else:
                failed += 1
            batch_task = db.query(Task).filter(Task.id == batch_task_id).first()
            if batch_task:
                batch_task.progress = int(index / total * 100) if total else 100
                batch_task.current_step = f"已处理 {index}/{total} 个分镜视频"
                db.commit()

        batch_task = db.query(Task).filter(Task.id == batch_task_id).first()
        if batch_task:
            batch_task.status = "completed" if failed == 0 and cancelled == 0 else "failed"
            batch_task.progress = 100
            batch_task.completed_at = datetime.utcnow()
            batch_task.current_step = f"完成：成功 {completed}，失败 {failed}，取消 {cancelled}"
            batch_task.error_message = None if failed == 0 and cancelled == 0 else batch_task.current_step
            db.commit()
    except Exception as exc:
        batch_task = db.query(Task).filter(Task.id == batch_task_id).first()
        if batch_task:
            batch_task.status = "failed"
            batch_task.error_message = str(exc)
            batch_task.current_step = "批量视频生成失败"
            batch_task.completed_at = datetime.utcnow()
            db.commit()
        print(f"[ShotVideoBatch] task {batch_task_id} failed: {exc}")
    finally:
        shot_video_batch_locks.discard(batch_task_id)
        db.close()


def resume_active_shot_video_batches() -> None:
    db = SessionLocal()
    try:
        active_batches = db.query(Task).filter(
            Task.type == "shot_video_batch",
            Task.status.in_(["pending", "running"]),
        ).order_by(Task.created_at.asc()).all()
        for batch_task in active_batches:
            enqueue_shot_video_batch_task(batch_task.id)
    finally:
        db.close()


@router.post("/{novel_id}/chapters/{chapter_id}/shot-videos/batch", response_model=dict)
async def generate_shot_videos_batch(
    novel_id: str,
    chapter_id: str,
    data: BatchShotVideoRequest,
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
):
    """创建持久化批量视频任务；页面关闭或服务重启后可继续。"""
    shot_ids = list(dict.fromkeys(data.shot_ids))
    if not shot_ids:
        raise HTTPException(status_code=400, detail="请选择要生成视频的分镜")
    novel = novel_repo.get_by_id(novel_id)
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not novel or not chapter:
        raise HTTPException(status_code=404, detail="小说或章节不存在")

    validated = []
    selected_shots = []
    for order, shot_id in enumerate(shot_ids, start=1):
        shot = shot_repo.get_by_id(shot_id)
        if not shot or shot.chapter_id != chapter_id:
            raise HTTPException(status_code=404, detail=f"分镜不存在：{shot_id}")
        plan = _safe_json_dict(shot.video_director_plan)
        semantic = isinstance(plan.get("clip_plan"), list) and bool(plan.get("clip_plan"))
        if semantic and plan.get("canonical_visual_plan") is True:
            readiness = get_canonical_execution_readiness(shot, plan)
            if not readiness["ready"]:
                detail = dict(readiness["blocking_clips"][0])
                detail.update({"shot_id": shot.id, "shot_index": shot.index})
                raise HTTPException(status_code=409, detail=detail)
            _ensure_required_physical_images(shot, plan)
        if not shot.image_url:
            raise HTTPException(status_code=400, detail=f"分镜 {shot.index} 尚未生成主分镜图")
        selected_shots.append({
            "shot_id": shot.id,
            "clip_plan_revision": int(plan.get("clip_plan_revision") or 0) if semantic else None,
            "batch_mode": "SEMANTIC_CLIP" if semantic else "LEGACY_SHOT",
        })
        active = db.query(Task).filter(
            Task.type == "shot_video",
            Task.shot_id == shot.id,
            Task.status.in_(["pending", "running"]),
        ).order_by(Task.created_at.desc()).first()
        if active:
            raise HTTPException(status_code=400, detail=f"分镜 {shot.index} 已有进行中的视频任务")
        validated.append((order, shot, None))

    modes = {item["batch_mode"] for item in selected_shots}
    batch_mode = next(iter(modes)) if len(modes) == 1 else "MIXED"

    batch_task = Task(
        type="shot_video_batch",
        status="pending",
        name="批量生成分镜视频",
        description=f"为章节 '{chapter.title}' 批量生成 {len(validated)} 个分镜视频",
        novel_id=novel_id,
        chapter_id=chapter_id,
        progress=0,
        current_step="等待处理",
        metadata_json=json.dumps({
            "shot_ids": shot_ids,
            "selected_shots": selected_shots,
            "batch_mode": batch_mode,
            "auto_complete_details": data.auto_complete_details,
            "use_reference_audio": data.use_reference_audio,
            "skip_llm_when_prompt_exists": data.skip_llm_when_prompt_exists,
            "force_rerun": data.force_rerun,
            "auto_assemble": data.auto_assemble,
        }, ensure_ascii=False),
    )
    db.add(batch_task)
    db.flush()
    children = []
    for order, shot, active in validated:
        child = active or Task(
            type="shot_video",
            name=f"生成视频: 镜{shot.index}",
            description=f"为章节 '{chapter.title}' 的分镜 {shot.index} 生成视频 (时长: {shot.duration or 4}s)",
            novel_id=novel_id,
            chapter_id=chapter_id,
            shot_id=shot.id,
            status="pending",
            current_step="等待批量处理",
        )
        if not active:
            db.add(child)
            db.flush()
        child.parent_task_id = batch_task.id
        child.batch_order = order
        child.metadata_json = json.dumps({
            **_safe_json_dict(child.metadata_json),
            "batch_shot_child": True,
            "batch_force_rerun": data.force_rerun,
            "batch_mode": "SEMANTIC_CLIP" if any(item["shot_id"] == shot.id and item["batch_mode"] == "SEMANTIC_CLIP" for item in selected_shots) else "LEGACY_SHOT",
            "clip_plan_revision": next((item["clip_plan_revision"] for item in selected_shots if item["shot_id"] == shot.id), None),
            "auto_assemble": data.auto_assemble,
        }, ensure_ascii=False)
        shot.video_status = "pending"
        shot.video_task_id = child.id
        children.append(child)
    db.flush()
    db.commit()
    enqueue_shot_video_batch_task(batch_task.id)
    return {
        "success": True,
        "message": f"已创建 {len(children)} 个持久化分镜视频任务，关闭页面后会继续执行",
        "data": {
            "batchTaskId": batch_task.id,
            "tasks": [{"taskId": task.id, "shotId": task.shot_id, "status": task.status} for task in children],
        },
    }


@router.post(
    "/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/generate-video",
    response_model=dict,
)
async def generate_shot_video(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    request: GenerateVideoRequest = GenerateVideoRequest(),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    task_repo: TaskRepository = Depends(get_task_repo),
    workflow_repo: WorkflowRepository = Depends(get_workflow_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
):
    """为指定分镜生成视频（基于已生成的分镜图片）

    Args:
        request: 视频生成请求参数
            - use_keyframes: 是否使用关键帧（如果存在），默认 True
            - use_reference_audio: 是否使用参考音频（如果存在），默认 True
            - workflow_id: 指定工作流ID（可选）
    """
    # 获取章节
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)

    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    # 获取小说
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    # 从 Shot 表获取分镜数据；兼容旧 API 按分镜序号传参。
    shot = _resolve_shot_by_id_or_index(shot_repo, chapter_id, shot_id)

    if not shot:
        raise HTTPException(status_code=400, detail=f"分镜 {shot_id} 不存在")

    video_director_plan = _safe_json_dict(shot.video_director_plan)
    _reject_legacy_video_execution_for_canonical(video_director_plan)

    shot_index = shot.index
    shot_duration = shot.duration or 4

    # 检查是否有已生成的分镜图片
    shot_image_url = shot.image_url

    if not shot_image_url:
        raise HTTPException(
            status_code=400, detail="该分镜尚未生成图片，请先生成分镜图片"
        )

    # 检查是否已有进行中的视频生成任务
    existing_task = task_repo.get_active_shot_task(
        novel_id, chapter_id, shot_index, "shot_video"
    )

    if existing_task:
        return {
            "success": True,
            "message": "已有进行中的视频生成任务",
            "data": {"taskId": existing_task.id, "status": existing_task.status},
        }

    # 检查是否有失败的任务，如果有则删除旧任务以便重新生成
    failed_task = task_repo.get_failed_shot_task(
        novel_id, chapter_id, shot_index, "shot_video"
    )

    if failed_task:
        print(
            f"[GenerateVideo] Deleting failed task {failed_task.id} for shot {shot_id} to allow regeneration"
        )
        task_repo.delete(failed_task)

    selected_mode = request.selected_mode or video_director_plan.get("selected_mode") or "SINGLE_FRAME"
    expected_workflow_type = "video"
    if selected_mode == "FIRST_LAST_FRAME":
        expected_workflow_type = "first_last_video"
    elif selected_mode == "MULTI_KEYFRAME":
        valid_plan, plan_error, first_frame_count = _validate_multi_keyframe_plan_for_execution(shot, video_director_plan)
        if not valid_plan:
            final_error = f"视频生成前置检查失败：{plan_error}"
            _mark_video_director_planning_failed(shot, shot_repo, video_director_plan, final_error)
            raise HTTPException(status_code=400, detail=final_error)
        window_plans = video_director_plan.get("window_plans") if isinstance(video_director_plan.get("window_plans"), list) else []
        needed_workflow_types = {
            "three_frame_video" if int(window_plan.get("selected_frame_count") or 0) == 3 else "four_frame_video"
            for window_plan in window_plans
        }
        for workflow_type in needed_workflow_types:
            clip_workflow = workflow_repo.get_active_by_type(workflow_type)
            if not clip_workflow:
                raise HTTPException(status_code=400, detail=f"未配置 {workflow_type} 视频生成工作流，请在系统设置中配置")
            is_valid, error_msg = TaskService.validate_workflow_node_mapping(clip_workflow, workflow_type)
            if not is_valid:
                raise HTTPException(status_code=400, detail=error_msg)
        expected_workflow_type = "three_frame_video" if first_frame_count == 3 else "four_frame_video"

    # 获取视频生成工作流（优先使用指定的工作流，否则按 selected_mode 使用激活工作流）
    if request.workflow_id:
        workflow = workflow_repo.get_by_id(request.workflow_id)
        if not workflow or workflow.type != expected_workflow_type:
            raise HTTPException(status_code=400, detail="指定的工作流不存在或类型不正确")
    else:
        workflow = workflow_repo.get_active_by_type(expected_workflow_type)

    if not workflow:
        raise HTTPException(
            status_code=400, detail=f"未配置 {expected_workflow_type} 视频生成工作流，请在系统设置中配置"
        )

    if selected_mode == "FIRST_LAST_FRAME":
        max_clip_duration = _get_video_workflow_capability(workflow)["max_clip_duration"]
        if shot_duration > max_clip_duration:
            raise HTTPException(status_code=400, detail=f"首尾帧模式当前仅支持不超过 {max_clip_duration}s 的 Shot；请改用多关键帧模式。")
        keyframes = video_director_plan.get("keyframes") if isinstance(video_director_plan.get("keyframes"), list) else []
        end_keyframe = next((keyframe for keyframe in keyframes if isinstance(keyframe, dict) and keyframe.get("role") == "END"), None)
        end_image_url = _get_video_director_keyframe_image_url(shot, end_keyframe)
        if not end_image_url or not url_to_local_path(end_image_url):
            raise HTTPException(status_code=400, detail="首尾帧模式需要先生成 END 关键帧图片。")

    # 验证工作流节点映射配置
    is_valid, error_msg = TaskService.validate_workflow_node_mapping(workflow, expected_workflow_type)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    # 清除该分镜的旧视频文件和记录。所有 preflight 通过后再删除，避免计划未就绪时丢失旧视频。
    if shot.video_url:
        print(f"[GenerateVideo] Clearing old video record for shot {shot_id}: {shot.video_url}")
    file_storage.delete_shot_video(novel_id, chapter_id, shot_index)
    shot.video_url = None
    shot.video_task_id = None
    shot_repo.update_video_status(shot, "generating")

    # 使用 Repository 创建任务记录
    task = task_repo.create_shot_video_task(
        novel_id=novel_id,
        chapter_id=chapter_id,
        shot_index=shot_index,
        shot_duration=shot_duration,
        chapter_title=chapter.title,
        workflow_id=workflow.id,
        workflow_name=workflow.name,
        shot_id=shot.id,
    )

    print(f"[GenerateVideo] Created task {task.id} for shot {shot.id}")
    task.description = f"{task.description}；视频模式：{VIDEO_MODE_LABELS.get(selected_mode, selected_mode)}"
    db = shot_repo.db
    db.commit()
    print(f"[GenerateVideo] selected_mode={selected_mode}, use_keyframes={request.use_keyframes}, use_reference_audio={request.use_reference_audio}")

    # 更新 Shot 表任务 ID
    shot_repo.update_video_status(shot, "generating", task_id=task.id)

    generate_shot_video_task(
        task.id,
        novel_id,
        chapter_id,
        shot_index,
        workflow.id,
        shot_image_url,
        use_keyframes=request.use_keyframes,
        use_reference_audio=request.use_reference_audio,
        selected_mode=selected_mode,
        skip_llm_when_prompt_exists=request.skip_llm_when_prompt_exists,
    )

    return {
        "success": True,
        "message": "视频生成任务已创建",
        "data": {"taskId": task.id, "status": "pending"},
    }


# ==================== 转场视频生成 ====================


@router.post("/{novel_id}/chapters/{chapter_id}/transitions", response_model=dict)
async def generate_transition_video(
    novel_id: str,
    chapter_id: str,
    data: TransitionVideoRequest,
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    task_repo: TaskRepository = Depends(get_task_repo),
    workflow_repo: WorkflowRepository = Depends(get_workflow_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
):
    """
    生成转场视频（两个分镜之间）
    """
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)

    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    from_index = data.from_index
    to_index = data.to_index
    duration_seconds = data.duration_seconds
    frame_count = data.frame_count
    workflow_id = data.workflow_id

    # 从 shots 表获取分镜数据
    shots = shot_repo.get_by_chapter(chapter_id)

    if not shots or len(shots) < 2:
        raise HTTPException(status_code=400, detail="分镜数据不足，无法生成转场")

    if from_index < 1 or to_index > len(shots) or from_index >= to_index:
        raise HTTPException(status_code=400, detail="无效的分镜索引")

    # 从 shots 表获取分镜视频 URL（get_by_chapter 已按 index 排序）
    first_video = shots[from_index - 1].video_url if from_index <= len(shots) else None
    second_video = shots[to_index - 1].video_url if to_index <= len(shots) else None

    if not first_video or not second_video:
        raise HTTPException(
            status_code=400, detail="分镜视频尚未生成，请先生成分镜视频"
        )

    # 检查是否已有进行中的转场视频任务
    existing_task = task_repo.get_transition_task(
        novel_id, chapter_id, from_index, to_index
    )

    if existing_task:
        return {
            "success": True,
            "message": "转场视频生成任务已在进行中",
            "task_id": existing_task.id,
            "status": existing_task.status,
        }

    # 获取转场视频工作流
    if workflow_id:
        workflow = workflow_repo.get_by_id(workflow_id)
        if not workflow:
            raise HTTPException(status_code=400, detail="指定的工作流不存在")
    else:
        workflow = workflow_repo.get_active_by_type("transition")

    if not workflow:
        raise HTTPException(
            status_code=400, detail="未配置转场视频工作流，请在系统设置中配置"
        )

    # 验证工作流节点映射配置
    is_valid, error_msg = TaskService.validate_workflow_node_mapping(
        workflow, "transition"
    )
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    # 使用 Repository 创建任务记录
    task = task_repo.create_transition_video_task(
        novel_id=novel_id,
        chapter_id=chapter_id,
        from_index=from_index,
        to_index=to_index,
        chapter_title=chapter.title,
        workflow_id=workflow.id,
        workflow_name=workflow.name,
        frame_count=frame_count,
    )

    print(
        f"[Transition] Created task {task.id} for transition {from_index}->{to_index} using workflow {workflow.name}"
    )

    enqueue_transition_video_task(
        task.id,
        novel_id,
        chapter_id,
        from_index,
        to_index,
        workflow.id,
        duration_seconds,
        frame_count,
    )

    return {
        "success": True,
        "message": "转场视频生成任务已创建",
        "task_id": task.id,
        "status": "pending",
    }


@router.post("/{novel_id}/chapters/{chapter_id}/transitions/batch", response_model=dict)
async def generate_all_transitions(
    novel_id: str,
    chapter_id: str,
    data: BatchTransitionRequest = BatchTransitionRequest(),
    db: Session = Depends(get_db),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    task_repo: TaskRepository = Depends(get_task_repo),
    workflow_repo: WorkflowRepository = Depends(get_workflow_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
):
    """一键生成所有相邻分镜之间的转场视频"""
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)

    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    # 从 shots 表获取分镜数据
    shots = shot_repo.get_by_chapter(chapter_id)

    if len(shots) < 2:
        raise HTTPException(status_code=400, detail="分镜数量不足，无法生成转场")

    # 检查是否所有分镜都有视频
    shots_without_video = [s for s in shots if not s.video_url]
    if shots_without_video:
        raise HTTPException(
            status_code=400, detail="部分分镜视频尚未生成，请先生成所有分镜视频"
        )

    duration_seconds = data.duration_seconds
    frame_count = data.frame_count
    workflow_id = data.workflow_id

    # 获取转场视频工作流
    if workflow_id:
        workflow = workflow_repo.get_by_id(workflow_id)
        if not workflow:
            raise HTTPException(status_code=400, detail="指定的工作流不存在")
    else:
        workflow = workflow_repo.get_active_by_type("transition")

    if not workflow:
        raise HTTPException(status_code=400, detail="未配置转场视频工作流")

    # 验证工作流节点映射配置
    is_valid, error_msg = TaskService.validate_workflow_node_mapping(
        workflow, "transition"
    )
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    # 为每对相邻分镜创建任务
    task_ids = []
    for i in range(1, len(shots)):
        from_idx = i
        to_idx = i + 1

        # 检查是否已有进行中的任务
        existing_task = task_repo.get_transition_task(
            novel_id, chapter_id, from_idx, to_idx
        )

        if existing_task:
            task_ids.append(existing_task.id)
            continue

        task = task_repo.create_transition_video_task(
            novel_id=novel_id,
            chapter_id=chapter_id,
            from_index=from_idx,
            to_index=to_idx,
            chapter_title=chapter.title,
            workflow_id=workflow.id,
            workflow_name=workflow.name,
            frame_count=frame_count,
        )
        task_ids.append(task.id)

        enqueue_transition_video_task(
            task.id,
            novel_id,
            chapter_id,
            from_idx,
            to_idx,
            workflow.id,
            duration_seconds,
            frame_count,
        )

    return {
        "success": True,
        "message": f"已创建 {len(task_ids)} 个转场视频生成任务",
        "task_count": len(task_ids),
        "task_ids": task_ids,
    }


# ==================== 素材下载与合并 ====================


@router.get("/{novel_id}/chapters/{chapter_id}/download-materials", response_model=dict)
async def download_chapter_materials(
    novel_id: str,
    chapter_id: str,
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
    db: Session = Depends(get_db),
):
    """导出当前 Chapter 的 canonical archive package。"""
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    chapter_shots = shot_repo.get_by_chapter(chapter_id)
    descriptor, zip_path = tempfile.mkstemp(prefix="novelflow_chapter_archive_", suffix=".zip")
    os.close(descriptor)
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            build_chapter_archive_package(archive, db, novel, chapter, chapter_shots)
    except Exception as exc:
        try:
            os.remove(zip_path)
        except OSError:
            pass
        raise HTTPException(status_code=500, detail=f"章节归档包创建失败: {exc}") from exc

    filename = f"chapter_{int(chapter.number):03d}_archive.zip"
    try:
        return FileResponse(
            zip_path,
            media_type="application/zip",
            filename=filename,
            background=BackgroundTask(os.remove, zip_path),
        )
    except Exception:
        try:
            os.remove(zip_path)
        except OSError:
            pass
        raise


def _build_shot_image_data_response(
    db: Session,
    novel_id: str,
    chapter_id: str,
    chapter,
    shots,
    filename: str,
):
    def resolve_path(value: Optional[str]) -> Optional[Path]:
        if not value:
            return None
        local = url_to_local_path(value)
        path = Path(local or value)
        return path if path.exists() and path.is_file() else None

    def safe_json(value, default):
        if not value:
            return default
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(value)
        except Exception:
            return default

    def add_file(zip_file: zipfile.ZipFile, source: Optional[str], arcname: str, manifest_items: list, label: str) -> None:
        path = resolve_path(source)
        if not path:
            return
        zip_file.write(path, arcname)
        manifest_items.append({"label": label, "path": arcname})

    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        parsed_data = safe_json(chapter.parsed_data, {})
        zip_file.writestr("ai_split_result.json", json.dumps(parsed_data, ensure_ascii=False, indent=2))

        manifest = {
            "version": 1,
            "novel_id": novel_id,
            "chapter_id": chapter_id,
            "generated_at": datetime.utcnow().isoformat(),
            "shots": [],
        }

        for shot in shots:
            shot_dir = f"shot{int(shot.index):03d}"
            latest_task = None
            if shot.image_task_id:
                latest_task = (
                    db.query(Task)
                    .filter(
                        Task.id == shot.image_task_id,
                        Task.shot_id == shot.id,
                        Task.type == "shot_image",
                        Task.workflow_json.isnot(None),
                    )
                    .first()
                )
            if not latest_task:
                latest_task = (
                    db.query(Task)
                    .filter(
                        Task.shot_id == shot.id,
                        Task.type == "shot_image",
                        Task.workflow_json.isnot(None),
                    )
                    .order_by(Task.created_at.desc())
                    .first()
                )
            scene = None
            if shot.scene:
                scene = (
                    db.query(Scene)
                    .filter(Scene.novel_id == novel_id, Scene.name == shot.scene)
                    .first()
                )

            shot_manifest = {
                "shot_id": shot.id,
                "index": shot.index,
                "materials": [],
            }
            add_file(zip_file, shot.merged_character_image, f"{shot_dir}/合并角色图{Path(resolve_path(shot.merged_character_image) or '').suffix or '.png'}", shot_manifest["materials"], "合并角色图")
            if scene:
                add_file(zip_file, scene.image_url, f"{shot_dir}/场景图{Path(resolve_path(scene.image_url) or '').suffix or '.png'}", shot_manifest["materials"], "场景图")
            add_file(zip_file, shot.merged_prop_image, f"{shot_dir}/合并道具图{Path(resolve_path(shot.merged_prop_image) or '').suffix or '.png'}", shot_manifest["materials"], "合并道具图")
            add_file(zip_file, shot.image_url or shot.image_path, f"{shot_dir}/生成的分镜图{Path(resolve_path(shot.image_url or shot.image_path) or '').suffix or '.png'}", shot_manifest["materials"], "生成的分镜图")

            prompt_text = latest_task.prompt_text if latest_task and latest_task.prompt_text else shot.shot_image_prompt or ""
            zip_file.writestr(f"{shot_dir}/主分镜图AI提示词.txt", prompt_text)
            shot_manifest["materials"].append({"label": "主分镜图AI提示词", "path": f"{shot_dir}/主分镜图AI提示词.txt"})

            workflow_json = latest_task.workflow_json if latest_task and latest_task.workflow_json else ""
            if workflow_json:
                workflow_obj = safe_json(workflow_json, workflow_json)
                workflow_content = json.dumps(workflow_obj, ensure_ascii=False, indent=2) if not isinstance(workflow_obj, str) else workflow_obj
                zip_file.writestr(f"{shot_dir}/生成图真实工作流.json", workflow_content)
                shot_manifest["materials"].append({
                    "label": "生成图真实工作流",
                    "path": f"{shot_dir}/生成图真实工作流.json",
                    "task_id": latest_task.id,
                    "workflow_id": latest_task.workflow_id,
                    "workflow_name": latest_task.workflow_name,
                    "comfyui_prompt_id": latest_task.comfyui_prompt_id,
                    "kind": "submitted_comfyui_workflow",
                })

            manifest["shots"].append(shot_manifest)

        zip_file.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/download-shot-image-data")
async def download_current_shot_image_data_package(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
):
    """打包当前分镜图生成数据。"""
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    shot = shot_repo.get_by_id(shot_id)
    if not shot or shot.chapter_id != chapter_id:
        raise HTTPException(status_code=404, detail="分镜不存在")

    chapter_short = chapter_id[:8] if chapter_id else "unknown"
    filename = f"chapter_{chapter_short}_shot_{int(shot.index):03d}_shot_image_data.zip"
    return _build_shot_image_data_response(db, novel_id, chapter_id, chapter, [shot], filename)


@router.get("/{novel_id}/chapters/{chapter_id}/download-shot-image-data")
async def download_shot_image_data_package(
    novel_id: str,
    chapter_id: str,
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
):
    """打包当前章回所有分镜图生成数据。"""
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    shots = shot_repo.get_by_chapter(chapter_id)
    if not shots:
        raise HTTPException(status_code=404, detail="章节分镜不存在")

    chapter_short = chapter_id[:8] if chapter_id else "unknown"
    filename = f"chapter_{chapter_short}_shot_image_data.zip"
    return _build_shot_image_data_response(db, novel_id, chapter_id, chapter, shots, filename)


@router.post("/{novel_id}/chapters/{chapter_id}/merge-videos", response_model=dict)
async def merge_chapter_videos(
    novel_id: str,
    chapter_id: str,
    data: MergeVideosRequest,
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
    db: Session = Depends(get_db),
):
    """创建章节视频合并任务。"""
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    mode = data.mode or ("shots_with_transitions" if data.include_transitions else "shots_only")

    shots = shot_repo.get_by_chapter(chapter_id)
    selected_shot_ids = set(data.shot_ids or [])
    if selected_shot_ids:
        selected_chapter_shot_ids = {shot.id for shot in shots}
        invalid_shot_ids = selected_shot_ids - selected_chapter_shot_ids
        if invalid_shot_ids:
            return {"success": False, "message": "选择的分镜不属于当前章节"}

    video_variant = data.video_variant
    selected = [shot for shot in shots if not selected_shot_ids or shot.id in selected_shot_ids]
    target_megapixels = data.target_megapixels
    if video_variant == "hd" and target_megapixels is None:
        return {"success": False, "message": "合并高清视频必须选择明确的目标 MP"}
    if video_variant == "hd" and len(selected) != len(shots):
        return {"success": False, "message": "高清章回视频必须包含本章全部 Shot"}

    if video_variant == "hd":
        from app.services.hd_repaint_service import get_latest_completed_hd_task
        frozen_inputs = []
        for shot in selected:
            execution = get_latest_completed_hd_task(db, shot.id, target_megapixels)
            if execution:
                frozen_inputs.append({
                    "shot_id": shot.id,
                    "shot_index": shot.index,
                    "execution_task_id": execution.id,
                    "video_url": execution.result_url,
                })
        available_ids = {item["shot_id"] for item in frozen_inputs}
        missing = [shot.index for shot in selected if shot.id not in available_ids]
    else:
        frozen_inputs = [{
            "shot_id": shot.id,
            "shot_index": shot.index,
            "execution_task_id": shot.video_task_id,
            "video_url": shot.video_url,
        } for shot in selected if shot.video_url]
        missing = [shot.index for shot in selected if not shot.video_url]
    if missing:
        label = f"高清 {target_megapixels} MP" if video_variant == "hd" else "初稿"
        return {"success": False, "message": f"以下分镜缺少{label}视频：{', '.join(map(str, missing))}"}
    selected_count = len(selected)
    if selected_count == 0:
        return {"success": False, "message": "没有分镜视频可以合并"}

    task = Task(
        type="chapter_video",
        status="pending",
        novel_id=novel_id,
        chapter_id=chapter_id,
        name=f"合并章节视频: {chapter.title or chapter.number}",
        description=f"合并章节 '{chapter.title or chapter.number}' 的 {selected_count} 个{f'高清 {target_megapixels} MP' if video_variant == 'hd' else '初稿'}分镜视频",
        progress=0,
        current_step="等待合并章节视频...",
        metadata_json=json.dumps({
            "mode": mode,
            "shot_ids": [shot.id for shot in selected],
            "video_variant": video_variant,
            "target_megapixels": target_megapixels,
            "inputs": frozen_inputs,
        }, ensure_ascii=False),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    enqueue_chapter_video_merge_task(task.id)

    return {
        "success": True,
        "data": {"taskId": task.id, "status": task.status, "mode": mode, "videoVariant": video_variant, "targetMegapixels": target_megapixels},
        "message": "章节视频合并任务已提交，可在任务列表查看进度。",
    }


# ==================== 资源管理 ====================


@router.post("/{novel_id}/chapters/{chapter_id}/clear-resources", response_model=dict)
async def clear_chapter_resources(
    novel_id: str,
    chapter_id: str,
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
):
    """清除章节的所有生成资源（用于重新拆分分镜头前）"""
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    # 删除物理文件
    print(f"[ClearResources] Deleting physical files for chapter {chapter_id}")
    file_deleted = file_storage.delete_chapter_directory(novel_id, chapter_id)

    # 删除 Shot 记录
    shot_repo = ShotRepository(db)
    shot_count = shot_repo.delete_by_chapter(chapter_id)

    # 清除数据库记录
    chapter.parsed_data = None
    chapter.shot_images = None
    chapter.shot_videos = None
    chapter.transition_videos = None
    chapter.merged_image = None

    db.commit()

    print(f"[ClearResources] Chapter resources cleared. Files deleted: {file_deleted}, Shots deleted: {shot_count}")

    return {
        "success": True,
        "message": "章节资源已清除"
        + ("（包含物理文件）" if file_deleted else "（物理文件清除失败）"),
        "files_deleted": file_deleted,
    }


@router.post("/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/reset-video-data", response_model=dict)
async def reset_shot_video_data(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    db: Session = Depends(get_db),
):
    """Reset one Shot's video stage while preserving its main image and shot data."""
    shot = db.query(Shot).filter(Shot.id == shot_id, Shot.chapter_id == chapter_id).first()
    if not db.query(Novel).filter(Novel.id == novel_id).first():
        raise HTTPException(status_code=404, detail="小说不存在")
    if not db.query(Chapter).filter(Chapter.id == chapter_id, Chapter.novel_id == novel_id).first():
        raise HTTPException(status_code=404, detail="章节不存在")
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")

    plan = _safe_json_dict(shot.video_director_plan)
    if plan.get("canonical_visual_plan") is True:
        raise HTTPException(
            status_code=409,
            detail="Canonical Shot 禁止使用 broad reset；请使用视觉状态、Clip 和 Final Assembly 的精确恢复操作。",
        )

    def local_files_from_json(value) -> set[str]:
        paths: set[str] = set()
        items = value if isinstance(value, list) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            for key in ("image_url", "imageUrl", "image_path", "imagePath", "local_path", "localPath", "video_url", "videoUrl"):
                local_path = url_to_local_path(item.get(key)) if item.get(key) else None
                if local_path:
                    paths.add(local_path)
        return paths

    keyframes = _safe_json_list(shot.keyframes)
    files_to_delete = local_files_from_json(plan.get("keyframes")) | local_files_from_json(keyframes)
    files_to_delete.update(local_files_from_json(plan.get("clip_plan")))
    files_to_delete.update(local_files_from_json(plan.get("window_plans")))
    files_to_delete.update(local_files_from_json(plan.get("clips")))

    tasks = db.query(Task).filter(Task.shot_id == shot.id, Task.type.in_(["shot_video", "keyframe_image"])).all()
    for task in tasks:
        if task.result_url:
            local_path = url_to_local_path(task.result_url)
            if local_path:
                files_to_delete.add(local_path)
        metadata = _safe_json_dict(task.metadata_json)
        for key in ("previous_approved_video_url", "source_video_url"):
            local_path = url_to_local_path(metadata.get(key)) if metadata.get(key) else None
            if local_path:
                files_to_delete.add(local_path)

    # Delete only paths inside this novel's storage tree; never follow arbitrary URLs.
    storage_root = file_storage._get_story_dir(novel_id).resolve()
    for raw_path in files_to_delete:
        try:
            path = Path(raw_path).resolve()
            if path.is_file() and (path == storage_root or storage_root in path.parents):
                path.unlink()
        except (OSError, RuntimeError):
            pass
    file_storage.delete_shot_video(novel_id, chapter_id, shot.index)
    file_storage.delete_shot_video(novel_id, chapter_id, shot.index, variant="hd")

    task_ids = {task.id for task in tasks}
    parent_ids = {task.parent_task_id for task in tasks if task.parent_task_id}
    for task in tasks:
        db.delete(task)
    db.flush()
    # Remove empty batch parents, including the Shot-level child that may have
    # owned semantic Clip tasks. Keep a batch parent if it still contains other Shots.
    pending_parent_ids = set(parent_ids)
    while pending_parent_ids:
        parent_id = pending_parent_ids.pop()
        parent = db.query(Task).filter(Task.id == parent_id).first()
        if not parent:
            continue
        remaining = db.query(Task).filter(Task.parent_task_id == parent.id).count()
        if remaining == 0:
            ancestor_id = parent.parent_task_id
            db.delete(parent)
            db.flush()
            if ancestor_id:
                pending_parent_ids.add(ancestor_id)

    shot.video_director_plan = json.dumps({}, ensure_ascii=False)
    shot.keyframes = json.dumps([], ensure_ascii=False)
    shot.video_url = None
    shot.video_status = "pending"
    shot.video_task_id = None
    shot.hd_video_url = None
    shot.hd_video_status = "pending"
    shot.hd_video_task_id = None
    shot.hd_video_source_task_id = None
    shot.hd_video_megapixels = None
    db.commit()
    return {"success": True, "message": "当前 Shot 视频阶段已重置", "data": {"shotId": shot.id, "deletedTaskCount": len(task_ids)}}


def _canonical_main_image_previous_path(db, shot):
    previous_url = shot.image_url
    if not previous_url and shot.image_task_id:
        previous = db.query(Task).filter(Task.id == shot.image_task_id).first()
        previous_url = _safe_json_dict(previous.metadata_json).get("canonical_image_previous_url") if previous else None
    return shot.image_path or url_to_local_path(previous_url)


def _cleanup_replaced_main_image(previous_path, new_path):
    if previous_path and Path(previous_path).resolve() != Path(new_path).resolve():
        try:
            Path(previous_path).unlink(missing_ok=True)
        except OSError as exc:
            print(f"[ShotImage] Old image cleanup deferred: {exc}")


@router.post(
    "/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/upload-image",
    response_model=dict,
)
async def upload_shot_image(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
):
    """上传分镜图片"""
    # 验证文件类型
    allowed_types = ["image/png", "image/jpeg", "image/jpg", "image/webp"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型：{file.content_type}，仅支持 PNG, JPG, WEBP",
        )

    # 获取章节
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)

    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    # 从 shots 表查询分镜
    shot = shot_repo.get_by_id(shot_id)

    if not shot or shot.chapter_id != chapter_id:
        raise HTTPException(status_code=404, detail=f"分镜 {shot_id} 不存在")

    shot_index = shot.index

    provenance = state_provenance(shot, 1)
    if provenance:
        # Use a unique file so a same-second legacy name cannot overwrite the
        # currently bound image before the transaction succeeds.
        previous_path = _canonical_main_image_previous_path(db, shot)
        file_path = None
        try:
            content = await file.read()
            base_path = file_storage.get_shot_image_path(
                novel_id=novel_id, chapter_id=chapter_id, shot_number=shot_index, shot_id=shot.id)
            file_path = base_path.with_name(f"{base_path.stem}_{uuid.uuid4().hex}{base_path.suffix}")
            image_url = f"/api/files/{file_path.relative_to(file_storage.base_dir).as_posix()}"
            commit_visual_state_image(db, shot, image_url, frame_index=None,
                                      expected_provenance=provenance, local_path=str(file_path))
            file_path.write_bytes(content)
            db.commit()
        except Exception as exc:
            db.rollback()
            if file_path:
                file_path.unlink(missing_ok=True)
            if isinstance(exc, CanonicalExecutionConflict):
                raise HTTPException(status_code=409, detail=str(exc))
            raise HTTPException(status_code=500, detail=f"上传失败：{exc}")
        _cleanup_replaced_main_image(previous_path, file_path)
        return {"success": True, "message": "图片上传成功", "data": {"imageUrl": image_url}}

    try:
        # 删除旧图片
        file_storage.delete_shot_image(novel_id, chapter_id, shot_index, shot_id=shot.id)

        # 获取保存路径（使用 shot.id 命名文件）
        file_path = file_storage.get_shot_image_path(
            novel_id=novel_id, chapter_id=chapter_id, shot_number=shot_index, shot_id=shot.id
        )

        # 保存文件
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)

        # 计算访问 URL
        relative_path = file_path.relative_to(file_storage.base_dir)
        image_url = f"/api/files/{relative_path}"

        # 更新 shot 记录
        shot_repo.update(
            shot,
            image_url=image_url,
            image_path=str(file_path),
            image_status="completed"
        )

        db.commit()

        return {
            "success": True,
            "message": "图片上传成功",
            "data": {"imageUrl": image_url},
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"上传失败：{str(e)}")


@router.post(
    "/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/edit-image",
    response_model=dict,
)
async def edit_shot_image(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    data: ShotImageEditRequest,
    db: Session = Depends(get_db),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
):
    """使用当前激活的单图编辑工作流编辑分镜图片。"""
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    shot = shot_repo.get_by_id(shot_id)
    if not shot or shot.chapter_id != chapter_id:
        raise HTTPException(status_code=404, detail="分镜不存在")
    if not shot.image_url:
        raise HTTPException(status_code=400, detail="分镜暂无图片，无法编辑")

    result = await SingleImageEditService(db).edit_image(
        source_image_url=shot.image_url,
        prompt=data.prompt,
        novel_id=novel_id,
        entity_id=shot.id,
        entity_name=f"镜{shot.index}",
        entity_type="shot",
        output_image_type="shot_edit",
    )
    if not result.get("success"):
        raise HTTPException(status_code=result.get("status_code", 500), detail=result.get("message", "编辑图片失败"))
    return {"success": True, "data": {"imageUrl": result["image_url"], "taskId": result.get("task_id")}, "message": "图片编辑成功"}


@router.post(
    "/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/replace-image",
    response_model=dict,
)
async def replace_shot_image(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    data: ShotImageReplaceRequest,
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
):
    """用编辑结果替换当前分镜图片。"""
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    shot = shot_repo.get_by_id(shot_id)
    if not shot or shot.chapter_id != chapter_id:
        raise HTTPException(status_code=404, detail="分镜不存在")
    local_path = url_to_local_path(data.image_url)
    if not local_path:
        raise HTTPException(status_code=400, detail="图片文件不存在或不是本地图片")

    db = shot_repo.db
    provenance = state_provenance(shot, 1)
    if provenance:
        previous_path = _canonical_main_image_previous_path(db, shot)
        try:
            commit_visual_state_image(db, shot, data.image_url, frame_index=None,
                                      expected_provenance=provenance, local_path=str(local_path))
            db.commit()
        except Exception as exc:
            db.rollback()
            if isinstance(exc, CanonicalExecutionConflict):
                raise HTTPException(status_code=409, detail=str(exc))
            raise
        _cleanup_replaced_main_image(previous_path, local_path)
        return {"success": True, "data": shot_repo.to_response(shot), "message": "分镜图片已替换"}

    shot = shot_repo.update(
        shot,
        image_url=data.image_url,
        image_path=str(local_path),
        image_status="completed",
    )
    return {"success": True, "data": shot_repo.to_response(shot), "message": "分镜图片已替换"}


# ====================# ==================== 台词音频生成 ====================


@router.post(
    "/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/audio", response_model=dict
)
async def generate_shot_audio(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    request: ShotAudioRequest,
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    task_repo: TaskRepository = Depends(get_task_repo),
    workflow_repo: WorkflowRepository = Depends(get_workflow_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
):
    """
    为指定分镜的角色台词生成音频

    Request Body:
    {
        "dialogues": [
            {
                "character_name": "角色名",
                "text": "台词文本",
                "emotion_prompt": "情感提示词（可选）"
            }
        ]
    }
    """
    from app.repositories.character_repository import CharacterRepository
    from app.services.shot_audio_service import ShotAudioService

    # 获取章节
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    # 获取小说
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    # 从 Shot 表获取分镜数据
    shot = shot_repo.get_by_id(shot_id)
    if not shot or shot.chapter_id != chapter_id:
        raise HTTPException(status_code=404, detail=f"分镜 {shot_id} 不存在")

    shot_index = shot.index

    # 获取台词数据
    dialogues = request.dialogues
    if not dialogues:
        raise HTTPException(status_code=400, detail="请提供要生成的台词数据")

    # 获取音频工作流
    workflow = workflow_repo.get_active_by_type("audio")
    if not workflow:
        raise HTTPException(
            status_code=400, detail="未配置音频生成工作流，请在系统设置中配置"
        )

    # 验证工作流节点映射
    is_valid, error_msg = TaskService.validate_workflow_node_mapping(
        workflow, "character_audio"
    )
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    # 初始化服务和仓库
    character_repo = CharacterRepository(db)
    audio_service = ShotAudioService(db)

    # 创建任务
    result = audio_service.create_shot_audio_tasks(
        novel_id=novel_id,
        chapter_id=chapter_id,
        shot_index=shot_index,
        dialogues=dialogues,
        chapter_title=chapter.title,
        workflow=workflow,
        character_repo=character_repo,
        task_repo=task_repo,
        shot_id=shot_id
    )

    return result


@router.post(
    "/{novel_id}/chapters/{chapter_id}/audio/generate-all", response_model=dict
)
async def generate_all_shot_audio(
    novel_id: str,
    chapter_id: str,
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    task_repo: TaskRepository = Depends(get_task_repo),
    workflow_repo: WorkflowRepository = Depends(get_workflow_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
):
    """
    批量生成章节所有分镜的角色台词音频

    遍历所有分镜的 dialogues 字段，为每个角色台词创建音频生成任务。
    跳过没有参考音频的角色，并在返回结果中记录警告。
    """
    from app.repositories.character_repository import CharacterRepository
    from app.services.shot_audio_service import ShotAudioService

    # 获取章节
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    # 获取小说
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    # 从 Shot 表获取分镜数据
    shots = shot_repo.get_by_chapter(chapter_id)
    if not shots:
        raise HTTPException(status_code=400, detail="章节没有分镜数据")

    # 获取音频工作流
    workflow = workflow_repo.get_active_by_type("audio")
    if not workflow:
        raise HTTPException(
            status_code=400, detail="未配置音频生成工作流，请在系统设置中配置"
        )

    # 验证工作流节点映射
    is_valid, error_msg = TaskService.validate_workflow_node_mapping(
        workflow, "character_audio"
    )
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    # 初始化服务和仓库
    character_repo = CharacterRepository(db)
    audio_service = ShotAudioService(db)

    # 批量创建任务
    result = audio_service.create_batch_audio_tasks(
        novel_id=novel_id,
        chapter_id=chapter_id,
        shots=shots,
        chapter_title=chapter.title,
        workflow=workflow,
        character_repo=character_repo,
        task_repo=task_repo,
    )

    return result


# ==================== 台词音频上传 ====================

# 支持的音频格式
ALLOWED_AUDIO_TYPES = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/flac": ".flac",
    "audio/x-flac": ".flac",
}
MAX_AUDIO_SIZE = 10 * 1024 * 1024  # 10MB


@router.post(
    "/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/dialogues/{character_name}/audio/upload",
    response_model=dict,
)
async def upload_dialogue_audio(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    character_name: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
):
    """
    上传分镜台词音频

    Args:
        novel_id: 小说ID
        chapter_id: 章节ID
        shot_id: 分镜ID
        character_name: 角色名称（URL编码）
        file: 音频文件（mp3、wav、flac，最大10MB）

    Returns:
        上传结果，包含音频URL和更新后的分镜数据
    """
    from urllib.parse import unquote

    # 解码角色名（URL编码）
    character_name = unquote(character_name)

    # 验证文件类型
    if file.content_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {file.content_type}，仅支持 mp3、wav、flac 格式",
        )

    # 验证文件大小
    content = await file.read()
    if len(content) > MAX_AUDIO_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"文件大小超过限制（最大 10MB），当前文件大小: {len(content) / 1024 / 1024:.2f}MB",
        )

    # 获取章节
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    # 解析章节数据
    if not chapter.parsed_data:
        raise HTTPException(status_code=400, detail="章节未拆分，请先进行AI拆分")

    # 从 Shot 表获取分镜数据
    shot = shot_repo.get_by_id(shot_id)
    if not shot or shot.chapter_id != chapter_id:
        raise HTTPException(status_code=404, detail=f"分镜 {shot_id} 不存在")

    shot_index = shot.index

    parsed_data = (
        json.loads(chapter.parsed_data)
        if isinstance(chapter.parsed_data, str)
        else chapter.parsed_data
    )
    shots = parsed_data.get("shots", [])

    if shot_index < 1 or shot_index > len(shots):
        raise HTTPException(status_code=400, detail="分镜索引超出范围")

    # 查找指定角色的台词
    shot_data = shots[shot_index - 1]
    dialogues = shot_data.get("dialogues", [])
    target_dialogue = None
    for dialogue in dialogues:
        if dialogue.get("character_name") == character_name:
            target_dialogue = dialogue
            break

    if not target_dialogue:
        raise HTTPException(
            status_code=404,
            detail=f"分镜 {shot_id} 中未找到角色 '{character_name}' 的台词",
        )

    try:
        # 保存音频文件
        ext = ALLOWED_AUDIO_TYPES.get(file.content_type, ".flac")
        audio_path = file_storage.save_shot_audio(
            novel_id=novel_id,
            shot_index=shot_index,
            character_name=character_name,
            content=content,
            ext=ext,
        )

        # 计算访问 URL
        relative_path = audio_path.relative_to(file_storage.base_dir)
        audio_url = f"/api/files/{relative_path}"

        # 更新 parsed_data 中的音频信息
        target_dialogue["audio_url"] = audio_url
        target_dialogue["audio_source"] = "uploaded"
        target_dialogue["audio_task_id"] = None  # 清除任务ID

        chapter.parsed_data = json.dumps(parsed_data, ensure_ascii=False)
        db.commit()

        return {
            "success": True,
            "data": {
                "shot_id": shot_id,
                "shot_index": shot_index,
                "character_name": character_name,
                "audio_url": audio_url,
                "audio_source": "uploaded",
                "parsed_data": parsed_data,
            },
            "message": "音频上传成功",
        }

    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")


@router.delete(
    "/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/dialogues/{character_name}/audio",
    response_model=dict,
)
async def delete_dialogue_audio(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    character_name: str,
    db: Session = Depends(get_db),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
):
    """
    删除分镜台词音频

    Args:
        novel_id: 小说ID
        chapter_id: 章节ID
        shot_id: 分镜ID
        character_name: 角色名称（URL编码）

    Returns:
        删除结果
    """
    from urllib.parse import unquote

    # 解码角色名（URL编码）
    character_name = unquote(character_name)

    # 获取章节
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    # 解析章节数据
    if not chapter.parsed_data:
        raise HTTPException(status_code=400, detail="章节未拆分，请先进行AI拆分")

    # 从 Shot 表获取分镜数据
    shot = shot_repo.get_by_id(shot_id)
    if not shot or shot.chapter_id != chapter_id:
        raise HTTPException(status_code=404, detail=f"分镜 {shot_id} 不存在")

    shot_index = shot.index

    parsed_data = (
        json.loads(chapter.parsed_data)
        if isinstance(chapter.parsed_data, str)
        else chapter.parsed_data
    )
    shots = parsed_data.get("shots", [])

    if shot_index < 1 or shot_index > len(shots):
        raise HTTPException(status_code=400, detail="分镜索引超出范围")

    # 查找指定角色的台词
    shot_data = shots[shot_index - 1]
    dialogues = shot_data.get("dialogues", [])
    target_dialogue = None
    for dialogue in dialogues:
        if dialogue.get("character_name") == character_name:
            target_dialogue = dialogue
            break

    if not target_dialogue:
        raise HTTPException(
            status_code=404,
            detail=f"分镜 {shot_id} 中未找到角色 '{character_name}' 的台词",
        )

    try:
        # 删除物理文件
        old_audio_url = target_dialogue.get("audio_url")
        if old_audio_url and old_audio_url.startswith("/api/files/"):
            file_storage.delete_shot_audio(novel_id, shot_index, character_name)

        # 清除 parsed_data 中的音频信息
        target_dialogue["audio_url"] = None
        target_dialogue["audio_source"] = None
        target_dialogue["audio_task_id"] = None

        chapter.parsed_data = json.dumps(parsed_data, ensure_ascii=False)
        db.commit()

        return {
            "success": True,
            "data": {"shot_id": shot_id, "shot_index": shot_index, "character_name": character_name},
            "message": "音频删除成功",
        }

    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


# ==================== 分镜 CRUD 接口 ====================


@router.get("/{novel_id}/chapters/{chapter_id}/shots", response_model=dict)
async def get_shots(
    novel_id: str,
    chapter_id: str,
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
    db: Session = Depends(get_db),
):
    """
    获取章节的所有分镜列表

    Returns:
        分镜列表，按 index 升序排列
    """
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    active_video_tasks = db.query(Task).filter(
        Task.chapter_id == chapter_id,
        Task.type == "shot_video",
        Task.status.in_(["pending", "queued", "running"]),
    ).all()
    if active_video_tasks:
        await TaskService(db).reconcile_active_tasks(active_video_tasks, db=db)
        db.expire_all()

    shots = shot_repo.get_by_chapter(chapter_id)
    shots_data = [shot_repo.to_response(shot) for shot in shots]

    return {
        "success": True,
        "data": shots_data,
        "message": f"获取到 {len(shots_data)} 个分镜",
    }


@router.patch("/{novel_id}/chapters/{chapter_id}/shots/batch", response_model=dict)
async def batch_update_shots(
    novel_id: str,
    chapter_id: str,
    data: BatchShotsUpdateRequest,
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
):
    """
    批量更新分镜信息

    Args:
        novel_id: 小说 ID
        chapter_id: 章节 ID
        data: 分镜数据列表

    Returns:
        更新结果
    """
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    updated_shots = []
    for shot_data in data.shots:
        shot_id = shot_data.get("id")
        if not shot_id:
            continue

        shot = shot_repo.get_by_id(shot_id)
        if not shot or shot.chapter_id != chapter_id:
            continue

        # 构建更新数据
        update_data = {}
        for key in ["description", "video_description", "shot_image_prompt", "characters", "scene", "props", "duration", "continuity_mode", "video_director_plan", "dialogues"]:
            if key in shot_data:
                update_data[key] = shot_data[key]

        if update_data:
            updated_shot = shot_repo.update(shot, **update_data)
            updated_shots.append(shot_repo.to_response(updated_shot))

    return {
        "success": True,
        "data": {
            "updated_count": len(updated_shots),
            "shots": updated_shots,
        },
        "message": "批量更新分镜成功",
    }


@router.get("/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/download-llm-data", response_model=None)
async def download_shot_llm_data(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    db: Session = Depends(get_db),
):
    """下载当前分镜 Video Director 相关 LLM 调用完整数据。"""
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id, Chapter.novel_id == novel_id).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    shot_repo = ShotRepository(db)
    shot = shot_repo.get_by_id(shot_id)
    if not shot or shot.chapter_id != chapter_id:
        raise HTTPException(status_code=404, detail="分镜不存在")

    try:
        plan = json.loads(shot.video_director_plan) if shot.video_director_plan else {}
    except Exception:
        plan = {}
    calls = plan.get("ai_calls") if isinstance(plan.get("ai_calls"), list) else []

    zip_buffer = BytesIO()
    used_log_ids = set()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        if not calls:
            zip_file.writestr("README.txt", "当前分镜没有 Video Director LLM 调用记录。\n")
        for index, call in enumerate(calls, 1):
            if not isinstance(call, dict):
                continue
            log = _match_full_llm_log(db, novel_id, chapter_id, call, used_log_ids)
            if log:
                used_log_ids.add(log.id)
            created_at = log.created_at if log else call.get("created_at")
            time_part = _format_shanghai_filename_time(created_at)
            step_part = _safe_filename_part(f"step_{call.get('step') or 'unknown'}")
            title_part = _safe_filename_part(call.get("title") or call.get("task_type") or "llm_call")[:60]
            clip_part = f"_clip_{call.get('clip_index')}" if call.get("clip_index") else ""
            filename = f"{index:02d}_{time_part}_{step_part}{clip_part}_{title_part}.txt"
            zip_file.writestr(filename, _format_llm_log_text(call, log))

    zip_buffer.seek(0)
    zip_filename = f"shot_{shot.index}_llm_data.zip"
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'},
    )


@router.get("/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/download-video-materials", response_model=None)
def download_shot_video_materials(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    db: Session = Depends(get_db),
    include: Optional[list[str]] = Query(None),
):
    """打包当前 Shot 生视频所需图片与实际提交的 ComfyUI 工作流。"""
    selected = None if include is None else set(include)
    if selected is not None and (not selected or not selected <= SHOT_EXPORT_SECTIONS):
        raise HTTPException(status_code=400, detail="请选择有效的导出项")
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id, Chapter.novel_id == novel_id).first()
    shot = db.query(Shot).filter(Shot.id == shot_id, Shot.chapter_id == chapter_id).first()
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")

    current_plan = _safe_json_dict(shot.video_director_plan)
    if current_plan.get("canonical_visual_plan") is True:
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_STORED) as archive:
            build_shot_production_package(archive, db, novel, chapter, shot, included_sections=selected)
        zip_buffer.seek(0)
        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="shot_{int(shot.index):03d}_production.zip"'},
        )

    def safe_json(value, default):
        if isinstance(value, (dict, list)):
            return value
        if not value:
            return default
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return default

    def resolve_path(value) -> Optional[Path]:
        if not value:
            return None
        local_path = url_to_local_path(str(value))
        path = Path(local_path or str(value))
        return path if path.is_file() else None

    zip_buffer = BytesIO()
    manifest = {
        "version": 1,
        "novel_id": novel_id,
        "chapter_id": chapter_id,
        "shot_id": shot.id,
        "shot_index": shot.index,
        "generated_at": datetime.utcnow().isoformat(),
        "assets": [],
        "workflows": [],
    }
    used_names = set()
    asset_count = 0

    def unique_name(arcname: str) -> str:
        if arcname not in used_names:
            used_names.add(arcname)
            return arcname
        path = Path(arcname)
        index = 2
        while True:
            candidate = str(path.with_name(f"{path.stem}_{index}{path.suffix}"))
            if candidate not in used_names:
                used_names.add(candidate)
                return candidate
            index += 1

    # Images and video are already compressed formats. Store them verbatim and
    # let FastAPI run this sync endpoint in its threadpool instead of blocking
    # the event loop while recompressing multi-megabyte media files.
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_STORED) as zip_file:
        if selected is not None:
            zip_file = SelectedShotArchive(zip_file, selected)
        def add_asset(value, arcname: str, kind: str, label: str) -> Optional[str]:
            nonlocal asset_count
            path = resolve_path(value)
            if not path:
                return None
            final_name = unique_name(f"{arcname}{path.suffix or '.png'}")
            zip_file.write(path, final_name)
            manifest["assets"].append({"kind": kind, "label": label, "path": final_name})
            asset_count += 1
            return final_name

        def add_workflow(value, arcname: str, label: str, **details) -> None:
            if not value:
                return
            parsed = safe_json(value, value)
            content = json.dumps(parsed, ensure_ascii=False, indent=2) if not isinstance(parsed, str) else parsed
            final_name = unique_name(arcname)
            zip_file.writestr(final_name, content)
            manifest["workflows"].append({"label": label, "path": final_name, **details})

        def padded_index(value, fallback: int) -> str:
            try:
                return f"{int(value):03d}"
            except (TypeError, ValueError):
                return _safe_filename_part(value or fallback)

        primary_value = shot.image_url or shot.image_path
        primary_path = add_asset(primary_value, "frames/主分镜图", "primary_frame", "主分镜图/单帧图")

        plan = safe_json(shot.video_director_plan, {})
        plan_keyframes = plan.get("keyframes") if isinstance(plan.get("keyframes"), list) else []
        legacy_keyframes = safe_json(shot.keyframes, [])
        represented_legacy_indexes = set()

        for position, keyframe in enumerate(plan_keyframes, 1):
            if not isinstance(keyframe, dict):
                continue
            keyframe_index = keyframe.get("index", position)
            role = str(keyframe.get("role") or "KEYFRAME").upper()
            image_value = (
                keyframe.get("image_url") or keyframe.get("imageUrl") or
                keyframe.get("image_path") or keyframe.get("imagePath") or
                keyframe.get("local_path") or keyframe.get("localPath") or
                keyframe.get("generated_image_url") or keyframe.get("generatedImageUrl")
            )
            if role == "START" and not image_value:
                image_value = primary_value
            if not image_value:
                legacy = next((item for item in legacy_keyframes if isinstance(item, dict) and (
                    item.get("plan_keyframe_index") == keyframe_index or
                    item.get("planKeyframeIndex") == keyframe_index
                )), None)
                if legacy:
                    represented_legacy_indexes.add(id(legacy))
                    image_value = legacy.get("image_url") or legacy.get("imageUrl") or legacy.get("image_path") or legacy.get("imagePath")
            add_asset(
                image_value,
                f"frames/keyframes/KF{padded_index(keyframe_index, position)}_{_safe_filename_part(role)}",
                "keyframe",
                f"关键帧 {keyframe_index} {role}",
            )

        for position, keyframe in enumerate(legacy_keyframes, 1):
            if not isinstance(keyframe, dict) or id(keyframe) in represented_legacy_indexes:
                continue
            image_value = keyframe.get("image_url") or keyframe.get("imageUrl") or keyframe.get("image_path") or keyframe.get("imagePath")
            frame_index = keyframe.get("plan_keyframe_index") or keyframe.get("planKeyframeIndex") or keyframe.get("frame_index") or position
            add_asset(image_value, f"frames/keyframes/KF{padded_index(frame_index, position)}", "keyframe", f"关键帧 {frame_index}")

        character_names = _safe_json_list(shot.characters)
        for index, name in enumerate(character_names, 1):
            character = db.query(Character).filter(Character.novel_id == novel_id, Character.name == name).first()
            add_asset(character.image_url if character else None, f"characters/{index:02d}_{_safe_filename_part(name)}", "character", str(name))
        add_asset(shot.merged_character_image, "characters/合并角色图", "merged_character", "合并角色图")

        if shot.scene:
            scene = db.query(Scene).filter(Scene.novel_id == novel_id, Scene.name == shot.scene).first()
            add_asset(scene.image_url if scene else None, f"scene/{_safe_filename_part(shot.scene)}", "scene", shot.scene)

        prop_names = get_visual_prop_names(db, novel_id, _safe_json_list(shot.props))
        for index, name in enumerate(prop_names, 1):
            prop = db.query(Prop).filter(
                Prop.novel_id == novel_id,
                Prop.name == name,
                Prop.existence == PROP_EXISTENCE_REAL,
            ).first()
            add_asset(prop.image_url if prop else None, f"props/{index:02d}_{_safe_filename_part(name)}", "prop", str(name))
        add_asset(shot.merged_prop_image, "props/合并道具图", "merged_prop", "合并道具图")

        image_task = None
        if shot.image_task_id:
            image_task = db.query(Task).filter(Task.id == shot.image_task_id, Task.shot_id == shot.id).first()
        if not image_task or not image_task.workflow_json:
            image_task = db.query(Task).filter(
                Task.shot_id == shot.id,
                Task.type == "shot_image",
                Task.workflow_json.isnot(None),
            ).order_by(Task.created_at.desc()).first()
        add_workflow(image_task.workflow_json if image_task else None, "workflows/images/主分镜图_ComfyUI.json", "主分镜图实际工作流")

        current_keyframe_task_ids = {
            str(item.get("image_task_id") or item.get("imageTaskId"))
            for item in plan_keyframes + legacy_keyframes
            if isinstance(item, dict) and (item.get("image_task_id") or item.get("imageTaskId"))
        }
        keyframe_query = db.query(Task).filter(
            Task.shot_id == shot.id,
            Task.type == "keyframe_image",
            Task.workflow_json.isnot(None),
        )
        if current_keyframe_task_ids:
            keyframe_query = keyframe_query.filter(Task.id.in_(current_keyframe_task_ids))
        keyframe_tasks = keyframe_query.order_by(Task.created_at.asc()).all()
        for index, task in enumerate(keyframe_tasks, 1):
            add_workflow(task.workflow_json, f"workflows/keyframes/KF{index:03d}_{task.id[:8]}_ComfyUI.json", f"关键帧图实际工作流 {index}")
            task_metadata = safe_json(task.metadata_json, {})
            selector_evidence = {
                "task_id": task.id,
                "keyframe_task_status": task.status,
                "reference_selector_input": task_metadata.get("reference_selector_input"),
                "reference_selector_raw_response": task_metadata.get("reference_selector_raw_response"),
                "reference_selector_result": task_metadata.get("reference_selector_result"),
                "reference_manifest": task_metadata.get("reference_manifest"),
                "submitted_reference_bindings": task_metadata.get("submitted_reference_bindings"),
            }
            if any(selector_evidence[key] is not None for key in (
                "reference_selector_input",
                "reference_selector_raw_response",
                "reference_selector_result",
                "reference_manifest",
                "submitted_reference_bindings",
            )):
                evidence_name = f"workflows/keyframes/KF{index:03d}_{task.id[:8]}_reference_selector.json"
                zip_file.writestr(evidence_name, json.dumps(selector_evidence, ensure_ascii=False, indent=2))
                manifest["workflows"].append({
                    "label": f"关键帧图 Reference Selector 审计 {index}",
                    "path": evidence_name,
                    "task_id": task.id,
                    "kind": "reference_selector_evidence",
                })
                if task.prompt_text:
                    prompt_name = f"prompts/keyframes/KF{index:03d}_{task.id[:8]}_Qwen.txt"
                    zip_file.writestr(prompt_name, task.prompt_text)
                    manifest["workflows"].append({
                        "label": f"关键帧图最终 Qwen Prompt {index}",
                        "path": prompt_name,
                        "task_id": task.id,
                        "kind": "keyframe_qwen_prompt",
                    })

        window_plans = plan.get("window_plans") if isinstance(plan.get("window_plans"), list) else []
        clips = plan.get("clips") if isinstance(plan.get("clips"), list) else []
        semantic_clips = plan.get("clip_plan") if isinstance(plan.get("clip_plan"), list) else []
        if semantic_clips:
            revision = int(plan.get("clip_plan_revision") or 0)
            clip_tasks = db.query(Task).filter(
                Task.shot_id == shot.id,
                Task.type == "shot_video",
                Task.workflow_json.isnot(None),
            ).order_by(Task.created_at.desc()).all()
            latest_task_by_clip = {}
            tasks_by_id = {task.id: task for task in clip_tasks}
            for task in clip_tasks:
                metadata = safe_json(task.metadata_json, {})
                if (
                    metadata.get("execution_scope") != "CLIP"
                    or int(metadata.get("clip_plan_revision") or 0) != revision
                ):
                    continue
                clip_index = int(metadata.get("clip_index") or 0)
                if clip_index and clip_index not in latest_task_by_clip:
                    latest_task_by_clip[clip_index] = task

            exported_task_ids = set()
            for position, clip in enumerate(sorted(semantic_clips, key=lambda item: int(item.get("clip_index") or 0)), 1):
                if not isinstance(clip, dict):
                    continue
                clip_index = int(clip.get("clip_index") or position)
                generated_task_id = str(clip.get("generated_by_task_id") or "")
                task = tasks_by_id.get(generated_task_id) or latest_task_by_clip.get(clip_index)
                if not task or task.id in exported_task_ids:
                    continue
                exported_task_ids.add(task.id)
                metadata = safe_json(task.metadata_json, {})
                capability = str(metadata.get("capability") or clip.get("capability") or "VIDEO")
                workflow_label = task.workflow_name or capability
                previous_av_path = add_asset(
                    metadata.get("previous_approved_video_url"),
                    f"videos/references/C{padded_index(clip_index, position)}_PreviousAV",
                    "previous_approved_video",
                    f"视频 Clip {clip_index} Previous AV 输入",
                )
                workflow_details = {
                    "task_id": task.id,
                    "clip_index": clip_index,
                    "clip_plan_revision": revision,
                    "capability": capability,
                    "workflow_name": task.workflow_name,
                }
                if previous_av_path:
                    workflow_details["previous_av_path"] = previous_av_path
                add_workflow(
                    task.workflow_json,
                    f"workflows/video/clips/C{padded_index(clip_index, position)}_{_safe_filename_part(capability)}_{task.id[:8]}_ComfyUI.json",
                    f"视频 Clip {clip_index} 实际工作流 · {workflow_label}",
                    **workflow_details,
                )
        else:
            video_task = None
            if shot.video_task_id:
                video_task = db.query(Task).filter(Task.id == shot.video_task_id, Task.shot_id == shot.id).first()
            if not video_task or not video_task.workflow_json:
                video_task = db.query(Task).filter(
                    Task.shot_id == shot.id,
                    Task.type == "shot_video",
                    Task.workflow_json.isnot(None),
                ).order_by(Task.created_at.desc()).first()
            add_workflow(
                video_task.workflow_json if video_task else None,
                "workflows/video/Shot视频_ComfyUI.json",
                "视频实际工作流",
            )

            task_clips = safe_json(video_task.video_director_clips, []) if video_task else []
            seen_windows = set()
            for position, window in enumerate(window_plans + clips + task_clips, 1):
                if not isinstance(window, dict) or not window.get("workflow_json"):
                    continue
                window_index = window.get("window_index") or window.get("clip_index") or position
                if window_index in seen_windows:
                    continue
                seen_windows.add(window_index)
                add_workflow(
                    window.get("workflow_json"),
                    f"workflows/video/clip_{padded_index(window_index, position)}_ComfyUI.json",
                    f"视频 Clip {window_index} 实际工作流",
                )

        if asset_count == 0 and not manifest["workflows"]:
            raise HTTPException(status_code=404, detail="当前分镜没有可打包的视频素材")
        zip_file.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="shot_{shot.index:03d}_video_materials.zip"'},
    )


@router.get("/{novel_id}/chapters/{chapter_id}/shots/{shot_id}", response_model=dict)
async def get_shot(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
    db: Session = Depends(get_db),
):
    """
    获取单个分镜详情

    Args:
        shot_id: 分镜 ID

    Returns:
        分镜详情
    """
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    shot = shot_repo.get_by_id(shot_id)
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")

    if shot.chapter_id != chapter_id:
        raise HTTPException(status_code=400, detail="分镜不属于该章节")

    active_video_tasks = db.query(Task).filter(
        Task.shot_id == shot_id,
        Task.type == "shot_video",
        Task.status.in_(["pending", "queued", "running"]),
    ).all()
    if active_video_tasks:
        await TaskService(db).reconcile_active_tasks(active_video_tasks, db=db)
        db.expire_all()
        shot = shot_repo.get_by_id(shot_id)

    return {
        "success": True,
        "data": shot_repo.to_response(shot),
        "message": "获取分镜成功",
    }


@router.patch("/{novel_id}/chapters/{chapter_id}/shots/{shot_id}", response_model=dict)
async def update_shot(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    data: ShotUpdate,
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
):
    """
    更新分镜信息

    Args:
        shot_id: 分镜 ID
        data: 更新数据

    Returns:
        更新后的分镜信息
    """
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    shot = shot_repo.get_by_id(shot_id)
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")

    if shot.chapter_id != chapter_id:
        raise HTTPException(status_code=400, detail="分镜不属于该章节")

    update_data = data.model_dump(exclude_unset=True)

    if not update_data:
        return {
            "success": True,
            "data": shot_repo.to_response(shot),
            "message": "没有需要更新的字段",
        }

    updated_shot = shot_repo.update(shot, **update_data)

    return {
        "success": True,
        "data": shot_repo.to_response(updated_shot),
        "message": "分镜更新成功",
    }


@router.patch("/{novel_id}/chapters/{chapter_id}/resources", response_model=dict)
async def update_chapter_resources(
    novel_id: str,
    chapter_id: str,
    data: PatchChapterResourcesRequest,
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
):
    """
    更新章节资源（角色、场景、道具）

    Args:
        novel_id: 小说 ID
        chapter_id: 章节 ID
        data: 章节资源数据

    Returns:
        更新结果
    """
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    # 解析 parsed_data
    if not chapter.parsed_data:
        raise HTTPException(status_code=400, detail="章节未拆分，请先进行 AI 拆分")

    parsed_data = (
        json.loads(chapter.parsed_data)
        if isinstance(chapter.parsed_data, str)
        else chapter.parsed_data
    )

    # 更新章节资源
    parsed_data["characters"] = data.characters
    parsed_data["scenes"] = data.scenes
    parsed_data["props"] = data.props

    # 保存回数据库
    chapter.parsed_data = json.dumps(parsed_data, ensure_ascii=False)
    db.commit()
    db.refresh(chapter)

    return {
        "success": True,
        "data": {
            "characters": data.characters,
            "scenes": data.scenes,
            "props": data.props,
        },
        "message": "章节资源更新成功",
    }


# ==================== 分镜 CRUD 操作 ====================


@router.post("/{novel_id}/chapters/{chapter_id}/shots", response_model=dict)
async def create_shot(
    novel_id: str,
    chapter_id: str,
    data: ShotUpdate,
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
):
    """
    创建新分镜

    Args:
        novel_id: 小说 ID
        chapter_id: 章节 ID
        data: 分镜数据（包含 description, characters, scene, props, duration, dialogues 等）
        insert_index: 插入位置（可选，默认为末尾）

    Returns:
        创建的分镜信息
    """
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    # 获取现有分镜
    existing_shots = shot_repo.get_by_chapter(chapter_id)
    max_index = max([shot.index for shot in existing_shots], default=0)

    # 确定插入位置
    insert_index = getattr(data, 'insert_index', None)
    if insert_index is not None and 1 <= insert_index <= max_index:
        # 在指定位置插入：从后往前更新，避免 index 冲突（只更新 index 字段）
        for shot in sorted(existing_shots, key=lambda s: s.index, reverse=True):
            if shot.index >= insert_index:
                shot_repo.update(shot, index=shot.index + 1)
        new_index = insert_index
    else:
        # 在末尾添加
        new_index = max_index + 1

    # 构建创建数据
    create_data = {
        "chapter_id": chapter_id,
        "index": new_index,
        "description": data.description or "",
        "characters": data.characters or [],
        "scene": data.scene or "",
        "props": data.props or [],
        "duration": data.duration or 5,
        "continuity_mode": data.continuity_mode or "NORMAL",
        "dialogues": data.dialogues or [],
    }

    # 创建分镜
    new_shot = shot_repo.create(**create_data)

    return {
        "success": True,
        "data": shot_repo.to_response(new_shot),
        "message": "分镜创建成功",
    }


@router.delete("/{novel_id}/chapters/{chapter_id}/shots/{shot_id}", response_model=dict)
async def delete_shot(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
):
    """
    删除分镜

    Args:
        novel_id: 小说 ID
        chapter_id: 章节 ID
        shot_id: 分镜 ID

    Returns:
        删除结果
    """
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    shot = shot_repo.get_by_id(shot_id)
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")

    if shot.chapter_id != chapter_id:
        raise HTTPException(status_code=400, detail="分镜不属于该章节")

    deleted_index = shot.index

    # 删除分镜
    shot_repo.delete(shot)

    # 删除物理文件（图片、音频等）
    file_storage.delete_shot_image(novel_id, chapter_id, deleted_index, shot_id=shot.id)
    file_storage.delete_shot_audio_files(novel_id, chapter_id, deleted_index)

    # 重新排序剩余分镜的 index（只更新 index 字段）
    remaining_shots = shot_repo.get_by_chapter(chapter_id)
    for s in remaining_shots:
        if s.index > deleted_index:
            shot_repo.update(s, index=s.index - 1)

    return {
        "success": True,
        "data": {"deleted_shot_id": shot_id, "deleted_index": deleted_index},
        "message": "分镜删除成功",
    }


# ==================== 关键帧 API ====================


@router.post(
    "/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/keyframes/generate-descriptions",
    response_model=dict,
)
async def generate_keyframe_descriptions(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    request: GenerateKeyframeDescriptionsRequest,
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
):
    """
    生成关键帧描述

    使用 LLM 根据分镜描述生成关键帧描述列表。

    Args:
        novel_id: 小说 ID
        chapter_id: 章节 ID
        shot_id: 分镜 ID
        request: 包含 count（要生成的关键帧数量）

    Returns:
        生成结果，包含关键帧列表
    """
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    shot = shot_repo.get_by_id(shot_id)
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")

    if shot.chapter_id != chapter_id:
        raise HTTPException(status_code=400, detail="分镜不属于该章节")

    keyframe_service = ShotKeyframeService()
    success, keyframes, message = await keyframe_service.generate_keyframe_descriptions(
        db, shot_id, request.count
    )

    return {
        "success": success,
        "data": {"keyframes": keyframes} if success else None,
        "message": message,
    }


@router.post(
    "/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/keyframes/{frame_index}/generate-image",
    response_model=dict,
)
async def generate_keyframe_image(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    frame_index: int,
    request: GenerateKeyframeImageRequest = GenerateKeyframeImageRequest(),
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
):
    """
    生成关键帧图片

    使用 ComfyUI 工作流生成关键帧图片。

    Args:
        novel_id: 小说 ID
        chapter_id: 章节 ID
        shot_id: 分镜 ID
        frame_index: 关键帧序号（从0开始）
        workflow_id: 可选的工作流 ID

    Returns:
        生成任务信息
    """
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    shot = shot_repo.get_by_id(shot_id)
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")

    if shot.chapter_id != chapter_id:
        raise HTTPException(status_code=400, detail="分镜不属于该章节")

    existing_keyframes = _safe_json_list(shot.keyframes)
    plan = _safe_json_dict(shot.video_director_plan)
    if plan.get("canonical_visual_plan") is True and 0 <= frame_index < len(existing_keyframes):
        legacy_keyframe = existing_keyframes[frame_index]
        state_index = legacy_keyframe.get("plan_keyframe_index")
        if state_index is not None:
            planned_state = next((
                item for item in plan.get("keyframes") or []
                if isinstance(item, dict) and int(item.get("index") or -1) == int(state_index)
            ), {})
            previous_image_url = (
                legacy_keyframe.get("image_url") or legacy_keyframe.get("imageUrl")
                or planned_state.get("image_url") or planned_state.get("imageUrl")
            )
            consumers = current_visual_state_consumers(
                db, shot, int(state_index), previous_image_url,
            )
            affected = canonical_clip_dependency_closure(plan, consumers)
            try:
                ensure_no_active_canonical_clip_tasks(db, shot.id, plan, affected)
            except CanonicalExecutionConflict as exc:
                raise HTTPException(status_code=409, detail=str(exc))
    plan_keyframes = plan.get("keyframes") if isinstance(plan.get("keyframes"), list) else []
    end_plan_keyframe = next(
        (keyframe for keyframe in plan_keyframes if isinstance(keyframe, dict) and keyframe.get("role") == "END"),
        None,
    )
    has_end_legacy_keyframe = any(
        isinstance(keyframe, dict)
        and end_plan_keyframe
        and int(keyframe.get("plan_keyframe_index") or -1) == int(end_plan_keyframe.get("index") or -2)
        for keyframe in existing_keyframes
    )
    if end_plan_keyframe and not has_end_legacy_keyframe:
        shot_repo.update(shot, keyframes=_build_legacy_keyframes_from_plan(shot, plan_keyframes))
        db.commit()

    keyframe_service = ShotKeyframeService()
    try:
        success, task_id, message = await keyframe_service.generate_keyframe_image(
            db,
            shot_id,
            frame_index,
            request.workflow_id,
            skip_llm_when_prompt_exists=request.skip_llm_when_prompt_exists,
        )
    except CanonicalExecutionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return {
        "success": success,
        "data": {"task_id": task_id} if success else None,
        "message": message,
    }


@router.post(
    "/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/keyframes/{frame_index}/edit-image",
    response_model=dict,
)
async def edit_keyframe_image(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    frame_index: int,
    data: ShotImageEditRequest,
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
):
    """使用当前激活的单图编辑工作流编辑关键帧图片。"""
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    shot = shot_repo.get_by_id(shot_id)
    if not shot or shot.chapter_id != chapter_id:
        raise HTTPException(status_code=404, detail="分镜不存在")

    keyframes = _safe_json_list(shot.keyframes)
    if frame_index >= len(keyframes):
        raise HTTPException(status_code=404, detail="关键帧不存在")
    source_image_url = keyframes[frame_index].get("image_url")
    if not source_image_url:
        raise HTTPException(status_code=400, detail="关键帧暂无图片，无法编辑")

    result = await SingleImageEditService(db).edit_image(
        source_image_url=source_image_url,
        prompt=data.prompt,
        novel_id=novel_id,
        entity_id=shot.id,
        entity_name=f"镜{shot.index}_KF{frame_index + 1}",
        entity_type="shot",
        output_image_type="shot_edit",
    )
    if not result.get("success"):
        raise HTTPException(status_code=result.get("status_code", 500), detail=result.get("message", "编辑图片失败"))
    return {"success": True, "data": {"imageUrl": result["image_url"], "taskId": result.get("task_id")}, "message": "图片编辑成功"}


@router.post(
    "/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/keyframes/{frame_index}/replace-image",
    response_model=dict,
)
async def replace_keyframe_image(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    frame_index: int,
    data: ShotImageReplaceRequest,
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
):
    """用编辑结果替换当前关键帧图片。"""
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    shot = shot_repo.get_by_id(shot_id)
    if not shot or shot.chapter_id != chapter_id:
        raise HTTPException(status_code=404, detail="分镜不存在")
    if not url_to_local_path(data.image_url):
        raise HTTPException(status_code=400, detail="图片文件不存在或不是本地图片")

    keyframe_service = ShotKeyframeService()
    success, image_url, message = await keyframe_service.replace_keyframe_image(db, shot_id, frame_index, data.image_url)
    if not success:
        raise HTTPException(status_code=409 if "CANONICAL_" in message else 400, detail=message)
    db.commit()
    updated_shot = shot_repo.get_by_id(shot_id)
    return {"success": True, "data": shot_repo.to_response(updated_shot), "message": message, "imageUrl": image_url}


@router.post(
    "/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/keyframes/{frame_index}/upload-image",
    response_model=dict,
)
async def upload_keyframe_image(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    frame_index: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
):
    """
    上传关键帧图片

    Args:
        novel_id: 小说 ID
        chapter_id: 章节 ID
        shot_id: 分镜 ID
        frame_index: 关键帧序号（从0开始）
        file: 上传的图片文件

    Returns:
        上传结果，包含图片 URL
    """
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    shot = shot_repo.get_by_id(shot_id)
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")

    if shot.chapter_id != chapter_id:
        raise HTTPException(status_code=400, detail="分镜不属于该章节")

    # 验证文件类型
    ALLOWED_IMAGE_TYPES = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
    }
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型，仅支持 PNG, JPG, WEBP 格式",
        )

    # 读取文件内容
    file_content = await file.read()

    keyframe_service = ShotKeyframeService()
    success, image_url, message = await keyframe_service.upload_keyframe_image(
        db, shot_id, frame_index, file_content, file.filename or "image.png"
    )

    if not success and "CANONICAL_" in message:
        raise HTTPException(status_code=409, detail=message)

    return {
        "success": success,
        "data": {"image_url": image_url} if success else None,
        "message": message,
    }


@router.post(
    "/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/keyframes/{frame_index}/upload-reference-image",
    response_model=dict,
)
async def upload_keyframe_reference_image(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    frame_index: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
):
    """
    上传关键帧参考图

    Args:
        novel_id: 小说 ID
        chapter_id: 章节 ID
        shot_id: 分镜 ID
        frame_index: 关键帧序号（从0开始）
        file: 上传的参考图片文件

    Returns:
        上传结果，包含参考图 URL
    """
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    shot = shot_repo.get_by_id(shot_id)
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")

    if shot.chapter_id != chapter_id:
        raise HTTPException(status_code=400, detail="分镜不属于该章节")

    # 验证文件类型
    ALLOWED_IMAGE_TYPES = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
    }
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型，仅支持 PNG, JPG, WEBP 格式",
        )

    # 读取文件内容
    file_content = await file.read()

    keyframe_service = ShotKeyframeService()
    success, reference_url, message = await keyframe_service.upload_reference_image(
        db, shot_id, frame_index, file_content, file.filename or "reference.png"
    )

    return {
        "success": success,
        "data": {"reference_image_url": reference_url} if success else None,
        "message": message,
    }


@router.put(
    "/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/keyframes/{frame_index}/reference-image",
    response_model=dict,
)
async def set_keyframe_reference_image(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    frame_index: int,
    request: SetReferenceImageRequest,
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
):
    """
    设置关键帧参考图

    Args:
        novel_id: 小说 ID
        chapter_id: 章节 ID
        shot_id: 分镜 ID
        frame_index: 关键帧序号（从0开始）
        request: 包含 mode（auto_select/custom/none）和可选的 reference_url

    Returns:
        设置结果，包含最终的参考图 URL
    """
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    shot = shot_repo.get_by_id(shot_id)
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")

    if shot.chapter_id != chapter_id:
        raise HTTPException(status_code=400, detail="分镜不属于该章节")

    keyframe_service = ShotKeyframeService()
    success, reference_url, message = await keyframe_service.set_reference_image(
        db, shot_id, frame_index, request.mode, request.reference_url
    )

    return {
        "success": success,
        "data": {"reference_image_url": reference_url} if success else None,
        "message": message,
    }


class UpdateKeyframesRequest(BaseModel):
    keyframes: list


@router.put(
    "/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/keyframes",
    response_model=dict,
)
async def update_keyframes(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    request: UpdateKeyframesRequest,
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
):
    """
    更新分镜的关键帧数据

    Args:
        novel_id: 小说 ID
        chapter_id: 章节 ID
        shot_id: 分镜 ID
        request: 包含关键帧列表

    Returns:
        更新结果
    """
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    shot = shot_repo.get_by_id(shot_id)
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")

    if shot.chapter_id != chapter_id:
        raise HTTPException(status_code=400, detail="分镜不属于该章节")

    # 更新关键帧数据
    import json
    shot_repo.update(shot, keyframes=json.dumps(request.keyframes))

    return {
        "success": True,
        "data": {"keyframes": request.keyframes},
        "message": "关键帧数据更新成功",
    }


# ==================== 音频参考 API ====================


@router.post(
    "/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/merge-audio",
    response_model=dict,
)
async def merge_dialogue_audio(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
):
    """
    合并分镜的台词音频作为参考音频

    Args:
        novel_id: 小说 ID
        chapter_id: 章节 ID
        shot_id: 分镜 ID

    Returns:
        合并结果，包含音频 URL 和时长
    """
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    # 获取分镜
    shot = shot_repo.get_by_id(shot_id)
    if not shot or shot.chapter_id != chapter_id:
        raise HTTPException(status_code=404, detail="分镜不存在")

    shot_index = shot.index

    # 调用音频参考服务合并音频
    audio_ref_service = AudioReferenceService(db)
    result = await audio_ref_service.merge_dialogue_audio(
        novel_id, chapter_id, shot_index, shot_id=shot.id
    )

    return result


@router.post(
    "/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/upload-reference-audio",
    response_model=dict,
)
async def upload_reference_audio(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
):
    """
    上传参考音频文件

    Args:
        novel_id: 小说 ID
        chapter_id: 章节 ID
        shot_id: 分镜 ID
        file: 音频文件（mp3、wav、flac、ogg、m4a）

    Returns:
        上传结果，包含音频 URL
    """
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    # 获取分镜
    shot = shot_repo.get_by_id(shot_id)
    if not shot or shot.chapter_id != chapter_id:
        raise HTTPException(status_code=404, detail="分镜不存在")

    shot_index = shot.index

    # 验证文件类型
    if file.content_type not in ALLOWED_AUDIO_TYPES:
        # 允许额外的音频格式
        extra_types = {
            "audio/ogg": ".ogg",
            "audio/mp4": ".m4a",
            "audio/x-m4a": ".m4a",
        }
        if file.content_type not in extra_types:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件类型: {file.content_type}，仅支持 mp3、wav、flac、ogg、m4a 格式",
            )

    # 验证文件大小
    content = await file.read()
    if len(content) > MAX_AUDIO_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"文件大小超过限制（最大 10MB），当前文件大小: {len(content) / 1024 / 1024:.2f}MB",
        )

    # 调用音频参考服务上传
    audio_ref_service = AudioReferenceService(db)
    result = await audio_ref_service.upload_reference_audio(
        novel_id, chapter_id, shot_index, content, file.filename or "audio.mp3", shot_id=shot.id
    )

    return result


@router.post(
    "/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/set-reference-audio",
    response_model=dict,
)
async def set_reference_audio(
    novel_id: str,
    chapter_id: str,
    shot_id: str,
    request: SetReferenceAudioRequest,
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
):
    """
    设置参考音频来源

    Args:
        novel_id: 小说 ID
        chapter_id: 章节 ID
        shot_id: 分镜 ID
        request: 包含 mode 和可选的 character_name

    Returns:
        设置结果
    """
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    # 获取分镜
    shot = shot_repo.get_by_id(shot_id)
    if not shot or shot.chapter_id != chapter_id:
        raise HTTPException(status_code=404, detail="分镜不存在")

    shot_index = shot.index

    audio_ref_service = AudioReferenceService(db)

    if request.mode == "none":
        # 清除参考音频
        result = await audio_ref_service.clear_reference_audio(
            novel_id, chapter_id, shot_index, shot_id=shot.id
        )
    elif request.mode == "character":
        # 使用角色音色
        if not request.character_name:
            return {
                "success": False,
                "message": "使用角色音色时需要提供 character_name",
            }
        result = await audio_ref_service.set_character_voice_reference(
            novel_id, chapter_id, shot_index, request.character_name, shot_id=shot.id
        )
    else:
        # merged 和 uploaded 模式需要先调用对应的接口
        return {
            "success": False,
            "message": f"模式 '{request.mode}' 需要先调用对应的接口：merged 请调用 /merge-audio，uploaded 请调用 /upload-reference-audio",
        }

    return result


class PrepareRequiredImagesRequest(BaseModel):
    clip_plan_revision: int
    clip_indexes: list[int] | None = None
    state_indexes: list[int] | None = None


@router.post('/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/video-director/prepare-required-images')
async def prepare_shot_required_images(
    novel_id: str, chapter_id: str, shot_id: str, request: PrepareRequiredImagesRequest,
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    chapter_repo: ChapterRepository = Depends(get_chapter_repo),
    task_repo: TaskRepository = Depends(get_task_repo),
    workflow_repo: WorkflowRepository = Depends(get_workflow_repo),
    shot_repo: ShotRepository = Depends(get_shot_repo),
    template_repo: PromptTemplateRepository = Depends(get_prompt_template_repo),
    llm_service: LLMService = Depends(get_llm_service),
):
    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    shot = shot_repo.get_by_id(shot_id)
    if not chapter or not shot or shot.chapter_id != chapter_id:
        raise HTTPException(status_code=404, detail='章节或分镜不存在')
    service = ShotKeyframeService()

    async def submit_keyframe(frame_index, provenance):
        success, task_id, message = await service.generate_keyframe_image(
            db, shot.id, frame_index, expected_provenance=provenance,
        )
        if not success or not task_id:
            raise ValueError(message)
        return task_id

    async def submit_start(provenance):
        result = await _prepare_and_enqueue_shot_image_generation(
            novel_id, chapter_id, shot.id, GenerateShotImageRequest(), db,
            novel_repo, chapter_repo, task_repo, workflow_repo, shot_repo, template_repo, llm_service,
            canonical_image_provenance=provenance,
        )
        return result['data']['taskId']

    try:
        items = await prepare_required_images(db, shot, request.clip_plan_revision,
            submit_keyframe, submit_start, clip_indexes=request.clip_indexes, state_indexes=request.state_indexes)
    except CanonicalExecutionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {'success': True, 'data': {'items': items, 'shot': shot_repo.to_response(shot)}}
