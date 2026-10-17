import asyncio
import hashlib
import json
import shutil
import subprocess

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.novel import Chapter, Character, Novel
from app.models.shot import Shot
from app.models.system_config import SystemConfig
from app.models.task import Task
from app.services import first_appearance_nameplates as nameplates


def test_first_appearance_uses_novel_order_and_excludes_narrator(db_session, monkeypatch, tmp_path):
    novel = Novel(title="姓名牌测试")
    db_session.add(novel)
    db_session.flush()
    later = Chapter(novel_id=novel.id, number=2, title="第二章")
    earlier = Chapter(novel_id=novel.id, number=1, title="第一章")
    db_session.add_all([later, earlier])
    db_session.flush()
    db_session.add_all([
        Character(novel_id=novel.id, name="甲"),
        Character(novel_id=novel.id, name="乙"),
        Character(novel_id=novel.id, name="旁白", is_narrator=True),
    ])
    shot_two = Shot(chapter_id=earlier.id, index=2, characters=json.dumps(["甲", "乙"]))
    shot_one = Shot(chapter_id=earlier.id, index=1, characters=json.dumps(["甲", "旁白"]))
    shot_later = Shot(chapter_id=later.id, index=1, characters=json.dumps(["乙", "甲"]))
    db_session.add_all([shot_two, shot_one, shot_later])
    db_session.commit()

    assert nameplates.first_appearance_names_by_shot(db_session, novel.id) == {
        shot_one.id: ["甲"], shot_two.id: ["乙"],
    }
    monkeypatch.setattr(nameplates, "_probe_video", lambda path: (640, 360, 4.0 if "shot" in str(path) else 1.0))
    events = nameplates.build_nameplate_events(db_session, novel.id, earlier.id, [
        {"kind": "shot", "key": "1", "path": tmp_path / "shot-1.mp4"},
        {"kind": "transition", "key": "1-2", "path": tmp_path / "transition.mp4"},
        {"kind": "shot", "key": "2", "path": tmp_path / "shot-2.mp4"},
    ])
    assert events == [
        {"start": 0.0, "end": 2.8, "names": ["甲"]},
        {"start": 5.0, "end": 7.8, "names": ["乙"]},
    ]


def test_config_defaults_and_can_toggle(client):
    assert client.get("/api/config/").json()["data"]["showFirstAppearanceNames"] is False
    assert client.post("/api/config/", json={"showFirstAppearanceNames": True}).status_code == 200
    assert client.get("/api/config/").json()["data"]["showFirstAppearanceNames"] is True
    assert client.post("/api/config/", json={"showFirstAppearanceNames": False}).status_code == 200
    assert client.get("/api/config/").json()["data"]["showFirstAppearanceNames"] is False


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg unavailable")
def test_nameplates_are_visible_only_during_first_seconds(tmp_path):
    raw = tmp_path / "raw.mp4"
    rendered = tmp_path / "rendered.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=white:s=640x360:r=10:d=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(raw),
    ], check=True)
    asyncio.run(nameplates.render_first_appearance_nameplates(raw, rendered, [
        {"start": 0.0, "end": 1.0, "names": ["甲"]},
    ]))
    assert rendered.is_file()
    assert nameplates._probe_video(rendered)[2] >= 1.9
    def pixel_at(second):
        output = subprocess.run([
            "ffmpeg", "-v", "error", "-ss", str(second), "-i", str(rendered),
            "-frames:v", "1", "-vf", "crop=1:1:30:50,format=rgb24", "-f", "rawvideo", "-",
        ], capture_output=True, check=True).stdout
        return tuple(output[:3])
    red = pixel_at(0.2)
    white = pixel_at(1.4)
    assert red[0] > red[1] * 2 and red[0] > red[2] * 2
    assert min(white) > 225


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg unavailable")
def test_chapter_merge_keeps_raw_shot_video_untouched(db_session, monkeypatch, tmp_path):
    from app.api import shots as shots_api

    source = tmp_path / "source.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=white:s=640x360:r=10:d=1",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
    ], check=True)
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    novel = Novel(title="合成测试")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="第一章")
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(chapter_id=chapter.id, index=1, characters=json.dumps(["甲"]), video_url="/api/files/source.mp4")
    db_session.add(shot)
    db_session.flush()
    task = Task(type="chapter_video", status="pending", name="合并", novel_id=novel.id, chapter_id=chapter.id,
                metadata_json=json.dumps({"mode": "shots_only", "video_variant": "draft", "inputs": [
                    {"shot_id": shot.id, "shot_index": 1, "video_url": shot.video_url},
                ]}))
    db_session.add_all([task, SystemConfig(id="default", show_first_appearance_names=True)])
    db_session.commit()
    task_id, source_url = task.id, shot.video_url

    monkeypatch.setattr(shots_api, "SessionLocal", sessionmaker(bind=db_session.bind))
    monkeypatch.setattr(shots_api, "url_to_local_path", lambda url: str(source) if url == source_url else None)
    monkeypatch.setattr(shots_api.file_storage, "base_dir", tmp_path)

    async def fake_merge(paths, output, transitions=None):
        shutil.copyfile(paths[0], output)
        return {"success": True}

    monkeypatch.setattr(shots_api.file_storage, "merge_videos", fake_merge)
    asyncio.run(shots_api.run_chapter_video_merge_task(task_id))

    db_session.expire_all()
    merged_task = db_session.query(Task).filter_by(id=task_id).one()
    assert merged_task.status == "completed", merged_task.error_message
    assert "-names-" in merged_task.result_url
    assert json.loads(merged_task.metadata_json)["nameplate_events"][0]["names"] == ["甲"]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash
    assert (tmp_path / merged_task.result_url.removeprefix("/api/files/")).is_file()
