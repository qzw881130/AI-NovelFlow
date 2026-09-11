"""Standalone offline tests. Run with --noconftest; never import app or storage."""

import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import wave

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
import pytest


MODULE = Path(__file__).resolve().parents[1] / "app/services/actual_state_frames.py"
spec = importlib.util.spec_from_file_location("standalone_actual_state_frames", MODULE)
frames = importlib.util.module_from_spec(spec)
spec.loader.exec_module(frames)

RESULT_KEYS = {
    "can_use", "reason", "error", "selected", "observation_candidates", "candidates",
    "last_frame_index", "last_frame_pts", "video_end_seconds", "window_start_pts",
    "source_path", "source_sha256", "expected_sha256", "source_size_bytes",
    "source_sha256_after", "source_size_bytes_after", "technical_tail_compatible",
    "recipe", "tail_difference",
}
CANDIDATE_KEYS = {
    "path", "sha256", "frame_index", "pts", "offset_from_last_frame_seconds",
    "offset_from_video_end_seconds", "usable", "reference_usable", "sharpness", "reason",
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(*args):
    return subprocess.run(args, check=True, capture_output=True, timeout=20).stdout


@pytest.fixture
def media_tools():
    if not all(shutil.which(tool) for tool in ("ffmpeg", "ffprobe")):
        pytest.skip("local ffmpeg/ffprobe required")


def pattern():
    image = Image.new("RGB", (96, 64), (85, 95, 105))
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 44, 55), fill=(210, 185, 150))
    draw.rectangle((52, 10, 88, 54), fill=(20, 35, 50))
    for x in range(15, 39, 3):
        draw.line((x, 18, x, 45), fill=(100, 100, 100))
    return image


def video(tmp_path, images, *, fps=12, audio=False, timing=None):
    for index, image in enumerate(images):
        image.save(tmp_path / f"input_{index:03d}.png")
    args = ["ffmpeg", "-v", "error", "-nostdin", "-n", "-framerate", str(fps),
            "-i", str(tmp_path / "input_%03d.png")]
    if audio:
        wav = tmp_path / "tiny.wav"
        with wave.open(str(wav), "wb") as target:
            target.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            target.writeframes(b"\x20\x00\xe0\xff" * int(4000 * len(images) / fps))
        args += ["-i", str(wav), "-map", "0:v:0", "-map", "1:a:0", "-c:a", "pcm_s16le"]
    if timing:
        args += ["-vf", timing, "-fps_mode", "vfr"]
    path = tmp_path / "source.mov"
    command(*args, "-c:v", "png", "-pix_fmt", "rgb24", str(path))
    return path


def extract(source, output):
    return asyncio.run(frames.extract_tail_window(source, output, expected_sha256=digest(source)))


def select(images):
    result = {
        "candidates": [{"path": f"frame_{i}.png", "sha256": None, "frame_index": i,
                        "pts": i / 10, "offset_from_last_frame_seconds": (len(images) - 1 - i) / 10,
                        "offset_from_video_end_seconds": (len(images) - i) / 10,
                        "usable": False, "reference_usable": False, "sharpness": None, "reason": "not_decoded"}
                       for i in range(len(images))],
        "tail_difference": {"scores": [], "maximum": None, "limit": 0.12, "semantic_proof": False},
        "technical_tail_compatible": False,
    }
    frames._select(result, images)
    return result


def test_standalone_import_blocks_app_db_and_network(tmp_path):
    script = """
import importlib.abc, importlib.util, socket, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'app', 'sqlalchemy', 'sqlite3'}:
            raise AssertionError('forbidden import: ' + fullname)
sys.meta_path.insert(0, Block())
def forbidden(*args, **kwargs):
    raise AssertionError('network forbidden')
socket.create_connection = forbidden
socket.socket.connect = forbidden
spec = importlib.util.spec_from_file_location('standalone', sys.argv[1])
spec.loader.exec_module(importlib.util.module_from_spec(spec))
"""
    subprocess.run([sys.executable, "-B", "-c", script, str(MODULE)], cwd=tmp_path,
                   check=True, capture_output=True, timeout=10)


def test_static_true_last_api_and_source_audio_unchanged(tmp_path, media_tools, monkeypatch):
    source = video(tmp_path, [pattern()] * 12, audio=True)
    before, size, mtime = digest(source), source.stat().st_size, source.stat().st_mtime_ns
    audio_before = command("ffmpeg", "-v", "error", "-i", str(source), "-map", "0:a:0",
                           "-f", "s16le", "pipe:1")
    existing = set(tmp_path.iterdir())
    output = tmp_path / "private-tail"
    with monkeypatch.context() as environment:
        environment.setenv("FFREPORT", f"file={tmp_path / 'forbidden-report.log'}")
        result = extract(source, output)
    assert set(result) == RESULT_KEYS
    assert result["can_use"] is True, result
    assert result["reason"] == "ok" and result["error"] is None
    assert result["last_frame_index"] == 11
    assert result["last_frame_pts"] == pytest.approx(11 / 12, abs=1e-6)
    assert result["video_end_seconds"] == pytest.approx(1, abs=1e-6)
    assert result["window_start_pts"] == pytest.approx(0.5, abs=1e-6)
    assert [c["frame_index"] for c in result["candidates"]] == [6, 7, 8, 10, 11]
    assert result["selected"]["frame_index"] == 11
    assert result["technical_tail_compatible"] is True
    assert result["tail_difference"]["maximum"] == 0
    assert result["recipe"]["semantic_proof"] is False
    assert result["recipe"]["parent_semantic_check_required"] is True
    assert result["source_path"] == str(source)
    assert result["source_sha256"] == result["source_sha256_after"] == result["expected_sha256"] == before
    assert result["source_size_bytes"] == result["source_size_bytes_after"] == size
    assert digest(source) == before and source.stat().st_mtime_ns == mtime
    assert audio_before == command("ffmpeg", "-v", "error", "-i", str(source), "-map", "0:a:0",
                                   "-f", "s16le", "pipe:1")
    assert set(tmp_path.iterdir()) == existing | {output}
    assert output.stat().st_mode & 0o777 == 0o700
    assert len(list(output.iterdir())) == len(result["candidates"])
    for candidate in result["candidates"]:
        assert set(candidate) == CANDIDATE_KEYS
        path = Path(candidate["path"])
        assert path.parent == output and digest(path) == candidate["sha256"]
        with Image.open(path) as image:
            assert image.mode == "RGB" and image.format == "PNG"
            assert image.tobytes() == pattern().tobytes()
        assert candidate["usable"] and candidate["reference_usable"]
        assert candidate["offset_from_last_frame_seconds"] == pytest.approx(11 / 12 - candidate["pts"], abs=1e-6)
        assert candidate["offset_from_video_end_seconds"] == pytest.approx(1 - candidate["pts"], abs=1e-6)
    observed = result["observation_candidates"]
    assert [c["frame_index"] for c in observed] == [11, 10]
    assert all(c["usable"] for c in observed)
    json.dumps(result, allow_nan=False)


def test_variable_actual_pts_not_planned_fps(tmp_path, media_tools):
    # Dropping frames preserves valid final duration, unlike setpts on PNG/MOV.
    source = video(tmp_path, [pattern()] * 13, fps=10,
                   timing="select=lt(n\\,4)+not(mod(n\\,2))")
    probe = json.loads(command("ffprobe", "-v", "error", "-select_streams", "v:0",
                               "-show_frames", "-of", "json", str(source)))["frames"]
    pts = [float(f["best_effort_timestamp_time"]) for f in probe]
    assert len(set(round(b - a, 3) for a, b in zip(pts, pts[1:]))) > 1
    result = extract(source, tmp_path / "vfr-tail")
    assert result["can_use"], result
    assert result["last_frame_index"] == len(probe) - 1 == 8
    assert result["last_frame_pts"] == pts[-1] == pytest.approx(1.2)
    assert result["video_end_seconds"] == pytest.approx(pts[-1] + float(probe[-1]["duration_time"]))
    assert result["candidates"][-1]["frame_index"] == 8
    assert 1 <= len(result["candidates"]) <= 5
    for candidate in result["candidates"]:
        assert candidate["pts"] == pts[candidate["frame_index"]]
        assert candidate["pts"] >= result["window_start_pts"]
        assert candidate["offset_from_last_frame_seconds"] <= 0.5
        assert candidate["offset_from_video_end_seconds"] == pytest.approx(
            result["video_end_seconds"] - candidate["pts"])


@pytest.mark.parametrize("fps", [1, 30])
def test_single_frame_including_held_true_last(tmp_path, media_tools, fps):
    source = video(tmp_path, [pattern()], fps=fps)
    result = extract(source, tmp_path / "single-tail")
    assert result["can_use"], result
    assert result["last_frame_index"] == result["selected"]["frame_index"] == 0
    assert len(result["candidates"]) == len(result["observation_candidates"]) == 1
    assert result["video_end_seconds"] == pytest.approx(1 / fps, abs=1e-6)
    assert result["selected"]["offset_from_video_end_seconds"] == result["video_end_seconds"]


def test_never_searches_back_outside_fixed_window(tmp_path, media_tools):
    source = video(tmp_path, [pattern()] * 12 + [Image.new("RGB", (96, 64))] * 12)
    result = extract(source, tmp_path / "fixed-tail")
    assert result["window_start_pts"] == pytest.approx(1.5)
    assert all(c["pts"] >= result["window_start_pts"] for c in result["candidates"])
    assert len({c["frame_index"] for c in result["candidates"]}) == 5
    assert result["candidates"][-1]["frame_index"] == 23
    assert result["selected"] is None and not result["can_use"]


def test_moving_test_pattern_with_b_frames_has_true_display_last(tmp_path, media_tools):
    source = tmp_path / "moving.mp4"
    command("ffmpeg", "-v", "error", "-nostdin", "-n", "-f", "lavfi", "-i",
            "testsrc2=size=96x64:rate=24:duration=1", "-c:v", "libx264", "-bf", "3",
            "-x264-params", "b-adapt=0", str(source))
    probe = json.loads(command("ffprobe", "-v", "error", "-select_streams", "v:0",
                               "-show_frames", "-show_streams", "-of", "json", str(source)))
    assert probe["streams"][0]["has_b_frames"] > 0
    result = extract(source, tmp_path / "moving-tail")
    assert result["can_use"], result
    assert result["last_frame_index"] == len(probe["frames"]) - 1 == 23
    assert result["last_frame_pts"] == float(probe["frames"][-1]["best_effort_timestamp_time"])
    assert result["video_end_seconds"] == pytest.approx(1, abs=1e-6)
    expected = command("ffmpeg", "-v", "error", "-i", str(source), "-vf", "select=eq(n\\,23)",
                       "-fps_mode", "passthrough", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1")
    with Image.open(result["candidates"][-1]["path"]) as image:
        assert image.tobytes() == expected


def test_relative_blur_selects_latest_near_best_not_prettiest(tmp_path, media_tools):
    sharp = pattern()
    blurred = sharp.filter(ImageFilter.GaussianBlur(1.5))
    source = video(tmp_path, [sharp] * 10 + [blurred] * 2)
    result = extract(source, tmp_path / "blur-tail")
    assert result["can_use"], result
    assert result["selected"]["frame_index"] == 8
    assert result["candidates"][-1]["usable"]
    assert not result["candidates"][-1]["reference_usable"]
    assert result["candidates"][-1]["reason"] == "relative_blur"
    assert 0 < result["tail_difference"]["maximum"] <= 0.12
    assert [s["frame_index"] for s in result["tail_difference"]["scores"]] == [8, 10, 11]
    assert [c["frame_index"] for c in result["observation_candidates"]] == [8, 11, 10]


def test_black_last_cannot_cherry_pick(tmp_path, media_tools):
    source = video(tmp_path, [pattern()] * 11 + [Image.new("RGB", (96, 64))])
    result = extract(source, tmp_path / "black-tail")
    assert result["can_use"] is False
    assert result["selected"]["frame_index"] == 10
    assert result["last_frame_index"] == result["candidates"][-1]["frame_index"] == 11
    assert not result["candidates"][-1]["usable"]
    assert not result["technical_tail_compatible"]
    assert any(not c["usable"] for c in result["observation_candidates"])
    assert "requires_human" in result["reason"]


@pytest.mark.parametrize("returns_to_original", [False, True])
def test_changed_layout_after_reference_requires_human(returns_to_original):
    sharp = pattern()
    changed = sharp.transpose(Image.Transpose.FLIP_LEFT_RIGHT).filter(ImageFilter.GaussianBlur(1.5))
    ending = sharp.filter(ImageFilter.GaussianBlur(1.5)) if returns_to_original else changed
    result = select([sharp, sharp, changed, ending, ending])
    assert result["selected"]["frame_index"] == 1
    assert result["tail_difference"]["maximum"] > 0.12
    assert not result["technical_tail_compatible"] and not result["can_use"]
    assert result["reason"] == "tail_appearance_change_requires_human"


def test_latest_near_best_wins_over_older_absolute_sharpest():
    sharp = pattern()
    near = sharp.filter(ImageFilter.GaussianBlur(0.3))
    result = select([sharp, near, sharp.filter(ImageFilter.GaussianBlur(1.5))])
    best, latest = result["candidates"][:2]
    assert best["sharpness"] > latest["sharpness"] >= best["sharpness"] * 0.65
    assert result["selected"]["frame_index"] == 1 and result["can_use"]


def test_static_equal_luminance_color_pattern_is_not_blank():
    image = Image.new("RGB", (96, 64), (255, 0, 0))
    ImageDraw.Draw(image).rectangle((48, 0, 95, 63), fill=(0, 130, 0))
    assert image.convert("L").getextrema() == (76, 76)
    result = select([image] * 5)
    assert result["can_use"] and result["selected"]["frame_index"] == 4
    assert all(c["usable"] and c["reference_usable"] for c in result["candidates"])


def test_normal_motion_and_local_blink_like_change_are_not_semantic_errors():
    original = pattern()
    moved = original.copy()
    ImageDraw.Draw(moved).rectangle((20, 20, 26, 22), fill=(150, 150, 150))
    result = select([original, moved, original, moved, moved])
    assert result["can_use"]
    assert result["selected"]["frame_index"] == 4
    assert all(c["usable"] for c in result["candidates"])
    assert result["tail_difference"]["semantic_proof"] is False


def test_fade_is_unsupported_even_without_black():
    sharp = pattern()
    result = select([sharp, ImageEnhance.Brightness(sharp).enhance(0.4)])
    assert all(c["usable"] for c in result["candidates"])
    assert not result["can_use"] and not result["technical_tail_compatible"]
    assert result["reason"] == "fade_unsupported_requires_human"


def test_unusable_observation_blocks_even_a_good_true_last():
    result = select([pattern(), Image.new("RGB", (96, 64)), pattern()])
    assert result["selected"]["frame_index"] == 2
    assert not result["can_use"]
    assert result["reason"] == "observation_candidate_unusable_requires_human"


@pytest.mark.parametrize("content", [b"", b"corrupt not a movie"])
def test_corrupt_empty_input_returns_integrity_error(tmp_path, media_tools, content):
    source = tmp_path / "bad.mov"
    source.write_bytes(content)
    result = extract(source, tmp_path / "bad-tail")
    assert set(result) == RESULT_KEYS
    assert not result["can_use"] and result["reason"] == "source_integrity"
    assert result["error"] and result["selected"] is None
    assert result["source_sha256_after"] == digest(source)
    assert not list((tmp_path / "bad-tail").iterdir())


def test_truncated_real_video_cannot_use_earlier_eof(tmp_path, media_tools):
    source = video(tmp_path, [pattern()] * 12)
    # Fixture corruption only: faststart retains the declared duration/frame count.
    damaged = tmp_path / "truncated.mov"
    command("ffmpeg", "-v", "error", "-n", "-i", str(source), "-c", "copy",
            "-movflags", "+faststart", str(damaged))
    damaged.write_bytes(damaged.read_bytes()[:-400])
    result = extract(damaged, tmp_path / "truncated-tail")
    assert not result["can_use"] and not result["technical_tail_compatible"]
    assert result["reason"] == "source_integrity" and result["error"]


def test_hash_mismatch_no_output_or_subprocess(tmp_path, monkeypatch):
    source = tmp_path / "source.mov"
    source.write_bytes(b"fixture")
    async def forbidden(*args):
        raise AssertionError("must validate input hash before subprocess")
    monkeypatch.setattr(frames, "_run", forbidden)
    with pytest.raises(ValueError, match="source_integrity: expected_sha256 mismatch"):
        asyncio.run(frames.extract_tail_window(source, tmp_path / "tail", expected_sha256="0" * 64))
    assert not (tmp_path / "tail").exists()


def test_new_directory_required_no_cached_reuse_or_parent_creation(tmp_path, monkeypatch):
    source = tmp_path / "source.mov"
    source.write_bytes(b"fixture")
    output = tmp_path / "tail"
    output.mkdir()
    cached = output / "frame_00000000.png"
    cached.write_bytes(b"unrelated cached bytes")
    async def forbidden(*args):
        raise AssertionError("collision must precede decode")
    monkeypatch.setattr(frames, "_run", forbidden)
    with pytest.raises(FileExistsError):
        extract(source, output)
    assert cached.read_bytes() == b"unrelated cached bytes"
    with pytest.raises(FileNotFoundError):
        extract(source, tmp_path / "missing-parent" / "tail")
    assert not (tmp_path / "missing-parent").exists()


def test_source_changed_during_read_raises(tmp_path, monkeypatch):
    source = tmp_path / "source.mov"
    source.write_bytes(b"before")
    async def changed(*args):
        source.write_bytes(b"after")
        raise ValueError("injected decode failure")
    monkeypatch.setattr(frames, "_run", changed)
    with pytest.raises(ValueError, match="source_integrity: source changed"):
        extract(source, tmp_path / "tail")


@pytest.mark.parametrize("fault", ["unknown_duration", "count", "end", "last_error", "decode_error", "short_raw"])
def test_untrusted_eof_retains_known_actual_metadata(tmp_path, monkeypatch, fault):
    source = tmp_path / "source.mov"
    source.write_bytes(b"mocked local source")
    probe = {
        "frames": [{"best_effort_timestamp_time": str(i / 10), "duration_time": "0.1",
                    "width": 96, "height": 64} for i in range(6)],
        "streams": [{"start_time": "0", "duration": "0.6", "nb_frames": "6", "width": 96, "height": 64}],
    }
    if fault == "unknown_duration":
        del probe["frames"][-1]["duration_time"]
    elif fault == "count":
        probe["streams"][0]["nb_frames"] = "7"
    elif fault == "end":
        probe["streams"][0]["duration"] = "0.7"
    elif fault == "last_error":
        probe["frames"][-1]["decode_error_flags"] = 1

    async def run(*args):
        assert args[args.index("-protocol_whitelist") + 1] == "file,pipe"
        assert "-format_whitelist" in args
        assert not {"-ss", "-sseof", "-t", "-r", "-y"}.intersection(args)
        if args[0] == "ffprobe":
            return json.dumps(probe).encode()
        if fault == "decode_error":
            raise ValueError("actual decoder EOF error")
        assert fault == "short_raw", "must stop before decoding an untrusted source"
        return b"short payload"

    monkeypatch.setattr(frames, "_run", run)
    result = extract(source, tmp_path / "tail")
    assert not result["can_use"] and not result["technical_tail_compatible"]
    assert result["reason"] == "source_integrity" and result["error"]
    assert result["last_frame_index"] == 5 and result["last_frame_pts"] == 0.5
    assert result["selected"] is None
    assert all(not c["usable"] for c in result["candidates"])
    assert result["source_sha256"] == result["source_sha256_after"] == digest(source)
    if fault != "unknown_duration":
        assert result["candidates"][-1]["frame_index"] == 5


def test_exclusive_png_creation_never_overwrites_intruding_file(tmp_path, media_tools, monkeypatch):
    source = video(tmp_path, [pattern()], fps=1)
    output = tmp_path / "tail"
    intruder = output / "frame_00000000.png"
    original = frames._run

    async def collide(*args):
        data = await original(*args)
        if args[0] == "ffmpeg":
            intruder.write_bytes(b"not our evidence")
        return data

    monkeypatch.setattr(frames, "_run", collide)
    result = extract(source, output)
    assert not result["can_use"] and "FileExistsError" in result["error"]
    assert intruder.read_bytes() == b"not our evidence"
    assert result["candidates"][0]["sha256"] is None


def test_network_url_rejected_without_subprocess(tmp_path, monkeypatch):
    async def forbidden(*args):
        raise AssertionError("network input must not start a subprocess")
    monkeypatch.setattr(frames, "_run", forbidden)
    with pytest.raises(ValueError, match="source_integrity"):
        asyncio.run(frames.extract_tail_window("https://example.invalid/video.mp4", tmp_path / "tail",
                                              expected_sha256="0" * 64))
    assert not (tmp_path / "tail").exists()


@pytest.mark.parametrize("during_spawn", [False, True])
def test_subprocess_cancellation_kills_and_reaps(tmp_path, monkeypatch, during_spawn):
    async def scenario():
        original = asyncio.create_subprocess_exec
        started, release = asyncio.Event(), asyncio.Event()
        children = []
        async def capture(*args, **kwargs):
            child = await original(*args, cwd=tmp_path, **kwargs)
            children.append(child)
            started.set()
            if during_spawn:
                await release.wait()
            return child
        monkeypatch.setattr(frames.asyncio, "create_subprocess_exec", capture)
        task = asyncio.create_task(frames._run(sys.executable, "-B", "-c", "import time; time.sleep(60)"))
        await asyncio.wait_for(started.wait(), 5)
        if not during_spawn:
            await asyncio.sleep(0.05)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
        assert children[0].returncode is not None
        with pytest.raises(ProcessLookupError):
            os.kill(children[0].pid, 0)
    asyncio.run(scenario())


def test_subprocess_timeout_kills_and_reaps(tmp_path, monkeypatch):
    async def scenario():
        original = asyncio.create_subprocess_exec
        children = []
        async def capture(*args, **kwargs):
            child = await original(*args, cwd=tmp_path, **kwargs)
            children.append(child)
            return child
        monkeypatch.setattr(frames.asyncio, "create_subprocess_exec", capture)
        monkeypatch.setattr(frames, "_TIMEOUT", 0.05)
        with pytest.raises(asyncio.TimeoutError):
            await frames._run(sys.executable, "-B", "-c", "import time; time.sleep(60)")
        assert children[0].returncode is not None
        with pytest.raises(ProcessLookupError):
            os.kill(children[0].pid, 0)
    asyncio.run(scenario())
