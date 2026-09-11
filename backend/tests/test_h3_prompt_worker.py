"""Isolated worker tests: --noconftest, no app startup, disk media, or network."""

import asyncio
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import socket
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import Boolean, Column, String, create_engine
from sqlalchemy.orm import Session, declarative_base, relationship


BACKEND = Path(__file__).resolve().parents[1]
HISTORY = json.loads(Path(__file__).with_name("h3_prompt_gate_fixtures.json").read_text(encoding="utf-8"))
PROMPT = (
    "subject_definitions:\n<Subject 1>: Ada in a blue coat. <Subject 2>: Bea in red.\n"
    "summary:\nTwo people wait beside the gate.\n"
    "detailed_description:\nThe camera moves slowly towards the gate.\n"
    "overall_soundscape:\nQuiet wind rustles the leaves.\n"
    "initial_state_anchor:\nBoth people stand beside the gate."
)
CONSTRAINT = (
    "drive_audio controls lip-sync only. Never transcribe audio. Spoken audio must remain audio only. "
    "No subtitles, no captions, no audio transcription."
)
MISSING = object()


@pytest.fixture
def worker(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Real application I/O is forbidden")

    monkeypatch.setattr(socket.socket, "connect", forbidden)

    def stub(name, **attributes):
        module = ModuleType(name)
        module.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, module)
        return module

    for name in ("app", "app.models", "app.core", "app.repositories", "app.services",
                 "app.services.llm", "app.services.comfyui", "app.utils"):
        stub(name, __path__=[])

    def load(name, relative):
        spec = importlib.util.spec_from_file_location(name, BACKEND / relative)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        return module

    base = declarative_base()
    stub("app.core.database", Base=base, SessionLocal=forbidden)

    class Novel(base):
        __tablename__ = "novels"
        id = Column(String, primary_key=True)
        aspect_ratio = Column(String, default="16:9")
        style_prompt_template_id = Column(String)

    class Chapter(base):
        __tablename__ = "chapters"
        id = Column(String, primary_key=True)
        novel_id = Column(String)
        shots = relationship("Shot", back_populates="chapter")

    class Character(base):
        __tablename__ = "characters"
        id = Column(String, primary_key=True)
        novel_id = Column(String)
        name = Column(String)
        appearance = Column(String)
        is_narrator = Column(Boolean, default=False)

    class Prop(base):
        __tablename__ = "props"
        id = Column(String, primary_key=True)
        novel_id = Column(String)
        name = Column(String)
        appearance = Column(String)

    stub("app.models.novel", Novel=Novel, Chapter=Chapter, Character=Character, Prop=Prop)
    shot_model = load("app.models.shot", "app/models/shot.py").Shot
    task_model = load("app.models.task", "app/models/task.py").Task
    workflow_model = load("app.models.workflow", "app/models/workflow.py").Workflow
    timeline_model = load("app.models.audio_drive", "app/models/audio_drive.py").ShotAudioTimeline
    engine = create_engine("sqlite:///:memory:")
    base.metadata.create_all(engine)
    db = Session(engine)
    monkeypatch.setattr(sys.modules["app.core.database"], "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    state = SimpleNamespace(db=db, engine=engine, events=[], queued=[], prequeue=[], files={}, upload_hook=None,
                            queue_error=None, queue_failure=False, upload_failure=False, wait_failure=False)
    state.novel = Novel(id="novel")
    state.shot = shot_model(id="shot", chapter_id="chapter", index=1, description="Two people wait beside a gate.",
                            characters=json.dumps(["Ada", "Bea"]), props="[]", duration=4, estimated_duration=4,
                            video_description="The camera moves towards the gate.", image_url="/api/files/start.png",
                            audio_status="READY", video_task_id="task", video_url="/old-shot.mp4")
    state.task = task_model(id="task", type="shot_video", status="running", name="Test video", description="Test",
                            novel_id="novel", chapter_id="chapter", shot_id="shot", workflow_id="workflow",
                            metadata_json=json.dumps({"unrelated": "keep"}), comfyui_prompt_id="previous-task-prompt")
    state.workflow = workflow_model(id="workflow", name="Not a graph classification hint", type="video", workflow_json="{}")
    state.timeline = timeline_model(id="timeline", shot_id="shot", revision=1, status="READY", generated_from_hash="hash")
    db.add_all([state.novel, Chapter(id="chapter", novel_id="novel"), state.shot, state.task, state.workflow,
                state.timeline, Character(id="ada", novel_id="novel", name="Ada", appearance="blue coat"),
                Character(id="bea", novel_id="novel", name="Bea", appearance="red coat")])
    db.commit()

    load("app.services.duration_contract", "app/services/duration_contract.py")
    load("app.repositories.shot_repository", "app/repositories/shot_repository.py")
    state.plans = load("app.services.video_director_plan_service", "app/services/video_director_plan_service.py")
    stub("app.core.config", get_settings=lambda: SimpleNamespace(LLM_TIMEOUT=1))
    stub("app.repositories.prompt_template", PromptTemplateRepository=forbidden)
    stub("app.services.prompt_builder", get_style=lambda *args: ("isolated painterly style", None))
    stub("app.services.llm.base", mark_matching_pending_llm_logs_error=Mock())
    state.llm = AsyncMock(return_value={"success": True, "content": PROMPT})
    stub("app.services.llm_service", LLMService=lambda: SimpleNamespace(chat_completion=state.llm))
    load("app.services.h3_prompt_validation", "app/services/h3_prompt_validation.py")
    state.ai = load("app.services.video_director_ai", "app/services/video_director_ai.py")
    state.template = SimpleNamespace(
        name="Isolated template", template="\u3010Audio Drive \u6587\u672c\u6e32\u67d3\u7981\u4ee4\u3011\n" + CONSTRAINT,
    )
    monkeypatch.setattr(state.ai, "resolve_prompt_template", lambda *args: state.template)

    async def upload(path):
        state.events.append("upload")
        if state.upload_hook:
            hook, state.upload_hook = state.upload_hook, None
            hook()
        return {"success": not state.upload_failure, "filename": f"uploaded/{Path(path).name}", "message": "upload failed"}

    async def queue(graph):
        state.events.append("queue")
        state.queued.append(deepcopy(graph))
        state.prequeue.append(deepcopy(records(state)))
        if state.queue_error:
            raise state.queue_error
        return {"success": not state.queue_failure, "prompt_id": f"queued-{len(state.queued)}", "error": "queue unavailable"}

    async def wait(*args, **kwargs):
        state.events.append("wait")
        return {"success": not state.wait_failure, "video_url": "/generated.mp4", "message": "execution failed" if state.wait_failure else ""}

    state.client = SimpleNamespace(upload_image=AsyncMock(side_effect=upload), upload_audio=AsyncMock(side_effect=upload),
                                   queue_prompt=AsyncMock(side_effect=queue), wait_for_result=AsyncMock(side_effect=wait))
    stub("app.services.comfyui.client", ComfyUIClient=lambda: state.client)
    load("app.utils.workflow_disconnect", "app/utils/workflow_disconnect.py")
    load("app.services.comfyui.workflows", "app/services/comfyui/workflows.py")
    state.comfy = load("app.services.comfyui.service", "app/services/comfyui/service.py")
    monkeypatch.setattr(sys.modules["app.services.comfyui"], "ComfyUIService", state.comfy.ComfyUIService, raising=False)
    state.storage = SimpleNamespace(base_dir=Path("/virtual"), download_video=AsyncMock(return_value="/virtual/generated.mp4"),
                                    merge_videos=AsyncMock(side_effect=forbidden), _get_story_dir=forbidden)
    stub("app.services.file_storage", file_storage=state.storage)
    state.matches_sources = Mock(return_value=True)
    stub("app.services.rendered_subtitles", load=lambda path: None, lock_generated_audio=AsyncMock(),
         matches_sources=state.matches_sources)
    stub("app.services.background_workers", worker_manager=SimpleNamespace(worker=forbidden))
    stub("app.services.audio_drive_service", AudioDriveService=forbidden)
    stub("app.utils.path_utils", url_to_local_path=lambda value: value.replace("/api/files/", "/virtual/") if value else None,
         local_path_to_url=lambda value: value.replace("/virtual/", "/api/files/") if value else None)
    state.module = load("app.services.shot_video_service", "app/services/shot_video_service.py")
    state.builder = AsyncMock(wraps=state.module.build_h3_video_prompt)
    monkeypatch.setattr(state.module, "build_h3_video_prompt", state.builder)

    class MediaPath:
        def __init__(self, value):
            self.value = str(value)
            self.name = Path(value).name

        def is_file(self):
            return self.value in state.files

        def __str__(self):
            return self.value

        exists = is_file
        stat = forbidden
        unlink = forbidden

    monkeypatch.setattr(state.module, "Path", MediaPath)
    state.models = SimpleNamespace(Shot=shot_model, Task=task_model, Character=Character, Prop=Prop, Timeline=timeline_model)

    def configure(mode="SINGLE_FRAME", *, windows=1, frames=3, prompt=MISSING, audio=True, audio_collection=None):
        state.mode = mode
        state.workflow.type = {"SINGLE_FRAME": "video", "FIRST_LAST_FRAME": "first_last_video",
                               "MULTI_KEYFRAME": "three_frame_video" if frames == 3 else "four_frame_video"}[mode]
        state.graph = {
            "text": {"class_type": "CR Prompt Text", "inputs": {"prompt": "old"}},
            "h3": {"class_type": "MiniMaxH3AudioConditioningT8" if audio else "MiniMaxH3ReferenceToVideo",
                   "inputs": {"prompt": ["text", 0], "drive_audio": ["drive", 0], "final_audio": ["final", 0]}},
            "image": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
            "kf1": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
            "kf2": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
            "kf3": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
            "drive": {"class_type": "LoadAudio", "inputs": {"audio": "old.wav"}},
            "final": {"class_type": "LoadAudio", "inputs": {"audio": "old.wav"}},
            "out": {"class_type": "SaveVideo", "inputs": {"video": ["h3", 1]}},
        }
        state.mapping = {"prompt_node_id": "text", "video_save_node_id": "out", "reference_image_node_id": "image",
                         "first_image_node_id": "image", "last_image_node_id": "kf1",
                         "keyframe_node_1": "kf1", "keyframe_node_2": "kf2", "keyframe_node_3": "kf3"}
        if audio:
            state.mapping.update(drive_audio_node_id="drive", final_audio_node_id="final")
        state.workflow.workflow_json = json.dumps(state.graph)
        state.workflow.node_mapping = json.dumps(state.mapping)
        keyframes = [{"index": index, "role": "START" if index == 1 else "END" if index == frames else "INTERMEDIATE",
                      "time_seconds": (index - 1) * 2, "description": f"Visual state {index}",
                      "image_url": f"/api/files/kf{index}.png"} for index in range(1, windows * frames + 1)]
        items = []
        for index in range(1, windows + 1):
            item = {"window_index" if mode == "MULTI_KEYFRAME" else "clip_index": index,
                    "start_time": (index - 1) * 4, "end_time": index * 4, "status": "SUCCEEDED",
                    "video_url": f"/old-clip-{index}.mp4", "user_note": "keep my edit"}
            if mode == "MULTI_KEYFRAME":
                item.update(selected_frame_count=frames, workflow_key=f"{frames}_frames",
                            keyframe_indexes=list(range((index - 1) * frames + 1, index * frames + 1)))
            if prompt is not MISSING:
                item["prompt_text"] = prompt
            if audio:
                item.update(audio_status="READY", audio_timeline_id="timeline", audio_timeline_revision=1,
                            audio_timeline_hash="hash", clip_audio_duration=4,
                            drive_audio_path=f"/virtual/drive-{index}.wav", final_audio_path=f"/virtual/final-{index}.wav",
                            speaker_timeline=[{"start_time": 0, "end_time": 4, "visible_speaker": "NONE"}])
                for field in ("drive_audio_path", "final_audio_path"):
                    state.files[item[field]] = SimpleNamespace(st_size=100, st_mtime_ns=1)
            items.append(item)
        state.collection = "window_plans" if mode == "MULTI_KEYFRAME" else "clips"
        plan = {"selected_mode": mode, state.collection: items, "keyframes": keyframes,
                "audio_timeline": {"id": "timeline", "revision": 1, "source_hash": "hash"}}
        if audio_collection and audio_collection != state.collection:
            plan[audio_collection] = [{
                "window_index": item.get("clip_index") or item.get("window_index"),
                "start_time": item["start_time"], "end_time": item["end_time"],
                **{field: item.pop(field) for field in list(item)
                   if field.startswith(("audio_", "drive_audio_", "final_audio_", "clip_audio_", "speaker_"))},
            } for item in items]
        state.shot.video_director_plan = json.dumps(plan)
        db.commit()
        state.clip = {**items[0], "clip_index": 1}
        state.audio = state.module._resolve_audio_drive_for_h3(json.loads(state.shot.video_director_plan), state.clip, state.mapping)

    state.configure = configure
    configure()
    yield state
    Session.close(db)
    engine.dispose()


def records(worker, clip_index=None):
    worker.db.refresh(worker.task)
    clips = json.loads(worker.task.metadata_json).get("h3_prompt_gate", {}).get("clips", {})
    return clips if clip_index is None else clips[str(clip_index)]


def edit_plan(worker, mutate):
    with Session(worker.engine) as editor:
        shot = editor.get(worker.models.Shot, "shot")
        plan = json.loads(shot.video_director_plan)
        mutate(plan)
        shot.video_director_plan = json.dumps(plan)
        shot.video_director_plan_revision += 1
        editor.commit()


def build(worker, *, reuse=False):
    plan = json.loads(worker.shot.video_director_plan)
    return asyncio.run(worker.module._build_h3_prompt_for_worker(
        db=worker.db, task=worker.task, novel=worker.novel, shot=worker.shot, selected_mode=worker.mode,
        clip=worker.clip, workflow=worker.workflow, workflow_capability={}, start_image_url=worker.shot.image_url,
        keyframes=plan["keyframes"], transitions=[], reference_images=[],
        character_appearances={"Ada": "blue coat", "Bea": "red coat"}, audio_drive=worker.audio,
        skip_llm_when_prompt_exists=reuse,
    ))


def submit(worker, prompt, callback):
    return asyncio.run(worker.comfy.ComfyUIService().generate_shot_video_with_workflow(
        prompt=prompt, workflow_json=worker.workflow.workflow_json, node_mapping=worker.mapping,
        character_reference_path="/virtual/start.png", drive_audio_path=worker.audio.get("drive_audio_path"),
        final_audio_path=worker.audio.get("final_audio_path"), on_before_submit=callback,
        on_prompt_queued=lambda prompt_id, graph: worker.module._save_h3_prompt_gate(
            worker.db, worker.task, callback.validation_record, prompt_id=prompt_id,
        ),
    ))


def run_worker(worker, *, reuse=False, only_window=None, auto_merge=False):
    asyncio.run(worker.module.generate_shot_video_task(
        worker.task.id, "novel", "chapter", "shot", 1, "workflow", "/api/files/start.png",
        selected_mode=worker.mode, only_window_index=only_window, skip_llm_when_prompt_exists=reuse,
        auto_merge_clips=auto_merge,
    ))


def save_prior_fallback_task(worker, record):
    # Copy evidence produced by the real worker gate and fake queue, not plan.ai_calls.
    record = deepcopy(record)
    record["target"]["id"] = "prior-fallback"
    submitted = deepcopy(worker.queued[-1])
    clip = {"window_index": record["clip_index"], "clip_index": record["clip_index"],
            "prompt_text": record["final_prompt"], "prompt_id": record["prompt_id"], "workflow_json": submitted}
    prior = worker.models.Task(
        id="prior-fallback", type="shot_video", status="completed", name="Prior server-validated fallback",
        novel_id="novel", chapter_id="chapter", shot_id="shot", workflow_id="workflow",
        comfyui_prompt_id=record["prompt_id"], prompt_text=record["final_prompt"],
        workflow_json=json.dumps(submitted), video_director_clips=json.dumps([clip]),
        metadata_json=json.dumps({"h3_prompt_gate": {"version": 1, "clips": {str(record["clip_index"]): [record]}}}),
    )
    worker.db.add(prior)
    worker.db.commit()


@pytest.mark.parametrize("mode,windows,frames,only_window", [
    ("SINGLE_FRAME", 1, 3, None), ("FIRST_LAST_FRAME", 1, 3, None),
    ("MULTI_KEYFRAME", 1, 3, None), ("MULTI_KEYFRAME", 1, 4, None), ("MULTI_KEYFRAME", 2, 3, 2),
])
@pytest.mark.parametrize("reuse", [False, True])
def test_all_worker_paths_use_common_builder_and_prequeue_gate(worker, mode, windows, frames, only_window, reuse):
    worker.configure(mode, windows=windows, frames=frames, prompt=PROMPT if reuse else MISSING)
    run_worker(worker, reuse=reuse, only_window=only_window)
    worker.db.refresh(worker.task)
    assert worker.task.status == "completed", worker.task.error_message
    index = only_window or 1
    record = records(worker, index)[0]
    assert record["raw_candidate"] == PROMPT
    assert record["origin"] == ("manual" if reuse else "llm")
    assert record["final_hash"] == worker.ai.prompt_digest(record["final_prompt"])
    assert record["prequeue_validation"]["passed"] is True
    assert record["prequeue_validation"]["final_prompt"] == record["final_prompt"]
    assert record["prompt_id"] == "queued-1"
    assert record["submission_state"] == "submitted"
    assert worker.prequeue[0][str(index)][0]["submission_state"] == "prepared"
    assert "prompt_id" not in worker.prequeue[0][str(index)][0]
    assert worker.comfy.resolve_h3_consumed_prompt(worker.queued[0], worker.mapping) == record["final_prompt"]
    assert worker.builder.await_count == 1
    assert worker.llm.await_count == (0 if reuse else 1)
    assert worker.builder.await_args.kwargs["reusable_prompt"] == (PROMPT if reuse else None)
    assert json.loads(worker.task.metadata_json)["unrelated"] == "keep"


@pytest.mark.parametrize("mode", ["SINGLE_FRAME", "MULTI_KEYFRAME"])
@pytest.mark.parametrize("candidate", ["", " \n\t", CONSTRAINT, "service error timeout INVALID_OUTPUT", "{broken", '{"summary": "only"}'])
def test_invalid_current_manual_never_uses_an_older_prompt(worker, mode, candidate):
    worker.configure(mode, prompt=candidate)
    edit_plan(worker, lambda plan: plan.update(ai_calls=[saved_call(worker, PROMPT)]))
    run_worker(worker, reuse=True)
    record = records(worker, 1)[0]
    assert record["passed"] is False
    assert record["raw_candidate"] == candidate
    assert record["submission_state"] == "not_submitted"
    assert "prompt_id" not in record
    worker.llm.assert_not_awaited()
    worker.client.queue_prompt.assert_not_awaited()
    plan = json.loads(worker.shot.video_director_plan)
    current = plan[worker.collection][0]
    assert current["status"] == "FAILED"
    assert current["prompt_text"] == candidate
    assert current["video_url"] == "/old-clip-1.mp4"
    assert current["user_note"] == "keep my edit"
    assert worker.shot.video_url == "/old-shot.mp4"
    assert worker.task.comfyui_prompt_id == "previous-task-prompt"


@pytest.mark.parametrize("mode", ["SINGLE_FRAME", "MULTI_KEYFRAME"])
@pytest.mark.parametrize("response", [
    {"success": True, "content": "unrecognized prose"},
    {"success": False, "failure_kind": "INVALID_OUTPUT", "diagnostic_content": "truncated"},
    {"success": False, "failure_kind": "UNKNOWN_ERROR", "error": "timeout is only error text"},
])
def test_fresh_failures_are_retained_without_retry(worker, mode, response):
    worker.configure(mode)
    worker.llm.return_value = response
    run_worker(worker)
    record = records(worker, 1)[0]
    assert record["passed"] is False
    assert record["errors"]
    assert worker.task.status == "failed"
    assert json.loads(worker.shot.video_director_plan)[worker.collection][0]["status"] == "FAILED"
    worker.llm.assert_awaited_once()
    worker.client.queue_prompt.assert_not_awaited()


def saved_call(worker, prompt, **changes):
    step, task_type = {"SINGLE_FRAME": ("11", "h3_single_frame_prompt"), "FIRST_LAST_FRAME": ("12", "h3_first_last_frame_prompt"),
                       "MULTI_KEYFRAME": ("13", "h3_multi_keyframe_prompt")}[worker.mode]
    return {"step": step, "task_type": task_type, "status": "success", "clip_index": 1,
            "workflow_type": worker.workflow.type, "final_prompt": prompt, **changes}


def lookup(worker, plan):
    return worker.module._get_reusable_video_prompt(
        plan, selected_mode=worker.mode, clip=worker.clip, workflow_type=worker.workflow.type, context={"scoped": True},
    )


@pytest.mark.parametrize("mode", ["SINGLE_FRAME", "FIRST_LAST_FRAME", "MULTI_KEYFRAME"])
def test_reuse_is_scoped_to_mode_and_clip_not_first_any_clip(worker, mode):
    worker.configure(mode)
    plan = json.loads(worker.shot.video_director_plan)
    other = {"clip_index": 9, "window_index": 9, "prompt_text": "wrong clip"}
    plan[worker.collection].insert(0, other)
    plan[worker.collection][1]["prompt_text"] = PROMPT
    assert lookup(worker, plan) == PROMPT
    plan["selected_mode"] = "FIRST_LAST_FRAME" if mode != "FIRST_LAST_FRAME" else "SINGLE_FRAME"
    assert lookup(worker, plan) is None


@pytest.mark.parametrize("changes", [{"step": "09"}, {"task_type": "shot_prompt"}, {"status": "error"},
                                      {"clip_index": 2}, {"workflow_type": "video"}])
def test_one_window_multi_ai_call_recovery_requires_exact_provenance(worker, changes):
    worker.configure("MULTI_KEYFRAME")
    plan = json.loads(worker.shot.video_director_plan)
    plan["ai_calls"] = [saved_call(worker, PROMPT, **changes)]
    assert lookup(worker, plan) is None
    plan["ai_calls"].insert(0, saved_call(worker, PROMPT))
    assert lookup(worker, plan) == PROMPT


@pytest.mark.parametrize("invalidation", ["marker", "new_plan", "context"])
def test_ai_call_recovery_cannot_resurrect_invalidated_context(worker, invalidation):
    worker.configure("MULTI_KEYFRAME")
    plan = json.loads(worker.shot.video_director_plan)
    plan["ai_calls"] = [saved_call(worker, PROMPT)]
    if invalidation == "marker":
        plan["invalidation_level"] = "SPEAKER_BINDING_CHANGED"
    elif invalidation == "new_plan":
        plan["ai_calls"].append({"step": "08", "status": "success"})
    else:
        plan["ai_calls"][0]["parsed_result"] = {"context": {"scoped": False}}
    assert lookup(worker, plan) is None


def test_one_window_multi_worker_recovers_legacy_ai_call(worker):
    worker.configure("MULTI_KEYFRAME")
    edit_plan(worker, lambda plan: plan.update(ai_calls=[saved_call(worker, PROMPT)]))
    run_worker(worker, reuse=True)
    assert worker.task.status == "completed", worker.task.error_message
    worker.llm.assert_not_awaited()
    assert records(worker, 1)[0]["raw_candidate"] == PROMPT


@pytest.mark.parametrize("mode", ["SINGLE_FRAME", "FIRST_LAST_FRAME", "MULTI_KEYFRAME"])
@pytest.mark.parametrize("failure_kind", ["TIMEOUT", "SERVICE_ERROR"])
def test_known_fallback_reuses_exact_candidate_without_llm_retry(worker, mode, failure_kind):
    worker.configure(mode)
    worker.llm.return_value = {"success": False, "failure_kind": failure_kind, "error": "unavailable"}
    prompt, callback = build(worker)
    assert callback.validation_record["origin"] == "fallback"
    assert submit(worker, prompt, callback)["success"] is True
    save_prior_fallback_task(worker, deepcopy(callback.validation_record))
    reused_prompt, reused_callback = build(worker, reuse=True)
    assert reused_prompt == prompt
    assert reused_callback.validation_record["origin"] == "reused_fallback"
    assert reused_callback.validation_record["raw_candidate"] == prompt
    reused_callback(worker.graph)
    assert len(records(worker, 1)) == 2
    worker.llm.assert_awaited_once()


@pytest.mark.parametrize("marker", [None, {}, {"clip_index": 2}, {"workflow_type": "first_last_video"}, {"status": "error"}])
def test_unproven_fallback_prose_is_not_rebuilt(worker, marker):
    candidate = worker.ai._build_deterministic_h3_prompt(worker.shot, worker.mode, worker.clip, [], [], [], {})
    edit_plan(worker, lambda plan: plan["clips"][0].update(prompt_text=candidate))
    if marker is not None:
        edit_plan(worker, lambda plan: plan.update(ai_calls=[saved_call(
            worker, candidate, parsed_result={"fallback": "deterministic_prompt"}, **marker,
        )]))
    with pytest.raises(worker.ai.H3PromptValidationError, match="PREAMBLE"):
        build(worker, reuse=True)
    worker.llm.assert_not_awaited()


@pytest.mark.parametrize("change", [
    "cancel", "task_shot", "owner", "claim", "manual", "manual_removed", "description", "video_description",
    "characters", "shot_image", "keyframe_description", "keyframe_image", "clip_range", "clip_frames", "workflow_type",
    "selected_mode", "timeline_ready", "timeline_id", "timeline_revision", "timeline_hash", "audio_status",
    "binding_id", "binding_revision", "binding_hash", "speaker_timeline", "audio_missing", "audio_path",
    "appearance", "subject_id",
])
def test_upload_time_changes_veto_queue_and_preserve_edits(worker, change):
    worker.configure("MULTI_KEYFRAME", prompt=PROMPT)
    prompt, callback = build(worker, reuse=True)

    def mutate():
        if change == "audio_missing":
            worker.files.pop(worker.audio["drive_audio_path"])
            return
        with Session(worker.engine) as editor:
            shot = editor.get(worker.models.Shot, "shot")
            task = editor.get(worker.models.Task, "task")
            timeline = editor.get(worker.models.Timeline, "timeline")
            plan = json.loads(shot.video_director_plan)
            item = plan["window_plans"][0]
            if change == "cancel":
                task.status = "cancelled"
            elif change == "task_shot":
                task.shot_id = "other-shot"
            elif change == "owner":
                shot.video_task_id = "replacement-task"
            elif change == "claim":
                task.claim_token = "replacement-claim"
            elif change == "manual":
                item["prompt_text"] = "my newly edited prompt"
            elif change == "manual_removed":
                item.pop("prompt_text")
            elif change in {"description", "video_description"}:
                setattr(shot, change, "New user direction")
            elif change == "characters":
                shot.characters = json.dumps(["Bea", "Ada"])
            elif change == "shot_image":
                shot.image_url = "/new-start.png"
            elif change.startswith("keyframe_"):
                plan["keyframes"][0]["description" if change.endswith("description") else "image_url"] = "changed"
            elif change == "clip_range":
                item["end_time"] = 3
            elif change == "clip_frames":
                item["keyframe_indexes"] = [3, 2, 1]
            elif change == "workflow_type":
                plan.setdefault("clips", []).append({"clip_index": 1, "workflow_type": "four_frame_video"})
            elif change == "selected_mode":
                plan["selected_mode"] = "SINGLE_FRAME"
            elif change == "timeline_ready":
                timeline.status = "STALE"
            elif change.startswith("timeline_"):
                setattr(timeline, {"timeline_id": "id", "timeline_revision": "revision", "timeline_hash": "generated_from_hash"}[change],
                        2 if change == "timeline_revision" else "new")
            elif change == "audio_status":
                item["audio_status"] = "STALE"
            elif change.startswith("binding_"):
                item["audio_timeline_" + change.removeprefix("binding_")] = 2 if change == "binding_revision" else "new"
            elif change == "speaker_timeline":
                item["speaker_timeline"][0]["visible_speaker"] = "Ada"
            elif change == "audio_path":
                item["drive_audio_path"] = "/virtual/replaced-drive.wav"
                worker.files[item["drive_audio_path"]] = SimpleNamespace(st_size=100, st_mtime_ns=1)
            elif change in {"appearance", "subject_id"}:
                character = editor.get(worker.models.Character, "ada")
                setattr(character, "appearance" if change == "appearance" else "id", "new")
            shot.video_director_plan = json.dumps(plan)
            shot.video_director_plan_revision += 1
            editor.commit()

    worker.upload_hook = mutate
    graph_before = deepcopy(worker.graph)
    result = submit(worker, prompt, callback)
    assert result["success"] is False
    worker.client.queue_prompt.assert_not_awaited()
    record = records(worker, 1)[0]
    assert record["passed"] is False
    assert record["prequeue_validation"]["passed"] is False
    assert record["submission_state"] == "not_submitted"
    assert "prompt_id" not in record
    assert worker.graph == graph_before
    assert worker.task.comfyui_prompt_id == "previous-task-prompt"
    plan = json.loads(worker.shot.video_director_plan)
    assert plan["window_plans"][0]["video_url"] == "/old-clip-1.mp4"
    if change == "manual":
        assert plan["window_plans"][0]["prompt_text"] == "my newly edited prompt"
    if change == "cancel":
        assert worker.task.status == "cancelled"
    if change in {"owner", "task_shot", "claim"}:
        assert plan["window_plans"][0]["status"] == "SUCCEEDED"
    if change in {"task_shot", "claim"}:
        assert worker.task.status == "running"


def test_progress_ai_calls_and_other_clip_edits_do_not_invalidate_semantics(worker, monkeypatch):
    worker.configure("MULTI_KEYFRAME", windows=2, prompt=PROMPT)
    prompt, callback = build(worker, reuse=True)
    original_revision = worker.shot.video_director_plan_revision
    prepare = Mock(wraps=worker.module.prepare_h3_prompt)
    monkeypatch.setattr(worker.module, "prepare_h3_prompt", prepare)

    def progress():
        def change(plan):
            plan["ai_calls"].append({"step": "09", "status": "success"})
            plan["window_plans"][0]["status"] = "RUNNING"
            plan["window_plans"][1].update(prompt_text="another Clip edit", end_time=9)
            plan["keyframes"][-1]["description"] = "another Clip keyframe edit"
            plan["keyframes"][0]["image_task_id"] = "progress-only"
        edit_plan(worker, change)
        with Session(worker.engine) as editor:
            task = editor.get(worker.models.Task, "task")
            task.progress = 49
            task.metadata_json = json.dumps({**json.loads(task.metadata_json), "parallel_edit": "keep"})
            editor.commit()
        worker.template.template = "new template is not this attempt's frozen constraint"

    worker.upload_hook = progress
    assert submit(worker, prompt, callback)["success"] is True
    assert worker.shot.video_director_plan_revision > original_revision
    prepare.assert_called_once()
    assert prepare.call_args.args == (PROMPT,)
    assert prepare.call_args.kwargs["constraint"] == CONSTRAINT
    assert json.loads(worker.task.metadata_json)["parallel_edit"] == "keep"
    record = records(worker, 1)[0]
    assert record["stage"] == "prepared"
    assert record["prequeue_validation"]["final_hash"] == record["final_hash"]


def test_edit_during_llm_is_not_overwritten(worker):
    async def complete(**kwargs):
        edit_plan(worker, lambda plan: plan["clips"][0].update(prompt_text="new manual input", video_url="/new-fact.mp4"))
        return {"success": True, "content": PROMPT}

    worker.llm.side_effect = complete
    run_worker(worker)
    plan = json.loads(worker.shot.video_director_plan)
    assert plan["clips"][0]["prompt_text"] == "new manual input"
    assert plan["clips"][0]["video_url"] == "/new-fact.mp4"
    assert records(worker, 1)[0]["errors"][0]["code"] == "MANUAL_PROMPT_CHANGED"
    worker.client.queue_prompt.assert_not_awaited()


def test_genuine_direct_has_nonapplicable_audio_audit(worker):
    worker.configure(audio=False)
    prompt, callback = build(worker)
    assert callback.validation_record["audio_audit"] == {"passed": True, "applicable": False, "issues": []}
    assert submit(worker, prompt, callback)["success"] is True
    assert callback.validation_record["prequeue_validation"]["audio_drive_enabled"] is False


@pytest.mark.parametrize("phase", ["build", "submit"])
def test_actual_audiodrive_graph_cannot_use_false_to_evade_audit(worker, phase):
    if phase == "build":
        worker.audio = {"enabled": False}
        with pytest.raises(worker.ai.H3PromptValidationError, match="AUDIODRIVE_REQUIRED_BY_GRAPH"):
            build(worker)
        worker.llm.assert_not_awaited()
    else:
        worker.configure(audio=False)
        prompt, callback = build(worker)
        changed = deepcopy(worker.graph)
        changed["h3"]["class_type"] = "MiniMaxH3AudioConditioningT8"
        with pytest.raises(worker.ai.H3PromptValidationError, match="AUDIODRIVE_REQUIRED_BY_GRAPH"):
            callback(changed)
        assert changed["h3"]["class_type"] == "MiniMaxH3AudioConditioningT8"
    worker.client.queue_prompt.assert_not_awaited()


@pytest.mark.parametrize("mode,windows,only_window", [
    ("SINGLE_FRAME", 1, None), ("MULTI_KEYFRAME", 1, None), ("MULTI_KEYFRAME", 2, 2),
])
@pytest.mark.parametrize("failure", ["upload", "queue", "queue_timeout", "execution"])
def test_failure_evidence_distinguishes_prequeue_unknown_and_submitted(worker, mode, windows, only_window, failure):
    worker.configure(mode, windows=windows)
    worker.upload_failure = failure == "upload"
    worker.queue_failure = failure == "queue"
    worker.queue_error = TimeoutError("queue acknowledgement lost") if failure == "queue_timeout" else None
    worker.wait_failure = failure == "execution"
    run_worker(worker, only_window=only_window)
    record = records(worker, only_window or 1)[0]
    assert worker.task.status == "failed"
    assert record["submission_state"] == {"upload": "not_submitted", "queue": "unknown",
                                           "queue_timeout": "unknown", "execution": "submitted"}[failure]
    if failure == "execution":
        assert record["prompt_id"] == "queued-1"
    else:
        assert "prompt_id" not in record
        assert worker.task.comfyui_prompt_id == "previous-task-prompt"
    assert record["submission_error"]
    current = json.loads(worker.shot.video_director_plan)[worker.collection][(only_window or 1) - 1]
    assert current["status"] == "FAILED"
    assert "h3_prompt_gate_failed" not in current
    if mode == "MULTI_KEYFRAME" and windows > 1 and failure != "upload":
        assert "video_url" not in current
    else:
        assert current["video_url"] == f"/old-clip-{only_window or 1}.mp4"


def test_second_clip_failure_does_not_steal_first_clip_prompt_id_or_evidence(worker):
    worker.configure("MULTI_KEYFRAME", windows=2, prompt=PROMPT)
    edit_plan(worker, lambda plan: plan["window_plans"][1].update(prompt_text="not a director document"))
    run_worker(worker, reuse=True)
    all_records = records(worker)
    assert all_records["1"][0]["prompt_id"] == "queued-1"
    assert all_records["1"][0]["submission_state"] == "submitted"
    assert all_records["1"][0]["passed"] is True
    assert all_records["2"][0]["passed"] is False
    assert all_records["2"][0]["submission_state"] == "not_submitted"
    assert "prompt_id" not in all_records["2"][0]
    assert worker.task.comfyui_prompt_id == "queued-1"
    plan = json.loads(worker.shot.video_director_plan)
    assert plan["window_plans"][0]["status"] == "SUCCEEDED"
    assert plan["window_plans"][0]["video_url"] == "/api/files/generated.mp4"
    assert plan["window_plans"][1]["status"] == "FAILED"
    assert plan["window_plans"][1]["video_url"] == "/old-clip-2.mp4"
    assert plan["window_plans"][1]["prompt_text"] == "not a director document"
    worker.client.queue_prompt.assert_awaited_once()


@pytest.mark.parametrize("candidate", [PROMPT + "\n<Subject 3> approaches.", PROMPT + "\nNONE speaks loudly."])
def test_reusable_director_document_still_runs_audio_audit(worker, candidate):
    worker.configure(prompt=candidate)
    run_worker(worker, reuse=True)
    record = records(worker, 1)[0]
    assert record["errors"][0]["code"] == "AUDIODRIVE_AUDIT_FAILED"
    worker.llm.assert_not_awaited()
    worker.client.queue_prompt.assert_not_awaited()


def test_builder_setup_exception_retains_failed_candidate_and_window(worker, monkeypatch):
    worker.configure("MULTI_KEYFRAME")
    monkeypatch.setattr(worker.ai, "resolve_prompt_template", Mock(side_effect=RuntimeError("template unavailable")))
    run_worker(worker)
    assert records(worker, 1)[0]["passed"] is False
    assert records(worker, 1)[0]["errors"][0]["details"] == "template unavailable"
    assert json.loads(worker.shot.video_director_plan)["window_plans"][0]["status"] == "FAILED"
    worker.llm.assert_not_awaited()


@pytest.mark.parametrize("failure", ["no_url", "download", "download_exception"])
def test_one_window_multi_output_failures_are_not_marked_succeeded(worker, failure):
    worker.configure("MULTI_KEYFRAME")
    if failure == "no_url":
        worker.client.wait_for_result.side_effect = None
        worker.client.wait_for_result.return_value = {"success": True}
    elif failure == "download":
        worker.storage.download_video.return_value = None
    else:
        worker.storage.download_video.side_effect = RuntimeError("download exception")
    run_worker(worker)
    assert worker.task.status == "failed"
    assert json.loads(worker.shot.video_director_plan)["window_plans"][0]["status"] == "FAILED"
    assert records(worker, 1)[0]["prompt_id"] == "queued-1"


def test_one_window_multi_rejects_another_requested_window(worker):
    worker.configure("MULTI_KEYFRAME", prompt=PROMPT)
    run_worker(worker, reuse=True, only_window=2)
    assert worker.task.status == "failed"
    assert json.loads(worker.shot.video_director_plan)["window_plans"][0]["status"] == "SUCCEEDED"
    worker.client.queue_prompt.assert_not_awaited()


def test_fresh_multi_gate_failure_keeps_previous_prompt_and_output(worker):
    worker.configure("MULTI_KEYFRAME", windows=2, prompt=PROMPT)
    worker.llm.return_value = {"success": True, "content": "invalid new candidate"}
    run_worker(worker)
    current = json.loads(worker.shot.video_director_plan)["window_plans"][0]
    assert current["prompt_text"] == PROMPT
    assert current["video_url"] == "/old-clip-1.mp4"
    assert current["status"] == "FAILED"
    worker.llm.assert_awaited_once()


def test_non_h3_classification_uses_nodes_not_workflow_name(worker):
    worker.configure(audio=False)
    worker.graph["h3"]["class_type"] = "LTXVConditioning"
    worker.workflow.name = "MiniMaxH3AudioConditioningT8"
    worker.workflow.workflow_json = json.dumps(worker.graph)
    worker.db.commit()
    prompt, callback = build(worker)
    assert submit(worker, prompt, callback)["success"] is True
    assert callback.validation_record["applicable"] is False
    assert set(callback.validation_record) == {"applicable", "target"}
    assert records(worker) == {}


@pytest.mark.parametrize("field", ["final_prompt", "final_hash"])
def test_prequeue_preparation_must_match_original_text_and_hash(worker, monkeypatch, field):
    prompt, callback = build(worker)
    prepare = worker.module.prepare_h3_prompt

    def changed(value, **kwargs):
        prepared = prepare(value, **kwargs)
        prepared[field] += "changed"
        return prepared

    monkeypatch.setattr(worker.module, "prepare_h3_prompt", changed)
    assert submit(worker, prompt, callback)["success"] is False
    assert records(worker, 1)[0]["errors"][0]["code"] == "PREQUEUE_PROMPT_CHANGED"
    worker.client.queue_prompt.assert_not_awaited()


@pytest.mark.parametrize("mode", ["SINGLE_FRAME", "MULTI_KEYFRAME"])
def test_initial_audio_preflight_keeps_original_behavior(worker, mode):
    worker.configure(mode)
    edit_plan(worker, lambda plan: plan[worker.collection][0].update(audio_status="STALE"))
    run_worker(worker)
    assert records(worker) == {}
    assert worker.task.status == "failed"
    assert worker.task.current_step == "Clip Audio \u672a READY"
    assert json.loads(worker.shot.video_director_plan)[worker.collection][0]["status"] == "SUCCEEDED"
    worker.builder.assert_not_awaited()
    worker.llm.assert_not_awaited()
    worker.client.queue_prompt.assert_not_awaited()


@pytest.mark.parametrize("mode", ["SINGLE_FRAME", "FIRST_LAST_FRAME"])
@pytest.mark.parametrize("audio_collection", ["window_plans", "execution_windows"])
@pytest.mark.parametrize("aliases", ["snake", "camel", "empty-primary-timeline"])
def test_separate_prompt_and_audio_collections_use_actual_execution_sources(worker, mode, audio_collection, aliases):
    worker.configure(mode, frames=4, prompt=PROMPT, audio_collection=audio_collection)

    def separate(plan):
        owner = plan["clips"][0]
        owner.update(selected_frame_count=2, workflow_key="editable-clip", keyframe_indexes=[9],
                     workflow_type=worker.workflow.type, audio_status="STALE", drive_audio_path="/wrong-owner.wav")
        audio = plan[audio_collection][0]
        audio.update(start_time=1, end_time=5, selected_frame_count=4, workflow_key="execution-window",
                     keyframe_indexes=[1, 2, 3, 4], prompt_text="not the editable prompt", workflow_type="unused-audio-hint")
        if audio_collection == "window_plans":
            plan["execution_windows"] = [{"window_index": 1, "audio_status": "STALE"}]
        if aliases == "camel":
            for source, target in (
                ("audio_status", "audioStatus"), ("audio_timeline_id", "audioTimelineId"),
                ("audio_timeline_revision", "audioTimelineRevision"), ("audio_timeline_hash", "audioTimelineHash"),
                ("speaker_timeline", "speakerTimeline"), ("clip_audio_duration", "clipAudioDuration"),
            ):
                audio[target] = audio.pop(source)
            for prefix, camel in (("drive_audio", "driveAudio"), ("final_audio", "finalAudio")):
                audio[camel + "Url"] = audio.pop(prefix + "_path").replace("/virtual/", "/api/files/")
        elif aliases == "empty-primary-timeline":
            audio["speakerTimeline"] = [{"start_time": 0, "end_time": 4, "visible_speaker": "unresolved decoy"}]
            audio["speaker_timeline"] = []
            audio["clip_audio_duration"] = 0
            audio["clipAudioDuration"] = 4

    edit_plan(worker, separate)
    run_worker(worker, reuse=True)
    assert worker.task.status == "completed", worker.task.error_message
    record = records(worker, 1)[0]
    assert record["raw_candidate"] == PROMPT
    effective = record["context"]["clip"]
    overlaid = audio_collection == "window_plans"
    assert [effective["start_time"], effective["end_time"]] == ([1, 5] if overlaid else [0, 4])
    assert effective["selected_frame_count"] == (4 if overlaid else 2)
    assert effective["workflow_key"] == ("execution-window" if overlaid else "editable-clip")
    assert effective["keyframe_indexes"] == ([1, 2, 3, 4] if overlaid else [9])
    assert effective["workflow_type"] == worker.workflow.type
    assert record["context"]["audio"]["drive_audio"] == {"path": "/virtual/drive-1.wav"}
    assert record["context"]["audio"]["duration"] == 4
    assert record["prequeue_validation"]["speaker_timeline"] == record["speaker_timeline"]
    if aliases == "empty-primary-timeline":
        assert record["speaker_timeline"] == []
    plan = json.loads(worker.shot.video_director_plan)
    assert plan["clips"][0]["prompt_text"] == record["final_prompt"]
    assert plan[audio_collection][0]["prompt_text"] == "not the editable prompt"
    assert worker.queued[0]["drive"]["inputs"]["audio"] == "uploaded/drive-1.wav"
    assert worker.queued[0]["final"]["inputs"]["audio"] == "uploaded/final-1.wav"
    worker.llm.assert_not_awaited()


@pytest.mark.parametrize("mode", ["SINGLE_FRAME", "FIRST_LAST_FRAME"])
@pytest.mark.parametrize("field,value", [
    ("start_time", 1), ("end_time", 5), ("selected_frame_count", 4),
    ("workflow_key", "changed"), ("keyframe_indexes", [3, 2, 1]), ("window_index", 2),
])
def test_non_multi_first_window_overlay_is_rechecked_after_uploads(worker, mode, field, value):
    worker.configure(mode, prompt=PROMPT, audio_collection="window_plans")
    worker.upload_hook = lambda: edit_plan(worker, lambda plan: plan["window_plans"][0].update({field: value}))
    run_worker(worker, reuse=True)
    record = records(worker, 1)[0]
    assert record["prequeue_validation"]["passed"] is False
    assert record["errors"][0]["code"] == "SEMANTIC_CONTEXT_CHANGED"
    assert json.loads(worker.shot.video_director_plan)["window_plans"][0][field] == value
    worker.client.queue_prompt.assert_not_awaited()


@pytest.mark.parametrize("mode", ["SINGLE_FRAME", "FIRST_LAST_FRAME"])
@pytest.mark.parametrize("audio_collection", ["window_plans", "execution_windows"])
@pytest.mark.parametrize("change", ["prompt", "audio-binding", "audio-speaker"])
def test_separate_owner_and_audio_changes_each_veto_submission(worker, mode, audio_collection, change):
    worker.configure(mode, prompt=PROMPT, audio_collection=audio_collection)

    def mutate(plan):
        if change == "prompt":
            plan["clips"][0]["prompt_text"] = "new current manual text"
        elif change == "audio-binding":
            plan[audio_collection][0]["audio_timeline_revision"] = 2
        else:
            plan[audio_collection][0]["speaker_timeline"][0]["visible_speaker"] = "Ada"

    worker.upload_hook = lambda: edit_plan(worker, mutate)
    run_worker(worker, reuse=True)
    record = records(worker, 1)[0]
    assert record["passed"] is False
    assert record["submission_state"] == "not_submitted"
    assert "prompt_id" not in record
    assert json.loads(worker.shot.video_director_plan)["clips"][0]["status"] == "FAILED"
    worker.client.queue_prompt.assert_not_awaited()


def test_audio_readiness_uses_existing_optional_hash_and_file_existence_contract(worker):
    worker.configure(audio_collection="execution_windows")
    worker.timeline.generated_from_hash = None
    worker.db.commit()

    def no_hash(plan):
        plan["audio_timeline"].pop("source_hash")
        plan["execution_windows"][0].pop("audio_timeline_hash")
        plan["execution_windows"][0].pop("clip_audio_duration")

    edit_plan(worker, no_hash)
    worker.upload_hook = lambda: worker.files.update({"/virtual/drive-1.wav": SimpleNamespace(st_size=999, st_mtime_ns=2)})
    run_worker(worker)
    assert worker.task.status == "completed", worker.task.error_message
    assert records(worker, 1)[0]["context"]["audio"]["hash"] is None
    assert records(worker, 1)[0]["context"]["audio"]["duration"] == 4


@pytest.mark.parametrize("partial_clip", [False, True])
def test_audio_duration_fallback_matches_resolver_not_visual_duration_defaults(worker, partial_clip):
    worker.configure(audio_collection="execution_windows")

    def missing_range(plan):
        plan["clips"] = [{"clip_index": 1}] if partial_clip else []
        plan["execution_windows"][0].pop("clip_audio_duration")
        plan["execution_windows"][0]["speaker_timeline"] = []

    edit_plan(worker, missing_range)
    run_worker(worker)
    assert worker.task.status == "completed", worker.task.error_message
    audio_duration = records(worker, 1)[0]["context"]["audio"]["duration"]
    assert audio_duration == worker.builder.await_args.kwargs["audio_drive_context"]["duration"]
    assert audio_duration == (0 if partial_clip else 4)


@pytest.mark.parametrize("mode,windows", [
    ("SINGLE_FRAME", 1), ("FIRST_LAST_FRAME", 1), ("MULTI_KEYFRAME", 1), ("MULTI_KEYFRAME", 2),
])
@pytest.mark.parametrize("route", ["fresh", "manual", "reuse", "ai-call"])
@pytest.mark.parametrize("case_id,error", [("53C1", None), ("115C1", "DIRECTOR_SECTIONS_MISSING"), ("119C3", "EMPTY_CORE")])
def test_whole_worker_canonical_candidates_use_actual_core(worker, mode, windows, route, case_id, error):
    case = HISTORY["cases"][case_id]
    core = case["core"]
    final = core + "\n\ntext_rendering_constraint:\n" + HISTORY["constraint"]
    worker.configure(mode, windows=windows)
    worker.template.template = worker.template.template.replace(CONSTRAINT, HISTORY["constraint"])
    if case_id == "53C1":
        subjects = case["subject_manifest"]["subjects"]
        worker.db.query(worker.models.Character).delete()
        worker.db.add_all([worker.models.Character(id=subject["character_id"], novel_id="novel",
                                                   name=subject["character_name"], appearance="canonical fixture appearance")
                           for subject in subjects])
        worker.shot.characters = json.dumps([subject["character_name"] for subject in subjects])
        speaker_timeline = [{"start_time": item["start_time"], "end_time": item["end_time"],
                             "visible_speaker": item["source_speaker"]} for item in case["speaker_timeline"]]
    else:
        speaker_timeline = [{"start_time": 0, "end_time": round(case["clip_range"][1] - case["clip_range"][0], 3),
                             "visible_speaker": "NONE"}]
    worker.db.commit()

    def configure_case(plan):
        item = plan[worker.collection][0]
        index_field = "window_index" if mode == "MULTI_KEYFRAME" else "clip_index"
        for offset, window in enumerate(plan[worker.collection]):
            window[index_field] = case["clip_index"] + offset
        item.update(start_time=case["clip_range"][0], end_time=case["clip_range"][1], speaker_timeline=speaker_timeline,
                    clip_audio_duration=round(case["clip_range"][1] - case["clip_range"][0], 3))
        if route in {"manual", "reuse"}:
            item["prompt_text"] = final
        if route in {"reuse", "ai-call"}:
            plan["ai_calls"] = [saved_call(worker, final, clip_index=case["clip_index"])]

    edit_plan(worker, configure_case)
    worker.llm.return_value = {"success": True, "content": core}
    run_worker(worker, reuse=route != "fresh", only_window=case["clip_index"] if mode == "MULTI_KEYFRAME" else None)
    record = records(worker, case["clip_index"])[0]
    assert record["raw_candidate"] == (core if route == "fresh" else final)
    assert worker.builder.await_count == 1
    assert worker.llm.await_count == (1 if route == "fresh" else 0)
    if error:
        assert worker.task.status == "failed"
        assert record["errors"][0]["code"] == error
        assert record["submission_state"] == "not_submitted"
        assert "prompt_id" not in record
        assert json.loads(worker.shot.video_director_plan)[worker.collection][0]["status"] == "FAILED"
        worker.client.queue_prompt.assert_not_awaited()
    else:
        assert worker.task.status == "completed", worker.task.error_message
        assert record["origin"] == {"fresh": "llm", "manual": "manual", "reuse": "reuse", "ai-call": "reuse"}[route]
        assert record["profile"] == "director_json"
        assert record["core_hash"] == case["core_sha256"]
        assert record["final_hash"] == case["final_sha256"]
        assert record["prequeue_validation"]["final_hash"] == case["final_sha256"]
        assert worker.comfy.resolve_h3_consumed_prompt(worker.queued[0], worker.mapping) == final


@pytest.mark.parametrize("mode,windows", [
    ("SINGLE_FRAME", 1), ("FIRST_LAST_FRAME", 1), ("MULTI_KEYFRAME", 1), ("MULTI_KEYFRAME", 2),
])
@pytest.mark.parametrize("failure_kind", ["TIMEOUT", "SERVICE_ERROR", "INVALID_OUTPUT", "UNKNOWN_ERROR", None])
def test_whole_worker_failure_kind_fallback_and_reused_fallback_use_actual_gate(worker, mode, windows, failure_kind):
    worker.configure(mode, windows=windows, prompt=PROMPT)
    diagnostic = HISTORY["cases"]["115C1"]["core"]
    worker.llm.return_value = {"success": False, "failure_kind": failure_kind, "diagnostic_content": diagnostic,
                              "diagnostic_type": "str", "error": "provider unavailable"}
    run_worker(worker, only_window=1 if windows > 1 else None)
    record = deepcopy(records(worker, 1)[0])
    assert record["diagnostic_content"] == diagnostic
    worker.llm.assert_awaited_once()
    if failure_kind in {"TIMEOUT", "SERVICE_ERROR"}:
        assert worker.task.status == "completed", worker.task.error_message
        assert record["origin"] == "fallback"
        assert record["profile"] == "deterministic_fallback"
        assert record["raw_candidate"] != diagnostic
        assert record["prequeue_validation"]["passed"] is True
        previous = worker.task
        saved = {column.key: deepcopy(getattr(previous, column.key)) for column in worker.models.Task.__table__.columns}
        worker.task = worker.models.Task(
            type="shot_video", status="pending", name="Fresh fallback reuse", description="Reuse prior proof",
            novel_id="novel", chapter_id="chapter", shot_id="shot", workflow_id=worker.workflow.id,
            workflow_name=worker.workflow.name, metadata_json="{}",
        )
        worker.db.add(worker.task)
        worker.db.flush()
        worker.shot.video_task_id = worker.task.id
        worker.shot.video_status = "generating"
        worker.db.commit()
        assert worker.task.id != previous.id
        run_worker(worker, reuse=True, only_window=1 if windows > 1 else None)
        attempts = records(worker, 1)
        assert worker.task.status == "completed", worker.task.error_message
        assert worker.shot.video_task_id == worker.task.id
        assert len(attempts) == 1
        assert attempts[0]["attempt_id"] != record["attempt_id"]
        assert attempts[0]["target"]["id"] == worker.task.id
        assert attempts[0]["fallback_source_task_id"] == previous.id
        assert attempts[0]["origin"] == "reused_fallback"
        assert attempts[0]["raw_candidate"] == record["final_prompt"]
        assert attempts[0]["final_hash"] == record["final_hash"]
        assert attempts[0]["prequeue_validation"]["passed"] is True
        worker.db.refresh(previous)
        assert {key: getattr(previous, key) for key in saved} == saved
        assert json.loads(previous.metadata_json)["h3_prompt_gate"]["clips"]["1"] == [record]
        worker.llm.assert_awaited_once()
    else:
        assert worker.task.status == "failed"
        assert record["errors"][0]["code"] == (failure_kind or "UNKNOWN_ERROR")
        assert "fallback_context" not in record
        worker.client.queue_prompt.assert_not_awaited()


@pytest.mark.parametrize("failure,mode,windows,step", [
    ("end-image", "FIRST_LAST_FRAME", 1, "\u7f3a\u5c11 END \u5173\u952e\u5e27"),
    ("frame-count", "MULTI_KEYFRAME", 1, "\u6267\u884c\u8ba1\u5212\u65e0\u6548"),
    ("workflow", "MULTI_KEYFRAME", 2, "\u7f3a\u5c11\u89c6\u9891\u5de5\u4f5c\u6d41"),
    ("start-image", "MULTI_KEYFRAME", 2, "\u7f3a\u5c11\u5173\u952e\u5e27\u56fe\u7247"),
    ("keyframe-image", "MULTI_KEYFRAME", 2, "\u7f3a\u5c11\u5173\u952e\u5e27\u56fe\u7247"),
])
def test_unrelated_preflights_keep_original_status_messages_without_gate_records(worker, failure, mode, windows, step):
    worker.configure(mode, windows=windows, prompt=PROMPT)
    if failure == "workflow":
        worker.workflow.is_active = False
        worker.db.commit()
    else:
        def missing(plan):
            if failure == "frame-count":
                plan["window_plans"][0]["selected_frame_count"] = 2
            else:
                index = {"end-image": 2, "start-image": 3, "keyframe-image": 4}[failure]
                plan["keyframes"][index]["image_url"] = None
        edit_plan(worker, missing)
    run_worker(worker, reuse=True, only_window=2 if windows > 1 else None)
    assert worker.task.status == "failed"
    assert worker.task.current_step == step
    assert records(worker) == {}
    worker.builder.assert_not_awaited()
    worker.client.queue_prompt.assert_not_awaited()


@pytest.mark.parametrize("rejection", ["body", "upload-edit"])
def test_multi_reset_waits_for_final_gate_and_never_merges_old_failed_clip_facts(worker, monkeypatch, rejection):
    worker.configure("MULTI_KEYFRAME", windows=2, prompt=PROMPT)
    invalid = HISTORY["cases"]["115C1"]["core"]

    def previous(plan):
        plan.update(merged_video_url="/old-merged.mp4", merged_at="2026-01-01T00:00:00")
        for index, item in enumerate(plan["window_plans"], 1):
            item.update(prompt_id=f"old-{index}", workflow_json={"old": index}, local_path=f"/virtual/old-{index}.mp4",
                        source_video_url=f"/old-source-{index}.mp4", generated_at="2025-12-31T00:00:00",
                        generated_by_task_id="earlier-task")
        if rejection == "body":
            plan["window_plans"][1]["prompt_text"] = invalid

    edit_plan(worker, previous)
    queue = worker.client.queue_prompt.side_effect

    def before_gate():
        plan = json.loads(worker.shot.video_director_plan)
        assert plan["window_plans"][0]["prompt_id"] == "old-1"
        assert plan["window_plans"][0]["generated_by_task_id"] == "earlier-task"

    async def after_gate(graph):
        window = json.loads(worker.shot.video_director_plan)["window_plans"][0]
        for field in ("prompt_id", "workflow_json", "video_url", "local_path", "source_video_url", "generated_at", "generated_by_task_id"):
            assert field not in window
        assert window["prompt_text"] == records(worker, 1)[0]["final_prompt"]
        assert records(worker, 1)[0]["prequeue_validation"]["passed"] is True
        return await queue(graph)

    async def download(**kwargs):
        if rejection == "upload-edit":
            worker.upload_hook = lambda: edit_plan(worker, lambda plan: plan["window_plans"][1].update(prompt_text=invalid))
        return "/virtual/generated.mp4"

    worker.upload_hook = before_gate
    worker.client.queue_prompt.side_effect = after_gate
    worker.storage.download_video.side_effect = download
    real_merge = worker.module.merge_video_director_clip_videos
    merge = AsyncMock(wraps=real_merge)
    monkeypatch.setattr(worker.module, "merge_video_director_clip_videos", merge)
    complete_shot = Mock(wraps=worker.module._clear_shot_video_error)
    monkeypatch.setattr(worker.module, "_clear_shot_video_error", complete_shot)
    run_worker(worker, reuse=True, auto_merge=True)

    assert worker.task.status == "failed"
    assert worker.task.result_url is None
    assert worker.task.comfyui_prompt_id == "queued-1"
    first, failed = records(worker, 1)[0], records(worker, 2)[0]
    assert first["prompt_id"] == "queued-1"
    assert first["submission_state"] == "submitted"
    assert failed["passed"] is False
    assert failed["submission_state"] == "not_submitted"
    assert "prompt_id" not in failed
    plan = json.loads(worker.shot.video_director_plan)
    assert plan["window_plans"][0]["generated_by_task_id"] == "task"
    assert plan["window_plans"][1]["generated_by_task_id"] == "earlier-task"
    assert plan["window_plans"][1]["prompt_id"] == "old-2"
    assert plan["window_plans"][1]["video_url"] == "/old-clip-2.mp4"
    assert plan["window_plans"][1]["prompt_text"] == invalid
    assert plan["window_plans"][1]["h3_prompt_gate_failed"] is True
    assert plan["merged_video_url"] == "/old-merged.mp4"
    assert worker.shot.video_url == "/old-shot.mp4"
    worker.client.queue_prompt.assert_awaited_once()
    worker.storage.merge_videos.assert_not_awaited()
    merge.assert_not_awaited()

    # The retained artifacts must not become eligible via a later manual merge.
    repo = worker.module.ShotRepository(worker.db)
    result = asyncio.run(real_merge(worker.db, worker.shot, repo, "novel", "chapter", 1))
    assert result["success"] is False
    assert "H3_PROMPT_GATE_FAILED: C2" in result["message"]
    assert worker.shot.video_status == "failed"
    worker.storage.merge_videos.assert_not_awaited()
    worker.matches_sources.assert_not_called()

    # Regenerating only C1 must not silently merge/re-complete the Shot using old C2.
    worker.task = worker.models.Task(
        id="retry-c1", type="shot_video", status="pending", name="Regenerate C1", description="Retry C1",
        novel_id="novel", chapter_id="chapter", shot_id="shot", workflow_id="workflow",
    )
    worker.db.add(worker.task)
    worker.shot.video_task_id = worker.task.id
    worker.shot.video_status = "generating"
    worker.db.commit()
    worker.client.queue_prompt.side_effect = queue
    worker.storage.download_video.side_effect = None
    run_worker(worker, reuse=True, only_window=1, auto_merge=True)
    assert worker.task.status == "failed"
    assert worker.task.result_url is None
    assert "H3_PROMPT_GATE_FAILED: C2" in worker.task.error_message
    assert worker.shot.video_status == "failed"
    assert worker.shot.video_url == "/old-shot.mp4"
    assert json.loads(worker.shot.video_director_plan)["window_plans"][1]["local_path"] == "/virtual/old-2.mp4"
    merge.assert_awaited_once()
    worker.storage.merge_videos.assert_not_awaited()
    complete_shot.assert_not_called()


@pytest.mark.parametrize("empty_graph", [False, True])
@pytest.mark.parametrize("source", ["fresh", "first-clip", "ai-call"])
def test_non_h3_free_prose_keeps_legacy_builder_and_reuse_selection(worker, source, empty_graph):
    prose = "The camera drifts past a quiet gate."
    worker.configure(audio=False)
    worker.graph["h3"]["class_type"] = "LTXVConditioning"
    if empty_graph:
        worker.graph = {}
    worker.workflow.workflow_json = json.dumps(worker.graph)
    worker.workflow.name = "Misleading MiniMaxH3 workflow name"
    worker.db.commit()

    def legacy(plan):
        plan.update(selected_mode="unrelated-old-mode", invalidation_level="old-invalidation")
        plan["clips"][0]["prompt_text"] = f"  {prose}\n" if source == "first-clip" else ""
        plan["clips"].append({"clip_index": 99, "prompt_text": ""})
        plan["ai_calls"] = [{"step": "09", "task_type": "unrelated", "status": "error", "clip_index": 99,
                             "final_prompt": "older history" if source == "first-clip" else f"  {prose}\n"}]

    edit_plan(worker, legacy)
    worker.llm.return_value = {"success": True, "content": prose}
    run_worker(worker, reuse=source != "fresh")
    assert worker.task.status == "completed", worker.task.error_message
    assert records(worker) == {}
    assert json.loads(worker.task.metadata_json) == {"unrelated": "keep"}
    assert worker.task.comfyui_prompt_id == "queued-1"
    if source == "fresh":
        assert prose in worker.task.prompt_text
        assert worker.task.prompt_text.endswith(CONSTRAINT)
        worker.builder.assert_awaited_once()
        worker.llm.assert_awaited_once()
        assert worker.builder.await_args.kwargs["workflow_graph"] == worker.graph
        assert "validation_record" not in worker.builder.await_args.kwargs
    else:
        assert worker.task.prompt_text == prose
        worker.builder.assert_not_awaited()
        worker.llm.assert_not_awaited()


def test_empty_non_h3_workflow_accepts_d2_style_string_only_builder(worker, monkeypatch):
    worker.configure(audio=False)
    worker.workflow.workflow_json = "{}"
    worker.workflow.node_mapping = json.dumps({"video_save_node_id": "150"})
    worker.shot.video_task_id = None
    worker.db.commit()
    builder = AsyncMock(return_value="stable shot-id prompt")
    monkeypatch.setattr(worker.module, "build_h3_video_prompt", builder)
    context = Mock(side_effect=AssertionError("Non-H3 does not require a strict H3 context"))
    monkeypatch.setattr(worker.module, "_h3_prompt_context", context)
    run_worker(worker)
    assert worker.task.status == "completed", worker.task.error_message
    assert worker.task.prompt_text == "stable shot-id prompt"
    assert builder.await_args.kwargs["workflow_graph"] == {}
    assert records(worker) == {}
    context.assert_not_called()


def test_non_h3_callback_rejects_a_graph_that_becomes_h3(worker):
    prose = "A quiet gate, with a slow camera move."
    worker.configure(audio=False, prompt=prose)
    worker.graph["h3"]["class_type"] = "LTXVConditioning"
    worker.workflow.workflow_json = json.dumps(worker.graph)
    worker.db.commit()
    prompt, callback = build(worker, reuse=True)
    assert callback.validation_record["applicable"] is False
    worker.graph["h3"]["class_type"] = "MiniMaxH3ReferenceToVideo"
    worker.workflow.workflow_json = json.dumps(worker.graph)
    worker.db.commit()
    result = submit(worker, prompt, callback)
    assert result["success"] is False
    assert "H3_GRAPH_REQUIRES_PROMPT_GATE" in result["message"]
    worker.client.queue_prompt.assert_not_awaited()
    assert records(worker) == {}


@pytest.mark.parametrize("reuse", [False, True])
def test_actual_h3_graph_still_rejects_free_prose(worker, reuse):
    prose = "A quiet gate, with a slow camera move."
    worker.configure(audio=False, prompt=prose)
    worker.llm.return_value = {"success": True, "content": prose}
    run_worker(worker, reuse=reuse)
    assert worker.task.status == "failed"
    assert records(worker, 1)[0]["errors"][0]["code"] == "UNSUPPORTED_DIRECTOR_FORMAT"
    worker.client.queue_prompt.assert_not_awaited()


def test_nonapplicable_gate_record_does_not_access_database_or_gain_evidence(worker):
    record = {"applicable": False, "target": {"id": "unused"}}
    db = Mock()
    worker.module._save_h3_prompt_gate(db, None, record, prompt_id="not-h3", error="not-h3 failure")
    assert db.mock_calls == []
    assert record == {"applicable": False, "target": {"id": "unused"}}


def test_non_h3_missing_reuse_fails_window_without_a_gate_failure_marker(worker):
    worker.configure("MULTI_KEYFRAME", windows=2, audio=False)
    worker.graph["h3"]["class_type"] = "LTXVConditioning"
    worker.workflow.workflow_json = json.dumps(worker.graph)
    worker.db.commit()
    run_worker(worker, reuse=True, only_window=2)
    assert worker.task.status == "failed"
    window = json.loads(worker.shot.video_director_plan)["window_plans"][1]
    assert window["status"] == "FAILED"
    assert "h3_prompt_gate_failed" not in window
    assert records(worker) == {}
    worker.builder.assert_not_awaited()
    worker.client.queue_prompt.assert_not_awaited()


def test_merge_gate_does_not_change_unrelated_failed_window_behavior(worker):
    worker.configure("MULTI_KEYFRAME", windows=2)

    def old_failure(plan):
        plan["window_plans"][1]["status"] = "FAILED"
        plan["window_plans"][1]["error_message"] = "unrelated legacy failure"
        for window in plan["window_plans"]:
            window["generated_at"] = "2025-12-31T00:00:00"
        plan.update(merged_video_url="/cached-merge.mp4", merged_at="2026-01-01T00:00:00")

    edit_plan(worker, old_failure)
    result = asyncio.run(worker.module.merge_video_director_clip_videos(
        worker.db, worker.shot, worker.module.ShotRepository(worker.db), "novel", "chapter", 1,
    ))
    assert result["success"] is True
    assert result["skipped"] is True
    assert result["video_url"] == "/cached-merge.mp4"
    worker.storage.merge_videos.assert_not_awaited()


def test_gate_failed_window_remains_unmergeable_until_regenerated_successfully(worker):
    worker.configure("MULTI_KEYFRAME", windows=2, prompt=PROMPT)
    edit_plan(worker, lambda plan: plan["window_plans"][1].update(prompt_text=HISTORY["cases"]["119C3"]["core"]))
    run_worker(worker, reuse=True)
    assert json.loads(worker.shot.video_director_plan)["window_plans"][1]["h3_prompt_gate_failed"] is True
    previous = worker.task
    previous_gates = deepcopy(records(worker))
    saved = {column.key: deepcopy(getattr(previous, column.key)) for column in worker.models.Task.__table__.columns}
    assert previous.status == "failed"
    edit_plan(worker, lambda plan: plan["window_plans"][1].update(prompt_text=PROMPT))
    worker.task = worker.models.Task(
        type="shot_video", status="pending", name="Fresh C2 regeneration", description="Regenerate failed window",
        novel_id="novel", chapter_id="chapter", shot_id="shot", workflow_id=worker.workflow.id,
        workflow_name=worker.workflow.name, metadata_json="{}",
    )
    worker.db.add(worker.task)
    worker.db.flush()
    worker.shot.video_task_id = worker.task.id
    worker.shot.video_status = "generating"
    worker.db.commit()
    assert worker.task.id != previous.id
    upload = worker.client.upload_image.side_effect

    async def check_during_retry(path):
        assert worker.shot.video_task_id == worker.task.id
        window = json.loads(worker.shot.video_director_plan)["window_plans"][1]
        assert window["status"] == "RUNNING"
        assert window["h3_prompt_gate_failed"] is True
        result = await worker.module.merge_video_director_clip_videos(
            worker.db, worker.shot, worker.module.ShotRepository(worker.db), "novel", "chapter", 1,
        )
        assert result["success"] is False
        assert "H3_PROMPT_GATE_FAILED: C2" in result["message"]
        return await upload(path)

    worker.client.upload_image.side_effect = check_during_retry
    run_worker(worker, reuse=True, only_window=2)
    window = json.loads(worker.shot.video_director_plan)["window_plans"][1]
    assert worker.task.status == "completed", worker.task.error_message
    assert window["status"] == "SUCCEEDED"
    assert "h3_prompt_gate_failed" not in window
    assert window["video_url"] == "/api/files/generated.mp4"
    assert window["generated_by_task_id"] == worker.task.id
    attempts = records(worker, 2)
    assert len(attempts) == 1
    assert attempts[0]["passed"] is True
    assert attempts[0]["attempt_id"] != previous_gates["2"][0]["attempt_id"]
    assert attempts[0]["target"]["id"] == worker.task.id
    worker.db.refresh(previous)
    assert {key: getattr(previous, key) for key in saved} == saved
    assert json.loads(previous.metadata_json)["h3_prompt_gate"]["clips"] == previous_gates
    assert previous_gates["2"][0]["passed"] is False
    worker.storage.merge_videos.assert_not_awaited()


@pytest.mark.parametrize("mode,windows", [("SINGLE_FRAME", 1), ("MULTI_KEYFRAME", 2)])
@pytest.mark.parametrize("change", ["mode", "removed", "range", "indices", "role"])
@pytest.mark.parametrize("phase", ["llm", "upload", "gpu"])
def test_failure_writeback_never_mutates_a_removed_or_replaced_clip(worker, mode, windows, change, phase):
    worker.configure(mode, windows=windows, audio=False)
    replacement = {}

    def replace_target():
        with Session(worker.engine) as editor:
            shot = editor.get(worker.models.Shot, "shot")
            plan = json.loads(shot.video_director_plan)
            if change == "mode":
                plan["selected_mode"] = "MULTI_KEYFRAME" if mode == "SINGLE_FRAME" else "SINGLE_FRAME"
                plan[worker.collection] = []
                collection = "window_plans" if mode == "SINGLE_FRAME" else "clips"
                plan[collection] = [{"clip_index": 1, "window_index": 1, "start_time": 8, "end_time": 12,
                                     "status": "SUCCEEDED", "video_url": "/replacement-clip.mp4"}]
            elif change == "removed":
                plan[worker.collection] = plan[worker.collection][1:]
            elif change == "range":
                plan[worker.collection][0].update(start_time=8, end_time=12)
            elif change == "indices":
                plan[worker.collection][0]["keyframe_indexes"] = [3, 2, 1]
            else:
                plan["keyframes"][0]["role"] = "END"
            for item in plan.get(worker.collection, []):
                item.update(status="SUCCEEDED", video_url="/replacement-clip.mp4", workflow_json={"replacement": True})
            plan["replacement_note"] = "keep the user's new plan"
            shot.video_director_plan = json.dumps(plan)
            shot.video_director_plan_revision += 1
            shot.video_status = "pending"
            shot.video_url = "/replacement-shot.mp4"
            replacement["plan"] = deepcopy(plan)
            editor.commit()

    if phase == "llm":
        async def complete(**kwargs):
            replace_target()
            return {"success": True, "content": PROMPT}
        worker.llm.side_effect = complete
    elif phase == "upload":
        worker.upload_hook = replace_target
    else:
        async def fail_gpu(*args, **kwargs):
            replace_target()
            return {"success": False, "message": "GPU execution failed"}
        worker.client.wait_for_result.side_effect = fail_gpu

    run_worker(worker, only_window=1 if windows > 1 else None)
    assert worker.task.status == "failed"
    record = records(worker, 1)[0]
    if phase == "gpu":
        assert record["submission_state"] == "submitted"
        assert record["submission_error"] == "GPU execution failed"
        worker.client.queue_prompt.assert_awaited_once()
    else:
        assert record["passed"] is False
        assert record["submission_state"] == "not_submitted"
        worker.client.queue_prompt.assert_not_awaited()
    current = json.loads(worker.shot.video_director_plan)
    expected = replacement["plan"]
    current.pop("ai_calls", None)
    expected.pop("ai_calls", None)
    assert current == expected
    assert worker.shot.video_status == "pending"
    assert worker.shot.video_url == "/replacement-shot.mp4"


def test_failure_identity_is_checked_inside_plan_mutation_retries(worker, monkeypatch):
    worker.configure(audio=False)
    _, callback = build(worker)
    mutate = worker.plans.VideoDirectorPlanService.mutate
    replacement = {}

    def race(service, shot_id, mutator, **kwargs):
        if mutator.__name__ == "fail_owned_clip" and not replacement:
            def change(plan):
                plan.update(selected_mode="MULTI_KEYFRAME", clips=[], window_plans=[{
                    "window_index": 1, "start_time": 8, "end_time": 12, "status": "PENDING",
                }])
                replacement.update(deepcopy(plan))
            edit_plan(worker, change)
        return mutate(service, shot_id, mutator, **kwargs)

    monkeypatch.setattr(worker.plans.VideoDirectorPlanService, "mutate", race)
    worker.module._fail_h3_video_clip(worker.db, worker.task, worker.shot, worker.clip, worker.mode,
                                     "old attempt failed", target=callback.validation_record["target"], gate_failed=True)
    assert worker.task.status == "failed"
    assert json.loads(worker.shot.video_director_plan) == replacement
    assert worker.shot.video_status == "pending"


@pytest.mark.parametrize("with_decoys", [False, True])
def test_non_h3_multi_reuse_submits_each_windows_own_manual_text(worker, with_decoys):
    worker.configure("MULTI_KEYFRAME", windows=2, audio=False)
    worker.graph["h3"]["class_type"] = "LTXVConditioning"
    worker.workflow.workflow_json = json.dumps(worker.graph)
    worker.db.commit()
    prompts = ["C1 pans slowly towards the gate.", "C2 follows the horse away from the gate."]

    def manual(plan):
        for item, text in zip(plan["window_plans"], prompts):
            item["prompt_text"] = text
        if with_decoys:
            plan["clips"] = [{"clip_index": 99, "prompt_text": "Wrong first clip prompt"}]
            plan["ai_calls"] = [{"clip_index": 99, "final_prompt": "Wrong last AI call prompt"}]

    edit_plan(worker, manual)
    for index in (1, 2):
        if index == 2:
            previous = worker.task
            worker.db.refresh(previous)
            saved = {column.key: deepcopy(getattr(previous, column.key)) for column in worker.models.Task.__table__.columns}
            worker.task = worker.models.Task(
                type="shot_video", status="pending", name="Fresh non-H3 C2", description="Generate next clip",
                novel_id="novel", chapter_id="chapter", shot_id="shot", workflow_id=worker.workflow.id,
                workflow_name=worker.workflow.name, metadata_json="{}",
            )
            worker.db.add(worker.task)
            worker.db.flush()
            worker.shot.video_task_id = worker.task.id
            worker.shot.video_status = "generating"
            worker.db.commit()
            assert worker.task.id != previous.id
        run_worker(worker, reuse=True, only_window=index)
        assert worker.task.status == "completed", worker.task.error_message
        assert worker.shot.video_task_id == worker.task.id
        assert [item["prompt_text"] for item in json.loads(worker.shot.video_director_plan)["window_plans"]] == prompts
    worker.db.refresh(previous)
    assert {key: getattr(previous, key) for key in saved} == saved
    assert previous.comfyui_prompt_id == "queued-1"
    assert worker.task.comfyui_prompt_id == "queued-2"
    assert [graph["text"]["inputs"]["prompt"] for graph in worker.queued] == prompts
    worker.builder.assert_not_awaited()
    worker.llm.assert_not_awaited()
    assert records(worker) == {}


@pytest.mark.parametrize("source", ["clips", "ai_calls"])
def test_one_window_non_h3_retains_legacy_reuse_selection(worker, source):
    worker.configure("MULTI_KEYFRAME", audio=False, prompt="The one-window prompt was historically ignored.")
    worker.graph["h3"]["class_type"] = "LTXVConditioning"
    worker.workflow.workflow_json = json.dumps(worker.graph)
    worker.db.commit()
    expected = "Legacy single-call prompt."

    def legacy(plan):
        plan["clips"] = [{"clip_index": 1, "prompt_text": expected}] if source == "clips" else []
        plan["ai_calls"] = [{"clip_index": 99, "final_prompt": expected if source == "ai_calls" else "ignored"}]

    edit_plan(worker, legacy)
    run_worker(worker, reuse=True)
    assert worker.task.status == "completed", worker.task.error_message
    assert worker.queued[0]["text"]["inputs"]["prompt"] == expected
    worker.builder.assert_not_awaited()
    worker.llm.assert_not_awaited()
    assert records(worker) == {}


@pytest.mark.parametrize("windows", [1, 2])
@pytest.mark.parametrize("fallback", [False, True])
def test_prompt_mapping_rejection_blocks_later_merges_without_losing_core_evidence(worker, windows, fallback):
    worker.configure("MULTI_KEYFRAME", windows=windows, prompt=PROMPT)
    worker.graph["decoy"] = {"class_type": "CR Prompt Text", "inputs": {"prompt": "unconnected"}}
    worker.workflow.workflow_json = json.dumps(worker.graph)
    worker.workflow.node_mapping = json.dumps({**worker.mapping, "prompt_node_id": "decoy"})
    worker.db.commit()
    if fallback:
        worker.llm.return_value = {"success": False, "failure_kind": "TIMEOUT", "error": "provider timeout"}

    def old_outputs(plan):
        plan.update(merged_video_url="/old-merged.mp4", merged_at="2026-01-01T00:00:00")
        for index, item in enumerate(plan["window_plans"], 1):
            item.update(local_path=f"/virtual/old-{index}.mp4", generated_at="2025-12-31T00:00:00",
                        generated_by_task_id="earlier-task", prompt_id=f"old-{index}")

    edit_plan(worker, old_outputs)
    run_worker(worker, reuse=not fallback, only_window=windows if windows > 1 else None)
    record = records(worker, windows)[0]
    assert record.get("submission_failure_kind") == "H3_PROMPT_SUBMISSION_REJECTED"
    assert record["prequeue_validation"]["passed"] is False
    assert record["prequeue_validation"]["failure_kind"] == "H3_PROMPT_SUBMISSION_REJECTED"
    assert record["passed"] is True
    assert record["profile"] == ("deterministic_fallback" if fallback else "director_prose")
    assert record["final_hash"] == worker.ai.prompt_digest(record["final_prompt"])
    assert record["submission_state"] == "not_submitted"
    assert "prompt_id" not in record
    assert worker.task.comfyui_prompt_id == "previous-task-prompt"
    worker.client.queue_prompt.assert_not_awaited()
    window = json.loads(worker.shot.video_director_plan)["window_plans"][windows - 1]
    assert window["h3_prompt_gate_failed"] is True
    assert window["local_path"] == f"/virtual/old-{windows}.mp4"
    result = asyncio.run(worker.module.merge_video_director_clip_videos(
        worker.db, worker.shot, worker.module.ShotRepository(worker.db), "novel", "chapter", 1,
    ))
    assert result["success"] is False
    assert f"H3_PROMPT_GATE_FAILED: C{windows}" in result["message"]
    worker.storage.merge_videos.assert_not_awaited()
    worker.matches_sources.assert_not_called()

    if windows > 1:
        worker.workflow.node_mapping = json.dumps(worker.mapping)
        worker.task = worker.models.Task(
            id="retry-c1-after-mapping-rejection", type="shot_video", status="pending", name="Retry C1", description="Retry",
            novel_id="novel", chapter_id="chapter", shot_id="shot", workflow_id="workflow",
        )
        worker.db.add(worker.task)
        worker.shot.video_task_id = worker.task.id
        worker.db.commit()
        run_worker(worker, reuse=True, only_window=1, auto_merge=True)
        assert worker.task.status == "failed"
        assert "H3_PROMPT_GATE_FAILED: C2" in worker.task.error_message
        assert worker.task.result_url is None
        assert worker.shot.video_status == "failed"
        assert worker.shot.video_url == "/old-shot.mp4"
        worker.storage.merge_videos.assert_not_awaited()


@pytest.mark.parametrize("reuse", [False, True])
@pytest.mark.parametrize("failure", ["upload", "prompt"])
def test_non_h3_preexecution_reset_prevents_old_failed_clip_merge(worker, monkeypatch, reuse, failure):
    worker.configure("MULTI_KEYFRAME", windows=2, audio=False, prompt=PROMPT)
    worker.graph["h3"]["class_type"] = "LTXVConditioning"
    worker.workflow.workflow_json = json.dumps(worker.graph)
    worker.workflow.name = "MiniMaxH3 name does not determine reset policy"
    worker.db.commit()

    def previous(plan):
        plan.update(merged_video_url="/old-merged.mp4", merged_at="2026-01-01T00:00:00")
        for index, window in enumerate(plan["window_plans"], 1):
            window.update(local_path=f"/virtual/old-{index}.mp4", prompt_id=f"old-{index}",
                          workflow_json={"old": index}, source_video_url=f"/old-source-{index}.mp4",
                          generated_at="2025-12-31T00:00:00", generated_by_task_id="old-task")
        if reuse and failure == "prompt":
            plan["window_plans"][1]["prompt_text"] = ""

    edit_plan(worker, previous)
    reset = Mock(wraps=worker.module._reset_multi_clip_window_plans_for_task)
    monkeypatch.setattr(worker.module, "_reset_multi_clip_window_plans_for_task", reset)
    upload = worker.client.upload_image.side_effect
    first_upload = True

    async def check_upload(path):
        nonlocal first_upload
        if first_upload:
            first_upload = False
            plan = json.loads(worker.shot.video_director_plan)
            assert "merged_video_url" not in plan
            assert "merged_at" not in plan
            for window in plan["window_plans"]:
                for field in ("local_path", "video_url", "prompt_id", "workflow_json", "source_video_url",
                              "generated_at", "generated_by_task_id"):
                    assert field not in window
            assert ("prompt_text" in plan["window_plans"][1]) is reuse
        if failure == "upload" and path == "/virtual/kf4.png":
            return {"success": False, "message": "C2 upload failed"}
        return await upload(path)

    worker.client.upload_image.side_effect = check_upload
    if not reuse:
        worker.llm.side_effect = [
            {"success": True, "content": PROMPT},
            {"success": True, "content": PROMPT + ("\n<Subject 99> appears." if failure == "prompt" else "")},
        ]
    run_worker(worker, reuse=reuse)
    assert worker.task.status == "failed"
    assert worker.shot.video_status == "failed"
    assert worker.task.result_url is None
    plan = json.loads(worker.shot.video_director_plan)
    assert plan["window_plans"][0]["status"] == "SUCCEEDED"
    assert plan["window_plans"][1]["status"] == "FAILED"
    assert "local_path" not in plan["window_plans"][1]
    assert "video_url" not in plan["window_plans"][1]
    assert "h3_prompt_gate_failed" not in plan["window_plans"][1]
    assert all(window["user_note"] == "keep my edit" for window in plan["window_plans"])
    reset.assert_called_once_with(worker.db, worker.task, worker.shot, only_window_index=None, preserve_prompt_text=reuse)
    assert worker.llm.await_count == (0 if reuse else 2)
    assert worker.builder.await_count == (0 if reuse else 2)
    worker.client.queue_prompt.assert_awaited_once()
    assert records(worker) == {}
    result = asyncio.run(worker.module.merge_video_director_clip_videos(
        worker.db, worker.shot, worker.module.ShotRepository(worker.db), "novel", "chapter", 1,
    ))
    assert result["success"] is False
    assert "C2" in result["message"]
    assert "H3_PROMPT_GATE_FAILED" not in result["message"]
    worker.storage.merge_videos.assert_not_awaited()
    worker.matches_sources.assert_not_called()


@pytest.mark.parametrize("only_window", [None, 2])
def test_mixed_workflows_pre_reset_only_selected_non_h3_windows(worker, monkeypatch, only_window):
    worker.configure("MULTI_KEYFRAME", windows=2, audio=False, prompt=PROMPT)
    worker.workflow.name = "Legacy-looking name for a real H3 graph"
    legacy_graph = deepcopy(worker.graph)
    legacy_graph["h3"]["class_type"] = "LTXVConditioning"
    worker.db.add(type(worker.workflow)(
        id="non-h3-four-frame", name="MiniMaxH3 misleading name", type="four_frame_video", is_active=True,
        workflow_json=json.dumps(legacy_graph), node_mapping=json.dumps(worker.mapping),
    ))
    worker.db.commit()

    def mixed(plan):
        for index, window in enumerate(plan["window_plans"], 1):
            window.update(local_path=f"/virtual/old-{index}.mp4", prompt_id=f"old-{index}")
        plan["window_plans"][1].update(selected_frame_count=4, keyframe_indexes=[4, 5, 6, 7])
        plan["keyframes"].append({"index": 7, "role": "END", "time_seconds": 8,
                                  "description": "Final state", "image_url": "/api/files/kf7.png"})

    edit_plan(worker, mixed)
    reset = Mock(wraps=worker.module._reset_multi_clip_window_plans_for_task)
    monkeypatch.setattr(worker.module, "_reset_multi_clip_window_plans_for_task", reset)
    upload = worker.client.upload_image.side_effect
    first_upload = True

    async def check_upload(path):
        nonlocal first_upload
        if first_upload:
            first_upload = False
            windows = json.loads(worker.shot.video_director_plan)["window_plans"]
            assert windows[0]["local_path"] == "/virtual/old-1.mp4"
            assert windows[0]["prompt_id"] == "old-1"
            assert "local_path" not in windows[1]
            assert "prompt_id" not in windows[1]
            assert windows[1]["prompt_text"] == PROMPT
            reset.assert_called_once_with(worker.db, worker.task, worker.shot, only_window_index=2, preserve_prompt_text=True)
        if path == "/virtual/kf4.png":
            return {"success": False, "message": "C2 upload failed"}
        return await upload(path)

    worker.client.upload_image.side_effect = check_upload
    run_worker(worker, reuse=True, only_window=only_window)
    assert worker.task.status == "failed"
    windows = json.loads(worker.shot.video_director_plan)["window_plans"]
    assert "local_path" not in windows[1]
    assert "video_url" not in windows[1]
    assert "h3_prompt_gate_failed" not in windows[1]
    if only_window is None:
        assert [call.kwargs["only_window_index"] for call in reset.call_args_list] == [2, 1]
        assert records(worker, 1)[0]["prequeue_validation"]["passed"] is True
        worker.client.queue_prompt.assert_awaited_once()
        worker.builder.assert_awaited_once()
    else:
        assert reset.call_count == 1
        assert windows[0]["local_path"] == "/virtual/old-1.mp4"
        worker.client.queue_prompt.assert_not_awaited()
        worker.builder.assert_not_awaited()
    worker.llm.assert_not_awaited()


@pytest.mark.parametrize("audio", [False, True])
@pytest.mark.parametrize("case_id,code", [("115C1", "DIRECTOR_SECTIONS_MISSING"), ("119C3", "EMPTY_CORE")])
def test_initial_single_empty_clips_core_failure_marks_shot_without_creating_clip(worker, audio, case_id, code):
    worker.configure(audio=audio, audio_collection="execution_windows" if audio else None)
    worker.shot.video_status = "generating"
    worker.shot.video_url = None
    worker.db.commit()
    edit_plan(worker, lambda plan: plan.update(clips=[]))
    worker.llm.return_value = {"success": True, "content": HISTORY["cases"][case_id]["core"]}
    run_worker(worker)
    assert worker.task.status == "failed"
    assert worker.shot.video_status == "failed"
    assert worker.shot.video_url is None
    assert json.loads(worker.shot.video_director_plan)["clips"] == []
    record = records(worker, 1)[0]
    assert record["target"]["clip_structure"]["owner"] is None
    assert record["errors"][0]["code"] == code
    assert record["submission_state"] == "not_submitted"
    assert "prompt_id" not in record
    worker.llm.assert_awaited_once()
    worker.client.queue_prompt.assert_not_awaited()
