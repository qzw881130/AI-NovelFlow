import json
from io import BytesIO
from zipfile import ZipFile

from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.task import Task


def test_current_shot_image_package_contains_submitted_comfyui_workflow(client, db_session):
    novel = Novel(title="测试小说")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="第一章", content="测试", parsed_data="{}")
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(chapter_id=chapter.id, index=1, description="测试分镜", image_status="completed")
    db_session.add(shot)
    db_session.flush()

    current_task = Task(
        type="shot_image",
        status="completed",
        novel_id=novel.id,
        chapter_id=chapter.id,
        shot_id=shot.id,
        name="当前分镜图任务",
        workflow_id="workflow-current",
        workflow_name="当前实际工作流",
        workflow_json=json.dumps({"marker": "submitted-current"}),
        comfyui_prompt_id="prompt-current",
        prompt_text="当前提示词",
    )
    newer_unrelated_task = Task(
        type="shot_image",
        status="completed",
        novel_id=novel.id,
        chapter_id=chapter.id,
        shot_id=shot.id,
        name="非当前分镜图任务",
        workflow_json=json.dumps({"marker": "not-current"}),
        prompt_text="非当前提示词",
    )
    db_session.add_all([current_task, newer_unrelated_task])
    db_session.flush()
    shot.image_task_id = current_task.id
    db_session.commit()

    response = client.get(
        f"/api/novels/{novel.id}/chapters/{chapter.id}/shots/{shot.id}/download-shot-image-data"
    )

    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as archive:
        workflow = json.loads(archive.read("shot001/生成图真实工作流.json"))
        manifest = json.loads(archive.read("manifest.json"))

    assert workflow == {"marker": "submitted-current"}
    workflow_item = next(
        item for item in manifest["shots"][0]["materials"]
        if item.get("kind") == "submitted_comfyui_workflow"
    )
    assert workflow_item["task_id"] == current_task.id
    assert workflow_item["workflow_id"] == "workflow-current"
    assert workflow_item["workflow_name"] == "当前实际工作流"
    assert workflow_item["comfyui_prompt_id"] == "prompt-current"

