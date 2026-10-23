import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import clip_planner


def _canonical_shot(duration=24, *, timed_index=None, image_path=None, continuity="CONTINUOUS_TAKE", count=5):
    keyframes = []
    for index in range(1, count + 1):
        time_seconds = (index - 1) * duration / (count - 1) if count > 1 else 0
        role = "START" if index == 1 else "END" if index == count else "INTERMEDIATE"
        keyframe = {
            "index": index,
            "time_seconds": time_seconds,
            "role": role,
            "description": "",
            "timed_visual_target": index == timed_index,
        }
        if index == timed_index and image_path:
            keyframe["image_url"] = str(image_path)
        keyframes.append(keyframe)
    return SimpleNamespace(
        id="shot-arbitrary-n",
        chapter_id="chapter-arbitrary-n",
        duration=duration,
        continuity_mode=continuity,
        description="continuous visual beats",
        video_description="",
        dialogues="[]",
        image_url=None,
        image_path=None,
        keyframes="[]",
        video_director_plan=json.dumps({"canonical_visual_plan": True, "keyframes": keyframes}),
    )


def test_deterministic_projection_matches_frozen_boundary_examples():
    candidates = [
        {"keyframe_index": 1, "time_seconds": 0, "role": "START"},
        {"keyframe_index": 2, "time_seconds": 6, "role": "INTERMEDIATE"},
        {"keyframe_index": 3, "time_seconds": 12, "role": "INTERMEDIATE"},
        {"keyframe_index": 4, "time_seconds": 18, "role": "INTERMEDIATE"},
        {"keyframe_index": 5, "time_seconds": 24, "role": "END"},
    ]
    clips = [
        {"clip_index": 1, "start_time": 0, "end_time": 8},
        {"clip_index": 2, "start_time": 8, "end_time": 16},
        {"clip_index": 3, "start_time": 16, "end_time": 24},
    ]
    clip_planner._project_clip_visual_states(clips, candidates)
    assert [item["visual_state_indexes"] for item in clips] == [[1, 2], [3], [4, 5]]
    assert [item["carry_in_state_index"] for item in clips] == [None, 2, 3]


def test_shared_boundary_is_owned_by_previous_clip():
    candidates = [{"keyframe_index": i, "time_seconds": (i - 1) * 8, "role": "START" if i == 1 else "INTERMEDIATE"} for i in range(1, 5)]
    clips = [{"clip_index": i, "start_time": (i - 1) * 8, "end_time": i * 8} for i in range(1, 4)]
    clip_planner._project_clip_visual_states(clips, candidates)
    assert [item["visual_state_indexes"] for item in clips] == [[1, 2], [3], [4]]
    assert [item["carry_in_state_index"] for item in clips] == [None, 2, 3]


def test_clip_with_no_owned_state_keeps_only_carry_in():
    candidates = [{"keyframe_index": 1, "time_seconds": 0, "role": "START"}, {"keyframe_index": 2, "time_seconds": 20, "role": "END"}]
    clips = [{"clip_index": 1, "start_time": 0, "end_time": 8}, {"clip_index": 2, "start_time": 8, "end_time": 14}]
    clip_planner._project_clip_visual_states(clips, candidates)
    assert clips[0]["visual_state_indexes"] == [1]
    assert clips[1]["visual_state_indexes"] == []
    assert clips[1]["carry_in_state_index"] == 1


def _fake_planner(monkeypatch, response):
    class FakePromptTemplateService:
        def __init__(self, db):
            pass

        def get_default_system_template(self, name):
            return SimpleNamespace(template="planner", name="planner")

    class FakeLLMService:
        async def chat_completion(self, **kwargs):
            payload = json.loads(kwargs['user_content'])
            for clip in response:
                clip['early_composition_state_id'] = None
                if clip['continuity_to_previous'] == 'CONTINUOUS' and not clip['selected_temporal_target_ids']:
                    interior = [v for v in payload['visual_state_candidates'] if clip['start_time'] + .05 < v['time_seconds'] < clip['end_time']]
                    if interior: clip['early_composition_state_id'] = interior[0]['visual_state_id']
            return {"success": True, "content": json.dumps({"clips": response})}

    monkeypatch.setattr(clip_planner, "PromptTemplateService", FakePromptTemplateService)
    monkeypatch.setattr(clip_planner, "LLMService", FakeLLMService)


def test_canonical_plan_persists_arbitrary_n_clip_projection(monkeypatch):
    shot = _canonical_shot()
    _fake_planner(monkeypatch, [
        {"clip_index": 1, "start_time": 0, "end_time": 8, "continuity_to_previous": "NONE", "selected_temporal_target_ids": [], "capability": "GENERATE"},
        {"clip_index": 2, "start_time": 8, "end_time": 16, "continuity_to_previous": "CONTINUOUS", "selected_temporal_target_ids": [], "capability": "EXTEND"},
        {"clip_index": 3, "start_time": 16, "end_time": 24, "continuity_to_previous": "CONTINUOUS", "selected_temporal_target_ids": [], "capability": "EXTEND"},
    ])
    clips, validation = asyncio.run(clip_planner.plan_clips(None, SimpleNamespace(id="novel"), shot, []))
    assert validation["passed"] is True, validation
    assert [item["visual_state_indexes"] for item in clips] == [[1, 2], [3], [4, 5]]
    assert [item["carry_in_state_index"] for item in clips] == [None, 2, 3]
    assert [item["capability"] for item in clips] == ["GENERATE", "TEMPORAL_EXTEND", "TEMPORAL_EXTEND"]


def test_first_or_cut_timed_target_stays_generate(monkeypatch):
    shot = _canonical_shot(timed_index=3, continuity="NORMAL")
    _fake_planner(monkeypatch, [
        {"clip_index": 1, "start_time": 0, "end_time": 8, "continuity_to_previous": "NONE", "selected_temporal_target_ids": [], "capability": "GENERATE"},
        {"clip_index": 2, "start_time": 8, "end_time": 20, "continuity_to_previous": "CUT", "selected_temporal_target_ids": [], "capability": "GENERATE"},
        {"clip_index": 3, "start_time": 20, "end_time": 24, "continuity_to_previous": "CUT", "selected_temporal_target_ids": [], "capability": "GENERATE"},
    ])
    clips, validation = asyncio.run(clip_planner.plan_clips(None, SimpleNamespace(id="novel"), shot, []))
    assert validation["passed"] is True, validation
    assert all(item["capability"] == "GENERATE" for item in clips)


def test_continuous_timed_target_requires_image_and_routes_temporal_extend(tmp_path, monkeypatch):
    image = tmp_path / "kf3.png"
    image.write_bytes(b"kf3")
    shot = _canonical_shot(timed_index=3, image_path=image)
    _fake_planner(monkeypatch, [
        {"clip_index": 1, "start_time": 0, "end_time": 8, "continuity_to_previous": "NONE", "selected_temporal_target_ids": [], "capability": "GENERATE"},
        {"clip_index": 2, "start_time": 8, "end_time": 20, "continuity_to_previous": "CONTINUOUS", "selected_temporal_target_ids": ["KF3"], "capability": "EXTEND"},
        {"clip_index": 3, "start_time": 20, "end_time": 24, "continuity_to_previous": "CUT", "selected_temporal_target_ids": [], "capability": "EXTEND"},
    ])
    clips, validation = asyncio.run(clip_planner.plan_clips(None, SimpleNamespace(id="novel"), shot, []))
    assert validation["passed"] is True, validation
    assert clips[1]["capability"] == "TEMPORAL_EXTEND"
    assert clips[1]["visual_state_indexes"] == [3, 4]
    assert clips[1]["selected_temporal_target_ids"] == ["KF3"]


def test_missing_continuous_timed_target_image_is_not_downgraded(monkeypatch):
    shot = _canonical_shot(timed_index=3)
    _fake_planner(monkeypatch, [
        {"clip_index": 1, "start_time": 0, "end_time": 8, "continuity_to_previous": "NONE", "selected_temporal_target_ids": [], "capability": "GENERATE"},
        {"clip_index": 2, "start_time": 8, "end_time": 20, "continuity_to_previous": "CONTINUOUS", "selected_temporal_target_ids": ["KF3"], "capability": "EXTEND"},
        {"clip_index": 3, "start_time": 20, "end_time": 24, "continuity_to_previous": "CUT", "selected_temporal_target_ids": []},
    ])
    anchors = []
    clips, validation = asyncio.run(clip_planner.plan_clips(None, SimpleNamespace(id="novel"), shot, anchors))
    assert validation["passed"] is True
    assert clips[1]["capability"] == "TEMPORAL_EXTEND"
    assert clips[1]["selected_temporal_target_ids"] == ["KF3"]
    assert anchors[0]["image_url"] is None


def test_n8_and_more_than_nine_owned_states_are_not_semantically_thinned(monkeypatch):
    shot = _canonical_shot(duration=40, continuity="NORMAL", count=9)
    _fake_planner(monkeypatch, [{"clip_index": 1, "start_time": 0, "end_time": 15, "continuity_to_previous": "NONE", "selected_temporal_target_ids": [], "capability": "GENERATE"}, {"clip_index": 2, "start_time": 15, "end_time": 30, "continuity_to_previous": "CUT", "selected_temporal_target_ids": [], "capability": "GENERATE"}, {"clip_index": 3, "start_time": 30, "end_time": 40, "continuity_to_previous": "CUT", "selected_temporal_target_ids": [], "capability": "GENERATE"}])
    clips, validation = asyncio.run(clip_planner.plan_clips(None, SimpleNamespace(id="novel"), shot, []))
    assert validation["passed"] is True, validation
    assert sum(len(item["visual_state_indexes"]) for item in clips) == 9
    assert max(len(item["visual_state_indexes"]) for item in clips) > 0


def test_validator_checks_canonical_ownership_without_physical_ref_budget():
    candidates = [{"keyframe_index": i, "time_seconds": i, "role": "START" if i == 1 else "INTERMEDIATE"} for i in range(1, 12)]
    clips = [{"clip_index": 1, "start_time": 0, "end_time": 11, "planned_duration": 11, "capability": "GENERATE", "continuity_to_previous": "NONE", "selected_temporal_target_ids": [], "visual_state_indexes": list(range(1, 12)), "carry_in_state_index": None}]
    from app.services.clip_validator import validate_clip_plan
    result = validate_clip_plan(11, clips, [], visual_state_candidates=candidates)
    assert result["passed"] is True, result


@pytest.mark.asyncio
async def test_canonical_clip_plan_persistence_and_reload(db_session, monkeypatch):
    from app.api import shots as shots_api
    from app.models.novel import Chapter, Novel
    from app.models.shot import Shot
    from app.repositories.chapter_repository import ChapterRepository
    from app.repositories.novel_repository import NovelRepository
    from app.repositories.shot_repository import ShotRepository
    from app.schemas.shot import PlanClipsRequest

    novel = Novel(title="G-2B persistence")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="Clip projection")
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(
        chapter_id=chapter.id,
        index=1,
        duration=24,
        description="canonical states",
        characters="[]",
        props="[]",
        dialogues="[]",
        video_director_plan=json.dumps({"canonical_visual_plan": True, "keyframes": []}),
    )
    db_session.add(shot)
    db_session.commit()
    clips = [{
        "clip_index": 1,
        "start_time": 0,
        "end_time": 12,
        "planned_duration": 12,
        "capability": "GENERATE",
        "continuity_to_previous": "NONE", "selected_temporal_target_ids": [],
        "visual_state_indexes": [1, 2],
        "carry_in_state_index": None,
        "execution_status": "PLANNED",
    }, {
        "clip_index": 2,
        "start_time": 12,
        "end_time": 24,
        "planned_duration": 12,
        "capability": "EXTEND",
        "continuity_to_previous": "CONTINUOUS", "selected_temporal_target_ids": [],
        "previous_clip_index": 1,
        "visual_state_indexes": [3],
        "carry_in_state_index": 2,
        "execution_status": "PLANNED",
    }]
    validation = {"passed": True, "blocking": [], "findings": [], "warnings": []}

    async def fake_plan(*args, **kwargs):
        return clips, validation

    monkeypatch.setattr(shots_api, "plan_clips", fake_plan)
    result = await shots_api.plan_shot_clips(
        novel.id,
        chapter.id,
        shot.id,
        PlanClipsRequest(force=True),
        db_session,
        NovelRepository(db_session),
        ShotRepository(db_session),
    )
    db_session.expire_all()
    reloaded = ShotRepository(db_session).get_by_id(shot.id)
    persisted = json.loads(reloaded.video_director_plan)
    assert result["data"]["revision"] == 1
    assert persisted["clip_plan_revision"] == 1
    assert persisted["clip_plan"][1]["visual_state_indexes"] == [3]
    assert persisted["clip_plan"][1]["carry_in_state_index"] == 2
