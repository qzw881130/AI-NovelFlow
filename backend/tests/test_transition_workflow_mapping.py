"""转场工作流节点映射测试。"""

import asyncio
import json
from types import SimpleNamespace

from app.services.comfyui.service import ComfyUIService
from app.services.task_service import TaskService


def test_transition_mapping_requires_frame_count_or_duration_seconds_only():
    workflow = SimpleNamespace(
        name="transition workflow",
        node_mapping=json.dumps(
            {
                "first_image_node_id": "1",
                "last_image_node_id": "2",
                "video_save_node_id": "3",
                "frame_count_node_id": "4",
                "duration_seconds_node_id": "5",
            }
        ),
    )

    is_valid, error = TaskService.validate_workflow_node_mapping(workflow, "transition")

    assert is_valid is False
    assert "总帧数节点和时长秒数节点必须且只能配置其中一个" in error


def test_transition_mapping_accepts_duration_seconds_without_frame_count():
    workflow = SimpleNamespace(
        name="transition workflow",
        node_mapping=json.dumps(
            {
                "first_image_node_id": "1",
                "last_image_node_id": "2",
                "video_save_node_id": "3",
                "duration_seconds_node_id": "5",
                "megapixels_node_id": "6",
                "megapixels_value": "0.98",
            }
        ),
    )

    is_valid, error = TaskService.validate_workflow_node_mapping(workflow, "transition")

    assert is_valid is True
    assert error == ""


def test_transition_workflow_sets_duration_seconds_and_megapixels():
    workflow = {
        "1": {"inputs": {"image": ""}, "class_type": "LoadImage"},
        "2": {"inputs": {"image": ""}, "class_type": "LoadImage"},
        "3": {"inputs": {}, "class_type": "VHS_VideoCombine"},
        "4": {"inputs": {"value": 49}, "class_type": "INTConstant"},
        "5": {"inputs": {"value": 1.0}, "class_type": "Float"},
        "6": {"inputs": {"value": 0.4}, "class_type": "Float"},
    }

    class FakeClient:
        async def upload_image(self, image_path):
            return {"success": True, "filename": image_path}

        async def queue_prompt(self, submitted_workflow):
            self.submitted_workflow = submitted_workflow
            return {"success": True, "prompt_id": "prompt-1"}

        async def wait_for_result(self, prompt_id, submitted_workflow, node_id, timeout):
            return {"success": True, "video_url": "/video.mp4"}

    service = ComfyUIService()
    service.client = FakeClient()

    result = asyncio.run(
        service.generate_transition_video_with_workflow(
            workflow_json=json.dumps(workflow),
            node_mapping={
                "first_image_node_id": "1",
                "last_image_node_id": "2",
                "video_save_node_id": "3",
                "frame_count_node_id": "4",
                "duration_seconds_node_id": "5",
                "megapixels_node_id": "6",
                "megapixels_value": "0.98",
            },
            first_image_path="first.png",
            last_image_path="last.png",
            duration_seconds=3.5,
            frame_count=84,
        )
    )

    submitted = result["submitted_workflow"]
    assert submitted["1"]["inputs"]["image"] == "first.png"
    assert submitted["2"]["inputs"]["image"] == "last.png"
    assert submitted["5"]["inputs"]["value"] == 3.5
    assert submitted["6"]["inputs"]["value"] == 0.98
    assert submitted["4"]["inputs"]["value"] == 49
