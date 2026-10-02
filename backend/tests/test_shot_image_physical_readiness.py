import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api import shots as shot_api
from app.models.novel import Chapter, Character, Novel, Prop, Scene
from app.models.shot import Shot
from app.models.task import Task
from app.models.workflow import Workflow
from app.services.prop_policy import PROP_EXISTENCE_REAL
from app.services.shot_image_service import _fail_shot_image_task


def _create_shot_fixture(db_session, *, existing_image=False):
    novel = Novel(title="物理参考测试")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(
        novel_id=novel.id,
        number=1,
        title="第一章",
        content="测试",
        parsed_data=json.dumps({"shots": [{}]}, ensure_ascii=False),
    )
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(
        chapter_id=chapter.id,
        index=1,
        description="角色进入场景并拿起道具",
        characters=json.dumps(["角色甲", "角色乙"], ensure_ascii=False),
        scene="大厅",
        props=json.dumps(["权杖"], ensure_ascii=False),
        image_url="/api/files/current.png" if existing_image else None,
        image_path="/existing/current.png" if existing_image else None,
        image_status="completed" if existing_image else "pending",
        image_task_id="current-image-task" if existing_image else None,
    )
    db_session.add(shot)
    db_session.commit()
    return novel, chapter, shot


def _add_resources(db_session, novel, *, character_images=(), scene_image=False, prop_image=False):
    for name in ("角色甲", "角色乙"):
        db_session.add(Character(
            novel_id=novel.id,
            name=name,
            image_url=f"/api/files/{name}.png" if name in character_images else None,
        ))
    db_session.add(Scene(
        novel_id=novel.id,
        name="大厅",
        image_url="/api/files/scene.png" if scene_image else None,
    ))
    db_session.add(Prop(
        novel_id=novel.id,
        name="权杖",
        existence=PROP_EXISTENCE_REAL,
        image_url="/api/files/prop.png" if prop_image else None,
    ))
    db_session.commit()


def _workflow():
    workflow = MagicMock(spec=Workflow)
    workflow.id = "workflow-physical-reference"
    workflow.name = "物理参考工作流"
    workflow.node_mapping = "{}"
    return workflow


def test_zero_physical_references_rejected_before_llm_task_or_submission_and_preserves_image(client, db_session):
    novel, chapter, shot = _create_shot_fixture(db_session, existing_image=True)
    _add_resources(db_session, novel)

    with (
        patch("app.api.shots.url_to_local_path", return_value=None),
        patch("app.api.shots._resolve_shot_image_prompt_text", new=AsyncMock()) as prompt_builder,
        patch("app.api.shots.generate_shot_task") as enqueue,
        patch("app.api.shots.file_storage.delete_shot_image") as delete_image,
    ):
        response = client.post(
            f"/api/novels/{novel.id}/chapters/{chapter.id}/shots/{shot.id}/generate"
        )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "SHOT_IMAGE_REFERENCES_NOT_READY"
    assert detail["available_reference_count"] == 0
    assert detail["missing"] == {
        "characters": ["角色甲", "角色乙"],
        "scenes": ["大厅"],
        "props": ["权杖"],
    }
    assert db_session.query(Task).filter(Task.type == "shot_image").count() == 0
    prompt_builder.assert_not_awaited()
    enqueue.assert_not_called()
    delete_image.assert_not_called()
    db_session.refresh(shot)
    assert shot.image_url == "/api/files/current.png"
    assert shot.image_path == "/existing/current.png"
    assert shot.image_status == "completed"
    assert shot.image_task_id == "current-image-task"


@pytest.mark.parametrize(
    ("character_images", "scene_image", "prop_image", "expected_count", "expected_missing"),
    [
        (("角色甲",), False, False, 1, {"characters": ["角色乙"], "scenes": ["大厅"], "props": ["权杖"]}),
        ((), True, False, 1, {"characters": ["角色甲", "角色乙"], "scenes": [], "props": ["权杖"]}),
        ((), False, True, 1, {"characters": ["角色甲", "角色乙"], "scenes": ["大厅"], "props": []}),
        (("角色甲",), True, False, 2, {"characters": ["角色乙"], "scenes": [], "props": ["权杖"]}),
        (("角色甲", "角色乙"), True, True, 3, {"characters": [], "scenes": [], "props": []}),
    ],
)
def test_partial_and_complete_physical_reference_sets_remain_allowed(
    client,
    db_session,
    character_images,
    scene_image,
    prop_image,
    expected_count,
    expected_missing,
):
    novel, chapter, shot = _create_shot_fixture(db_session)
    _add_resources(
        db_session,
        novel,
        character_images=character_images,
        scene_image=scene_image,
        prop_image=prop_image,
    )

    with (
        patch("app.api.shots.url_to_local_path", side_effect=lambda value: value if value else None),
        patch("app.repositories.workflow_repository.WorkflowRepository.get_active_by_type", return_value=_workflow()),
        patch("app.api.shots.TaskService.validate_workflow_node_mapping", return_value=(True, "")),
        patch("app.api.shots._resolve_shot_image_prompt_text", new=AsyncMock(return_value=("提示词", "测试模板"))) as prompt_builder,
        patch("app.api.shots.generate_shot_task") as enqueue,
        patch("app.api.shots.file_storage.delete_shot_image"),
    ):
        readiness = shot_api._build_shot_image_reference_readiness(db_session, novel, shot)
        response = client.post(
            f"/api/novels/{novel.id}/chapters/{chapter.id}/shots/{shot.id}/generate"
        )

    assert readiness["available_reference_count"] == expected_count
    assert readiness["missing"] == expected_missing
    assert response.status_code == 200
    assert response.json()["success"] is True
    prompt_builder.assert_awaited_once()
    enqueue.assert_called_once()
    db_session.refresh(shot)
    assert shot.image_status == "generating"
    assert shot.image_task_id == response.json()["data"]["taskId"]


def test_zero_reference_batch_rejected_before_parent_or_child_task_creation(client, db_session):
    novel, chapter, shot = _create_shot_fixture(db_session)
    _add_resources(db_session, novel)

    with patch("app.api.shots.url_to_local_path", return_value=None):
        response = client.post(
            f"/api/novels/{novel.id}/chapters/{chapter.id}/shot-images/batch",
            json={"shot_ids": [shot.id]},
        )

    assert response.status_code == 409
    assert db_session.query(Task).filter(Task.type.in_(["shot_image", "shot_image_batch"])).count() == 0


def test_current_task_failure_projects_failed_shot_and_retains_task_identity(db_session):
    novel, chapter, shot = _create_shot_fixture(db_session)
    task = Task(
        type="shot_image",
        name="生成分镜图: 镜1",
        novel_id=novel.id,
        chapter_id=chapter.id,
        shot_id=shot.id,
        status="running",
    )
    db_session.add(task)
    db_session.flush()
    shot.image_status = "generating"
    shot.image_task_id = task.id
    db_session.commit()

    _fail_shot_image_task(db_session, task, "ComfyUI 失败", "生成失败", chapter.id, 1)

    db_session.refresh(task)
    db_session.refresh(shot)
    assert task.status == "failed"
    assert task.error_message == "ComfyUI 失败"
    assert shot.image_status == "failed"
    assert shot.image_task_id == task.id


def test_stale_task_failure_does_not_overwrite_newer_current_shot_state(db_session):
    novel, chapter, shot = _create_shot_fixture(db_session)
    stale_task = Task(
        type="shot_image",
        name="生成分镜图: 镜1",
        novel_id=novel.id,
        chapter_id=chapter.id,
        shot_id=shot.id,
        status="running",
    )
    current_task = Task(
        type="shot_image",
        name="生成分镜图: 镜1",
        novel_id=novel.id,
        chapter_id=chapter.id,
        shot_id=shot.id,
        status="completed",
        result_url="/api/files/new.png",
    )
    db_session.add_all([stale_task, current_task])
    db_session.flush()
    shot.image_status = "completed"
    shot.image_task_id = current_task.id
    shot.image_url = current_task.result_url
    db_session.commit()

    _fail_shot_image_task(db_session, stale_task, "旧任务失败", "生成失败", chapter.id, 1)

    db_session.refresh(shot)
    assert shot.image_status == "completed"
    assert shot.image_task_id == current_task.id
    assert shot.image_url == "/api/files/new.png"
