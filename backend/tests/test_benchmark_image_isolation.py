"""Task-private image regressions: --noconftest, no live DB, startup or network."""
import ast
import asyncio
from copy import deepcopy
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from types import ModuleType, SimpleNamespace

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Query

import test_keyframe_reference_worker as p1
from test_keyframe_reference_worker import worker as reference_worker


SHOT_NUMBER_FIELDS = (("107", "megapixels"), ("108", "cfg"), ("128", "megapixels"), ("133", "megapixels"))


@pytest.fixture
def isolated(reference_worker, monkeypatch):
    state = reference_worker

    def load(name, relative):
        spec = importlib.util.spec_from_file_location(name, p1.BACKEND / relative)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        return module

    state.execution = load("app.services.task_execution", "app/services/task_execution.py")
    # Load the real class without constructing its production singleton.
    source = ast.parse((p1.BACKEND / "app/services/file_storage.py").read_text())
    source.body = [node for node in source.body if not (
        isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "file_storage" for target in node.targets)
    )]
    storage_module = ModuleType("_benchmark_storage")
    exec(compile(source, str(p1.BACKEND / "app/services/file_storage.py"), "exec"), storage_module.__dict__)
    state.storage_module = storage_module
    state.storage = storage_module.FileStorageService(base_dir=state.root)
    monkeypatch.setattr(sys.modules["app.services.file_storage"], "file_storage", state.storage)
    monkeypatch.setattr(sys.modules["app.services.file_storage"], "FileStorageService", storage_module.FileStorageService, raising=False)
    monkeypatch.setattr(state.module, "file_storage", state.storage)
    state.http_calls = []

    class LocalHTTP:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, **kwargs):
            assert url.startswith(p1.ENDPOINT + "/view?")
            state.http_calls.append(url)
            state.events.append("download")
            hook = state.hooks.pop("download", None)
            if hook:
                hook()
            if state.output_kind == "missing":
                raise OSError("download failed")
            data = b"invalid image" if state.output_kind == "corrupt" else Path(state.to_path(state.urls["replacement"])).read_bytes()
            return SimpleNamespace(content=data, raise_for_status=lambda: None)

    monkeypatch.setattr(storage_module.httpx, "AsyncClient", LocalHTTP)
    load("app.utils.image_utils", "app/utils/image_utils.py")
    load("app.utils.workflow_disconnect", "app/utils/workflow_disconnect.py")
    state.images = load("app.services.shot_image_service", "app/services/shot_image_service.py")

    def image_client(endpoint):
        client = state.client_factory(endpoint)

        async def upload(path):
            return await client.upload(path, upload_name=Path(path).name, payload=Path(path).read_bytes())

        client.upload_image = upload
        return client

    monkeypatch.setattr(state.contracts, "frozen_keyframe_client", image_client)
    state.protect_shot = True
    state.shot_writes = []

    def forbid_shot_writes(conn, cursor, statement, parameters, context, executemany):
        if re.match(r'^\s*(UPDATE|INSERT\s+INTO|DELETE\s+FROM)\s+["`]?shots\b', statement, re.I):
            state.shot_writes.append(statement)
            assert not state.protect_shot, "Benchmark must never issue production Shot SQL"

    event.listen(state.engine, "before_cursor_execute", forbid_shot_writes)
    yield state
    event.remove(state.engine, "before_cursor_execute", forbid_shot_writes)


def shot_columns(state):
    shot = p1.saved(state).shot
    return {column.key: getattr(shot, column.key) for column in state.Shot.__table__.columns}


def original_bytes(state):
    return {url: Path(state.to_path(url)).read_bytes() for url in state.urls.values()}


def create_image(state, *, purpose="benchmark"):
    with state.sessions() as db:
        shot = db.get(state.Shot, "shot")
        workflow = db.get(state.Workflow, "workflow")
        mapping = json.loads(workflow.node_mapping)
        mapping["character_reference_image_node_id"] = mapping["reference_image_node_id"]
        workflow.node_mapping = json.dumps(mapping)
        task = state.Task(type="shot_image", status="pending", name="Image attempt", novel_id="novel", chapter_id="chapter",
                          shot_id="shot", workflow_id="workflow", workflow_name=workflow.name, prompt_text="Literal benchmark prompt.",
                          metadata_json=json.dumps(state.execution.create_execution_metadata(shot, purpose=purpose)))
        db.add(task)
        db.commit()
        state.task_id = task.id
        return task.id


def run_image(state):
    asyncio.run(state.images.generate_shot_image_task(state.task_id, "wrong-novel", "wrong-chapter", 999, "Wrong stale prompt", "wrong-workflow"))
    return p1.saved(state)


def restore_task(state, snapshot):
    with state.sessions() as db:
        current = db.get(state.Task, snapshot.id)
        for column in state.Task.__table__.columns:
            setattr(current, column.key, getattr(snapshot, column.key))
        db.commit()


def history_for(state, task):
    graph = json.loads(task.workflow_json)
    node = next(key for key, value in graph.items() if value["class_type"] == "SaveImage")
    return {"prompt": [0, task.comfyui_prompt_id, graph, {}, [node]], "status": {"completed": True},
             "outputs": {node: {"images": [{"filename": "result.png", "subfolder": "", "type": "output"}]}}}


@pytest.fixture
def three_reference_image(isolated):
    state = isolated
    create_image(state)
    graph = json.loads((p1.BACKEND / "workflows/shot_flux2_klein_three_ref_edit.json").read_text())
    mapping = {"prompt_node_id": "117", "save_image_node_id": "9", "width_node_id": "123", "height_node_id": "125",
               "character_reference_image_node_id": "76", "scene_reference_image_node_id": "127", "custom_reference_image_node_1": "132"}
    with state.sessions() as db:
        workflow = db.get(state.Workflow, "workflow")
        workflow.workflow_json, workflow.node_mapping, workflow.type = json.dumps(graph), json.dumps(mapping), "shot"
        db.commit()
    return state


def exact_graph_hash(graph):
    encoded = json.dumps(graph, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


@pytest.mark.parametrize("fields", [(field,) for field in SHOT_NUMBER_FIELDS] + [SHOT_NUMBER_FIELDS])
@pytest.mark.parametrize("prepared_float", [False, True])
def test_three_reference_shot_worker_accepts_only_numeric_reencoding(three_reference_image, fields, prepared_float):
    state = three_reference_image
    before, files, histories = shot_columns(state), original_bytes(state), []
    if prepared_float:
        with state.sessions() as db:
            workflow = db.get(state.Workflow, "workflow")
            graph = json.loads(workflow.workflow_json)
            for node, field in fields:
                graph[node]["inputs"][field] = 1.0
            workflow.workflow_json = json.dumps(graph)
            db.commit()

    def numeric_history(history):
        for node, field in fields:
            history["prompt"][2][node]["inputs"][field] = 1 if prepared_float else 1.0
        histories.append(deepcopy(history))

    state.history_hook = numeric_history
    result = run_image(state)
    assert result.task.status == "completed", result.task.error_message
    graph = json.loads(result.task.workflow_json)
    record = state.execution.execution_record(result.task)
    proof = record["shot_image"]
    attempted = state.execution.execution_record(state.prequeue[0].task)["shot_image"]
    assert attempted["submission_state"] == "attempted" and proof["submission_state"] == "submitted"
    assert proof["graph_hash"] == attempted["graph_hash"] == exact_graph_hash(state.queued[0]) == state.images._image_graph_hash(graph)
    assert proof["semantic_graph_hash"] == attempted["semantic_graph_hash"] == state.graphs.numeric_graph_digest(graph)
    assert (proof["graph_hash"] != proof["semantic_graph_hash"]) is prepared_float
    assert exact_graph_hash(histories[0]["prompt"][2]) != proof["graph_hash"]
    assert state.graphs.numeric_graph_digest(histories[0]["prompt"][2]) == proof["semantic_graph_hash"]
    assert json.dumps(graph, sort_keys=True) == json.dumps(state.queued[0], sort_keys=True)
    for node, field in SHOT_NUMBER_FIELDS:
        assert type(graph[node]["inputs"][field]) is (float if prepared_float and (node, field) in fields else int)
    for node, upload in zip(("76", "127", "132"), state.uploads):
        assert graph[node]["inputs"]["image"] == "receipts/" + upload["upload_name"]
    assert len(state.uploads) == 3 and len(state.queued) == len(state.http_calls) == 1
    assert record["version"] == 1 and record["result"]["attachment"] == "archived"
    assert shot_columns(state) == before and original_bytes(state) == files and not state.shot_writes


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("fields", [(field,) for field in SHOT_NUMBER_FIELDS] + [SHOT_NUMBER_FIELDS])
def test_three_reference_shot_recovery_accepts_numeric_history_and_legacy_receipt(three_reference_image, fields, legacy):
    state = three_reference_image
    before, captured = shot_columns(state), []
    state.hooks["download"] = lambda: captured.append(p1.saved(state).task)
    assert run_image(state).task.status == "completed"
    snapshot = captured[0]
    if legacy:
        metadata = json.loads(snapshot.metadata_json)
        metadata["execution"]["shot_image"].pop("semantic_graph_hash")
        snapshot.metadata_json = json.dumps(metadata)
    restore_task(state, snapshot)
    with state.sessions() as db:
        task = db.get(state.Task, state.task_id)
        history = history_for(state, task)
        for node, field in fields:
            history["prompt"][2][node]["inputs"][field] = 1.0
        metadata_before, graph_before = task.metadata_json, task.workflow_json
        history_before = json.dumps(history, sort_keys=True)
        receipt = state.execution.execution_record(task)["shot_image"]
        assert receipt["graph_hash"] == exact_graph_hash(json.loads(graph_before))
        assert state.images._benchmark_shot_image_output(task, history).endswith("filename=result.png&subfolder=&type=output")
        assert task.metadata_json == metadata_before and task.workflow_json == graph_before
        assert json.dumps(history, sort_keys=True) == history_before
        assert asyncio.run(state.images.recover_benchmark_shot_image(db, task, history)) is True
        assert task.workflow_json == graph_before
        assert state.execution.execution_record(task)["shot_image"] == receipt
        assert ("semantic_graph_hash" not in receipt) is legacy
        calls = len(state.http_calls)
        assert asyncio.run(state.images.recover_benchmark_shot_image(db, task, None)) is True
        assert len(state.http_calls) == calls
    assert len(state.queued) == 1 and len(state.http_calls) == 2
    assert shot_columns(state) == before and not state.shot_writes


@pytest.mark.parametrize("stage", ["worker", "recovery"])
@pytest.mark.parametrize("change", [
    "bool", "false", "string", "null", "value", "adjacent-float", "nan", "inf", "negative-inf",
    "107-bool", "128-bool", "133-bool", "link-slot-float", "link-slot-bool", "link-order", "connection",
    "seed", "seed-float", "metadata-number", "metadata-order", "unknown-node-number", "unknown-port-number",
    "prompt", "character-binding", "scene-binding", "prop-binding", "runtime-field",
])
def test_shot_numeric_equivalence_preserves_all_other_history_evidence(three_reference_image, stage, change):
    state = three_reference_image
    # Unknown node/port values are deliberately frozen too, never normalized or dropped.
    with state.sessions() as db:
        workflow = db.get(state.Workflow, "workflow")
        graph = json.loads(workflow.workflow_json)
        graph["opaque"] = {"class_type": "UnreviewedNode", "inputs": {"cfg": 1}}
        graph["108"]["inputs"]["unreviewed_number"] = 1
        graph["9"]["_meta"].update(number=1, order=[1, 2])
        workflow.workflow_json = json.dumps(graph)
        db.commit()
    before, original_histories = shot_columns(state), []

    def changed_history(history):
        graph = history["prompt"][2]
        for node, field in SHOT_NUMBER_FIELDS:
            graph[node]["inputs"][field] = 1.0
        values = {"bool": True, "false": False, "string": "1", "null": None, "value": 2,
                  "adjacent-float": 1.0000000000000002, "nan": float("nan"), "inf": float("inf"), "negative-inf": -float("inf")}
        if change in values:
            graph["108"]["inputs"]["cfg"] = values[change]
        elif change in {"107-bool", "128-bool", "133-bool"}:
            graph[change.split("-")[0]]["inputs"]["megapixels"] = True
        elif change in {"link-slot-float", "link-slot-bool", "link-order", "connection"}:
            graph["101"]["inputs"]["samples"] = {
                "link-slot-float": ["100", 0.0], "link-slot-bool": ["100", False],
                "link-order": [0, "100"], "connection": ["100", 1],
            }[change]
        elif change.startswith("seed"):
            seed = graph["102"]["inputs"]["noise_seed"]
            graph["102"]["inputs"]["noise_seed"] = float(seed) if change == "seed-float" else seed + 1
        elif change == "metadata-number":
            graph["9"]["_meta"]["number"] = 1.0
        elif change == "metadata-order":
            graph["9"]["_meta"]["order"].reverse()
        elif change == "unknown-node-number":
            graph["opaque"]["inputs"]["cfg"] = 1.0
        elif change == "unknown-port-number":
            graph["108"]["inputs"]["unreviewed_number"] = 1.0
        elif change == "prompt":
            graph["117"]["inputs"]["text"] += " changed"
        elif change.endswith("binding"):
            node = {"character-binding": "76", "scene-binding": "127", "prop-binding": "132"}[change]
            graph[node]["inputs"]["image"] = "other.png"
        else:
            graph["76"]["is_changed"] = ["runtime-cache-fingerprint"]
        original_histories.append((history, json.dumps(history, sort_keys=True)))

    if stage == "worker":
        state.history_hook = changed_history
        result = run_image(state)
        assert result.task.status == "failed" and "BENCHMARK_IMAGE_HISTORY_MISMATCH" in result.task.error_message
        assert not state.http_calls
    else:
        captured = []
        state.hooks["download"] = lambda: captured.append(p1.saved(state).task)
        assert run_image(state).task.status == "completed"
        restore_task(state, captured[0])
        with state.sessions() as db:
            task = db.get(state.Task, state.task_id)
            history = history_for(state, task)
            changed_history(history)
            assert asyncio.run(state.images.recover_benchmark_shot_image(db, task, history)) is False
            assert task.status == "failed" and "BENCHMARK_IMAGE_HISTORY_MISMATCH" in task.error_message
        assert len(state.http_calls) == 1
    result = p1.saved(state)
    receipt = state.execution.execution_record(result.task)["shot_image"]
    assert receipt["graph_hash"] == exact_graph_hash(state.queued[0])
    assert json.dumps(json.loads(result.task.workflow_json), sort_keys=True) == json.dumps(state.queued[0], sort_keys=True)
    assert all(json.dumps(history, sort_keys=True) == original for history, original in original_histories)
    assert len(state.queued) == 1 and shot_columns(state) == before and not state.shot_writes


@pytest.mark.parametrize("change", ["task-numeric", "task-seed", "raw-hash", "semantic-hash", "semantic-null"])
def test_shot_recovery_checks_raw_frozen_graph_and_optional_semantic_receipt(three_reference_image, change):
    state = three_reference_image
    captured = []
    state.hooks["download"] = lambda: captured.append(p1.saved(state).task)
    assert run_image(state).task.status == "completed"
    task = captured[0]
    history = history_for(state, task)
    if change.startswith("task-"):
        graph = json.loads(task.workflow_json)
        if change == "task-numeric":
            graph["108"]["inputs"]["cfg"] = 1.0
        else:
            graph["102"]["inputs"]["noise_seed"] += 1
        task.workflow_json = json.dumps(graph)
    else:
        metadata = json.loads(task.metadata_json)
        receipt = metadata["execution"]["shot_image"]
        receipt["graph_hash" if change == "raw-hash" else "semantic_graph_hash"] = None if change == "semantic-null" else "0" * 64
        task.metadata_json = json.dumps(metadata)
    restore_task(state, task)
    before = shot_columns(state)
    with state.sessions() as db:
        current = db.get(state.Task, state.task_id)
        assert asyncio.run(state.images.recover_benchmark_shot_image(db, current, history)) is False
        assert current.status == "failed" and "BENCHMARK_IMAGE_SUBMISSION_UNVERIFIED" in current.error_message
    assert len(state.http_calls) == len(state.queued) == 1
    assert shot_columns(state) == before and not state.shot_writes


def test_shot_worker_archives_literal_prompt_private_composites_and_result(isolated):
    state = isolated
    before, files = shot_columns(state), original_bytes(state)
    create_image(state)
    result = run_image(state)
    assert result.task.status == "completed", result.task.error_message
    assert result.task.prompt_text == "Literal benchmark prompt."
    state.llm.assert_not_awaited()
    record = state.execution.execution_record(result.task)
    assert record["result"]["attachment"] == "archived"
    assert record["working_shot"]["image_url"] == result.task.result_url
    assert record["working_shot"]["shot_image_prompt"] == result.task.prompt_text
    assert record["shot_snapshot"]["image_url"] == before["image_url"]
    assert f"/benchmarks/{result.task.id}/{record['attempt_id']}/" in result.task.result_url
    assert record["reference_sources"] and all("/benchmarks/" in item["url"] for item in record["reference_sources"])
    assert "/benchmarks/" in record["working_shot"]["merged_character_image"]
    assert shot_columns(state) == before and original_bytes(state) == files
    assert not state.shot_writes


def test_keyframe_creation_prompt_and_result_use_only_private_cas(isolated):
    state = isolated
    before, files = shot_columns(state), original_bytes(state)
    p1.create(state, workflow_id="workflow", execution_purpose="benchmark")
    created = p1.saved(state)
    record = state.execution.execution_record(created.task)
    private = json.loads(record["working_shot"]["keyframes"])[state.frame_index]
    assert private["image_task_id"] == created.task.id
    assert private["image_url"] == created.frames[state.frame_index]["image_url"]
    assert shot_columns(state) == before
    result = p1.run(state)
    assert result.task.status == "completed", result.task.error_message
    assert result.contract["result"]["attachment"] == "archived"
    record = state.execution.execution_record(result.task)
    private_plan = json.loads(record["working_shot"]["video_director_plan"])
    private_frame = json.loads(record["working_shot"]["keyframes"])[state.frame_index]
    assert private_frame["prompt_text"] == result.task.prompt_text
    assert private_frame["image_url"] == result.task.result_url
    assert private_plan["keyframes"][state.target_kf - 1]["image_url"] == result.task.result_url
    assert private_plan["ai_calls"] and not result.plan["ai_calls"]
    assert shot_columns(state) == before and original_bytes(state) == files
    assert not state.shot_writes


@pytest.mark.parametrize("kind", ["shot", "keyframe"])
@pytest.mark.parametrize("failure", ["queue", "missing", "corrupt"])
def test_failed_attempts_keep_private_prompts_and_never_claim_local_archive(isolated, kind, failure):
    state = isolated
    before, files = shot_columns(state), original_bytes(state)
    if failure == "queue":
        state.queue_response = {"success": False, "error": "queue failed"}
    else:
        state.output_kind = failure
    if kind == "shot":
        create_image(state)
        result = run_image(state)
    else:
        p1.create(state, workflow_id="workflow", execution_purpose="benchmark")
        result = p1.run(state)
    assert result.task.status == "failed"
    assert result.task.prompt_text
    assert not result.task.result_url or "/api/files/" in result.task.result_url
    record = state.execution.execution_record(result.task)
    assert record.get("result", {}).get("attachment") != "archived"
    assert shot_columns(state) == before and original_bytes(state) == files


@pytest.mark.parametrize("kind", ["shot", "keyframe"])
@pytest.mark.parametrize("stage", ["queue", "download"])
@pytest.mark.parametrize("terminal", ["cancelled", "failed", "deleted"])
def test_late_cancellation_keeps_terminal_status_and_detached_evidence(isolated, kind, stage, terminal):
    state = isolated
    before = shot_columns(state)
    if kind == "shot":
        create_image(state)
    else:
        p1.create(state, workflow_id="workflow", execution_purpose="benchmark")

    def cancel():
        with state.sessions() as db:
            task = db.get(state.Task, state.task_id)
            if terminal == "deleted":
                db.delete(task)
            else:
                task.status, task.error_message = terminal, "Original terminal reason"
            db.commit()

    state.hooks[stage] = cancel
    result = run_image(state) if kind == "shot" else p1.run(state)
    assert shot_columns(state) == before
    if terminal == "deleted":
        assert result.task is None
        return
    assert result.task.status == terminal and result.task.error_message == "Original terminal reason"
    if stage == "queue" and kind == "shot":
        observations = json.loads(result.task.metadata_json)["execution_observations"]
        acknowledgement = next(item["details"] for item in observations if "details" in item)
        assert acknowledgement["prompt_id"] and acknowledgement["workflow"] == state.queued[0]
    if stage == "download":
        metadata = json.loads(result.task.metadata_json)
        evidence = metadata.get("execution_observations", []) + metadata.get("keyframe_reference_observations", [])
        retained = [item.get("artifact_url") for item in evidence if item.get("artifact_url")]
        retained += [result.contract.get("result", {}).get("url")] if result.contract else []
        assert any(retained)


@pytest.mark.parametrize("kind", ["shot", "keyframe"])
def test_exact_history_recovery_archives_idempotently_without_shot_writes(isolated, kind):
    state = isolated
    before = shot_columns(state)
    if kind == "shot":
        create_image(state)
    else:
        p1.create(state, workflow_id="workflow", execution_purpose="benchmark")
    captured = []
    state.hooks["download"] = lambda: captured.append(p1.saved(state).task)
    first = run_image(state) if kind == "shot" else p1.run(state)
    assert first.task.status == "completed", first.task.error_message
    restore_task(state, captured[0])
    hook = state.images.recover_benchmark_shot_image if kind == "shot" else state.service.recover_benchmark_image
    with state.sessions() as db:
        task = db.get(state.Task, state.task_id)
        assert asyncio.run(hook(db, task, history_for(state, task))) is True
        archived = task.result_url
        calls = len(state.http_calls)
        assert asyncio.run(hook(db, task, None)) is True
        assert len(state.http_calls) == calls and task.result_url == archived
    assert archived != first.task.result_url
    assert Path(state.to_path(first.task.result_url)).is_file()
    assert shot_columns(state) == before and not state.shot_writes


@pytest.mark.parametrize("change", ["cid", "graph", "output"])
def test_shot_recovery_rejects_unproven_history_before_download(isolated, change):
    state = isolated
    create_image(state)
    captured = []
    state.hooks["download"] = lambda: captured.append(p1.saved(state).task)
    run_image(state)
    restore_task(state, captured[0])
    calls = len(state.http_calls)
    with state.sessions() as db:
        task = db.get(state.Task, state.task_id)
        history = history_for(state, task)
        if change == "cid":
            history["prompt"][1] = "another-job"
        elif change == "graph":
            history["prompt"][2]["unrelated"] = {"class_type": "SaveImage", "inputs": {}}
        else:
            history["outputs"] = {"other": next(iter(history["outputs"].values()))}
        assert asyncio.run(state.images.recover_benchmark_shot_image(db, task, history)) is False
        assert task.status == "failed"
    assert len(state.http_calls) == calls


def test_private_state_cas_rejects_duplicate_actors_and_preserves_sibling_metadata(isolated):
    state = isolated
    create_image(state)
    with state.sessions() as db:
        task = db.get(state.Task, state.task_id)
        first = state.execution.load_execution_shot(task)
        stale = state.execution.load_execution_shot(task)
        with state.sessions() as editor:
            saved = editor.get(state.Task, task.id)
            metadata = json.loads(saved.metadata_json)
            metadata["sibling"] = {"keep": True}
            saved.metadata_json = json.dumps(metadata)
            editor.commit()
        first.shot_image_prompt = "private first"
        state.execution.persist_execution_shot(db, task, first, status="running")
        assert json.loads(task.metadata_json)["sibling"] == {"keep": True}
        stale.image_url = "/must-not-publish.png"
        with pytest.raises(state.execution.ExecutionConflict, match="OWNERSHIP_CHANGED"):
            state.execution.persist_execution_shot(db, task, stale, status="completed")
        assert task.status == "running"


def test_keyframe_private_cas_conflict_cannot_write_shot_or_replace_newer_contract(isolated, monkeypatch):
    state = isolated
    p1.create(state, execution_purpose="benchmark")
    with state.sessions() as db:
        task = db.get(state.Task, state.task_id)
        contract = state.contracts.read_contract(task)
        state.contracts.store_contract(db, task.id, contract, statuses=("pending",), status="running")
        before = task.metadata_json
        update = Query.update

        def conflict(query, values, *args, **kwargs):
            if query.column_descriptions[0]["entity"] is state.Task:
                return 0
            return update(query, values, *args, **kwargs)

        monkeypatch.setattr(Query, "update", conflict)
        with pytest.raises(state.contracts.KeyframeReferenceError, match="TARGET_WRITE_CONFLICT"):
            state.contracts.patch_target(db, task.id, contract, prompt="private candidate")
        db.refresh(task)
        assert task.metadata_json == before
    assert not state.shot_writes


@pytest.mark.parametrize("kind", ["shot", "keyframe"])
def test_duplicate_recovery_completion_keeps_first_result_and_records_other_capture(isolated, kind):
    state = isolated
    before = shot_columns(state)
    if kind == "shot":
        create_image(state)
    else:
        p1.create(state, workflow_id="workflow", execution_purpose="benchmark")
    captured = []
    state.hooks["download"] = lambda: captured.append(p1.saved(state).task)
    first = run_image(state) if kind == "shot" else p1.run(state)
    assert first.task.status == "completed", first.task.error_message
    restore_task(state, captured[0])
    state.hooks["download"] = lambda: restore_task(state, first.task)
    hook = state.images.recover_benchmark_shot_image if kind == "shot" else state.service.recover_benchmark_image
    with state.sessions() as db:
        task = db.get(state.Task, state.task_id)
        asyncio.run(hook(db, task, history_for(state, task)))
    after = p1.saved(state)
    assert after.task.status == "completed" and after.task.result_url == first.task.result_url
    metadata = json.loads(after.task.metadata_json)
    observations = metadata.get("execution_observations", []) + metadata.get("keyframe_reference_observations", [])
    other_url = observations[-1]["artifact_url"]
    assert other_url != first.task.result_url and Path(state.to_path(other_url)).is_file()
    assert shot_columns(state) == before


def test_shot_composites_never_delete_existing_character_or_prop_files(isolated):
    state = isolated
    state.protect_shot = False
    with state.sessions() as db:
        shot = db.get(state.Shot, "shot")
        shot.props = '["sword", "shield"]'
        db.add(state.novels.Prop(novel_id="novel", name="shield", image_url=state.urls["prop"]))
        db.commit()
    state.protect_shot = True
    old_paths = [state.storage.get_merged_characters_path("novel", "chapter", 1, ["Ada", "Bea"]),
                 state.storage.get_merged_props_path("novel", "chapter", 1, ["sword", "shield"])]
    data = Path(state.to_path(state.urls["primary"])).read_bytes()
    for path in old_paths:
        path.write_bytes(data)
    before = shot_columns(state)
    create_image(state)
    result = run_image(state)
    assert result.task.status == "completed", result.task.error_message
    assert all(path.read_bytes() == data for path in old_paths)
    private = state.execution.execution_record(result.task)["working_shot"]
    assert "/benchmarks/" in private["merged_prop_image"]
    assert shot_columns(state) == before


@pytest.mark.parametrize("kind", ["shot", "keyframe"])
def test_same_second_attempts_have_distinct_archives_and_do_not_replay(isolated, monkeypatch, kind):
    state = isolated
    monkeypatch.setattr(state.storage_module, "datetime", SimpleNamespace(now=lambda: datetime(2026, 9, 8, 12, 0, 0)))
    urls, attempts = [], []
    for _ in range(2):
        if kind == "shot":
            create_image(state)
            result = run_image(state)
        else:
            p1.create(state, workflow_id="workflow", execution_purpose="benchmark")
            result = p1.run(state)
        assert result.task.status == "completed", result.task.error_message
        urls.append(result.task.result_url)
        attempts.append(state.execution.execution_record(result.task)["attempt_id"])
    assert urls[0] != urls[1] and attempts[0] != attempts[1]
    assert all(Path(state.to_path(url)).is_file() for url in urls)
    queues = len(state.queued)
    run_image(state) if kind == "shot" else p1.run(state)
    assert len(state.queued) == queues


@pytest.mark.parametrize("kind", ["shot", "keyframe"])
def test_private_attempt_ignores_later_production_edits_and_reordering(isolated, kind):
    state = isolated
    if kind == "shot":
        create_image(state)
    else:
        p1.create(state, workflow_id="workflow", execution_purpose="benchmark")
    state.protect_shot = False
    with state.sessions() as db:
        shot = db.get(state.Shot, "shot")
        shot.index, shot.description, shot.image_url = 37, "User changed the scene", state.urls["replacement"]
        frames = json.loads(shot.keyframes)
        frames[state.frame_index]["prompt_text"] = "New production draft"
        shot.keyframes = json.dumps(frames)
        db.commit()
    state.protect_shot = True
    before = shot_columns(state)
    result = run_image(state) if kind == "shot" else p1.run(state)
    assert result.task.status == "completed", result.task.error_message
    private = state.execution.execution_record(result.task)["working_shot"]
    assert private["index"] == 1 and private["description"] != before["description"]
    assert shot_columns(state) == before


def test_keyframe_first_insert_contains_purpose_snapshot_and_sealed_attempt(isolated):
    state = isolated
    inserted = []

    def check_insert(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO tasks"):
            values = dict(zip(context.compiled.positiontup, parameters))
            metadata = json.loads(values["metadata_json"])
            assert metadata["execution_purpose"] == "benchmark"
            assert metadata["execution"]["revision"] == 0
            assert metadata["keyframe_reference_contract"]["storage_revision"] == 0
            inserted.append(metadata)

    event.listen(state.engine, "before_cursor_execute", check_insert)
    try:
        p1.create(state, execution_purpose="benchmark")
    finally:
        event.remove(state.engine, "before_cursor_execute", check_insert)
    assert len(inserted) == 1 and not state.shot_writes


def test_keyframe_task_purpose_cannot_switch_to_production_at_publication(isolated):
    state = isolated
    p1.create(state, execution_purpose="benchmark")
    with state.sessions() as db:
        task = db.get(state.Task, state.task_id)
        contract = state.contracts.read_contract(task)
        metadata = json.loads(task.metadata_json)
        metadata["execution_purpose"] = "production"
        task.metadata_json = json.dumps(metadata)
        db.commit()
        with pytest.raises(state.contracts.KeyframeReferenceError, match="EXECUTION_PURPOSE_CHANGED"):
            state.contracts.patch_target(db, task.id, contract, prompt="must not publish")
        with pytest.raises(state.contracts.KeyframeReferenceError, match="EXECUTION_PURPOSE_CHANGED"):
            state.contracts.store_contract(db, task.id, contract, statuses=("pending",), status="running")
    assert not state.shot_writes


def test_keyframe_guards_prevent_incidental_shot_autoflush(isolated):
    state = isolated
    with state.sessions() as db:
        db.get(state.Shot, "shot").description = "Uncommitted production edit"
        success, _, message = asyncio.run(state.service.generate_keyframe_image(db, "shot", state.frame_index, execution_purpose="benchmark"))
        assert success is False and message == "PRODUCTION_SHOT_DIRTY"
    p1.create(state, execution_purpose="benchmark")
    with state.sessions() as db:
        task = db.get(state.Task, state.task_id)
        contract = state.contracts.read_contract(task)
        db.get(state.Shot, "shot").description = "Another uncommitted edit"
        with pytest.raises(state.contracts.KeyframeReferenceError, match="PRODUCTION_SHOT_DIRTY"):
            state.contracts.store_contract(db, task.id, contract, statuses=("pending",), status="running")
        with pytest.raises(state.contracts.KeyframeReferenceError, match="PRODUCTION_SHOT_DIRTY"):
            state.contracts.patch_target(db, task.id, contract, prompt="never published")
        state.service._finish_reference_error(db, task.id, contract, RuntimeError("failed"))
    assert not state.shot_writes


def test_shot_private_actor_rejects_prompt_id_change_during_download(isolated):
    state = isolated
    create_image(state)

    def replace_cid():
        with state.sessions() as db:
            task = db.get(state.Task, state.task_id)
            task.comfyui_prompt_id = "new-actor-job"
            db.commit()

    state.hooks["download"] = replace_cid
    result = run_image(state)
    assert result.task.status == "running" and result.task.comfyui_prompt_id == "new-actor-job"
    assert result.task.result_url is None
    assert json.loads(result.task.metadata_json)["execution_observations"][-1]["artifact_url"]


def test_keyframe_parent_cancellation_is_checked_in_private_publication_cas(isolated, monkeypatch):
    state = isolated
    with state.sessions() as db:
        parent = db.get(state.Task, "parent")
        parent.metadata_json = '{"execution_purpose":"benchmark"}'
        db.commit()
    p1.create(state, execution_purpose="benchmark", parent_task_id="parent")
    with state.sessions() as db:
        task = db.get(state.Task, state.task_id)
        contract = state.contracts.read_contract(task)
        state.contracts.store_contract(db, task.id, contract, statuses=("pending",), status="running")
        update, cancelled = Query.update, []

        def race(query, values, *args, **kwargs):
            if query.column_descriptions[0]["entity"] is state.Task and not cancelled:
                with state.sessions() as editor:
                    editor.get(state.Task, "parent").status = "cancelled"
                    editor.commit()
                cancelled.append(True)
            return update(query, values, *args, **kwargs)

        monkeypatch.setattr(Query, "update", race)
        with pytest.raises(state.contracts.KeyframeReferenceError, match="PARENT_NOT_ACTIVE"):
            state.contracts.patch_target(db, task.id, contract, prompt="uncommitted candidate")
        db.refresh(task)
        assert task.prompt_text is None
    assert not state.shot_writes


def test_storage_opt_in_destination_is_exclusive_scoped_and_default_unchanged(isolated, monkeypatch):
    state = isolated
    url = p1.ENDPOINT + "/view?filename=result.png"
    fixed = SimpleNamespace(now=lambda: datetime(2026, 9, 8, 12, 0, 0))
    monkeypatch.setattr(state.storage_module, "datetime", fixed)
    for method, options, suffix in (
        (state.storage.download_image, {"novel_id": "novel", "character_name": "shot_test", "image_type": "shot", "chapter_id": "chapter"}, ".png"),
        (state.storage.download_video, {"novel_id": "novel", "chapter_id": "chapter", "shot_number": 1}, ".mp4"),
    ):
        destination = state.root / "private" / ("capture" + suffix)
        first = asyncio.run(method(url, **options, destination=destination))
        assert first == str(destination)
        data = destination.read_bytes()
        assert asyncio.run(method(url, **options, destination=destination)) is None
        assert destination.read_bytes() == data
        assert asyncio.run(method(url, **options, destination=state.root.parent / ("outside" + suffix))) is None
        legacy = asyncio.run(method(url, **options))
        assert legacy.endswith("_20260908_120000" + suffix) and Path(legacy).relative_to(state.root).parts[0] == "story_novel"


def test_default_keyframe_production_behavior_still_claims_and_publishes(isolated):
    state = isolated
    state.protect_shot = False
    p1.create(state, workflow_id="workflow")
    result = p1.run(state)
    assert result.task.status == "completed", result.task.error_message
    assert result.contract["result"]["attachment"] == "attached"
    assert result.frames[state.frame_index]["image_url"] == result.task.result_url
    assert result.plan["keyframes"][state.target_kf - 1]["image_url"] == result.task.result_url
    assert state.shot_writes


def test_default_shot_result_publication_is_unchanged(isolated):
    state = isolated
    state.protect_shot = False
    create_image(state, purpose="production")
    with state.sessions() as db:
        task = db.get(state.Task, state.task_id)
        repo = sys.modules["app.repositories.shot_repository"].ShotRepository(db)
        asyncio.run(state.images._save_generated_image(
            {"image_url": p1.ENDPOINT + "/view?filename=result.png"}, task, None,
            "novel", "chapter", 1, db, task.id, "shot", repo,
        ))
    result = p1.saved(state)
    assert result.task.status == "completed" and result.shot.image_url == result.task.result_url
    assert result.shot.image_task_id == result.task.id and state.shot_writes


def test_production_keyframe_does_not_implicitly_consume_benchmark_producer(isolated):
    state = isolated
    state.protect_shot = False
    p1.configure(state, previous=state.urls["previous"])
    with state.sessions() as db:
        db.get(state.Task, state.previous_producer_id).metadata_json = '{"execution_purpose":"benchmark"}'
        db.commit()
    p1.create(state, workflow_id="workflow")
    result = p1.run(state)
    assert result.task.status == "failed" and "BENCHMARK_REFERENCE_REQUIRES_ADOPTION" in result.task.error_message
    assert not state.queued


def test_artifact_directory_rejects_escape_before_creating_attempt_directory(isolated):
    state = isolated
    create_image(state)
    story = state.root / "story_novel"
    story.symlink_to(state.root.parent, target_is_directory=True)
    with state.sessions() as db:
        task = db.get(state.Task, state.task_id)
        with pytest.raises(state.execution.ExecutionConflict, match="INVALID_TASK_ARTIFACT_DIRECTORY"):
            state.execution.artifact_directory(task)


@pytest.mark.parametrize("value", ["[]", "false", "{broken", '{"execution_purpose":"unknown"}', '{"execution":{}}'])
def test_malformed_purpose_cannot_fall_back_to_production(isolated, value):
    with pytest.raises(isolated.execution.ExecutionConflict):
        isolated.execution.execution_purpose(SimpleNamespace(metadata_json=value))
