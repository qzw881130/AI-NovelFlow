"""Manual review must bind to the current image in each library."""

from types import SimpleNamespace

import pytest

from app.api import image_reviews
from app.models.novel import Character, Novel, Prop, Scene
from app.models.task import Task


@pytest.mark.parametrize("kind, model, task_field, entity_field, task_type", [
    ("character", Character, "portrait_task_id", "character_id", "character_portrait"),
    ("scene", Scene, "scene_task_id", "scene_id", "scene_image"),
    ("prop", Prop, "prop_task_id", "prop_id", "prop_image"),
])
def test_library_review_creates_input_for_uploaded_image_and_reuses_it(
    client, db_session, monkeypatch, kind, model, task_field, entity_field, task_type,
):
    novel = Novel(title="图库评审测试")
    db_session.add(novel)
    db_session.flush()
    entity = model(novel_id=novel.id, name="测试图", description="描述",
                   image_url="/api/files/current.png")
    db_session.add(entity)
    db_session.commit()
    seen = []

    async def fake_review(db, task_id):
        seen.append(task_id)
        return SimpleNamespace(id=f"review-{len(seen)}")

    monkeypatch.setattr(image_reviews, "review_image_task", fake_review)
    monkeypatch.setattr(image_reviews, "review_to_dict", lambda review: {"id": review.id})
    url = "/api/tasks/library-image-reviews"
    response = client.post(url, json={"kind": kind, "entityId": entity.id})
    assert response.status_code == 200, response.text
    task_id = response.json()["data"]["taskId"]
    task = db_session.get(Task, task_id)
    assert task.type == task_type and task.status == "completed"
    assert task.result_url == entity.image_url and task.prompt_text
    assert getattr(task, entity_field) == entity.id
    assert getattr(entity, task_field) == task_id

    again = client.post(url, json={"kind": kind, "entityId": entity.id})
    assert again.status_code == 200
    assert again.json()["data"]["taskId"] == task_id
    assert seen == [task_id, task_id]


def test_library_review_ignores_previous_image_task(client, db_session, monkeypatch):
    novel = Novel(title="旧图不能复用")
    db_session.add(novel)
    db_session.flush()
    character = Character(novel_id=novel.id, name="人物", image_url="/api/files/new.png")
    db_session.add(character)
    db_session.flush()
    old_task = Task(type="character_portrait", status="completed", novel_id=novel.id,
                    character_id=character.id, name="旧图", result_url="/api/files/old.png",
                    prompt_text="旧提示词")
    db_session.add(old_task)
    db_session.flush()
    character.portrait_task_id = old_task.id
    db_session.commit()

    async def fake_review(db, task_id):
        return SimpleNamespace(id="review-new")

    monkeypatch.setattr(image_reviews, "review_image_task", fake_review)
    monkeypatch.setattr(image_reviews, "review_to_dict", lambda review: {"id": review.id})
    response = client.post("/api/tasks/library-image-reviews",
                           json={"kind": "character", "entityId": character.id})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["taskId"] != old_task.id
    assert db_session.get(Task, response.json()["data"]["taskId"]).result_url == character.image_url


def test_library_review_uses_current_generation_task_and_prompt(client, db_session, monkeypatch):
    novel = Novel(title="沿用生图任务")
    db_session.add(novel)
    db_session.flush()
    scene = Scene(novel_id=novel.id, name="庭院", image_url="/api/files/scene.png")
    db_session.add(scene)
    db_session.flush()
    task = Task(type="scene_image", status="completed", novel_id=novel.id,
                scene_id=scene.id, name="生成场景", result_url=scene.image_url,
                prompt_text="原始生图提示词")
    db_session.add(task)
    db_session.flush()
    scene.scene_task_id = task.id
    db_session.commit()

    async def fake_review(db, task_id):
        assert task_id == task.id
        return SimpleNamespace(id="review-scene")

    monkeypatch.setattr(image_reviews, "review_image_task", fake_review)
    monkeypatch.setattr(image_reviews, "review_to_dict", lambda review: {"id": review.id})
    response = client.post("/api/tasks/library-image-reviews",
                           json={"kind": "scene", "entityId": scene.id})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["taskId"] == task.id
    assert task.prompt_text == "原始生图提示词"
    assert db_session.query(Task).count() == 1
