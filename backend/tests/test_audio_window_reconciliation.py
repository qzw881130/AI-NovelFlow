from copy import deepcopy

import pytest

from app.services.audio_drive_service import _reconciled_audio_windows


def accepted_windows():
    return [
        {"window_index": 1, "start_time": 0, "end_time": 4.137, "duration": 4.137},
        {"window_index": 2, "start_time": 4.137, "end_time": 10, "duration": 5.863},
    ]


def test_partial_window_plans_cannot_hide_later_accepted_window():
    accepted = accepted_windows()
    c1 = {**accepted[0], "audio_status": "READY", "audio_timeline_id": "timeline",
          "drive_audio_path": "/audio/c1-drive.wav", "final_audio_path": "/audio/c1-final.wav"}
    plan = {"execution_windows": deepcopy(accepted), "window_plans": [c1]}

    reconciled = _reconciled_audio_windows(plan)

    assert [(item["window_index"], item["start_time"], item["end_time"]) for item in reconciled] == [
        (1, 0, 4.137), (2, 4.137, 10)]
    assert reconciled[0]["audio_status"] == "READY"
    assert "audio_status" not in reconciled[1]
    assert plan == {"execution_windows": accepted, "window_plans": [c1]}


def test_same_index_different_range_never_transfers_audio_fields():
    accepted = accepted_windows()
    stale = {**accepted[1], "start_time": 4, "audio_status": "READY",
             "final_audio_path": "/audio/stale-c2.wav"}
    reconciled = _reconciled_audio_windows({"execution_windows": accepted, "window_plans": [stale]})
    assert reconciled[1] == accepted[1]


def test_explicit_empty_execution_set_does_not_revive_stale_plans():
    stale = {**accepted_windows()[0], "audio_status": "READY", "final_audio_path": "/audio/stale.wav"}
    assert _reconciled_audio_windows({"execution_windows": [], "window_plans": [stale]}) == []
    assert _reconciled_audio_windows({"window_plans": [stale]}) == [stale]


def test_large_integer_identity_is_exact_and_conflicting_alias_is_rejected():
    large = 2 ** 53 + 1
    window = {"window_index": large, "start_time": 0, "end_time": 1}
    assert _reconciled_audio_windows({"execution_windows": [window]})[0]["window_index"] == large
    with pytest.raises(ValueError):
        _reconciled_audio_windows({"execution_windows": [{**window, "index": large - 1}]})


@pytest.mark.parametrize("plan", [
    {"execution_windows": [*accepted_windows(), {**accepted_windows()[1], "start_time": 8}]},
    {"execution_windows": [{"window_index": True, "start_time": 0, "end_time": 1}]},
    {"execution_windows": [{"window_index": 1.9, "start_time": 0, "end_time": 1}]},
    {"execution_windows": [{"window_index": 1, "index": 2, "start_time": 0, "end_time": 1}]},
    {"execution_windows": [{"window_index": 1, "index": True, "start_time": 0, "end_time": 1}]},
    {"execution_windows": [{"window_index": 1, "start_time": 0, "end_time": float("nan")}]},
    {"execution_windows": accepted_windows(), "window_plans": [accepted_windows()[0], accepted_windows()[0]]},
])
def test_ambiguous_or_invalid_window_identity_is_rejected(plan):
    with pytest.raises(ValueError):
        _reconciled_audio_windows(plan)
