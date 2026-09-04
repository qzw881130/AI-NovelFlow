import json

from app.api.shots import _build_first_last_clip_plan, _build_clip_plan, _preserve_matching_clip_audio_fields
from app.models.novel import Chapter, Novel
from app.models.shot import Shot


READY_AUDIO_FIELDS = {
    "audio_status": "READY",
    "audio_message": "ok",
    "audio_timeline_id": "timeline-1",
    "drive_audio_url": "/api/files/drive.wav",
    "final_audio_url": "/api/files/final.wav",
    "drive_audio_path": "/tmp/drive.wav",
    "final_audio_path": "/tmp/final.wav",
    "clip_audio_manifest_path": "/tmp/manifest.json",
    "clip_audio_duration": 4.0,
    "speaker_timeline": [{"start": 0, "end": 4, "speaker": "A"}],
}


def _create_shot(db_session, plan):
    novel = Novel(title="Video Director Gate B1")
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
        duration=4,
        audio_status="READY",
        video_director_plan=json.dumps(plan, ensure_ascii=False),
    )
    db_session.add(shot)
    db_session.commit()
    db_session.refresh(shot)
    return novel, chapter, shot


def test_preserve_matching_clip_audio_fields_accepts_clip_index_sources():
    previous_clip = {
        "clip_index": 1,
        "start_time": 0,
        "end_time": 4,
        **READY_AUDIO_FIELDS,
    }

    next_clips = _preserve_matching_clip_audio_fields(_build_first_last_clip_plan(4), [previous_clip])

    assert next_clips[0]["clip_index"] == 1
    for key, value in READY_AUDIO_FIELDS.items():
        assert next_clips[0][key] == value


def test_select_first_last_preserves_ready_clip_audio_from_existing_window_plan(client, db_session):
    existing_window = {
        "window_index": 1,
        "start_time": 0,
        "end_time": 4,
        "selected_frame_count": 3,
        "keyframe_indexes": [1, 2, 3],
        **READY_AUDIO_FIELDS,
    }
    plan = {
        "selected_mode": "MULTI_KEYFRAME",
        "workflow_capability": {"max_clip_duration": 15},
        "execution_windows": [existing_window],
        "window_plans": [existing_window],
        "clips": [],
    }
    novel, chapter, shot = _create_shot(db_session, plan)

    response = client.patch(
        f"/api/novels/{novel.id}/chapters/{chapter.id}/shots/{shot.id}/video-director",
        json={"selected_mode": "FIRST_LAST_FRAME", "expectedRevision": 0},
    )

    assert response.status_code == 200
    saved_plan = response.json()["data"]
    assert saved_plan["execution_windows"] == []
    assert saved_plan["window_plans"] == []
    assert len(saved_plan["clips"]) == 1
    for key, value in READY_AUDIO_FIELDS.items():
        assert saved_plan["clips"][0][key] == value


def test_select_single_preserves_ready_clip_audio_from_existing_clip(client, db_session):
    existing_clip = {
        "clip_index": 1,
        "start_time": 0,
        "end_time": 4,
        **READY_AUDIO_FIELDS,
    }
    plan = {
        "selected_mode": "FIRST_LAST_FRAME",
        "workflow_capability": {"max_clip_duration": 15},
        "execution_windows": [],
        "window_plans": [],
        "clips": [existing_clip],
    }
    novel, chapter, shot = _create_shot(db_session, plan)

    response = client.patch(
        f"/api/novels/{novel.id}/chapters/{chapter.id}/shots/{shot.id}/video-director",
        json={"selected_mode": "SINGLE_FRAME", "expectedRevision": 0},
    )

    assert response.status_code == 200
    saved_plan = response.json()["data"]
    assert saved_plan["execution_windows"] == []
    assert saved_plan["window_plans"] == []
    assert len(saved_plan["clips"]) == 1
    for key, value in READY_AUDIO_FIELDS.items():
        assert saved_plan["clips"][0][key] == value


def test_single_clip_plan_does_not_preserve_audio_when_range_changes():
    previous_clip = {
        "clip_index": 1,
        "start_time": 0,
        "end_time": 3,
        **READY_AUDIO_FIELDS,
    }

    next_clips = _preserve_matching_clip_audio_fields(_build_clip_plan(4, 15), [previous_clip])

    assert "audio_status" not in next_clips[0]
    assert "drive_audio_url" not in next_clips[0]
