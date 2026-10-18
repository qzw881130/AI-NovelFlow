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
        Character(novel_id=novel.id, name="甲", is_protagonist=True),
        Character(novel_id=novel.id, name="乙"),
        Character(novel_id=novel.id, name="旁白", is_narrator=True, is_protagonist=True),
    ])
    shot_two = Shot(chapter_id=earlier.id, index=2, characters=json.dumps(["甲", "乙"]))
    shot_one = Shot(chapter_id=earlier.id, index=1, characters=json.dumps(["甲", "旁白"]))
    shot_later = Shot(chapter_id=later.id, index=1, characters=json.dumps(["乙", "甲"]))
    db_session.add_all([shot_two, shot_one, shot_later])
    db_session.commit()

    assert nameplates.first_appearance_names_by_shot(db_session, novel.id) == {
        shot_one.id: ["甲"],
    }
    monkeypatch.setattr(nameplates, "_probe_video", lambda path: (640, 360, 4.0 if "shot" in str(path) else 1.0))
    async def fake_locate(video, character, duration):
        return [{"time": 0.25, "bbox": [300, 100, 600, 950]},
                {"time": 1.25, "bbox": [320, 100, 620, 950]}]
    monkeypatch.setattr(nameplates, "_locate_protagonist", fake_locate)
    events, warnings = asyncio.run(nameplates.build_nameplate_events(db_session, novel.id, earlier.id, [
        {"kind": "shot", "key": "1", "path": tmp_path / "shot-1.mp4"},
        {"kind": "transition", "key": "1-2", "path": tmp_path / "transition.mp4"},
        {"kind": "shot", "key": "2", "path": tmp_path / "shot-2.mp4"},
    ]))
    assert warnings == []
    assert len(events) == 1
    assert events[0]["name"] == "甲"
    assert events[0]["start"] == 0.25
    assert events[0]["end"] == 3.05
    assert events[0]["track"][0]["xy"] != events[0]["track"][1]["xy"]


def test_detection_rejects_uncertain_or_invalid_positions():
    parsed = nameplates._parse_detection(json.dumps({"frames": [
        {"index": 1, "visible": True, "confidence": 0.99, "bbox": [100, 100, 300, 900]},
        {"index": 2, "visible": True, "confidence": 0.4, "bbox": [100, 100, 300, 900]},
        {"index": 3, "visible": True, "confidence": 0.95, "bbox": [900, 100, 100, 900]},
    ]}), 3)
    assert [item["index"] for item in parsed] == [1]


def test_location_hint_does_not_confuse_gaze_direction():
    shot = Shot(description="Characters:\n- 邹忌: 位于画面中央，身体朝向画面右侧的铜镜。")
    assert nameplates._position_hint(shot, "邹忌") == "center"


def test_config_defaults_and_can_toggle(client):
    initial = client.get("/api/config/").json()["data"]
    assert initial["showFirstAppearanceNames"] is False
    assert initial["autoApproveFirstAppearanceNames"] is False
    assert client.post("/api/config/", json={
        "showFirstAppearanceNames": True,
        "autoApproveFirstAppearanceNames": True,
    }).status_code == 200
    updated = client.get("/api/config/").json()["data"]
    assert updated["showFirstAppearanceNames"] is True
    assert updated["autoApproveFirstAppearanceNames"] is True
    assert client.post("/api/config/", json={"autoApproveFirstAppearanceNames": False}).status_code == 200
    assert client.get("/api/config/").json()["data"]["autoApproveFirstAppearanceNames"] is False


def test_protagonist_can_be_selected_and_cleared(client, db_session):
    novel = Novel(title="主角设置")
    db_session.add(novel)
    db_session.commit()
    created = client.post("/api/characters/", json={
        "novelId": novel.id, "name": "主角甲", "isProtagonist": True,
    })
    assert created.status_code == 200
    character_id = created.json()["data"]["id"]
    assert created.json()["data"]["isProtagonist"] is True
    assert client.get(f"/api/characters/{character_id}").json()["data"]["isProtagonist"] is True
    assert client.put(f"/api/characters/{character_id}", json={
        "isProtagonist": False,
    }).json()["data"]["isProtagonist"] is False
    assert client.get(f"/api/characters?novel_id={novel.id}").json()["data"][0]["isProtagonist"] is False


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg unavailable")
def test_nameplates_are_visible_only_during_first_seconds(tmp_path):
    raw = tmp_path / "raw.mp4"
    rendered = tmp_path / "rendered.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=white:s=640x360:r=10:d=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(raw),
    ], check=True)
    asyncio.run(nameplates.render_first_appearance_nameplates(raw, rendered, [
        {"start": 0.0, "end": 1.0, "name": "甲",
         "track": [{"time": 0.0, "xy": [300, 50]}, {"time": 0.7, "xy": [330, 50]}]},
    ]))
    assert rendered.is_file()
    assert nameplates._probe_video(rendered)[2] >= 1.9
    def pixel_at(second, x=315):
        output = subprocess.run([
            "ffmpeg", "-v", "error", "-ss", str(second), "-i", str(rendered),
            "-frames:v", "1", "-vf", f"crop=1:1:{x}:55,format=rgb24", "-f", "rawvideo", "-",
        ], capture_output=True, check=True).stdout
        return tuple(output[:3])
    red = pixel_at(0.2)
    white = pixel_at(1.4)
    assert red[0] > red[1] * 2 and red[0] > red[2] * 2
    assert pixel_at(0.8, 335)[0] > pixel_at(0.8, 335)[1] * 2
    assert min(pixel_at(0.8, 315)) > 225
    assert min(white) > 225


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg unavailable")
@pytest.mark.parametrize("auto_approve,has_preview", [(False, True), (True, True), (True, False)])
def test_chapter_merge_keeps_raw_shot_video_untouched(client, db_session, monkeypatch, tmp_path,
                                                      auto_approve, has_preview):
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
    db_session.add(Character(novel_id=novel.id, name="甲", is_protagonist=True))
    task = Task(type="chapter_video", status="pending", name="合并", novel_id=novel.id, chapter_id=chapter.id,
                metadata_json=json.dumps({"mode": "shots_only", "video_variant": "draft", "inputs": [
                    {"shot_id": shot.id, "shot_index": 1, "video_url": shot.video_url},
                ]}))
    db_session.add(task)
    config = db_session.query(SystemConfig).filter_by(id="default").one()
    config.show_first_appearance_names = True
    config.auto_approve_first_appearance_names = auto_approve
    db_session.commit()
    task_id, source_url = task.id, shot.video_url

    monkeypatch.setattr(shots_api, "SessionLocal", sessionmaker(bind=db_session.bind))
    monkeypatch.setattr(shots_api, "url_to_local_path", lambda url: (
        str(source) if url == source_url else
        str(tmp_path / url.removeprefix("/api/files/")) if url.startswith("/api/files/") else None))
    monkeypatch.setattr(shots_api.file_storage, "base_dir", tmp_path)

    async def fake_merge(paths, output, transitions=None):
        shutil.copyfile(paths[0], output)
        return {"success": True}

    monkeypatch.setattr(shots_api.file_storage, "merge_videos", fake_merge)
    async def fake_events(db, novel_id, chapter_id, segments, output_size=None):
        assert nameplates.first_appearance_names_by_shot(db, novel_id) == {shot.id: ["甲"]}
        return ([{"start": 0.0, "end": 0.8, "name": "甲",
                  "track": [{"time": 0.0, "xy": [300, 50]}]}] if has_preview else [], [])
    monkeypatch.setattr(shots_api, "build_nameplate_events", fake_events)
    asyncio.run(shots_api.run_chapter_video_merge_task(task_id))

    db_session.expire_all()
    merged_task = db_session.query(Task).filter_by(id=task_id).one()
    assert merged_task.status == "completed", merged_task.error_message
    metadata = json.loads(merged_task.metadata_json)
    assert metadata["nameplate_status"] == (
        "approved" if auto_approve and has_preview else "pending_confirmation" if has_preview else "none"
    )
    assert metadata["nameplate_auto_approved"] is (auto_approve and has_preview)
    assert ("-names-" in merged_task.result_url) is (auto_approve and has_preview)
    if has_preview:
        assert "-names-" in metadata["nameplate_preview_url"]
        assert metadata["nameplate_raw_url"] != metadata["nameplate_preview_url"]
    else:
        assert metadata["nameplate_preview_url"] is None
    assert db_session.query(Chapter).filter_by(id=chapter.id).one().final_video == merged_task.result_url
    listed = client.get("/api/tasks/?summary=true").json()["data"]
    projected = next(item for item in listed if item["id"] == task_id)
    assert projected["nameplatePreview"]["autoApproved"] is (auto_approve and has_preview)
    assert projected["nameplatePreview"]["status"] == metadata["nameplate_status"]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash
    assert (tmp_path / merged_task.result_url.removeprefix("/api/files/")).is_file()
    if has_preview and not auto_approve:
        approved = asyncio.run(shots_api.approve_chapter_nameplate_preview(
            novel.id, chapter.id, task_id, db_session))
        assert approved["video_url"] == metadata["nameplate_preview_url"]
        db_session.expire_all()
        assert db_session.query(Chapter).filter_by(id=chapter.id).one().final_video == approved["video_url"]
        assert db_session.query(Task).filter_by(id=task_id).one().result_url == approved["video_url"]


def test_nameplate_position_accounts_for_chapter_merge_scaling():
    # An 800x800 Shot is padded to the first Shot's 1600x900 canvas.
    assert nameplates._badge_position([100, 100, 300, 600], "甲", 800, 800,
                                      (1600, 900)) == (645, 77)
