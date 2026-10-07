"""Asset upload retries stay below the worker and /prompt boundary."""
import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from app.services.comfyui.client import ComfyUIClient


class UploadHTTP:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []
        self.files = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def post(self, endpoint, *, files, data, timeout):
        filename, file, mime = files["image"]
        self.files.append(file)
        self.calls.append((endpoint, filename, file.read(), mime, dict(data), timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return httpx.Response(outcome, json={"name": filename} if outcome == 200 else {"error": "upstream"})


@pytest.mark.asyncio
@pytest.mark.parametrize("method,ext,mime,timeout", [
    ("upload_image", ".png", "image/png", 30.0),
    ("upload_video", ".mp4", "video/mp4", 120.0),
    ("upload_audio", ".wav", "audio/wav", 60.0),
])
@pytest.mark.parametrize("outcomes,delays,success,outcome", [
    ([502, 200], [2], True, "recovered"),
    ([502, 502, 200], [2, 4], True, "recovered"),
    ([502, 502, 502, 502], [2, 4, 8], False, "exhausted"),
    ([400], [], False, "non_retryable"),
    ([httpx.ReadTimeout("temporary timeout"), 200], [2], True, "recovered"),
])
async def test_common_upload_retry_and_full_file_request_invariance(
    method, ext, mime, timeout, outcomes, delays, success, outcome, tmp_path, monkeypatch, capsys,
):
    asset = tmp_path / ("same-asset" + ext)
    asset.write_bytes(b"complete asset payload\x00\x01")
    client = ComfyUIClient(runtime_mode="standalone")
    transport = UploadHTTP(outcomes)
    monkeypatch.setattr(client, "_client", lambda: transport)
    monkeypatch.setattr(ComfyUIClient, "base_url", property(lambda _: "http://comfy.test"))
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)

    result = await getattr(client, method)(str(asset))
    assert result["success"] is success
    assert result["upload_attempts"] == len(outcomes)
    assert result["upload_retries"] == len(outcomes) - 1
    assert [c.args[0] for c in sleep.await_args_list] == delays
    assert all(call == transport.calls[0] for call in transport.calls)
    assert transport.calls[0] == ("http://comfy.test/upload/image", asset.name, asset.read_bytes(), mime,
                                  {"type": "input", "overwrite": "true"}, timeout)
    assert len({id(file) for file in transport.files}) == len(outcomes)
    assert all(file.closed for file in transport.files)
    records = [json.loads(line.split("] ", 1)[1]) for line in capsys.readouterr().out.splitlines()]
    assert [r["attempt"] for r in records] == list(range(1, len(outcomes) + 1))
    assert all(r["max_attempts"] == 4 for r in records)
    assert [r["next_delay"] for r in records[:-1]] == delays
    assert all(r["error"] for r in records[:-1])
    assert records[-1]["outcome"] == outcome
    assert records[-1]["next_delay"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [408, 429, 500, 503, 504, 401, 403, 404])
async def test_status_allowlist_only(status, tmp_path, monkeypatch):
    path = tmp_path / "asset.png"
    path.write_bytes(b"asset")
    client = ComfyUIClient(runtime_mode="standalone")
    retry = status in {408, 429, 500, 503, 504}
    transport = UploadHTTP([status, 200] if retry else [status])
    monkeypatch.setattr(client, "_client", lambda: transport)
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    result = await client.upload_image(str(path))
    assert result["success"] is retry
    assert result["upload_attempts"] == (2 if retry else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [httpx.ConnectError("connection reset"), httpx.ReadError("connection reset"),
                                 httpx.WriteError("broken pipe"), httpx.RemoteProtocolError("server disconnected")])
async def test_transient_connection_failure_retries(error, tmp_path, monkeypatch):
    path = tmp_path / "asset.png"
    path.write_bytes(b"asset")
    client = ComfyUIClient(runtime_mode="standalone")
    transport = UploadHTTP([error, 200])
    monkeypatch.setattr(client, "_client", lambda: transport)
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    assert (await client.upload_image(str(path)))["upload_attempts"] == 2


@pytest.mark.asyncio
async def test_invalid_certificate_is_not_a_transient_connection_failure(tmp_path, monkeypatch):
    path = tmp_path / "asset.png"
    path.write_bytes(b"asset")
    client = ComfyUIClient(runtime_mode="standalone")
    transport = UploadHTTP([httpx.ConnectError("CERTIFICATE_VERIFY_FAILED")])
    monkeypatch.setattr(client, "_client", lambda: transport)
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)
    result = await client.upload_image(str(path))
    assert not result["success"] and result["upload_attempts"] == 1
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_malformed_success_and_local_missing_file_do_not_retry(tmp_path, monkeypatch):
    path = tmp_path / "asset.png"
    path.write_bytes(b"asset")
    client = ComfyUIClient(runtime_mode="standalone")
    transport = UploadHTTP([])
    async def malformed(endpoint, **kwargs):
        transport.calls.append(endpoint)
        return httpx.Response(200, content=b"{broken")
    transport.post = malformed
    monkeypatch.setattr(client, "_client", lambda: transport)
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)
    assert (await client.upload_image(str(path)))["upload_attempts"] == 1
    missing = await client.upload_video(str(tmp_path / "missing.mp4"))
    assert not missing["success"] and missing["upload_attempts"] == 0
    assert len(transport.calls) == 1
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_prompt_submission_never_uses_asset_retry(monkeypatch):
    client = ComfyUIClient(runtime_mode="standalone")
    post = AsyncMock(return_value=httpx.Response(502, text="upstream"))
    class PromptHTTP:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return None
    http = PromptHTTP()
    http.post = post
    monkeypatch.setattr(client, "_client", lambda: http)
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)
    assert not (await client.queue_prompt({"same": "workflow"}))["success"]
    post.assert_awaited_once()
    assert post.await_args.args[0].endswith("/prompt")
    sleep.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcomes,retried_file", [
    ([502, 200, 200, 200], "previous.mp4"),
    ([200, 502, 200, 200], "ordinary.png"),
    ([200, 200, 502, 200], "anchor.png"),
    ([502, 502, 502, 502], None),
])
async def test_recovered_upload_continues_same_execution_with_one_prompt_submission(
    outcomes, retried_file, db_session, tmp_path, monkeypatch,
):
    from app.models.workflow import Workflow
    from app.services.workflow_service import WorkflowService
    from app.services.comfyui.service import ComfyUIService

    WorkflowService(db_session).load_default_workflows()
    workflow = db_session.query(Workflow).filter(Workflow.type == "TEMPORAL_EXTEND", Workflow.is_system == True).one()
    paths = {}
    for filename in ("previous.mp4", "ordinary.png", "anchor.png"):
        path = tmp_path / filename
        path.write_bytes(filename.encode())
        paths[filename] = str(path)
    service = ComfyUIService()
    transport = UploadHTTP(outcomes)
    monkeypatch.setattr(service.client, "_client", lambda: transport)
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    queued = AsyncMock(return_value={"success": True, "prompt_id": "only-generation"})
    waited = AsyncMock(return_value={"success": True, "video_url": "native-output.mp4"})
    monkeypatch.setattr(service.client, "queue_prompt", queued)
    monkeypatch.setattr(service.client, "wait_for_result", waited)
    result = await service.generate_video_continuation_with_workflow(
        "fixed prompt", workflow.workflow_json, json.loads(workflow.node_mapping), paths["previous.mp4"],
        11.1, "test/output", capability="TEMPORAL_EXTEND",
        anchors=[{"image_path": paths["anchor.png"], "position": 135}],
        reference_image_paths=[paths["ordinary.png"]], require_native_output=True,
    )
    assert len(transport.calls) == 4
    if retried_file:
        assert result["success"]
        assert [call[1] for call in transport.calls].count(retried_file) == 2
        assert all([call[1] for call in transport.calls].count(name) == 1 for name in paths if name != retried_file)
        queued.assert_awaited_once()
        waited.assert_awaited_once()
        graph = queued.await_args.args[0]
        assert graph["66"]["inputs"]["video"] == "previous.mp4"
        assert graph["117"]["inputs"]["image"] == "anchor.png"
        assert json.loads(graph["116"]["inputs"]["keyframe_state"])["positions"] == [135]
    else:
        assert not result["success"]
        queued.assert_not_awaited()
        waited.assert_not_awaited()
