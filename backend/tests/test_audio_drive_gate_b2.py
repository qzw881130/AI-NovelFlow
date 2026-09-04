import json

import pytest
from fastapi import HTTPException

from app.api.shots import _assert_audio_drive_ready_for_video
from app.models.audio_drive import ShotAudioTimeline
from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.workflow import Workflow
from app.services.audio_drive_service import AudioDriveService
from app.services.file_storage import file_storage
from app.services.shot_video_service import _resolve_audio_drive_for_h3


def _create_shot(db_session, plan=None, audio_status="READY"):
    novel = Novel(title="AudioDrive Gate B2")
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
        audio_status=audio_status,
        video_director_plan=json.dumps(plan or {}, ensure_ascii=False),
    )
    db_session.add(shot)
    db_session.commit()
    db_session.refresh(shot)
    return novel, chapter, shot


def _create_timeline(db_session, shot_id, revision=1, status="READY", source_hash="hash-1"):
    timeline = ShotAudioTimeline(
        shot_id=shot_id,
        revision=revision,
        total_duration=4,
        status=status,
        generated_from_hash=source_hash,
        audio_summary_json=json.dumps({"event_count": 0}),
    )
    db_session.add(timeline)
    db_session.commit()
    db_session.refresh(timeline)
    return timeline


def _workflow_requires_audio():
    return Workflow(
        name="H3 audio",
        type="video",
        workflow_json="{}",
        node_mapping=json.dumps({"drive_audio_node_id": "1", "final_audio_node_id": "2"}),
    )


def _plan_with_clip(timeline, drive_path, final_path, revision=None, timeline_id=None, source_hash=None):
    timeline_id = timeline_id or timeline.id
    revision = timeline.revision if revision is None else revision
    source_hash = timeline.generated_from_hash if source_hash is None else source_hash
    return {
        "audio_timeline": {
            "id": timeline.id,
            "revision": timeline.revision,
            "source_hash": timeline.generated_from_hash,
            "resolved_duration": 4,
        },
        "clips": [
            {
                "clip_index": 1,
                "start_time": 0,
                "end_time": 4,
                "audio_status": "READY",
                "audio_timeline_id": timeline_id,
                "audio_timeline_revision": revision,
                "audio_timeline_hash": source_hash,
                "drive_audio_path": str(drive_path),
                "final_audio_path": str(final_path),
                "clip_audio_duration": 4,
                "speaker_timeline": [],
            }
        ],
    }


def _audio_files(tmp_path):
    drive_path = tmp_path / "drive.wav"
    final_path = tmp_path / "final.wav"
    drive_path.write_bytes(b"drive")
    final_path.write_bytes(b"final")
    return drive_path, final_path


def test_video_precheck_accepts_clip_audio_bound_to_latest_ready_timeline(db_session, tmp_path):
    _, _, shot = _create_shot(db_session)
    timeline = _create_timeline(db_session, shot.id, revision=1, source_hash="hash-1")
    drive_path, final_path = _audio_files(tmp_path)
    plan = _plan_with_clip(timeline, drive_path, final_path)
    shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
    db_session.commit()

    _assert_audio_drive_ready_for_video(shot, plan, _workflow_requires_audio(), {1})


def test_video_precheck_rejects_old_clip_audio_after_timeline_revision_changes(db_session, tmp_path):
    _, _, shot = _create_shot(db_session)
    old_timeline = _create_timeline(db_session, shot.id, revision=1, source_hash="hash-1")
    latest_timeline = _create_timeline(db_session, shot.id, revision=2, source_hash="hash-2")
    drive_path, final_path = _audio_files(tmp_path)
    plan = _plan_with_clip(latest_timeline, drive_path, final_path, revision=old_timeline.revision, source_hash=old_timeline.generated_from_hash)
    shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
    db_session.commit()

    with pytest.raises(HTTPException) as exc:
        _assert_audio_drive_ready_for_video(shot, plan, _workflow_requires_audio(), {1})
    assert "不匹配" in exc.value.detail


def test_video_precheck_rejects_old_clip_audio_after_timeline_id_changes(db_session, tmp_path):
    _, _, shot = _create_shot(db_session)
    old_timeline = _create_timeline(db_session, shot.id, revision=1, source_hash="hash-1")
    latest_timeline = _create_timeline(db_session, shot.id, revision=2, source_hash="hash-2")
    drive_path, final_path = _audio_files(tmp_path)
    plan = _plan_with_clip(latest_timeline, drive_path, final_path, timeline_id=old_timeline.id)
    shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
    db_session.commit()

    with pytest.raises(HTTPException) as exc:
        _assert_audio_drive_ready_for_video(shot, plan, _workflow_requires_audio(), {1})
    assert "不匹配" in exc.value.detail


def test_video_precheck_rejects_when_latest_timeline_is_stale(db_session, tmp_path):
    _, _, shot = _create_shot(db_session)
    timeline = _create_timeline(db_session, shot.id, revision=1, status="STALE", source_hash="hash-1")
    drive_path, final_path = _audio_files(tmp_path)
    plan = _plan_with_clip(timeline, drive_path, final_path)
    shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
    db_session.commit()

    with pytest.raises(HTTPException) as exc:
        _assert_audio_drive_ready_for_video(shot, plan, _workflow_requires_audio(), {1})
    assert "Audio Timeline 未 READY" in exc.value.detail


def test_rebuilding_clip_audio_binds_latest_timeline_revision_and_restores_ready(db_session, tmp_path, monkeypatch):
    timeline = None
    _, _, shot = _create_shot(db_session, plan={"window_plans": [{"window_index": 1, "start_time": 0, "end_time": 4}]})
    timeline = _create_timeline(db_session, shot.id, revision=2, source_hash="hash-2")
    monkeypatch.setattr(file_storage, "base_dir", tmp_path)

    def fake_render(_self, _segments, output_path, _duration):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"wav")
        return {"success": True}

    monkeypatch.setattr(AudioDriveService, "_render_clip_audio", fake_render)

    result = AudioDriveService(db_session).build_clip_audio(shot.id, 1, force=True)

    assert result["success"] is True
    db_session.refresh(shot)
    plan = json.loads(shot.video_director_plan)
    clip = plan["window_plans"][0]
    assert clip["audio_status"] == "READY"
    assert clip["audio_timeline_id"] == timeline.id
    assert clip["audio_timeline_revision"] == 2
    assert clip["audio_timeline_hash"] == "hash-2"
    _assert_audio_drive_ready_for_video(shot, plan, _workflow_requires_audio(), {1})


def test_h3_audio_resolver_rejects_clip_audio_with_stale_timeline_binding(tmp_path):
    drive_path, final_path = _audio_files(tmp_path)
    plan = {
        "audio_timeline": {"id": "timeline-2", "revision": 2, "source_hash": "hash-2"},
        "clips": [
            {
                "clip_index": 1,
                "start_time": 0,
                "end_time": 4,
                "audio_status": "READY",
                "audio_timeline_id": "timeline-1",
                "audio_timeline_revision": 1,
                "audio_timeline_hash": "hash-1",
                "drive_audio_path": str(drive_path),
                "final_audio_path": str(final_path),
                "clip_audio_duration": 4,
            }
        ],
    }

    with pytest.raises(RuntimeError) as exc:
        _resolve_audio_drive_for_h3(plan, plan["clips"][0], {"drive_audio_node_id": "1", "final_audio_node_id": "2"})
    assert "不匹配" in str(exc.value)


def test_h3_audio_resolver_accepts_clip_audio_with_current_timeline_binding(tmp_path):
    drive_path, final_path = _audio_files(tmp_path)
    plan = {
        "audio_timeline": {"id": "timeline-1", "revision": 1, "source_hash": "hash-1"},
        "clips": [
            {
                "clip_index": 1,
                "start_time": 0,
                "end_time": 4,
                "audio_status": "READY",
                "audio_timeline_id": "timeline-1",
                "audio_timeline_revision": 1,
                "audio_timeline_hash": "hash-1",
                "drive_audio_path": str(drive_path),
                "final_audio_path": str(final_path),
                "clip_audio_duration": 4,
                "speaker_timeline": [{"start_time": 0, "end_time": 4, "visible_speaker": "A"}],
            }
        ],
    }

    result = _resolve_audio_drive_for_h3(plan, plan["clips"][0], {"drive_audio_node_id": "1", "final_audio_node_id": "2"})

    assert result["enabled"] is True
    assert result["drive_audio_path"] == str(drive_path)
    assert result["final_audio_path"] == str(final_path)
