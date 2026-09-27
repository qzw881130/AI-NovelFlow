import json

from app.models.novel import Character, Novel


def test_export_all_characters_only_includes_selected_novel(client, db_session):
    selected = Novel(title="测试小说", author="作者")
    other = Novel(title="其他小说")
    db_session.add_all([selected, other])
    db_session.flush()
    db_session.add_all([
        Character(
            novel_id=selected.id,
            name="主角",
            description="角色描述",
            appearance="角色外貌",
            voice_prompt="角色音色",
            reference_audio_url="/audio/hero.wav",
            image_url="/images/hero.png",
            generating_status="completed",
            portrait_task_id="portrait-task",
            start_chapter=1,
            end_chapter=9,
            is_incremental=True,
            is_narrator=False,
            source_range="1-9",
        ),
        Character(novel_id=selected.id, name="旁白", is_narrator=True),
        Character(novel_id=other.id, name="不应导出"),
    ])
    db_session.commit()

    response = client.get(f"/api/characters/export?novel_id={selected.id}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert f'filename="characters_{selected.id[:8]}.json"' in response.headers["content-disposition"]
    payload = json.loads(response.content)
    assert payload["version"] == 1
    assert payload["novel"] == {"id": selected.id, "title": "测试小说", "author": "作者"}
    assert payload["total"] == 2
    assert [item["name"] for item in payload["characters"]] == ["主角", "旁白"]
    assert payload["characters"][0]["appearance"] == "角色外貌"
    assert payload["characters"][0]["voicePrompt"] == "角色音色"
    assert payload["characters"][0]["portraitTaskId"] == "portrait-task"
    assert payload["characters"][1]["isNarrator"] is True


def test_export_characters_returns_404_for_unknown_novel(client):
    response = client.get("/api/characters/export?novel_id=missing")

    assert response.status_code == 404

