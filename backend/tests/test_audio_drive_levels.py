from array import array
from copy import deepcopy
import json
import math
from pathlib import Path
import shutil
import subprocess
import wave

import pytest
from sqlalchemy.orm import Session

from app.models.audio_drive import AudioEventTTSAsset, ShotAudioEvent, ShotAudioTimeline
from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.task import Task
from app.services.audio_drive_service import AudioDriveService, CLIP_AUDIO_RENDER_PROFILE
from app.services.file_storage import file_storage
from app.services.rendered_subtitles import fingerprint, load, publish, sidecar
from app.services.video_director_plan_service import VideoDirectorPlanService


pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="local ffmpeg/ffprobe required")
RATE = 44100


def source(tmp_path, name, expression="0.1*sin(2*PI*1000*t)", duration=0.2, rate=RATE):
    path = tmp_path / f"{name}.wav"
    subprocess.run([
        "ffmpeg", "-nostdin", "-v", "error", "-xerror", "-n", "-f", "lavfi", "-i",
        f"aevalsrc=exprs='{expression}':s={rate}:d={duration}", "-c:a", "pcm_f32le", str(path),
    ], capture_output=True, check=True)
    return path


def segment(path, start=0.0, duration=0.2, source_start=0.0):
    return {"source_path": str(path), "clip_start": start, "duration": duration, "source_start": source_start}


def pcm(path):
    with wave.open(str(path), "rb") as stream:
        assert (stream.getframerate(), stream.getnchannels(), stream.getsampwidth()) == (RATE, 2, 2)
        samples = array("h", stream.readframes(stream.getnframes()))
    return samples


def rms_db(samples):
    return 20 * math.log10(math.sqrt(sum((sample / 32768) ** 2 for sample in samples) / len(samples)))


def test_delayed_utterances_have_no_input_count_or_order_attenuation(tmp_path):
    voice = source(tmp_path, "voice")
    silent = source(tmp_path, "silent", "0")
    one = [segment(voice, start=0.1)]
    many = [segment(voice, start=start) for start in (0.1, 0.5, 0.9)] + [segment(silent)]
    outputs = []
    for name, segments in (("one", one), ("many", many), ("reversed", deepcopy(many[::-1])), ("empty", [])):
        output = tmp_path / f"{name}.wav"
        result = AudioDriveService(None)._render_clip_audio(segments, output, 1.234)
        assert result["success"], result
        outputs.append(pcm(output))
    single, mixed, reversed_mix, empty = outputs
    assert all(len(samples) == 2 * round(1.234 * RATE) for samples in outputs)
    assert mixed == reversed_mix
    utterance = single[2 * round(0.1 * RATE):2 * round(0.3 * RATE)]
    assert rms_db(utterance) == pytest.approx(-20, abs=0.005)
    assert not any(single[:2 * round(0.1 * RATE)])
    assert not any(single[2 * round(0.3 * RATE):])
    assert not any(empty)
    for start in (0.1, 0.5, 0.9):
        offset = 2 * round(start * RATE)
        assert mixed[offset:offset + len(utterance)] == utterance
    assert one[0]["speech_level"]["sourceRmsDbfs"] == pytest.approx(-23.0103, abs=0.001)
    assert all(s["speech_level"] == one[0]["speech_level"] for s in many[:3])


def test_mono_is_unity_duplicated_and_stereo_image_is_preserved(tmp_path):
    mono = source(tmp_path, "mono")
    stereo = source(tmp_path, "stereo", "0.1*sin(2*PI*1000*t)|0.1*sin(2*PI*1000*t)")
    asymmetric = source(tmp_path, "asymmetric", "0.2*sin(2*PI*1000*t)|-0.05*sin(2*PI*1000*t)")
    samples = []
    for index, path in enumerate((mono, stereo, asymmetric)):
        output = tmp_path / f"out-{index}.wav"
        assert AudioDriveService(None)._render_clip_audio([segment(path)], output, 0.2)["success"]
        samples.append(pcm(output))
    assert samples[0] == samples[1]
    assert samples[0][::2] == samples[0][1::2]
    assert max(abs(left + 4 * right) for left, right in zip(samples[2][::2], samples[2][1::2])) <= 3


def test_different_source_levels_share_one_target_not_one_clip_gain(tmp_path):
    quiet = source(tmp_path, "quiet", "0.08*sin(2*PI*1000*t)")
    loud = source(tmp_path, "loud", "0.2*sin(2*PI*1000*t)")
    segments = [segment(quiet), segment(loud, start=0.4)]
    output = tmp_path / "dialogue-narration.wav"
    assert AudioDriveService(None)._render_clip_audio(segments, output, 2.0)["success"]
    samples = pcm(output)
    assert rms_db(samples[:2 * round(0.2 * RATE)]) == pytest.approx(-20, abs=0.005)
    assert rms_db(samples[2 * round(0.4 * RATE):2 * round(0.6 * RATE)]) == pytest.approx(-20, abs=0.005)
    assert segments[0]["speech_level"]["gainDb"] > 0
    assert segments[1]["speech_level"]["gainDb"] < 0


@pytest.mark.parametrize("amplitude,expected_gain,reason", [
    (0.03, 6.0, "gain_bound"),
    (0.7, -6.0, "gain_bound"),
    (0.0001, 0.0, "silence_guard"),
    (0.0, 0.0, "silence_guard"),
])
def test_gain_bounds_and_silence_guard(tmp_path, amplitude, expected_gain, reason):
    path = source(tmp_path, "source", f"{amplitude}*sin(2*PI*1000*t)")
    segments = [segment(path)]
    output = tmp_path / "out.wav"
    assert AudioDriveService(None)._render_clip_audio(segments, output, 0.4)["success"]
    level = segments[0]["speech_level"]
    assert level["gainDb"] == expected_gain
    assert level["gainReason"] == reason
    assert len(pcm(output)) == 2 * round(0.4 * RATE)
    json.dumps(level, allow_nan=False)
    if amplitude == 0:
        assert level["sourceRmsDbfs"] is None and level["sourcePeakDbfs"] is None
        assert not any(pcm(output))


def test_source_peak_headroom_and_overlap_guard_do_not_shift_impulses(tmp_path):
    path = source(tmp_path, "impulses", "0.99*(eq(n,100)+eq(n,8819))")
    single, overlapping = [], []
    for count, collection in ((1, single), (3, overlapping)):
        segments = [segment(path, start=0.1) for _ in range(count)]
        output = tmp_path / f"peak-{count}.wav"
        assert AudioDriveService(None)._render_clip_audio(segments, output, 0.3)["success"]
        collection.extend(pcm(output)[::2])
        assert segments[0]["speech_level"]["gainReason"] == "peak_headroom"
        assert segments[0]["speech_level"]["gainDb"] < 0
    ceiling = math.floor(32768 * 10 ** (-1 / 20))
    for samples in (single, overlapping):
        assert len(samples) == round(0.3 * RATE)
        assert [index for index, sample in enumerate(samples) if sample] == [4410 + 100, 4410 + 8819]
        assert max(abs(sample) for sample in samples) <= ceiling


@pytest.mark.parametrize("duration", [0.025, 0.145, 1.234])
def test_clip_sample_count_and_delays_match_existing_ffmpeg_timing(tmp_path, duration):
    path = source(tmp_path, "impulse", "0.1*eq(n,50)", duration=0.02)
    legacy = tmp_path / "legacy.wav"
    subprocess.run([
        "ffmpeg", "-nostdin", "-v", "error", "-n", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-i", str(path), "-filter_complex",
        f"[0:a]atrim=0:{duration:.3f},asetpts=PTS-STARTPTS[base];"
        "[1:a]atrim=start=0:duration=0.02,asetpts=PTS-STARTPTS,aresample=44100,"
        "aformat=sample_fmts=s16:channel_layouts=stereo,adelay=3|3[voice];"
        f"[base][voice]amix=inputs=2:duration=first:dropout_transition=0,atrim=0:{duration:.3f}[out]",
        "-map", "[out]", "-c:a", "pcm_s16le", str(legacy),
    ], capture_output=True, check=True)
    improved = tmp_path / "improved.wav"
    silence = tmp_path / "silence.wav"
    service = AudioDriveService(None)
    assert service._render_clip_audio([segment(path, start=0.003, duration=0.02)], improved, duration)["success"]
    assert service._render_clip_audio([], silence, duration)["success"]
    original, new = pcm(legacy)[::2], pcm(improved)[::2]
    assert len(new) == len(original) == len(pcm(silence)[::2])
    assert [index for index, sample in enumerate(new) if sample] == [index for index, sample in enumerate(original) if sample]


@pytest.mark.parametrize("rate", [44100, 48000])
def test_whole_utterance_gain_and_samples_survive_clip_boundaries_and_padding(tmp_path, rate):
    path = source(tmp_path, "changing-level", "(0.035+0.175*gte(t,0.6))*sin(2*PI*997*t)", duration=1.2, rate=rate)
    measured = []
    rendered = []
    for name, start, length, output_duration in (("whole", 0, 1.2, 1.2), ("left", 0, 0.6, 0.6),
                                               ("right", 0.6, 0.6, 0.6), ("padded", 0, 1.2, 3.0)):
        segments = [segment(path, source_start=start, duration=length)]
        output = tmp_path / f"{name}.wav"
        # Separate service instances cannot accidentally reuse a per-clip measurement.
        assert AudioDriveService(None)._render_clip_audio(segments, output, output_duration)["success"]
        measured.append(segments[0]["speech_level"])
        rendered.append(pcm(output))
    assert all(level == measured[0] for level in measured)
    assert rendered[1] + rendered[2] == rendered[0]
    assert rendered[3][:len(rendered[0])] == rendered[0]
    assert not any(rendered[3][len(rendered[0]):])


@pytest.fixture
def ready_clip(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(file_storage, "base_dir", tmp_path)
    novel = Novel(title="Isolated audio levels")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="Test", content="")
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(chapter_id=chapter.id, index=1, description="Test", estimated_duration=1.2, duration=9,
                continuity_mode="CONTINUOUS_TAKE")
    db_session.add(shot)
    db_session.flush()
    event = ShotAudioEvent(shot_id=shot.id, event_order=1, event_type="DIALOGUE", text="Bound source",
                          voice_owner_name="A", visible_speaker_name="A", requires_visible_lipsync=True,
                          pause_after="NONE", tts_status="READY")
    db_session.add(event)
    db_session.commit()
    service = AudioDriveService(db_session)
    path = source(tmp_path, "tts", "0.07*sin(2*PI*997*t)", duration=1.2)
    asset = service.repo.add_tts_asset(event.id, audio_path=str(path), status="READY", duration_seconds=1.2,
                                      text_hash=service._hash_payload({"text": event.text}))
    publish(path, [{"start": "0", "end": "1.2", "text": event.text}],
            {"kind": "tts", "tts_asset_id": asset.id, "text_hash": asset.text_hash})
    assert service.build_timeline(shot.id, force=True)["success"]
    assert service.build_execution_windows(shot.id)["success"]
    return service, shot, event, asset


def test_versioned_publication_cache_and_subtitle_lineage_preserve_all_old_files(ready_clip, db_session, monkeypatch):
    service, shot, event, asset = ready_clip
    old_paths = [file_storage.get_clip_audio_path(shot.chapter.novel_id, shot.chapter_id, shot.id, 1, kind)
                 for kind in ("drive_audio", "final_audio")]
    for path in old_paths:
        path.write_bytes(b"historical audio bytes")
    old_manifest = old_paths[0].with_suffix(".json")
    old_manifest.write_text('{"historical": true}')
    publish(old_paths[1], [{"start": "0", "end": "1", "text": "Historical"}], {"kind": "clip_audio"})
    preserved = {path: path.read_bytes() for path in [*old_paths, old_manifest, sidecar(old_paths[1]),
                                                    Path(asset.audio_path), sidecar(asset.audio_path)]}
    before_timeline = service.repo.latest_timeline(shot.id)
    timeline_state = (before_timeline.id, before_timeline.revision, before_timeline.audio_summary_json)
    plan_before = json.loads(shot.video_director_plan)
    first = service.build_clip_audio(shot.id, 1, force=True)["data"]
    first_window = json.loads(shot.video_director_plan)["window_plans"][0]
    first_manifest = json.loads(Path(first_window["clip_audio_manifest_path"]).read_text())
    metadata = first["renderMetadata"]
    assert metadata["profile"] == CLIP_AUDIO_RENDER_PROFILE
    assert metadata["sourceLevels"][0]["ttsAssetId"] == asset.id
    assert metadata["sourceLevels"][0]["sourceSha256"] == fingerprint(asset.audio_path)
    assert metadata == first_manifest["render_metadata"]
    assert first_manifest["drive_segments"][0]["speech_level"] == first_manifest["final_segments"][0]["speech_level"]
    assert pcm(first_window["drive_audio_path"]) == pcm(first_window["final_audio_path"])
    first_snapshot = load(first_window["final_audio_path"])
    assert first_snapshot["lineage"]["render_metadata"] == metadata
    assert first_snapshot["cues"][0]["text"] == event.text
    for key in ("drive_audio_path", "final_audio_path", "clip_audio_manifest_path"):
        path = Path(first_window[key])
        preserved[path] = path.read_bytes()
    preserved[sidecar(first_window["final_audio_path"])] = sidecar(first_window["final_audio_path"]).read_bytes()

    plan_state = shot.video_director_plan
    with monkeypatch.context() as guard:
        guard.setattr(service, "_render_clip_audio", lambda *_: pytest.fail("cache must not render"))
        guard.setattr(service, "_measure_speech_level", lambda *_: pytest.fail("cache must not measure"))
        guard.setattr(service, "build_timeline", lambda *_: pytest.fail("cache must not rebuild timeline"))
        assert service.build_clip_audio(shot.id, 1)["data"]["renderMetadata"] == metadata
        assert service.get_timeline(shot.id)["data"]["timingSummary"]["lastTtsFileEndSeconds"] == 1.2
    assert shot.video_director_plan == plan_state
    second = service.build_clip_audio(shot.id, 1, force=True)["data"]
    assert second["finalAudioUrl"] != first["finalAudioUrl"]
    assert second["renderMetadata"]["renderId"] != metadata["renderId"]
    assert second["renderMetadata"]["sourceLevels"] == metadata["sourceLevels"]
    assert all(path.read_bytes() == data for path, data in preserved.items())
    assert json.loads(shot.video_director_plan)["execution_windows"] == plan_before["execution_windows"]
    assert (before_timeline.id, before_timeline.revision, before_timeline.audio_summary_json) == timeline_state
    assert db_session.query(ShotAudioTimeline).count() == 1
    assert db_session.query(AudioEventTTSAsset).count() == 1
    assert db_session.query(Task).count() == 0
    assert shot.duration == 9 and shot.continuity_mode == "CONTINUOUS_TAKE"


def test_changed_media_does_not_claim_verified_levels_or_repair_cached_audio(ready_clip, monkeypatch):
    service, shot, _, _ = ready_clip
    assert service.build_clip_audio(shot.id, 1, force=True)["success"]
    before = shot.video_director_plan
    window = json.loads(before)["window_plans"][0]
    Path(window["final_audio_path"]).write_bytes(b"externally replaced test media")
    original_sidecar = sidecar(window["final_audio_path"]).read_bytes()
    monkeypatch.setattr(service, "_render_clip_audio", lambda *_: pytest.fail("must not repair cached audio"))
    result = service.build_clip_audio(shot.id, 1)["data"]
    assert result["audioStatus"] == "READY"
    assert result["subtitleStatus"] == "UNAVAILABLE"
    assert result["renderMetadata"] is None
    assert sidecar(window["final_audio_path"]).read_bytes() == original_sidecar
    assert shot.video_director_plan == before


@pytest.mark.parametrize("snapshot_state", ["missing", "unavailable", "verified"])
def test_legacy_ready_cache_is_reused_without_profile_or_subtitle_backfill(ready_clip, db_session, monkeypatch, snapshot_state):
    service, shot, _, _ = ready_clip
    timeline = service.repo.latest_timeline(shot.id)
    paths = [file_storage.get_clip_audio_path(shot.chapter.novel_id, shot.chapter_id, shot.id, 1, kind)
             for kind in ("drive_audio", "final_audio")]
    for path in paths:
        path.write_bytes(b"legacy")
    if snapshot_state != "missing":
        publish(paths[1], [], {"kind": "clip_audio"}, unavailable="legacy source" if snapshot_state == "unavailable" else None)
    plan = json.loads(shot.video_director_plan)
    plan["window_plans"][0].update(audio_status="READY", audio_timeline_id=timeline.id,
                                   audio_timeline_revision=timeline.revision, audio_timeline_hash=timeline.generated_from_hash)
    shot.video_director_plan = json.dumps(plan)
    db_session.commit()
    before = shot.video_director_plan
    before_files = {path: path.read_bytes() for path in paths[0].parent.iterdir() if path.is_file()}
    monkeypatch.setattr(service, "_render_clip_audio", lambda *_: pytest.fail("legacy audio must not rerender"))
    result = service.build_clip_audio(shot.id, 1)
    assert result["success"]
    assert result["data"]["renderMetadata"] is None
    assert result["data"]["subtitleStatus"] == ("READY" if snapshot_state == "verified" else "UNAVAILABLE")
    assert shot.video_director_plan == before
    assert {path: path.read_bytes() for path in paths[0].parent.iterdir() if path.is_file()} == before_files


@pytest.mark.parametrize("change", [{"audio_timeline_id": "old"}, {"audio_timeline_revision": 0}, {"audio_timeline_hash": "old"}])
def test_stale_timeline_binding_does_not_become_a_cache_hit(ready_clip, db_session, monkeypatch, change):
    service, shot, _, _ = ready_clip
    assert service.build_clip_audio(shot.id, 1, force=True)["success"]
    plan = json.loads(shot.video_director_plan)
    plan["window_plans"][0].update(change)
    shot.video_director_plan = json.dumps(plan)
    db_session.commit()
    monkeypatch.setattr(service, "_render_clip_audio", lambda *_: {"success": False, "message": "cache missed"})
    assert service.build_clip_audio(shot.id, 1) == {"success": False, "message": "cache missed"}


@pytest.mark.parametrize("failure", ["second_track", "source_changed", "invalid_source"])
def test_failed_new_render_leaves_previous_selection_and_snapshot_intact(ready_clip, db_session, monkeypatch, failure):
    service, shot, _, asset = ready_clip
    assert service.build_clip_audio(shot.id, 1, force=True)["success"]
    before = shot.video_director_plan
    window = json.loads(before)["window_plans"][0]
    snapshot = load(window["final_audio_path"])
    originals = {Path(window[key]): Path(window[key]).read_bytes()
                 for key in ("drive_audio_path", "final_audio_path", "clip_audio_manifest_path")}
    if failure == "invalid_source":
        Path(asset.audio_path).write_bytes(b"broken test source")
    else:
        render = service._render_clip_audio
        calls = []

        def fail(segments, path, duration):
            calls.append(path)
            if len(calls) == 2 and failure == "second_track":
                return {"success": False, "message": "isolated render failure"}
            result = render(segments, path, duration)
            if len(calls) == 2 and failure == "source_changed":
                Path(asset.audio_path).write_bytes(b"changed test source")
            return result

        monkeypatch.setattr(service, "_render_clip_audio", fail)
    assert not service.build_clip_audio(shot.id, 1, force=True)["success"]
    assert shot.video_director_plan == before
    assert load(window["final_audio_path"]) == snapshot
    assert all(path.read_bytes() == content for path, content in originals.items())
    assert db_session.query(Task).count() == 0


@pytest.mark.parametrize("change", ["range", "removed_window", "timeline_revision", "timeline_status", "new_timeline",
                                    "window_revision", "audio_status", "manifest_selection", "source_selection"])
def test_concurrent_render_input_change_preserves_current_selection(ready_clip, db_session, monkeypatch, change):
    service, shot, _, asset = ready_clip
    assert service.build_clip_audio(shot.id, 1, force=True)["success"]
    window = json.loads(shot.video_director_plan)["window_plans"][0]
    originals = {Path(window[key]): Path(window[key]).read_bytes()
                 for key in ("drive_audio_path", "final_audio_path", "clip_audio_manifest_path")}
    originals[sidecar(window["final_audio_path"])] = sidecar(window["final_audio_path"]).read_bytes()
    originals[Path(asset.audio_path)] = Path(asset.audio_path).read_bytes()
    timeline = service.repo.latest_timeline(shot.id)
    starting_revision = shot.video_director_plan_revision
    render = service._render_clip_audio
    concurrent_plan = []

    def render_with_change(segments, path, duration):
        result = render(segments, path, duration)
        if not concurrent_plan:
            with Session(db_session.get_bind()) as other:
                current_shot = other.get(Shot, shot.id)
                plan = json.loads(current_shot.video_director_plan)
                if change == "range":
                    plan["window_plans"][0]["end_time"] += 0.5
                elif change == "removed_window":
                    plan["window_plans"] = []
                    plan["execution_windows"] = []
                elif change == "source_selection":
                    # A selected source/binding can change without changing the range.
                    plan["window_plans"][0]["final_audio_url"] = "/api/files/new-selected-audio.wav"
                elif change == "window_revision":
                    plan["window_plans"][0]["audio_timeline_revision"] += 1
                elif change == "audio_status":
                    plan["window_plans"][0]["audio_status"] = "STALE"
                elif change == "manifest_selection":
                    plan["window_plans"][0]["clip_audio_manifest_path"] = str(Path(asset.audio_path).with_suffix(".json"))
                elif change == "new_timeline":
                    other.add(ShotAudioTimeline(shot_id=shot.id, revision=timeline.revision + 1,
                                               status="READY", generated_from_hash="new-timeline"))
                else:
                    current_timeline = other.get(ShotAudioTimeline, timeline.id)
                    if change == "timeline_revision":
                        current_timeline.revision += 1
                    else:
                        current_timeline.status = "STALE"
                # Also cover legacy/direct writes that do not advance the plan revision.
                current_shot.video_director_plan = json.dumps(plan)
                other.commit()
                concurrent_plan.append(current_shot.video_director_plan)
        return result

    monkeypatch.setattr(service, "_render_clip_audio", render_with_change)
    result = service.build_clip_audio(shot.id, 1, force=True)
    assert result["success"] is False and result["status_code"] == 409
    assert "Refresh" in result["message"] and "explicitly rebuild" in result["message"]
    db_session.refresh(shot)
    assert shot.video_director_plan == concurrent_plan[0]
    assert shot.video_director_plan_revision == starting_revision
    assert all(path.read_bytes() == content for path, content in originals.items())
    assert db_session.query(Task).count() == 0


@pytest.mark.parametrize("change", ["range", "timeline_revision", "source_bytes"])
def test_publication_cas_rejects_change_after_snapshot_check(ready_clip, db_session, monkeypatch, change):
    service, shot, _, asset = ready_clip
    assert service.build_clip_audio(shot.id, 1, force=True)["success"]
    window = json.loads(shot.video_director_plan)["window_plans"][0]
    snapshot = load(window["final_audio_path"])
    originals = {Path(window[key]): Path(window[key]).read_bytes()
                 for key in ("drive_audio_path", "final_audio_path", "clip_audio_manifest_path")}
    starting_revision = shot.video_director_plan_revision
    original_mutate = VideoDirectorPlanService.mutate
    concurrent_plan = []
    checked_plans = []

    def race_mutate(plan_service, shot_id, mutator, **kwargs):
        def change_after_check(latest):
            checked_plans.append(deepcopy(latest))
            candidate = mutator(latest)
            with Session(db_session.get_bind()) as other:
                current = other.get(Shot, shot_id)
                plan = json.loads(current.video_director_plan)
                if change == "range":
                    plan["window_plans"][0]["end_time"] += 0.5
                elif change == "timeline_revision":
                    other.get(ShotAudioTimeline, window["audio_timeline_id"]).revision += 1
                else:
                    Path(asset.audio_path).write_bytes(b"test source changed during publication")
                current.video_director_plan = json.dumps(plan)
                current.video_director_plan_revision += 1
                other.commit()
                concurrent_plan.append(current.video_director_plan)
            return candidate

        return original_mutate(plan_service, shot_id, change_after_check, **kwargs)

    monkeypatch.setattr(VideoDirectorPlanService, "mutate", race_mutate)
    result = service.build_clip_audio(shot.id, 1, force=True)
    assert result["success"] is False and result["status_code"] == 409
    assert len(concurrent_plan) == 1
    assert len(checked_plans) == 2
    db_session.refresh(shot)
    assert shot.video_director_plan == concurrent_plan[0]
    assert shot.video_director_plan_revision == starting_revision + 1
    assert load(window["final_audio_path"]) == snapshot
    assert all(path.read_bytes() == content for path, content in originals.items())
    assert db_session.query(Task).count() == 0


@pytest.mark.parametrize("update_at", ["render", "publication"])
@pytest.mark.parametrize("collection", ["window_plans", "execution_windows"])
def test_benign_parallel_plan_updates_survive_audio_publication(ready_clip, db_session, monkeypatch, update_at, collection):
    service, shot, _, _ = ready_clip
    assert service.build_clip_audio(shot.id, 1, force=True)["success"]
    plan = json.loads(shot.video_director_plan)
    old_window = plan["window_plans"][0]
    old_snapshot = load(old_window["final_audio_path"])
    if collection == "execution_windows":
        plan["execution_windows"] = plan.pop("window_plans")
        shot.video_director_plan = json.dumps(plan)
        db_session.commit()
    starting_revision = shot.video_director_plan_revision
    concurrent_plans = []
    render_calls = []
    publication_attempts = []
    render = service._render_clip_audio
    original_mutate = VideoDirectorPlanService.mutate

    def update_unrelated_fields():
        with Session(db_session.get_bind()) as other:
            current = other.get(Shot, shot.id)
            latest = json.loads(current.video_director_plan)
            latest["keyframes"] = [{"index": 1, "image_url": "/api/files/test-keyframe.png", "status": "READY"}]
            latest["keyframe_planning_status"] = "READY"
            latest["ai_calls"] = [{"id": "parallel-image-call", "status": "completed"}]
            latest[collection][0].update(prompt_text="Updated image prompt", keyframe_indexes=[1],
                                         image_url="/api/files/test-window.png", status="COMPLETED",
                                         ai_calls=[{"id": "parallel-window-call"}])
            current.video_director_plan = json.dumps(latest)
            current.video_director_plan_revision += 1
            other.commit()
            concurrent_plans.append(latest)

    def render_with_update(segments, path, duration):
        render_calls.append(path)
        result = render(segments, path, duration)
        if update_at == "render" and not concurrent_plans:
            update_unrelated_fields()
        return result

    def publish_with_update(plan_service, shot_id, mutator, **kwargs):
        def after_check(latest):
            publication_attempts.append(deepcopy(latest))
            candidate = mutator(latest)
            if update_at == "publication" and not concurrent_plans:
                update_unrelated_fields()
            return candidate

        return original_mutate(plan_service, shot_id, after_check, **kwargs)

    monkeypatch.setattr(service, "_render_clip_audio", render_with_update)
    monkeypatch.setattr(VideoDirectorPlanService, "mutate", publish_with_update)
    result = service.build_clip_audio(shot.id, 1, force=True)
    assert result["success"], result
    assert len(render_calls) == 2  # Final and drive, never rerendered on a publication retry.
    assert len(publication_attempts) == (2 if update_at == "publication" else 1)
    db_session.refresh(shot)
    saved = json.loads(shot.video_director_plan)
    for key, value in concurrent_plans[0].items():
        if key != "window_plans":
            assert saved[key] == value
    for key in ("prompt_text", "keyframe_indexes", "image_url", "status", "ai_calls"):
        assert saved["window_plans"][0][key] == concurrent_plans[0][collection][0][key]
    assert saved["window_plans"][0]["final_audio_path"] != old_window["final_audio_path"]
    assert saved["window_plans"][0]["audio_status"] == "READY"
    assert load(old_window["final_audio_path"]) == old_snapshot
    assert shot.video_director_plan_revision == starting_revision + 2
    assert db_session.query(AudioEventTTSAsset).count() == 1
    assert db_session.query(Task).count() == 0
