import json

from app.api.shots import _assert_audio_drive_ready_for_video
from app.models.audio_drive import AudioEventTTSAsset, ShotAudioEvent
from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.workflow import Workflow
from app.services.audio_drive_service import AudioDriveService
from app.services.file_storage import file_storage


def _create_shot(db_session, *, characters=None, estimated_duration=5):
    novel = Novel(title="E1 Integration")
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
        characters=json.dumps(characters or [], ensure_ascii=False),
        props=json.dumps([], ensure_ascii=False),
        estimated_duration=estimated_duration,
        duration=99,
        image_url="/api/files/shot.png",
        video_director_plan=json.dumps({}, ensure_ascii=False),
    )
    db_session.add(shot)
    db_session.commit()
    db_session.refresh(shot)
    return novel, chapter, shot


def _workflow(workflow_type: str) -> Workflow:
    mapping = {
        "prompt_node_id": "prompt",
        "video_save_node_id": "save",
        "reference_image_node_id": "ref1",
        "max_side_node_id": "max_side",
        "drive_audio_node_id": "drive_audio",
        "final_audio_node_id": "final_audio",
    }
    if workflow_type == "first_last_video":
        mapping.update({"first_image_node_id": "first", "last_image_node_id": "last", "frame_count_node_id": "frames"})
    if workflow_type == "three_frame_video":
        mapping.update({"keyframe_node_1": "ref2", "keyframe_node_2": "ref3"})
    if workflow_type == "four_frame_video":
        mapping.update({"keyframe_node_1": "ref2", "keyframe_node_2": "ref3", "keyframe_node_3": "ref4"})
    return Workflow(name=workflow_type, type=workflow_type, workflow_json="{}", node_mapping=json.dumps(mapping), is_active=True)


def _fake_clip_audio_render(monkeypatch, tmp_path):
    monkeypatch.setattr(file_storage, "base_dir", tmp_path)
    calls = []

    def fake_render(_self, segments, output_path, duration):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"wav")
        calls.append({"segments": segments, "output_path": str(output_path), "duration": duration})
        return {"success": True}

    monkeypatch.setattr(AudioDriveService, "_render_clip_audio", fake_render)
    return calls


def _add_ready_tts_assets(db_session, tmp_path, shot_id, durations):
    events = db_session.query(ShotAudioEvent).filter(ShotAudioEvent.shot_id == shot_id).order_by(ShotAudioEvent.event_order).all()
    assert len(events) == len(durations)
    for event, duration in zip(events, durations):
        source_path = tmp_path / f"source-{event.id}.wav"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(b"wav")
        event.tts_status = "READY"
        db_session.add(AudioEventTTSAsset(
            audio_event_id=event.id,
            provider="e1",
            audio_url=f"/api/files/source-{event.id}.wav",
            audio_path=str(source_path),
            duration_seconds=duration,
            revision=1,
            is_current=True,
            status="READY",
        ))
    db_session.commit()
    return events


def _sync_events(client, novel_id, chapter_id, shot_id, events):
    response = client.patch(f"/api/novels/{novel_id}/chapters/{chapter_id}/shots/batch", json={
        "shots": [{"id": shot_id, "audio_events": events}],
    })
    assert response.status_code == 200, response.text


def _build_audio_chain(client, shot_id, max_clip_duration=15):
    timeline_response = client.post(f"/api/shots/{shot_id}/audio-timeline/build", json={"force": True})
    assert timeline_response.status_code == 200, timeline_response.text
    windows_response = client.post(f"/api/shots/{shot_id}/video/execution-windows/build", json={"maxClipDuration": max_clip_duration})
    assert windows_response.status_code == 200, windows_response.text
    clip_response = client.post(f"/api/shots/{shot_id}/video-director/clips/1/audio/build", json={"force": True})
    assert clip_response.status_code == 200, clip_response.text
    return timeline_response.json()["data"], windows_response.json()["data"], clip_response.json()["data"]


def test_e1_visible_a_b_a_chain_builds_timeline_clip_audio_and_video_preflights(client, db_session, tmp_path, monkeypatch):
    novel, chapter, shot = _create_shot(db_session, characters=["A", "B"], estimated_duration=5)
    _sync_events(client, novel.id, chapter.id, shot.id, [
        {"order": 1, "type": "DIALOGUE", "voiceOwnerName": "A", "visibleSpeakerName": "A", "requiresVisibleLipsync": True, "text": "a"},
        {"order": 2, "type": "DIALOGUE", "voiceOwnerName": "B", "visibleSpeakerName": "B", "requiresVisibleLipsync": True, "text": "b"},
        {"order": 3, "type": "DIALOGUE", "voiceOwnerName": "A", "visibleSpeakerName": "A", "requiresVisibleLipsync": True, "text": "a2"},
    ])
    _add_ready_tts_assets(db_session, tmp_path, shot.id, [1.0, 1.2, 1.1])
    render_calls = _fake_clip_audio_render(monkeypatch, tmp_path)

    timeline, windows, clip_audio = _build_audio_chain(client, shot.id)

    db_session.refresh(shot)
    plan = json.loads(shot.video_director_plan)
    clip = plan["window_plans"][0]
    assert timeline["audioRequiredDuration"] == 3.3
    assert timeline["totalDuration"] == 5.0
    assert windows["executionWindows"][0]["end_time"] == 5.0
    assert clip_audio["audioStatus"] == "READY"
    assert [segment["visible_speaker"] for segment in clip["speaker_timeline"] if segment["visible_speaker"] != "NONE"] == ["A", "B", "A"]
    assert len(render_calls) == 2
    assert len(render_calls[0]["segments"]) == 3
    assert len(render_calls[1]["segments"]) == 3

    _assert_audio_drive_ready_for_video(shot, plan, _workflow("three_frame_video"), {1})
    _assert_audio_drive_ready_for_video(shot, plan, _workflow("four_frame_video"), {1})
    single_plan = {**plan, "clips": [{"clip_index": 1, **clip}], "window_plans": [], "execution_windows": []}
    _assert_audio_drive_ready_for_video(shot, single_plan, _workflow("video"), {1})
    first_last_plan = {**plan, "clips": [{"clip_index": 1, **clip}], "window_plans": [], "execution_windows": []}
    _assert_audio_drive_ready_for_video(shot, first_last_plan, _workflow("first_last_video"), {1})

    event_b = db_session.query(ShotAudioEvent).filter(ShotAudioEvent.shot_id == shot.id, ShotAudioEvent.voice_owner_name == "B").one()
    patch_response = client.patch(f"/api/audio-events/{event_b.id}", json={"visibleSpeakerName": "A"})
    assert patch_response.status_code == 200
    db_session.refresh(shot)
    stale_plan = json.loads(shot.video_director_plan)
    assert shot.audio_status == "STALE"
    assert stale_plan["window_plans"][0]["audio_status"] == "STALE"


def test_e1_narration_builds_final_audio_with_drive_silence_and_none_speaker_timeline(client, db_session, tmp_path, monkeypatch):
    novel, chapter, shot = _create_shot(db_session, characters=["A"], estimated_duration=4)
    _sync_events(client, novel.id, chapter.id, shot.id, [
        {"order": 1, "type": "NARRATION", "voiceOwnerName": "旁白", "visibleSpeakerName": None, "requiresVisibleLipsync": False, "text": "narration"},
    ])
    _add_ready_tts_assets(db_session, tmp_path, shot.id, [2.0])
    render_calls = _fake_clip_audio_render(monkeypatch, tmp_path)

    timeline, _windows, _clip_audio = _build_audio_chain(client, shot.id)

    db_session.refresh(shot)
    plan = json.loads(shot.video_director_plan)
    clip = plan["window_plans"][0]
    assert timeline["audioRequiredDuration"] == 2.0
    assert timeline["totalDuration"] == 4.0
    assert clip["speaker_timeline"] == [{"start_time": 0.0, "end_time": 4.0, "visible_speaker": "NONE"}]
    assert len(render_calls) == 2
    assert len(render_calls[0]["segments"]) == 1
    assert render_calls[1]["segments"] == []
    _assert_audio_drive_ready_for_video(shot, plan, _workflow("video"), {1})
