"""Isolated #09 recovery/API tests: Python 3.11, --noconftest, no production I/O."""

import ast
import asyncio
import builtins
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timedelta
import importlib.util
import io
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock
import zlib

import httpx
from PIL import Image
import pytest
from sqlalchemy import Column, String, create_engine
from sqlalchemy.orm import Query, Session, declarative_base, relationship

import test_keyframe_reference_worker as worker_tests
from test_keyframe_reference_worker import worker as p1_worker


BACKEND = Path(__file__).resolve().parents[1]
KEY = "keyframe_reference_contract"
OBSERVATIONS = "keyframe_reference_observations"
ENDPOINT = "http://frozen-comfy.test:8188"
CURRENT_ENDPOINT = "http://current-comfy.test:8188"
PROMPT_ID = "20ec1452-f26b-4a86-a126-8e97fef2c340"
LOCAL_PATH = "/virtual/result.png"
LOCAL_URL = "/api/files/result.png"
PROMPT = "Use Picture 1 as the primary storyboard image. Change the light. "


@pytest.fixture
def recovery(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Application startup, real media, database, and network I/O are forbidden")

    for name in ("connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, name, forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    original_connect = sqlite3.connect

    def memory_only(database, *args, **kwargs):
        assert database == ":memory:"
        return original_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", memory_only)
    monkeypatch.setattr(sqlite3.dbapi2, "connect", memory_only)
    for owner in (builtins, io):
        original_open = owner.open

        def read_only(file, mode="r", *args, _open=original_open, **kwargs):
            if any(flag in mode for flag in "wax+"):
                forbidden()
            return _open(file, mode, *args, **kwargs)

        monkeypatch.setattr(owner, "open", read_only)

    def stub(name, **attributes):
        module = ModuleType(name)
        module.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, module)
        return module

    def load(name, relative):
        spec = importlib.util.spec_from_file_location(name, BACKEND / relative)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        return module

    for name in ("app", "app.api", "app.core", "app.models", "app.repositories",
                 "app.services", "app.services.comfyui", "app.utils"):
        stub(name, __path__=[])
    base = declarative_base()
    stub("app.core.database", Base=base, SessionLocal=forbidden, get_db=forbidden)

    class Novel(base):
        __tablename__ = "novels"
        id = Column(String, primary_key=True)

    class Chapter(base):
        __tablename__ = "chapters"
        id = Column(String, primary_key=True)
        shots = relationship("Shot", back_populates="chapter")

    stub("app.models.novel", Novel=Novel, Chapter=Chapter)
    Task = load("app.models.task", "app/models/task.py").Task
    Shot = load("app.models.shot", "app/models/shot.py").Shot
    Workflow = load("app.models.workflow", "app/models/workflow.py").Workflow
    stub("app.models.llm_log", LLMLog=type("LLMLog", (), {}))
    engine = create_engine("sqlite:///:memory:")
    base.metadata.create_all(engine)
    db = Session(engine)
    gate = load("app.services.keyframe_reference_contract", "app/services/keyframe_reference_contract.py")
    graph_gate = load("app.services.keyframe_reference_graph", "app/services/keyframe_reference_graph.py")
    load("app.services.task_execution", "app/services/task_execution.py")
    load("app.services.shot_video_execution", "app/services/shot_video_execution.py")
    task_repo = load("app.repositories.task", "app/repositories/task.py").TaskRepository
    load("app.repositories.shot_repository", "app/repositories/shot_repository.py")
    stub("app.repositories", TaskRepository=task_repo, WorkflowRepository=forbidden)
    character = SimpleNamespace(id="character", name="Ada", appearance="blue coat", description="Waiting")
    for name, symbol in (("character_repository", "CharacterRepository"), ("scene_repository", "SceneRepository"),
                         ("prop_repository", "PropRepository")):
        stub("app.repositories." + name, **{symbol: lambda db: SimpleNamespace(get_by_id=lambda value: character)})
    stub("app.repositories.prompt_template", PromptTemplateRepository=forbidden)
    settings = SimpleNamespace(COMFYUI_HOST=CURRENT_ENDPOINT, COMFYUI_TIMEOUT=900, LLM_TIMEOUT=300)
    stub("app.core.config", get_settings=lambda: settings)
    stub("app.utils.time_utils", format_datetime=lambda value: value.isoformat() if value else None)
    def to_local(url):
        assert url == LOCAL_URL, "Recovery must not re-read or resolve current reference images"
        return LOCAL_PATH

    stub("app.utils.path_utils", local_path_to_url=lambda value: LOCAL_URL if str(value) == LOCAL_PATH else None,
         url_to_local_path=to_local)
    stub("app.services.video_director_plan_service", VideoDirectorPlanService=forbidden)
    stub("app.services.prompt_builder", build_character_prompt=forbidden, build_scene_prompt=forbidden, get_style=forbidden)
    stub("app.models.prompt_template", PromptTemplate=type("PromptTemplate", (), {}))
    stub("app.services.llm_service", LLMService=forbidden)
    stub("app.services.background_workers", worker_manager=SimpleNamespace(worker=forbidden))
    client_module = load("app.services.comfyui.client", "app/services/comfyui/client.py")
    state = SimpleNamespace(db=db, engine=engine, gate=gate, graph_gate=graph_gate, Task=Task, Shot=Shot, Workflow=Workflow,
                            downloads=[], requests=[], polls=[], download_hook=None, poll_hook=None,
                            queue=[], remote_state="completed", settings=settings)

    image_bytes = io.BytesIO()
    Image.new("RGB", (4, 4), "blue").save(image_bytes, format="PNG")
    state.image = image_bytes.getvalue()
    template_graph = json.loads((BACKEND / "workflows/keyframe_flux2_klein.json").read_text())
    mapping = {"prompt_node_id": "110", "save_image_node_id": "9", "reference_image_node_id": "76"}
    graph = graph_gate.prepare_keyframe_graph(template_graph, mapping, has_reference=True)
    graph["110"]["inputs"]["text"] = PROMPT
    graph["76"]["inputs"]["image"] = "frozen-reference.png"
    graph["preview"] = {"class_type": "PreviewImage", "inputs": {"images": ["76", 0]}}
    inspection = graph_gate.validate_keyframe_graph(
        graph, mapping, reference_count=1, expected_filename="frozen-reference.png", expected_prompt=PROMPT,
    )
    state.graph = graph
    state.history = {"prompt": [7, PROMPT_ID, deepcopy(graph), {}, ["9"]],
                     "status": {"status_str": "success", "completed": True},
                     "outputs": {"preview": {"images": [{"filename": "preview.png", "type": "output"}]},
                                 "9": {"images": [{"filename": "final.png", "subfolder": "frozen run", "type": "output"}]}}}
    frames = [{"frame_index": index, "plan_keyframe_index": index + 1, "role": role,
               "time_seconds": index * 4, "description": f"State {index}", "prompt_text": PROMPT,
               "reference_mode": "auto_select", "image_url": f"/old-{index}.png", "image_task_id": "previous"}
              for index, role in enumerate(("START", "END"))]
    plan = {"keyframes": [{**frame, "index": frame["plan_keyframe_index"]} for frame in frames],
            "window_plans": [{"window_index": 1, "video_url": "/old.mp4", "status": "SUCCEEDED"}],
            "user_note": "Preserve this note"}
    state.shot = Shot(id="shot", chapter_id="chapter", index=1, description="A quiet street",
                      keyframes=json.dumps(frames), video_director_plan=json.dumps(plan),
                      video_url="/old.mp4", image_url="/primary.png")
    old = datetime.utcnow() - timedelta(seconds=2000)
    state.parent = Task(id="parent", type="shot_image_batch", status="running", name="Parent")
    state.task = Task(id="task", type="keyframe_image", status="pending", name="Not an index or identity",
                      shot_id="shot", chapter_id="chapter", novel_id="novel", parent_task_id="parent",
                      workflow_id="workflow", result_url="/previous-task.png", reference_images="[]",
                      created_at=old, started_at=old, updated_at=old)
    state.workflow = Workflow(id="workflow", name="Changed current workflow", type="keyframe_image",
                              node_mapping=json.dumps({"save_image_node_id": "preview"}), workflow_json="{}")
    db.add_all([Chapter(id="chapter"), state.shot, state.parent, state.task, state.workflow])
    db.flush()
    target = gate.snapshot_target(state.shot, 1)
    contract = {"version": 1, "attempt_id": "frozen-attempt", "phase": "planned", "target": target,
                "draft": deepcopy(target["draft"]),
                "planned": {"novel_id": "novel", "parent_task_id": "parent", "requested_workflow_id": "workflow",
                            "skip_llm_when_prompt_exists": True, "intent": target["reference_intent"]},
                "binding_resolved": False, "resolved": None, "binding": None,
                "prompt": {"llm_invoked": False}, "submit": {"state": "not_submitted"}}
    gate.seal_contract(contract)
    state.task.metadata_json = json.dumps({"unrelated": {"keep": True}, KEY: contract})
    gate.patch_target(db, state.task.id, contract, claiming=True)
    gate.store_contract(db, state.task.id, contract, statuses=("pending",), status="running", updated_at=old)
    template = (BACKEND / "prompt_templates/09_NovelFlow_QwenEdit2511_KeyframeImagePrompt_V1.txt").read_text()
    contract.update({
        "phase": "submitting", "endpoint": ENDPOINT,
        "context": {"shot": {"id": state.shot.id, "index": state.shot.index, **target["shot_state"]},
                    "current_keyframe": {**target["current_state"], "frame_index": target["frame_index"]},
                    "previous_keyframe_state_text": target["previous_state_text"], "visual_style": "ink", "aspect_ratio": "16:9"},
        "llm_config": {"provider": "fixture", "model": "fixture", "temperature": 0.3, "max_tokens": 2500},
        "template": {"id": "template", "name": "Frozen #09", "type": "keyframe_image_prompt", "text": template, "hash": gate.digest(template)},
        "workflow": {"id": "workflow", "name": "Frozen workflow", "type": "keyframe_image", "node_mapping": mapping,
                     "output_node_id": inspection["save_image_node_id"], "family": inspection["family"],
                     "contract_hash": graph_gate.stable_graph_fingerprint(graph, mapping), "template_graph_hash": gate.digest(template_graph)},
        "prepared_workflow": deepcopy(graph), "validation": {"passed": True, "graph": inspection},
        "binding_resolved": True,
        "resolved": {"url": "/primary.png", "label": "Primary storyboard", "source_kind": "PRIMARY_STORYBOARD",
                     "source_keyframe_index": None, "sha256": gate.digest(state.image), "size": len(state.image)},
        "binding": {"picture_index": 1, "node_id": inspection["reference_node_id"], "field": "image", "output_slot": 0,
                    "uploaded_filename": "frozen-reference.png", "payload_sha256": gate.digest(state.image), "payload_size": len(state.image)},
        "prompt": {"text": PROMPT, "text_hash": gate.digest(PROMPT), "llm_invoked": False,
                   "validation": gate.validate_reference_prompt(PROMPT, "PRIMARY_STORYBOARD")},
        "submit": {"state": "attempted", "graph_hash": gate.digest(graph)},
    })
    contract["manifest"] = gate.reference_manifest(contract)
    contract["frozen_binding_hash"] = gate.digest({key: contract[key] for key in ("resolved", "binding", "manifest")})
    contract["prompt"]["cache_fingerprint"] = gate.reference_cache_fingerprint(contract)
    gate.store_contract(db, state.task.id, contract, prompt_text=PROMPT, workflow_name="Frozen workflow",
                        reference_images=json.dumps(gate.reference_images(contract)), updated_at=old)
    contract["submit"].update(state="submitted", prompt_id=PROMPT_ID)
    contract["phase"] = "submitted"
    gate.store_contract(db, state.task.id, contract, comfyui_prompt_id=PROMPT_ID, workflow_json=json.dumps(graph), updated_at=old)
    assert gate.validate_frozen_contract(contract, state.task, require_submitted=True) == inspection
    assert contract["workflow"]["id"] == state.task.workflow_id
    assert contract["submit"]["prompt_id"] == state.task.comfyui_prompt_id

    async def get(url, **kwargs):
        state.requests.append(url)
        if state.poll_hook:
            hook, state.poll_hook = state.poll_hook, None
            hook()
        if url.startswith(CURRENT_ENDPOINT):
            return httpx.Response(200, json={"queue_running": state.queue, "queue_pending": []} if url.endswith("/queue") else {})
        assert url.startswith(ENDPOINT)
        if url.endswith("/queue"):
            queue = [[7, PROMPT_ID]] if state.remote_state == "queued" else []
            return httpx.Response(200, json={"queue_running": queue, "queue_pending": []})
        assert url == ENDPOINT + "/history/" + PROMPT_ID
        history = deepcopy(state.history)
        if state.remote_state == "error":
            history["status"] = {"status_str": "error", "completed": False,
                                 "messages": [["execution_error", "Fixture ComfyUI failure"]]}
        elif state.remote_state == "history":
            history["status"] = {"status_str": "running", "completed": False}
        return httpx.Response(503 if state.remote_state == "unknown" else 200,
                              json={} if state.remote_state == "missing" else {PROMPT_ID: history})

    @asynccontextmanager
    async def transport(client):
        yield SimpleNamespace(get=get)

    monkeypatch.setattr(client_module.ComfyUIClient, "_client", transport)
    real_poll = client_module.ComfyUIClient.get_prompt_state

    async def poll(client, *args, **kwargs):
        state.polls.append((client.base_url, args, kwargs))
        return await real_poll(client, *args, **kwargs)

    monkeypatch.setattr(client_module.ComfyUIClient, "get_prompt_state", poll)
    shared = client_module.ComfyUIClient()
    state.comfy = SimpleNamespace(client=shared, get_queue_info=AsyncMock(side_effect=shared.get_queue_info))
    stub("app.services.comfyui", ComfyUIService=lambda: state.comfy)
    class OutputPath:
        def __init__(self, value):
            assert str(value) == LOCAL_PATH

        def __str__(self):
            return LOCAL_PATH

        def is_file(self):
            return True

        def read_bytes(self):
            return state.image

    async def download(**kwargs):
        state.downloads.append(kwargs)
        if state.download_hook:
            hook, state.download_hook = state.download_hook, None
            hook()
        return LOCAL_PATH

    state.storage = SimpleNamespace(download_image=AsyncMock(side_effect=download))
    stub("app.services.file_storage", file_storage=state.storage)
    worker_module = load("app.services.shot_keyframe_service", "app/services/shot_keyframe_service.py")
    monkeypatch.setattr(worker_module, "Path", OutputPath)
    monkeypatch.setattr(worker_module.ShotKeyframeService, "__init__", forbidden)
    state.output_reader = worker_module.ShotKeyframeService._read_reference_payload
    state.read_output = Mock(wraps=state.output_reader)
    monkeypatch.setattr(worker_module.ShotKeyframeService, "_read_reference_payload", staticmethod(state.read_output))
    state.module = load("app.services.task_service", "app/services/task_service.py")
    state.service = state.module.TaskService(db)
    stub("app.api.deps", get_task_repo=forbidden)
    state.api = load("app.api.tasks", "app/api/tasks.py")
    state.repo = task_repo(db)
    state.enqueue = Mock()
    stub("app.services.character_service", enqueue_character_portrait_task=state.enqueue)
    try:
        yield state
    finally:
        db.close()
        engine.dispose()


def recover(state, history=True):
    return asyncio.run(state.service._recover_completed_keyframe_prompt(
        state.task, state.history if history is True else history, state.db,
    ))


def saved_contract(state):
    state.db.refresh(state.task)
    return state.gate.read_contract(state.task)


def save_contract(state, contract):
    metadata = json.loads(state.task.metadata_json)
    metadata[KEY] = contract
    state.task.metadata_json = json.dumps(metadata)
    state.db.commit()


def change_task(state, **fields):
    with Session(state.engine) as other:
        other.query(state.Task).filter(state.Task.id == state.task.id).update(fields)
        other.commit()


def edit_target(state, representation, field, value):
    with Session(state.engine) as other:
        shot = other.get(state.Shot, "shot")
        value_json = json.loads(getattr(shot, representation))
        (value_json if representation == "keyframes" else value_json["keyframes"])[1][field] = value
        setattr(shot, representation, json.dumps(value_json))
        if representation == "video_director_plan":
            shot.video_director_plan_revision += 1
        other.commit()


def media(state):
    state.db.refresh(state.shot)
    return {key: getattr(state.shot, key) for key in (
        "keyframes", "video_director_plan", "video_director_plan_revision", "image_url", "video_url",
    )}


def task_evidence(state):
    state.db.refresh(state.task)
    return {column.name: getattr(state.task, column.name) for column in state.Task.__table__.columns}


def test_recovery_uses_frozen_map_endpoint_and_exact_save_image(recovery):
    state = recovery
    before = saved_contract(state)
    assert recover(state) is True
    assert state.task.status == "completed" and state.task.progress == 100 and state.task.result_url == LOCAL_URL
    assert state.task.completed_at and state.task.error_message is None
    result = saved_contract(state)
    assert result["result"] == {"url": LOCAL_URL, "attachment": "attached"}
    assert result["prepared_workflow"] == before["prepared_workflow"]
    assert result["prompt"] == before["prompt"]
    assert json.loads(state.task.metadata_json)["unrelated"] == {"keep": True}
    assert json.loads(state.shot.keyframes)[1]["image_url"] == LOCAL_URL
    plan = json.loads(state.shot.video_director_plan)
    assert plan["keyframes"][1]["image_url"] == LOCAL_URL
    assert plan["window_plans"][0]["video_url"] == "/old.mp4" and plan["user_note"] == "Preserve this note"
    request = state.downloads[0]
    assert request == {"url": ENDPOINT + "/view?filename=final.png&subfolder=frozen+run&type=output",
                       "novel_id": "novel", "chapter_id": "chapter", "character_name": "keyframe_1", "image_type": "keyframe"}
    assert not state.requests and not state.polls
    assert state.comfy.client.base_url == CURRENT_ENDPOINT
    state.read_output.assert_called_with(LOCAL_URL)


def test_graph_comparison_parses_ack_json_and_ignores_key_order_not_content(recovery):
    state = recovery
    state.task.workflow_json = json.dumps(dict(reversed(list(state.graph.items()))), indent=4)
    state.history["prompt"][2] = json.loads(state.task.workflow_json)
    state.db.commit()
    assert recover(state) is True


def test_full_frozen_proof_is_checked_before_and_after_download(recovery, monkeypatch):
    state = recovery
    validate = state.module.validate_frozen_contract
    calls = []

    def check(contract, task, **options):
        calls.append((deepcopy(contract), task.comfyui_prompt_id, task.prompt_text, task.reference_images, options))
        return validate(contract, task, **options)

    monkeypatch.setattr(state.module, "validate_frozen_contract", check)
    before = saved_contract(state)
    assert recover(state) is True
    assert len(calls) == 2
    for contract, prompt_id, prompt, references, options in calls:
        assert contract == before and options == {"require_submitted": True}
        assert prompt_id == PROMPT_ID and prompt == PROMPT
        assert json.loads(references) == state.gate.reference_images(before)


@pytest.mark.parametrize("field", [
    "storage_revision", "storage_hash", "binding_resolved", "resolved", "binding", "manifest", "frozen_binding_hash",
    "template", "context", "llm_config", "prompt.text", "prompt.text_hash", "prompt.cache_fingerprint",
    "prepared_workflow", "workflow.node_mapping", "validation.graph", "submit.graph_hash",
])
def test_missing_proof_fields_never_attach_or_fall_through_to_legacy_api(recovery, field):
    state = recovery
    contract = saved_contract(state)
    section, _, key = field.partition(".")
    (contract[section] if key else contract).pop(key or section)
    save_contract(state, contract)  # Deliberate tampering: retain the old seal.
    before, evidence = media(state), task_evidence(state)
    assert recover(state) is False
    assert media(state) == before and not state.downloads and not state.requests
    assert saved_contract(state) == contract
    after = task_evidence(state)
    assert {key: value for key, value in after.items() if key not in {"metadata_json", "updated_at"}} == {
        key: value for key, value in evidence.items() if key not in {"metadata_json", "updated_at"}
    }
    assert after["updated_at"] >= evidence["updated_at"]
    assert json.loads(state.task.metadata_json)[OBSERVATIONS][-1]["code"] == "CONTRACT_SEAL_INVALID"
    data = asyncio.run(state.api.get_task_workflow(state.task.id, state.repo))["data"]
    assert data["workflowSource"] == "unverified" and data["sourceProof"]["verified"] is False
    assert data["diagnostic"]["metadataJson"] == state.task.metadata_json


@pytest.mark.parametrize("change,code", [
    ("context", "CONTRACT_PROOF_INVALID"), ("llm_config", "CONTRACT_PROOF_INVALID"),
    ("template", "CONTRACT_PROOF_INVALID"), ("binding-hash", "FROZEN_BINDING_CHANGED"),
    ("manifest", "FROZEN_BINDING_CHANGED"), ("workflow-hash", "WORKFLOW_PROOF_INVALID"),
    ("cache", "CACHE_PROOF_INVALID"), ("prompt-stamp", "PROMPT_PROOF_INVALID"),
    ("graph-stamp", "GRAPH_PROOF_INVALID"), ("positive-route", "GRAPH_PROOF_INVALID"),
])
def test_sealed_staged_proof_is_recomputed_not_replaced_by_passed_flags(recovery, change, code):
    state = recovery
    contract = saved_contract(state)
    original_revision = contract["storage_revision"]
    fields = {}
    if change in {"context", "llm_config"}:
        contract.pop(change)
    elif change == "template":
        contract["template"].pop("text")
    elif change == "binding-hash":
        contract["frozen_binding_hash"] = "0" * 64
    elif change == "manifest":
        contract["manifest"][0]["picture_index"] = 2
    elif change == "workflow-hash":
        contract["workflow"]["contract_hash"] = "0" * 64
    elif change == "cache":
        contract["prompt"]["cache_fingerprint"] = "0" * 64
    elif change == "prompt-stamp":
        contract["prompt"]["validation"] = {"passed": True}
    elif change == "graph-stamp":
        contract["validation"]["graph"] = {"passed": True}
    else:
        graph = contract["prepared_workflow"]
        graph["108"]["inputs"]["positive"] = ["111", 0]
        contract["submit"]["graph_hash"] = state.gate.digest(graph)
        fields["workflow_json"] = json.dumps(graph)
    # Storage supports staged evidence; its CAS seal is not a graph/binding proof.
    # Use the real write helper, never manually reseal a staged production write.
    state.gate.store_contract(state.db, state.task.id, contract, **fields)
    assert contract["storage_revision"] == original_revision + 1 and contract["validation"]["passed"] is True
    before = media(state)
    assert recover(state) is False
    assert state.task.status == "failed" and code in state.task.error_message
    assert media(state) == before and not state.downloads and not state.requests
    saved = saved_contract(state)
    assert saved["validation"] == contract["validation"] and saved["failure"]["code"] == code
    assert OBSERVATIONS not in json.loads(state.task.metadata_json)
    data = asyncio.run(state.api.get_task_workflow(state.task.id, state.repo))["data"]
    assert data["workflowSource"] == "unverified" and data["sourceProof"]["code"] == code


@pytest.mark.parametrize("completed", [False, True], ids=["running", "completed"])
@pytest.mark.parametrize("field,value", [
    ("prompt_text", "Other actor's prompt"), ("prompt_text", None),
    ("reference_images", '[{"label":"Other reference","url":"/other.png"}]'),
    ("reference_images", None), ("reference_images", "not-json"),
    ("workflow_id", "other-workflow"), ("workflow_name", "Other workflow"),
    ("comfyui_prompt_id", "other-prompt"), ("workflow_json", "{}"), ("workflow_json", None),
])
def test_task_projection_changes_are_observations_not_repairs_or_idempotent_success(recovery, completed, field, value):
    state = recovery
    if completed:
        assert recover(state) is True
    contract = saved_contract(state)
    change_task(state, **{field: value})
    before, evidence, downloads = media(state), task_evidence(state), len(state.downloads)
    assert recover(state) is False
    assert media(state) == before and len(state.downloads) == downloads
    assert saved_contract(state) == contract
    after = task_evidence(state)
    assert {key: value for key, value in after.items() if key not in {"metadata_json", "updated_at"}} == {
        key: value for key, value in evidence.items() if key not in {"metadata_json", "updated_at"}
    }
    assert after["updated_at"] >= evidence["updated_at"]
    data = asyncio.run(state.api.get_task_workflow(state.task.id, state.repo))["data"]
    assert data["workflowSource"] == "unverified" and data["sourceProof"]["verified"] is False
    assert data["metadata"][OBSERVATIONS] == json.loads(state.task.metadata_json)[OBSERVATIONS]
    assert data["diagnostic"]["workflowJson"] == evidence["workflow_json"]


@pytest.mark.parametrize("change,code", [
    ("prompt-id", "HISTORY_SUBMISSION_MISMATCH"), ("graph", "HISTORY_SUBMISSION_MISMATCH"),
    ("not-completed", "RESULT_NOT_COMPLETED"), ("history-error", "RESULT_NOT_COMPLETED"),
    ("preview-only", "RESULT_NODE_UNCERTAIN"), ("empty-output", "RESULT_NODE_UNCERTAIN"),
    ("two-images", "RESULT_NODE_UNCERTAIN"), ("temp", "INVALID_OUTPUT_LOCATOR"),
    ("path", "INVALID_OUTPUT_LOCATOR"), ("subfolder", "INVALID_OUTPUT_LOCATOR"),
    ("preview-mapping", "CONTRACT_SEAL_INVALID"), ("mapping-mismatch", "CONTRACT_SEAL_INVALID"),
    ("prepared-graph", "CONTRACT_SEAL_INVALID"), ("ack-graph", "TASK_PROJECTION_CHANGED"),
    ("unconfirmed", "CONTRACT_SEAL_INVALID"), ("comfy-id", "TASK_SUBMISSION_CHANGED"),
])
def test_unverifiable_history_or_contract_never_downloads_or_attaches(recovery, change, code):
    state = recovery
    contract = saved_contract(state)
    image = state.history["outputs"]["9"]["images"][0]
    if change == "prompt-id":
        state.history["prompt"][1] = "different-prompt"
    elif change == "graph":
        state.history["prompt"][2]["110"]["inputs"]["text"] += " changed"
    elif change in {"not-completed", "history-error"}:
        state.history["status"] = {"completed": False, "status_str": "error" if change == "history-error" else "running"}
    elif change == "preview-only":
        del state.history["outputs"]["9"]
    elif change == "empty-output":
        state.history["outputs"]["9"]["images"] = []
    elif change == "two-images":
        state.history["outputs"]["9"]["images"].append(deepcopy(image))
    elif change == "temp":
        image["type"] = "temp"
    elif change == "path":
        image["filename"] = "../escape.png"
    elif change == "subfolder":
        image["subfolder"] = "../escape"
    elif change == "preview-mapping":
        contract["workflow"].update(output_node_id="preview", node_mapping={"save_image_node_id": "preview"})
    elif change == "mapping-mismatch":
        contract["workflow"]["node_mapping"]["save_image_node_id"] = "preview"
    elif change == "prepared-graph":
        contract["prepared_workflow"]["110"]["inputs"]["text"] += " changed"
    elif change == "ack-graph":
        state.task.workflow_json = "{}"
    elif change == "unconfirmed":
        contract["submit"]["state"] = "unknown"
    else:
        state.task.comfyui_prompt_id = "different-prompt"
    save_contract(state, contract)
    before, evidence = media(state), task_evidence(state)
    assert recover(state) is False
    assert media(state) == before and not state.downloads
    if change in {"preview-mapping", "mapping-mismatch", "prepared-graph", "ack-graph", "unconfirmed", "comfy-id"}:
        assert state.task.status == evidence["status"] and state.task.error_message == evidence["error_message"]
        assert saved_contract(state) == contract
        assert json.loads(state.task.metadata_json)[OBSERVATIONS][-1]["code"] == code
    else:
        assert state.task.status == "failed" and code in state.task.error_message
        assert saved_contract(state)["failure"]["code"] == code
    for key in ("workflow_json", "prompt_text", "reference_images", "result_url", "comfyui_prompt_id"):
        assert getattr(state.task, key) == evidence[key]


@pytest.mark.parametrize("during", [False, True], ids=["before-download", "during-download"])
@pytest.mark.parametrize("representation,field,value,code", [
    ("keyframes", "description", "User edit", "TARGET_CHANGED"),
    ("video_director_plan", "description", "User edit", "TARGET_CHANGED"),
    ("keyframes", "prompt_text", "User draft", "PROMPT_EDITED"),
    ("video_director_plan", "prompt_text", "User draft", "PROMPT_EDITED"),
    ("keyframes", "reference_image_url", "/new-reference.png", "TARGET_CHANGED"),
    ("keyframes", "image_url", "/new-upload.png", "TARGET_CHANGED"),
    ("video_director_plan", "image_url", "/new-upload.png", "TARGET_CHANGED"),
    ("keyframes", "image_task_id", "another-owner", "TARGET_OWNER_CHANGED"),
    ("video_director_plan", "image_task_id", "another-owner", "TARGET_OWNER_CHANGED"),
])
def test_target_edit_or_owner_change_is_never_overwritten(recovery, during, representation, field, value, code):
    state = recovery
    edited = []

    def edit():
        edit_target(state, representation, field, value)
        edited.append(media(state))

    if during:
        state.download_hook = edit
    else:
        edit()
    assert recover(state) is False
    assert media(state) == edited[0]
    contract = saved_contract(state)
    assert state.task.status == "failed" and contract["failure"]["code"] == code
    assert state.task.result_url == "/previous-task.png"
    assert json.loads(state.task.metadata_json)["unrelated"] == {"keep": True}
    item = state.service.format_task_list([state.task], {}, {}, {})[0]
    detail = state.service.format_task_detail(state.task)
    assert item["status"] == detail["status"] == "failed"
    assert item["resultUrl"] != LOCAL_URL
    if during:
        assert contract["result"]["attachment"] == "detached" and contract["result"]["url"] == LOCAL_URL
        assert contract["result"]["local_path"] == LOCAL_PATH
        assert len(state.downloads) == 1
        assert detail["metadata"][KEY]["result"]["attachment"] == "detached"
    else:
        assert not state.downloads and "result" not in contract


def test_target_reordered_during_download_is_detached_not_projected_completed(recovery):
    state = recovery
    edited = []

    def reorder():
        with Session(state.engine) as other:
            shot = other.get(state.Shot, "shot")
            shot.keyframes = json.dumps(list(reversed(json.loads(shot.keyframes))))
            plan = json.loads(shot.video_director_plan)
            plan["keyframes"].reverse()
            shot.video_director_plan = json.dumps(plan)
            shot.video_director_plan_revision += 1
            other.commit()
        edited.append(media(state))

    state.download_hook = reorder
    assert recover(state) is False
    assert media(state) == edited[0] and len(state.downloads) == 1
    item = state.service.format_task_list([state.task], {}, {}, {})[0]
    detail = state.service.format_task_detail(state.task)
    assert item["status"] == detail["status"] == "failed"
    assert item["resultUrl"] != LOCAL_URL
    assert detail["metadata"][KEY]["result"]["attachment"] == "detached"
    assert detail["metadata"][KEY]["result"]["url"] == LOCAL_URL


@pytest.mark.parametrize("during", [False, True])
@pytest.mark.parametrize("status", ["cancelled", "failed", "completed", "removed"])
def test_parent_must_stay_active_before_and_after_download(recovery, during, status):
    state = recovery

    def stop_parent():
        with Session(state.engine) as other:
            parent = other.get(state.Task, "parent")
            if status == "removed":
                other.delete(parent)
            else:
                parent.status = status
            other.commit()

    if during:
        state.download_hook = stop_parent
    else:
        stop_parent()
    before = media(state)
    assert recover(state) is False
    assert state.task.status == "failed" and "PARENT_NOT_ACTIVE" in state.task.error_message
    assert media(state) == before
    assert len(state.downloads) == int(during)
    if during:
        assert saved_contract(state)["result"]["attachment"] == "detached"


@pytest.mark.parametrize("during", [False, True])
@pytest.mark.parametrize("status", ["cancelled", "failed", "pending"])
def test_ineligible_task_states_are_not_revived(recovery, during, status):
    state = recovery
    finished = datetime(2026, 1, 1)

    def stop():
        change_task(state, status=status, error_message="Original terminal reason", completed_at=finished)

    if during:
        state.download_hook = stop
    else:
        stop()
    before = media(state)
    assert recover(state) is False
    expected = "failed" if during and status == "pending" else status
    assert media(state) == before and state.task.status == expected
    if expected == status:
        assert state.task.error_message == "Original terminal reason" and state.task.completed_at == finished
    else:
        assert "TASK_NOT_ACTIVE" in state.task.error_message
    assert len(state.downloads) == int(during)
    if during:
        assert saved_contract(state)["result"]["attachment"] == "detached"


def test_concurrent_worker_failure_keeps_terminal_evidence_and_downloaded_artifact(recovery):
    state = recovery
    failure = {"stage": "worker", "code": "WORKER_INTERRUPTED", "message": "Original reason"}

    def stop():
        contract = saved_contract(state)
        contract.update(phase="failed", failure=failure)
        state.gate.store_contract(state.db, "task", contract, terminal=True, status="failed", error_message="Original reason")

    state.download_hook = stop
    before = media(state)
    assert recover(state) is False
    assert state.task.status == "failed" and state.task.error_message == "Original reason"
    contract = saved_contract(state)
    assert contract["failure"] == failure
    assert "result" not in contract
    observation = json.loads(state.task.metadata_json)[OBSERVATIONS][-1]
    assert observation["artifact_url"] == LOCAL_URL and observation["code"] == "CONTRACT_STALE"
    assert media(state) == before


@pytest.mark.parametrize("during", [False, True])
def test_replaced_attempt_does_not_receive_old_recovery_evidence(recovery, during):
    state = recovery
    replacement = saved_contract(state)
    replacement["attempt_id"] = "new-attempt"
    state.gate.seal_contract(replacement, advance=True)
    metadata = json.dumps({"unrelated": "new evidence", KEY: replacement})

    def replace():
        change_task(state, metadata_json=metadata)

    if during:
        state.download_hook = replace
    else:
        replace()
    before = media(state)
    assert recover(state) is False
    assert state.task.status == "running" and saved_contract(state) == replacement
    observed = json.loads(state.task.metadata_json)
    assert observed["unrelated"] == "new evidence" and observed[OBSERVATIONS][-1]["attempt_id"] == "frozen-attempt"
    assert media(state) == before and len(state.downloads) == int(during)


def test_comfy_id_changed_during_download_cannot_publish(recovery):
    state = recovery
    state.download_hook = lambda: change_task(state, comfyui_prompt_id="replacement-prompt")
    before = media(state)
    assert recover(state) is False
    assert media(state) == before and state.task.comfyui_prompt_id == "replacement-prompt"
    assert state.task.status != "completed"


def test_completed_attached_recovery_is_idempotent_without_history_or_download(recovery):
    state = recovery
    assert recover(state) is True
    before, evidence = media(state), task_evidence(state)
    assert recover(state, None) is True
    assert len(state.downloads) == 1 and media(state) == before and task_evidence(state) == evidence


def test_completed_historical_attachment_never_republishes_a_later_user_replacement(recovery):
    state = recovery
    assert recover(state) is True
    edit_target(state, "keyframes", "image_url", "/later-user-image.png")
    edit_target(state, "video_director_plan", "image_url", "/later-user-image.png")
    before, evidence = media(state), task_evidence(state)
    assert recover(state, None) is True
    assert media(state) == before and task_evidence(state) == evidence and len(state.downloads) == 1


@pytest.mark.parametrize("checkpoint", ["download", "file-validated"])
@pytest.mark.parametrize("actor", ["cid", "prompt", "references", "metadata", "cid-and-metadata", "completed-winner"])
def test_old_copy_only_observes_newer_same_attempt_facts_after_download(recovery, checkpoint, actor):
    state = recovery
    expected = saved_contract(state)
    canonical = []

    def change():
        if actor == "completed-winner":
            state.gate.patch_target(state.db, state.task.id, saved_contract(state), image_url="/canonical-winner.png")
        elif actor == "metadata":
            newer = saved_contract(state)
            newer["worker_note"] = "Newer same-attempt evidence"
            state.gate.store_contract(state.db, state.task.id, newer, current_step="Other worker owns this attempt")
        elif actor == "cid-and-metadata":
            newer = saved_contract(state)
            newer["submit"]["prompt_id"] = "new-canonical-prompt"
            newer.update(phase="failed", failure={"stage": "other-worker", "code": "OTHER_ACTOR_WON"})
            # Construct the other actor's complete, self-consistent current record.
            # This fixture setup is not a resealing hook around production writes.
            state.gate.seal_contract(newer, advance=True)
            metadata = json.loads(state.task.metadata_json)
            metadata[KEY] = newer
            change_task(state, metadata_json=json.dumps(metadata), comfyui_prompt_id="new-canonical-prompt",
                        status="failed", error_message="Other worker failure", result_url="/canonical-winner.png")
            state.gate.validate_frozen_contract(saved_contract(state), state.task, require_submitted=True)
        else:
            field, value = {"cid": ("comfyui_prompt_id", "new-canonical-prompt"),
                            "prompt": ("prompt_text", "Another actor's prompt"),
                            "references": ("reference_images", '[{"label":"New reference","url":"/new.png"}]')}[actor]
            change_task(state, **{field: value})
        canonical.append((task_evidence(state), media(state)))

    if checkpoint == "download":
        state.download_hook = change
    else:
        def validate_then_change(url):
            result = state.output_reader(url)
            change()
            return result
        state.read_output.side_effect = validate_then_change
    assert recover(state) is (actor == "completed-winner")
    assert len(state.downloads) == 1 and len(canonical) == 1
    before, before_media = canonical[0]
    after = task_evidence(state)
    assert media(state) == before_media
    assert {key: value for key, value in after.items() if key not in {"metadata_json", "updated_at"}} == {
        key: value for key, value in before.items() if key not in {"metadata_json", "updated_at"}
    }
    assert after["updated_at"] >= before["updated_at"]
    metadata = json.loads(after["metadata_json"])
    assert {key: value for key, value in metadata.items() if key != OBSERVATIONS} == json.loads(before["metadata_json"])
    observation = metadata[OBSERVATIONS][-1]
    assert observation["artifact_url"] == LOCAL_URL and observation["attempt_id"] == expected["attempt_id"]
    assert observation["expected_storage_revision"] == expected["storage_revision"]
    assert observation["expected_prompt_id"] == PROMPT_ID
    assert after["result_url"] != LOCAL_URL


def test_concurrent_completion_wins_without_overwriting_or_detaching_it(recovery):
    state = recovery
    state.download_hook = lambda: state.gate.patch_target(state.db, state.task.id, saved_contract(state), image_url="/winner.png")
    assert recover(state) is True
    assert state.task.result_url == "/winner.png"
    assert saved_contract(state)["result"] == {"url": "/winner.png", "attachment": "attached"}
    assert json.loads(state.shot.keyframes)[1]["image_url"] == "/winner.png"
    assert json.loads(state.task.metadata_json)[OBSERVATIONS][-1]["artifact_url"] == LOCAL_URL


def test_atomic_publish_cas_rolls_back_both_representations_when_task_write_conflicts(recovery, monkeypatch):
    state = recovery
    original_update = Query.update
    conflicts = []

    def conflict(query, values, *args, **kwargs):
        if query.column_descriptions[0]["entity"] is state.Task and values.get("status") == "completed":
            conflicts.append(True)
            return 0
        return original_update(query, values, *args, **kwargs)

    monkeypatch.setattr(Query, "update", conflict)
    before = media(state)
    assert recover(state) is False
    assert len(conflicts) == 3 and media(state) == before
    assert saved_contract(state)["result"]["attachment"] == "detached"
    assert state.task.status == "failed" and "TARGET_WRITE_CONFLICT" in state.task.error_message


@pytest.mark.parametrize("change", ["parent-cancel", "prompt-replaced", "workflow-replaced"])
def test_parent_contract_must_recheck_identity_atomically_at_publish(recovery, monkeypatch, change):
    state = recovery
    original_update = Query.update
    changed = []

    def race(query, values, *args, **kwargs):
        if not changed and query.column_descriptions[0]["entity"] is state.Shot:
            changed.append(True)
            with Session(state.engine) as other:
                if change == "parent-cancel":
                    other.get(state.Task, "parent").status = "cancelled"
                elif change == "prompt-replaced":
                    other.get(state.Task, "task").comfyui_prompt_id = "replacement-prompt"
                else:
                    other.get(state.Task, "task").workflow_id = "replacement-workflow"
                other.commit()
        return original_update(query, values, *args, **kwargs)

    monkeypatch.setattr(Query, "update", race)
    before = media(state)
    assert recover(state) is False
    assert media(state) == before and state.task.status != "completed"
    assert changed == [True]
    if change == "parent-cancel":
        assert state.task.status == "failed" and saved_contract(state)["result"]["attachment"] == "detached"
    else:
        assert state.task.status == "running"
        assert json.loads(state.task.metadata_json)[OBSERVATIONS][-1]["artifact_url"] == LOCAL_URL


@pytest.mark.parametrize("kind", ["invalid", "invalid-pixels", "animated", "download-failure"])
def test_downloaded_output_must_be_one_valid_image(recovery, kind):
    state = recovery
    if kind == "invalid":
        state.image = b"not an image"
    elif kind == "invalid-pixels":
        start = state.image.index(b"IDAT")
        length = int.from_bytes(state.image[start - 4:start], "big")
        data = b"not a compressed pixel stream"
        chunk = b"IDAT" + data
        state.image = (state.image[:start - 4] + len(data).to_bytes(4, "big") + chunk
                       + zlib.crc32(chunk).to_bytes(4, "big") + state.image[start + length + 8:])
        with Image.open(io.BytesIO(state.image)) as image:
            image.verify()
    elif kind == "animated":
        payload = io.BytesIO()
        Image.new("RGB", (4, 4), "red").save(payload, format="GIF", save_all=True,
                                             append_images=[Image.new("RGB", (4, 4), "blue")])
        state.image = payload.getvalue()
    else:
        state.storage.download_image.side_effect = None
        state.storage.download_image.return_value = None
    before = media(state)
    assert recover(state) is False
    assert media(state) == before and state.task.status == "failed"
    contract = saved_contract(state)
    if kind != "download-failure":
        assert contract["result"]["attachment"] == "detached"
        state.read_output.assert_called_with(LOCAL_URL)
    else:
        assert "result" not in contract


@pytest.mark.parametrize("metadata", [None, "{malformed", json.dumps({"old": "keep"}),
                                      json.dumps({KEY: {"version": 2}, "old": "keep"})])
def test_legacy_recovery_fails_without_fabricating_contract_or_touching_old_media(recovery, metadata):
    state = recovery
    state.task.metadata_json = metadata
    state.db.commit()
    before = media(state)
    assert recover(state) is False
    assert state.task.status == "failed" and "LEGACY_CONTRACT_UNVERIFIED" in state.task.error_message
    assert state.task.metadata_json == metadata and state.task.result_url == "/previous-task.png"
    assert media(state) == before and not state.downloads and not state.requests


@pytest.mark.parametrize("status", ["failed", "completed"])
@pytest.mark.parametrize("legacy", [False, True])
def test_keyframe_retry_rejects_before_erasing_any_evidence(recovery, status, legacy):
    state = recovery
    state.task.status = status
    state.task.error_message = "Keep this failure"
    state.task.completed_at = datetime(2026, 1, 1)
    if legacy:
        state.task.metadata_json = '{"old":"evidence"}'
    state.db.commit()
    before, evidence = media(state), task_evidence(state)
    result = state.service.retry_task(state.task.id)
    assert result["success"] is False and result["status_code"] == 400
    assert media(state) == before and task_evidence(state) == evidence
    state.enqueue.assert_not_called()


def test_other_task_retry_keeps_original_reset_and_enqueue_behavior(recovery):
    state = recovery
    state.task.type = "character_portrait"
    state.task.character_id = "character"
    state.task.status = "failed"
    state.db.commit()
    metadata = state.task.metadata_json
    assert state.service.retry_task(state.task.id)["success"] is True
    assert state.task.status == "pending" and state.task.progress == 0
    for key in ("current_step", "error_message", "result_url", "completed_at", "comfyui_prompt_id", "workflow_json"):
        assert getattr(state.task, key) is None
    assert state.task.metadata_json == metadata
    state.enqueue.assert_called_once_with("task", "character", "Ada", "blue coat", "Waiting")


def test_reconcile_polls_frozen_host_not_current_queue_and_recovers(recovery):
    state = recovery
    state.queue = [[7, PROMPT_ID]]
    assert asyncio.run(state.service.reconcile_active_tasks([state.task])) == 1
    assert state.task.status == "completed"
    state.comfy.get_queue_info.assert_not_awaited()
    assert state.polls == [(ENDPOINT, (PROMPT_ID,), {})]
    assert state.requests == [ENDPOINT + "/queue", ENDPOINT + "/history/" + PROMPT_ID]
    contract = saved_contract(state)
    assert state.task.comfyui_prompt_id == contract["submit"]["prompt_id"] == PROMPT_ID
    assert json.loads(state.task.workflow_json) == contract["prepared_workflow"] == state.graph


@pytest.mark.parametrize("remote_state,updated", [("queued", 0), ("history", 0), ("unknown", 0), ("missing", 1), ("error", 1)])
def test_frozen_reconcile_preserves_existing_prompt_poll_behavior(recovery, remote_state, updated):
    state = recovery
    state.remote_state = remote_state
    assert asyncio.run(state.service.reconcile_active_tasks([state.task])) == updated
    assert state.task.status == ("failed" if updated else "running")
    assert len(state.polls) == 1 and state.polls[0] == (ENDPOINT, (PROMPT_ID,), {})
    assert len(state.requests) == (1 if remote_state == "queued" else 2)
    assert not state.downloads


@pytest.mark.parametrize("remote_state,parent_status,during_poll", [
    ("error", None, False), ("missing", None, False),
    *[("completed", status, during) for status in ("cancelled", "failed", "completed", "removed") for during in (False, True)],
])
def test_reconcile_failure_seals_failed_phase_and_precise_diagnostic(recovery, monkeypatch, remote_state, parent_status, during_poll):
    state = recovery
    state.remote_state = remote_state
    captured = saved_contract(state)
    original = deepcopy(captured)
    before, evidence = media(state), task_evidence(state)
    monkeypatch.setattr(state.module, "read_contract", Mock(return_value=captured))

    def stop_parent():
        with Session(state.engine) as other:
            parent = other.get(state.Task, "parent")
            if parent_status == "removed":
                other.delete(parent)
            else:
                parent.status = parent_status
            other.commit()

    if parent_status:
        if during_poll:
            state.poll_hook = stop_parent
        else:
            stop_parent()
    assert asyncio.run(state.service.reconcile_active_tasks([state.task])) == 1
    contract = saved_contract(state)
    code = "PARENT_NOT_ACTIVE" if parent_status else "GENERATION_FAILED" if remote_state == "error" else "SUBMITTED_JOB_MISSING"
    message = f"#09 {code}" + (": Fixture ComfyUI failure" if remote_state == "error" else "")
    assert state.task.status == contract["phase"] == "failed"
    assert contract["failure"] == {"stage": "reconciliation", "code": code, "message": message}
    assert state.task.error_message == message and state.task.completed_at is not None and state.task.progress != 100
    assert captured == original
    assert {key: value for key, value in contract.items() if key not in {"phase", "failure", "storage_revision", "storage_hash"}} == {
        key: value for key, value in original.items() if key not in {"phase", "failure", "storage_revision", "storage_hash"}
    }
    assert contract["storage_revision"] == original["storage_revision"] + 1
    assert contract["storage_hash"] != original["storage_hash"]
    assert state.gate.validate_frozen_contract(contract, state.task, require_submitted=True) == original["validation"]["graph"]
    for field in ("comfyui_prompt_id", "workflow_id", "workflow_name", "workflow_json", "prompt_text", "reference_images", "result_url"):
        assert getattr(state.task, field) == evidence[field]
    with pytest.raises(state.gate.KeyframeReferenceError, match="TASK_NOT_ACTIVE"):
        state.gate.assert_task_active(state.db, state.task, original)
    with Session(state.engine) as other:
        parent = other.get(state.Task, "parent")
        assert (parent.status if parent else "removed") == (parent_status or "running")
    assert OBSERVATIONS not in json.loads(state.task.metadata_json)
    assert media(state) == before and not state.downloads
    assert len(state.polls) == (0 if parent_status and not during_poll else 1)


def test_reconcile_staged_failure_cannot_replace_a_newer_failure_at_cas(recovery, monkeypatch):
    state = recovery
    state.remote_state = "error"
    captured = saved_contract(state)
    staged = []
    canonical = []
    store = state.module.store_contract

    def conflict(db, task_id, working, **fields):
        staged.append(deepcopy(working))
        newer = saved_contract(state)
        newer.update(phase="failed", failure={"stage": "worker", "code": "OTHER_WORKER_FAILURE", "message": "Other worker failed"})
        state.gate.store_contract(db, task_id, newer, terminal=True, status="failed",
                                  error_message="Other worker failed", result_url="/canonical-result.png")
        canonical.append(task_evidence(state))
        return store(db, task_id, working, **fields)

    monkeypatch.setattr(state.module, "store_contract", conflict)
    assert asyncio.run(state.service.reconcile_active_tasks([state.task])) == 0
    assert len(staged) == 1 and staged[0]["phase"] == "failed"
    assert staged[0]["failure"] == {"stage": "reconciliation", "code": "GENERATION_FAILED",
                                    "message": "#09 GENERATION_FAILED: Fixture ComfyUI failure"}
    assert (staged[0]["storage_revision"], staged[0]["storage_hash"]) == (captured["storage_revision"], captured["storage_hash"])
    after = task_evidence(state)
    assert {key: value for key, value in after.items() if key not in {"metadata_json", "updated_at"}} == {
        key: value for key, value in canonical[0].items() if key not in {"metadata_json", "updated_at"}
    }
    assert after["updated_at"] >= canonical[0]["updated_at"]
    metadata = json.loads(after["metadata_json"])
    assert {key: value for key, value in metadata.items() if key != OBSERVATIONS} == json.loads(canonical[0]["metadata_json"])
    assert metadata[OBSERVATIONS][-1]["code"] == "CONTRACT_STALE"
    assert metadata[OBSERVATIONS][-1]["expected_storage_revision"] == captured["storage_revision"]
    assert not state.downloads


def test_reconcile_keeps_single_shared_queue_poll_for_other_models(recovery):
    state = recovery
    other = state.Task(id="other", type="shot_video", name="Other", status="running", comfyui_prompt_id="other-prompt")
    state.db.add(other)
    state.db.commit()
    state.queue = [[1, "other-prompt"], [7, PROMPT_ID]]
    assert asyncio.run(state.service.reconcile_active_tasks([state.task, other])) == 1
    assert other.status == "running" and state.task.status == "completed"
    state.comfy.get_queue_info.assert_awaited_once_with()
    assert state.polls == [(ENDPOINT, (PROMPT_ID,), {}),
                           (CURRENT_ENDPOINT, ("other-prompt",), {"queue_info": {"queue_running": state.queue, "queue_pending": []}})]
    assert state.requests.count(CURRENT_ENDPOINT + "/queue") == 1


@pytest.mark.parametrize("history_change", [None, "prompt-id", "graph", "preview-only"])
def test_normal_p1_worker_polls_frozen_endpoint_and_strict_history(p1_worker, monkeypatch, history_change):
    state = p1_worker
    # Exercise the actual creator seal, not the parent fixture's integration shim.
    monkeypatch.setattr(state.module, "patch_target", state.contracts.patch_target)
    state.hooks["llm"] = lambda: setattr(state.shared_client, "base_url", CURRENT_ENDPOINT)

    def history(value):
        value["outputs"]["preview"] = {"images": [{"filename": "preview.png", "type": "output"}]}
        if history_change == "prompt-id":
            value["prompt"][1] = "different-prompt"
        elif history_change == "graph":
            value["prompt"][2]["110"]["inputs"]["text"] += " changed"
        elif history_change == "preview-only":
            value["outputs"].pop("9")

    state.history_hook = history
    worker_tests.create(state, workflow_id="workflow", parent_task_id="parent")
    result = worker_tests.run(state)
    state.client_factory.assert_called_once_with(ENDPOINT)
    state.clients[0].get_prompt_state.assert_awaited_once_with(result.task.comfyui_prompt_id)
    state.clients[0].wait_for_result.assert_not_awaited()
    assert state.shared_client.base_url == CURRENT_ENDPOINT
    assert result.contract["endpoint"] == state.clients[0].base_url == ENDPOINT
    assert result.contract["workflow"]["id"] == result.task.workflow_id == "workflow"
    assert result.contract["submit"]["state"] == "submitted"
    assert result.contract["submit"]["prompt_id"] == result.task.comfyui_prompt_id
    assert json.loads(result.task.workflow_json) == result.contract["prepared_workflow"] == state.queued[0]
    assert result.contract["submit"]["graph_hash"] == state.contracts.digest(state.queued[0])
    if history_change is None:
        assert result.task.status == "completed", result.task.error_message
        assert len(state.downloads) == 1 and state.downloads[0]["url"] == ENDPOINT + "/view?filename=out.png&subfolder=&type=output"
    else:
        assert result.task.status == "failed" and not state.downloads
        code = "RESULT_NODE_UNCERTAIN" if history_change == "preview-only" else "HISTORY_SUBMISSION_MISMATCH"
        assert result.contract["failure"]["code"] == code


def test_reconcile_does_not_replace_specific_recovery_failure_with_generic_timeout(recovery):
    state = recovery
    state.history["prompt"][1] = "wrong-prompt"
    assert asyncio.run(state.service.reconcile_active_tasks([state.task])) == 1
    assert "HISTORY_SUBMISSION_MISMATCH" in state.task.error_message
    assert state.task.status == "failed" and not state.downloads


@pytest.mark.parametrize("status", ["cancelled", "failed", "completed"])
def test_reconcile_does_not_revive_terminal_task_changed_during_poll(recovery, status):
    state = recovery
    state.poll_hook = lambda: change_task(state, status=status, error_message="Concurrent terminal state")
    assert asyncio.run(state.service.reconcile_active_tasks([state.task])) == 0
    assert state.task.status == status and state.task.error_message == "Concurrent terminal state"
    assert not state.downloads


def test_reconcile_ignores_task_deleted_during_poll(recovery):
    state = recovery

    def remove():
        with Session(state.engine) as other:
            other.delete(other.get(state.Task, "task"))
            other.commit()

    state.poll_hook = remove
    assert asyncio.run(state.service.reconcile_active_tasks([state.task])) == 0
    assert not state.downloads


@pytest.mark.parametrize("change", ["cid", "sealed-record"])
def test_reconcile_observes_instead_of_replacing_facts_changed_during_poll(recovery, change):
    state = recovery
    canonical = []

    def replace():
        if change == "cid":
            change_task(state, comfyui_prompt_id="new-canonical-prompt")
        else:
            record = saved_contract(state)
            record["worker_note"] = "Newer same-attempt evidence"
            state.gate.store_contract(state.db, state.task.id, record)
        canonical.append(task_evidence(state))

    state.poll_hook = replace
    assert asyncio.run(state.service.reconcile_active_tasks([state.task])) == 0
    after = task_evidence(state)
    assert {key: value for key, value in after.items() if key not in {"metadata_json", "updated_at"}} == {
        key: value for key, value in canonical[0].items() if key not in {"metadata_json", "updated_at"}
    }
    assert after["updated_at"] >= canonical[0]["updated_at"]
    metadata = json.loads(after["metadata_json"])
    assert {key: value for key, value in metadata.items() if key != OBSERVATIONS} == json.loads(canonical[0]["metadata_json"])
    assert metadata[OBSERVATIONS][-1]["expected_prompt_id"] == PROMPT_ID
    assert "artifact_url" not in metadata[OBSERVATIONS][-1] and not state.downloads


@pytest.mark.parametrize("submit_state,actual", [("submitted", True), ("attempted", False), ("unknown", False), ("not_submitted", False)])
def test_workflow_api_projects_only_frozen_ack_or_labelled_prepared_graph(recovery, submit_state, actual):
    state = recovery
    contract = saved_contract(state)
    contract["submit"]["state"] = submit_state
    if not actual:
        contract["submit"] = {"state": submit_state}
        if submit_state in {"attempted", "unknown"}:
            contract["submit"]["graph_hash"] = state.gate.digest(state.graph)
        state.task.workflow_json = None
        state.task.comfyui_prompt_id = None
        contract["phase"] = "prompt_ready" if submit_state == "not_submitted" else "submitting"
        state.gate.seal_contract(contract, advance=True)
    save_contract(state, contract)
    before = task_evidence(state)
    result = asyncio.run(state.api.get_task_workflow(state.task.id, state.repo))["data"]
    assert result["workflow"] == state.graph and result["prompt"] == PROMPT
    assert result["workflowSource"] == ("submitted" if actual else "prepared")
    assert result["submitState"] == submit_state and result["note"]
    assert result["sourceProof"]["verified"] is True and result["diagnostic"] is None
    assert result["referenceImages"] == [{"label": "Primary storyboard", "url": "/primary.png"}]
    summary = result["metadata"][KEY]
    assert summary["submit"] == contract["submit"]
    assert summary["workflow"]["node_mapping"]["save_image_node_id"] == "9"
    assert summary["attempt_id"] == "frozen-attempt" and summary["endpoint"] == ENDPOINT
    assert summary["storage_revision"] == contract["storage_revision"] and summary["storage_hash"] == contract["storage_hash"]
    assert "prepared_workflow" not in summary and "text" not in summary["prompt"]
    assert task_evidence(state) == before and not state.requests and not state.downloads


def test_workflow_api_does_not_claim_ack_from_unconfirmed_task_json(recovery):
    state = recovery
    contract = saved_contract(state)
    contract["submit"]["state"] = "unknown"
    state.task.workflow_json = '{"not":"acknowledged"}'
    save_contract(state, contract)
    data = asyncio.run(state.api.get_task_workflow(state.task.id, state.repo))["data"]
    assert data["workflowSource"] == "unverified" and data["sourceProof"]["verified"] is False
    assert data["diagnostic"]["workflowJson"] == state.task.workflow_json
    assert data["submitState"] == "unknown" and data["metadata"][KEY]["submit"] == contract["submit"]


def test_workflow_api_does_not_claim_actual_when_prepared_proof_was_tampered(recovery):
    state = recovery
    contract = saved_contract(state)
    contract["prepared_workflow"] = {"different": "prepared graph"}
    save_contract(state, contract)
    data = asyncio.run(state.api.get_task_workflow(state.task.id, state.repo))["data"]
    assert data["workflow"] == state.graph and data["workflowSource"] == "unverified"
    assert data["sourceProof"]["code"] == "CONTRACT_SEAL_INVALID"


def test_workflow_api_before_preparation_never_guesses_current_template(recovery):
    state = recovery
    contract = saved_contract(state)
    for field in ("prepared_workflow", "manifest", "frozen_binding_hash", "validation"):
        contract.pop(field)
    contract["phase"] = "resolved"
    contract["binding_resolved"] = False
    contract["binding"] = None
    contract["submit"] = {"state": "not_submitted"}
    contract["prompt"] = {"llm_invoked": False}
    state.task.workflow_json = state.task.prompt_text = state.task.comfyui_prompt_id = None
    state.task.reference_images = "[]"
    state.gate.seal_contract(contract, advance=True)
    save_contract(state, contract)
    data = asyncio.run(state.api.get_task_workflow(state.task.id, state.repo))["data"]
    assert data["workflow"] is None and data["workflowSource"] is None
    assert data["submitState"] == "not_submitted" and data["note"]


@pytest.mark.parametrize("workflow_json", ["not-json", "[]", "null", "1", '"{}"', '{"value":NaN}', '{"value":1e999}'])
def test_p1_api_invalid_actual_json_is_diagnostic_not_an_actual_graph(recovery, workflow_json):
    state = recovery
    state.task.workflow_json = workflow_json
    state.db.commit()
    before = task_evidence(state)
    data = asyncio.run(state.api.get_task_workflow(state.task.id, state.repo))["data"]
    assert data["workflowSource"] == "unverified" and data["sourceProof"]["verified"] is False
    assert data["workflow"] is None and data["diagnostic"]["workflowJson"] == workflow_json
    assert data["submitState"] == "submitted" and data["note"]
    json.dumps(data, allow_nan=False)
    assert task_evidence(state) == before and not state.requests


@pytest.mark.parametrize("references", ['[NaN]', '[{"label":"x","url":NaN}]', '[null]', '["not-an-image"]'])
def test_p1_api_invalid_reference_projection_remains_json_safe(recovery, references):
    state = recovery
    state.task.reference_images = references
    state.db.commit()
    before = task_evidence(state)
    data = asyncio.run(state.api.get_task_workflow(state.task.id, state.repo))["data"]
    assert data["workflowSource"] == "unverified" and data["sourceProof"]["verified"] is False
    assert data["referenceImages"] == [] and data["diagnostic"]["referenceImages"] == references
    json.dumps(data, allow_nan=False)
    assert task_evidence(state) == before


def test_p1_api_malformed_partial_phase_is_diagnostic_not_an_exception(recovery):
    state = recovery
    state.task.workflow_json = None
    save_contract(state, {"version": 1, "phase": [], "submit": {"state": "not_submitted"}})
    before = task_evidence(state)
    data = asyncio.run(state.api.get_task_workflow(state.task.id, state.repo))["data"]
    assert data["workflow"] is None and data["workflowSource"] == "unverified"
    assert data["sourceProof"]["verified"] is False and data["diagnostic"]["metadataJson"] == state.task.metadata_json
    assert task_evidence(state) == before


@pytest.mark.parametrize("contract", [None, [], "invalid", {}, {"version": 2}, {"version": 1, "prompt": [], "target": [], "submit": []}])
def test_p1_namespace_with_invalid_record_never_falls_back_to_generic_workflow_api(recovery, contract):
    state = recovery
    save_contract(state, contract)
    before = task_evidence(state)
    data = asyncio.run(state.api.get_task_workflow(state.task.id, state.repo))["data"]
    assert data["workflowSource"] == "unverified" and data["sourceProof"]["verified"] is False
    assert data["diagnostic"]["metadataJson"] == state.task.metadata_json
    assert task_evidence(state) == before and not state.requests


@pytest.mark.parametrize("task_type", ["keyframe_image", "shot_image", "shot_video", "audio_prepare"])
@pytest.mark.parametrize("workflow_json", [None, "{}", "not-json"])
def test_legacy_and_other_workflow_api_responses_are_unchanged(recovery, task_type, workflow_json):
    state = recovery
    state.task.type = task_type
    state.task.metadata_json = '{"old":"keep"}'
    state.task.workflow_json = workflow_json
    state.db.commit()
    data = asyncio.run(state.api.get_task_workflow(state.task.id, state.repo))["data"]
    assert data["workflow"] == ({} if workflow_json == "{}" else workflow_json)
    assert data["prompt"] == PROMPT
    assert data["execution_purpose"] == "production"
    expected_keys = {"workflow", "prompt", "execution_purpose"}
    if workflow_json is None:
        expected_keys.add("note")
    if task_type == "shot_video":
        expected_keys.add("videoExecution")
    assert set(data) == expected_keys


def test_existing_list_references_and_detail_metadata_already_project_evidence(recovery):
    state = recovery
    detail = state.service.format_task_detail(state.task)
    item = state.service.format_task_list([state.task], {}, {}, {})[0]
    assert item["referenceImages"] == detail["referenceImages"] == json.loads(state.task.reference_images)
    assert detail["metadata"][KEY] == saved_contract(state)


@pytest.mark.parametrize("relative,changed", [
    ("app/services/task_service.py", {
        "retry_task", "reconcile_active_tasks", "_recover_completed_keyframe_prompt",
        "_mark_related_task_failed", "_cleanup_cancelled_video_task", "_mark_pending_video_llm_logs_cancelled",
        "cancel_task", "cancel_all_tasks", "mark_related_shot_failed",
        "_recover_completed_shot_image_prompt", "_recover_completed_shot_video_prompt",
        "_recover_completed_single_shot_video_prompt", "_enqueue_remaining_shot_video_clip",
        "format_task_list", "format_video_director_clips", "format_task_detail", "mutate_window_result",
    }),
    ("app/api/tasks.py", {"get_task_workflow", "get_task_clip_workflow", "cancel_all_tasks", "delete_task", "mutate"}),
])
def test_other_functions_and_p0_business_branches_are_source_frozen(relative, changed):
    current = (BACKEND / relative).read_text()
    original = subprocess.check_output(["git", "show", "HEAD:backend/" + relative], cwd=BACKEND.parent, text=True)

    def functions(source):
        return {node.name: node for node in ast.walk(ast.parse(source))
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}

    before, after = functions(original), functions(current)
    for name in before.keys() - changed:
        assert ast.dump(before[name]) == ast.dump(after[name]), name

    # Explicitly retire proofless video publication, not unrelated legacy branches.
    guard = ast.parse('''if has_video_execution(task) or self.format_execution_purpose(task)["execution_purpose"] != "production":
    return False
''').body[0]
    for name in {"_recover_completed_shot_video_prompt", "_recover_completed_single_shot_video_prompt",
                 "_enqueue_remaining_shot_video_clip"} & changed:
        authorized_guard = deepcopy(guard)
        enqueue = name == "_enqueue_remaining_shot_video_clip"
        if enqueue:
            authorized_guard.body[0].value = None
        body = after[name].body if enqueue else after[name].body[1:]
        forwarding = ast.parse("self._fail_unproven_legacy_video(task, db)" if enqueue else
                               "return self._fail_unproven_legacy_video(task, db, prompt_history)").body[0]
        assert [ast.dump(node) for node in body] == [ast.dump(authorized_guard), ast.dump(forwarding)]
    if relative == "app/services/task_service.py":
        calls = {ast.unparse(node.func) for node in ast.walk(ast.parse(current)) if isinstance(node, ast.Call)}
        assert not calls & {"merge_video_director_clip_videos", "enqueue_shot_video_task", "file_storage.download_video"}

    class TerminalCAS(ast.NodeTransformer):
        """Normalize only the exact legacy failure assignment sequence to its CAS call."""
        def generic_visit(self, node):
            node = super().generic_visit(node)
            for field, children in ast.iter_fields(node):
                if not isinstance(children, list):
                    continue
                index = 0
                while index < len(children):
                    if not isinstance(children[index], ast.Assign) or ast.unparse(children[index]) != "task.status = 'failed'":
                        index += 1
                        continue
                    block = children[index:]
                    if len(block) < 4 or not all(isinstance(item, ast.Assign) for item in block[:3]):
                        index += 1
                        continue
                    assert ast.unparse(block[1].targets[0]) == "task.error_message"
                    assert ast.unparse(block[2].targets[0]) == "task.current_step"
                    end = 3
                    while ast.unparse(block[end]) in {"task.completed_at = datetime.utcnow()", "mark_related_shot_failed()"}:
                        end += 1
                    assert ast.unparse(block[end]) == "updated_count += 1"
                    children[index:index + end + 1] = [ast.Expr(value=ast.Call(
                        func=ast.Name(id="fail_task", ctx=ast.Load()), args=[block[1].value, block[2].value], keywords=[]))]
                    index += 1
            return node

    for name in {"retry_task", "reconcile_active_tasks"} & changed:
        def branches(function):
            if name == "reconcile_active_tasks":
                # The last loop remains the legacy path; strict dispatch lives before it.
                function = [node for node in function.body if isinstance(node, ast.For)
                            and ast.unparse(node.target) == "task"][-1]
                function = deepcopy(function)
                function.body = [node for node in function.body if not isinstance(node, ast.FunctionDef)]
                function = TerminalCAS().visit(function)
            result = {}
            for node in ast.walk(function):
                if isinstance(node, ast.If):
                    condition = ast.unparse(node.test)
                    if condition in {
                        "task.type == 'shot_video' and task.novel_id and task.chapter_id and task.workflow_id",
                        "task.type == 'shot_video' and inactive_seconds(task) > 60",
                        "task.type == 'shot_video' or self.format_execution_purpose(task)['execution_purpose'] != 'production'",
                    }:
                        continue
                    if "task.type" in condition and any(repr(kind) in condition for kind in (
                        "character_portrait", "scene_image", "prop_image", "shot_image", "shot_video",
                    )):
                        result[condition] = [ast.dump(child) for child in node.body]
            return result
        assert branches(before[name]) == branches(after[name])
