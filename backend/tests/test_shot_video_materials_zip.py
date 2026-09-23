import json
from io import BytesIO
from zipfile import ZipFile

from app.models.novel import Chapter, Character, Novel, Prop, Scene
from app.models.shot import Shot
from app.models.task import Task


def test_download_shot_video_materials_includes_images_and_actual_workflows(client, db_session, monkeypatch, tmp_path):
    novel = Novel(title="测试小说")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="第一章")
    db_session.add(chapter)
    db_session.flush()

    asset_names = ["primary", "end", "middle", "character", "merged-character", "scene", "prop", "merged-prop"]
    paths = {}
    for name in asset_names:
        path = tmp_path / f"{name}.png"
        path.write_bytes(name.encode())
        paths[f"/api/files/{name}.png"] = str(path)

    character = Character(novel_id=novel.id, name="皇帝", image_url="/api/files/character.png")
    scene = Scene(novel_id=novel.id, name="王宫", image_url="/api/files/scene.png")
    prop = Prop(novel_id=novel.id, name="王冠", image_url="/api/files/prop.png", existence="REAL")
    db_session.add_all([character, scene, prop])

    image_task = Task(type="shot_image", status="completed", name="主分镜图", workflow_json='{"image": "actual"}')
    keyframe_task = Task(type="keyframe_image", status="completed", name="尾帧", workflow_json='{"keyframe": "actual"}')
    video_task = Task(
        type="shot_video",
        status="completed",
        name="视频",
        workflow_json='{"video": "actual"}',
        video_director_clips=json.dumps([{"window_index": 1, "workflow_json": {"clip": "actual"}}]),
    )
    db_session.add_all([image_task, keyframe_task, video_task])
    db_session.flush()

    plan = {
        "selected_mode": "FIRST_LAST_FRAME",
        "keyframes": [
            {"index": 1, "role": "START"},
            {"index": 2, "role": "END", "image_url": "/api/files/end.png", "image_task_id": keyframe_task.id},
        ],
        "window_plans": [{"window_index": 1, "workflow_json": {"clip": "actual"}}],
    }
    shot = Shot(
        chapter_id=chapter.id,
        index=4,
        image_url="/api/files/primary.png",
        image_task_id=image_task.id,
        characters=json.dumps(["皇帝"], ensure_ascii=False),
        scene="王宫",
        props=json.dumps(["王冠"], ensure_ascii=False),
        merged_character_image="/api/files/merged-character.png",
        merged_prop_image="/api/files/merged-prop.png",
        keyframes=json.dumps([{"frame_index": 3, "image_url": "/api/files/middle.png"}]),
        video_director_plan=json.dumps(plan),
        video_task_id=video_task.id,
    )
    db_session.add(shot)
    db_session.flush()
    image_task.shot_id = shot.id
    keyframe_task.shot_id = shot.id
    video_task.shot_id = shot.id
    db_session.commit()

    monkeypatch.setattr("app.api.shots.url_to_local_path", lambda url: paths.get(url))

    response = client.get(
        f"/api/novels/{novel.id}/chapters/{chapter.id}/shots/{shot.id}/download-video-materials"
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with ZipFile(BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("manifest.json"))

    assert "frames/主分镜图.png" in names
    assert "frames/keyframes/KF001_START.png" in names
    assert "frames/keyframes/KF002_END.png" in names
    assert "frames/keyframes/KF003.png" in names
    assert "characters/01_皇帝.png" in names
    assert "characters/合并角色图.png" in names
    assert "scene/王宫.png" in names
    assert "props/01_王冠.png" in names
    assert "props/合并道具图.png" in names
    assert "workflows/images/主分镜图_ComfyUI.json" in names
    assert any(name.startswith("workflows/keyframes/") for name in names)
    assert "workflows/video/Shot视频_ComfyUI.json" in names
    assert "workflows/video/clip_001_ComfyUI.json" in names
    assert len(manifest["assets"]) == 9
    assert len(manifest["workflows"]) == 4
