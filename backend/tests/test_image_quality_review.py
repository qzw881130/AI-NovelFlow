"""Image reviews use registered prompts and never change generation state."""
import asyncio
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch
from sqlalchemy.orm import sessionmaker

from app.models.prompt_template import PromptTemplate
from app.models.novel import Novel
from app.models.task import Task
from app.models.system_config import SystemConfig
from app.services.image_quality_review import DIMENSIONS, build_review_input, create_image_review, normalize_review_response, review_image_task
from app.services.prompt_template_service import PromptTemplateService


def _response(identity_status="FAIL", visibility="OBSERVED"):
    return json.dumps({
        "overall": identity_status,
        "summary": "人物身份需要核对",
        "dimensions": {name: {"status": identity_status if name == "CHARACTER_IDENTITY" else "PASS", "summary": "已检查"}
                       for name in DIMENSIONS},
        "issues": [{"type": "CHARACTER_IDENTITY", "severity": "FAIL", "expected": "骗子1、骗子2",
                    "observed": "角色脸部与绑定参考图明显不同", "location": "画面左侧人物",
                    "evidence": "对照 CHAR:骗子1、CHAR:骗子2 绑定参考图", "suggestion": "加强角色身份约束",
                    "visibility": visibility}],
    }, ensure_ascii=False)


def _task(db_session):
    task = Task(id="review-test", type="keyframe_image", status="completed", name="生成关键帧图片",
                prompt_text="骗子1蹲在箱旁，骗子2站在桌旁", result_url="/api/files/generated.png",
                reference_images=json.dumps([{"url": "/api/files/reference.png", "sources": ["CHAR:骗子1", "CHAR:骗子2"]}]),
                metadata_json=json.dumps({"reference_manifest": [{"picture": 1, "url": "/api/files/reference.png",
                    "kind": "CHARACTER_IDENTITY", "sources": ["CHAR:骗子1", "CHAR:骗子2"], "purpose": "双人身份参照"}],
                    "reference_selector_input": {"current_anchor": {"description": "骗子1、骗子2在箱子旁"}}}, ensure_ascii=False))
    db_session.add(task)
    db_session.commit()
    return task


def test_review_uses_active_template_and_preserves_task(db_session):
    task = _task(db_session)
    db_session.add(PromptTemplate(id="system-review", name="AI 图片质量评审", type="image_quality_review_prompt",
                                  template="系统版本", is_system=True, is_active=True))
    db_session.commit()
    service = PromptTemplateService(db_session)
    custom = service.copy_template("system-review")
    service.update_template(custom.id, template="用户修改后的版本")
    novel = Novel(title="评审小说", image_quality_review_prompt_template_id=custom.id)
    db_session.add(novel)
    db_session.flush()
    task.novel_id = novel.id
    db_session.commit()
    calls = []

    class FakeLLM:
        provider = "test"
        model = "vision-test"

        async def chat_completion(self, **kwargs):
            calls.append(kwargs)
            return {"success": True, "content": _response(), "log_id": None}

    with patch("app.services.image_quality_review.vision_proxy", side_effect=lambda url, **kw: {**kw, "url": "data:image/png;base64,AA=="}), \
         patch("app.services.image_quality_review.LLMService", FakeLLM):
        review = asyncio.run(review_image_task(db_session, task.id))
        assert review.status == "success"
        assert review.overall == "FAIL"
        assert review.template_text == "用户修改后的版本"
        assert calls[0]["system_prompt"] == "用户修改后的版本"
        assert len(calls[0]["images"]) == 2
        assert calls[0]["images"][1]["sources"] == ["CHAR:骗子1", "CHAR:骗子2"]
        assert build_review_input(task)["target"]["current_anchor"]["description"]
        custom.is_active = False
        db_session.commit()
        second = asyncio.run(review_image_task(db_session, task.id))
        assert second.template_text == "系统版本"
        assert calls[1]["system_prompt"] == "系统版本"
    db_session.refresh(task)
    assert task.status == "completed" and task.result_url == "/api/files/generated.png"


def test_novel_default_review_ignores_global_custom_version(db_session):
    task = _task(db_session)
    db_session.add(PromptTemplate(id="system-review", name="系统评审", type="image_quality_review_prompt",
                                  template="系统版本", is_system=True, is_active=True))
    db_session.commit()
    custom = PromptTemplateService(db_session).copy_template("system-review")
    PromptTemplateService(db_session).update_template(custom.id, template="全局当前自定义版本")
    novel = Novel(title="未选择评审模板")
    db_session.add(novel)
    db_session.flush()
    task.novel_id = novel.id
    db_session.commit()

    review = create_image_review(db_session, task.id)
    assert review.template_id == "system-review"
    assert review.template_text == "系统版本"


def test_uncertain_identity_is_warning():
    result = normalize_review_response(_response(visibility="OCCLUDED"))
    assert result["overall"] == "WARNING"
    assert result["dimensions"]["CHARACTER_IDENTITY"]["status"] == "WARNING"
    assert result["issues"][0]["severity"] == "WARNING"


def test_all_clear_result_is_pass():
    raw = json.dumps({"overall": "PASS", "summary": "符合要求", "dimensions": {
        name: {"status": "PASS", "summary": "可见证据符合要求"} for name in DIMENSIONS}, "issues": []}, ensure_ascii=False)
    result = normalize_review_response(raw)
    assert result["overall"] == "PASS" and result["issues"] == []


def test_llm_error_is_recorded_without_changing_generation(db_session):
    task = _task(db_session)
    db_session.add(PromptTemplate(id="system-review", name="AI 图片质量评审", type="image_quality_review_prompt",
                                  template="系统版本", is_system=True, is_active=True))
    db_session.commit()

    class FailingLLM:
        provider = "test"
        model = "vision-test"

        async def chat_completion(self, **kwargs):
            return {"success": False, "error": "provider unavailable", "log_id": "failed-log"}

    with patch("app.services.image_quality_review.vision_proxy", side_effect=lambda url, **kw: {**kw, "url": "data:image/png;base64,AA=="}), \
         patch("app.services.image_quality_review.LLMService", FailingLLM):
        review = asyncio.run(review_image_task(db_session, task.id))
    db_session.refresh(task)
    assert review.status == "error" and review.llm_log_id == "failed-log"
    assert task.status == "completed" and task.result_url == "/api/files/generated.png"


def test_prompt_management_and_review_history_api(client, db_session):
    templates = client.get("/api/prompt-templates/?type=image_quality_review_prompt").json()["data"]
    assert len(templates) == 1 and templates[0]["template"].startswith("你是 NovelFlow 的 AI 图片质量评审员")
    copied = client.post(f"/api/prompt-templates/{templates[0]['id']}/copy").json()["data"]
    changed = client.put(f"/api/prompt-templates/{copied['id']}", json={
        "name": "AI 图片质量评审自定义", "description": "测试", "template": "已修改的评审系统提示词",
        "type": "image_quality_review_prompt",
    })
    assert changed.status_code == 200
    effective = client.get("/api/prompt-templates/image-quality-review/effective").json()["data"]
    assert effective["template"] == "已修改的评审系统提示词"
    second = client.post(f"/api/prompt-templates/{templates[0]['id']}/copy").json()["data"]
    assert client.put(f"/api/prompt-templates/{second['id']}", json={
        "name": "另一个自定义评审", "description": "测试", "template": "另一个评审提示词",
        "type": "image_quality_review_prompt",
    }).status_code == 200
    db_session.expire_all()
    assert db_session.get(PromptTemplate, copied["id"]).is_active
    assert db_session.get(PromptTemplate, second["id"]).is_active
    assert client.post("/api/prompt-templates/image-quality-review/restore-default").status_code == 404
    task = _task(db_session)
    assert client.get(f"/api/tasks/{task.id}/image-reviews").json()["data"] == []


def test_automatic_review_is_off_until_enabled(db_session):
    from app.services.image_review_worker import enqueue_automatic_review, process_review_queue
    task = _task(db_session)
    db_session.add(PromptTemplate(id="system-review", name="评审", type="image_quality_review_prompt",
                                  template="系统版本", is_system=True, is_active=True))
    selected = PromptTemplate(id="custom-review", name="自定义评审", type="image_quality_review_prompt",
                              template="自定义版本", is_system=False, is_active=True)
    novel = Novel(title="已选择评审模板", image_quality_review_prompt_template_id=selected.id)
    db_session.add_all([selected, novel])
    db_session.flush()
    task.novel_id = novel.id
    config = SystemConfig(id="default", auto_image_review_enabled=False)
    db_session.add(config)
    db_session.commit()
    with patch("app.services.image_review_worker.execute_image_review", new_callable=AsyncMock) as execute:
        assert enqueue_automatic_review(db_session, task.id) is None
        asyncio.run(process_review_queue(db_session))
        execute.assert_not_called()
        config.auto_image_review_enabled = True
        db_session.commit()
        queued = enqueue_automatic_review(db_session, task.id)
        assert queued.status == "pending" and queued.trigger == "automatic"
        assert queued.template_id == selected.id
        assert queued.template_text == "自定义版本"
        assert enqueue_automatic_review(db_session, task.id).id == queued.id
        asyncio.run(process_review_queue(db_session))
        execute.assert_awaited_once_with(db_session, queued.id)
