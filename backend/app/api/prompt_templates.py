"""
PromptTemplate API 层

提示词模板相关的路由定义
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.schemas.prompt_template import PromptTemplateCreate, PromptTemplateUpdate
from app.services.prompt_template_service import PromptTemplateService
from app.repositories import PromptTemplateRepository

router = APIRouter(tags=["prompt_templates"])


def get_template_repo(db: Session = Depends(get_db)) -> PromptTemplateRepository:
    """获取 PromptTemplateRepository 实例"""
    return PromptTemplateRepository(db)


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
