import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.api import shots as api
from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.task import Task
from app.models.audio_drive import ShotAudioTimeline
from app.repositories import ChapterRepository, NovelRepository, ShotRepository


@pytest.fixture
def batch(db_session, monkeypatch):
    novel = Novel(title="Batch failures")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="Chapter", content="content")
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(
        chapter_id=chapter.id, index=1, description="Shot", duration=4,
        video_status="pending", video_director_plan=json.dumps({"clips": [{"video_url": "old-clip.mp4"}]}),
    )
    db_session.add(shot)
    db_session.commit()
    monkeypatch.setattr(api, "SessionLocal", lambda: db_session)

    def submit(**options):
        response = asyncio.run(api.generate_shot_videos_batch(
            novel.id, chapter.id, api.BatchShotVideoRequest(shot_ids=[shot.id], **options),
            novel_repo=NovelRepository(db_session), chapter_repo=ChapterRepository(db_session),
            shot_repo=ShotRepository(db_session), db=db_session,
        ))
        return response["data"]["taskId"]

    return shot, submit


@pytest.mark.parametrize("stage", ["prepare", "generate"])
@pytest.mark.parametrize("error", [HTTPException(400, "Missing workflow"), RuntimeError("Clip audio unavailable"), TimeoutError()])
def test_preflight_failure_persists_without_child(db_session, monkeypatch, batch, stage, error):
    shot, submit = batch
    shot_id = shot.id
    parent_id = submit()
    assert shot.video_task_id == parent_id
    assert shot.video_status == "pending"
    prepare = AsyncMock(return_value="SINGLE_FRAME")
    generate = AsyncMock()
    (prepare if stage == "prepare" else generate).side_effect = error
    monkeypatch.setattr(api, "_ensure_shot_ready_for_batch_video", prepare)
    monkeypatch.setattr(api, "_generate_shot_video", generate)

    asyncio.run(api.run_shot_video_batch_task(parent_id))

    shot = db_session.get(Shot, shot_id)
    parent = db_session.get(Task, parent_id)
    message = str(error.detail) if isinstance(error, HTTPException) else str(error) or type(error).__name__
    assert shot.video_status == "failed"
    assert shot.video_task_id == parent_id
    plan = json.loads(shot.video_director_plan)
    assert plan["error_message"] == plan["task_error_message"] == message
    assert plan["clips"] == [{"video_url": "old-clip.mp4"}]
    assert shot.video_director_plan_revision == 1
    assert json.loads(parent.metadata_json)["results"][shot_id]["message"] == message
    assert parent.status == "failed"
    assert db_session.query(Task).filter(Task.type == "shot_video").count() == 0


def test_legacy_unbound_pending_shot_is_claimed(db_session, monkeypatch, batch):
    shot, submit = batch
    shot_id = shot.id
    parent_id = submit()
    shot.video_task_id = None
    db_session.commit()
    monkeypatch.setattr(api, "_ensure_shot_ready_for_batch_video", AsyncMock(side_effect=RuntimeError("preflight")))
    asyncio.run(api.run_shot_video_batch_task(parent_id))
    shot = db_session.get(Shot, shot_id)
    assert (shot.video_status, shot.video_task_id) == ("failed", parent_id)


@pytest.mark.parametrize("raise_error", [True, False])
def test_new_owner_during_preflight_is_not_overwritten(db_session, monkeypatch, batch, raise_error):
    shot, submit = batch
    shot_id = shot.id
    parent_id = submit()

    async def prepare(*args, **kwargs):
        shot.video_task_id = "new-task"
        shot.video_status = "generating"
        shot.video_director_plan = '{"new_plan": true}'
        db_session.commit()
        if raise_error:
            raise RuntimeError("old preflight")
        return "SINGLE_FRAME"

    generate = AsyncMock()
    monkeypatch.setattr(api, "_ensure_shot_ready_for_batch_video", prepare)
    monkeypatch.setattr(api, "_generate_shot_video", generate)
    asyncio.run(api.run_shot_video_batch_task(parent_id))
    shot = db_session.get(Shot, shot_id)
    assert (shot.video_status, shot.video_task_id) == ("generating", "new-task")
    assert json.loads(shot.video_director_plan) == {"new_plan": True}
    generate.assert_not_awaited()


def test_historical_video_survives_failed_replacement(db_session, monkeypatch, batch):
    shot, submit = batch
    shot_id = shot.id
    shot.video_status = "completed"
    shot.video_url = "/api/files/historical.mp4"
    db_session.commit()
    parent_id = submit()
    monkeypatch.setattr(api, "_ensure_shot_ready_for_batch_video", AsyncMock(side_effect=RuntimeError("preflight")))
    asyncio.run(api.run_shot_video_batch_task(parent_id))
    shot = db_session.get(Shot, shot_id)
    assert shot.video_status == "completed"
    assert shot.video_url == "/api/files/historical.mp4"
    assert json.loads(shot.video_director_plan)["task_error_message"] == "preflight"


def test_active_child_not_rebound_by_batch_creation(db_session, monkeypatch, batch):
    shot, submit = batch
    shot_id = shot.id
    chapter = db_session.get(Chapter, shot.chapter_id)
    child = Task(type="shot_video", status="running", name="child", shot_id=shot.id,
                 novel_id=chapter.novel_id, chapter_id=chapter.id)
    db_session.add(child)
    db_session.flush()
    child_id = child.id
    shot.video_task_id = child_id
    shot.video_status = "generating"
    db_session.commit()
    parent_id = submit()
    assert shot.video_task_id == child_id
    prepare = AsyncMock()
    monkeypatch.setattr(api, "_ensure_shot_ready_for_batch_video", prepare)
    asyncio.run(api.run_shot_video_batch_task(parent_id))
    shot = db_session.get(Shot, shot_id)
    assert (shot.video_status, shot.video_task_id) == ("generating", child_id)
    assert db_session.get(Task, child_id).parent_task_id is None
    prepare.assert_not_awaited()


@pytest.mark.parametrize("child_status", [None, "failed", "completed"])
def test_child_outcome_and_ownership_handoff(db_session, monkeypatch, batch, child_status):
    shot, submit = batch
    shot_id = shot.id
    parent_id = submit()
    child_id = None

    async def generate(*args, **kwargs):
        nonlocal child_id
        if child_status is None:
            return {"data": {}}
        child = Task(type="shot_video", status=child_status, name="child", shot_id=shot.id,
                     parent_task_id=kwargs["parent_task_id"], batch_order=kwargs["batch_order"],
                     error_message="Child failed" if child_status == "failed" else None)
        db_session.add(child)
        db_session.flush()
        child_id = child.id
        shot.video_task_id = child.id
        shot.video_status = "completed" if child_status == "completed" else "generating"
        if child_status == "completed":
            shot.video_url = "/api/files/new.mp4"
        db_session.commit()
        return {"data": {"taskId": child.id}}

    monkeypatch.setattr(api, "_ensure_shot_ready_for_batch_video", AsyncMock(return_value="SINGLE_FRAME"))
    monkeypatch.setattr(api, "_generate_shot_video", generate)
    asyncio.run(api.run_shot_video_batch_task(parent_id))
    shot = db_session.get(Shot, shot_id)
    assert shot.video_task_id == (child_id or parent_id)
    assert shot.video_status == ("completed" if child_status == "completed" else "failed")
    if child_id:
        assert db_session.get(Task, child_id).parent_task_id == parent_id
    plan = json.loads(shot.video_director_plan)
    assert ("task_error_message" in plan) == (child_status != "completed")


def test_completed_batch_persists_all_fourteen_preflight_failures(db_session, monkeypatch, batch):
    shot, submit = batch
    parent_id = submit()
    failed_shots = [
        Shot(chapter_id=shot.chapter_id, index=index, description="Preflight failure", duration=4,
             video_task_id=parent_id, video_status="pending")
        for index in range(2, 16)
    ]
    db_session.add_all(failed_shots)
    db_session.flush()
    failed_ids = [item.id for item in failed_shots]
    parent = db_session.get(Task, parent_id)
    metadata = json.loads(parent.metadata_json)
    metadata["shot_ids"] += failed_ids
    parent.metadata_json = json.dumps(metadata)
    db_session.commit()

    async def prepare(db, parent, current_shot, *args, **kwargs):
        if current_shot.id != shot.id:
            raise RuntimeError("Missing clip audio")
        return "SINGLE_FRAME"

    async def generate(*args, **kwargs):
        child = Task(type="shot_video", status="completed", name="completed child", shot_id=shot.id,
                     parent_task_id=kwargs["parent_task_id"], batch_order=kwargs["batch_order"],
                     result_url="/api/files/success.mp4")
        db_session.add(child)
        db_session.flush()
        shot.video_status = "completed"
        shot.video_url = child.result_url
        shot.video_task_id = child.id
        db_session.commit()
        return {"data": {"taskId": child.id}}

    monkeypatch.setattr(api, "_ensure_shot_ready_for_batch_video", prepare)
    monkeypatch.setattr(api, "_generate_shot_video", generate)

    asyncio.run(api.run_shot_video_batch_task(parent_id))

    parent = db_session.get(Task, parent_id)
    metadata = json.loads(parent.metadata_json)
    assert parent.status == "completed"
    assert (metadata["success_count"], metadata["failed_count"]) == (1, 14)
    for shot_id in failed_ids:
        failed_shot = db_session.get(Shot, shot_id)
        assert failed_shot.video_status == "failed"
        assert failed_shot.video_task_id == parent_id
        assert json.loads(failed_shot.video_director_plan)["task_error_message"] == "Missing clip audio"
        assert metadata["results"][shot_id]["status"] == "failed"


def test_outer_batch_failure_releases_parent_owned_shots(db_session, monkeypatch, batch):
    shot, submit = batch
    shot_id = shot.id
    parent_id = submit()
    def fail_setup(db):
        raise RuntimeError("Batch setup failed")

    monkeypatch.setattr(api, "NovelRepository", fail_setup)
    asyncio.run(api.run_shot_video_batch_task(parent_id))
    shot = db_session.get(Shot, shot_id)
    assert shot.video_status == "failed"
    assert json.loads(shot.video_director_plan)["task_error_message"] == "Batch setup failed"
    assert db_session.get(Task, parent_id).status == "failed"


def test_failure_does_not_replace_completed_shot_or_plan(db_session, batch):
    shot, submit = batch
    parent_id = submit()
    shot.video_status = "completed"
    shot.video_url = "/api/files/completed.mp4"
    db_session.commit()
    previous_plan = shot.video_director_plan
    previous_revision = shot.video_director_plan_revision

    api._persist_batch_video_failure(db_session, shot.id, parent_id, "Late failure")
    db_session.commit()
    db_session.refresh(shot)

    assert shot.video_status == "completed"
    assert shot.video_url == "/api/files/completed.mp4"
    assert shot.video_director_plan == previous_plan
    assert shot.video_director_plan_revision == previous_revision


@pytest.fixture
def auto_details(db_session, monkeypatch, batch, tmp_path):
    shot, submit = batch
    audio_path = tmp_path / "current.wav"
    audio_path.write_bytes(b"existing audio; never rendered by these tests")
    shot.image_url = "/primary.png"
    shot.estimated_duration = shot.duration = 10
    shot.audio_status = "READY"
    timeline = ShotAudioTimeline(shot_id=shot.id, revision=2, total_duration=10, status="READY", generated_from_hash="hash")
    db_session.add(timeline)
    db_session.flush()
    window = {"window_index": 1, "start_time": 0, "end_time": 10, "audio_status": "READY",
              "audio_timeline_id": timeline.id, "audio_timeline_revision": 2, "audio_timeline_hash": "hash",
              "drive_audio_path": str(audio_path), "final_audio_path": str(audio_path)}
    frames = [{"index": 1, "role": "START", "time_seconds": 0, "description": "Start"},
              {"index": 2, "role": "END", "time_seconds": 10, "description": "End", "image_url": "/end.png"}]
    transition = {"from_keyframe_index": 1, "to_keyframe_index": 2, "start_time": 0, "end_time": 10,
                  "transition_description": "Move continuously to the end."}
    shot.keyframes = json.dumps(api._build_legacy_keyframes_from_plan(shot, frames))
    shot.video_director_plan = json.dumps({"selected_mode": "FIRST_LAST_FRAME", "keyframes": frames,
        "execution_windows": [window], "clips": api._build_first_last_clip_plan(10), "window_plans": [],
        "keyframe_planning_status": "STALE"})
    db_session.commit()
    audio = Mock(get_timeline=Mock(return_value={"success": True, "data": {"status": "READY"}}),
                 build_execution_windows=Mock(side_effect=AssertionError("Do not rewindow current audio")),
                 build_clip_audio=Mock(side_effect=AssertionError("Do not rerender current audio")))
    llm = SimpleNamespace(chat_completion=AsyncMock(return_value={"success": True, "content": json.dumps({
        "keyframes": frames, "window_plans": [], "validation": {"executable": True}})}))
    images = Mock(generate_keyframe_image=AsyncMock(side_effect=AssertionError("Reuse the compatible END")))
    transitions = AsyncMock(return_value=[transition])
    generate = AsyncMock(side_effect=RuntimeError("video admission probe"))
    monkeypatch.setattr("app.services.audio_drive_service.AudioDriveService", lambda _: audio)
    monkeypatch.setattr(api, "LLMService", lambda: llm)
    monkeypatch.setattr(api, "ShotKeyframeService", lambda: images)
    monkeypatch.setattr(api, "_get_keyframe_planner_template", lambda *_: SimpleNamespace(name="08", template="test"))
    monkeypatch.setattr(api, "_plan_keyframe_transitions", transitions)
    monkeypatch.setattr(api, "_generate_shot_video", generate)
    parent_id = submit(auto_complete=True)
    return SimpleNamespace(shot=shot, shot_id=shot.id, parent_id=parent_id, timeline=timeline, window=window, frames=frames,
                           transition=transition, audio=audio, llm=llm, images=images, transitions=transitions, generate=generate)


@pytest.mark.parametrize("failure", ["admission", "planner", "transition", "keyframe", "incomplete_transition"])
def test_real_auto_details_keeps_owner_and_persists_failure(db_session, auto_details, failure):
    state = auto_details
    if failure == "planner":
        state.llm.chat_completion.return_value = {"success": False, "error": "planner failed"}
    elif failure == "transition":
        state.transitions.side_effect = RuntimeError("transition failed")
    elif failure == "incomplete_transition":
        state.transitions.return_value = []
    elif failure == "keyframe":
        frames = json.loads(state.shot.keyframes)
        frames[0]["image_url"] = None
        state.shot.keyframes = json.dumps(frames)
        db_session.commit()
        state.images.generate_keyframe_image.side_effect = None
        state.images.generate_keyframe_image.return_value = (False, None, "#09 UNBOUND_ASSET_REFERENCE")
    asyncio.run(api.run_shot_video_batch_task(state.parent_id))
    state.shot = db_session.get(Shot, state.shot_id)
    parent = db_session.get(Task, state.parent_id)
    result = json.loads(parent.metadata_json)["results"][state.shot.id]
    assert result["status"] == "failed" and "ownership changed" not in result["message"]
    assert state.shot.video_task_id == parent.id and state.shot.video_status == "failed"
    assert json.loads(state.shot.video_director_plan)["task_error_message"] == result["message"]
    assert db_session.query(Task).filter(Task.type == "shot_video").count() == 0
    assert state.generate.await_count == (1 if failure == "admission" else 0)
    state.audio.build_execution_windows.assert_not_called()
    state.audio.build_clip_audio.assert_not_called()
    if failure == "admission":
        assert json.loads(state.shot.keyframes)[0]["image_url"] == "/end.png"


@pytest.mark.parametrize("change", ["owner", "plan", "parent"])
def test_staged_planner_cannot_overwrite_concurrent_changes(db_session, auto_details, change):
    state = auto_details
    answer = state.llm.chat_completion.return_value

    async def concurrent_plan(**kwargs):
        if change == "owner":
            state.shot.video_task_id = "other-video"
            state.shot.video_status = "generating"
        elif change == "parent":
            db_session.get(Task, state.parent_id).status = "cancelled"
        state.shot.video_director_plan = '{"user_note": "concurrent change"}'
        state.shot.video_director_plan_revision += 1
        db_session.commit()
        return answer

    state.llm.chat_completion.side_effect = concurrent_plan
    asyncio.run(api.run_shot_video_batch_task(state.parent_id))
    state.shot = db_session.get(Shot, state.shot_id)
    saved = json.loads(state.shot.video_director_plan)
    assert saved["user_note"] == "concurrent change" and "keyframes" not in saved
    if change == "owner":
        assert (state.shot.video_task_id, state.shot.video_status) == ("other-video", "generating")
        assert "task_error_message" not in saved
    state.generate.assert_not_awaited()


@pytest.mark.parametrize("defect", [None, "stale", "placeholder", "missing_transition", "wrong_transition"])
def test_first_last_readiness_checks_plan_and_transitions(db_session, auto_details, defect):
    state = auto_details
    plan = json.loads(state.shot.video_director_plan)
    plan.update(keyframe_planning_status="READY", transitions=[state.transition])
    if defect == "stale":
        plan["keyframe_planning_status"] = "STALE"
    elif defect == "placeholder":
        plan["keyframes"] = api._build_minimal_keyframes(state.shot, "FIRST_LAST_FRAME", 15)
        plan.pop("transitions")
    elif defect == "missing_transition":
        plan["transitions"] = []
    elif defect == "wrong_transition":
        plan["transitions"] = [{**state.transition, "to_keyframe_index": 3}]
    state.shot.video_director_plan = json.dumps(plan)
    db_session.commit()
    asyncio.run(api.run_shot_video_batch_task(state.parent_id))
    assert state.llm.chat_completion.await_count == (0 if defect is None else 1)
    state.generate.assert_awaited_once()


@pytest.mark.parametrize("missing_audio", [None, "stale", "missing_file", "old_hash"])
def test_batch_preserves_manual_two_windows_and_current_clip_audio(db_session, auto_details, missing_audio):
    state = auto_details
    windows = [{**state.window, "window_index": index, "start_time": start, "end_time": end,
                "selected_frame_count": 3, "keyframe_indexes": indexes}
               for index, (start, end, indexes) in enumerate([(0, 4.137, [1, 2, 3]), (4.137, 10, [3, 4, 5])], 1)]
    frames = [{"index": index, "time_seconds": time, "role": "START" if index == 1 else "END" if index == 5 else "INTERMEDIATE",
               "description": f"State {index}", "image_url": f"/frame{index}.png"}
              for index, time in enumerate([0, 2, 4.137, 7, 10], 1)]
    if missing_audio == "stale":
        windows[1]["audio_status"] = "STALE"
    geometry = [{k: v for k, v in window.items() if k in ("window_index", "start_time", "end_time", "audio_timeline_id", "audio_timeline_revision", "audio_timeline_hash")}
                for window in windows]
    if missing_audio == "missing_file":
        windows[1]["final_audio_path"] += ".missing"
    elif missing_audio == "old_hash":
        windows[1]["audio_timeline_hash"] = "old"
    state.shot.video_director_plan = json.dumps({"selected_mode": "MULTI_KEYFRAME", "keyframe_planning_status": "READY",
                                               "execution_windows": geometry, "window_plans": windows, "keyframes": frames})
    state.shot.keyframes = json.dumps(api._build_legacy_keyframes_from_plan(state.shot, frames))
    db_session.commit()
    state.audio.build_clip_audio.side_effect = None
    state.audio.build_clip_audio.return_value = {"success": True}
    asyncio.run(api.run_shot_video_batch_task(state.parent_id))
    state.shot = db_session.get(Shot, state.shot_id)
    saved = json.loads(state.shot.video_director_plan)
    assert saved["execution_windows"] == geometry
    assert saved["window_plans"] == windows
    assert saved["keyframes"] == frames
    state.audio.build_execution_windows.assert_not_called()
    state.llm.chat_completion.assert_not_awaited()
    state.images.generate_keyframe_image.assert_not_awaited()
    if missing_audio:
        state.audio.build_clip_audio.assert_called_once_with(state.shot.id, 2, force=False)
    else:
        state.audio.build_clip_audio.assert_not_called()
    state.generate.assert_awaited_once()


def test_unready_timeline_fails_without_invalidating_owner_or_rebuilding_tts(db_session, auto_details):
    state = auto_details
    state.audio.get_timeline.return_value = {"success": True, "data": {"status": "STALE"}}
    asyncio.run(api.run_shot_video_batch_task(state.parent_id))
    shot = db_session.get(Shot, state.shot_id)
    assert shot.video_task_id == state.parent_id and shot.video_status == "failed"
    assert "Audio Timeline" in json.loads(shot.video_director_plan)["task_error_message"]
    state.audio.build_timeline.assert_not_called()
    state.generate.assert_not_awaited()


def test_staged_planning_does_not_clear_an_existing_video(db_session, auto_details):
    state = auto_details
    state.shot.video_url = "/existing.mp4"
    state.shot.video_status = "completed"
    db_session.commit()
    asyncio.run(api.run_shot_video_batch_task(state.parent_id))
    shot = db_session.get(Shot, state.shot_id)
    assert (shot.video_url, shot.video_status, shot.video_task_id) == ("/existing.mp4", "completed", state.parent_id)
    state.generate.assert_awaited_once()
