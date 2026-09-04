import json
import shutil

import pytest

from app.api.shots import _assert_audio_drive_ready_for_video
from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.workflow import Workflow
from app.services.audio_drive_service import AudioDriveService
from app.services.file_storage import file_storage


def _create_visual_shot(db_session, estimated_duration=4.2):
    novel = Novel(title="AudioDrive Gate C3")
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
        description="Pure visual shot",
        characters=json.dumps([], ensure_ascii=False),
        scene="房间",
        props=json.dumps([], ensure_ascii=False),
        estimated_duration=estimated_duration,
        duration=99,
        audio_status="NOT_READY",
        video_director_plan=json.dumps({}, ensure_ascii=False),
    )
    db_session.add(shot)
    db_session.commit()
    db_session.refresh(shot)
    return shot


def _workflow_requires_audio():
    return Workflow(
        name="H3 audio",
        type="video",
        workflow_json="{}",
        node_mapping=json.dumps({"drive_audio_node_id": "1", "final_audio_node_id": "2"}),
    )


def test_pure_visual_shot_completes_audiodrive_ready_chain(db_session, tmp_path, monkeypatch):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe required for real silent WAV validation")
    monkeypatch.setattr(file_storage, "base_dir", tmp_path)
    shot = _create_visual_shot(db_session, estimated_duration=4.2)
    service = AudioDriveService(db_session)

    timeline_result = service.build_timeline(shot.id, force=True)
    windows_result = service.build_execution_windows(shot.id, max_clip_duration=15)
    clip_result = service.build_clip_audio(shot.id, 1, force=True)

    assert timeline_result["success"] is True
    assert timeline_result["data"]["audioRequiredDuration"] == 0.0
    assert timeline_result["data"]["totalDuration"] == 4.2
    assert timeline_result["data"]["status"] == "READY"
    assert timeline_result["data"]["events"] == []

    assert windows_result["success"] is True
    window = windows_result["data"]["executionWindows"][0]
    assert window["start_time"] == 0
    assert window["end_time"] == 4.2
    assert window["duration"] == 4.2

    assert clip_result["success"] is True
    db_session.refresh(shot)
    plan = json.loads(shot.video_director_plan)
    clip = plan["window_plans"][0]
    drive_path = clip["drive_audio_path"]
    final_path = clip["final_audio_path"]
    assert clip["audio_status"] == "READY"
    assert clip["clip_audio_duration"] == 4.2
    assert clip["speaker_timeline"] == [{"start_time": 0.0, "end_time": 4.2, "visible_speaker": "NONE"}]
    assert service._probe_audio_duration(drive_path) == pytest.approx(4.2, abs=0.05)
    assert service._probe_audio_duration(final_path) == pytest.approx(4.2, abs=0.05)

    _assert_audio_drive_ready_for_video(shot, plan, _workflow_requires_audio(), {1})


def test_prepare_tts_wait_accepts_empty_audio_events(db_session):
    shot = _create_visual_shot(db_session, estimated_duration=4.2)
    task = type("TaskStub", (), {"current_step": "", "progress": 0})()

    async def run_wait():
        await AudioDriveService._wait_for_prepare_tts_ready(AudioDriveService(db_session), shot.id, task, shot.index)

    import asyncio
    asyncio.run(run_wait())
