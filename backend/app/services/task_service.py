"""
任务服务层

封装任务相关的业务逻辑和后台任务
"""
import json
import asyncio
from datetime import datetime
from typing import Dict, Any, Tuple

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.utils.time_utils import format_datetime
from app.models.task import Task
from app.models.novel import Novel
from app.models.workflow import Workflow
from app.repositories import TaskRepository, WorkflowRepository
from app.repositories.character_repository import CharacterRepository
from app.repositories.scene_repository import SceneRepository
from app.repositories.prompt_template import PromptTemplateRepository
from app.services.comfyui import ComfyUIService
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

        # 根据任务类型检查必需的字段
        required_fields = {
            "character": ["prompt_node_id", "save_image_node_id"],
            "scene": ["prompt_node_id", "save_image_node_id"],
            "shot": ["prompt_node_id", "save_image_node_id", "width_node_id", "height_node_id"],
            "video": ["prompt_node_id", "video_save_node_id", "reference_image_node_id"],
            "transition": ["first_image_node_id", "last_image_node_id", "video_save_node_id"],
            "character_audio": ["reference_audio_node_id", "text_node_id"]
        }

        fields = required_fields.get(task_type)
        if not fields:
            return True, ""

        missing_fields = []
        field_names = {
            "prompt_node_id": "提示词输入节点",
            "save_image_node_id": "图片保存节点",
            "video_save_node_id": "视频保存节点",
            "width_node_id": "宽度节点",
            "height_node_id": "高度节点",
            "reference_image_node_id": "参考图片节点",
            "first_image_node_id": "第一张图片节点",
            "last_image_node_id": "最后一张图片节点",
            "reference_audio_node_id": "参考音频节点",
            "text_node_id": "文本节点"
        }

        for field in fields:
            if not node_mapping.get(field):
                missing_fields.append(field_names.get(field, field))

        if missing_fields:
            return False, f"工作流 '{workflow.name}' 的映射配置不完整，缺少以下必需字段：{', '.join(missing_fields)}。请在【系统配置-ComfyUI工作流】中配置完整后再试。"

        return True, ""
    
    # ==================== 任务创建 ====================
    
    # ==================== 任务操作 ====================
    
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
        db.commit()

        # 根据任务类型重新执行
        if task.type == "character_portrait" and task.character_id:
            # 从CharacterService重新执行任务
            from app.services.character_service import CharacterService
            character_service = CharacterService(db)
            character = character_repo.get_by_id(task.character_id)
            if character:
                asyncio.create_task(
                    character_service._generate_portrait_task(
                        task.id,
                        character.id,
                        character.name,
                        character.appearance,
                        character.description
                    )
                )
        elif task.type == "scene_image" and task.scene_id:
            # 从SceneService重新执行任务
            from app.services.scene_service import SceneService
            scene_service = SceneService(db)
            scene = scene_repo.get_by_id(task.scene_id)
            if scene:
                asyncio.create_task(
                    scene_service._generate_scene_image_task(
                        task.id,
                        scene.id,
                        scene.name,
                        scene.setting,
                        scene.description
                    )
                )

        return {
            "success": True,
            "message": "任务已重新启动",
            "data": {
                "taskId": task.id,
                "status": "pending"
            }
        }
    
    # ==================== 任务列表格式化 ====================
    
    @staticmethod
    def format_task_list(tasks: list, novels: dict, chapters: dict, workflows: dict) -> list:
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
                "novelId": t.novel_id,
                "novelName": novels.get(t.novel_id).title if t.novel_id and t.novel_id in novels else None,
                "chapterId": t.chapter_id,
                "chapterTitle": chapters.get(t.chapter_id).title if t.chapter_id and t.chapter_id in chapters else None,
                "characterId": t.character_id,
                "sceneId": t.scene_id,
                "shotId": t.shot_id,
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
            "novelId": task.novel_id,
            "chapterId": task.chapter_id,
            "characterId": task.character_id,
            "sceneId": task.scene_id,
            "shotId": task.shot_id,
            "comfyuiPromptId": task.comfyui_prompt_id,
            "createdAt": format_datetime(task.created_at),
            "startedAt": format_datetime(task.started_at),
            "completedAt": format_datetime(task.completed_at),
        }
