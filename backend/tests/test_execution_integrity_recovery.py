"""Task recovery/cancellation/projection slice: --noconftest, ephemeral DBs, fake I/O."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import httpx
from fastapi import FastAPI
from sqlalchemy.orm import Query, Session

import test_benchmark_image_isolation as images
from test_benchmark_image_isolation import isolated, reference_worker
import test_keyframe_reference_worker as keyframes
from test_keyframe_reference_recovery import recovery
import test_shot_video_execution as videos
from test_shot_video_execution import execution, worker


BACKEND = Path(__file__).resolve().parents[1]


def task_layer(db, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No application startup, live DB, LLM, or global ComfyUI access")

    def load(name, relative):
        spec = importlib.util.spec_from_file_location(name, BACKEND / relative)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        return module

    def stub(name, **attributes):
        module = ModuleType(name)
        module.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, module)
        return module

    for name in ("task_execution", "shot_video_execution", "keyframe_reference_contract"):
        if "app.services." + name not in sys.modules:
            load("app.services." + name, f"app/services/{name}.py")
    if "app.models.llm_log" not in sys.modules:
        logs = load("app.models.llm_log", "app/models/llm_log.py")
        logs.LLMLog.__table__.create(db.get_bind())
    repo = load("app.repositories.task", "app/repositories/task.py").TaskRepository
    monkeypatch.setattr(sys.modules["app.repositories"], "TaskRepository", repo, raising=False)
    monkeypatch.setattr(sys.modules["app.repositories"], "WorkflowRepository", forbidden, raising=False)
    for name, symbol in (("character", "Character"), ("scene", "Scene"), ("prop", "Prop")):
        stub(f"app.repositories.{name}_repository", **{symbol + "Repository": forbidden})
    stub("app.utils.time_utils", format_datetime=lambda value: value.isoformat() if value else None)
    if "app.services.prompt_builder" not in sys.modules:
        stub("app.services.prompt_builder", build_character_prompt=forbidden, build_scene_prompt=forbidden, get_style=forbidden)
    monkeypatch.setattr(sys.modules["app.core.config"], "get_settings", lambda: SimpleNamespace(COMFYUI_TIMEOUT=900, LLM_TIMEOUT=300))
    module = load("app.services.task_service", "app/services/task_service.py")
    service = module.TaskService(db)
    service.comfyui_service.get_queue_info = AsyncMock(side_effect=forbidden)
    service.comfyui_service.cancel_all_matching_tasks = AsyncMock(side_effect=forbidden)
    stub("app.api", __path__=[])
    stub("app.api.deps", get_task_repo=forbidden)
    monkeypatch.setattr(sys.modules["app.core.database"], "get_db", forbidden, raising=False)
    api = load("app.api.tasks", "app/api/tasks.py")
    return SimpleNamespace(module=module, service=service, api=api, repo=repo(db))


def reconcile(layer, task):
    return asyncio.run(layer.service.reconcile_active_tasks([task]))


async def task_request(layer, method, path):
    app = FastAPI()
    app.include_router(layer.api.router, prefix="/tasks")

    async def service():
        return layer.service

    async def repository():
        return layer.repo

    app.dependency_overrides[layer.api.get_task_service] = service
    app.dependency_overrides[layer.api.get_task_repo] = repository
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://isolated.test") as client:
        return await client.request(method, path)


def assert_shot_unchanged(state):
    state.db.refresh(state.shot)
    assert {key: getattr(state.shot, key) for key in state.before_shot} == state.before_shot
    assert not state.shot_updates


def test_live_worker_reconcile_does_not_enter_old_clip_recovery(execution, monkeypatch):
    state = execution
    layer = task_layer(state.db, monkeypatch)
    for name in ("_recover_completed_shot_video_prompt", "_recover_completed_single_shot_video_prompt",
                 "_enqueue_remaining_shot_video_clip"):
        monkeypatch.setattr(layer.service, name, Mock(side_effect=AssertionError("Legacy dispatch forbidden")))
    wait = state.client.wait_for_result.side_effect
    observations = []

    async def concurrently_poll(cid, graph, *args, **kwargs):
        with Session(state.engine) as db:
            task = db.get(state.models.Task, "task")
            assert await layer.service.reconcile_active_tasks([task], db=db) == 0
            assert task.status == "running"
            observations.append(cid)
        return await wait(cid, graph, *args, **kwargs)

    state.client.wait_for_result.side_effect = concurrently_poll
    task = videos.run(state)
    assert task.status == "completed", task.error_message
    assert observations == ["queued-1", "queued-2"]
    assert state.execution.HEARTBEAT_SECONDS == 15 and state.execution.LEASE_SECONDS == 120
    layer.service.comfyui_service.get_queue_info.assert_not_awaited()
    assert_shot_unchanged(state)


def test_stale_strict_run_is_terminal_before_frozen_poll_and_keeps_detached_output(execution, monkeypatch):
    state = execution
    task, _, handle = state.execution.claim_video_execution(state.db, "task")
    slot = videos.complete_slot(state, handle, 1)
    history = json.loads(Path(slot["receipt"]["history"]["path"]).read_text())
    videos.change_task(state, heartbeat_at=datetime.utcnow() - timedelta(seconds=121))
    layer = task_layer(state.db, monkeypatch)
    endpoints = []

    async def poll(cid):
        with Session(state.engine) as db:
            stopped = db.get(state.models.Task, "task")
            assert stopped.status == "failed"
            assert json.loads(stopped.metadata_json)["video_run"]["phase"] == "failed"
        assert cid == slot["submission"]["prompt_id"]
        return {"state": "completed", "history": history}

    monkeypatch.setattr(state.execution, "frozen_client", lambda endpoint: (
        endpoints.append(endpoint) or SimpleNamespace(get_prompt_state=poll)))
    assert reconcile(layer, task) == 1
    state.db.refresh(task)
    assert task.status == "failed" and not task.result_url
    observations = json.loads(task.metadata_json)["video_observations"]
    assert any(item["kind"] == "recovery-output" and item["attachment"] == "detached" for item in observations)
    assert endpoints == [slot["submission"]["endpoint"]]
    assert reconcile(layer, task) == 0
    state.client.queue_prompt.assert_not_awaited()
    state.storage.merge_videos.assert_not_awaited()
    assert_shot_unchanged(state)


@pytest.mark.parametrize("handled", [False, True, RuntimeError("bad execution metadata")])
def test_integrity_dispatch_never_falls_back_even_on_exception(execution, monkeypatch, handled):
    state = execution
    layer = task_layer(state.db, monkeypatch)
    task = state.task
    task.created_at = task.started_at = datetime.utcnow() - timedelta(days=1)
    state.db.commit()
    hook = AsyncMock(side_effect=handled) if isinstance(handled, Exception) else AsyncMock(return_value=handled)
    monkeypatch.setattr(layer.module, "reconcile_video_execution", hook)
    assert reconcile(layer, task) == int(handled is True or isinstance(handled, Exception))
    layer.service.comfyui_service.get_queue_info.assert_not_awaited()
    state.client.get_prompt_state.assert_not_awaited()
    assert task.status == ("failed" if isinstance(handled, Exception) else "pending")
    assert_shot_unchanged(state)


@pytest.mark.parametrize("purpose", ["production", "benchmark"])
def test_direct_video_legacy_entrypoints_cannot_backfill_or_continue(execution, monkeypatch, purpose):
    state = execution
    data = json.loads(state.task.metadata_json)
    data["execution_purpose"] = purpose
    state.task.metadata_json = json.dumps(data)
    state.db.commit()
    layer = task_layer(state.db, monkeypatch)
    before = layer.service._task_snapshot(state.task)
    assert asyncio.run(layer.service._recover_completed_shot_video_prompt(state.task, {"outputs": {"out": {}}}, state.db)) is False
    assert asyncio.run(layer.service._recover_completed_single_shot_video_prompt(state.task, {"outputs": {"out": {}}}, state.db)) is False
    layer.service._enqueue_remaining_shot_video_clip(state.task, 2, state.db)
    assert layer.service._task_snapshot(state.task) == before
    state.storage.download_video.assert_not_awaited()
    assert_shot_unchanged(state)


@pytest.mark.parametrize("all_tasks", [False, True])
def test_cancellation_fences_every_child_before_remote_await(execution, monkeypatch, all_tasks):
    state = execution
    Task = state.models.Task
    parent = Task(id="parent", name="Batch", type="shot_video_batch", status="running",
                  metadata_json='{"execution_purpose":"benchmark"}')
    child = Task(id="child", name="Waiting", type="shot_video", status="pending", parent_task_id="parent",
                 metadata_json='{"execution_purpose":"benchmark"}', shot_id="shot", chapter_id="chapter")
    state.db.add_all([parent, child])
    state.task.parent_task_id = "parent"
    state.db.commit()
    task, _, handle = state.execution.claim_video_execution(state.db, "task")
    videos.complete_slot(state, handle, 1)
    layer = task_layer(state.db, monkeypatch)
    polled = []

    async def cancel(cids):
        with Session(state.engine) as db:
            assert {db.get(Task, value).status for value in ("task", "parent", "child")} == {"cancelled"}
        polled.extend(cids)
        raise RuntimeError("Remote cancel unavailable")

    monkeypatch.setattr(layer.module, "frozen_keyframe_client", lambda endpoint: SimpleNamespace(cancel_all_matching_tasks=cancel))
    result = asyncio.run(layer.service.cancel_all_tasks() if all_tasks else layer.service.cancel_task("parent"))
    assert result["success"] and result["details"]["cancelled_count"] == 3
    assert polled
    before_polls = list(polled)
    assert json.loads(state.db.get(Task, "parent").metadata_json)["cancellation"]["state"] == "unknown"
    assert asyncio.run(task_request(layer, "DELETE", "/tasks/parent")).status_code == 409
    assert polled == before_polls
    assert_shot_unchanged(state)


@pytest.mark.parametrize("change", ["completed", "claim", "run", "sibling"])
def test_cancel_cas_cannot_overwrite_newer_actor_or_metadata(execution, monkeypatch, change):
    state = execution
    state.execution.claim_video_execution(state.db, "task")
    layer = task_layer(state.db, monkeypatch)
    update, fired = Query.update, []

    def race(query, values, *args, **kwargs):
        if not fired and query.column_descriptions[0]["entity"] is state.models.Task and values.get("status") == "cancelled":
            fired.append(True)
            with Session(state.engine) as db:
                task = db.get(state.models.Task, "task")
                if change == "completed":
                    task.status, task.result_url = "completed", "/winner.mp4"
                elif change == "claim":
                    task.claim_token, task.attempt = "new-owner", 9
                else:
                    data = json.loads(task.metadata_json)
                    if change == "run":
                        data["video_run"]["run_id"] = "replacement-run"
                    else:
                        data["sibling"] = {"keep": True}
                    task.metadata_json = json.dumps(data)
                db.commit()
        return update(query, values, *args, **kwargs)

    monkeypatch.setattr(Query, "update", race)
    result = asyncio.run(layer.service.cancel_task("task"))
    assert fired and result["details"]["cancelled_count"] == 0
    assert result["success"] is False and result["status_code"] == 409
    state.db.refresh(state.task)
    assert state.task.status == ("completed" if change == "completed" else "running")
    if change == "sibling":
        assert json.loads(state.task.metadata_json)["sibling"] == {"keep": True}
    assert_shot_unchanged(state)


@pytest.mark.parametrize("method,path", [("DELETE", "/tasks/task"), ("POST", "/tasks/task/cancel")])
@pytest.mark.parametrize("change", ["metadata", "heartbeat", "completed"])
def test_real_endpoint_cancel_cas_conflict_cannot_authorize_delete(execution, monkeypatch, method, path, change):
    state = execution
    _, _, handle = state.execution.claim_video_execution(state.db, "task")
    videos.complete_slot(state, handle, 1)
    layer = task_layer(state.db, monkeypatch)
    original_update, raced = Query.update, []

    def race(query, values, *args, **kwargs):
        if not raced and query.column_descriptions[0]["entity"] is state.models.Task and values.get("status") == "cancelled":
            raced.append(True)
            with Session(state.engine) as db:
                current = db.get(state.models.Task, "task")
                if change == "metadata":
                    data = json.loads(current.metadata_json)
                    data["new_evidence"] = {"keep": True}
                    current.metadata_json = json.dumps(data)
                elif change == "heartbeat":
                    current.heartbeat_at = datetime.utcnow() + timedelta(seconds=1)
                else:
                    current.status, current.result_url = "completed", "/winner.mp4"
                db.commit()
        return original_update(query, values, *args, **kwargs)

    monkeypatch.setattr(Query, "update", race)
    remote = AsyncMock(side_effect=AssertionError("Losing cancellation cannot orphan remote work"))
    monkeypatch.setattr(layer.module, "frozen_keyframe_client", lambda endpoint: SimpleNamespace(cancel_all_matching_tasks=remote))
    response = asyncio.run(task_request(layer, method, path))
    assert response.status_code == 409, response.text
    state.db.expire_all()
    task = state.db.get(state.models.Task, "task")
    assert task is not None and task.status == ("completed" if change == "completed" else "running")
    assert json.loads(task.metadata_json)["video_run"]["clips"]["1"]["receipt"]
    remote.assert_not_awaited()
    assert_shot_unchanged(state)


@pytest.mark.parametrize("change", ["claim", "late-evidence", "heartbeat"])
def test_delete_cas_uses_terminal_snapshot_captured_before_remote_await(execution, monkeypatch, change):
    state = execution
    _, _, handle = state.execution.claim_video_execution(state.db, "task")
    videos.complete_slot(state, handle, 1)
    layer = task_layer(state.db, monkeypatch)

    async def remote(cids):
        with Session(state.engine) as db:
            current = db.get(state.models.Task, "task")
            assert current.status == "cancelled"
            if change == "claim":
                current.status, current.claim_token, current.attempt = "running", "new-claim", 8
            elif change == "late-evidence":
                data = json.loads(current.metadata_json)
                data["late_ack"] = {"prompt_id": "keep-this-ack"}
                current.metadata_json = json.dumps(data)
            else:
                current.heartbeat_at = datetime.utcnow() + timedelta(seconds=1)
            db.commit()
        return {"deleted_from_queue": cids}

    monkeypatch.setattr(layer.module, "frozen_keyframe_client", lambda endpoint: SimpleNamespace(cancel_all_matching_tasks=remote))
    response = asyncio.run(task_request(layer, "DELETE", "/tasks/task"))
    assert response.status_code == 409, response.text
    state.db.expire_all()
    task = state.db.get(state.models.Task, "task")
    assert task is not None and task.status == ("running" if change == "claim" else "cancelled")
    if change == "late-evidence":
        assert json.loads(task.metadata_json)["late_ack"]["prompt_id"] == "keep-this-ack"
    assert_shot_unchanged(state)


@pytest.mark.parametrize("confirmed", [False, True])
def test_active_delete_requires_successful_fence_and_remote_outcome(execution, monkeypatch, confirmed):
    state = execution
    _, _, handle = state.execution.claim_video_execution(state.db, "task")
    slot = videos.complete_slot(state, handle, 1)
    layer = task_layer(state.db, monkeypatch)
    remote = AsyncMock(return_value={"deleted_from_queue": [slot["submission"]["prompt_id"]]} if confirmed else {"error": "Still running"})
    monkeypatch.setattr(layer.module, "frozen_keyframe_client", lambda endpoint: SimpleNamespace(cancel_all_matching_tasks=remote))
    response = asyncio.run(task_request(layer, "DELETE", "/tasks/task"))
    assert response.status_code == (200 if confirmed else 409), response.text
    with Session(state.engine) as db:
        current = db.get(state.models.Task, "task")
        assert (current is None) is confirmed
        if not confirmed:
            assert current.status == "cancelled" and current.metadata_json
            saved = layer.service._task_snapshot(current)
            assert json.loads(current.metadata_json)["cancellation"]["state"] == "unknown"
            second_layer = SimpleNamespace(api=layer.api, service=layer.service, repo=type(layer.repo)(db))
            second = asyncio.run(task_request(second_layer, "DELETE", "/tasks/task"))
            assert second.status_code == 409, second.text
            db.refresh(current)
            assert layer.service._task_snapshot(current) == saved
    remote.assert_awaited_once_with([slot["submission"]["prompt_id"]])
    assert Path(slot["receipt"]["path"]).is_file()
    assert_shot_unchanged(state)


@pytest.mark.parametrize("remote_state", ["queued", "unknown", "missing", "completed"])
def test_remote_not_found_cannot_alone_authorize_active_delete(execution, monkeypatch, remote_state):
    state = execution
    _, _, handle = state.execution.claim_video_execution(state.db, "task")
    slot = videos.complete_slot(state, handle, 1)
    layer = task_layer(state.db, monkeypatch)
    cid = slot["submission"]["prompt_id"]
    remote = SimpleNamespace(cancel_all_matching_tasks=AsyncMock(return_value={"not_found": [cid]}),
                             get_prompt_state=AsyncMock(return_value={"state": remote_state}))
    monkeypatch.setattr(layer.module, "frozen_keyframe_client", lambda endpoint: remote)
    response = asyncio.run(task_request(layer, "DELETE", "/tasks/task"))
    assert response.status_code == (200 if remote_state == "completed" else 409), response.text
    remote.get_prompt_state.assert_awaited_once_with(cid)
    with Session(state.engine) as db:
        assert (db.get(state.models.Task, "task") is None) is (remote_state == "completed")
        if remote_state != "completed":
            second_layer = SimpleNamespace(api=layer.api, service=layer.service, repo=type(layer.repo)(db))
            assert asyncio.run(task_request(second_layer, "DELETE", "/tasks/task")).status_code == 409
    remote.cancel_all_matching_tasks.assert_awaited_once_with([cid])
    remote.get_prompt_state.assert_awaited_once_with(cid)
    assert Path(slot["receipt"]["path"]).is_file()
    assert_shot_unchanged(state)


@pytest.mark.parametrize("execution", [{"purpose": "benchmark", "only": 2}, {"purpose": "production", "only": 2}], indirect=True)
@pytest.mark.parametrize("confirmed", [False, True])
def test_parallel_delete_reads_persisted_pending_fence_without_remote_actions(execution, monkeypatch, confirmed):
    state = execution
    _, _, handle = state.execution.claim_video_execution(state.db, "task")
    slot = videos.complete_slot(state, handle, 2)
    proof = json.loads(state.task.metadata_json)
    layer = task_layer(state.db, monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()

    async def remote(cids):
        entered.set()
        await release.wait()
        return {"deleted_from_queue": cids} if confirmed else {"error": "GPU may still be running"}

    cancel = AsyncMock(side_effect=remote)
    monkeypatch.setattr(layer.module, "frozen_keyframe_client", lambda endpoint: SimpleNamespace(cancel_all_matching_tasks=cancel))

    async def requests():
        first = asyncio.create_task(task_request(layer, "DELETE", "/tasks/task"))
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            with Session(state.engine) as db:
                task = db.get(state.models.Task, "task")
                data = json.loads(task.metadata_json)
                assert task.status == "cancelled" and data["cancellation"]["state"] == "pending"
                assert {key: value for key, value in data.items() if key != "cancellation"} == proof
                saved = layer.service._task_snapshot(task)
                reader = SimpleNamespace(api=layer.api, service=layer.service, repo=type(layer.repo)(db))
                second = await task_request(reader, "DELETE", "/tasks/task")
                assert second.status_code == 409, second.text
                db.refresh(task)
                assert layer.service._task_snapshot(task) == saved
                assert cancel.await_count == 1
        finally:
            release.set()
        response = await first
        assert response.status_code == (200 if confirmed else 409), response.text
        if not confirmed:
            with Session(state.engine) as db:
                reader = SimpleNamespace(api=layer.api, service=layer.service, repo=type(layer.repo)(db))
                assert (await task_request(reader, "DELETE", "/tasks/task")).status_code == 409
                task = db.get(state.models.Task, "task")
                assert json.loads(task.metadata_json)["cancellation"]["state"] == "unknown"

    asyncio.run(requests())
    cancel.assert_awaited_once_with([slot["submission"]["prompt_id"]])
    assert Path(slot["receipt"]["path"]).is_file()
    assert_shot_unchanged(state)


@pytest.mark.parametrize("execution", [{"purpose": "benchmark"}, {"purpose": "production", "only": 2}], indirect=True)
def test_cancellation_outcome_cas_preserves_concurrent_root_counter_and_proof(execution, monkeypatch):
    state = execution
    _, _, handle = state.execution.claim_video_execution(state.db, "task")
    slot = videos.complete_slot(state, handle, state.run_request["only_window_index"] or 1)
    layer = task_layer(state.db, monkeypatch)
    proof = json.loads(state.task.metadata_json)

    async def remote(cids):
        with Session(state.engine) as db:
            current = db.get(state.models.Task, "task")
            data = json.loads(current.metadata_json)
            assert data["cancellation"]["state"] == "pending"
            data["root_counter"] = data.get("root_counter", 0) + 1
            current.metadata_json = json.dumps(data)
            db.commit()
        return {"deleted_from_queue": cids}

    cancel = AsyncMock(side_effect=remote)
    monkeypatch.setattr(layer.module, "frozen_keyframe_client", lambda endpoint: SimpleNamespace(cancel_all_matching_tasks=cancel))
    assert asyncio.run(task_request(layer, "DELETE", "/tasks/task")).status_code == 409
    with Session(state.engine) as db:
        current = db.get(state.models.Task, "task")
        data = json.loads(current.metadata_json)
        assert data["root_counter"] == 1 and data["cancellation"]["state"] == "pending"
        assert {key: value for key, value in data.items() if key not in {"cancellation", "root_counter"}} == proof
        reader = SimpleNamespace(api=layer.api, service=layer.service, repo=type(layer.repo)(db))
        assert asyncio.run(task_request(reader, "DELETE", "/tasks/task")).status_code == 409
        assert json.loads(db.get(state.models.Task, "task").metadata_json) == data
    cancel.assert_awaited_once_with([slot["submission"]["prompt_id"]])
    assert_shot_unchanged(state)


@pytest.mark.parametrize("raw", ["{malformed", "[]", "null", '{"bad": NaN}',
                                  '{"execution_purpose":[]}', '{"execution":{}}',
                                  '{"cancellation":null}', '{"cancellation":[]}',
                                  '{"cancellation":{"state":"confirmed"}}'])
@pytest.mark.parametrize("status", ["running", "cancelled"])
def test_delete_malformed_cancellation_metadata_is_read_only_and_fail_closed(execution, monkeypatch, raw, status):
    state = execution
    state.task.status, state.task.metadata_json = status, raw
    state.db.commit()
    layer = task_layer(state.db, monkeypatch)
    before = layer.service._task_snapshot(state.task)
    factory = Mock(side_effect=AssertionError("Malformed cancellation must not cause remote actions"))
    monkeypatch.setattr(layer.module, "frozen_keyframe_client", factory)
    for _ in range(2):
        response = asyncio.run(task_request(layer, "DELETE", "/tasks/task"))
        assert response.status_code == 409, response.text
        state.db.refresh(state.task)
        assert layer.service._task_snapshot(state.task) == before
    factory.assert_not_called()
    layer.service.comfyui_service.cancel_all_matching_tasks.assert_not_awaited()
    assert_shot_unchanged(state)


def test_confirmed_cancellation_allows_later_stable_delete_without_new_remote_work(execution, monkeypatch):
    state = execution
    _, _, handle = state.execution.claim_video_execution(state.db, "task")
    slot = videos.complete_slot(state, handle, 1)
    layer = task_layer(state.db, monkeypatch)
    proof = json.loads(state.task.metadata_json)
    cancel = AsyncMock(return_value={"deleted_from_queue": [slot["submission"]["prompt_id"]]})
    monkeypatch.setattr(layer.module, "frozen_keyframe_client", lambda endpoint: SimpleNamespace(cancel_all_matching_tasks=cancel))
    assert asyncio.run(task_request(layer, "POST", "/tasks/task/cancel")).status_code == 200
    with Session(state.engine) as db:
        task = db.get(state.models.Task, "task")
        data = json.loads(task.metadata_json)
        assert data["cancellation"]["state"] == "confirmed"
        assert {key: value for key, value in data.items() if key != "cancellation"} == proof
        reader = SimpleNamespace(api=layer.api, service=layer.service, repo=type(layer.repo)(db))
        assert asyncio.run(task_request(reader, "DELETE", "/tasks/task")).status_code == 200
    cancel.assert_awaited_once_with([slot["submission"]["prompt_id"]])
    assert Path(slot["receipt"]["path"]).is_file()
    assert_shot_unchanged(state)


@pytest.mark.parametrize("status", ["failed", "completed", "cancelled"])
def test_explicit_stable_terminal_delete_is_allowed_without_deleting_media(execution, monkeypatch, status):
    state = execution
    _, _, handle = state.execution.claim_video_execution(state.db, "task")
    slot = videos.complete_slot(state, handle, 1)
    videos.change_task(state, status=status)
    state.db.refresh(state.task)
    layer = task_layer(state.db, monkeypatch)
    response = asyncio.run(task_request(layer, "DELETE", "/tasks/task"))
    assert response.status_code == 200, response.text
    with Session(state.engine) as db:
        assert db.get(state.models.Task, "task") is None
    assert Path(slot["receipt"]["path"]).is_file()
    assert_shot_unchanged(state)


def test_terminal_delete_is_conditional_at_sql_write_not_just_a_read_check(execution, monkeypatch):
    state = execution
    videos.change_task(state, status="failed")
    state.db.refresh(state.task)
    layer = task_layer(state.db, monkeypatch)
    original_delete = Query.delete
    raced = []

    def race(query, *args, **kwargs):
        if not raced:
            raced.append(True)
            videos.change_task(state, status="running", claim_token="replacement")
        return original_delete(query, *args, **kwargs)

    monkeypatch.setattr(Query, "delete", race)
    response = asyncio.run(task_request(layer, "DELETE", "/tasks/task"))
    assert response.status_code == 409
    state.db.refresh(state.task)
    assert state.task.status == "running" and state.task.claim_token == "replacement"
    assert_shot_unchanged(state)


@pytest.mark.parametrize("entrypoint", ["multi", "single", "continue", "reconcile"])
@pytest.mark.parametrize("race", [None, "new-owner", "cancelled", "completed", "new-claim"])
def test_legacy_video_has_no_download_or_merge_race_window_and_requires_fresh_run(execution, monkeypatch, entrypoint, race):
    state = execution
    task = state.task
    task.status, task.metadata_json = "running", '{"old":"keep"}'
    task.comfyui_prompt_id, task.result_url = "old-cid", "/previous-task-result.mp4"
    task.started_at = task.updated_at = datetime.utcnow() - timedelta(seconds=2000)
    clips = [{"window_index": index, "status": "SUCCEEDED", "video_url": f"/known-{index}.mp4",
              "prompt_id": "old-cid" if index == 2 else "older-cid"} for index in (1, 2)]
    task.video_director_clips = json.dumps(clips) if entrypoint != "single" else None
    state.shot.video_status = "generating"
    state.db.commit()
    history = {"prompt": [0, "old-cid", {"out": {"class_type": "SaveVideo"}}],
               "status": {"completed": True, "status_str": "success"},
               "outputs": {"out": {"videos": [{"filename": "known.mp4", "type": "output"}]}}}
    layer = task_layer(state.db, monkeypatch)
    old_merge = AsyncMock(side_effect=AssertionError("Old merger publishes before returning"))
    monkeypatch.setattr(state.module, "merge_video_director_clip_videos", old_merge)
    state.storage.download_video.side_effect = AssertionError("Unproven legacy recovery must not download or publish")
    enqueue = Mock(side_effect=AssertionError("Legacy video must not be re-executed"))
    monkeypatch.setattr(state.module, "enqueue_shot_video_task", enqueue)
    layer.service.comfyui_service.get_queue_info = AsyncMock(return_value={})
    state.client.get_prompt_state = AsyncMock(return_value={"state": "completed", "history": history})
    before = {column.key: getattr(state.shot, column.key) for column in state.models.Shot.__table__.columns}
    original_update, raced = Query.update, []

    def concurrent_actor(query, values, *args, **kwargs):
        if race and not raced and query.column_descriptions[0]["entity"] is state.models.Task and values.get("status") == "failed":
            raced.append(True)
            with Session(state.engine) as db:
                current = db.get(state.models.Task, "task")
                if race == "new-owner":
                    shot = db.get(state.models.Shot, "shot")
                    shot.video_task_id, shot.video_url = "replacement", "/replacement.mp4"
                    shot.video_director_plan = '{"new_plan":true}'
                    before.update(video_task_id="replacement", video_url="/replacement.mp4", video_director_plan=shot.video_director_plan)
                elif race == "new-claim":
                    current.claim_token, current.attempt = "replacement", 9
                else:
                    current.status, current.error_message = race, "Winner's decision"
                db.commit()
        return original_update(query, values, *args, **kwargs)

    monkeypatch.setattr(Query, "update", concurrent_actor)
    if entrypoint == "continue":
        layer.service._enqueue_remaining_shot_video_clip(task, 2, state.db)
    elif entrypoint == "reconcile":
        reconcile(layer, task)
    else:
        method = (layer.service._recover_completed_shot_video_prompt if entrypoint == "multi"
                  else layer.service._recover_completed_single_shot_video_prompt)
        asyncio.run(method(task, history, state.db))
    state.db.refresh(task)
    assert task.status == (race if race in {"cancelled", "completed"} else "running" if race == "new-claim" else "failed")
    if task.status == "failed":
        assert "LEGACY_VIDEO_RUN_UNVERIFIED" in task.error_message and "Fresh complete" in task.current_step
    assert task.result_url == "/previous-task-result.mp4" and task.comfyui_prompt_id == "old-cid"
    if entrypoint != "continue":
        evidence = json.loads(task.metadata_json)["legacy_video_observations"][0]
        assert evidence["history"] == history and evidence["attachment"] == "detached"
        assert evidence["prompt_id"] == "old-cid"
    state.db.refresh(state.shot)
    for key in before.keys() - {"video_status", "updated_at"}:
        assert getattr(state.shot, key) == before[key]
    old_merge.assert_not_awaited()
    state.storage.download_video.assert_not_awaited()
    enqueue.assert_not_called()
    evidence = layer.service._task_snapshot(task)
    assert layer.service.retry_task(task.id)["status_code"] == 400
    assert layer.service._task_snapshot(task) == evidence


@pytest.mark.parametrize("terminal", ["cancelled", "failed"])
def test_direct_worker_late_ack_after_taskservice_terminal_is_detached(execution, monkeypatch, terminal):
    state = execution
    layer = task_layer(state.db, monkeypatch)
    queued = state.client.queue_prompt.side_effect

    async def cancel_during_submission(graph):
        with Session(state.engine) as db:
            if terminal == "cancelled":
                assert (await layer.service.cancel_task("task", db=db))["success"]
            else:
                assert layer.service._transition_task_terminal(db.get(state.models.Task, "task"), db,
                                                               message="Submission interrupted", step="failed")
        return await queued(graph)

    state.client.queue_prompt.side_effect = cancel_during_submission
    task = videos.run(state)
    assert task.status == terminal
    data = json.loads(task.metadata_json)
    ack = next(item for item in data["video_observations"] if item["kind"] == "ack")
    assert json.loads(Path(ack["evidence"]["path"]).read_text())["prompt_id"] == "queued-1"
    assert ack["attachment"] == "detached"
    assert not task.result_url and data["video_run"]["clips"]["1"]["receipt"] is None
    assert_shot_unchanged(state)


def test_failed_finalizer_cannot_overwrite_completed_winner(execution, monkeypatch):
    state = execution
    task, _, handle = state.execution.claim_video_execution(state.db, "task")
    layer = task_layer(state.db, monkeypatch)
    expected = layer.service._task_snapshot(task)
    videos.change_task(state, status="completed", result_url="/winner.mp4", error_message="Winner")
    assert not layer.service._transition_task_terminal(task, state.db, message="Late failure", step="failed", expected=expected)
    assert not state.execution.fail_execution(state.db, handle, "Late worker failure")
    state.db.refresh(task)
    assert (task.status, task.result_url, task.error_message) == ("completed", "/winner.mp4", "Winner")
    assert_shot_unchanged(state)


@pytest.mark.parametrize("endpoint", [None, "", "   "])
def test_cancel_missing_frozen_endpoint_never_uses_global_comfy(execution, monkeypatch, endpoint):
    state = execution
    task, _, handle = state.execution.claim_video_execution(state.db, "task")
    videos.complete_slot(state, handle, 1)
    data = json.loads(task.metadata_json)
    data["video_run"]["clips"]["1"]["submission"]["endpoint"] = endpoint
    task.metadata_json = json.dumps(data)
    state.db.commit()
    layer = task_layer(state.db, monkeypatch)
    result = asyncio.run(layer.service.cancel_task("task"))
    assert result["details"]["tasks"][0]["diagnostic"] == "CANCELLATION_SUBMISSION_UNVERIFIED"
    assert task.status == "cancelled"
    layer.service.comfyui_service.cancel_all_matching_tasks.assert_not_awaited()
    assert_shot_unchanged(state)


@pytest.mark.parametrize("execution", [{"purpose": "production"}, {"purpose": "benchmark"}], indirect=True)
@pytest.mark.parametrize("status", ["failed", "completed"])
def test_strict_retry_rejects_before_erasing_any_attempt_fields(execution, monkeypatch, status):
    state = execution
    state.execution.claim_video_execution(state.db, "task")
    videos.change_task(state, status=status, error_message="Original", result_url="/archived.mp4",
                       workflow_json='{"out":{}}', comfyui_prompt_id="known", completed_at=datetime(2026, 1, 1))
    state.db.refresh(state.task)
    layer = task_layer(state.db, monkeypatch)
    before = layer.service._task_snapshot(state.task)
    result = layer.service.retry_task("task")
    assert result["status_code"] == 400 and not result["success"]
    assert layer.service._task_snapshot(state.task) == before
    assert_shot_unchanged(state)


@pytest.mark.parametrize("execution", [{"purpose": "production"}], indirect=True)
@pytest.mark.parametrize("changed_target", [None, "owner", "plan", "status"])
def test_production_cancel_settles_only_matching_owner_run_and_status(execution, monkeypatch, changed_target):
    state = execution
    state.shot.video_status = "generating"
    state.db.commit()
    state.execution.claim_video_execution(state.db, "task")
    with Session(state.engine) as db:
        shot = db.get(state.models.Shot, "shot")
        if changed_target == "owner":
            shot.video_task_id = "new-owner"
        elif changed_target == "plan":
            shot.video_director_plan = '{"user_edit":true}'
            shot.video_director_plan_revision += 1
        elif changed_target == "status":
            shot.video_status = "completed"
        db.commit()
    state.db.refresh(state.shot)
    before = {column.key: getattr(state.shot, column.key) for column in state.models.Shot.__table__.columns}
    state.shot_updates.clear()
    layer = task_layer(state.db, monkeypatch)
    assert asyncio.run(layer.service.cancel_task("task"))["success"]
    state.db.refresh(state.shot)
    for key in before.keys() - {"updated_at", "video_status"}:
        assert getattr(state.shot, key) == before[key]
    assert state.shot.video_status == ("failed" if changed_target is None else before["video_status"])
    assert len(state.shot_updates) == int(changed_target is None)


@pytest.mark.parametrize("execution", [{"purpose": "production"}, {"purpose": "production", "only": 2}], indirect=True)
def test_preclaim_cancel_uses_shared_settlement_without_claiming_clip_assets(execution, monkeypatch):
    state = execution
    state.shot.video_status = "generating"
    state.db.commit()
    before = {column.key: getattr(state.shot, column.key) for column in state.models.Shot.__table__.columns}
    state.shot_updates.clear()
    layer = task_layer(state.db, monkeypatch)
    assert "video_run" not in json.loads(state.task.metadata_json)
    result = asyncio.run(layer.service.cancel_task("task"))
    assert result["success"] and state.task.status == "cancelled"
    state.db.refresh(state.shot)
    whole = state.run_request["only_window_index"] is None
    assert state.shot.video_status == ("failed" if whole else "generating")
    assert len(state.shot_updates) == int(whole)
    for key in before.keys() - {"video_status", "updated_at"}:
        assert getattr(state.shot, key) == before[key]


@pytest.mark.parametrize("kind", ["shot", "keyframe"])
def test_benchmark_hooks_reconcile_archive_get_retry_cancel_never_write_shot(isolated, monkeypatch, kind):
    state = isolated
    before = images.shot_columns(state)
    if kind == "shot":
        images.create_image(state)
    else:
        keyframes.create(state, execution_purpose="benchmark", workflow_id="workflow")
    captured = []
    state.hooks["download"] = lambda: captured.append(keyframes.saved(state).task)
    first = images.run_image(state) if kind == "shot" else keyframes.run(state)
    assert first.task.status == "completed", first.task.error_message
    images.restore_task(state, captured[0])
    with state.sessions() as db:
        task = db.get(state.Task, state.task_id)
        layer = task_layer(db, monkeypatch)
        history = images.history_for(state, task)
        polls = []
        endpoint = (state.execution.execution_record(task)["shot_image"]["endpoint"] if kind == "shot"
                    else state.contracts.read_contract(task)["endpoint"])

        def client(url):
            assert url == endpoint
            polls.append(url)
            return SimpleNamespace(get_prompt_state=AsyncMock(return_value={"state": "completed", "history": history}))

        monkeypatch.setattr(layer.module, "frozen_keyframe_client", client)
        assert reconcile(layer, task) == 1
        assert task.status == "completed"
        stored = (state.execution.execution_record(task) if kind == "shot" else state.contracts.read_contract(task))
        assert stored["result"]["attachment"] == "archived"
        recover = (layer.service._recover_completed_shot_image_prompt if kind == "shot" else layer.service._recover_completed_keyframe_prompt)
        downloads = len(state.http_calls)
        assert asyncio.run(recover(task, None, db)) is True
        assert len(state.http_calls) == downloads and polls == [endpoint]
        evidence = layer.service._task_snapshot(task)
        assert layer.service.retry_task(task.id)["status_code"] == 400
        assert asyncio.run(layer.service.cancel_task(task.id))["details"]["skipped"]
        assert layer.service._task_snapshot(task) == evidence
        payloads = [layer.service.format_task_list([task], {}, {}, {}, shots={"shot": db.get(state.Shot, "shot")})[0],
                    layer.service.format_task_detail(task), asyncio.run(layer.api.get_task_workflow(task.id, layer.repo))["data"]]
        assert all(item["execution_purpose"] == "benchmark" for item in payloads)
    assert images.shot_columns(state) == before and not state.shot_writes


@pytest.mark.parametrize("kind", ["shot", "keyframe"])
@pytest.mark.parametrize("during", ["poll", "download"])
def test_benchmark_recovery_cancel_race_retains_terminal_and_never_writes_shot(isolated, monkeypatch, kind, during):
    state = isolated
    before = images.shot_columns(state)
    if kind == "shot":
        images.create_image(state)
    else:
        keyframes.create(state, execution_purpose="benchmark", workflow_id="workflow")
    captured = []
    state.hooks["download"] = lambda: captured.append(keyframes.saved(state).task)
    first = images.run_image(state) if kind == "shot" else keyframes.run(state)
    assert first.task.status == "completed"
    images.restore_task(state, captured[0])
    with state.sessions() as db:
        task = db.get(state.Task, state.task_id)
        layer = task_layer(db, monkeypatch)
        history = images.history_for(state, task)
        endpoint = (state.execution.execution_record(task)["shot_image"]["endpoint"] if kind == "shot"
                    else state.contracts.read_contract(task)["endpoint"])
        remote = []
        log = state.LLMLog(id="unrelated-log", provider="fake", model="fake", user_prompt="Other task",
                           status="pending", task_type="h3_single_frame_prompt", novel_id="novel", chapter_id="chapter")
        db.add(log)
        db.commit()

        async def cancel(cids):
            with state.sessions() as check:
                assert check.get(state.Task, task.id).status == "cancelled"
            remote.extend(cids)
            return {"interrupted": False, "error": "Remote unavailable"}

        async def poll(cid):
            if during == "poll":
                await layer.service.cancel_task(task.id)
            return {"state": "completed", "history": history}

        def frozen(url):
            assert url == endpoint
            return SimpleNamespace(get_prompt_state=poll, cancel_all_matching_tasks=cancel)

        monkeypatch.setattr(layer.module, "frozen_keyframe_client", frozen)
        if during == "download":
            def stop():
                with state.sessions() as check:
                    current = check.get(state.Task, task.id)
                    assert layer.service._transition_task_terminal(current, check, status="cancelled",
                                                                   message="Cancelled during download", step="cancelled")
            state.hooks["download"] = stop
        reconcile(layer, task)
        db.refresh(task)
        assert task.status == "cancelled"
        layer.service._mark_pending_video_llm_logs_cancelled(task, db)
        layer.service._mark_related_task_failed(task, db)
        layer.service._cleanup_cancelled_video_task(task, db)
        db.commit()
        db.refresh(log)
        assert log.status == "pending"
        if during == "poll":
            assert remote == [task.comfyui_prompt_id]
        else:
            data = json.loads(task.metadata_json)
            observations = data.get("execution_observations", []) + data.get("keyframe_reference_observations", [])
            detached = data.get("keyframe_reference_contract", {}).get("result", {})
            assert any(item.get("artifact_url") for item in observations) or (
                detached.get("attachment") == "detached" and detached.get("url"))
    assert images.shot_columns(state) == before and not state.shot_writes


def test_benchmark_video_cancel_never_cancels_chapter_llm_logs(execution, monkeypatch):
    state = execution
    layer = task_layer(state.db, monkeypatch)
    log = layer.module.LLMLog(id="other", provider="fake", model="fake", user_prompt="Other shot",
                              status="pending", task_type="h3_single_frame_prompt", novel_id="novel", chapter_id="chapter")
    state.db.add(log)
    state.db.commit()
    layer.service._mark_pending_video_llm_logs_cancelled(state.task, state.db)
    assert asyncio.run(layer.service.cancel_task("task"))["success"]
    state.db.refresh(log)
    assert log.status == "pending"
    assert_shot_unchanged(state)


@pytest.mark.parametrize("kind", ["shot", "keyframe"])
@pytest.mark.parametrize("status", ["pending", "failed", "cancelled"])
def test_benchmark_direct_recovery_never_revives_nonactive_tasks(isolated, monkeypatch, kind, status):
    state = isolated
    if kind == "shot":
        images.create_image(state)
    else:
        keyframes.create(state, execution_purpose="benchmark")
    with state.sessions() as db:
        task = db.get(state.Task, state.task_id)
        task.status, task.error_message = status, "Original decision"
        db.commit()
        layer = task_layer(db, monkeypatch)
        recover = (layer.service._recover_completed_shot_image_prompt if kind == "shot" else layer.service._recover_completed_keyframe_prompt)
        assert asyncio.run(recover(task, {"outputs": {"out": {}}}, db)) is False
        assert task.status == status and task.error_message == "Original decision"
        assert not state.http_calls and not state.shot_writes


@pytest.mark.parametrize("kind", ["shot", "keyframe"])
def test_false_benchmark_hook_never_enters_legacy_timeout_or_live_shot(isolated, monkeypatch, kind):
    state = isolated
    if kind == "shot":
        images.create_image(state)
    else:
        keyframes.create(state, execution_purpose="benchmark")
    with state.sessions() as db:
        task = db.get(state.Task, state.task_id)
        layer = task_layer(db, monkeypatch)
        if kind == "shot":
            monkeypatch.setattr(state.images, "recover_benchmark_shot_image", AsyncMock(return_value=False))
            recover = layer.service._recover_completed_shot_image_prompt
        else:
            monkeypatch.setattr(state.module.ShotKeyframeService, "recover_benchmark_image", AsyncMock(return_value=False))
            recover = layer.service._recover_completed_keyframe_prompt
        assert asyncio.run(recover(task, {"outputs": {"out": {}}}, db)) is False
        assert not state.shot_writes and not state.http_calls


@pytest.mark.parametrize("metadata", [None, '{"old":"evidence"}', '{"execution_purpose":"benchmark"}',
                                      '{"execution_purpose":null}', '{"execution_purpose":[]}', '{"execution":{}}', '{bad'])
def test_purpose_projection_is_consistent_and_malformed_is_not_production(recovery, metadata):
    state = recovery
    state.task.metadata_json = metadata
    state.db.commit()
    expected = "production" if metadata in (None, '{"old":"evidence"}') else "benchmark" if metadata == '{"execution_purpose":"benchmark"}' else None
    payloads = [state.service.format_task_list([state.task], {}, {}, {})[0], state.service.format_task_detail(state.task),
                asyncio.run(state.api.get_task_workflow(state.task.id, state.repo))["data"]]
    assert all(item["execution_purpose"] == expected for item in payloads)
    if expected is None:
        assert all(item["executionPurposeError"] for item in payloads)


@pytest.mark.parametrize("purpose", ["production", "benchmark"])
@pytest.mark.parametrize("snapshot", [None, "[]", '[{"window_index":1,"prompt_id":"known-cid"}]'])
def test_strict_clip_workflow_missing_evidence_never_uses_live_plan_or_network(execution, monkeypatch, purpose, snapshot):
    state = execution
    data = json.loads(state.task.metadata_json)
    data["execution_purpose"] = purpose
    state.task.metadata_json, state.task.video_director_clips = json.dumps(data), snapshot
    state.db.commit()
    layer = task_layer(state.db, monkeypatch)
    before = layer.service._task_snapshot(state.task)
    result = asyncio.run(layer.api.get_task_clip_workflow("task", 1, state.db, layer.repo))["data"]
    assert result["execution_purpose"] == purpose
    assert result["workflow"] is None and result["workflowSource"] == "not_recorded"
    assert layer.service._task_snapshot(state.task) == before
    if not snapshot or snapshot == "[]":
        assert layer.service.format_task_list([state.task], {}, {}, {}, shots={"shot": state.shot})[0]["videoDirectorClips"] == []
    state.client.get_prompt_state.assert_not_awaited()
    assert_shot_unchanged(state)


@pytest.mark.parametrize("conflict", [False, True])
def test_legacy_clip_get_backfills_only_task_evidence_with_cas(recovery, monkeypatch, conflict):
    state = recovery
    task = state.task
    task.type, task.metadata_json = "shot_video", '{"sibling":"old"}'
    task.video_director_clips = '[{"window_index":1,"prompt_id":"known"}]'
    state.db.commit()
    before = state.shot.video_director_plan

    async def poll(*args, **kwargs):
        if conflict:
            with Session(state.engine) as db:
                db.get(state.Task, task.id).metadata_json = '{"sibling":"new"}'
                db.commit()
        return {"state": "completed", "history": {"prompt": [0, "known", {"out": {"class_type": "SaveVideo"}}]}}

    monkeypatch.setattr(state.comfy.client, "get_prompt_state", poll)
    data = asyncio.run(state.api.get_task_clip_workflow(task.id, 1, state.db, state.repo))["data"]
    state.db.refresh(task)
    state.db.refresh(state.shot)
    assert state.shot.video_director_plan == before
    assert json.loads(task.metadata_json)["sibling"] == ("new" if conflict else "old")
    assert bool(data["workflow"]) is not conflict
    assert ("workflow_json" in json.loads(task.video_director_clips)[0]) is not conflict


def test_numeric_projection_uses_equivalence_but_not_changed_graph(recovery):
    state = recovery
    graph = deepcopy(state.graph)
    field = graph["108"]["inputs"]
    original = field["cfg"]
    field["cfg"] = float(original) if type(original) is int else int(original)
    state.task.workflow_json = json.dumps(graph)
    state.db.commit()
    assert asyncio.run(state.api.get_task_workflow(state.task.id, state.repo))["data"]["sourceProof"]["verified"]
    field["cfg"] += 1
    state.task.workflow_json = json.dumps(graph)
    state.db.commit()
    result = asyncio.run(state.api.get_task_workflow(state.task.id, state.repo))["data"]
    assert not result["sourceProof"]["verified"] and result["sourceProof"]["code"] == "TASK_PROJECTION_CHANGED"


@pytest.mark.parametrize("execution", [
    {"purpose": "production", "mode": "SINGLE_FRAME"},
    {"purpose": "production", "only": 2},
    {"purpose": "benchmark", "mode": "SINGLE_FRAME"},
    {"purpose": "benchmark", "only": 2},
], indirect=True)
def test_task_video_projection_exposes_scope_attachment_without_adopting_archives(execution, monkeypatch):
    state = execution
    task = videos.run(state)
    assert task.status == "completed", task.error_message
    layer = task_layer(state.db, monkeypatch)
    data = json.loads(task.metadata_json)
    scope = "whole_shot" if state.run_request["only_window_index"] is None else "clip"
    published = data["execution_purpose"] == "production" and scope == "whole_shot"
    expected = {"strict": True, "scope": scope, "attachment": data["video_run"]["result"]["attachment"], "published": published}
    payloads = [layer.service.format_task_list([task], {}, {}, {}, shots={"shot": state.shot})[0],
                layer.service.format_task_detail(task), asyncio.run(layer.api.get_task_workflow(task.id, layer.repo))["data"],
                asyncio.run(layer.api.get_task_clip_workflow(task.id, state.run_request["only_window_index"] or 1, state.db, layer.repo))["data"]]
    assert all(item["videoExecution"] == expected for item in payloads)
    assert payloads[0]["resultUrl"] == payloads[1]["resultUrl"] == task.result_url
    if not published:
        assert_shot_unchanged(state)


@pytest.mark.parametrize("only", [None, 2])
def test_pending_video_projection_uses_frozen_request_scope_before_claim(execution, monkeypatch, only):
    state = execution
    data = json.loads(state.task.metadata_json)
    data["execution"]["request"]["only_window_index"] = only
    state.task.metadata_json = json.dumps(data)
    state.db.commit()
    layer = task_layer(state.db, monkeypatch)
    assert layer.service.format_video_execution(state.task)["videoExecution"] == {
        "strict": True, "scope": "whole_shot" if only is None else "clip", "attachment": None, "published": False,
    }


def test_video_projection_fails_closed_for_mismatched_scope_and_result(execution, monkeypatch):
    state = execution
    task, _, handle = state.execution.claim_video_execution(state.db, "task")
    data = json.loads(task.metadata_json)
    data["video_run"].update(scope="clip", phase="completed", result={"url": "/unproven.mp4", "attachment": "attached", "kind": "whole_shot"})
    task.metadata_json, task.status, task.result_url = json.dumps(data), "completed", "/unproven.mp4"
    state.db.commit()
    layer = task_layer(state.db, monkeypatch)
    projection = layer.service.format_video_execution(task)["videoExecution"]
    assert projection["scope"] is None and not projection["published"] and projection["error"]


def test_frontend_clip_tracking_and_unpublished_results_never_claim_whole_shot():
    frontend = BACKEND.parent / "frontend/my-app"
    script = r'''
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const base = 'src/pages/ChapterGenerate/';
const transpile = text => ts.transpileModule(text, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const silent = { log() {}, error() {} };
function harness(tasks) {
  const initial = { id: 'shot', index: 1, videoUrl: '/whole.mp4', videoStatus: 'completed', videoTaskId: 'whole-owner', imageStatus: 'generating' };
  let state = { chapter: { id: 'chapter', novelId: 'novel' }, shots: [initial] }, refreshes = 0;
  const imports = { '../../../../api/shots': { shotsApi: { getShot: async () => { refreshes++; return { success: true, data: { ...initial, videoUrl: '/authoritative.mp4' } }; } } },
    '../../../../api/chapters': { chapterApi: {} }, '../../../../utils': { formatUserFacingError: value => value }, '../../videoPlan': {} };
  const exports = {};
  vm.runInNewContext(transpile(readFileSync(base + 'stores/slices/generationSlice.ts', 'utf8')), {
    exports, require: name => imports[name], localStorage: { getItem: () => null }, console: silent,
    fetch: async url => ({ json: async () => ({ success: true, data: url.includes('shot_video_batch') ? [] : tasks }) }),
  });
  const set = patch => { state = { ...state, ...(typeof patch === 'function' ? patch(state) : patch) }; };
  state = { ...state, ...exports.createGenerationSlice(set, () => state), shotVideos: { shot: '/whole.mp4' } };
  return { get: () => state, initial, refreshes: () => refreshes };
}
(async () => {
  const clipProof = { strict: true, scope: 'clip', attachment: 'detached', published: false };
  const fullProof = { strict: true, scope: 'whole_shot', attachment: 'attached', published: true };
  for (const proof of [clipProof, { ...fullProof, attachment: 'detached' }, { ...fullProof, attachment: 'archived' }, { ...fullProof, published: false }, null]) {
    const task = { id: 'clip-owner', shotId: 'shot', status: 'completed', resultUrl: '/C2-only.mp4', execution_purpose: 'production', videoExecution: proof };
    const h = harness([task]);
    await h.get().checkVideoTaskStatus('chapter');
    assert.equal(h.get().shots[0], h.initial);
    assert.equal(h.get().shotVideos.shot, '/whole.mp4');
    assert.equal(h.refreshes(), 0);
    assert.equal(task.resultUrl, '/C2-only.mp4'); // The task archive remains intact.
  }
  for (const status of ['pending', 'queued', 'running', 'failed', 'cancelled', 'completed']) {
    const clip = { id: 'newer-clip', shotId: 'shot', status, execution_purpose: 'production', videoExecution: clipProof, createdAt: '2026-09-08' };
    const h = harness([clip]);
    await h.get().checkVideoTaskStatus('chapter');
    assert.equal(h.get().shots[0], h.initial);
    assert.equal(h.get().generatingVideos.size, 0);
  }
  for (const status of ['pending', 'queued', 'running', 'completed']) {
    for (const strict of [false, true]) {
      const task = { id: 'full-owner', shotId: 'shot', status, resultUrl: '/task-result.mp4', ...(strict ? { videoExecution: fullProof } : {}) };
      const h = harness([task, { ...task, id: 'newest-benchmark', execution_purpose: 'benchmark', createdAt: '2026-09-09' }]);
      await h.get().checkVideoTaskStatus('chapter');
      assert.equal(h.get().shots[0].videoTaskId, 'full-owner');
      assert.equal(h.get().shots[0].videoStatus, status === 'pending' ? 'pending' : status === 'completed' ? 'completed' : 'generating');
      assert.equal(h.get().shots[0].videoUrl, '/authoritative.mp4');
      assert.equal(h.get().shotVideos.shot, '/authoritative.mp4');
      assert.equal(h.get().shots[0].imageStatus, 'generating');
    }
  }
  const text = readFileSync(base + 'components/VideoGenTab.tsx', 'utf8');
  const ast = ts.createSourceFile('VideoGenTab.tsx', text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let regenerate, poll;
  function visit(node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(ast) === 'handleRegenerateClip') regenerate = node.initializer.arguments[0].getText(ast);
    if (ts.isVariableDeclaration(node) && node.name.getText(ast) === 'pollClipTask') poll = node.initializer.getText(ast);
    ts.forEachChild(node, visit);
  }
  visit(ast);
  assert.ok(regenerate && poll);
  let localTask = null, localKey = null, options, status = 'running';
  const forbidden = () => assert.fail('Clip tracking must never write whole-Shot state');
  const context = { effectiveNovelId: 'novel', effectiveChapterId: 'chapter', currentShotId: 'shot', currentShotData: {},
    getAudioDriveReadiness: () => ({ ready: true }), window: { confirm: () => true }, getPlanClipKey: clip => `C${clip.window_index}`,
    setRegeneratingClipKey: key => { localKey = key; }, setSelectedPreviewClipKey() {}, setRegeneratingClipTask: task => { localTask = task; },
    useChapterGenerateStore: { setState: forbidden, getState: forbidden }, setShots: forbidden, setShotVideos: forbidden,
    toast: { error: forbidden, success() {}, info() {} }, console: silent, formatUserFacingError: value => value,
    shotsApi: { generateVideoDirectorClip: async (...args) => { options = args[4]; return { success: true, data: { taskId: 'clip-task' } }; } },
    taskApi: { fetch: async id => { assert.equal(id, 'clip-task'); return { success: true, data: { status, resultUrl: '/detached-C2.mp4', videoExecution: clipProof } }; } },
    stopped: false, inFlight: false,
  };
  const run = vm.runInNewContext(transpile(`(${regenerate})`), context);
  await run({ window_index: 2, video_url: '/old-C2.mp4', prompt_text: 'Saved prompt' }, 'video_only');
  assert.equal(options.auto_merge, false);
  assert.equal(localTask.taskId, 'clip-task');
  assert.equal(localTask.shotId, 'shot');
  const pollTask = vm.runInNewContext(transpile(`(${poll})`), { ...context, regeneratingClipTask: localTask });
  await pollTask();
  assert.equal(localTask.taskId, 'clip-task');
  assert.equal(localKey, 'C2');
  status = 'completed';
  await pollTask();
  assert.equal(localTask, null);
  assert.equal(localKey, null);
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
    result = subprocess.run(["node", "-e", script], cwd=frontend, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def test_production_frontend_poll_selection_ignores_benchmarks_and_invalid_purpose():
    frontend = BACKEND.parent / "frontend/my-app"
    script = r'''
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
function load(path, imports = {}) {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(readFileSync(path, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  }).outputText, { exports, require: name => imports[name], localStorage: { getItem: () => null },
    console: { log() {}, error() {} }, fetch: imports.fetch });
  return exports;
}
(async () => {
  for (const purpose of ['benchmark', null, [], 'invalid']) {
    const production = { id: 'production', shotId: 'shot', frameIndex: 0, status: 'completed', resultUrl: '/production', createdAt: '2026-01-01' };
    const excluded = { ...production, id: 'excluded', execution_purpose: purpose, resultUrl: '/excluded', createdAt: '2026-09-08' };
    for (const method of ['checkShotTaskStatus', 'checkVideoTaskStatus', 'checkKeyframeTaskStatus']) {
      let state = { chapter: { id: 'chapter' }, shots: [{ id: 'shot', index: 1, imageUrl: '/old', videoUrl: '/old',
        keyframes: [{ frame_index: 0, image_task_id: 'production' }] }] };
      const imports = { '../../../../api/shots': { shotsApi: {} }, '../../../../api/chapters': { chapterApi: {} },
        '../../../../utils': { formatUserFacingError: value => value }, '../../videoPlan': {},
        fetch: async url => ({ json: async () => ({ success: true, data: url.includes('shot_video_batch') ?
          [{ ...excluded, metadata: { shot_ids: ['shot'], results: { shot: { status: 'completed', resultUrl: '/batch-benchmark' } } } }] :
          [excluded, production] }) }) };
      const { createGenerationSlice } = load('src/pages/ChapterGenerate/stores/slices/generationSlice.ts', imports);
      const set = patch => { state = { ...state, ...(typeof patch === 'function' ? patch(state) : patch) }; };
      state = { ...state, ...createGenerationSlice(set, () => state) };
      await state[method]('chapter');
      const url = method === 'checkShotTaskStatus' ? state.shots[0].imageUrl : method === 'checkVideoTaskStatus' ? state.shots[0].videoUrl : state.shots[0].keyframes[0].image_url;
      assert.equal(url, '/production', `${method}: ${JSON.stringify(purpose)}`);
    }
  }
  const source = readFileSync('src/components/KeyframesManager.tsx', 'utf8');
  const ast = ts.createSourceFile('KeyframesManager.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let selector;
  function visit(node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(ast) === 'task') selector = node.initializer.getText(ast);
    ts.forEachChild(node, visit);
  }
  visit(ast);
  for (const purpose of ['benchmark', null, [], 'invalid', 'production', undefined]) {
    const task = { id: 'tracked', ...(purpose === undefined ? {} : { execution_purpose: purpose }) };
    const js = ts.transpileModule(selector, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
    const selected = vm.runInNewContext(js, { result: { data: [task] }, kf: { image_task_id: 'tracked' } });
    assert.equal(Boolean(selected), purpose === undefined || purpose === 'production');
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
    result = subprocess.run(["node", "-e", script], cwd=frontend, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
