from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.utils.time_utils import format_datetime
from app.models.test_case import TestCase
from app.models.novel import Novel
from app.models.novel import Chapter, Character
from app.repositories import TestCaseRepository
from app.schemas.test_case import TestCaseCreate, TestCaseUpdate
from app.constants import (
    PRESET_NAME_KEYS,
    PRESET_DESC_KEYS,
    PRESET_NOTES_KEYS,
    XIAOMA_CHAPTERS,
    XIAOMA_CHARACTERS,
    XIAOMA_TEST_CASE_CONFIG,
    XIAOMA_NOVEL_CONFIG,
    REDRIDINGHOOD_CHAPTERS,
    REDRIDINGHOOD_CHARACTERS,
    REDRIDINGHOOD_TEST_CASE_CONFIG,
    REDRIDINGHOOD_NOVEL_CONFIG,
    EMPEROR_CHAPTERS,
    EMPEROR_CHARACTERS,
    EMPEROR_TEST_CASE_CONFIG,
    EMPEROR_NOVEL_CONFIG,
)

router = APIRouter()


def get_testcase_repo(db: Session = Depends(get_db)) -> TestCaseRepository:
    """获取 TestCaseRepository 实例"""
    return TestCaseRepository(db)


@router.get("/", response_model=dict)
async def list_test_cases(
    type: Optional[str] = None,
    is_preset: Optional[bool] = None,
    testcase_repo: TestCaseRepository = Depends(get_testcase_repo)
):
    """获取测试用例列表"""
    # 使用 Repository 获取数据
    test_cases_with_details = testcase_repo.list_test_cases_with_details(
        test_type=type, 
        is_preset=is_preset
    )
    
    result = []
    for item in test_cases_with_details:
        tc = item["test_case"]
        novel = item["novel"]
        
        # 如果是预设测试用例，添加翻译键
        name_key = PRESET_NAME_KEYS.get(tc.name) if tc.is_preset else None
        desc_key = PRESET_DESC_KEYS.get(tc.description) if tc.is_preset else None
        notes_key = PRESET_NOTES_KEYS.get(tc.notes) if tc.is_preset else None
        
        result.append({
            "id": tc.id,
            "name": tc.name,
            "nameKey": name_key,
            "description": tc.description,
            "descriptionKey": desc_key,
            "type": tc.type,
            "isActive": tc.is_active,
            "isPreset": tc.is_preset,
            "novelId": tc.novel_id,
            "novelTitle": novel.title if novel else "未知",
            "chapterCount": item["chapter_count"],
            "characterCount": item["character_count"],
            "expectedCharacterCount": tc.expected_character_count,
            "expectedShotCount": tc.expected_shot_count,
            "notes": tc.notes,
            "notesKey": notes_key,
            "createdAt": format_datetime(tc.created_at),
        })
    
    return {
        "success": True,
        "data": result
    }


@router.get("/{test_case_id}", response_model=dict)
async def get_test_case(
    test_case_id: str, 
    testcase_repo: TestCaseRepository = Depends(get_testcase_repo)
):
    """获取测试用例详情"""
    data = testcase_repo.get_test_case_with_novel(test_case_id)
    if not data:
        raise HTTPException(status_code=404, detail="测试用例不存在")
    
    tc = data["test_case"]
    novel = data["novel"]
    chapters = data["chapters"]
    characters = data["characters"]
    
    return {
        "success": True,
        "data": {
            "id": tc.id,
            "name": tc.name,
            "description": tc.description,
            "type": tc.type,
            "isActive": tc.is_active,
            "isPreset": tc.is_preset,
            "expectedCharacterCount": tc.expected_character_count,
            "expectedShotCount": tc.expected_shot_count,
            "notes": tc.notes,
            "novel": {
                "id": novel.id if novel else None,
                "title": novel.title if novel else None,
                "author": novel.author if novel else None,
                "description": novel.description if novel else None,
            },
            "chapters": [
                {
                    "id": c.id,
                    "number": c.number,
                    "title": c.title,
                    "contentLength": len(c.content) if c.content else 0,
                }
                for c in chapters
            ],
            "characters": [
                {
                    "id": c.id,
                    "name": c.name,
                    "hasImage": c.image_url is not None,
                }
                for c in characters
            ],
            "createdAt": format_datetime(tc.created_at),
        }
    }


@router.post("/", response_model=dict)
async def create_test_case(
    data: TestCaseCreate,
    testcase_repo: TestCaseRepository = Depends(get_testcase_repo)
):
    """创建测试用例"""
    # 验证小说存在
    novel = testcase_repo.get_novel_by_id(data.novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    test_case = TestCase(
        name=data.name,
        description=data.description,
        novel_id=data.novel_id,
        type=data.type,
        expected_character_count=data.expected_character_count,
        expected_shot_count=data.expected_shot_count,
        notes=data.notes,
        is_preset=False,  # 用户创建的不是预设
    )
    test_case = testcase_repo.create(test_case)
    
    return {
        "success": True,
        "data": {
            "id": test_case.id,
            "name": test_case.name,
            "novelId": test_case.novel_id,
            "type": test_case.type,
        }
    }


@router.put("/{test_case_id}", response_model=dict)
async def update_test_case(
    test_case_id: str, 
    data: TestCaseUpdate,
    testcase_repo: TestCaseRepository = Depends(get_testcase_repo)
):
    """更新测试用例"""
    tc = testcase_repo.get_by_id(test_case_id)
    if not tc:
        raise HTTPException(status_code=404, detail="测试用例不存在")
    
    # 使用 Schema 更新字段
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(tc, key, value)
    
    tc = testcase_repo.update(tc)
    
    return {
        "success": True,
        "data": {
            "id": tc.id,
            "name": tc.name,
            "type": tc.type,
            "isActive": tc.is_active,
        }
    }


@router.delete("/{test_case_id}")
async def delete_test_case(
    test_case_id: str, 
    testcase_repo: TestCaseRepository = Depends(get_testcase_repo)
):
    """删除测试用例"""
    tc = testcase_repo.get_by_id(test_case_id)
    if not tc:
        raise HTTPException(status_code=404, detail="测试用例不存在")
    
    # 预设测试用例不能删除
    if tc.is_preset:
        raise HTTPException(status_code=403, detail="预设测试用例不能删除")
    
    testcase_repo.delete(tc)
    
    return {"success": True, "message": "删除成功"}


@router.post("/{test_case_id}/run")
async def run_test_case(
    test_case_id: str,
    testcase_repo: TestCaseRepository = Depends(get_testcase_repo)
):
    """运行测试用例"""
    tc = testcase_repo.get_by_id(test_case_id)
    if not tc:
        raise HTTPException(status_code=404, detail="测试用例不存在")
    
    # 根据测试类型启动不同的任务 - 使用 asyncio.create_task 实现真正并发
    if tc.type in ["full", "character"]:
        # 启动角色解析任务
        import asyncio
        asyncio.create_task(
            parse_characters_task(tc.novel_id)
        )
    
    return {
        "success": True,
        "message": f"测试用例 '{tc.name}' 已开始运行",
        "data": {
            "testCaseId": tc.id,
            "type": tc.type,
        }
    }


# 初始化预设测试用例
async def init_preset_test_cases(db: Session):
    """初始化预设测试用例"""
    from app.repositories import PromptTemplateRepository, TestCaseRepository
    
    template_repo = PromptTemplateRepository(db)
    testcase_repo = TestCaseRepository(db)
    
    # 获取默认提示词模板
    default_template = template_repo.get_first_system_template()
    
    # 检查是否已存在预设测试用例
    existing_names = testcase_repo.get_preset_names()
    
    # 创建预设测试用例配置映射
    preset_configs = [
        (XIAOMA_TEST_CASE_CONFIG["name"], _create_preset_test_case, XIAOMA_NOVEL_CONFIG, XIAOMA_CHAPTERS, XIAOMA_CHARACTERS, XIAOMA_TEST_CASE_CONFIG),
        (REDRIDINGHOOD_TEST_CASE_CONFIG["name"], _create_preset_test_case, REDRIDINGHOOD_NOVEL_CONFIG, REDRIDINGHOOD_CHAPTERS, REDRIDINGHOOD_CHARACTERS, REDRIDINGHOOD_TEST_CASE_CONFIG),
        (EMPEROR_TEST_CASE_CONFIG["name"], _create_preset_test_case, EMPEROR_NOVEL_CONFIG, EMPEROR_CHAPTERS, EMPEROR_CHARACTERS, EMPEROR_TEST_CASE_CONFIG),
    ]
    
    for name, create_func, novel_config, chapters, characters, test_case_config in preset_configs:
        if name not in existing_names:
            await create_func(db, default_template, novel_config, chapters, characters, test_case_config)


async def _create_preset_test_case(
    db: Session, 
    default_template, 
    novel_config: dict, 
    chapters: list, 
    characters: list, 
    test_case_config: dict
):
    """创建预设测试用例的通用函数"""
    # 创建小说
    novel = Novel(
        title=novel_config["title"],
        author=novel_config["author"],
        description=novel_config["description"],
        is_preset=True,
        prompt_template_id=default_template.id if default_template else None,
    )
    db.add(novel)
    db.commit()
    db.refresh(novel)
    
    # 创建章节
    for idx, ch_data in enumerate(chapters, 1):
        chapter = Chapter(
            novel_id=novel.id,
            number=idx,
            title=ch_data["title"],
            content=ch_data["content"],
        )
        db.add(chapter)
    
    novel.chapter_count = len(chapters)
    db.commit()
    
    # 创建角色
    for char_data in characters:
        character = Character(
            novel_id=novel.id,
            name=char_data["name"],
            description=char_data["description"],
            appearance=char_data["appearance"],
        )
        db.add(character)
    
    db.commit()
    
    # 创建测试用例
    test_case = TestCase(
        name=test_case_config["name"],
        description=test_case_config["description"],
        novel_id=novel.id,
        type=test_case_config["type"],
        is_preset=True,
        is_active=True,
        expected_character_count=test_case_config["expected_character_count"],
        expected_shot_count=test_case_config["expected_shot_count"],
        notes=test_case_config["notes"],
    )
    db.add(test_case)
    db.commit()
    
    print(f"[初始化] 已创建预设测试用例: {test_case.name}")


from app.services.llm_service import LLMService


def get_llm_service() -> LLMService:
    """获取 LLMService 实例（每次调用创建新实例以获取最新配置）"""
    return LLMService()


async def parse_characters_task(novel_id: str):
    """后台任务：解析小说文本提取角色"""
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        print(f"[测试任务] 开始解析小说 {novel_id} 的角色")
        
        # 获取所有章节内容
        chapters = db.query(Chapter).filter(Chapter.novel_id == novel_id).all()
        full_text = "\n\n".join([c.content for c in chapters if c.content])[:10000]
        
        # 调用 DeepSeek 解析文本
        result = await get_llm_service().parse_novel_text(full_text)
        
        if "error" in result:
            print(f"[测试任务] 解析失败: {result['error']}")
            return
        
        characters_data = result.get("characters", [])
        print(f"[测试任务] 识别到 {len(characters_data)} 个角色")
        
        # 创建角色
        for char_data in characters_data:
            name = char_data.get("name", "").strip()
            if not name:
                continue
                
            existing = db.query(Character).filter(
                Character.novel_id == novel_id,
                Character.name == name
            ).first()
            
            if not existing:
                character = Character(
                    novel_id=novel_id,
                    name=name,
                    description=char_data.get("description", ""),
                    appearance=char_data.get("appearance", ""),
                )
                db.add(character)
                print(f"[测试任务] 创建角色: {name}")
        
        db.commit()
        print(f"[测试任务] 完成！")
        
    except Exception as e:
        print(f"[测试任务] 异常: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()
