"""A ComfyUI queue number must never be mistaken for a prompt ID."""

from unittest.mock import AsyncMock

import pytest

from app.services.comfyui.client import ComfyUIClient


@pytest.mark.asyncio
async def test_cancel_running_prompt_uses_second_queue_field():
    client = ComfyUIClient(runtime_mode="standalone", base_url="http://localhost:8188")
    client.get_queue_info = AsyncMock(return_value={
        "queue_running": [[41, "running-prompt", {"1": {"class_type": "Video"}}, {}]],
        "queue_pending": [],
    })
    client.interrupt_execution = AsyncMock(return_value={"success": True})
    client.delete_from_queue = AsyncMock()

    result = await client.cancel_all_matching_tasks(["running-prompt"])

    assert result == {"deleted_from_queue": [], "interrupted": True, "not_found": []}
    client.interrupt_execution.assert_awaited_once()
    client.delete_from_queue.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_pending_prompt_uses_second_queue_field():
    client = ComfyUIClient(runtime_mode="standalone", base_url="http://localhost:8188")
    client.get_queue_info = AsyncMock(return_value={
        "queue_running": [],
        "queue_pending": [[42, "pending-prompt", {}, {}]],
    })
    client.interrupt_execution = AsyncMock()
    client.delete_from_queue = AsyncMock(return_value={"success": True})

    result = await client.cancel_all_matching_tasks(["pending-prompt", "missing-prompt"])

    assert result == {"deleted_from_queue": ["pending-prompt"],
                      "interrupted": False, "not_found": ["missing-prompt"]}
    client.delete_from_queue.assert_awaited_once_with("pending-prompt")
    client.interrupt_execution.assert_not_awaited()
