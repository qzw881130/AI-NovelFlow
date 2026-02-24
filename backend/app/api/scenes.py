from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
import json
from datetime import datetime

from app.core.database import get_db
from app.core.config import get_settings
from app.models.novel import Scene, Novel, Chapter
from app.models.prompt_template import PromptTemplate
from app.services.comfyui import ComfyUIService
from app.services.llm_service import LLMService

router = APIRouter()
settings = get_settings()
comfyui_service = ComfyUIService()


def extract_style_from_character_template(template: str) -> str:
    """从角色提示词模板中提取 style
    
    兼容逻辑：
    1. 尝试解析为 JSON，获取 style 字段
    2. 否则清理模板中的 {appearance} 和 {description} 占位符
    """
    if not template:
        return "anime style, high quality, detailed"

    # 尝试解析 JSON
    try:
        template_data = json.loads(template)
        if isinstance(template_data, dict) and "style" in template_data:
            return template_data["style"]
    except:
        pass

    # 清理占位符和角色相关内容
    style = (template.replace("{appearance}", "").replace("{description}", "")
             .replace("character portrait", "")
             .replace("single character", "")
             .replace("centered", "")
             .replace("colorful", "")
             .replace("clean background", "")
             .strip(", ").strip(","))
    
    # 清理多余的逗号和空格
    style = " ".join(style.split())  # 合并多余空格
    style = style.replace(", ,", ",").replace(",,", ",")  # 清理连续逗号
    style = style.strip(", ")  # 再次清理首尾
    
    if style:
        return style

    return "anime style, high quality, detailed"


def get_llm_service() -> LLMService:
    """获取 LLMService 实例（每次调用创建新实例以获取最新配置）"""
    return LLMService()


@router.get("/", response_model=dict)
async def list_scenes(novel_id: str = None, db: Session = Depends(get_db)):
    """获取场景列表"""
    query = db.query(Scene)
    if novel_id:
        query = query.filter(Scene.novel_id == novel_id)
    scenes = query.order_by(Scene.created_at.desc()).all()

    result = []
    for s in scenes:
        novel = db.query(Novel).filter(Novel.id == s.novel_id).first()
        result.append({
            "id": s.id,
            "novelId": s.novel_id,
            "name": s.name,
            "description": s.description,
            "setting": s.setting,
            "imageUrl": s.image_url,
            "generatingStatus": s.generating_status,
            "sceneTaskId": s.scene_task_id,
            "novelName": novel.title if novel else None,
            "startChapter": s.start_chapter,
            "endChapter": s.end_chapter,
            "isIncremental": s.is_incremental,
            "sourceRange": s.source_range,
            "lastParsedAt": s.last_parsed_at.isoformat() if s.last_parsed_at else None,
            "createdAt": s.created_at.isoformat() if s.created_at else None,
            "updatedAt": s.updated_at.isoformat() if s.updated_at else None,
        })

    return {"success": True, "data": result}


@router.get("/{scene_id}", response_model=dict)
async def get_scene(scene_id: str, db: Session = Depends(get_db)):
    """获取场景详情"""
    scene = db.query(Scene).filter(Scene.id == scene_id).first()
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")

    novel = db.query(Novel).filter(Novel.id == scene.novel_id).first()

    return {
        "success": True,
        "data": {
            "id": scene.id,
            "novelId": scene.novel_id,
            "name": scene.name,
            "description": scene.description,
            "setting": scene.setting,
            "imageUrl": scene.image_url,
            "generatingStatus": scene.generating_status,
            "sceneTaskId": scene.scene_task_id,
            "novelName": novel.title if novel else None,
            "startChapter": scene.start_chapter,
            "endChapter": scene.end_chapter,
            "isIncremental": scene.is_incremental,
            "sourceRange": scene.source_range,
            "lastParsedAt": scene.last_parsed_at.isoformat() if scene.last_parsed_at else None,
            "createdAt": scene.created_at.isoformat() if scene.created_at else None,
            "updatedAt": scene.updated_at.isoformat() if scene.updated_at else None,
        }
    }


@router.post("/", response_model=dict)
async def create_scene(
        data: dict,
        db: Session = Depends(get_db)
):
    """创建场景"""
    # 验证小说存在
    novel = db.query(Novel).filter(Novel.id == data.get('novelId')).first()
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    scene = Scene(
        novel_id=data.get('novelId'),
        name=data.get('name'),
        description=data.get('description', ''),
        setting=data.get('setting', ''),
    )
    db.add(scene)
    db.commit()
    db.refresh(scene)

    return {
        "success": True,
        "data": {
            "id": scene.id,
            "novelId": scene.novel_id,
            "name": scene.name,
            "description": scene.description,
            "setting": scene.setting,
            "imageUrl": scene.image_url,
            "novelName": novel.title,
            "createdAt": scene.created_at.isoformat() if scene.created_at else None,
        }
    }


@router.put("/{scene_id}", response_model=dict)
async def update_scene(
        scene_id: str,
        data: dict,
        db: Session = Depends(get_db)
):
    """更新场景"""
    scene = db.query(Scene).filter(Scene.id == scene_id).first()
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")

    if 'name' in data:
        scene.name = data['name']
    if 'description' in data:
        scene.description = data['description']
    if 'setting' in data:
        scene.setting = data['setting']

    db.commit()
    db.refresh(scene)

    novel = db.query(Novel).filter(Novel.id == scene.novel_id).first()

    return {
        "success": True,
        "data": {
            "id": scene.id,
            "novelId": scene.novel_id,
            "name": scene.name,
            "description": scene.description,
            "setting": scene.setting,
            "imageUrl": scene.image_url,
            "novelName": novel.title if novel else None,
            "updatedAt": scene.updated_at.isoformat() if scene.updated_at else None,
        }
    }


@router.delete("/{scene_id}")
async def delete_scene(scene_id: str, db: Session = Depends(get_db)):
    """删除场景"""
    scene = db.query(Scene).filter(Scene.id == scene_id).first()
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")

    db.delete(scene)
    db.commit()

    return {"success": True, "message": "删除成功"}


@router.delete("/")
async def delete_scenes_by_novel(novel_id: str = Query(..., description="小说ID"), db: Session = Depends(get_db)):
    """删除指定小说的所有场景"""
    # 检查小说是否存在
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    # 删除该小说的所有场景
    result = db.query(Scene).filter(Scene.novel_id == novel_id).delete()
    db.commit()

    # 删除场景图片目录
    from app.services.file_storage import file_storage
    file_storage.delete_scenes_dir(novel_id)

    return {"success": True, "message": f"已删除 {result} 个场景", "deleted_count": result}


@router.post("/clear-scenes-dir")
async def clear_scenes_dir(novel_id: str = Query(..., description="小说ID"), db: Session = Depends(get_db)):
    """清空小说的场景图片目录（用于批量重新生成前）"""
    # 检查小说是否存在
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    # 清空场景图片目录
    from app.services.file_storage import file_storage
    success = file_storage.delete_scenes_dir(novel_id)

    if success:
        return {"success": True, "message": "场景图片目录已清空"}
    else:
        raise HTTPException(status_code=500, detail="清空场景图片目录失败")


@router.get("/{scene_id}/prompt", response_model=dict)
async def get_scene_prompt(scene_id: str, db: Session = Depends(get_db)):
    """获取场景生成时使用的拼接后提示词"""
    scene = db.query(Scene).filter(Scene.id == scene_id).first()
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")

    # 获取场景所属小说
    novel = db.query(Novel).filter(Novel.id == scene.novel_id).first()

    # 获取场景提示词模板（类型为 'scene'）
    template = None
    if novel:
        template = db.query(PromptTemplate).filter(
            PromptTemplate.type == 'scene',
            PromptTemplate.is_system == True
        ).order_by(PromptTemplate.created_at.asc()).first()

    # 获取角色提示词模板（用于提取 style）
    character_template = None
    if novel and novel.prompt_template_id:
        character_template = db.query(PromptTemplate).filter(
            PromptTemplate.id == novel.prompt_template_id
        ).first()

    # 如果没有指定模板，使用默认系统模板
    if not character_template:
        character_template = db.query(PromptTemplate).filter(
            PromptTemplate.is_system == True,
            PromptTemplate.type == "character"
        ).order_by(PromptTemplate.created_at.asc()).first()

    # 获取 style（从模板的 style 字段）
    style = "anime style, high quality, detailed, environment"
    if character_template and character_template.style:
        style = character_template.style
    elif character_template:
        # 兼容旧模板：从角色模板内容中提取 style
        style = extract_style_from_character_template(character_template.template if character_template else None)

    # 构建提示词（只使用 setting 字段）
    prompt = build_scene_prompt(
        name=scene.name,
        setting=scene.setting,
        description="",  # 不使用 description
        template=template.template if template else None
    )

    # 替换 ##STYLE## 占位符
    if "##STYLE##" in prompt:
        prompt = prompt.replace("##STYLE##", style)

    return {
        "success": True,
        "data": {
            "prompt": prompt,
            "templateName": template.name if template else "默认模板",
            "templateId": template.id if template else None,
            "isSystem": template.is_system if template else False,
            "template": template.template if template else None,
            "setting": scene.setting,
            "description": scene.description,
            "style": style
        }
    }


@router.post("/{scene_id}/generate-setting", response_model=dict)
async def generate_scene_setting(
        scene_id: str,
        db: Session = Depends(get_db)
):
    """使用 AI 智能生成场景设定（环境设置）"""
    scene = db.query(Scene).filter(Scene.id == scene_id).first()
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")

    if not scene.description:
        return {
            "success": False,
            "message": "请先填写场景描述"
        }

    try:
        # 调用 LLM 生成场景设定
        setting = await get_llm_service().generate_scene_setting(
            scene_name=scene.name,
            description=scene.description,
            style="anime"
        )

        # 更新场景
        scene.setting = setting
        db.commit()

        return {
            "success": True,
            "data": {
                "setting": setting,
                "message": "场景设定生成成功"
            }
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"生成失败: {str(e)}"
        }


def build_scene_prompt(name: str, setting: str, description: str, template: str = None) -> str:
    """构建场景图提示词
    
    Args:
        name: 场景名称
        setting: 环境设置/布景描述（用于生成场景图）
        description: 场景描述（不使用，保留参数兼容性）
        template: 提示词模板
    
    Note:
        场景图生成只使用 setting 字段，不使用 description 字段
        因为分镜生成时会参考角色图+场景图，场景设定应该是纯环境描述
    """
    if template:
        # 使用模板构建提示词，只使用 setting，忽略 description
        prompt = template.replace("{setting}", setting or "").replace("{description}", "").replace("{name}", name or "")
        # 清理多余的逗号和空格
        prompt = " ".join(prompt.split())
        prompt = prompt.replace(" ,", ",").replace(",,", ",").strip(", ")
        return prompt

    # 默认提示词 - 只使用 setting 字段
    base_prompt = "environment design, background art, landscape, "

    if name:
        base_prompt += f"{name}, "

    if setting:
        base_prompt += setting + ", "

    # 不再使用 description 字段
    base_prompt += "high quality, detailed, no characters, professional artwork"

    return base_prompt


@router.post("/parse-scenes")
async def parse_scenes(
        data: dict,
        db: Session = Depends(get_db)
):
    """
    解析场景（支持选定章节范围和单章节增量生成）
    
    Request Body:
    {
        "novel_id": "xxx",
        "chapter_ids": ["id1", "id2"],  # 可选，不传则解析所有章节
        "mode": "incremental" | "full"  # 可选，默认 incremental
    }
    """
    novel_id = data.get("novel_id")
    chapter_ids = data.get("chapter_ids", [])
    mode = data.get("mode", "incremental")  # incremental 或 full

    if not novel_id:
        raise HTTPException(status_code=400, detail="缺少 novel_id")

    # 获取小说
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    # 获取章节
    if chapter_ids:
        chapters = db.query(Chapter).filter(
            Chapter.novel_id == novel_id,
            Chapter.id.in_(chapter_ids)
        ).order_by(Chapter.number).all()
    else:
        chapters = db.query(Chapter).filter(
            Chapter.novel_id == novel_id
        ).order_by(Chapter.number).all()

    if not chapters:
        raise HTTPException(status_code=400, detail="没有找到章节")

    # 构建章节范围说明
    if len(chapters) == 1:
        source_range = f"第{chapters[0].number}章"
    else:
        source_range = f"第{chapters[0].number}章 ~ 第{chapters[-1].number}章"

    # 合并章节内容
    combined_content = ""
    for chapter in chapters:
        combined_content += f"\n\n【第{chapter.number}章 {chapter.title}】\n{chapter.content or ''}"

    # 获取场景解析提示词模板
    template = db.query(PromptTemplate).filter(
        PromptTemplate.type == 'scene_parse',
        PromptTemplate.is_system == True
    ).order_by(PromptTemplate.created_at.asc()).first()

    prompt_template = template.template if template else None

    try:
        # 调用 LLM 解析场景
        result = await get_llm_service().parse_scenes(
            novel_id=novel_id,
            chapter_content=combined_content[:150000],  # 限制长度
            chapter_title=source_range,
            prompt_template=prompt_template
        )

        if result.get("error"):
            return {"success": False, "message": result["error"]}

        scenes_data = result.get("scenes", [])

        # 获取现有场景
        existing_scenes = db.query(Scene).filter(Scene.novel_id == novel_id).all()
        existing_scene_names = {s.name: s for s in existing_scenes}

        created_scenes = []
        updated_scenes = []

        for scene_data in scenes_data:
            name = scene_data.get("name", "")
            if not name:
                continue

            if name in existing_scene_names:
                # 更新现有场景
                existing = existing_scene_names[name]
                existing.description = scene_data.get("description", existing.description)
                existing.setting = scene_data.get("setting", existing.setting)

                # 更新章节范围
                if mode == "incremental":
                    if existing.start_chapter:
                        existing.start_chapter = min(existing.start_chapter, chapters[0].number)
                    else:
                        existing.start_chapter = chapters[0].number
                    if existing.end_chapter:
                        existing.end_chapter = max(existing.end_chapter, chapters[-1].number)
                    else:
                        existing.end_chapter = chapters[-1].number

                existing.is_incremental = mode == "incremental"
                existing.source_range = source_range
                existing.last_parsed_at = datetime.utcnow()
                updated_scenes.append(existing)
            else:
                # 创建新场景
                scene = Scene(
                    novel_id=novel_id,
                    name=name,
                    description=scene_data.get("description", ""),
                    setting=scene_data.get("setting", ""),
                    start_chapter=chapters[0].number,
                    end_chapter=chapters[-1].number,
                    is_incremental=mode == "incremental",
                    source_range=source_range,
                    last_parsed_at=datetime.utcnow()
                )
                db.add(scene)
                created_scenes.append(scene)

        db.commit()

        # 刷新对象
        for s in created_scenes + updated_scenes:
            db.refresh(s)

        # 构造响应
        message_parts = []
        if created_scenes:
            message_parts.append(f"新增 {len(created_scenes)} 个场景")
        if updated_scenes:
            message_parts.append(f"更新 {len(updated_scenes)} 个场景")

        return {
            "success": True,
            "data": [
                {
                    "id": s.id,
                    "name": s.name,
                    "description": s.description,
                    "setting": s.setting,
                    "startChapter": s.start_chapter,
                    "endChapter": s.end_chapter,
                    "isIncremental": s.is_incremental,
                    "sourceRange": s.source_range,
                    "lastParsedAt": s.last_parsed_at.isoformat() if s.last_parsed_at else None
                }
                for s in created_scenes + updated_scenes
            ],
            "message": "，".join(message_parts) if message_parts else "未识别到场景",
            "statistics": {
                "created": len(created_scenes),
                "updated": len(updated_scenes),
                "total": len(created_scenes) + len(updated_scenes)
            }
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "message": f"解析异常: {str(e)}"}
