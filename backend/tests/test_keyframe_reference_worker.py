"""Full #09 worker regressions: Python 3.11, --noconftest, plugin autoload off.

Real models, repositories, builder, reference contracts and publication SQL;
only external services are replaced. All media is generated under tmp_path.
No P0 test/helper, app.main, application settings or production DB is imported.
"""

import asyncio
import builtins
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import importlib.util
import io
from itertools import count
import json
from pathlib import Path
import socket
import sqlite3
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock
import zlib

from PIL import Image
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Query, declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND = Path(__file__).resolve().parents[1]
KEY = "keyframe_reference_contract"
ENDPOINT = "http://frozen-comfy.test:8188"
DEFAULT = object()
OLD_PROMPT = "Old draft: reference image 1/2/3/4. Preserve this exact text on failure."
PROSE = {
    "en": {
        "PRIMARY_STORYBOARD": "Use Picture 1, the primary storyboard image, as the only edit base. Raise Ada's hand beside the gate.",
        "PREVIOUS_KEYFRAME": "Use Picture 1, the previous keyframe image, as the only edit base. Raise Ada's hand beside the gate.",
        "CUSTOM_REFERENCE": "Use Picture 1, the custom reference image, as the only edit base. Raise Ada's hand beside the gate.",
        "SAVED_REFERENCE": "Use Picture 1, the fixed reference image, as the only edit base. Raise Ada's hand beside the gate.",
        "NONE": "No reference images are provided. Draw Ada raising her hand beside the gate.",
    },
    "zh": {
        "PRIMARY_STORYBOARD": "\u4ee5\u56fe\u72471\u7684\u4e3b\u5206\u955c\u56fe\u4e3a\u5e95\u56fe\uff0c\u8ba9\u963f\u5c9a\u5728\u95e8\u65c1\u62ac\u8d77\u53f3\u624b\u3002",
        "PREVIOUS_KEYFRAME": "\u4ee5\u56fe\u72471\u7684\u4e0a\u4e00\u5173\u952e\u5e27\u56fe\u7247\u4e3a\u5e95\u56fe\uff0c\u8ba9\u963f\u5c9a\u5728\u95e8\u65c1\u62ac\u8d77\u53f3\u624b\u3002",
        "CUSTOM_REFERENCE": "\u4ee5\u56fe\u72471\u7684\u81ea\u5b9a\u4e49\u53c2\u8003\u56fe\u4e3a\u5e95\u56fe\uff0c\u8ba9\u963f\u5c9a\u62ac\u8d77\u53f3\u624b\u3002",
        "SAVED_REFERENCE": "\u4ee5\u56fe\u72471\u7684\u5df2\u56fa\u5b9a\u53c2\u8003\u56fe\u4e3a\u5e95\u56fe\uff0c\u8ba9\u963f\u5c9a\u62ac\u8d77\u53f3\u624b\u3002",
        "NONE": "\u65e0\u53c2\u8003\u56fe\u3002\u753b\u51fa\u963f\u5c9a\u5728\u95e8\u65c1\u62ac\u8d77\u53f3\u624b\u7684\u753b\u9762\u3002",
    },
}


@pytest.fixture
def worker(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("Production startup, database, storage and network I/O are forbidden")

    for name in ("connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, name, forbidden)
    for name in ("create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, forbidden)
    original_connect = sqlite3.dbapi2.connect

    def memory_only(database, *args, **kwargs):
        assert database == ":memory:"
        return original_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", memory_only)
    monkeypatch.setattr(sqlite3.dbapi2, "connect", memory_only)
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    for owner in (builtins, io):
        original_open = owner.open

        def temporary_writes(file, mode="r", *args, _open=original_open, **kwargs):
            if any(flag in mode for flag in "wax+"):
                assert not isinstance(file, int) and Path(file).resolve().is_relative_to(tmp_path)
            return _open(file, mode, *args, **kwargs)

        monkeypatch.setattr(owner, "open", temporary_writes)

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

    for name in ("app", "app.core", "app.models", "app.repositories", "app.services",
                 "app.services.llm", "app.services.comfyui", "app.utils"):
        stub(name, __path__=[])
    stub("app.core.config", get_settings=forbidden)
    base = declarative_base()
    database = stub("app.core.database", Base=base, SessionLocal=forbidden, get_db=forbidden)
    novels = load("app.models.novel", "app/models/novel.py")
    Shot = load("app.models.shot", "app/models/shot.py").Shot
    Task = load("app.models.task", "app/models/task.py").Task
    Workflow = load("app.models.workflow", "app/models/workflow.py").Workflow
    Template = load("app.models.prompt_template", "app/models/prompt_template.py").PromptTemplate
    LLMLog = load("app.models.llm_log", "app/models/llm_log.py").LLMLog
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    database.SessionLocal = sessions
    state = SimpleNamespace(
        sessions=sessions, engine=engine, Shot=Shot, Task=Task, Workflow=Workflow, Template=Template, novels=novels, LLMLog=LLMLog,
        root=tmp_path, hooks={}, events=[], uploads=[], queued=[], prequeue=[], downloads=[], inputs=[],
        clients=[], builders=[], enqueued=[], jobs={}, task_id=None, language="en", response=DEFAULT,
        receipt_changes={}, queue_response=DEFAULT, queue_error=None, history_hook=None, poll_states=[],
        output_kind="png", shared_client=SimpleNamespace(base_url=ENDPOINT), previous_producer_id="previous-producer",
    )
    state.urls = {name: make_image(state, name, color) for name, color in (
        ("primary", "blue"), ("previous", "green"), ("custom", "yellow"), ("replacement", "red"),
        ("old-legacy", "gray"), ("old-plan", "white"), ("characters", "pink"), ("scene", "brown"), ("prop", "purple"),
    )}

    async def checkpoint(stage):
        state.events.append(stage)
        hook = state.hooks.pop(stage, None)
        if hook:
            hook()
        await asyncio.sleep(0)

    async def complete(**kwargs):
        payload = json.loads(kwargs["user_content"].split("\n\n", 1)[1])
        state.inputs.append(payload)
        await checkpoint("llm")
        if state.response is not DEFAULT:
            return deepcopy(state.response)
        source = payload["reference_resolution"]["source_kind"]
        return {"success": True, "content": PROSE[state.language][source]}

    state.llm = AsyncMock(side_effect=complete)

    class FakeLLM:
        provider = "isolated-provider"
        model = "source-specific-prose"
        max_tokens = 2500
        temperature = 0.3

        def __init__(self):
            self.chat_completion = state.llm

    stub("app.services.llm_service", LLMService=FakeLLM)
    stub("app.services.llm.base", mark_matching_pending_llm_logs_error=forbidden)
    load("app.repositories.shot_repository", "app/repositories/shot_repository.py")
    load("app.repositories.prompt_template", "app/repositories/prompt_template.py")
    load("app.services.prompt_builder", "app/services/prompt_builder.py")
    load("app.services.video_director_plan_service", "app/services/video_director_plan_service.py")
    load("app.services.h3_prompt_validation", "app/services/h3_prompt_validation.py")
    load("app.services.video_director_ai", "app/services/video_director_ai.py")
    state.contracts = load("app.services.keyframe_reference_contract", "app/services/keyframe_reference_contract.py")
    state.graphs = load("app.services.keyframe_reference_graph", "app/services/keyframe_reference_graph.py")
    load("app.services.task_execution", "app/services/task_execution.py")
    builders = load("app.services.comfyui.workflows", "app/services/comfyui/workflows.py")
    seeds = count(101)
    monkeypatch.setattr(builders, "random", SimpleNamespace(randint=lambda *args: next(seeds)))

    class FakeComfyService:
        def __init__(self):
            self.client = state.shared_client
            self.builder = builders.WorkflowBuilder()
            self.builder.build_shot_workflow = Mock(wraps=self.builder.build_shot_workflow)
            state.builders.append(self.builder)

    client_ids, prompt_ids, download_ids = count(1), count(1), count(1)

    class FakeClient:
        def __init__(self, endpoint):
            self.base_url = endpoint
            self.client_id = f"task-local-client-{next(client_ids)}"
            self.submitted = {}
            self.upload_image = AsyncMock(side_effect=self.upload)
            self.queue_prompt = AsyncMock(side_effect=self.queue)
            self.get_prompt_state = AsyncMock(side_effect=self.poll)
            self.wait_for_result = AsyncMock(side_effect=forbidden)
            state.clients.append(self)

        async def upload(self, path, *, upload_name, payload):
            assert Path(path).is_relative_to(tmp_path) and isinstance(payload, bytes)
            state.uploads.append({"path": path, "upload_name": upload_name, "payload": payload, "endpoint": self.base_url})
            await checkpoint("upload")
            receipt = {"success": True, "filename": "receipts/" + upload_name,
                       "payload_sha256": hashlib.sha256(payload).hexdigest(), "payload_size": len(payload)}
            receipt.update(state.receipt_changes)
            return receipt

        async def queue(self, graph):
            state.queued.append(deepcopy(graph))
            state.prequeue.append(saved(state))
            prompt_id = f"queued-{next(prompt_ids)}"
            self.submitted[prompt_id] = deepcopy(graph)
            await checkpoint("queue")
            if state.queue_error:
                raise state.queue_error
            return {"success": True, "prompt_id": prompt_id} if state.queue_response is DEFAULT else deepcopy(state.queue_response)

        async def poll(self, prompt_id):
            await checkpoint("poll")
            if state.poll_states:
                return state.poll_states.pop(0)
            graph = self.submitted[prompt_id]
            save_id = next(node_id for node_id, node in graph.items() if node["class_type"] == "SaveImage")
            prompt_history = {
                "prompt": [0, prompt_id, deepcopy(graph), {}, [save_id]],
                "status": {"completed": True, "status_str": "success"},
                "outputs": {save_id: {"images": [{"filename": "out.png", "subfolder": "", "type": "output"}]}},
            }
            if state.history_hook:
                state.history_hook(prompt_history)
            return {"state": "completed", "history": prompt_history}

    stub("app.services.comfyui", ComfyUIService=FakeComfyService, __path__=[])

    def to_path(url):
        if not url or not url.startswith("/api/files/"):
            return None
        path = (tmp_path / url.removeprefix("/api/files/")).resolve()
        assert path.is_relative_to(tmp_path)
        return str(path)

    def to_url(path):
        return "/api/files/" + Path(path).relative_to(tmp_path).as_posix() if path else None

    stub("app.utils.path_utils", url_to_local_path=to_path, local_path_to_url=to_url)
    state.to_path = to_path

    async def download(**kwargs):
        assert kwargs["url"].startswith(ENDPOINT + "/view?")
        state.downloads.append(kwargs)
        path = tmp_path / f"result-{next(download_ids)}.png"
        if state.output_kind != "missing":
            make_image(state, path.stem, "cyan", animated=state.output_kind == "animated")
            if state.output_kind == "corrupt":
                path.write_bytes(b"not a PNG")
        await checkpoint("download")
        if state.output_kind == "exception":
            raise OSError("download interrupted")
        return None if state.output_kind == "missing" else str(path)

    state.storage = SimpleNamespace(base_dir=tmp_path, download_image=AsyncMock(side_effect=download))
    stub("app.services.file_storage", file_storage=state.storage)
    state.enqueue = Mock(side_effect=state.enqueued.append)
    state.worker_factory = Mock(return_value=SimpleNamespace(enqueue=state.enqueue))
    stub("app.services.background_workers", worker_manager=SimpleNamespace(worker=state.worker_factory))
    state.module = load("app.services.shot_keyframe_service", "app/services/shot_keyframe_service.py")
    state.client_factory = Mock(side_effect=FakeClient)
    monkeypatch.setattr(state.module, "frozen_keyframe_client", state.client_factory)
    state.service = state.module.ShotKeyframeService()
    with sessions() as db:
        db.add_all([
            novels.Novel(id="novel", title="Isolated novel", aspect_ratio="16:9", keyframe_image_prompt_template_id="template"),
            novels.Chapter(id="chapter", novel_id="novel", number=1, title="Isolated chapter"),
            Template(id="template", name="Frozen #09", type="keyframe_image_prompt", is_system=True,
                     template=(BACKEND / "prompt_templates/09_NovelFlow_QwenEdit2511_KeyframeImagePrompt_V1.txt").read_text()),
            Workflow(id="workflow", name="Frozen workflow", type="keyframe_image", workflow_json="{}"),
            Task(id="parent", name="Active batch", type="keyframe_batch", status="running"),
            Task(id="primary-producer", name="Primary source", type="shot_image", status="completed",
                 novel_id="novel", shot_id="shot", result_url=state.urls["primary"]),
            Task(id="previous-producer", name="KF4 source", type="keyframe_image", status="completed",
                 novel_id="novel", shot_id="shot", result_url=state.urls["previous"]),
            novels.Character(id="ada", novel_id="novel", name="Ada", appearance="blue coat", image_url=state.urls["characters"]),
            novels.Character(id="bea", novel_id="novel", name="Bea", appearance="red coat", image_url=state.urls["characters"]),
            novels.Scene(id="scene", novel_id="novel", name="courtyard", setting="stone gate", image_url=state.urls["scene"]),
            novels.Prop(id="prop", novel_id="novel", name="sword", image_url=state.urls["prop"]),
        ])
        db.commit()
    configure(state)
    try:
        yield state
    finally:
        for client in state.clients:
            client.wait_for_result.assert_not_awaited()
        engine.dispose()
        base.registry.dispose()


def make_image(worker, name, color="blue", *, animated=False):
    path = worker.root / f"{name}.png"
    options = {"save_all": True, "append_images": [Image.new("RGB", (4, 4), "red")], "duration": 50} if animated else {}
    Image.new("RGB", (4, 4), color).save(path, format="PNG", **options)
    return "/api/files/" + path.name


def configure(worker, *, shot_index=1, target_kf=5, previous=None, mode="auto_select", reference=None,
              prompt=OLD_PROMPT, family="flux", legacy_description=None):
    worker.frame_index = target_kf - 2
    worker.target_kf = target_kf
    graph_path = BACKEND / "workflows/keyframe_flux2_klein.json"
    mapping = {"prompt_node_id": "110", "save_image_node_id": "9", "reference_image_node_id": "76",
               "width_node_id": "123", "height_node_id": "125"}
    if family == "qwen":
        graph_path = next((BACKEND / "user_workflows").glob("*Qwen-Edit-2511*keyframe_image.json"))
        mapping = {"prompt_node_id": "184", "save_image_node_id": "163", "reference_image_node_id": "170"}
    worker.graph = json.loads(graph_path.read_text())
    worker.mapping = mapping
    plan_frames = [{"index": index, "role": "START" if index == 1 else "END" if index == 6 else "INTERMEDIATE",
                    "time_seconds": index - 1, "description": f"KF{index}: Ada waits beside the gate.",
                    "image_url": worker.urls["primary"] if index == 1 else None}
                   for index in range(1, 7)]
    frames = [{**item, "frame_index": index, "plan_keyframe_index": item["index"], "reference_mode": "auto_select"}
              for index, item in enumerate(plan_frames[1:])]
    for item in frames:
        item.pop("index")
    target, planned = frames[worker.frame_index], plan_frames[target_kf - 1]
    target.update(reference_mode=mode, reference_image_url=reference, image_url=worker.urls["old-legacy"], image_task_id="old-legacy-owner")
    planned.update(image_url=worker.urls["old-plan"], image_task_id="old-plan-owner")
    if prompt is not DEFAULT:
        target["prompt_text"] = planned["prompt_text"] = prompt
    if legacy_description is not None:
        target["description"] = legacy_description
    if worker.frame_index:
        frames[worker.frame_index - 1]["image_url"] = previous
        plan_frames[target_kf - 2]["image_url"] = previous
    plan = {"selected_mode": "MULTI_KEYFRAME", "keyframes": plan_frames, "ai_calls": [],
            "window_plans": [{"window_index": 1, "status": "SUCCEEDED", "video_url": "/old-window.mp4"}], "user_note": "keep"}
    with worker.sessions() as db:
        shot = db.get(worker.Shot, "shot")
        if not shot:
            shot = worker.Shot(id="shot", chapter_id="chapter", index=shot_index)
            db.add(shot)
        shot.index = shot_index
        shot.description = "Ada and Bea wait beside the courtyard gate with a sword."
        shot.video_description = "Ada slowly raises her hand."
        shot.characters, shot.scene, shot.props = '["Ada", "Bea"]', "courtyard", '["sword"]'
        shot.duration, shot.continuity_mode, shot.dialogues = 5, "NORMAL", "[]"
        shot.image_url, shot.video_url = worker.urls["primary"], "/old-shot.mp4"
        shot.merged_character_image, shot.merged_prop_image = worker.urls["characters"], worker.urls["prop"]
        shot.keyframes, shot.video_director_plan = json.dumps(frames), json.dumps(plan)
        shot.video_director_plan_revision = 7
        workflow = db.get(worker.Workflow, "workflow")
        workflow.workflow_json, workflow.node_mapping = json.dumps(worker.graph), json.dumps(mapping)
        db.commit()


def saved(worker, task_id=None):
    # Never assert against the worker's identity map or an uncommitted transaction.
    with worker.sessions() as db:
        task = db.get(worker.Task, task_id or worker.task_id) if task_id or worker.task_id else None
        shot = db.get(worker.Shot, "shot")
        return SimpleNamespace(task=task, shot=shot, contract=worker.contracts.read_contract(task) if task else None,
                               frames=json.loads(shot.keyframes), plan=json.loads(shot.video_director_plan))


def edit(worker, mutate):
    with worker.sessions() as db:
        shot = db.get(worker.Shot, "shot")
        view = SimpleNamespace(db=db, shot=shot, task=db.get(worker.Task, worker.task_id) if worker.task_id else None,
                               frames=json.loads(shot.keyframes), plan=json.loads(shot.video_director_plan))
        mutate(view)
        if view.frames != json.loads(shot.keyframes):
            shot.keyframes = json.dumps(view.frames, ensure_ascii=False)
        if view.plan != json.loads(shot.video_director_plan):
            shot.video_director_plan = json.dumps(view.plan, ensure_ascii=False)
            shot.video_director_plan_revision += 1
        db.commit()


def request(worker, **options):
    frame_index = options.pop("frame_index", worker.frame_index)
    before = len(worker.enqueued)
    with worker.sessions() as db:
        result = asyncio.run(worker.service.generate_keyframe_image(db, "shot", frame_index, **options))
    if result[0]:
        worker.task_id = result[1]
        if len(worker.enqueued) != before:
            worker.jobs[result[1]] = worker.enqueued[-1]
    return result


def create(worker, **options):
    success, task_id, message = request(worker, **options)
    assert success and task_id, message
    return task_id


def run(worker, task_id=None):
    # Invoke the actual closure enqueued by generate_keyframe_image; it owns a new Session.
    task_id = task_id or worker.task_id
    asyncio.run(worker.jobs[task_id]())
    return saved(worker, task_id)


def assert_completed(worker, result, source):
    task, contract = result.task, result.contract
    assert task.status == "completed", task.error_message
    assert task.progress == 100 and task.started_at and task.completed_at and task.error_message is None
    assert contract["phase"] == "completed" and contract["result"] == {"url": task.result_url, "attachment": "attached"}
    assert contract["prompt"]["validation"]["source_kind"] == source
    assert contract["validation"]["passed"] is True
    assert task.prompt_text == contract["prompt"]["text"]
    assert contract["prompt"]["text_hash"] == worker.contracts.digest(task.prompt_text)
    assert json.loads(task.workflow_json) == contract["prepared_workflow"] == worker.queued[-1]
    assert task.comfyui_prompt_id == contract["submit"]["prompt_id"]
    assert contract["submit"]["graph_hash"] == worker.contracts.digest(worker.queued[-1])
    frame, planned = result.frames[worker.frame_index], result.plan["keyframes"][worker.target_kf - 1]
    assert frame["prompt_text"] == planned["prompt_text"] == task.prompt_text
    assert frame["image_url"] == planned["image_url"] == task.result_url
    assert frame["image_task_id"] == planned["image_task_id"] == task.id
    assert result.shot.video_url == "/old-shot.mp4" and result.plan["window_plans"][0]["video_url"] == "/old-window.mp4"
    references = worker.contracts.reference_images(contract)
    assert json.loads(task.reference_images) == references
    call = result.plan["ai_calls"][-1]
    assert call["reference_images"] == references and call["final_prompt"] == task.prompt_text
    assert call["parsed_result"]["manifest"] == contract["manifest"] == worker.contracts.reference_manifest(contract)
    assert call["parsed_result"]["binding_hash"] == contract["frozen_binding_hash"]
    assert call["parsed_result"]["resolved"] == contract["resolved"]
    assert contract["frozen_binding_hash"] == worker.contracts.digest({key: contract[key] for key in ("resolved", "binding", "manifest")})
    inspection = contract["validation"]["graph"]
    assert worker.contracts.validate_frozen_contract(contract, task, require_submitted=True) == inspection
    assert inspection["effective_prompt"] == task.prompt_text
    assert inspection["reference_count"] == len(references) == len(contract["manifest"])
    if source != "NONE":
        binding, upload = contract["binding"], worker.uploads[-1]
        assert binding["payload_sha256"] == contract["resolved"]["sha256"] == hashlib.sha256(upload["payload"]).hexdigest()
        assert binding["payload_size"] == contract["resolved"]["size"] == len(upload["payload"])
        assert binding["uploaded_filename"] == inspection["reference_filename"] == "receipts/" + upload["upload_name"]
        assert inspection["image_source_nodes"] == [binding["node_id"]]
        assert inspection["reference_node_id"] == binding["node_id"]
        assert worker.queued[-1][binding["node_id"]]["inputs"]["image"] == binding["uploaded_filename"]
    else:
        assert contract["resolved"] is contract["binding"] is None
        assert references == inspection["image_source_nodes"] == []
        assert not any(node["class_type"] == "LoadImage" for node in worker.queued[-1].values())
    with Image.open(worker.to_path(task.result_url)) as image:
        image.load()
        assert image.format == "PNG" and image.n_frames == 1 and image.size == (4, 4)
    for builder in worker.builders:
        builder.build_shot_workflow.assert_called_once()
        assert builder.build_shot_workflow.call_args.kwargs["prompt"] == ""


def assert_failed(worker, result, code, *, queued=0, llm=0):
    assert len(worker.queued) == queued
    assert worker.llm.await_count == llm
    assert result.task.status == "failed", result.task.error_message
    assert result.task.completed_at and result.task.progress != 100
    assert result.contract["phase"] == "failed" and result.contract["failure"]["code"] == code
    assert code in result.task.error_message or result.contract["failure"]["message"] == result.task.error_message


def assert_observation_only(worker, before, after, expected, code, *, prompt_id=None, artifact_url=None):
    for column in worker.Task.__table__.columns:
        if column.name not in {"metadata_json", "updated_at"}:
            assert getattr(after.task, column.name) == getattr(before.task, column.name), column.name
    assert after.frames == before.frames and after.plan == before.plan
    assert after.contract == before.contract
    original, current = json.loads(before.task.metadata_json), json.loads(after.task.metadata_json)
    observations_key = worker.contracts.OBSERVATIONS_KEY
    previous = original.pop(observations_key, [])
    observations = current.pop(observations_key)
    assert current == original and observations[:-1] == previous
    observation = observations[-1]
    assert observation["code"] == code and code in observation["reason"]
    assert observation["attempt_id"] == expected["attempt_id"]
    assert observation["expected_storage_revision"] == expected["storage_revision"]
    assert observation["expected_prompt_id"] == prompt_id
    assert observation["at"].endswith("Z")
    if artifact_url is None:
        assert "artifact_url" not in observation
    else:
        assert observation["artifact_url"] == artifact_url
        with Image.open(worker.to_path(artifact_url)) as image:
            image.load()
            assert image.format == "PNG" and image.n_frames == 1


@pytest.mark.parametrize("explicit", [False, True])
def test_real_creation_claims_both_targets_without_resolving_or_rewriting(worker, explicit):
    before = saved(worker)
    task_id = create(worker, workflow_id="workflow" if explicit else None, parent_task_id="parent", batch_order=4)
    result = saved(worker)
    assert isinstance(result.task, worker.Task) and isinstance(result.shot, worker.Shot)
    assert result.task.id == task_id and result.task.status == "pending"
    assert result.task.parent_task_id == "parent" and result.task.batch_order == 4
    assert result.contract["phase"] == "planned" and result.contract["binding_resolved"] is False
    assert worker.module.patch_target is worker.contracts.patch_target
    assert result.contract["storage_revision"] == 1
    assert worker.contracts.seal_contract(deepcopy(result.contract)) == result.contract
    assert result.contract["planned"]["intent"]["selection"] == "dynamic_auto"
    assert result.contract["target"]["plan_keyframe_index"] == 5
    assert result.contract["target"]["images"] == {"legacy": worker.urls["old-legacy"], "plan": worker.urls["old-plan"]}
    for frames, original, index in ((result.frames, before.frames, worker.frame_index),
                                    (result.plan["keyframes"], before.plan["keyframes"], 4)):
        assert frames[index] == {**original[index], "image_task_id": task_id}
    assert result.shot.video_director_plan_revision == before.shot.video_director_plan_revision + 1
    assert not worker.events and not worker.clients and result.task.prompt_text is None
    worker.worker_factory.assert_called_once_with("keyframe_image")
    worker.enqueue.assert_called_once()
    result = run(worker)
    assert_completed(worker, result, "PRIMARY_STORYBOARD")
    assert result.contract["workflow"]["selection"] == ("explicit" if explicit else "default_keyframe")


@pytest.mark.parametrize("language", ["en", "zh"])
def test_shot1_kf5_missing_kf4_stays_primary_when_previous_becomes_ready_during_llm(worker, language):
    worker.language = language
    before = saved(worker)
    assert before.plan["keyframes"][3]["index"] == 4 and before.plan["keyframes"][3]["image_url"] is None
    assert before.frames[worker.frame_index - 1]["image_url"] is None

    def previous_ready():
        def change(view):
            view.frames[worker.frame_index - 1]["image_url"] = worker.urls["previous"]
            view.plan["keyframes"][3].update(image_url=worker.urls["previous"], image_task_id="previous-producer")
            view.shot.image_url = worker.urls["replacement"]
        edit(worker, change)

    worker.hooks["llm"] = previous_ready
    create(worker)
    result = run(worker)
    assert_completed(worker, result, "PRIMARY_STORYBOARD")
    contract = result.contract
    assert contract["resolved"]["url"] == worker.urls["primary"]
    assert contract["resolved"]["producer_task_id"] == "primary-producer"
    assert contract["fallback"] == {"from": "PREVIOUS_KEYFRAME", "to": "PRIMARY_STORYBOARD", "reason": "PREVIOUS_IMAGE_NOT_READY"}
    assert result.plan["keyframes"][3]["image_url"] == worker.urls["previous"]
    payload = worker.inputs[0]
    assert payload["previous_keyframe_state_text"]["index"] == 4
    assert payload["previous_keyframe_state_text"]["description"] == before.plan["keyframes"][3]["description"]
    assert "image_url" not in payload["previous_keyframe_state_text"]
    assert payload["reference_image_manifest"] == contract["manifest"]
    assert payload["reference_resolution"] == {"source_kind": "PRIMARY_STORYBOARD", "fallback": contract["fallback"], "reference_count": 1}
    assert payload["audit_context"] == {"task_id": result.task.id, "binding_hash": contract["frozen_binding_hash"]}
    prequeue = worker.prequeue[0]
    assert prequeue.contract["resolved"] == contract["resolved"]
    assert prequeue.contract["binding"] == contract["binding"]
    assert prequeue.contract["submit"]["state"] == "attempted" and prequeue.task.comfyui_prompt_id is None
    assert json.loads(prequeue.task.reference_images) == json.loads(result.task.reference_images)
    with worker.sessions() as db:
        assert db.get(worker.Task, "primary-producer").result_url == contract["resolved"]["url"]
        assert db.get(worker.Task, "previous-producer").result_url == worker.urls["previous"]
    assert worker.events == ["upload", "llm", "queue", "poll", "download"]


@pytest.mark.parametrize("language", ["en", "zh"])
@pytest.mark.parametrize("family", ["flux", "qwen"])
def test_shot2_kf5_binds_ready_kf4_through_real_workflow(worker, language, family):
    configure(worker, shot_index=2, previous=worker.urls["previous"], family=family)
    worker.language = language
    create(worker)
    result = run(worker)
    assert_completed(worker, result, "PREVIOUS_KEYFRAME")
    assert result.contract["workflow"]["family"] == ("flux2" if family == "flux" else "qwen")
    assert result.contract["resolved"]["source_keyframe_index"] == 4
    assert result.contract["resolved"]["producer_task_id"] == "previous-producer"
    assert result.contract["resolved"]["url"] == worker.urls["previous"]
    assert result.contract.get("fallback") is None
    assert worker.inputs[0]["reference_image_manifest"] == result.contract["manifest"]
    worker.llm.assert_awaited_once()


@pytest.mark.parametrize("language", ["en", "zh"])
def test_shot17_kf2_assets_are_text_context_not_extra_graph_images(worker, language):
    configure(worker, shot_index=17, target_kf=2)
    worker.language = language
    create(worker)
    result = run(worker)
    assert_completed(worker, result, "PRIMARY_STORYBOARD")
    payload = worker.inputs[0]
    assert payload["shot"]["index"] == 17 and payload["current_keyframe"]["index"] == 2
    assert payload["shot"]["characters"] == ["Ada", "Bea"] and payload["shot"]["props"] == ["sword"]
    assert payload["shot"]["scene"] == "courtyard" and payload["previous_keyframe_state_text"] is None
    assert len(payload["reference_image_manifest"]) == len(worker.uploads) == 1
    assert payload["reference_image_manifest"][0]["type"] == "PRIMARY_STORYBOARD"
    assert result.contract["validation"]["graph"]["image_source_nodes"] == ["76"]
    for name in ("characters", "scene", "prop"):
        assert worker.urls[name] not in json.dumps(payload)


@pytest.mark.parametrize("suffix", [
    "Use reference image 2 for Ada, reference image 3 for the courtyard, and reference image 4 for the sword.",
    "\u53c2\u8003\u56fe2\u63d0\u4f9b\u4eba\u7269\uff0c\u53c2\u8003\u56fe3\u63d0\u4f9b\u5ead\u9662\uff0c\u53c2\u8003\u56fe4\u63d0\u4f9b\u957f\u5251\u3002",
    "Use Picture 1/2/3/4 as the four supplied references.",
    "Use ref1/2/3/4 as the four supplied references.",
], ids=["expanded-en", "expanded-zh", "picture-slash", "ref-slash"])
def test_old_multireference_prose_never_queues_or_rewrites_old_draft(worker, suffix):
    configure(worker, shot_index=17, target_kf=2)
    raw = json.dumps({"final_prompt": PROSE["en"]["PRIMARY_STORYBOARD"] + " " + suffix})
    worker.response = {"success": True, "content": raw}
    create(worker)
    result = run(worker)
    assert_failed(worker, result, "UNBOUND_PICTURE_REFERENCE", llm=1)
    assert result.frames[0]["prompt_text"] == result.plan["keyframes"][1]["prompt_text"] == OLD_PROMPT
    assert result.task.prompt_text is None and result.task.workflow_json is None
    assert result.contract["prompt"]["raw_response"] == raw
    assert result.contract["binding_resolved"] is True
    call = result.plan["ai_calls"][-1]
    assert call["status"] == "error" and call["response"] == raw and call["final_prompt"] is None
    assert call["reference_images"] == json.loads(result.task.reference_images)


@pytest.mark.parametrize("mode,reference,source,selection", [
    ("auto_select", None, "PREVIOUS_KEYFRAME", "dynamic_auto"),
    ("auto_select", "primary", "PRIMARY_STORYBOARD", "fixed_auto"),
    ("auto_select", "previous", "PREVIOUS_KEYFRAME", "fixed_auto"),
    ("auto_select", "custom", "SAVED_REFERENCE", "fixed_auto"),
    ("custom", "custom", "CUSTOM_REFERENCE", "custom"),
    ("none", "custom", "NONE", "none"),
])
@pytest.mark.parametrize("language", ["en", "zh"])
def test_dynamic_fixed_custom_and_none_intents(worker, mode, reference, source, selection, language):
    configure(worker, previous=worker.urls["previous"], mode=mode, reference=worker.urls.get(reference))
    worker.language = language
    create(worker)
    result = run(worker)
    assert_completed(worker, result, source)
    assert result.contract["planned"]["intent"]["selection"] == selection
    assert len(worker.uploads) == (0 if source == "NONE" else 1)
    assert worker.inputs[0]["reference_resolution"]["reference_count"] == len(worker.uploads)


@pytest.mark.parametrize("previous,code", [
    ("not-ready", "PREVIOUS_IMAGE_NOT_READY"), ("missing", "REFERENCE_FILE_UNAVAILABLE"),
    ("corrupt", "INVALID_REFERENCE_IMAGE"), ("animated", "MULTIFRAME_REFERENCE_UNSUPPORTED"),
    ("stale", "PREVIOUS_STATE_STALE"),
])
def test_dynamic_previous_failure_falls_back_before_binding(worker, previous, code):
    url = None if previous == "not-ready" else worker.urls["previous"]
    configure(worker, previous=url)
    path = Path(worker.to_path(worker.urls["previous"]))
    if previous == "missing":
        path.unlink()
    elif previous == "corrupt":
        path.write_bytes(b"broken image")
    elif previous == "animated":
        make_image(worker, "previous", "green", animated=True)
    elif previous == "stale":
        edit(worker, lambda view: view.frames[worker.frame_index - 1].update(description="old unrendered state"))
    create(worker)
    result = run(worker)
    assert_completed(worker, result, "PRIMARY_STORYBOARD")
    assert result.contract["fallback"]["reason"] == code
    assert result.contract["resolution_attempts"][0]["reason"] == code
    assert len(worker.uploads) == 1 and worker.uploads[0]["path"] == worker.to_path(worker.urls["primary"])


@pytest.mark.parametrize("kind,code", [("missing", "REFERENCE_FILE_UNAVAILABLE"), ("corrupt", "INVALID_REFERENCE_IMAGE")])
@pytest.mark.parametrize("mode", ["dynamic", "custom", "fixed"])
def test_unavailable_primary_or_explicit_reference_fails_without_fallback(worker, kind, code, mode):
    name = "primary" if mode == "dynamic" else "custom"
    configure(worker, previous=None if mode == "dynamic" else worker.urls["previous"],
              mode="custom" if mode == "custom" else "auto_select",
              reference=None if mode == "dynamic" else worker.urls[name])
    path = Path(worker.to_path(worker.urls[name]))
    if kind == "missing":
        path.unlink()
    else:
        path.write_bytes(b"not an image")
    create(worker)
    result = run(worker)
    assert_failed(worker, result, code)
    assert not worker.uploads and result.contract["binding_resolved"] is False
    assert result.frames[worker.frame_index]["prompt_text"] == OLD_PROMPT
    if mode != "dynamic":
        assert result.contract.get("fallback") is None and len(result.contract["resolution_attempts"]) == 1


def test_custom_without_url_rejects_at_creation(worker):
    configure(worker, mode="custom")
    before = saved(worker)
    success, task_id, message = request(worker)
    assert not success and task_id is None and "CUSTOM_REFERENCE_MISSING" in message
    assert saved(worker).frames == before.frames and not worker.enqueued


def test_missing_primary_url_cannot_turn_dynamic_auto_into_none(worker):
    edit(worker, lambda view: setattr(view.shot, "image_url", None))
    create(worker)
    result = run(worker)
    assert_failed(worker, result, "REFERENCE_FILE_UNAVAILABLE")
    assert not worker.uploads and not worker.downloads
    assert result.contract["binding_resolved"] is False
    assert result.contract["planned"]["intent"]["selection"] == "dynamic_auto"


@pytest.mark.parametrize("receipt,code", [
    ({"success": False, "message": "upload unavailable"}, "REFERENCE_UPLOAD_FAILED"),
    ({"payload_sha256": "wrong"}, "UPLOAD_RECEIPT_MISMATCH"),
    ({"payload_size": -1}, "UPLOAD_RECEIPT_MISMATCH"),
    ({"filename": ""}, "UPLOAD_RECEIPT_MISMATCH"),
    ({"payload_sha256": None, "payload_size": None}, "UPLOAD_RECEIPT_MISMATCH"),
])
def test_opt_in_upload_requires_exact_byte_receipt_before_llm(worker, receipt, code):
    worker.receipt_changes = receipt
    create(worker)
    result = run(worker)
    assert_failed(worker, result, code)
    assert len(worker.uploads) == 1 and worker.events == ["upload"]
    assert result.contract["failure"]["stage"] == "resolved"
    assert result.contract["binding_resolved"] is False and result.contract["binding"] is None
    assert json.loads(result.task.reference_images) == []
    assert result.frames[worker.frame_index]["prompt_text"] == OLD_PROMPT
    assert result.plan["ai_calls"][-1]["reference_images"] == []


@pytest.mark.parametrize("change,code", [
    ("mapping", "invalid_mapping"), ("unknown-node", "unsupported_node"),
    ("second-image", "reference_count"), ("positive-erased", "prompt_binding"),
    ("qwen-none", "unsupported_none"),
])
def test_graph_failure_is_separate_preflight_before_any_upload(worker, change, code):
    if change == "qwen-none":
        configure(worker, family="qwen", mode="none")
    else:
        with worker.sessions() as db:
            workflow = db.get(worker.Workflow, "workflow")
            graph, mapping = json.loads(workflow.workflow_json), json.loads(workflow.node_mapping)
            if change == "mapping":
                mapping["character_image_node_id"] = "76"
            elif change == "unknown-node":
                graph["76"]["class_type"] = "UnknownImageSource"
            elif change == "second-image":
                graph["extra"] = {"class_type": "LoadImage", "inputs": {"image": "unbound.png"}}
            else:
                graph["108"]["inputs"]["positive"] = ["111", 0]
            workflow.workflow_json, workflow.node_mapping = json.dumps(graph), json.dumps(mapping)
            db.commit()
    create(worker)
    result = run(worker)
    assert_failed(worker, result, code)
    assert not worker.uploads and not worker.events and not worker.downloads
    assert result.contract["submit"]["state"] == "not_submitted"
    assert result.frames[worker.frame_index]["prompt_text"] == OLD_PROMPT


@pytest.mark.parametrize("stage", ["upload", "llm"])
def test_workflow_mapping_template_and_endpoint_are_frozen_across_await(worker, stage):
    with worker.sessions() as db:
        original_template = db.get(worker.Template, "template").template

    def change_configuration():
        with worker.sessions() as db:
            workflow = db.get(worker.Workflow, "workflow")
            workflow.workflow_json, workflow.node_mapping, workflow.name = "{}", '{"save_image_node_id":"wrong"}', "Changed workflow"
            template = db.get(worker.Template, "template")
            template.template, template.name = "Changed template must not leak", "Changed template"
            db.commit()
        worker.shared_client.base_url = "http://changed-comfy.test:9999"

    worker.hooks[stage] = change_configuration
    create(worker)
    result = run(worker)
    assert_completed(worker, result, "PRIMARY_STORYBOARD")
    assert result.contract["workflow"]["node_mapping"] == worker.mapping
    assert result.contract["workflow"]["template_graph_hash"] == worker.contracts.digest(worker.graph)
    assert result.task.workflow_name == result.contract["workflow"]["name"] == "Frozen workflow"
    assert result.contract["template"]["text"] == original_template
    assert worker.llm.await_args.kwargs["system_prompt"] == original_template
    assert result.contract["template"]["name"] == worker.llm.await_args.kwargs["prompt_template_name"] == "Frozen #09"
    assert result.contract["llm_config"] == {"provider": "isolated-provider", "model": "source-specific-prose", "max_tokens": 2500, "temperature": 0.3}
    worker.client_factory.assert_called_once_with(ENDPOINT)
    assert result.contract["endpoint"] == worker.clients[0].base_url == ENDPOINT
    assert result.contract["client_id"] == worker.clients[0].client_id
    assert worker.uploads[0]["endpoint"] == ENDPOINT
    assert worker.downloads[0]["url"] == ENDPOINT + "/view?filename=out.png&subfolder=&type=output"


@pytest.mark.parametrize("change", ["replace", "remove"])
def test_source_binding_uploads_exact_resolved_bytes_not_reopened_path(worker, change):
    path = Path(worker.to_path(worker.urls["primary"]))
    original = path.read_bytes()
    worker.hooks["upload"] = (lambda: make_image(worker, "primary", "red")) if change == "replace" else path.unlink
    create(worker)
    result = run(worker)
    assert_completed(worker, result, "PRIMARY_STORYBOARD")
    assert worker.uploads[0]["payload"] == original
    assert result.contract["resolved"]["sha256"] == hashlib.sha256(original).hexdigest()
    if change == "replace":
        assert path.read_bytes() != original
    else:
        assert not path.exists()


def test_valid_prior_task_reuses_prompt_with_new_attempt_upload_name_client_and_seed(worker):
    first_id = create(worker)
    first = run(worker)
    assert_completed(worker, first, "PRIMARY_STORYBOARD")
    worker.llm.reset_mock()
    second_id = create(worker, skip_llm_when_prompt_exists=True)
    second = run(worker)
    assert_completed(worker, second, "PRIMARY_STORYBOARD")
    assert first_id != second_id and first.contract["attempt_id"] != second.contract["attempt_id"]
    assert first.contract["client_id"] != second.contract["client_id"] and worker.clients[0] is not worker.clients[1]
    assert first.contract["binding"]["uploaded_filename"] != second.contract["binding"]["uploaded_filename"]
    assert worker.queued[0]["102"]["inputs"]["noise_seed"] != worker.queued[1]["102"]["inputs"]["noise_seed"]
    assert first.contract["workflow"]["contract_hash"] == second.contract["workflow"]["contract_hash"]
    assert first.contract["prompt"]["cache_fingerprint"] == second.contract["prompt"]["cache_fingerprint"]
    assert second.contract["prompt"]["origin"] == "reuse" and second.contract["prompt"]["reused_from_task_id"] == first_id
    assert second.contract["prompt"]["llm_invoked"] is False
    assert first.task.prompt_text == second.task.prompt_text and worker.uploads[0]["payload"] == worker.uploads[1]["payload"]
    worker.llm.assert_not_awaited()
    assert saved(worker, first_id).contract == first.contract


@pytest.mark.parametrize("damage", ["legacy", "wrong-version", "corrupt-json", "unbound", "text-hash", "prompt-validation", "graph-validation"])
def test_old_unproven_or_corrupt_task_metadata_never_authorizes_reuse(worker, damage):
    first_id = create(worker)
    first = run(worker)
    assert first.task.status == "completed"
    with worker.sessions() as db:
        task = db.get(worker.Task, first_id)
        contract = worker.contracts.read_contract(task)
        if damage == "wrong-version":
            contract["version"] = -1
        elif damage == "unbound":
            contract["binding_resolved"] = False
        elif damage == "text-hash":
            contract["prompt"]["text_hash"] = "tampered"
        elif damage == "prompt-validation":
            contract["prompt"]["validation"]["passed"] = False
        elif damage == "graph-validation":
            contract["validation"]["passed"] = False
        task.metadata_json = "{broken" if damage == "corrupt-json" else "{}" if damage == "legacy" else json.dumps({KEY: contract})
        db.commit()
    worker.llm.reset_mock()
    create(worker, skip_llm_when_prompt_exists=True)
    result = run(worker)
    code = "INVALID_SAVED_JSON" if damage == "corrupt-json" else "CACHE_BINDING_UNVERIFIED"
    assert_failed(worker, result, code, queued=1)
    assert result.frames[worker.frame_index]["prompt_text"] == first.task.prompt_text
    assert result.contract["prompt"]["llm_invoked"] is False
    assert result.task.comfyui_prompt_id is None


@pytest.mark.parametrize("damage", ["matching-flags-only", "binding", "prepared_workflow", "frozen_binding_hash"])
def test_cached_matching_flags_and_hashes_without_complete_proof_never_reuse(worker, damage):
    first_id = create(worker)
    first = run(worker)
    assert_completed(worker, first, "PRIMARY_STORYBOARD")
    with worker.sessions() as db:
        prior = db.get(worker.Task, first_id)
        record = worker.contracts.read_contract(prior)
        worker.contracts.validate_frozen_contract(record, prior, require_submitted=True)
        if damage == "matching-flags-only":
            record = {"version": record["version"], "attempt_id": record["attempt_id"],
                      "storage_revision": record["storage_revision"], "binding_resolved": True,
                      "prompt": {"cache_fingerprint": record["prompt"]["cache_fingerprint"],
                                 "text_hash": record["prompt"]["text_hash"], "validation": {"passed": True}},
                      "validation": {"passed": True}}
        else:
            record.pop(damage)
        worker.contracts.seal_contract(record, advance=True)
        prior.metadata_json = json.dumps({KEY: record, "outside_proof": "preserve"})
        with pytest.raises(worker.contracts.KeyframeReferenceError):
            worker.contracts.validate_frozen_contract(record, prior)
        db.commit()
    damaged = saved(worker, first_id)
    worker.llm.reset_mock()
    create(worker, skip_llm_when_prompt_exists=True)
    result = run(worker)
    assert_failed(worker, result, "CACHE_BINDING_UNVERIFIED", queued=1)
    assert record["binding_resolved"] is record["validation"]["passed"] is record["prompt"]["validation"]["passed"] is True
    assert record["prompt"]["cache_fingerprint"] == result.contract["prompt"]["cache_fingerprint"]
    assert record["prompt"]["text_hash"] == worker.contracts.digest(first.task.prompt_text)
    assert result.frames[worker.frame_index]["prompt_text"] == result.plan["keyframes"][4]["prompt_text"] == first.task.prompt_text
    assert result.frames[worker.frame_index]["image_url"] == first.task.result_url
    assert result.task.prompt_text is result.task.comfyui_prompt_id is result.task.workflow_json is None
    assert result.contract["prompt"]["llm_invoked"] is False
    assert "reused_from_task_id" not in result.contract["prompt"]
    assert saved(worker, first_id).task.metadata_json == damaged.task.metadata_json


@pytest.mark.parametrize("source_change", ["url", "kind"])
def test_other_tasks_wrong_source_contract_cannot_be_laundered_with_current_fingerprint(worker, source_change):
    first_id = create(worker)
    first = run(worker)
    assert_completed(worker, first, "PRIMARY_STORYBOARD")
    if source_change == "url":
        edit(worker, lambda view: setattr(view.shot, "image_url", worker.urls["replacement"]))
    else:
        edit(worker, lambda view: (view.frames[2].update(image_url=worker.urls["previous"]),
                                   view.plan["keyframes"][3].update(image_url=worker.urls["previous"])))
    other_id = create(worker)
    other = run(worker)
    assert_completed(worker, other, "PRIMARY_STORYBOARD" if source_change == "url" else "PREVIOUS_KEYFRAME")
    assert other.contract["prompt"]["cache_fingerprint"] != first.contract["prompt"]["cache_fingerprint"]
    with worker.sessions() as db:
        prior = db.get(worker.Task, first_id)
        copied = deepcopy(other.contract)
        for field in ("comfyui_prompt_id", "prompt_text", "reference_images", "workflow_id", "workflow_name", "workflow_json"):
            setattr(prior, field, getattr(other.task, field))
        prior.metadata_json = json.dumps({KEY: copied})
        worker.contracts.validate_frozen_contract(copied, prior, require_submitted=True)
        copied["version"] = worker.contracts.CONTRACT_VERSION
        copied["prompt"]["cache_fingerprint"] = first.contract["prompt"]["cache_fingerprint"]
        worker.contracts.seal_contract(copied, advance=True)
        prior.metadata_json = json.dumps({KEY: copied})
        with pytest.raises(worker.contracts.KeyframeReferenceError, match="CACHE_PROOF_INVALID"):
            worker.contracts.validate_frozen_contract(copied, prior, require_submitted=True)
        db.commit()

    def restore_reference(view):
        view.shot.image_url = worker.urls["primary"]
        view.frames[2]["image_url"] = view.plan["keyframes"][3]["image_url"] = None

    edit(worker, restore_reference)
    current_text = saved(worker).frames[worker.frame_index]["prompt_text"]
    worker.llm.reset_mock()
    create(worker, skip_llm_when_prompt_exists=True)
    result = run(worker)
    assert_failed(worker, result, "CACHE_BINDING_UNVERIFIED", queued=2)
    assert result.contract["prompt"]["cache_fingerprint"] == copied["prompt"]["cache_fingerprint"]
    assert copied["prompt"]["text_hash"] == worker.contracts.digest(current_text)
    assert result.frames[worker.frame_index]["prompt_text"] == result.plan["keyframes"][4]["prompt_text"] == current_text
    assert result.contract["resolved"]["url"] == worker.urls["primary"] != copied["resolved"]["url"]
    assert result.task.prompt_text is result.task.comfyui_prompt_id is None
    assert saved(worker, first_id).contract == copied and saved(worker, other_id).contract == other.contract


@pytest.mark.parametrize("candidate", ["", " \n\t", None, False, {"prompt": "manual"}, "New manual direction", PROSE["zh"]["PRIMARY_STORYBOARD"]])
def test_changed_current_manual_text_cannot_fall_back_to_older_valid_task(worker, candidate):
    first_id = create(worker)
    first = run(worker)
    assert first.task.status == "completed"
    edit(worker, lambda view: (view.frames[worker.frame_index].update(prompt_text=candidate),
                               view.plan["keyframes"][4].update(prompt_text=candidate)))
    worker.llm.reset_mock()
    create(worker, skip_llm_when_prompt_exists=True)
    result = run(worker)
    code = "CACHE_BINDING_UNVERIFIED" if isinstance(candidate, str) and candidate.strip() else "UNVERIFIED_CURRENT_PROMPT"
    assert_failed(worker, result, code, queued=1)
    assert result.frames[worker.frame_index]["prompt_text"] == result.plan["keyframes"][4]["prompt_text"] == candidate
    assert saved(worker, first_id).contract == first.contract


@pytest.mark.parametrize("representation", ["legacy", "plan"])
def test_disagreeing_current_drafts_cannot_reuse_the_older_matching_projection(worker, representation):
    first_id = create(worker)
    first = run(worker)
    assert first.task.status == "completed"

    def change(view):
        item = view.frames[worker.frame_index] if representation == "legacy" else view.plan["keyframes"][4]
        item["prompt_text"] = PROSE["zh"]["PRIMARY_STORYBOARD"]

    edit(worker, change)
    before = saved(worker)
    worker.llm.reset_mock()
    create(worker, skip_llm_when_prompt_exists=True)
    result = run(worker)
    assert_failed(worker, result, "UNVERIFIED_CURRENT_PROMPT", queued=1)
    assert result.frames[worker.frame_index]["prompt_text"] == before.frames[worker.frame_index]["prompt_text"]
    assert result.plan["keyframes"][4]["prompt_text"] == before.plan["keyframes"][4]["prompt_text"]
    assert saved(worker, first_id).contract == first.contract


@pytest.mark.parametrize("change", ["url", "bytes", "source-kind"])
def test_source_change_is_a_cache_miss_without_implicit_llm(worker, change):
    first_id = create(worker)
    first = run(worker)
    assert first.task.status == "completed"
    if change == "url":
        identical_url = make_image(worker, "same-bytes-new-url", "blue")
        assert Path(worker.to_path(identical_url)).read_bytes() == worker.uploads[0]["payload"]
        edit(worker, lambda view: setattr(view.shot, "image_url", identical_url))
    elif change == "bytes":
        make_image(worker, "primary", "red")
    else:
        edit(worker, lambda view: (view.frames[worker.frame_index - 1].update(image_url=worker.urls["previous"]),
                                   view.plan["keyframes"][3].update(image_url=worker.urls["previous"])))
    worker.llm.reset_mock()
    create(worker, skip_llm_when_prompt_exists=True)
    result = run(worker)
    assert_failed(worker, result, "CACHE_BINDING_UNVERIFIED", queued=1)
    assert result.contract["prompt"]["cache_fingerprint"] != first.contract["prompt"]["cache_fingerprint"]
    assert result.frames[worker.frame_index]["prompt_text"] == first.task.prompt_text


@pytest.mark.parametrize("skip,prior", [(True, False), (True, True), (False, False)])
def test_parent_batch_does_not_override_explicit_skip_policy(worker, skip, prior):
    if prior:
        create(worker)
        assert run(worker).task.status == "completed"
    worker.llm.reset_mock()
    create(worker, skip_llm_when_prompt_exists=skip, parent_task_id="parent", batch_order=3)
    result = run(worker)
    assert result.contract["planned"]["skip_llm_when_prompt_exists"] is skip
    if skip and not prior:
        assert_failed(worker, result, "CACHE_BINDING_UNVERIFIED")
        assert result.frames[worker.frame_index]["prompt_text"] == OLD_PROMPT
    else:
        assert_completed(worker, result, "PRIMARY_STORYBOARD")
    assert worker.llm.await_count == (0 if skip else 1)


@pytest.mark.parametrize("running", [False, True])
def test_same_inflight_intent_returns_existing_task_without_reclaiming(worker, running):
    task_id = create(worker)

    def duplicate():
        before = saved(worker)
        result = request(worker)
        assert result[0] and result[1] == task_id
        after = saved(worker)
        assert after.contract == before.contract and after.frames == before.frames and after.plan == before.plan
        assert after.task.status == ("running" if running else "pending")
        assert len(worker.enqueued) == 1

    if running:
        # request is async; call it directly in this await boundary rather than nesting asyncio.run.
        async def complete(**kwargs):
            before = saved(worker)
            with worker.sessions() as db:
                success, returned_id, _ = await worker.service.generate_keyframe_image(db, "shot", worker.frame_index)
            assert success and returned_id == task_id
            assert saved(worker).contract == before.contract and len(worker.enqueued) == 1
            with worker.sessions() as db:
                success, returned_id, _ = await worker.service.generate_keyframe_image(
                    db, "shot", worker.frame_index, skip_llm_when_prompt_exists=True,
                )
            assert not success and returned_id is None
            assert saved(worker).contract == before.contract and len(worker.enqueued) == 1
            return {"success": True, "content": PROSE["en"]["PRIMARY_STORYBOARD"]}
        worker.llm.side_effect = complete
        assert_completed(worker, run(worker), "PRIMARY_STORYBOARD")
    else:
        duplicate()


@pytest.mark.parametrize("change", ["skip", "workflow", "parent", "batch", "reference", "target", "legacy-task"])
def test_conflicting_inflight_request_does_not_overwrite_claim_or_evidence(worker, change):
    task_id = create(worker)
    options = {}
    if change in {"skip", "workflow", "parent", "batch"}:
        key, value = {"skip": ("skip_llm_when_prompt_exists", True), "workflow": ("workflow_id", "workflow"),
                      "parent": ("parent_task_id", "parent"), "batch": ("batch_order", 2)}[change]
        options[key] = value
    elif change == "reference":
        edit(worker, lambda view: view.frames[worker.frame_index].update(reference_mode="custom", reference_image_url=worker.urls["custom"]))
    elif change == "target":
        edit(worker, lambda view: view.plan["keyframes"][4].update(description="Changed current direction"))
    else:
        edit(worker, lambda view: setattr(view.task, "metadata_json", "{}"))
    before = saved(worker)
    success, returned_id, _ = request(worker, **options)
    assert not success and returned_id is None and worker.task_id == task_id
    after = saved(worker)
    assert after.task.metadata_json == before.task.metadata_json
    assert after.frames == before.frames and after.plan == before.plan and len(worker.enqueued) == 1
    assert not worker.events


@pytest.mark.parametrize("stage", ["before-start", "upload", "llm", "queue", "poll", "download"])
def test_cancelled_task_is_never_revived_at_any_await_boundary(worker, stage):
    create(worker)
    stopped = []
    finished = datetime(2026, 1, 1)

    def cancel():
        edit(worker, lambda view: (setattr(view.task, "status", "cancelled"),
                                   setattr(view.task, "error_message", "User cancelled"),
                                   setattr(view.task, "completed_at", finished)))
        stopped.append(saved(worker))

    if stage == "before-start":
        cancel()
    else:
        worker.hooks[stage] = cancel
    result = run(worker)
    assert result.task.status == "cancelled" and result.task.error_message == "User cancelled"
    assert result.task.completed_at == finished
    assert result.frames == stopped[0].frames and result.plan == stopped[0].plan
    assert worker.llm.await_count == int(stage in {"llm", "queue", "poll", "download"})
    assert len(worker.queued) == int(stage in {"queue", "poll", "download"})
    assert len(worker.downloads) == int(stage == "download")
    if stage == "before-start":
        assert result.contract["phase"] == "planned" and not worker.clients
    else:
        assert result.contract["phase"] == "failed" and result.contract["failure"]["code"] == "TASK_NOT_ACTIVE"
    if stage == "download":
        assert result.contract["result"]["attachment"] == "detached" and result.task.result_url
    if stage in {"llm", "queue", "poll", "download"}:
        assert result.contract["prompt"]["raw_response"] == PROSE["en"]["PRIMARY_STORYBOARD"]


@pytest.mark.parametrize("stage", ["upload", "llm", "queue", "download"])
def test_coroutine_cancellation_persists_failure_and_propagates_without_retry(worker, stage):
    def interrupt():
        raise asyncio.CancelledError()

    worker.hooks[stage] = interrupt
    create(worker)
    with pytest.raises(asyncio.CancelledError):
        run(worker)
    result = saved(worker)
    assert_failed(worker, result, "WORKER_INTERRUPTED", queued=int(stage in {"queue", "download"}), llm=int(stage != "upload"))
    before = len(worker.queued)
    run(worker)
    assert len(worker.queued) == before and result.contract["binding_resolved"] is (stage != "upload")


@pytest.mark.parametrize("stage", ["before-start", "llm", "download"])
@pytest.mark.parametrize("parent_status", ["cancelled", "failed", "completed", "removed"])
def test_parent_cancellation_vetoes_child_without_reviving_parent(worker, stage, parent_status):
    create(worker, parent_task_id="parent")

    def stop_parent():
        with worker.sessions() as db:
            parent = db.get(worker.Task, "parent")
            if parent_status == "removed":
                db.delete(parent)
            else:
                parent.status = parent_status
            db.commit()

    if stage == "before-start":
        stop_parent()
    else:
        worker.hooks[stage] = stop_parent
    result = run(worker)
    assert_failed(worker, result, "PARENT_NOT_ACTIVE", queued=int(stage == "download"), llm=int(stage != "before-start"))
    assert result.frames[worker.frame_index]["image_url"] == worker.urls["old-legacy"]
    with worker.sessions() as db:
        parent = db.get(worker.Task, "parent")
        assert parent is None if parent_status == "removed" else parent.status == parent_status
    if stage == "download":
        assert result.contract["result"]["attachment"] == "detached"


@pytest.mark.parametrize("stage", ["upload", "llm", "queue", "download"])
@pytest.mark.parametrize("change,code", [
    ("columns", "TASK_SUBMISSION_CHANGED"), ("resealed-metadata", "CONTRACT_STALE"),
    ("unsealed-metadata", "CONTRACT_SEAL_INVALID"),
])
def test_replaced_current_cid_workflow_and_failure_receive_observation_not_old_facts(worker, stage, change, code):
    changed, original = [], []

    def replace():
        original.append(saved(worker))
        c1 = "queued-1" if stage == "download" else None
        assert original[0].task.comfyui_prompt_id == c1
        replacement_graph = deepcopy(worker.queued[-1] if worker.queued else worker.graph)
        replacement_graph["110"]["inputs"]["text"] = PROSE["zh"]["PRIMARY_STORYBOARD"]
        replacement_graph["102"]["inputs"]["noise_seed"] = 9001

        def mutate(view):
            view.task.comfyui_prompt_id = "replacement-C2"
            view.task.workflow_json = json.dumps(replacement_graph, indent=2)
            view.task.workflow_id, view.task.workflow_name = "replacement-workflow", "C2 workflow"
            view.task.status, view.task.error_message = "failed", "Concurrent C2 failure"
            view.task.current_step, view.task.progress = "C2 terminal state", 61
            view.task.completed_at = datetime(2026, 1, 1)
            view.task.result_url = worker.urls["replacement"]
            metadata = json.loads(view.task.metadata_json)
            metadata["other_namespace"] = {"note": "C2 evidence"}
            metadata[worker.contracts.OBSERVATIONS_KEY] = [{"note": "earlier observation"}]
            if change != "columns":
                record = metadata[KEY]
                record.update(phase="failed", failure={"stage": "replacement", "code": "C2_FAILURE", "message": "Newer failure"})
                if change == "resealed-metadata":
                    worker.contracts.seal_contract(record, advance=True)
            view.task.metadata_json = json.dumps(metadata)

        edit(worker, mutate)
        changed.append(saved(worker))

    worker.hooks[stage] = replace
    create(worker)
    result = run(worker)
    artifact = "/api/files/result-1.png" if stage == "download" else None
    expected_cid = "queued-1" if stage in {"queue", "download"} else None
    assert_observation_only(worker, changed[0], result, original[0].contract, code, prompt_id=expected_cid, artifact_url=artifact)
    assert result.task.comfyui_prompt_id == "replacement-C2" and result.task.error_message == "Concurrent C2 failure"
    assert result.contract["attempt_id"] == original[0].contract["attempt_id"]
    assert worker.llm.await_count == int(stage != "upload")
    assert len(worker.queued) == int(stage in {"queue", "download"}) and len(worker.downloads) == int(stage == "download")
    assert run(worker).task.metadata_json == result.task.metadata_json


@pytest.mark.parametrize("stage", ["upload", "llm", "download"])
@pytest.mark.parametrize("field", ["prompt_text", "reference_images"])
def test_current_task_prompt_or_reference_projection_tamper_blocks_without_repair(worker, stage, field):
    changed, original = [], []

    def tamper():
        original.append(saved(worker))
        value = "A newer Task-only prompt" if field == "prompt_text" else json.dumps([
            {"label": "New Task-only reference", "url": worker.urls["custom"]},
        ])
        edit(worker, lambda view: setattr(view.task, field, value))
        changed.append(saved(worker))

    worker.hooks[stage] = tamper
    create(worker)
    result = run(worker)
    assert_observation_only(worker, changed[0], result, original[0].contract, "TASK_PROJECTION_CHANGED",
                            prompt_id="queued-1" if stage == "download" else None,
                            artifact_url="/api/files/result-1.png" if stage == "download" else None)
    assert result.task.status != "completed"
    assert len(worker.queued) == int(stage == "download") and len(worker.downloads) == int(stage == "download")
    assert worker.llm.await_count == int(stage != "upload")
    observations = json.loads(result.task.metadata_json)[worker.contracts.OBSERVATIONS_KEY]
    assert field in observations[-1]["reason"]


@pytest.mark.parametrize("stage", ["upload", "llm"])
@pytest.mark.parametrize("change,code", [
    ("legacy-description", "TARGET_CHANGED"), ("plan-description", "TARGET_CHANGED"),
    ("previous-description", "TARGET_CHANGED"), ("reorder", "TARGET_CHANGED"),
    ("reference", "TARGET_CHANGED"), ("legacy-image", "TARGET_CHANGED"), ("plan-image", "TARGET_CHANGED"),
    ("legacy-owner", "TARGET_OWNER_CHANGED"), ("plan-owner", "TARGET_OWNER_CHANGED"),
    ("legacy-draft", "PROMPT_EDITED"), ("plan-draft", "PROMPT_EDITED"), ("removed-draft", "PROMPT_EDITED"),
    ("shot-characters", "TARGET_CHANGED"), ("plan-time", "TARGET_CHANGED"),
])
def test_target_edits_reorders_and_drafts_during_await_preserve_user_state(worker, stage, change, code):
    changed = []

    def modify():
        def mutate(view):
            frame, planned = view.frames[worker.frame_index], view.plan["keyframes"][4]
            if change == "reorder":
                view.frames[1], view.frames[worker.frame_index] = view.frames[worker.frame_index], view.frames[1]
            elif change == "reference":
                frame.update(reference_mode="custom", reference_image_url=worker.urls["custom"])
            elif change == "previous-description":
                view.plan["keyframes"][3]["description"] = "new previous planning text"
            elif change == "removed-draft":
                planned.pop("prompt_text")
            elif change == "shot-characters":
                view.shot.characters = '["Bea", "Ada"]'
            else:
                representation, field = change.split("-")
                item = frame if representation == "legacy" else planned
                item[{"description": "description", "image": "image_url", "owner": "image_task_id",
                      "draft": "prompt_text", "time": "time_seconds"}[field]] = 9 if field == "time" else "User edit"
        edit(worker, mutate)
        changed.append(saved(worker))

    worker.hooks[stage] = modify
    create(worker)
    result = run(worker)
    assert_failed(worker, result, code, llm=int(stage == "llm"))
    assert result.frames == changed[0].frames and result.plan == changed[0].plan
    assert result.shot.characters == changed[0].shot.characters
    if stage == "llm":
        assert result.contract["binding_resolved"] is True
        assert result.contract["prompt"]["raw_response"] == PROSE["en"]["PRIMARY_STORYBOARD"]
        assert json.loads(result.task.reference_images) == worker.contracts.reference_images(result.contract)


def test_success_uses_canonical_plan_description_and_updates_legacy_only_on_publish(worker):
    configure(worker, legacy_description="Old legacy description that was never rendered")
    create(worker)
    result = run(worker)
    assert_completed(worker, result, "PRIMARY_STORYBOARD")
    canonical = result.plan["keyframes"][4]
    assert worker.inputs[0]["current_keyframe"]["description"] == canonical["description"]
    assert result.contract["target"]["legacy_state"]["description"] == "Old legacy description that was never rendered"
    assert worker.prequeue[0].frames[worker.frame_index]["description"] == "Old legacy description that was never rendered"
    assert {key: result.frames[worker.frame_index][key] for key in ("description", "role", "time_seconds")} == {
        key: canonical[key] for key in ("description", "role", "time_seconds")
    }


@pytest.mark.parametrize("representation", ["legacy", "plan"])
def test_manual_image_change_after_queue_detaches_result_and_fails_task(worker, representation):
    changed = []

    def manual_image():
        assert len(worker.queued) == 1
        def mutate(view):
            item = view.frames[worker.frame_index] if representation == "legacy" else view.plan["keyframes"][4]
            item["image_url"] = worker.urls["replacement"]
        edit(worker, mutate)
        changed.append(saved(worker))

    worker.hooks["download"] = manual_image
    create(worker)
    result = run(worker)
    assert_failed(worker, result, "TARGET_CHANGED", queued=1, llm=1)
    assert result.frames == changed[0].frames and result.plan == changed[0].plan
    assert result.task.result_url == "/api/files/result-1.png"
    assert result.contract["result"] == {"url": result.task.result_url, "attachment": "detached", "reason": "TARGET_CHANGED"}
    assert result.contract["submit"]["state"] == "submitted"


def test_unrelated_json_progress_other_frames_and_logs_survive_every_boundary(worker):
    def update(stage):
        def mutate(view):
            view.plan.setdefault("parallel", {})[stage] = "keep"
            view.plan["window_plans"][0]["user_note"] = stage
            view.plan["keyframes"][-1]["description"] = "Unrelated last frame edit"
            view.frames[-1]["description"] = "Unrelated legacy last frame edit"
            view.plan["ai_calls"].append({"step": "08", "note": stage})
            metadata = json.loads(view.task.metadata_json)
            metadata.setdefault("other_namespace", {})[stage] = "keep"
            view.task.metadata_json = json.dumps(metadata)
            view.task.progress = 42
        edit(worker, mutate)

    for stage in ("upload", "llm", "queue", "download"):
        worker.hooks[stage] = lambda stage=stage: update(stage)
    create(worker)
    result = run(worker)
    assert result.task.status == "completed", result.task.error_message
    expected = {stage: "keep" for stage in ("upload", "llm", "queue", "download")}
    assert result.plan["parallel"] == json.loads(result.task.metadata_json)["other_namespace"] == expected
    assert result.plan["keyframes"][-1]["description"] == "Unrelated last frame edit"
    assert result.frames[-1]["description"] == "Unrelated legacy last frame edit"
    assert result.plan["window_plans"][0]["user_note"] == "download"
    assert [call["note"] for call in result.plan["ai_calls"] if call["step"] == "08"] == list(expected)
    assert len([call for call in result.plan["ai_calls"] if call["step"] == "09"]) == 1


@pytest.mark.parametrize("change,code,attempts", [
    ("shot-description", "TARGET_CHANGED", 1),
    ("legacy-draft", "PROMPT_EDITED", 1),
    ("plan-draft", "PROMPT_EDITED", 1),
    ("reference-intent", "TARGET_CHANGED", 1),
    ("unrelated-plan", "TARGET_WRITE_CONFLICT", 3),
])
def test_prompt_publication_cas_failure_keeps_unpublished_candidate_out_of_task_projections(worker, monkeypatch, change, code, attempts):
    candidate = PROSE["en"]["PRIMARY_STORYBOARD"]
    raw = " \n" + json.dumps({"final_prompt": candidate}, indent=2) + "\n"
    worker.response = {"success": True, "content": raw}
    original_update = Query.update
    before, interleaved, shot_counts, task_prompt_writes = [], [], [], []
    manual = "New user draft committed after the LLM completed."

    def race(query, values, *args, **kwargs):
        model = query.column_descriptions[0]["entity"]
        if model is worker.Task and values.get("prompt_text") == candidate:
            task_prompt_writes.append(deepcopy(values))
        if model is worker.Shot:
            proposed = json.loads(values["keyframes"])[worker.frame_index]
            if proposed.get("prompt_text") == candidate:
                # This SQL runs after the LLM/target checks, not in an upload/LLM hook.
                assert worker.events == ["upload", "llm"]
                assert proposed["image_url"] == worker.urls["old-legacy"]
                staged_call = json.loads(values["video_director_plan"])["ai_calls"][-1]
                assert staged_call["response"] == raw and staged_call["final_prompt"] == candidate
                assert staged_call["status"] == "success"
                before.append(saved(worker))
                assert before[-1].task.status == "running" and before[-1].task.prompt_text is None
                assert len(interleaved) < attempts
                number = len(interleaved) + 1

                def mutate(view):
                    if change == "shot-description":
                        view.shot.description = "User changed the Shot context immediately before prompt publication."
                    elif change in {"legacy-draft", "plan-draft"}:
                        item = view.frames[worker.frame_index] if change == "legacy-draft" else view.plan["keyframes"][4]
                        item["prompt_text"] = manual
                    elif change == "reference-intent":
                        view.frames[worker.frame_index].update(reference_mode="custom", reference_image_url=worker.urls["custom"])
                    else:
                        view.plan.setdefault("prompt_cas_edits", []).append(number)
                        view.plan["window_plans"][0]["user_note"] = f"Parallel window edit {number}"
                        view.plan["keyframes"][-1]["description"] = f"Unrelated final frame edit {number}"
                        view.plan["ai_calls"].append({"step": "08", "note": f"Parallel log {number}"})

                edit(worker, mutate)
                interleaved.append(saved(worker))
                if change == "shot-description":
                    assert interleaved[-1].shot.keyframes == before[-1].shot.keyframes
                    assert interleaved[-1].shot.video_director_plan == before[-1].shot.video_director_plan
                    assert interleaved[-1].shot.video_director_plan_revision == before[-1].shot.video_director_plan_revision
                affected = original_update(query, values, *args, **kwargs)
                shot_counts.append(affected)
                return affected
        return original_update(query, values, *args, **kwargs)

    monkeypatch.setattr(Query, "update", race)
    create(worker)
    result = run(worker)
    assert len(interleaved) == attempts and shot_counts == [0] * attempts
    assert not task_prompt_writes
    assert_failed(worker, result, code, llm=1)
    assert result.contract["failure"]["stage"] == "prompt_publish"
    assert result.contract["failure"]["message"] == result.task.error_message
    assert result.task.prompt_text is result.task.comfyui_prompt_id is result.task.workflow_json is None
    assert result.task.result_url is None
    assert result.contract["submit"] == {"state": "not_submitted"}
    assert result.contract["prompt"]["raw_response"] == raw
    assert result.contract["prompt"]["llm_invoked"] is True
    assert result.contract["prompt"]["unpublished_candidate"] == {
        "text": candidate, "text_hash": worker.contracts.digest(candidate),
        "validation": worker.contracts.validate_reference_prompt(candidate, "PRIMARY_STORYBOARD"),
    }
    assert not {"text", "text_hash"} & result.contract["prompt"].keys()
    assert "prepared_workflow" not in result.contract and "validation" not in result.contract
    assert worker.contracts.seal_contract(deepcopy(result.contract)) == result.contract
    assert worker.contracts.OBSERVATIONS_KEY not in json.loads(result.task.metadata_json)
    for field in ("draft", "resolved", "binding", "manifest", "frozen_binding_hash"):
        assert result.contract[field] == before[0].contract[field]
    assert result.task.reference_images == before[0].task.reference_images
    assert result.frames == interleaved[-1].frames
    assert result.shot.description == interleaved[-1].shot.description
    expected_prompts = [manual if change == "legacy-draft" else OLD_PROMPT, manual if change == "plan-draft" else OLD_PROMPT]
    assert [result.frames[worker.frame_index]["prompt_text"], result.plan["keyframes"][4]["prompt_text"]] == expected_prompts
    if change == "unrelated-plan":
        call = result.plan["ai_calls"][-1]
        assert call["status"] == "error" and code in call["error_message"]
        assert call["response"] == raw and call["final_prompt"] is None
        assert call["reference_images"] == json.loads(result.task.reference_images)
        assert call["parsed_result"]["phase"] == "prompt_publish"
        assert result.plan == {**interleaved[-1].plan, "ai_calls": [*interleaved[-1].plan["ai_calls"], call]}
        assert result.plan["prompt_cas_edits"] == [1, 2, 3]
    else:
        assert result.plan == interleaved[-1].plan
    assert worker.events == ["upload", "llm"] and len(worker.uploads) == 1
    worker.clients[0].queue_prompt.assert_not_awaited()
    worker.clients[0].get_prompt_state.assert_not_awaited()
    worker.storage.download_image.assert_not_awaited()
    assert run(worker).contract == result.contract and worker.llm.await_count == 1


@pytest.mark.parametrize("change", ["unrelated-plan", "unrelated-metadata", "owner", "image"])
def test_real_publication_cas_rechecks_edits_between_read_and_sql(worker, monkeypatch, change):
    original_update = Query.update
    interleaved, counts = [], []

    def race(query, values, *args, **kwargs):
        model = query.column_descriptions[0]["entity"]
        publishing = model is worker.Shot and json.loads(values["keyframes"])[worker.frame_index]["image_url"] == "/api/files/result-1.png"
        if publishing and not interleaved:
            def mutate(view):
                if change == "unrelated-plan":
                    view.plan["during_cas"] = "preserve"
                elif change == "unrelated-metadata":
                    view.task.metadata_json = json.dumps({**json.loads(view.task.metadata_json), "during_cas": "preserve"})
                else:
                    view.frames[worker.frame_index]["image_task_id" if change == "owner" else "image_url"] = "Manual CAS edit"
            edit(worker, mutate)
            interleaved.append(saved(worker))
        result = original_update(query, values, *args, **kwargs)
        if publishing:
            counts.append(result)
        return result

    monkeypatch.setattr(Query, "update", race)
    create(worker)
    result = run(worker)
    assert len(interleaved) == 1
    if change.startswith("unrelated"):
        assert_completed(worker, result, "PRIMARY_STORYBOARD")
        if change == "unrelated-plan":
            assert result.plan["during_cas"] == "preserve" and counts == [0, 1]
        else:
            assert json.loads(result.task.metadata_json)["during_cas"] == "preserve" and counts == [1, 1]
    else:
        assert_failed(worker, result, "TARGET_OWNER_CHANGED" if change == "owner" else "TARGET_CHANGED", queued=1, llm=1)
        assert result.frames == interleaved[0].frames and result.plan == interleaved[0].plan
        assert counts == [0] and result.contract["result"]["attachment"] == "detached"


@pytest.mark.parametrize("failures", [1, 3])
def test_failed_task_publication_cas_rolls_back_shot_before_retry(worker, monkeypatch, failures):
    original_update = Query.update
    conflicts = []

    def conflict(query, values, *args, **kwargs):
        if query.column_descriptions[0]["entity"] is worker.Task and values.get("status") == "completed" and len(conflicts) < failures:
            # Inspect with the same transaction: reading through another StaticPool Session here would roll it back.
            shot = query.session.query(worker.Shot).populate_existing().filter_by(id="shot").one()
            assert json.loads(shot.keyframes)[worker.frame_index]["image_url"] == "/api/files/result-1.png"
            conflicts.append(True)
            return 0
        return original_update(query, values, *args, **kwargs)

    monkeypatch.setattr(Query, "update", conflict)
    create(worker)
    result = run(worker)
    assert len(conflicts) == failures
    if failures == 1:
        assert_completed(worker, result, "PRIMARY_STORYBOARD")
    else:
        assert_failed(worker, result, "TARGET_WRITE_CONFLICT", queued=1, llm=1)
        assert result.frames[worker.frame_index]["image_url"] == worker.urls["old-legacy"]
        assert result.plan["keyframes"][4]["image_url"] == worker.urls["old-plan"]
        assert result.contract["result"]["attachment"] == "detached"


@pytest.mark.parametrize("change,code", [
    ("preview-only", "RESULT_NODE_UNCERTAIN"), ("two-images", "RESULT_NODE_UNCERTAIN"),
    ("prompt-id", "HISTORY_SUBMISSION_MISMATCH"), ("graph", "HISTORY_SUBMISSION_MISMATCH"),
    ("not-completed", "RESULT_NOT_COMPLETED"), ("temp", "INVALID_OUTPUT_LOCATOR"),
])
def test_polling_rejects_unproven_or_ambiguous_save_output_without_preview_fallback(worker, change, code):
    def history(history):
        outputs = history["outputs"]
        outputs["preview"] = {"images": [{"filename": "wrong-preview.png", "subfolder": "", "type": "output"}]}
        if change == "preview-only":
            outputs.pop("9")
        elif change == "two-images":
            outputs["9"]["images"] *= 2
        elif change == "prompt-id":
            history["prompt"][1] = "other-task-prompt"
        elif change == "graph":
            history["prompt"][2]["110"]["inputs"]["text"] += "changed"
        elif change == "not-completed":
            history["status"] = {"completed": False, "status_str": "running"}
        else:
            outputs["9"]["images"][0]["type"] = "temp"

    worker.history_hook = history
    create(worker)
    result = run(worker)
    assert_failed(worker, result, code, queued=1, llm=1)
    assert not worker.downloads
    assert result.contract["prepared_workflow"] == json.loads(result.task.workflow_json) == worker.queued[0]
    assert result.contract["submit"]["state"] == "submitted" and result.task.comfyui_prompt_id == "queued-1"
    assert result.contract["prompt"]["raw_response"] == PROSE["en"]["PRIMARY_STORYBOARD"]
    assert result.contract["resolved"]["url"] == worker.urls["primary"]
    assert result.frames[worker.frame_index]["image_url"] == worker.urls["old-legacy"]
    worker.clients[0].get_prompt_state.assert_awaited_once_with("queued-1")


def test_only_get_prompt_state_polls_and_only_mapped_save_image_downloads(worker, monkeypatch):
    worker.poll_states = [{"state": "running"}, {"state": "unknown"}]
    sleep = AsyncMock()
    monkeypatch.setattr(worker.module, "asyncio", SimpleNamespace(get_running_loop=asyncio.get_running_loop,
                                                                 sleep=sleep, CancelledError=asyncio.CancelledError))
    worker.history_hook = lambda history: history["outputs"].update(
        preview={"images": [{"filename": "preview.png", "subfolder": "", "type": "output"}]},
    )
    create(worker)
    result = run(worker)
    assert_completed(worker, result, "PRIMARY_STORYBOARD")
    assert worker.clients[0].get_prompt_state.await_count == 3
    assert all(call.args == ("queued-1",) for call in worker.clients[0].get_prompt_state.await_args_list)
    assert sleep.await_count == 2 and all(call.args == (2,) for call in sleep.await_args_list)
    assert worker.downloads == [{"url": ENDPOINT + "/view?filename=out.png&subfolder=&type=output", "novel_id": "novel",
                                 "character_name": f"keyframe_{worker.frame_index}", "image_type": "keyframe", "chapter_id": "chapter"}]


@pytest.mark.parametrize("kind,code", [
    ("missing", "IMAGE_DOWNLOAD_FAILED"), ("corrupt", "INVALID_REFERENCE_IMAGE"),
    ("animated", "MULTIFRAME_REFERENCE_UNSUPPORTED"), ("exception", "OSError"),
])
def test_download_must_be_a_valid_single_frame_image_before_publication(worker, kind, code):
    worker.output_kind = kind
    create(worker)
    result = run(worker)
    assert_failed(worker, result, code, queued=1, llm=1)
    assert result.frames[worker.frame_index]["image_url"] == worker.urls["old-legacy"]
    assert result.plan["keyframes"][4]["image_url"] == worker.urls["old-plan"]
    assert result.contract["prompt"]["raw_response"] == PROSE["en"]["PRIMARY_STORYBOARD"]
    assert result.contract["binding_resolved"] is True and len(worker.downloads) == 1
    if kind in {"corrupt", "animated"}:
        assert result.contract["result"]["attachment"] == "detached"


@pytest.mark.parametrize("location", ["previous-reference", "downloaded-output"])
def test_png_with_valid_chunk_checksums_but_undecodable_pixels_is_not_accepted(worker, location):
    def damage_pixels(path):
        payload = path.read_bytes()
        start = payload.index(b"IDAT")
        length = int.from_bytes(payload[start - 4:start], "big")
        data = b"not a compressed pixel stream"
        chunk = b"IDAT" + data
        # Pillow.verify checks the PNG chunk CRC, not whether its pixels decode.
        path.write_bytes(payload[:start - 4] + len(data).to_bytes(4, "big") + chunk
                         + zlib.crc32(chunk).to_bytes(4, "big") + payload[start + length + 8:])
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image, pytest.raises(OSError):
            image.load()

    if location == "previous-reference":
        configure(worker, previous=worker.urls["previous"])
        damage_pixels(Path(worker.to_path(worker.urls["previous"])))
    else:
        worker.hooks["download"] = lambda: damage_pixels(worker.root / "result-1.png")
    create(worker)
    result = run(worker)
    if location == "previous-reference":
        assert_completed(worker, result, "PRIMARY_STORYBOARD")
        assert result.contract["fallback"]["reason"] == "INVALID_REFERENCE_IMAGE"
        assert worker.uploads[0]["path"] == worker.to_path(worker.urls["primary"])
    else:
        assert_failed(worker, result, "INVALID_REFERENCE_IMAGE", queued=1, llm=1)
        assert result.frames[worker.frame_index]["image_url"] == worker.urls["old-legacy"]
        assert result.contract["result"]["attachment"] == "detached"


@pytest.mark.parametrize("response,code", [
    ({"success": False, "content": "Raw partial prose", "failure_kind": "TIMEOUT", "diagnostic_content": "truncated", "error": "timeout"}, "PROMPT_BUILD_FAILED"),
    ({"success": True, "content": {"prompt": "not a string"}}, "INVALID_PROMPT_RESPONSE_TYPE"),
    ({"success": True, "content": ""}, "PROMPT_EMPTY"),
    ({"success": True, "content": PROSE["en"]["PREVIOUS_KEYFRAME"]}, "WRONG_REFERENCE_SOURCE"),
])
def test_llm_failure_metadata_keeps_raw_response_and_frozen_reference(worker, response, code):
    worker.response = response
    create(worker)
    result = run(worker)
    assert_failed(worker, result, code, llm=1)
    assert result.contract["prompt"]["raw_response"] == response["content"]
    assert result.contract["prompt"]["llm_invoked"] is True
    assert result.contract["failure"]["stage"] == "prompt_building"
    assert result.contract["resolved"]["url"] == worker.urls["primary"]
    assert result.contract["binding"]["uploaded_filename"] == "receipts/" + worker.uploads[0]["upload_name"]
    assert result.frames[worker.frame_index]["prompt_text"] == result.plan["keyframes"][4]["prompt_text"] == OLD_PROMPT
    assert result.task.prompt_text is None
    call = result.plan["ai_calls"][-1]
    raw = response["content"] if isinstance(response["content"], str) else json.dumps(response["content"])
    assert call["status"] == "error" and call["response"] == raw
    assert call["reference_images"] == json.loads(result.task.reference_images)
    if not response["success"]:
        assert result.contract["prompt"]["failure_kind"] == "TIMEOUT"
        assert result.contract["prompt"]["diagnostic_content"] == "truncated"


@pytest.mark.parametrize("ack", [
    {"success": True}, {"success": True, "prompt_id": " "}, {"success": False, "error": "ACK missing"},
])
def test_missing_queue_ack_is_unconfirmed_and_never_resubmitted(worker, ack):
    worker.queue_response = ack
    create(worker)
    result = run(worker)
    assert_failed(worker, result, "SUBMISSION_UNCONFIRMED", queued=1, llm=1)
    assert result.contract["submit"]["state"] == "unknown" and "prompt_id" not in result.contract["submit"]
    assert result.contract["prepared_workflow"] == worker.queued[0]
    assert result.task.workflow_json is None and result.task.comfyui_prompt_id is None
    worker.clients[0].get_prompt_state.assert_not_awaited()
    assert not worker.downloads
    assert run(worker).contract == result.contract and len(worker.queued) == 1


def test_queue_exception_remains_unconfirmed_without_resubmit(worker):
    worker.queue_error = TimeoutError("Queue ACK lost after submission")
    create(worker)
    result = run(worker)
    assert_failed(worker, result, "TimeoutError", queued=1, llm=1)
    assert result.contract["submit"]["state"] in {"attempted", "unknown"}
    assert "prompt_id" not in result.contract["submit"]
    assert result.task.comfyui_prompt_id is None and result.task.workflow_json is None
    assert result.contract["prepared_workflow"] == worker.queued[0]
    assert run(worker).contract == result.contract and len(worker.queued) == 1


def save_previous_producer(worker, *, state=None, metadata=DEFAULT):
    before = saved(worker)
    state = deepcopy(state if state is not None else before.plan["keyframes"][3])
    state = {key: state[key] for key in ("description", "time_seconds", "role", "index") if key in state}
    if not hasattr(worker, "producer_record"):
        frame_index, target_kf, current_task_id = worker.frame_index, worker.target_kf, worker.task_id
        old_url = worker.urls["previous"]

        def prepare(view):
            planned = view.plan["keyframes"][3]
            planned.update(state)
            view.frames[2].update({key: planned[key] for key in ("description", "role", "time_seconds")})
            view.frames[2].update(plan_keyframe_index=planned["index"], reference_mode="auto_select", reference_image_url=None)

        edit(worker, prepare)
        worker.frame_index, worker.target_kf = 2, 4
        producer_id = create(worker)
        produced = run(worker)
        assert_completed(worker, produced, "PRIMARY_STORYBOARD")
        worker.previous_producer_id = producer_id
        worker.producer_record = deepcopy(produced.contract)
        worker.urls["previous"] = produced.task.result_url
        with worker.sessions() as db:
            db.delete(db.get(worker.Task, "previous-producer"))
            shot = db.get(worker.Shot, "shot")
            for item in [*before.frames, *before.plan["keyframes"]]:
                for field in ("image_url", "reference_image_url"):
                    if item.get(field) == old_url:
                        item[field] = produced.task.result_url
            shot.keyframes, shot.video_director_plan = json.dumps(before.frames), json.dumps(before.plan)
            shot.video_director_plan_revision = before.shot.video_director_plan_revision
            db.commit()
        worker.frame_index, worker.target_kf, worker.task_id = frame_index, target_kf, current_task_id
        # Keep the real prior Task/artifact; start current-attempt observations afresh.
        for client in worker.clients:
            client.wait_for_result.assert_not_awaited()
        for name in ("events", "uploads", "queued", "prequeue", "downloads", "inputs", "clients", "builders", "enqueued", "jobs"):
            getattr(worker, name).clear()
        for mock in (worker.llm, worker.storage.download_image, worker.client_factory, worker.worker_factory, worker.enqueue):
            mock.reset_mock()
    record = deepcopy(worker.producer_record)
    record["context"]["current_keyframe"].update(state)
    record["target"]["current_state"].update(state)
    record["target"]["legacy_state"].update(state)
    record["prompt"]["cache_fingerprint"] = worker.contracts.reference_cache_fingerprint(record)
    worker.contracts.seal_contract(record, advance=True)
    with worker.sessions() as db:
        task = db.get(worker.Task, worker.previous_producer_id)
        task.created_at = datetime(2026, 1, 1)
        task.completed_at = task.created_at + timedelta(minutes=2)
        task.metadata_json = json.dumps({KEY: record})
        worker.contracts.validate_frozen_contract(record, task, require_submitted=True)
        if metadata is not DEFAULT:
            # Deliberate legacy/corrupt evidence starts from a complete, validated producer.
            task.metadata_json = metadata if isinstance(metadata, str) or metadata is None else json.dumps(metadata)
        db.commit()


def add_producer_log(worker, *, state=None, log_id="producer-log", **changes):
    state = deepcopy(state if state is not None else saved(worker).plan["keyframes"][3])
    current = {"frame_index": 2, "plan_keyframe_index": state.get("index"),
               "description": state.get("description"), "time_seconds": state.get("time_seconds")}
    # The shipped #08 legacy projection has no role field.
    payload = {"shot": {"id": "shot", "index": 1}, "current_keyframe": current}
    with worker.sessions() as db:
        producer = db.get(worker.Task, worker.previous_producer_id)
        values = {"id": log_id, "provider": "isolated", "model": "legacy-producer",
                  "task_type": "keyframe_image_prompt", "status": "success", "novel_id": "novel", "chapter_id": "chapter",
                  "user_prompt": "Original #09 planning context\n\n" + json.dumps(payload),
                  "response": json.dumps({"final_prompt": producer.prompt_text}),
                  "created_at": producer.created_at + timedelta(seconds=10), "duration": 1.0}
        db.add(worker.LLMLog(**{**values, **changes}))
        db.commit()
    return payload


@pytest.mark.parametrize("change", ["unchanged", "description", "time_seconds", "role"])
def test_replanned_both_descriptions_check_actual_p1_image_producer_not_new_owner(worker, change):
    configure(worker, target_kf=4)
    producer_id = create(worker)
    produced = run(worker)
    assert_completed(worker, produced, "PRIMARY_STORYBOARD")
    original_state = deepcopy(produced.contract["context"]["current_keyframe"])

    def replan(view):
        old_images = {item["plan_keyframe_index"]: item for item in view.frames}
        new_frames = deepcopy(view.plan["keyframes"])
        if change != "unchanged":
            new_frames[3][change] = {"description": "Pose B: Ada lowers her arm.", "time_seconds": 3.5, "role": "END"}[change]
        for item in new_frames:
            old = old_images.get(item["index"], {})
            item["image_url"] = old.get("image_url", item.get("image_url"))
        view.plan["keyframes"] = new_frames
        view.plan["keyframe_planning_status"] = "READY"
        # Reproduce #08's index-based image retention and fresh legacy projection.
        view.frames = [{"frame_index": index, "plan_keyframe_index": item["index"], "time_seconds": item["time_seconds"],
                        "description": item["description"], "image_url": item.get("image_url"), "image_task_id": item.get("image_task_id"),
                        "reference_mode": "auto_select", "reference_image_url": None}
                       for index, item in enumerate(item for item in new_frames if item["role"] != "START")]

    edit(worker, replan)
    replacement_id = create(worker)
    with worker.sessions() as db:
        replacement = db.get(worker.Task, replacement_id)
        worker.contracts.store_contract(db, replacement_id, worker.contracts.read_contract(replacement),
                                        statuses=("pending",), status="running")
    worker.frame_index, worker.target_kf = 3, 5
    before = saved(worker)
    assert before.frames[2]["description"] == before.plan["keyframes"][3]["description"]
    assert before.frames[2]["image_url"] == before.plan["keyframes"][3]["image_url"] == produced.task.result_url
    assert before.frames[2]["image_task_id"] == replacement_id
    create(worker)
    result = run(worker)
    assert_completed(worker, result, "PREVIOUS_KEYFRAME" if change == "unchanged" else "PRIMARY_STORYBOARD")
    proof = result.contract["resolution_attempts"][0]["state_proof"]
    assert proof["source"] == "p1_task" and proof["producer_task_ids"] == [producer_id]
    assert proof["state_validated"] is (change == "unchanged")
    for item in proof["evidence"]:
        assert item["state"] == {key: original_state[key] for key in ("description", "time_seconds", "role", "index")}
    if change == "unchanged":
        assert proof["status"] == "verified" and result.contract["resolved"]["producer_task_id"] == producer_id
    else:
        assert proof["status"] == "mismatch" and proof["conflicting_fields"] == [change]
        assert result.contract["fallback"] == {"from": "PREVIOUS_KEYFRAME", "to": "PRIMARY_STORYBOARD", "reason": "PREVIOUS_PRODUCER_STATE_MISMATCH"}
        assert worker.uploads[-1]["path"] == worker.to_path(worker.urls["primary"])
    assert worker.inputs[-1]["previous_keyframe_state_text"]["description"] == before.plan["keyframes"][3]["description"]
    assert saved(worker, producer_id).contract == produced.contract


@pytest.mark.parametrize("field,value,matched", [
    ("description", "A different original pose", False), ("description", "KF4: Ada waits beside the gate. ", False),
    ("index", 9, False), ("role", "END", False), ("time_seconds", 3.001, True), ("time_seconds", 3.0011, False),
])
def test_p1_source_state_checks_exact_known_fields_with_one_ms_time_tolerance(worker, field, value, matched):
    configure(worker, previous=worker.urls["previous"])
    state = deepcopy(saved(worker).plan["keyframes"][3])
    state[field] = value
    save_previous_producer(worker, state=state)
    create(worker)
    result = run(worker)
    assert_completed(worker, result, "PREVIOUS_KEYFRAME" if matched else "PRIMARY_STORYBOARD")
    proof = result.contract["resolution_attempts"][0]["state_proof"]
    assert proof["status"] == ("verified" if matched else "mismatch")
    assert proof["conflicting_fields"] == ([] if matched else [field])
    assert proof["compared_fields"] == ["description", "index", "role", "time_seconds"]


@pytest.mark.parametrize("conflicting", [False, True])
def test_legacy_exact_log_proves_original_state_without_inventing_missing_role(worker, conflicting):
    configure(worker, previous=worker.urls["previous"])
    save_previous_producer(worker, metadata=None)
    state = deepcopy(saved(worker).plan["keyframes"][3])
    if conflicting:
        state["description"] = "Pose A before #08 rewrote both descriptions"
    payload = add_producer_log(worker, state=state)
    assert "role" not in payload["current_keyframe"]
    create(worker)
    result = run(worker)
    assert_completed(worker, result, "PRIMARY_STORYBOARD" if conflicting else "PREVIOUS_KEYFRAME")
    proof = result.contract["resolution_attempts"][0]["state_proof"]
    assert proof["source"] == "legacy_llm_log" and proof["state_validated"] is not conflicting
    assert proof["compared_fields"] == ["description", "index", "time_seconds"]
    assert proof["evidence"] == [{"source": "llm_log", "log_id": "producer-log", "state": {
        "description": state["description"], "time_seconds": 3, "index": 4,
    }}]
    if conflicting:
        assert result.contract["fallback"]["reason"] == "PREVIOUS_PRODUCER_STATE_MISMATCH"
    else:
        assert proof["status"] == "verified"


@pytest.mark.parametrize("decoy", [
    "other-shot", "missing-shot-id", "other-frame", "missing-frame", "string-frame", "other-response", "unknown-response-wrapper",
    "before-created", "after-completed", "response-after-completed", "other-novel", "other-chapter", "other-step", "failed-log", "malformed-payload",
])
def test_legacy_state_proof_requires_exact_log_identity_response_and_chronology(worker, decoy):
    configure(worker, previous=worker.urls["previous"])
    save_previous_producer(worker, metadata=None)
    state = {**saved(worker).plan["keyframes"][3], "description": "Old conflicting pose"}
    payload = add_producer_log(worker, state=state)
    with worker.sessions() as db:
        log = db.get(worker.LLMLog, "producer-log")
        if decoy == "other-shot":
            payload["shot"]["id"] = "other-shot"
        elif decoy == "missing-shot-id":
            payload["shot"].pop("id")
        elif decoy == "other-frame":
            payload["current_keyframe"]["frame_index"] = 1
        elif decoy == "missing-frame":
            payload["current_keyframe"].pop("frame_index")
        elif decoy == "string-frame":
            payload["current_keyframe"]["frame_index"] = "2"
        elif decoy == "other-response":
            log.response = "Different final text"
        elif decoy == "unknown-response-wrapper":
            log.response = json.dumps({"unrecognized": db.get(worker.Task, worker.previous_producer_id).prompt_text})
        elif decoy == "before-created":
            log.created_at = datetime(2025, 12, 31, 23, 59, 59)
        elif decoy == "after-completed":
            log.created_at = datetime(2026, 1, 1, 0, 2, 1)
        elif decoy == "response-after-completed":
            log.duration = 111
        elif decoy == "other-novel":
            log.novel_id = "other-novel"
        elif decoy == "other-chapter":
            log.chapter_id = "other-chapter"
        elif decoy == "other-step":
            log.task_type = "shot_image_prompt"
        elif decoy == "failed-log":
            log.status = "error"
        log.user_prompt = "{broken" if decoy == "malformed-payload" else "Original #09\n\n" + json.dumps(payload)
        db.commit()
    create(worker)
    result = run(worker)
    assert_completed(worker, result, "PREVIOUS_KEYFRAME")
    proof = result.contract["resolved"]["state_proof"]
    assert proof["status"] == "unverified_legacy" and proof["state_validated"] is False
    assert proof["evidence"] == [] and result.contract.get("fallback") is None


@pytest.mark.parametrize("contradictory,reverse", [(False, False), (True, False), (True, True)])
def test_multiple_legacy_logs_are_all_checked_not_nearest_selected(worker, contradictory, reverse):
    configure(worker, previous=worker.urls["previous"])
    save_previous_producer(worker, metadata=None)
    state = deepcopy(saved(worker).plan["keyframes"][3])
    add_producer_log(worker, log_id="matching", created_at=datetime(2026, 1, 1, 0, 0, 20 if reverse else 10))
    if contradictory:
        state["description"] = "A contradictory original pose"
    add_producer_log(worker, state=state, log_id="second", created_at=datetime(2026, 1, 1, 0, 0, 10 if reverse else 20))
    create(worker)
    result = run(worker)
    assert_completed(worker, result, "PREVIOUS_KEYFRAME")
    proof = result.contract["resolved"]["state_proof"]
    assert {entry["log_id"] for entry in proof["evidence"]} == {"matching", "second"}
    assert proof["status"] == ("unverified_legacy" if contradictory else "verified")
    assert proof["state_validated"] is not contradictory
    if contradictory:
        assert proof["reason"] == "contradictory_producer_states"


@pytest.mark.parametrize("damage", ["missing-state", "bad-json", "null-contract", "unknown-version", "wrong-state-type", "partial-state", "bad-shot-id", "oversized-time", "contradictory-snapshots"])
def test_incomplete_or_corrupt_p1_evidence_is_not_silently_replaced_by_legacy_logs(worker, damage):
    configure(worker, previous=worker.urls["previous"])
    save_previous_producer(worker)
    add_producer_log(worker)
    with worker.sessions() as db:
        task = db.get(worker.Task, worker.previous_producer_id)
        metadata = json.loads(task.metadata_json)
        record = metadata[KEY]
        if damage == "missing-state":
            record.pop("context")
            record.pop("target")
        elif damage == "null-contract":
            metadata[KEY] = None
        elif damage == "unknown-version":
            record["version"] = -1
        elif damage == "wrong-state-type":
            record["context"]["current_keyframe"] = []
        elif damage == "partial-state":
            record.pop("target")
            record["context"]["current_keyframe"] = {"description": "KF4: Ada waits beside the gate."}
        elif damage == "bad-shot-id":
            record["context"]["shot"]["id"] = ["shot"]
        elif damage == "oversized-time":
            record["context"]["current_keyframe"]["time_seconds"] = 10 ** 400
        elif damage == "contradictory-snapshots":
            record["target"]["current_state"]["description"] = "Conflicting P1 snapshot"
        if damage not in {"bad-json", "null-contract", "unknown-version"}:
            worker.contracts.seal_contract(record, advance=True)
        task.metadata_json = "{broken" if damage == "bad-json" else json.dumps(metadata)
        db.commit()
    create(worker)
    result = run(worker)
    assert_completed(worker, result, "PREVIOUS_KEYFRAME")
    proof = result.contract["resolved"]["state_proof"]
    assert proof["status"] == "unverified_p1" and proof["state_validated"] is False
    assert all(entry["source"] != "llm_log" for entry in proof["evidence"])


def test_partial_p1_state_still_detects_a_known_description_conflict(worker):
    configure(worker, previous=worker.urls["previous"])
    save_previous_producer(worker, state={"description": "Known original pose A"})
    with worker.sessions() as db:
        task = db.get(worker.Task, worker.previous_producer_id)
        metadata = json.loads(task.metadata_json)
        record = metadata[KEY]
        record["context"].pop("current_keyframe")
        record["target"]["current_state"] = {"description": "Known original pose A"}
        worker.contracts.seal_contract(record, advance=True)
        task.metadata_json = json.dumps(metadata)
        db.commit()
    add_producer_log(worker)
    create(worker)
    result = run(worker)
    assert_completed(worker, result, "PRIMARY_STORYBOARD")
    proof = result.contract["resolution_attempts"][0]["state_proof"]
    assert proof["status"] == "mismatch" and proof["conflicting_fields"] == ["description"]
    assert proof["source"] == "p1_task" and proof["state_validated"] is False


def test_corrupted_existing_p1_seal_never_claims_validated_state_or_uses_legacy_log(worker):
    configure(worker, previous=worker.urls["previous"])
    save_previous_producer(worker)
    add_producer_log(worker)
    with worker.sessions() as db:
        task = db.get(worker.Task, worker.previous_producer_id)
        metadata = json.loads(task.metadata_json)
        record = metadata[KEY]
        worker.contracts.validate_frozen_contract(record, task, require_submitted=True)
        record["storage_hash"] = "0" * 64
        task.metadata_json = json.dumps(metadata)
        db.commit()
    create(worker)
    result = run(worker)
    assert_completed(worker, result, "PREVIOUS_KEYFRAME")
    proof = result.contract["resolved"]["state_proof"]
    assert proof["status"] == "unverified_p1" and proof["reason"] == "invalid_producer_seal"
    assert proof["state_validated"] is False and proof["evidence"] == []


@pytest.mark.parametrize("producer_case", ["missing", "multiple", "other-novel", "other-url"])
def test_non_unique_or_unresolved_image_producer_is_unknown_not_asserted(worker, producer_case):
    configure(worker, previous=worker.urls["previous"])
    save_previous_producer(worker)
    with worker.sessions() as db:
        producer = db.get(worker.Task, worker.previous_producer_id)
        if producer_case == "missing":
            db.delete(producer)
        elif producer_case == "multiple":
            duplicate = worker.Task(**{column.name: getattr(producer, column.name) for column in worker.Task.__table__.columns})
            duplicate.id, duplicate.name = "also-this-url", "Ambiguous image producer"
            db.add(duplicate)
            worker.contracts.validate_frozen_contract(worker.contracts.read_contract(duplicate), duplicate, require_submitted=True)
        elif producer_case == "other-novel":
            producer.novel_id = "other-novel"
        else:
            producer.result_url = worker.urls["custom"]
        db.commit()
    create(worker)
    result = run(worker)
    assert_completed(worker, result, "PREVIOUS_KEYFRAME")
    assert result.contract["resolved"]["producer_task_id"] is None
    assert result.contract["resolved"]["state_proof"]["status"] == "unknown"
    assert result.contract["resolved"]["state_proof"]["state_validated"] is False


@pytest.mark.parametrize("mode,reference,source", [
    ("auto_select", "previous", "PREVIOUS_KEYFRAME"), ("custom", "previous", "CUSTOM_REFERENCE"),
    ("auto_select", "custom", "SAVED_REFERENCE"), ("auto_select", "primary", "PRIMARY_STORYBOARD"),
])
def test_explicit_reference_keeps_selected_url_and_primary_needs_no_previous_state_proof(worker, mode, reference, source):
    configure(worker, previous=worker.urls["previous"], mode=mode, reference=worker.urls[reference])
    save_previous_producer(worker, state={"description": "Clearly conflicting old pose", "index": 4, "role": "END", "time_seconds": 3})
    if reference == "custom":
        with worker.sessions() as db:
            db.get(worker.Task, worker.previous_producer_id).result_url = worker.urls["custom"]
            db.commit()
    create(worker)
    result = run(worker)
    assert_completed(worker, result, source)
    assert result.contract["resolved"]["url"] == worker.urls[reference]
    assert worker.uploads[0]["path"] == worker.to_path(worker.urls[reference])
    assert result.contract.get("fallback") is None
    proof = result.contract["resolved"]["state_proof"]
    assert proof["status"] == ("mismatch" if source == "PREVIOUS_KEYFRAME" else "not_applicable")
    assert proof["state_validated"] is False


def test_source_state_proof_and_exact_payload_stay_frozen_when_producer_changes_during_llm(worker):
    configure(worker, previous=worker.urls["previous"])
    save_previous_producer(worker)
    original_payload = Path(worker.to_path(worker.urls["previous"])).read_bytes()

    def change_producer():
        save_previous_producer(worker, state={"description": "Replacement producer state"})
        make_image(worker, "previous", "red")

    worker.hooks["llm"] = change_producer
    create(worker)
    result = run(worker)
    assert_completed(worker, result, "PREVIOUS_KEYFRAME")
    proof = result.contract["resolved"]["state_proof"]
    assert proof["status"] == "verified" and proof["state_validated"] is True
    assert all(entry["state"]["description"] == "KF4: Ada waits beside the gate." for entry in proof["evidence"])
    assert worker.uploads[0]["payload"] == original_payload
    assert result.contract["resolved"]["sha256"] == hashlib.sha256(original_payload).hexdigest()
    assert result.contract["resolution_attempts"][0]["state_proof"] == proof
