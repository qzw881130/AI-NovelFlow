import json

from app.models.audio_drive import AudioEventTTSAsset, ShotAudioEvent, ShotAudioTimeline, ShotAudioTimelineEvent
from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.task import Task


def _create_shot(db_session):
    novel = Novel(title="AudioDrive Gate A")
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
        description="原始描述",
        characters=json.dumps(["A", "B"], ensure_ascii=False),
        scene="房间",
        props=json.dumps([], ensure_ascii=False),
        duration=4,
        audio_status="READY",
        video_director_plan=json.dumps({"clips": [{"window_index": 1, "audio_status": "READY"}]}, ensure_ascii=False),
    )
    db_session.add(shot)
    db_session.commit()
    db_session.refresh(shot)
    return novel, chapter, shot


def _create_event(db_session, shot_id, order=1, text="你好", speaker="A"):
    event = ShotAudioEvent(
        shot_id=shot_id,
        event_order=order,
        event_type="DIALOGUE",
        voice_owner_name=speaker,
        visible_speaker_name=speaker,
        requires_visible_lipsync=True,
        text=text,
        emotion_prompt="自然",
        pause_after="NONE",
        tts_status="READY",
        text_hash=f"text-hash-{order}",
    )
    db_session.add(event)
    db_session.commit()
    db_session.refresh(event)
    return event


def _create_asset(db_session, event, revision=1):
    asset = AudioEventTTSAsset(
        audio_event_id=event.id,
        provider="test",
        audio_url=f"/api/files/{event.id}.wav",
        audio_path=f"/tmp/{event.id}.wav",
        duration_seconds=1.2,
        content_hash=f"audio-hash-{event.event_order}",
        text_hash=event.text_hash,
        revision=revision,
        is_current=True,
        status="READY",
    )
    db_session.add(asset)
    db_session.commit()
    db_session.refresh(asset)
    return asset


def _event_payload(event, **overrides):
    payload = {
        "id": event.id,
        "order": event.event_order,
        "type": event.event_type,
        "voiceOwnerName": event.voice_owner_name,
        "visibleSpeakerName": event.visible_speaker_name,
        "requiresVisibleLipsync": event.requires_visible_lipsync,
        "text": event.text,
        "emotionPrompt": event.emotion_prompt,
        "pauseAfter": event.pause_after,
    }
    payload.update(overrides)
    return payload


def _batch_save(client, novel_id, chapter_id, shot_id, **payload):
    response = client.patch(
        f"/api/novels/{novel_id}/chapters/{chapter_id}/shots/batch",
        json={"shots": [{"id": shot_id, **payload}]},
    )
    assert response.status_code == 200
    return response.json()


def test_shot_only_save_preserves_audio_event_tts_asset_and_revision(client, db_session):
    novel, chapter, shot = _create_shot(db_session)
    event = _create_event(db_session, shot.id)
    asset = _create_asset(db_session, event, revision=3)

    _batch_save(
        client,
        novel.id,
        chapter.id,
        shot.id,
        description="仅修改描述",
        scene="新房间",
        audio_events=[_event_payload(event)],
    )

    saved_event = db_session.query(ShotAudioEvent).filter(ShotAudioEvent.shot_id == shot.id).one()
    saved_asset = db_session.query(AudioEventTTSAsset).filter(AudioEventTTSAsset.id == asset.id).one()
    db_session.refresh(shot)
    assert saved_event.id == event.id
    assert saved_event.tts_status == "READY"
    assert shot.audio_status == "READY"
    assert saved_asset.audio_event_id == event.id
    assert saved_asset.revision == 3
    assert saved_asset.is_current is True
    assert saved_asset.status == "READY"


def test_tts_affecting_event_change_keeps_id_but_stales_tts_asset(client, db_session):
    novel, chapter, shot = _create_shot(db_session)
    event = _create_event(db_session, shot.id)
    asset = _create_asset(db_session, event)

    _batch_save(
        client,
        novel.id,
        chapter.id,
        shot.id,
        audio_events=[_event_payload(event, text="新的台词", emotionPrompt="紧张")],
    )

    saved_event = db_session.query(ShotAudioEvent).filter(ShotAudioEvent.id == event.id).one()
    saved_asset = db_session.query(AudioEventTTSAsset).filter(AudioEventTTSAsset.id == asset.id).one()
    assert saved_event.tts_status == "STALE"
    assert saved_event.text_hash is None
    assert saved_asset.revision == 1
    assert saved_asset.is_current is False
    assert saved_asset.status == "STALE"


def test_lipsync_only_change_keeps_tts_ready_but_stales_timeline_and_clip_audio(client, db_session):
    novel, chapter, shot = _create_shot(db_session)
    event = _create_event(db_session, shot.id)
    asset = _create_asset(db_session, event)
    timeline = ShotAudioTimeline(shot_id=shot.id, revision=1, total_duration=1.2, status="READY")
    db_session.add(timeline)
    db_session.commit()

    _batch_save(
        client,
        novel.id,
        chapter.id,
        shot.id,
        audio_events=[_event_payload(event, visibleSpeakerName="B", requiresVisibleLipsync=False)],
    )

    db_session.refresh(shot)
    db_session.refresh(timeline)
    saved_event = db_session.query(ShotAudioEvent).filter(ShotAudioEvent.id == event.id).one()
    saved_asset = db_session.query(AudioEventTTSAsset).filter(AudioEventTTSAsset.id == asset.id).one()
    plan = json.loads(shot.video_director_plan)
    assert saved_event.tts_status == "READY"
    assert saved_asset.is_current is True
    assert saved_asset.status == "READY"
    assert shot.audio_status == "STALE"
    assert timeline.status == "STALE"
    assert plan["clips"][0]["audio_status"] == "STALE"


def test_adding_event_only_creates_one_new_stable_id(client, db_session):
    novel, chapter, shot = _create_shot(db_session)
    event = _create_event(db_session, shot.id)
    asset = _create_asset(db_session, event)

    _batch_save(
        client,
        novel.id,
        chapter.id,
        shot.id,
        audio_events=[
            _event_payload(event),
            {
                "id": "local-123",
                "order": 2,
                "type": "NARRATION",
                "voiceOwnerName": "旁白",
                "visibleSpeakerName": None,
                "requiresVisibleLipsync": False,
                "text": "新的旁白",
                "emotionPrompt": "自然",
                "pauseAfter": "NONE",
            },
        ],
    )

    events = db_session.query(ShotAudioEvent).filter(ShotAudioEvent.shot_id == shot.id).order_by(ShotAudioEvent.event_order).all()
    saved_asset = db_session.query(AudioEventTTSAsset).filter(AudioEventTTSAsset.id == asset.id).one()
    assert [item.id for item in events][0] == event.id
    assert len(events) == 2
    assert not events[1].id.startswith("local-")
    assert saved_asset.audio_event_id == event.id
    assert saved_asset.is_current is True


def test_deleting_middle_event_preserves_other_events_and_removes_timeline_reference(client, db_session):
    novel, chapter, shot = _create_shot(db_session)
    first = _create_event(db_session, shot.id, order=1, text="一")
    middle = _create_event(db_session, shot.id, order=2, text="二")
    last = _create_event(db_session, shot.id, order=3, text="三")
    first_asset = _create_asset(db_session, first)
    last_asset = _create_asset(db_session, last)
    timeline = ShotAudioTimeline(shot_id=shot.id, revision=1, total_duration=3.6, status="READY")
    db_session.add(timeline)
    db_session.commit()
    db_session.add(ShotAudioTimelineEvent(timeline_id=timeline.id, audio_event_id=middle.id, event_order=2, start_time=1.2, end_time=2.4, event_type="DIALOGUE", voice_owner_name="A"))
    db_session.commit()

    _batch_save(
        client,
        novel.id,
        chapter.id,
        shot.id,
        audio_events=[_event_payload(first), _event_payload(last, order=2)],
    )

    events = db_session.query(ShotAudioEvent).filter(ShotAudioEvent.shot_id == shot.id).order_by(ShotAudioEvent.event_order).all()
    assert [item.id for item in events] == [first.id, last.id]
    assert db_session.query(ShotAudioTimelineEvent).filter(ShotAudioTimelineEvent.audio_event_id == middle.id).count() == 0
    assert db_session.query(AudioEventTTSAsset).filter(AudioEventTTSAsset.id == first_asset.id).one().is_current is True
    assert db_session.query(AudioEventTTSAsset).filter(AudioEventTTSAsset.id == last_asset.id).one().is_current is True


def test_empty_audio_events_deletes_last_event_assets_timeline_refs_and_cancels_tasks(client, db_session):
    novel, chapter, shot = _create_shot(db_session)
    event = _create_event(db_session, shot.id)
    asset = _create_asset(db_session, event)
    timeline = ShotAudioTimeline(shot_id=shot.id, revision=1, total_duration=1.2, status="READY")
    db_session.add(timeline)
    db_session.commit()
    timeline_event = ShotAudioTimelineEvent(timeline_id=timeline.id, audio_event_id=event.id, tts_asset_id=asset.id, event_order=1, start_time=0, end_time=1.2, event_type="DIALOGUE", voice_owner_name="A")
    task = Task(type="audio_event_tts", status="pending", name="TTS", shot_id=shot.id, metadata_json=json.dumps({"audio_event_id": event.id}))
    db_session.add_all([timeline_event, task])
    db_session.commit()

    _batch_save(client, novel.id, chapter.id, shot.id, audio_events=[])

    db_session.refresh(task)
    db_session.refresh(timeline)
    assert db_session.query(ShotAudioEvent).filter(ShotAudioEvent.shot_id == shot.id).count() == 0
    assert db_session.query(AudioEventTTSAsset).filter(AudioEventTTSAsset.id == asset.id).count() == 0
    assert db_session.query(ShotAudioTimelineEvent).filter(ShotAudioTimelineEvent.audio_event_id == event.id).count() == 0
    assert task.status == "cancelled"
    assert timeline.status == "STALE"
