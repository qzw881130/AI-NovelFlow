from copy import deepcopy

import pytest

from app.api.shots import _collect_audio_clip_sources, _preserve_matching_clip_audio_fields


def test_shot116_production_duplicate_sources_preserve_audio():
    windows = [
        {"window_index": 1, "start_time": 0, "end_time": 14.117},
        {"window_index": 2, "start_time": 14.117, "end_time": 21.634},
    ]
    bindings = [
        {
            "audio_status": "READY", "audio_message": "", "audio_timeline_id": "shot116-timeline",
            "audio_timeline_revision": 3, "audio_timeline_hash": "canonical-hash",
            "speaker_timeline": [{"speaker": "speaker-1", "start": 0}],
            "drive_audio_url": f"/audio/116-{index}-drive.wav",
            "final_audio_url": f"/audio/116-{index}-final.wav",
            "drive_audio_path": f"/tmp/116-{index}-drive.wav",
            "final_audio_path": f"/tmp/116-{index}-final.wav",
            "clip_audio_manifest_path": f"/tmp/116-{index}.json",
            "clip_audio_duration": window["end_time"] - window["start_time"],
        }
        for index, window in enumerate(windows, 1)
    ]
    plan = {
        "window_plans": [{**window, **binding} for window, binding in zip(windows, bindings)],
        "execution_windows": deepcopy(windows),
        "clips": [
            {"clip_index": window["window_index"], "start_time": window["start_time"], "end_time": window["end_time"]}
            for window in windows
        ],
    }
    original = deepcopy(plan)
    for target_key in ("execution_windows", "clips"):
        targets = deepcopy(plan[target_key])
        result = _preserve_matching_clip_audio_fields(targets, _collect_audio_clip_sources(plan))
        assert result is targets
        assert result == [{**window, **binding} for window, binding in zip(plan[target_key], bindings)]
    assert plan == original


@pytest.mark.parametrize("fallback_key", ["execution_windows", "clips"])
def test_bare_primary_source_does_not_hide_audio_fallback(fallback_key):
    window = {"window_index": 1, "start_time": 0, "end_time": 14.117}
    bound = {**window, "audio_timeline_id": "fallback", "drive_audio_url": "fallback.wav"}
    plan = {"window_plans": [window], fallback_key: [bound]}
    assert _preserve_matching_clip_audio_fields([dict(window)], _collect_audio_clip_sources(plan)) == [bound]


def test_first_matching_binding_wins_without_merging_stale_fields():
    window = {"window_index": 1, "start_time": 0, "end_time": 14.117}
    primary = {**window, "audio_status": "STALE", "audio_timeline_id": "primary", "audio_timeline_revision": 0}
    conflicting = {
        **window, "audio_status": "READY", "audio_timeline_id": "other", "audio_timeline_revision": 9,
        "drive_audio_url": "other.wav", "final_audio_path": "other-final.wav",
    }
    plan = {"window_plans": [primary, conflicting], "execution_windows": [conflicting], "clips": [conflicting]}
    assert _preserve_matching_clip_audio_fields([dict(conflicting)], _collect_audio_clip_sources(plan)) == [primary]


@pytest.mark.parametrize("stale_range", [(0, 15), (1, 14.117), (0, 14.118)])
def test_range_matching_precedes_candidate_priority(stale_range):
    target = {"window_index": 1, "start_time": 0, "end_time": 14.117}
    stale = {**target, "start_time": stale_range[0], "end_time": stale_range[1], "drive_audio_url": "stale.wav"}
    matching = {**target, "drive_audio_url": "matching.wav"}
    plan = {"window_plans": [stale, matching], "clips": [stale]}
    assert _preserve_matching_clip_audio_fields([dict(target)], _collect_audio_clip_sources(plan)) == [matching]


@pytest.mark.parametrize("change", [
    {"window_index": 2}, {"start_time": 0.001}, {"end_time": 14.118},
    {"start_time": None}, {"end_time": None},
])
def test_audio_is_not_transferred_to_changed_index_or_range(change):
    source = {"window_index": 1, "start_time": 0, "end_time": 14.117, "drive_audio_url": "old.wav"}
    target = {"window_index": 1, "start_time": 0, "end_time": 14.117, **change}
    assert _preserve_matching_clip_audio_fields([dict(target)], [source]) == [target]


def test_missing_source_range_does_not_match_zero_start():
    target = {"clip_index": 1, "start_time": 0, "end_time": 14.117}
    source = {"clip_index": 1, "end_time": 14.117, "drive_audio_url": "old.wav"}
    assert _preserve_matching_clip_audio_fields([dict(target)], [source]) == [target]
