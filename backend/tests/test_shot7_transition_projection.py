"""Offline checks for the shared #11–#14 semantic Clip transition view."""
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.services import h3_execution_optimizer, h3_continuation
from app.services.shot_video_service import (
    _apply_h3_execution_optimizer,
    _project_semantic_clip_transitions,
    _select_video_prompt_context,
)


def _transition(segment, start, end):
    return {
        "segment_index": segment,
        "from_keyframe_index": segment,
        "to_keyframe_index": segment + 1,
        "start_time": start,
        "end_time": end,
        "transition_description": f"Original canonical action {segment}; later outcome stays later.",
    }


def _shot7_plan():
    return {
        "clip_plan_revision": 1,
        "keyframes": [{"index": i} for i in range(1, 6)],
        "transitions": [
            _transition(1, 0.0, 4.2),
            _transition(2, 4.2, 6.2),
            _transition(3, 6.2, 10.5),
            _transition(4, 10.5, 27.0),
        ],
        "clip_plan": [
            {"clip_index": 1, "start_time": 0.0, "end_time": 10.6,
             "capability": "GENERATE", "visual_state_indexes": [1, 2, 3, 4],
             "continuity_to_previous": "NONE", "dialogue_assignment": []},
            {"clip_index": 2, "start_time": 10.6, "end_time": 27.0,
             "capability": "EXTEND", "visual_state_indexes": [5],
             "carry_in_state_index": 4, "continuity_to_previous": "CONTINUOUS",
             "dialogue_assignment": []},
        ],
    }


def test_transition_projection_uses_positive_overlap_and_preserves_original_times():
    original = _transition(2, 4.0, 6.0)
    before = deepcopy(original)
    full = _project_semantic_clip_transitions([original], [2, 3], clip_start=3.0, clip_end=7.0)
    assert len(full) == 1
    assert (full[0]["clip_local_start_time"], full[0]["clip_local_end_time"]) == (1.0, 3.0)
    assert (full[0]["start_time"], full[0]["end_time"]) == (4.0, 6.0)
    assert _project_semantic_clip_transitions([original], [2, 3], clip_start=6.0, clip_end=8.0) == []
    assert _project_semantic_clip_transitions([original], [2, 3], clip_start=4.0, clip_end=7.0)[0]["clip_local_start_time"] == 0.0
    assert _project_semantic_clip_transitions([original], [2], clip_start=0.0, clip_end=4.0) == []
    continuation = _project_semantic_clip_transitions(
        [original], [3], 2, clip_start=5.0, clip_end=8.0,
    )[0]
    assert continuation["projection_mode"] == "CROSS_CLIP_CONTINUATION"
    assert (continuation["clip_local_start_time"], continuation["clip_local_end_time"]) == (0.0, 1.0)
    assert original == before


def test_shot7_cross_clip_transition_is_scoped_once_per_clip():
    plan = _shot7_plan()
    before = deepcopy(plan)
    c1, c2 = plan["clip_plan"]
    first = _project_semantic_clip_transitions(
        plan["transitions"], c1["visual_state_indexes"],
        clip_start=c1["start_time"], clip_end=c1["end_time"],
    )
    second = _project_semantic_clip_transitions(
        plan["transitions"], c2["visual_state_indexes"], c2["carry_in_state_index"],
        clip_start=c2["start_time"], clip_end=c2["end_time"],
    )
    assert [x["canonical_source_id"] for x in first] == [f"transition_{i}" for i in range(1, 5)]
    assert [x["canonical_source_id"] for x in second] == ["transition_4"]
    opening, continuing = first[-1], second[0]
    assert opening["projection_mode"] == "CROSS_CLIP_OPENING"
    assert (opening["clip_local_start_time"], opening["clip_local_end_time"]) == (10.5, 10.6)
    assert opening["target_state_owned"] is False
    assert "do not perform later actions" in opening["execution_scope"]
    assert continuing["projection_mode"] == "CROSS_CLIP_CONTINUATION"
    assert (continuing["clip_local_start_time"], continuing["clip_local_end_time"]) == (0.0, 16.4)
    assert continuing["target_state_owned"] is True
    assert continuing["action_progress"] == "UNVERIFIED_FROM_PREVIOUS_VIDEO"
    assert opening["transition_description"] == continuing["transition_description"]
    assert (opening["start_time"], opening["end_time"]) == (10.5, 27.0)
    assert (continuing["start_time"], continuing["end_time"]) == (10.5, 27.0)
    assert len({x["canonical_source_id"] for x in first}) == len(first)
    assert plan == before


@pytest.mark.asyncio
@pytest.mark.parametrize("clip_index", [1, 2])
async def test_shot7_prompt_steps_and_optimizer_receive_identical_projection(monkeypatch, clip_index):
    plan = _shot7_plan()
    before = deepcopy(plan)
    expected = _select_video_prompt_context(
        plan, {"execution_scope": "CLIP", "clip_index": clip_index},
        "SINGLE_FRAME", 27.0, True,
    )["transitions"]
    for mode in ("FIRST_LAST_FRAME", "MULTI_KEYFRAME"):
        assert _select_video_prompt_context(
            plan, {"execution_scope": "CLIP", "clip_index": clip_index},
            mode, 27.0, True,
        )["transitions"] == expected

    invoke = AsyncMock(return_value=("optimized", {"status": "OPTIMIZED"}))
    monkeypatch.setattr(h3_execution_optimizer, "optimize_h3_execution_prompt", invoke)
    monkeypatch.setattr(h3_continuation, "continuation_contract", lambda *args: {})
    clip = plan["clip_plan"][clip_index - 1]
    shot = SimpleNamespace(video_director_plan=json.dumps(plan), duration=27.0, description="Opening state")
    task = SimpleNamespace(metadata_json=json.dumps({"optimize_h3_prompt": True, "capability": clip["capability"]}))
    assert await _apply_h3_execution_optimizer(
        Mock(), task, None, shot, "Raw", "SINGLE_FRAME", clip,
        execution_context={"previous_clip": {"task_id": "c1"}} if clip_index == 2 else {},
    ) == "optimized"
    context = invoke.call_args.kwargs["execution_context"]
    assert context["canonical_transitions"] == expected
    source = context["canonical_visual_sources"][-1]
    assert source["id"] == expected[-1]["canonical_source_id"]
    assert source["text"] == expected[-1]["transition_description"]
    assert source["clip_scope"]["clip_local_end_time"] == expected[-1]["clip_local_end_time"]
    assert plan == before
