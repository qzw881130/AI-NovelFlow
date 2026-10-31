import json
from io import BytesIO
from zipfile import ZipFile
from sqlalchemy import text

from app.main import backfill_llm_log_shot_ids
from app.models.llm_log import LLMLog
from app.models.novel import Novel, Chapter
from app.models.shot import Shot


def test_grid_log_types_are_labeled_filterable_and_exportable_without_hiding_history(client, db_session):
    novel = Novel(id="grid-novel", title="宫格小说")
    chapter = Chapter(id="grid-chapter", novel_id=novel.id, number=1, title="黄昏投宿")
    shot = Shot(id="grid-shot", chapter_id=chapter.id, index=2)
    db_session.add_all([novel, chapter, shot])
    grid_types = {
        "grid_shot_plan": "shot_planning",
        "grid_image_prompt": "shot_image",
        "grid_clip_plan": "video_director",
        "grid_h3_phase_b": "video_generation",
    }
    for task_type in grid_types:
        db_session.add(LLMLog(
            id=task_type, provider="openai", model="test", user_prompt=task_type,
            task_type=task_type, status="success", novel_id=novel.id,
            chapter_id=chapter.id, shot_id=shot.id,
            prompt_template_name=f"测试-{task_type}",
        ))
    retired_types = {"h3_multi_keyframe_prompt", "h3_execution_optimizer_prompt", "h3_preflight_repair_prompt"}
    for task_type in retired_types:
        db_session.add(LLMLog(
            id=task_type, provider="openai", model="test", user_prompt="旧提示词",
            task_type=task_type, status="success", novel_id=novel.id,
            chapter_id=chapter.id, shot_id=shot.id,
        ))
    db_session.commit()

    options = set(client.get("/api/llm-logs/filters").json()["data"]["task_types"])
    assert grid_types.keys() <= options
    assert not retired_types & options
    for task_type, category in grid_types.items():
        response = client.get("/api/llm-logs/", params={"category": category, "novel_id": novel.id})
        assert response.status_code == 200
        item = next(item for item in response.json()["data"]["items"] if item["id"] == task_type)
        assert (item["novel_title"], item["chapter_number"], item["shot_index"]) == ("宫格小说", 1, 2)
        assert client.get(f"/api/llm-logs/{task_type}").status_code == 200

    # Removing retired types from new filter choices must not make stored calls unreadable.
    old_type = "h3_preflight_repair_prompt"
    old_response = client.get("/api/llm-logs/", params={"task_type": old_type, "novel_id": novel.id})
    assert [item["id"] for item in old_response.json()["data"]["items"]] == [old_type]
    assert client.get(f"/api/llm-logs/{old_type}").status_code == 200

    export = client.post("/api/llm-logs/export-selected", json={"ids": ["grid_h3_phase_b", old_type]})
    assert export.status_code == 200
    with ZipFile(BytesIO(export.content)) as archive:
        names = archive.namelist()
        assert len(names) == 2
        assert any("宫格 H3 六段式提示词" in name for name in names)
        assert any("Preflight 自动修复" in name for name in names)


def test_subtitle_correction_logs_are_filterable_as_video_subtitles(client, db_session):
    db_session.add_all([
        LLMLog(id="subtitle-log", provider="openai", model="test", user_prompt="字幕",
               task_type="subtitle_correction", status="success"),
        LLMLog(id="translation-log", provider="openai", model="test", user_prompt="翻译",
               task_type="subtitle_translation", status="success"),
        LLMLog(id="other-log", provider="openai", model="test", user_prompt="其他",
               task_type="parse_scenes", status="success"),
    ])
    db_session.commit()
    response = client.get("/api/llm-logs/?category=video_subtitles")
    assert response.status_code == 200
    assert {item["id"] for item in response.json()["data"]["items"]} == {"subtitle-log", "translation-log"}
    assert "subtitle_correction" in client.get("/api/llm-logs/filters").json()["data"]["task_types"]
    assert "subtitle_translation" in client.get("/api/llm-logs/filters").json()["data"]["task_types"]


def test_token_hierarchy_counts_each_call_once_and_marks_missing_usage(client, db_session):
    novel = Novel(id="novel-a", title="测试小说")
    chapter = Chapter(id="chapter-a", novel_id=novel.id, number=3, title="重逢")
    shot = Shot(id="shot-a", chapter_id=chapter.id, index=7)
    db_session.add_all([novel, chapter, shot])
    db_session.add_all([
        LLMLog(id="a", provider="openai", model="test", user_prompt="x", status="success",
               novel_id=novel.id, chapter_id=chapter.id, shot_id=shot.id,
               usage_metrics={"input_tokens": 100, "output_tokens": 30, "total_tokens": 130}),
        LLMLog(id="b", provider="openai", model="test", user_prompt="y", status="error",
               novel_id=novel.id, chapter_id=chapter.id, shot_id=shot.id),
        LLMLog(id="c", provider="openai", model="test", user_prompt="z", status="success",
               novel_id=novel.id, chapter_id=chapter.id,
               usage_metrics={"input_tokens": 20, "output_tokens": 10}),
        LLMLog(id="d", provider="openai", model="test", user_prompt="w", status="success",
               novel_id=novel.id, usage_metrics={"total_tokens": 9}),
    ])
    db_session.commit()

    response = client.get("/api/llm-logs/token-usage/hierarchy")
    assert response.status_code == 200
    data = response.json()["data"]
    assert (data["call_count"], data["total_tokens"], data["missing_usage_count"]) == (4, 169, 1)
    assert data["partial_usage_count"] == 1
    novel_data = data["novels"][0]
    assert novel_data["label"] == "测试小说"
    chapter_data = next(item for item in novel_data["chapters"] if item["id"] == chapter.id)
    assert (chapter_data["call_count"], chapter_data["total_tokens"]) == (3, 160)
    shot_data = next(item for item in chapter_data["shots"] if item["id"] == shot.id)
    assert (shot_data["call_count"], shot_data["total_tokens"], shot_data["missing_usage_count"]) == (2, 130, 1)

    list_response = client.get("/api/llm-logs/")
    listed = next(item for item in list_response.json()["data"]["items"] if item["id"] == "a")
    assert (listed["novel_title"], listed["chapter_number"], listed["shot_index"]) == ("测试小说", 3, 7)


def test_legacy_shot_backfill_requires_structured_matching_existing_shot(db_engine):
    with db_engine.begin() as conn:
        conn.execute(text("INSERT INTO novels (id, title) VALUES ('novel-a', '测试小说')"))
        conn.execute(text("INSERT INTO chapters (id, novel_id, number, title) VALUES ('chapter-a', 'novel-a', 1, '第一章')"))
        conn.execute(text("INSERT INTO shots (id, chapter_id, \"index\") VALUES ('shot-a', 'chapter-a', 1)"))
        for log_id, novel_id, prompt in [
            ("valid", "novel-a", json.dumps({"shot": {"id": "shot-a"}})),
            ("prefixed", "novel-a", "请参考以下数据：\n" + json.dumps({"shot": {"id": "shot-a"}})),
            ("review-linked", "novel-a", "图片评审"),
            ("metadata-linked", "novel-a", "执行提示词优化"),
            ("conflict", "another-novel", json.dumps({"shot": {"id": "shot-a"}})),
            ("text-only", "novel-a", "Shot shot-a"),
        ]:
            conn.execute(text("INSERT INTO llm_logs (id, provider, model, user_prompt, novel_id) "
                              "VALUES (:id, 'openai', 'test', :prompt, :novel_id)"),
                         {"id": log_id, "prompt": prompt, "novel_id": novel_id})
        conn.execute(text("INSERT INTO tasks (id, type, name, shot_id, metadata_json) "
                          "VALUES ('task-a', 'shot_image', '生成图片', 'shot-a', :metadata)"),
                     {"metadata": json.dumps({"optimizer": {"llm_log_id": "metadata-linked"}})})
        conn.execute(text("INSERT INTO image_quality_reviews (id, task_id, status, trigger, llm_log_id) "
                          "VALUES ('review-a', 'task-a', 'completed', 'manual', 'review-linked')"))
        backfill_llm_log_shot_ids(conn)
        backfill_llm_log_shot_ids(conn)
        rows = {row.id: row for row in conn.execute(text(
            "SELECT id, chapter_id, shot_id FROM llm_logs"
        )).all()}
    assert (rows["valid"].chapter_id, rows["valid"].shot_id) == ("chapter-a", "shot-a")
    assert all(rows[key].shot_id == "shot-a" for key in ("prefixed", "review-linked", "metadata-linked"))
    assert rows["conflict"].shot_id is None
    assert rows["text-only"].shot_id is None
