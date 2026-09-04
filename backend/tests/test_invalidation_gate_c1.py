import json

from app.models.audio_drive import AudioEventTTSAsset, ShotAudioEvent, ShotAudioTimeline
from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.services.audio_drive_service import AudioDriveService


def _create_completed_shot(db_session):
    novel = Novel(title="Invalidation Gate C1")
    db_session.add(novel)
    db_session.commit()
    db_session.refresh(novel)

    chapter = Chapter(novel_id=novel.id, number=1, title="Chapter", content="content", final_video="/api/files/final.mp4")
    db_session.add(chapter)
    db_session.commit()
    db_session.refresh(chapter)

    plan = {
        "selected_mode": "SINGLE_FRAME",
        "audio_timeline": {"id": "old-timeline", "revision": 1, "audio_required_duration": 4, "resolved_duration": 4},
        "clips": [
            {
                "clip_index": 1,
                "start_time": 0,
                "end_time": 4,
                "audio_status": "READY",
                "audio_timeline_id": "old-timeline",
                "audio_timeline_revision": 1,
                "audio_timeline_hash": "old-hash",
                "speaker_timeline": [{"start_time": 0, "end_time": 4, "visible_speaker": "A"}],
                "drive_audio_url": "/api/files/drive.wav",
                "final_audio_url": "/api/files/final.wav",
                "clip_audio_duration": 4,
                "prompt_text": "old prompt",
                "prompt_id": "prompt-1",
                "video_url": "/api/files/clip.mp4",
                "local_path": "/tmp/clip.mp4",
                "generated_at": "2026-01-01T00:00:00",
                "status": "COMPLETED",
            }
        ],
        "merged_video_url": "/api/files/shot-merged.mp4",
        "merged_at": "2026-01-01T00:00:00",
    }
    shot = Shot(
        chapter_id=chapter.id,
        index=1,
        description="Shot",
        characters=json.dumps(["A", "B"], ensure_ascii=False),
        scene="房间",
        props=json.dumps([], ensure_ascii=False),
        estimated_duration=4,
        duration=4,
        audio_status="READY",
        video_url="/api/files/shot.mp4",
        video_status="completed",
        video_task_id="video-task-1",
        video_director_plan=json.dumps(plan, ensure_ascii=False),
    )
    db_session.add(shot)
    db_session.commit()
    db_session.refresh(shot)
    timeline = ShotAudioTimeline(shot_id=shot.id, revision=1, total_duration=4, audio_required_duration=4, status="READY", generated_from_hash="old-hash")
    db_session.add(timeline)
    db_session.commit()
    db_session.refresh(timeline)
    return novel, chapter, shot, timeline


def _create_ready_event(db_session, shot_id):
    event = ShotAudioEvent(
        shot_id=shot_id,
        event_order=1,
        event_type="DIALOGUE",
        voice_owner_name="A",
        visible_speaker_name="A",
        requires_visible_lipsync=True,
        text="hello",
        emotion_prompt="自然",
        pause_after="NONE",
        tts_status="READY",
        text_hash="text-hash",
    )
    db_session.add(event)
    db_session.commit()
    db_session.refresh(event)
    asset = AudioEventTTSAsset(
        audio_event_id=event.id,
        provider="test",
        audio_url=f"/api/files/{event.id}.wav",
        audio_path=f"/tmp/{event.id}.wav",
        duration_seconds=4,
        revision=1,
        is_current=True,
        status="READY",
    )
    db_session.add(asset)
    db_session.commit()
    db_session.refresh(asset)
    return event, asset


def test_speaker_binding_change_invalidates_prompt_video_and_chapter_final_but_not_tts(client, db_session):
    novel, chapter, shot, timeline = _create_completed_shot(db_session)
    event, asset = _create_ready_event(db_session, shot.id)

    response = client.patch(
        f"/api/audio-events/{event.id}",
        json={"visibleSpeakerName": "B"},
    )

    assert response.status_code == 200
    db_session.refresh(shot)
    db_session.refresh(chapter)
    db_session.refresh(timeline)
    db_session.refresh(event)
    db_session.refresh(asset)
    plan = json.loads(shot.video_director_plan)
    clip = plan["clips"][0]
    assert event.tts_status == "READY"
    assert asset.is_current is True
    assert shot.audio_status == "STALE"
    assert timeline.status == "STALE"
    assert shot.video_url is None
    assert shot.video_status == "pending"
    assert shot.video_task_id is None
    assert chapter.final_video is None
    assert plan["invalidation_level"] == "SPEAKER_BINDING_CHANGED"
    assert "merged_video_url" not in plan
    assert clip["audio_status"] == "STALE"
    assert clip["status"] == "PENDING"
    assert "prompt_text" not in clip
    assert "video_url" not in clip
    assert "drive_audio_url" not in clip


def test_timeline_rebuild_invalidates_old_video_but_keeps_new_timeline_ready(db_session):
    _, chapter, shot, old_timeline = _create_completed_shot(db_session)
    _create_ready_event(db_session, shot.id)

    result = AudioDriveService(db_session).build_timeline(shot.id, force=True)

    assert result["success"] is True
    db_session.refresh(shot)
    db_session.refresh(chapter)
    db_session.refresh(old_timeline)
    latest = db_session.query(ShotAudioTimeline).filter(ShotAudioTimeline.shot_id == shot.id).order_by(ShotAudioTimeline.revision.desc()).first()
    plan = json.loads(shot.video_director_plan)
    clip = plan["clips"][0]
    assert latest.status == "READY"
    assert latest.revision == 2
    assert shot.audio_status == "READY"
    assert shot.video_url is None
    assert shot.video_status == "pending"
    assert chapter.final_video is None
    assert plan["audio_timeline"]["id"] == latest.id
    assert plan["invalidation_level"] == "AUDIO_TIMING_CHANGED"
    assert clip["audio_status"] == "STALE"
    assert "prompt_text" not in clip
    assert "video_url" not in clip


def test_tts_affecting_change_invalidates_video_and_chapter_final(client, db_session):
    _, chapter, shot, timeline = _create_completed_shot(db_session)
    event, asset = _create_ready_event(db_session, shot.id)

    response = client.patch(
        f"/api/audio-events/{event.id}",
        json={"text": "changed"},
    )

    assert response.status_code == 200
    db_session.refresh(shot)
    db_session.refresh(chapter)
    db_session.refresh(timeline)
    db_session.refresh(event)
    db_session.refresh(asset)
    plan = json.loads(shot.video_director_plan)
    assert event.tts_status == "STALE"
    assert asset.is_current is False
    assert asset.status == "STALE"
    assert timeline.status == "STALE"
    assert shot.video_url is None
    assert shot.video_status == "pending"
    assert chapter.final_video is None
    assert plan["invalidation_level"] == "AUDIO_TIMING_CHANGED"
    assert plan["keyframe_planning_status"] == "STALE"
