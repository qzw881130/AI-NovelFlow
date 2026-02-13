from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.api import novels, characters, tasks, config, health, test_cases
from app.core.database import engine, Base
# 导入所有模型以确保创建表
from app.models.novel import Novel, Chapter, Character
from app.models.task import Task
from app.models.test_case import TestCase


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    Base.metadata.create_all(bind=engine)
    
    # 初始化预设测试用例
    from app.api.test_cases import init_preset_test_cases
    from app.core.database import SessionLocal
    db = SessionLocal()
    try:
        await init_preset_test_cases(db)
    finally:
        db.close()
    
    yield
    # Shutdown


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


@app.get("/")
async def root():
    return {"message": "Welcome to NovelFlow API", "version": "0.1.0"}
