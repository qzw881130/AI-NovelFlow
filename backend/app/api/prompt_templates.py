import os
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel

from app.core.database import get_db
from app.models.prompt_template import PromptTemplate

router = APIRouter(tags=["prompt_templates"])

# 模板文件目录 (位于 backend/prompt_templates/)
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'prompt_templates')

def load_template(filename: str) -> str:
    """从文件加载模板内容"""
    filepath = os.path.join(TEMPLATES_DIR, filename)
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        raise FileNotFoundError(f"Template file not found: {filepath}")


# 系统预设的人设提示词模板（角色生成）
SYSTEM_CHARACTER_TEMPLATES = [
    {
        "name": "标准动漫风格",
        "description": "适合大多数动漫角色的标准人设生成",
        "template": load_template("standard_anime.txt"),
        "style": "anime style, high quality, detailed, professional artwork",
        "type": "character"
    },
    {
        "name": "写实风格",
        "description": "写实风格的角色人设",
        "template": load_template("realistic.txt"),
        "style": "realistic style, photorealistic, highly detailed, professional photography",
        "type": "character"
    },
    {
        "name": "Q版卡通",
        "description": "可爱Q版卡通风格",
        "template": load_template("chibi_cartoon.txt"),
        "style": "chibi character, cute cartoon style, kawaii, colorful",
        "type": "character"
    },
    {
        "name": "水墨风格",
        "description": "中国传统水墨画风格",
        "template": load_template("ink_painting.txt"),
        "style": "Chinese ink painting style, traditional art, elegant, artistic",
        "type": "character"
    }
]

# 系统预设的章节拆分提示词模板
SYSTEM_CHAPTER_SPLIT_TEMPLATES = [
    {
        "name": "标准分镜拆分",
        "description": "适用于大多数小说的标准分镜拆分",
        "template": load_template("standard_chapter_split.txt"),
        "type": "chapter_split"
    },
    {
        "name": "电影风格分镜",
        "description": "电影级分镜拆分，强调画面构图和镜头语言",
        "template": load_template("cinema_style.txt"),
        "type": "chapter_split"
    }
]

# 系统预设的场景解析提示词模板
SYSTEM_SCENE_TEMPLATES = [
    {
        "name": "标准场景解析",
        "description": "适用于大多数小说的场景解析",
        "template": load_template("scene_parse.txt"),
        "type": "scene_parse"
    }
]

# 系统预设的场景图生成提示词模板
SYSTEM_SCENE_IMAGE_TEMPLATES = [
    {
        "name": "标准场景图",
        "description": "适用于大多数场景的标准图生成",
        "template": load_template("scene.txt"),
        "style": "anime style, high quality, detailed, professional artwork",
        "type": "scene"
    }
]

# 合并所有系统模板
SYSTEM_PROMPT_TEMPLATES = SYSTEM_CHARACTER_TEMPLATES + SYSTEM_CHAPTER_SPLIT_TEMPLATES + SYSTEM_SCENE_TEMPLATES + SYSTEM_SCENE_IMAGE_TEMPLATES


def get_template_name_key(name: str) -> str:
    """获取模板名称的翻译键"""
    return f"promptConfig.templateNames.{name}"


def get_template_description_key(name: str) -> str:
    """获取模板描述的翻译键"""
    return f"promptConfig.templateDescriptions.{name}"


def init_system_prompt_templates(db: Session):
    """初始化系统预设提示词模板"""
    print("[初始化] 更新系统预设提示词模板...")
    
    # 创建或更新系统预设模板
    for tmpl_data in SYSTEM_PROMPT_TEMPLATES:
        # 检查是否已存在同名同类型的系统模板
        existing = db.query(PromptTemplate).filter(
            PromptTemplate.name == tmpl_data["name"],
            PromptTemplate.type == tmpl_data.get("type", "character"),
            PromptTemplate.is_system == True
        ).first()
        
        if existing:
            # 更新现有模板内容
            existing.description = tmpl_data["description"]
            existing.template = tmpl_data["template"]
            # 更新 style 字段（如果模板数据中有定义）
            if "style" in tmpl_data:
                existing.style = tmpl_data["style"]
        else:
            # 创建新模板
            template = PromptTemplate(
                name=tmpl_data["name"],
                description=tmpl_data["description"],
                template=tmpl_data["template"],
                style=tmpl_data.get("style", ""),  # 保存 style 字段
                type=tmpl_data.get("type", "character"),
                is_system=True,
                is_active=True
            )
            db.add(template)
    
    db.commit()
    print("[初始化] 系统预设提示词模板更新完成")


class PromptTemplateCreate(BaseModel):
    name: str
    description: str = ""
    template: str
    style: str = ""  # 风格提示词
    type: str = "character"  # character 或 chapter_split


class PromptTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    template: Optional[str] = None
    style: Optional[str] = None
    type: Optional[str] = None


class PromptTemplateResponse(BaseModel):
    id: str
    name: str
    description: str
    template: str
    style: str
    type: str
    isSystem: bool
    isActive: bool
    createdAt: str
    
    class Config:
        from_attributes = True


@router.get("/", response_model=dict)
def list_prompt_templates(
    type: Optional[str] = Query(None, description="筛选类型: character 或 chapter_split"),
    db: Session = Depends(get_db)
):
    """获取所有提示词模板"""
    query = db.query(PromptTemplate)
    
    if type:
        query = query.filter(PromptTemplate.type == type)
    
    templates = query.order_by(
        PromptTemplate.is_system.desc(),
        PromptTemplate.created_at.desc()
    ).all()
    
    return {
        "success": True,
        "data": [
            {
                "id": t.id,
                "name": t.name,
                "nameKey": get_template_name_key(t.name) if t.is_system else None,
                "description": t.description,
                "descriptionKey": get_template_description_key(t.name) if t.is_system else None,
                "template": t.template,
                "style": t.style or "",
                "type": t.type or "character",
                "isSystem": t.is_system,
                "isActive": t.is_active,
                "createdAt": t.created_at.isoformat() if t.created_at else None,
            }
            for t in templates
        ]
    }


@router.get("/{template_id}", response_model=dict)
def get_prompt_template(template_id: str, db: Session = Depends(get_db)):
    """获取单个提示词模板"""
    template = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="提示词模板不存在")
    
    return {
        "success": True,
        "data": {
            "id": template.id,
            "name": template.name,
            "nameKey": get_template_name_key(template.name) if template.is_system else None,
            "description": template.description,
            "descriptionKey": get_template_description_key(template.name) if template.is_system else None,
            "template": template.template,
            "style": template.style or "",
            "type": template.type or "character",
            "isSystem": template.is_system,
            "isActive": template.is_active,
            "createdAt": template.created_at.isoformat() if template.created_at else None,
        }
    }


@router.post("/", response_model=dict)
def create_prompt_template(data: PromptTemplateCreate, db: Session = Depends(get_db)):
    """创建用户自定义提示词模板"""
    template = PromptTemplate(
        name=data.name,
        description=data.description,
        template=data.template,
        style=data.style,
        type=data.type,
        is_system=False,  # 用户创建的默认为非系统
        is_active=True
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    
    return {
        "success": True,
        "message": "提示词模板创建成功",
        "data": {
            "id": template.id,
            "name": template.name,
            "nameKey": get_template_name_key(template.name) if template.is_system else None,
            "description": template.description,
            "descriptionKey": get_template_description_key(template.name) if template.is_system else None,
            "template": template.template,
            "style": template.style or "",
            "type": template.type or "character",
            "isSystem": template.is_system,
            "isActive": template.is_active,
            "createdAt": template.created_at.isoformat() if template.created_at else None,
        }
    }


@router.post("/{template_id}/copy", response_model=dict)
def copy_prompt_template(template_id: str, db: Session = Depends(get_db)):
    """复制系统提示词模板为用户自定义模板"""
    source = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="源提示词模板不存在")
    
    # 创建副本
    new_template = PromptTemplate(
        name=f"{source.name} (副本)",
        description=source.description,
        template=source.template,
        style=source.style or "",  # 复制 style 字段
        type=source.type or "character",
        is_system=False,  # 复制出来的为用户类型
        is_active=True
    )
    db.add(new_template)
    db.commit()
    db.refresh(new_template)
    
    return {
        "success": True,
        "message": "提示词模板复制成功",
        "data": {
            "id": new_template.id,
            "name": new_template.name,
            "nameKey": get_template_name_key(new_template.name) if new_template.is_system else None,
            "description": new_template.description,
            "descriptionKey": get_template_description_key(new_template.name) if new_template.is_system else None,
            "template": new_template.template,
            "style": new_template.style or "",
            "type": new_template.type or "character",
            "isSystem": new_template.is_system,
            "isActive": new_template.is_active,
            "createdAt": new_template.created_at.isoformat() if new_template.created_at else None,
        }
    }


@router.put("/{template_id}", response_model=dict)
def update_prompt_template(
    template_id: str, 
    data: PromptTemplateUpdate, 
    db: Session = Depends(get_db)
):
    """更新提示词模板（仅用户自定义可编辑）"""
    template = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="提示词模板不存在")
    
    if template.is_system:
        raise HTTPException(status_code=403, detail="系统预设提示词不可编辑")
    
    if data.name is not None:
        template.name = data.name
    if data.description is not None:
        template.description = data.description
    if data.template is not None:
        template.template = data.template
    if data.style is not None:
        template.style = data.style
    if data.type is not None:
        template.type = data.type
    
    db.commit()
    db.refresh(template)
    
    return {
        "success": True,
        "message": "提示词模板更新成功",
        "data": {
            "id": template.id,
            "name": template.name,
            "nameKey": get_template_name_key(template.name) if template.is_system else None,
            "description": template.description,
            "descriptionKey": get_template_description_key(template.name) if template.is_system else None,
            "template": template.template,
            "style": template.style or "",
            "type": template.type or "character",
            "isSystem": template.is_system,
            "isActive": template.is_active,
            "createdAt": template.created_at.isoformat() if template.created_at else None,
        }
    }


@router.delete("/{template_id}", response_model=dict)
def delete_prompt_template(template_id: str, db: Session = Depends(get_db)):
    """删除提示词模板（仅用户自定义可删除）"""
    template = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="提示词模板不存在")
    
    if template.is_system:
        raise HTTPException(status_code=403, detail="系统预设提示词不可删除")
    
    db.delete(template)
    db.commit()
    
    return {"success": True, "message": "提示词模板删除成功"}


@router.get("/system/default", response_model=dict)
def get_default_system_template(
    type: Optional[str] = Query("character", description="模板类型: character 或 chapter_split"),
    db: Session = Depends(get_db)
):
    """获取默认的系统提示词模板"""
    template = db.query(PromptTemplate).filter(
        PromptTemplate.is_system == True,
        PromptTemplate.type == type
    ).order_by(PromptTemplate.created_at.asc()).first()
    
    if not template:
        raise HTTPException(status_code=404, detail="未找到系统提示词模板")
    
    return {
        "success": True,
        "data": {
            "id": template.id,
            "name": template.name,
            "nameKey": get_template_name_key(template.name) if template.is_system else None,
            "description": template.description,
            "descriptionKey": get_template_description_key(template.name) if template.is_system else None,
            "template": template.template,
            "style": template.style or "",
            "type": template.type or "character",
            "isSystem": template.is_system,
            "isActive": template.is_active,
            "createdAt": template.created_at.isoformat() if template.created_at else None,
        }
    }
