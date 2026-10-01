import json
from types import SimpleNamespace

import pytest

from app.api.shots import (
    _build_keyframe_planner_user_content,
    _normalize_keyframe_planner_result,
    _preserve_matching_keyframe_assets,
)


def _states(count: int, duration: int = 10, *, end: bool = False):
    states = [{"index": 1, "time_seconds": 0, "role": "START", "description": None, "timed_visual_target": False}]
    for index in range(2, count + 1):
        is_end = end and index == count
        time_seconds = duration if is_end else duration * (index - 1) / count
        states.append({
            "index": index,
            "time_seconds": time_seconds,
            "role": "END" if is_end else "INTERMEDIATE",
            "description": f"state {index}",
            "timed_visual_target": False,
        })
    return states


@pytest.mark.parametrize("count", [1, 2, 3, 5, 8])
def test_canonical_keyframe_counts_normalize_without_window_identity(count):
    keyframes, windows, _ = _normalize_keyframe_planner_result(
        {"keyframes": _states(count), "window_plans": [{"selected_frame_count": 4, "workflow_key": "MINIMAX_H3_4FRAME"}]},
        [], 10,
    )
    assert len(keyframes) == count
    assert windows == []
    assert all("workflow_key" not in item and "selected_frame_count" not in item for item in keyframes)
    assert count != 8 or len(keyframes) == 8


@pytest.mark.parametrize(
    ("keyframes", "error"),
    [
        (_states(2)[:1] + [{**_states(2)[1], "index": 1}], "重复 index"),
        (_states(3)[:1] + [{**_states(3)[1], "time_seconds": 4}, {**_states(3)[2], "time_seconds": 4}], "重复 time_seconds"),
        (_states(3)[:1] + [{**_states(3)[1], "time_seconds": 3}, {**_states(3)[2], "time_seconds": 2}], "严格递增"),
        ([{"index": 1, "time_seconds": 0, "role": "INTERMEDIATE", "timed_visual_target": False}], "只能包含一个 START"),
        ([{"index": 1, "time_seconds": 0, "role": "START", "timed_visual_target": False},
          {"index": 2, "time_seconds": 5, "role": "START", "timed_visual_target": False}], "只能包含一个 START"),
        ([{"index": 1, "time_seconds": 1, "role": "START", "timed_visual_target": False}], "START keyframe time_seconds 必须为 0"),
        (_states(2, end=True)[:-1] + [{**_states(2, end=True)[-1], "time_seconds": 9}], "END keyframe time_seconds 必须等于 Shot duration"),
        ([{"index": 1, "time_seconds": 0, "role": "START", "timed_visual_target": True}], "START keyframe timed_visual_target 必须为 false"),
    ],
)
def test_canonical_keyframe_validation_rejects_invalid_states(keyframes, error):
    with pytest.raises(ValueError, match=error):
        _normalize_keyframe_planner_result({"keyframes": keyframes}, None, 10)


def test_canonical_end_is_optional_and_valid_end_must_be_at_duration():
    states, _, _ = _normalize_keyframe_planner_result({"keyframes": _states(2)}, None, 10)
    assert states[-1]["role"] == "INTERMEDIATE"
    with_end, _, _ = _normalize_keyframe_planner_result({"keyframes": _states(3, end=True)}, None, 10)
    assert with_end[-1]["role"] == "END"
    assert with_end[-1]["time_seconds"] == 10


def test_intermediate_timed_target_is_preserved():
    raw = _states(2)
    raw[1]["timed_visual_target"] = True
    states, _, _ = _normalize_keyframe_planner_result({"keyframes": raw}, None, 10)
    assert states[1]["timed_visual_target"] is True


def test_planner_prompt_does_not_include_physical_mode_or_window_authority():
    shot = SimpleNamespace(
        id="shot", index=1, description="A", video_description="B", characters="[]",
        scene="", props="[]", duration=10, continuity_mode="NORMAL", dialogues="[]",
    )
    content = _build_keyframe_planner_user_content(
        shot,
        {"selected_mode": "MULTI_KEYFRAME", "execution_windows": [{"window_index": 1}], "keyframes": []},
        {"supported_frame_counts": [3, 4]},
    )
    payload = json.loads(content.split("\n\n", 1)[1])
    assert "selected_mode" not in payload
    assert "execution_windows" not in payload
    assert "workflow_capability" not in payload
    assert payload["requirements"]["output_top_level_keys"] == ["keyframes"]


def test_replan_preserves_images_only_for_unchanged_indexed_state():
    existing = {"keyframes": [{
        "index": 2, "time_seconds": 5, "role": "INTERMEDIATE", "description": "same",
        "image_url": "same.png", "image_task_id": "task-2",
    }]}
    unchanged = [{"index": 2, "time_seconds": 5, "role": "INTERMEDIATE", "description": "same", "timed_visual_target": False}]
    changed = [{"index": 2, "time_seconds": 6, "role": "INTERMEDIATE", "description": "new", "timed_visual_target": False}]
    assert _preserve_matching_keyframe_assets(unchanged, existing, [])[0]["image_task_id"] == "task-2"
    assert "image_url" not in _preserve_matching_keyframe_assets(changed, existing, [])[0]


def test_historical_mode_and_windows_are_removed_only_when_new_plan_is_written():
    # This focuses the new-path contract: the normalizer ignores legacy window fields.
    normalized, windows, _ = _normalize_keyframe_planner_result(
        {"keyframes": _states(5), "selected_mode": "MULTI_KEYFRAME", "window_plans": [{"selected_frame_count": 3}]}, None, 10,
    )
    assert len(normalized) == 5
    assert windows == []


@pytest.mark.asyncio
@pytest.mark.parametrize("force", [False, True])
async def test_legacy_mode_recommendation_cannot_overwrite_canonical_n5_plan(db_session, force):
    from app.api import shots as shot_api
    from app.models.novel import Chapter, Novel
    from app.models.shot import Shot
    from app.repositories.chapter_repository import ChapterRepository
    from app.repositories.novel_repository import NovelRepository
    from app.repositories.prompt_template import PromptTemplateRepository
    from app.repositories.shot_repository import ShotRepository
    from app.repositories.workflow_repository import WorkflowRepository
    from app.schemas.shot import RecommendVideoModeRequest

    novel = Novel(title="canonical authority test")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="test")
    db_session.add(chapter)
    db_session.flush()
    canonical_plan = {
        "canonical_visual_plan": True,
        "keyframes": [
            {"index": 1, "time_seconds": 0, "role": "START", "description": None, "timed_visual_target": False},
            {"index": 2, "time_seconds": 6, "role": "INTERMEDIATE", "description": "state 2", "timed_visual_target": False},
            {"index": 3, "time_seconds": 12, "role": "INTERMEDIATE", "description": "state 3", "timed_visual_target": True},
            {"index": 4, "time_seconds": 18, "role": "INTERMEDIATE", "description": "state 4", "timed_visual_target": True},
            {"index": 5, "time_seconds": 24, "role": "END", "description": "state 5", "timed_visual_target": False},
        ],
        "transitions": [
            {"segment_index": index, "from_keyframe_index": index, "to_keyframe_index": index + 1}
            for index in range(1, 5)
        ],
        "clip_plan": [{"clip_index": 1, "start_time": 0, "end_time": 24}],
    }
    shot = Shot(
        chapter_id=chapter.id,
        index=1,
        description="A performer crosses the room.",
        duration=24,
        characters="[]",
        props="[]",
        dialogues="[]",
        video_director_plan=json.dumps(canonical_plan),
    )
    db_session.add(shot)
    db_session.commit()

    class FailIfCalledLLM:
        async def chat_completion(self, **_kwargs):
            raise AssertionError("legacy #07 LLM must not run for a canonical plan")

    result = await shot_api.recommend_video_mode(
        novel.id,
        chapter.id,
        shot.id,
        RecommendVideoModeRequest(force=force),
        db_session,
        NovelRepository(db_session),
        ChapterRepository(db_session),
        ShotRepository(db_session),
        WorkflowRepository(db_session),
        PromptTemplateRepository(db_session),
        FailIfCalledLLM(),
    )

    db_session.expire_all()
    persisted = json.loads(ShotRepository(db_session).get_by_id(shot.id).video_director_plan)
    assert result == {"success": True, "data": canonical_plan}
    assert persisted == canonical_plan
    assert len(persisted["keyframes"]) == 5
    assert [item["timed_visual_target"] for item in persisted["keyframes"]] == [False, False, True, True, False]
    assert len(persisted["transitions"]) == 4
    assert "selected_mode" not in persisted
    assert "recommended_mode" not in persisted


@pytest.mark.asyncio
async def test_normal_plan_keyframes_endpoint_persists_and_reloads_canonical_plan(db_session, monkeypatch):
    from app.api import shots as shot_api
    from app.models.novel import Chapter, Novel
    from app.models.prompt_template import PromptTemplate
    from app.models.shot import Shot
    from app.repositories.chapter_repository import ChapterRepository
    from app.repositories.novel_repository import NovelRepository
    from app.repositories.prompt_template import PromptTemplateRepository
    from app.repositories.shot_repository import ShotRepository
    from app.schemas.shot import PlanVideoKeyframesRequest

    novel = Novel(title="canonical plan test")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="test")
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(
        chapter_id=chapter.id,
        index=1,
        description="A person waits by a window.",
        duration=10,
        characters="[]",
        props="[]",
        dialogues="[]",
        video_director_plan=json.dumps({
            "selected_mode": "MULTI_KEYFRAME",
            "recommended_mode": "MULTI_KEYFRAME",
            "window_plans": [{"selected_frame_count": 3, "workflow_key": "MINIMAX_H3_3FRAME"}],
        }),
    )
    template = PromptTemplate(name="canonical planner", type="keyframe_planner", template="plan", is_system=True)
    db_session.add_all([shot, template])
    db_session.commit()

    async def complete(**kwargs):
        payload = json.loads(kwargs["user_content"].split("\n\n", 1)[1])
        assert "selected_mode" not in payload
        assert "execution_windows" not in payload
        return {"success": True, "content": json.dumps({
            "keyframes": [{"index": 1, "time_seconds": 0, "role": "START", "description": None, "timed_visual_target": False}]
        })}

    monkeypatch.setattr(shot_api, "get_style", lambda *args, **kwargs: ("", None))
    result = await shot_api.plan_video_keyframes(
        novel.id,
        chapter.id,
        shot.id,
        PlanVideoKeyframesRequest(force=True),
        db_session,
        NovelRepository(db_session),
        ChapterRepository(db_session),
        ShotRepository(db_session),
        PromptTemplateRepository(db_session),
        SimpleNamespace(chat_completion=complete),
    )
    db_session.expire_all()
    reloaded = ShotRepository(db_session).get_by_id(shot.id)
    persisted = json.loads(reloaded.video_director_plan)
    assert result["success"] is True
    assert persisted["canonical_visual_plan"] is True
    assert len(persisted["keyframes"]) == 1
    assert persisted["transitions"] == []
    assert "selected_mode" not in persisted
    assert "recommended_mode" not in persisted
    assert "window_plans" not in persisted
