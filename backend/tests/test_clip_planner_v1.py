import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.clip_validator import validate_clip_plan
from app.services.clip_planner import build_clip_planner_input


@pytest.mark.skip(reason="OBSOLETE: legacy mode execution contract removed in G-2B")
def test_clip_execution_planner_prompt_freezes_first_and_cut_temporal_contract():
    prompt = (Path(__file__).parents[1] / "prompt_templates" / "10A_NovelFlow_ClipExecutionPlanner_V1.txt").read_text()
    assert "The first Clip must always use" in prompt
    assert "Any Clip with CUT continuity must likewise use false" in prompt
    assert "GENERATE Clips may use SINGLE_FRAME, FIRST_LAST_FRAME, or MULTI_KEYFRAME" in prompt
    assert "Do not semantically author `requires_temporal_control`" in prompt
    assert "upstream #08 timed targets" in prompt


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


@pytest.mark.skip(reason="OBSOLETE: legacy 3/4-frame validator contract removed in G-2B")
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


@pytest.mark.skip(reason="OBSOLETE: director_mode is not canonical planner input")
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


def test_clip_planner_input_projects_shot_start_and_deduplicates_compatibility_fallback(tmp_path):
    shot_image = tmp_path / "shot.png"
    kf2 = tmp_path / "kf2.png"
    kf3 = tmp_path / "kf3.png"
    for image in (shot_image, kf2, kf3):
        image.write_bytes(image.name.encode())
    shot = SimpleNamespace(
        id="shot-multi",
        chapter_id="chapter-multi",
        duration=8,
        continuity_mode="NORMAL",
        description="",
        video_description="",
        dialogues="[]",
        image_url=str(shot_image),
        image_path=str(shot_image),
        keyframes=json.dumps([
            {"plan_keyframe_index": 2, "image_url": str(kf2)},
            {"plan_keyframe_index": 3, "image_url": str(kf3)},
        ]),
        video_director_plan=json.dumps({
            "selected_mode": "MULTI_KEYFRAME",
            "keyframes": [
                {"index": 1, "role": "START", "time_seconds": 0, "image_url": None},
                {"index": 2, "role": "INTERMEDIATE", "time_seconds": 4, "image_url": str(kf2)},
                {"index": 3, "role": "END", "time_seconds": 8, "image_url": str(kf3)},
            ],
        }),
    )

    payload = build_clip_planner_input(shot, [])

    assert payload["available_generation_inputs"]["keyframe_images"] == [
        {"index": 1, "url": str(shot_image)},
        {"index": 2, "url": str(kf2)},
        {"index": 3, "url": str(kf3)},
    ]


def test_clip_planner_input_keeps_missing_image_target_and_historical_missing_flag_false():
    shot = SimpleNamespace(
        id="shot-target-no-image", chapter_id="chapter", duration=10, continuity_mode="NORMAL",
        description="", video_description="", dialogues="[]", image_url=None, image_path=None,
        keyframes="[]", video_director_plan=json.dumps({"selected_mode": "SINGLE_FRAME", "keyframes": [
            {"index": 2, "role": "INTERMEDIATE", "time_seconds": 6, "timed_visual_target": True},
            {"index": 3, "role": "END", "time_seconds": 10},
        ]}),
    )

    candidates = build_clip_planner_input(shot, [])["visual_state_candidates"]

    assert [(item["visual_state_id"], item["timed_visual_target"], item["image_available"]) for item in candidates] == [
        ("KF2", True, False), ("KF3", False, False),
    ]


def test_clip_planner_input_rejects_duplicate_canonical_visual_state_identity(tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(b"shot")
    shot = SimpleNamespace(
        id="shot-duplicate-state", chapter_id="chapter", duration=10, continuity_mode="NORMAL",
        description="", video_description="", dialogues="[]", image_url=str(image), image_path=str(image),
        keyframes="[]", video_director_plan=json.dumps({"keyframes": [
            {"index": 2, "role": "INTERMEDIATE", "time_seconds": 4, "timed_visual_target": False},
            {"index": 2, "role": "END", "time_seconds": 10, "timed_visual_target": False},
        ]}),
    )
    with pytest.raises(ValueError, match="Duplicate canonical visual-state identity"):
        build_clip_planner_input(shot, [])


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
                {"clip_index": 1, "start_time": 0, "end_time": 10, "capability": "MULTI_KEYFRAME", "continuity_to_previous": "NONE", "temporal_anchor_ids": []},
                {"clip_index": 2, "start_time": 10, "end_time": 20, "capability": "VIDEO_CONTINUATION", "continuity_to_previous": "CONTINUOUS", "previous_clip_index": 1},
                {"clip_index": 3, "start_time": 20, "end_time": 28, "capability": "VIDEO_CONTINUATION", "continuity_to_previous": "CONTINUOUS", "previous_clip_index": 2},
            ]})}

    monkeypatch.setattr(clip_planner, "PromptTemplateService", FakePromptTemplateService)
    monkeypatch.setattr(clip_planner, "LLMService", FakeLLMService)
    clips, validation = asyncio.run(clip_planner.plan_clips(None, SimpleNamespace(id="novel"), shot, []))

    assert [clip["capability"] for clip in clips] == ["GENERATE", "EXTEND", "EXTEND"]
    assert [clip["continuity_to_previous"] for clip in clips] == ["NONE", "CONTINUOUS", "CONTINUOUS"]
    assert [clip["requires_temporal_control"] for clip in clips] == [False, False, False]
    assert [clip["previous_clip_index"] for clip in clips] == [None, 1, 2]
    assert validation["passed"] is True


@pytest.mark.skip(reason="OBSOLETE: _align_multi_keyframe_references removed in G-2B")
def test_multi_keyframe_director_mode_aligns_clip_local_indexes(tmp_path, monkeypatch):
    import asyncio
    from app.services import clip_planner

    images = [tmp_path / name for name in ("shot.png", "kf2.png", "kf3.png")]
    for image in images:
        image.write_bytes(image.name.encode())
    shot = SimpleNamespace(
        id="shot-multi-align",
        chapter_id="chapter-multi-align",
        duration=8,
        continuity_mode="NORMAL",
        description="",
        video_description="",
        dialogues="[]",
        image_url=str(images[0]),
        image_path=str(images[0]),
        keyframes="[]",
        video_director_plan=json.dumps({
            "selected_mode": "MULTI_KEYFRAME",
            "keyframes": [
                {"index": 1, "role": "START", "time_seconds": 0, "image_url": None},
                {"index": 2, "role": "INTERMEDIATE", "time_seconds": 4, "image_url": str(images[1])},
                {"index": 3, "role": "END", "time_seconds": 8, "image_url": str(images[2])},
            ],
        }),
    )

    class FakePromptTemplateService:
        def __init__(self, db):
            pass

        def get_default_system_template(self, name):
            return SimpleNamespace(template="planner", name="planner")

    class FakeLLMService:
        async def chat_completion(self, **kwargs):
            return {"success": True, "content": json.dumps({"clips": [
                    {"clip_index": 1, "start_time": 0, "end_time": 8, "capability": "SINGLE_FRAME", "continuity_to_previous": "NONE"},
            ]})}

    monkeypatch.setattr(clip_planner, "PromptTemplateService", FakePromptTemplateService)
    monkeypatch.setattr(clip_planner, "LLMService", FakeLLMService)
    clips, validation = asyncio.run(clip_planner.plan_clips(None, SimpleNamespace(id="novel"), shot, []))

    assert validation["passed"] is True
    assert clips[0]["capability"] == "GENERATE"
    assert clips[0]["planning_mode"] == "MULTI_KEYFRAME"
    assert clips[0]["keyframe_indexes"] == [1, 2, 3]


def test_multi_keyframe_alignment_keeps_fallback_when_required_image_missing(tmp_path, monkeypatch):
    import asyncio
    from app.services import clip_planner

    shot_image = tmp_path / "shot.png"
    kf2 = tmp_path / "kf2.png"
    shot_image.write_bytes(b"shot")
    kf2.write_bytes(b"kf2")
    shot = SimpleNamespace(
        id="shot-multi-missing",
        chapter_id="chapter-multi-missing",
        duration=8,
        continuity_mode="NORMAL",
        description="",
        video_description="",
        dialogues="[]",
        image_url=str(shot_image),
        image_path=str(shot_image),
        keyframes="[]",
        video_director_plan=json.dumps({
            "selected_mode": "MULTI_KEYFRAME",
            "keyframes": [
                {"index": 1, "role": "START", "time_seconds": 0, "image_url": None},
                {"index": 2, "role": "INTERMEDIATE", "time_seconds": 4, "image_url": str(kf2)},
                {"index": 3, "role": "END", "time_seconds": 8, "image_url": str(tmp_path / "missing.png")},
            ],
        }),
    )

    class FakePromptTemplateService:
        def __init__(self, db):
            pass

        def get_default_system_template(self, name):
            return SimpleNamespace(template="planner", name="planner")

    class FakeLLMService:
        async def chat_completion(self, **kwargs):
            return {"success": True, "content": json.dumps({"clips": [
                {"clip_index": 1, "start_time": 0, "end_time": 8, "capability": "SINGLE_FRAME", "continuity_to_previous": "NONE"},
            ]})}

    monkeypatch.setattr(clip_planner, "PromptTemplateService", FakePromptTemplateService)
    monkeypatch.setattr(clip_planner, "LLMService", FakeLLMService)
    clips, validation = asyncio.run(clip_planner.plan_clips(None, SimpleNamespace(id="novel"), shot, []))

    assert validation["passed"] is True
    assert clips[0]["capability"] == "GENERATE"
    assert "keyframe_indexes" not in clips[0]


def test_multi_keyframe_alignment_does_not_change_first_last_or_single(tmp_path, monkeypatch):
    import asyncio
    from app.services import clip_planner

    shot_image = tmp_path / "shot.png"
    end_image = tmp_path / "end.png"
    shot_image.write_bytes(b"shot")
    end_image.write_bytes(b"end")

    class FakePromptTemplateService:
        def __init__(self, db):
            pass

        def get_default_system_template(self, name):
            return SimpleNamespace(template="planner", name="planner")

    monkeypatch.setattr(clip_planner, "PromptTemplateService", FakePromptTemplateService)
    for mode in ("FIRST_LAST_FRAME", "SINGLE_FRAME"):
        class FakeLLMService:
            async def chat_completion(self, **kwargs):
                return {"success": True, "content": json.dumps({"clips": [
                    {"clip_index": 1, "start_time": 0, "end_time": 8, "capability": mode, "continuity_to_previous": "NONE"},
                ]})}

        monkeypatch.setattr(clip_planner, "LLMService", FakeLLMService)
        shot = SimpleNamespace(
            id=f"shot-{mode}", chapter_id="chapter", duration=8,
            continuity_mode="NORMAL", description="", video_description="", dialogues="[]",
            image_url=str(shot_image), image_path=str(shot_image), keyframes="[]",
            video_director_plan=json.dumps({
                "selected_mode": mode,
                "keyframes": [{"index": 1, "role": "START", "time_seconds": 0, "image_url": None},
                              {"index": 2, "role": "END", "time_seconds": 8, "image_url": str(end_image)}],
            }),
        )
        clips, validation = asyncio.run(clip_planner.plan_clips(None, SimpleNamespace(id="novel"), shot, []))
        assert validation["passed"] is True
        assert clips[0]["capability"] == "GENERATE"
        assert clips[0]["continuity_to_previous"] == "NONE"


@pytest.mark.skip(reason="OBSOLETE: historical mode/window plans are not canonical execution input")
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


def test_clip_planner_input_projects_visual_state_candidates_without_reference_manifest(tmp_path):
    shot_image = tmp_path / "shot.png"
    kf4 = tmp_path / "kf4.png"
    shot_image.write_bytes(b"shot")
    kf4.write_bytes(b"kf4")
    shot = SimpleNamespace(
        id="shot-candidates", chapter_id="chapter", duration=20,
        continuity_mode="CONTINUOUS_TAKE", description="", video_description="",
        dialogues="[]", image_url=str(shot_image), image_path=str(shot_image), keyframes="[]",
        video_director_plan=json.dumps({
            "selected_mode": "MULTI_KEYFRAME",
            "keyframes": [
                {"index": 1, "role": "START", "time_seconds": 0, "image_url": None},
                {"index": 4, "role": "INTERMEDIATE", "time_seconds": 16.5, "description": "arrival", "image_url": str(kf4), "image_task_id": "task-kf4"},
            ],
            "transitions": [{"from_keyframe_index": 1, "to_keyframe_index": 4, "start_time": 0, "end_time": 16.5, "transition_description": "move"}],
        }),
    )
    payload = build_clip_planner_input(shot, [])
    candidates = payload["visual_state_candidates"]
    assert [item["visual_state_id"] for item in candidates] == ["KF1", "KF4"]
    assert candidates[1]["time_seconds"] == 16.5
    assert candidates[1]["image_available"] is True
    assert candidates[1]["source"]["image_task_id"] == "task-kf4"
    assert payload["transition_context"] == [{
        "from_keyframe_index": 1, "to_keyframe_index": 4,
        "start_time": 0, "end_time": 16.5, "transition_description": "move",
    }]
    assert "reference_manifest" not in json.dumps(payload)


def test_clip_planner_projects_upstream_target_despite_contradictory_raw_fields(tmp_path, monkeypatch):
    import asyncio
    from app.services import clip_planner

    images = [tmp_path / name for name in ("shot.png", "kf4.png")]
    for image in images:
        image.write_bytes(image.name.encode())
    shot = SimpleNamespace(
        id="shot-temporal-bridge", chapter_id="chapter", duration=20,
        continuity_mode="CONTINUOUS_TAKE", description="", video_description="", dialogues="[]",
        image_url=str(images[0]), image_path=str(images[0]), keyframes="[]",
        video_director_plan=json.dumps({"selected_mode": "MULTI_KEYFRAME", "keyframes": [
            {"index": 1, "role": "START", "time_seconds": 0, "image_url": None},
            {"index": 4, "role": "INTERMEDIATE", "time_seconds": 16.5, "timed_visual_target": True, "image_url": str(images[1]), "image_task_id": "task-kf4"},
        ]}),
    )

    class FakePromptTemplateService:
        def __init__(self, db): pass
        def get_default_system_template(self, name): return SimpleNamespace(template="planner", name="planner")

    class FakeLLMService:
        async def chat_completion(self, **kwargs):
            assert kwargs["user_content"]
            return {"success": True, "content": json.dumps({"clips": [
                {"clip_index": 1, "start_time": 0, "end_time": 15, "capability": "GENERATE", "continuity_to_previous": "NONE"},
                {"clip_index": 2, "start_time": 15, "end_time": 20, "capability": "EXTEND",
                 "continuity_to_previous": "CONTINUOUS", "requires_temporal_control": False,
                 "selected_temporal_target_ids": []},
            ]})}

    monkeypatch.setattr(clip_planner, "PromptTemplateService", FakePromptTemplateService)
    monkeypatch.setattr(clip_planner, "LLMService", FakeLLMService)
    anchors = []
    clips, validation = asyncio.run(clip_planner.plan_clips(None, SimpleNamespace(id="novel"), shot, anchors))

    assert validation["passed"] is True, validation
    assert clips[1]["capability"] == "TEMPORAL_EXTEND"
    assert clips[1]["requires_temporal_control"] is True
    assert clips[1]["temporal_anchor_ids"] == ["clip-2-KF4"]
    assert anchors == [{
        "anchor_id": "clip-2-KF4", "time_seconds": 1.5, "image_url": str(images[1]),
        "source": {"type": "KEYFRAME", "id": "KF4", "keyframe_index": 4, "image_task_id": "task-kf4"},
        "description": "",
    }]


def test_clip_planner_does_not_infer_temporal_intent_from_visual_states(tmp_path, monkeypatch):
    import asyncio
    from app.services import clip_planner
    image = tmp_path / "shot.png"
    image.write_bytes(b"shot")
    shot = SimpleNamespace(
        id="shot-no-temporal-inference", chapter_id="chapter", duration=12,
        continuity_mode="CONTINUOUS_TAKE", description="", video_description="", dialogues="[]",
        image_url=str(image), image_path=str(image), keyframes="[]",
        video_director_plan=json.dumps({"selected_mode": "MULTI_KEYFRAME", "keyframes": [
            {"index": 1, "role": "START", "time_seconds": 0, "image_url": None},
            {"index": 2, "role": "INTERMEDIATE", "time_seconds": 6, "image_url": str(image)},
            {"index": 3, "role": "END", "time_seconds": 12, "image_url": str(image)},
        ]}),
    )
    class FakePromptTemplateService:
        def __init__(self, db): pass
        def get_default_system_template(self, name): return SimpleNamespace(template="planner", name="planner")
    class FakeLLMService:
        async def chat_completion(self, **kwargs):
            return {"success": True, "content": json.dumps({"clips": [
                {"clip_index": 1, "start_time": 0, "end_time": 6, "capability": "GENERATE", "continuity_to_previous": "NONE"},
                {"clip_index": 2, "start_time": 6, "end_time": 12, "capability": "EXTEND",
                 "continuity_to_previous": "CONTINUOUS", "requires_temporal_control": False,
                 "selected_temporal_target_ids": []},
            ]})}
    monkeypatch.setattr(clip_planner, "PromptTemplateService", FakePromptTemplateService)
    monkeypatch.setattr(clip_planner, "LLMService", FakeLLMService)
    anchors = []
    clips, validation = asyncio.run(clip_planner.plan_clips(None, SimpleNamespace(id="novel"), shot, anchors))
    assert validation["passed"] is True
    assert clips[1]["capability"] == "EXTEND"
    assert clips[1]["requires_temporal_control"] is False
    assert clips[1]["temporal_anchor_ids"] == []
    assert anchors == []


def test_clip_planner_blocks_required_upstream_target_without_image(tmp_path, monkeypatch):
    import asyncio
    from app.services import clip_planner
    image = tmp_path / "shot.png"
    image.write_bytes(b"shot")
    shot = SimpleNamespace(
        id="shot-invalid-temporal", chapter_id="chapter", duration=10,
        continuity_mode="CONTINUOUS_TAKE", description="", video_description="", dialogues="[]",
        image_url=str(image), image_path=str(image), keyframes="[]",
        video_director_plan=json.dumps({"selected_mode": "SINGLE_FRAME", "keyframes": [
            {"index": 2, "role": "INTERMEDIATE", "time_seconds": 7, "timed_visual_target": True},
        ]}),
    )
    class FakePromptTemplateService:
        def __init__(self, db): pass
        def get_default_system_template(self, name): return SimpleNamespace(template="planner", name="planner")
    class FakeLLMService:
        async def chat_completion(self, **kwargs):
            return {"success": True, "content": json.dumps({"clips": [
                {"clip_index": 1, "start_time": 0, "end_time": 5, "capability": "GENERATE", "continuity_to_previous": "NONE"},
            {"clip_index": 2, "start_time": 5, "end_time": 10, "capability": "EXTEND",
                 "continuity_to_previous": "CONTINUOUS", "requires_temporal_control": False,
                 "selected_temporal_target_ids": []},
        ]})}
    shot.video_director_plan = json.dumps({"selected_mode": "SINGLE_FRAME", "keyframes": [
        {"index": 2, "role": "INTERMEDIATE", "time_seconds": 7, "timed_visual_target": True, "image_url": None},
    ]})
    monkeypatch.setattr(clip_planner, "PromptTemplateService", FakePromptTemplateService)
    monkeypatch.setattr(clip_planner, "LLMService", FakeLLMService)
    with pytest.raises(ValueError, match="TEMPORAL_ANCHOR_UNAVAILABLE"):
        asyncio.run(clip_planner.plan_clips(None, SimpleNamespace(id="novel"), shot, []))


def test_clip_planner_ignores_raw_temporal_capability_without_upstream_intent(tmp_path, monkeypatch):
    import asyncio
    from app.services import clip_planner
    image = tmp_path / "shot.png"
    image.write_bytes(b"shot")
    shot = SimpleNamespace(
        id="shot-missing-intent", chapter_id="chapter", duration=10,
        continuity_mode="CONTINUOUS_TAKE", description="", video_description="", dialogues="[]",
        image_url=str(image), image_path=str(image), keyframes="[]",
        video_director_plan=json.dumps({"selected_mode": "SINGLE_FRAME", "keyframes": []}),
    )
    class FakePromptTemplateService:
        def __init__(self, db): pass
        def get_default_system_template(self, name): return SimpleNamespace(template="planner", name="planner")
    class FakeLLMService:
        async def chat_completion(self, **kwargs):
            return {"success": True, "content": json.dumps({"clips": [
                {"clip_index": 1, "start_time": 0, "end_time": 5, "capability": "GENERATE", "continuity_to_previous": "NONE"},
                {"clip_index": 2, "start_time": 5, "end_time": 10, "capability": "TEMPORAL_EXTEND", "continuity_to_previous": "CONTINUOUS", "requires_temporal_control": True, "selected_temporal_target_ids": ["KF2"]},
            ]})}
    monkeypatch.setattr(clip_planner, "PromptTemplateService", FakePromptTemplateService)
    monkeypatch.setattr(clip_planner, "LLMService", FakeLLMService)
    clips, validation = asyncio.run(clip_planner.plan_clips(None, SimpleNamespace(id="novel"), shot, []))
    assert validation["passed"] is True
    assert clips[1]["capability"] == "EXTEND"
    assert clips[1]["requires_temporal_control"] is False


def test_clip_planner_first_generate_ignores_raw_temporal_intent(tmp_path, monkeypatch):
    import asyncio
    from app.services import clip_planner
    image = tmp_path / "shot.png"
    image.write_bytes(b"shot")
    shot = SimpleNamespace(
        id="shot-first-temporal", chapter_id="chapter", duration=10,
        continuity_mode="CONTINUOUS_TAKE", description="", video_description="", dialogues="[]",
        image_url=str(image), image_path=str(image), keyframes="[]",
        video_director_plan=json.dumps({"selected_mode": "MULTI_KEYFRAME", "keyframes": [
            {"index": 2, "role": "INTERMEDIATE", "time_seconds": 5, "timed_visual_target": True},
        ]}),
    )
    class FakePromptTemplateService:
        def __init__(self, db): pass
        def get_default_system_template(self, name): return SimpleNamespace(template="planner", name="planner")
    class FakeLLMService:
        async def chat_completion(self, **kwargs):
            return {"success": True, "content": json.dumps({"clips": [
                {"clip_index": 1, "start_time": 0, "end_time": 10, "capability": "MULTI_KEYFRAME",
                 "continuity_to_previous": "NONE", "requires_temporal_control": True,
                 "selected_temporal_target_ids": ["KF2"]},
            ]})}
    monkeypatch.setattr(clip_planner, "PromptTemplateService", FakePromptTemplateService)
    monkeypatch.setattr(clip_planner, "LLMService", FakeLLMService)
    clips, validation = asyncio.run(clip_planner.plan_clips(None, SimpleNamespace(id="novel"), shot, []))
    assert validation["passed"] is True
    assert clips[0]["capability"] == "GENERATE"
    assert clips[0]["requires_temporal_control"] is False
    assert clips[0]["temporal_anchor_ids"] == []


def test_clip_planner_cut_generate_ignores_raw_temporal_intent(tmp_path, monkeypatch):
    import asyncio
    from app.services import clip_planner
    image = tmp_path / "shot.png"
    image.write_bytes(b"shot")
    shot = SimpleNamespace(
        id="shot-cut-temporal", chapter_id="chapter", duration=10,
        continuity_mode="NORMAL", description="", video_description="", dialogues="[]",
        image_url=str(image), image_path=str(image), keyframes="[]",
        video_director_plan=json.dumps({"selected_mode": "SINGLE_FRAME", "keyframes": [
            {"index": 2, "role": "INTERMEDIATE", "time_seconds": 7, "timed_visual_target": True},
        ]}),
    )
    class FakePromptTemplateService:
        def __init__(self, db): pass
        def get_default_system_template(self, name): return SimpleNamespace(template="planner", name="planner")
    class FakeLLMService:
        async def chat_completion(self, **kwargs):
            return {"success": True, "content": json.dumps({"clips": [
                {"clip_index": 1, "start_time": 0, "end_time": 5, "capability": "GENERATE", "continuity_to_previous": "NONE"},
                {"clip_index": 2, "start_time": 5, "end_time": 10, "capability": "GENERATE",
                 "continuity_to_previous": "CUT", "requires_temporal_control": True,
                 "selected_temporal_target_ids": ["KF2"]},
            ]})}
    monkeypatch.setattr(clip_planner, "PromptTemplateService", FakePromptTemplateService)
    monkeypatch.setattr(clip_planner, "LLMService", FakeLLMService)
    clips, validation = asyncio.run(clip_planner.plan_clips(None, SimpleNamespace(id="novel"), shot, []))
    assert validation["passed"] is True
    assert clips[1]["capability"] == "GENERATE"
    assert clips[1]["requires_temporal_control"] is False
    assert clips[1]["temporal_anchor_ids"] == []


def test_clip_planner_repairs_subminimum_tail_before_validation(tmp_path, monkeypatch):
    import asyncio
    from app.services import clip_planner
    image = tmp_path / "shot.png"
    image.write_bytes(b"shot")
    shot = SimpleNamespace(
        id="shot-short-tail", chapter_id="chapter", duration=18,
        continuity_mode="CONTINUOUS_TAKE", description="", video_description="", dialogues="[]",
        image_url=str(image), image_path=str(image), keyframes="[]",
        video_director_plan=json.dumps({"selected_mode": "SINGLE_FRAME", "keyframes": []}),
    )
    class FakePromptTemplateService:
        def __init__(self, db): pass
        def get_default_system_template(self, name): return SimpleNamespace(template="planner", name="planner")
    class FakeLLMService:
        async def chat_completion(self, **kwargs):
            return {"success": True, "content": json.dumps({"clips": [
                {"clip_index": 1, "start_time": 0, "end_time": 15, "capability": "GENERATE", "continuity_to_previous": "NONE"},
                {"clip_index": 2, "start_time": 15, "end_time": 18, "capability": "EXTEND",
                 "continuity_to_previous": "CONTINUOUS", "requires_temporal_control": False},
            ]})}
    monkeypatch.setattr(clip_planner, "PromptTemplateService", FakePromptTemplateService)
    monkeypatch.setattr(clip_planner, "LLMService", FakeLLMService)
    clips, validation = asyncio.run(clip_planner.plan_clips(None, SimpleNamespace(id="novel"), shot, []))
    assert validation["passed"] is True
    assert [(item["start_time"], item["end_time"], item["planned_duration"]) for item in clips] == [(0, 14.0, 14.0), (14.0, 18, 4.0)]


@pytest.mark.skip(reason="OBSOLETE: legacy keyframe_indexes projection replaced by visual_state_indexes")
def test_final_boundary_reprojects_keyframes_scope_and_temporal_time(tmp_path, monkeypatch):
    import asyncio
    from app.services import clip_planner

    images = [tmp_path / f"kf{index}.png" for index in range(1, 6)]
    for image in images:
        image.write_bytes(image.name.encode())
    shot = SimpleNamespace(
        id="shot-final-boundary-derived", chapter_id="chapter", duration=18,
        continuity_mode="CONTINUOUS_TAKE", description="", video_description="", dialogues="[]",
        image_url=str(images[0]), image_path=str(images[0]), keyframes="[]",
        video_director_plan=json.dumps({
            "selected_mode": "MULTI_KEYFRAME",
            "keyframes": [
                {"index": 1, "role": "START", "time_seconds": 0, "image_url": str(images[0])},
                {"index": 2, "role": "INTERMEDIATE", "time_seconds": 7, "image_url": str(images[1])},
                {"index": 3, "role": "INTERMEDIATE", "time_seconds": 15, "image_url": str(images[2])},
                {"index": 4, "role": "INTERMEDIATE", "time_seconds": 16.5, "timed_visual_target": True, "image_url": str(images[3])},
                {"index": 5, "role": "END", "time_seconds": 18, "image_url": str(images[4])},
            ],
        }),
    )

    class FakePromptTemplateService:
        def __init__(self, db): pass
        def get_default_system_template(self, name): return SimpleNamespace(template="planner", name="planner")

    class FakeLLMService:
        async def chat_completion(self, **kwargs):
            return {"success": True, "content": json.dumps({"clips": [
                {"clip_index": 1, "start_time": 0, "end_time": 15, "capability": "MULTI_KEYFRAME",
                 "continuity_to_previous": "NONE", "requires_temporal_control": False,
                 "selected_temporal_target_ids": [], "dialogue_scope": {"start_time": 0, "end_time": 15}},
                {"clip_index": 2, "start_time": 15, "end_time": 18, "capability": "VIDEO_CONTINUATION",
                 "continuity_to_previous": "CONTINUOUS", "requires_temporal_control": True,
                 "selected_temporal_target_ids": ["KF4"], "dialogue_scope": {"start_time": 15, "end_time": 18}},
            ]})}

    monkeypatch.setattr(clip_planner, "PromptTemplateService", FakePromptTemplateService)
    monkeypatch.setattr(clip_planner, "LLMService", FakeLLMService)
    anchors = []
    clips, validation = asyncio.run(clip_planner.plan_clips(None, SimpleNamespace(id="novel"), shot, anchors))

    assert validation["passed"] is True, validation
    assert (clips[0]["start_time"], clips[0]["end_time"]) == (0.0, 14.0)
    assert clips[0]["planning_mode"] == "SINGLE_FRAME"
    assert "keyframe_indexes" not in clips[0]
    assert clips[0]["dialogue_scope"] == {"start_time": 0.0, "end_time": 14.0}
    assert (clips[1]["start_time"], clips[1]["end_time"]) == (14.0, 18.0)
    assert clips[1]["keyframe_indexes"] == [3, 4, 5]
    assert clips[1]["dialogue_scope"] == {"start_time": 14.0, "end_time": 18.0}
    assert clips[1]["capability"] == "TEMPORAL_EXTEND"
    assert clips[1]["selected_temporal_target_ids"] == ["KF4"]
    assert anchors[0]["anchor_id"] == "clip-2-KF4"
    assert anchors[0]["time_seconds"] == 2.5


def test_dialogue_gap_alignment_does_not_create_subminimum_tail():
    from app.services.video_director_ai import align_clip_boundaries_to_dialogue_gaps

    clips = [
        {"clip_index": 1, "start_time": 0, "end_time": 15},
        {"clip_index": 2, "start_time": 15, "end_time": 18},
    ]
    align_clip_boundaries_to_dialogue_gaps(
        clips,
        [{"start_time": 14, "end_time": 16}],
        max_clip_duration=15,
        min_clip_duration=4,
    )
    assert [(item["start_time"], item["end_time"]) for item in clips] == [(0, 14), (14, 18)]


def test_duration_repair_does_not_move_boundary_into_dialogue():
    from app.services.clip_planner import _normalize_provider_boundaries

    clips = [
        {"clip_index": 1, "start_time": 0, "end_time": 15},
        {"clip_index": 2, "start_time": 15, "end_time": 18},
    ]
    assert _normalize_provider_boundaries(
        clips, 18, 4, 15, [{"start_time": 13.5, "end_time": 16.5}]
    ) is False
    assert [(item["start_time"], item["end_time"]) for item in clips] == [(0, 15), (15, 18)]


def test_temporal_anchor_bridge_requires_future_state_but_allows_explicit_end():
    from app.services.clip_planner import _build_temporal_anchors

    candidates = [
        {"visual_state_id": "KF3", "time_seconds": 15, "image_available": True, "image_url": "/kf3.png", "source": {"type": "KEYFRAME", "id": "KF3"}},
        {"visual_state_id": "KF4", "time_seconds": 20, "image_available": True, "image_url": "/kf4.png", "source": {"type": "KEYFRAME", "id": "KF4"}},
    ]
    clips = [{"clip_index": 2, "start_time": 15, "end_time": 20, "continuity_to_previous": "CONTINUOUS", "requires_temporal_control": True, "selected_temporal_target_ids": ["KF4"]}]
    anchors = _build_temporal_anchors(clips, candidates)
    assert anchors[0]["time_seconds"] == 5
    assert clips[0]["temporal_anchor_ids"] == ["clip-2-KF4"]

    start_clip = [{"clip_index": 2, "start_time": 15, "end_time": 20, "continuity_to_previous": "CONTINUOUS", "requires_temporal_control": True, "selected_temporal_target_ids": ["KF3"]}]
    with pytest.raises(ValueError, match="outside Clip"):
        _build_temporal_anchors(start_clip, candidates)


def test_temporal_projection_assigns_shared_boundary_only_to_prior_clip():
    from app.services.clip_planner import _build_temporal_anchors, _project_temporal_targets

    candidates = [{"visual_state_id": "KF4", "time_seconds": 10, "timed_visual_target": True,
                   "image_available": True, "image_url": "/kf4.png", "source": {"type": "KEYFRAME", "id": "KF4"}}]
    clips = [
        {"clip_index": 1, "start_time": 0, "end_time": 5, "continuity_to_previous": "NONE"},
        {"clip_index": 2, "start_time": 5, "end_time": 10, "continuity_to_previous": "CONTINUOUS"},
        {"clip_index": 3, "start_time": 10, "end_time": 15, "continuity_to_previous": "CONTINUOUS"},
    ]

    _project_temporal_targets(clips, candidates, 15)
    anchors = _build_temporal_anchors(clips, candidates)

    assert clips[1]["selected_temporal_target_ids"] == ["KF4"]
    assert clips[2]["selected_temporal_target_ids"] == []
    assert clips[2]["capability"] == "EXTEND"
    assert anchors == [{"anchor_id": "clip-2-KF4", "time_seconds": 5, "image_url": "/kf4.png",
                        "source": {"type": "KEYFRAME", "id": "KF4"}, "description": ""}]


def test_temporal_projection_orders_all_targets_and_enforces_eight_limit():
    from app.services.clip_planner import _build_temporal_anchors, _project_temporal_targets

    candidates = [
        {"visual_state_id": f"KF{index}", "time_seconds": 5 + index, "timed_visual_target": True,
         "image_available": True, "image_url": f"/kf{index}.png"}
        for index in range(2, 5)
    ]
    clip = {"clip_index": 2, "start_time": 5, "end_time": 10, "continuity_to_previous": "CONTINUOUS"}
    _project_temporal_targets([clip], list(reversed(candidates)), 10)
    assert clip["selected_temporal_target_ids"] == ["KF2", "KF3", "KF4"]
    assert clip["capability"] == "TEMPORAL_EXTEND"
    anchors = _build_temporal_anchors([clip], candidates)
    assert [item["time_seconds"] for item in anchors] == [2, 3, 4]

    too_many = [
        {"visual_state_id": f"KF{index}", "time_seconds": 5 + index / 10, "timed_visual_target": True,
         "image_available": True, "image_url": f"/kf{index}.png"}
        for index in range(2, 11)
    ]
    with pytest.raises(ValueError, match="TEMPORAL_ANCHOR_LIMIT"):
        _project_temporal_targets([{"clip_index": 2, "start_time": 5, "end_time": 10,
                                   "continuity_to_previous": "CONTINUOUS"}], too_many, 10)


@pytest.mark.parametrize("candidates, message", [
    ([{"visual_state_id": "KF2", "time_seconds": 5, "timed_visual_target": True},
      {"visual_state_id": "KF2", "time_seconds": 6, "timed_visual_target": True}], "Duplicate"),
    ([{"visual_state_id": "KF2", "time_seconds": float("nan"), "timed_visual_target": True}], "invalid time"),
    ([{"visual_state_id": "KF2", "time_seconds": 11, "timed_visual_target": True}], "outside Shot timeline"),
    ([{"visual_state_id": "KF2", "time_seconds": 6, "timed_visual_target": True, "image_available": True, "image_url": "/kf2.png"},
      {"visual_state_id": "KF3", "time_seconds": 6, "timed_visual_target": True, "image_available": True, "image_url": "/kf3.png"}], "duplicate temporal target time"),
])
def test_temporal_projection_rejects_invalid_target_identity_and_time(candidates, message):
    from app.services.clip_planner import _project_temporal_targets
    with pytest.raises(ValueError, match=message):
        _project_temporal_targets([{"clip_index": 2, "start_time": 0, "end_time": 10,
                                   "continuity_to_previous": "CONTINUOUS"}], candidates, 10)


def test_planner_rechecks_target_after_boundary_normalization(tmp_path, monkeypatch):
    import asyncio
    from app.services import clip_planner
    image = tmp_path / "shot.png"
    image.write_bytes(b"shot")
    shot = SimpleNamespace(
        id="shot-target-boundary", chapter_id="chapter", duration=18,
        continuity_mode="CONTINUOUS_TAKE", description="", video_description="", dialogues="[]",
        image_url=str(image), image_path=str(image), keyframes="[]",
        video_director_plan=json.dumps({"selected_mode": "SINGLE_FRAME", "keyframes": [
            {"index": 2, "role": "INTERMEDIATE", "time_seconds": 3.5, "timed_visual_target": True, "image_url": str(image)},
        ]}),
    )
    class FakePromptTemplateService:
        def __init__(self, db): pass
        def get_default_system_template(self, name): return SimpleNamespace(template="planner", name="planner")
    class FakeLLMService:
        async def chat_completion(self, **kwargs):
            return {"success": True, "content": json.dumps({"clips": [
                {"clip_index": 1, "start_time": 0, "end_time": 3, "capability": "GENERATE", "continuity_to_previous": "NONE"},
                {"clip_index": 2, "start_time": 3, "end_time": 18, "capability": "EXTEND",
                 "continuity_to_previous": "CONTINUOUS", "requires_temporal_control": True,
                 "selected_temporal_target_ids": ["KF2"]},
            ]})}
    monkeypatch.setattr(clip_planner, "PromptTemplateService", FakePromptTemplateService)
    monkeypatch.setattr(clip_planner, "LLMService", FakeLLMService)
    clips, validation = asyncio.run(clip_planner.plan_clips(None, SimpleNamespace(id="novel"), shot, []))
    assert validation["passed"] is True
    assert clips[1]["capability"] == "EXTEND"
    assert clips[1]["selected_temporal_target_ids"] == []


def test_clip_planner_normalizes_explicit_continuity_routing(tmp_path, monkeypatch):
    import asyncio
    from app.services import clip_planner

    image = tmp_path / "shot.png"
    image.write_bytes(b"shot")
    shot = SimpleNamespace(
        id="shot-routing", chapter_id="chapter", duration=12,
        continuity_mode="NORMAL", description="", video_description="", dialogues="[]",
        image_url=str(image), image_path=str(image), keyframes="[]",
        video_director_plan=json.dumps({"selected_mode": "SINGLE_FRAME", "keyframes": []}),
    )

    class FakePromptTemplateService:
        def __init__(self, db): pass
        def get_default_system_template(self, name): return SimpleNamespace(template="planner", name="planner")

    class FakeLLMService:
        async def chat_completion(self, **kwargs):
            return {"success": True, "content": json.dumps({"clips": [
                {"clip_index": 1, "start_time": 0, "end_time": 6, "capability": "GENERATE", "continuity_to_previous": "NONE", "requires_temporal_control": False},
                {"clip_index": 2, "start_time": 6, "end_time": 12, "capability": "GENERATE", "continuity_to_previous": "CUT", "requires_temporal_control": False},
            ]})}

    monkeypatch.setattr(clip_planner, "PromptTemplateService", FakePromptTemplateService)
    monkeypatch.setattr(clip_planner, "LLMService", FakeLLMService)
    clips, validation = asyncio.run(clip_planner.plan_clips(None, SimpleNamespace(id="novel"), shot, []))
    assert validation["passed"] is True
    assert [clip["capability"] for clip in clips] == ["GENERATE", "GENERATE"]
    assert [clip["continuity_to_previous"] for clip in clips] == ["NONE", "CUT"]


def test_clip_planner_normalizes_continuous_to_extend_and_defers_temporal(tmp_path, monkeypatch):
    import asyncio
    from app.services import clip_planner

    image = tmp_path / "shot.png"
    image.write_bytes(b"shot")
    shot = SimpleNamespace(
        id="shot-routing-2", chapter_id="chapter", duration=12,
        continuity_mode="NORMAL", description="", video_description="", dialogues="[]",
        image_url=str(image), image_path=str(image), keyframes="[]",
        video_director_plan=json.dumps({"selected_mode": "SINGLE_FRAME", "keyframes": []}),
    )

    class FakePromptTemplateService:
        def __init__(self, db): pass
        def get_default_system_template(self, name): return SimpleNamespace(template="planner", name="planner")

    class FakeLLMService:
        async def chat_completion(self, **kwargs):
            return {"success": True, "content": json.dumps({"clips": [
                {"clip_index": 1, "start_time": 0, "end_time": 6, "capability": "GENERATE", "continuity_to_previous": "NONE"},
                {"clip_index": 2, "start_time": 6, "end_time": 12, "capability": "VIDEO_CONTINUATION", "continuity_to_previous": "CONTINUOUS", "previous_clip_index": 1},
            ]})}

    monkeypatch.setattr(clip_planner, "PromptTemplateService", FakePromptTemplateService)
    monkeypatch.setattr(clip_planner, "LLMService", FakeLLMService)
    clips, _ = asyncio.run(clip_planner.plan_clips(None, SimpleNamespace(id="novel"), shot, []))
    assert clips[1]["capability"] == "EXTEND"
    assert clips[1]["continuity_to_previous"] == "CONTINUOUS"
    assert clips[1]["requires_temporal_control"] is False


@pytest.mark.skip(reason="OBSOLETE: assertions depended on legacy planning_mode labels")
def test_clip_planner_recomputes_durations_after_dialogue_boundary_alignment(tmp_path, monkeypatch):
    import asyncio
    from app.services import clip_planner

    images = [tmp_path / name for name in ("shot.png", "kf2.png", "kf3.png", "kf4.png", "kf5.png")]
    for image in images:
        image.write_bytes(image.name.encode())
    dialogue_texts = ["甲乙", "甲乙丙丁", "甲乙丙丁戊己庚辛壬癸子丑", "甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未", "甲乙丙丁戊己庚辛", "甲乙丙丁戊己庚辛壬癸", "甲乙丙丁戊己庚辛壬癸子丑"]
    dialogues = [
        {"dialogue_id": f"D{index}", "character_name": "甲", "text": text}
        for index, text in enumerate(dialogue_texts, 1)
    ]
    shot = SimpleNamespace(
        id="shot-duration-alignment",
        chapter_id="chapter-duration-alignment",
        duration=24,
        continuity_mode="NORMAL",
        description="",
        video_description="",
        characters=json.dumps(["甲"]),
        dialogues=json.dumps(dialogues, ensure_ascii=False),
        image_url=str(images[0]),
        image_path=str(images[0]),
        keyframes="[]",
        video_director_plan=json.dumps({
            "selected_mode": "MULTI_KEYFRAME",
            "keyframes": [
                {"index": 1, "role": "START", "time_seconds": 0, "image_url": None},
                {"index": 2, "role": "INTERMEDIATE", "time_seconds": 7.5, "image_url": str(images[1])},
                {"index": 3, "role": "INTERMEDIATE", "time_seconds": 15, "image_url": str(images[2])},
                {"index": 4, "role": "INTERMEDIATE", "time_seconds": 19.5, "image_url": str(images[3])},
                {"index": 5, "role": "END", "time_seconds": 24, "image_url": str(images[4])},
            ],
        }),
    )

    class FakePromptTemplateService:
        def __init__(self, db):
            pass

        def get_default_system_template(self, name):
            return SimpleNamespace(template="planner", name="planner")

    class FakeLLMService:
        async def chat_completion(self, **kwargs):
            return {"success": True, "content": json.dumps({"clips": [
                {"clip_index": 1, "start_time": 0, "end_time": 10, "capability": "SINGLE_FRAME", "continuity_to_previous": "NONE"},
                {"clip_index": 2, "start_time": 10, "end_time": 24, "capability": "VIDEO_CONTINUATION", "continuity_to_previous": "CONTINUOUS", "previous_clip_index": 1},
            ]})}

    monkeypatch.setattr(clip_planner, "PromptTemplateService", FakePromptTemplateService)
    monkeypatch.setattr(clip_planner, "LLMService", FakeLLMService)
    clips, validation = asyncio.run(clip_planner.plan_clips(None, SimpleNamespace(id="novel"), shot, []))

    assert [(clip["start_time"], clip["end_time"], clip["planned_duration"]) for clip in clips] == [
        (0, 10.6, 10.6),
        (10.6, 24, 13.4),
    ]
    assert not any(item["code"] == "CLIP_DURATION_MISMATCH" for item in validation["blocking"])
    assert validation["passed"] is True
    assert [clip["planning_mode"] for clip in clips] == ["SINGLE_FRAME", "MULTI_KEYFRAME"]
    assert [clip["capability"] for clip in clips] == ["GENERATE", "EXTEND"]
    assert [clip["continuity_to_previous"] for clip in clips] == ["NONE", "CONTINUOUS"]
    assert clips[1]["requires_temporal_control"] is False
    assert clips[1]["previous_clip_index"] == 1
    assert clips[1]["keyframe_indexes"] == [3, 4, 5]
    assert [[item["dialogue_id"] for item in clip["dialogue_assignment"]] for clip in clips] == [
        ["D1", "D2", "D3", "D4"],
        ["D5", "D6", "D7"],
    ]
    assert [item["text"] for item in clips[0]["dialogue_assignment"] + clips[1]["dialogue_assignment"]] == dialogue_texts


@pytest.mark.skip(reason="OBSOLETE: legacy MULTI_KEYFRAME planning mode removed")
def test_explicit_multiframe_continuity_is_orthogonal_to_execution_routing():
    from app.services.clip_planner import _normalize_continuity_contract

    clips = [
        {"clip_index": 1, "capability": "MULTI_KEYFRAME", "continuity_to_previous": "NONE", "requires_temporal_control": False},
        {"clip_index": 2, "capability": "MULTI_KEYFRAME", "continuity_to_previous": "CONTINUOUS", "previous_clip_index": 1, "requires_temporal_control": False},
    ]
    _normalize_continuity_contract(clips, "CONTINUOUS_TAKE")
    assert clips[0]["planning_mode"] == "MULTI_KEYFRAME"
    assert clips[0]["capability"] == "GENERATE"
    assert clips[1]["planning_mode"] == "MULTI_KEYFRAME"
    assert clips[1]["continuity_to_previous"] == "CONTINUOUS"
    assert clips[1]["capability"] == "EXTEND"


@pytest.mark.parametrize("visual_mode", ["SINGLE_FRAME", "FIRST_LAST_FRAME"])
def test_continuous_visual_modes_remain_extend_when_temporal_intent_is_false(visual_mode):
    from app.services.clip_planner import _normalize_continuity_contract

    clips = [{
        "clip_index": 2,
        "capability": visual_mode,
        "planning_mode": visual_mode,
        "continuity_to_previous": "CONTINUOUS",
        "previous_clip_index": 1,
        "requires_temporal_control": False,
        "selected_temporal_target_ids": [],
    }]
    _normalize_continuity_contract(clips, "CONTINUOUS_TAKE")
    assert clips[0]["planning_mode"] == visual_mode
    assert clips[0]["continuity_to_previous"] == "CONTINUOUS"
    assert clips[0]["capability"] == "EXTEND"


def test_continuous_take_rejects_explicit_cut_and_invalid_first_continuity():
    from app.services.clip_planner import _normalize_continuity_contract

    with pytest.raises(ValueError, match="不能使用 CUT"):
        _normalize_continuity_contract([
            {"clip_index": 1, "capability": "MULTI_KEYFRAME", "continuity_to_previous": "NONE"},
            {"clip_index": 2, "capability": "MULTI_KEYFRAME", "continuity_to_previous": "CUT"},
        ], "CONTINUOUS_TAKE")
    with pytest.raises(ValueError, match="必须为 NONE"):
        _normalize_continuity_contract([
            {"clip_index": 1, "capability": "MULTI_KEYFRAME", "continuity_to_previous": "CONTINUOUS"},
        ], "CONTINUOUS_TAKE")


def test_current_planner_contract_rejects_missing_continuity():
    from app.services.clip_planner import _normalize_continuity_contract

    with pytest.raises(ValueError, match="缺少 continuity_to_previous"):
        _normalize_continuity_contract([
            {"clip_index": 1, "capability": "MULTI_KEYFRAME"},
        ], "NORMAL")


def test_later_none_continuity_is_rejected_instead_of_bypassing_routing():
    from app.services.clip_planner import _normalize_continuity_contract

    with pytest.raises(ValueError, match="Later Clip .* 不能为 NONE"):
        _normalize_continuity_contract([
            {"clip_index": 1, "capability": "MULTI_KEYFRAME", "continuity_to_previous": "NONE"},
            {"clip_index": 2, "capability": "VIDEO_CONTINUATION", "continuity_to_previous": "NONE", "previous_clip_index": 1},
        ], "NORMAL")


def test_video_continuation_without_explicit_continuity_is_rejected():
    from app.services.clip_planner import _normalize_continuity_contract

    with pytest.raises(ValueError, match="缺少 continuity_to_previous"):
        _normalize_continuity_contract([
            {"clip_index": 2, "capability": "VIDEO_CONTINUATION", "previous_clip_index": 1},
        ], "NORMAL")


def test_normal_shot_explicit_cut_still_routes_to_generate():
    from app.services.clip_planner import _normalize_continuity_contract

    clips = [
        {"clip_index": 1, "capability": "SINGLE_FRAME", "continuity_to_previous": "NONE"},
        {"clip_index": 2, "capability": "MULTI_KEYFRAME", "continuity_to_previous": "CUT"},
    ]
    _normalize_continuity_contract(clips, "NORMAL")
    assert clips[1]["continuity_to_previous"] == "CUT"
    assert clips[1]["capability"] == "GENERATE"
