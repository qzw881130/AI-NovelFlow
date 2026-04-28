"""
道具图片生成服务

封装道具图片生成的业务逻辑
"""
import json
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional

from sqlalchemy.orm import Session

from app.models.novel import Prop, Novel
from app.models.task import Task
from app.models.workflow import Workflow
from app.repositories import TaskRepository, WorkflowRepository, PropRepository
from app.services.comfyui import ComfyUIService
from app.services.file_storage import file_storage
from app.services.prompt_builder import build_prop_prompt, get_style


class PropService:
    """道具服务"""

    def __init__(self, db: Session = None):
        self.db = db
        self.comfyui_service = ComfyUIService()

    def create_prop_image_task(
        self,
        prop_id: str,
        db: Session = None
    ) -> Dict[str, Any]:
        """
        创建道具图生成任务

        Args:
            prop_id: 道具ID
            db: 数据库会话

        Returns:
            创建结果
        """
        db = db or self.db
        prop_repo = PropRepository(db)
        task_repo = TaskRepository(db)
        workflow_repo = WorkflowRepository(db)

        # 获取道具
        prop = prop_repo.get_by_id(prop_id)
        if not prop:
            return {"success": False, "message": "道具不存在"}

        # 检查是否已有进行中的任务
        existing_task = task_repo.get_active_by_prop(prop_id)
        if existing_task:
            return {
                "success": True,
                "message": "已有进行中的生成任务",
                "data": {
                    "taskId": existing_task.id,
                    "status": existing_task.status
                }
            }

        # 检查道具生成状态
        if prop.generating_status == "running":
            return {
                "success": False,
                "message": "该道具正在生成图片中，请稍后再试"
            }

        # 获取并验证工作流
        workflow = workflow_repo.get_active_by_type("prop")

        # 如果没有 prop 类型工作流，尝试使用 scene 类型
        if not workflow:
            workflow = workflow_repo.get_active_by_type("scene")

        is_valid, error_msg = self._validate_workflow_node_mapping(workflow, "prop")
        if not is_valid:
            return {"success": False, "message": error_msg}

        # 创建任务
        task = Task(
            type="prop_image",
            name=f"生成道具图: {prop.name}",
            description=f"为道具 '{prop.name}' 生成图片",
            novel_id=prop.novel_id,
            prop_id=prop_id,
            status="pending"
        )
        task_repo.create(task)

        # 更新道具生成状态
        prop.generating_status = "running"
        prop.prop_task_id = task.id
        db.commit()

        # 启动后台任务
        asyncio.create_task(
            self._generate_prop_image_task(
                task.id,
                prop_id,
                prop.name,
                prop.appearance,
                prop.description
            )
        )

        return {
            "success": True,
            "message": "道具图生成任务已创建",
            "data": {
                "taskId": task.id,
                "status": "pending"
            }
        }

    async def _generate_prop_image_task(
        self,
        task_id: str,
        prop_id: str,
        name: str,
        appearance: str,
        description: str
    ):
        """
        后台任务：生成道具图

        Args:
            task_id: 任务ID
            prop_id: 道具ID
            name: 道具名称
            appearance: 道具外观
            description: 道具描述
        """
        from app.core.database import SessionLocal
        db = SessionLocal()
        task_repo = TaskRepository(db)
        workflow_repo = WorkflowRepository(db)
        prop_repo = PropRepository(db)

        try:
            # 获取任务
            task = task_repo.get_by_id(task_id)
            if not task:
                return

            # 获取当前激活的工作流（优先 prop，其次 scene）
            workflow = workflow_repo.get_active_by_type("prop")

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

            # 获取道具所属小说
            prop = prop_repo.get_by_id(prop_id)
            novel = db.query(Novel).filter(Novel.id == prop.novel_id).first() if prop else None

            # 获取道具生成提示词模板
            from app.repositories import PromptTemplateRepository
            template_repo = PromptTemplateRepository(db)
            template = None
            if novel and novel.prop_prompt_template_id:
                template = template_repo.get_by_id(novel.prop_prompt_template_id)
            if not template:
                template = template_repo.get_default_system_template("prop")

            # 获取风格提示词
            style, style_template = get_style(db, novel, "prop")

            print(f"[PropTask] Final style: {style}")

            # 构建提示词（使用外观或描述）
            raw_appearance = appearance or description
            if not raw_appearance:
                task.status = "failed"
                task.error_message = "道具缺少外观描述，无法生成图片"
                task.current_step = "生成失败"
                self._update_prop_status(prop_repo, prop_id, "failed")
                db.commit()
                return

            prompt = build_prop_prompt(name, raw_appearance, "", template.template if template else None, style)
            print(f"[PropTask] Generated prompt: {prompt[:100]}...")

            task.current_step = f"使用模板: {template.name if template else '默认'}, 提示词: {prompt[:80]}..."

            # 保存提示词
            task.prompt_text = prompt
            db.commit()

            # 获取工作流JSON字符串
            workflow_json_str = workflow.workflow_json if workflow else None
            print(
                f"[PropTask] Workflow JSON available: {workflow_json_str is not None}, length: {len(workflow_json_str) if workflow_json_str else 0}")

            # 获取工作流的节点映射配置
            node_mapping = None
            if workflow and workflow.node_mapping:
                try:
                    node_mapping = json.loads(workflow.node_mapping)
                    print(f"[PropTask] Using node mapping: {node_mapping}")
                except Exception as e:
                    print(f"[PropTask] Failed to parse node_mapping: {e}")

            # 构建实际提交给ComfyUI的完整工作流
            print(f"[PropTask] Building workflow with: {workflow.name if workflow else 'default'}")
            print(f"[PropTask] Novel ID: {task.novel_id}, Prop: {name}")

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
            print(f"[PropTask] Saved submitted workflow to task")

            # 调用 ComfyUI 生成图片
            task.current_step = "正在调用 ComfyUI 生成图片..."
            task.progress = 30
            db.commit()

            result = await self.comfyui_service.generate_scene_image(
                prompt,
                workflow_json=workflow_json_str,
                novel_id=task.novel_id,
                scene_name=name,
                aspect_ratio=novel.aspect_ratio if novel else None,
                node_mapping=node_mapping,
                workflow=submitted_workflow
            )

            print(f"[PropTask] Generation result: {json.dumps(result, ensure_ascii=True)}")

            if result.get("prompt_id"):
                task.comfyui_prompt_id = result["prompt_id"]

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
                        image_type="prop"
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
                    print(f"[PropTask] Failed to download prop image: {e}")
                    task.result_url = image_url
                    task.current_step = "生成完成，使用远程图片"

                task.status = "completed"
                task.progress = 100
                task.completed_at = datetime.utcnow()

                # 更新道具图片和状态
                prop = prop_repo.get_by_id(prop_id)
                if prop:
                    prop.image_url = task.result_url
                    prop.generating_status = "completed"
            else:
                task.status = "failed"
                task.error_message = result.get("message", "生成失败")
                task.current_step = "生成失败"

                # 更新道具状态为失败
                prop = prop_repo.get_by_id(prop_id)
                if prop:
                    prop.generating_status = "failed"

            db.commit()

        except Exception as e:
            task.status = "failed"
            task.error_message = str(e)
            task.current_step = "任务异常"

            # 更新道具状态为失败
            try:
                prop = prop_repo.get_by_id(prop_id)
                if prop:
                    prop.generating_status = "failed"
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
            task_type: 任务类型 (prop)

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

        # 检查必需的字段
        required_fields = ["prompt_node_id", "save_image_node_id"]

        missing_fields = []
        field_names = {
            "prompt_node_id": "提示词输入节点",
            "save_image_node_id": "图片保存节点",
        }

        for field in required_fields:
            if not node_mapping.get(field):
                missing_fields.append(field_names.get(field, field))

        if missing_fields:
            return False, f"工作流 '{workflow.name}' 的映射配置不完整，缺少以下必需字段：{', '.join(missing_fields)}。请在【系统配置-ComfyUI工作流】中配置完整后再试。"

        return True, ""

    def _update_prop_status(self, prop_repo: PropRepository, prop_id: str, status: str):
        """更新道具生成状态"""
        prop = prop_repo.get_by_id(prop_id)
        if prop:
            prop.generating_status = status