import asyncio
import json
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import AsyncMock

import pytest

from app.services.file_storage import FileStorageService


def test_progress_parser_drains_both_pipes(tmp_path, monkeypatch):
    async def check():
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-c",
            "import sys; sys.stderr.write('x'*200000); sys.stderr.flush(); "
            "sys.stdout.write('out_time_us=N/A\\nout_time_ms=9000000\\nout_time_us=-1\\n'"
            "'out_time_us=1250000\\nprogress=end\\n'); sys.stdout.flush()",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        create = AsyncMock(return_value=process)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
        callback = AsyncMock()
        result = await asyncio.wait_for(FileStorageService(str(tmp_path))._run_merge_process(
            ["ffmpeg", "-y", "output.mp4"], callback), 10)
        assert [call.args[0] for call in callback.await_args_list] == [0, 1.25]
        assert result.returncode == 0
        assert len(result.stderr) == 65536
        assert create.call_args.args[:4] == ("ffmpeg", "-progress", "pipe:1", "-nostats")

    asyncio.run(check())


@pytest.mark.parametrize("failure", [None, "source", "normalize", "encode", "validate", "publish", "cancel"])
def test_measured_progress_and_publication(tmp_path, monkeypatch, failure):
    storage = FileStorageService(str(tmp_path))
    source = tmp_path / "source.mov"
    source.write_bytes(b"source")
    output = tmp_path / "output.mp4"
    output.write_bytes(b"old")
    events = []

    async def callback(percent, step):
        assert output.read_bytes() == (b"new" if percent == 100 else b"old")
        events.append((percent, step))

    async def run(cmd, on_time=None):
        if cmd[0] == "ffprobe":
            merged = Path(cmd[-1]).name == "merged.mp4"
            streams = [{"codec_type": "video", "width": 64, "height": 64,
                        "start_time": "0", "duration_ts": "60" if merged else "48",
                        "time_base": "1/24", "nb_read_frames": "60" if merged else "48"},
                       {"codec_type": "audio", "start_time": "0.5", "duration_ts": "120000", "time_base": "1/48000"}]
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"streams": streams}), "")
        if on_time and "0:a:0" in cmd and cmd[-2:] == ["null", "-"]:
            await on_time(2.5)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if on_time:
            if failure == "cancel":
                raise asyncio.CancelledError()
            for seconds in [0, 1.5, 0.5, 99]:
                await on_time(seconds)
            Path(cmd[-1]).write_bytes(b"new")
            stage = "normalize" if "-vf" in cmd else "encode"
        else:
            input_path = Path(cmd[cmd.index("-i") + 1]) if "-i" in cmd else None
            stage = "source" if input_path and input_path.name == "frozen_000.mov" else "validate"
        return subprocess.CompletedProcess(cmd, int(stage == failure), "", "bad" if stage == failure else "")

    monkeypatch.setattr(storage, "_run_merge_process", run)
    if failure == "publish":
        monkeypatch.setattr("os.replace", lambda *args: (_ for _ in ()).throw(OSError("publish failed")))
    if failure == "cancel":
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(storage.merge_videos([str(source)], str(output), progress_callback=callback))
    else:
        result = asyncio.run(storage.merge_videos([str(source)], str(output), progress_callback=callback))
        assert result["success"] == (failure is None)
    values = [percent for percent, _ in events]
    assert values == sorted(values)
    assert (100 in values) == (failure is None)
    if failure is None:
        # Source common timeline is 3s; normalized final timeline is 2.5s.
        assert 40 in values  # 15 + 50 * 1.5 / 3
        assert 83 in values  # 65 + 30 * 1.5 / 2.5
        assert values[-3:] == [95, 99, 100]
    assert not list(tmp_path.glob(".novelflow_merge_*"))
    assert output.read_bytes() == (b"new" if failure is None else b"old")


@pytest.mark.parametrize("callback_failure", [False, True])
def test_process_reaped_on_cancellation_or_callback_error(tmp_path, callback_failure):
    async def check():
        storage = FileStorageService(str(tmp_path))
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-c", "import time; print('out_time_us=1', flush=True); time.sleep(60)",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        from unittest.mock import patch

        async def callback(seconds):
            raise RuntimeError("callback failed")

        with patch.object(asyncio, "create_subprocess_exec", AsyncMock(return_value=process)):
            task = asyncio.create_task(storage._run_merge_process(["ffmpeg"], callback if callback_failure else None))
            if callback_failure:
                with pytest.raises(RuntimeError, match="callback failed"):
                    await asyncio.wait_for(task, 10)
            else:
                await asyncio.sleep(0.05)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
        assert process.returncode is not None

    asyncio.run(check())


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg required")
def test_real_small_merge_progress(tmp_path):
    source = tmp_path / "source.mov"
    subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=red:s=64x64:r=24:d=0.5",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=0.7", "-c:v", "libx264",
        "-c:a", "pcm_s16le", str(source),
    ], check=True, capture_output=True)
    events = []
    output = tmp_path / "output.mp4"

    async def callback(percent, step):
        events.append((percent, step))
        assert output.exists() == (percent == 100)

    result = asyncio.run(FileStorageService(str(tmp_path)).merge_videos(
        [str(source), str(source)], str(output), [str(source)], callback))
    assert result["success"], result
    values = [value for value, _ in events]
    assert values == sorted(values)
    assert values[-3:] == [95, 99, 100]
    assert any(65 < value < 95 for value in values)
    assert any("3/3" in step for _, step in events)


@pytest.mark.parametrize("outcome", ["success", "cache", "publish_failure"])
def test_chapter_task_throttling_cache_and_final_publish(db_session, tmp_path, monkeypatch, outcome):
    from app.api import shots as api
    from app.models.novel import Novel, Chapter
    from app.models.shot import Shot
    from app.models.task import Task

    novel = Novel(title="Progress")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="Progress", content="test")
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(chapter_id=chapter.id, index=1, description="test", video_url="/api/files/source.mp4")
    task = Task(type="chapter_video", status="pending", name="merge",
                novel_id=novel.id, chapter_id=chapter.id)
    db_session.add_all([shot, task])
    db_session.commit()
    task_id = task.id
    storage = FileStorageService(str(tmp_path))
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    signature = storage.get_video_merge_signature("shots_only", [{"kind": "shot", "key": "1", "path": str(source)}])
    directory = storage._get_story_dir(novel.id) / f"chapter_{chapter.id[:8]}" / "merged-videos"
    directory.mkdir(parents=True)
    published = directory / f"shots_only-{signature}.mp4"
    if outcome == "cache":
        published.write_bytes(b"cached")
        from app.services.rendered_subtitles import publish
        publish(published, [], {"kind": "merge"}, unavailable="Legacy source has no subtitle binding")
    monkeypatch.setattr(api, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(api, "file_storage", storage)
    monkeypatch.setattr(api, "url_to_local_path", lambda url: str(source))
    monkeypatch.setattr(api, "_probe_video_duration", lambda path: 1.0)
    clock = [10.0]
    monkeypatch.setattr(api, "monotonic", lambda: clock[0])
    writes = []
    commit = db_session.commit

    def record_commit():
        writes.append((task.progress, task.current_step))
        if task.progress == 100:
            assert published.is_file()
        commit()

    monkeypatch.setattr(db_session, "commit", record_commit)

    async def merge(paths, output, transitions, progress_callback):
        assert outcome != "cache"
        await progress_callback(0, "source 1/1")
        await progress_callback(15, "normalize 1/1")
        before = len(writes)
        for percent in range(16, 60):
            await progress_callback(percent, "normalize 1/1")
        assert len(writes) == before
        clock[0] += 1
        await progress_callback(60, "normalize 1/1")
        assert writes[-1][0] == 67
        await progress_callback(65, "encode")
        await progress_callback(95, "validate")
        await progress_callback(99, "publish")
        Path(output).write_bytes(b"new")
        await progress_callback(100, "published")
        assert task.progress == 99
        assert not published.exists()
        return {"success": True}

    mocked_merge = AsyncMock(side_effect=merge)
    monkeypatch.setattr(storage, "merge_videos", mocked_merge)
    if outcome == "publish_failure":
        def fail_publish(*args):
            raise OSError("publish failed")
        monkeypatch.setattr(api.os, "replace", fail_publish)
    asyncio.run(api.run_chapter_video_merge_task(task_id))
    saved = db_session.get(Task, task_id)
    values = [value for value, _ in writes]
    assert values == sorted(values)
    assert saved.status == ("failed" if outcome == "publish_failure" else "completed")
    assert (100 in values) == (outcome != "publish_failure")
    assert not list(directory.glob(".*.tmp.mp4"))
    if outcome == "cache":
        mocked_merge.assert_not_awaited()
        assert values == [5, 20, 100]
        assert json.loads(saved.metadata_json)["cache_hit"] is True
    else:
        mocked_merge.assert_awaited_once()
        assert len(writes) <= 11
