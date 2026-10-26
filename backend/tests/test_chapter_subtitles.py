"""Subtitle artifacts must share the same valid, final-video cue timeline."""

import asyncio
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker

from app.services.chapter_subtitles import _aligned_cues, _duration, _reference_for_cues, _run_media, burn_subtitles, correct_cue_text, english_cues, read_cues, translate_cues, validate_cues, write_cues, write_srt
from app.services.comfyui.client import ComfyUIClient
from app.constants.workflow import EXTRA_SYSTEM_WORKFLOWS
from app.models.task import Task
from app.models.background_job import BackgroundJob
from app.services.background_workers import WorkerManager


def test_new_qwen_hf_workflows_are_registered_for_distinct_purposes():
    root = Path(__file__).resolve().parents[1] / "workflows"
    presets = {item["type"]: item for item in EXTRA_SYSTEM_WORKFLOWS
               if item["type"] in {"subtitle_asr", "audio_transcription"}}
    assert set(presets) == {"subtitle_asr", "audio_transcription"}
    aligned = json.loads((root / presets["subtitle_asr"]["filename"]).read_text())
    text_only = json.loads((root / presets["audio_transcription"]["filename"]).read_text())
    assert aligned["11"]["class_type"] == "AILab_Qwen3ASRSubtitle"
    assert aligned["18"]["class_type"] == "AILab_Qwen3TimestampColumns"
    assert aligned["11"]["inputs"]["model"] == "Qwen/Qwen3-ASR-1.7B-hf"
    assert aligned["11"]["inputs"]["forced_aligner"] == "Qwen/Qwen3-ForcedAligner-0.6B-hf"
    assert text_only["11"]["class_type"] == "AILab_Qwen3ASR"
    for config, graph in ((presets["subtitle_asr"], aligned), (presets["audio_transcription"], text_only)):
        for node_id in config["node_mapping"].values():
            assert node_id in graph
    assert _aligned_cues({
        "19": "第一章，\n甄士隐梦幻识通灵，贾雨村风尘怀闺秀。",
        "20": "0.720\n2.080", "21": "1.440\n6.640",
    }, presets["subtitle_asr"]["node_mapping"], 60, 70) == [
        {"start": 60.72, "end": 61.44, "text": "第一章，"},
        {"start": 62.08, "end": 66.64, "text": "甄士隐梦幻识通灵，贾雨村风尘怀闺秀。"},
    ]


def test_aligned_cues_keep_chunk_offset_and_reject_mismatched_outputs():
    mapping = {
        "timestamps_output_node_id": "17",
        "text_list_output_node_id": "19", "start_times_output_node_id": "20",
        "end_times_output_node_id": "21",
    }
    outputs = {"19": "['第一句', '第二句']", "20": "[0.5, 2.0]", "21": "[1.5, 3.0]"}
    assert _aligned_cues(outputs, mapping, 60, 64) == [
        {"start": 60.5, "end": 61.5, "text": "第一句"},
        {"start": 62.0, "end": 63.0, "text": "第二句"},
    ]
    with pytest.raises(ValueError, match="数量不一致"):
        _aligned_cues({**outputs, "21": "[1.5]"}, mapping, 60, 64)
    assert _aligned_cues({"17": "第一句\t0.5\t1.5\n第二句\t2\t3"}, mapping, 60, 64) == [
        {"start": 60.5, "end": 61.5, "text": "第一句"},
        {"start": 62.0, "end": 63.0, "text": "第二句"},
    ]


def test_aligner_zero_length_cue_at_chunk_boundary_does_not_fail_merge():
    mapping = {"text_list_output_node_id": "19", "start_times_output_node_id": "20",
               "end_times_output_node_id": "21"}
    # Real AILab output from the failed 5-chapter merge: the final token has
    # no duration because it falls exactly on the 60-second chunk boundary.
    outputs = {"19": "这么多。\n嗯。", "20": "59.600\n60.000", "21": "60.000\n60.000"}
    diagnostics = {}
    assert _aligned_cues(outputs, mapping, 0, 219, chunk_duration=60.02,
                         diagnostics=diagnostics) == [
        {"start": 59.6, "end": 60.0, "text": "这么多。"},
    ]
    assert diagnostics == {"skipped_cue_count": 1}
    with pytest.raises(ValueError, match="超出音频分片"):
        _aligned_cues({"19": "错", "20": "61", "21": "62"}, mapping, 0, 219, chunk_duration=60)


def test_subtitle_time_validation_rejects_outside_final_video():
    with pytest.raises(ValueError, match="成片范围"):
        validate_cues([{"start": 1.0, "end": 3.0, "text": "越界"}], 2.0)
    with pytest.raises(ValueError, match="有序"):
        validate_cues([
            {"start": 1.0, "end": 1.5, "text": "后"},
            {"start": 0.2, "end": 0.5, "text": "前"},
        ], 2.0)


def test_cues_sidecar_can_be_reloaded_without_task_metadata_blob(tmp_path, monkeypatch):
    path = tmp_path / "cues.json"
    cues = [{"start": 0.2, "end": 0.8, "text": "测试"}]
    write_cues(cues, path)
    monkeypatch.setattr("app.utils.path_utils.url_to_local_path", lambda url: str(path))
    assert read_cues({"cues_url": "/api/files/cues.json", "count": 1}) == cues


def test_auto_correction_only_replaces_text_and_uses_matching_chapter(monkeypatch):
    references = [
        {"start": 0, "end": 10, "label": "第一章", "text": "无关正文"},
        {"start": 10, "end": 20, "label": "第二章", "text": "王戎说这棵李子树很奇怪"},
    ]
    cues = [{"start": 12.1234, "end": 13.5678, "text": "王荣说这颗李子树很奇怪"}]
    assert _reference_for_cues(cues, references) == [
        {"chapter": "第二章", "text": "王戎说这棵李子树很奇怪"},
    ]
    monkeypatch.setattr("app.services.chapter_subtitles.PromptTemplateService",
                        lambda db: SimpleNamespace(get_default_system_template=lambda _: SimpleNamespace(
                            name="字幕文本校对", template="只修正文案")))

    class FakeLLM:
        async def chat_completion(self, **kwargs):
            payload = json.loads(kwargs["user_content"])
            assert payload["dialogues"] == [{"chapter": "第二章", "text": "王戎说这棵李子树很奇怪"}]
            assert payload["cues"] == [{"index": 1, "text": cues[0]["text"]}]
            assert "start" not in kwargs["user_content"] and "end" not in kwargs["user_content"]
            return {"success": True, "content": '{"segments":[{"index":1,"text":"王戎说这棵李子树很奇怪"}]}' }

    monkeypatch.setattr("app.services.chapter_subtitles.LLMService", FakeLLM)
    corrected = asyncio.run(correct_cue_text(None, cues, references, "novel", ""))
    assert corrected == [{"start": 12.1234, "end": 13.5678, "text": "王戎说这棵李子树很奇怪"}]
    assert cues[0]["text"] == "王荣说这颗李子树很奇怪"


def test_auto_correction_rejects_extra_timestamp_fields(monkeypatch):
    monkeypatch.setattr("app.services.chapter_subtitles.PromptTemplateService",
                        lambda db: SimpleNamespace(get_default_system_template=lambda _: SimpleNamespace(
                            name="字幕文本校对", template="只修正文案")))

    class FakeLLM:
        async def chat_completion(self, **kwargs):
            return {"success": True, "content": '{"segments":[{"index":1,"text":"文本","start":0}]}' }

    monkeypatch.setattr("app.services.chapter_subtitles.LLMService", FakeLLM)
    cues = [{"start": 1.0, "end": 2.0, "text": "原文"}]
    references = [{"start": 0, "end": 3, "label": "第一章", "text": "参考"}]
    with pytest.raises(ValueError, match="格式无效"):
        asyncio.run(correct_cue_text(None, cues, references, "novel", ""))
    assert cues == [{"start": 1.0, "end": 2.0, "text": "原文"}]


def test_bilingual_translation_preserves_timestamps_and_existing_english(monkeypatch):
    monkeypatch.setattr("app.services.chapter_subtitles.PromptTemplateService",
                        lambda db: SimpleNamespace(get_default_system_template=lambda _: SimpleNamespace(
                            name="字幕英文翻译", template="仅翻译文字")))
    cues = [
        {"start": 0.1234, "end": 1.5678, "text": "你好"},
        {"start": 2.0, "end": 3.0, "text": "再见", "en_text": "Goodbye"},
    ]
    class FakeLLM:
        async def chat_completion(self, **kwargs):
            assert kwargs["task_type"] == "subtitle_translation"
            assert json.loads(kwargs["user_content"]) == {"segments": [{"index": 1, "text": "你好"}]}
            assert "start" not in kwargs["user_content"] and "end" not in kwargs["user_content"]
            return {"success": True, "content": '{"segments":[{"index":1,"text":"Hello"}]}' }
    monkeypatch.setattr("app.services.chapter_subtitles.LLMService", FakeLLM)
    result = asyncio.run(translate_cues(None, cues, "novel", "chapter"))
    assert result == [
        {"start": 0.1234, "end": 1.5678, "text": "你好", "en_text": "Hello"},
        {"start": 2.0, "end": 3.0, "text": "再见", "en_text": "Goodbye"},
    ]
    assert "en_text" not in cues[0]
    assert english_cues(result) == [
        {"start": 0.1234, "end": 1.5678, "text": "Hello"},
        {"start": 2.0, "end": 3.0, "text": "Goodbye"},
    ]


def test_bilingual_translation_rejects_timestamps_from_llm(monkeypatch):
    monkeypatch.setattr("app.services.chapter_subtitles.PromptTemplateService",
                        lambda db: SimpleNamespace(get_default_system_template=lambda _: SimpleNamespace(
                            name="字幕英文翻译", template="仅翻译文字")))
    class FakeLLM:
        async def chat_completion(self, **kwargs):
            return {"success": True, "content": '{"segments":[{"index":1,"text":"Hello","start":0}]}' }
    monkeypatch.setattr("app.services.chapter_subtitles.LLMService", FakeLLM)
    cues = [{"start": 1.0, "end": 2.0, "text": "你好"}]
    with pytest.raises(ValueError, match="格式无效"):
        asyncio.run(translate_cues(None, cues, "novel", "chapter"))
    assert cues == [{"start": 1.0, "end": 2.0, "text": "你好"}]


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg not installed")
def test_subtitle_save_endpoint_reburns_disposable_video(client, db_session, db_engine, tmp_path, monkeypatch):
    source = tmp_path / "test-source.mp4"
    _run_media(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=640x360:d=2",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                "-c:v", "libx264", "-c:a", "aac", "-shortest", str(source)])
    srt_path, cues_path = tmp_path / "test.srt", tmp_path / "test.json"
    original = [{"start": 0.2, "end": 1.8, "text": "原字幕"}]
    write_srt(original, srt_path)
    write_cues(original, cues_path)
    def resolve(url):
        path = tmp_path / url.removeprefix("/api/files/")
        return str(path) if url.startswith("/api/files/") and path.is_file() else None
    monkeypatch.setattr("app.services.subtitle_render_service.url_to_local_path", resolve)
    monkeypatch.setattr("app.utils.path_utils.url_to_local_path", resolve)
    monkeypatch.setattr("app.services.chapter_subtitles.file_storage.base_dir", tmp_path)
    session_factory = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)
    manager = WorkerManager(session_factory)
    monkeypatch.setattr(manager.worker("subtitle_render"), "signal", lambda _job_id: None)
    monkeypatch.setattr("app.services.subtitle_render_service.worker_manager", manager)
    monkeypatch.setattr("app.services.subtitle_render_service.SessionLocal", session_factory)
    task = Task(id="subtitle-test-task", type="novel_video", status="completed",
                novel_id="subtitle-test-novel", name="临时字幕保存测试",
                result_url="/api/files/test-source.mp4", metadata_json=json.dumps({
                    "subtitle": {"source_url": "/api/files/test-source.mp4",
                                 "srt_url": "/api/files/test.srt", "cues_url": "/api/files/test.json"},
                    "video_url": "/api/files/test-source.mp4",
                }))
    db_session.add(task)
    db_session.commit()
    parent_id = task.id
    route = "/api/novels/subtitle-test-novel/video-merges/subtitle-test-task/subtitles"
    updated = [{"start": 0.2, "end": 1.8, "text": "校正后的字幕"}]
    response = client.put(route, json={"cues": updated})
    assert response.status_code == 200, response.text
    render_id = response.json()["data"]["id"]
    assert response.json()["data"]["status"] == "pending"
    job = db_session.query(BackgroundJob).filter_by(task_id=render_id).one()
    assert job.queue_name == "subtitle_render" and job.status == "queued"
    assert json.loads(cues_path.read_text(encoding="utf-8")) == original
    assert db_session.get(Task, parent_id).result_url == "/api/files/test-source.mp4"
    duplicate = client.put(route, json={"cues": updated})
    assert duplicate.status_code == 409

    manager._local_factories.clear()  # Simulate restart: replay the stored handler descriptor.
    asyncio.run(manager.run_persisted(job.id))
    db_session.expire_all()
    parent = db_session.get(Task, parent_id)
    subtitle = json.loads(parent.metadata_json)["subtitle"]
    assert json.loads(Path(resolve(subtitle["cues_url"])).read_text(encoding="utf-8")) == updated
    assert "校正后的字幕" in Path(resolve(subtitle["srt_url"])).read_text(encoding="utf-8")
    assert "原字幕" in srt_path.read_text(encoding="utf-8")
    burned_url = parent.result_url
    burned = tmp_path / burned_url.removeprefix("/api/files/")
    assert burned.is_file() and burned != source
    assert abs(_duration(burned) - 2) < 0.1
    assert db_session.get(Task, render_id).status == "completed"
    assert db_session.get(BackgroundJob, job.id).status == "completed"
    assert parent.result_url == burned_url

    failed_update = [{"start": 0.2, "end": 1.8, "text": "不能发布的字幕"}]
    failed_response = client.put(route, json={"cues": failed_update})
    assert failed_response.status_code == 200
    failed_render_id = failed_response.json()["data"]["id"]
    failed_job = db_session.query(BackgroundJob).filter_by(task_id=failed_render_id).one()
    monkeypatch.setattr("app.services.subtitle_render_service.burn_subtitles",
                        lambda *_args: (_ for _ in ()).throw(RuntimeError("模拟烧录失败")))
    with pytest.raises(RuntimeError, match="模拟烧录失败"):
        asyncio.run(manager.run_persisted(failed_job.id))
    db_session.expire_all()
    assert db_session.get(Task, parent_id).result_url == burned_url
    assert db_session.get(Task, failed_render_id).status == "failed"
    assert db_session.get(BackgroundJob, failed_job.id).status == "failed"
    assert json.loads(Path(resolve(subtitle["cues_url"])).read_text(encoding="utf-8")) == updated


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg not installed")
def test_bilingual_save_retranslates_changed_chinese_in_render_queue(client, db_session, db_engine, tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    _run_media(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=640x360:d=2",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                "-c:v", "libx264", "-c:a", "aac", "-shortest", str(source)])
    old = [{"start": 0.2, "end": 1.8, "text": "你好", "en_text": "Hello"}]
    write_srt(old, tmp_path / "zh.srt")
    write_cues(old, tmp_path / "cues.json")
    def resolve(url):
        path = tmp_path / url.removeprefix("/api/files/")
        return str(path) if url.startswith("/api/files/") and path.is_file() else None
    monkeypatch.setattr("app.services.subtitle_render_service.url_to_local_path", resolve)
    monkeypatch.setattr("app.utils.path_utils.url_to_local_path", resolve)
    monkeypatch.setattr("app.services.chapter_subtitles.file_storage.base_dir", tmp_path)
    monkeypatch.setattr("app.services.chapter_subtitles.PromptTemplateService",
                        lambda db: SimpleNamespace(get_default_system_template=lambda _: SimpleNamespace(
                            name="字幕英文翻译", template="仅翻译文字")))
    class FakeLLM:
        async def chat_completion(self, **kwargs):
            assert json.loads(kwargs["user_content"]) == {"segments": [{"index": 1, "text": "你好啊"}]}
            return {"success": True, "content": '{"segments":[{"index":1,"text":"Hello there"}]}' }
    monkeypatch.setattr("app.services.chapter_subtitles.LLMService", FakeLLM)
    session_factory = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)
    manager = WorkerManager(session_factory)
    monkeypatch.setattr(manager.worker("subtitle_render"), "signal", lambda _job_id: None)
    monkeypatch.setattr("app.services.subtitle_render_service.worker_manager", manager)
    monkeypatch.setattr("app.services.subtitle_render_service.SessionLocal", session_factory)
    parent = Task(id="bilingual-test-task", type="novel_video", status="completed",
                  novel_id="bilingual-test-novel", name="双语更新测试",
                  result_url="/api/files/source.mp4", metadata_json=json.dumps({
                      "subtitle_mode": "bilingual", "subtitle": {
                          "mode": "bilingual", "source_url": "/api/files/source.mp4",
                          "srt_url": "/api/files/zh.srt", "cues_url": "/api/files/cues.json",
                      }, "video_url": "/api/files/source.mp4",
                  }))
    db_session.add(parent)
    db_session.commit()
    route = "/api/novels/bilingual-test-novel/video-merges/bilingual-test-task/subtitles"
    # A stale English cue from a client must be invalidated when Chinese changes.
    response = client.put(route, json={"cues": [{"start": 0.2, "end": 1.8,
                                                  "text": "你好啊", "en_text": "Hello"}]})
    assert response.status_code == 200, response.text
    render_id = response.json()["data"]["id"]
    job = db_session.query(BackgroundJob).filter_by(task_id=render_id).one()
    assert job.queue_name == "subtitle_render"
    manager._local_factories.clear()
    asyncio.run(manager.run_persisted(job.id))
    db_session.expire_all()
    updated = json.loads(db_session.get(Task, parent.id).metadata_json)["subtitle"]
    cues = json.loads(Path(resolve(updated["cues_url"])).read_text(encoding="utf-8"))
    assert cues == [{"start": 0.2, "end": 1.8, "text": "你好啊", "en_text": "Hello there"}]
    assert "你好啊" in Path(resolve(updated["srt_url"])).read_text(encoding="utf-8")
    assert "Hello there" in Path(resolve(updated["en_srt_url"])).read_text(encoding="utf-8")
    assert db_session.get(Task, render_id).status == "completed"


def test_asr_timeout_does_not_interrupt_other_running_prompts(monkeypatch):
    client = ComfyUIClient(runtime_mode="standalone", base_url="http://127.0.0.1:8188")
    async def queue():
        return {"queue_running": [[0, "ours", {}], [1, "other", {}]], "queue_pending": []}
    async def interrupt(*_args, **_kwargs):
        raise AssertionError("must not interrupt other prompts")
    monkeypatch.setattr(client, "get_queue_info", queue)
    monkeypatch.setattr(client, "interrupt_execution", interrupt)
    assert "未发送全局中断" in asyncio.run(client._cleanup_timed_out_prompt("ours"))


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg not installed")
def test_srt_and_burned_mp4_use_identical_cues(tmp_path):
    source = tmp_path / "source.mp4"
    _run_media([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=640x360:d=2",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-c:v", "libx264", "-c:a", "aac", "-shortest", str(source),
    ])
    cues = validate_cues([{"start": 0.2, "end": 1.8, "text": "你好，世界"}], 2)
    srt = tmp_path / "subtitles.srt"
    write_srt(cues, srt)
    burned = burn_subtitles(source, cues, tmp_path)

    assert "00:00:00,200 --> 00:00:01,800" in srt.read_text(encoding="utf-8")
    assert "你好，世界" in srt.read_text(encoding="utf-8")
    assert burned.is_file() and burned.stat().st_size > 0
    assert abs(_duration(burned) - _duration(source)) < 0.1
    assert burn_subtitles(source, cues, tmp_path) == burned


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg not installed")
def test_bilingual_srt_and_burned_mp4_share_timeline(tmp_path):
    source = tmp_path / "source.mp4"
    _run_media(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=640x360:d=2",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                "-c:v", "libx264", "-c:a", "aac", "-shortest", str(source)])
    cues = validate_cues([{"start": 0.2, "end": 1.8, "text": "你好，世界", "en_text": "Hello, world"}], 2)
    zh_path, en_path = tmp_path / "zh.srt", tmp_path / "en.srt"
    write_srt(cues, zh_path)
    write_srt(english_cues(cues), en_path)
    burned = burn_subtitles(source, cues, tmp_path)
    assert "00:00:00,200 --> 00:00:01,800" in zh_path.read_text()
    assert "00:00:00,200 --> 00:00:01,800" in en_path.read_text()
    assert "你好，世界" in zh_path.read_text()
    assert "Hello, world" in en_path.read_text()
    assert burned.is_file() and abs(_duration(burned) - _duration(source)) < 0.1
