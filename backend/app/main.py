from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from sqlalchemy import text
import asyncio

from app.api import characters, tasks, config, health, test_cases, workflows, files, prompt_templates, llm_logs, scenes, props, novel_videos
from app.api import novels, chapters, shots, hd_repaint
from app.core.database import engine, Base
from app.services.comfyui_monitor import init_monitor
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
            if "hd_video_url" not in shot_columns:
                conn.execute(text("ALTER TABLE shots ADD COLUMN hd_video_url VARCHAR"))
            if "hd_video_status" not in shot_columns:
                conn.execute(text("ALTER TABLE shots ADD COLUMN hd_video_status VARCHAR DEFAULT 'pending'"))
            if "hd_video_task_id" not in shot_columns:
                conn.execute(text("ALTER TABLE shots ADD COLUMN hd_video_task_id VARCHAR"))
            if "hd_video_source_task_id" not in shot_columns:
                conn.execute(text("ALTER TABLE shots ADD COLUMN hd_video_source_task_id VARCHAR"))
            if "hd_video_megapixels" not in shot_columns:
                conn.execute(text("ALTER TABLE shots ADD COLUMN hd_video_megapixels REAL"))
            if "current_video_variant" not in shot_columns:
                conn.execute(text("ALTER TABLE shots ADD COLUMN current_video_variant VARCHAR DEFAULT 'draft'"))

            result = conn.execute(text("PRAGMA table_info(props)"))
            prop_columns = [row[1] for row in result.fetchall()]
            if "existence" not in prop_columns:
                conn.execute(text("ALTER TABLE props ADD COLUMN existence VARCHAR NOT NULL DEFAULT 'REAL'"))
            conn.execute(text("""
                UPDATE props
                SET existence = 'FICTIONAL_OR_NONEXISTENT'
                WHERE existence = 'REAL'
                  AND (
                    description LIKE '%不存在%'
                    OR description LIKE '%并不真实%'
                    OR description LIKE '%仅为谎言%'
                  )
            """))
            conn.execute(text("""
                UPDATE shots
                SET merged_prop_image = NULL
                WHERE chapter_id IN (
                    SELECT chapters.id
                    FROM chapters
                    WHERE chapters.novel_id IN (
                        SELECT DISTINCT novel_id FROM props
                        WHERE existence = 'FICTIONAL_OR_NONEXISTENT'
                    )
                )
            """))

            result = conn.execute(text("PRAGMA table_info(novels)"))
            novel_columns = [row[1] for row in result.fetchall()]
            novel_prompt_columns = [
                "story_world_context_prompt_template_id",
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
            if "story_world_context" not in novel_columns:
                conn.execute(text("ALTER TABLE novels ADD COLUMN story_world_context TEXT"))
            if "story_world_context_locked" not in novel_columns:
                conn.execute(text("ALTER TABLE novels ADD COLUMN story_world_context_locked BOOLEAN DEFAULT 0"))
            if "story_world_context_updated_at" not in novel_columns:
                conn.execute(text("ALTER TABLE novels ADD COLUMN story_world_context_updated_at DATETIME"))

            result = conn.execute(text("PRAGMA table_info(chapters)"))
            chapter_columns = [row[1] for row in result.fetchall()]
            if "hd_final_video" not in chapter_columns:
                conn.execute(text("ALTER TABLE chapters ADD COLUMN hd_final_video VARCHAR"))

            result = conn.execute(text("PRAGMA table_info(tasks)"))
            task_columns = [row[1] for row in result.fetchall()]
            if "reference_images" not in task_columns:
                conn.execute(text("ALTER TABLE tasks ADD COLUMN reference_images TEXT"))
            if "video_director_clips" not in task_columns:
                conn.execute(text("ALTER TABLE tasks ADD COLUMN video_director_clips TEXT"))
            if "parent_task_id" not in task_columns:
                conn.execute(text("ALTER TABLE tasks ADD COLUMN parent_task_id VARCHAR"))
            if "batch_order" not in task_columns:
                conn.execute(text("ALTER TABLE tasks ADD COLUMN batch_order INTEGER"))
            if "metadata_json" not in task_columns:
                conn.execute(text("ALTER TABLE tasks ADD COLUMN metadata_json TEXT"))
            if "seed" not in task_columns:
                conn.execute(text("ALTER TABLE tasks ADD COLUMN seed INTEGER"))
            if "source_task_id" not in task_columns:
                conn.execute(text("ALTER TABLE tasks ADD COLUMN source_task_id VARCHAR"))

            result = conn.execute(text("PRAGMA table_info(llm_logs)"))
            llm_log_columns = [row[1] for row in result.fetchall()]
            if "request_info" not in llm_log_columns:
                conn.execute(text("ALTER TABLE llm_logs ADD COLUMN request_info TEXT"))
            if "prompt_template_name" not in llm_log_columns:
                conn.execute(text("ALTER TABLE llm_logs ADD COLUMN prompt_template_name VARCHAR"))
            if "usage_metrics" not in llm_log_columns:
                conn.execute(text("ALTER TABLE llm_logs ADD COLUMN usage_metrics JSON"))
            conn.commit()
        except Exception as exc:
            print(f"[Startup] Failed to ensure schema updates: {exc}")


async def reconcile_active_tasks_loop():
    """Periodically reconcile active tasks so stale ComfyUI states are corrected after restarts."""
    from app.core.database import SessionLocal
    from app.repositories import TaskRepository
    from app.services.task_service import TaskService

    while True:
        db = SessionLocal()
        try:
            task_repo = TaskRepository(db)
            active_tasks = task_repo.list_active_tasks()
            if active_tasks:
                updated_count = await TaskService(db).reconcile_active_tasks(active_tasks, db=db)
                if updated_count:
                    print(f"[TaskReconcile] Updated {updated_count} stale active task(s)")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[TaskReconcile] Failed to reconcile active tasks: {exc}")
        finally:
            db.close()
        await asyncio.sleep(30)


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
    from app.core.config import get_settings
    settings = get_settings()
    
    monitor = init_monitor(settings.COMFYUI_HOST)
    await monitor.start()
    from app.api.shots import resume_active_shot_image_batches, resume_active_shot_video_batches, resume_active_chapter_video_merges
    resume_active_shot_image_batches()
    resume_active_shot_video_batches()
    resume_active_chapter_video_merges()
    from app.services.novel_video_merge_service import resume_active_novel_video_merges
    resume_active_novel_video_merges()
    from app.services.hd_repaint_service import resume_active_hd_repaints
    resume_active_hd_repaints()
    task_reconcile_task = asyncio.create_task(reconcile_active_tasks_loop())
    app.state.task_reconcile_task = task_reconcile_task
    
    yield
    
    # Shutdown
    task_reconcile_task.cancel()
    try:
        await task_reconcile_task
    except asyncio.CancelledError:
        pass
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
app.include_router(hd_repaint.router, prefix="/api/novels", tags=["hd-repaint"])
app.include_router(characters.router, prefix="/api/characters", tags=["characters"])
app.include_router(scenes.router, prefix="/api/scenes", tags=["scenes"])
app.include_router(props.router, prefix="/api/props", tags=["props"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
app.include_router(test_cases.router, prefix="/api/test-cases", tags=["test-cases"])
app.include_router(workflows.router, prefix="/api/workflows", tags=["workflows"])
app.include_router(files.router, prefix="/api/files", tags=["files"])
app.include_router(prompt_templates.router, prefix="/api/prompt-templates", tags=["prompt-templates"])
app.include_router(novel_videos.router, prefix="/api", tags=["novel-videos"])
app.include_router(llm_logs.router, prefix="/api/llm-logs", tags=["llm-logs"])


@app.get("/")
async def root():
    return {"message": "Welcome to NovelFlow API", "version": "0.1.0"}
