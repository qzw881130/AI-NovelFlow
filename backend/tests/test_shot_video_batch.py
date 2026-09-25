import json

import pytest
from sqlalchemy.orm import sessionmaker

from app.api import shots as shots_api
from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.task import Task
from app.models.workflow import Workflow
from app.repositories.shot_repository import ShotRepository


def _create_video_batch(db_session, status="pending", child_count=2):
    novel = Novel(title="持久化批量视频测试")
    db_session.add(novel)
    db_session.commit()
    chapter = Chapter(novel_id=novel.id, number=1, title="第一章", content="内容")
    db_session.add(chapter)
    db_session.commit()
    batch = Task(
        type="shot_video_batch",
        status=status,
        name="批量生成分镜视频",
        novel_id=novel.id,
        chapter_id=chapter.id,
        metadata_json=json.dumps({"auto_complete_details": False}),
    )
    db_session.add(batch)
    db_session.flush()
    children = []
    for index in range(1, child_count + 1):
        shot = Shot(
            chapter_id=chapter.id,
            index=index,
            description=f"分镜{index}",
            characters="[]",
            props="[]",
            duration=4,
            image_url=f"/api/files/shot-{index}.png",
            image_status="completed",
            video_status="pending",
            video_director_plan=json.dumps({"selected_mode": "SINGLE_FRAME"}),
        )
        db_session.add(shot)
        db_session.flush()
        child = Task(
            type="shot_video",
            status="pending",
            name=f"生成视频: 镜{index}",
            novel_id=novel.id,
            chapter_id=chapter.id,
            shot_id=shot.id,
            parent_task_id=batch.id,
            batch_order=index,
        )
        db_session.add(child)
        children.append(child)
    db_session.commit()
    return batch, children


def test_resume_active_shot_video_batches_uses_persisted_parents(db_session, monkeypatch):
    testing_session = sessionmaker(bind=db_session.bind)
    monkeypatch.setattr(shots_api, "SessionLocal", testing_session)
    pending, _ = _create_video_batch(db_session, status="pending", child_count=1)
    running, _ = _create_video_batch(db_session, status="running", child_count=1)
    completed, _ = _create_video_batch(db_session, status="completed", child_count=1)
    enqueued = []
    monkeypatch.setattr(shots_api, "enqueue_shot_video_batch_task", enqueued.append)

    shots_api.resume_active_shot_video_batches()

    assert set(enqueued) == {pending.id, running.id}
    assert completed.id not in enqueued


@pytest.mark.asyncio
async def test_video_batch_runner_completes_persisted_children_in_order(db_session, monkeypatch):
    testing_session = sessionmaker(bind=db_session.bind)
    monkeypatch.setattr(shots_api, "SessionLocal", testing_session)
    batch, children = _create_video_batch(db_session)
    processed = []

    def complete_child(db, child, selected_mode, use_reference_audio, skip_llm_when_prompt_exists):
        processed.append(child.batch_order)
        child.status = "completed"
        child.progress = 100
        db.commit()

    monkeypatch.setattr(shots_api, "_prepare_and_enqueue_batch_video_child", complete_child)

    await shots_api.run_shot_video_batch_task(batch.id)

    db_session.expire_all()
    refreshed_batch = db_session.query(Task).filter(Task.id == batch.id).one()
    refreshed_children = db_session.query(Task).filter(
        Task.parent_task_id == batch.id,
        Task.type == "shot_video",
    ).order_by(Task.batch_order).all()
    assert processed == [1, 2]
    assert refreshed_batch.status == "completed"
    assert refreshed_batch.progress == 100
    assert [child.status for child in refreshed_children] == ["completed", "completed"]


@pytest.mark.asyncio
async def test_video_batch_runner_delegates_semantic_shot_and_waits_for_final(db_session, monkeypatch):
    testing_session = sessionmaker(bind=db_session.bind)
    monkeypatch.setattr(shots_api, "SessionLocal", testing_session)
    batch, children = _create_video_batch(db_session, child_count=1)
    shot = db_session.query(Shot).filter(Shot.id == children[0].shot_id).one()
    shot.video_director_plan = json.dumps({
        "clip_plan_revision": 4,
        "clip_plan_validation": {"passed": True},
        "clip_plan_approval_mode": "AUTO_APPROVE",
        "clip_plan": [{"clip_index": 1, "capability": "SINGLE_FRAME", "planned_duration": 8}],
    })
    db_session.commit()
    calls = []

    async def start_semantic(**kwargs):
        calls.append(kwargs)

    async def wait_for_final(db, child, shot, plan):
        assert plan["clip_plan_revision"] == 4
        return "completed"

    monkeypatch.setattr(shots_api, "generate_clip_plan_video", start_semantic)
    monkeypatch.setattr(shots_api, "_wait_for_semantic_shot_final", wait_for_final)

    await shots_api.run_shot_video_batch_task(batch.id)

    db_session.expire_all()
    refreshed_batch = db_session.query(Task).filter(Task.id == batch.id).one()
    refreshed_child = db_session.query(Task).filter(Task.id == children[0].id).one()
    assert len(calls) == 1
    assert calls[0]["batch_parent_task_id"] == batch.id
    assert refreshed_child.status == "completed"
    assert refreshed_batch.status == "completed"


@pytest.mark.asyncio
async def test_multi_clip_video_initializes_node_mapping_before_plan_update(db_session, tmp_path, monkeypatch):
    from app.services import shot_video_service

    novel = Novel(title="multi clip mapping", aspect_ratio="16:9")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="chapter")
    db_session.add(chapter)
    db_session.flush()
    window_plan = {
        "window_index": 1,
        "start_time": 0,
        "end_time": 3,
        "selected_frame_count": 3,
        "keyframe_indexes": [1, 2, 3],
    }
    director_plan = {
        "selected_mode": "MULTI_KEYFRAME",
        "keyframes": [{"index": 1}, {"index": 2}, {"index": 3}],
        "window_plans": [window_plan],
    }
    shot = Shot(
        chapter_id=chapter.id,
        index=1,
        duration=3,
        dialogues="[]",
        video_director_plan=json.dumps(director_plan),
    )
    task = Task(
        type="shot_video",
        status="running",
        name="multi clip",
        novel_id=novel.id,
        chapter_id=chapter.id,
        shot_id=shot.id,
    )
    workflow = Workflow(
        name="three frame",
        type="three_frame_video",
        workflow_json="{}",
        node_mapping=json.dumps({"megapixels_node_id": "132", "video_save_node_id": "150"}),
        is_active=True,
    )
    db_session.add_all([shot, task, workflow])
    db_session.commit()

    captured = {}

    async def fake_build_prompt(**kwargs):
        return "clip prompt"

    async def fake_generate(self, **kwargs):
        captured["node_mapping"] = kwargs["node_mapping"]
        return {"success": True, "video_url": "http://comfy.test/clip.mp4"}

    output_path = tmp_path / "clip.mp4"

    async def fake_download(**kwargs):
        output_path.write_bytes(b"video")
        return str(output_path)

    monkeypatch.setattr(shot_video_service, "build_h3_video_prompt", fake_build_prompt)
    monkeypatch.setattr(shot_video_service.ComfyUIService, "generate_shot_video_with_workflow", fake_generate)
    monkeypatch.setattr(shot_video_service.file_storage, "download_video", fake_download)
    monkeypatch.setattr(shot_video_service, "url_to_local_path", lambda _url: str(tmp_path / "keyframe.png"))

    await shot_video_service._generate_multi_clip_video_task(
        db=db_session,
        task=task,
        novel=novel,
        shot=shot,
        shot_repo=ShotRepository(db_session),
        novel_id=novel.id,
        chapter_id=chapter.id,
        shot_index=shot.index,
        shot_image_url="/api/files/shot.png",
        shot_image_path=str(tmp_path / "shot.png"),
        plan_keyframes_by_index={
            1: {"index": 1, "role": "START"},
            2: {"index": 2, "image_url": "/api/files/kf2.png"},
            3: {"index": 3, "image_url": "/api/files/kf3.png"},
        },
        window_plans=[window_plan],
        video_director_plan=director_plan,
        style="",
        character_appearances={},
        scene_setting="",
        prop_appearances={},
        reference_audio_path=None,
        task_id=task.id,
        only_window_index=1,
    )

    db_session.refresh(task)
    refreshed_plan = json.loads(shot.video_director_plan)
    assert captured["node_mapping"] == {"megapixels_node_id": "132", "video_save_node_id": "150"}
    assert refreshed_plan["window_plans"][0]["megapixels_node_id"] == "132"
    assert refreshed_plan["window_plans"][0]["video_save_node_id"] == "150"
    assert task.status == "completed"


@pytest.mark.asyncio
async def test_semantic_batch_failure_does_not_block_other_shot_final(db_session, monkeypatch):
    testing_session = sessionmaker(bind=db_session.bind)
    monkeypatch.setattr(shots_api, "SessionLocal", testing_session)
    batch, children = _create_video_batch(db_session, child_count=2)
    for child in children:
        shot = db_session.query(Shot).filter(Shot.id == child.shot_id).one()
        shot.video_director_plan = json.dumps({
            "clip_plan_revision": 2,
            "clip_plan_validation": {"passed": True},
            "clip_plan_approval_mode": "AUTO_APPROVE",
            "clip_plan": [{"clip_index": 1, "capability": "SINGLE_FRAME", "planned_duration": 8}],
        })
    db_session.commit()

    async def start_semantic(**kwargs):
        return None

    async def wait_for_final(db, child, shot, plan):
        return "failed" if shot.index == 1 else "completed"

    monkeypatch.setattr(shots_api, "generate_clip_plan_video", start_semantic)
    monkeypatch.setattr(shots_api, "_wait_for_semantic_shot_final", wait_for_final)

    await shots_api.run_shot_video_batch_task(batch.id)

    db_session.expire_all()
    refreshed_batch = db_session.query(Task).filter(Task.id == batch.id).one()
    refreshed_children = db_session.query(Task).filter(
        Task.parent_task_id == batch.id,
        Task.batch_order.isnot(None),
    ).order_by(Task.batch_order).all()
    assert [child.status for child in refreshed_children] == ["failed", "completed"]
    assert refreshed_batch.status == "failed"
    assert "成功 1，失败 1" in refreshed_batch.current_step


@pytest.mark.asyncio
async def test_single_clip_semantic_execution_still_runs_final_assembly(db_session, tmp_path, monkeypatch):
    from app.services import shot_video_service

    novel = Novel(title="single semantic assembly")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="chapter")
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(
        chapter_id=chapter.id, index=1, duration=8, image_url="/api/files/image.png",
        video_director_plan=json.dumps({"clip_plan_revision": 1, "clip_plan": [{"clip_index": 1}]}),
    )
    task = Task(
        id="single-clip-task", type="shot_video", status="completed", name="C1",
        novel_id=novel.id, chapter_id=chapter.id, shot_id=shot.id,
        metadata_json=json.dumps({
            "execution_scope": "CLIP", "clip_index": 1, "clip_plan_revision": 1,
            "capability": "SINGLE_FRAME", "approval_mode": "AUTO_APPROVE",
        }),
    )
    db_session.add_all([shot, task])
    db_session.commit()
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"image")
    db_session.expire_all()
    shot = db_session.query(Shot).filter(Shot.id == shot.id).one()
    task = db_session.query(Task).filter(Task.id == task.id).one()

    assembly_calls = []

    async def fake_merge(db, current_shot, shot_repo, novel_id, chapter_id, shot_index):
        assembly_calls.append(current_shot.id)
        return {"success": True, "video_url": "/api/files/final.mp4"}

    monkeypatch.setattr(shot_video_service, "merge_video_director_clip_videos", fake_merge)
    monkeypatch.setattr(shot_video_service, "url_to_local_path", lambda url: str(image_path))
    await shot_video_service._enqueue_next_clip_if_needed(
        db_session, task, shot, novel, {"clip_index": 1, "capability": "SINGLE_FRAME"}
    )
    assert assembly_calls == [shot.id]


@pytest.mark.asyncio
@pytest.mark.parametrize("previous_capability", ["SINGLE_FRAME", "VIDEO_CONTINUATION", "TEMPORAL_EXTEND"])
async def test_semantic_continuation_enqueue_uses_previous_assembled_result_when_available(
    db_session, tmp_path, monkeypatch, previous_capability,
):
    from app.models.workflow import Workflow
    from app.services import shot_video_service

    novel = Novel(title="continuation source")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="chapter")
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(
        chapter_id=chapter.id, index=1,
        video_director_plan=json.dumps({"clip_plan_revision": 7, "clip_plan": [
            {"clip_index": 1, "capability": previous_capability},
            {"clip_index": 2, "capability": "TEMPORAL_EXTEND", "planned_duration": 8},
        ]}),
    )
    previous_file = tmp_path / "previous-assembled.mp4"
    previous_file.write_bytes(b"approved previous")
    previous_url = f"/api/files/{previous_file}"
    previous_metadata = {
        "execution_scope": "CLIP", "clip_index": 1, "clip_plan_revision": 7,
        "capability": previous_capability, "approval_status": "APPROVED",
    }
    if previous_capability in {"VIDEO_CONTINUATION", "TEMPORAL_EXTEND"}:
        previous_metadata["assembled_result"] = {"url": previous_url}
    previous = Task(
        id="previous-clip", type="shot_video", status="completed", name="C1",
        novel_id=novel.id, chapter_id=chapter.id, shot_id=shot.id,
        result_url="/api/files/independent-output.mp4",
        metadata_json=json.dumps(previous_metadata),
    )
    workflow = Workflow(id="temporal-workflow", name="Temporal", type="TEMPORAL_EXTEND", workflow_json="{}", is_active=True)
    completed = Task(
        id="completed-clip", type="shot_video", status="completed", name="C1",
        novel_id=novel.id, chapter_id=chapter.id, shot_id=shot.id,
        result_url=previous_url,
        metadata_json=json.dumps({"assembled_result": {"url": previous_url}}),
    )
    db_session.add_all([shot, previous, workflow, completed])
    db_session.commit()
    captured = {}

    def enqueue(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs

    monkeypatch.setattr(shot_video_service, "enqueue_shot_video_task", enqueue)
    await shot_video_service._enqueue_next_clip_if_needed(
        db_session, completed, shot, novel,
        {"clip_index": 1, "capability": previous_capability, "batch_parent_task_id": None},
    )
    next_task = db_session.query(Task).filter(Task.id != completed.id, Task.shot_id == shot.id).order_by(Task.created_at.desc()).first()
    next_metadata = json.loads(next_task.metadata_json)
    assert next_metadata["capability"] == "TEMPORAL_EXTEND"
    assert next_metadata["previous_approved_video_url"] == previous_url
    if previous_capability in {"VIDEO_CONTINUATION", "TEMPORAL_EXTEND"}:
        assert next_metadata["previous_approved_video_source"] == "approved_assembled_result"


@pytest.mark.asyncio
@pytest.mark.parametrize("prompt_text, expected_skip", [(None, False), ("existing keyframe prompt", True)])
async def test_batch_video_only_reuses_keyframe_prompt_when_it_exists(db_session, monkeypatch, prompt_text, expected_skip):
    novel = Novel(title="关键帧提示词批量测试")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="第一章")
    db_session.add(chapter)
    db_session.flush()
    keyframe = {
        "frame_index": 0,
        "plan_keyframe_index": 2,
        "description": "尾帧描述",
        "image_url": None,
    }
    if prompt_text:
        keyframe["prompt_text"] = prompt_text
    shot = Shot(
        chapter_id=chapter.id,
        index=1,
        image_url="/api/files/shot.png",
        characters="[]",
        props="[]",
        duration=8,
        keyframes=json.dumps([keyframe]),
        video_director_plan=json.dumps({
            "selected_mode": "FIRST_LAST_FRAME",
            "workflow_capability": {"max_clip_duration": 15},
            "keyframes": [{"index": 1, "role": "START"}, {"index": 2, "role": "END", "description": "尾帧描述"}],
            "transitions": [{"from_keyframe_index": 1, "to_keyframe_index": 2}],
        }),
    )
    db_session.add(shot)
    db_session.flush()
    batch = Task(type="shot_video_batch", status="running", name="批量", novel_id=novel.id, chapter_id=chapter.id)
    child = Task(type="shot_video", status="running", name="子任务", novel_id=novel.id, chapter_id=chapter.id, shot_id=shot.id, parent_task_id=batch.id)
    keyframe_task = Task(type="keyframe_image", status="pending", name=f"生成关键帧图片: {shot.id}-0", novel_id=novel.id, chapter_id=chapter.id, shot_id=shot.id)
    db_session.add_all([batch, child, keyframe_task])
    db_session.commit()
    observed = {}

    async def fake_generate(self, db, shot_id, frame_index, workflow_id=None, skip_llm_when_prompt_exists=False):
        observed["skip"] = skip_llm_when_prompt_exists
        return True, keyframe_task.id, "created"

    monkeypatch.setattr("app.services.shot_keyframe_service.ShotKeyframeService.generate_keyframe_image", fake_generate)
    monkeypatch.setattr(shots_api, "_wait_for_persistent_task", lambda *args, **kwargs: _completed())

    async def _run():
        return await shots_api._prepare_batch_video_details(db_session, batch, child)

    async def _completed():
        return "completed"

    await _run()

    assert observed["skip"] is expected_skip
