import asyncio
from copy import deepcopy
import json

import pytest

from app.api.audio_drive import get_audio_timeline
from app.models.audio_drive import AudioEventTTSAsset, ShotAudioTimeline
from app.models.task import Task
from app.schemas.audio_drive import AudioTimelineResponse
from app.services.audio_drive_service import AudioDriveService
from test_duration_contract_gate_b3 import _create_ready_event, _create_shot


@pytest.mark.parametrize("visual", [2.0, 12.0])
@pytest.mark.parametrize("continuity", ["NORMAL", "CONTINUOUS_TAKE"])
def test_timing_summary_keeps_visual_floor_and_explicit_final_pause(db_session, monkeypatch, visual, continuity):
    shot = _create_shot(db_session, estimated_duration=visual, duration=99)
    shot.continuity_mode = continuity
    first_event, _ = _create_ready_event(db_session, shot.id, 1.25, pause_after="SHORT")
    last_event, _ = _create_ready_event(db_session, shot.id, 2.0, pause_after="LONG")
    last_event.event_order = 2
    db_session.commit()
    service = AudioDriveService(db_session)
    built = service.build_timeline(shot.id, force=True)["data"]
    assert built["audioRequiredDuration"] == 4.75
    assert service.build_execution_windows(shot.id, max_clip_duration=6)["success"]
    timeline = service.repo.latest_timeline(shot.id)
    before = (shot.video_director_plan, shot.video_director_plan_revision, shot.duration,
              timeline.audio_summary_json, timeline.total_duration, timeline.revision)
    monkeypatch.setattr(service, "_probe_audio_duration", lambda *_: pytest.fail("GET must not probe files"))
    monkeypatch.setattr(service, "_render_clip_audio", lambda *_: pytest.fail("GET must not render"))
    response = service.get_timeline(shot.id)["data"]
    summary = response["timingSummary"]
    assert summary == {
        "measurementBasis": "READY_TTS_ASSET_FILE_DURATION", "ttsEventCount": 2, "readyTtsEventCount": 2,
        "ttsCoverageComplete": True, "unmeasuredAudioEventIds": [],
        "measuredTtsDurationSeconds": 3.25, "measuredTtsCoverageSeconds": 3.25,
        "lastTtsFileEndSeconds": 3.55, "authoredFinalPauseSeconds": 1.2,
        "visualEstimatedFloorSeconds": visual, "resolvedDurationSeconds": max(visual, 4.75),
        "remainingNonSpeechHoldSeconds": round(max(visual, 4.75) - 3.55, 3),
        "holdAfterAuthoredFinalPauseSeconds": round(max(visual, 4.75) - 4.75, 3),
        "longTailReviewSuggested": visual == 12.0,
    }
    assert AudioTimelineResponse.model_validate(response).model_dump()["timingSummary"] == summary
    assert service.build_timeline(shot.id)["data"]["id"] == built["id"]
    assert asyncio.run(get_audio_timeline(shot.id, db_session))["data"]["timingSummary"] == summary
    assert (shot.video_director_plan, shot.video_director_plan_revision, shot.duration,
            timeline.audio_summary_json, timeline.total_duration, timeline.revision) == before
    assert first_event.pause_after == "SHORT" and last_event.pause_after == "LONG"
    assert shot.continuity_mode == continuity
    assert db_session.query(ShotAudioTimeline).count() == 1
    assert db_session.query(Task).count() == 0


def test_legacy_pause_comes_from_saved_audio_cursor_not_edited_event(db_session):
    shot = _create_shot(db_session, estimated_duration=12)
    event, _ = _create_ready_event(db_session, shot.id, 3, pause_after="LONG")
    service = AudioDriveService(db_session)
    service.build_timeline(shot.id, force=True)
    timeline = service.repo.latest_timeline(shot.id)
    timeline.audio_summary_json = '{"legacy": true}'
    event.pause_after = "NONE"
    db_session.commit()
    before = (timeline.audio_summary_json, shot.video_director_plan)
    assert service.get_timeline(shot.id)["data"]["timingSummary"]["authoredFinalPauseSeconds"] == 1.2
    assert (timeline.audio_summary_json, shot.video_director_plan) == before
    timeline.audio_required_duration = None
    db_session.commit()
    summary = service.get_timeline(shot.id)["data"]["timingSummary"]
    assert summary["authoredFinalPauseSeconds"] is None
    assert summary["holdAfterAuthoredFinalPauseSeconds"] is None
    assert not summary["longTailReviewSuggested"]


@pytest.mark.parametrize("defect", ["stale_asset", "missing_duration", "stale_timeline"])
def test_incomplete_coverage_does_not_claim_speech_tail(db_session, defect):
    shot = _create_shot(db_session)
    event, asset = _create_ready_event(db_session, shot.id, 3)
    service = AudioDriveService(db_session)
    service.build_timeline(shot.id, force=True)
    if defect == "stale_asset":
        asset.status = "STALE"
    elif defect == "missing_duration":
        asset.duration_seconds = None
    else:
        service.repo.latest_timeline(shot.id).status = "STALE"
    db_session.commit()
    summary = service.get_timeline(shot.id)["data"]["timingSummary"]
    assert not summary["ttsCoverageComplete"]
    assert summary["remainingNonSpeechHoldSeconds"] is None
    assert summary["holdAfterAuthoredFinalPauseSeconds"] is None
    assert not summary["longTailReviewSuggested"]
    if defect != "stale_timeline":
        assert summary["readyTtsEventCount"] == 0
        assert summary["lastTtsFileEndSeconds"] is None
        assert summary["unmeasuredAudioEventIds"] == [event.id]


def test_coverage_uses_bound_ready_asset_not_new_current_asset_and_deduplicates_overlap(db_session):
    shot = _create_shot(db_session)
    event, asset = _create_ready_event(db_session, shot.id, 2)
    second, _ = _create_ready_event(db_session, shot.id, 2)
    second.event_order = 2
    db_session.commit()
    service = AudioDriveService(db_session)
    service.build_timeline(shot.id, force=True)
    timeline = service.repo.latest_timeline(shot.id)
    rows = service.repo.list_timeline_events(timeline.id)
    rows[1].start_time = 1
    rows[1].end_time = 3
    service.repo.add_tts_asset(event.id, status="READY", duration_seconds=99)
    db_session.commit()
    summary = service.get_timeline(shot.id)["data"]["timingSummary"]
    assert summary["measuredTtsDurationSeconds"] == 4
    assert summary["measuredTtsCoverageSeconds"] == 3
    assert summary["lastTtsFileEndSeconds"] == 3
    assert asset.status == "READY" and not asset.is_current
    assert db_session.query(AudioEventTTSAsset).count() == 3


def test_visual_only_and_missing_timeline_are_read_only(db_session):
    shot = _create_shot(db_session, estimated_duration=7)
    service = AudioDriveService(db_session)
    assert service.get_timeline(shot.id) == {"success": True, "data": None}
    service.build_timeline(shot.id, force=True)
    before = deepcopy(json.loads(shot.video_director_plan))
    summary = service.get_timeline(shot.id)["data"]["timingSummary"]
    assert summary["ttsCoverageComplete"]
    assert summary["measuredTtsDurationSeconds"] == summary["measuredTtsCoverageSeconds"] == 0
    assert summary["lastTtsFileEndSeconds"] is None
    assert summary["authoredFinalPauseSeconds"] == 0
    assert summary["remainingNonSpeechHoldSeconds"] == summary["resolvedDurationSeconds"] == 7
    assert not summary["longTailReviewSuggested"]
    assert json.loads(shot.video_director_plan) == before
