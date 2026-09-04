"""
任务服务层

封装任务相关的业务逻辑和后台任务
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Tuple

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.config import get_settings
from app.utils.time_utils import format_datetime
from app.models.task import Task
from app.models.novel import Novel
from app.models.workflow import Workflow
from app.models.llm_log import LLMLog
from app.repositories import TaskRepository, WorkflowRepository
from app.repositories.shot_repository import ShotRepository
from app.repositories.character_repository import CharacterRepository
from app.repositories.scene_repository import SceneRepository
from app.repositories.prop_repository import PropRepository
from app.repositories.prompt_template import PromptTemplateRepository
from app.services.comfyui import ComfyUIService
from app.utils.path_utils import local_path_to_url, url_to_local_path
from app.services.file_storage import file_storage
from app.services.prompt_builder import (
    build_character_prompt,
    build_scene_prompt,
    get_style
)


class TaskService:
    """任务服务"""
    
    def __init__(self, db: Session = None):
        self.db = db
        self.comfyui_service = ComfyUIService()
    
    # ==================== 工作流验证 ====================
    
    @staticmethod
    def validate_workflow_node_mapping(workflow: Workflow, task_type: str) -> Tuple[bool, str]:
        """
        验证工作流的节点映射配置是否完整
        
        Args:
            workflow: 工作流对象
            task_type: 任务类型 (character, shot, video, transition)
            
        Returns:
            (是否有效, 错误信息)
        """
        if not workflow:
            # 使用默认工作流，不需要验证
            return True, ""

        # 解析节点映射
        node_mapping = {}
        if workflow.node_mapping:
            try:
                node_mapping = json.loads(workflow.node_mapping)
            except Exception:
                return False, f"工作流 '{workflow.name}' 的节点映射配置格式无效"
        if node_mapping.get("output_node_id") and not node_mapping.get("save_image_node_id"):
            node_mapping["save_image_node_id"] = node_mapping.get("output_node_id")
        if node_mapping.get("video_output_node_id") and not node_mapping.get("video_save_node_id"):
            node_mapping["video_save_node_id"] = node_mapping.get("video_output_node_id")

        # 根据任务类型检查必需的字段
        required_fields = {
            "character": ["prompt_node_id", "save_image_node_id"],
            "scene": ["prompt_node_id", "save_image_node_id"],
            "shot_scene": ["prompt_node_id", "save_image_node_id", "width_node_id", "height_node_id", "scene_reference_image_node_id"],
            "shot_character_scene": ["prompt_node_id", "save_image_node_id", "width_node_id", "height_node_id", "character_reference_image_node_id", "scene_reference_image_node_id"],
            "shot_scene_prop": ["prompt_node_id", "save_image_node_id", "width_node_id", "height_node_id", "scene_reference_image_node_id", "prop_reference_image_node_id"],
            "shot": ["prompt_node_id", "save_image_node_id", "width_node_id", "height_node_id"],
            "video": ["prompt_node_id", "video_save_node_id", "reference_image_node_id"],
            "first_last_video": ["prompt_node_id", "first_image_node_id", "last_image_node_id", "video_save_node_id"],
            "three_frame_video": ["prompt_node_id", "video_save_node_id", "reference_image_node_id", "keyframe_node_1", "keyframe_node_2"],
            "four_frame_video": ["prompt_node_id", "video_save_node_id", "reference_image_node_id", "keyframe_node_1", "keyframe_node_2", "keyframe_node_3"],
            "transition": ["first_image_node_id", "last_image_node_id", "video_save_node_id"],
            "character_audio": ["reference_audio_node_id", "text_node_id"]
        }

        fields = required_fields.get(task_type)
        if task_type == "shot" and node_mapping.get("output_node_id"):
            fields = ["prompt_node_id", "save_image_node_id"]
        if task_type == "video" and node_mapping.get("video_output_node_id"):
            fields = ["prompt_node_id", "video_save_node_id"]
        if not fields:
            return True, ""

        missing_fields = []
        field_names = {
            "prompt_node_id": "提示词输入节点",
            "save_image_node_id": "图片保存节点",
            "video_save_node_id": "视频保存节点",
            "width_node_id": "宽度节点",
            "height_node_id": "高度节点",
            "reference_image_node_id": "参考图片节点1",
            "character_reference_image_node_id": "角色参考图节点",
            "scene_reference_image_node_id": "场景参考图节点",
            "prop_reference_image_node_id": "道具参考图节点",
            "first_image_node_id": "第一张图片节点",
            "last_image_node_id": "最后一张图片节点",
            "frame_count_node_id": "总帧数节点",
            "duration_seconds_node_id": "时长秒数节点",
            "reference_audio_node_id": "参考音频节点",
            "text_node_id": "文本节点",
            "keyframe_node_1": "参考图片节点2",
            "keyframe_node_2": "参考图片节点3",
            "keyframe_node_3": "参考图片节点4",
        }

        for field in fields:
            if not node_mapping.get(field):
                missing_fields.append(field_names.get(field, field))

        if missing_fields:
            return False, f"工作流 '{workflow.name}' 的映射配置不完整，缺少以下必需字段：{', '.join(missing_fields)}。请在【系统配置-ComfyUI工作流】中配置完整后再试。"

        if task_type in {"video", "three_frame_video", "four_frame_video"} and not node_mapping.get("video_output_node_id"):
            has_max_side = bool(node_mapping.get("max_side_node_id"))
            has_megapixels = bool(node_mapping.get("megapixels_node_id"))
            if has_max_side == has_megapixels:
                return False, f"工作流 '{workflow.name}' 的映射配置不完整，最长边节点和 Megapixels 必须且只能配置其中一个。"

        if task_type in {"transition", "first_last_video"}:
            has_frame_count = bool(node_mapping.get("frame_count_node_id"))
            has_duration_seconds = bool(node_mapping.get("duration_seconds_node_id"))
            if has_frame_count == has_duration_seconds:
                return False, f"工作流 '{workflow.name}' 的映射配置不完整，总帧数节点和时长秒数节点必须且只能配置其中一个。"

        return True, ""
    
    # ==================== 任务创建 ====================
    
    # ==================== 任务操作 ====================

    @staticmethod
    def _mark_related_task_failed(task: Task, db: Session) -> None:
        """Keep entity generation status in sync when a task is cancelled."""
        if task.type == "character_portrait" and task.character_id:
            character = CharacterRepository(db).get_by_id(task.character_id)
            if character and character.portrait_task_id == task.id:
                character.generating_status = "failed"
        elif task.type == "scene_image" and task.scene_id:
            scene = SceneRepository(db).get_by_id(task.scene_id)
            if scene and scene.scene_task_id == task.id:
                scene.generating_status = "failed"
        elif task.type == "prop_image" and task.prop_id:
            prop = PropRepository(db).get_by_id(task.prop_id)
            if prop and prop.prop_task_id == task.id:
                prop.generating_status = "failed"
        elif task.type == "shot_video" and task.shot_id:
            shot = ShotRepository(db).get_by_id(task.shot_id)
            if shot and shot.video_task_id == task.id:
                shot.video_status = "failed"

    @staticmethod
    def _cleanup_cancelled_video_task(task: Task, db: Session) -> None:
        if task.type != "shot_video" or not task.shot_id:
            return
        shot_repo = ShotRepository(db)
        shot = shot_repo.get_by_id(task.shot_id)
        if not shot:
            return
        plan = json.loads(shot.video_director_plan or "{}") if shot.video_director_plan else {}
        if not isinstance(plan, dict):
            return
        window_plans = plan.get("window_plans") if isinstance(plan.get("window_plans"), list) else []
        changed = False
        for window_plan in window_plans:
            if not isinstance(window_plan, dict):
                continue
            is_current_task_clip = window_plan.get("generated_by_task_id") == task.id
            is_active_clip = str(window_plan.get("status") or "").upper() in {"PROMPT_BUILDING", "QUEUED", "RUNNING"}
            if not is_current_task_clip and not is_active_clip:
                continue
            if is_current_task_clip:
                local_path = window_plan.get("local_path") or url_to_local_path(window_plan.get("video_url"))
                if local_path:
                    try:
                        path = Path(local_path)
                        if path.exists() and path.is_file():
                            path.unlink()
                    except Exception as exc:
                        print(f"[TaskCancel] Failed to delete clip video {local_path}: {exc}")
                for key in ["video_url", "local_path", "source_video_url", "generated_at", "generated_by_task_id"]:
                    window_plan.pop(key, None)
            window_plan["status"] = "CANCELLED"
            window_plan["error_message"] = "任务已取消"
            changed = True
        if changed:
            shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
            task.video_director_clips = json.dumps(window_plans, ensure_ascii=False)
        if shot.video_task_id == task.id:
            shot.video_status = "failed"
        db.commit()

    @staticmethod
    def _mark_pending_video_llm_logs_cancelled(task: Task, db: Session) -> None:
        if task.type != "shot_video" or not task.chapter_id:
            return
        h3_task_types = [
            "h3_single_frame_prompt",
            "h3_first_last_frame_prompt",
            "h3_multi_keyframe_prompt",
        ]
        query = db.query(LLMLog).filter(
            LLMLog.chapter_id == task.chapter_id,
            LLMLog.task_type.in_(h3_task_types),
            LLMLog.status == "pending",
        )
        if task.novel_id:
            query = query.filter(LLMLog.novel_id == task.novel_id)
        if task.created_at:
            query = query.filter(LLMLog.created_at >= task.created_at)

        for log in query.all():
            log.status = "error"
            log.error_message = "任务被用户取消，LLM 响应已忽略"

    async def cancel_task(self, task_id: str, db: Session = None) -> Dict[str, Any]:
        """取消单个任务对应的 ComfyUI 执行。"""
        db = db or self.db
        task_repo = TaskRepository(db)

        task = task_repo.get_by_id(task_id)
        if not task:
            return {"success": False, "message": "任务不存在", "status_code": 404}

        if task.status not in ["pending", "running"]:
            return {
                "success": True,
                "message": "任务不是进行中状态，无需取消",
                "task": task,
                "details": {"skipped": True},
            }

        if task.type in {"shot_image_batch", "shot_video_batch"}:
            child_tasks = db.query(Task).filter(Task.parent_task_id == task.id).all()
            details = {"children_cancelled": 0, "children_requested": len(child_tasks)}
            for child in child_tasks:
                if child.status == "pending":
                    child.status = "cancelled"
                    child.error_message = "批量任务被用户取消"
                    child.current_step = "已终止"
                    details["children_cancelled"] += 1
                    self._mark_pending_video_llm_logs_cancelled(child, db)
                    self._mark_related_task_failed(child, db)
                    self._cleanup_cancelled_video_task(child, db)
                elif child.status == "running":
                    cancel_result = {"skipped_comfyui": True}
                    if child.comfyui_prompt_id:
                        cancel_result = await self.comfyui_service.cancel_all_matching_tasks([child.comfyui_prompt_id])
                    child.status = "cancelled"
                    child.error_message = "批量任务被用户取消"
                    child.current_step = "已终止"
                    details.setdefault("running_children", []).append({"task_id": child.id, "cancel_result": cancel_result})
                    self._mark_pending_video_llm_logs_cancelled(child, db)
                    self._mark_related_task_failed(child, db)
                    self._cleanup_cancelled_video_task(child, db)
            task.status = "cancelled"
            task.error_message = "任务被用户取消"
            task.current_step = "已终止"
            db.commit()
            return {"success": True, "message": "批量任务已取消", "task": task, "details": details}

        cancel_result = {"skipped_comfyui": True}
        if task.comfyui_prompt_id:
            cancel_result = await self.comfyui_service.cancel_all_matching_tasks([task.comfyui_prompt_id])
        deleted_from_queue = cancel_result.get("deleted_from_queue", [])
        interrupted = cancel_result.get("interrupted", False)
        not_found = cancel_result.get("not_found", [])

        if task.comfyui_prompt_id and task.comfyui_prompt_id not in not_found and not deleted_from_queue and not interrupted:
            return {
                "success": False,
                "message": "终止 ComfyUI 任务失败，已阻止删除",
                "status_code": 502,
                "details": cancel_result,
            }

        task.status = "cancelled"
        task.error_message = "任务被用户取消"
        task.current_step = "已终止"
        self._mark_pending_video_llm_logs_cancelled(task, db)
        self._mark_related_task_failed(task, db)
        self._cleanup_cancelled_video_task(task, db)
        db.commit()

        return {
            "success": True,
            "message": "任务已取消",
            "task": task,
            "details": cancel_result,
        }

    async def cancel_all_tasks(self, db: Session = None) -> Dict[str, Any]:
        """
        终止所有正在进行或待处理的任务
        
        执行顺序：
        1. 先清空 ComfyUI 队列（清除所有等待中的任务）
        2. 再中断当前正在执行的任务
        
        Args:
            db: 数据库会话
            
        Returns:
            操作结果
        """
        db = db or self.db
        task_repo = TaskRepository(db)
        
        # 获取所有 pending 或 running 的任务
        active_tasks = task_repo.list_active_tasks()

        if not active_tasks:
            return {
                "success": True,
                "message": "没有需要终止的任务",
                "cancelled_count": 0
            }

        # 检查是否有 running 状态的任务
        has_running_task = any(t.status == "running" for t in active_tasks)

        print(f"[CancelAll] Found {len(active_tasks)} active tasks, has_running: {has_running_task}")

        cancel_result = {
            "queue_cleared": False,
            "interrupted": False
        }

        # 1. 【第一步】清空 ComfyUI 队列（先清除等待中的任务）
        try:
            print(f"[CancelAll] Step 1: Clearing ComfyUI queue")
            clear_result = await self.comfyui_service.clear_queue()
            cancel_result["queue_cleared"] = clear_result.get("success", False)
            print(f"[CancelAll] Clear queue result: {clear_result}")
        except Exception as e:
            print(f"[CancelAll] Clear queue error: {e}")

        # 2. 【第二步】中断当前正在执行的任务
        if has_running_task:
            try:
                print(f"[CancelAll] Step 2: Interrupting running task")
                interrupt_result = await self.comfyui_service.interrupt_execution()
                cancel_result["interrupted"] = interrupt_result.get("success", False)
                print(f"[CancelAll] Interrupt result: {interrupt_result}")
            except Exception as e:
                print(f"[CancelAll] Interrupt error: {e}")

        # 更新所有任务状态为 failed
        cancelled_count = 0
        failed_count = 0
        for task in active_tasks:
            try:
                task.status = "failed"
                task.error_message = "任务被用户终止"
                task.current_step = "已终止"
                self._mark_related_task_failed(task, db)
                cancelled_count += 1
            except Exception as e:
                print(f"[CancelAll] Failed to update task {task.id}: {e}")
                failed_count += 1

        db.commit()

        # 构建返回消息
        message_parts = []
        if cancelled_count > 0:
            message_parts.append(f"已终止 {cancelled_count} 个任务")
        if cancel_result.get("queue_cleared"):
            message_parts.append("已清空队列")
        if cancel_result.get("interrupted"):
            message_parts.append("已中断运行中任务")
        if failed_count > 0:
            message_parts.append(f"{failed_count} 个更新失败")

        return {
            "success": True,
            "message": "；".join(message_parts) if message_parts else "操作完成",
            "cancelled_count": cancelled_count,
            "failed_count": failed_count,
            "details": cancel_result
        }
    
    def retry_task(self, task_id: str, db: Session = None) -> Dict[str, Any]:
        """
        重试失败的任务
        
        Args:
            task_id: 任务ID
            db: 数据库会话
            
        Returns:
            重试结果
        """
        db = db or self.db
        task_repo = TaskRepository(db)
        character_repo = CharacterRepository(db)
        scene_repo = SceneRepository(db)
        
        task = task_repo.get_by_id(task_id)
        if not task:
            return {"success": False, "message": "任务不存在", "status_code": 404}

        if task.status not in ["failed", "completed"]:
            return {"success": False, "message": "只能重试失败或已完成的任务", "status_code": 400}

        # 重置任务状态
        task.status = "pending"
        task.progress = 0
        task.current_step = None
        task.error_message = None
        task.result_url = None
        task.completed_at = None
        task.comfyui_prompt_id = None
        task.workflow_json = None
        db.commit()

        # 根据任务类型重新执行
        restarted = False
        if task.type == "character_portrait" and task.character_id:
            # 从CharacterService重新执行任务
            from app.services.character_service import enqueue_character_portrait_task
            character = character_repo.get_by_id(task.character_id)
            if character:
                enqueue_character_portrait_task(
                    task.id,
                    character.id,
                    character.name,
                    character.appearance,
                    character.description,
                )
                restarted = True
        elif task.type == "scene_image" and task.scene_id:
            # 从SceneService重新执行任务
            from app.services.scene_service import enqueue_scene_image_task
            scene = scene_repo.get_by_id(task.scene_id)
            if scene:
                enqueue_scene_image_task(
                    task.id,
                    scene.id,
                    scene.name,
                    scene.setting,
                    scene.description,
                )
                restarted = True
        elif task.type == "prop_image" and task.prop_id:
            from app.services.prop_image_service import enqueue_prop_image_task

            prop_repo = PropRepository(db)
            prop = prop_repo.get_by_id(task.prop_id)
            if prop:
                enqueue_prop_image_task(
                    task.id,
                    prop.id,
                    prop.name,
                    prop.appearance,
                    prop.description,
                )
                restarted = True
        elif task.type == "shot_image" and task.novel_id and task.chapter_id and task.workflow_id:
            from app.services.shot_image_service import enqueue_shot_image_task

            shot_repo = ShotRepository(db)
            shot = shot_repo.get_by_id(task.shot_id) if task.shot_id else None
            if not shot:
                match = re.search(r"镜\s*(\d+)", task.name or "")
                if match:
                    shot = shot_repo.get_by_chapter_and_index(task.chapter_id, int(match.group(1)))

            if not shot:
                task.status = "failed"
                task.error_message = "重试失败：找不到关联分镜"
                task.current_step = "重试失败"
                db.commit()
                return {"success": False, "message": task.error_message, "status_code": 400}

            shot_repo.update(
                shot,
                image_url=None,
                image_path=None,
                image_status="generating",
                image_task_id=task.id,
            )

            enqueue_shot_image_task(
                task.id,
                task.novel_id,
                task.chapter_id,
                shot.index,
                shot.description or "",
                task.workflow_id,
            )
            restarted = True
        elif task.type == "shot_video" and task.novel_id and task.chapter_id and task.workflow_id:
            from app.services.shot_video_service import enqueue_shot_video_task

            shot_repo = ShotRepository(db)
            shot = shot_repo.get_by_id(task.shot_id) if task.shot_id else None
            if not shot:
                match = re.search(r"镜\s*(\d+)", task.name or "")
                if match:
                    shot = shot_repo.get_by_chapter_and_index(task.chapter_id, int(match.group(1)))

            if not shot:
                task.status = "failed"
                task.error_message = "重试失败：找不到关联分镜"
                task.current_step = "重试失败"
                db.commit()
                return {"success": False, "message": task.error_message, "status_code": 400}

            shot_repo.update(
                shot,
                video_url=None,
                video_status="generating",
                video_task_id=task.id,
            )

            try:
                video_director_plan = json.loads(shot.video_director_plan) if shot.video_director_plan else {}
            except Exception:
                video_director_plan = {}

            enqueue_shot_video_task(
                task.id,
                task.novel_id,
                task.chapter_id,
                shot.index,
                task.workflow_id,
                shot.image_url or "",
                selected_mode=video_director_plan.get("selected_mode") or "SINGLE_FRAME",
            )
            restarted = True

        if not restarted:
            task.status = "failed"
            task.error_message = "当前任务类型暂不支持重试，或缺少必要关联数据"
            task.current_step = "重试失败"
            db.commit()
            return {"success": False, "message": task.error_message, "status_code": 400}

        return {
            "success": True,
            "message": "任务已重新启动",
            "data": {
                "taskId": task.id,
                "status": "pending"
            }
        }
    
    # ==================== 任务列表格式化 ====================

    async def reconcile_active_tasks(self, tasks=None, db: Session = None) -> int:
        """校准本地 running/pending 任务，避免 ComfyUI 已无任务但本地假死。"""
        db = db or self.db
        task_repo = TaskRepository(db)
        tasks = tasks if tasks is not None else task_repo.list_active_tasks()
        active_tasks = [task for task in tasks if task.status in ["pending", "running"]]
        if not active_tasks:
            return 0

        queue_info = await self.comfyui_service.get_queue_info()
        now = datetime.utcnow()
        comfyui_timeout = int(getattr(get_settings(), "COMFYUI_TIMEOUT", 900) or 900)
        llm_timeout = int(getattr(get_settings(), "LLM_TIMEOUT", 300) or 300)
        updated_count = 0

        def task_age_seconds(task: Task) -> float:
            started_at = task.started_at or task.created_at
            if not started_at:
                return 0
            if started_at.tzinfo is not None:
                started_at = started_at.astimezone(timezone.utc).replace(tzinfo=None)
            return (now - started_at).total_seconds()

        def inactive_seconds(task: Task) -> float:
            updated_at = task.updated_at or task.started_at or task.created_at
            if not updated_at:
                return 0
            if updated_at.tzinfo is not None:
                updated_at = updated_at.astimezone(timezone.utc).replace(tzinfo=None)
            return (now - updated_at).total_seconds()

        for task in active_tasks:
            age_seconds = task_age_seconds(task)
            def mark_related_shot_failed() -> None:
                if not task.shot_id:
                    return
                shot = ShotRepository(db).get_by_id(task.shot_id)
                if not shot:
                    return
                if task.type == "shot_video":
                    ShotRepository(db).update(shot, video_status="failed")
                elif task.type == "shot_image":
                    ShotRepository(db).update(shot, image_status="failed")

            pending_start_timeout = 600 if task.type == "keyframe_image" else 1800
            is_batch_waiting_child = bool(getattr(task, "parent_task_id", None))
            db_backed_task = task.type in {"audio_event_tts", "audio_prepare", "shot_video_batch"}
            if task.status == "pending" and not task.started_at and age_seconds > pending_start_timeout and task.type != "shot_image_batch" and not is_batch_waiting_child and not db_backed_task:
                task.status = "failed"
                task.error_message = "任务长期未启动，后台内存队列可能已因服务重启或热更新丢失，请重新提交"
                task.current_step = "任务未启动"
                updated_count += 1
                continue

            if task.comfyui_prompt_id:
                prompt_state = await self.comfyui_service.client.get_prompt_state(
                    task.comfyui_prompt_id,
                    queue_info=queue_info,
                )
                state = prompt_state.get("state")
                if state in ["queued", "history", "unknown"]:
                    continue

                if state == "completed":
                    if task.type == "shot_image" and inactive_seconds(task) > 60:
                        recovered = await self._recover_completed_shot_image_prompt(task, prompt_state.get("history"), db)
                        if recovered:
                            updated_count += 1
                            continue
                    if task.type == "keyframe_image" and inactive_seconds(task) > 60:
                        recovered = await self._recover_completed_keyframe_prompt(task, prompt_state.get("history"), db)
                        if recovered:
                            updated_count += 1
                            continue
                    if task.type == "shot_video" and inactive_seconds(task) > 60:
                        clip_state = self._shot_video_clip_state_for_prompt(task, task.comfyui_prompt_id)
                        if clip_state.get("has_prompt_building_clip"):
                            if inactive_seconds(task) > llm_timeout + 60:
                                task.status = "failed"
                                task.error_message = "任务停留在 H3 提示词构建阶段过久，可能是 LLM 调用中断或后台任务已退出"
                                task.current_step = "任务异常"
                                task.completed_at = datetime.utcnow()
                                mark_related_shot_failed()
                                updated_count += 1
                            continue
                        if clip_state.get("status") == "SUCCEEDED" and clip_state.get("video_url"):
                            next_window_index = self._next_unfinished_shot_video_window_index(task)
                            if next_window_index is not None:
                                self._enqueue_remaining_shot_video_clip(task, next_window_index, db)
                                updated_count += 1
                                continue
                            if inactive_seconds(task) > comfyui_timeout:
                                task.status = "failed"
                                task.error_message = "ComfyUI 已完成当前 Clip，但后端后台任务长时间未继续；已保存完成的 Clip，请重新生成剩余 Clip"
                                task.current_step = "任务异常"
                                task.completed_at = datetime.utcnow()
                                mark_related_shot_failed()
                                updated_count += 1
                            continue
                        recovered = await self._recover_completed_shot_video_prompt(task, prompt_state.get("history"), db)
                        if recovered:
                            updated_count += 1
                            continue
                        recovered = await self._recover_completed_single_shot_video_prompt(task, prompt_state.get("history"), db)
                        if recovered:
                            updated_count += 1
                            continue
                    if age_seconds > comfyui_timeout:
                        task.status = "failed"
                        task.error_message = "ComfyUI 已完成该任务，但后端未保存结果，可能是输出节点映射错误或后台任务中断"
                        task.current_step = "任务异常"
                        mark_related_shot_failed()
                        updated_count += 1
                    continue

                if state == "error":
                    task.status = "failed"
                    task.error_message = prompt_state.get("message") or "ComfyUI 执行失败"
                    task.current_step = "生成失败"
                    mark_related_shot_failed()
                    updated_count += 1
                    continue

                if state == "missing" and age_seconds > 60:
                    task.status = "failed"
                    task.error_message = "ComfyUI 队列和 history 中均找不到该任务，可能已被清理、取消或 ComfyUI 异常退出"
                    task.current_step = "任务异常"
                    mark_related_shot_failed()
                    updated_count += 1
                    continue

            elif task.status == "running":
                if db_backed_task:
                    continue
                clip_state = self._shot_video_clip_state_for_prompt(task, None) if task.type == "shot_video" else {}
                if clip_state.get("has_prompt_building_clip") and inactive_seconds(task) > llm_timeout + 60:
                    task.status = "failed"
                    task.error_message = "任务停留在 H3 提示词构建阶段过久，可能是 LLM 调用中断或后台任务已退出"
                    task.current_step = "任务异常"
                    mark_related_shot_failed()
                    updated_count += 1
                    continue
                if task.current_step and "ComfyUI" in task.current_step and age_seconds > 600:
                    task.status = "failed"
                    task.error_message = "任务停留在 ComfyUI 调用阶段超过 10 分钟且未保存 prompt_id，可能是旧后台任务已中断"
                    task.current_step = "任务异常"
                    mark_related_shot_failed()
                    updated_count += 1

        if updated_count:
            db.commit()
        return updated_count

    async def _recover_completed_shot_image_prompt(self, task: Task, prompt_history: dict, db: Session) -> bool:
        """Recover a completed shot image prompt when the worker missed persistence."""
        if task.type != "shot_image" or not task.shot_id or not prompt_history:
            return False

        outputs = prompt_history.get("outputs") or {}
        if not outputs:
            return False

        shot_repo = ShotRepository(db)
        shot = shot_repo.get_by_id(task.shot_id)
        if not shot:
            return False

        node_mapping = {}
        if task.workflow_id:
            workflow = db.query(Workflow).filter(Workflow.id == task.workflow_id).first()
            if workflow and workflow.node_mapping:
                try:
                    node_mapping = json.loads(workflow.node_mapping)
                except Exception:
                    node_mapping = {}

        prompt_workflow = None
        prompt_payload = prompt_history.get("prompt") or []
        if isinstance(prompt_payload, list) and len(prompt_payload) > 2 and isinstance(prompt_payload[2], dict):
            prompt_workflow = prompt_payload[2]

        save_image_node_id = node_mapping.get("save_image_node_id") or node_mapping.get("output_node_id")
        result = self.comfyui_service.client._parse_outputs(outputs, prompt_workflow, save_image_node_id)
        if not result or not result.get("success") or not result.get("image_url"):
            return False

        local_path = await file_storage.download_image(
            url=result["image_url"],
            novel_id=task.novel_id,
            character_name=f"shot_{shot.id[:8]}",
            image_type="shot",
            chapter_id=task.chapter_id,
        )
        if not local_path:
            return False

        local_url = local_path_to_url(local_path)
        shot_repo.update(shot, image_url=local_url, image_path=str(local_path), image_status="completed", image_task_id=task.id)
        task.status = "completed"
        task.progress = 100
        task.result_url = local_url
        task.error_message = None
        task.current_step = "生成完成"
        task.completed_at = datetime.utcnow()
        db.commit()
        return True

    async def _recover_completed_keyframe_prompt(self, task: Task, prompt_history: dict, db: Session) -> bool:
        """Recover a completed keyframe ComfyUI prompt when the worker missed persistence."""
        if task.type != "keyframe_image" or not task.shot_id or not prompt_history:
            return False

        outputs = prompt_history.get("outputs") or {}
        if not outputs:
            return False

        shot_repo = ShotRepository(db)
        shot = shot_repo.get_by_id(task.shot_id)
        if not shot:
            return False

        frame_index = self._keyframe_frame_index_from_task(task)
        if frame_index is None:
            return False

        try:
            keyframes = json.loads(shot.keyframes or "[]")
            if not isinstance(keyframes, list) or frame_index >= len(keyframes):
                return False
        except Exception:
            return False

        node_mapping = {}
        if task.workflow_id:
            workflow = db.query(Workflow).filter(Workflow.id == task.workflow_id).first()
            if workflow and workflow.node_mapping:
                try:
                    node_mapping = json.loads(workflow.node_mapping)
                except Exception:
                    node_mapping = {}

        prompt_workflow = None
        prompt_payload = prompt_history.get("prompt") or []
        if isinstance(prompt_payload, list) and len(prompt_payload) > 2 and isinstance(prompt_payload[2], dict):
            prompt_workflow = prompt_payload[2]

        save_image_node_id = node_mapping.get("save_image_node_id") or node_mapping.get("output_node_id")
        result = self.comfyui_service.client._parse_outputs(outputs, prompt_workflow, save_image_node_id)
        if not result or not result.get("success") or not result.get("image_url"):
            return False

        local_path = await file_storage.download_image(
            url=result["image_url"],
            novel_id=task.novel_id,
            character_name=f"keyframe_{frame_index}",
            image_type="keyframe",
            chapter_id=task.chapter_id,
        )
        if not local_path:
            return False

        local_url = local_path_to_url(local_path)
        keyframes[frame_index]["image_url"] = local_url
        keyframes[frame_index]["image_task_id"] = task.id

        plan_changed = False
        try:
            plan_keyframe_index = keyframes[frame_index].get("plan_keyframe_index")
            if plan_keyframe_index is not None and shot.video_director_plan:
                plan = json.loads(shot.video_director_plan or "{}")
                if isinstance(plan, dict) and isinstance(plan.get("keyframes"), list):
                    for plan_keyframe in plan["keyframes"]:
                        if isinstance(plan_keyframe, dict) and int(plan_keyframe.get("index") or -1) == int(plan_keyframe_index):
                            plan_keyframe["image_url"] = local_url
                            plan_keyframe["image_task_id"] = task.id
                            plan_changed = True
                            break
                    if plan_changed:
                        shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
        except Exception:
            pass

        shot.keyframes = json.dumps(keyframes, ensure_ascii=False)
        task.status = "completed"
        task.result_url = local_url
        task.error_message = None
        task.current_step = "生成完成"
        task.completed_at = datetime.utcnow()
        db.commit()
        return True

    @staticmethod
    def _keyframe_frame_index_from_task(task: Task) -> int | None:
        match = re.search(r"-(\d+)\s*$", task.name or "")
        if not match:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None

    @staticmethod
    def _shot_video_clip_state_for_prompt(task: Task, prompt_id: str) -> dict:
        try:
            window_plans = json.loads(task.video_director_clips or "[]")
            if not isinstance(window_plans, list):
                window_plans = []
        except Exception:
            window_plans = []

        result = {
            "status": None,
            "video_url": None,
            "has_prompt_building_clip": False,
        }
        for window in window_plans:
            if not isinstance(window, dict):
                continue
            status = str(window.get("status") or "").upper()
            if status == "PROMPT_BUILDING":
                result["has_prompt_building_clip"] = True
            if prompt_id and window.get("prompt_id") == prompt_id:
                result["status"] = status
                result["video_url"] = window.get("video_url")
        return result

    @staticmethod
    def _next_unfinished_shot_video_window_index(task: Task) -> int | None:
        try:
            window_plans = json.loads(task.video_director_clips or "[]")
            if not isinstance(window_plans, list):
                return None
        except Exception:
            return None

        for window in sorted(
            [item for item in window_plans if isinstance(item, dict)],
            key=lambda item: int(item.get("window_index") or item.get("clip_index") or 0),
        ):
            status = str(window.get("status") or "").upper()
            has_video = bool(window.get("video_url") or window.get("local_path"))
            if status != "SUCCEEDED" or not has_video:
                window_index = window.get("window_index") or window.get("clip_index")
                try:
                    return int(window_index)
                except (TypeError, ValueError):
                    return None
        return None

    def _enqueue_remaining_shot_video_clip(self, task: Task, window_index: int, db: Session) -> None:
        if not task.novel_id or not task.chapter_id or not task.shot_id or not task.workflow_id:
            return
        shot = ShotRepository(db).get_by_id(task.shot_id)
        if not shot:
            return

        shot_image_url = shot.image_url or ""
        task.comfyui_prompt_id = None
        task.status = "running"
        task.current_step = f"已重新入队，准备继续生成 Clip {window_index}..."
        task.error_message = None
        task.updated_at = datetime.utcnow()
        ShotRepository(db).update(shot, video_status="generating", video_task_id=task.id)
        db.commit()

        from app.services.shot_video_service import enqueue_shot_video_task
        enqueue_shot_video_task(
            task_id=task.id,
            novel_id=task.novel_id,
            chapter_id=task.chapter_id,
            shot_index=int(shot.index or 0),
            workflow_id=task.workflow_id,
            shot_image_url=shot_image_url,
            use_keyframes=True,
            use_reference_audio=True,
            selected_mode="MULTI_KEYFRAME",
            only_window_index=window_index,
            auto_merge_clips=True,
            skip_llm_when_prompt_exists=False,
        )

    async def _recover_completed_shot_video_prompt(self, task: Task, prompt_history: dict, db: Session) -> bool:
        """Recover a completed ComfyUI video prompt when the original worker missed persistence."""
        if not task.shot_id or not prompt_history:
            return False

        outputs = prompt_history.get("outputs") or {}
        if not outputs:
            return False

        shot_repo = ShotRepository(db)
        shot = shot_repo.get_by_id(task.shot_id)
        if not shot:
            return False

        try:
            window_plans = json.loads(task.video_director_clips or "[]")
            if not isinstance(window_plans, list):
                window_plans = []
        except Exception:
            window_plans = []

        active_index = None
        for index, window in enumerate(window_plans):
            if isinstance(window, dict) and window.get("prompt_id") == task.comfyui_prompt_id:
                active_index = index
                break
        if active_index is None:
            for index, window in enumerate(window_plans):
                status = str((window or {}).get("status") or "").upper()
                if status in {"PROMPT_BUILDING", "QUEUED", "RUNNING"}:
                    active_index = index
                    break
        if active_index is None:
            return False

        existing_window = window_plans[active_index]
        if str(existing_window.get("status") or "").upper() == "SUCCEEDED" and existing_window.get("video_url"):
            return False

        prompt_workflow = None
        prompt_payload = prompt_history.get("prompt") or []
        if isinstance(prompt_payload, list) and len(prompt_payload) > 2 and isinstance(prompt_payload[2], dict):
            prompt_workflow = prompt_payload[2]

        node_mapping = {}
        if task.workflow_id:
            workflow = db.query(Workflow).filter(Workflow.id == task.workflow_id).first()
            if workflow and workflow.node_mapping:
                try:
                    node_mapping = json.loads(workflow.node_mapping)
                except Exception:
                    node_mapping = {}

        video_save_node_id = node_mapping.get("video_save_node_id") or "150"
        result = self.comfyui_service.client._parse_outputs(outputs, prompt_workflow, video_save_node_id)
        if not result or not result.get("success") or not result.get("video_url"):
            return False

        window = window_plans[active_index]
        window_index = int(window.get("window_index") or window.get("clip_index") or active_index + 1)
        local_path = await file_storage.download_video(
            url=result["video_url"],
            novel_id=task.novel_id,
            chapter_id=task.chapter_id,
            shot_number=(int(shot.index or 0) * 1000) + window_index,
        )
        if not local_path:
            return False

        video_url = local_path_to_url(local_path)
        window.update({
            "status": "SUCCEEDED",
            "video_url": video_url,
            "local_path": local_path,
            "source_video_url": result.get("video_url"),
            "error_message": None,
            "generated_at": datetime.utcnow().isoformat(),
            "generated_by_task_id": task.id,
        })
        task.video_director_clips = json.dumps(window_plans, ensure_ascii=False)

        try:
            plan = json.loads(shot.video_director_plan or "{}")
            if isinstance(plan.get("window_plans"), list):
                for plan_window in plan["window_plans"]:
                    if int(plan_window.get("window_index") or plan_window.get("clip_index") or -1) == window_index:
                        plan_window.update(window)
                        break
                shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
        except Exception:
            pass

        all_succeeded = bool(window_plans) and all(
            str((window or {}).get("status") or "").upper() == "SUCCEEDED" and (window or {}).get("video_url")
            for window in window_plans
        )
        if all_succeeded:
            try:
                from app.services.shot_video_service import merge_video_director_clip_videos
                merge_result = await merge_video_director_clip_videos(db, shot, shot_repo, task.novel_id, task.chapter_id, int(shot.index or 0))
            except Exception as exc:
                merge_result = {"success": False, "message": str(exc)}

            if merge_result.get("success"):
                task.status = "completed"
                task.progress = 100
                task.current_step = "生成完成"
                task.result_url = merge_result.get("video_url")
                task.error_message = None
                task.completed_at = datetime.utcnow()
                shot_repo.update(shot, video_status="completed", video_url=merge_result.get("video_url"), video_task_id=task.id)
            else:
                task.status = "failed"
                task.current_step = "拼接失败"
                task.error_message = merge_result.get("message") or "多 Clip 拼接失败"
                shot_repo.update(shot, video_status="failed")
        else:
            task.status = "running"
            task.current_step = "已恢复完成 Clip，等待后续 Clip..."
            task.error_message = None
            try:
                plan = json.loads(shot.video_director_plan or "{}")
                plan.pop("task_error_message", None)
                shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
            except Exception:
                pass
            shot_repo.update(shot, video_status="generating")

        return True

    async def _recover_completed_single_shot_video_prompt(self, task: Task, prompt_history: dict, db: Session) -> bool:
        """Recover a completed single-clip shot video prompt when the worker missed persistence."""
        if task.type != "shot_video" or not task.shot_id or not prompt_history:
            return False
        try:
            window_plans = json.loads(task.video_director_clips or "[]")
            if isinstance(window_plans, list) and window_plans:
                return False
        except Exception:
            pass

        outputs = prompt_history.get("outputs") or {}
        if not outputs:
            return False

        shot_repo = ShotRepository(db)
        shot = shot_repo.get_by_id(task.shot_id)
        if not shot:
            return False

        prompt_workflow = None
        prompt_payload = prompt_history.get("prompt") or []
        if isinstance(prompt_payload, list) and len(prompt_payload) > 2 and isinstance(prompt_payload[2], dict):
            prompt_workflow = prompt_payload[2]

        node_mapping = {}
        if task.workflow_id:
            workflow = db.query(Workflow).filter(Workflow.id == task.workflow_id).first()
            if workflow and workflow.node_mapping:
                try:
                    node_mapping = json.loads(workflow.node_mapping)
                except Exception:
                    node_mapping = {}

        video_save_node_id = node_mapping.get("video_save_node_id") or node_mapping.get("video_output_node_id") or "150"
        result = self.comfyui_service.client._parse_outputs(outputs, prompt_workflow, video_save_node_id)
        if not result or not result.get("success") or not result.get("video_url"):
            return False

        local_path = await file_storage.download_video(
            url=result["video_url"],
            novel_id=task.novel_id,
            chapter_id=task.chapter_id,
            shot_number=int(shot.index or 0),
        )
        if not local_path:
            return False

        local_url = local_path_to_url(local_path)
        shot_repo.update(shot, video_url=local_url, video_status="completed", video_task_id=task.id)
        task.status = "completed"
        task.progress = 100
        task.result_url = local_url
        task.error_message = None
        task.current_step = "生成完成"
        task.completed_at = datetime.utcnow()
        db.commit()
        return True

    @staticmethod
    def format_task_list(tasks: list, novels: dict, chapters: dict, workflows: dict, shots: dict = None) -> list:
        """
        格式化任务列表响应
        
        Args:
            tasks: 任务列表
            novels: 小说字典
            chapters: 章节字典
            workflows: 工作流字典
            
        Returns:
            格式化后的任务列表
        """
        import json

        shots = shots or {}

        def parse_reference_images(value: str):
            if not value:
                return []
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, list) else []
            except Exception:
                return []

        def parse_metadata(value: str):
            if not value:
                return {}
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                return {}

        def format_video_director_clips(task: Task):
            if task.type != "shot_video":
                return []
            window_plans = []
            if task.video_director_clips:
                try:
                    parsed = json.loads(task.video_director_clips)
                    window_plans = parsed if isinstance(parsed, list) else []
                except Exception:
                    window_plans = []
            if not window_plans:
                shot = shots.get(task.shot_id) if task.shot_id else None
                if not shot or not shot.video_director_plan:
                    return []
                try:
                    plan = json.loads(shot.video_director_plan)
                except Exception:
                    return []
                window_plans = plan.get("window_plans") if isinstance(plan.get("window_plans"), list) else []
            clips = []
            for window in window_plans:
                if not isinstance(window, dict):
                    continue
                video_url = window.get("video_url")
                status = window.get("status")
                if task.status != "running" and str(status or "").upper() in {"PROMPT_BUILDING", "QUEUED", "RUNNING"}:
                    status = "SUCCEEDED" if video_url else ("FAILED" if task.status == "failed" else None)
                clips.append({
                    "windowIndex": window.get("window_index"),
                    "status": status,
                    "startTime": window.get("start_time"),
                    "endTime": window.get("end_time"),
                    "workflowType": window.get("workflow_type"),
                    "workflowName": window.get("workflow_name"),
                    "promptId": window.get("prompt_id"),
                    "promptText": window.get("prompt_text"),
                    "hasWorkflowJson": window.get("workflow_json") is not None,
                    "referenceImages": window.get("reference_images") if isinstance(window.get("reference_images"), list) else [],
                    "videoUrl": video_url,
                    "sourceVideoUrl": window.get("source_video_url"),
                    "audioStatus": window.get("audio_status"),
                    "audioMessage": window.get("audio_message"),
                    "driveAudioUrl": window.get("drive_audio_url"),
                    "finalAudioUrl": window.get("final_audio_url"),
                    "clipAudioDuration": window.get("clip_audio_duration"),
                    "errorMessage": window.get("error_message") or (task.error_message if task.status == "failed" and status == "FAILED" else None),
                    "generatedAt": window.get("generated_at"),
                    "dialogueCount": len(window.get("clip_dialogues") or []) if isinstance(window.get("clip_dialogues"), list) else None,
                })
            return clips

        return [
            {
                "id": t.id,
                "type": t.type,
                "name": t.name,
                "description": t.description,
                "status": t.status,
                "progress": t.progress,
                "currentStep": t.current_step,
                "resultUrl": t.result_url,
                "errorMessage": t.error_message,
                "workflowId": t.workflow_id,
                "workflowName": t.workflow_name,
                "workflowIsSystem": workflows.get(
                    t.workflow_id).is_system if t.workflow_id and t.workflow_id in workflows else False,
                "hasWorkflowJson": t.workflow_json is not None,
                "hasPromptText": t.prompt_text is not None,
                "referenceImages": parse_reference_images(t.reference_images),
                "videoDirectorClips": format_video_director_clips(t),
                "novelId": t.novel_id,
                "novelName": novels.get(t.novel_id).title if t.novel_id and t.novel_id in novels else None,
                "chapterId": t.chapter_id,
                "chapterTitle": chapters.get(t.chapter_id).title if t.chapter_id and t.chapter_id in chapters else None,
                "characterId": t.character_id,
                "sceneId": t.scene_id,
                "shotId": t.shot_id,
                "parentTaskId": getattr(t, "parent_task_id", None),
                "batchOrder": getattr(t, "batch_order", None),
                "metadata": parse_metadata(getattr(t, "metadata_json", None)) if t.type == "shot_video_batch" else {},
                "createdAt": format_datetime(t.created_at),
                "startedAt": format_datetime(t.started_at),
                "completedAt": format_datetime(t.completed_at),
            }
            for t in tasks
        ]
    
    @staticmethod
    def format_task_detail(task: Task) -> dict:
        """
        格式化任务详情响应
        
        Args:
            task: 任务对象
            
        Returns:
            格式化后的任务详情
        """
        import json

        try:
            reference_images = json.loads(task.reference_images) if task.reference_images else []
        except Exception:
            reference_images = []
        try:
            metadata = json.loads(task.metadata_json) if task.metadata_json else {}
        except Exception:
            metadata = {}

        return {
            "id": task.id,
            "type": task.type,
            "name": task.name,
            "description": task.description,
            "status": task.status,
            "progress": task.progress,
            "currentStep": task.current_step,
            "resultUrl": task.result_url,
            "errorMessage": task.error_message,
            "workflowId": task.workflow_id,
            "workflowName": task.workflow_name,
            "workflowJson": task.workflow_json,
            "promptText": task.prompt_text,
            "referenceImages": reference_images,
            "metadata": metadata,
            "novelId": task.novel_id,
            "chapterId": task.chapter_id,
            "characterId": task.character_id,
            "sceneId": task.scene_id,
            "shotId": task.shot_id,
            "parentTaskId": getattr(task, "parent_task_id", None),
            "batchOrder": getattr(task, "batch_order", None),
            "comfyuiPromptId": task.comfyui_prompt_id,
            "createdAt": format_datetime(task.created_at),
            "startedAt": format_datetime(task.started_at),
            "completedAt": format_datetime(task.completed_at),
        }
