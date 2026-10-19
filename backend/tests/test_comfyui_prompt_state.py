"""Queue lookup failures and queue/history transitions are not missing prompts."""

import httpx
import pytest

from app.services.comfyui.client import ComfyUIClient


@pytest.mark.asyncio
async def test_failed_queue_lookup_with_empty_history_is_unknown(monkeypatch):
    client = ComfyUIClient(runtime_mode="standalone", base_url="http://localhost:8188")

    def respond(request):
        if request.url.path == "/queue":
            return httpx.Response(503)
        return httpx.Response(200, json={})

    monkeypatch.setattr(client, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    queue_info = await client.get_queue_info()

    assert (await client.get_prompt_state("prompt", queue_info=queue_info))["state"] == "unknown"


@pytest.mark.asyncio
async def test_prompt_entering_queue_during_history_lookup_is_queued(monkeypatch):
    client = ComfyUIClient(runtime_mode="standalone", base_url="http://localhost:8188")
    queue_reads = 0

    def respond(request):
        nonlocal queue_reads
        if request.url.path == "/queue":
            queue_reads += 1
            running = [] if queue_reads == 1 else [[1, "prompt", {}, {}]]
            return httpx.Response(200, json={"queue_running": running, "queue_pending": []})
        return httpx.Response(200, json={})

    monkeypatch.setattr(client, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond)))

    assert (await client.get_prompt_state("prompt"))["state"] == "queued"
    assert queue_reads == 2
