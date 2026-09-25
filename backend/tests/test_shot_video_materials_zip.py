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


def test_download_shot_video_materials_includes_each_current_semantic_clip_workflow(client, db_session, monkeypatch, tmp_path):
    novel = Novel(title="Semantic 素材导出")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="第一章")
    db_session.add(chapter)
    db_session.flush()

    primary_path = tmp_path / "primary.png"
    primary_path.write_bytes(b"primary")
    previous_av_path = tmp_path / "previous.mp4"
    previous_av_path.write_bytes(b"previous-av")
    shot = Shot(
        chapter_id=chapter.id,
        index=4,
        image_url="/api/files/primary.png",
        video_director_plan="{}",
    )
    db_session.add(shot)
    db_session.flush()

    current_c1 = Task(
        type="shot_video", status="completed", name="C1", shot_id=shot.id,
        workflow_name="单帧工作流", workflow_json='{"clip": 1, "revision": 4}',
        metadata_json=json.dumps({"execution_scope": "CLIP", "clip_index": 1, "clip_plan_revision": 4, "capability": "SINGLE_FRAME"}),
    )
    current_c2 = Task(
        type="shot_video", status="completed", name="C2", shot_id=shot.id,
        workflow_name="续生成工作流", workflow_json='{"clip": 2, "revision": 4}',
        metadata_json=json.dumps({
            "execution_scope": "CLIP", "clip_index": 2, "clip_plan_revision": 4,
            "capability": "VIDEO_CONTINUATION", "previous_approved_video_url": "/api/files/previous.mp4",
        }),
    )
    stale_c1 = Task(
        type="shot_video", status="completed", name="旧 C1", shot_id=shot.id,
        workflow_name="旧工作流", workflow_json='{"clip": 1, "revision": 3}',
        metadata_json=json.dumps({"execution_scope": "CLIP", "clip_index": 1, "clip_plan_revision": 3, "capability": "SINGLE_FRAME"}),
    )
    db_session.add_all([current_c1, current_c2, stale_c1])
    db_session.flush()
    shot.video_director_plan = json.dumps({
        "clip_plan_revision": 4,
        "clip_plan": [
            {"clip_index": 1, "capability": "SINGLE_FRAME", "generated_by_task_id": current_c1.id},
            {"clip_index": 2, "capability": "VIDEO_CONTINUATION", "generated_by_task_id": current_c2.id},
        ],
    })
    db_session.commit()

    paths = {
        "/api/files/primary.png": str(primary_path),
        "/api/files/previous.mp4": str(previous_av_path),
    }
    monkeypatch.setattr("app.api.shots.url_to_local_path", lambda url: paths.get(url))

    response = client.get(
        f"/api/novels/{novel.id}/chapters/{chapter.id}/shots/{shot.id}/download-video-materials"
    )

    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as archive:
        archive_names = set(archive.namelist())
        workflow_names = sorted(name for name in archive_names if name.startswith("workflows/video/"))
        manifest = json.loads(archive.read("manifest.json"))

    assert len(workflow_names) == 2
    assert any("C001_SINGLE_FRAME" in name for name in workflow_names)
    assert any("C002_VIDEO_CONTINUATION" in name for name in workflow_names)
    assert "videos/references/C002_PreviousAV.mp4" in archive_names
    assert {item["task_id"] for item in manifest["workflows"]} == {current_c1.id, current_c2.id}
    assert {item["clip_plan_revision"] for item in manifest["workflows"]} == {4}
    continuation = next(item for item in manifest["workflows"] if item["clip_index"] == 2)
    assert continuation["previous_av_path"] == "videos/references/C002_PreviousAV.mp4"
