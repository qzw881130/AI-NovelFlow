import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from app.services.file_storage import FileStorageService


@pytest.mark.parametrize("failure", [None, "copy_decode", "fallback_decode", "fallback_encode", "source", "missing"])
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
            streams = [{"codec_type": "video", "width": 64, "height": 64}]
            if has_audio:
                streams.append({"codec_type": "audio"})
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"streams": streams}), "")
        if cmd[-2:] == ["null", "-"]:
            path = Path(cmd[cmd.index("-i") + 1])
            error = ""
            if path in sources and failure == "source":
                error = "Invalid NAL unit; non-existing PPS; decode_slice_header error"
            if path.name == "merged.mp4":
                candidate_validations += 1
                if failure in {"copy_decode", "fallback_decode", "fallback_encode"} and candidate_validations == 1:
                    error = "Invalid NAL unit"
                if failure == "fallback_decode" and candidate_validations == 2:
                    error = "decode_slice_header error"
            # Some ffmpeg builds report decode errors with exit status zero.
            return subprocess.CompletedProcess(cmd, 0, "", error)
        Path(cmd[-1]).write_bytes(b"candidate")
        code = 1 if "-filter_complex" in cmd and failure == "fallback_encode" else 0
        return subprocess.CompletedProcess(cmd, code, "", "encoder failed" if code else "")

    monkeypatch.setattr(subprocess, "run", run)
    result = asyncio.run(FileStorageService(str(tmp_path)).merge_videos([str(p) for p in sources], str(output)))
    assert result["success"] == (failure in {None, "copy_decode"})
    assert output.exists() == (result["success"] or existing_output)
    if output.exists():
        assert output.read_bytes() == (b"candidate" if result["success"] else b"previous valid output")
    assert not list(tmp_path.glob(".novelflow_merge_*"))
    filters = [cmd for cmd in calls if "-filter_complex" in cmd]
    assert len(filters) == int(failure in {"copy_decode", "fallback_decode", "fallback_encode"})
    if filters:
        assert "concat=n=2:v=1:a=1" in filters[0][filters[0].index("-filter_complex") + 1]
        assert "-xerror" in filters[0]
        assert candidate_validations == (1 if failure == "fallback_encode" else 2)
    normalizations = [cmd for cmd in calls if "-vf" in cmd]
    if failure in {"source", "missing"}:
        assert not normalizations
        assert str(sources[0 if failure == "source" else 1]) in result["message"]
    else:
        assert len(normalizations) == 2
        for cmd in normalizations:
            assert ("anullsrc=channel_layout=stereo:sample_rate=48000" in cmd) == (not has_audio)
            assert ("-shortest" in cmd) == (not has_audio)
