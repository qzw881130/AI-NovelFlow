"""Exercise normal state-transfer paths with mocks, no app startup or database writes."""
import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.api import shots
from app.models.shot import Shot
from app.repositories.shot_repository import ShotRepository
from app.services import shot_keyframe_service, shot_video_service
from app.services.shot_video_execution import _video_reference_inputs


@pytest.mark.parametrize("source", ["window_plans", "execution_windows", "clips"])
@pytest.mark.parametrize("change", [None, "range", "duration", "stale", "revision"])
def test_single_recommend_save_get_keep_audio_and_reject_stale_or_changed_ranges(monkeypatch, source, change):
    timeline = SimpleNamespace(id="timeline", revision=1, generated_from_hash="hash", status="READY",
                               total_duration=8, audio_required_duration=4.697, audio_summary_json="{}")
    audio = {"audio_status": "READY", "audio_timeline_id": "timeline", "audio_timeline_revision": 1,
             "audio_timeline_hash": "hash", "clip_audio_duration": 8,
             "drive_audio_url": "/drive.wav", "final_audio_url": "/final.wav"}
    window = {"clip_index" if source == "clips" else "window_index": 1, "start_time": 0, "end_time": 8, **audio}
    if change == "range":
        window["end_time"] = 7
    elif change == "stale":
        window["audio_status"] = "STALE"
    elif change == "revision":
        window["audio_timeline_revision"] = 0
    shot = Shot(id="shot", chapter_id="chapter", index=2, description="Start", duration=8,
                estimated_duration=7.5 if change == "duration" else 8, audio_status="READY",
                video_director_plan=json.dumps({source: [window]}))

    def update(obj, **values):
        for key, value in values.items():
            setattr(obj, key, json.dumps(value) if isinstance(value, (dict, list)) else value)

    db = Mock()
    db.query.return_value.filter.return_value.all.return_value = []
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
    repo = Mock(db=db, get_by_id=Mock(return_value=shot), update=Mock(side_effect=update),
                to_response=ShotRepository(db).to_response)
    chapter_repo = Mock(get_by_id=Mock(return_value=SimpleNamespace(id="chapter")))
    novel_repo = Mock(get_by_id=Mock(return_value=SimpleNamespace(id="novel")))
    monkeypatch.setattr("app.repositories.audio_drive.AudioDriveRepository", lambda _: Mock(
        latest_timeline=Mock(return_value=timeline), list_events=Mock(return_value=[]), list_timeline_events=Mock(return_value=[])))
    monkeypatch.setattr(shots, "_get_video_mode_template", lambda *_: SimpleNamespace(name="07", template="test"))
    monkeypatch.setattr(shots, "_latest_audio_timeline_for_shot", lambda *_: timeline)
    monkeypatch.setattr(shots, "Path", lambda _: SimpleNamespace(is_file=lambda: True))
    monkeypatch.setattr(shots, "url_to_local_path", lambda url: url)
    monkeypatch.setattr(shots.VideoDirectorPlanService, "replace_structure", lambda _, __, plan, revision: (
        update(shot, video_director_plan=plan) or plan, revision + 1))
    llm = SimpleNamespace(chat_completion=AsyncMock(return_value={"success": True, "content": '{"recommended_mode":"SINGLE_FRAME"}'}))
    workflow = SimpleNamespace(name="H3", extension='{"max_clip_duration":15}', node_mapping='{"drive_audio_node_id":"1"}')
    args = dict(db=db, chapter_repo=chapter_repo, novel_repo=novel_repo, shot_repo=repo,
                workflow_repo=Mock(get_active_by_type=Mock(return_value=workflow)), template_repo=Mock(), llm_service=llm)
    recommended = asyncio.run(shots.recommend_video_mode("novel", "chapter", "shot", **args))["data"]
    assert asyncio.run(shots.recommend_video_mode("novel", "chapter", "shot", **args))["data"] == recommended
    llm.chat_completion.assert_awaited_once()
    saved = asyncio.run(shots.save_video_director_plan("novel", "chapter", "shot",
        shots.SaveVideoDirectorPlanRequest(selected_mode="SINGLE_FRAME", expectedRevision=0),
        chapter_repo=chapter_repo, shot_repo=repo))["data"]
    fetched = asyncio.run(shots.get_shot("novel", "chapter", "shot", db=db,
        novel_repo=novel_repo, chapter_repo=chapter_repo, shot_repo=repo))["data"]["videoDirectorPlan"]
    for plan in (recommended, saved, fetched):
        assert plan["execution_windows"] == plan["window_plans"] == []
        assert plan["clips"][0]["end_time"] == shot.estimated_duration
        if change is None:
            assert {key: plan["clips"][0][key] for key in audio} == audio
            shots._assert_audio_drive_ready_for_video(shot, plan, workflow, db=db)
        else:
            with pytest.raises(HTTPException):
                shots._assert_audio_drive_ready_for_video(shot, plan, workflow, db=db)
            if change in {"range", "duration"}:
                assert "drive_audio_url" not in plan["clips"][0]
    assert shot.duration == 8 and shot.audio_status == "READY"
    db.commit.assert_not_called()


def test_replaced_shared_keyframe_is_saved_and_selected_for_both_video_clips(monkeypatch):
    frames = [{"index": i + 1, "role": "START" if i == 0 else "END" if i == 4 else "INTERMEDIATE",
               "time_seconds": time, "image_url": f"/frame{i}.png", "image_task_id": f"task{i}"}
              for i, time in enumerate([0, 2, 4.137, 7, 10])]
    history = [{"step": "09", "parsed_result": deepcopy(frames[2])}]
    plan = {"keyframes": frames, "ai_calls": history}
    legacy = [{**frame, "frame_index": i, "plan_keyframe_index": frame["index"]} for i, frame in enumerate(frames[1:])]
    shot = Shot(id="shot13", chapter_id="chapter", image_url="/start.png", keyframes=json.dumps(legacy), video_director_plan=json.dumps(plan))

    def update(obj, **values):
        for key, value in values.items():
            setattr(obj, key, json.dumps(value))

    db = Mock()
    monkeypatch.setattr(shot_keyframe_service, "ShotRepository", lambda _: Mock(get_by_id=Mock(return_value=shot), update=Mock(side_effect=update)))
    monkeypatch.setattr(shot_keyframe_service, "object_session", lambda _: db)
    monkeypatch.setattr(shot_keyframe_service.VideoDirectorPlanService, "mutate", lambda _, __, mutate: update(shot, video_director_plan=mutate(json.loads(shot.video_director_plan))))
    service = shot_keyframe_service.ShotKeyframeService.__new__(shot_keyframe_service.ShotKeyframeService)
    edited = "/edits/KF2_edit.png"
    assert asyncio.run(service.replace_keyframe_image(db, shot.id, 1, edited))[0]
    saved = json.loads(shot.video_director_plan)
    assert saved["ai_calls"] == history
    assert json.loads(shot.keyframes)[1]["image_url"] == saved["keyframes"][2]["image_url"] == edited
    assert saved["keyframes"][2]["image_task_id"] == "task2"
    monkeypatch.setattr(shot_video_service, "url_to_local_path", lambda url: url)
    monkeypatch.setattr(shot_video_service, "local_path_to_url", lambda path: path)
    frames = shot_video_service._hydrate_plan_keyframes_from_legacy(shot, saved["keyframes"])
    for index, indexes in enumerate(([1, 2, 3], [3, 4, 5]), 1):
        inputs = _video_reference_inputs(shot_video_service, shot, saved, frames, "MULTI_KEYFRAME", True,
            {"clip_index": index, "keyframe_indexes": indexes}, {}, check_files=False)
        assert inputs["references"][2 if index == 1 else 0]["url"] == edited
    assert db.mock_calls == []
