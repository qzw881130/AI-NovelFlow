from io import BytesIO
from zipfile import ZipFile

from app.api.llm_logs import LLM_LOG_TASK_CATEGORY_TYPES, LLM_LOG_TASK_LABELS
from app.constants.prompt_template import PROMPT_TEMPLATE_FILE_NUMBERS, PROMPT_TEMPLATE_TYPES, PromptTemplateType
from app.models.llm_log import LLMLog
from app.models.novel import Novel
from app.models.prompt_template import PromptTemplate
from app.services.prompt_template_service import PromptTemplateService, load_template


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


def test_prompt_export_places_h3_optimizer_and_custom_templates_under_video_generation(client, db_session):
    template_type = PromptTemplateType.H3_EXECUTION_OPTIMIZER_PROMPT
    system = db_session.query(PromptTemplate).filter_by(type=template_type, is_system=True).one()
    custom = PromptTemplate(
        name="自定义 H3 执行优化",
        type=template_type,
        template="保留导演意图与说话人绑定。\nCustom H3 execution prompt.",
        is_system=False,
        is_active=True,
    )
    db_session.add(custom)
    db_session.commit()

    response = client.get("/api/prompt-templates/export-all")

    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as archive:
        directory = "视频生成/MiniMax H3 执行提示词优化/"
        assert archive.read(f"{directory}系统-{system.name}.txt").decode("utf-8") == system.template
        assert archive.read(f"{directory}用户-{custom.name}.txt").decode("utf-8") == custom.template
        assert not any(path.startswith(f"未分类/{template_type}/") for path in archive.namelist())


def test_h3_preflight_repair_uses_registered_14a_template_and_existing_management(client, db_session):
    template_type = PromptTemplateType.H3_PREFLIGHT_REPAIR_PROMPT
    system_templates = db_session.query(PromptTemplate).filter_by(type=template_type, is_system=True).all()
    assert len(system_templates) == 1
    system = system_templates[0]
    assert system.name == "MiniMax H3 Preflight 自动修复"
    assert system.template == load_template("14A_MiniMax_H3_Preflight_Repair_V1.txt")
    assert PROMPT_TEMPLATE_FILE_NUMBERS[template_type] == "14A"

    listed = client.get("/api/prompt-templates/", params={"type": template_type}).json()["data"]
    assert [item["id"] for item in listed] == [system.id]
    assert client.get("/api/prompt-templates/system/default", params={"type": template_type}).json()["data"]["id"] == system.id

    custom = client.post(f"/api/prompt-templates/{system.id}/copy").json()["data"]
    updated = client.put(f"/api/prompt-templates/{custom['id']}", json={
        "name": "自定义 #14A", "description": "测试有效配置", "template": "Edited #14A system prompt", "type": template_type,
    }).json()["data"]
    assert updated["template"] == "Edited #14A system prompt"
    assert updated["isSystem"] is False
    assert len(client.get("/api/prompt-templates/", params={"type": template_type}).json()["data"]) == 2


def test_legacy_14a_system_template_is_renamed_in_place(db_session):
    legacy = PromptTemplate(name="MiniMax H3 Preflight 定向修复", type=PromptTemplateType.H3_PREFLIGHT_REPAIR_PROMPT,
                            template="old content", is_system=True, is_active=True)
    db_session.add(legacy)
    db_session.commit()
    old_id = legacy.id

    PromptTemplateService(db_session).init_system_templates()

    templates = db_session.query(PromptTemplate).filter_by(type=PromptTemplateType.H3_PREFLIGHT_REPAIR_PROMPT, is_system=True).all()
    assert len(templates) == 1
    assert templates[0].id == old_id
    assert templates[0].name == "MiniMax H3 Preflight 自动修复"
    assert templates[0].template == load_template("14A_MiniMax_H3_Preflight_Repair_V1.txt")


def test_legacy_14a_duplicate_keeps_selected_template_valid(db_session):
    template_type = PromptTemplateType.H3_PREFLIGHT_REPAIR_PROMPT
    old = PromptTemplate(name="MiniMax H3 Preflight 定向修复", type=template_type,
                         template="old", is_system=True, is_active=True)
    current = PromptTemplate(name="MiniMax H3 Preflight 自动修复", type=template_type,
                             template="current", is_system=True, is_active=True)
    db_session.add_all([old, current])
    db_session.flush()
    novel = Novel(title="测试模板归并", h3_preflight_repair_prompt_template_id=old.id)
    db_session.add(novel)
    db_session.commit()

    PromptTemplateService(db_session).init_system_templates()

    templates = db_session.query(PromptTemplate).filter_by(type=template_type, is_system=True).all()
    assert [template.id for template in templates] == [current.id]
    db_session.refresh(novel)
    assert novel.h3_preflight_repair_prompt_template_id == current.id


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
    assert old_log.task_type in client.get("/api/llm-logs/filters").json()["data"]["task_types"]
    assert db_session.get(LLMLog, old_log.id).prompt_template_name == "MiniMax H3 Preflight 定向修复 [old-version]"
