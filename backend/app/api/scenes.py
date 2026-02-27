from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import get_settings
from app.models.novel import Scene, Chapter
from app.models.prompt_template import PromptTemplate
from app.services.comfyui import ComfyUIService
from app.services.llm_service import LLMService
from app.services.novel_service import NovelService
from app.services.prompt_builder import (
    build_scene_prompt,
    get_style
)
from app.services.file_storage import file_storage
from app.repositories import NovelRepository, SceneRepository, ChapterRepository, PromptTemplateRepository
from app.schemas.scene import SceneCreate, SceneUpdate, ParseScenesRequest
from app.utils.time_utils import format_datetime

router = APIRouter()
settings = get_settings()
comfyui_service = ComfyUIService()



def get_llm_service() -> LLMService:
    """获取 LLMService 实例（每次调用创建新实例以获取最新配置）"""
    return LLMService()


def get_novel_repo(db: Session = Depends(get_db)) -> NovelRepository:
    """获取 NovelRepository 实例"""
    return NovelRepository(db)


def get_scene_repo(db: Session = Depends(get_db)) -> SceneRepository:
    """获取 SceneRepository 实例"""
    return SceneRepository(db)


def get_chapter_repo(db: Session = Depends(get_db)) -> ChapterRepository:
    """获取 ChapterRepository 实例"""
    return ChapterRepository(db)


def get_prompt_template_repo(db: Session = Depends(get_db)) -> PromptTemplateRepository:
    """获取 PromptTemplateRepository 实例"""
    return PromptTemplateRepository(db)


@router.get("/", response_model=dict)
async def list_scenes(
    novel_id: str = None, 
    novel_repo: NovelRepository = Depends(get_novel_repo), 
    scene_repo: SceneRepository = Depends(get_scene_repo)
):
    """获取场景列表"""
    if novel_id:
        scenes = scene_repo.list_by_novel(novel_id)
    else:
        scenes = scene_repo.list_all()

    # 批量预加载小说信息，避免 N+1 查询
    novel_ids = {s.novel_id for s in scenes if s.novel_id}
    novels_map = {}
    for nid in novel_ids:
        novel = novel_repo.get_by_id(nid)
        if novel:
            novels_map[nid] = novel

    result = []
    for s in scenes:
        novel = novels_map.get(s.novel_id)
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
            "lastParsedAt": format_datetime(s.last_parsed_at),
            "createdAt": format_datetime(s.created_at),
            "updatedAt": format_datetime(s.updated_at),
        })

    return {"success": True, "data": result}


@router.get("/{scene_id}", response_model=dict)
async def get_scene(scene_id: str, novel_repo: NovelRepository = Depends(get_novel_repo), scene_repo: SceneRepository = Depends(get_scene_repo)):
    """获取场景详情"""
    scene = scene_repo.get_by_id(scene_id)
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")

    novel = novel_repo.get_by_id(scene.novel_id)

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
            "lastParsedAt": format_datetime(scene.last_parsed_at),
            "createdAt": format_datetime(scene.created_at),
            "updatedAt": format_datetime(scene.updated_at),
        }
    }


@router.post("/", response_model=dict)
async def create_scene(
        data: SceneCreate,
        novel_repo: NovelRepository = Depends(get_novel_repo),
        scene_repo: SceneRepository = Depends(get_scene_repo)
):
    """创建场景"""
    # 验证小说存在
    novel = novel_repo.get_by_id(data.novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    scene = scene_repo.create_from_schema(
        novel_id=data.novel_id,
        name=data.name,
        description=data.description or "",
        setting=data.setting or ""
    )

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
            "createdAt": format_datetime(scene.created_at),
        }
    }


@router.put("/{scene_id}", response_model=dict)
async def update_scene(
        scene_id: str,
        data: SceneUpdate,
        novel_repo: NovelRepository = Depends(get_novel_repo),
        scene_repo: SceneRepository = Depends(get_scene_repo)
):
    """更新场景"""
    scene = scene_repo.get_by_id(scene_id)
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")

    scene = scene_repo.update_from_schema(
        scene=scene,
        name=data.name,
        description=data.description,
        setting=data.setting
    )

    novel = novel_repo.get_by_id(scene.novel_id)

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
            "updatedAt": format_datetime(scene.updated_at),
        }
    }


@router.delete("/{scene_id}")
async def delete_scene(scene_id: str, scene_repo: SceneRepository = Depends(get_scene_repo)):
    """删除场景"""
    scene = scene_repo.get_by_id(scene_id)
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")

    scene_repo.delete(scene)

    return {"success": True, "message": "删除成功"}


@router.delete("/")
async def delete_scenes_by_novel(
    novel_id: str = Query(..., description="小说ID"), 
    novel_repo: NovelRepository = Depends(get_novel_repo),
    scene_repo: SceneRepository = Depends(get_scene_repo)
):
    """删除指定小说的所有场景"""
    # 检查小说是否存在
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    # 删除该小说的所有场景
    result = scene_repo.delete_by_novel(novel_id)

    # 删除场景图片目录
    file_storage.delete_scenes_dir(novel_id)

    return {"success": True, "message": f"已删除 {result} 个场景", "deleted_count": result}


@router.post("/clear-scenes-dir")
async def clear_scenes_dir(novel_id: str = Query(..., description="小说ID"), novel_repo: NovelRepository = Depends(get_novel_repo)):
    """清空小说的场景图片目录（用于批量重新生成前）"""
    # 检查小说是否存在
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    # 清空场景图片目录
    success = file_storage.delete_scenes_dir(novel_id)

    if success:
        return {"success": True, "message": "场景图片目录已清空"}
    else:
        raise HTTPException(status_code=500, detail="清空场景图片目录失败")


@router.get("/{scene_id}/prompt", response_model=dict)
async def get_scene_prompt(
    scene_id: str,
    db: Session = Depends(get_db),
    novel_repo: NovelRepository = Depends(get_novel_repo),
    scene_repo: SceneRepository = Depends(get_scene_repo),
    prompt_template_repo: PromptTemplateRepository = Depends(get_prompt_template_repo)
):
    """获取场景生成时使用的拼接后提示词"""
    scene = scene_repo.get_by_id(scene_id)
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")

    # 获取场景所属小说
    novel = novel_repo.get_by_id(scene.novel_id)

    # 获取场景生成提示词模板
    template = None
    if novel and novel.scene_prompt_template_id:
        template = prompt_template_repo.get_by_id(novel.scene_prompt_template_id)
    if not template:
        templates = prompt_template_repo.list_by_type('scene')
        if templates:
            template = templates[0]

    # 获取风格提示词
    style, style_template = get_style(db, novel, "scene")

    # 构建提示词（只使用 setting 字段，传入 style）
    prompt = build_scene_prompt(
        name=scene.name,
        setting=scene.setting,
        description="",  # 不使用 description
        template=template.template if template else None,
        style=style  # 传入风格模板
    )

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
            "style": style,
            "styleTemplateName": style_template.name if style_template else "默认风格"
        }
    }


@router.post("/{scene_id}/generate-setting", response_model=dict)
async def generate_scene_setting(
        scene_id: str,
        scene_repo: SceneRepository = Depends(get_scene_repo)
):
    """使用 AI 智能生成场景设定（环境设置）"""
    scene = scene_repo.get_by_id(scene_id)
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
        scene_repo.update_setting(scene, setting)

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


# build_scene_prompt 函数已移至 app/services/prompt_builder.py
# 已从 prompt_builder 导入 build_scene_prompt


@router.post("/parse-scenes")
async def parse_scenes(
        data: ParseScenesRequest,
        db: Session = Depends(get_db),
        novel_repo: NovelRepository = Depends(get_novel_repo),
        scene_repo: SceneRepository = Depends(get_scene_repo),
        chapter_repo: ChapterRepository = Depends(get_chapter_repo),
        prompt_template_repo: PromptTemplateRepository = Depends(get_prompt_template_repo)
):
    """
    解析场景（支持选定章节范围和单章节增量生成）
    
    API层只负责：参数校验、调用Service、格式化响应
    """
    novel_id = data.novel_id
    chapter_ids = data.chapter_ids
    mode = data.mode

    if not novel_id:
        raise HTTPException(status_code=400, detail="缺少 novel_id")

    # 获取小说
    novel = novel_repo.get_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    # 获取章节
    if chapter_ids:
        chapters = chapter_repo.list_by_ids(novel_id, chapter_ids)
    else:
        chapters = chapter_repo.list_by_novel(novel_id)

    if not chapters:
        raise HTTPException(status_code=400, detail="没有找到章节")

    # 调用服务层处理业务逻辑
    novel_service = NovelService(db)
    return await novel_service.parse_scenes_from_chapters(
        novel_id=novel_id,
        chapters=chapters,
        mode=mode,
        scene_repo=scene_repo,
        prompt_template_repo=prompt_template_repo
    )


@router.post("/{scene_id}/upload-image", response_model=dict)
async def upload_scene_image(
    scene_id: str,
    file: UploadFile = File(...),
    scene_repo: SceneRepository = Depends(get_scene_repo),
    novel_repo: NovelRepository = Depends(get_novel_repo)
):
    """
    上传场景图片
    
    支持用户从本地上传场景图片，替代AI生成
    """
    scene = scene_repo.get_by_id(scene_id)
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")
    
    # 验证文件类型
    allowed_types = ["image/png", "image/jpeg", "image/jpg", "image/webp"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400, 
            detail=f"不支持的文件类型: {file.content_type}，仅支持 PNG, JPG, WEBP"
        )
    
    try:
        # 获取保存路径
        file_path = file_storage.get_scene_image_path(
            novel_id=scene.novel_id,
            scene_name=scene.name
        )
        
        # 保存文件
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)
        
        # 计算访问URL
        relative_path = file_path.relative_to(file_storage.base_dir)
        image_url = f"/api/files/{relative_path}"
        
        # 更新场景记录
        scene_repo.update_image(scene, image_url)
        
        novel = novel_repo.get_by_id(scene.novel_id)
        
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
                "novelName": novel.title if novel else None,
                "updatedAt": scene.updated_at.isoformat() if scene.updated_at else None,
            },
            "message": "图片上传成功"
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")
