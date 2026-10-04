import json
from pathlib import Path

import pytest

from app.models.shot import Shot
from app.models.task import Task
from app.repositories.shot_repository import ShotRepository
from app.services.canonical_execution_invalidation import (
    CanonicalExecutionConflict,
    canonical_clip_dependency_closure,
    current_visual_state_consumers,
    ensure_no_active_canonical_clip_tasks,
    invalidate_current_canonical_execution,
    sync_temporal_anchor_state_image,
)
from app.services.shot_video_service import _save_generated_video, resolve_extend_previous_av


def _clip(index, capability, previous=None, task_id=None, url=None, states=None):
    clip = {
        "clip_index": index,
        "start_time": (index - 1) * 4,
        "end_time": index * 4,
        "planned_duration": 4,
        "capability": capability,
        "continuity_to_previous": "CONTINUOUS" if previous else "CUT",
        "previous_clip_index": previous,
        "visual_state_indexes": states or [],
        "carry_in_state_index": index if index > 1 else None,
        "execution_status": "APPROVED",
        "generated_by_task_id": task_id,
        "video_url": url,
        "prompt_text": f"prompt-{index}",
    }
    return clip


def _plan(task_ids):
    return {
        "canonical_visual_plan": True,
        "clip_plan_revision": 7,
        "keyframes": [
            {"index": 1, "role": "START", "time_seconds": 0},
            {"index": 2, "role": "INTERMEDIATE", "time_seconds": 3, "image_url": "/old-state.png", "timed_visual_target": False},
            {"index": 3, "role": "INTERMEDIATE", "time_seconds": 7, "timed_visual_target": True},
            {"index": 4, "role": "END", "time_seconds": 16},
        ],
        "transitions": [
            {"from_keyframe_index": 1, "to_keyframe_index": 2},
            {"from_keyframe_index": 2, "to_keyframe_index": 3},
            {"from_keyframe_index": 3, "to_keyframe_index": 4},
        ],
        "clip_plan_validation": {"passed": True},
        "clip_plan": [
            _clip(1, "GENERATE", task_id=task_ids[0], url="/c1.mp4", states=[1, 2]),
            _clip(2, "EXTEND", previous=1, task_id=task_ids[1], url="/c2.mp4", states=[3]),
            _clip(3, "TEMPORAL_EXTEND", previous=2, task_id=task_ids[2], url="/c3.mp4", states=[]),
            _clip(4, "GENERATE", task_id=task_ids[3], url="/c4.mp4", states=[4]),
        ],
        "temporal_anchors": [{
            "anchor_id": "clip-2-KF3",
            "image_url": "/old-anchor.png",
            "source": {"type": "KEYFRAME", "id": "KF3", "keyframe_index": 3, "image_task_id": "old-image-task"},
        }],
        "merged_video_url": "/final.mp4",
        "merged_at": "now",
        "assembly_status": "COMPLETED",
        "assembly_clip_plan_revision": 7,
        "assembly_task_ids": list(task_ids),
        "assembly_mode": "CONCAT",
        "assembled_result": {"url": "/final.mp4", "task_ids": list(task_ids)},
    }


def _task(shot_id, index, task_id, *, reference_state=None, status="completed"):
    url = f"/c{index}.mp4"
    manifest = {"version": 1, "references": []}
    if reference_state is not None:
        manifest["references"].append({
            "slot": 1,
            "source_keyframe_index": reference_state,
            "image_url": "/old-state.png",
        })
    metadata = {
        "execution_scope": "CLIP",
        "clip_index": index,
        "clip_plan_revision": 7,
        "capability": "GENERATE" if index in {1, 4} else "EXTEND",
        "approval_status": "APPROVED",
        "video_reference_manifest": manifest,
        "execution_contract": {
            "artifact_kind": "CLIP_ONLY",
            "clip": {"clip_index": index, "clip_plan_revision": 7},
        },
    }
    return Task(
        id=task_id,
        type="shot_video",
        status=status,
        name=f"C{index}",
        shot_id=shot_id,
        result_url=url if status == "completed" else None,
        metadata_json=json.dumps(metadata),
    )


def _fixture(db_session, tmp_path):
    task_ids = [f"task-{index}" for index in range(1, 5)]
    history_files = []
    for index in range(1, 5):
        path = tmp_path / f"c{index}.mp4"
        path.write_bytes(f"clip-{index}".encode())
        history_files.append(path)
    shot = Shot(
        id="canonical-shot",
        chapter_id="chapter",
        index=1,
        duration=16,
        video_url="/final.mp4",
        video_status="completed",
        video_task_id="assembly-owner",
        video_director_plan=json.dumps(_plan(task_ids)),
    )
    db_session.add(shot)
    db_session.add_all([
        _task(shot.id, 1, task_ids[0], reference_state=2),
        _task(shot.id, 2, task_ids[1]),
        _task(shot.id, 3, task_ids[2]),
        _task(shot.id, 4, task_ids[3]),
    ])
    db_session.commit()
    return shot, task_ids, history_files


def test_visual_state_replacement_invalidates_only_physical_consumer_dependency_closure(db_session, tmp_path):
    shot, task_ids, history_files = _fixture(db_session, tmp_path)
    original = json.loads(shot.video_director_plan)

    consumers = current_visual_state_consumers(db_session, shot, 2, "/old-state.png")
    assert consumers == {1}
    assert canonical_clip_dependency_closure(original, consumers) == {1, 2, 3}

    invalidated = invalidate_current_canonical_execution(shot, consumers)
    db_session.commit()
    persisted = json.loads(shot.video_director_plan)
    clips = {item["clip_index"]: item for item in persisted["clip_plan"]}

    assert invalidated == {1, 2, 3}
    for index in (1, 2, 3):
        assert clips[index]["execution_status"] == "PLANNED"
        assert "generated_by_task_id" not in clips[index]
        assert "video_url" not in clips[index]
        assert clips[index]["prompt_text"] == f"prompt-{index}"
        assert clips[index]["capability"] == original["clip_plan"][index - 1]["capability"]
        assert clips[index]["previous_clip_index"] == original["clip_plan"][index - 1]["previous_clip_index"]
        assert clips[index]["visual_state_indexes"] == original["clip_plan"][index - 1]["visual_state_indexes"]
        assert clips[index]["carry_in_state_index"] == original["clip_plan"][index - 1]["carry_in_state_index"]
    assert clips[4]["generated_by_task_id"] == task_ids[3]
    assert clips[4]["video_url"] == "/c4.mp4"
    assert persisted["keyframes"] == original["keyframes"]
    assert persisted["transitions"] == original["transitions"]
    assert persisted["clip_plan_revision"] == 7
    assert "assembly_status" not in persisted
    assert "merged_video_url" not in persisted
    assert shot.video_url is None
    assert shot.video_task_id is None
    assert db_session.query(Task).filter(Task.shot_id == shot.id).count() == 4
    assert all(path.is_file() for path in history_files)


def test_first_optional_state_image_does_not_invalidate_unrelated_execution(db_session, tmp_path):
    shot, task_ids, _ = _fixture(db_session, tmp_path)
    plan_before = json.loads(shot.video_director_plan)
    assert current_visual_state_consumers(db_session, shot, 3, None) == set()
    assert invalidate_current_canonical_execution(shot, set()) == set()
    assert json.loads(shot.video_director_plan) == plan_before
    assert shot.video_url == "/final.mp4"
    assert json.loads(shot.video_director_plan)["keyframes"][2]["timed_visual_target"] is True


def test_clip_replacement_preserves_new_clip_invalidates_previous_av_successors_and_assembly(db_session, tmp_path):
    shot, task_ids, history_files = _fixture(db_session, tmp_path)
    plan = json.loads(shot.video_director_plan)
    c1 = plan["clip_plan"][0]
    c1.update({"generated_by_task_id": "new-task-1", "video_url": "/new-c1.mp4", "execution_status": "APPROVED"})
    shot.video_director_plan = json.dumps(plan)

    invalidated = invalidate_current_canonical_execution(shot, {1}, preserve_clip_indexes={1})
    db_session.commit()
    persisted = json.loads(shot.video_director_plan)
    clips = {item["clip_index"]: item for item in persisted["clip_plan"]}

    assert invalidated == {2, 3}
    assert clips[1]["generated_by_task_id"] == "new-task-1"
    assert clips[1]["video_url"] == "/new-c1.mp4"
    for index in (2, 3):
        assert "generated_by_task_id" not in clips[index]
        assert clips[index]["execution_status"] == "PLANNED"
    assert clips[4]["generated_by_task_id"] == task_ids[3]
    assert "assembly_status" not in persisted
    assert shot.video_url is None
    assert db_session.query(Task).filter(Task.id.in_(task_ids)).count() == 4
    assert all(path.is_file() for path in history_files)


def test_regenerating_c2_invalidates_c3_but_preserves_c1_and_independent_c4(db_session, tmp_path):
    shot, task_ids, _ = _fixture(db_session, tmp_path)
    plan = json.loads(shot.video_director_plan)
    plan["clip_plan"][1].update({"generated_by_task_id": "new-task-2", "video_url": "/new-c2.mp4"})
    shot.video_director_plan = json.dumps(plan)

    assert invalidate_current_canonical_execution(shot, {2}, preserve_clip_indexes={2}) == {3}
    persisted = json.loads(shot.video_director_plan)
    clips = {item["clip_index"]: item for item in persisted["clip_plan"]}
    assert clips[1]["generated_by_task_id"] == task_ids[0]
    assert clips[2]["generated_by_task_id"] == "new-task-2"
    assert "generated_by_task_id" not in clips[3]
    assert clips[4]["generated_by_task_id"] == task_ids[3]


@pytest.mark.parametrize("active_status", ["queued", "running"])
def test_active_successor_task_rejects_invalidation_without_partial_mutation(
    db_session, tmp_path, active_status
):
    shot, _, _ = _fixture(db_session, tmp_path)
    plan_before = json.loads(shot.video_director_plan)
    active = _task(shot.id, 2, "active-c2", status=active_status)
    db_session.add(active)
    db_session.commit()

    affected = canonical_clip_dependency_closure(plan_before, {1})
    with pytest.raises(CanonicalExecutionConflict):
        ensure_no_active_canonical_clip_tasks(db_session, shot.id, plan_before, affected)

    assert json.loads(shot.video_director_plan) == plan_before
    assert shot.video_url == "/final.mp4"


def test_temporal_anchor_image_sync_preserves_anchor_identity_and_timing():
    plan = _plan([f"task-{index}" for index in range(1, 5)])
    before = dict(plan["temporal_anchors"][0])
    sync_temporal_anchor_state_image(plan, 3, "/new-anchor.png", "new-image-task")
    anchor = plan["temporal_anchors"][0]
    assert anchor["anchor_id"] == before["anchor_id"]
    assert anchor["image_url"] == "/new-anchor.png"
    assert anchor["source"]["image_task_id"] == "new-image-task"


def test_temporal_anchor_manifest_is_a_physical_state_dependency(db_session, tmp_path):
    shot, task_ids, _ = _fixture(db_session, tmp_path)
    task = db_session.get(Task, task_ids[1])
    metadata = json.loads(task.metadata_json)
    metadata["execution_contract"]["temporal_anchor_manifest"] = {
        "manifest_version": "1.0",
        "anchors": [{
            "anchor_id": "clip-2-KF3",
            "image_url": "/old-anchor.png",
            "source": {"type": "KEYFRAME", "id": "KF3", "keyframe_index": 3},
        }],
    }
    task.metadata_json = json.dumps(metadata)
    db_session.commit()

    consumers = current_visual_state_consumers(
        db_session, shot, 3, "/old-anchor.png",
    )
    assert consumers == {2}
    assert canonical_clip_dependency_closure(json.loads(shot.video_director_plan), consumers) == {2, 3}


@pytest.mark.asyncio
async def test_canonical_clip_save_promotes_new_artifact_and_invalidates_exact_successors(
    db_session, tmp_path, monkeypatch
):
    shot, old_task_ids, history_files = _fixture(db_session, tmp_path)
    metadata = {
        "execution_scope": "CLIP",
        "clip_index": 1,
        "clip_plan_revision": 7,
        "capability": "GENERATE",
        "requested_duration": 4,
        "execution_contract": {
            "artifact_kind": "CLIP_ONLY",
            "capability": "GENERATE",
            "clip": {"clip_index": 1, "clip_plan_revision": 7},
        },
    }
    regenerated = Task(
        id="new-task-1",
        type="shot_video",
        status="running",
        name="Regenerated C1",
        novel_id="novel",
        chapter_id=shot.chapter_id,
        shot_id=shot.id,
        metadata_json=json.dumps(metadata),
    )
    db_session.add(regenerated)
    db_session.commit()
    output = tmp_path / "new-c1.mp4"
    output.write_bytes(b"new-current-c1")

    async def download_video(**_kwargs):
        return str(output)

    monkeypatch.setattr("app.services.shot_video_service.file_storage.base_dir", tmp_path)
    monkeypatch.setattr("app.services.shot_video_service.file_storage.download_video", download_video)
    monkeypatch.setattr("app.services.shot_video_service._probe_video_duration", lambda _path: 4.0)
    monkeypatch.setattr("app.services.shot_video_service.url_to_local_path", lambda _url: str(output))
    from test_continuous_clip_native_av import physical
    monkeypatch.setattr("app.services.shot_video_service.probe_clip_av", lambda path: physical(209, Path(path).read_bytes()))

    await _save_generated_video(
        {"success": True, "video_url": "http://comfy/new-c1.mp4"},
        regenerated,
        "novel",
        shot.chapter_id,
        shot.index,
        db_session,
        regenerated.id,
        ShotRepository(db_session),
        clip_metadata=metadata,
        update_shot_result=False,
        artifact_suffix="clip_1_regenerated",
    )

    db_session.refresh(shot)
    db_session.refresh(regenerated)
    plan = json.loads(shot.video_director_plan)
    clips = {item["clip_index"]: item for item in plan["clip_plan"]}
    assert regenerated.status == "completed"
    assert clips[1]["generated_by_task_id"] == regenerated.id
    assert clips[1]["video_url"] == "/api/files/new-c1.mp4"
    assert clips[1]["execution_status"] == "APPROVED"
    for index in (2, 3):
        assert clips[index]["execution_status"] == "PLANNED"
        assert "generated_by_task_id" not in clips[index]
        assert "video_url" not in clips[index]
    assert clips[4]["generated_by_task_id"] == old_task_ids[3]
    assert clips[4]["video_url"] == "/c4.mp4"
    assert shot.video_url is None
    assert shot.video_task_id is None
    assert "assembly_status" not in plan
    assert db_session.query(Task).filter(Task.id.in_(old_task_ids)).count() == 4
    assert all(path.is_file() for path in history_files)

    c2 = clips[2]
    previous = {
        "clip_index": 1,
        "clip_plan_revision": 7,
        "generated_by_task_id": regenerated.id,
        "result_url": regenerated.result_url,
    }
    resolved = resolve_extend_previous_av(
        db_session, "novel", shot.chapter_id, shot, c2, previous,
    )
    assert resolved["generated_by_task_id"] == regenerated.id
    assert resolved["result_url"] == "/api/files/new-c1.mp4"
    assert resolved["local_path"] == str(output)
