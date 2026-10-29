"""Image reviews use registered prompts and never change generation state."""
import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest
from sqlalchemy.orm import sessionmaker

from app.models.prompt_template import PromptTemplate
from app.models.novel import Novel, Character, Prop
from app.models.task import Task
from app.models.system_config import SystemConfig
from app.services.image_quality_review import DIMENSIONS, build_review_input, create_image_review, current_image_reviews, normalize_review_response, review_image_task
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


def test_grid_panel_review_uses_its_own_template_and_panel_authority(db_session):
    general = PromptTemplate(id="general-review", name="通用评审", type="image_quality_review_prompt",
                             template="通用规则", is_system=True, is_active=True)
    grid = PromptTemplate(id="grid-review", name="子格评审", type="grid_panel_review_prompt",
                          template="本格焦点优先", is_system=True, is_active=True)
    novel = Novel(id="grid-review-novel", title="宫格评审", video_mode="grid")
    task = Task(id="grid-review-task", type="grid_panel_review", status="running",
                novel_id=novel.id, name="审核格 3", prompt_text="前景听众虚化，老翁清晰",
                result_url="/api/files/panel.png",
                metadata_json=json.dumps({"structured_target": {"panel": {
                    "index": 3, "characters": ["杜甫", "老翁"],
                    "camera": "focus_subject: 老翁；前景杜甫虚化"},
                    "speakers": ["老翁"], "offscreen_speakers": []}}, ensure_ascii=False))
    db_session.add_all([general, grid, novel, task])
    db_session.commit()

    review = create_image_review(db_session, task.id)
    snapshot = json.loads(review.input_snapshot_json)
    assert review.template_id == grid.id and review.template_text == "本格焦点优先"
    assert snapshot["target"]["grid_panel"]["panel"]["index"] == 3
    assert "Shot 角色表仅是全镜头背景" in snapshot["target"]["authority_note"]

    task.type = "keyframe_image"
    task.status = "completed"
    db_session.commit()
    assert create_image_review(db_session, task.id).template_id == general.id


@pytest.mark.parametrize("workflow_name,expected_mode", [
    ("Qwen image 2.1【四视图】", "four_view"),
    ("Z-image-turbo 单图生成", "single_view"),
    ("通用角色工作流", "unspecified"),
])
def test_character_review_carries_only_character_layout(db_session, workflow_name, expected_mode):
    task = Task(id="portrait-layout", type="character_portrait", status="completed",
                name="生成角色形象", workflow_name=workflow_name,
                prompt_text="single character, centered", result_url="/api/files/portrait.png")
    db_session.add(task)
    db_session.commit()
    snapshot = build_review_input(task)
    assert snapshot["target"]["character_portrait_layout"]["mode"] == expected_mode
    assert "同一角色的重复展示" in snapshot["target"]["character_portrait_layout"]["counting_rule"]
    task.type = "shot_image"
    db_session.commit()
    assert "character_portrait_layout" not in build_review_input(task)["target"]


def test_character_review_sends_layout_and_task_type_to_model(db_session):
    task = Task(id="portrait-review", type="character_portrait", status="completed",
                name="生成角色形象", workflow_name="Qwen image 2.1【四视图】",
                prompt_text="single character, centered", result_url="/api/files/portrait.png")
    db_session.add_all([task, PromptTemplate(id="portrait-template", name="评审", type="image_quality_review_prompt",
                                           template="按目标版式评审", is_system=True, is_active=True)])
    db_session.commit()
    calls = []

    class FakeLLM:
        provider, model = "test", "vision-test"

        async def chat_completion(self, **kwargs):
            calls.append(json.loads(kwargs["user_content"]))
            return {"success": True, "content": json.dumps({"overall": "PASS", "summary": "同一角色四视图",
                "dimensions": {name: {"status": "PASS", "summary": "符合要求"} for name in DIMENSIONS},
                "issues": []}, ensure_ascii=False)}

    with patch("app.services.image_quality_review.vision_proxy", side_effect=lambda url, **kw: {**kw, "url": url}), \
         patch("app.services.image_quality_review.LLMService", FakeLLM):
        review = asyncio.run(review_image_task(db_session, task.id))
    assert review.overall == "PASS"
    assert calls[0]["task_type"] == "character_portrait"
    assert calls[0]["target"]["character_portrait_layout"]["mode"] == "four_view"


def test_shot_review_uses_only_submitted_reference_slots_and_bindings(db_session, monkeypatch):
    from types import SimpleNamespace
    from app.services import shot_image_service

    novel = Novel(id="review-novel", title="参考图绑定")
    character = Character(id="review-character", novel_id=novel.id, name="甲", image_url="/api/files/char.png")
    prop = Prop(id="review-prop", novel_id=novel.id, name="王座", image_url="/api/files/prop.png")
    task = Task(id="shot-ref-task", type="shot_image", status="completed", name="生成主分镜图",
                novel_id=novel.id, prompt_text="甲坐在王座上", result_url="/api/files/generated.png")
    db_session.add_all([novel, character, prop, task])
    db_session.commit()

    monkeypatch.setattr(shot_image_service, "url_to_local_path", lambda url: url if url else None)
    monkeypatch.setattr(shot_image_service, "local_path_to_url", lambda path: f"/api/files/{path}")

    class FakeClient:
        async def upload_image(self, path):
            return {"success": path != "scene.png", "filename": path if path != "scene.png" else None}

    workflow = {key: {"inputs": {"image": ""}} for key in ("11", "22", "33")}
    mapping = {"character_reference_image_node_id": "11", "scene_reference_image_node_id": "22",
               "prop_reference_image_node_id": "33"}
    asyncio.run(shot_image_service._upload_references_and_update_workflow(
        SimpleNamespace(client=FakeClient()), workflow, mapping, "characters.png", "scene.png",
        task, db_session, task.id, prop_reference_paths={"王座": "prop.png"},
        character_names=["甲"], scene_name="宫殿", prop_names=["王座"],
    ))
    references = json.loads(task.reference_images)
    assert [item["picture"] for item in references] == [1, 3]
    assert references[0]["members"] == ["甲"]
    assert references[0]["sources"] == ["CHAR:review-character"]
    assert references[1]["sources"] == ["PROP:王座"]
    assert json.loads(task.workflow_json)["22"]["inputs"]["image"] == ""
    snapshot = build_review_input(task)
    assert [item["picture"] for item in snapshot["references"]] == [1, 3]
    assert snapshot["references"][0]["name"] == "角色合并图"
    assert snapshot["references"][1]["members"] == ["王座"]

    db_session.add(PromptTemplate(id="shot-ref-template", name="评审", type="image_quality_review_prompt",
                                  template="核对参考图来源", is_system=True, is_active=True))
    db_session.commit()
    calls = []

    class FakeLLM:
        provider, model = "test", "vision-test"

        async def chat_completion(self, **kwargs):
            calls.append(json.loads(kwargs["user_content"]))
            return {"success": True, "content": _response()}

    with patch("app.services.image_quality_review.vision_proxy", side_effect=lambda url, **kw: {**kw, "url": url}), \
         patch("app.services.image_quality_review.LLMService", FakeLLM):
        asyncio.run(review_image_task(db_session, task.id))
    assert [item["logical_id"] for item in calls[0]["images"]] == ["GENERATED_OUTPUT", "Picture1", "Picture3"]
    assert calls[0]["images"][1]["name"] == "角色合并图"
    assert calls[0]["images"][1]["members"] == ["甲"]
    assert calls[0]["images"][2]["sources"] == ["PROP:王座"]


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
    assert result["dimensions"]["CHARACTER_IDENTITY"]["original_status"] == "FAIL"
    assert result["issues"][0]["severity"] == "WARNING"
    assert result["issues"][0]["original_severity"] == "FAIL"


def _dimension_response(name, *, status="FAIL", severity="FAIL"):
    return json.dumps({"overall": "FAIL", "summary": f"{name} 需要处理",
        "dimensions": {key: {"status": status if key == name else "PASS", "summary": "原始模型判断"}
                       for key in DIMENSIONS},
        "issues": [{"type": name, "severity": severity, "expected": "预期", "observed": "实际",
                    "location": "画面中央", "evidence": "可见直接证据", "suggestion": "改进建议",
                    "visibility": "OBSERVED"}]}, ensure_ascii=False)


@pytest.mark.parametrize("name", ["CHARACTER_IDENTITY", "CHARACTER_COUNT", "HUMAN_ANATOMY"])
def test_core_dimension_fail_still_fails_overall(name):
    result = normalize_review_response(_dimension_response(name))
    assert result["overall"] == "FAIL"
    assert result["dimensions"][name]["status"] == "FAIL"
    assert result["issues"][0]["severity"] == "FAIL"


@pytest.mark.parametrize("name", ["ACTION_ACCURACY", "PROP_ACCURACY", "SCENE_CONSISTENCY"])
def test_noncore_fail_is_warning_with_original_judgment_and_description(name):
    result = normalize_review_response(_dimension_response(name))
    assert result["overall"] == "WARNING"
    assert result["dimensions"][name] == {"status": "WARNING", "original_status": "FAIL",
                                          "summary": "原始模型判断"}
    assert result["issues"][0]["severity"] == "WARNING"
    assert result["issues"][0]["original_severity"] == "FAIL"
    assert result["issues"][0]["observed"] == "实际"
    assert result["issues"][0]["suggestion"] == "改进建议"


def test_noncore_warning_never_masks_simultaneous_core_failure():
    data = json.loads(_dimension_response("CHARACTER_COUNT"))
    data["dimensions"]["ACTION_ACCURACY"]["status"] = "FAIL"
    data["issues"].append({**data["issues"][0], "type": "ACTION_ACCURACY"})
    result = normalize_review_response(json.dumps(data, ensure_ascii=False))
    assert result["overall"] == "FAIL"
    assert result["dimensions"]["CHARACTER_COUNT"]["status"] == "FAIL"
    assert result["dimensions"]["ACTION_ACCURACY"]["status"] == "WARNING"


@pytest.mark.parametrize("name,visibility,observed,expected", [
    ("CHARACTER_IDENTITY", "UNCERTAIN", "远景人物面容不可辨认", "WARNING"),
    ("CHARACTER_IDENTITY", "OCCLUDED", "人物面部部分被遮挡", "WARNING"),
    ("CHARACTER_COUNT", "UNCERTAIN", "无法确认远景是否缺少一人", "WARNING"),
    ("CHARACTER_COUNT", "OBSERVED", "画面右侧明确多出一人", "FAIL"),
    ("CHARACTER_IDENTITY", "OBSERVED", "两名角色的脸和服装身份明显交换", "FAIL"),
    ("HUMAN_ANATOMY", "OBSERVED", "画面中央人物清楚可见第三只手", "FAIL"),
    ("ACTION_ACCURACY", "OBSERVED", "动作与提示词不完全一致", "WARNING"),
    ("PROP_ACCURACY", "OBSERVED", "道具颜色偏差", "WARNING"),
    ("SCENE_CONSISTENCY", "OBSERVED", "背景布局偏差", "WARNING"),
])
def test_review_requires_observable_core_error_for_fail(name, visibility, observed, expected):
    data = json.loads(_dimension_response(name))
    data["issues"][0].update(visibility=visibility, observed=observed)
    result = normalize_review_response(json.dumps(data, ensure_ascii=False))
    assert result["overall"] == expected
    assert result["dimensions"][name]["status"] == expected


def test_noncore_review_keeps_raw_llm_result_and_generated_image(db_session):
    task = _task(db_session)
    db_session.add(PromptTemplate(id="system-review", name="AI 图片质量评审", type="image_quality_review_prompt",
                                  template="系统版本", is_system=True, is_active=True))
    db_session.commit()
    original = _dimension_response("ACTION_ACCURACY")

    class FakeLLM:
        provider, model = "test", "vision-test"

        async def chat_completion(self, **kwargs):
            return {"success": True, "content": original, "log_id": None}

    with patch("app.services.image_quality_review.vision_proxy", side_effect=lambda url, **kw: {**kw, "url": url}), \
         patch("app.services.image_quality_review.LLMService", FakeLLM):
        review = asyncio.run(review_image_task(db_session, task.id))
    db_session.refresh(task)
    assert review.status == "success" and review.overall == "WARNING"
    assert review.raw_response == original
    assert json.loads(review.dimensions_json)["ACTION_ACCURACY"]["status"] == "WARNING"
    assert json.loads(review.issues_json)[0]["suggestion"] == "改进建议"
    assert current_image_reviews(db_session, [{"taskId": task.id, "imageUrl": task.result_url}])[0]["qualityStatus"] == "WARNING"
    assert task.status == "completed" and task.result_url == "/api/files/generated.png"


def test_all_clear_result_is_pass():
    raw = json.dumps({"overall": "PASS", "summary": "符合要求", "dimensions": {
        name: {"status": "PASS", "summary": "可见证据符合要求"} for name in DIMENSIONS}, "issues": []}, ensure_ascii=False)
    result = normalize_review_response(raw)
    assert result["overall"] == "PASS" and result["issues"] == []


def _count_response(status, *, issue=None, identity_uncertain=False):
    dimensions = {name: {"status": "PASS", "summary": "已检查"} for name in DIMENSIONS}
    dimensions["CHARACTER_COUNT"] = {"status": status, "summary": "预期四人，按可确认轮廓计数"}
    issues = []
    if issue:
        issues.append({"type": "CHARACTER_COUNT", "severity": "FAIL",
                       "expected": "画面应有四名人物", "observed": issue[0],
                       "location": "画面前景与远景", "evidence": issue[1],
                       "suggestion": "核对人数", "visibility": issue[2]})
    if identity_uncertain:
        dimensions["CHARACTER_IDENTITY"] = {"status": "WARNING", "summary": "面容无法辨认"}
        issues.append({"type": "CHARACTER_IDENTITY", "severity": "WARNING",
                       "expected": "身份与参考图一致", "observed": "远景面容不清",
                       "location": "远景", "evidence": "无法核验面容细节",
                       "suggestion": "人工复核身份", "visibility": "UNCERTAIN"})
    return json.dumps({"overall": status, "summary": "人物数量核对", "dimensions": dimensions,
                       "issues": issues}, ensure_ascii=False)


@pytest.mark.parametrize("status,issue,expected", [
    ("PASS", None, "PASS"),
    ("FAIL", ("可确认五名人物", "五个独立头部及连贯身体轮廓彼此分离", "OBSERVED"), "FAIL"),
    ("PASS", ("疑似第五人", "远景候选轮廓与家具重叠，无法可靠分离", "OBSERVED"), "WARNING"),
    ("WARNING", ("疑似第五人", "远景候选轮廓与家具重叠，无法可靠分离", "OBSERVED"), "WARNING"),
    ("FAIL", ("远景人数不明", "人物身体被织机遮挡", "OCCLUDED"), "WARNING"),
    ("FAIL", ("明确只有三人", "三个独立人物完整可见，第四人应在无遮挡区域却不存在", "OBSERVED"), "FAIL"),
])
def test_character_count_requires_consistent_clear_evidence(status, issue, expected):
    result = normalize_review_response(_count_response(status, issue=issue))
    assert result["overall"] == expected
    assert result["dimensions"]["CHARACTER_COUNT"]["status"] == expected


def test_unclear_identity_does_not_override_clear_count_evidence():
    raw = _count_response("FAIL", issue=("可确认五名人物", "五个独立人物轮廓清楚分离", "OBSERVED"),
                          identity_uncertain=True)
    result = normalize_review_response(raw)
    assert result["overall"] == "FAIL"
    assert result["dimensions"]["CHARACTER_IDENTITY"]["status"] == "WARNING"
    assert result["dimensions"]["CHARACTER_COUNT"]["status"] == "FAIL"


def test_shot12_state7_original_review_replay_keeps_clear_count_fail():
    raw = (Path(__file__).parent / "fixtures/shot12_state7_count_review.json").read_text()
    result = normalize_review_response(raw)
    assert result["overall"] == "FAIL"
    assert result["dimensions"]["CHARACTER_COUNT"]["status"] == "FAIL"


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
