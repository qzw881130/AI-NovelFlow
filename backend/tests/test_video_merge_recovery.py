import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from app.services.file_storage import FileStorageService


@pytest.mark.parametrize("failure", [None, "decode", "encode", "normalize", "source", "missing", "no_output", "probe"])
@pytest.mark.parametrize("has_audio", [True, False])
@pytest.mark.parametrize("existing_output", [True, False])
def test_merge_validation_and_atomic_publication(tmp_path, monkeypatch, failure, has_audio, existing_output):
    sources = [tmp_path / "first.mp4", tmp_path / "second.mp4"]
    for source in sources:
        source.write_bytes(b"source")
    if failure == "missing":
        sources[1].unlink()
    output = tmp_path / "published.mp4"
    if existing_output:
        output.write_bytes(b"previous valid output")
    calls = []
    candidate_validations = 0

    def run(cmd, **kwargs):
        nonlocal candidate_validations
        calls.append(cmd)
        assert output.exists() == existing_output
        if existing_output:
            assert output.read_bytes() == b"previous valid output"
        if cmd[0] == "ffprobe":
            if failure == "probe":
                return subprocess.CompletedProcess(cmd, 1, "", "probe failed")
            merged = Path(cmd[-1]).name == "merged.mp4"
            streams = [{"codec_type": "video", "width": 64, "height": 64,
                        "nb_read_frames": "48" if merged else "24"}]
            if has_audio or merged:
                streams.append({"codec_type": "audio", "duration_ts": "96000" if merged else "24000",
                                "time_base": "1/48000"})
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"streams": streams}), "")
        if cmd[-2:] == ["null", "-"]:
            path = Path(cmd[cmd.index("-i") + 1])
            error = ""
            if path.name == "frozen_000.mp4" and failure == "source":
                error = "Invalid NAL unit; non-existing PPS; decode_slice_header error"
            if path.name == "merged.mp4" and "0:v:0" in cmd:
                candidate_validations += 1
                if failure == "decode":
                    error = "Invalid NAL unit"
            # Some ffmpeg builds report decode errors with exit status zero.
            return subprocess.CompletedProcess(cmd, 0, "", error)
        if not (failure == "no_output" and "-filter_complex" in cmd):
            Path(cmd[-1]).write_bytes(b"candidate")
        code = int(("-filter_complex" in cmd and failure == "encode") or ("-vf" in cmd and failure == "normalize"))
        return subprocess.CompletedProcess(cmd, code, "", "encoder failed" if code else "")

    async def run_process(self, cmd, on_time=None):
        if on_time is not None and "0:a:0" in cmd and cmd[-2:] == ["null", "-"]:
            await on_time(2.0)
        return run(cmd)

    monkeypatch.setattr(FileStorageService, "_run_merge_process", run_process)
    result = asyncio.run(FileStorageService(str(tmp_path)).merge_videos([str(p) for p in sources], str(output)))
    assert result["success"] == (failure is None)
    assert output.exists() == (result["success"] or existing_output)
    if output.exists():
        assert output.read_bytes() == (b"candidate" if result["success"] else b"previous valid output")
    assert not list(tmp_path.glob(".novelflow_merge_*"))
    filters = [cmd for cmd in calls if "-filter_complex" in cmd]
    assert len(filters) == int(failure not in {"source", "missing", "normalize", "probe"})
    if filters:
        assert "concat=n=2:v=1:a=1" in filters[0][filters[0].index("-filter_complex") + 1]
        assert "-xerror" in filters[0]
        assert candidate_validations == (0 if failure in {"encode", "no_output"} else 1)
        assert "atrim=end_sample=48000" in filters[0][filters[0].index("-filter_complex") + 1]
    normalizations = [cmd for cmd in calls if "-vf" in cmd]
    if failure in {"source", "missing", "probe"}:
        assert not normalizations
        if failure == "missing":
            assert str(sources[1]) in result["message"]
        else:
            assert "frozen_000.mp4" in result["message"]
    else:
        assert len(normalizations) == (1 if failure == "normalize" else 2)
        for cmd in normalizations:
            assert "pcm_s16le" in cmd
            assert ("-af" in cmd) == has_audio
            assert "-shortest" not in cmd
    assert not any("copy" in cmd for cmd in calls)
