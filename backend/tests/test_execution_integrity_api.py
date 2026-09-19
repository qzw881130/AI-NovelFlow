"""CANONICAL_DB admission tests with ephemeral SQLite and isolated generation I/O."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import re
import socket
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4
import zipfile

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

from app.core.database import Base as APP_BASE
import app.models.audio_drive as _audio_drive
import app.models.llm_log as _llm_log
import app.models.novel as _novel
import app.models.prompt_template as _prompt_template
import app.models.shot as _shot
import app.models.system_config as _system_config
import app.models.task as _task
import app.models.test_case as _test_case
import app.models.workflow as _workflow


pytestmark = pytest.mark.CANONICAL_DB
_API_MODELS = {
    "novel": _novel, "shot": _shot, "task": _task, "workflow": _workflow,
    "llm_log": _llm_log, "prompt_template": _prompt_template, "audio_drive": _audio_drive,
}


BACKEND = Path(__file__).resolve().parents[1]
ROOT = "/api/novels/novel/chapters/chapter"
SHOT = ROOT + "/shots/shot"
BENCHMARK_ROUTES = ("/benchmark/generate", "/benchmark/generate-video", "/benchmark/keyframes/0/generate-image")
NORMAL_ROUTES = ("/generate", "/generate-video", "/keyframes/0/generate-image", "/video-director/clips/1/generate")
VIDEO_ROUTES = ("/generate-video", "/benchmark/generate-video", "/video-director/clips/1/generate")
VISUAL_STATE_VALIDATION = {
    "enabled": True,
    "anchors": [{"clip_index": 1, "reference_index": 0, "requirements": [
        {"predicate": "character_location", "subject": " hero ", "value": " river_bank ", "source": "clip_plan"},
    ]}],
    "invariants": [{"predicate": "prop_present", "subject": "sword", "source": "clip_plan", "protected": True}],
}


@pytest.fixture
def api(monkeypatch, tmp_path, request):
    module_snapshot = {
        name: module for name, module in sys.modules.items()
        if name == "app" or name.startswith("app.")
    }

    def restore_modules():
        for name in tuple(sys.modules):
            if (name == "app" or name.startswith("app.")) and name not in module_snapshot:
                sys.modules.pop(name, None)
        sys.modules.update(module_snapshot)

    request.addfinalizer(restore_modules)

    def forbidden(*args, **kwargs):
        raise AssertionError("Real application I/O is forbidden")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    base = APP_BASE
    models = dict(_API_MODELS)
    engine = create_engine(f"sqlite:///file:api-{uuid4().hex}?mode=memory&cache=shared&uri=true",
                           connect_args={"check_same_thread": False}, poolclass=QueuePool)
    base.metadata.create_all(engine)
    db = Session(engine, autoflush=False)

    def close_private_database():
        db.close()
        engine.dispose()

    request.addfinalizer(close_private_database)
    legal_marker = request.node.get_closest_marker("c03_legal")
    legal_mode = legal_marker.args[0] if legal_marker else None
    if legal_mode not in {None, "api"}:
        raise RuntimeError(f"Unknown C03 API fixture mode: {legal_mode}")
    legal_chain = None
    if legal_mode:
        from r5_c03_support import build_legal_chain

        legal_chain = build_legal_chain(db, tmp_path, monkeypatch)

    isolated_prefixes = ("app.api", "app.repositories", "app.schemas", "app.services", "app.utils")
    for name in tuple(sys.modules):
        if any(name == prefix or name.startswith(prefix + ".") for prefix in isolated_prefixes):
            if name in module_snapshot:
                monkeypatch.delitem(sys.modules, name)
            else:
                sys.modules.pop(name, None)

    def stub(name, **attributes):
        module = ModuleType(name)
        module.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, module)
        if "." in name and name.rsplit(".", 1)[0] in sys.modules:
            monkeypatch.setattr(sys.modules[name.rsplit(".", 1)[0]], name.rsplit(".", 1)[1], module, raising=False)
        return module

    for name in ("app.api", "app.schemas", "app.services", "app.repositories", "app.utils"):
        stub(name, __path__=[str(BACKEND.joinpath(*name.split(".")))])

    def load(name, relative):
        spec = importlib.util.spec_from_file_location(name, BACKEND / relative)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        monkeypatch.setattr(sys.modules[name.rsplit(".", 1)[0]], name.rsplit(".", 1)[1], module, raising=False)
        return module

    def isolated_get_db():
        yield db

    database = stub("app.core.database", Base=base, SessionLocal=forbidden, get_db=isolated_get_db)
    state = SimpleNamespace(db=db, engine=engine, models=SimpleNamespace(**models), forbidden=forbidden,
                            writes_forbidden=True, shot_updates=[], inserts=[], queued=[], enqueue_hook=None)
    state.chain = legal_chain
    state.foundation = load("app.services.task_execution", "app/services/task_execution.py")
    state.execution = load("app.services.shot_video_execution", "app/services/shot_video_execution.py")
    load("app.services.duration_contract", "app/services/duration_contract.py")
    load("app.services.execution_window_builder", "app/services/execution_window_builder.py")
    load("app.services.video_director_plan_service", "app/services/video_director_plan_service.py")
    load("app.services.keyframe_reference_contract", "app/services/keyframe_reference_contract.py")
    load("app.services.keyframe_reference_graph", "app/services/keyframe_reference_graph.py")
    for name, filename in (("ShotRepository", "shot_repository"), ("TaskRepository", "task"),
                           ("WorkflowRepository", "workflow"), ("PromptTemplateRepository", "prompt_template")):
        cls = getattr(load("app.repositories." + filename, "app/repositories/" + filename + ".py"), name)
        monkeypatch.setattr(sys.modules["app.repositories"], name, cls, raising=False)
        setattr(state, name, cls)
    load("app.repositories.audio_drive", "app/repositories/audio_drive.py")
    Novel, Chapter, Task, ShotModel = models["novel"].Novel, models["novel"].Chapter, models["task"].Task, models["shot"].Shot

    class NovelRepository:
        def __init__(self, session):
            self.db = session

        def get_by_id(self, novel_id):
            return self.db.get(Novel, novel_id)

    class ChapterRepository(NovelRepository):
        def get_by_id(self, chapter_id, novel_id):
            return self.db.query(Chapter).filter(Chapter.id == chapter_id, Chapter.novel_id == novel_id).first()

    for cls in (NovelRepository, ChapterRepository):
        monkeypatch.setattr(sys.modules["app.repositories"], cls.__name__, cls, raising=False)
    state.novel_repo, state.chapter_repo = NovelRepository(db), ChapterRepository(db)
    state.shot_repo, state.task_repo = state.ShotRepository(db), state.TaskRepository(db)
    state.workflow_repo = state.WorkflowRepository(db)
    state.llm = SimpleNamespace(chat_completion=AsyncMock(return_value={"success": True, "content": "literal final prompt\n"}))
    stub("app.services.llm_service", LLMService=lambda: state.llm)
    stub("app.services.prompt_builder", get_style=lambda *args: (
        legal_chain.style_text if legal_chain else "", None if legal_chain else "",
    ))
    stub("app.services.comfyui", __path__=[str(BACKEND / "app/services/comfyui")],
         ComfyUIService=lambda: SimpleNamespace())
    stub("app.services.comfyui.service", is_h3_workflow=lambda graph: False)

    def delete(*args, **kwargs):
        if state.writes_forbidden:
            forbidden()

    media_root = legal_chain.root if legal_chain else tmp_path
    state.storage = SimpleNamespace(base_dir=media_root, delete_shot_image=Mock(side_effect=delete),
                                    delete_shot_video=Mock(side_effect=forbidden), merge_videos=AsyncMock(side_effect=forbidden))
    stub("app.services.file_storage", file_storage=state.storage)
    state.storage._get_story_dir = lambda novel_id: media_root / novel_id

    def enqueue(*args, **kwargs):
        state.queued.append((args, kwargs))
        if state.enqueue_hook:
            state.enqueue_hook(*args, **kwargs)

    state.enqueue = Mock(side_effect=enqueue)
    stub("app.services.background_workers", worker_manager=SimpleNamespace(worker=lambda name: SimpleNamespace(enqueue=state.enqueue)))
    stub("app.services.shot_image_service", enqueue_shot_image_task=state.enqueue)
    video = stub("app.services.shot_video_service", enqueue_shot_video_task=state.enqueue, _clip_dialogues_for_prompt=forbidden,
                 safe_json_dict=lambda value: json.loads(value) if isinstance(value, str) else value or {},
                 safe_json_list=lambda value: json.loads(value) if isinstance(value, str) else value or [])
    stub("app.services.novel_service", NovelService=forbidden, generate_transition_video_task=forbidden)
    for name, cls in (("shot_service", "ShotService"), ("audio_reference_service", "AudioReferenceService"),
                      ("single_image_edit_service", "SingleImageEditService")):
        stub("app.services." + name, **{cls: forbidden})
    stub("app.services.task_service", TaskService=(
        legal_chain.task_service_class if legal_chain
        else SimpleNamespace(validate_workflow_node_mapping=Mock(return_value=(True, "")))
    ))
    stub("app.core.config", get_settings=forbidden)
    stub("app.services.llm", __path__=[str(BACKEND / "app/services/llm")])
    stub("app.services.llm.base", mark_matching_pending_llm_logs_error=forbidden)
    load("app.services.h3_prompt_validation", "app/services/h3_prompt_validation.py")
    load("app.services.video_director_ai", "app/services/video_director_ai.py")
    stub("app.utils.path_utils", url_to_local_path=lambda value: str(media_root / value.removeprefix("/api/files/")) if value else None,
         local_path_to_url=lambda value: "/api/files/" + Path(value).name)
    stub("app.utils.time_utils", format_datetime=lambda value: str(value))
    state.keyframes = load("app.services.shot_keyframe_service", "app/services/shot_keyframe_service.py")
    load("app.schemas.visual_state", "app/schemas/visual_state.py")
    load("app.services.visual_state_validator", "app/services/visual_state_validator.py")
    load("app.services.actual_state_handoff", "app/services/actual_state_handoff.py")
    state.schemas = load("app.schemas.shot", "app/schemas/shot.py")
    dependencies = {}
    for name in ("novel_repo", "chapter_repo", "task_repo", "workflow_repo", "shot_repo", "prompt_template_repo", "llm_service"):
        def dependency():
            forbidden()
        dependencies["get_" + name] = dependency
    deps = stub("app.api.deps", **dependencies)
    module = load("app.api.shots", "app/api/shots.py")
    state.module = module
    video._resolved_duration_from_plan = module._plan_resolved_duration
    monkeypatch.setattr(database, "SessionLocal", lambda: Session(engine, autoflush=False))
    monkeypatch.setattr(module, "SessionLocal", lambda: Session(engine, autoflush=False))
    app = FastAPI()
    app.include_router(module.router, prefix="/api/novels")
    template = SimpleNamespace(name="fixture template", template="Generate a prompt")
    state.template_repo = SimpleNamespace(get_default_system_template=lambda name: template, get_by_id=lambda value: template)
    overrides = {"novel_repo": state.novel_repo, "chapter_repo": state.chapter_repo, "task_repo": state.task_repo,
                 "workflow_repo": state.workflow_repo, "shot_repo": state.shot_repo,
                 "prompt_template_repo": state.template_repo, "llm_service": state.llm}
    for name, value in overrides.items():
        def override(value=value):
            return value
        # Avoid exposing the captured repository as a FastAPI query parameter.
        override.__signature__ = __import__("inspect").Signature()
        app.dependency_overrides[getattr(deps, "get_" + name)] = override
    app.dependency_overrides[database.get_db] = lambda: db

    def post(suffix, body=None, *, absolute=False):
        async def send():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://isolated") as client:
                return await client.post(suffix if absolute else SHOT + suffix, json=body)
        return asyncio.run(send())

    state.post = post
    if legal_chain:
        state.novel, state.chapter, state.shot = legal_chain.novel, legal_chain.chapter, legal_chain.shot
    else:
        state.novel = Novel(id="novel", title="Novel")
        state.chapter = Chapter(id="chapter", novel_id="novel", number=1, title="Chapter", parsed_data="{}")
        state.shot = ShotModel(id="shot", chapter_id="chapter", index=7, description="Source description", duration=4,
                               image_url="/api/files/start.png", image_path="/api/files/start.png", image_status="completed",
                               image_task_id="active-image", shot_image_prompt="Old primary prompt", video_url="/old.mp4",
                               video_status="completed", video_task_id="old-video", video_director_plan="{}")
        db.add_all([state.novel, state.chapter, state.shot])
    for kind in ("shot", "video", "first_last_video", "three_frame_video", "four_frame_video"):
        definition = legal_chain.video_workflow if legal_chain and kind == "video" else None
        db.add(models["workflow"].Workflow(
            id=kind, type=kind, name=kind, is_active=True,
            workflow_json=definition["graph"] if definition else "{}",
            node_mapping=json.dumps(definition["mapping"]) if definition else "{}",
            extension=json.dumps(definition["extension"]) if definition else None,
        ))
    db.commit()
    for name in ("start.png", "end.png", "mid.png", "boundary.png", "mid2.png", "drive.wav", "final.wav"):
        (media_root / name).write_bytes(b"isolated fixture")

    def configure(mode="SINGLE_FRAME", audio=False):
        state.writes_forbidden = False
        plan = {"selected_mode": mode, "clips": [{"clip_index": 1, "start_time": 0, "end_time": 4,
                                                   "video_url": "/old-clip.mp4", "prompt_text": "old clip prompt"}]}
        frames = [{"index": 1, "role": "START", "time_seconds": 0},
                  {"index": 2, "role": "END", "time_seconds": 4, "description": "End state", "image_url": "/api/files/end.png"}]
        if mode == "MULTI_KEYFRAME":
            frames.insert(1, {"index": 3, "role": "INTERMEDIATE", "time_seconds": 2, "image_url": "/api/files/mid.png"})
            plan.update(execution_windows=module._build_execution_windows(4, 15),
                        window_plans=[{"window_index": 1, "start_time": 0, "end_time": 4, "selected_frame_count": 3,
                                       "keyframe_indexes": [1, 3, 2], "video_url": "/old-window.mp4"}], clips=[])
        plan["keyframes"] = frames
        state.shot.keyframes = json.dumps([{"frame_index": 0, "plan_keyframe_index": 2, "description": "End state",
                                           "reference_mode": "none", "image_url": "/api/files/end.png", "prompt_text": "Old END prompt"}])
        if audio:
            timeline = models["audio_drive"].ShotAudioTimeline(id="timeline", shot_id="shot", revision=1, total_duration=4,
                                                              audio_required_duration=4, status="READY", generated_from_hash="hash")
            db.add(timeline)
            plan["audio_timeline"] = {"id": "timeline", "revision": 1, "source_hash": "hash", "resolved_duration": 4,
                                      "audio_required_duration": 4, "events": []}
            state.shot.audio_status = "READY"
            for clip in plan.get("window_plans") or plan["clips"]:
                clip.update(audio_timeline_id="timeline", audio_timeline_revision=1, audio_timeline_hash="hash", audio_status="READY",
                            drive_audio_path=str(tmp_path / "drive.wav"), final_audio_path=str(tmp_path / "final.wav"))
            for workflow in db.query(models["workflow"].Workflow).filter(models["workflow"].Workflow.type != "shot"):
                workflow.node_mapping = json.dumps({"drive_audio_node_id": "drive", "final_audio_node_id": "final"})
        state.shot.video_director_plan = json.dumps(plan)
        db.commit()
        state.before = state.foundation.create_execution_metadata(state.shot)["execution"]["shot_snapshot"]
        state.writes_forbidden = True
        state.shot_updates.clear()

    state.configure = configure

    def configure_handoff():
        configure("MULTI_KEYFRAME")
        state.writes_forbidden = False
        state.shot.estimated_duration = state.shot.duration = 8
        windows = module._build_execution_windows(8, 4)
        frames = [{"index": index, "role": "START" if index == 1 else "END" if index == 5 else "INTERMEDIATE",
                   "time_seconds": (index - 1) * 2, "description": f"Frame {index}", "image_url": f"/api/files/{name}"}
                  for index, name in enumerate(("start.png", "mid.png", "boundary.png", "mid2.png", "end.png"), 1)]
        state.shot.video_director_plan = json.dumps({
            "selected_mode": "MULTI_KEYFRAME", "workflow_capability": {"max_clip_duration": 4},
            "execution_windows": windows, "keyframes": frames, "clips": [],
            "window_plans": [{**window, "selected_frame_count": 3, "keyframe_indexes": indexes,
                              "video_url": f"/old-window-{window['window_index']}.mp4", "prompt_text": "old window prompt"}
                             for window, indexes in zip(windows, ([1, 2, 3], [3, 4, 5]))],
        })
        state.shot.keyframes = json.dumps([{**frame, "frame_index": index, "plan_keyframe_index": frame["index"],
                                           "reference_mode": "none", "prompt_text": "Old frame prompt"}
                                          for index, frame in enumerate(frames[1:])])
        db.commit()
        state.before = state.foundation.create_execution_metadata(state.shot)["execution"]["shot_snapshot"]
        state.writes_forbidden = True
        state.shot_updates.clear()

    state.configure_handoff = configure_handoff
    configure()

    @event.listens_for(engine, "before_cursor_execute")
    def guard(connection, cursor, statement, parameters, context, executemany):
        if re.match(r'^\s*UPDATE\s+["`]?shots\b', statement, re.I):
            state.shot_updates.append(statement)
            if state.writes_forbidden:
                forbidden()

    @event.listens_for(Task, "after_insert")
    def inserted(mapper, connection, task):
        state.inserts.append({key: deepcopy(getattr(task, key)) for key in ("id", "type", "metadata_json", "parent_task_id", "batch_order")})

    yield state
    event.remove(Task, "after_insert", inserted)
    event.remove(engine, "before_cursor_execute", guard)
    db.close()
    engine.dispose()


def assert_unchanged(state):
    state.db.refresh(state.shot)
    assert state.foundation.create_execution_metadata(state.shot)["execution"]["shot_snapshot"] == state.before
    assert state.shot_updates == []
    state.storage.delete_shot_image.assert_not_called()
    state.storage.delete_shot_video.assert_not_called()


def task_from_response(state, response):
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    return state.db.get(state.models.task.Task, data.get("taskId") or data.get("task_id"))


@pytest.mark.parametrize("schema", ["GenerateShotImageRequest", "GenerateVideoRequest", "GenerateKeyframeImageRequest",
                                    "GenerateVideoDirectorClipRequest", "BatchShotImageRequest", "BatchShotVideoRequest"])
def test_purpose_defaults_and_strict_validation(api, schema):
    cls = getattr(api.module, schema)
    required = {"shot_ids": ["shot"]} if schema.startswith("Batch") else {}
    assert cls(**required).execution_purpose == "production"
    for key in ("execution_purpose", "executionPurpose"):
        assert cls(**required, **{key: "benchmark"}).execution_purpose == "benchmark"
        for invalid in (None, "", "PRODUCTION", "archive", False, 1, []):
            with pytest.raises(ValidationError):
                cls(**required, **{key: invalid})
    with pytest.raises(ValidationError):
        cls(**required, execution_purpose="production", executionPurpose="benchmark")


@pytest.mark.parametrize("route", BENCHMARK_ROUTES)
@pytest.mark.parametrize("body", [None, {}, {"execution_purpose": "benchmark"}])
def test_explicit_benchmark_routes_default_to_archive(api, route, body):
    task = task_from_response(api, api.post(route, body))
    assert api.foundation.execution_purpose(task) == "benchmark"
    first = next(item for item in api.inserts if item["id"] == task.id)
    assert json.loads(first["metadata_json"])["execution"]["shot_snapshot"] == api.before
    assert len(api.queued) == 1
    assert_unchanged(api)


@pytest.mark.parametrize("route", BENCHMARK_ROUTES)
@pytest.mark.parametrize("key", ["execution_purpose", "executionPurpose"])
def test_benchmark_wrappers_reject_production_override(api, route, key):
    response = api.post(route, {key: "production"})
    assert response.status_code == 400
    assert response.json() == {"detail": "BENCHMARK_EXECUTION_PURPOSE_REQUIRED"}
    assert api.inserts == api.queued == []
    assert_unchanged(api)


@pytest.mark.parametrize("route", NORMAL_ROUTES + BENCHMARK_ROUTES)
@pytest.mark.parametrize("purpose", [None, "invalid", True])
def test_invalid_purpose_fails_before_admission(api, route, purpose):
    assert api.post(route, {"execution_purpose": purpose}).status_code == 422
    assert api.inserts == api.queued == []
    assert_unchanged(api)


@pytest.mark.parametrize("mode", ["SINGLE_FRAME", "FIRST_LAST_FRAME", "MULTI_KEYFRAME"])
@pytest.mark.parametrize("purpose", ["production", "benchmark"])
def test_video_first_insert_freezes_complete_request_after_preflight(api, mode, purpose):
    api.configure(mode, audio=True)
    api.writes_forbidden = purpose == "benchmark"
    response = api.post("/generate-video", {"execution_purpose": purpose, "selectedMode": mode,
                                           "useKeyframes": False, "useReferenceAudio": False, "skipLlmWhenPromptExists": True})
    task = task_from_response(api, response)
    first = json.loads(api.inserts[0]["metadata_json"])
    expected = {"use_keyframes": False, "use_reference_audio": False, "selected_mode": mode,
                "workflow_id": {"SINGLE_FRAME": "video", "FIRST_LAST_FRAME": "first_last_video", "MULTI_KEYFRAME": "three_frame_video"}[mode],
                "only_window_index": None, "auto_merge_clips": False, "skip_llm_when_prompt_exists": True}
    assert first["execution"]["request"] == expected
    assert set(expected) == api.execution.REQUEST_KEYS
    assert first["execution"]["shot_snapshot"] == api.before
    assert api.foundation.execution_record(task)["request"] == expected
    api.db.refresh(api.shot)
    if purpose == "benchmark":
        assert_unchanged(api)
    else:
        assert api.shot.video_task_id == task.id
        assert api.shot.video_status == "generating"
        assert api.shot.video_url == "/old.mp4"


@pytest.mark.parametrize("purpose", ["production", "benchmark"])
@pytest.mark.parametrize("auto_merge", [False, True])
def test_clip_admission_never_claims_whole_shot_even_auto_merge(api, purpose, auto_merge):
    api.configure("MULTI_KEYFRAME", audio=True)
    task = task_from_response(api, api.post("/video-director/clips/1/generate", {
        "execution_purpose": purpose, "autoMerge": auto_merge, "skipLlmWhenPromptExists": True,
    }))
    frozen = json.loads(api.inserts[0]["metadata_json"])["execution"]
    assert set(frozen["request"]) == api.execution.REQUEST_KEYS
    assert frozen["request"]["only_window_index"] == 1
    assert frozen["request"]["auto_merge_clips"] is auto_merge
    assert frozen["shot_snapshot"] == api.before
    assert task.type == "shot_video"
    assert_unchanged(api)


@pytest.mark.parametrize("schema", ["ExecutionRequest", "GenerateShotImageRequest", "GenerateKeyframeImageRequest",
                                    "GenerateVideoRequest", "GenerateVideoDirectorClipRequest", "BatchShotImageRequest", "BatchShotVideoRequest"])
def test_visual_state_validation_is_optional_and_video_only(api, schema):
    cls = getattr(api.module, schema)
    required = {"shot_ids": ["shot"]} if schema.startswith("Batch") else {}
    video = schema in {"GenerateVideoRequest", "GenerateVideoDirectorClipRequest"}
    assert ("visual_state_validation" in cls.model_fields) is video
    if video:
        assert cls(**required).visual_state_validation is None
    for key in ("visual_state_validation", "visualStateValidation"):
        if video:
            assert cls(**{key: None}).visual_state_validation is None
            default = cls(**{key: {}}).visual_state_validation
            assert default.model_dump(mode="json") == api.schemas.VisualStateValidation().model_dump(mode="json")
            assert default.enabled is False and default.anchors == default.invariants == []
            assert default.capability_policy == "coarse_v1"
            assert cls(**{key: VISUAL_STATE_VALIDATION}).visual_state_validation.enabled is True
        else:
            with pytest.raises(ValidationError):
                cls(**required, **{key: VISUAL_STATE_VALIDATION})


@pytest.mark.parametrize("route", VIDEO_ROUTES)
@pytest.mark.parametrize("body", [None, {}, {"visualStateValidation": None}])
def test_video_without_optin_preserves_seven_options_and_request_hash(api, route, body):
    api.configure("MULTI_KEYFRAME")
    api.writes_forbidden = route != "/generate-video"
    task = task_from_response(api, api.post(route, body))
    clip = route.endswith("/clips/1/generate")
    expected = {"use_keyframes": True, "use_reference_audio": True, "selected_mode": "MULTI_KEYFRAME",
                "workflow_id": "three_frame_video", "only_window_index": 1 if clip else None,
                "auto_merge_clips": clip, "skip_llm_when_prompt_exists": False}
    first = json.loads(api.inserts[0]["metadata_json"])["execution"]["request"]
    assert first == api.foundation.execution_record(task)["request"] == expected
    assert set(first) == api.execution.REQUEST_KEYS
    assert api.execution.digest(first) == api.execution.digest(expected)
    if api.writes_forbidden:
        assert_unchanged(api)


@pytest.mark.parametrize("route,purpose", [
    ("/generate-video", "production"), ("/generate-video", "benchmark"),
    ("/benchmark/generate-video", "benchmark"),
    ("/video-director/clips/1/generate", "production"), ("/video-director/clips/1/generate", "benchmark"),
])
@pytest.mark.parametrize("enabled", [False, True])
def test_video_optin_is_frozen_at_first_insert_and_durable_before_enqueue(api, route, purpose, enabled):
    api.configure("MULTI_KEYFRAME", audio=True)
    clip = route.endswith("/clips/1/generate")
    api.writes_forbidden = purpose == "benchmark" or clip
    validation = {**deepcopy(VISUAL_STATE_VALIDATION), "enabled": enabled}
    normalized = api.schemas.VisualStateValidation.model_validate(validation).model_dump(mode="json")
    assert normalized["anchors"][0]["requirements"][0]["value"] == "river_bank"
    assert normalized["anchors"][0]["requirements"][0]["known_unknown"] is False
    assert normalized["invariants"][0]["known_unknown"] is False
    expected = {"use_keyframes": True, "use_reference_audio": False, "selected_mode": "MULTI_KEYFRAME",
                "workflow_id": "three_frame_video", "only_window_index": 1 if clip else None,
                "auto_merge_clips": clip, "skip_llm_when_prompt_exists": True, "visual_state_validation": normalized}

    def inspect_queue(task_id, *args, **kwargs):
        with Session(api.engine) as observer:
            task = observer.get(api.models.task.Task, task_id)
            first = next(item for item in api.inserts if item["id"] == task_id)
            assert task.metadata_json == first["metadata_json"]
            frozen = api.foundation.execution_record(task)
            assert frozen["request"] == expected
            assert frozen["shot_snapshot"] == api.before
            assert api.foundation.execution_purpose(task) == purpose
            assert "visual_state_validation" not in kwargs

    api.enqueue_hook = inspect_queue
    body = {"visualStateValidation": validation, "useReferenceAudio": False, "skipLlmWhenPromptExists": True}
    if not route.startswith("/benchmark/"):
        body["executionPurpose"] = purpose
    task = task_from_response(api, api.post(route, body))
    assert api.foundation.execution_record(task)["request"] == expected
    assert len(api.inserts) == len(api.queued) == 1
    api.llm.chat_completion.assert_not_awaited()
    if api.writes_forbidden:
        assert_unchanged(api)
    else:
        api.db.refresh(api.shot)
        assert (api.shot.video_task_id, api.shot.video_status, api.shot.video_url) == (task.id, "generating", "/old.mp4")


@pytest.mark.parametrize("route", VIDEO_ROUTES)
@pytest.mark.parametrize("body", [
    {"visualStateValidation": True},
    {"visualStateValidation": {"enabled": "true"}},
    {"visualStateValidation": {"enabled": True, "unknown": True}},
    {"visualStateValidation": {"enabled": True, "observations": []}},
    {"visualStateValidation": {"enabled": True, "anchors": [{"clip_index": 1, "reference_index": 0, "requirements": [
        {"predicate": "character_location", "subject": "hero", "value": "river_bank", "source": "clip_plan", "state": "PRESENT"},
    ]}]}},
    {"visualStateValidation": {"enabled": True}, "observations": []},
])
def test_invalid_visual_state_body_is_rejected_without_task_or_queue(api, route, body):
    assert api.post(route, body).status_code == 422
    assert api.db.query(api.models.task.Task).count() == 0
    assert api.inserts == api.queued == []
    api.llm.chat_completion.assert_not_awaited()
    assert_unchanged(api)


@pytest.mark.parametrize("route", ["/generate-video", "/video-director/clips/1/generate"])
@pytest.mark.parametrize("purpose", ["production", "benchmark"])
@pytest.mark.parametrize("saved_kind,incoming,status", [
    ("legacy", True, 409), ("missing", True, 409), ("disabled", True, 409), ("different", True, 409),
    ("malformed_execution", True, 409), ("malformed_request", True, 409), ("malformed_validation", True, 409),
    ("coerced_enabled", True, 409), ("matching", True, 200),
    ("legacy", None, 200), ("legacy", False, 200), ("matching", None, 200), ("matching", False, 200),
])
def test_active_video_optin_conflict_never_retrofits_or_resets_task(api, monkeypatch, route, purpose, saved_kind, incoming, status):
    api.configure("MULTI_KEYFRAME", audio=True)
    normalized = api.schemas.VisualStateValidation.model_validate(VISUAL_STATE_VALIDATION).model_dump(mode="json")
    clip = route.endswith("/clips/1/generate")
    options = {"use_keyframes": True, "use_reference_audio": True, "selected_mode": "MULTI_KEYFRAME",
               "workflow_id": "three_frame_video", "only_window_index": 1 if clip else None,
               "auto_merge_clips": clip, "skip_llm_when_prompt_exists": False, "visual_state_validation": normalized}
    data = api.foundation.create_execution_metadata(api.shot, purpose=purpose, request=options)
    saved = data["execution"]["request"]
    if saved_kind == "legacy":
        data.pop("execution")
    elif saved_kind == "missing":
        saved.pop("visual_state_validation")
    elif saved_kind == "disabled":
        saved["visual_state_validation"]["enabled"] = False
    elif saved_kind == "different":
        saved["visual_state_validation"]["anchors"][0]["requirements"][0]["value"] = "boat_deck"
    elif saved_kind == "malformed_execution":
        data["execution"]["version"] = 99
    elif saved_kind == "malformed_request":
        data["execution"]["request"] = []
    elif saved_kind == "malformed_validation":
        saved["visual_state_validation"] = []
    elif saved_kind == "coerced_enabled":
        saved["visual_state_validation"]["enabled"] = 1
    Task = api.models.task.Task
    task = Task(id="active-video", type="shot_video", name="Existing attempt", status="running", progress=43,
                novel_id="novel", chapter_id="chapter", shot_id="shot", workflow_id="three_frame_video",
                claim_token="existing-claim", attempt=2, started_at=datetime(2026, 9, 7), prompt_text="Original prompt",
                current_step="Original step", result_url="/partial.mp4", metadata_json=json.dumps(data))
    api.db.add(task)
    api.db.commit()
    before = {column.key: getattr(task, column.key) for column in Task.__table__.columns}
    api.inserts.clear()
    monkeypatch.setattr(api.module, "generate_shot_video_task", api.forbidden)
    monkeypatch.setattr(api.module, "_sync_latest_audio_timeline_into_plan", api.forbidden)
    body = {"executionPurpose": purpose}
    if incoming is not None:
        body["visualStateValidation"] = {**deepcopy(VISUAL_STATE_VALIDATION), "enabled": incoming}
    response = api.post(route, body)
    assert response.status_code == status, response.text
    if status == 200:
        assert response.json()["data"] == {"taskId": task.id, "status": "running"}
    else:
        assert response.json() == {"detail": "VISUAL_STATE_VALIDATION_ACTIVE_TASK_MISMATCH"}
    api.db.refresh(task)
    assert {column.key: getattr(task, column.key) for column in Task.__table__.columns} == before
    assert api.db.query(Task).count() == 1
    assert api.inserts == api.queued == []
    api.llm.chat_completion.assert_not_awaited()
    assert_unchanged(api)


@pytest.mark.parametrize("schema", ["ExecutionRequest", "GenerateShotImageRequest", "GenerateKeyframeImageRequest",
                                    "GenerateVideoRequest", "GenerateVideoDirectorClipRequest", "BatchShotImageRequest", "BatchShotVideoRequest"])
def test_actual_state_handoff_is_optional_and_whole_shot_only(api, schema):
    cls = getattr(api.module, schema)
    required = {"shot_ids": ["shot"]} if schema.startswith("Batch") else {}
    whole = schema == "GenerateVideoRequest"
    assert ("actual_state_handoff" in cls.model_fields) is whole
    if whole:
        assert cls().actual_state_handoff is None
    for key in ("actual_state_handoff", "actualStateHandoff"):
        if whole:
            assert cls(**{key: None}).actual_state_handoff is None
            assert cls(**{key: {}}).actual_state_handoff.model_dump(mode="json") == {"enabled": False}
            assert cls(**{key: {"enabled": True}}).actual_state_handoff.model_dump(mode="json") == {"enabled": True}
        else:
            with pytest.raises(ValidationError):
                cls(**required, **{key: {"enabled": True}})


@pytest.mark.parametrize("route", ["/generate-video", "/benchmark/generate-video"])
@pytest.mark.parametrize("visual", [None, VISUAL_STATE_VALIDATION])
@pytest.mark.parametrize("key", [None, "actual_state_handoff", "actualStateHandoff"])
def test_absent_or_null_handoff_preserves_exact_legacy_request_shape(api, route, visual, key):
    api.configure("MULTI_KEYFRAME")
    api.writes_forbidden = route != "/generate-video"
    body = {"visualStateValidation": visual}
    if key:
        body[key] = None
    task = task_from_response(api, api.post(route, body))
    expected = {"use_keyframes": True, "use_reference_audio": True, "selected_mode": "MULTI_KEYFRAME",
                "workflow_id": "three_frame_video", "only_window_index": None,
                "auto_merge_clips": False, "skip_llm_when_prompt_exists": False}
    if visual is not None:
        expected["visual_state_validation"] = api.schemas.VisualStateValidation.model_validate(visual).model_dump(mode="json")
    first = json.loads(api.inserts[0]["metadata_json"])["execution"]["request"]
    assert first == api.foundation.execution_record(task)["request"] == expected
    assert len(first) == (7 if visual is None else 8)
    assert api.execution.digest(first) == api.execution.digest(expected)
    if api.writes_forbidden:
        assert_unchanged(api)


@pytest.mark.parametrize("route,purpose", [
    ("/generate-video", "production"), ("/generate-video", "benchmark"), ("/benchmark/generate-video", "benchmark"),
])
@pytest.mark.parametrize("key", ["actual_state_handoff", "actualStateHandoff"])
def test_handoff_is_frozen_at_first_insert_and_durable_before_enqueue(api, route, purpose, key):
    api.configure_handoff()
    api.writes_forbidden = purpose == "benchmark"
    expected = {"use_keyframes": False, "use_reference_audio": False, "selected_mode": "MULTI_KEYFRAME",
                "workflow_id": "three_frame_video", "only_window_index": None, "auto_merge_clips": False,
                "skip_llm_when_prompt_exists": False, "actual_state_handoff": {"enabled": True},
                "visual_state_validation": api.schemas.VisualStateValidation.model_validate(VISUAL_STATE_VALIDATION).model_dump(mode="json")}

    def inspect_queue(task_id, *args, **kwargs):
        with Session(api.engine) as observer:
            task = observer.get(api.models.task.Task, task_id)
            first = next(item for item in api.inserts if item["id"] == task_id)
            assert task.metadata_json == first["metadata_json"]
            frozen = api.foundation.execution_record(task)
            assert frozen["request"] == expected
            assert frozen["shot_snapshot"] == api.before
            assert api.foundation.execution_purpose(task) == purpose
            assert "actual_state_handoff" not in kwargs and "visual_state_validation" not in kwargs

    api.enqueue_hook = inspect_queue
    body = {key: {"enabled": True}, "visualStateValidation": VISUAL_STATE_VALIDATION,
            "useKeyframes": False, "useReferenceAudio": False, "selectedMode": "MULTI_KEYFRAME",
            "workflowId": "three_frame_video", "skipLlmWhenPromptExists": False}
    if not route.startswith("/benchmark/"):
        body["executionPurpose"] = purpose
    task = task_from_response(api, api.post(route, body))
    assert api.foundation.execution_record(task)["request"] == expected
    assert len(api.inserts) == len(api.queued) == 1
    api.llm.chat_completion.assert_not_awaited()
    if api.writes_forbidden:
        assert_unchanged(api)
    else:
        api.db.refresh(api.shot)
        assert (api.shot.video_task_id, api.shot.video_status, api.shot.video_url) == (task.id, "generating", "/old.mp4")


@pytest.mark.parametrize("route", ["/generate-video", "/benchmark/generate-video"])
@pytest.mark.parametrize("mode", ["SINGLE_FRAME", "FIRST_LAST_FRAME", "MULTI_KEYFRAME"])
@pytest.mark.parametrize("option", [{}, {"enabled": False}])
def test_disabled_handoff_does_not_require_p0_fresh_prompt_or_two_windows(api, route, mode, option):
    api.configure(mode)
    api.writes_forbidden = route != "/generate-video"
    task = task_from_response(api, api.post(route, {"actualStateHandoff": option, "skipLlmWhenPromptExists": True}))
    expected = {"use_keyframes": True, "use_reference_audio": True, "selected_mode": mode,
                "workflow_id": {"SINGLE_FRAME": "video", "FIRST_LAST_FRAME": "first_last_video", "MULTI_KEYFRAME": "three_frame_video"}[mode],
                "only_window_index": None, "auto_merge_clips": False, "skip_llm_when_prompt_exists": True,
                "actual_state_handoff": {"enabled": False}}
    assert json.loads(api.inserts[0]["metadata_json"])["execution"]["request"] == expected
    assert api.foundation.execution_record(task)["request"] == expected
    assert len(api.inserts) == len(api.queued) == 1
    api.llm.chat_completion.assert_not_awaited()
    if api.writes_forbidden:
        assert_unchanged(api)
    else:
        api.db.refresh(api.shot)
        assert (api.shot.video_task_id, api.shot.video_status, api.shot.video_url) == (task.id, "generating", "/old.mp4")


@pytest.mark.parametrize("route", ["/generate-video", "/benchmark/generate-video"])
@pytest.mark.parametrize("option", [True, [], {"enabled": "true"}, {"enabled": 1}, {"enabled": None},
                                    {"enabled": True, "observations": []}, {"enabled": True, "unknown": False}])
def test_invalid_handoff_body_is_rejected_without_task_or_queue(api, route, option):
    assert api.post(route, {"actualStateHandoff": option}).status_code == 422
    assert api.db.query(api.models.task.Task).count() == 0
    assert api.inserts == api.queued == []
    api.llm.chat_completion.assert_not_awaited()
    assert_unchanged(api)


@pytest.mark.parametrize("route", [SHOT + "/video-director/clips/1/generate", ROOT + "/videos/generate-batch"])
@pytest.mark.parametrize("key", ["actual_state_handoff", "actualStateHandoff"])
@pytest.mark.parametrize("option", [None, {"enabled": False}, {"enabled": True}])
def test_clip_and_batch_reject_handoff_field_even_when_disabled(api, route, key, option):
    api.configure_handoff()
    body = {key: option, "visualStateValidation": VISUAL_STATE_VALIDATION} if "/clips/" in route else {
        key: option, "shot_ids": ["shot"],
    }
    assert api.post(route, body, absolute=True).status_code == 422
    assert api.db.query(api.models.task.Task).count() == 0
    assert api.inserts == api.queued == []
    api.llm.chat_completion.assert_not_awaited()
    assert_unchanged(api)


@pytest.mark.parametrize("route", ["/generate-video", "/benchmark/generate-video"])
@pytest.mark.parametrize("target,change,error", [
    ("request", {"selectedMode": "SINGLE_FRAME"}, "HANDOFF_REQUIRES_WHOLE_TWO_CLIP_MULTI"),
    ("request", {"selectedMode": "FIRST_LAST_FRAME"}, "HANDOFF_REQUIRES_WHOLE_TWO_CLIP_MULTI"),
    ("count", 1, "HANDOFF_REQUIRES_WHOLE_TWO_CLIP_MULTI"),
    ("count", 3, "HANDOFF_REQUIRES_WHOLE_TWO_CLIP_MULTI"),
    ("count", 4, "HANDOFF_REQUIRES_WHOLE_TWO_CLIP_MULTI"),
    (0, {"window_index": 2}, "HANDOFF_INVALID_CLIP_MEMBERSHIP"),
    (1, {"window_index": 1}, "HANDOFF_INVALID_CLIP_MEMBERSHIP"),
    (1, {"window_index": "2"}, "HANDOFF_INVALID_CLIP_MEMBERSHIP"),
    (0, {"selected_frame_count": 2}, "HANDOFF_INVALID_CLIP_MEMBERSHIP"),
    (1, {"selected_frame_count": 5}, "HANDOFF_INVALID_CLIP_MEMBERSHIP"),
    (1, {"selected_frame_count": 4}, "HANDOFF_INVALID_CLIP_MEMBERSHIP"),
    (0, {"keyframe_indexes": [1, 3, 2]}, "HANDOFF_INVALID_CLIP_MEMBERSHIP"),
    (0, {"keyframe_indexes": [1, 2, 2]}, "HANDOFF_INVALID_CLIP_MEMBERSHIP"),
    (0, {"keyframe_indexes": [1, "2", 3]}, "HANDOFF_INVALID_CLIP_MEMBERSHIP"),
    (0, {"keyframe_indexes": [0, 2, 3]}, "HANDOFF_INVALID_CLIP_MEMBERSHIP"),
    (0, {"start_time": -1}, "HANDOFF_INVALID_CLIP_RANGE"),
    (0, {"end_time": 0}, "HANDOFF_INVALID_CLIP_RANGE"),
    (1, {"end_time": 3}, "HANDOFF_INVALID_CLIP_RANGE"),
    (1, {"start_time": "4"}, "HANDOFF_INVALID_CLIP_RANGE"),
    (0, {"start_time": False}, "HANDOFF_INVALID_CLIP_RANGE"),
    (0, {"end_time": float("nan")}, "HANDOFF_INVALID_CLIP_RANGE"),
    (1, {"start_time": float("inf")}, "HANDOFF_INVALID_CLIP_RANGE"),
    (1, {"start_time": 4.002}, "HANDOFF_REQUIRES_ADJACENT_WINDOWS"),
    (1, {"start_time": 3.998}, "HANDOFF_REQUIRES_ADJACENT_WINDOWS"),
    (1, {"keyframe_indexes": [2, 4, 5]}, "HANDOFF_REQUIRES_SHARED_PLANNED_BOUNDARY"),
])
def test_unsupported_handoff_scope_stops_before_cleanup_audio_sync_or_admission(api, monkeypatch, route, target, change, error):
    api.configure_handoff()
    body = {"actualStateHandoff": {"enabled": True}, "visualStateValidation": VISUAL_STATE_VALIDATION}
    plan = json.loads(api.shot.video_director_plan)
    if target == "request":
        body.update(change)
    elif target == "count":
        plan["window_plans"] = (plan["window_plans"] * 2)[:change]
    else:
        plan["window_plans"][target].update(change)
    api.writes_forbidden = False
    api.shot.video_director_plan = json.dumps(plan)
    api.db.commit()
    api.before = api.foundation.create_execution_metadata(api.shot)["execution"]["shot_snapshot"]
    api.writes_forbidden = True
    api.shot_updates.clear()
    monkeypatch.setattr(api.task_repo, "get_failed_shot_task", api.forbidden)
    monkeypatch.setattr(api.task_repo, "delete", api.forbidden)
    monkeypatch.setattr(api.module, "_sync_latest_audio_timeline_into_plan", api.forbidden)
    monkeypatch.setattr(api.module, "_admit_video_execution", api.forbidden)
    response = api.post(route, body)
    assert response.status_code == 400, response.text
    assert response.json() == {"detail": error}
    assert api.db.query(api.models.task.Task).count() == 0
    assert api.inserts == api.queued == []
    api.llm.chat_completion.assert_not_awaited()
    assert_unchanged(api)


@pytest.mark.parametrize("route", ["/generate-video", "/benchmark/generate-video"])
@pytest.mark.parametrize("active", [False, True])
@pytest.mark.parametrize("extra,error", [
    ({}, "HANDOFF_REQUIRES_VISUAL_STATE_VALIDATION"),
    ({"visualStateValidation": None}, "HANDOFF_REQUIRES_VISUAL_STATE_VALIDATION"),
    ({"visualStateValidation": {"enabled": False}}, "HANDOFF_REQUIRES_VISUAL_STATE_VALIDATION"),
    ({"visualStateValidation": VISUAL_STATE_VALIDATION, "skipLlmWhenPromptExists": True}, "HANDOFF_REQUIRES_FRESH_PROMPT"),
])
def test_handoff_requires_fresh_p0_before_writes_or_active_return(api, monkeypatch, route, active, extra, error):
    api.configure_handoff()
    Task = api.models.task.Task
    if active:
        task = Task(id="active-video", type="shot_video", name="Existing attempt", status="running", shot_id="shot",
                    chapter_id="chapter", novel_id="novel", metadata_json=json.dumps(api.foundation.create_execution_metadata(
                        api.shot, purpose="benchmark" if route.startswith("/benchmark/") else "production")))
        api.db.add(task)
        api.db.commit()
        before = {column.key: getattr(task, column.key) for column in Task.__table__.columns}
        api.inserts.clear()
    monkeypatch.setattr(api.task_repo, "get_failed_shot_task", api.forbidden)
    monkeypatch.setattr(api.module, "_sync_latest_audio_timeline_into_plan", api.forbidden)
    monkeypatch.setattr(api.module, "_admit_video_execution", api.forbidden)
    response = api.post(route, {"actualStateHandoff": {"enabled": True}, **extra})
    assert response.status_code == 400, response.text
    assert response.json() == {"detail": error}
    if active:
        api.db.refresh(task)
        assert {column.key: getattr(task, column.key) for column in Task.__table__.columns} == before
    assert api.db.query(Task).count() == int(active)
    assert api.inserts == api.queued == []
    assert_unchanged(api)


@pytest.mark.parametrize("route", ["/generate-video", "/benchmark/generate-video"])
@pytest.mark.parametrize("change,error", [
    ({"selected_mode": "FIRST_LAST_FRAME"}, "HANDOFF_REQUIRES_WHOLE_TWO_CLIP_MULTI"),
    ({"window_plans": []}, "HANDOFF_REQUIRES_WHOLE_TWO_CLIP_MULTI"),
])
def test_handoff_rechecks_resolved_plan_before_admission(api, monkeypatch, route, change, error):
    api.configure_handoff()
    resolved = {**json.loads(api.shot.video_director_plan), **change}
    resolve = Mock(return_value=resolved)
    monkeypatch.setattr(api.module, "_benchmark_video_plan" if route.startswith("/benchmark/") else "_sync_latest_audio_timeline_into_plan", resolve)
    scope = Mock(wraps=api.module.validate_handoff_scope)
    monkeypatch.setattr(api.module, "validate_handoff_scope", scope)
    monkeypatch.setattr(api.module, "_admit_video_execution", api.forbidden)
    response = api.post(route, {"actualStateHandoff": {"enabled": True}, "visualStateValidation": VISUAL_STATE_VALIDATION})
    assert response.status_code == 400, response.text
    assert response.json() == {"detail": error}
    resolve.assert_called_once()
    assert scope.call_count == 2 and scope.call_args.args[1] is resolved
    assert api.db.query(api.models.task.Task).count() == 0
    assert api.inserts == api.queued == []
    assert_unchanged(api)


@pytest.mark.parametrize("route,purpose", [("/generate-video", "production"), ("/benchmark/generate-video", "benchmark")])
@pytest.mark.parametrize("saved_kind,incoming", [(kind, True) for kind in (
    "matching", "missing", "disabled", "malformed", "coerced_enabled", "extra_field", "clip", "clip_auto_merge",
    "single_frame", "first_last", "skip_prompt", "missing_skip", "null_skip", "missing_scope",
    "one_window", "three_windows", "bad_indexes", "bad_times", "nonshared", "missing_p0", "disabled_p0", "different_p0",
)] + [("missing", False), ("matching", False), ("clip", False), ("matching", None)])
def test_active_handoff_requires_matching_frozen_whole_two_clip_contract(api, monkeypatch, route, purpose, saved_kind, incoming):
    api.configure_handoff()
    options = {"use_keyframes": True, "use_reference_audio": True, "selected_mode": "MULTI_KEYFRAME",
               "workflow_id": "three_frame_video", "only_window_index": None, "auto_merge_clips": False,
               "skip_llm_when_prompt_exists": False, "actual_state_handoff": {"enabled": True},
               "visual_state_validation": api.schemas.VisualStateValidation.model_validate(VISUAL_STATE_VALIDATION).model_dump(mode="json")}
    data = api.foundation.create_execution_metadata(api.shot, purpose=purpose, request=options)
    saved = data["execution"]["request"]
    plan = json.loads(data["execution"]["shot_snapshot"]["video_director_plan"])
    if saved_kind == "missing":
        saved.pop("actual_state_handoff")
    elif saved_kind == "disabled":
        saved["actual_state_handoff"]["enabled"] = False
    elif saved_kind == "malformed":
        saved["actual_state_handoff"] = []
    elif saved_kind == "coerced_enabled":
        saved["actual_state_handoff"]["enabled"] = 1
    elif saved_kind == "extra_field":
        saved["actual_state_handoff"]["unknown"] = True
    elif saved_kind in {"clip", "clip_auto_merge"}:
        saved.update(only_window_index=1, auto_merge_clips=saved_kind == "clip_auto_merge")
    elif saved_kind in {"single_frame", "first_last"}:
        saved["selected_mode"] = "SINGLE_FRAME" if saved_kind == "single_frame" else "FIRST_LAST_FRAME"
    elif saved_kind in {"skip_prompt", "null_skip"}:
        saved["skip_llm_when_prompt_exists"] = True if saved_kind == "skip_prompt" else None
    elif saved_kind in {"missing_skip", "missing_scope"}:
        saved.pop("skip_llm_when_prompt_exists" if saved_kind == "missing_skip" else "only_window_index")
    elif saved_kind in {"one_window", "three_windows"}:
        plan["window_plans"] = (plan["window_plans"] * 2)[:1 if saved_kind == "one_window" else 3]
    elif saved_kind == "bad_indexes":
        plan["window_plans"][1]["window_index"] = 1
    elif saved_kind == "bad_times":
        plan["window_plans"][1]["start_time"] = 4.1
    elif saved_kind == "nonshared":
        plan["window_plans"][1]["keyframe_indexes"] = [2, 4, 5]
    elif saved_kind == "missing_p0":
        saved.pop("visual_state_validation")
    elif saved_kind == "disabled_p0":
        saved["visual_state_validation"]["enabled"] = False
    elif saved_kind == "different_p0":
        saved["visual_state_validation"]["anchors"][0]["requirements"][0]["value"] = "boat_deck"
    data["execution"]["shot_snapshot"]["video_director_plan"] = json.dumps(plan)
    Task = api.models.task.Task
    task = Task(id="active-video", type="shot_video", name="Existing attempt", status="running", progress=43,
                novel_id="novel", chapter_id="chapter", shot_id="shot", workflow_id="three_frame_video",
                claim_token="existing-claim", attempt=2, started_at=datetime(2026, 9, 7), prompt_text="Original prompt",
                current_step="Original step", result_url="/partial.mp4", metadata_json=json.dumps(data))
    api.db.add(task)
    api.db.commit()
    before = {column.key: getattr(task, column.key) for column in Task.__table__.columns}
    api.inserts.clear()
    monkeypatch.setattr(api.task_repo, "get_failed_shot_task", api.forbidden)
    monkeypatch.setattr(api.module, "_sync_latest_audio_timeline_into_plan", api.forbidden)
    monkeypatch.setattr(api.module, "generate_shot_video_task", api.forbidden)
    body = {"visualStateValidation": VISUAL_STATE_VALIDATION}
    if incoming is not None:
        body["actualStateHandoff"] = {"enabled": incoming}
    response = api.post(route, body)
    reused = saved_kind == "matching" or incoming is not True
    assert response.status_code == (200 if reused else 409), response.text
    if reused:
        assert response.json()["data"] == {"taskId": task.id, "status": "running"}
    else:
        prefix = "VISUAL_STATE_VALIDATION" if saved_kind in {"missing_p0", "disabled_p0", "different_p0"} else "ACTUAL_STATE_HANDOFF"
        assert response.json() == {"detail": prefix + "_ACTIVE_TASK_MISMATCH"}
    api.db.refresh(task)
    assert {column.key: getattr(task, column.key) for column in Task.__table__.columns} == before
    assert api.db.query(Task).count() == 1
    assert api.inserts == api.queued == []
    api.llm.chat_completion.assert_not_awaited()
    assert_unchanged(api)


@pytest.mark.parametrize("failure", ["exception", "unsuccessful", "empty"])
def test_benchmark_image_has_durable_task_before_llm_failure(api, failure):
    async def resolve(**kwargs):
        with Session(api.engine) as observer:
            tasks = observer.query(api.models.task.Task).all()
            assert len(tasks) == 1
            assert api.foundation.execution_record(tasks[0])["shot_snapshot"] == api.before
            assert tasks[0].prompt_text is None
        if failure == "exception":
            raise RuntimeError("LLM failed")
        return {"success": failure != "unsuccessful", "content": "", "error": "LLM failed"}
    api.llm.chat_completion.side_effect = resolve
    response = api.post("/benchmark/generate")
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["code"] == "BENCHMARK_PROMPT_RESOLUTION_FAILED"
    task = api.db.get(api.models.task.Task, detail["taskId"])
    assert task.status == "failed"
    assert api.foundation.execution_record(task)["failure"]["message"]
    assert api.queued == []
    assert_unchanged(api)


def test_benchmark_image_literal_prompt_is_durable_before_enqueue(api):
    literal = "  literal prompt\n"
    def inspect_queue(task_id, *args, **kwargs):
        with Session(api.engine) as observer:
            task = observer.get(api.models.task.Task, task_id)
            assert task.prompt_text == literal
            assert task.shot_id == "shot"
            assert api.foundation.execution_record(task)["request"]["prompt_text"] == literal
    api.enqueue_hook = inspect_queue
    task = task_from_response(api, api.post("/generate", {"execution_purpose": "benchmark", "prompt_text": literal}))
    assert task.prompt_text == literal
    api.llm.chat_completion.assert_not_awaited()
    assert_unchanged(api)


@pytest.mark.parametrize("field,value", [("status", "cancelled"), ("parent_task_id", "new-parent"), ("prompt_text", "new prompt")])
def test_prompt_resolution_does_not_overwrite_replaced_task(api, field, value):
    async def replaced(**kwargs):
        with Session(api.engine) as editor:
            task = editor.query(api.models.task.Task).one()
            setattr(task, field, value)
            editor.commit()
        return {"success": True, "content": "late prompt"}
    api.llm.chat_completion.side_effect = replaced
    assert api.post("/benchmark/generate").status_code == 409
    api.db.expire_all()
    task = api.db.query(api.models.task.Task).one()
    assert getattr(task, field) == value
    assert json.loads(task.metadata_json)["execution_observations"]
    assert api.queued == []
    assert_unchanged(api)


@pytest.mark.parametrize("route,task_type", [("/generate", "shot_image"), ("/generate-video", "shot_video"),
                                            ("/keyframes/0/generate-image", "keyframe_image")])
@pytest.mark.parametrize("first_purpose", ["production", "benchmark"])
def test_active_purpose_collision_never_reuses_or_reparents_other_purpose(api, route, task_type, first_purpose):
    api.writes_forbidden = False
    first = task_from_response(api, api.post(route, {"execution_purpose": first_purpose, **({"prompt_text": "first"} if task_type == "shot_image" else {})}))
    if task_type == "shot_image":
        # Production admission clears its input image; the next #06 still uses saved source descriptions.
        api.db.refresh(api.shot)
    next_purpose = "benchmark" if first_purpose == "production" else "production"
    api.writes_forbidden = next_purpose == "benchmark"
    second = task_from_response(api, api.post(route, {"execution_purpose": next_purpose, **({"prompt_text": "second"} if task_type == "shot_image" else {})}))
    assert second.id != first.id
    assert api.foundation.execution_purpose(first) == first_purpose
    assert api.foundation.execution_purpose(second) == next_purpose
    assert first.parent_task_id is second.parent_task_id is None


@pytest.mark.c03_legal("api")
def test_production_cleanup_preserves_benchmark_failure_history(api):
    Task = api.models.task.Task
    benchmark = Task(id="failed-benchmark", type="shot_video", name="benchmark", status="failed", shot_id="shot",
                     novel_id="novel", chapter_id="chapter", metadata_json=json.dumps(api.foundation.create_execution_metadata(api.shot, purpose="benchmark")))
    legacy = Task(id="failed-production", type="shot_video", name="production", status="failed", shot_id="shot", novel_id="novel", chapter_id="chapter")
    api.db.add_all([benchmark, legacy])
    api.db.commit()
    api.writes_forbidden = False
    assert api.post("/generate-video", {}).status_code == 200
    assert api.db.get(Task, benchmark.id) is not None
    assert api.db.get(Task, "failed-production") is None


@pytest.mark.parametrize("route", ["/benchmark/generate-video", "/benchmark/keyframes/0/generate-image"])
def test_missing_end_slot_is_an_explicit_stop_without_mutation(api, route):
    api.configure("FIRST_LAST_FRAME")
    api.writes_forbidden = False
    api.shot.keyframes = "[]"
    if route.endswith("generate-video"):
        plan = json.loads(api.shot.video_director_plan)
        plan["keyframes"][1].pop("image_url")
        api.shot.video_director_plan = json.dumps(plan)
    api.db.commit()
    api.before = api.foundation.create_execution_metadata(api.shot)["execution"]["shot_snapshot"]
    api.writes_forbidden = True
    api.shot_updates.clear()
    response = api.post(route)
    assert response.status_code == 400
    assert api.inserts == api.queued == []
    assert_unchanged(api)


@pytest.mark.parametrize("route", ["/benchmark/generate-video", "/video-director/clips/1/generate"])
def test_benchmark_rejects_stale_audio_instead_of_synchronizing(api, route):
    api.configure("MULTI_KEYFRAME", audio=True)
    api.db.add(api.models.audio_drive.ShotAudioTimeline(id="new-timeline", shot_id="shot", revision=2,
                                                      status="READY", generated_from_hash="new-hash", total_duration=4))
    api.db.commit()
    response = api.post(route, {"execution_purpose": "benchmark"})
    assert response.status_code == 400
    assert "BENCHMARK_SOURCE_NOT_READY" in response.json()["detail"]
    assert api.inserts == api.queued == []
    assert_unchanged(api)


@pytest.mark.parametrize("use_reference_audio", [False, True])
def test_benchmark_checks_only_requested_legacy_reference_audio(api, use_reference_audio):
    api.writes_forbidden = False
    api.shot.reference_audio_url = "/api/files/missing-audio.wav"
    api.db.commit()
    api.before = api.foundation.create_execution_metadata(api.shot)["execution"]["shot_snapshot"]
    api.shot_updates.clear()
    api.writes_forbidden = True
    response = api.post("/benchmark/generate-video", {"useReferenceAudio": use_reference_audio})
    assert response.status_code == (400 if use_reference_audio else 200)
    assert_unchanged(api)


@pytest.mark.parametrize("suffix,extra", [("/shot-images/batch", {}), ("/videos/generate-batch", {"auto_complete": True})])
def test_benchmark_batch_rejected_before_any_persistence(api, suffix, extra):
    response = api.post(ROOT + suffix, {"shot_ids": ["shot", "missing"], "execution_purpose": "benchmark", **extra}, absolute=True)
    assert response.status_code == 400
    assert response.json() == {"detail": "BENCHMARK_BATCH_UNSUPPORTED"}
    assert api.inserts == api.queued == []
    assert_unchanged(api)


@pytest.mark.parametrize("field,value", [("video_task_id", "new-owner"), ("description", "edited source"), ("image_url", "/new.png")])
def test_stale_video_admission_cas_rejects_without_overwriting(api, monkeypatch, field, value):
    api.writes_forbidden = False
    create = api.task_repo.create_shot_video_task
    def raced(**kwargs):
        task = create(**kwargs)
        with Session(api.engine) as editor:
            shot = editor.get(api.models.shot.Shot, "shot")
            setattr(shot, field, value)
            editor.commit()
        return task
    monkeypatch.setattr(api.task_repo, "create_shot_video_task", raced)
    response = api.post("/generate-video", {})
    assert response.status_code == 409
    assert response.json() == {"detail": "VIDEO_ADMISSION_CONFLICT"}
    api.db.refresh(api.shot)
    assert getattr(api.shot, field) == value
    assert api.db.query(api.models.task.Task).one().status == "failed"
    assert api.queued == []


@pytest.mark.parametrize("invalid_plan", [False, True])
def test_preflight_refresh_cannot_authorize_a_new_active_owner(api, monkeypatch, invalid_plan):
    api.writes_forbidden = False
    def sync(shot, repo):
        with Session(api.engine) as editor:
            current = editor.get(api.models.shot.Shot, "shot")
            current.video_task_id = "new-active-owner"
            if invalid_plan:
                current.video_director_plan = '{"selected_mode": "MULTI_KEYFRAME"}'
            editor.add(api.models.task.Task(id="new-active-owner", type="shot_video", name="New owner", status="running",
                                           shot_id="shot", novel_id="novel", chapter_id="chapter"))
            editor.commit()
        repo.db.refresh(shot)
        return json.loads(shot.video_director_plan)
    monkeypatch.setattr(api.module, "_sync_latest_audio_timeline_into_plan", sync)
    assert api.post("/generate-video", {}).status_code == 409
    api.db.refresh(api.shot)
    assert api.shot.video_task_id == "new-active-owner"
    assert api.db.query(api.models.task.Task).count() == 1
    assert api.queued == []


@pytest.mark.parametrize("race", [False, True])
def test_production_invalid_plan_failure_write_is_owner_fenced(api, monkeypatch, race):
    api.configure("MULTI_KEYFRAME")
    api.writes_forbidden = False
    def invalid(shot, plan):
        if race:
            with Session(api.engine) as editor:
                editor.get(api.models.shot.Shot, "shot").video_task_id = "new-owner"
                editor.commit()
        return False, "invalid plan", None
    monkeypatch.setattr(api.module, "_validate_multi_keyframe_plan_for_execution", invalid)
    response = api.post("/generate-video", {})
    assert response.status_code == (409 if race else 400)
    api.db.refresh(api.shot)
    assert api.shot.video_task_id == ("new-owner" if race else None)
    assert api.shot.video_status == ("completed" if race else "failed")
    assert api.shot.video_url == "/old.mp4"
    assert api.inserts == api.queued == []


@pytest.mark.parametrize("field,value", [("parent_task_id", "replacement-parent"), ("workflow_id", "replacement-workflow"),
                                        ("shot_id", "replacement-shot"), ("status", "running")])
def test_replaced_video_task_actor_is_not_failed_or_attached_by_admission(api, monkeypatch, field, value):
    create = api.task_repo.create_shot_video_task
    def raced(**kwargs):
        task = create(**kwargs)
        with Session(api.engine) as editor:
            setattr(editor.get(api.models.task.Task, task.id), field, value)
            editor.commit()
        return task
    monkeypatch.setattr(api.task_repo, "create_shot_video_task", raced)
    response = api.post("/generate-video", {})
    assert response.status_code == 409
    api.db.expire_all()
    task = api.db.query(api.models.task.Task).one()
    assert getattr(task, field) == value
    assert task.status == ("running" if field == "status" else "pending")
    assert api.queued == []
    assert_unchanged(api)


def test_snapshot_is_captured_after_production_preflight_writes(api, monkeypatch):
    api.writes_forbidden = False
    def sync(shot, repo):
        plan = json.loads(shot.video_director_plan)
        plan["preflight_binding"] = "prepared production input"
        repo.update(shot, video_director_plan=plan)
        return plan
    monkeypatch.setattr(api.module, "_sync_latest_audio_timeline_into_plan", sync)
    task = task_from_response(api, api.post("/generate-video", {}))
    first = json.loads(api.inserts[0]["metadata_json"])["execution"]["shot_snapshot"]
    assert json.loads(first["video_director_plan"])["preflight_binding"] == "prepared production input"
    assert first["video_director_plan_revision"] == api.before["video_director_plan_revision"] + 1
    assert first["video_task_id"] == "old-video"
    assert api.foundation.execution_record(task)["shot_snapshot"] == first


def test_benchmark_never_enters_production_preparation_or_cleanup(api, monkeypatch):
    failed = api.models.task.Task(id="old-failure", type="shot_video", status="failed", name="old failure",
                                  shot_id="shot", novel_id="novel", chapter_id="chapter")
    api.db.add(failed)
    api.db.commit()
    for name in ("_sync_latest_audio_timeline_into_plan", "_mark_video_director_planning_failed",
                 "_ensure_shot_ready_for_batch_video", "_ensure_legacy_keyframe_slots"):
        monkeypatch.setattr(api.module, name, api.forbidden)
    monkeypatch.setattr(api.task_repo, "get_failed_shot_task", api.forbidden)
    monkeypatch.setattr(api.task_repo, "delete", api.forbidden)
    task = task_from_response(api, api.post("/benchmark/generate-video"))
    assert task.id != failed.id and api.db.get(api.models.task.Task, failed.id).status == "failed"
    assert_unchanged(api)


@pytest.mark.parametrize("field,value", [("characters", "broken"), ("video_director_plan", "[]"), ("keyframes", "null")])
def test_invalid_benchmark_source_is_stopped_not_repaired(api, field, value):
    api.writes_forbidden = False
    setattr(api.shot, field, value)
    api.db.commit()
    api.before = api.foundation.create_execution_metadata(api.shot)["execution"]["shot_snapshot"]
    api.shot_updates.clear()
    api.writes_forbidden = True
    response = api.post("/benchmark/generate-video")
    assert response.status_code == 400
    assert response.json()["detail"] == f"BENCHMARK_SOURCE_NOT_READY: {field}"
    assert api.inserts == api.queued == []
    assert_unchanged(api)


@pytest.mark.parametrize("collision", ["standalone", "other-parent", "benchmark-parent", "cancelled-parent"])
def test_batch_link_is_validated_upfront_and_never_reparents_active_task(api, collision):
    api.writes_forbidden = False
    Task = api.models.task.Task
    parent = Task(id="parent", type="shot_video_batch", name="batch", status="cancelled" if collision == "cancelled-parent" else "running",
                  chapter_id="chapter", novel_id="novel", metadata_json=json.dumps({"shot_ids": ["shot"],
                    "execution_purpose": "benchmark" if collision == "benchmark-parent" else "production"}))
    child = Task(id="existing", type="shot_video", name="existing", status="running", chapter_id="chapter", novel_id="novel",
                 shot_id="shot", parent_task_id="other-parent" if collision == "other-parent" else None)
    api.db.add_all([parent, child])
    api.shot.video_task_id = child.id
    api.db.commit()
    with pytest.raises(HTTPException) as error:
        asyncio.run(api.module._generate_shot_video("novel", "chapter", "shot", api.schemas.GenerateVideoRequest(),
                    api.novel_repo, api.chapter_repo, api.task_repo, api.workflow_repo, api.shot_repo, parent_task_id=parent.id, batch_order=1))
    assert error.value.status_code == 409
    assert child.parent_task_id == ("other-parent" if collision == "other-parent" else None)
    assert api.db.query(Task).count() == 2
    assert api.queued == []


def test_parent_cancellation_between_insert_and_admission_is_fenced(api, monkeypatch):
    api.writes_forbidden = False
    parent = task_from_response(api, api.post(ROOT + "/videos/generate-batch", {"shot_ids": ["shot"]}, absolute=True))
    create = api.task_repo.create_shot_video_task
    def cancelled(**kwargs):
        task = create(**kwargs)
        with Session(api.engine) as editor:
            editor.get(api.models.task.Task, parent.id).status = "cancelled"
            editor.commit()
        return task
    monkeypatch.setattr(api.task_repo, "create_shot_video_task", cancelled)
    with pytest.raises(HTTPException) as error:
        asyncio.run(api.module._generate_shot_video("novel", "chapter", "shot", api.schemas.GenerateVideoRequest(),
                    api.novel_repo, api.chapter_repo, api.task_repo, api.workflow_repo, api.shot_repo, parent_task_id=parent.id, batch_order=1))
    assert error.value.status_code == 409
    api.db.refresh(api.shot)
    assert api.shot.video_task_id == parent.id
    assert api.queued == []


def test_benchmark_image_lock_is_not_shared_with_production(api):
    async def run():
        lock = asyncio.Lock()
        api.module.shot_image_generation_locks["novel:chapter:shot:production"] = lock
        async with lock:
            return await api.module.benchmark_generate_shot_image("novel", "chapter", "shot", None, api.db,
                api.novel_repo, api.chapter_repo, api.task_repo, api.workflow_repo, api.shot_repo, api.template_repo, api.llm)
    response = asyncio.run(run())
    assert response["data"]["taskId"]
    assert len(api.queued) == 1
    assert_unchanged(api)


@pytest.mark.parametrize("invalid_metadata", ['{"execution_purpose": null}', '{"execution_purpose": "typo"}', '{"execution": {}}', 'broken'])
def test_invalid_saved_purpose_never_matches_production_lookup_or_cleanup(api, invalid_metadata):
    Task = api.models.task.Task
    task = Task(id="invalid", type="shot_video", name="invalid", shot_id="shot", novel_id="novel", chapter_id="chapter", metadata_json=invalid_metadata)
    api.db.add(task)
    api.db.commit()
    assert api.task_repo.get_active_shot_task("novel", "chapter", 7, "shot_video", shot_id="shot") is None
    task.status = "failed"
    api.db.commit()
    assert api.task_repo.get_failed_shot_task("novel", "chapter", 7, "shot_video", shot_id="shot") is None


def test_batch_child_is_bound_with_full_metadata_before_queue(api, monkeypatch):
    api.writes_forbidden = False
    response = api.post(ROOT + "/videos/generate-batch", {"shot_ids": ["shot"], "auto_complete": False}, absolute=True)
    parent = task_from_response(api, response)
    async def ready(*args, **kwargs):
        return "SINGLE_FRAME"
    monkeypatch.setattr(api.module, "_ensure_shot_ready_for_batch_video", ready)
    def complete(task_id, *args, **kwargs):
        with Session(api.engine) as observer:
            child = observer.get(api.models.task.Task, task_id)
            assert child.parent_task_id == parent.id
            assert child.batch_order == 1
            assert set(api.foundation.execution_record(child)["request"]) == api.execution.REQUEST_KEYS
            first = next(item for item in api.inserts if item["id"] == task_id)
            assert first["parent_task_id"] == parent.id and first["batch_order"] == 1
            child.status = "completed"
            observer.commit()
    api.enqueue_hook = complete
    asyncio.run(api.module.run_shot_video_batch_task(parent.id))
    api.db.refresh(parent)
    assert parent.status == "completed", parent.error_message
    assert len(api.queued) == 1


@pytest.mark.parametrize("explicit", [False, True])
def test_manual_merge_calls_completed_run_barrier_not_live_clip_merge(api, monkeypatch, explicit):
    barrier = Mock(return_value={"success": True, "skipped": True, "video_url": "/verified.mp4", "plan": {"verified": True}})
    monkeypatch.setattr(api.execution, "completed_video_artifact", barrier)
    response = api.post("/video-director/clips/merge" + ("?task_id=explicit-task" if explicit else ""))
    assert response.status_code == 200
    barrier.assert_called_once_with(api.db, "explicit-task" if explicit else "old-video", shot_id="shot")
    assert response.json()["data"] == {"videoUrl": "/verified.mp4", "videoDirectorPlan": {"verified": True}, "skipped": True}
    api.storage.merge_videos.assert_not_awaited()
    assert_unchanged(api)


@pytest.mark.parametrize("kind", ["legacy", "incomplete", "benchmark", "clip"])
def test_manual_merge_rejects_unproven_or_detached_artifact(api, kind):
    options = {"use_keyframes": True, "use_reference_audio": True, "selected_mode": "SINGLE_FRAME", "workflow_id": "video",
               "only_window_index": 1 if kind == "clip" else None, "auto_merge_clips": False, "skip_llm_when_prompt_exists": False}
    data = api.foundation.create_execution_metadata(api.shot, purpose="benchmark" if kind == "benchmark" else "production", request=options)
    if kind == "clip":
        data["video_run"] = {"phase": "completed", "scope": "clip", "result": {}}
    task = api.models.task.Task(id="proof", type="shot_video", name="proof", status="pending" if kind == "incomplete" else "completed",
                               novel_id="novel", chapter_id="chapter", shot_id="shot", workflow_id="video",
                               metadata_json=None if kind == "legacy" else json.dumps(data))
    api.db.add(task)
    api.db.commit()
    response = api.post("/video-director/clips/merge?task_id=proof")
    assert response.status_code == 400
    api.storage.merge_videos.assert_not_awaited()
    assert_unchanged(api)


@pytest.mark.parametrize("active", [True, False])
def test_image_export_uses_active_production_task_not_newest_benchmark(api, active):
    api.writes_forbidden = False
    api.shot.image_task_id = "active-image" if active else None
    now = datetime.utcnow()
    for task_id, purpose, age in (("active-image", "production", 2), ("other-production", "production", 1), ("newest-benchmark", "benchmark", 0)):
        api.db.add(api.models.task.Task(id=task_id, type="shot_image", name=task_id, status="completed", shot_id="shot", novel_id="novel",
                                       chapter_id="chapter", prompt_text=task_id, workflow_json=json.dumps({"task": task_id}),
                                       created_at=now - timedelta(seconds=age), metadata_json=json.dumps({"execution_purpose": purpose})))
    api.db.commit()
    response = api.module._build_shot_image_data_response(api.db, "novel", "chapter", api.chapter, [api.shot], "test.zip")
    async def contents():
        return b"".join([chunk async for chunk in response.body_iterator])
    with zipfile.ZipFile(BytesIO(asyncio.run(contents()))) as archive:
        prompt_path = next(name for name in archive.namelist() if name.endswith(".txt"))
        assert archive.read(prompt_path).decode() == ("active-image" if active else "other-production")
        assert b"newest-benchmark" not in b"".join(archive.read(name) for name in archive.namelist())


def test_ordinary_image_and_keyframe_defaults_retain_production_behavior(api):
    api.writes_forbidden = False
    image = task_from_response(api, api.post("/generate", {"prompt_text": "Production prompt"}))
    api.db.refresh(api.shot)
    assert api.foundation.execution_purpose(image) == "production"
    assert api.shot.shot_image_prompt == "Production prompt"
    assert api.shot.image_url is None and api.shot.image_status == "generating"
    api.storage.delete_shot_image.assert_called_once()
    keyframe = task_from_response(api, api.post("/keyframes/0/generate-image", {}))
    assert api.foundation.execution_purpose(keyframe) == "production"
    api.db.refresh(api.shot)
    assert json.loads(api.shot.keyframes)[0]["image_task_id"] == keyframe.id


def interrupted_video_batch(api, submission_state="submitting", *, parent_status="running", child_status="running"):
    api.writes_forbidden = False
    parent = task_from_response(api, api.post(ROOT + "/videos/generate-batch", {"shot_ids": ["shot"]}, absolute=True))
    response = asyncio.run(api.module._generate_shot_video(
        "novel", "chapter", "shot", api.schemas.GenerateVideoRequest(), api.novel_repo, api.chapter_repo,
        api.task_repo, api.workflow_repo, api.shot_repo, parent_task_id=parent.id, batch_order=1,
    ))
    child = api.db.get(api.models.task.Task, response["data"]["taskId"])
    if submission_state is not None:
        _, _, handle = api.execution.claim_video_execution(api.db, child.id)
        def record_intent(data):
            slot = next(iter(data["video_run"]["clips"].values()))
            slot["submission"] = {"state": submission_state, "endpoint": "http://never-contact.invalid",
                                  "graph": {"out": {"class_type": "SaveVideo", "inputs": {}}}, "output_node": "out"}
            if submission_state == "acknowledged":
                slot["submission"]["prompt_id"] = "remote-slot-cid"
        api.execution._write(api.db, handle, record_intent)
    saved_time = datetime(2026, 9, 7, 12, 34, 56)
    child.status = child_status
    child.comfyui_prompt_id = None
    child.result_url = "/partial-attempt-evidence.mp4"
    child.completed_at = saved_time
    child.error_message = "preserve original child diagnostic"
    parent.status = parent_status
    parent.started_at = saved_time
    parent.completed_at = saved_time
    parent.result_url = "/previous-parent-result.mp4"
    metadata = json.loads(parent.metadata_json)
    metadata.update(results={"shot": {"status": "running", "taskId": child.id}}, audit_note="preserve original options and results")
    parent.metadata_json = json.dumps(metadata)
    api.db.commit()
    api.db.refresh(api.shot)
    api.before = api.foundation.create_execution_metadata(api.shot)["execution"]["shot_snapshot"]
    api.writes_forbidden = True
    api.shot_updates.clear()
    api.inserts.clear()
    api.queued.clear()
    api.enqueue.reset_mock()
    return parent, child


@pytest.mark.parametrize("submission,parent_status,child_status", [
    ("submitting", "running", "running"), ("unknown", "running", "running"),
    ("acknowledged", "running", "running"), ("not_submitted", "running", "running"),
    (None, "running", "pending"), ("submitting", "pending", "pending"),
    ("unknown", "pending", "failed"), ("acknowledged", "pending", "completed"),
])
def test_restart_holds_strict_video_batch_without_replacing_or_rewriting_attempt(api, monkeypatch, submission, parent_status, child_status):
    parent, child = interrupted_video_batch(api, submission, parent_status=parent_status, child_status=child_status)
    before_child = {column.key: getattr(child, column.key) for column in api.models.task.Task.__table__.columns}
    before_parent = {key: getattr(parent, key) for key in ("metadata_json", "result_url", "started_at", "completed_at")}
    monkeypatch.setattr(api.module, "_ensure_shot_ready_for_batch_video", api.forbidden)
    monkeypatch.setattr(api.module, "_generate_shot_video", api.forbidden)
    api.module.resume_active_shot_video_batches()
    assert asyncio.run(api.module.run_next_persistent_shot_video_batch_task()) is False
    asyncio.run(api.module.run_shot_video_batch_task(parent.id))
    api.module.resume_active_shot_video_batches()
    api.db.refresh(parent)
    api.db.refresh(child)
    assert parent.status == "failed"
    assert "BATCH_EXECUTION_REVIEW_REQUIRED" in parent.error_message
    assert {column.key: getattr(child, column.key) for column in api.models.task.Task.__table__.columns} == before_child
    assert {key: getattr(parent, key) for key in before_parent} == before_parent
    assert api.db.query(api.models.task.Task).count() == 2
    assert api.inserts == api.queued == []
    api.enqueue.assert_not_called()
    assert_unchanged(api)


def test_pending_batch_cannot_bypass_restart_guard_or_retry_a_strict_failed_child(api, monkeypatch):
    parent, child = interrupted_video_batch(api, "unknown", parent_status="pending", child_status="failed")
    before = {column.key: getattr(child, column.key) for column in api.models.task.Task.__table__.columns}
    with pytest.raises(HTTPException) as error:
        asyncio.run(api.module._generate_shot_video(
            "novel", "chapter", "shot", api.schemas.GenerateVideoRequest(), api.novel_repo, api.chapter_repo,
            api.task_repo, api.workflow_repo, api.shot_repo, parent_task_id=parent.id, batch_order=1,
        ))
    assert error.value.status_code == 409
    assert "BATCH_EXECUTION_REVIEW_REQUIRED" in error.value.detail
    monkeypatch.setattr(api.module, "_ensure_shot_ready_for_batch_video", api.forbidden)
    assert asyncio.run(api.module.run_next_persistent_shot_video_batch_task()) is True
    assert asyncio.run(api.module.run_next_persistent_shot_video_batch_task()) is False
    api.db.refresh(parent)
    api.db.refresh(child)
    assert parent.status == "failed"
    assert {column.key: getattr(child, column.key) for column in api.models.task.Task.__table__.columns} == before
    assert api.inserts == api.queued == []
    assert_unchanged(api)


def test_terminal_children_cannot_leave_parent_permanently_running(api):
    api.writes_forbidden = False
    Task = api.models.task.Task
    parent = Task(id="stranded-parent", type="shot_video_batch", status="running", name="stranded",
        novel_id="novel", chapter_id="chapter", started_at=datetime(2026, 9, 7),
        metadata_json=json.dumps({"execution_purpose":"production","shot_ids":["shot"],"selected_modes":{},
            "auto_complete":True,"skip_llm_when_prompt_exists":False,"results":{}}))
    child = Task(id="terminal-child", type="shot_video", status="failed", name="terminal",
        novel_id="novel", chapter_id="chapter", shot_id="shot", parent_task_id=parent.id,batch_order=1,
        error_message="preserve child diagnostic",completed_at=datetime(2026,9,7))
    api.db.add_all([parent,child]);api.db.commit()
    before_child = {column.key: getattr(child, column.key) for column in api.models.task.Task.__table__.columns}
    api.writes_forbidden = True;api.inserts.clear();api.queued.clear()
    settled = api.module.settle_stranded_video_batches(api.db, stale_seconds=0)
    api.db.refresh(parent);api.db.refresh(child)
    assert settled == [parent.id] and parent.status == "failed"
    assert parent.error_message.startswith("BATCH_WORKER_INTERRUPTED")
    assert {column.key: getattr(child, column.key) for column in api.models.task.Task.__table__.columns} == before_child
    assert api.db.query(api.models.task.Task).count() == 2
    assert api.inserts == api.queued == []


@pytest.mark.parametrize("legacy", [False, True])
def test_restart_only_recovers_unattempted_batch_with_explicit_options(api, monkeypatch, legacy):
    api.writes_forbidden = False
    parent = task_from_response(api, api.post(ROOT + "/videos/generate-batch", {
        "shot_ids": ["shot"], "selected_modes": {"shot": "FIRST_LAST_FRAME"},
        "auto_complete": False, "skip_llm_when_prompt_exists": True,
    }, absolute=True))
    parent.status = "running"
    if legacy:
        saved = json.loads(parent.metadata_json)
        saved.pop("execution_purpose")
        parent.metadata_json = json.dumps(saved)
    api.db.commit()
    before = parent.metadata_json
    api.module.resume_active_shot_video_batches()
    api.db.refresh(parent)
    assert parent.status == "pending" and parent.started_at is None
    assert parent.metadata_json == before
    assert api.db.query(api.models.task.Task).count() == 1
    api.enqueue.assert_not_called()
    ready = AsyncMock(return_value="FIRST_LAST_FRAME")
    monkeypatch.setattr(api.module, "_ensure_shot_ready_for_batch_video", ready)
    def complete(task_id, *args, **kwargs):
        with Session(api.engine) as editor:
            task = editor.get(api.models.task.Task, task_id)
            assert task.parent_task_id == parent.id and task.batch_order == 1
            request = api.foundation.execution_record(task)["request"]
            assert request["selected_mode"] == "FIRST_LAST_FRAME" and request["skip_llm_when_prompt_exists"] is True
            task.status = "completed"
            editor.commit()
    api.enqueue_hook = complete
    assert asyncio.run(api.module.run_next_persistent_shot_video_batch_task()) is True
    assert ready.call_args.args[3] == "FIRST_LAST_FRAME" and ready.call_args.kwargs["auto_complete"] is False
    assert len(api.queued) == 1
    assert api.db.query(api.models.task.Task).count() == 2
    api.db.refresh(parent)
    assert parent.status == "completed"
    assert asyncio.run(api.module.run_next_persistent_shot_video_batch_task()) is False


@pytest.mark.parametrize("defect", ["auto_complete", "skip_llm_when_prompt_exists", "selected_modes", "shot_ids", "started_at", "results"])
def test_restart_without_explicit_options_or_no_attempt_proof_is_held(api, defect):
    api.writes_forbidden = False
    parent = task_from_response(api, api.post(ROOT + "/videos/generate-batch", {"shot_ids": ["shot"]}, absolute=True))
    saved = json.loads(parent.metadata_json)
    if defect == "results":
        saved["results"] = {"shot": {"taskId": "missing-child", "status": "running"}}
    elif defect == "started_at":
        parent.started_at = datetime(2026, 9, 7)
    else:
        saved.pop(defect)
    parent.metadata_json = json.dumps(saved)
    parent.status = "running"
    api.db.commit()
    original = parent.metadata_json
    api.inserts.clear()
    api.writes_forbidden = True
    api.module.resume_active_shot_video_batches()
    api.db.refresh(parent)
    assert parent.status == "failed"
    assert parent.error_message.startswith("BATCH_EXECUTION_REVIEW_REQUIRED" if defect in {"results", "started_at"} else "BATCH_EXPLICIT_OPTIONS_REQUIRED")
    assert parent.metadata_json == original
    assert api.inserts == api.queued == []
    assert asyncio.run(api.module.run_next_persistent_shot_video_batch_task()) is False


@pytest.mark.parametrize("kind", ["shot_image_batch", "shot_video_batch"])
@pytest.mark.parametrize("benchmark_on", ["parent", "child"])
@pytest.mark.parametrize("entry", ["startup", "enqueue", "worker"])
def test_persisted_benchmark_batches_are_blocked_at_startup_enqueue_and_worker(api, kind, benchmark_on, entry):
    Task = api.models.task.Task
    parent = Task(id="blocked-parent", type=kind, status="running" if entry == "startup" else "pending", name="blocked parent", novel_id="novel", chapter_id="chapter",
                  metadata_json=json.dumps({"execution_purpose": "benchmark" if benchmark_on == "parent" else "production",
                                             "shot_ids": ["shot"], "selected_modes": {}, "auto_complete": False, "skip_llm_when_prompt_exists": False}))
    child = Task(id="blocked-child", type="shot_image" if kind == "shot_image_batch" else "shot_video", status="running",
                 name="blocked child", novel_id="novel", chapter_id="chapter", shot_id="shot", parent_task_id=parent.id,
                 metadata_json=json.dumps(api.foundation.create_execution_metadata(api.shot, purpose="benchmark")),
                 result_url="/archived-evidence.png", completed_at=datetime(2026, 9, 7))
    api.db.add_all([parent, child])
    api.db.commit()
    before = {column.key: getattr(child, column.key) for column in Task.__table__.columns}
    api.inserts.clear()
    if kind == "shot_image_batch":
        if entry == "startup":
            api.module.resume_active_shot_image_batches()
        elif entry == "enqueue":
            api.module.enqueue_shot_image_batch_task(parent.id)
        asyncio.run(api.module.run_shot_image_batch_task(parent.id))
    else:
        if entry == "startup":
            api.module.resume_active_shot_video_batches()
        elif entry == "enqueue":
            assert asyncio.run(api.module.run_next_persistent_shot_video_batch_task()) is True
        asyncio.run(api.module.run_shot_video_batch_task(parent.id))
    api.db.refresh(parent)
    api.db.refresh(child)
    assert parent.status == "failed" and parent.error_message == "BENCHMARK_BATCH_UNSUPPORTED"
    assert {column.key: getattr(child, column.key) for column in Task.__table__.columns} == before
    assert api.inserts == api.queued == []
    assert_unchanged(api)


def test_restart_hold_cas_does_not_overwrite_a_newer_parent_actor(api):
    parent, child = interrupted_video_batch(api)
    before_child = {column.key: getattr(child, column.key) for column in api.models.task.Task.__table__.columns}
    reason = api.module._batch_start_error(api.db, parent)
    with Session(api.engine) as editor:
        current = editor.get(api.models.task.Task, parent.id)
        current.status = "cancelled"
        current.error_message = "Newer cancellation"
        current.metadata_json = '{"cancelled_actor": true}'
        editor.commit()
    api.module._hold_batch_task(api.db, parent, reason)
    api.db.refresh(parent)
    api.db.refresh(child)
    assert (parent.status, parent.error_message, parent.metadata_json) == ("cancelled", "Newer cancellation", '{"cancelled_actor": true}')
    assert {column.key: getattr(child, column.key) for column in api.models.task.Task.__table__.columns} == before_child
    assert api.inserts == api.queued == []
    assert_unchanged(api)


@pytest.mark.parametrize("failure,change,settled", [
    (failure, change, True)
    for failure in ("failed", "cancelled", "timeout", "preclaim-failed", "preclaim-cancelled")
    for change in ("none", "owner", "plan")
] + [("failed", change, True) for change in ("missing", "detached", "callback-error")]
  + [(failure, "none", False) for failure in ("preclaim-failed", "preclaim-cancelled")])
def test_batch_preserves_strict_child_terminal_settlement(api, monkeypatch, failure, change, settled):
    api.writes_forbidden = False
    parent = task_from_response(api, api.post(ROOT + "/videos/generate-batch", {"shot_ids": ["shot"]}, absolute=True))
    monkeypatch.setattr(api.module, "_ensure_shot_ready_for_batch_video", AsyncMock(return_value="SINGLE_FRAME"))
    observed = {}
    message = "VIDEO_TIMEOUT" if failure == "timeout" else f"Strict child {failure}"

    def terminate(task_id, *args, **kwargs):
        with Session(api.engine, autoflush=False) as worker:
            child = worker.get(api.models.task.Task, task_id)
            assert child.parent_task_id == parent.id
            source = worker.get(api.models.shot.Shot, "shot")
            assert source.video_status == "generating" and source.video_task_id == child.id
            assert source.video_url == "/old.mp4"
            original_plan = source.video_director_plan
            original_revision = source.video_director_plan_revision
            if not failure.startswith("preclaim"):
                child, _, handle = api.execution.claim_video_execution(worker, child.id)
            if change in {"owner", "plan"}:
                with Session(api.engine) as editor:
                    newer = editor.get(api.models.shot.Shot, "shot")
                    if change == "owner":
                        newer.video_task_id = "newer-owner"
                        newer.video_url = "/newer-video.mp4"
                    newer.video_director_plan = '{"newer_source": true}'
                    newer.video_director_plan_revision += 1
                    editor.commit()
            if failure.startswith("preclaim"):
                count = worker.query(api.models.task.Task).filter(
                    api.models.task.Task.id == child.id, api.models.task.Task.status == "pending",
                    api.models.task.Task.metadata_json == child.metadata_json,
                ).update({"status": "cancelled" if failure.endswith("cancelled") else "failed",
                          "error_message": message, "completed_at": datetime.utcnow()}, synchronize_session=False)
                assert count == 1
                worker.refresh(child)
                if settled:
                    assert api.execution.settle_terminated_video(worker, child) is (change == "none")
                worker.commit()
            elif failure == "cancelled":
                def cancel(data):
                    data["video_run"]["phase"] = "cancelled"
                    return {"status": "cancelled", "error_message": message, "completed_at": datetime.utcnow()}
                api.execution._write(worker, handle, cancel, target=False, parent_active=False)
            else:
                assert api.execution.fail_execution(worker, handle, message, clip_index=1)
            worker.refresh(source)
            if change not in {"owner", "plan"}:
                assert source.video_status == ("failed" if settled else "generating")
                assert (source.video_url, source.video_director_plan, source.video_director_plan_revision, source.video_task_id) == (
                    "/old.mp4", original_plan, original_revision, child.id)
            else:
                assert source.video_status == "generating"
            if change == "detached":
                child.parent_task_id = None
                worker.commit()
            worker.refresh(child)
            observed["child_id"] = child.id
            observed["child"] = {column.key: getattr(child, column.key) for column in api.models.task.Task.__table__.columns}
            observed["shot"] = {column.key: getattr(source, column.key) for column in api.models.shot.Shot.__table__.columns}
            if change == "missing":
                worker.delete(child)
                worker.commit()
        api.shot_updates.clear()
        api.writes_forbidden = settled
        if change == "callback-error":
            raise RuntimeError("Callback failed after strict settlement")

    api.enqueue_hook = terminate
    asyncio.run(api.module.run_shot_video_batch_task(parent.id))
    api.db.refresh(parent)
    api.db.refresh(api.shot)
    assert parent.status == "failed" and parent.error_message
    result = json.loads(parent.metadata_json)["results"]["shot"]
    assert result["status"] == "failed"
    if change == "callback-error":
        assert result["message"] == "Callback failed after strict settlement"
    else:
        assert result["taskId"] == observed["child_id"]
        if change == "missing":
            assert result["message"]
        else:
            assert result["message"] == message
    for key, value in observed["shot"].items():
        if not settled and key in {"video_status", "updated_at"}:
            continue
        assert getattr(api.shot, key) == value, key
    if settled:
        assert api.shot_updates == []
    else:
        assert api.shot.video_status == "failed"
        assert len(api.shot_updates) == 1
        assert "video_director_plan" not in api.shot_updates[0].split(" WHERE ", 1)[0]
    child = api.db.get(api.models.task.Task, observed["child_id"])
    if change == "missing":
        assert child is None
    else:
        assert {column.key: getattr(child, column.key) for column in api.models.task.Task.__table__.columns} == observed["child"]
    assert len(api.queued) == 1
    api.storage.delete_shot_video.assert_not_called()


@pytest.mark.parametrize("stage", ["admission", "outer-setup"])
def test_batch_exception_does_not_apply_legacy_failure_to_unattached_strict_attempt(api, monkeypatch, stage):
    api.writes_forbidden = False
    parent = task_from_response(api, api.post(ROOT + "/videos/generate-batch", {"shot_ids": ["shot"]}, absolute=True))
    observed = {}

    def fail_after_insert(db):
        source = db.get(api.models.shot.Shot, "shot")
        child = api.models.task.Task(id="unattached-strict-child", type="shot_video", name="Unattached execution", status="failed",
            novel_id="novel", chapter_id="chapter", shot_id="shot", parent_task_id=parent.id, batch_order=1, workflow_id="video",
            error_message="Preclaim failure", completed_at=datetime.utcnow(), metadata_json=json.dumps(api.foundation.create_execution_metadata(
                source, request={"use_keyframes": True, "use_reference_audio": True, "selected_mode": "SINGLE_FRAME",
                                 "workflow_id": "video", "only_window_index": None, "auto_merge_clips": False,
                                 "skip_llm_when_prompt_exists": False})))
        db.add(child)
        db.commit()
        assert api.execution.settle_terminated_video(db, child) is False
        observed["shot"] = {column.key: getattr(source, column.key) for column in api.models.shot.Shot.__table__.columns}
        observed["child"] = {column.key: getattr(child, column.key) for column in api.models.task.Task.__table__.columns}
        api.writes_forbidden = True
        api.shot_updates.clear()
        raise RuntimeError("Failure after durable strict attempt")

    async def admission(*args, **kwargs):
        fail_after_insert(kwargs["task_repo"].db)

    monkeypatch.setattr(api.module, "_ensure_shot_ready_for_batch_video", AsyncMock(return_value="SINGLE_FRAME"))
    if stage == "outer-setup":
        monkeypatch.setattr(api.module, "NovelRepository", fail_after_insert)
    else:
        monkeypatch.setattr(api.module, "_generate_shot_video", admission)
    asyncio.run(api.module.run_shot_video_batch_task(parent.id))
    api.db.refresh(parent)
    api.db.refresh(api.shot)
    assert parent.status == "failed"
    if stage == "outer-setup":
        assert parent.error_message == "Failure after durable strict attempt"
    else:
        assert json.loads(parent.metadata_json)["results"]["shot"]["message"] == "Failure after durable strict attempt"
    assert {column.key: getattr(api.shot, column.key) for column in api.models.shot.Shot.__table__.columns} == observed["shot"]
    child = api.db.get(api.models.task.Task, "unattached-strict-child")
    assert {column.key: getattr(child, column.key) for column in api.models.task.Task.__table__.columns} == observed["child"]
    assert api.shot_updates == api.queued == []


@pytest.mark.parametrize("owner_kind", ["shot_video_batch", "shot_video"])
def test_legacy_batch_failure_with_old_video_is_not_misclassified_as_strict(api, owner_kind):
    api.writes_forbidden = False
    owner = api.models.task.Task(id="legacy-owner", type=owner_kind, name="Legacy owner", status="running",
                                novel_id="novel", chapter_id="chapter", shot_id="shot" if owner_kind == "shot_video" else None)
    other_execution = api.foundation.create_execution_metadata(api.shot)
    for key in ("shot_snapshot", "working_shot"):
        other_execution["execution"][key]["id"] = "other-shot"
    unrelated = api.models.task.Task(id="unrelated-strict", type="shot_video", name="Other shot attempt", status="failed",
                                    parent_task_id=owner.id, shot_id="other-shot", novel_id="novel", chapter_id="chapter",
                                    metadata_json=json.dumps(other_execution))
    api.db.add_all([owner, unrelated])
    api.shot.video_task_id = owner.id
    api.shot.video_status = "generating"
    api.db.commit()
    revision = api.shot.video_director_plan_revision
    api.module._persist_batch_video_failure(api.db, "shot", owner.id, "Legacy failure")
    api.db.commit()
    api.db.refresh(api.shot)
    assert api.shot.video_status == "completed" and api.shot.video_url == "/old.mp4"
    assert api.shot.video_director_plan_revision == revision + 1
    assert json.loads(api.shot.video_director_plan)["task_error_message"] == "Legacy failure"
