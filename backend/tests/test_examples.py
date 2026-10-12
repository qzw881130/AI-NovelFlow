"""示例预览与事务导入使用隔离的内存数据库。"""
from unittest.mock import Mock

from app.constants.examples import EXAMPLES
from app.models.novel import Novel, Chapter, Character, Scene, Prop
from app.models.shot import Shot
from app.models.task import Task
from app.services.business_events import safe_details
from app.services.notification_registry import EVENT_REGISTRY


def test_examples_preview_import_and_defaults(client, db_session, monkeypatch):
    events = Mock()
    monkeypatch.setattr("app.api.examples.publish", events)
    listed = client.get("/api/examples/")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["data"]] == list(EXAMPLES)

    formal = client.post("/api/novels/", json={"title": "默认设置对照"})
    assert formal.status_code == 200
    reference = db_session.get(Novel, formal.json()["data"]["id"])
    imported_ids = []
    for example_id, example in EXAMPLES.items():
        preview = client.get(f"/api/examples/{example_id}/")
        assert preview.status_code == 200
        source = preview.json()["data"]
        assert source["chapterCount"] == len(example["chapters"])
        assert source["chapters"] == [
            {"number": i, "title": chapter["title"], "content": chapter["content"]}
            for i, chapter in enumerate(example["chapters"], 1)
        ]

        result = client.post(f"/api/examples/{example_id}/import/")
        assert result.status_code == 200, result.text
        novel_id = result.json()["data"]["novel_id"]
        imported_ids.append(novel_id)
        novel = db_session.get(Novel, novel_id)
        assert novel.title == source["title"]
        assert novel.description == source["description"]
        assert novel.chapter_count == len(source["chapters"])
        for attr in (
            "status", "is_preset", "aspect_ratio", "prompt_template_id", "style_prompt_template_id",
            "story_world_context", "story_world_context_locked", "story_world_context_prompt_template_id",
            "character_parse_prompt_template_id", "scene_parse_prompt_template_id", "prop_parse_prompt_template_id",
            "video_mode_recommender_prompt_template_id", "keyframe_planner_prompt_template_id",
            "h3_single_frame_prompt_template_id", "h3_first_last_frame_prompt_template_id",
        ):
            assert getattr(novel, attr) == getattr(reference, attr), attr
        chapters = db_session.query(Chapter).filter_by(novel_id=novel_id).order_by(Chapter.number).all()
        assert [(chapter.number, chapter.title, chapter.content) for chapter in chapters] == [
            (chapter["number"], chapter["title"], chapter["content"]) for chapter in source["chapters"]
        ]
        assert all(chapter.status == "pending" and chapter.progress == 0 and chapter.parsed_data is None for chapter in chapters)
        for model in (Character, Scene, Prop, Task):
            assert db_session.query(model).filter_by(novel_id=novel_id).count() == 0
        assert db_session.query(Shot).filter(Shot.chapter_id.in_([chapter.id for chapter in chapters])).count() == 0

    duplicate = client.post("/api/examples/xiaoma/import/")
    assert duplicate.status_code == 200
    duplicate_id = duplicate.json()["data"]["novel_id"]
    assert duplicate_id not in imported_ids
    assert db_session.query(Chapter).filter_by(novel_id=imported_ids[0]).count() == 8
    assert db_session.query(Chapter).filter_by(novel_id=duplicate_id).count() == 8
    assert events.call_count == 4
    assert all(call.args[0] == "example.import.completed" for call in events.call_args_list)
    assert all(call.args[1]["status"] == "SUCCESS" for call in events.call_args_list)
    assert {"example.import.completed", "example.import.failed"} <= set(EVENT_REGISTRY)
    assert safe_details({"example_id": "xiaoma", "chapter_count": 8, "duration_ms": 5}) == {
        "example_id": "xiaoma", "chapter_count": 8, "duration_ms": 5,
    }


def test_example_import_rolls_back_on_chapter_commit_failure(client, db_session, monkeypatch):
    events = Mock()
    monkeypatch.setattr("app.api.examples.publish", events)
    before = db_session.query(Novel).count()
    original_commit = db_session.commit

    def fail_commit():
        raise RuntimeError("模拟章回写入失败")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    result = client.post("/api/examples/xiaoma/import/")
    monkeypatch.setattr(db_session, "commit", original_commit)
    assert result.status_code == 500
    assert "模拟章回写入失败" in result.json()["detail"]
    assert db_session.query(Novel).count() == before
    assert events.call_args.args[0] == "example.import.failed"


def test_unknown_example_does_not_create_novel(client, db_session, monkeypatch):
    monkeypatch.setattr("app.api.examples.publish", Mock())
    before = db_session.query(Novel).count()
    assert client.get("/api/examples/missing/").status_code == 404
    assert client.post("/api/examples/missing/import/").status_code == 404
    assert db_session.query(Novel).count() == before


def test_event_failure_does_not_undo_import(client, db_session, monkeypatch):
    def fail_event(*_args, **_kwargs):
        raise RuntimeError("事件中心不可用")

    monkeypatch.setattr("app.api.examples.publish", fail_event)
    result = client.post("/api/examples/emperor/import/")
    assert result.status_code == 200
    novel_id = result.json()["data"]["novel_id"]
    assert db_session.query(Chapter).filter_by(novel_id=novel_id).count() == 5
