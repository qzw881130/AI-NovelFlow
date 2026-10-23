"""New-task defaults and persisted-task compatibility for #14 repair."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.api.shots import (
    BatchShotVideoRequest,
    SemanticClipGenerateRequest,
    _batch_task_preflight_auto_repair,
    _new_task_preflight_auto_repair,
)
from app.schemas.shot import GenerateVideoDirectorClipRequest, GenerateVideoRequest
from app.services import h3_execution_optimizer
from app.services.shot_video_service import _apply_h3_execution_optimizer


@pytest.mark.parametrize("model, kwargs", [
    (GenerateVideoRequest, {}),
    (GenerateVideoDirectorClipRequest, {}),
    (SemanticClipGenerateRequest, {}),
    (BatchShotVideoRequest, {"shot_ids": ["shot-1"]}),
])
def test_request_preserves_missing_and_explicit_false(model, kwargs):
    assert model(**kwargs).preflight_auto_repair is None
    assert model(**kwargs, preflight_auto_repair=True).preflight_auto_repair is True
    assert model(**kwargs, preflight_auto_repair=False).preflight_auto_repair is False


@pytest.mark.parametrize("optimize, requested, expected", [
    (True, None, True), (True, True, True), (True, False, False),
    (False, None, False), (False, True, False), (False, False, False),
])
def test_new_task_resolves_repair_once(optimize, requested, expected):
    assert _new_task_preflight_auto_repair(optimize, requested) is expected


@pytest.mark.parametrize("parent, child, expected", [
    ({"preflight_auto_repair": True}, {"preflight_auto_repair": False}, False),
    ({"preflight_auto_repair": False}, {"preflight_auto_repair": True}, True),
    ({"preflight_auto_repair": True}, {}, True),
    ({"preflight_auto_repair": False}, {}, False),
    ({}, {"automatic_shot": True}, True),
    ({}, {"automatic_shot": False}, False),
    ({}, {}, False),
])
def test_batch_resume_uses_persisted_value_or_historical_behavior(parent, child, expected):
    assert _batch_task_preflight_auto_repair(parent, child) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize("metadata, expected", [
    ({"optimize_h3_prompt": True, "preflight_auto_repair": True}, True),
    ({"optimize_h3_prompt": True, "preflight_auto_repair": False}, False),
    ({"optimize_h3_prompt": True}, False),
    ({"optimize_h3_prompt": False, "preflight_auto_repair": True}, None),
])
async def test_worker_receives_persisted_setting_and_skips_disabled_optimizer(monkeypatch, metadata, expected):
    task = SimpleNamespace(id="task", metadata_json=json.dumps(metadata), prompt_text=None)
    shot = SimpleNamespace(id="shot", video_director_plan="{}", duration=4, description="opening")
    db = Mock()
    db.query.return_value.filter.return_value.all.return_value = []
    optimize = AsyncMock(return_value=("final", {"status": "OPTIMIZED"}))
    monkeypatch.setattr(h3_execution_optimizer, "optimize_h3_execution_prompt", optimize)
    result = await _apply_h3_execution_optimizer(
        db, task, None, shot, "raw", "SINGLE_FRAME", {"clip_index": 1, "planned_duration": 4})
    if expected is None:
        assert result == "raw"
        optimize.assert_not_called()
    else:
        assert result == "final"
        assert optimize.call_args.kwargs["execution_context"]["preflight_auto_repair"] is expected


@pytest.mark.asyncio
async def test_failed_optimizer_never_returns_raw_to_video_generation(monkeypatch):
    task = SimpleNamespace(id="task", metadata_json=json.dumps({
        "optimize_h3_prompt": True, "preflight_auto_repair": True}), prompt_text=None)
    shot = SimpleNamespace(id="shot", video_director_plan="{}", duration=4, description="opening")
    db = Mock()
    db.query.return_value.filter.return_value.all.return_value = []
    monkeypatch.setattr(h3_execution_optimizer, "optimize_h3_execution_prompt", AsyncMock(
        return_value=("raw", {"status": "FALLBACK", "error_code": "PREFLIGHT_FAIL", "error": "authority"})))
    with pytest.raises(ValueError, match="PREFLIGHT_FAIL"):
        await _apply_h3_execution_optimizer(
            db, task, None, shot, "raw", "SINGLE_FRAME", {"clip_index": 1, "planned_duration": 4})
    assert json.loads(task.metadata_json)["h3_prompt_optimizer"]["generation_blocked"] is True
