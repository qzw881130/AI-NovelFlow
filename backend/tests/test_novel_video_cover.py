import asyncio
import io
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

import pytest
from PIL import Image, ImageChops

from app.models.novel import Novel
from app.models.task import Task
from app.models.workflow import Workflow
from app.services.novel_video_cover_service import COVER_SIZES, _draw_cover, _set_dimension, run_novel_video_cover_task


@pytest.mark.parametrize("aspect_ratio,text_style", [("9:16", "editorial"), ("3:4", "vintage")])
def test_cover_task_uses_active_scene_workflow_and_selected_frame(client, db_session, monkeypatch, tmp_path, aspect_ratio, text_style):
    novel = Novel(title="药", author="鲁迅")
    db_session.add(novel)
    db_session.flush()
    video = tmp_path / "merged.mp4"
    video.write_bytes(b"video")
    merge = Task(type="novel_video", status="completed", novel_id=novel.id,
                 name="合并视频", result_url="/api/files/merged.mp4",
                 metadata_json=json.dumps({"duration": 60}))
    workflow = Workflow(type="shot_scene", name="当前场景工作流", is_active=True,
                        workflow_json="{}", node_mapping=json.dumps({
                            "prompt_node_id": "1", "save_image_node_id": "2",
                            "width_node_id": "3", "height_node_id": "4",
                            "scene_reference_image_node_id": "5",
                        }))
    db_session.add_all([merge, workflow])
    db_session.commit()
    queued = []
    monkeypatch.setattr("app.api.novel_videos.url_to_local_path", lambda _: str(video))
    def fake_enqueue(task_id):
        asyncio.get_running_loop()
        queued.append(task_id)
    monkeypatch.setattr("app.api.novel_videos.enqueue_novel_video_cover_task", fake_enqueue)

    response = client.post(f"/api/novels/{novel.id}/video-merges/{merge.id}/cover", json={
        "frame_seconds": 12.5, "aspect_ratio": aspect_ratio, "text_style": text_style, "title": "药（有声版）",
        "author": "鲁迅", "production": "旺仔有声小说",
    })
    assert response.status_code == 200, response.text
    task = db_session.query(Task).filter(Task.type == "novel_video_cover").one()
    assert queued == [task.id]
    assert task.workflow_id == workflow.id
    assert json.loads(task.metadata_json)["output_size"] == list(COVER_SIZES[aspect_ratio])
    assert json.loads(task.metadata_json)["frame_seconds"] == 12.5
    assert json.loads(task.metadata_json)["text_style"] == text_style
    assert response.json()["data"]["title"] == "药（有声版）"
    assert response.json()["data"]["textStyle"] == text_style

    history = client.get(f"/api/novels/{novel.id}/video-merges").json()["data"]
    assert history[0]["cover"]["id"] == task.id
    second = client.post(f"/api/novels/{novel.id}/video-merges/{merge.id}/cover", json={
        "frame_seconds": 13, "aspect_ratio": "16:9",
    })
    assert second.status_code == 200
    assert len(queued) == 2
    history = client.get(f"/api/novels/{novel.id}/video-merges").json()["data"][0]
    assert {cover["id"] for cover in history["activeCovers"]} == set(queued)


def test_cover_rejects_seconds_outside_video(client, db_session, monkeypatch, tmp_path):
    novel = Novel(title="药", author="鲁迅")
    db_session.add(novel)
    db_session.flush()
    video = tmp_path / "merged.mp4"
    video.write_bytes(b"video")
    merge = Task(type="novel_video", status="completed", novel_id=novel.id,
                 name="合并视频", result_url="/api/files/merged.mp4",
                 metadata_json=json.dumps({"duration": 5}))
    db_session.add(merge)
    db_session.commit()
    monkeypatch.setattr("app.api.novel_videos.url_to_local_path", lambda _: str(video))
    response = client.post(f"/api/novels/{novel.id}/video-merges/{merge.id}/cover", json={"frame_seconds": 5})
    assert response.status_code == 400


def test_cover_draws_exact_output_ratio_and_updates_int_nodes(tmp_path):
    source = Image.new("RGB", (128, 72), "#406080")
    buffer = io.BytesIO()
    source.save(buffer, format="PNG")
    destination = tmp_path / "cover.png"
    _draw_cover(buffer.getvalue(), destination, COVER_SIZES["4:3"], "药", "鲁迅", "旺仔有声小说")
    bracketed_destination = tmp_path / "bracketed-cover.png"
    _draw_cover(buffer.getvalue(), bracketed_destination, COVER_SIZES["4:3"], "《药》", "鲁迅", "旺仔有声小说")
    with Image.open(destination) as image:
        assert image.size == COVER_SIZES["4:3"]
        assert image.getpixel((100, 800)) != image.getpixel((100, 100))
        bright_text_x = [x for y in range(image.height // 2, image.height) for x in range(image.width)
                         if all(channel > 225 for channel in image.getpixel((x, y)))]
        assert bright_text_x
        assert abs((min(bright_text_x) + max(bright_text_x)) / 2 - image.width / 2) < image.width * 0.05
        with Image.open(bracketed_destination) as bracketed_image:
            assert ImageChops.difference(image, bracketed_image).getbbox() is not None

    workflow = {"3": {"inputs": {"Number": "512", "value": 512}}}
    _set_dimension(workflow, "3", 1152)
    assert workflow["3"]["inputs"] == {"Number": "1152"}


@pytest.mark.parametrize("aspect_ratio", list(COVER_SIZES))
@pytest.mark.parametrize("text_style", ["cinematic", "editorial", "vintage"])
def test_cover_text_styles_render_in_each_ratio(tmp_path, aspect_ratio, text_style):
    source = Image.new("RGB", (64, 64), "#406080")
    buffer = io.BytesIO()
    source.save(buffer, format="PNG")
    destination = tmp_path / f"{text_style}-{aspect_ratio.replace(':', 'x')}.png"
    _draw_cover(buffer.getvalue(), destination, COVER_SIZES[aspect_ratio],
                "药", "鲁迅", "旺仔有声小说", text_style)
    with Image.open(destination) as cover:
        assert cover.size == COVER_SIZES[aspect_ratio]
        assert ImageChops.difference(cover, Image.new("RGB", cover.size, "#406080")).getbbox()


def test_cover_download_and_content_setting(client, db_session, monkeypatch, tmp_path):
    novel = Novel(title="药", author="鲁迅")
    db_session.add(novel)
    db_session.flush()
    merge = Task(type="novel_video", status="completed", novel_id=novel.id,
                 name="合并视频", result_url="/api/files/merged.mp4")
    db_session.add(merge)
    db_session.flush()
    image_path = tmp_path / "cover.png"
    image_path.write_bytes(b"cover-png")
    cover = Task(type="novel_video_cover", status="completed", novel_id=novel.id,
                 parent_task_id=merge.id, name="视频封面", result_url="/api/files/cover.png",
                 metadata_json=json.dumps({"aspect_ratio": "16:9", "frame_seconds": 2}))
    db_session.add(cover)
    db_session.commit()
    monkeypatch.setattr("app.api.novel_videos.url_to_local_path", lambda _: str(image_path))
    monkeypatch.setattr("app.api.novel_videos.file_storage.base_dir", tmp_path)

    response = client.get(f"/api/novels/{novel.id}/video-merges/{merge.id}/cover/download")
    assert response.status_code == 200
    assert response.content == b"cover-png"
    assert unquote(response.headers["content-disposition"]).endswith("药-视频封面.png")

    response = client.post("/api/config/", json={"coverProduction": "测试制作方"})
    assert response.status_code == 200
    assert client.get("/api/config/").json()["data"]["coverProduction"] == "测试制作方"


def test_merge_history_keeps_latest_successful_cover_for_each_ratio(client, db_session, monkeypatch, tmp_path):
    novel = Novel(title="药", author="鲁迅")
    db_session.add(novel)
    db_session.flush()
    merge = Task(type="novel_video", status="completed", novel_id=novel.id,
                 name="合并视频", result_url="/api/files/merged.mp4")
    db_session.add(merge)
    db_session.flush()
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def add_cover(ratio, status, index):
        cover = Task(type="novel_video_cover", status=status, novel_id=novel.id,
                     parent_task_id=merge.id, name="视频封面",
                     result_url=f"/api/files/cover-{index}.png" if status == "completed" else None,
                     metadata_json=json.dumps({"aspect_ratio": ratio}),
                     created_at=base_time + timedelta(minutes=index))
        db_session.add(cover)
        db_session.flush()
        return cover

    old_landscape = add_cover("16:9", "completed", 1)
    portrait = add_cover("9:16", "completed", 2)
    new_landscape = add_cover("16:9", "completed", 3)
    new_landscape.created_at = old_landscape.created_at
    old_landscape.completed_at = base_time + timedelta(minutes=2)
    new_landscape.completed_at = base_time + timedelta(minutes=3)
    add_cover("9:16", "failed", 4)
    pending_square = add_cover("1:1", "pending", 5)
    db_session.commit()

    history = client.get(f"/api/novels/{novel.id}/video-merges").json()["data"][0]
    assert history["cover"]["id"] == pending_square.id
    assert [cover["id"] for cover in history["activeCovers"]] == [pending_square.id]
    assert {cover["aspectRatio"]: cover["id"] for cover in history["covers"]} == {
        "16:9": new_landscape.id, "9:16": portrait.id,
    }
    assert old_landscape.id not in [cover["id"] for cover in history["covers"]]

    image_paths = {}
    for cover in (portrait, new_landscape):
        path = tmp_path / f"{cover.id}.png"
        path.write_bytes(cover.id.encode())
        image_paths[cover.result_url] = str(path)
    monkeypatch.setattr("app.api.novel_videos.url_to_local_path", image_paths.get)
    monkeypatch.setattr("app.api.novel_videos.file_storage.base_dir", tmp_path)
    for cover in (portrait, new_landscape):
        response = client.get(f"/api/novels/{novel.id}/video-merges/{merge.id}/cover/download?cover_id={cover.id}")
        assert response.status_code == 200
        assert response.content == cover.id.encode()
        assert unquote(response.headers["content-disposition"]).endswith(
            f"药-视频封面-{json.loads(cover.metadata_json)['aspect_ratio'].replace(':', 'x')}.png")

    pending_square.status = "completed"
    pending_square.result_url = "/api/files/cover-square.png"
    db_session.commit()
    history = client.get(f"/api/novels/{novel.id}/video-merges").json()["data"][0]
    assert {cover["aspectRatio"] for cover in history["covers"]} == {"16:9", "9:16", "1:1"}


@pytest.mark.parametrize("aspect_ratio,expected_size", [("1:1", (1024, 1024)), ("3:4", (864, 1152))])
def test_cover_worker_sends_selected_frame_and_ratio_to_scene_workflow(db_session, monkeypatch, tmp_path, aspect_ratio, expected_size):
    novel = Novel(title="药", author="鲁迅")
    db_session.add(novel)
    db_session.flush()
    video = tmp_path / "merged.mp4"
    video.write_bytes(b"video")
    merge = Task(type="novel_video", status="completed", novel_id=novel.id,
                 name="合并视频", result_url="/api/files/merged.mp4")
    workflow = Workflow(type="shot_scene", name="场景分镜图", is_active=True,
                        workflow_json="{}", node_mapping=json.dumps({
                            "prompt_node_id": "1", "save_image_node_id": "2",
                            "width_node_id": "3", "height_node_id": "4",
                            "scene_reference_image_node_id": "5",
                        }))
    db_session.add_all([merge, workflow])
    db_session.flush()
    task = Task(type="novel_video_cover", status="pending", novel_id=novel.id,
                parent_task_id=merge.id, workflow_id=workflow.id, name="生成封面",
                metadata_json=json.dumps({"frame_seconds": 7.5, "aspect_ratio": aspect_ratio,
                                          "title": "药", "author": "鲁迅", "production": "旺仔有声小说"}))
    db_session.add(task)
    db_session.commit()
    task_id = task.id

    generated_image = tmp_path / "generated.png"
    Image.new("RGB", (64, 64), "#708090").save(generated_image)
    observed = {}

    def fake_extract(_video, seconds, output):
        observed["seconds"] = seconds
        Image.new("RGB", (64, 64), "#708090").save(output)

    class FakeBuilder:
        def build_shot_workflow(self, **_kwargs):
            return {"3": {"inputs": {"Number": 512}},
                    "4": {"inputs": {"value": 512}},
                    "5": {"inputs": {"image": "old.png"}}}

    class FakeClient:
        async def upload_image(self, path):
            observed["frame_path"] = path
            return {"success": True, "filename": "selected-frame.png"}

    class FakeComfyUIService:
        def __init__(self, **_kwargs):
            self.builder = FakeBuilder()
            self.client = FakeClient()

        async def generate_shot_image_with_workflow(self, **kwargs):
            observed["graph"] = kwargs["workflow"]
            return {"success": True, "image_url": "/api/files/generated.png"}

    monkeypatch.setattr("app.services.novel_video_cover_service.SessionLocal", lambda: db_session)
    monkeypatch.setattr("app.services.novel_video_cover_service.url_to_local_path",
                        lambda url: str(video if url.endswith("merged.mp4") else generated_image))
    monkeypatch.setattr("app.services.novel_video_cover_service.local_path_to_url", lambda _: "/api/files/cover.png")
    monkeypatch.setattr("app.services.novel_video_cover_service.file_storage.base_dir", tmp_path)
    monkeypatch.setattr("app.services.novel_video_cover_service._extract_frame", fake_extract)
    monkeypatch.setattr("app.services.novel_video_cover_service.ComfyUIService", FakeComfyUIService)
    monkeypatch.setattr("app.services.novel_video_cover_service.get_style", lambda *_: ("cinematic", None))

    asyncio.run(run_novel_video_cover_task(task_id))

    db_session.expire_all()
    assert db_session.query(Task).filter_by(id=task_id).one().status == "completed"
    assert observed["seconds"] == 7.5
    assert observed["graph"]["3"]["inputs"] == {"Number": expected_size[0]}
    assert observed["graph"]["4"]["inputs"]["value"] == expected_size[1]
    assert observed["graph"]["5"]["inputs"]["image"] == "selected-frame.png"
