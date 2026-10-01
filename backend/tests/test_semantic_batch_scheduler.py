import json
from pathlib import Path

import pytest

from app.api import shots as shots_api
from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.task import Task


def _plan(capabilities, revision=3):
    clips = []
    for index, capability in enumerate(capabilities, 1):
        clips.append({
            "clip_id": f"shot-batch:clip:{index}",
            "clip_index": index,
            "clip_plan_revision": revision,
            "capability": capability,
            "continuity_to_previous": "CONTINUOUS" if index > 1 else "NONE",
            "previous_clip_index": index - 1 if index > 1 else None,
            "execution_status": "PLANNED",
            "planned_duration": 4,
        })
    return {
        "clip_plan_revision": revision,
        "clip_plan_validation": {"passed": True},
        "clip_plan_approval_mode": "AUTO_APPROVE",
        "clip_plan": clips,
    }


def _fixture(db_session, *, capabilities=("GENERATE", "TEMPORAL_EXTEND", "EXTEND"), revision=3):
    novel = Novel(id="batch-novel", title="Batch")
    chapter = Chapter(id="batch-chapter", novel_id=novel.id, number=1, title="Chapter")
    shot = Shot(id="shot-batch", chapter_id=chapter.id, index=1, image_url="/api/files/shot.png")
    shot.video_director_plan = json.dumps(_plan(capabilities, revision))
    parent = Task(
        id="batch-parent", type="shot_video_batch", status="running", name="Batch",
        novel_id=novel.id, chapter_id=chapter.id,
        metadata_json=json.dumps({"auto_assemble": False}),
    )
    child = Task(
        id="batch-child", type="shot_video", status="pending", name="Shot",
        novel_id=novel.id, chapter_id=chapter.id, shot_id=shot.id,
        parent_task_id=parent.id, batch_order=1,
        metadata_json=json.dumps({
            "batch_mode": "SEMANTIC_CLIP",
            "clip_plan_revision": revision,
            "auto_assemble": False,
        }),
    )
    db_session.add_all([novel, chapter, shot, parent, child])
    db_session.commit()
    return novel, chapter, shot, parent, child


def _install_execution_fake(db_session, monkeypatch, tmp_path, calls):
    def add_artifact(shot, index, capability, revision):
        task_id = f"generated-{index}"
        url = f"/api/files/generated-{index}.mp4"
        path = tmp_path / f"generated-{index}.mp4"
        path.write_bytes(b"clip")
        metadata = {
            "execution_scope": "CLIP",
            "clip_id": f"{shot.id}:clip:{index}",
            "clip_index": index,
            "clip_plan_revision": revision,
            "capability": capability,
            "approval_status": "APPROVED",
            "execution_contract": {
                "artifact_kind": "CLIP_ONLY",
                "clip": {
                    "clip_id": f"{shot.id}:clip:{index}",
                    "clip_index": index,
                    "clip_plan_revision": revision,
                },
            },
        }
        task = Task(
            id=task_id, type="shot_video", status="completed", name=f"C{index}",
            novel_id=shot.chapter.novel_id, chapter_id=shot.chapter_id,
            shot_id=shot.id, result_url=url, metadata_json=json.dumps(metadata),
        )
        db_session.add(task)
        plan = json.loads(shot.video_director_plan)
        clip = next(item for item in plan["clip_plan"] if item["clip_index"] == index)
        clip.update({"generated_by_task_id": task_id, "video_url": url, "execution_status": "APPROVED"})
        shot.video_director_plan = json.dumps(plan)
        db_session.commit()
        return task, path

    def validate(db, shot, clip, revision, novel_id, chapter_id):
        task_id = clip.get("generated_by_task_id")
        if not task_id:
            raise ValueError("missing artifact")
        task = db.query(Task).filter(Task.id == task_id).one()
        if json.loads(task.metadata_json).get("approval_status") != "APPROVED":
            raise ValueError("approval required")
        return task, json.loads(task.metadata_json), str(tmp_path / f"generated-{task.id.split('-')[-1]}.mp4")

    monkeypatch.setattr(shots_api, "validate_semantic_clip_artifact", validate)

    async def fake_execute(*args, **kwargs):
        shot = db_session.query(Shot).filter(Shot.id == args[2]).one()
        index = args[3]
        revision = kwargs.get("request", args[4]).clip_plan_revision if "request" in kwargs else args[4].clip_plan_revision
        plan = json.loads(shot.video_director_plan)
        clip = next(item for item in plan["clip_plan"] if item["clip_index"] == index)
        calls.append(index)
        task, _ = add_artifact(shot, index, clip["capability"], revision)
        return {"success": True, "data": {"taskId": task.id}}

    monkeypatch.setattr(shots_api, "execute_semantic_clip", fake_execute)
    monkeypatch.setattr(shots_api, "url_to_local_path", lambda url: str(tmp_path / Path(url).name))
    return add_artifact


@pytest.mark.asyncio
async def test_fresh_semantic_scheduler_executes_in_order(db_session, monkeypatch, tmp_path):
    _, _, shot, parent, child = _fixture(db_session)
    calls = []
    _install_execution_fake(db_session, monkeypatch, tmp_path, calls)
    result = await shots_api._run_semantic_shot_for_batch(db_session, parent, child, shot)
    assert result == "completed"
    assert calls == [1, 2, 3]
    assert json.loads(child.metadata_json)["batch_state"] == "COMPLETED_CLIPS"


@pytest.mark.asyncio
async def test_scheduler_reuses_completed_prefix(db_session, monkeypatch, tmp_path):
    _, _, shot, parent, child = _fixture(db_session, capabilities=("GENERATE", "TEMPORAL_EXTEND", "EXTEND"))
    calls = []
    add_artifact = _install_execution_fake(db_session, monkeypatch, tmp_path, calls)
    add_artifact(shot, 1, "GENERATE", 3)
    add_artifact(shot, 2, "TEMPORAL_EXTEND", 3)
    assert await shots_api._run_semantic_shot_for_batch(db_session, parent, child, shot) == "completed"
    assert calls == [3]


@pytest.mark.asyncio
async def test_auto_assemble_false_stops_at_completed_clips(db_session, monkeypatch, tmp_path):
    _, _, shot, parent, child = _fixture(db_session, capabilities=("GENERATE",), revision=3)
    calls = []
    add_artifact = _install_execution_fake(db_session, monkeypatch, tmp_path, calls)
    await shots_api._run_semantic_shot_for_batch(db_session, parent, child, shot)
    assert json.loads(child.metadata_json)["batch_state"] == "COMPLETED_CLIPS"


@pytest.mark.asyncio
async def test_auto_assemble_true_calls_existing_assembly_once(db_session, monkeypatch, tmp_path):
    _, _, shot, parent, child = _fixture(db_session, capabilities=("GENERATE",), revision=3)
    child.metadata_json = json.dumps({"batch_mode": "SEMANTIC_CLIP", "clip_plan_revision": 3, "auto_assemble": True})
    db_session.commit()
    calls = []
    _install_execution_fake(db_session, monkeypatch, tmp_path, calls)

    async def merge(db, current_shot, repo, novel_id, chapter_id, shot_index):
        calls.append("assemble")
        plan = json.loads(current_shot.video_director_plan)
        plan.update({"assembly_status": "COMPLETED", "assembly_clip_plan_revision": 3, "assembly_task_ids": ["generated-1"], "merged_video_url": "/api/files/final.mp4"})
        current_shot.video_director_plan = json.dumps(plan)
        current_shot.video_url = "/api/files/final.mp4"
        return {"success": True, "video_url": current_shot.video_url}

    monkeypatch.setattr(shots_api, "merge_video_director_clip_videos", merge)
    assert await shots_api._run_semantic_shot_for_batch(db_session, parent, child, shot) == "completed"
    assert calls.count("assemble") == 1


@pytest.mark.asyncio
async def test_waiting_review_blocks_dependent_clip(db_session, monkeypatch, tmp_path):
    _, _, shot, parent, child = _fixture(db_session, capabilities=("GENERATE", "EXTEND"))
    calls = []
    add_artifact = _install_execution_fake(db_session, monkeypatch, tmp_path, calls)
    task, _ = add_artifact(shot, 1, "GENERATE", 3)
    metadata = json.loads(task.metadata_json)
    metadata["approval_status"] = "REVIEW_REQUIRED"
    task.metadata_json = json.dumps(metadata)
    db_session.commit()
    assert await shots_api._run_semantic_shot_for_batch(db_session, parent, child, shot) == "waiting_review"
    assert calls == []


@pytest.mark.asyncio
async def test_revision_stale_fails_closed(db_session, monkeypatch, tmp_path):
    _, _, shot, parent, child = _fixture(db_session, revision=3)
    child.metadata_json = json.dumps({"batch_mode": "SEMANTIC_CLIP", "clip_plan_revision": 3, "auto_assemble": False})
    plan = json.loads(shot.video_director_plan)
    plan["clip_plan_revision"] = 4
    shot.video_director_plan = json.dumps(plan)
    db_session.commit()
    with pytest.raises(RuntimeError, match="BATCH_CLIP_PLAN_REVISION_STALE"):
        await shots_api._run_semantic_shot_for_batch(db_session, parent, child, shot)


@pytest.mark.asyncio
async def test_active_clip_task_is_reused_without_duplicate_execution(db_session, monkeypatch, tmp_path):
    _, _, shot, parent, child = _fixture(db_session, capabilities=("GENERATE",), revision=3)
    active = Task(
        id="active-c1", type="shot_video", status="pending", name="C1",
        novel_id="batch-novel", chapter_id="batch-chapter", shot_id=shot.id,
        metadata_json=json.dumps({"execution_scope": "CLIP", "clip_index": 1, "clip_plan_revision": 3}),
    )
    db_session.add(active)
    db_session.commit()
    calls = []
    _install_execution_fake(db_session, monkeypatch, tmp_path, calls)
    async def wait(db, task_id):
        return db.query(Task).filter(Task.id == task_id).one()
    monkeypatch.setattr(shots_api, "_wait_for_semantic_clip_task", wait)
    assert await shots_api._run_semantic_shot_for_batch(db_session, parent, child, shot) == "failed"
    assert calls == []


@pytest.mark.asyncio
async def test_force_rerun_does_not_clear_valid_semantic_artifacts(db_session, monkeypatch, tmp_path):
    _, _, shot, parent, child = _fixture(db_session, capabilities=("GENERATE",), revision=3)
    child.metadata_json = json.dumps({"batch_mode": "SEMANTIC_CLIP", "clip_plan_revision": 3, "auto_assemble": False, "batch_force_rerun": True})
    db_session.commit()
    calls = []
    add_artifact = _install_execution_fake(db_session, monkeypatch, tmp_path, calls)
    existing, _ = add_artifact(shot, 1, "GENERATE", 3)
    await shots_api._run_semantic_shot_for_batch(db_session, parent, child, shot)
    assert db_session.query(Task).filter(Task.id == existing.id).one().status == "completed"
    assert calls == []


@pytest.mark.asyncio
async def test_cut_clip_does_not_require_previous(db_session, monkeypatch, tmp_path):
    _, _, shot, parent, child = _fixture(db_session, capabilities=("GENERATE",), revision=3)
    plan = json.loads(shot.video_director_plan)
    plan["clip_plan"][0]["continuity_to_previous"] = "CUT"
    plan["clip_plan"][0]["previous_clip_index"] = None
    shot.video_director_plan = json.dumps(plan)
    db_session.commit()
    calls = []
    _install_execution_fake(db_session, monkeypatch, tmp_path, calls)
    assert await shots_api._run_semantic_shot_for_batch(db_session, parent, child, shot) == "completed"
    assert calls == [1]


@pytest.mark.asyncio
async def test_semantic_failure_never_falls_back_to_legacy(db_session, monkeypatch, tmp_path):
    _, _, shot, parent, child = _fixture(db_session, capabilities=("GENERATE",), revision=3)
    async def fail(*args, **kwargs):
        raise shots_api.HTTPException(status_code=400, detail="semantic failed")
    monkeypatch.setattr(shots_api, "execute_semantic_clip", fail)
    legacy_called = []
    monkeypatch.setattr(shots_api, "_prepare_and_enqueue_batch_video_child", lambda *args: legacy_called.append(True))
    assert await shots_api._run_semantic_shot_for_batch(db_session, parent, child, shot) == "failed"
    assert legacy_called == []


@pytest.mark.asyncio
async def test_existing_current_revision_assembly_is_reused(db_session, monkeypatch, tmp_path):
    _, _, shot, parent, child = _fixture(db_session, capabilities=("GENERATE",), revision=3)
    child.metadata_json = json.dumps({"batch_mode": "SEMANTIC_CLIP", "clip_plan_revision": 3, "auto_assemble": True})
    db_session.commit()
    calls = []
    add_artifact = _install_execution_fake(db_session, monkeypatch, tmp_path, calls)
    task, _ = add_artifact(shot, 1, "GENERATE", 3)
    plan = json.loads(shot.video_director_plan)
    plan.update({"assembly_status": "COMPLETED", "assembly_clip_plan_revision": 3, "assembly_task_ids": [task.id], "merged_video_url": "/api/files/final.mp4"})
    shot.video_director_plan = json.dumps(plan)
    shot.video_url = "/api/files/final.mp4"
    db_session.commit()
    (tmp_path / "final.mp4").write_bytes(b"final")
    monkeypatch.setattr(shots_api, "url_to_local_path", lambda url: str(tmp_path / Path(url).name))
    monkeypatch.setattr(shots_api, "merge_video_director_clip_videos", lambda *args: (_ for _ in ()).throw(AssertionError("reassembled")))
    assert await shots_api._run_semantic_shot_for_batch(db_session, parent, child, shot) == "completed"


def test_old_shot_url_does_not_count_as_current_assembly(db_session, monkeypatch, tmp_path):
    _, _, shot, parent, child = _fixture(db_session, capabilities=("GENERATE",), revision=3)
    shot.video_url = "/api/files/old.mp4"
    db_session.commit()
    assert json.loads(shot.video_director_plan).get("assembly_status") is None


@pytest.mark.asyncio
async def test_failed_predecessor_blocks_dependent_and_preserves_previous(db_session, monkeypatch, tmp_path):
    _, _, shot, parent, child = _fixture(db_session)
    calls = []
    add_artifact = _install_execution_fake(db_session, monkeypatch, tmp_path, calls)
    add_artifact(shot, 1, "GENERATE", 3)
    failed = Task(
        id="failed-c2", type="shot_video", status="failed", name="C2",
        novel_id="batch-novel", chapter_id="batch-chapter", shot_id=shot.id,
        metadata_json=json.dumps({"execution_scope": "CLIP", "clip_index": 2, "clip_plan_revision": 3}),
        error_message="C2 failed",
    )
    db_session.add(failed)
    db_session.commit()
    monkeypatch.setattr(shots_api.TaskService, "retry_task", lambda self, task_id: {"success": False, "message": "retry blocked"})
    assert await shots_api._run_semantic_shot_for_batch(db_session, parent, child, shot) == "failed"
    assert json.loads(child.metadata_json)["failed_clip_index"] == 2
    assert json.loads(shot.video_director_plan)["clip_plan"][0]["execution_status"] == "APPROVED"
    assert calls == []


def test_batch_creation_pins_semantic_revision_and_mode(client, db_session, monkeypatch):
    novel = Novel(id="route-novel", title="Route")
    chapter = Chapter(id="route-chapter", novel_id=novel.id, number=1, title="Chapter")
    shot = Shot(id="route-shot", chapter_id=chapter.id, index=1, image_url="/api/files/shot.png", video_director_plan=json.dumps(_plan(("GENERATE",), 7)))
    db_session.add_all([novel, chapter, shot])
    db_session.commit()
    monkeypatch.setattr(shots_api, "enqueue_shot_video_batch_task", lambda _: None)
    response = client.post(f"/api/novels/{novel.id}/chapters/{chapter.id}/shot-videos/batch", json={"shot_ids": [shot.id], "auto_assemble": False})
    assert response.status_code == 200
    parent = db_session.query(Task).filter(Task.id == response.json()["data"]["batchTaskId"]).one()
    child = db_session.query(Task).filter(Task.parent_task_id == parent.id, Task.type == "shot_video").one()
    assert json.loads(parent.metadata_json)["selected_shots"][0]["clip_plan_revision"] == 7
    assert json.loads(child.metadata_json)["clip_plan_revision"] == 7
    assert json.loads(child.metadata_json)["auto_assemble"] is False
