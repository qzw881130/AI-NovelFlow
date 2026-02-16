from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.api import novels, characters, tasks, config, health, test_cases, workflows, files, prompt_templates
from app.core.database import engine, Base
# 导入所有模型以确保创建表
from app.models.novel import Novel, Chapter, Character
from app.models.task import Task
from app.models.test_case import TestCase
from app.models.prompt_template import PromptTemplate
from app.models.system_config import SystemConfig  # 导入系统配置模型


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    Base.metadata.create_all(bind=engine)
    
    # 初始化预设数据和系统配置
    from app.api.test_cases import init_preset_test_cases
    from app.api.prompt_templates import init_system_prompt_templates
    from app.api.config import init_system_config  # 导入配置初始化函数
    from app.core.database import SessionLocal
    db = SessionLocal()
    try:
        # 从数据库加载系统配置
        init_system_config(db)
        init_system_prompt_templates(db)
        await init_preset_test_cases(db)
    finally:
        db.close()
    
    # 启动 ComfyUI 监控器
    from app.services.comfyui_monitor import init_monitor
    from app.core.config import get_settings
    settings = get_settings()
    
    monitor = init_monitor(settings.COMFYUI_HOST)
    await monitor.start()
    
    yield
    
    # Shutdown
    await monitor.stop()


app = FastAPI(
    title="NovelFlow API",
    description="AI 小说转视频平台 API",
    version="0.1.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(health.router, prefix="/api/health", tags=["health"])
app.include_router(config.router, prefix="/api/config", tags=["config"])
app.include_router(novels.router, prefix="/api/novels", tags=["novels"])
app.include_router(characters.router, prefix="/api/characters", tags=["characters"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
app.include_router(test_cases.router, prefix="/api/test-cases", tags=["test-cases"])
app.include_router(workflows.router, prefix="/api/workflows", tags=["workflows"])
app.include_router(files.router, prefix="/api/files", tags=["files"])
app.include_router(prompt_templates.router, prefix="/api/prompt-templates", tags=["prompt-templates"])


@app.get("/")
async def root():
    return {"message": "Welcome to NovelFlow API", "version": "0.1.0"}
