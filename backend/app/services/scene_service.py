"""
场景服务

封装场景相关的业务逻辑
"""
import json
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional

from sqlalchemy.orm import Session

from app.models.novel import Scene
from app.models.task import Task
from app.models.workflow import Workflow
from app.repositories import TaskRepository, WorkflowRepository, SceneRepository
from app.services.comfyui import ComfyUIService
from app.services.file_storage import file_storage
from app.services.prompt_builder import build_scene_prompt, get_style


class SceneService:
    """场景服务"""
    
    def __init__(self, db: Session = None):
        self.db = db
        self.comfyui_service = ComfyUIService()
    
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
        is_valid, error_msg = self._validate_workflow_node_mapping(workflow, "scene")
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
            self._generate_scene_image_task(
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
    
    async def _generate_scene_image_task(
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
        from app.core.database import SessionLocal
        db = SessionLocal()
        task_repo = TaskRepository(db)
        workflow_repo = WorkflowRepository(db)
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
            from app.models.novel import Novel
            novel = db.query(Novel).filter(Novel.id == scene.novel_id).first() if scene else None

            # 获取场景生成提示词模板
            from app.repositories import PromptTemplateRepository
            template_repo = PromptTemplateRepository(db)
            template = None
            if novel and novel.scene_prompt_template_id:
                template = template_repo.get_by_id(novel.scene_prompt_template_id)
            if not template:
                template = template_repo.get_default_system_template("scene")

            # 获取风格提示词
            style, style_template = get_style(db, novel, "scene")
            
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

            print(f"[Task] Scene generation result: {json.dumps(result, ensure_ascii=True)}")

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
    
    def _validate_workflow_node_mapping(self, workflow: Workflow, task_type: str) -> tuple[bool, str]:
        """
        验证工作流的节点映射配置是否完整
        
        Args:
            workflow: 工作流对象
            task_type: 任务类型 (scene)
            
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
            "scene": ["prompt_node_id", "save_image_node_id"],
        }

        fields = required_fields.get(task_type)
        if not fields:
            return True, ""

        missing_fields = []
        field_names = {
            "prompt_node_id": "提示词输入节点",
            "save_image_node_id": "图片保存节点",
        }

        for field in fields:
            if not node_mapping.get(field):
                missing_fields.append(field_names.get(field, field))

        if missing_fields:
            return False, f"工作流 '{workflow.name}' 的映射配置不完整，缺少以下必需字段：{', '.join(missing_fields)}。请在【系统配置-ComfyUI工作流】中配置完整后再试。"

        return True, ""