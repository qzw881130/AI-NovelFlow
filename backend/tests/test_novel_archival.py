from app.models.llm_log import LLMLog
from app.models.novel import Chapter, Novel
from app.models.shot import Shot


def test_archive_and_restore_novel_filters_token_usage(client, db_session):
    active = Novel(id="active-novel", title="活动小说")
    archived = Novel(id="archived-novel", title="归档小说", is_archived=True)
    archived_chapter = Chapter(id="archived-chapter", novel_id=archived.id, number=1, title="第一章")
    archived_shot = Shot(id="archived-shot", chapter_id=archived_chapter.id, index=1)
    db_session.add_all([active, archived, archived_chapter, archived_shot])
    db_session.add_all([
        LLMLog(id="active-log", provider="openai", model="test", user_prompt="a",
               novel_id=active.id, usage_metrics={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}),
        # The existing hierarchy resolves the novel from the Shot before filtering.
        LLMLog(id="archived-log", provider="openai", model="test", user_prompt="b",
               novel_id=active.id, shot_id=archived_shot.id,
               usage_metrics={"input_tokens": 20, "output_tokens": 5, "total_tokens": 25}),
        LLMLog(id="unassigned-log", provider="openai", model="test", user_prompt="c",
               usage_metrics={"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}),
    ])
    db_session.commit()

    novels = client.get("/api/novels/").json()["data"]
    assert {item["id"]: item["isArchived"] for item in novels if item["id"] in {active.id, archived.id}} == {
        active.id: False, archived.id: True,
    }

    def usage(scope=None):
        params = {"scope": scope} if scope else None
        response = client.get("/api/llm-logs/token-usage/hierarchy", params=params)
        assert response.status_code == 200
        return response.json()["data"]

    assert (usage()["total_tokens"], [n["id"] for n in usage()["novels"]]) == (15, [active.id])
    assert (usage("archived")["total_tokens"], [n["id"] for n in usage("archived")["novels"]]) == (25, [archived.id])
    assert usage("all")["total_tokens"] == 45
    assert any(node["id"] is None for node in usage("all")["novels"])

    response = client.patch(f"/api/novels/{active.id}/archive", json={"isArchived": True})
    assert response.status_code == 200
    assert response.json()["data"]["isArchived"] is True
    db_session.refresh(active)
    assert active.is_archived is True
    assert usage()["call_count"] == 0
    assert usage("archived")["total_tokens"] == 40

    response = client.patch(f"/api/novels/{active.id}/archive", json={"isArchived": False})
    assert response.status_code == 200
    assert response.json()["data"]["isArchived"] is False
    assert usage()["total_tokens"] == 15
    assert client.patch("/api/novels/missing/archive", json={"isArchived": True}).status_code == 404
    assert client.get("/api/llm-logs/token-usage/hierarchy?scope=invalid").status_code == 422
