from io import BytesIO
from zipfile import ZipFile

from app.api.llm_logs import LLM_LOG_TASK_CATEGORY_TYPES
from app.constants.prompt_template import PROMPT_TEMPLATE_TYPES, PromptTemplateType
from app.models.prompt_template import PromptTemplate


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
