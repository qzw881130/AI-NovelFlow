"""Main Shot image review/retry behavior without ComfyUI or a real LLM."""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.image_quality_review import ImageQualityReview
from app.models.background_job import BackgroundJob
from app.models.novel import Chapter, Novel
from app.models.prompt_template import PromptTemplate
from app.models.shot import Shot
from app.models.task import Task
from app.models.workflow import Workflow
from app.services import shot_image_service as images
from app.services.image_quality_review import DIMENSIONS
from app.services.task_service import TaskService
from app.api import shots as shot_api


def _review_response(verdict):
    issue = ({"type": "CHARACTER_COUNT", "severity": "FAIL", "expected": "两人",
              "observed": "画面右侧明确多出一人", "location": "画面右侧",
              "evidence": "可见第三个人物完整身体", "suggestion": "重生", "visibility": "OBSERVED"}
             if verdict == "FAIL" else None)
    return json.dumps({
        "overall": verdict, "summary": verdict,
        "dimensions": {name: {"status": verdict if name == "CHARACTER_COUNT" else "PASS", "summary": verdict}
                       for name in DIMENSIONS},
        "issues": [issue] if issue else [],
    }, ensure_ascii=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("review_results,expected_status,expected_count", [
    (["WARNING"], "WARNING", 1),
    (["FAIL", "FAIL", "PASS"], "PASS", 3),
    (["FAIL", "FAIL", "FAIL"], "FAIL", 3),
    (["ERROR"], "ERROR", 1),
])
async def test_primary_shot_image_reuses_workflow_and_reviews_each_attempt(
    db_session, db_engine, tmp_path, monkeypatch, review_results, expected_status, expected_count,
):
    novel = Novel(title="主分镜图")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="章")
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(chapter_id=chapter.id, index=1, description="两人站立", characters="[]", props="[]",
                image_status="generating")
    workflow = Workflow(type="shot", name="image", workflow_json="{}",
                        node_mapping=json.dumps({"save_image_node_id": "2"}))
    task = Task(type="shot_image", name="主分镜图", novel_id=novel.id, chapter_id=chapter.id,
                shot_id=shot.id, status="pending", prompt_text="原始提示词", workflow_id=workflow.id,
                metadata_json=json.dumps({"reference_manifest": [{"picture": 1, "url": "/api/files/reference.png",
                    "kind": "CHARACTER_IDENTITY", "sources": ["CHAR:甲"]}]}))
    db_session.add_all([shot, workflow, task, PromptTemplate(
        name="15", type="image_quality_review_prompt", template="原审核模板", is_system=True, is_active=True,
    )])
    db_session.flush()
    shot.image_task_id = task.id
    db_session.commit()

    queued_seeds = []

    class FakeBuilder:
        def build_shot_workflow(self, **kwargs):
            return {"1": {"class_type": "KSampler", "inputs": {"seed": 123}},
                    "2": {"class_type": "SaveImage", "inputs": {}}}

    class FakeComfyUI:
        def __init__(self):
            self.builder = FakeBuilder()

        async def generate_shot_image_with_workflow(self, **kwargs):
            graph = kwargs["workflow"]
            queued_seeds.append(graph["1"]["inputs"]["seed"])
            number = len(queued_seeds)
            kwargs["on_prompt_queued"](f"prompt-{number}", graph)
            return {"success": True, "image_url": f"mock://image-{number}",
                    "prompt_id": f"prompt-{number}", "submitted_workflow": graph}

    class FakeLLM:
        provider, model = "test", "vision"
        async def chat_completion(self, **kwargs):
            number = len(queued_seeds)
            verdict = review_results[number - 1]
            return ({"success": False, "error": "审核服务超时"} if verdict == "ERROR" else
                    {"success": True, "content": _review_response(verdict)})

    async def download_image(*, url, character_name, **kwargs):
        path = tmp_path / f"{character_name}.png"
        path.write_bytes(url.encode())
        return str(path)

    async def no_upload(*args, **kwargs):
        return None

    monkeypatch.setattr(images, "SessionLocal", sessionmaker(bind=db_engine))
    monkeypatch.setattr(images, "ComfyUIService", FakeComfyUI)
    monkeypatch.setattr(images, "get_style", lambda *args: ("", None))
    monkeypatch.setattr(images, "_upload_references_and_update_workflow", no_upload)
    monkeypatch.setattr(images.file_storage, "download_image", download_image)
    monkeypatch.setattr(images.file_storage, "base_dir", tmp_path)
    monkeypatch.setattr("app.services.image_quality_review.vision_proxy",
                        lambda url, **kwargs: {**kwargs, "url": url})
    monkeypatch.setattr("app.services.image_quality_review.LLMService", FakeLLM)

    await images.generate_shot_image_task(task.id, novel.id, chapter.id, 1, "原始提示词", workflow.id)
    db_session.expire_all()
    task = db_session.get(Task, task.id)
    shot = db_session.get(Shot, shot.id)
    quality = json.loads(task.metadata_json)["shot_image_quality"]
    reviews = db_session.query(ImageQualityReview).filter_by(task_id=task.id).all()

    assert task.status == shot.image_status == "completed"
    assert len(queued_seeds) == expected_count == len(reviews) == quality["generation_count"]
    assert len(set(queued_seeds)) == expected_count
    assert quality["status"] == expected_status
    assert len(quality["attempts"]) == expected_count
    assert shot.image_url == task.result_url == quality["attempts"][-1]["image_url"]
    assert json.loads(task.metadata_json)["reference_manifest"][0]["sources"] == ["CHAR:甲"]
    if expected_status == "FAIL":
        assert "需人工处理" in task.current_step
    if expected_status == "ERROR":
        assert reviews[0].status == "error" and "审核服务超时" in reviews[0].error_message


@pytest.mark.asyncio
async def test_batch_counts_quality_fail_separately_and_continues(db_session, db_engine, monkeypatch):
    novel = Novel(title="批量")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="章")
    db_session.add(chapter)
    db_session.flush()
    batch = Task(type="shot_image_batch", name="batch", status="pending", novel_id=novel.id,
                 chapter_id=chapter.id, metadata_json="{}")
    db_session.add(batch)
    db_session.flush()
    for index in range(1, 5):
        shot = Shot(chapter_id=chapter.id, index=index, description=f"Shot {index}")
        db_session.add(shot)
        db_session.flush()
        db_session.add(Task(type="shot_image", name=f"child {index}", status="completed" if index == 1 else "pending",
                            novel_id=novel.id, chapter_id=chapter.id, shot_id=shot.id,
                            parent_task_id=batch.id, batch_order=index,
                            metadata_json=json.dumps({"shot_image_quality": {"status": "FAIL"}} if index == 1 else {})))
    db_session.commit()

    async def prepare(**kwargs):
        child = kwargs["existing_task"]
        shot = kwargs["db"].get(Shot, child.shot_id)
        if shot.index == 3:
            raise ValueError("参考图缺失")
        child.status = "completed"
        child.metadata_json = json.dumps({"shot_image_quality": {"status": "PASS"}})
        kwargs["db"].commit()

    async def wait(db, child_id):
        return db.get(Task, child_id).status

    monkeypatch.setattr(shot_api, "SessionLocal", sessionmaker(bind=db_engine))
    monkeypatch.setattr(shot_api, "LLMService", lambda: SimpleNamespace())
    monkeypatch.setattr(shot_api, "_prepare_and_enqueue_shot_image_generation", prepare)
    monkeypatch.setattr(shot_api, "_wait_for_shot_image_child_task", wait)
    await shot_api.run_shot_image_batch_task(batch.id)
    db_session.expire_all()
    saved = db_session.get(Task, batch.id)
    assert saved.status == "failed"
    assert "成功 2，审核未通过 1，审核未完成 0，生成失败 1" in saved.current_step
    assert db_session.query(Task).filter_by(parent_task_id=batch.id, status="completed").count() == 3


@pytest.mark.asyncio
async def test_restart_finishes_staged_review_without_regenerating(db_session, db_engine, monkeypatch):
    novel = Novel(title="恢复")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="章")
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(chapter_id=chapter.id, index=1, description="人物", image_status="generating")
    db_session.add(shot)
    db_session.flush()
    task = Task(type="shot_image", name="主图", novel_id=novel.id, chapter_id=chapter.id,
                shot_id=shot.id, status="running", prompt_text="人物", result_url="/api/files/staged.png",
                comfyui_prompt_id="already-generated", metadata_json=json.dumps({
                    "shot_image_quality": {"generation_count": 1, "pending_review": True,
                                           "pending_image_path": None}}))
    db_session.add(task)
    db_session.flush()
    shot.image_task_id = task.id
    db_session.add(ImageQualityReview(task_id=task.id, trigger="generation", status="success",
                                      overall="PASS", input_snapshot_json=json.dumps({
                                          "generated_image": task.result_url})))
    db_session.commit()
    monkeypatch.setattr(images, "SessionLocal", sessionmaker(bind=db_engine))
    monkeypatch.setattr(images, "ComfyUIService", lambda: (_ for _ in ()).throw(AssertionError("不能重新生图")))

    await images.generate_shot_image_task(task.id, novel.id, chapter.id, 1, "人物", "unused")
    db_session.expire_all()
    saved_task, saved_shot = db_session.get(Task, task.id), db_session.get(Shot, shot.id)
    assert saved_task.status == saved_shot.image_status == "completed"
    assert saved_shot.image_url == "/api/files/staged.png"
    assert json.loads(saved_task.metadata_json)["shot_image_quality"]["generation_count"] == 1
    assert db_session.query(ImageQualityReview).filter_by(task_id=task.id).count() == 1


@pytest.mark.asyncio
async def test_reconciler_does_not_publish_before_durable_image_worker_review(db_session, monkeypatch):
    old = datetime.utcnow() - timedelta(minutes=3)
    task = Task(type="shot_image", name="主分镜图", status="running",
                comfyui_prompt_id="finished-prompt", started_at=old, updated_at=old)
    db_session.add(task)
    db_session.flush()
    db_session.add(BackgroundJob(task_id=task.id, queue_name="shot_image",
                                 handler="app.services.shot_image_service:generate_shot_image_task",
                                 payload_json="{}", status="running"))
    db_session.commit()
    service = TaskService(db_session)
    service.comfyui_service.get_queue_info = AsyncMock(return_value={})
    service.comfyui_service.client.get_prompt_state = AsyncMock(return_value={"state": "completed"})
    monkeypatch.setattr(service, "_recover_completed_shot_image_prompt",
                        AsyncMock(side_effect=AssertionError("评审前不得回写图片")))
    assert await service.reconcile_active_tasks([task], db=db_session) == 0
    service._recover_completed_shot_image_prompt.assert_not_awaited()
    assert task.status == "running"


@pytest.mark.asyncio
@pytest.mark.parametrize("final_verdict,batch_status", [("PASS", "completed"), ("FAIL", "failed")])
async def test_resumed_batch_waits_for_quality_retry_worker(db_session, db_engine, monkeypatch,
                                                            final_verdict, batch_status):
    novel = Novel(title="恢复批量")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="章")
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(chapter_id=chapter.id, index=1, description="人物")
    batch = Task(type="shot_image_batch", name="batch", status="running", novel_id=novel.id,
                 chapter_id=chapter.id, metadata_json="{}")
    db_session.add_all([shot, batch])
    db_session.flush()
    child = Task(type="shot_image", name="child", status="running", novel_id=novel.id,
                 chapter_id=chapter.id, shot_id=shot.id, parent_task_id=batch.id, batch_order=1,
                 metadata_json=json.dumps({"shot_image_quality": {"generation_count": 1,
                                                                  "retry_pending": True}}))
    db_session.add(child)
    db_session.commit()

    async def wait(db, child_id):
        resumed = db.get(Task, child_id)
        resumed.status = "completed"
        resumed.metadata_json = json.dumps({"shot_image_quality": {"generation_count": 2, "status": final_verdict}})
        db.commit()
        return "completed"

    monkeypatch.setattr(shot_api, "SessionLocal", sessionmaker(bind=db_engine))
    monkeypatch.setattr(shot_api, "_prepare_and_enqueue_shot_image_generation",
                        lambda **kwargs: (_ for _ in ()).throw(AssertionError("不能重新准备工作流")))
    monkeypatch.setattr(shot_api, "_wait_for_shot_image_child_task", wait)
    await shot_api.run_shot_image_batch_task(batch.id)
    db_session.expire_all()
    assert db_session.get(Task, batch.id).status == batch_status
    assert ("成功 1" if final_verdict == "PASS" else "审核未通过 1") in db_session.get(Task, batch.id).current_step
