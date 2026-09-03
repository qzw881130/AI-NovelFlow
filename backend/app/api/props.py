"""
道具路由 - 道具 CRUD 和图像生成相关接口
"""
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Body, UploadFile, File
from sqlalchemy.orm import Session
import json

from app.core.database import get_db
from app.repositories.prop_repository import PropRepository
from app.repositories.task import TaskRepository
from app.repositories.novel_repository import NovelRepository
from app.repositories import PromptTemplateRepository
from app.services.llm_service import LLMService
from app.services.file_storage import file_storage
from app.services.prompt_builder import build_prop_prompt, get_style
from app.api.deps import get_prop_repo, get_novel_repo, get_llm_service, get_prompt_template_repo, get_task_repo
from app.services.prop_image_service import PropService
from app.schemas.prop import PropCreate, PropUpdate, PropImageEditRequest, PropImageReplaceRequest
from app.services.single_image_edit_service import SingleImageEditService
from app.utils.path_utils import url_to_local_path

router = APIRouter()


def format_datetime(dt: Optional[datetime]) -> Optional[str]:
    if dt:
        return dt.isoformat()
    return None


# ==================== 道具管理 ====================

@router.get("/", response_model=dict)
async def get_props(
    novel_id: str = Query(..., description="小说ID"),
    db: Session = Depends(get_db),
    prop_repo: PropRepository = Depends(get_prop_repo),
    task_repo: TaskRepository = Depends(get_task_repo)
):
    """获取小说的所有道具"""
    props = prop_repo.list_by_novel(novel_id)
    fixed_stale_status = False
    for prop in props:
        if prop.generating_status == "running" and prop.prop_task_id:
            task = task_repo.get_by_id(prop.prop_task_id)
            if not task or task.status not in ["pending", "running"]:
                prop.generating_status = "completed" if prop.image_url and task and task.status == "completed" else "failed"
                fixed_stale_status = True

    if fixed_stale_status:
        prop_repo.db.commit()

    return {
        "success": True,
        "data": [
            {
                "id": p.id,
                "novelId": p.novel_id,
                "name": p.name,
                "description": p.description,
                "appearance": p.appearance,
                "imageUrl": p.image_url,
                "generatingStatus": p.generating_status,
                "propTaskId": p.prop_task_id,
                "startChapter": p.start_chapter,
                "endChapter": p.end_chapter,
                "isIncremental": p.is_incremental,
                "sourceRange": p.source_range,
                "lastParsedAt": format_datetime(p.last_parsed_at),
                "createdAt": format_datetime(p.created_at),
                "updatedAt": format_datetime(p.updated_at)
            }
            for p in props
        ]
    }


@router.post("/generate-missing-images", response_model=dict)
async def generate_missing_prop_images(
    novel_id: str = Query(...),
    db: Session = Depends(get_db)
):
    """Queue image tasks for props without images or with failed generation."""
    prop_service = PropService(db)
    return prop_service.create_missing_prop_image_tasks(novel_id)


@router.get("/{prop_id}", response_model=dict)
async def get_prop(
    prop_id: str,
    db: Session = Depends(get_db),
    prop_repo: PropRepository = Depends(get_prop_repo)
):
    """获取单个道具详情"""
    prop = prop_repo.get_by_id(prop_id)
    if not prop:
        raise HTTPException(status_code=404, detail="道具不存在")
    
    return {
        "success": True,
        "data": {
            "id": prop.id,
            "novelId": prop.novel_id,
            "name": prop.name,
            "description": prop.description,
            "appearance": prop.appearance,
            "imageUrl": prop.image_url,
            "generatingStatus": prop.generating_status,
            "propTaskId": prop.prop_task_id,
            "startChapter": prop.start_chapter,
            "endChapter": prop.end_chapter,
            "isIncremental": prop.is_incremental,
            "sourceRange": prop.source_range,
            "lastParsedAt": format_datetime(prop.last_parsed_at),
            "createdAt": format_datetime(prop.created_at),
            "updatedAt": format_datetime(prop.updated_at)
        }
    }


@router.post("/", response_model=dict)
async def create_prop(
    data: PropCreate,
    db: Session = Depends(get_db),
    prop_repo: PropRepository = Depends(get_prop_repo),
    novel_repo: NovelRepository = Depends(get_novel_repo)
):
    """创建新道具"""
    # 验证小说存在
    novel = novel_repo.get_by_id(data.novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    # 检查是否已存在同名道具
    existing_prop = prop_repo.get_by_name(data.novel_id, data.name)
    if existing_prop:
        raise HTTPException(status_code=400, detail="道具名称已存在")

    prop = prop_repo.create(
        novel_id=data.novel_id,
        name=data.name,
        description=data.description or "",
        appearance=data.appearance or ""
    )

    return {
        "success": True,
        "data": {
            "id": prop.id,
            "novelId": prop.novel_id,
            "name": prop.name,
            "description": prop.description,
            "appearance": prop.appearance,
            "imageUrl": prop.image_url,
            "novelName": novel.title,
            "createdAt": format_datetime(prop.created_at),
        },
        "message": "道具创建成功"
    }


@router.put("/{prop_id}", response_model=dict)
async def update_prop(
    prop_id: str,
    data: PropUpdate,
    db: Session = Depends(get_db),
    prop_repo: PropRepository = Depends(get_prop_repo)
):
    """更新道具信息"""
    prop = prop_repo.get_by_id(prop_id)
    if not prop:
        raise HTTPException(status_code=404, detail="道具不存在")

    # 检查名称是否已被其他道具使用
    if data.name and data.name != prop.name:
        existing_prop = prop_repo.get_by_name(prop.novel_id, data.name)
        if existing_prop:
            raise HTTPException(status_code=400, detail="道具名称已存在")

    update_data = {}
    if data.name is not None:
        update_data["name"] = data.name
    if data.description is not None:
        update_data["description"] = data.description
    if data.appearance is not None:
        update_data["appearance"] = data.appearance

    prop = prop_repo.update(prop, **update_data)

    return {
        "success": True,
        "data": {
            "id": prop.id,
            "novelId": prop.novel_id,
            "name": prop.name,
            "description": prop.description,
            "appearance": prop.appearance,
            "imageUrl": prop.image_url
        },
        "message": "道具更新成功"
    }


@router.delete("/{prop_id}", response_model=dict)
async def delete_prop(
    prop_id: str,
    db: Session = Depends(get_db),
    prop_repo: PropRepository = Depends(get_prop_repo)
):
    """删除道具"""
    prop = prop_repo.get_by_id(prop_id)
    if not prop:
        raise HTTPException(status_code=404, detail="道具不存在")

    prop_repo.delete(prop)

    return {
        "success": True,
        "message": "道具删除成功"
    }


@router.delete("/", response_model=dict)
async def delete_props_by_novel(
    novel_id: str = Query(..., description="小说ID"),
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    prop_repo: PropRepository = Depends(get_prop_repo)
):
    """删除指定小说的所有道具"""
    # 检查小说是否存在
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    # 删除该小说的所有道具
    result = prop_repo.delete_by_novel(novel_id)

    # 删除道具图片目录
    file_storage.delete_props_dir(novel_id)

    return {"success": True, "message": f"已删除 {result} 个道具", "deleted_count": result}


@router.post("/{prop_id}/upload-image", response_model=dict)
async def upload_prop_image(
    prop_id: str,
    file: UploadFile = File(...),
    prop_repo: PropRepository = Depends(get_prop_repo),
    novel_repo: NovelRepository = Depends(get_novel_repo)
):
    """
    上传道具图片
    
    支持用户从本地上传道具图片，替代AI生成
    """
    prop = prop_repo.get_by_id(prop_id)
    if not prop:
        raise HTTPException(status_code=404, detail="道具不存在")
    
    # 验证文件类型
    allowed_types = ["image/png", "image/jpeg", "image/jpg", "image/webp"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400, 
            detail=f"不支持的文件类型: {file.content_type}，仅支持 PNG, JPG, WEBP"
        )
    
    try:
        # 获取保存路径
        file_path = file_storage.get_prop_image_path(
            novel_id=prop.novel_id,
            prop_name=prop.name
        )
        
        # 保存文件
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)
        
        # 计算访问URL
        relative_path = file_path.relative_to(file_storage.base_dir)
        image_url = f"/api/files/{relative_path}"
        
        # 更新道具记录
        prop_repo.update_image(prop, image_url)
        
        novel = novel_repo.get_by_id(prop.novel_id)
        
        return {
            "success": True,
            "data": {
                "id": prop.id,
                "novelId": prop.novel_id,
                "name": prop.name,
                "description": prop.description,
                "appearance": prop.appearance,
                "imageUrl": prop.image_url,
                "generatingStatus": prop.generating_status,
                "novelName": novel.title if novel else None,
                "updatedAt": prop.updated_at.isoformat() if prop.updated_at else None,
            },
            "message": "图片上传成功"
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")


@router.post("/{prop_id}/edit-image", response_model=dict)
async def edit_prop_image(
    prop_id: str,
    data: PropImageEditRequest,
    db: Session = Depends(get_db),
    prop_repo: PropRepository = Depends(get_prop_repo),
):
    """使用当前激活的单图编辑工作流编辑道具图片。"""
    prop = prop_repo.get_by_id(prop_id)
    if not prop:
        raise HTTPException(status_code=404, detail="道具不存在")
    if not prop.image_url:
        raise HTTPException(status_code=400, detail="道具暂无图片，无法编辑")

    result = await SingleImageEditService(db).edit_image(
        source_image_url=prop.image_url,
        prompt=data.prompt,
        novel_id=prop.novel_id,
        entity_id=prop.id,
        entity_name=prop.name,
        entity_type="prop",
        output_image_type="prop_edit",
    )
    if not result.get("success"):
        raise HTTPException(status_code=result.get("status_code", 500), detail=result.get("message", "编辑图片失败"))

    return {"success": True, "data": {"imageUrl": result["image_url"], "taskId": result.get("task_id")}, "message": "图片编辑成功"}


@router.post("/{prop_id}/replace-image", response_model=dict)
async def replace_prop_image(
    prop_id: str,
    data: PropImageReplaceRequest,
    prop_repo: PropRepository = Depends(get_prop_repo),
    novel_repo: NovelRepository = Depends(get_novel_repo),
):
    """用编辑结果替换道具图片。"""
    prop = prop_repo.get_by_id(prop_id)
    if not prop:
        raise HTTPException(status_code=404, detail="道具不存在")
    if not url_to_local_path(data.image_url):
        raise HTTPException(status_code=400, detail="图片文件不存在或不是本地图片")

    prop_repo.update_image(prop, data.image_url)
    novel = novel_repo.get_by_id(prop.novel_id)
    return {
        "success": True,
        "data": {
            "id": prop.id,
            "novelId": prop.novel_id,
            "name": prop.name,
            "description": prop.description,
            "appearance": prop.appearance,
            "imageUrl": prop.image_url,
            "generatingStatus": prop.generating_status,
            "propTaskId": prop.prop_task_id,
            "novelName": novel.title if novel else None,
            "updatedAt": format_datetime(prop.updated_at),
        },
        "message": "道具图片已替换",
    }


# ==================== 道具解析 ====================

@router.post("/parse", response_model=dict)
async def parse_props(
    novel_id: str = Query(..., description="小说ID"),
    text: str = Body(..., description="小说文本"),
    start_chapter: int = Body(None, description="开始章节"),
    end_chapter: int = Body(None, description="结束章节"),
    source_range: str = Body(None, description="来源范围"),
    db: Session = Depends(get_db),
    llm_service: LLMService = Depends(get_llm_service),
    prop_repo: PropRepository = Depends(get_prop_repo),
    novel_repo: NovelRepository = Depends(get_novel_repo)
):
    """解析小说文本中的道具"""
    try:
        # 获取小说信息以获取模板配置
        novel = novel_repo.get_by_id(novel_id)
        
        # 获取道具解析提示词模板
        prompt_template = None
        prompt_template_name = None
        if novel and novel.prop_parse_prompt_template_id:
            # 使用小说配置的模板
            template_repo = PromptTemplateRepository(db)
            template = template_repo.get_by_id(novel.prop_parse_prompt_template_id)
            if template:
                prompt_template = template.template
                prompt_template_name = template.name
        
        # 如果没有配置模板，使用默认模板文件
        if not prompt_template:
            import os
            template_path = os.path.join(os.path.dirname(__file__), '..', '..', 'prompt_templates', 'prop_parse.txt')
            with open(template_path, "r", encoding="utf-8") as f:
                prompt_template = f.read()
                prompt_template_name = "默认道具解析提示词"
        
        # 调用LLM解析道具
        result = await llm_service.chat_completion(
            system_prompt=prompt_template,
            user_content=text,
            temperature=0.3,
            max_tokens=4000,
            response_format="json_object",
            task_type="parse_props",
            prompt_template_name=prompt_template_name,
            novel_id=novel_id
        )
        if not result.get("success"):
            raise HTTPException(status_code=500, detail=result.get("error") or "解析道具失败")
        
        # 解析LLM返回的JSON
        parsed_data = json.loads(result.get("content") or "{}")
        props_data = parsed_data.get("props", [])
        
        # 处理解析结果
        created_props = []
        updated_props = []
        
        for prop_data in props_data:
            # 查找是否已存在同名道具
            existing_prop = prop_repo.get_by_name(
                novel_id=novel_id,
                name=prop_data["name"]
            )
            
            if existing_prop:
                # 更新现有道具
                updated_prop = prop_repo.update(
                    existing_prop,
                    description=prop_data.get("description", ""),
                    appearance=prop_data.get("appearance", ""),
                    start_chapter=start_chapter or existing_prop.start_chapter,
                    end_chapter=end_chapter or existing_prop.end_chapter,
                    source_range=source_range,
                    last_parsed_at=datetime.utcnow()
                )
                updated_props.append(updated_prop)
            else:
                # 创建新道具
                new_prop = prop_repo.create(
                    novel_id=novel_id,
                    name=prop_data["name"],
                    description=prop_data.get("description", ""),
                    appearance=prop_data.get("appearance", ""),
                    start_chapter=start_chapter,
                    end_chapter=end_chapter,
                    source_range=source_range
                )
                created_props.append(new_prop)
        
        # 构造响应
        message_parts = []
        if created_props:
            message_parts.append(f"新增 {len(created_props)} 个道具")
        if updated_props:
            message_parts.append(f"更新 {len(updated_props)} 个道具")
        
        return {
            "success": True,
            "data": [
                {
                    "id": p.id,
                    "name": p.name,
                    "description": p.description,
                    "appearance": p.appearance,
                    "startChapter": p.start_chapter,
                    "endChapter": p.end_chapter,
                    "isIncremental": p.is_incremental,
                    "sourceRange": p.source_range,
                    "lastParsedAt": format_datetime(p.last_parsed_at)
                }
                for p in created_props + updated_props
            ],
            "message": "，".join(message_parts) if message_parts else "未识别到道具",
            "statistics": {
                "created": len(created_props),
                "updated": len(updated_props),
                "total": len(created_props) + len(updated_props)
            }
        }
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "message": f"解析异常: {str(e)}"}


# ==================== 道具图片生成 ====================

@router.post("/{prop_id}/generate-image", response_model=dict)
async def generate_prop_image(
    prop_id: str,
    db: Session = Depends(get_db)
):
    """
    生成道具图片

    自动参考小说中的场景图和角色图生成道具图片
    只需传入道具ID，后端自动获取相关信息
    """
    from app.services.prop_image_service import PropService

    prop_service = PropService(db)
    result = prop_service.create_prop_image_task(prop_id, db)

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message"))

    return result


# ==================== 道具提示词 ====================

@router.get("/{prop_id}/prompt", response_model=dict)
async def get_prop_prompt(
    prop_id: str,
    db: Session = Depends(get_db),
    prop_repo: PropRepository = Depends(get_prop_repo),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    prompt_template_repo: PromptTemplateRepository = Depends(get_prompt_template_repo)
):
    """获取道具生成时使用的拼接后提示词"""
    prop = prop_repo.get_by_id(prop_id)
    if not prop:
        raise HTTPException(status_code=404, detail="道具不存在")

    # 获取道具所属小说
    novel = novel_repo.get_by_id(prop.novel_id)

    # 获取道具生成提示词模板
    template = None
    if novel and novel.prop_prompt_template_id:
        template = prompt_template_repo.get_by_id(novel.prop_prompt_template_id)
    if not template:
        templates = prompt_template_repo.list_by_type('prop')
        if templates:
            template = templates[0]

    # 获取风格提示词
    style, style_template = get_style(db, novel, "prop")

    # 构建提示词
    prompt = build_prop_prompt(
        name=prop.name,
        appearance=prop.appearance or "",
        description=prop.description or "",
        template=template.template if template else None,
        style=style
    )

    return {
        "success": True,
        "data": {
            "prompt": prompt,
            "templateName": template.name if template else "默认模板",
            "templateId": template.id if template else None,
            "isSystem": template.is_system if template else False,
            "template": template.template if template else None,
            "appearance": prop.appearance,
            "description": prop.description,
            "style": style,
            "styleTemplateName": style_template.name if style_template else "默认风格"
        }
    }


@router.post("/{prop_id}/generate-appearance", response_model=dict)
async def generate_prop_appearance(
    prop_id: str,
    prop_repo: PropRepository = Depends(get_prop_repo)
):
    """使用 AI 智能生成道具外观描述"""
    prop = prop_repo.get_by_id(prop_id)
    if not prop:
        raise HTTPException(status_code=404, detail="道具不存在")

    if not prop.description:
        return {
            "success": False,
            "message": "请先填写道具描述"
        }

    try:
        # 调用 LLM 生成道具外观
        appearance = await get_llm_service().generate_prop_appearance(
            prop_name=prop.name,
            description=prop.description,
            style="anime"
        )

        # 更新道具
        prop_repo.update(prop, appearance=appearance)

        return {
            "success": True,
            "data": {
                "appearance": appearance,
                "message": "道具外观生成成功"
            }
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"生成失败: {str(e)}"
        }
