import json

from app.api.shots import _build_clip_plan, _build_first_last_clip_plan
from app.models.audio_drive import AudioEventTTSAsset, ShotAudioEvent
from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.services.audio_drive_service import AudioDriveService
from app.services.duration_contract import clip_duration, legal_h3_frame_count, resolved_duration, visual_required_duration
from app.services.execution_window_builder import build_natural_execution_windows
from app.services.file_storage import file_storage


def _create_shot(db_session, estimated_duration=12.0, duration=99):
    novel = Novel(title="Duration Contract Gate B3")
    db_session.add(novel)
    db_session.commit()
    db_session.refresh(novel)

    chapter = Chapter(novel_id=novel.id, number=1, title="Chapter", content="content")
    db_session.add(chapter)
    db_session.commit()
    db_session.refresh(chapter)

    shot = Shot(
        chapter_id=chapter.id,
        index=1,
        description="Shot",
        characters=json.dumps(["A"], ensure_ascii=False),
        scene="房间",
        props=json.dumps([], ensure_ascii=False),
        estimated_duration=estimated_duration,
        duration=duration,
        audio_status="NOT_READY",
    )
    db_session.add(shot)
    db_session.commit()
    db_session.refresh(shot)
    return shot


def _create_ready_event(db_session, shot_id, duration_seconds, pause_after="NONE"):
    event = ShotAudioEvent(
        shot_id=shot_id,
        event_order=1,
        event_type="DIALOGUE",
        voice_owner_name="A",
        visible_speaker_name="A",
        requires_visible_lipsync=True,
        text="hello",
        emotion_prompt="自然",
        pause_after=pause_after,
        tts_status="READY",
    )
    db_session.add(event)
    db_session.commit()
    db_session.refresh(event)
    asset = AudioEventTTSAsset(
        audio_event_id=event.id,
        provider="test",
        audio_url=f"/api/files/{event.id}.wav",
        audio_path=f"/tmp/{event.id}.wav",
        duration_seconds=duration_seconds,
        revision=1,
        is_current=True,
        status="READY",
    )
    db_session.add(asset)
    db_session.commit()
    db_session.refresh(asset)
    return event, asset


def test_short_audio_does_not_shrink_visual_duration(db_session):
    shot = _create_shot(db_session, estimated_duration=12.0, duration=99)
    _create_ready_event(db_session, shot.id, 3.0)

    result = AudioDriveService(db_session).build_timeline(shot.id, force=True)

    timeline = result["data"]
    db_session.refresh(shot)
    assert timeline["audioRequiredDuration"] == 3.0
    assert timeline["totalDuration"] == 12.0
    assert shot.duration == 99


def test_long_audio_extends_resolved_duration(db_session):
    shot = _create_shot(db_session, estimated_duration=12.0, duration=99)
    _create_ready_event(db_session, shot.id, 14.3)

    result = AudioDriveService(db_session).build_timeline(shot.id, force=True)

    assert result["data"]["audioRequiredDuration"] == 14.3
    assert result["data"]["totalDuration"] == 14.3


def test_timeline_rebuild_after_shorter_tts_shrinks_back_to_visual_minimum(db_session):
    shot = _create_shot(db_session, estimated_duration=12.0, duration=99)
    event, old_asset = _create_ready_event(db_session, shot.id, 16.0)
    first = AudioDriveService(db_session).build_timeline(shot.id, force=True)
    assert first["data"]["totalDuration"] == 16.0

    old_asset.is_current = False
    old_asset.status = "STALE"
    new_asset = AudioEventTTSAsset(
        audio_event_id=event.id,
        provider="test",
        audio_url=f"/api/files/{event.id}-rev2.wav",
        audio_path=f"/tmp/{event.id}-rev2.wav",
        duration_seconds=8.0,
        revision=2,
        is_current=True,
        status="READY",
    )
    db_session.add(new_asset)
    shot.duration = 16
    db_session.commit()

    second = AudioDriveService(db_session).build_timeline(shot.id, force=True)

    db_session.refresh(shot)
    assert second["data"]["audioRequiredDuration"] == 8.0
    assert second["data"]["totalDuration"] == 12.0
    assert shot.duration == 16


def test_timeline_rebuild_does_not_use_previous_resolved_as_visual_minimum(db_session):
    shot = _create_shot(db_session, estimated_duration=12.0, duration=30)
    _create_ready_event(db_session, shot.id, 8.0)

    result = AudioDriveService(db_session).build_timeline(shot.id, force=True)

    assert visual_required_duration(shot) == 12.0
    assert result["data"]["totalDuration"] == 12.0


def test_single_first_last_and_multi_use_same_float_clip_duration():
    duration = 4.2
    single_clip = _build_clip_plan(duration, 15)[0]
    first_last_clip = _build_first_last_clip_plan(duration)[0]
    multi_window = build_natural_execution_windows(duration, 15, [])[0]

    assert clip_duration(single_clip["start_time"], single_clip["end_time"]) == 4.2
    assert clip_duration(first_last_clip["start_time"], first_last_clip["end_time"]) == 4.2
    assert clip_duration(multi_window["start_time"], multi_window["end_time"]) == 4.2
    assert multi_window["duration"] == 4.2


def test_drive_and_final_audio_render_use_same_precise_clip_duration(db_session, tmp_path, monkeypatch):
    shot = _create_shot(db_session, estimated_duration=4.2, duration=99)
    timeline = AudioDriveService(db_session).build_timeline(shot.id, force=True)["data"]
    db_session.refresh(shot)
    plan = json.loads(shot.video_director_plan)
    plan["window_plans"] = [{"window_index": 1, "start_time": 0, "end_time": 4.2}]
    shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
    db_session.commit()
    monkeypatch.setattr(file_storage, "base_dir", tmp_path)
    render_durations = []

    def fake_render(_self, _segments, output_path, duration):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"wav")
        render_durations.append(duration)
        return {"success": True}

    monkeypatch.setattr(AudioDriveService, "_render_clip_audio", fake_render)

    result = AudioDriveService(db_session).build_clip_audio(shot.id, 1, force=True)

    assert timeline["totalDuration"] == 4.2
    assert result["success"] is True
    assert render_durations == [4.2, 4.2]


def test_h3_frame_count_uses_single_shared_rule():
    assert legal_h3_frame_count(4.2, 25) == ((int(25 * 4.2) // 8) * 8) + 1
    assert legal_h3_frame_count(14.3, 25) == ((int(25 * 14.3) // 8) * 8) + 1


def test_no_audio_event_resolves_to_estimated_duration(db_session):
    shot = _create_shot(db_session, estimated_duration=12.0, duration=99)

    result = AudioDriveService(db_session).build_timeline(shot.id, force=True)

    timeline = result["data"]
    assert timeline["audioRequiredDuration"] == 0.0
    assert timeline["totalDuration"] == 12.0
    assert resolved_duration(shot, None) == 12.0
