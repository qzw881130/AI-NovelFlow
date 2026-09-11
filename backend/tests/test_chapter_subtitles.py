import asyncio
from array import array
from decimal import Decimal
from fractions import Fraction
import json
import shutil
import subprocess
from urllib.parse import unquote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.models.novel import Novel, Chapter
from app.models.shot import Shot
from app.services.chapter_subtitle_service import (
    SubtitleNotReady, chapter_subtitles, render_subtitles, subtitle_text, timestamp,
)
from app.services.file_storage import FileStorageService
from app.services.rendered_subtitles import compose, fingerprint, load, publish, sidecar, lock_generated_audio


@pytest.fixture
def chapter(db_session):
    novel = Novel(title="Novel")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="\u7b2c\u4e00\u7ae0 \u98ce\u96e8", content="")
    db_session.add(chapter)
    db_session.commit()
    return chapter


@pytest.mark.parametrize("seconds,srt,ass", [
    ("0", "00:00:00,000", "0:00:00.00"),
    ("59.9995", "00:01:00,000", "0:01:00.00"),
    ("3599.995", "00:59:59,995", "1:00:00.00"),
    ("360000.125", "100:00:00,125", "100:00:00.13"),
])
def test_timestamp_round_half_up(seconds, srt, ass):
    assert timestamp(Decimal(seconds), "srt") == srt
    assert timestamp(Decimal(seconds), "ass") == ass


def test_text_and_precision():
    assert subtitle_text("<b>\n\nhello\x00", "srt") == "&lt;b&gt;\nhello"
    assert "{" not in subtitle_text(r"{\pos(0,0)}\N", "ass")
    with pytest.raises(SubtitleNotReady):
        render_subtitles([{"start": "0", "end": "0.001", "text": "short"}], "ass")


@pytest.mark.parametrize("damage", ["missing", "media", "sidecar", "version", "unavailable"])
def test_fail_closed(tmp_path, damage):
    media = tmp_path / "video.mp4"
    media.write_bytes(b"media")
    publish(media, [{"start": "0", "end": "1", "text": "bound"}], {"kind": "merge"})
    assert load(media)
    if damage == "missing":
        sidecar(media).unlink()
    elif damage == "media":
        media.write_bytes(b"other")
    elif damage == "sidecar":
        sidecar(media).write_text("{}")
    elif damage == "version":
        envelope = json.loads(sidecar(media).read_text())
        envelope["snapshot"]["version"] = 999
        sidecar(media).write_text(json.dumps(envelope))
    else:
        publish(media, [], {"kind": "merge"}, unavailable="unknown source")
        assert load(media, require_ready=False)
    assert load(media) is None


def test_actual_selection_and_immutable_export(db_session, chapter, tmp_path, monkeypatch):
    media = tmp_path / "final.mp4"
    media.write_bytes(b"selected output")
    chapter.final_video = "/api/files/final.mp4"
    monkeypatch.setattr("app.services.chapter_subtitle_service.url_to_local_path", lambda url: str(media))
    publish(media, [{"start": "73/24", "end": "4", "text": "original"}], {"kind": "merge"})
    before = chapter_subtitles(db_session, chapter.id, "srt")
    assert "00:00:03,042 --> 00:00:04,000" in before
    db_session.add(Shot(chapter_id=chapter.id, index=1, description="changed", dialogues='[{"text":"wrong"}]'))
    db_session.commit()
    assert chapter_subtitles(db_session, chapter.id, "srt") == before
    media.write_bytes(b"replaced output")
    with pytest.raises(SubtitleNotReady):
        chapter_subtitles(db_session, chapter.id, "srt")


def test_api(db_session, chapter, tmp_path, monkeypatch):
    from app.api.chapter_subtitles import router

    app = FastAPI()
    app.include_router(router, prefix="/api/novels")
    media = tmp_path / "final.mp4"
    media.write_bytes(b"selected output")
    chapter.final_video = "/api/files/final.mp4"
    db_session.commit()
    monkeypatch.setattr("app.services.chapter_subtitle_service.url_to_local_path", lambda url: str(media))
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)  # No lifespan, live DB or workers.
        url = f"/api/novels/{chapter.novel_id}/chapters/{chapter.id}/subtitles"
        assert client.get(url).status_code == 409
        publish(media, [{"start": "0", "end": "1", "text": "hello"}], {"kind": "merge"})
        response = client.get(url)
        assert response.status_code == 200
        assert response.headers["x-subtitle-timeline"] == "rendered-media-v1"
        assert chapter.title in unquote(response.headers["content-disposition"])
        assert client.get(url + "?format=ass").status_code == 200
        assert client.get(url + "?format=vtt").status_code == 422
        assert client.get(url.replace(chapter.novel_id, "wrong")).status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_composition_trims_and_retains_actual_offsets():
    # A split event resumes in the next clip after an actual held frame/padding.
    segments = [
        {"origin": "0", "target_samples": 50000, "offset_samples": 0},
        {"origin": "1/8", "target_samples": 48000, "offset_samples": 50000},
    ]
    snapshots = [
        {"cues": [{"start": "3/4", "end": "1", "text": "spanning"}]},
        {"cues": [{"start": "1/8", "end": "5/8", "text": "spanning"},
                  {"start": "1", "end": "2", "text": "trim"}]},
    ]
    cues, error = compose(segments, snapshots)
    assert error is None
    assert [(Fraction(c["start"]), Fraction(c["end"])) for c in cues] == [
        (Fraction(3, 4), Fraction(1)), (Fraction(25, 24), Fraction(37, 24)),
        (Fraction(23, 12), Fraction(49, 24)),
    ]
    assert compose(segments, [snapshots[0], None])[1]


def ffmpeg(*args):
    return subprocess.run(["ffmpeg", "-v", "error", "-xerror", *map(str, args)],
                          check=True, capture_output=True).stdout


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg required")
def test_real_early_mid_late_beeps_two_level_merge(tmp_path):
    storage = FileStorageService(str(tmp_path))
    paths = []
    for index in range(3):
        path = tmp_path / f"clip{index}.mov"
        # Middle source has a delayed audio start and audio longer than video.
        delay = 0.125 if index == 1 else 0
        ffmpeg("-f", "lavfi", "-i", "color=black:s=64x64:r=25:d=0.8",
               "-f", "lavfi", "-i",
               "aevalsrc=0.6*sin(2*PI*1000*t)*(between(t\\,0.1\\,0.18)+between(t\\,0.4\\,0.48)+between(t\\,0.9\\,0.98)):s=48000:d=1.03",
               "-af", f"asetpts=PTS+{delay}/TB", "-c:v", "libx264", "-c:a", "pcm_s16le", "-y", path)
        publish(path, [{"start": str(start + delay), "end": str(start + delay + 0.08),
                        "text": f"{index}-{start}"} for start in (0.1, 0.4, 0.9)], {"kind": "synthetic"})
        paths.append(str(path))
    shot = tmp_path / "shot.mp4"
    first = asyncio.run(storage.merge_videos(paths[:2], str(shot)))
    assert first["success"]
    transition = tmp_path / "transition.mp4"
    ffmpeg("-f", "lavfi", "-i", "color=black:s=64x64:r=24:d=0.25", "-c:v", "libx264", "-y", transition)
    final = tmp_path / "chapter.mp4"
    result = asyncio.run(storage.merge_videos([str(shot), paths[2]], str(final), [str(transition)]))
    assert result["success"]
    snapshot = load(final)
    assert snapshot and len(snapshot["cues"]) == 9
    samples = array("f")
    samples.frombytes(ffmpeg("-i", final, "-map", "0:a:0", "-ac", "1", "-ar", "48000", "-f", "f32le", "-"))
    for cue in snapshot["cues"]:
        start, end = [round(float(Fraction(cue[key])) * 48000) for key in ("start", "end")]
        active = [i for i in range(max(0, start - 480), min(len(samples), end + 480)) if abs(samples[i]) > 0.15]
        assert abs(active[0] - start) < 240
        assert abs(active[-1] - end) < 240
    assert first["media_segments"][1]["audio_start"] == "1/8"
    assert first["media_segments"][0]["target_frames"] > first["media_segments"][0]["normalized_frames"]
    # Source changes later do not change the selected final snapshot.
    original = render_subtitles(snapshot["cues"], "srt")
    publish(paths[0], [], {"kind": "changed"})
    assert render_subtitles(load(final)["cues"], "srt") == original
    legacy = tmp_path / "legacy.mp4"
    sidecar(paths[2]).unlink()
    assert asyncio.run(storage.merge_videos([paths[2]], str(legacy)))["success"]
    assert load(legacy) is None
    assert load(legacy, require_ready=False)["unavailable"]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")
def test_generated_audio_is_locally_locked_and_changed_binding_rejected(tmp_path):
    video = tmp_path / "video.mp4"
    audio = tmp_path / "final.wav"
    ffmpeg("-f", "lavfi", "-i", "color=black:s=64x64:r=24:d=0.3", "-c:v", "libx264", "-y", video)
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=1000:duration=0.5", "-y", audio)
    snapshot = publish(audio, [{"start": "0", "end": "0.5", "text": "locked"}], {"kind": "clip_audio"})
    storage = FileStorageService(str(tmp_path))
    asyncio.run(lock_generated_audio(storage, str(video), str(audio), snapshot))
    assert load(video)["cues"] == snapshot["cues"]
    before = fingerprint(video)
    audio.write_bytes(b"replaced")
    asyncio.run(lock_generated_audio(storage, str(video), str(audio), snapshot))
    assert fingerprint(video) == before


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")
def test_clip_render_splits_bound_tts_and_does_not_recover_legacy(db_session, chapter, tmp_path, monkeypatch):
    from app.models.audio_drive import ShotAudioEvent
    from app.services.audio_drive_service import AudioDriveService
    from app.services.shot_video_service import _resolve_audio_drive_for_h3
    from app.services.file_storage import file_storage

    monkeypatch.setattr(file_storage, "base_dir", tmp_path)
    shot = Shot(chapter_id=chapter.id, index=1, description="split", duration=1, estimated_duration=1)
    db_session.add(shot)
    db_session.flush()
    event = ShotAudioEvent(shot_id=shot.id, event_order=1, event_type="NARRATION",
                          text="spanning", tts_status="READY", pause_after="NONE")
    db_session.add(event)
    db_session.commit()
    service = AudioDriveService(db_session)
    tts = tmp_path / "tts.wav"
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=1000:duration=1", "-y", tts)
    asset = service.repo.add_tts_asset(event.id, audio_path=str(tts), duration_seconds=1,
                                     status="READY", text_hash=service._hash_payload({"text": event.text}))
    publish(tts, [{"start": "0", "end": "1", "text": event.text}],
            {"kind": "tts", "tts_asset_id": asset.id, "text_hash": asset.text_hash})
    assert service.build_timeline(shot.id, force=True)["success"]
    plan = json.loads(shot.video_director_plan)
    plan["window_plans"] = [{"window_index": i + 1, "start_time": start, "end_time": end}
                            for i, (start, end) in enumerate([(0, 0.5), (0.5, 1)])]
    shot.video_director_plan = json.dumps(plan)
    db_session.commit()
    for index in (1, 2):
        assert service.build_clip_audio(shot.id, index, force=True)["success"]
    db_session.refresh(shot)
    plan = json.loads(shot.video_director_plan)
    windows = plan["window_plans"]
    for window in windows:
        snapshot = load(window["final_audio_path"])
        assert [(c["start"], c["end"], c["text"]) for c in snapshot["cues"]] == [("0.0", "0.5", "spanning")]
        assert snapshot["lineage"]["segments"][0]["source_start"] == window["start_time"]
        clip = {"clip_index": window["window_index"], "start_time": window["start_time"], "end_time": window["end_time"]}
        _resolve_audio_drive_for_h3(plan, clip, {"final_audio_node_id": "1"})
        assert clip["subtitle_snapshot"] == snapshot
    # Old TTS bytes with just a DB text_hash are not trustworthy retrospective evidence.
    sidecar(tts).unlink()
    assert service.build_clip_audio(shot.id, 1, force=True)["success"]
    rebuilt = json.loads(shot.video_director_plan)["window_plans"][0]
    assert rebuilt["final_audio_path"] != windows[0]["final_audio_path"]
    assert load(rebuilt["final_audio_path"]) is None
    assert load(windows[0]["final_audio_path"])["cues"][0]["text"] == "spanning"
    assert load(windows[1]["final_audio_path"])["cues"][0]["text"] == "spanning"
