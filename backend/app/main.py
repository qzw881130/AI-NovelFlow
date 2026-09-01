from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from sqlalchemy import text

from app.api import characters, tasks, config, health, test_cases, workflows, files, prompt_templates, llm_logs, scenes, props
from app.api import novels, chapters, shots
from app.core.database import engine, Base
# 导入所有模型以确保创建表
from app.models.novel import Novel, Chapter, Character, Scene, Prop
from app.models.task import Task
from app.models.test_case import TestCase
from app.models.prompt_template import PromptTemplate
from app.models.llm_log import LLMLog
from app.models.system_config import SystemConfig  # 导入系统配置模型
from app.models.shot import Shot


def ensure_schema_updates():
    """补齐 create_all 不会自动添加的轻量字段。"""
    with engine.connect() as conn:
        try:
            result = conn.execute(text("PRAGMA table_info(shots)"))
            shot_columns = [row[1] for row in result.fetchall()]
            if "merged_prop_image" not in shot_columns:
                conn.execute(text("ALTER TABLE shots ADD COLUMN merged_prop_image VARCHAR"))
            if "continuity_mode" not in shot_columns:
                conn.execute(text("ALTER TABLE shots ADD COLUMN continuity_mode VARCHAR DEFAULT 'NORMAL'"))
            if "video_director_plan" not in shot_columns:
                conn.execute(text("ALTER TABLE shots ADD COLUMN video_director_plan TEXT DEFAULT '{}'"))
            if "shot_image_prompt" not in shot_columns:
                conn.execute(text("ALTER TABLE shots ADD COLUMN shot_image_prompt TEXT DEFAULT ''"))

            result = conn.execute(text("PRAGMA table_info(novels)"))
            novel_columns = [row[1] for row in result.fetchall()]
            novel_prompt_columns = [
                "keyframe_description_prompt_template_id",
                "shot_image_prompt_template_id",
                "video_mode_recommender_prompt_template_id",
                "keyframe_planner_prompt_template_id",
                "keyframe_image_prompt_template_id",
                "keyframe_transition_prompt_template_id",
                "h3_single_frame_prompt_template_id",
                "h3_first_last_frame_prompt_template_id",
                "h3_multi_keyframe_prompt_template_id",
            ]
            for column in novel_prompt_columns:
                if column not in novel_columns:
                    conn.execute(text(f"ALTER TABLE novels ADD COLUMN {column} VARCHAR"))

            result = conn.execute(text("PRAGMA table_info(tasks)"))
            task_columns = [row[1] for row in result.fetchall()]
            if "reference_images" not in task_columns:
                conn.execute(text("ALTER TABLE tasks ADD COLUMN reference_images TEXT"))

            result = conn.execute(text("PRAGMA table_info(llm_logs)"))
            llm_log_columns = [row[1] for row in result.fetchall()]
            if "request_info" not in llm_log_columns:
                conn.execute(text("ALTER TABLE llm_logs ADD COLUMN request_info TEXT"))
            if "prompt_template_name" not in llm_log_columns:
                conn.execute(text("ALTER TABLE llm_logs ADD COLUMN prompt_template_name VARCHAR"))
            conn.commit()
        except Exception as exc:
            print(f"[Startup] Failed to ensure schema updates: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    Base.metadata.create_all(bind=engine)
    ensure_schema_updates()
    
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


# CORS - 动态允许所有来源，支持任意 IP/端口访问
# 使用动态 origin 检查，支持从任何来源访问
allow_origin_regex = r"https?://.*"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_origin_regex=allow_origin_regex,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH", "HEAD"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Request-ID"],
    max_age=86400,  # 预检请求缓存 24 小时
)

# Routers
app.include_router(health.router, prefix="/api/health", tags=["health"])
app.include_router(config.router, prefix="/api/config", tags=["config"])
# 小说相关路由（拆分为多个模块）
app.include_router(novels.router, prefix="/api/novels", tags=["novels"])
app.include_router(chapters.router, prefix="/api/novels", tags=["novels"])
app.include_router(shots.router, prefix="/api/novels", tags=["novels"])
app.include_router(characters.router, prefix="/api/characters", tags=["characters"])
app.include_router(scenes.router, prefix="/api/scenes", tags=["scenes"])
app.include_router(props.router, prefix="/api/props", tags=["props"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
app.include_router(test_cases.router, prefix="/api/test-cases", tags=["test-cases"])
app.include_router(workflows.router, prefix="/api/workflows", tags=["workflows"])
app.include_router(files.router, prefix="/api/files", tags=["files"])
app.include_router(prompt_templates.router, prefix="/api/prompt-templates", tags=["prompt-templates"])
app.include_router(llm_logs.router, prefix="/api/llm-logs", tags=["llm-logs"])


@app.get("/")
async def root():
    return {"message": "Welcome to NovelFlow API", "version": "0.1.0"}
