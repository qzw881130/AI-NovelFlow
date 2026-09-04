import json

from app.models.audio_drive import AudioEventTTSAsset, ShotAudioEvent, ShotAudioTimeline, ShotAudioTimelineEvent
from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.services.audio_drive_service import AudioDriveService
from app.services.file_storage import file_storage


def _create_shot_with_timeline(db_session, tmp_path, monkeypatch, duration=4.0):
    novel = Novel(title="AudioDrive Gate C2")
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
        estimated_duration=duration,
        duration=int(duration),
        audio_status="READY",
        video_director_plan=json.dumps({"window_plans": [{"window_index": 1, "start_time": 0, "end_time": duration}]}, ensure_ascii=False),
    )
    db_session.add(shot)
    db_session.commit()
    db_session.refresh(shot)
    timeline = ShotAudioTimeline(shot_id=shot.id, revision=1, total_duration=duration, audio_required_duration=duration, status="READY", generated_from_hash="hash-1")
    db_session.add(timeline)
    db_session.commit()
    db_session.refresh(timeline)
    monkeypatch.setattr(file_storage, "base_dir", tmp_path)
    return shot, timeline


def _add_timeline_event(db_session, timeline, shot, *, visible=True, asset_status="READY", create_file=True, include_asset=True):
    event = ShotAudioEvent(
        shot_id=shot.id,
        event_order=1,
        event_type="DIALOGUE" if visible else "NARRATION",
        voice_owner_name="A" if visible else "旁白",
        visible_speaker_name="A" if visible else None,
        requires_visible_lipsync=visible,
        text="hello",
        emotion_prompt="自然",
        pause_after="NONE",
        tts_status="READY",
    )
    db_session.add(event)
    db_session.commit()
    db_session.refresh(event)

    asset = None
    if include_asset:
        source_path = file_storage.base_dir / f"source-{event.id}.wav"
        if create_file:
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_bytes(b"wav")
        asset = AudioEventTTSAsset(
            audio_event_id=event.id,
            provider="test",
            audio_url=f"/api/files/source-{event.id}.wav",
            audio_path=str(source_path),
            duration_seconds=4,
            revision=1,
            is_current=True,
            status=asset_status,
        )
        db_session.add(asset)
        db_session.commit()
        db_session.refresh(asset)

    timeline_event = ShotAudioTimelineEvent(
        timeline_id=timeline.id,
        audio_event_id=event.id,
        event_order=1,
        start_time=0,
        end_time=4,
        event_type=event.event_type,
        voice_owner_name=event.voice_owner_name,
        visible_speaker_name=event.visible_speaker_name,
        requires_visible_lipsync=event.requires_visible_lipsync,
        tts_asset_id=asset.id if asset else None,
    )
    db_session.add(timeline_event)
    db_session.commit()
    return event, asset


def _fake_render(monkeypatch):
    calls = []

    def fake_render(_self, segments, output_path, duration):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"wav")
        calls.append({"segments": segments, "duration": duration})
        return {"success": True}

    monkeypatch.setattr(AudioDriveService, "_render_clip_audio", fake_render)
    return calls


def test_dialogue_ready_asset_with_existing_wav_builds_clip_audio(db_session, tmp_path, monkeypatch):
    shot, timeline = _create_shot_with_timeline(db_session, tmp_path, monkeypatch)
    _add_timeline_event(db_session, timeline, shot, visible=True, create_file=True)
    calls = _fake_render(monkeypatch)

    result = AudioDriveService(db_session).build_clip_audio(shot.id, 1, force=True)

    assert result["success"] is True
    assert len(calls) == 2
    assert len(calls[0]["segments"]) == 1
    assert len(calls[1]["segments"]) == 1


def test_ready_asset_with_missing_physical_wav_fails_instead_of_silence(db_session, tmp_path, monkeypatch):
    shot, timeline = _create_shot_with_timeline(db_session, tmp_path, monkeypatch)
    _add_timeline_event(db_session, timeline, shot, visible=True, create_file=False)
    calls = _fake_render(monkeypatch)

    result = AudioDriveService(db_session).build_clip_audio(shot.id, 1, force=True)

    assert result["success"] is False
    assert result["status_code"] == 400
    assert result["data"]["missingSegments"][0]["reason"] == "tts_file_missing"
    assert calls == []


def test_ready_event_without_current_tts_asset_fails_instead_of_silence(db_session, tmp_path, monkeypatch):
    shot, timeline = _create_shot_with_timeline(db_session, tmp_path, monkeypatch)
    _add_timeline_event(db_session, timeline, shot, visible=True, include_asset=False)
    calls = _fake_render(monkeypatch)

    result = AudioDriveService(db_session).build_clip_audio(shot.id, 1, force=True)

    assert result["success"] is False
    assert result["data"]["missingSegments"][0]["reason"] == "missing_tts_asset_id"
    assert calls == []


def test_stale_tts_asset_fails_instead_of_silence(db_session, tmp_path, monkeypatch):
    shot, timeline = _create_shot_with_timeline(db_session, tmp_path, monkeypatch)
    _add_timeline_event(db_session, timeline, shot, visible=True, asset_status="STALE", create_file=True)
    calls = _fake_render(monkeypatch)

    result = AudioDriveService(db_session).build_clip_audio(shot.id, 1, force=True)

    assert result["success"] is False
    assert result["data"]["missingSegments"][0]["reason"] == "tts_asset_not_ready"
    assert calls == []


def test_narration_allows_drive_silence_but_requires_final_audio(db_session, tmp_path, monkeypatch):
    shot, timeline = _create_shot_with_timeline(db_session, tmp_path, monkeypatch)
    _add_timeline_event(db_session, timeline, shot, visible=False, create_file=True)
    calls = _fake_render(monkeypatch)

    result = AudioDriveService(db_session).build_clip_audio(shot.id, 1, force=True)

    assert result["success"] is True
    assert len(calls) == 2
    assert len(calls[0]["segments"]) == 1
    assert calls[1]["segments"] == []


def test_window_with_no_audio_events_allows_two_silent_tracks(db_session, tmp_path, monkeypatch):
    shot, _timeline = _create_shot_with_timeline(db_session, tmp_path, monkeypatch)
    calls = _fake_render(monkeypatch)

    result = AudioDriveService(db_session).build_clip_audio(shot.id, 1, force=True)

    assert result["success"] is True
    assert len(calls) == 2
    assert calls[0]["segments"] == []
    assert calls[1]["segments"] == []
