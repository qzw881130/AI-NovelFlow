import json
from unittest.mock import AsyncMock

import pytest

from app.services.comfyui.service import ComfyUIService


@pytest.mark.asyncio
async def test_semantic_single_frame_without_shot_image_stops_before_comfy_upload():
    service = ComfyUIService()
    service.builder.build_video_workflow = lambda **_: {
        "137": {"class_type": "LoadImage", "inputs": {"image": "file1.png"}},
        "170": {"class_type": "SaveVideo", "inputs": {"filename_prefix": "test"}},
    }
    service.client.upload_image = AsyncMock()

    result = await service.generate_shot_video_with_workflow(
        prompt="prompt",
        workflow_json="{}",
        node_mapping={"reference_image_node_id": "137", "video_save_node_id": "170"},
        character_reference_path=None,
        strict_reference_image=True,
    )

    assert result["success"] is False
    assert "缺少 Shot Image" in result["message"]
    service.client.upload_image.assert_not_awaited()


@pytest.mark.asyncio
async def test_semantic_single_frame_overwrites_default_loadimage_with_uploaded_shot_asset():
    service = ComfyUIService()
    service.builder.build_video_workflow = lambda **_: {
        "137": {"class_type": "LoadImage", "inputs": {"image": "file1.png"}},
        "138": {"class_type": "LoadImage", "inputs": {"image": "historic.png"}},
        "170": {"class_type": "SaveVideo", "inputs": {"filename_prefix": "test"}},
    }
    service.client.upload_image = AsyncMock(return_value={"success": True, "filename": "shot-current.png"})
    service.client.queue_prompt = AsyncMock(return_value={"success": True, "prompt_id": "test-prompt"})
    service.client.wait_for_result = AsyncMock(return_value={"success": True, "video_url": "result.mp4"})

    result = await service.generate_shot_video_with_workflow(
        prompt="prompt",
        workflow_json="{}",
        node_mapping={"reference_image_node_id": "not-a-load-image", "video_save_node_id": "170"},
        character_reference_path="/assets/current-shot.png",
        strict_reference_image=True,
    )

    assert result["success"] is True
    submitted = result["submitted_workflow"]
    assert submitted["137"]["inputs"]["image"] == "shot-current.png"
    assert submitted["138"]["inputs"]["image"] == "shot-current.png"


def test_semantic_clip_plan_generation_rejects_missing_shot_image(client, db_session):
    from app.models.novel import Novel, Chapter
    from app.models.shot import Shot
    from app.models.workflow import Workflow

    novel = Novel(id="novel-assets", title="Asset Test")
    chapter = Chapter(id="chapter-assets", novel_id=novel.id, number=1, title="Chapter")
    shot = Shot(
        id="shot-assets",
        chapter_id=chapter.id,
        index=1,
        duration=10,
        image_url=None,
        image_path=None,
        video_director_plan=json.dumps({
            "clip_plan_revision": 1,
            "clip_plan_validation": {"passed": True},
            "clip_plan": [{
                "clip_index": 1,
                "start_time": 0,
                "end_time": 10,
                "planned_duration": 10,
                "capability": "SINGLE_FRAME",
                "execution_status": "PLANNED",
            }],
        }),
    )
    workflow = Workflow(id="video-assets", type="video", name="Video", workflow_json="{}", is_active=True)
    db_session.add_all([novel, chapter, shot, workflow])
    db_session.commit()

    response = client.post(
        f"/api/novels/{novel.id}/chapters/{chapter.id}/shots/{shot.id}/video-director/clip-plan/generate"
    )

    assert response.status_code == 400
    assert "需要当前 Shot 已生成的有效分镜图" in response.json()["detail"]
