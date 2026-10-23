"""Task status reads must not load execution blobs or change task history."""
import json

from sqlalchemy import event

from app.models.task import Task


def test_task_status_projection_and_full_detail_remain_compatible(client, db_session, db_engine):
    metadata = {
        "execution_scope": "CLIP", "clip_index": 2, "clip_plan_revision": 4,
        "approval_status": "APPROVED", "video_reference_manifest": {"references": [{"slot": 1}]},
        "physical_output": {"physical_output_role": "NATIVE_CONTINUITY_OUTPUT", "output_node_id": "65"},
        "comfyui_error": {"error_code": "HTTP_ERROR", "stage": "submit", "underlying_error": "failed"},
        "h3_prompt_optimizer": {"raw_response": "large-secret" * 30000},
    }
    task = Task(
        id="task-perf-recovered", type="shot_video", status="completed", name="Recovered C2",
        novel_id="novel", chapter_id="chapter", shot_id="shot", result_url="/video.mp4",
        source_task_id="prior-attempt", comfyui_prompt_id="prompt-123",
        metadata_json=json.dumps(metadata), workflow_json="workflow-secret" * 1000,
        prompt_text="prompt-secret" * 1000, error_message="original error",
        reference_images=json.dumps([{"url": "/reference.png", "label": "source"}]),
    )
    failed = Task(id="task-perf-failed", type="shot_video", status="failed", name="Failed",
                  chapter_id="chapter", shot_id="shot", error_message="visible failure")
    running = Task(id="task-perf-running", type="shot_video", status="running", name="Running",
                   chapter_id="chapter", shot_id="shot", progress=57)
    cancelled = Task(id="task-perf-cancelled", type="shot_video", status="cancelled", name="Cancelled",
                     chapter_id="chapter", shot_id="shot", source_task_id=task.id)
    db_session.add_all([task, failed, running, cancelled])
    db_session.commit()

    statements = []
    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.lower())

    event.listen(db_engine, "before_cursor_execute", capture)
    try:
        status = client.get("/api/tasks/", params={"chapter_id": "chapter", "status_only": "true"})
        summary = client.get("/api/tasks/", params={"chapter_id": "chapter", "summary": "true"})
        one = client.get(f"/api/tasks/{task.id}", params={"summary": "true"})
    finally:
        event.remove(db_engine, "before_cursor_execute", capture)

    assert status.status_code == summary.status_code == one.status_code == 200
    assert "db;dur=" in status.headers["Server-Timing"]
    assert len(status.json()["data"]) == 4
    assert all("clipExecution" not in row for row in status.json()["data"])
    assert "large-secret" not in status.text + summary.text + one.text
    assert "workflow-secret" not in status.text + summary.text + one.text
    assert "prompt-secret" not in status.text + summary.text + one.text
    assert not any("select tasks.metadata_json" in query or "select tasks.workflow_json" in query for query in statements)
    projected = one.json()["data"]
    assert projected["sourceTaskId"] == "prior-attempt"
    assert projected["comfyuiPromptId"] == "prompt-123"
    assert projected["ordinaryReferenceCount"] == 1
    assert projected["clipExecution"]["clip_index"] == 2
    assert projected["comfyuiError"]["error_code"] == "HTTP_ERROR"
    assert next(row for row in summary.json()["data"] if row["id"] == failed.id)["errorMessage"] == "visible failure"
    assert any(row["id"] == cancelled.id for row in status.json()["data"])

    active = client.get("/api/tasks/", params={"chapter_id": "chapter", "active_only": "true",
                                                 "status_only": "true", "limit": 1})
    assert [row["id"] for row in active.json()["data"]] == [running.id]
    full = client.get(f"/api/tasks/{task.id}", headers={"Accept-Encoding": "gzip"})
    assert full.status_code == 200 and full.headers["Content-Encoding"] == "gzip"
    assert full.json()["data"]["workflowJson"] == task.workflow_json
    assert full.json()["data"]["metadata"]["h3_prompt_optimizer"]["raw_response"] == metadata["h3_prompt_optimizer"]["raw_response"]
    references = client.get(f"/api/tasks/{task.id}", params={"references_only": "true"})
    assert references.json()["data"]["referenceImages"] == [{"url": "/reference.png", "label": "source"}]
    assert "workflow-secret" not in references.text
    assert db_session.get(Task, task.id).metadata_json == json.dumps(metadata)
