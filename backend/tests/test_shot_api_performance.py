"""Chapter summary must keep navigation state without transferring execution history."""
import json

from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.task import Task


def test_summary_projection_preserves_detail_and_compresses_reads(client, db_session):
    novel = Novel(id="perf-novel", title="Performance")
    chapter = Chapter(id="perf-chapter", novel_id=novel.id, number=1, title="Chapter")
    plan = {
        "clip_plan_revision": 3,
        "clip_plan": [{"clip_index": 1, "status": "COMPLETED", "prompt_text": "secret clip prompt"}],
        "ai_calls": [{"step": "prompt", "final_prompt": "secret llm prompt"}],
        "window_plans": [{"window_index": 1, "prompt_text": "secret legacy prompt"}],
    }
    shots = [Shot(
        id=f"perf-shot-{index}", chapter_id=chapter.id, index=index,
        description=f"Shot {index}", duration=4, image_status="completed",
        video_director_plan=json.dumps(plan),
    ) for index in range(1, 3)]
    db_session.add_all([novel, chapter, *shots])
    db_session.commit()
    path = f"/api/novels/{novel.id}/chapters/{chapter.id}/shots"

    summary = client.get(path, params={"summary": "true", "include_ai_history": "false"}, headers={"Accept-Encoding": "gzip"})
    assert summary.status_code == 200
    assert summary.headers["Content-Encoding"] == "gzip"
    assert "db;dur=" in summary.headers["Server-Timing"]
    listed = summary.json()["data"]
    assert [shot["id"] for shot in listed] == [shot.id for shot in shots]
    assert all(shot["summaryOnly"] for shot in listed)
    assert listed[0]["videoDirectorPlan"]["clip_plan"][0]["status"] == "COMPLETED"
    assert "secret" not in summary.text

    detail = client.get(f"{path}/{shots[0].id}", headers={"Accept-Encoding": "gzip"})
    assert detail.status_code == 200
    assert detail.headers["Content-Encoding"] == "gzip"
    assert detail.json()["data"]["summaryOnly"] is False
    assert detail.json()["data"]["videoDirectorPlan"]["ai_calls"][0]["final_prompt"] == "secret llm prompt"
    assert json.loads(db_session.get(Shot, shots[0].id).video_director_plan) == plan

    legacy = client.get(path)
    assert legacy.status_code == 200
    assert legacy.json()["data"][0]["summaryOnly"] is False
    assert legacy.json()["data"][0]["videoDirectorPlan"]["ai_calls"][0]["final_prompt"] == "secret llm prompt"


def test_chapter_active_task_probe_excludes_history(client, db_session):
    novel = Novel(id="active-probe-novel", title="Performance")
    chapter = Chapter(id="active-probe-chapter", novel_id=novel.id, number=1, title="Chapter")
    db_session.add_all([
        novel, chapter,
        Task(id="historical-task", type="shot_video", status="completed", name="Old", novel_id=novel.id, chapter_id=chapter.id),
        Task(id="active-task", type="shot_video", status="running", name="Current", novel_id=novel.id, chapter_id=chapter.id),
    ])
    db_session.commit()
    response = client.get("/api/tasks/", params={"chapter_id": chapter.id, "active_only": "true", "limit": 1})
    assert response.status_code == 200
    assert [task["id"] for task in response.json()["data"]] == ["active-task"]
