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
        if on_time and cmd[-2:] == ["null", "-"]:
            await on_time(2.5)
            stage = "validate"
            return subprocess.CompletedProcess(cmd, int(stage == failure), "", "bad" if stage == failure else "")
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
        assert values[-3:] == [97, 99, 100]
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
    assert values[-3:] == [97, 99, 100]
    assert any(65 < value < 95 for value in values)
    assert any("3/3" in step for _, step in events)


def test_chapter_task_delegates_to_governed_merge(monkeypatch):
    from app.api import shots as api
    from app.services import chapter_video_merge_service as service
    governed = AsyncMock(return_value=None)
    monkeypatch.setattr(service, "run_merge", governed)
    asyncio.run(api.run_chapter_video_merge_task("task-id"))
    governed.assert_awaited_once_with("task-id")
