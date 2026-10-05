"""Blocking planning failures do not replace the current canonical revision."""
import json
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from app.services import clip_planner
from test_two_stage_temporal_decision import _plan, _clips, _db_fixture


@pytest.mark.asyncio
async def test_dialogue_failure_propagates_through_planner_before_contract_markers(monkeypatch, tmp_path):
    child = {"passed": False, "findings": ["DIALOGUE_SEGMENT_TIMING_GAP"],
             "source_dialogue_count": 1, "assigned_segment_count": 1}
    monkeypatch.setattr(clip_planner, "assign_dialogues_to_clips", lambda *_args: ([], child))
    _, plan, calls = await _plan(monkeypatch, tmp_path, [_clips(["KF3"])])
    validation = plan["clip_plan_validation"]
    assert len(calls) == 1
    assert validation["passed"] is False
    assert validation["dialogue_ownership"] == child
    assert [f["code"] for f in validation["blocking"]] == child["findings"]
    assert "temporal_contract" not in validation and "composition_contract" not in validation


def test_child_failure_removes_success_markers_and_remains_idempotent():
    validation = {"passed": True, "findings": [], "blocking": [],
                  "temporal_contract": "ELIGIBLE_THEN_SELECTED_V1", "composition_contract": "EARLY_COMPOSITION_V1"}
    child = {"passed": False, "findings": ["DIALOGUE_SPEAKER_CHANGED"]}
    clip_planner.merge_dialogue_ownership_validation(validation, child)
    first = deepcopy(validation)
    clip_planner.merge_dialogue_ownership_validation(validation, child)
    assert validation == first and validation["passed"] is False
    assert "temporal_contract" not in validation and "composition_contract" not in validation


def test_successful_dialogue_validation_does_not_authorize_an_unvalidated_plan():
    validation = {}
    clip_planner.merge_dialogue_ownership_validation(validation, {"passed": True, "findings": []})
    assert validation["passed"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("child_failure", [True, False])
async def test_rejected_candidate_does_not_replace_plan_or_increment_revision(db_session, tmp_path, monkeypatch, child_failure):
    from app.api import shots as api
    from app.repositories import NovelRepository, ShotRepository
    from app.models.task import Task
    novel, chapter, shot, _, artifact = _db_fixture(db_session, tmp_path)
    before = shot.video_director_plan
    count = db_session.query(Task).count()
    validation = {"passed": True, "findings": [], "blocking": []}
    if child_failure:
        clip_planner.merge_dialogue_ownership_validation(validation, {"passed": False, "findings": ["DIALOGUE_SPEAKER_CHANGED"]})
    else:
        validation.update(passed=False, findings=[{"code": "PROVIDER_DURATION_LIMIT", "severity": "BLOCKING"}])
    mock = AsyncMock(return_value=(_clips(["KF3"]), validation))
    monkeypatch.setattr(api, "plan_clips", mock)
    result = await api.plan_shot_clips(
        novel.id, chapter.id, shot.id, api.PlanClipsRequest(force=True), db_session,
        NovelRepository(db_session), ShotRepository(db_session),
    )
    assert result["data"]["validation"]["passed"] is False
    assert "revision" not in result["data"]
    db_session.refresh(shot)
    assert shot.video_director_plan == before
    assert json.loads(shot.video_director_plan)["clip_plan_revision"] == 7
    assert db_session.query(Task).count() == count and artifact.read_bytes() == b"historical"
    assert mock.await_count == 1


@pytest.mark.asyncio
async def test_cached_plan_dialogue_failure_returns_diagnostics_without_persistence(db_session, tmp_path, monkeypatch):
    from app.api import shots as api
    from app.repositories import NovelRepository, ShotRepository
    novel, chapter, shot, _, _ = _db_fixture(db_session, tmp_path)
    shot.dialogues = json.dumps([{"character_name": "甲", "text": "原文。"}])
    plan = json.loads(shot.video_director_plan)
    plan["dialogue_timeline_source"] = [{"id": "D1", "speaker": "甲", "text": "被改写。", "start_time": 1, "end_time": 3}]
    shot.video_director_plan = json.dumps(plan)
    db_session.commit()
    before = shot.video_director_plan
    mock = AsyncMock(side_effect=AssertionError("Cached validation must not call the planner"))
    monkeypatch.setattr(api, "plan_clips", mock)
    result = await api.plan_shot_clips(
        novel.id, chapter.id, shot.id, api.PlanClipsRequest(force=False), db_session,
        NovelRepository(db_session), ShotRepository(db_session),
    )
    assert result["data"]["validation"]["passed"] is False
    assert "DIALOGUE_TEXT_MISSING_OR_CHANGED" in result["data"]["validation"]["dialogue_ownership"]["findings"]
    db_session.refresh(shot)
    assert shot.video_director_plan == before
    mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_early_coverage_remains_continuous_and_hard_fails_once(monkeypatch, tmp_path):
    raw = _clips([])
    before = deepcopy(raw)
    with pytest.raises(ValueError, match="EARLY_COMPOSITION_COVERAGE_INVALID"):
        await _plan(monkeypatch, tmp_path, [raw])
    assert raw == before and raw[1]["continuity_to_previous"] == "CONTINUOUS"


@pytest.mark.asyncio
async def test_real_cut_still_accepts_no_early_composition(monkeypatch, tmp_path):
    _, plan, calls = await _plan(monkeypatch, tmp_path, [_clips([], "CUT")])
    assert len(calls) == 1 and plan["clip_plan_validation"]["passed"]
    assert plan["clip_plan"][1]["continuity_to_previous"] == "CUT"
    assert plan["clip_plan"][1]["capability"] == "GENERATE"
    assert plan["temporal_anchors"] == []
