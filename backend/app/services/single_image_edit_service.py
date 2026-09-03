"""单图编辑服务。"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.task import Task
from app.repositories import TaskRepository, WorkflowRepository
from app.services.comfyui import ComfyUIService
from app.services.file_storage import file_storage
from app.utils.path_utils import url_to_local_path


class SingleImageEditService:
    """封装单图编辑工作流调用和任务记录。"""

    def __init__(self, db: Session):
        self.db = db
        self.comfyui_service = ComfyUIService()

    async def edit_image(
        self,
        *,
        source_image_url: str,
        prompt: str,
        novel_id: str,
        entity_id: str,
        entity_name: str,
        entity_type: str,
        output_image_type: str,
    ) -> Dict[str, Any]:
        image_path = url_to_local_path(source_image_url)
        if not image_path:
            return {"success": False, "message": "图片文件不存在或不是本地图片", "status_code": 400}

        workflow = WorkflowRepository(self.db).get_active_by_type("single_image_edit")
        if not workflow:
            return {"success": False, "message": "未配置单图编辑工作流", "status_code": 400}

        try:
            node_mapping = json.loads(workflow.node_mapping) if workflow.node_mapping else {}
        except Exception:
            node_mapping = {}

        missing_fields = [
            field for field in ["load_image_node_id", "prompt_node_id", "save_image_node_id"]
            if not node_mapping.get(field)
        ]
        if missing_fields:
            return {
                "success": False,
                "message": f"单图编辑工作流节点映射不完整: {', '.join(missing_fields)}",
                "status_code": 400,
            }

        label_by_type = {"character": "角色", "scene": "场景", "prop": "道具", "shot": "分镜"}
        entity_label = label_by_type.get(entity_type, "素材")
        task_kwargs = {
            "character": {"character_id": entity_id},
            "scene": {"scene_id": entity_id},
            "prop": {"prop_id": entity_id},
            "shot": {"shot_id": entity_id},
        }.get(entity_type, {})

        task_repo = TaskRepository(self.db)
        task = task_repo.create(Task(
            type="single_image_edit",
            name=f"编辑{entity_label}图片: {entity_name}",
            description=f"为{entity_label} '{entity_name}' 编辑图片",
            novel_id=novel_id,
            status="running",
            progress=10,
            current_step="提交 ComfyUI 单图编辑任务",
            workflow_id=workflow.id,
            workflow_name=workflow.name,
            prompt_text=prompt,
            reference_images=json.dumps([{"label": "原图", "url": source_image_url}], ensure_ascii=False),
            started_at=datetime.now(timezone.utc),
            **task_kwargs,
        ))

        def on_prompt_queued(prompt_id: str, submitted_workflow: dict):
            task.comfyui_prompt_id = prompt_id
            task.workflow_json = json.dumps(submitted_workflow, ensure_ascii=False)
            task.progress = 30
            task.current_step = "ComfyUI 正在编辑图片"
            self.db.commit()

        result = await self.comfyui_service.edit_image_with_workflow(
            image_path=image_path,
            prompt=prompt,
            workflow_json=workflow.workflow_json,
            node_mapping=node_mapping,
            on_prompt_queued=on_prompt_queued,
        )
        if not result.get("success") or not result.get("image_url"):
            self._mark_failed(task, result.get("message", "编辑图片失败"))
            return {"success": False, "message": result.get("message", "编辑图片失败"), "status_code": 500, "task_id": task.id}

        task.progress = 80
        task.current_step = "保存编辑结果"
        self.db.commit()

        local_path = await file_storage.download_image(
            result["image_url"],
            novel_id,
            f"{entity_name}_edit",
            image_type=output_image_type,
        )
        if not local_path:
            self._mark_failed(task, "保存编辑结果失败")
            return {"success": False, "message": "保存编辑结果失败", "status_code": 500, "task_id": task.id}

        relative_path = Path(local_path).relative_to(file_storage.base_dir)
        relative_url = str(relative_path).replace("\\", "/")
        image_url = f"/api/files/{relative_url}"
        task.status = "completed"
        task.progress = 100
        task.current_step = "编辑完成"
        task.result_url = image_url
        task.completed_at = datetime.now(timezone.utc)
        self.db.commit()

        return {"success": True, "image_url": image_url, "task_id": task.id}

    def _mark_failed(self, task: Task, message: Optional[str]) -> None:
        task.status = "failed"
        task.progress = 100
        task.current_step = "编辑失败"
        task.error_message = message or "编辑图片失败"
        task.completed_at = datetime.now(timezone.utc)
        self.db.commit()
