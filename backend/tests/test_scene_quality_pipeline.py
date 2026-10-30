"""Scene candidates are published only after the bounded quality loop passes."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.image_quality_review import ImageQualityReview
from app.models.novel import Novel, Scene
from app.models.task import Task
from app.services import scene_quality_pipeline as pipeline
from app.services.image_quality_review import build_review_input
from app.services.scene_reference_quality import scene_reference_review_status


def _fixture(db):
    novel = Novel(id="scene-novel", title="测试小说")
    scene = Scene(id="scene-1", novel_id=novel.id, name="空庭",
                  image_url="/api/files/old.png", scene_task_id="scene-task",
                  generating_status="running")
    task = Task(id="scene-task", type="scene_image", name="生成场景图", novel_id=novel.id,
                scene_id=scene.id, status="running")
    db.add_all([novel, scene, task])
    db.commit()
    return scene, task


def _stub_generation(monkeypatch, reviews):
    generated = AsyncMock(return_value={"success": True, "image_url": "http://comfy/generated.png"})
    edited = AsyncMock(return_value={"success": True, "image_url": "http://comfy/edited.png"})
    saved = []

    async def save(db, task, image_url, name, cycle, kind):
        url = f"/api/files/{kind}_{cycle}.png"
        saved.append(url)
        return url

    async def review(db, task_id, trigger):
        url = db.get(Task, task_id).result_url
        status, overall, count = reviews[url]
        return SimpleNamespace(id=f"review-{len(saved)}", status=status, overall=overall,
                               dimensions_json=json.dumps({"CHARACTER_COUNT": {"status": count}}),
                               issues_json="[]",
                               summary=overall, error_message="review error" if status == "error" else None)

    monkeypatch.setattr(pipeline, "_generate", generated)
    monkeypatch.setattr(pipeline, "_edit", edited)
    monkeypatch.setattr(pipeline, "_save_candidate", save)
    monkeypatch.setattr(pipeline, "review_image_task", review)
    return generated, edited


@pytest.mark.asyncio
async def test_scene_first_candidate_passes_without_cleanup(db_session, monkeypatch):
    scene, task = _fixture(db_session)
    generated, edited = _stub_generation(monkeypatch, {
        "/api/files/generate_1.png": ("success", "PASS", "PASS"),
    })
    await pipeline.run_scene_quality_pipeline(db_session, task, scene, object())
    assert task.status == "completed"
    assert scene.image_url == "/api/files/generate_1.png"
    assert generated.await_count == 1
    edited.assert_not_awaited()


@pytest.mark.asyncio
async def test_scene_people_fail_then_cleanup_passes(db_session, monkeypatch):
    scene, task = _fixture(db_session)
    generated, edited = _stub_generation(monkeypatch, {
        "/api/files/generate_1.png": ("success", "FAIL", "FAIL"),
        "/api/files/edit_1.png": ("success", "PASS", "PASS"),
    })
    await pipeline.run_scene_quality_pipeline(db_session, task, scene, object())
    assert scene.image_url == "/api/files/edit_1.png"
    assert generated.await_count == edited.await_count == 1
    attempt = json.loads(task.metadata_json)["scene_quality"]["attempts"][0]
    assert attempt["generated_review"]["character_count"] == "FAIL"
    assert attempt["cleaned_review"]["overall"] == "PASS"


@pytest.mark.asyncio
async def test_non_person_review_issue_regenerates_without_cleanup(db_session, monkeypatch):
    scene, task = _fixture(db_session)
    generated, edited = _stub_generation(monkeypatch, {
        "/api/files/generate_1.png": ("success", "WARNING", "PASS"),
        "/api/files/generate_2.png": ("success", "PASS", "PASS"),
    })
    await pipeline.run_scene_quality_pipeline(db_session, task, scene, object())
    assert scene.image_url == "/api/files/generate_2.png"
    assert generated.await_count == 2
    edited.assert_not_awaited()


def test_next_scene_cycle_uses_previous_review_feedback():
    state = {"cycle": 2, "attempts": [
        {"cycle": 1, "generated_review": {
            "summary": "火把直接出现在画面中",
            "feedback": ["移除可见火把，仅保留间接火光"],
        }},
        {"cycle": 2},
    ]}
    assert pipeline._review_feedback(state) == "移除可见火把，仅保留间接火光"


@pytest.mark.asyncio
async def test_scene_three_failed_cycles_keep_previous_image(db_session, monkeypatch):
    scene, task = _fixture(db_session)
    reviews = {f"/api/files/{kind}_{cycle}.png": ("success", "FAIL", "FAIL")
               for cycle in range(1, 4) for kind in ("generate", "edit")}
    generated, edited = _stub_generation(monkeypatch, reviews)
    with pytest.raises(RuntimeError, match="经过 3 轮.*FAIL；保留原场景图"):
        await pipeline.run_scene_quality_pipeline(db_session, task, scene, object())
    assert scene.image_url == "/api/files/old.png"
    assert generated.await_count == edited.await_count == 3
    assert len(json.loads(task.metadata_json)["scene_quality"]["attempts"]) == 3


@pytest.mark.asyncio
async def test_scene_review_error_does_not_regenerate(db_session, monkeypatch):
    scene, task = _fixture(db_session)
    generated, edited = _stub_generation(monkeypatch, {
        "/api/files/generate_1.png": ("error", None, None),
    })
    with pytest.raises(RuntimeError, match="AI 审核未完成"):
        await pipeline.run_scene_quality_pipeline(db_session, task, scene, object())
    assert scene.image_url == "/api/files/old.png"
    assert generated.await_count == 1
    edited.assert_not_awaited()


@pytest.mark.asyncio
async def test_scene_resumes_saved_candidate_without_resubmitting_comfyui(db_session, monkeypatch):
    scene, task = _fixture(db_session)
    task.metadata_json = json.dumps({"scene_quality": {
        "cycle": 1, "stage": "generated_review", "original_url": scene.image_url,
        "candidate_url": "/api/files/generate_1.png", "attempts": [{"cycle": 1}],
    }})
    db_session.commit()
    generated, edited = _stub_generation(monkeypatch, {
        "/api/files/generate_1.png": ("success", "PASS", "PASS"),
    })
    await pipeline.run_scene_quality_pipeline(db_session, task, scene, object())
    generated.assert_not_awaited()
    edited.assert_not_awaited()
    assert scene.image_url == "/api/files/generate_1.png"


@pytest.mark.asyncio
async def test_scene_manual_replacement_is_not_overwritten(db_session, monkeypatch):
    scene, task = _fixture(db_session)
    generated, _ = _stub_generation(monkeypatch, {
        "/api/files/generate_1.png": ("success", "PASS", "PASS"),
    })
    original_generate = pipeline._generate

    async def replace_during_generation(*args):
        scene.image_url = "/api/files/manual.png"
        db_session.commit()
        return await original_generate(*args)

    monkeypatch.setattr(pipeline, "_generate", replace_during_generation)
    with pytest.raises(RuntimeError, match="用户替换"):
        await pipeline.run_scene_quality_pipeline(db_session, task, scene, object())
    assert scene.image_url == "/api/files/manual.png"
    assert generated.await_count == 1


def test_previous_scene_review_still_blocks_while_new_task_is_running(db_session):
    scene, task = _fixture(db_session)
    task.result_url = scene.image_url
    task.status = "completed"
    db_session.add(ImageQualityReview(task_id=task.id, status="success", overall="FAIL",
        input_snapshot_json=json.dumps({"generated_image": scene.image_url}),
        dimensions_json=json.dumps({"CHARACTER_COUNT": {"status": "FAIL"}})))
    db_session.add(Task(id="new-scene-task", type="scene_image", name="再次生成",
                        scene_id=scene.id, novel_id=task.novel_id, status="running"))
    scene.scene_task_id = "new-scene-task"
    db_session.commit()
    assert scene_reference_review_status(db_session, scene)[0] is False


def test_running_scene_can_be_reviewed_before_publication(db_session):
    scene, task = _fixture(db_session)
    task.result_url = "/api/files/staged.png"
    task.prompt_text = "Empty environment with zero people"
    db_session.commit()
    snapshot = build_review_input(task, generation_review=True)
    assert snapshot["generated_image"] == "/api/files/staged.png"
    assert "必须为 0" in snapshot["target"]["authority_note"]
    assert scene.image_url == "/api/files/old.png"
