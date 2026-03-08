"""
测试配置和共享 fixtures
"""
import os
import sys
import pytest
import tempfile
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.core.database import Base, get_db
from app.main import app
from app.api.deps import (
    get_novel_repo,
    get_chapter_repo,
    get_character_repo,
    get_scene_repo,
    get_prop_repo,
    get_task_repo,
    get_workflow_repo,
    get_shot_repo,
)
from app.repositories import (
    NovelRepository,
    ChapterRepository,
    CharacterRepository,
    SceneRepository,
    PropRepository,
    TaskRepository,
    WorkflowRepository,
    ShotRepository,
)

# 显式导入所有模型，确保 Base.metadata 包含所有表
from app.models.novel import Novel, Chapter, Character, Scene, Prop
from app.models.shot import Shot
from app.models.task import Task
from app.models.workflow import Workflow
from app.models.prompt_template import PromptTemplate
from app.models.test_case import TestCase
from app.models.system_config import SystemConfig


# 使用内存数据库进行测试
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="function")
def db_engine():
    """创建测试数据库引擎"""
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        connect_args={"check_same_thread": False}
    )
    # 创建所有表
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def db_session(db_engine):
    """创建测试数据库会话"""
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function")
def client(db_session, db_engine):
    """创建测试客户端"""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    
    # 覆盖 get_db 依赖
    app.dependency_overrides[get_db] = override_get_db
    
    # 创建 Repository 工厂函数
    def make_repo_factory(repo_class):
        def factory():
            return repo_class(db_session)
        return factory
    
    # 覆盖所有 Repository 依赖
    app.dependency_overrides[get_novel_repo] = make_repo_factory(NovelRepository)
    app.dependency_overrides[get_chapter_repo] = make_repo_factory(ChapterRepository)
    app.dependency_overrides[get_character_repo] = make_repo_factory(CharacterRepository)
    app.dependency_overrides[get_scene_repo] = make_repo_factory(SceneRepository)
    app.dependency_overrides[get_prop_repo] = make_repo_factory(PropRepository)
    app.dependency_overrides[get_task_repo] = make_repo_factory(TaskRepository)
    app.dependency_overrides[get_workflow_repo] = make_repo_factory(WorkflowRepository)
    app.dependency_overrides[get_shot_repo] = make_repo_factory(ShotRepository)
    
    # Mock lifespan 中的启动逻辑，避免连接真实数据库和 ComfyUI
    from app.main import lifespan
    
    async def mock_lifespan(app):
        # 使用测试数据库初始化数据
        from app.api.test_cases import init_preset_test_cases
        from app.api.prompt_templates import init_system_prompt_templates
        from app.api.config import init_system_config
        
        # 使用测试 session
        init_system_config(db_session)
        init_system_prompt_templates(db_session)
        await init_preset_test_cases(db_session)
        
        # Mock ComfyUI 监控器
        mock_monitor = MagicMock()
        mock_monitor.start = AsyncMock()
        mock_monitor.stop = AsyncMock()
        
        yield
    
    # 使用 patch 来 mock lifespan 中的依赖
    with patch('app.main.init_monitor', return_value=MagicMock(start=AsyncMock(), stop=AsyncMock())):
        with patch('app.core.database.SessionLocal', return_value=db_session):
            with TestClient(app) as c:
                yield c
    
    app.dependency_overrides.clear()


@pytest.fixture
def sample_novel_data():
    """示例小说数据"""
    return {
        "title": "测试小说",
        "author": "测试作者",
        "description": "这是一个测试小说"
    }


@pytest.fixture
def sample_chapter_data():
    """示例章节数据"""
    return {
        "number": 1,
        "title": "第一章 测试章节",
        "content": "这是测试章节的内容。主角小明走进房间，看到了小红。"
    }


@pytest.fixture
def sample_parsed_data():
    """示例解析后的章节数据"""
    return {
        "characters": ["小明", "小红"],
        "scenes": ["房间"],
        "props": [],
        "transition_videos": {},
        "shots": [
            {
                "description": "主角小明走进房间",
                "characters": ["小明"],
                "scene": "房间",
                "props": [],
                "duration": 4,
                "dialogues": []
            },
            {
                "description": "小明看到了小红",
                "characters": ["小明", "小红"],
                "scene": "房间",
                "props": [],
                "duration": 4,
                "dialogues": [
                    {
                        "character_name": "小明",
                        "text": "你好，小红！"
                    }
                ]
            }
        ]
    }