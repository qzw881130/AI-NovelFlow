from io import BytesIO
from zipfile import ZipFile

from app.api.llm_logs import LLM_LOG_TASK_CATEGORY_TYPES
from app.constants.prompt_template import PROMPT_TEMPLATE_TYPES, PromptTemplateType


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

