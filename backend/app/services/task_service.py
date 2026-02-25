"""
任务服务层

封装任务相关的业务逻辑和后台任务
"""
import json
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.utils import format_datetime
from app.models.task import Task
from app.models.novel import Character, Novel, Scene
from app.models.prompt_template import PromptTemplate
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
    extract_style_from_template,
    extract_style_from_character_template
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
            "transition": ["first_image_node_id", "last_image_node_id", "video_save_node_id"]
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
            "last_image_node_id": "最后一张图片节点"
        }

        for field in fields:
            if not node_mapping.get(field):
                missing_fields.append(field_names.get(field, field))

        if missing_fields:
            return False, f"工作流 '{workflow.name}' 的映射配置不完整，缺少以下必需字段：{', '.join(missing_fields)}。请在【系统配置-ComfyUI工作流】中配置完整后再试。"

        return True, ""
    
    # ==================== 任务创建 ====================
    
    def create_character_portrait_task(
        self, 
        character_id: str,
        db: Session = None
    ) -> Dict[str, Any]:
        """
        创建角色人设图生成任务
        
        Args:
            character_id: 角色ID
            db: 数据库会话
            
        Returns:
            创建结果
        """
        db = db or self.db
        character_repo = CharacterRepository(db)
        task_repo = TaskRepository(db)
        workflow_repo = WorkflowRepository(db)
        
        # 获取角色
        character = character_repo.get_by_id(character_id)
        if not character:
            return {"success": False, "message": "角色不存在"}
        
        # 检查是否已有进行中的任务
        existing_task = task_repo.get_active_by_character(character_id)
        if existing_task:
            return {
                "success": True,
                "message": "已有进行中的生成任务",
                "data": {
                    "taskId": existing_task.id,
                    "status": existing_task.status
                }
            }
        
        # 检查角色生成状态
        if character.generating_status == "running":
            return {
                "success": False,
                "message": "该角色正在生成形象中，请稍后再试"
            }
        
        # 获取并验证工作流
        workflow = workflow_repo.get_active_by_type("character")
        is_valid, error_msg = self.validate_workflow_node_mapping(workflow, "character")
        if not is_valid:
            return {"success": False, "message": error_msg}
        
        # 创建任务
        task = Task(
            type="character_portrait",
            name=f"生成角色形象: {character.name}",
            description=f"为角色 '{character.name}' 生成人设图",
            novel_id=character.novel_id,
            character_id=character_id,
            status="pending"
        )
        task_repo.create(task)
        
        # 更新角色生成状态
        character.generating_status = "running"
        character.portrait_task_id = task.id
        db.commit()
        
        # 启动后台任务
        asyncio.create_task(
            self.generate_portrait_task(
                task.id,
                character_id,
                character.name,
                character.appearance,
                character.description
            )
        )
        
        return {
            "success": True,
            "message": "人设图生成任务已创建",
            "data": {
                "taskId": task.id,
                "status": "pending"
            }
        }
    
    def create_scene_image_task(
        self,
        scene_id: str,
        db: Session = None
    ) -> Dict[str, Any]:
        """
        创建场景图生成任务
        
        Args:
            scene_id: 场景ID
            db: 数据库会话
            
        Returns:
            创建结果
        """
        db = db or self.db
        scene_repo = SceneRepository(db)
        task_repo = TaskRepository(db)
        workflow_repo = WorkflowRepository(db)
        
        # 获取场景
        scene = scene_repo.get_by_id(scene_id)
        if not scene:
            return {"success": False, "message": "场景不存在"}
        
        # 检查是否已有进行中的任务
        existing_task = task_repo.get_active_by_scene(scene_id)
        if existing_task:
            return {
                "success": True,
                "message": "已有进行中的生成任务",
                "data": {
                    "taskId": existing_task.id,
                    "status": existing_task.status
                }
            }
        
        # 检查场景生成状态
        if scene.generating_status == "running":
            return {
                "success": False,
                "message": "该场景正在生成图片中，请稍后再试"
            }
        
        # 获取并验证工作流
        workflow = workflow_repo.get_active_by_type("scene")
        is_valid, error_msg = self.validate_workflow_node_mapping(workflow, "scene")
        if not is_valid:
            return {"success": False, "message": error_msg}
        
        # 创建任务
        task = Task(
            type="scene_image",
            name=f"生成场景图: {scene.name}",
            description=f"为场景 '{scene.name}' 生成图片",
            novel_id=scene.novel_id,
            scene_id=scene_id,
            status="pending"
        )
        task_repo.create(task)
        
        # 更新场景生成状态
        scene.generating_status = "running"
        scene.scene_task_id = task.id
        db.commit()
        
        # 启动后台任务
        asyncio.create_task(
            self.generate_scene_image_task(
                task.id,
                scene_id,
                scene.name,
                scene.setting,
                scene.description
            )
        )
        
        return {
            "success": True,
            "message": "场景图生成任务已创建",
            "data": {
                "taskId": task.id,
                "status": "pending"
            }
        }
    
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
            character = character_repo.get_by_id(task.character_id)
            if character:
                asyncio.create_task(
                    self.generate_portrait_task(
                        task.id,
                        character.id,
                        character.name,
                        character.appearance,
                        character.description
                    )
                )
        elif task.type == "scene_image" and task.scene_id:
            scene = scene_repo.get_by_id(task.scene_id)
            if scene:
                asyncio.create_task(
                    self.generate_scene_image_task(
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
    
    # ==================== 后台任务 ====================
    
    async def generate_portrait_task(
        self,
        task_id: str,
        character_id: str,
        name: str,
        appearance: str,
        description: str
    ):
        """
        后台任务：生成角色人设图
        
        Args:
            task_id: 任务ID
            character_id: 角色ID
            name: 角色名称
            appearance: 外貌描述
            description: 角色描述
        """
        db = SessionLocal()
        task_repo = TaskRepository(db)
        workflow_repo = WorkflowRepository(db)
        template_repo = PromptTemplateRepository(db)
        character_repo = CharacterRepository(db)
        
        try:
            # 获取任务
            task = task_repo.get_by_id(task_id)
            if not task:
                return

            # 获取当前激活的 character 工作流
            workflow = workflow_repo.get_active_by_type("character")

            # 记录工作流信息
            if workflow:
                task.workflow_id = workflow.id
                task.workflow_name = workflow.name
                task.current_step = f"使用工作流: {workflow.name}"
            else:
                task.current_step = "使用默认工作流"

            # 更新任务状态为运行中
            task.status = "running"
            task.started_at = datetime.utcnow()
            db.commit()

            # 获取角色所属小说
            character = character_repo.get_by_id(character_id)
            novel = db.query(Novel).filter(Novel.id == character.novel_id).first() if character else None

            # 获取提示词模板
            template = None
            if novel and novel.prompt_template_id:
                template = template_repo.get_by_id(novel.prompt_template_id)

            # 如果没有指定模板，使用默认系统模板
            if not template:
                template = template_repo.get_default_system_template("character")

            # 构建提示词
            prompt = build_character_prompt(name, appearance, description, template.template if template else None)

            # 获取 style（从模板的 style 字段）
            style = "anime style, high quality, detailed"
            if template and template.style:
                style = template.style
            elif template:
                # 兼容旧模板：从模板内容中提取 style
                style = extract_style_from_template(template.template)

            task.current_step = f"使用模板: {template.name if template else '默认'}, 提示词: {prompt[:80]}..., style: {style[:50]}..."

            # 保存提示词
            task.prompt_text = prompt
            db.commit()

            # 获取工作流JSON字符串
            workflow_json_str = workflow.workflow_json if workflow else None
            print(
                f"[Task] Workflow JSON available: {workflow_json_str is not None}, length: {len(workflow_json_str) if workflow_json_str else 0}")

            # 获取工作流的节点映射配置
            node_mapping = None
            if workflow and workflow.node_mapping:
                try:
                    node_mapping = json.loads(workflow.node_mapping)
                    print(f"[Task] Using node mapping: {node_mapping}")
                except Exception as e:
                    print(f"[Task] Failed to parse node_mapping: {e}")

            # 构建实际提交给ComfyUI的完整工作流（注入参数后）
            print(f"[Task] Building workflow with: {workflow.name if workflow else 'default'}")
            print(f"[Task] Novel ID: {task.novel_id}, Character: {name}")

            submitted_workflow = self.comfyui_service.builder.build_character_workflow(
                prompt=prompt,
                workflow_json=workflow_json_str,
                novel_id=task.novel_id,
                character_name=name,
                aspect_ratio=novel.aspect_ratio if novel else None,
                node_mapping=node_mapping,
                style=style
            )

            # 保存构建后的完整工作流到任务，让用户可以立即查看
            task.workflow_json = json.dumps(submitted_workflow, ensure_ascii=False, indent=2)
            db.commit()
            print(f"[Task] Saved submitted workflow to task")

            # 调用 ComfyUI 生成图片（使用已构建的工作流）
            result = await self.comfyui_service.generate_character_image(
                prompt,
                workflow_json=workflow_json_str,
                novel_id=task.novel_id,
                character_name=name,
                aspect_ratio=novel.aspect_ratio if novel else None,
                node_mapping=node_mapping,
                workflow=submitted_workflow  # 传递已构建的工作流，避免重复构建
            )

            print(f"[Task] Generation result: {result}")

            if result.get("success"):
                image_url = result.get("image_url")

                # 下载图片到本地存储
                task.current_step = "下载图片到服务器..."
                db.commit()

                try:
                    local_path = await file_storage.download_image(
                        url=image_url,
                        novel_id=task.novel_id or "default",
                        character_name=name,
                        image_type="character"
                    )

                    if local_path:
                        # 构建本地可访问的URL (通过静态文件服务)
                        relative_path = local_path.replace(str(file_storage.base_dir), "").replace("\\", "/")
                        local_url = f"/api/files/{relative_path.lstrip('/')}"
                        task.result_url = local_url
                        task.current_step = "生成完成，图片已保存"
                    else:
                        # 下载失败，使用原始URL
                        task.result_url = image_url
                        task.current_step = "生成完成，使用远程图片"
                except Exception as e:
                    print(f"[Task] Failed to download image: {e}")
                    task.result_url = image_url
                    task.current_step = "生成完成，使用远程图片"

                task.status = "completed"
                task.progress = 100
                task.completed_at = datetime.utcnow()

                # 更新角色图片和状态
                character = character_repo.get_by_id(character_id)
                if character:
                    character.image_url = task.result_url
                    character.generating_status = "completed"
            else:
                task.status = "failed"
                task.error_message = result.get("message", "生成失败")
                task.current_step = "生成失败"

                # 更新角色状态为失败
                character = character_repo.get_by_id(character_id)
                if character:
                    character.generating_status = "failed"

            db.commit()

        except Exception as e:
            task.status = "failed"
            task.error_message = str(e)
            task.current_step = "任务异常"

            # 更新角色状态为失败
            try:
                character = character_repo.get_by_id(character_id)
                if character:
                    character.generating_status = "failed"
            except:
                pass

            db.commit()
        finally:
            db.close()
    
    async def generate_scene_image_task(
        self,
        task_id: str,
        scene_id: str,
        name: str,
        setting: str,
        description: str
    ):
        """
        后台任务：生成场景图
        
        Args:
            task_id: 任务ID
            scene_id: 场景ID
            name: 场景名称
            setting: 环境设置
            description: 场景描述
        """
        db = SessionLocal()
        task_repo = TaskRepository(db)
        workflow_repo = WorkflowRepository(db)
        template_repo = PromptTemplateRepository(db)
        scene_repo = SceneRepository(db)
        
        try:
            # 获取任务
            task = task_repo.get_by_id(task_id)
            if not task:
                return

            # 获取当前激活的 scene 工作流
            workflow = workflow_repo.get_active_by_type("scene")

            # 记录工作流信息
            if workflow:
                task.workflow_id = workflow.id
                task.workflow_name = workflow.name
                task.current_step = f"使用工作流: {workflow.name}"
            else:
                task.current_step = "使用默认工作流"

            # 更新任务状态为运行中
            task.status = "running"
            task.started_at = datetime.utcnow()
            db.commit()

            # 获取场景所属小说
            scene = scene_repo.get_by_id(scene_id)
            novel = db.query(Novel).filter(Novel.id == scene.novel_id).first() if scene else None

            # 获取场景提示词模板（类型为 'scene'）
            template = None
            if novel:
                template = template_repo.get_default_system_template("scene")

            # 获取角色提示词模板（用于提取 style）
            character_template = None
            if novel and novel.prompt_template_id:
                character_template = template_repo.get_by_id(novel.prompt_template_id)

            # 如果没有指定模板，使用默认系统模板
            if not character_template:
                character_template = template_repo.get_default_system_template("character")

            # 获取 style（优先使用小说配置的 Image Style - 角色模板的 style）
            style = "anime style, high quality, detailed, environment"
            if character_template and character_template.style:
                # 优先使用小说配置的 Image Style（角色模板的 style）
                style = character_template.style
                print(f"[SceneTask] Using character template style (Image Style): {style}")
            elif character_template:
                # 兼容旧模板：从角色模板内容中提取 style
                style = extract_style_from_character_template(character_template.template)
                print(f"[SceneTask] Extracted style from character template: {style}")
            elif template and template.style:
                # 最后使用场景模板的 style 作为后备
                style = template.style
                print(f"[SceneTask] Using scene template style: {style}")
            
            print(f"[SceneTask] Final style: {style}")

            # 构建提示词（只使用 setting 字段，传入 style）
            prompt = build_scene_prompt(name, setting, "", template.template if template else None, style)
            print(f"[SceneTask] Generated prompt: {prompt[:100]}...")

            task.current_step = f"使用模板: {template.name if template else '默认'}, 提示词: {prompt[:80]}..."

            # 保存提示词
            task.prompt_text = prompt
            db.commit()

            # 获取工作流JSON字符串
            workflow_json_str = workflow.workflow_json if workflow else None
            print(
                f"[Task] Scene Workflow JSON available: {workflow_json_str is not None}, length: {len(workflow_json_str) if workflow_json_str else 0}")

            # 获取工作流的节点映射配置
            node_mapping = None
            if workflow and workflow.node_mapping:
                try:
                    node_mapping = json.loads(workflow.node_mapping)
                    print(f"[Task] Using scene node mapping: {node_mapping}")
                except Exception as e:
                    print(f"[Task] Failed to parse scene node_mapping: {e}")

            # 构建实际提交给ComfyUI的完整工作流
            print(f"[Task] Building scene workflow with: {workflow.name if workflow else 'default'}")
            print(f"[Task] Novel ID: {task.novel_id}, Scene: {name}")

            submitted_workflow = self.comfyui_service.builder.build_scene_workflow(
                prompt=prompt,
                workflow_json=workflow_json_str,
                novel_id=task.novel_id,
                scene_name=name,
                aspect_ratio=novel.aspect_ratio if novel else None,
                node_mapping=node_mapping,
                style=style
            )

            # 保存构建后的完整工作流到任务
            task.workflow_json = json.dumps(submitted_workflow, ensure_ascii=False, indent=2)
            db.commit()
            print(f"[Task] Saved submitted scene workflow to task")

            # 调用 ComfyUI 生成图片
            result = await self.comfyui_service.generate_scene_image(
                prompt,
                workflow_json=workflow_json_str,
                novel_id=task.novel_id,
                scene_name=name,
                aspect_ratio=novel.aspect_ratio if novel else None,
                node_mapping=node_mapping,
                workflow=submitted_workflow
            )

            print(f"[Task] Scene generation result: {result}")

            if result.get("success"):
                image_url = result.get("image_url")

                # 下载图片到本地存储
                task.current_step = "下载图片到服务器..."
                db.commit()

                try:
                    local_path = await file_storage.download_image(
                        url=image_url,
                        novel_id=task.novel_id or "default",
                        character_name=name,
                        image_type="scene"
                    )

                    if local_path:
                        # 构建本地可访问的URL
                        relative_path = local_path.replace(str(file_storage.base_dir), "").replace("\\", "/")
                        local_url = f"/api/files/{relative_path.lstrip('/')}"
                        task.result_url = local_url
                        task.current_step = "生成完成，图片已保存"
                    else:
                        # 下载失败，使用原始URL
                        task.result_url = image_url
                        task.current_step = "生成完成，使用远程图片"
                except Exception as e:
                    print(f"[Task] Failed to download scene image: {e}")
                    task.result_url = image_url
                    task.current_step = "生成完成，使用远程图片"

                task.status = "completed"
                task.progress = 100
                task.completed_at = datetime.utcnow()

                # 更新场景图片和状态
                scene = scene_repo.get_by_id(scene_id)
                if scene:
                    scene.image_url = task.result_url
                    scene.generating_status = "completed"
            else:
                task.status = "failed"
                task.error_message = result.get("message", "生成失败")
                task.current_step = "生成失败"

                # 更新场景状态为失败
                scene = scene_repo.get_by_id(scene_id)
                if scene:
                    scene.generating_status = "failed"

            db.commit()

        except Exception as e:
            task.status = "failed"
            task.error_message = str(e)
            task.current_step = "任务异常"

            # 更新场景状态为失败
            try:
                scene = scene_repo.get_by_id(scene_id)
                if scene:
                    scene.generating_status = "failed"
            except:
                pass

            db.commit()
        finally:
            db.close()
    
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
            "comfyuiPromptId": task.comfyui_prompt_id,
            "createdAt": format_datetime(task.created_at),
            "startedAt": format_datetime(task.started_at),
            "completedAt": format_datetime(task.completed_at),
        }
