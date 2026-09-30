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

    assert [clip["capability"] for clip in clips] == ["GENERATE", "EXTEND", "EXTEND"]
    assert [clip["continuity_to_previous"] for clip in clips] == ["NONE", "CONTINUOUS", "CONTINUOUS"]
    assert [clip["requires_temporal_control"] for clip in clips] == [False, False, False]
    assert [clip["previous_clip_index"] for clip in clips] == [None, 1, 2]
    assert validation["passed"] is True


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
                {"clip_index": 1, "start_time": 0, "end_time": 8, "capability": "SINGLE_FRAME"},
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
                {"clip_index": 1, "start_time": 0, "end_time": 8, "capability": "SINGLE_FRAME"},
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
                    {"clip_index": 1, "start_time": 0, "end_time": 8, "capability": mode},
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
                {"clip_index": 1, "start_time": 0, "end_time": 6, "capability": "GENERATE"},
                {"clip_index": 2, "start_time": 6, "end_time": 12, "capability": "VIDEO_CONTINUATION", "previous_clip_index": 1},
            ]})}

    monkeypatch.setattr(clip_planner, "PromptTemplateService", FakePromptTemplateService)
    monkeypatch.setattr(clip_planner, "LLMService", FakeLLMService)
    clips, _ = asyncio.run(clip_planner.plan_clips(None, SimpleNamespace(id="novel"), shot, []))
    assert clips[1]["capability"] == "EXTEND"
    assert clips[1]["continuity_to_previous"] == "CONTINUOUS"
    assert clips[1]["requires_temporal_control"] is False


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
                {"clip_index": 1, "start_time": 0, "end_time": 10, "capability": "SINGLE_FRAME"},
                {"clip_index": 2, "start_time": 10, "end_time": 24, "capability": "VIDEO_CONTINUATION", "previous_clip_index": 1},
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
