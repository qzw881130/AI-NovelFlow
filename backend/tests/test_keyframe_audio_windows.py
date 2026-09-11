import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.api import shots
from app.services.audio_drive_service import AudioDriveService


@pytest.fixture
def planning(monkeypatch):
    timeline = SimpleNamespace(id="timeline", revision=2, generated_from_hash="hash", status="READY",
                               total_duration=10, audio_required_duration=8.2, audio_summary_json="{}")
    shot = SimpleNamespace(id="shot", chapter_id="chapter", chapter=SimpleNamespace(novel_id="novel"),
                           index=13, estimated_duration=10, duration=10, audio_status="READY", keyframes="[]",
                           description="Start", video_description="End", image_url="/primary.png",
                           characters="[]", props="[]", dialogues="[]", scene="", continuity_mode="NORMAL",
                           video_director_plan=json.dumps({"selected_mode": "MULTI_KEYFRAME",
                                                          "workflow_capability": {"max_clip_duration": 15}}))

    def update(obj, **values):
        for key, value in values.items():
            setattr(obj, key, json.dumps(value) if isinstance(value, (dict, list)) else value)

    repo = Mock(get_by_id=Mock(return_value=shot), update=Mock(side_effect=update))
    audio = AudioDriveService(None)
    audio.shot_repo = repo
    audio.repo = Mock(latest_timeline=Mock(return_value=timeline), list_events=Mock(return_value=[]),
                     list_timeline_events=Mock(return_value=[
                         SimpleNamespace(start_time=start, end_time=end, event_type="NARRATION",
                                         requires_visible_lipsync=False, audio_event_id=str(index), event_order=index,
                                         voice_owner_name="Narrator", visible_speaker_name=None, tts_asset_id=str(index))
                         for index, (start, end) in enumerate([(0, 4.137), (4.137, 8.2)], 1)
                     ]))
    monkeypatch.setattr("app.repositories.audio_drive.AudioDriveRepository", lambda _: audio.repo)
    monkeypatch.setattr(shots, "_latest_audio_timeline_for_shot", lambda *_: timeline)
    monkeypatch.setattr("app.services.audio_drive_service.VideoDirectorPlanService", lambda _: SimpleNamespace(
        mutate=lambda _, mutate: update(shot, video_director_plan=mutate(json.loads(shot.video_director_plan)))))
    monkeypatch.setattr(shots, "_get_keyframe_planner_template", lambda *_: SimpleNamespace(name="08", template="test"))
    monkeypatch.setattr(shots, "get_style", lambda *_: ("test ink style", None))
    monkeypatch.setattr(shots, "_plan_keyframe_transitions", AsyncMock(return_value=[]))

    async def complete(**kwargs):
        payload = json.loads(kwargs["user_content"].split("\n\n", 1)[1])
        windows = payload["execution_windows"]
        times = sorted({time for window in windows for time in (
            window["start_time"], (window["start_time"] + window["end_time"]) / 2, window["end_time"])})
        return {"success": True, "content": json.dumps({
            "keyframes": [{"index": index, "time_seconds": time,
                           "role": "START" if time == 0 else "END" if time == 10 else "INTERMEDIATE"}
                          for index, time in enumerate(times, 1)],
            "window_plans": [{"window_index": window["window_index"], "selected_frame_count": 3,
                              "keyframe_indexes": [i for i, time in enumerate(times, 1)
                                                   if window["start_time"] <= time <= window["end_time"]]}
                             for window in windows],
        })}

    llm = SimpleNamespace(chat_completion=AsyncMock(side_effect=complete))
    workflows = {kind: SimpleNamespace(name=kind, extension=json.dumps({"max_clip_duration": 15}))
                 for kind in ("video", "three_frame_video", "four_frame_video")}

    def replan(force=True):
        return asyncio.run(shots.plan_video_keyframes(
            "novel", "chapter", shot.id, shots.PlanVideoKeyframesRequest(force=force), db=None,
            novel_repo=Mock(get_by_id=Mock(return_value=SimpleNamespace(id="novel"))),
            chapter_repo=Mock(get_by_id=Mock(return_value=SimpleNamespace(id="chapter"))),
            shot_repo=repo, workflow_repo=Mock(get_active_by_type=Mock(side_effect=workflows.get)),
            template_repo=Mock(), llm_service=llm,
        ))["data"]

    assert audio.build_execution_windows(shot.id, max_clip_duration=6)["success"]
    plan = json.loads(shot.video_director_plan)
    for window in plan["window_plans"]:
        window.update(audio_status="READY", audio_timeline_id=timeline.id, audio_timeline_revision=2,
                      audio_timeline_hash="hash", drive_audio_url=f"/drive{window['window_index']}.wav",
                      final_audio_url=f"/final{window['window_index']}.wav", speaker_timeline=[],
                      clip_audio_duration=window["duration"], clip_audio_manifest_path="/manifest.json")
    shot.video_director_plan = json.dumps(plan)
    return SimpleNamespace(shot=shot, timeline=timeline, audio=audio, replan=replan, llm=llm, workflows=workflows)


@pytest.mark.parametrize("binding", ["built", "legacy", "before_audio"])
def test_manual_windows_survive_forced_replan_and_audio_stays_reusable(planning, monkeypatch, binding):
    plan = json.loads(planning.shot.video_director_plan)
    if binding == "legacy":
        for window in plan["execution_windows"]:
            for key in ("audio_timeline_id", "audio_timeline_revision", "audio_timeline_hash"):
                window.pop(key)
    elif binding == "before_audio":
        plan["window_plans"] = []
    planning.shot.video_director_plan = json.dumps(plan)
    before = deepcopy(plan["window_plans"])
    assert [w["duration"] for w in plan["execution_windows"]] == [4.137, 5.863]
    saved = planning.replan()
    assert saved["execution_windows"] == plan["execution_windows"]
    assert [(w["start_time"], w["end_time"]) for w in saved["window_plans"]] == [(0, 4.137), (4.137, 10)]
    assert saved["keyframe_planning_status"] == "READY"
    assert len(saved["keyframes"]) == 5
    assert saved["window_plans"][0]["keyframe_indexes"][-1] == saved["window_plans"][1]["keyframe_indexes"][0]
    payload = json.loads(planning.llm.chat_completion.call_args.kwargs["user_content"].split("\n\n", 1)[1])
    assert payload["execution_windows"] == plan["execution_windows"]
    assert shots._execution_windows_match_duration(saved["execution_windows"], 10, 15)
    for keyframe in saved["keyframes"]:
        keyframe["image_url"] = "/keyframe.png"
    assert shots._validate_multi_keyframe_plan_for_execution(planning.shot, saved)[0]
    monkeypatch.setattr("app.services.audio_drive_service.file_storage.get_clip_audio_path", Mock(return_value=Mock(exists=lambda: True)))
    monkeypatch.setattr("app.services.rendered_subtitles.load", Mock(return_value={"cues": []}))
    planning.audio._render_clip_audio = Mock(side_effect=AssertionError("Must reuse, not render"))
    for old, new in zip(before, saved["window_plans"]):
        assert {key: new[key] for key in old if key not in {"duration", "boundary_reason"}} == {
            key: value for key, value in old.items() if key not in {"duration", "boundary_reason"}}
        result = planning.audio.build_clip_audio(planning.shot.id, new["window_index"], force=False)
        assert result["success"] and result["data"]["audioStatus"] == "READY"
    planning.audio._render_clip_audio.assert_not_called()
    assert planning.replan()["execution_windows"] == plan["execution_windows"]


@pytest.mark.parametrize("defect", ["gap", "overlap", "partial", "nan", "index", "duration", "stale_id", "stale_revision", "stale_hash", "stale_status", "workflow_cap"])
def test_invalid_or_stale_windows_are_rebuilt_not_preserved(planning, defect):
    plan = json.loads(planning.shot.video_director_plan)
    window = plan["execution_windows"][1]
    if defect in {"gap", "overlap", "partial", "nan", "index", "duration"}:
        key, value = {"gap": ("start_time", 5), "overlap": ("start_time", 4), "partial": ("end_time", 9),
                      "nan": ("end_time", float("nan")), "index": ("window_index", "bad"), "duration": ("duration", 1)}[defect]
        window[key] = value
    elif defect in {"stale_id", "stale_revision", "stale_hash", "stale_status"}:
        key, value = {"stale_id": ("audio_timeline_id", "old"), "stale_revision": ("audio_timeline_revision", 1), "stale_hash": ("audio_timeline_hash", "old"),
                      "stale_status": ("audio_status", "STALE")}[defect]
        for item in plan["execution_windows"] + plan["window_plans"]:
            item[key] = value
    else:
        planning.workflows["four_frame_video"].extension = json.dumps({"max_clip_duration": 5})
    planning.shot.video_director_plan = json.dumps(plan)
    saved = planning.replan(force=False)
    cap = 5 if defect == "workflow_cap" else 15
    expected = shots._build_execution_windows(10, cap, [{"start_time": 0, "end_time": 4.137}, {"start_time": 4.137, "end_time": 8.2}])
    assert saved["execution_windows"] == expected
    assert saved["workflow_capability"]["max_clip_duration"] == cap
    assert all(w.get("audio_status") != "READY" for w in saved["window_plans"] if w["end_time"] != 4.137)


def test_new_timeline_revision_bypasses_cached_plan_and_stale_audio(planning):
    planning.replan()
    planning.timeline.revision = 3
    saved = planning.replan(force=False)
    assert saved["audio_timeline"]["revision"] == 3
    assert len(saved["execution_windows"]) == 1
    assert saved["window_plans"][0].get("audio_status") != "READY"


def test_current_windows_do_not_rebind_old_clip_audio(planning):
    plan = json.loads(planning.shot.video_director_plan)
    plan["window_plans"][0]["audio_timeline_revision"] = 1
    planning.shot.video_director_plan = json.dumps(plan)
    saved = planning.replan()
    assert saved["execution_windows"] == plan["execution_windows"]
    assert saved["window_plans"][0].get("audio_status") != "READY"
    assert saved["window_plans"][1]["audio_status"] == "READY"


def test_rebuilt_windows_survive_llm_validation_retry(planning):
    planning.workflows["four_frame_video"].extension = json.dumps({"max_clip_duration": 5})
    complete = planning.llm.chat_completion.side_effect

    async def retry(**kwargs):
        if planning.llm.chat_completion.await_count == 1:
            return {"success": True, "content": "{}"}
        return await complete(**kwargs)

    planning.llm.chat_completion.side_effect = retry
    saved = planning.replan()
    assert len(saved["execution_windows"]) == len(saved["window_plans"]) == 3
    assert saved["workflow_capability"]["max_clip_duration"] == 5
    assert planning.llm.chat_completion.await_count == 2


@pytest.mark.parametrize("missing", [False, True])
def test_stale_timeline_and_single_mode_reject_without_planning(planning, monkeypatch, missing):
    planning.timeline.status = "STALE"
    if missing:
        monkeypatch.setattr(shots, "_latest_audio_timeline_for_shot", lambda *_: None)
    before = planning.shot.video_director_plan
    with pytest.raises(HTTPException) as exc:
        planning.replan()
    assert exc.value.status_code == 400
    assert planning.shot.video_director_plan == before
    plan = json.loads(before)
    plan["selected_mode"] = "SINGLE_FRAME"
    planning.shot.video_director_plan = json.dumps(plan)
    with pytest.raises(HTTPException) as exc:
        planning.replan()
    assert exc.value.status_code == 400
    planning.llm.chat_completion.assert_not_called()
