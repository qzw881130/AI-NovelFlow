import asyncio
import json
from types import SimpleNamespace

import pytest

from app.services.clip_execution_compiler import compile_extend_clip
from app.services.shot_video_service import (
    _project_semantic_clip_transitions,
    _select_video_prompt_context,
    _semantic_clip_prompt_context,
)
from app.services import video_director_ai


def test_semantic_extend_dialogue_reaches_canonical_h3_prompt_path(monkeypatch):
    captured = {}

    class FakeLLMService:
        async def chat_completion(self, **kwargs):
            captured.update(kwargs)
            return {
                "success": True,
                "content": """subject_definitions:
<Subject 1> is 骗子1, the first visible speaker.
<Subject 2> is 骗子2, the second visible speaker.
summary:
The two subjects continue their visual action across the current Clip.
detailed_description:
The camera and scene continue from the current visual anchors.
overall_soundscape:
Room tone and action Foley accompany the scene.""",
            }

    monkeypatch.setattr(video_director_ai, "LLMService", FakeLLMService)
    monkeypatch.setattr(video_director_ai, "resolve_prompt_template", lambda *_args: SimpleNamespace(template="system", name="template-13"))

    dialogues = [
        {"dialogue_id": f"D{index}", "speaker": speaker, "text": text,
         "start_time": start, "end_time": end, "estimated_duration": end - start}
        for index, (speaker, text, start, end) in enumerate([
            ("骗子1", "旧对白一", 1.0, 1.5),
            ("骗子2", "旧对白二", 1.7, 2.7),
            ("骗子1", "旧对白三", 2.9, 5.9),
            ("骗子2", "旧对白四", 6.1, 10.6),
            ("骗子1", "可是谁把你带进王城的？", 10.8, 13.3),
            ("骗子2", "没有我的主意，你连宫门都进不来。", 13.5, 17.0),
            ("骗子1", "没有我，你现在还在城外睡马棚。", 17.2, 20.45),
        ], 1)
    ]
    keyframes = [
        {"index": index, "role": role, "time_seconds": time, "description": description,
         "image_url": f"/api/files/kf{index}.png" if index > 1 else None}
        for index, role, time, description in [
            (1, "START", 0.0, "Characters:\n- 骗子1: holds gold thread\n- 骗子2: reaches forward"),
            (2, "INTERMEDIATE", 7.5, "Characters:\n- 骗子1: speaks\n- 骗子2: listens"),
            (3, "INTERMEDIATE", 15.0, "Characters:\n- 骗子1: glares\n- 骗子2: speaks"),
            (4, "INTERMEDIATE", 19.5, "Characters:\n- 骗子1: speaks\n- 骗子2: speaks"),
            (5, "END", 24.0, "Characters:\n- 骗子1: glares\n- 骗子2: glares"),
        ]
    ]
    clip_plan = [
        {"clip_index": 1, "start_time": 0.0, "end_time": 10.6, "capability": "GENERATE", "visual_state_indexes": [1, 2]},
        {
            "clip_index": 2, "start_time": 10.6, "end_time": 24.0,
            "planned_duration": 13.4, "capability": "EXTEND",
            "continuity_to_previous": "CONTINUOUS", "requires_temporal_control": False,
            "previous_clip_index": 1, "visual_state_indexes": [3, 4, 5], "carry_in_state_index": 2,
            "dialogue_assignment": dialogues[4:],
        },
    ]
    plan = {
        "clip_plan_revision": 1,
        "clip_plan": clip_plan,
        "keyframes": keyframes,
        "transitions": [
            {
                "from_keyframe_index": index,
                "to_keyframe_index": index + 1,
                "transition_description": f"KF{index} to KF{index + 1}",
            }
            for index in range(1, 5)
        ],
        # The legacy visual window starts at 0 and must not replace semantic C2.
        "canonical_visual_plan": True,
    }
    clip_metadata = {
        "execution_scope": "CLIP",
        "clip_index": 2,
        "clip_plan_revision": 1,
        "dialogue_assignment": dialogues[4:],
        "execution_contract": {
            "version": 1,
            "capability": "EXTEND",
            "artifact_kind": "CLIP_ONLY",
            "clip": {"clip_index": 2, "clip_plan_revision": 1, "duration_seconds": 13.4},
            "previous_clip": {
                "clip_index": 1,
                "clip_plan_revision": 1,
                "generated_by_task_id": "task-a",
                "result_url": "/api/files/task-a.mp4",
            },
        },
    }
    context = _select_video_prompt_context(
        plan,
        clip_metadata,
        "GENERATE",
        duration=24.0,
        clip_only_execution=True,
    )
    shot = SimpleNamespace(
        id="shot-c4c", index=20, chapter_id="chapter-c4c", description="Visual description",
        video_description="", duration=24, continuity_mode="NORMAL",
        characters=json.dumps(["骗子1", "骗子2"], ensure_ascii=False), scene="weaving room",
        props="[]", dialogues="[]", video_director_plan=json.dumps(plan, ensure_ascii=False),
        image_url="/api/files/shot.png",
    )

    compiled = compile_extend_clip(
        shot, plan, context["clip"], 1,
        {"clip_index": 1, "clip_plan_revision": 1, "generated_by_task_id": "task-a", "result_url": "/api/files/task-a.mp4"},
    )
    prompt = asyncio.run(video_director_ai.build_h3_video_prompt(
        db=SimpleNamespace(commit=lambda: None),
        novel=SimpleNamespace(id="novel-c4c"),
        shot=shot,
        selected_mode="MULTI_KEYFRAME",
        clip=context["clip"],
        workflow_capability={},
        workflow_type="VIDEO_CONTINUATION",
        workflow_name="frozen continuation workflow",
        start_image_url=None,
        keyframes=context["keyframes"],
        transitions=context["transitions"],
        clip_dialogues=context["clip_dialogues"],
        reference_images=[{"label": "ref", "url": "/api/files/ref.png"}],
    ))

    payload = json.loads(captured["user_content"].split("\n\n", 1)[1])
    assert compiled["execution_contract"]["capability"] == "EXTEND"
    assert compiled["execution_contract"]["previous_clip"]["generated_by_task_id"] == "task-a"
    assert context["clip"]["capability"] == "EXTEND"
    assert context["clip"]["visual_state_indexes"] == [3, 4, 5]
    assert (context["clip"]["start_time"], context["clip"]["end_time"]) == (10.6, 24.0)
    assert [
        (item["from_keyframe_index"], item["to_keyframe_index"])
        for item in context["transitions"]
    ] == [(2, 3), (3, 4), (4, 5)]
    assert [item["source_keyframe_index"] for item in compiled["video_reference_manifest"]["references"]] == [3, 4, 5]

    assert [item["dialogue_id"] for item in context["clip_dialogues"]] == ["D5", "D6", "D7"]
    assert [(item["local_start_time"], item["local_end_time"]) for item in context["clip_dialogues"]] == [
        (0.2, 2.7), (2.9, 6.4), (6.6, 9.85),
    ]
    assert [item["id"] for item in payload["dialogue_timeline_source"]] == ["D5", "D6", "D7"]
    assert [(item["start_time"], item["end_time"]) for item in payload["dialogue_timeline_source"]] == [
        (0.2, 2.7), (2.9, 6.4), (6.6, 9.85),
    ]
    assert [
        (item["from_keyframe_index"], item["to_keyframe_index"])
        for item in payload["transitions"]
    ] == [(2, 3), (3, 4), (4, 5)]
    assert payload["silent_characters"] == []
    assert "No assigned dialogue" not in prompt
    assert "D5:" in prompt and "D6:" in prompt and "D7:" in prompt
    assert "可是谁把你带进王城的？" in prompt
    assert "没有我的主意，你连宫门都进不来。" in prompt
    assert "没有我，你现在还在城外睡马棚。" in prompt
    for stale_text in ("旧对白一", "旧对白二", "旧对白三", "旧对白四"):
        assert stale_text not in prompt


@pytest.mark.parametrize(
    "start,end",
    [(9.0, 10.0), (10.0, 11.0), (23.0, 25.0)],
    ids=["fully-before", "partial-before", "partial-after"],
)
def test_semantic_clip_dialogue_projection_rejects_out_of_clip_assignment(start, end):
    plan = {
        "clip_plan": [{
            "clip_index": 2,
            "start_time": 10.6,
            "end_time": 24.0,
            "dialogue_assignment": [{
                "dialogue_id": "D5",
                "speaker": "骗子1",
                "text": "current line",
                "start_time": start,
                "end_time": end,
            }],
        }],
        "keyframes": [],
        "transitions": [],
    }
    with pytest.raises(ValueError, match="outside clip interval"):
        _semantic_clip_prompt_context(plan, {"clip_index": 2})


def _canonical_transitions():
    return [
        {
            "segment_index": index,
            "from_keyframe_index": index,
            "to_keyframe_index": index + 1,
            "start_time": start,
            "end_time": end,
            "transition_description": f"KF{index} to KF{index + 1}",
        }
        for index, (start, end) in enumerate(
            [(0, 2), (2, 5), (5, 9.5), (9.5, 14.5), (14.5, 18)],
            1,
        )
    ]


@pytest.mark.parametrize(
    "owned,carry_in,expected",
    [
        ([1, 2, 3], None, [(1, 2), (2, 3)]),
        ([4, 5, 6], 3, [(3, 4), (4, 5), (5, 6)]),
        ([4, 5, 6], None, [(4, 5), (5, 6)]),
        ([4], None, []),
        ([4], 3, [(3, 4)]),
    ],
)
def test_semantic_clip_transition_projection_uses_owned_progression_and_optional_carry_in(
    owned, carry_in, expected,
):
    projected = _project_semantic_clip_transitions(_canonical_transitions(), owned, carry_in)
    assert [
        (item["from_keyframe_index"], item["to_keyframe_index"])
        for item in projected
    ] == expected


def test_semantic_clip_transition_projection_fails_soft_without_expanding_scope():
    transitions = [
        None,
        {"from_keyframe_index": "invalid", "to_keyframe_index": 2},
        {"from_keyframe_index": 1},
        {"from_keyframe_index": 1, "to_keyframe_index": 3},
        {"from_keyframe_index": 3, "to_keyframe_index": 4},
        {"from_keyframe_index": "1", "to_keyframe_index": "2"},
        {"from_keyframe_index": 2, "to_keyframe_index": 3},
    ]

    projected = _project_semantic_clip_transitions(transitions, [1, "bad", 2, 3], "bad")

    assert projected == [transitions[5], transitions[6]]


def test_semantic_clip_context_projects_transitions_without_mutating_canonical_authorities():
    transitions = _canonical_transitions()
    dialogue_timeline = [
        {"id": "D3", "dialogue_id": "D3", "speaker": "皇帝", "text": "第一句。", "start_time": 8.0, "end_time": 10.0},
        {"id": "D4", "dialogue_id": "D4", "speaker": "侍从2", "text": "第二句。", "start_time": 11.0, "end_time": 13.0},
    ]
    physical_manifest = {
        "version": 1,
        "references": [{"slot": 1, "source_keyframe_index": 4, "image_url": "/kf4.png"}],
    }
    clip = {
        "clip_index": 2,
        "start_time": 7.15,
        "end_time": 18,
        "capability": "GENERATE",
        "continuity_to_previous": "CUT",
        "visual_state_indexes": [4, 5, 6],
        "carry_in_state_index": 3,
        "dialogue_assignment": dialogue_timeline,
        "video_reference_manifest": physical_manifest,
    }
    plan = {
        "clip_plan": [clip],
        "keyframes": [
            {"index": index, "time_seconds": time}
            for index, time in enumerate([0, 2, 5, 9.5, 14.5, 18], 1)
        ],
        "transitions": transitions,
        "dialogue_timeline_source": dialogue_timeline,
    }
    before = json.loads(json.dumps(plan, ensure_ascii=False))

    context = _semantic_clip_prompt_context(plan, {"clip_index": 2})

    assert [item["index"] for item in context["keyframes"]] == [4, 5, 6]
    assert [
        (item["from_keyframe_index"], item["to_keyframe_index"])
        for item in context["transitions"]
    ] == [(3, 4), (4, 5), (5, 6)]
    assert context["clip"]["visual_state_indexes"] == [4, 5, 6]
    assert context["clip"]["carry_in_state_index"] == 3
    assert context["clip"]["video_reference_manifest"] == physical_manifest
    assert [item["dialogue_id"] for item in context["clip_dialogues"]] == ["D3", "D4"]
    assert plan == before
