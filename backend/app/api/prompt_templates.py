from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel

from app.core.database import get_db
from app.models.prompt_template import PromptTemplate

router = APIRouter(tags=["prompt_templates"])


# 系统预设的人设提示词模板（角色生成）
SYSTEM_CHARACTER_TEMPLATES = [
    {
        "name": "标准动漫风格",
        "description": "适合大多数动漫角色的标准人设生成",
        "template": "character portrait, anime style, high quality, detailed, {appearance}, {description}, single character, centered, clean background, professional artwork, 8k",
        "type": "character"
    },
    {
        "name": "写实风格",
        "description": "写实风格的角色人设",
        "template": "character portrait, realistic style, photorealistic, highly detailed, {appearance}, {description}, single character, centered, professional photography, studio lighting, 8k",
        "type": "character"
    },
    {
        "name": "Q版卡通",
        "description": "可爱Q版卡通风格",
        "template": "chibi character, cute cartoon style, kawaii, {appearance}, {description}, single character, centered, colorful, clean background, professional artwork, 4k",
        "type": "character"
    },
    {
        "name": "水墨风格",
        "description": "中国传统水墨画风格",
        "template": "character portrait, Chinese ink painting style, traditional art, {appearance}, {description}, single character, centered, elegant, artistic, high quality",
        "type": "character"
    }
]

# 系统预设的章节拆分提示词模板
SYSTEM_CHAPTER_SPLIT_TEMPLATES = [
    {
        "name": "标准分镜拆分",
        "description": "适用于大多数小说的标准分镜拆分",
        "template": """你是一名资深影视导演、分镜设计师、动画脚本结构专家。

任务：
将用户提供的小说章节内容，拆分为适用于AI动画制作的分镜数据结构。

核心要求：

1. 严格按照影视分镜逻辑进行拆分
2. 每个分镜必须具备：
   - 明确的画面动作
   - 清晰的场景位置
   - 出现角色
   - 可视化描述（用于AI生成图像）
3. 每个分镜的剧情字数必须控制在 {每个分镜对应拆分故事字数} 左右（允许±20%浮动）
4. 所有画面视觉描述必须符合：{图像风格}
5. 不允许长段叙事，一个镜头只表达一个清晰动作或画面
6. 输出必须是纯JSON，不允许任何解释文字，不允许Markdown
7. 必须提取：
   - chapter 章节标题
   - characters 本章出现角色（去重）
   - scenes 本章出现的场景（去重）
   - shots 分镜数组

分镜规则：

- id：从1递增
- description：必须是画面级描述，带动作感，便于AI生图
- characters：当前镜头出现角色
- scene：当前镜头所在场景
- duration：根据动作复杂度自动估算时长（3-10秒）

时长规则：
- 静态画面：3-5秒
- 对话画面：5-8秒
- 动作冲突：6-10秒

禁止：
- 不得出现心理描写无法可视化内容
- 不得输出无效空镜头
- 不得改变原剧情走向

输出格式必须严格如下：

{{
    "chapter": "第3章 客人",
    "characters": [
        "萧炎",
        "萧战",
        "葛叶"
    ],
    "scenes": [
        "萧家门口",
        "萧家大厅",
        "练武场"
    ],
    "shots": [
        {{
            "id": 1,
            "description": "萧炎站在萧家门口，仰望牌匾",
            "characters": [
                "萧炎"
            ],
            "scene": "萧家门口",
            "duration": 5
        }},
        {{
            "id": 2,
            "description": "萧战从大厅走出，面带忧色",
            "characters": [
                "萧战"
            ],
            "scene": "萧家大厅",
            "duration": 8
        }}
    ]
}}""",
        "type": "chapter_split"
    },
    {
        "name": "电影风格分镜",
        "description": "电影级分镜拆分，强调画面构图和镜头语言",
        "template": """你是一名资深电影导演、分镜设计师、动画脚本结构专家。

任务：
将用户提供的小说章节内容，拆分为适用于AI动画制作的分镜数据结构，采用电影级分镜语言。

核心要求：

1. 严格按照电影分镜逻辑进行拆分
2. 每个分镜必须具备：
   - 明确的画面动作
   - 清晰的场景位置
   - 出现角色
   - 可视化描述（用于AI生成图像）
   - 镜头类型（特写、中景、全景等）
3. 每个分镜的剧情字数必须控制在 {每个分镜对应拆分故事字数} 左右（允许±20%浮动）
4. 所有画面视觉描述必须符合：{图像风格}
5. 不允许长段叙事，一个镜头只表达一个清晰动作或画面
6. 输出必须是纯JSON，不允许任何解释文字，不允许Markdown
7. 必须提取：
   - chapter 章节标题
   - characters 本章出现角色（去重）
   - scenes 本章出现的场景（去重）
   - shots 分镜数组

分镜规则：

- id：从1递增
- description：必须是画面级描述，带动作感，便于AI生图，包含镜头类型建议
- characters：当前镜头出现角色
- scene：当前镜头所在场景
- duration：根据动作复杂度自动估算时长（3-10秒）

镜头类型：
- 特写(CU)：用于表现情绪、细节
- 中景(MS)：用于对话、动作
- 全景(WS)：用于场景展示
- 远景(EWS)：用于环境交代

时长规则：
- 静态画面/特写：3-5秒
- 对话画面中景：5-8秒
- 动作全景：6-10秒
- 环境远景：4-6秒

禁止：
- 不得出现心理描写无法可视化内容
- 不得输出无效空镜头
- 不得改变原剧情走向

输出格式必须严格如下：

{{
    "chapter": "第3章 客人",
    "characters": [
        "萧炎",
        "萧战",
        "葛叶"
    ],
    "scenes": [
        "萧家门口",
        "萧家大厅",
        "练武场"
    ],
    "shots": [
        {{
            "id": 1,
            "description": "[中景] 萧炎站在萧家门口，仰望牌匾，表情复杂",
            "characters": [
                "萧炎"
            ],
            "scene": "萧家门口",
            "duration": 5
        }},
        {{
            "id": 2,
            "description": "[特写] 萧战从大厅走出，面带忧色，眉头紧锁",
            "characters": [
                "萧战"
            ],
            "scene": "萧家大厅",
            "duration": 8
        }}
    ]
}}""",
        "type": "chapter_split"
    }
]

# 合并所有系统模板
SYSTEM_PROMPT_TEMPLATES = SYSTEM_CHARACTER_TEMPLATES + SYSTEM_CHAPTER_SPLIT_TEMPLATES


def init_system_prompt_templates(db: Session):
    """初始化系统预设提示词模板"""
    # 检查是否已有系统模板
    existing = db.query(PromptTemplate).filter(PromptTemplate.is_system == True).first()
    if existing:
        # 检查是否已有章节拆分类型模板
        chapter_split = db.query(PromptTemplate).filter(
            PromptTemplate.is_system == True,
            PromptTemplate.type == "chapter_split"
        ).first()
        if chapter_split:
            return
        print("[初始化] 补充章节拆分提示词模板...")
    else:
        print("[初始化] 创建系统预设提示词模板...")
    
    # 创建系统预设模板
    for tmpl_data in SYSTEM_PROMPT_TEMPLATES:
        # 检查是否已存在同名同类型的系统模板
        existing = db.query(PromptTemplate).filter(
            PromptTemplate.name == tmpl_data["name"],
            PromptTemplate.type == tmpl_data.get("type", "character"),
            PromptTemplate.is_system == True
        ).first()
        
        if not existing:
            template = PromptTemplate(
                name=tmpl_data["name"],
                description=tmpl_data["description"],
                template=tmpl_data["template"],
                type=tmpl_data.get("type", "character"),
                is_system=True,
                is_active=True
            )
            db.add(template)
    
    db.commit()
    print("[初始化] 系统预设提示词模板创建完成")


class PromptTemplateCreate(BaseModel):
    name: str
    description: str = ""
    template: str
    type: str = "character"  # character 或 chapter_split


class PromptTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    template: Optional[str] = None
    type: Optional[str] = None


class PromptTemplateResponse(BaseModel):
    id: str
    name: str
    description: str
    template: str
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
                "description": t.description,
                "template": t.template,
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
            "description": template.description,
            "template": template.template,
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
            "description": template.description,
            "template": template.template,
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
            "description": new_template.description,
            "template": new_template.template,
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
            "description": template.description,
            "template": template.template,
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
            "description": template.description,
            "template": template.template,
            "type": template.type or "character",
            "isSystem": template.is_system,
            "isActive": template.is_active,
            "createdAt": template.created_at.isoformat() if template.created_at else None,
        }
    }
