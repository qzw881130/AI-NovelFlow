from io import BytesIO
from zipfile import ZipFile

from app.api.llm_logs import LLM_LOG_TASK_CATEGORY_TYPES, LLM_LOG_TASK_LABELS
from app.constants.prompt_template import PROMPT_TEMPLATE_TYPES, PromptTemplateType, prompt_template_scope
from app.models.llm_log import LLMLog
from app.models.novel import Novel
from app.models.prompt_template import PromptTemplate
from app.services.prompt_template_service import PromptTemplateService


def test_clip_execution_planner_is_a_registered_video_director_template():
    assert PromptTemplateType.CLIP_EXECUTION_PLANNER in PROMPT_TEMPLATE_TYPES
    assert "clip_execution_planner" in LLM_LOG_TASK_CATEGORY_TYPES["video_director"]
    assert "clip_execution_planner" not in LLM_LOG_TASK_CATEGORY_TYPES["video_generation"]


def test_prompt_export_places_clip_execution_planner_under_video_director(client):
    response = client.get("/api/prompt-templates/export-all")

    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as archive:
        paths = archive.namelist()

    assert "视频导演/Clip Execution Planner/系统-Clip Execution Planner.txt" in paths
    assert not any(path.startswith("未分类/clip_execution_planner/") for path in paths)


def test_grid_templates_are_distinct_and_exported_under_existing_categories(client, db_session):
    expected = {"grid_shot_plan", "grid_image_prompt", "grid_clip_plan", "grid_h3_phase_b"}
    assert expected <= set(PROMPT_TEMPLATE_TYPES)
    assert all(prompt_template_scope(template_type) == "grid" for template_type in expected)
    assert prompt_template_scope("h3_multi_keyframe_director_phase_b") == "single"
    assert prompt_template_scope("character") == "shared"
    assert not expected & {"h3_multi_keyframe_director_phase_b"}

    response = client.get("/api/prompt-templates/export-all")
    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as archive:
        paths = archive.namelist()
    assert any(path.startswith("视频生成/宫格 H3 六段式提示词/") for path in paths)
    assert any(path.startswith("分镜规划/宫格 Shot 与逐格机位规划/") for path in paths)
    assert db_session.query(PromptTemplate).filter_by(type="h3_multi_keyframe_director_phase_b", is_system=True).count() == 1


def test_retired_system_templates_do_not_reappear_on_startup(client, db_session):
    retired = {"h3_multi_keyframe_prompt", "h3_execution_optimizer_prompt", "h3_preflight_repair_prompt"}
    for template_type in retired:
        db_session.add(PromptTemplate(name=f"旧预设 {template_type}", type=template_type,
                                      template="old", is_system=True, is_active=True))
    db_session.commit()
    PromptTemplateService(db_session).init_system_templates()
    assert db_session.query(PromptTemplate).filter(PromptTemplate.type.in_(retired), PromptTemplate.is_system.is_(True)).count() == 0
    assert all(template_type not in PROMPT_TEMPLATE_TYPES for template_type in retired)
    assert client.get("/api/prompt-templates/config-types").json()["data"] == PROMPT_TEMPLATE_TYPES


def test_bound_retired_system_template_is_preserved_inactive(db_session):
    old = PromptTemplate(name="旧 #14A", type="h3_preflight_repair_prompt",
                         template="old", is_system=True, is_active=True)
    db_session.add(old)
    db_session.flush()
    novel = Novel(title="历史绑定", h3_preflight_repair_prompt_template_id=old.id)
    db_session.add(novel)
    db_session.commit()
    PromptTemplateService(db_session).init_system_templates()
    db_session.refresh(old)
    assert old.is_active is False
    assert novel.h3_preflight_repair_prompt_template_id == old.id


def test_existing_14a_logs_use_dynamic_video_generation_category(client, db_session):
    old_log = LLMLog(provider="openai", model="existing-model", user_prompt="old request",
                     task_type=PromptTemplateType.H3_PREFLIGHT_REPAIR_PROMPT, status="success",
                     prompt_template_name="MiniMax H3 Preflight 定向修复 [old-version]")
    db_session.add(old_log)
    db_session.commit()
    assert PromptTemplateType.H3_PREFLIGHT_REPAIR_PROMPT in LLM_LOG_TASK_CATEGORY_TYPES["video_generation"]
    assert LLM_LOG_TASK_LABELS[old_log.task_type] == "视频生成-MiniMax H3 Preflight 自动修复"

    response = client.get("/api/llm-logs/", params={"category": "video_generation", "task_type": old_log.task_type})
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]["items"]] == [old_log.id]
    assert old_log.task_type not in client.get("/api/llm-logs/filters").json()["data"]["task_types"]
    assert db_session.get(LLMLog, old_log.id).prompt_template_name == "MiniMax H3 Preflight 定向修复 [old-version]"
