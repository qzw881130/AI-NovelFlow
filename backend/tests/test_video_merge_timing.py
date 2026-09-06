import asyncio
from array import array
import json
from math import ceil
import shutil
import subprocess

import pytest

from app.services.file_storage import FileStorageService


pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg required"
)


def ffmpeg(*args):
    return subprocess.run(
        ["ffmpeg", "-v", "error", "-xerror", *map(str, args)],
        check=True, capture_output=True,
    ).stdout


@pytest.mark.parametrize("single", [False, True])
@pytest.mark.parametrize("audio_codec", ["pcm_s16le", "aac"])
def test_sample_continuity_and_late_av_markers(tmp_path, single, audio_codec):
    # Short audio accumulates several seconds of missing samples in copy concat.
    # Include a non-frame-aligned longer track, silence, 30fps and 44.1kHz input.
    specs = [(1, 0.4, 0)] * 13 + [(0.5, 1.07, 0), (0.75, None, 0), (1, 0.5, 0.125)]
    if single:
        specs = [specs[-1]]
    paths = []
    expected = []
    offset = 0
    for index, (video_duration, audio_duration, audio_delay) in enumerate(specs):
        path = tmp_path / f"clip_{index}.mov"
        # White flash and beep both start at local 0.25s on the common timeline.
        cmd = ["-f", "lavfi", "-i",
               f"color=black:s=64x64:r=30:d={video_duration},"
               "drawbox=color=white:t=fill:enable='between(t,0.25,0.35)'",]
        if audio_duration is not None:
            beep_start = 0.25 - audio_delay
            tail = "+between(t\\,0.95\\,1.03)" if audio_duration == 1.07 else ""
            cmd += ["-f", "lavfi", "-i",
                    f"aevalsrc=0.6*sin(2*PI*1000*t)*(between(t\\,{beep_start}\\,{beep_start + 0.08}){tail}):s=44100:d={audio_duration}",
                    "-af", f"asetpts=PTS+{audio_delay}/TB", "-c:a", audio_codec]
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", path]
        ffmpeg(*cmd)
        paths.append(str(path))
        frames = round(video_duration * 24)
        if audio_duration == 1.07:
            # Measure decoded samples independently, including source codec padding.
            source_audio = ffmpeg("-i", path, "-map", "0:a:0", "-ar", "48000", "-ac", "1", "-f", "f32le", "-")
            frames = max(frames, ceil(len(source_audio) / 4 / 2000))
        expected.append((offset, frames * 2000, audio_duration))
        offset += frames * 2000

    output = tmp_path / "merged.mp4"
    transitions = None
    if not single:
        # Route the silent segment through the real transition insertion path.
        transitions = [None] * 13 + [paths.pop(14)]
    result = asyncio.run(FileStorageService(str(tmp_path)).merge_videos(paths, str(output), transitions))
    assert result["success"], result
    audio = array("f")
    audio.frombytes(ffmpeg("-i", output, "-map", "0:a:0", "-ac", "1", "-f", "f32le", "-"))
    video = ffmpeg("-i", output, "-map", "0:v:0", "-vf", "scale=1:1", "-pix_fmt", "gray", "-f", "rawvideo", "-")
    assert len(video) == offset // 2000
    # Only the final AAC packet may contain encoder padding, never each boundary.
    assert offset <= len(audio) < offset + 1024
    for start, samples, audio_duration in expected:
        active = [i for i in range(start, start + samples) if abs(audio[i]) > 0.15]
        if audio_duration is None:
            assert not active
            continue
        assert abs(active[0] - (start + 12000)) < 240  # within 5ms in decoded samples
        beep_end = 49440 if audio_duration == 1.07 else 15840
        assert abs(active[-1] - (start + beep_end)) < 240
        if audio_duration == 1.07:
            assert all(value == video[start // 2000 + 11] for value in video[start // 2000 + 12:(start + samples) // 2000])
        flashes = [i for i in range(start // 2000, (start + samples) // 2000) if video[i] > 200]
        assert flashes
        assert abs(flashes[0] * 2000 - active[0]) <= 2000

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_packets",
         "-show_entries", "packet=pts,dts,duration", "-of", "json", str(output)],
        check=True, capture_output=True, text=True,
    )
    packets = json.loads(probe.stdout)["packets"]
    for previous, current in zip(packets, packets[1:]):
        assert current["pts"] == previous["pts"] + previous["duration"]
        assert current["dts"] > previous["dts"]
    video_probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_frames",
         "-show_entries", "frame=pts_time", "-of", "json", str(output)],
        check=True, capture_output=True, text=True,
    )
    for index, frame in enumerate(json.loads(video_probe.stdout)["frames"]):
        assert abs(float(frame["pts_time"]) - index / 24) < 0.000002
    assert not list(tmp_path.glob(".novelflow_merge_*"))


def test_corrupt_source_is_not_concealed(tmp_path):
    source = tmp_path / "broken.mp4"
    source.write_bytes(b"not a video")
    output = tmp_path / "published.mp4"
    output.write_bytes(b"previous output")
    result = asyncio.run(FileStorageService(str(tmp_path)).merge_videos([str(source)], str(output)))
    assert not result["success"]
    assert output.read_bytes() == b"previous output"
    assert source.read_bytes() == b"not a video"
    assert not list(tmp_path.glob(".novelflow_merge_*"))
