import asyncio
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from app.api import shots
from app.models.shot import Shot


def planner_result(mode, count=3, duration=14.3):
    times = [0, duration] if mode == "FIRST_LAST_FRAME" else [0, *([5] if count == 3 else [4, 9]), duration]
    return {
        "validation": {"executable": True},
        "keyframes": [
            {"index": i, "time_seconds": time, "role": "START" if i == 1 else "END" if time == duration else "INTERMEDIATE"}
            for i, time in enumerate(times, 1)
        ],
        "window_plans": [] if mode == "FIRST_LAST_FRAME" else [
            {"window_index": 1, "selected_frame_count": count, "keyframe_indexes": list(range(1, count + 1))}
        ],
    }


@pytest.mark.parametrize("windows", [[], [{"window_index": 1, "audio_status": "READY"}]])
def test_first_last_accepts_empty_llm_windows(windows):
    frames, plans, _ = shots._normalize_keyframe_planner_result(planner_result("FIRST_LAST_FRAME"), windows, 14.3, "FIRST_LAST_FRAME", 15)
    assert [frame["time_seconds"] for frame in frames] == [0, 14.3]
    assert plans == []


@pytest.mark.parametrize("defect", ["extra", "role", "start", "end", "index", "windows", "missing_windows", "too_long"])
def test_first_last_rejects_invalid_contract(defect):
    result = planner_result("FIRST_LAST_FRAME")
    if defect == "extra":
        result["keyframes"].append({"index": 3, "role": "INTERMEDIATE", "time_seconds": 7})
    elif defect in {"role", "start", "end", "index"}:
        frame, key, value = {
            "role": (1, "role", "INTERMEDIATE"), "start": (0, "time_seconds", 0.001),
            "end": (1, "time_seconds", 14), "index": (1, "index", 1),
        }[defect]
        result["keyframes"][frame][key] = value
    elif defect == "windows":
        result["window_plans"] = [{"window_index": 1}]
    elif defect == "missing_windows":
        result.pop("window_plans")
    with pytest.raises(ValueError):
        shots._normalize_keyframe_planner_result(result, [], 14.3, "FIRST_LAST_FRAME", 14 if defect == "too_long" else 15)


@pytest.mark.parametrize("count", [3, 4])
def test_multi_keeps_strict_window_and_frame_matching(count):
    result = planner_result("MULTI_KEYFRAME", count)
    windows = [{"window_index": 1, "start_time": 0, "end_time": 14.3}]
    _, plans, _ = shots._normalize_keyframe_planner_result(result, windows, 14.3, "MULTI_KEYFRAME", 15)
    assert plans[0]["selected_frame_count"] == count
    for invalid in ([], [{"window_index": 1, "selected_frame_count": 2, "keyframe_indexes": [1, 2]}],
                    [{"window_index": 1, "selected_frame_count": count, "keyframe_indexes": [1, 2]}],
                    [{"window_index": 2, "selected_frame_count": count, "keyframe_indexes": list(range(1, count + 1))}]):
        with pytest.raises(ValueError):
            shots._normalize_keyframe_planner_result({**result, "window_plans": invalid}, windows, 14.3, "MULTI_KEYFRAME", 15)


def test_multi_rejects_duplicate_window_mapping():
    result = planner_result("MULTI_KEYFRAME")
    result["window_plans"] *= 2
    windows = [{"window_index": 1}, {"window_index": 2}]
    with pytest.raises(ValueError, match="distinct execution_windows"):
        shots._normalize_keyframe_planner_result(result, windows, 14.3, "MULTI_KEYFRAME", 15)


def test_audio_is_not_rebound_to_changed_duration():
    clips = shots._preserve_matching_clip_audio_fields(
        shots._build_first_last_clip_plan(14.3),
        [{"window_index": 1, "start_time": 0, "end_time": 12, "audio_status": "READY", "drive_audio_path": "/old.wav"}],
    )
    assert clips[0]["end_time"] == 14.3
    assert "audio_status" not in clips[0]


@pytest.mark.parametrize("mode", ["FIRST_LAST_FRAME", "MULTI_KEYFRAME"])
@pytest.mark.parametrize("source", ["execution_windows", "window_plans", "clips"])
def test_planning_call_preserves_ready_audio_and_canonical_duration(monkeypatch, mode, source):
    audio = {
        "audio_status": "READY", "audio_message": "ready", "audio_timeline_id": "timeline",
        "audio_timeline_revision": 2, "audio_timeline_hash": "hash", "speaker_timeline": [{"speaker": "A"}],
        "drive_audio_url": "/drive.wav", "final_audio_url": "/final.wav",
        "drive_audio_path": "/audio/drive.wav", "final_audio_path": "/audio/final.wav",
        "clip_audio_manifest_path": "/audio/manifest.json", "clip_audio_duration": 14.3,
    }
    binding = {"window_index": 1, "start_time": 0, "end_time": 14.3, **audio}
    timeline = {"id": "timeline", "revision": 2, "source_hash": "hash",
                "audio_required_duration": 14.3, "resolved_duration": 14.3, "events": []}
    plan = {"selected_mode": mode, "workflow_capability": {"max_clip_duration": 15},
            "keyframe_planning_status": "STALE", "keyframe_planning_message": "Old audio build",
            "audio_timeline": timeline, source: [deepcopy(binding)]}
    shot = Shot(id="shot46", chapter_id="chapter", index=46, description="Start", video_description="End",
                estimated_duration=12, duration=99, audio_status="READY", video_director_plan=json.dumps(plan))

    def update(obj, **values):
        for key, value in values.items():
            setattr(obj, key, json.dumps(value) if isinstance(value, (dict, list)) else value)

    repo = Mock(get_by_id=Mock(return_value=shot), update=Mock(side_effect=update))
    monkeypatch.setattr(shots, "_latest_audio_timeline_for_shot", Mock(return_value=SimpleNamespace(
        id="timeline", revision=2, generated_from_hash="hash", status="READY")))
    monkeypatch.setattr(shots, "_sync_latest_audio_timeline_into_plan", lambda *_: json.loads(shot.video_director_plan))
    template = SimpleNamespace(name="08 V2", template=(Path(__file__).parents[1] / "prompt_templates/08_NovelFlow_VideoDirector_KeyframePlanner_V2_3Frame4Frame.txt").read_text())
    monkeypatch.setattr(shots, "_get_keyframe_planner_template", Mock(return_value=template))
    monkeypatch.setattr(shots, "get_style", Mock(return_value=("test ink style", None)))
    transitions = AsyncMock(return_value=[])
    monkeypatch.setattr(shots, "_plan_keyframe_transitions", transitions)
    llm = SimpleNamespace(chat_completion=AsyncMock(return_value={"success": True, "content": json.dumps(planner_result(mode))}))
    result = asyncio.run(shots.plan_video_keyframes(
        "novel", "chapter", shot.id, shots.PlanVideoKeyframesRequest(force=True), db=None,
        novel_repo=Mock(get_by_id=Mock(return_value=SimpleNamespace(id="novel"))),
        chapter_repo=Mock(get_by_id=Mock(return_value=SimpleNamespace(id="chapter"))),
        shot_repo=repo, workflow_repo=Mock(get_active_by_type=Mock(return_value=None)),
        template_repo=Mock(), llm_service=llm,
    ))
    saved = result["data"]
    assert saved["keyframe_planning_status"] == "READY"
    assert "keyframe_planning_message" not in saved
    persisted = json.loads(shot.video_director_plan)
    assert persisted["keyframe_planning_status"] == "READY"
    assert "keyframe_planning_message" not in persisted
    target = saved["clips" if mode == "FIRST_LAST_FRAME" else "window_plans"][0]
    assert {key: target[key] for key in audio} == audio
    assert target["end_time"] == 14.3
    assert saved["keyframes"][-1]["time_seconds"] == 14.3
    assert saved["audio_timeline"] == timeline
    assert shot.duration == 99 and shot.estimated_duration == 12 and shot.audio_status == "READY"
    assert llm.chat_completion.await_count == 1
    payload = json.loads(llm.chat_completion.call_args.kwargs["user_content"].split("\n\n", 1)[1])
    assert payload["shot"]["duration"] == 14.3
    assert payload["visual_style"] == "test ink style"
    assert "##STYLE##" not in llm.chat_completion.call_args.kwargs["system_prompt"]
    assert "test ink style" in llm.chat_completion.call_args.kwargs["system_prompt"]
    assert "##STYLE##" in template.template
    if mode == "FIRST_LAST_FRAME":
        assert payload["execution_windows"] == []
        assert saved["window_plans"] == []
    else:
        assert len(payload["execution_windows"]) == 1


@pytest.mark.parametrize("change", [None, "time_seconds", "description", "role", "index", "missing_time"])
def test_replan_reuses_only_state_compatible_images(change):
    frame = {"index": 2, "role": "END", "time_seconds": 10, "description": "End"}
    legacy = {**frame, "plan_keyframe_index": 2, "image_url": "/existing.png", "image_task_id": "producer"}
    if change == "index":
        legacy["plan_keyframe_index"] = 5
    elif change == "missing_time":
        legacy.pop("time_seconds")
        frame.pop("time_seconds")
    elif change:
        legacy[change] = {"time_seconds": 5, "description": "Different state", "role": "INTERMEDIATE"}[change]
    shot = Shot(description="Start", keyframes=json.dumps([legacy]))
    hydrated = shots._hydrate_plan_keyframes_from_legacy(shot, [frame])[0]
    assert hydrated.get("image_url") == ("/existing.png" if change in (None, "index") else None)


def test_single_window_images_cannot_fake_a_two_window_reuse_plan():
    shot = Shot(description="Start", video_description="End", keyframes="[]")
    plan = {"keyframes": [{"time_seconds": time, "description": str(time), "image_url": f"/{time}.png"} for time in (5, 10)]}
    windows = [{"window_index": 1, "start_time": 0, "end_time": 4.137}, {"window_index": 2, "start_time": 4.137, "end_time": 10}]
    assert shots._build_reused_three_frame_keyframe_plan(shot, plan, windows, 10) is None
