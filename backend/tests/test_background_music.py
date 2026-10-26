import json
from array import array
import shutil
import subprocess

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.novel import Chapter, Novel
from app.models.task import Task
from app.models.prompt_template import PromptTemplate
from app.models.workflow import Workflow
from app.services.background_music_service import (_assemble_preview, _ensure_cue_preview, _prepare_generation_text,
                                                   _probe_seconds, _set_cue_duration, _validate_plan,
                                                   format_background_music_prompt,
                                                   enqueue_background_music_task, run_background_music_task)
from app.services.background_workers import PersistentJobRequest
from app.services.novel_video_merge_service import _mix_chapter_background_music
from app.services.notification_registry import EVENT_REGISTRY
from app.repositories.workflow import WorkflowRepository
from app.services.workflow_service import WorkflowService
from app.services.prompt_template_service import PromptTemplateService
from app.services.task_service import TaskService


def test_batch_music_request_only_enqueues_worker_jobs(client, db_session, monkeypatch, tmp_path):
    novel = Novel(title="药")
    db_session.add(novel)
    db_session.flush()
    chapters = [Chapter(novel_id=novel.id, number=index, title=f"第{index}章",
                        final_video=f"/api/files/chapter-{index}.mp4") for index in (1, 2)]
    db_session.add_all(chapters)
    db_session.commit()
    for index in (1, 2):
        (tmp_path / f"chapter-{index}.mp4").write_bytes(b"video")
    monkeypatch.setattr("app.api.background_music.url_to_local_path",
                        lambda url: str(tmp_path / url.rsplit("/", 1)[-1]))
    queued = []
    monkeypatch.setattr("app.api.background_music.enqueue_background_music_task", queued.append)

    response = client.post(f"/api/novels/{novel.id}/background-music",
                           json={"chapter_ids": [chapters[1].id, chapters[0].id]})
    assert response.status_code == 200
    tasks = db_session.query(Task).filter_by(type="chapter_background_music").order_by(Task.chapter_id).all()
    assert len(tasks) == 2
    assert set(queued) == {task.id for task in tasks}
    assert all(task.status == "pending" and not task.comfyui_prompt_id for task in tasks)
    assert all(json.loads(task.metadata_json)["source_video_url"] in
               {chapter.final_video for chapter in chapters} for task in tasks)
    assert all(json.loads(task.metadata_json)["music_mode"] == "partial" for task in tasks)
    duplicate = client.post(f"/api/novels/{novel.id}/background-music",
                            json={"chapter_ids": [chapters[0].id]})
    assert duplicate.status_code == 409
    listing = client.get(f"/api/novels/{novel.id}/background-music")
    assert listing.status_code == 200
    assert set(listing.json()["data"]) == {chapter.id for chapter in chapters}


def test_full_music_request_replaces_effective_chapter_selection(client, db_session, monkeypatch, tmp_path):
    novel = Novel(title="故事")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="起伏", final_video="/api/files/chapter.mp4")
    db_session.add(chapter)
    db_session.commit()
    (tmp_path / "chapter.mp4").write_bytes(b"video")
    monkeypatch.setattr("app.api.background_music.url_to_local_path", lambda _: str(tmp_path / "chapter.mp4"))
    monkeypatch.setattr("app.api.background_music.enqueue_background_music_task", lambda _: None)
    old = Task(type="chapter_background_music", status="completed", name="旧配乐",
               novel_id=novel.id, chapter_id=chapter.id, result_url="/api/files/old.m4a",
               metadata_json=json.dumps({"source_video_url": chapter.final_video}))
    db_session.add(old)
    db_session.commit()

    created = client.post(f"/api/novels/{novel.id}/background-music",
                          json={"chapter_ids": [chapter.id], "mode": "full"})
    assert created.status_code == 200
    assert created.json()["data"][0]["mode"] == "full"
    latest = client.get(f"/api/novels/{novel.id}/background-music").json()["data"][chapter.id]
    assert latest["id"] == created.json()["data"][0]["id"]
    assert latest["audioUrl"] is None
    assert TaskService.format_task_list([db_session.get(Task, latest["id"])], {}, {}, {})[0]["musicMode"] == "full"
    assert db_session.get(Task, old.id) is not None  # Historical task remains auditable.


def test_background_music_uses_durable_worker_descriptor(monkeypatch):
    captured = []

    class FakeWorker:
        def enqueue(self, request):
            captured.append(request)

    monkeypatch.setattr("app.services.background_music_service.worker_manager.worker",
                        lambda queue: FakeWorker() if queue == "background_music" else pytest.fail("wrong queue"))
    enqueue_background_music_task("music-task")
    assert len(captured) == 1
    assert isinstance(captured[0], PersistentJobRequest)
    assert captured[0].task_id == "music-task"
    assert captured[0].handler == "app.services.background_music_service:run_background_music_task"


def test_system_music_workflow_maps_style_lyrics_and_decimal_duration(db_session):
    WorkflowService(db_session).load_default_workflows()
    workflow = WorkflowRepository(db_session).get_active_by_type("background_music")
    assert workflow is not None and workflow.is_system
    graph = json.loads(workflow.workflow_json)
    mapping = json.loads(workflow.node_mapping)
    for key in ("music_style_node_id", "music_lyrics_node_id"):
        assert graph[mapping[key]]["class_type"] == "CR Prompt Text"
        assert isinstance(graph[mapping[key]]["inputs"]["prompt"], str)
    assert graph[mapping["save_audio_node_id"]]["class_type"] == "SaveAudio"
    generation = next(node for node in graph.values() if node["class_type"] == "TextEncodeAceStepAudio1.5")
    assert generation["inputs"]["tags"] == [mapping["music_style_node_id"], 0]
    assert generation["inputs"]["lyrics"] == [mapping["music_lyrics_node_id"], 0]
    assert graph[mapping["music_duration_node_id"]]["class_type"] == "EmptyAceStep1.5LatentAudio"
    assert generation is graph[mapping["music_conditioning_node_id"]]
    _set_cue_duration(graph, mapping, 13.184)
    assert graph[mapping["music_duration_node_id"]]["inputs"]["seconds"] == 13.184
    assert generation["inputs"]["duration"] == 13.184
    assert isinstance(graph[mapping["music_duration_node_id"]]["inputs"]["seconds"], float)
    with pytest.raises(ValueError, match="1～1000"):
        _set_cue_duration(graph, mapping, 1000.001)


def test_music_preset_refreshes_old_name_even_when_graph_is_current(db_session):
    service = WorkflowService(db_session)
    service.load_default_workflows()
    workflow = WorkflowRepository(db_session).get_active_by_type("background_music")
    workflow.name = "ACE-Step 纯器乐背景音乐 V1"
    db_session.commit()

    service.load_default_workflows()
    db_session.expire_all()
    assert db_session.get(Workflow, workflow.id).name == "ACE-Step1.5 纯器乐背景音乐 V1"


def test_ace_step_replaces_old_active_system_preset_once(db_session):
    service = WorkflowService(db_session)
    service.load_default_workflows()
    workflows = db_session.query(Workflow).filter(Workflow.type == "background_music").all()
    ace = next(item for item in workflows if item.name.startswith("ACE-Step"))
    legacy = Workflow(type="background_music", name="YuE2 纯器乐背景音乐 V1", is_system=True,
        is_active=True, file_path="/old/yue2_background_music_v1.json", workflow_json="{}")
    ace.is_active = False
    db_session.add(legacy)
    db_session.commit()
    service.load_default_workflows()
    active = WorkflowRepository(db_session).get_active_by_type("background_music")
    assert active is not None and active.id == ace.id
    assert db_session.get(Workflow, legacy.id) is None


def test_ace_step_becomes_active_when_retired_yue2_has_task_history(db_session):
    service = WorkflowService(db_session)
    service.load_default_workflows()
    ace = WorkflowRepository(db_session).get_active_by_type("background_music")
    ace.is_active = False
    legacy = Workflow(type="background_music", name="YuE2 纯器乐背景音乐 V1", is_system=True,
        is_active=True, file_path="/old/yue2_background_music_v1.json", workflow_json="{}")
    db_session.add(legacy)
    db_session.flush()
    db_session.add(Task(type="chapter_background_music", status="completed", name="历史配乐",
                        workflow_id=legacy.id))
    db_session.commit()

    service.load_default_workflows()
    db_session.expire_all()
    assert db_session.get(Workflow, legacy.id) is not None
    assert db_session.get(Workflow, legacy.id).is_active is False
    assert WorkflowRepository(db_session).get_active_by_type("background_music").id == ace.id


def test_background_music_prompt_includes_plan_and_submitted_tags():
    prompt = format_background_music_prompt({"cues": [{"index": 1, "startShot": 2, "endShot": 3,
        "style": "Sparse strings", "melody": "Descending phrase", "soundPriority": "对白优先",
        "generationStyle": "instrumental, sparse strings, descending phrase, no vocals",
        "lyrics": "[inst]"}]})
    assert "导演风格: Sparse strings" in prompt
    assert "旋律: Descending phrase" in prompt
    assert "生成标签 tags: instrumental, sparse strings, descending phrase, no vocals" in prompt


@pytest.mark.asyncio
async def test_ace_step_prompt_passes_cue_duration_and_parses_music_metadata(db_session, monkeypatch):
    monkeypatch.setattr("app.services.background_music_service._read_template", lambda *_: "ACE-Step 1.5 prompt")
    received = {}

    class FakeLLM:
        async def chat_completion(self, **kwargs):
            received.update(kwargs)
            return {"success": True, "content": json.dumps({
                "tags": "sparse cinematic strings, descending melody, warm and restrained, instrumental, no vocals",
                "lyrics": "[inst]", "bpm": 68, "keyscale": "D minor", "timesignature": "4",
            })}

    chapter = Chapter(novel_id="novel-1", id="chapter-1")
    cue = {"style": "Sparse strings", "melody": "Descending phrase",
           "soundPriority": "对白优先", "durationSeconds": 11.552}
    tags, lyrics, bpm, keyscale, timesignature = await _prepare_generation_text(
        FakeLLM(), db_session, chapter, cue)
    assert json.loads(received["user_content"])["duration_seconds"] == 11.552
    assert (lyrics, bpm, keyscale, timesignature) == ("[inst]", 68, "D minor", "4")
    assert "descending melody" in tags
    assert "no sound effects or environmental ambience" in tags


def test_music_system_prompts_separate_score_from_h3_sound_effects(db_session):
    PromptTemplateService(db_session).init_system_templates()
    director = db_session.query(PromptTemplate).filter_by(
        type="background_music_director", is_system=True).one()
    full_director = db_session.query(PromptTemplate).filter_by(
        type="background_music_director_full", is_system=True).one()
    generation = db_session.query(PromptTemplate).filter_by(
        type="background_music_generation", is_system=True).one()
    assert "MiniMax H3 视频已负责" in director.template
    assert "第一段必须从首个 Shot 开始" in full_director.template
    assert "MiniMax H3 已负责对白、脚步、风" in full_director.template
    assert "sound_priority 只说明配乐应给哪些已有声音让位" in generation.template


def test_existing_music_task_workflow_shows_saved_plan(client, db_session):
    task = Task(type="chapter_background_music", status="completed", name="背景音乐",
        workflow_json='{"14":{"class_type":"CR Prompt Text","inputs":{"prompt":"instrumental strings"}}}',
        metadata_json=json.dumps({"cues": [{"index": 1, "startShot": 1, "endShot": 2,
            "style": "Sparse strings", "melody": "Descending phrase",
            "generationStyle": "instrumental strings"}]}))
    db_session.add(task)
    db_session.commit()
    result = client.get(f"/api/tasks/{task.id}/workflow/")
    assert result.status_code == 200
    assert "导演风格: Sparse strings" in result.json()["data"]["prompt"]
    assert "旋律: Descending phrase" in result.json()["data"]["prompt"]


def test_legacy_music_prompt_is_upgraded_to_ace_step_1_5(db_session):
    legacy = PromptTemplate(name="YuE2 纯器乐生成约束 V1", type="background_music_generation",
        template="legacy", description="legacy", is_system=True, is_active=True)
    db_session.add(legacy)
    db_session.commit()
    legacy_id = legacy.id
    PromptTemplateService(db_session).init_system_templates()
    db_session.expire_all()
    upgraded = db_session.get(PromptTemplate, legacy_id)
    assert upgraded.name == "ACE-Step1.5 纯器乐标签 V1"
    assert "ACE-Step 1.5" in upgraded.template
    assert not db_session.query(PromptTemplate).filter_by(name="YuE2 纯器乐生成约束 V1").first()


def test_director_plan_validates_source_evidence_and_shot_boundaries():
    chapter = Chapter(number=1, content="他推开门，风吹过空院，随后久久没有人说话。")
    spans = [
        {"index": 1, "start_seconds": 0, "end_seconds": 8, "dialogues": []},
        {"index": 2, "start_seconds": 8, "end_seconds": 16, "dialogues": [{"text": "你好"}]},
    ]
    cue = {"start_shot": 1, "end_shot": 2, "reason": "气氛转折",
           "evidence_quote": "风吹过空院", "sound_priority": "对白优先",
           "style": "Sparse low strings", "melody": "A slow descending phrase"}
    reason, result = _validate_plan({"chapters": [{"chapter_number": 1,
        "no_music_reason": "", "cues": [cue]}]}, chapter, spans)
    assert reason == ""
    assert result[0]["startSeconds"] == 0
    assert result[0]["durationSeconds"] == 16
    assert result[0]["gainDb"] == -27
    with pytest.raises(ValueError, match="证据"):
        _validate_plan({"chapters": [{"chapter_number": 1, "cues": [
            {**cue, "evidence_quote": "原文不存在的内容"}]}]}, chapter, spans)
    with pytest.raises(ValueError, match="重叠"):
        _validate_plan({"chapters": [{"chapter_number": 1, "cues": [cue, cue]}]}, chapter, spans)


def test_full_chapter_director_requires_contiguous_music_from_first_to_last_shot():
    chapter = Chapter(number=1, content="先是安静的夜晚，随后他们奔跑，最后终于重逢。")
    spans = [{"index": index, "start_seconds": (index - 1) * 8,
              "end_seconds": index * 8, "dialogues": []} for index in (1, 2, 3)]
    def cue(start, end, evidence):
        return {"start_shot": start, "end_shot": end, "reason": "情绪变化",
                "evidence_quote": evidence, "sound_priority": "对白优先",
                "style": "Restrained instrumental score", "melody": "Short rising motif"}
    def plan(cues):
        return {"chapters": [{"chapter_number": 1, "no_music_reason": "", "cues": cues}]}
    _, result = _validate_plan(plan([cue(1, 1, "安静的夜晚"), cue(2, 3, "最后终于重逢")]),
                               chapter, spans, "full")
    assert [(item["startSeconds"], item["endSeconds"]) for item in result] == [(0, 8), (8, 24)]
    for invalid in ([], [cue(2, 3, "最后终于重逢")],
                    [cue(1, 1, "安静的夜晚"), cue(3, 3, "最后终于重逢")],
                    [cue(1, 2, "安静的夜晚")]):
        with pytest.raises(ValueError):
            _validate_plan(plan(invalid), chapter, spans, "full")


@pytest.mark.asyncio
async def test_worker_records_intentional_no_music_without_calling_comfyui(db_session, db_engine, monkeypatch, tmp_path):
    novel = Novel(title="药")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="安静", content="风吹过空院。",
                      final_video="/api/files/chapter.mp4")
    db_session.add(chapter)
    db_session.flush()
    task = Task(type="chapter_background_music", status="pending", name="背景音乐",
                novel_id=novel.id, chapter_id=chapter.id,
                metadata_json=json.dumps({"source_video_url": chapter.final_video}))
    db_session.add(task)
    db_session.commit()
    video = tmp_path / "chapter.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr("app.services.background_music_service.SessionLocal", sessionmaker(bind=db_engine))
    monkeypatch.setattr("app.services.background_music_service.url_to_local_path", lambda _: str(video))
    monkeypatch.setattr("app.services.background_music_service._probe_seconds", lambda _: 5.0)
    monkeypatch.setattr("app.services.background_music_service._shot_spans",
                        lambda *_: [{"index": 1, "start_seconds": 0, "end_seconds": 5,
                                     "scene": "", "description": "", "video_description": "", "dialogues": []}])
    monkeypatch.setattr("app.services.background_music_service._read_template", lambda *_: "系统提示词")

    class FakeLLM:
        async def chat_completion(self, **_kwargs):
            return {"success": True, "content": json.dumps({"chapters": [{"chapter_number": 1,
                "no_music_reason": "环境声优先", "cues": []}]}, ensure_ascii=False)}

    monkeypatch.setattr("app.services.background_music_service.LLMService", FakeLLM)
    monkeypatch.setattr("app.services.background_music_service.ComfyUIClient.for_product_runtime",
                        lambda *_: pytest.fail("无音乐章节不应调用 ComfyUI"))
    await run_background_music_task(task.id)
    db_session.expire_all()
    saved = db_session.get(Task, task.id)
    assert saved.status == "completed"
    assert saved.result_url is None
    assert json.loads(saved.metadata_json)["no_music_reason"] == "环境声优先"


@pytest.mark.asyncio
async def test_full_music_worker_uses_full_director_and_rejects_silent_plan(db_session, db_engine, monkeypatch, tmp_path):
    novel = Novel(title="故事")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="起伏", content="夜里响起鼓声。",
                      final_video="/api/files/chapter.mp4")
    db_session.add(chapter)
    db_session.flush()
    task = Task(type="chapter_background_music", status="pending", name="全章音乐",
                novel_id=novel.id, chapter_id=chapter.id,
                metadata_json=json.dumps({"source_video_url": chapter.final_video, "music_mode": "full"}))
    db_session.add(task)
    db_session.commit()
    video = tmp_path / "chapter.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr("app.services.background_music_service.SessionLocal", sessionmaker(bind=db_engine))
    monkeypatch.setattr("app.services.background_music_service.url_to_local_path", lambda _: str(video))
    monkeypatch.setattr("app.services.background_music_service._probe_seconds", lambda _: 5.0)
    monkeypatch.setattr("app.services.background_music_service._shot_spans",
                        lambda *_: [{"index": 1, "start_seconds": 0, "end_seconds": 5,
                                     "scene": "", "description": "", "video_description": "", "dialogues": []}])
    monkeypatch.setattr("app.services.background_music_service._read_template", lambda _, kind: kind)
    captured = {}

    class FakeLLM:
        async def chat_completion(self, **kwargs):
            captured.update(kwargs)
            return {"success": True, "content": json.dumps({"chapters": [{"chapter_number": 1,
                "no_music_reason": "留白", "cues": []}]}, ensure_ascii=False)}

    monkeypatch.setattr("app.services.background_music_service.LLMService", FakeLLM)
    await run_background_music_task(task.id)
    db_session.expire_all()
    assert captured["system_prompt"] == "background_music_director_full"
    assert captured["task_type"] == "background_music_director_full"
    assert db_session.get(Task, task.id).status == "failed"
    assert "配乐段数无效" in db_session.get(Task, task.id).error_message


def test_background_music_events_are_available_in_notification_settings(client):
    response = client.get("/api/notifications/config")
    assert response.status_code == 200
    events = {item["event_code"]: item for item in response.json()["data"]["events"]}
    for code in ("background_music.generation.completed", "background_music.generation.failed",
                 "novel.video.merge.completed", "novel.video.merge.failed"):
        assert code in EVENT_REGISTRY
        assert events[code]["enabled"] is True


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg unavailable")
def test_long_yue2_output_is_clipped_for_cue_player_and_keeps_raw_for_mix(tmp_path, monkeypatch):
    source = tmp_path / "cue-01.flac"
    preview = tmp_path / "cue-01-preview.m4a"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                    "sine=frequency=330:duration=4", "-c:a", "flac", "-y", str(source)], check=True)
    monkeypatch.setattr("app.services.background_music_service.local_path_to_url",
                        lambda path: f"/api/files/{tmp_path.joinpath(path).name}")
    cue = {"index": 1, "durationSeconds": 1.25,
           "audioUrl": "/api/files/cue-01.flac", "audioSeconds": 4.0}
    _ensure_cue_preview(cue, source, preview)
    assert cue["audioUrl"] == "/api/files/cue-01-preview.m4a"
    assert cue["rawAudioUrl"] == "/api/files/cue-01.flac"
    assert abs(cue["audioSeconds"] - 1.25) < 0.1
    assert abs(cue["rawAudioSeconds"] - 4.0) < 0.1
    assert abs(_probe_seconds(str(source)) - 4.0) < 0.1
    _ensure_cue_preview(cue, source, preview)
    assert abs(_probe_seconds(str(preview)) - 1.25) < 0.1


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg unavailable")
def test_sparse_preview_and_chapter_mix_preserve_video_duration(tmp_path, monkeypatch):
    cue_audio = tmp_path / "cue.flac"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                    "sine=frequency=330:duration=3", "-c:a", "flac", "-y", str(cue_audio)], check=True)
    monkeypatch.setattr("app.services.background_music_service.url_to_local_path",
                        lambda _: str(cue_audio))
    preview = tmp_path / "preview.m4a"
    _assemble_preview([{"audioUrl": "/api/files/cue.flac", "startSeconds": 1,
                        "durationSeconds": 2, "gainDb": -23}], preview, 4)
    assert abs(_probe_seconds(str(preview)) - 4) < 0.25

    chapter_video = tmp_path / "chapter.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                    "color=c=black:s=160x120:r=15:d=4", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=4", "-c:v", "mpeg4", "-c:a", "aac",
                    "-shortest", "-y", str(chapter_video)], check=True)
    mixed = tmp_path / "mixed.mp4"
    _mix_chapter_background_music(str(chapter_video), str(preview), str(mixed))
    assert abs(_probe_seconds(str(mixed)) - _probe_seconds(str(chapter_video))) < 0.25

    silent_chapter = tmp_path / "silent-chapter.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                    "color=c=black:s=160x120:r=15:d=4", "-c:v", "mpeg4", "-y",
                    str(silent_chapter)], check=True)
    mixed_silent = tmp_path / "mixed-silent.mp4"
    _mix_chapter_background_music(str(silent_chapter), str(preview), str(mixed_silent))
    assert abs(_probe_seconds(str(mixed_silent)) - 4) < 0.25


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg unavailable")
def test_full_chapter_track_stretches_short_cue_and_reaches_last_second(tmp_path, monkeypatch):
    short = tmp_path / "short.flac"
    final = tmp_path / "final.flac"
    for path, length, frequency in ((short, 1.8, 330), (final, 2.0, 440)):
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                        f"sine=frequency={frequency}:duration={length}", "-c:a", "flac", "-y", str(path)], check=True)
    monkeypatch.setattr("app.services.background_music_service.url_to_local_path",
                        lambda url: str(tmp_path / url.rsplit("/", 1)[-1]))
    monkeypatch.setattr("app.services.background_music_service.local_path_to_url",
                        lambda path: f"/api/files/{path.rsplit('/', 1)[-1]}")
    cue_preview = tmp_path / "short-preview.m4a"
    short_cue = {"rawAudioUrl": "/api/files/short.flac", "startSeconds": 0,
                 "durationSeconds": 2.0, "gainDb": -23}
    _ensure_cue_preview(short_cue, short, cue_preview, "full")
    assert abs(_probe_seconds(str(cue_preview)) - 2.0) < 0.1
    preview = tmp_path / "full-preview.m4a"
    _assemble_preview([short_cue, {"rawAudioUrl": "/api/files/final.flac", "rawAudioSeconds": 2.0,
                   "startSeconds": 2.0, "durationSeconds": 2.0, "gainDb": -23}], preview, 4.0, "full")
    assert abs(_probe_seconds(str(preview)) - 4.0) < 0.1
    decoded = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(preview),
                              "-ac", "1", "-ar", "48000", "-f", "s16le", "pipe:1"],
                             check=True, capture_output=True).stdout
    samples = array("h")
    samples.frombytes(decoded)
    for start in (1.85, 3.85):
        window = samples[int(start * 48000):int((start + 0.1) * 48000)]
        assert max(abs(sample) for sample in window) > 100
