import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.comfyui.service import ComfyUIService


def _workflow():
    return {
        "519": {
            "class_type": "QwenPERewriteT8",
            "inputs": {"seed": 42, "user_prompt": ["516", 0]},
        },
        "482": {"class_type": "KSampler", "inputs": {"seed": 890110077}},
        "510": {"class_type": "LoadImage", "inputs": {"image": "character.png"}},
        "516": {"class_type": "CR Prompt Text", "inputs": {"prompt": "original"}},
        "515": {"class_type": "SaveImage", "inputs": {}},
    }


def _service_with_format_failure_then_success():
    service = ComfyUIService.__new__(ComfyUIService)
    service.builder = MagicMock()
    service.client = MagicMock()
    service.client.queue_prompt = AsyncMock(side_effect=[
        {"success": True, "prompt_id": "first-prompt"},
        {"success": True, "prompt_id": "retry-prompt"},
    ])
    service.client.wait_for_result = AsyncMock(side_effect=[
        {
            "success": False,
            "message": "QwenPERewriteT8: model failed format validation after one retry: "
            "model returned an unmatched thinking block close",
        },
        {"success": True, "image_url": "/output.png"},
    ])
    return service


@pytest.mark.asyncio
async def test_character_scene_prop_image_retry_changes_only_pe_seed():
    service = _service_with_format_failure_then_success()
    workflow = _workflow()
    queued = []

    result = await service.generate_scene_image(
        prompt="test",
        workflow_json="{}",
        node_mapping={"save_image_node_id": "515"},
        workflow=workflow,
        on_prompt_queued=lambda prompt_id, graph: queued.append(
            (prompt_id, graph["519"]["inputs"]["seed"])
        ),
    )

    assert result["success"] is True
    assert result["prompt_id"] == "retry-prompt"
    assert workflow["519"]["inputs"]["seed"] != 42
    assert workflow["519"]["inputs"]["user_prompt"] == ["516", 0]
    assert workflow["482"]["inputs"]["seed"] == 890110077
    assert workflow["510"]["inputs"]["image"] == "character.png"
    assert [item[0] for item in queued] == ["first-prompt", "retry-prompt"]
    assert service.client.queue_prompt.await_count == 2
    assert service.client.wait_for_result.await_count == 2


@pytest.mark.asyncio
async def test_shot_image_retry_changes_pe_seed_and_preserves_references():
    service = _service_with_format_failure_then_success()
    workflow = _workflow()

    result = await service.generate_shot_image_with_workflow(
        prompt="test",
        workflow_json="{}",
        node_mapping={"save_image_node_id": "515"},
        workflow=workflow,
    )

    assert result["success"] is True
    assert result["prompt_id"] == "retry-prompt"
    assert workflow["519"]["inputs"]["seed"] != 42
    assert workflow["482"]["inputs"]["seed"] == 890110077
    assert workflow["510"]["inputs"]["image"] == "character.png"


@pytest.mark.asyncio
async def test_single_image_edit_retry_changes_pe_seed_and_preserves_uploaded_image():
    service = _service_with_format_failure_then_success()
    workflow = _workflow()
    service.client.upload_image = AsyncMock(
        return_value={"success": True, "filename": "uploaded.png"}
    )

    result = await service.edit_image_with_workflow(
        image_path="/source.png",
        prompt="edit prompt",
        workflow_json=json.dumps(workflow),
        node_mapping={
            "load_image_node_id": "510",
            "prompt_node_id": "516",
            "save_image_node_id": "515",
        },
    )

    submitted = result["submitted_workflow"]
    assert result["success"] is True
    assert result["prompt_id"] == "retry-prompt"
    assert submitted["519"]["inputs"]["seed"] != 42
    assert submitted["482"]["inputs"]["seed"] == 890110077
    assert submitted["510"]["inputs"]["image"] == "uploaded.png"


@pytest.mark.asyncio
async def test_non_rewrite_failure_does_not_retry():
    service = ComfyUIService.__new__(ComfyUIService)
    service.client = MagicMock()
    service.client.queue_prompt = AsyncMock()
    workflow = _workflow()
    result_before = {"success": False, "message": "ComfyUI connection timeout"}

    result = await service.retry_prompt_rewrite_format_failure(
        result_before,
        workflow,
        "515",
    )

    assert result is result_before
    assert workflow["519"]["inputs"]["seed"] == 42
    service.client.queue_prompt.assert_not_awaited()
