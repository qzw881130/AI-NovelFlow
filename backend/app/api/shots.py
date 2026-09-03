"""
分镜路由 - 分镜图/视频/转场生成相关接口
"""

import json
import asyncio
import os
import subprocess
import uuid
import zipfile
from io import BytesIO
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.core.database import get_db
from app.models.novel import Novel, Chapter, Character, Scene, Prop
from app.models.shot import Shot
from app.models.task import Task
from app.models.workflow import Workflow
from app.models.llm_log import LLMLog
from app.services.comfyui import ComfyUIService
from app.services.file_storage import file_storage
from app.services.novel_service import (
    NovelService,
    generate_transition_video_task,
)
from app.services.shot_image_service import enqueue_shot_image_task
from app.services.shot_video_service import enqueue_shot_video_task, merge_video_director_clip_videos, _clip_dialogues_for_prompt

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
from app.services.shot_keyframe_service import ShotKeyframeService
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
    GenerateShotImageRequest,
    ShotImageEditRequest,
    ShotImageReplaceRequest,
    GenerateVideoRequest,
    GenerateVideoDirectorClipRequest,
    RecommendVideoModeRequest,
    PlanVideoKeyframesRequest,
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
from app.utils.path_utils import url_to_local_path
from app.utils.time_utils import format_datetime
from app.services.prompt_builder import get_style
from app.services.llm_service import LLMService
from app.repositories import PromptTemplateRepository
from app.services.video_director_ai import append_video_ai_call, strip_media_refs
from app.core.database import SessionLocal
from app.services.background_workers import worker_manager

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

        generated_shots = [
            (shot.index, shot.video_url)
            for shot in shots
            if shot.video_url and (not selected_shot_ids or shot.id in selected_shot_ids)
        ]
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

        signature = await asyncio.to_thread(file_storage.get_video_merge_signature, mode, segments)
        story_dir = file_storage._get_story_dir(novel_id)
        chapter_short = chapter_id[:8] if chapter_id else "unknown"
        output_dir = story_dir / f"chapter_{chapter_short}" / "merged-videos"
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
        valid_shot_ids = {shot.id for shot in shots if shot.video_url and (not selected_shot_ids or shot.id in selected_shot_ids)}
        is_final_video = bool(all_shot_ids) and valid_shot_ids == all_shot_ids and len(valid_shots) == len(all_shot_ids)
        metadata.update({
            "cache_hit": cache_hit,
            "mode": mode,
            "video_url": video_url,
            "segments_count": len(segments),
            "shots_count": len(valid_shots),
            "total_shots_count": len(all_shot_ids),
            "is_final_video": is_final_video,
            "file_size": output_path.stat().st_size if output_path.exists() else None,
            "duration": _probe_video_duration(output_path),
        })
        if is_final_video:
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


class BatchShotImageRequest(BaseModel):
    shot_ids: list[str]
    skip_llm_when_prompt_exists: bool = True


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


def _build_shot_image_reference_manifest(db: Session, novel: Novel, shot):
    shot_characters = _safe_json_list(shot.characters)
    shot_props = _safe_json_list(shot.props)

    manifest = []
    picture_index = 1

    character_members = []
    for name in shot_characters:
        character = (
            db.query(Character)
            .filter(Character.novel_id == novel.id, Character.name == name)
            .first()
        )
        if character and character.image_url and url_to_local_path(character.image_url):
            character_members.append(name)
    if character_members:
        manifest.append(
            {
                "picture_index": picture_index,
                "type": "MERGED_CHARACTER",
                "members": character_members,
            }
        )
        picture_index += 1

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

    prop_members = []
    for name in shot_props:
        prop = (
            db.query(Prop)
            .filter(Prop.novel_id == novel.id, Prop.name == name)
            .first()
        )
        if prop and prop.image_url and url_to_local_path(prop.image_url):
            prop_members.append(name)
    if prop_members:
        manifest.append(
            {
                "picture_index": picture_index,
                "type": "MERGED_PROP",
                "members": prop_members,
            }
        )

    return manifest


def _resolve_shot_image_workflow_type(db: Session, novel: Novel, shot) -> str:
    manifest = _build_shot_image_reference_manifest(db, novel, shot)
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
    shot_characters = _safe_json_list(shot.characters)
    shot_props = _safe_json_list(shot.props)

    character_members = []
    for name in shot_characters:
        character = (
            db.query(Character)
            .filter(Character.novel_id == novel.id, Character.name == name)
            .first()
        )
        if character and character.image_url and url_to_local_path(character.image_url):
            character_members.append(name)

    scene_name = ""
    scene_empty = True
    if shot.scene:
        scene = (
            db.query(Scene)
            .filter(Scene.novel_id == novel.id, Scene.name == shot.scene)
            .first()
        )
        scene_name = shot.scene
        scene_empty = not bool(
            scene and scene.image_url and url_to_local_path(scene.image_url)
        )

    prop_members = []
    for name in shot_props:
        prop = (
            db.query(Prop)
            .filter(Prop.novel_id == novel.id, Prop.name == name)
            .first()
        )
        if prop and prop.image_url and url_to_local_path(prop.image_url):
            prop_members.append(name)

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
    shot_props = _safe_json_list(shot.props)
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
    fallback_prompt = shot.description or "主分镜图"
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

    # 检查是否已有进行中的任务
    active_task = task_repo.get_active_shot_task(novel_id, chapter_id, shot_index, "shot_image")
    if active_task and (not existing_task or active_task.id != existing_task.id):
        return {
            "success": True,
            "message": "已有进行中的生成任务",
            "data": {"taskId": active_task.id, "status": active_task.status, "promptText": active_task.prompt_text},
        }

    # 获取激活的分镜生图工作流
    shot_workflow_type = request.workflow_type if request and request.workflow_type else _resolve_shot_image_workflow_type(db, novel, shot)
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
    shot = db.merge(shot)

    # 清除旧的图片数据和文件
    file_storage.delete_shot_image(novel_id, chapter_id, shot_index, shot_id=resolved_shot_id)

    # 更新分镜图片状态为 generating，并清除旧图片数据
    shot.image_url = None
    shot.image_path = None
    shot.image_task_id = None
    shot_repo.update_image_status(shot, "generating")

    db.commit()

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
    task.description = f"{task.description}；提示词模板：{prompt_template_name}"
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
    worker_manager.worker("shot_image_batch").enqueue(lambda: run_shot_image_batch_task(batch_task_id))


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
            shot_workflow_type = _resolve_shot_image_workflow_type(db, novel, shot)
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
    for current, expected in zip(execution_windows, expected_windows):
        if int(current.get("window_index") or 0) != int(expected.get("window_index") or 0):
            return False
        if float(current.get("start_time") or 0) != float(expected.get("start_time") or 0):
            return False
        if float(current.get("end_time") or 0) != float(expected.get("end_time") or 0):
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


def _build_keyframe_planner_user_content(shot, plan: dict, workflow_capability: dict, previous_failures: list = None) -> str:
    selected_mode = plan.get("selected_mode") or "MULTI_KEYFRAME"
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
        "selected_mode": selected_mode,
        "execution_windows": plan.get("execution_windows") or [],
        "workflow_capability": strip_media_refs(workflow_capability),
        "existing_keyframes": strip_media_refs(plan.get("keyframes") or []),
        "continuity_requirements": _build_continuity_requirements(shot),
        "requirements": {
            "output_top_level_keys": ["validation", "keyframes", "window_plans"],
            "first_last_rule": "FIRST_LAST_FRAME 只输出 KF1 START 与 KF2 END；window_plans 必须为空数组。",
            "window_plan_rule": "MULTI_KEYFRAME 每个 execution_window 必须对应一个 window_plan，且 selected_frame_count 只能为 3 或 4。",
            "shared_boundary_rule": "相邻 window 共享边界 Keyframe。",
        },
    }
    if previous_failures:
        payload["previous_failed_attempts"] = previous_failures
        payload["retry_instruction"] = "上一次 #08 输出未通过程序校验。请重新规划完整 JSON，必须修正 previous_failed_attempts 中的错误；尤其保证每个 window_plan.keyframe_indexes 数量严格等于 selected_frame_count，且每个 window 至少包含起点、中间点、终点三个关键帧。"
    return "请基于以下正式保存的 Shot 与执行窗口，规划视频关键帧时间轴。\n\n" + json.dumps(payload, ensure_ascii=False, indent=2)


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


def _normalize_keyframe_planner_result(parsed: dict, execution_windows: list, duration: int) -> tuple[list, list, dict]:
    if not isinstance(parsed, dict):
        raise ValueError("#08 返回必须是 JSON Object")
    raw_keyframes = parsed.get("keyframes") if isinstance(parsed.get("keyframes"), list) else []
    raw_window_plans = parsed.get("window_plans") if isinstance(parsed.get("window_plans"), list) else []
    if not raw_keyframes:
        raise ValueError("#08 返回缺少 keyframes")
    if len(raw_window_plans) != len(execution_windows):
        raise ValueError("#08 返回的 window_plans 数量必须与 execution_windows 一致")

    normalized_keyframes = []
    for idx, keyframe in enumerate(raw_keyframes, 1):
        if not isinstance(keyframe, dict):
            raise ValueError("keyframes 中存在无效对象")
        keyframe_index = int(keyframe.get("index") or idx)
        time_seconds = float(keyframe.get("time_seconds") if keyframe.get("time_seconds") is not None else 0)
        role = keyframe.get("role") or ("START" if keyframe_index == 1 else "END" if time_seconds >= duration else "INTERMEDIATE")
        if role not in {"START", "INTERMEDIATE", "END"}:
            role = "INTERMEDIATE"
        normalized_keyframes.append({
            "index": keyframe_index,
            "time_seconds": time_seconds,
            "role": role,
            "description": keyframe.get("description") or keyframe.get("visual_description") or "",
            "image_url": None,
            "image_task_id": None,
        })

    keyframe_indexes = {kf["index"] for kf in normalized_keyframes}
    windows_by_index = {int(window["window_index"]): window for window in execution_windows}
    normalized_window_plans = []
    for idx, plan_item in enumerate(raw_window_plans, 1):
        if not isinstance(plan_item, dict):
            raise ValueError("window_plans 中存在无效对象")
        window_index = int(plan_item.get("window_index") or idx)
        window = windows_by_index.get(window_index)
        if not window:
            raise ValueError(f"window_plans 引用了不存在的 execution_window {window_index}")
        selected_frame_count = int(plan_item.get("selected_frame_count") or plan_item.get("frame_count") or 0)
        if selected_frame_count not in {3, 4}:
            raise ValueError("每个 window_plan 的 selected_frame_count 必须是 3 或 4")
        indexes = [int(index) for index in (plan_item.get("keyframe_indexes") or [])]
        if len(indexes) != selected_frame_count:
            raise ValueError(f"window_plan {window_index} 的 keyframe_indexes 数量必须等于 selected_frame_count")
        missing = [index for index in indexes if index not in keyframe_indexes]
        if missing:
            raise ValueError(f"window_plan {window_index} 引用了不存在的 Keyframe: {missing}")
        workflow_type = "three_frame_video" if selected_frame_count == 3 else "four_frame_video"
        workflow_key = "MINIMAX_H3_3FRAME" if selected_frame_count == 3 else "MINIMAX_H3_4FRAME"
        normalized_window_plans.append({
            "window_index": window_index,
            "start_time": window.get("start_time"),
            "end_time": window.get("end_time"),
            "selected_frame_count": selected_frame_count,
            "workflow_key": plan_item.get("workflow_key") or workflow_key,
            "workflow_type": plan_item.get("workflow_type") or workflow_type,
            "keyframe_indexes": indexes,
            "status": plan_item.get("status") or "PENDING",
        })

    validation = parsed.get("validation") if isinstance(parsed.get("validation"), dict) else {}
    return normalized_keyframes, normalized_window_plans, validation


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
    if keyframe.get("role") == "START" and not description:
        description = shot.description or ""
    return strip_media_refs({
        "index": keyframe.get("index"),
        "role": keyframe.get("role"),
        "time_seconds": keyframe.get("time_seconds"),
        "description": description or "",
    })


def _build_segment_dialogue_state(shot, from_keyframe: dict, to_keyframe: dict) -> dict:
    segment = {
        "start_time": from_keyframe.get("time_seconds") or 0,
        "end_time": to_keyframe.get("time_seconds") or shot.duration or 0,
    }
    segment_dialogues = _clip_dialogues_for_prompt(_safe_json_list(shot.dialogues), segment, float(shot.duration or 0))
    return {
        "start_time": segment["start_time"],
        "end_time": segment["end_time"],
        "has_dialogue": bool(segment_dialogues),
        "segment_dialogues": segment_dialogues,
        "speech_rule": "仅 segment_dialogues 中的人物可发声。" if segment_dialogues else "本 segment 所有人物保持沉默，不说话、不低语、不发出人物语音。",
    }


def _build_keyframe_transition_user_content(shot, from_keyframe: dict, to_keyframe: dict, segment_index: int) -> str:
    dialogue_state = _build_segment_dialogue_state(shot, from_keyframe, to_keyframe)
    payload = {
        "shot": {
            "id": shot.id,
            "index": shot.index,
            "description": shot.description or "",
            "video_description": "",
            "characters": _safe_json_list(shot.characters),
            "scene": shot.scene or "",
            "props": _safe_json_list(shot.props),
            "duration": shot.duration or 4,
            "continuity_mode": shot.continuity_mode or "NORMAL",
            "dialogues": dialogue_state["segment_dialogues"],
        },
        "segment_index": segment_index,
        "segment_dialogue_state": dialogue_state,
        "continuity_requirements": _build_continuity_requirements(shot),
        "from_keyframe": _transition_keyframe_payload(shot, from_keyframe),
        "to_keyframe": _transition_keyframe_payload(shot, to_keyframe),
    }
    return "请基于以下相邻关键帧规划，生成这两个关键帧之间的动态过渡导演描述。\n\n" + json.dumps(payload, ensure_ascii=False, indent=2)


async def _plan_keyframe_transitions(
    db: Session,
    novel: Novel,
    chapter: Chapter,
    shot,
    keyframes: list,
    template_repo: PromptTemplateRepository,
    llm_service: LLMService,
) -> list:
    if len(keyframes) < 2:
        return []
    template = _get_keyframe_transition_template(novel, template_repo)
    transitions = []
    for index in range(len(keyframes) - 1):
        from_keyframe = keyframes[index]
        to_keyframe = keyframes[index + 1]
        segment_index = index + 1
        result = await llm_service.chat_completion(
            system_prompt=template.template,
            user_content=_build_keyframe_transition_user_content(shot, from_keyframe, to_keyframe, segment_index),
            temperature=0.3,
            max_tokens=1600,
            response_format="json_object",
            task_type="keyframe_transition",
            prompt_template_name=template.name,
            novel_id=novel.id,
            chapter_id=chapter.id,
        )
        if not result.get("success"):
            append_video_ai_call(shot, {
                "step": "10",
                "task_type": "keyframe_transition",
                "prompt_template_name": template.name,
                "status": "error",
                "input_summary": f"Shot {shot.index} KF{from_keyframe.get('index')} -> KF{to_keyframe.get('index')}",
                "response": result.get("error") or "",
            })
            db.commit()
            raise HTTPException(status_code=500, detail=result.get("error") or "关键帧过渡规划失败")
        try:
            parsed = _parse_keyframe_planner_content(result.get("content") or "{}")
        except Exception as exc:
            append_video_ai_call(shot, {
                "step": "10",
                "task_type": "keyframe_transition",
                "prompt_template_name": template.name,
                "status": "error",
                "input_summary": f"Shot {shot.index} KF{from_keyframe.get('index')} -> KF{to_keyframe.get('index')}",
                "response": result.get("content") or "",
                "parsed_result": {"error": str(exc)},
            })
            db.commit()
            raise HTTPException(status_code=400, detail=f"#10 返回格式无效：{exc}")

        transition = {
            "segment_index": int(parsed.get("segment_index") or segment_index),
            "from_keyframe_index": int(parsed.get("from_keyframe_index") or from_keyframe.get("index")),
            "to_keyframe_index": int(parsed.get("to_keyframe_index") or to_keyframe.get("index")),
            "start_time": parsed.get("start_time") if parsed.get("start_time") is not None else from_keyframe.get("time_seconds"),
            "end_time": parsed.get("end_time") if parsed.get("end_time") is not None else to_keyframe.get("time_seconds"),
            "transition_description": parsed.get("transition_description") or "",
        }
        transitions.append(transition)
        append_video_ai_call(shot, {
            "step": "10",
            "task_type": "keyframe_transition",
            "prompt_template_name": template.name,
            "status": "success",
            "input_summary": f"Shot {shot.index} KF{from_keyframe.get('index')} -> KF{to_keyframe.get('index')}",
            "response": result.get("content") or "",
            "parsed_result": transition,
        })
        db.commit()
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

    plan = _safe_json_dict(shot.video_director_plan)
    selected_mode = plan.get("selected_mode") or plan.get("recommended_mode")
    if selected_mode not in {"FIRST_LAST_FRAME", "MULTI_KEYFRAME"}:
        raise HTTPException(status_code=400, detail="当前模式不需要 #08 关键帧时间轴规划。")
    if selected_mode == "MULTI_KEYFRAME" and plan.get("window_plans") and not request.force:
        return {"success": True, "data": plan}
    if selected_mode == "FIRST_LAST_FRAME" and plan.get("keyframes") and plan.get("transitions") and not request.force:
        return {"success": True, "data": plan}

    workflow = workflow_repo.get_active_by_type("video")
    workflow_capability = plan.get("workflow_capability") if isinstance(plan.get("workflow_capability"), dict) else _get_video_workflow_capability(workflow)
    max_clip_duration = int(workflow_capability.get("max_clip_duration") or 15)
    duration = shot.duration or 4
    if selected_mode == "FIRST_LAST_FRAME" and duration > max_clip_duration:
        raise HTTPException(status_code=400, detail=f"当前 Workflow 单次最大 {max_clip_duration}s，本 Shot {duration}s，请使用多关键帧。")
    execution_windows = plan.get("execution_windows") if isinstance(plan.get("execution_windows"), list) else []
    if selected_mode == "FIRST_LAST_FRAME":
        execution_windows = []
        plan["execution_windows"] = []
        plan["window_plans"] = []
        plan["clips"] = _build_first_last_clip_plan(duration)
    elif request.force or not _execution_windows_match_duration(execution_windows, duration, max_clip_duration):
        execution_windows = _build_execution_windows(duration, max_clip_duration)
        plan["execution_windows"] = execution_windows
        plan["window_plans"] = []
        plan["keyframes"] = _build_minimal_keyframes(shot, selected_mode, max_clip_duration)
    plan["workflow_capability"] = workflow_capability
    if selected_mode == "MULTI_KEYFRAME":
        plan["clips"] = []

    template = _get_keyframe_planner_template(novel, template_repo)
    previous_failures = []
    result = None
    keyframes = []
    window_plans = []
    validation = {}
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        user_content = _build_keyframe_planner_user_content(shot, plan, workflow_capability, previous_failures)
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
        input_summary = f"Shot {shot.index} · {len(execution_windows)} execution windows · attempt {attempt}/{max_attempts}"
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
            keyframes, window_plans, validation = _normalize_keyframe_planner_result(parsed, execution_windows, duration)
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

    plan.update({
        "selected_mode": selected_mode,
        "recommended_label": VIDEO_MODE_LABELS[selected_mode],
        "keyframes": keyframes,
        "transitions": [],
        "window_plans": [] if selected_mode == "FIRST_LAST_FRAME" else window_plans,
        "clips": _build_first_last_clip_plan(duration) if selected_mode == "FIRST_LAST_FRAME" else [],
        "validation": validation,
    })
    plan.pop("task_error_message", None)
    plan.pop("error_message", None)
    plan.pop("merged_video_url", None)
    plan.pop("merged_at", None)
    legacy_keyframes = [
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
    shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
    plan = append_video_ai_call(shot, {
        "step": "08",
        "task_type": "keyframe_planner",
        "prompt_template_name": template.name,
        "status": "success",
        "input_summary": f"Shot {shot.index} · {selected_mode} · {len(execution_windows)} execution windows",
        "response": result.get("content") or "",
        "parsed_result": {"keyframes": keyframes, "window_plans": window_plans, "validation": validation},
    })
    shot_repo.update(
        shot,
        video_director_plan=plan,
        keyframes=legacy_keyframes,
        video_url=None,
        video_status="pending",
        video_task_id=None,
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

    video_director_plan = _safe_json_dict(shot.video_director_plan)
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

    # 启动后台任务
    asyncio.create_task(
        generate_transition_video_task(
            task.id,
            novel_id,
            chapter_id,
            from_index,
            to_index,
            workflow.id,
            duration_seconds,
            frame_count,
        )
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

        asyncio.create_task(
            generate_transition_video_task(
                task.id,
                novel_id,
                chapter_id,
                from_idx,
                to_idx,
                workflow.id,
                duration_seconds,
                frame_count,
            )
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
):
    """下载章节素材 ZIP 包"""
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    chapter = chapter_repo.get_by_id(chapter_id, novel_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    # 生成 ZIP 文件
    chapter_shots = shot_repo.get_by_chapter(chapter_id)
    zip_path = file_storage.zip_chapter_materials(novel_id, chapter_id, chapter_shots)

    if not zip_path:
        raise HTTPException(status_code=404, detail="章节素材不存在或打包失败")

    chapter_short = chapter_id[:8] if chapter_id else "unknown"
    filename = f"{novel.title}_chapter_{chapter_short}_materials.zip"

    return FileResponse(zip_path, media_type="application/zip", filename=filename)


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
            latest_task = (
                db.query(Task)
                .filter(Task.shot_id == shot.id, Task.type == "shot_image")
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
                shot_manifest["materials"].append({"label": "生成图真实工作流", "path": f"{shot_dir}/生成图真实工作流.json"})

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

    selected_count = len(selected_shot_ids) or len([shot for shot in shots if shot.video_url])
    if selected_count == 0:
        return {"success": False, "message": "没有分镜视频可以合并"}

    task = Task(
        type="chapter_video",
        status="pending",
        novel_id=novel_id,
        chapter_id=chapter_id,
        name=f"合并章节视频: {chapter.title or chapter.number}",
        description=f"合并章节 '{chapter.title or chapter.number}' 的 {selected_count} 个分镜视频",
        progress=0,
        current_step="等待合并章节视频...",
        metadata_json=json.dumps({"mode": mode, "shot_ids": list(selected_shot_ids)}, ensure_ascii=False),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    worker_manager.worker("chapter_video").enqueue(lambda: run_chapter_video_merge_task(task.id))

    return {
        "success": True,
        "data": {"taskId": task.id, "status": task.status, "mode": mode},
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
    success, task_id, message = await keyframe_service.generate_keyframe_image(
        db,
        shot_id,
        frame_index,
        request.workflow_id,
        skip_llm_when_prompt_exists=request.skip_llm_when_prompt_exists,
    )

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
        raise HTTPException(status_code=400, detail=message)
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
