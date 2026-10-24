"""
场景服务

封装场景相关的业务逻辑
"""
import json
from datetime import datetime
from typing import Dict, Any

from sqlalchemy.orm import Session

from app.models.novel import Scene
from app.models.task import Task
from app.models.workflow import Workflow
from app.repositories import TaskRepository, WorkflowRepository, SceneRepository
from app.services.comfyui import ComfyUIService
from app.services.scene_quality_pipeline import run_scene_quality_pipeline
from app.services.background_workers import (
    persistent_job, worker_manager, ensure_task_active,
)


async def run_scene_image_job(
    task_id: str,
    scene_id: str,
    name: str,
    setting: str,
    description: str,
) -> None:
    await SceneService()._generate_scene_image_task(
        task_id, scene_id, name, setting, description
    )


def enqueue_scene_image_task(
    task_id: str,
    scene_id: str,
    name: str,
    setting: str,
    description: str
) -> None:
    """Queue scene image generation in its dedicated serial worker."""
    payload = {
        "task_id": task_id,
        "scene_id": scene_id,
        "name": name,
        "setting": setting,
        "description": description,
    }
    worker_manager.worker("scene_image").enqueue(persistent_job(
        task_id,
        "app.services.scene_service:run_scene_image_job",
        payload,
        lambda: run_scene_image_job(**payload),
    ))


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
        if scene.generating_status in ["pending", "running"]:
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
            status="pending",
            metadata_json=json.dumps({"scene_quality": {
                "cycle": 1, "stage": "generate", "original_url": scene.image_url,
                "attempts": [],
            }}, ensure_ascii=False),
        )
        task_repo.create(task)
        
        # 更新场景生成状态
        scene.generating_status = "pending"
        scene.scene_task_id = task.id
        db.commit()
        
        enqueue_scene_image_task(
            task.id,
            scene_id,
            scene.name,
            scene.setting,
            scene.description,
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
        """Generate and publish only a scene candidate that passes AI review."""
        from app.core.database import SessionLocal
        db = SessionLocal()
        task = None
        try:
            task = TaskRepository(db).get_by_id(task_id)
            if not task or task.status not in {"pending", "running"}:
                return
            scene = SceneRepository(db).get_by_id(scene_id)
            if not scene:
                raise RuntimeError("场景不存在")
            await run_scene_quality_pipeline(db, task, scene, self.comfyui_service)
        except Exception as exc:
            if task:
                ensure_task_active(db, task)
                task.status = "failed"
                task.progress = 100
                task.error_message = str(exc)
                task.current_step = "场景图审核或生成失败"
                task.completed_at = datetime.utcnow()
                scene = SceneRepository(db).get_by_id(scene_id)
                if scene and scene.scene_task_id == task.id:
                    metadata = json.loads(task.metadata_json or "{}")
                    original_url = (metadata.get("scene_quality") or {}).get("original_url")
                    if scene.image_url == original_url:
                        scene.generating_status = "failed"
                    else:
                        scene.generating_status = "completed" if scene.image_url else "failed"
                db.commit()
        finally:
            db.close()

    def create_missing_scene_image_tasks(self, novel_id: str, db: Session = None) -> Dict[str, Any]:
        """Queue image tasks for scenes without images or with failed generation."""
        db = db or self.db
        scene_repo = SceneRepository(db)
        task_repo = TaskRepository(db)
        scenes = scene_repo.list_by_novel(novel_id)
        targets = [
            scene for scene in scenes
            if (not scene.image_url or scene.generating_status == "failed")
            and not task_repo.get_active_by_scene(scene.id)
        ]

        queued_count = 0
        failed_items = []
        for scene in targets:
            result = self.create_scene_image_task(scene.id, db=db)
            if result.get("success"):
                queued_count += 1
            else:
                failed_items.append({"id": scene.id, "name": scene.name, "message": result.get("message", "创建任务失败")})

        return {"success": True, "message": f"已加入 {queued_count} 个场景图生成任务", "data": {"queuedCount": queued_count, "failedCount": len(failed_items), "failedItems": failed_items}}
    
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
