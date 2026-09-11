"""Isolated execution-integrity tests; --noconftest, no application/network/real DB."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta
import importlib.util
import json
from pathlib import Path
import socket
import sys
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

from test_h3_prompt_worker import worker, PROMPT


@pytest.fixture
def execution(worker, monkeypatch, tmp_path, request):
    state = worker
    options = getattr(request, "param", {})
    state.configure(options.get("mode", "MULTI_KEYFRAME"), windows=options.get("windows", 2),
                    prompt=PROMPT, audio=options.get("audio", False))
    state.shot.scene = ""
    state.task.status = "pending"
    state.db.commit()

    # Distinct connections and sessions, sharing only an ephemeral SQLite database.
    engine = create_engine(f"sqlite:///file:video-{uuid4().hex}?mode=memory&cache=shared&uri=true", poolclass=QueuePool)
    state.models.Task.metadata.create_all(engine)
    with state.engine.connect() as source, engine.begin() as destination:
        for table in state.models.Task.metadata.sorted_tables:
            rows = [dict(row) for row in source.execute(table.select()).mappings()]
            if rows:
                destination.execute(table.insert(), rows)
    db = Session(engine, autoflush=False)
    state.db, state.engine = db, engine
    state.shot = db.get(state.models.Shot, "shot")
    state.task = db.get(state.models.Task, "task")
    state.novel = db.get(type(state.novel), "novel")
    state.workflow = db.get(type(state.workflow), "workflow")
    state.directory = tmp_path
    state.shot_updates = []
    state.stage_hook = None
    state.history_hook = None
    state.queue_hook = None
    state.run_request = {
        "use_keyframes": True, "use_reference_audio": True, "selected_mode": state.mode,
        "workflow_id": "workflow", "only_window_index": options.get("only"), "auto_merge_clips": options.get("auto_merge", False),
        "skip_llm_when_prompt_exists": options.get("reuse", True),
    }

    def load(name, filename):
        spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / "app/services" / filename)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        return module

    state.foundation = load("app.services.task_execution", "task_execution.py")
    state.graphs = load("app.services.keyframe_reference_graph", "keyframe_reference_graph.py")
    state.execution = load("app.services.shot_video_execution", "shot_video_execution.py")
    monkeypatch.setattr(sys.modules["app.services"], "shot_video_service", state.module, raising=False)
    monkeypatch.setattr(state.module, "Path", Path)
    monkeypatch.setattr(socket.socket, "connect_ex", lambda *args: pytest.fail("Network forbidden"))
    for name in ["start.png", *[f"kf{index}.png" for index in range(1, options.get("windows", 2) * 3 + 1)]]:
        (tmp_path / name).write_bytes(name.encode())
    if options.get("audio"):
        plan = json.loads(state.shot.video_director_plan)
        for item in plan.get("window_plans") or plan.get("clips") or []:
            for field in ("drive_audio_path", "final_audio_path"):
                path = tmp_path / Path(item[field]).name
                path.write_bytes(b"frozen audio")
                item[field] = str(path)
        state.shot.video_director_plan = json.dumps(plan)

    def to_path(value):
        return str(tmp_path / str(value).removeprefix("/api/files/")) if value else None

    def to_url(value):
        return "/api/files/" + str(Path(value).relative_to(tmp_path)) if value else None

    monkeypatch.setattr(state.module, "url_to_local_path", to_path)
    monkeypatch.setattr(state.module, "local_path_to_url", to_url)
    monkeypatch.setattr(sys.modules["app.utils.path_utils"], "local_path_to_url", to_url)
    monkeypatch.setattr(sys.modules["app.utils.path_utils"], "url_to_local_path", to_path)
    state.storage.base_dir = tmp_path
    state.storage._get_story_dir = lambda novel_id: tmp_path / "story"
    state.client.base_url = "http://comfy.test"
    monkeypatch.setattr(state.execution, "frozen_client", lambda endpoint: state.client)
    monkeypatch.setattr(state.module, "SessionLocal", lambda: Session(engine, autoflush=False))

    def hook(stage):
        if state.stage_hook:
            state.stage_hook(stage)

    queue = state.client.queue_prompt.side_effect

    async def queued(graph):
        hook("queue")
        result = await queue(graph)
        if state.queue_hook:
            state.queue_hook(result)
        return result

    async def wait(cid, graph, *args, **kwargs):
        hook("wait")
        return {"success": not state.wait_failure, "video_url": f"http://comfy.test/view?filename={cid}.mp4&subfolder=video&type=output",
                "message": "Timed out" if state.wait_failure else ""}

    async def history(cid):
        hook("history")
        if state.history_hook:
            return state.history_hook(cid)
        graph = state.queued[int(cid.removeprefix("queued-")) - 1]
        return {"state": "completed", "history": {
            "prompt": [0, cid, deepcopy(graph)], "status": {"completed": True, "status_str": "success"},
            "outputs": {"out": {"images": [{"filename": f"{cid}.mp4", "subfolder": "video", "type": "output"}]}},
        }}

    async def download(*, destination, **kwargs):
        destination.write_bytes(kwargs["url"].encode())
        hook("download")
        return str(destination)

    async def lock(*args):
        hook("audio_lock")

    async def merge(paths, output):
        Path(output).write_bytes(b"".join(Path(path).read_bytes() for path in paths))
        hook("merge")
        return {"success": True, "media_segments": [
            {"source_path": path, "source_sha256": state.execution.file_digest(path)} for path in paths]}

    state.client.queue_prompt.side_effect = queued
    state.client.wait_for_result.side_effect = wait
    from unittest.mock import AsyncMock
    state.client.get_prompt_state = AsyncMock(side_effect=history)
    state.storage.download_video.side_effect = download
    state.storage.merge_videos.side_effect = merge
    sys.modules["app.services.rendered_subtitles"].lock_generated_audio.side_effect = lock
    state.task.metadata_json = json.dumps(state.foundation.create_execution_metadata(
        state.shot, purpose=options.get("purpose", "benchmark"), request=state.run_request))
    state.task.comfyui_prompt_id = None
    if options.get("admitted"):
        state.shot.video_task_id = state.task.id
        state.shot.video_status = "generating"
    db.commit()
    state.before_shot = {column.key: getattr(state.shot, column.key) for column in state.models.Shot.__table__.columns}

    @event.listens_for(engine, "before_cursor_execute")
    def trace(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("UPDATE SHOTS"):
            state.shot_updates.append(statement)

    yield state
    db.close()
    engine.dispose()


def run(state):
    asyncio.run(state.module.generate_shot_video_task(
        "task", "novel", "chapter", "shot", 17, "workflow", "/wrong-enqueue-image.png",
        selected_mode="WRONG_ENQUEUE_MODE", only_window_index=999,
    ))
    state.db.expire_all()
    return state.db.get(state.models.Task, "task")


def change_task(state, **fields):
    with Session(state.engine) as editor:
        task = editor.get(state.models.Task, "task")
        for key, value in fields.items():
            setattr(task, key, value)
        editor.commit()


def complete_slot(state, handle, index):
    module = state.execution
    data = module.check_current(state.db, handle)[1]
    slot = deepcopy(data["video_run"]["clips"][str(index)])
    cid = f"receipt-{index}"
    graph = {"out": {"class_type": "SaveVideo", "inputs": {"source": index}}}
    slot["submission"] = {"state": "acknowledged", "prompt_id": cid, "graph": graph, "graph_hash": module.digest(graph),
                          "endpoint": "http://comfy.test", "output_node": "out"}
    history = {"prompt": [0, cid, graph], "status": {"completed": True, "status_str": "success"},
               "outputs": {"out": {"images": [{"filename": f"{cid}.mp4", "subfolder": "video", "type": "output"}]}}}
    path = Path(handle["directory"]) / f"fixture-{index}.mp4"
    path.write_bytes(cid.encode())
    slot.update(state="SUCCEEDED", receipt={
        "run_id": handle["run_id"], "attempt_id": slot["attempt_id"], "clip_index": index, "prompt_id": cid,
        "graph_hash": module.digest(graph), "source_url": module.verify_history(slot, history),
        "path": str(path), "sha256": module.file_digest(path), "bytes": path.stat().st_size, "history": module.capture(handle, "history", history),
    })
    module._write(state.db, handle, lambda current: current["video_run"]["clips"].update({str(index): slot}))
    return slot


@pytest.mark.parametrize("execution", [
    {"mode": "SINGLE_FRAME"}, {"mode": "FIRST_LAST_FRAME"}, {"windows": 1}, {"windows": 2}, {"windows": 3},
    {"windows": 3, "reuse": False},
    {"windows": 2, "audio": True}, {"mode": "FIRST_LAST_FRAME", "audio": True},
], indirect=True)
def test_private_benchmark_all_modes_and_three_clips(execution):
    state = execution
    task = run(state)
    assert task.status == "completed", task.error_message
    data = json.loads(task.metadata_json)
    video_run = data["video_run"]
    assert video_run["request"] == state.run_request
    assert len(video_run["expected"]) == len(state.queued)
    assert all(slot["state"] == "SUCCEEDED" for slot in video_run["clips"].values())
    assert video_run["result"]["attachment"] == "archived"
    assert data["execution"]["result"] == video_run["result"]
    assert data["execution"]["working_shot"]["video_url"] == task.result_url == video_run["result"]["url"]
    state.db.refresh(state.shot)
    assert {key: getattr(state.shot, key) for key in state.before_shot} == state.before_shot
    assert state.shot_updates == []
    private = json.loads(data["execution"]["working_shot"]["video_director_plan"])
    assert private["ai_calls"]
    assert "benchmarks" in video_run["directory"]
    assert state.builder.await_count == len(state.queued)
    for index, record in data["h3_prompt_gate"]["clips"].items():
        assert record[0]["prequeue_validation"]["passed"] is True
        assert record[0]["attempt_id"] == video_run["clips"][index]["attempt_id"]


@pytest.mark.parametrize("execution", [{"windows": 3, "only": 2, "auto_merge": True}], indirect=True)
def test_clip_only_never_auto_merges_old_clips(execution):
    task = run(execution)
    assert task.status == "completed", task.error_message
    record = json.loads(task.metadata_json)["video_run"]
    assert record["scope"] == "clip"
    assert [item["clip_index"] for item in record["expected"]] == [2]
    assert record["auto_merge_note"]
    assert record["result"]["kind"] == "clip"
    assert record["result"]["attachment"] == "archived"
    assert json.loads(task.metadata_json)["execution"]["result"] == record["result"]
    execution.storage.merge_videos.assert_not_awaited()
    assert not execution.shot_updates


def test_shot17_two_sessions_new_c1_old_c2_live_recovery_cannot_complete(execution):
    state = execution
    observed = []

    async def wait(cid, graph, *args, **kwargs):
        if cid == "queued-2":
            with Session(state.engine) as recovery:
                task = recovery.get(state.models.Task, "task")
                current = json.loads(task.metadata_json)
                slots = current["video_run"]["clips"]
                assert slots["1"]["receipt"]
                assert slots["2"]["receipt"] is None
                assert slots["2"]["submission"]["prompt_id"] == cid
                live = recovery.get(state.models.Shot, "shot")
                assert json.loads(live.video_director_plan)["window_plans"][1]["video_url"] == "/old-clip-2.mp4"
                result = await state.execution.reconcile_video_execution(recovery, task)
                assert result is False
                assert task.status == "running"
                assert not task.result_url
                observed.append(True)
        return {"success": True, "video_url": f"http://comfy.test/view?filename={cid}.mp4&subfolder=video&type=output"}

    state.client.wait_for_result.side_effect = wait
    task = run(state)
    assert task.status == "completed", task.error_message
    assert observed == [True]
    state.storage.merge_videos.assert_awaited_once()
    paths = state.storage.merge_videos.await_args.args[0]
    assert len(paths) == 2 and all("old-clip" not in path for path in paths)


@pytest.mark.parametrize("status", ["failed", "cancelled", "completed"])
@pytest.mark.parametrize("stage", ["queue", "wait", "history", "download", "audio_lock", "merge"])
def test_terminal_after_await_preserves_original_result_and_time(execution, status, stage):
    state = execution
    completed = datetime(2025, 1, 1)
    fired = []

    def stop(current):
        if current == stage and not fired:
            fired.append(True)
            change_task(state, status=status, result_url="/original-result.mp4", completed_at=completed, error_message="Original decision")

    state.stage_hook = stop
    task = run(state)
    assert fired
    assert (task.status, task.result_url, task.completed_at, task.error_message) == (status, "/original-result.mp4", completed, "Original decision")
    assert not state.shot_updates
    data = json.loads(task.metadata_json)
    assert any(item["kind"] == "late-failure" for item in data["video_observations"])
    assert all(Path(item["evidence"]["path"]).is_file() for item in data["video_observations"])


@pytest.mark.parametrize("stage", ["queue", "wait", "download", "audio_lock", "merge"])
def test_claim_superseded_after_await_never_changes_new_owner(execution, stage):
    fired = []
    def stop(current):
        if current == stage and not fired:
            fired.append(True)
            change_task(execution, claim_token="replacement", attempt=8, current_step="Replacement owns this task")
    execution.stage_hook = stop
    task = run(execution)
    assert task.claim_token == "replacement"
    assert task.attempt == 8
    assert task.status == "running"
    assert task.current_step == "Replacement owns this task"
    assert not task.result_url
    assert not execution.shot_updates


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
@pytest.mark.parametrize("contract", [True, False])
def test_queued_terminal_task_never_revives(execution, status, contract):
    change_task(execution, status=status, result_url="/saved.mp4", completed_at=datetime(2025, 1, 1),
                **({"metadata_json": None} if not contract else {}))
    task = run(execution)
    assert task.status == status
    assert task.result_url == "/saved.mp4"
    assert task.completed_at == datetime(2025, 1, 1)
    execution.client.queue_prompt.assert_not_awaited()


def test_duplicate_worker_and_merge_claims_are_fenced(execution):
    module = execution.execution
    task, shot, handle = module.claim_video_execution(execution.db, "task")
    with Session(execution.engine) as other:
        assert module.claim_video_execution(other, "task") is None
    for index in (1, 2):
        complete_slot(execution, handle, index)
    merge = module.begin_merge(execution.db, handle)
    with Session(execution.engine) as other:
        with pytest.raises(module.ExecutionConflict, match="MERGE_ALREADY_CLAIMED"):
            module.begin_merge(other, handle)
    assert merge["manifest"] == module.completion_manifest(json.loads(task.metadata_json))


@pytest.mark.parametrize("change", ["missing", "old-run", "attempt", "cid", "index", "graph", "history", "bytes", "order"])
def test_completion_barrier_rejects_wrong_receipts(execution, change):
    state, module = execution, execution.execution
    task, shot, handle = module.claim_video_execution(state.db, "task")
    slots = [complete_slot(state, handle, index) for index in (1, 2)]
    data = json.loads(task.metadata_json)
    slot = data["video_run"]["clips"]["2"]
    if change == "missing":
        slot["receipt"] = None
    elif change in {"old-run", "attempt", "cid", "index", "graph"}:
        key = {"old-run": "run_id", "attempt": "attempt_id", "cid": "prompt_id", "index": "clip_index", "graph": "graph_hash"}[change]
        slot["receipt"][key] = "wrong"
    elif change == "history":
        Path(slot["receipt"]["history"]["path"]).write_text("{}")
    elif change == "bytes":
        Path(slot["receipt"]["path"]).write_bytes(b"changed")
    else:
        data["video_run"]["expected"].reverse()
        data["video_run"]["expected_hash"] = module.digest(data["video_run"]["expected"])
    with pytest.raises(module.ExecutionConflict):
        module.completion_manifest(data)


def test_metadata_cas_rebases_unrelated_evidence_without_losing_it(execution, monkeypatch):
    module = execution.execution
    task, shot, handle = module.claim_video_execution(execution.db, "task")
    original = module._conditions
    fired = []
    def race(db, task, data, **kwargs):
        conditions = original(db, task, data, **kwargs)
        if not fired:
            fired.append(True)
            with Session(execution.engine) as editor:
                current = editor.get(execution.models.Task, "task")
                saved = json.loads(current.metadata_json)
                saved["parallel_evidence"] = {"preserve": True}
                current.metadata_json = json.dumps(saved)
                editor.commit()
        return conditions
    monkeypatch.setattr(module, "_conditions", race)
    module._write(execution.db, handle, lambda data: data.update(worker_evidence="also preserve"))
    saved = json.loads(task.metadata_json)
    assert saved["parallel_evidence"] == {"preserve": True}
    assert saved["worker_evidence"] == "also preserve"


@pytest.mark.parametrize("execution", [{"purpose": "production"}], indirect=True)
def test_production_only_publishes_after_barrier_and_manual_lookup_is_read_only(execution):
    def inspect(stage):
        with Session(execution.engine) as observer:
            shot = observer.get(execution.models.Shot, "shot")
            assert shot.video_url == "/old-shot.mp4"
            assert json.loads(shot.video_director_plan)["window_plans"][1]["video_url"] == "/old-clip-2.mp4"
    execution.stage_hook = inspect
    task = run(execution)
    assert task.status == "completed", task.error_message
    assert len(execution.shot_updates) == 1
    result = execution.execution.completed_video_artifact(execution.db, "task", shot_id="shot")
    assert result["success"] is True
    assert result["skipped"] is True
    assert result["video_url"] == task.result_url
    assert len(execution.shot_updates) == 1


@pytest.mark.parametrize("execution", [{"purpose": "production"}], indirect=True)
def test_production_publication_task_and_shot_cas_roll_back_together(execution, monkeypatch):
    state, module = execution, execution.execution
    task, shot, handle = module.claim_video_execution(state.db, "task")
    for index in (1, 2):
        complete_slot(state, handle, index)
    merge = module.begin_merge(state.db, handle)
    output = Path(handle["directory"]) / "candidate.mp4"
    output.write_bytes(b"candidate")
    from sqlalchemy.orm import Query
    update = Query.update
    def reject_shot(query, values, *args, **kwargs):
        if query.column_descriptions[0].get("entity") is state.models.Shot:
            return 0
        return update(query, values, *args, **kwargs)
    monkeypatch.setattr(Query, "update", reject_shot)
    with pytest.raises(module.ExecutionConflict, match="WRITE_CONFLICT"):
        module.publish_result(state.db, handle, merge, output)
    state.db.refresh(task)
    state.db.refresh(state.shot)
    assert task.status == "running"
    assert not task.result_url and not task.completed_at
    assert state.shot.video_url == "/old-shot.mp4"
    assert output.is_file()


@pytest.mark.parametrize("execution", [{"purpose": "production"}], indirect=True)
def test_source_superseded_during_merge_cannot_be_overwritten(execution):
    def supersede(stage):
        if stage == "merge":
            with Session(execution.engine) as editor:
                shot = editor.get(execution.models.Shot, "shot")
                shot.video_task_id = "new-owner"
                shot.video_url = "/replacement.mp4"
                editor.commit()
    execution.stage_hook = supersede
    task = run(execution)
    assert task.status == "failed"
    execution.db.refresh(execution.shot)
    assert execution.shot.video_url == "/replacement.mp4"
    assert execution.shot.video_task_id == "new-owner"
    assert len(execution.shot_updates) == 1  # The editor, not the losing publisher.


def test_interrupted_recovery_fails_run_archives_output_and_never_submits(execution):
    state, module = execution, execution.execution
    task, shot, handle = module.claim_video_execution(state.db, "task")
    slot = complete_slot(state, handle, 1)
    state.history_hook = lambda cid: {"state": "completed", "history": json.loads(Path(slot["receipt"]["history"]["path"]).read_text())}
    change_task(state, heartbeat_at=datetime.utcnow() - timedelta(seconds=500))
    with Session(state.engine) as recovery:
        recovered = asyncio.run(module.reconcile_video_execution(recovery, recovery.get(state.models.Task, "task")))
    assert recovered is True
    state.db.refresh(task)
    assert task.status == "failed"
    completed = task.completed_at
    assert not task.result_url
    assert json.loads(task.metadata_json)["video_run"]["clips"]["2"]["receipt"] is None
    module.fail_execution(state.db, handle, "late error")
    state.db.refresh(task)
    assert task.completed_at == completed
    kinds = [item["kind"] for item in json.loads(task.metadata_json)["video_observations"]]
    assert "recovery-history" in kinds and "recovery-output" in kinds and "late-failure" in kinds
    state.client.queue_prompt.assert_not_awaited()
    assert not state.shot_updates


def test_unknown_ack_stays_unknown_without_requeue(execution):
    execution.queue_error = TimeoutError("ACK lost")
    task = run(execution)
    assert task.status == "failed"
    data = json.loads(task.metadata_json)
    assert data["video_run"]["clips"]["1"]["submission"]["state"] == "unknown"
    execution.client.queue_prompt.assert_awaited_once()
    execution.client.get_prompt_state.assert_not_awaited()
    execution.storage.download_video.assert_not_awaited()


def test_wrong_history_cid_cannot_fill_a_receipt(execution):
    execution.history_hook = lambda cid: {"state": "completed", "history": {
        "prompt": [0, "other-cid", execution.queued[0]], "status": {"completed": True, "status_str": "success"}, "outputs": {},
    }}
    task = run(execution)
    assert task.status == "failed"
    assert json.loads(task.metadata_json)["video_run"]["clips"]["1"]["receipt"] is None
    execution.storage.download_video.assert_not_awaited()


def test_artifact_captures_are_unique_and_never_deleted_on_failure(execution):
    task = run(execution)
    assert task.status == "completed", task.error_message
    data = json.loads(task.metadata_json)
    handle = execution.execution._handle(task, data)
    first = execution.execution.capture(handle, "same-kind", {"same": "content"})
    second = execution.execution.capture(handle, "same-kind", {"same": "content"})
    assert first["path"] != second["path"]
    assert first["sha256"] == second["sha256"]
    before = set(Path(handle["directory"]).iterdir())
    execution.execution.fail_execution(execution.db, handle, "late failure")
    assert before <= set(Path(handle["directory"]).iterdir())
    destinations = [call.kwargs["destination"] for call in execution.storage.download_video.await_args_list]
    assert len(destinations) == len(set(destinations)) == 2
    assert all(path.parent == Path(handle["directory"]) for path in destinations)


def test_recovery_wins_during_worker_download_and_both_captures_survive(execution):
    state, module = execution, execution.execution
    interrupted = []
    async def download(*, destination, **kwargs):
        destination.write_bytes(kwargs["url"].encode())
        if not interrupted:
            interrupted.append(True)
            change_task(state, heartbeat_at=datetime.utcnow() - timedelta(seconds=500))
            with Session(state.engine) as recovery:
                assert await module.reconcile_video_execution(recovery, recovery.get(state.models.Task, "task")) is True
        return str(destination)
    state.storage.download_video.side_effect = download
    task = run(state)
    assert task.status == "failed"
    data = json.loads(task.metadata_json)
    assert all(slot["receipt"] is None for slot in data["video_run"]["clips"].values())
    state.client.queue_prompt.assert_awaited_once()
    state.storage.merge_videos.assert_not_awaited()
    assert len(list(Path(data["video_run"]["directory"]).glob("*.mp4"))) == 2
    assert not task.result_url


def test_recovery_expiry_cas_loses_to_renewed_heartbeat(execution, monkeypatch):
    module = execution.execution
    task, shot, handle = module.claim_video_execution(execution.db, "task")
    old = datetime.utcnow() - timedelta(seconds=500)
    change_task(execution, heartbeat_at=old)
    fail = module.fail_execution
    def renew_before_failure(*args, **kwargs):
        change_task(execution, heartbeat_at=datetime.utcnow())
        return fail(*args, **kwargs)
    monkeypatch.setattr(module, "fail_execution", renew_before_failure)
    with Session(execution.engine) as recovery:
        assert asyncio.run(module.reconcile_video_execution(recovery, recovery.get(execution.models.Task, "task"))) is False
    execution.db.refresh(task)
    assert task.status == "running"
    assert task.heartbeat_at > old
    assert task.completed_at is None
    execution.client.get_prompt_state.assert_not_awaited()


def test_heartbeat_uses_a_separate_session_and_stops_on_terminal(execution, monkeypatch):
    module = execution.execution
    task, shot, handle = module.claim_video_execution(execution.db, "task")
    change_task(execution, heartbeat_at=datetime.utcnow() - timedelta(seconds=20))
    original = execution.db.get(execution.models.Task, "task").heartbeat_at
    monkeypatch.setattr(module, "HEARTBEAT_SECONDS", 0.001)
    async def exercise():
        heartbeat = asyncio.create_task(module._heartbeat(handle, lambda: Session(execution.engine)))
        await asyncio.sleep(0.025)
        change_task(execution, status="cancelled")
        await asyncio.wait_for(heartbeat, timeout=1)
    asyncio.run(exercise())
    execution.db.refresh(task)
    assert task.status == "cancelled"
    assert task.heartbeat_at > original


@pytest.mark.parametrize("execution", [{"reuse": False, "mode": "SINGLE_FRAME"}], indirect=True)
@pytest.mark.parametrize("failure_kind", ["TIMEOUT", "SERVICE_ERROR"])
def test_fallback_can_be_reused_by_a_fresh_run_not_terminal_task(execution, failure_kind):
    state = execution
    state.llm.return_value = {"success": False, "failure_kind": failure_kind, "error": "provider unavailable"}
    first = run(state)
    assert first.status == "completed", first.error_message
    data = json.loads(first.metadata_json)
    record = data["h3_prompt_gate"]["clips"]["1"][0]
    assert record["origin"] == "fallback"
    saved_first = (first.result_url, first.completed_at, first.metadata_json)
    private = state.foundation.load_execution_shot(first)
    request = {**state.run_request, "skip_llm_when_prompt_exists": True}
    new = state.models.Task(id="fresh-reuse", type="shot_video", status="pending", name="Fresh reuse", description="Fresh",
                           novel_id="novel", chapter_id="chapter", shot_id="shot", workflow_id="workflow",
                           metadata_json=json.dumps(state.foundation.create_execution_metadata(private, purpose="benchmark", request=request)))
    state.db.add(new)
    state.db.commit()
    asyncio.run(state.execution.run_video_execution(state.db, new.id))
    state.db.refresh(new)
    state.db.refresh(first)
    assert new.status == "completed", new.error_message
    assert json.loads(new.metadata_json)["h3_prompt_gate"]["clips"]["1"][0]["origin"] == "reused_fallback"
    assert (first.result_url, first.completed_at, first.metadata_json) == saved_first
    state.llm.assert_awaited_once()


@pytest.mark.parametrize("execution", [{"reuse": False}], indirect=True)
def test_late_llm_result_cannot_write_live_ai_calls_or_terminal_gate(execution):
    state = execution
    frozen = []
    async def late(**kwargs):
        change_task(state, status="failed", error_message="Original failure", completed_at=datetime(2025, 1, 1))
        with Session(state.engine) as observer:
            frozen.append(json.loads(observer.get(state.models.Task, "task").metadata_json)["video_run"])
        return {"success": True, "content": PROMPT}
    state.llm.side_effect = late
    task = run(state)
    assert task.status == "failed"
    assert task.error_message == "Original failure"
    assert json.loads(task.metadata_json)["video_run"] == frozen[0]
    state.client.queue_prompt.assert_not_awaited()
    assert not state.shot_updates


@pytest.mark.parametrize("failure", ["core", "mapping", "failed-history", "empty-history"])
def test_strict_run_does_not_weaken_p0_or_successful_history_requirement(execution, failure):
    state = execution
    if failure == "core":
        metadata = json.loads(state.task.metadata_json)
        plan = json.loads(metadata["execution"]["working_shot"]["video_director_plan"])
        plan["window_plans"][0]["prompt_text"] = "invalid core"
        metadata["execution"]["working_shot"]["video_director_plan"] = json.dumps(plan)
        state.task.metadata_json = json.dumps(metadata)
    elif failure == "mapping":
        state.workflow.node_mapping = json.dumps({**json.loads(state.workflow.node_mapping), "prompt_node_id": "missing"})
    elif failure == "failed-history":
        state.history_hook = lambda cid: {"state": "error", "history": {
            "prompt": [0, cid, state.queued[0]], "status": {"completed": True, "status_str": "error"}, "outputs": {"out": {"images": []}},
        }}
    else:
        state.history_hook = lambda cid: {"state": "missing"}
    state.db.commit()
    task = run(state)
    assert task.status == "failed"
    data = json.loads(task.metadata_json)
    assert data["video_run"]["clips"]["1"]["receipt"] is None
    assert not task.result_url
    state.storage.merge_videos.assert_not_awaited()
    if failure in {"core", "mapping"}:
        state.client.queue_prompt.assert_not_awaited()
    else:
        state.storage.download_video.assert_not_awaited()


def test_benchmark_cas_refuses_to_flush_a_dirty_live_shot(execution):
    module = execution.execution
    task, shot, handle = module.claim_video_execution(execution.db, "task")
    execution.shot.video_url = "/must-not-flush.mp4"
    with pytest.raises(module.ExecutionConflict, match="LIVE_SHOT_DIRTY"):
        module._write(execution.db, handle, lambda data: {})
    assert not execution.shot_updates
    execution.db.rollback()


def test_completed_run_manual_merge_rejects_benchmark_and_missing_barrier(execution):
    module = execution.execution
    task, shot, handle = module.claim_video_execution(execution.db, "task")
    assert module.completed_video_artifact(execution.db, "task")["success"] is False
    for index in (1, 2):
        complete_slot(execution, handle, index)
    merge = module.begin_merge(execution.db, handle)
    output = Path(handle["directory"]) / "test-merge.mp4"
    output.write_bytes(b"merge")
    module.publish_result(execution.db, handle, merge, output)
    assert module.completed_video_artifact(execution.db, "task")["success"] is False
    assert not execution.shot_updates


def test_raw_download_survives_audio_postprocessing(execution):
    async def lock(storage, path, *args):
        Path(path).write_bytes(b"processed media")
    sys.modules["app.services.rendered_subtitles"].lock_generated_audio.side_effect = lock
    task = run(execution)
    assert task.status == "completed", task.error_message
    for slot in json.loads(task.metadata_json)["video_run"]["clips"].values():
        receipt = slot["receipt"]
        assert receipt["raw"]["path"] != receipt["path"]
        assert execution.execution.file_digest(receipt["raw"]["path"]) == receipt["raw"]["sha256"]
        assert Path(receipt["path"]).read_bytes() == b"processed media"


def test_hash_drift_during_merge_never_publishes(execution):
    def corrupt(stage):
        if stage == "merge":
            paths = execution.storage.merge_videos.await_args.args[0]
            Path(paths[0]).write_bytes(b"source changed while merging")
    execution.stage_hook = corrupt
    task = run(execution)
    assert task.status == "failed"
    assert not task.result_url
    assert not execution.shot_updates


def test_boolean_is_not_numeric_graph_equivalence(execution):
    graph = {"video": {"class_type": "CreateVideo", "inputs": {"fps": 1}}}
    other = deepcopy(graph)
    other["video"]["inputs"]["fps"] = 1.0
    assert execution.execution._same_graph(graph, other)
    other["video"]["inputs"]["fps"] = True
    assert not execution.execution._same_graph(graph, other)
    assert not execution.execution._same_graph({"value": 1}, {"value": 1.0})


def test_unstarted_expired_run_fails_without_submit_or_evidence_replacement(execution):
    change_task(execution, created_at=datetime.utcnow() - timedelta(hours=1))
    execution.db.refresh(execution.task)
    before = json.loads(execution.task.metadata_json)["execution"]
    assert asyncio.run(execution.execution.reconcile_video_execution(execution.db, execution.task)) is True
    execution.db.refresh(execution.task)
    assert execution.task.status == "failed"
    assert json.loads(execution.task.metadata_json)["execution"] == before
    execution.client.queue_prompt.assert_not_awaited()
    execution.client.get_prompt_state.assert_not_awaited()


def test_parent_stopping_fences_child_and_allows_failure_evidence(execution):
    parent = execution.models.Task(id="parent", type="shot_video_batch", status="running", name="parent")
    execution.db.add(parent)
    execution.task.parent_task_id = parent.id
    execution.db.commit()
    def stop(stage):
        if stage == "wait":
            with Session(execution.engine) as editor:
                editor.get(execution.models.Task, "parent").status = "failed"
                editor.commit()
    execution.stage_hook = stop
    task = run(execution)
    assert task.status == "failed"
    assert not task.result_url
    execution.client.queue_prompt.assert_awaited_once()
    assert not execution.shot_updates


@pytest.mark.parametrize("execution", [{"purpose": "production"}], indirect=True)
def test_deleted_strict_task_does_not_enable_legacy_manual_merge(execution):
    task = run(execution)
    assert task.status == "completed", task.error_message
    execution.db.delete(task)
    execution.db.commit()
    execution.db.refresh(execution.shot)
    result = asyncio.run(execution.module.merge_video_director_clip_videos(
        execution.db, execution.shot, execution.module.ShotRepository(execution.db), "novel", "chapter", 1,
    ))
    assert result["success"] is False
    execution.storage.merge_videos.assert_awaited_once()  # Original worker only.


def test_strict_dispatch_exception_never_uses_legacy_failure_writeback(execution, monkeypatch):
    async def unavailable(db, task_id):
        change_task(execution, status="completed", result_url="/original.mp4", completed_at=datetime(2025, 1, 1))
        raise RuntimeError("Claim store unavailable")
    monkeypatch.setattr(execution.execution, "run_video_execution", unavailable)
    task = run(execution)
    assert task.status == "completed"
    assert task.result_url == "/original.mp4"
    assert task.completed_at == datetime(2025, 1, 1)
    assert not execution.shot_updates


def test_legacy_start_cas_cannot_revive_concurrently_completed_task(execution, monkeypatch):
    from sqlalchemy.orm import Query
    change_task(execution, metadata_json=None)
    update = Query.update
    fired = []
    def stop_before_update(query, values, *args, **kwargs):
        if query.column_descriptions[0].get("entity") is execution.models.Task and values.get("status") == "running" and not fired:
            fired.append(True)
            change_task(execution, status="completed", result_url="/original.mp4", completed_at=datetime(2025, 1, 1))
        return update(query, values, *args, **kwargs)
    monkeypatch.setattr(Query, "update", stop_before_update)
    task = run(execution)
    assert fired
    assert task.status == "completed"
    assert task.result_url == "/original.mp4"
    assert task.completed_at == datetime(2025, 1, 1)
    execution.client.queue_prompt.assert_not_awaited()


@pytest.mark.parametrize("execution", [
    {"purpose": "production", "admitted": True}, {"purpose": "benchmark", "admitted": True},
], indirect=True)
@pytest.mark.parametrize("failure", ["gate", "queue", "download", "merge"])
def test_full_run_failure_settles_only_production_status(execution, failure):
    state = execution
    if failure == "gate":
        saved = json.loads(state.task.metadata_json)
        saved["execution"]["request"]["skip_llm_when_prompt_exists"] = False
        state.task.metadata_json = json.dumps(saved)
        state.db.commit()
        state.llm.return_value = {"success": True, "content": "invalid H3 core"}
    elif failure == "queue":
        state.queue_failure = True
    elif failure == "download":
        state.storage.download_video.side_effect = None
        state.storage.download_video.return_value = None
    else:
        state.storage.merge_videos.side_effect = None
        state.storage.merge_videos.return_value = {"success": False, "message": "merge failed"}
    task = run(state)
    assert task.status == "failed", task.error_message
    assert task.completed_at is not None and task.result_url is None
    data = json.loads(task.metadata_json)
    assert data["video_run"]["phase"] == "failed"
    assert data["execution"]["working_shot"]["video_status"] == "failed"
    assert "result" not in data["video_run"] and "result" not in data["execution"]
    state.db.refresh(state.shot)
    production = data["execution_purpose"] == "production"
    assert state.shot.video_status == ("failed" if production else "generating")
    assert len(state.shot_updates) == int(production)
    assert {key: getattr(state.shot, key) for key in state.before_shot if key not in {"video_status", "updated_at"}} == {
        key: value for key, value in state.before_shot.items() if key not in {"video_status", "updated_at"}
    }
    if not production:
        assert {key: getattr(state.shot, key) for key in state.before_shot} == state.before_shot
    if failure == "gate":
        state.client.queue_prompt.assert_not_awaited()
    if failure == "merge":
        assert all(slot["state"] == "SUCCEEDED" for slot in data["video_run"]["clips"].values())
    completed = task.completed_at
    state.execution.fail_execution(state.db, state.execution._handle(task, data), "late failure")
    state.db.refresh(task)
    assert task.completed_at == completed
    assert len(state.shot_updates) == int(production)


@pytest.mark.parametrize("execution", [{"purpose": "production", "admitted": True}], indirect=True)
def test_preclaim_cancel_settlement_uses_request_and_preserves_terminal_facts(execution):
    state = execution
    stamp = datetime(2025, 1, 1)
    state.db.query(state.models.Task).filter_by(id="task", status="pending").update({
        "status": "cancelled", "completed_at": stamp, "error_message": "Cancelled before claim",
    }, synchronize_session=False)
    state.db.refresh(state.task)
    saved = {column.key: getattr(state.task, column.key) for column in state.models.Task.__table__.columns}
    assert "video_run" not in json.loads(state.task.metadata_json)
    assert state.execution.settle_terminated_video(state.db, state.task) is True
    state.db.commit()
    state.db.refresh(state.task)
    state.db.refresh(state.shot)
    assert {key: getattr(state.task, key) for key in saved} == saved
    assert state.shot.video_status == "failed"
    assert state.shot.video_url == state.before_shot["video_url"]
    assert state.shot.video_director_plan == state.before_shot["video_director_plan"]
    assert state.shot.video_director_plan_revision == state.before_shot["video_director_plan_revision"]
    assert state.shot.video_task_id == "task"
    assert len(state.shot_updates) == 1
    assert state.execution.settle_terminated_video(state.db, state.task) is False
    assert len(state.shot_updates) == 1
    state.client.queue_prompt.assert_not_awaited()
    state.client.get_prompt_state.assert_not_awaited()


@pytest.mark.parametrize("execution", [{"purpose": "production", "admitted": True}], indirect=True)
def test_settlement_does_not_commit_the_parent_cancel_transaction(execution):
    state = execution
    state.db.query(state.models.Task).filter_by(id="task", status="pending").update({
        "status": "cancelled", "completed_at": datetime(2025, 1, 1),
    }, synchronize_session=False)
    state.db.refresh(state.task)
    assert state.execution.settle_terminated_video(state.db, state.task) is True
    state.db.refresh(state.shot)
    assert state.shot.video_status == "failed"
    state.db.rollback()
    state.db.refresh(state.task)
    state.db.refresh(state.shot)
    assert state.task.status == "pending" and state.task.completed_at is None
    assert state.shot.video_status == "generating"


@pytest.mark.parametrize("execution", [{"purpose": "production", "admitted": True}], indirect=True)
@pytest.mark.parametrize("claimed", [False, True])
@pytest.mark.parametrize("change", ["owner", "asset", "plan", "completed"])
def test_failure_settlement_never_changes_a_newer_source(execution, claimed, change):
    state = execution
    handle = state.execution.claim_video_execution(state.db, "task")[2] if claimed else None
    with Session(state.engine) as editor:
        shot = editor.get(state.models.Shot, "shot")
        if change == "owner":
            shot.video_task_id = "new-owner"
        elif change == "asset":
            shot.video_url = "/new-formal-asset.mp4"
        elif change == "plan":
            shot.video_director_plan = '{"new_plan": true}'
            shot.video_director_plan_revision += 1
        else:
            shot.video_status = "completed"
        editor.commit()
        saved_source = {column.key: getattr(shot, column.key) for column in state.models.Shot.__table__.columns}
    state.shot_updates.clear()
    if claimed:
        assert state.execution.fail_execution(state.db, handle, "Old execution failed") is True
    else:
        change_task(state, status="cancelled", completed_at=datetime(2025, 1, 1))
        state.db.refresh(state.task)
        assert state.execution.settle_terminated_video(state.db, state.task) is False
    state.db.refresh(state.task)
    state.db.refresh(state.shot)
    assert state.task.status == ("failed" if claimed else "cancelled")
    assert {key: getattr(state.shot, key) for key in saved_source} == saved_source
    assert state.shot_updates == []


@pytest.mark.parametrize("execution", [{"purpose": "production", "admitted": True}], indirect=True)
def test_failed_shot_cas_does_not_undo_task_failure(execution, monkeypatch):
    from sqlalchemy.orm import Query
    state = execution
    task, shot, handle = state.execution.claim_video_execution(state.db, "task")
    update = Query.update
    attempted = []
    def lose_settlement(query, values, *args, **kwargs):
        if query.column_descriptions[0].get("entity") is state.models.Shot:
            assert values == {"video_status": "failed"}
            attempted.append(True)
            return 0
        return update(query, values, *args, **kwargs)
    monkeypatch.setattr(Query, "update", lose_settlement)
    assert state.execution.fail_execution(state.db, handle, "Generation failed") is True
    state.db.refresh(task)
    state.db.refresh(state.shot)
    assert attempted == [True]
    assert task.status == "failed" and task.completed_at is not None
    assert json.loads(task.metadata_json)["video_run"]["phase"] == "failed"
    assert {key: getattr(state.shot, key) for key in state.before_shot} == state.before_shot


@pytest.mark.parametrize("execution", [{"purpose": "production", "admitted": True}], indirect=True)
def test_settlement_exception_rolls_back_task_and_shot_together(execution, monkeypatch):
    from sqlalchemy.orm import Query
    state = execution
    task, shot, handle = state.execution.claim_video_execution(state.db, "task")
    saved_task = {column.key: getattr(task, column.key) for column in state.models.Task.__table__.columns}
    update = Query.update
    def fail_after_settlement(query, values, *args, **kwargs):
        count = update(query, values, *args, **kwargs)
        if query.column_descriptions[0].get("entity") is state.models.Shot:
            raise RuntimeError("Settlement transaction failed")
        return count
    monkeypatch.setattr(Query, "update", fail_after_settlement)
    with pytest.raises(RuntimeError, match="Settlement transaction failed"):
        state.execution.fail_execution(state.db, handle, "Generation failed")
    state.db.refresh(task)
    state.db.refresh(state.shot)
    assert {key: getattr(task, key) for key in saved_task} == saved_task
    assert {key: getattr(state.shot, key) for key in state.before_shot} == state.before_shot


@pytest.mark.parametrize("execution", [
    {"purpose": "benchmark", "admitted": True},
    {"purpose": "production", "admitted": True, "only": 2, "auto_merge": True},
], indirect=True)
def test_preclaim_cancel_never_settles_benchmark_or_clip_only_shots(execution):
    state = execution
    change_task(state, status="cancelled", completed_at=datetime(2025, 1, 1))
    state.db.refresh(state.task)
    assert state.execution.settle_terminated_video(state.db, state.task) is False
    state.db.refresh(state.shot)
    assert {key: getattr(state.shot, key) for key in state.before_shot} == state.before_shot
    assert state.shot_updates == []


@pytest.mark.parametrize("execution", [{"purpose": "production", "only": 2, "auto_merge": True}], indirect=True)
def test_successful_unadopted_production_clip_remains_detached(execution):
    task = run(execution)
    assert task.status == "completed", task.error_message
    data = json.loads(task.metadata_json)
    assert data["video_run"]["result"]["kind"] == "clip"
    assert data["video_run"]["result"]["attachment"] == "detached"
    assert data["execution"]["result"] == data["video_run"]["result"]
    assert execution.execution.completed_video_artifact(execution.db, "task")["success"] is False
    assert execution.shot_updates == []


@pytest.mark.parametrize("execution", [{"purpose": "production", "admitted": True}], indirect=True)
@pytest.mark.parametrize("failure", ["unstarted-timeout", "claim-rejection"])
def test_unclaimed_failure_paths_also_settle_owned_production_shots(execution, failure):
    state = execution
    if failure == "unstarted-timeout":
        change_task(state, created_at=datetime.utcnow() - timedelta(hours=1))
        state.db.refresh(state.task)
        assert asyncio.run(state.execution.reconcile_video_execution(state.db, state.task)) is True
        state.db.refresh(state.task)
        task = state.task
    else:
        saved = json.loads(state.task.metadata_json)
        saved["execution"]["request"]["selected_mode"] = "invalid mode"
        state.task.metadata_json = json.dumps(saved)
        state.db.commit()
        task = run(state)
    state.db.refresh(state.shot)
    assert task.status == "failed"
    assert state.shot.video_status == "failed"
    assert state.shot.video_url == state.before_shot["video_url"]
    assert state.shot.video_director_plan == state.before_shot["video_director_plan"]
    assert len(state.shot_updates) == 1
    state.client.queue_prompt.assert_not_awaited()


# Exact class/field/value spellings in the accepted V017 task/history comparison.
H3_SPELLINGS = (
    ("46", "VHS_VideoCombine", "frame_rate", 24),
    ("53", "MiniMaxH3DualClockSamplerT8", "shift_video", 12),
    ("53", "MiniMaxH3DualClockSamplerT8", "shift_audio", 3),
    ("54", "MiniMaxH3AudioConditioningT8", "audio_denoise_strength", 0),
    ("93", "CreateVideo", "fps", 24),
    ("94", "RTXVideoSuperResolution", "resize_type.scale", 2),
)


@pytest.fixture
def h3_numeric(monkeypatch):
    import sqlite3
    from types import SimpleNamespace
    def forbidden(*args, **kwargs):
        raise AssertionError("Numeric comparison must not access a database or network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(sqlite3.dbapi2, "connect", forbidden)
    backend = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("_pure_h3_numeric", backend / "app/services/keyframe_reference_graph.py")
    graphs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(graphs)
    graph = json.loads((backend / "workflows/three_frame_video_minimax_h3_audiodrive.json").read_text(encoding="utf-8"))
    for node, kind, field, value in H3_SPELLINGS:
        assert graph[node]["class_type"] == kind
        graph[node]["inputs"][field] = value
    return SimpleNamespace(graphs=graphs, graph=graph,
                           digest=lambda value: graphs.numeric_graph_digest(value, extra_number_ports=graphs.H3_NUMBER_PORTS))


@pytest.mark.parametrize("node,kind,field,value", H3_SPELLINGS)
@pytest.mark.parametrize("reverse", [False, True])
def test_confirmed_h3_port_spelling_equivalence_is_opt_in_and_pure(h3_numeric, node, kind, field, value, reverse):
    state = h3_numeric
    integer, floating = deepcopy(state.graph), deepcopy(state.graph)
    floating[node]["inputs"][field] = float(value)
    left, right = (floating, integer) if reverse else (integer, floating)
    before = json.dumps([left, right], ensure_ascii=False)
    assert state.digest(left) == state.digest(right)
    assert state.graphs.numeric_graph_digest(left) != state.graphs.numeric_graph_digest(right)
    assert json.dumps([left, right], ensure_ascii=False) == before


@pytest.mark.parametrize("reverse", [False, True])
def test_all_six_h3_spellings_preserve_raw_seals_and_do_not_extend_09(h3_numeric, reverse):
    state = h3_numeric
    other = deepcopy(state.graph)
    for node, _, field, value in H3_SPELLINGS:
        other[node]["inputs"][field] = float(value)
    left, right = (other, state.graph) if reverse else (state.graph, other)
    before = json.dumps([left, right], ensure_ascii=False)
    assert state.digest(left) == state.digest(right)
    assert state.graphs.numeric_graph_digest(left) != state.graphs.numeric_graph_digest(right)
    for graph in (left, right):
        with pytest.raises(state.graphs.KeyframeGraphError, match="Unsupported class"):
            state.graphs.semantic_graph_digest(graph)
        with pytest.raises(state.graphs.KeyframeGraphError, match="Unsupported class"):
            state.graphs.validate_keyframe_graph(graph, {"prompt_node_id": "51", "save_image_node_id": "95"}, reference_count=1)
    assert json.dumps([left, right], ensure_ascii=False) == before


@pytest.mark.parametrize("location", [
    "unknown-class", "unknown-port", "metadata", "runtime-metadata", "unknown-float-widget", "guessed-upscale",
    "seed", "steps", "loop-count", "bit-depth", "width", "height", "inactive-scale",
    "video-link", "float-link", "nested-list", "metadata-list", "unreviewed-lora",
])
@pytest.mark.parametrize("value", [1.0, True, "1", None])
def test_h3_numeric_identity_never_aliases_unreviewed_types(h3_numeric, location, value):
    state = h3_numeric
    graph = deepcopy(state.graph)
    if location == "unknown-class":
        graph["opaque"] = {"class_type": "UnknownVideo", "inputs": {"fps": 1}}
        container, field = graph["opaque"]["inputs"], "fps"
    elif location == "unknown-port":
        container, field = graph["46"]["inputs"], "unreviewed_number"
    elif location == "metadata":
        container, field = graph["46"]["_meta"], "number"
    elif location == "runtime-metadata":
        container, field = graph["46"], "is_changed"
    elif location == "unknown-float-widget":
        container, field = graph["48"]["inputs"], "value"
    elif location == "guessed-upscale":
        graph["opaque"] = {"class_type": "ImageScaleBy", "inputs": {"upscale_by": 1}}
        container, field = graph["opaque"]["inputs"], "upscale_by"
    elif location in {"seed", "steps", "loop-count", "bit-depth", "unreviewed-lora"}:
        node, field = {"seed": ("42", "noise_seed"), "steps": ("53", "steps"), "loop-count": ("46", "loop_count"),
                       "bit-depth": ("93", "bit_depth"), "unreviewed-lora": ("52", "strength_model")}[location]
        container = graph[node]["inputs"]
    elif location in {"width", "height", "inactive-scale"}:
        container = graph["94"]["inputs"]
        container["resize_type"] = "target dimensions"
        field = "resize_type." + ("scale" if location == "inactive-scale" else location)
    elif location in {"video-link", "float-link"}:
        if location == "float-link":
            graph["93"]["inputs"]["fps"] = ["48", 1]
        container, field = (graph["93"]["inputs"]["fps"] if location == "float-link" else graph["95"]["inputs"]["video"]), 1
    else:
        owner = graph["93"]["inputs"] if location == "nested-list" else graph["93"]["_meta"]
        owner["numbers"] = [[1, 2]]
        container, field = owner["numbers"][0], 0
    container[field] = 1
    expected = state.digest(graph)
    container[field] = value
    before = json.dumps(graph, ensure_ascii=False)
    try:
        actual = state.digest(graph)
    except state.graphs.KeyframeGraphError:
        assert location == "float-link"
    else:
        assert actual != expected
    assert json.dumps(graph, ensure_ascii=False) == before


@pytest.mark.parametrize("node,kind,field,value", H3_SPELLINGS)
@pytest.mark.parametrize("impostor", [None, True, False, "1", {"number": 1}, [1], float("nan"), float("inf"), -float("inf")])
def test_h3_float_ports_reject_nonnumeric_impostors(h3_numeric, node, kind, field, value, impostor):
    graph = deepcopy(h3_numeric.graph)
    graph[node]["inputs"][field] = impostor
    before = json.dumps(graph, ensure_ascii=False)
    with pytest.raises(h3_numeric.graphs.KeyframeGraphError):
        h3_numeric.digest(graph)
    assert json.dumps(graph, ensure_ascii=False) == before


@pytest.mark.parametrize("change", ["link-slot-float", "link-slot-bool", "link-source-type", "link-source", "link-order",
                                     "link-tuple", "metadata-tuple", "metadata-key-type", "metadata-order", "prompt", "media", "extra-node"])
def test_h3_graph_identity_preserves_all_other_evidence(h3_numeric, change):
    state = h3_numeric
    graph = deepcopy(state.graph)
    graph["95"]["_meta"].update(order=[1, 2], mapping={"1": "value"})
    expected = state.digest(graph)
    if change == "link-slot-float":
        graph["95"]["inputs"]["video"][1] = 0.0
    elif change == "link-slot-bool":
        graph["95"]["inputs"]["video"][1] = False
    elif change == "link-source-type":
        graph["95"]["inputs"]["video"][0] = 92
    elif change == "link-source":
        graph["95"]["inputs"]["video"][0] = "93"
    elif change == "link-order":
        graph["95"]["inputs"]["video"].reverse()
    elif change == "link-tuple":
        graph["95"]["inputs"]["video"] = tuple(graph["95"]["inputs"]["video"])
    elif change == "metadata-tuple":
        graph["95"]["_meta"]["order"] = (1, 2)
    elif change == "metadata-key-type":
        graph["95"]["_meta"]["mapping"] = {1: "value"}
    elif change == "metadata-order":
        graph["95"]["_meta"]["order"].reverse()
    elif change == "prompt":
        graph["51"]["inputs"]["prompt"] += " "
    elif change == "media":
        graph["45"]["inputs"]["image"] = "another.png"
    else:
        graph["new"] = {"class_type": "UnknownVideo", "inputs": {}}
    if change in {"link-tuple", "metadata-tuple", "metadata-key-type"}:
        with pytest.raises(state.graphs.KeyframeGraphError):
            state.digest(graph)
    else:
        assert state.digest(graph) != expected


@pytest.mark.parametrize("integer", [2**53 - 1, 2**53, 2**53 + 1, 2**63 + 55])
def test_h3_numeric_folding_respects_safe_integer_limit(h3_numeric, integer):
    graph = deepcopy(h3_numeric.graph)
    graph["46"]["inputs"]["frame_rate"] = integer
    before = json.dumps(graph, ensure_ascii=False)
    expected = h3_numeric.digest(graph)
    assert json.dumps(graph, ensure_ascii=False) == before
    graph["46"]["inputs"]["frame_rate"] = float(integer)
    assert (h3_numeric.digest(graph) == expected) is (integer <= 2**53 - 1)


def test_h3_negative_zero_and_nonintegral_values_are_not_folded(h3_numeric):
    graph = deepcopy(h3_numeric.graph)
    integer = h3_numeric.digest(graph)
    graph["54"]["inputs"]["audio_denoise_strength"] = -0.0
    negative = h3_numeric.digest(graph)
    graph["54"]["inputs"]["audio_denoise_strength"] = 0.0
    assert h3_numeric.digest(graph) == integer != negative
    graph["46"]["inputs"]["frame_rate"] = 1
    integer = h3_numeric.digest(graph)
    graph["46"]["inputs"]["frame_rate"] = 1.0000000000000002
    assert h3_numeric.digest(graph) != integer
    graph["46"]["inputs"]["frame_rate"] = 10**400
    before = json.dumps(graph, ensure_ascii=False)
    assert h3_numeric.digest(graph)
    assert json.dumps(graph, ensure_ascii=False) == before


@pytest.mark.parametrize("field,value", [("fps", 121), ("frame_rate", 0), ("shift_video", 101),
                                         ("shift_audio", 0), ("audio_denoise_strength", 2), ("resize_type.scale", 5)])
def test_h3_aliases_require_reviewed_schema_bounds(h3_numeric, field, value):
    graph = deepcopy(h3_numeric.graph)
    node = next(node for node, _, port, _ in H3_SPELLINGS if field == port)
    graph[node]["inputs"][field] = value
    with pytest.raises(h3_numeric.graphs.KeyframeGraphError):
        h3_numeric.digest(graph)


@pytest.mark.parametrize("execution", [{"windows": 1}], indirect=True)
@pytest.mark.parametrize("reverse", [False, True])
def test_h3_numeric_history_does_not_rewrite_raw_task_graph_or_seal(execution, reverse):
    state, module = execution, execution.execution
    task, shot, handle = module.claim_video_execution(state.db, "task")
    slot = complete_slot(state, handle, 1)
    submitted = json.loads((Path(__file__).parents[1] / "workflows/three_frame_video_minimax_h3_audiodrive.json").read_text(encoding="utf-8"))
    history_graph = deepcopy(submitted)
    for node, kind, field, value in H3_SPELLINGS:
        assert submitted[node]["class_type"] == kind
        submitted[node]["inputs"][field] = float(value) if reverse else value
        history_graph[node]["inputs"][field] = value if reverse else float(value)
    slot["submission"].update(graph=submitted, graph_hash=module.digest(submitted), output_node="95")
    history = {"prompt": [0, slot["submission"]["prompt_id"], history_graph],
               "status": {"completed": True, "status_str": "success"},
               "outputs": {"95": {"images": [{"filename": "receipt-1.mp4", "subfolder": "video", "type": "output"}]}}}
    slot["receipt"].update(graph_hash=slot["submission"]["graph_hash"], history=module.capture(handle, "history", history))
    raw_graph = json.dumps(submitted, ensure_ascii=False)
    def save(data):
        data["video_run"]["clips"]["1"] = slot
        return {"workflow_json": raw_graph, "comfyui_prompt_id": slot["submission"]["prompt_id"]}
    module._write(state.db, handle, save)
    saved_task = {column.key: getattr(task, column.key) for column in state.models.Task.__table__.columns}
    original = json.dumps([slot, history], ensure_ascii=False)
    assert module.verify_history(slot, history) == slot["receipt"]["source_url"]
    assert module.completion_manifest(json.loads(task.metadata_json))[0]["graph_hash"] == module.digest(submitted)
    assert json.dumps([slot, history], ensure_ascii=False) == original
    assert module.digest(submitted) != module.digest(history_graph)
    broken_seal = deepcopy(slot)
    broken_seal["submission"]["graph_hash"] = module.digest(history_graph)
    with pytest.raises(module.ExecutionConflict, match="HISTORY_NOT_PROVEN"):
        module.verify_history(broken_seal, history)
    state.db.refresh(task)
    assert {key: getattr(task, key) for key in saved_task} == saved_task
    assert state.shot_updates == []


@pytest.mark.parametrize("container", ["list", "dict"])
def test_h3_numeric_identity_rejects_non_json_cycles(h3_numeric, container):
    graph = deepcopy(h3_numeric.graph)
    graph["95"]["_meta"]["cycle"] = [graph] if container == "list" else graph
    with pytest.raises(h3_numeric.graphs.KeyframeGraphError, match="finite JSON"):
        h3_numeric.digest(graph)


def test_h3_numeric_opt_in_cannot_reclassify_keyframe_integer_ports(h3_numeric):
    with pytest.raises(h3_numeric.graphs.KeyframeGraphError, match="cannot override"):
        h3_numeric.graphs.numeric_graph_digest(h3_numeric.graph, extra_number_ports={
            "RandomNoise": {"noise_seed": (0, None, None)},
        })


@pytest.mark.parametrize("slot", [0.0, False, "0", None])
def test_h3_float_port_connections_require_exact_integer_slots(h3_numeric, slot):
    graph = deepcopy(h3_numeric.graph)
    graph["93"]["inputs"]["fps"] = ["48", 0]
    before = json.dumps(graph, ensure_ascii=False)
    assert h3_numeric.digest(graph)
    assert json.dumps(graph, ensure_ascii=False) == before
    graph["93"]["inputs"]["fps"][1] = slot
    with pytest.raises(h3_numeric.graphs.KeyframeGraphError):
        h3_numeric.digest(graph)
