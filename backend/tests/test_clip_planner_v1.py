import json
from types import SimpleNamespace

from app.services.clip_validator import validate_clip_plan
from app.services.clip_planner import build_clip_planner_input


def test_clip_validator_accepts_contiguous_auto_approve_flow():
    clips = [
        {"clip_index": 1, "start_time": 0, "end_time": 10, "capability": "SINGLE_FRAME"},
        {"clip_index": 2, "start_time": 10, "end_time": 20, "capability": "VIDEO_CONTINUATION", "previous_clip_index": 1},
    ]

    result = validate_clip_plan(20, clips, [])

    assert result["passed"] is True
    assert result["blocking"] == []


def test_clip_validator_reports_hard_duration_and_soft_quality_findings():
    clips = [{"clip_index": 1, "start_time": 0, "end_time": 3, "capability": "SINGLE_FRAME"}]

    result = validate_clip_plan(3, clips, [])

    assert result["passed"] is False
    assert any(item["code"] == "PROVIDER_DURATION_LIMIT" for item in result["blocking"])


def test_clip_validator_rejects_multi_keyframe_without_keyframe_inputs():
    clips = [{
        "clip_index": 1,
        "start_time": 0,
        "end_time": 10,
        "capability": "MULTI_KEYFRAME",
        "temporal_anchor_ids": [],
    }]

    result = validate_clip_plan(
        10,
        clips,
        [],
        available_inputs={"shot_image": True, "keyframe_images": [], "temporal_anchor_images": []},
    )

    assert result["passed"] is False
    assert any(item["code"] == "KEYFRAME_INPUTS_REQUIRED" for item in result["blocking"])


def test_clip_planner_input_reports_actual_shot_and_keyframe_assets(tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(b"shot-image")
    shot = SimpleNamespace(
        id="shot-assets",
        chapter_id="chapter-assets",
        duration=10,
        continuity_mode="NORMAL",
        description="",
        video_description="",
        dialogues="[]",
        image_url=str(image),
        image_path=str(image),
        keyframes="[]",
        video_director_plan=json.dumps({"selected_mode": "MULTI_KEYFRAME", "keyframes": [{"index": 1, "image_url": str(image)}]}),
    )

    payload = build_clip_planner_input(shot, [])

    assert payload["director_mode"] == "MULTI_KEYFRAME"
    assert payload["available_generation_inputs"]["shot_image"] is True
    assert payload["available_generation_inputs"]["keyframe_images"] == [{"index": 1, "url": str(image)}]


def test_clip_planner_compiles_director_mode_into_available_foundation_capability(tmp_path, monkeypatch):
    import asyncio
    from app.services import clip_planner

    image = tmp_path / "shot.png"
    image.write_bytes(b"shot-image")
    shot = SimpleNamespace(
        id="shot-assets",
        chapter_id="chapter-assets",
        duration=28,
        continuity_mode="NORMAL",
        description="",
        video_description="",
        dialogues="[]",
        image_url=str(image),
        image_path=str(image),
        keyframes="[]",
        video_director_plan=json.dumps({"selected_mode": "MULTI_KEYFRAME", "keyframes": []}),
    )

    class FakePromptTemplateService:
        def __init__(self, db):
            pass

        def get_default_system_template(self, name):
            return SimpleNamespace(template="planner", name="planner")

    class FakeLLMService:
        async def chat_completion(self, **kwargs):
            return {"success": True, "content": json.dumps({"clips": [
                {"clip_index": 1, "start_time": 0, "end_time": 10, "capability": "MULTI_KEYFRAME", "temporal_anchor_ids": []},
                {"clip_index": 2, "start_time": 10, "end_time": 20, "capability": "VIDEO_CONTINUATION", "previous_clip_index": 1},
                {"clip_index": 3, "start_time": 20, "end_time": 28, "capability": "VIDEO_CONTINUATION", "previous_clip_index": 2},
            ]})}

    monkeypatch.setattr(clip_planner, "PromptTemplateService", FakePromptTemplateService)
    monkeypatch.setattr(clip_planner, "LLMService", FakeLLMService)
    clips, validation = asyncio.run(clip_planner.plan_clips(None, SimpleNamespace(id="novel"), shot, []))

    assert [clip["capability"] for clip in clips] == ["SINGLE_FRAME", "VIDEO_CONTINUATION", "VIDEO_CONTINUATION"]
    assert [clip["previous_clip_index"] for clip in clips] == [None, 1, 2]
    assert validation["passed"] is True


def test_clip_planner_input_preserves_old_shot_plan_without_window_rewrite():
    shot = SimpleNamespace(
        id="shot-1",
        chapter_id="chapter-1",
        duration=20,
        continuity_mode="CONTINUOUS_TAKE",
        description="A continuous action",
        video_description="Camera moves forward",
        dialogues="[]",
        video_director_plan=json.dumps({"selected_mode": "FIRST_LAST_FRAME", "window_plans": [{"window_index": 1}]}),
    )

    payload = build_clip_planner_input(shot, [{"anchor_id": "END", "role": "END", "time_seconds": 20}])

    assert payload["director_mode"] == "FIRST_LAST_FRAME"
    assert payload["temporal_anchors"][0]["anchor_id"] == "END"
    assert payload["planning_policy"]["approval_mode"] == "AUTO_APPROVE"
