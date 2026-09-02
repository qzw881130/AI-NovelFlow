"""
提示词模板 API 路由

提示词模板相关的路由定义
"""
from datetime import datetime
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile
import re
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.schemas.prompt_template import PromptTemplateCreate, PromptTemplateUpdate
from app.services.prompt_template_service import PromptTemplateService
from app.repositories import PromptTemplateRepository
from app.api.deps import get_prompt_template_repo

router = APIRouter(tags=["prompt_templates"])


PROMPT_TEMPLATE_EXPORT_CATEGORIES = [
    ("素材解析", [
        ("character_parse", "角色解析提示词"),
        ("scene_parse", "场景解析提示词"),
        ("prop_parse", "道具解析提示词"),
    ]),
    ("素材生成", [
        ("character", "角色生成提示词"),
        ("scene", "场景生成提示词"),
        ("prop", "道具生成提示词"),
    ]),
    ("风格设计", [("style", "风格提示词")]),
    ("分镜规划", [("chapter_split", "分镜拆分提示词")]),
    ("分镜生图", [("shot_image_prompt", "主分镜图生成提示词构建")]),
    ("视频导演", [
        ("video_mode_recommender", "视频生成模式推荐"),
        ("keyframe_planner", "关键帧时间轴规划"),
        ("keyframe_transition", "关键帧过渡规划"),
    ]),
    ("关键帧生图", [("keyframe_image_prompt", "视频关键帧生图提示词构建")]),
    ("视频生成", [
        ("h3_single_frame_prompt", "MiniMax H3 单帧视频提示词构建"),
        ("h3_first_last_frame_prompt", "MiniMax H3 首尾帧视频提示词构建"),
        ("h3_multi_keyframe_prompt", "MiniMax H3 多关键帧视频提示词构建"),
    ]),
]


def _safe_zip_path_part(value: str, fallback: str) -> str:
    """Return a cross-platform safe directory/file name segment."""
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", (value or fallback).strip())
    cleaned = re.sub(r"\s+", " ", cleaned).rstrip(" .")
    return cleaned or fallback


def _unique_zip_path(path: str, used_paths: set[str]) -> str:
    if path not in used_paths:
        used_paths.add(path)
        return path

    stem, suffix = path.rsplit(".", 1) if "." in path else (path, "")
    index = 2
    while True:
        candidate = f"{stem} ({index}).{suffix}" if suffix else f"{stem} ({index})"
        if candidate not in used_paths:
            used_paths.add(candidate)
            return candidate
        index += 1


def get_template_service(db: Session = Depends(get_db)) -> PromptTemplateService:
    """获取 PromptTemplateService 实例"""
    return PromptTemplateService(db)


def init_system_prompt_templates(db: Session):
    """初始化系统预设提示词模板（供 main.py 调用）"""
    service = PromptTemplateService(db)
    service.init_system_templates()


# ==================== 模板 CRUD ====================

@router.get("/", response_model=dict)
def list_prompt_templates(
    type: Optional[str] = Query(None, description="筛选类型: character 或 chapter_split"),
    service: PromptTemplateService = Depends(get_template_service)
):
    """获取所有提示词模板"""
    templates = service.list_templates(type)
    return {
        "success": True,
        "data": [service.to_response(t) for t in templates]
    }


@router.get("/export-all", response_class=StreamingResponse)
def export_all_prompt_templates(
    repo: PromptTemplateRepository = Depends(get_prompt_template_repo)
):
    """按一级/二级分类打包导出所有提示词模板。"""
    templates_by_type = {}
    for template in repo.list_all():
        templates_by_type.setdefault(template.type, []).append(template)

    buffer = BytesIO()
    used_paths: set[str] = set()

    with ZipFile(buffer, "w", ZIP_DEFLATED) as zip_file:
        for category_name, type_configs in PROMPT_TEMPLATE_EXPORT_CATEGORIES:
            category_dir = _safe_zip_path_part(category_name, "未分类")
            for template_type, type_name in type_configs:
                type_dir = _safe_zip_path_part(type_name, template_type)
                templates = templates_by_type.get(template_type, [])
                for template in templates:
                    source = "系统" if template.is_system else "用户"
                    file_name = _safe_zip_path_part(f"{source}-{template.name}", f"{source}-{template.id}")
                    zip_path = _unique_zip_path(f"{category_dir}/{type_dir}/{file_name}.txt", used_paths)
                    zip_file.writestr(zip_path, template.template or "")

        known_types = {template_type for _, type_configs in PROMPT_TEMPLATE_EXPORT_CATEGORIES for template_type, _ in type_configs}
        for template_type, templates in sorted(templates_by_type.items()):
            if template_type in known_types:
                continue
            type_dir = _safe_zip_path_part(template_type, "unknown")
            for template in templates:
                source = "系统" if template.is_system else "用户"
                file_name = _safe_zip_path_part(f"{source}-{template.name}", f"{source}-{template.id}")
                zip_path = _unique_zip_path(f"未分类/{type_dir}/{file_name}.txt", used_paths)
                zip_file.writestr(zip_path, template.template or "")

    buffer.seek(0)
    filename = f"prompt_templates_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    quoted_filename = quote(filename)
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quoted_filename}"}
    return StreamingResponse(buffer, media_type="application/zip", headers=headers)


@router.get("/{template_id}", response_model=dict)
def get_prompt_template(
    template_id: str,
    service: PromptTemplateService = Depends(get_template_service)
):
    """获取单个提示词模板"""
    template = service.get_template_by_id(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="提示词模板不存在")

    return {
        "success": True,
        "data": service.to_response(template)
    }


@router.post("/", response_model=dict)
def create_prompt_template(
    data: PromptTemplateCreate,
    service: PromptTemplateService = Depends(get_template_service)
):
    """创建用户自定义提示词模板"""
    template = service.create_template(
        name=data.name,
        description=data.description,
        template=data.template,
        template_type=data.type
    )

    return {
        "success": True,
        "message": "提示词模板创建成功",
        "data": service.to_response(template)
    }


@router.post("/{template_id}/copy", response_model=dict)
def copy_prompt_template(
    template_id: str,
    service: PromptTemplateService = Depends(get_template_service)
):
    """复制系统提示词模板为用户自定义模板"""
    try:
        new_template = service.copy_template(template_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {
        "success": True,
        "message": "提示词模板复制成功",
        "data": service.to_response(new_template)
    }


@router.put("/{template_id}", response_model=dict)
def update_prompt_template(
    template_id: str,
    data: PromptTemplateUpdate,
    service: PromptTemplateService = Depends(get_template_service)
):
    """更新提示词模板（仅用户自定义可编辑）"""
    try:
        template = service.update_template(
            template_id=template_id,
            name=data.name,
            description=data.description,
            template=data.template,
            template_type=data.type
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    return {
        "success": True,
        "message": "提示词模板更新成功",
        "data": service.to_response(template)
    }


@router.delete("/{template_id}", response_model=dict)
def delete_prompt_template(
    template_id: str,
    service: PromptTemplateService = Depends(get_template_service)
):
    """删除提示词模板（仅用户自定义可删除）"""
    try:
        service.delete_template(template_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    return {"success": True, "message": "提示词模板删除成功"}


@router.get("/system/default", response_model=dict)
def get_default_system_template(
    type: Optional[str] = Query("character", description="模板类型: character 或 chapter_split"),
    service: PromptTemplateService = Depends(get_template_service)
):
    """获取默认的系统提示词模板"""
    template = service.get_default_system_template(type)

    if not template:
        raise HTTPException(status_code=404, detail="未找到系统提示词模板")

    return {
        "success": True,
        "data": service.to_response(template)
    }
