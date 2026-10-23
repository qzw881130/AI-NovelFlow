"""Display readiness must not grant physical execution authority."""
import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.task import Task
from app.repositories.shot_repository import ShotRepository
from app.services import continuous_clip_av as av, shot_video_service as video
from app.services.required_visual_state_images import project_clip_execution_readiness


@pytest.fixture
def approved_chain(db_session, tmp_path, monkeypatch):
    # Real local fixture media; strict resolver/probe/acceptance are not mocked.
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe required for physical authority boundary")
    paths = {}
    for index, frames in [(1, 48), (2, 72)]:
        path = tmp_path / f"c{index}.mp4"
        subprocess.run([
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=s=32x32:r=24",
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
            "-t", str(frames / 24), "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", str(path),
        ], check=True, capture_output=True)
        paths[f"/api/files/c{index}.mp4"] = path
    image = tmp_path / "state.png"
    image.write_bytes(b"image fixture")
    for module in (video, __import__("app.services.required_visual_state_images", fromlist=["_"])):
        monkeypatch.setattr(module, "url_to_local_path", lambda url: str(paths[url]) if url in paths else url)

    novel = Novel(id="read-novel", title="Read")
    chapter = Chapter(id="read-chapter", novel_id=novel.id, number=1, title="Read")
    shot = Shot(id="read-shot", chapter_id=chapter.id, index=1, duration=6, image_url=str(image))
    clips = []
    tasks = []
    previous = None
    for index, capability in [(1, "GENERATE"), (2, "EXTEND")]:
        identity = {"clip_id": f"{shot.id}:clip:{index}", "clip_index": index, "clip_plan_revision": 1}
        url = f"/api/files/c{index}.mp4"
        contract = {"capability": capability, "artifact_kind": "CLIP_ONLY" if index == 1 else av.NATIVE_CONTINUITY_OUTPUT,
                    "clip": identity}
        if index == 2:
            contract["previous_clip"] = previous
        metadata = {"execution_scope": "CLIP", **identity, "approval_status": "APPROVED", "execution_contract": contract}
        clip = {**identity, "capability": capability, "execution_status": "APPROVED", "video_url": url,
                "generated_by_task_id": f"read-c{index}", "start_time": index - 1, "end_time": index + 1,
                "visual_state_indexes": [1] if index == 1 else [], "previous_clip_index": index - 1 if index > 1 else None}
        if index == 2:
            output = av.continuity_output_metadata(
                {"physical_output_role": av.NATIVE_CONTINUITY_OUTPUT, "output_node_id": "65", "video_url": url},
                contract, str(paths[url]), url,
            )
            metadata["physical_output"] = output
            clip["physical_output"] = copy.deepcopy(output)
        physical = {**av.probe_clip_av(str(paths[url])), "physical_output_role": contract["artifact_kind"]}
        previous = {"clip_index": index, "clip_plan_revision": 1, "generated_by_task_id": clip["generated_by_task_id"],
                    "result_url": url, "physical_output": physical, "source_frame_start": 0}
        tasks.append(Task(id=clip["generated_by_task_id"], type="shot_video", status="completed", name=f"C{index}",
                          novel_id=novel.id, chapter_id=chapter.id, shot_id=shot.id,
                          result_url=url, metadata_json=json.dumps(metadata)))
        clips.append(clip)
    clips.append({"clip_index": 3, "capability": "EXTEND", "previous_clip_index": 2, "execution_status": "PLANNED",
                  "continuity_to_previous": "CONTINUOUS", "visual_state_indexes": [], "start_time": 3, "end_time": 6})
    plan = {"canonical_visual_plan": True, "clip_plan_revision": 1, "clip_plan": clips,
            "clip_plan_validation": {"passed": True, "temporal_contract": "ELIGIBLE_THEN_SELECTED_V1",
                                     "composition_contract": "EARLY_COMPOSITION_V2"},
            "keyframes": [{"index": 1, "role": "START", "time_seconds": 0, "description": "start"}]}
    shot.video_director_plan = json.dumps(plan)
    db_session.add_all([novel, chapter, shot, *tasks])
    db_session.commit()
    return novel, chapter, shot, plan, tasks, paths


def forbid_expensive_read(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Ordinary read invoked execution resolver or media scan")
    monkeypatch.setattr(video, "resolve_extend_previous_av", forbidden)
    monkeypatch.setattr(video, "probe_clip_av", forbidden)
    monkeypatch.setattr(video, "validate_native_output", forbidden)
    monkeypatch.setattr(av, "probe_clip_av", forbidden)
    monkeypatch.setattr(av, "validate_native_output", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)


@pytest.mark.parametrize("endpoint", ["detail", "chapter"])
def test_get_preserves_response_and_never_scans_media(client, db_session, approved_chain, monkeypatch, endpoint):
    novel, chapter, shot, plan, tasks, paths = approved_chain
    original = shot.video_director_plan
    forbid_expensive_read(monkeypatch)
    path = f"/api/novels/{novel.id}/chapters/{chapter.id}/shots"
    if endpoint == "detail":
        path += f"/{shot.id}"
    for _ in range(2):
        response = client.get(path)
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        if endpoint == "chapter":
            assert len(data) == 1
            data = data[0]
        assert data["id"] == shot.id
        projected = data["videoDirectorPlan"]
        assert projected["clip_plan"] == plan["clip_plan"]
        assert projected["clip_execution_readiness"] == [
            {"clip_index": i, "images_ready": True, "ready": True, "code": "READY", "previous_clip_index": i-1 if i > 1 else None}
            for i in range(1, 4)
        ]
        assert projected["required_execution_images"][0]["ready"]
    assert shot.video_director_plan == original


@pytest.mark.parametrize("damage", ["missing_task", "failed", "unapproved", "revision", "wrong_shot", "wrong_url",
                                    "missing_file", "missing_physical", "physical_mismatch", "raw_output", "output_bound"])
def test_read_rejects_known_stale_or_missing_dependencies(db_session, approved_chain, monkeypatch, damage):
    _, _, shot, plan, tasks, paths = approved_chain
    task = tasks[1]
    meta = json.loads(task.metadata_json)
    if damage == "missing_task":
        plan["clip_plan"][1]["generated_by_task_id"] = "absent"
    elif damage == "failed":
        task.status = "failed"
    elif damage == "unapproved":
        meta["approval_status"] = "FAILED"
    elif damage == "revision":
        meta["clip_plan_revision"] = 0
    elif damage == "wrong_shot":
        task.shot_id = "other"
    elif damage == "wrong_url":
        task.result_url = "/api/files/other.mp4"
    elif damage == "missing_file":
        paths[task.result_url].unlink()
    elif damage == "missing_physical":
        meta.pop("physical_output")
    elif damage == "physical_mismatch":
        meta["physical_output"]["sha256"] = "different"
    elif damage == "raw_output":
        meta["physical_output"]["physical_output_role"] = "RAW_CONTEXT_OUTPUT"
        plan["clip_plan"][1]["physical_output"] = copy.deepcopy(meta["physical_output"])
    elif damage == "output_bound":
        meta["execution_contract"]["temporal_anchor_manifest"] = {"anchors": [{"frame_position": 999}]}
    task.metadata_json = json.dumps(meta)
    shot.video_director_plan = json.dumps(plan)
    db_session.commit()
    forbid_expensive_read(monkeypatch)
    result = project_clip_execution_readiness(db_session, shot, plan, [])[-1]
    assert result == {"clip_index": 3, "images_ready": True, "ready": False, "code": "WAITING_PREVIOUS_AV", "previous_clip_index": 2}


@pytest.mark.parametrize("capability", ["EXTEND", "TEMPORAL_EXTEND"])
def test_cheap_read_cannot_authorize_changed_bytes_for_execution(client, db_session, approved_chain, monkeypatch, capability):
    novel, chapter, shot, plan, tasks, paths = approved_chain
    clip = plan["clip_plan"][2]
    clip["capability"] = capability
    if capability == "TEMPORAL_EXTEND":
        clip.update(requires_temporal_control=True, temporal_anchor_ids=["clip-3-KF2"], selected_temporal_target_ids=["KF2"])
        plan["keyframes"].append({"index": 2, "role": "INTERMEDIATE", "time_seconds": 4, "description": "target"})
        plan["temporal_anchors"] = [{"anchor_id": "clip-3-KF2", "time_seconds": 1, "image_url": shot.image_url,
                                     "source": {"type": "KEYFRAME", "id": "KF2", "keyframe_index": 2}}]
    shot.video_director_plan = json.dumps(plan)
    db_session.commit()
    # Change bytes while retaining valid decodable media, so SHA is the decisive check.
    path = paths[tasks[1].result_url]
    path.write_bytes(path.read_bytes() + b"tampered after acceptance")
    assert project_clip_execution_readiness(db_session, shot, plan, [])[-1]["ready"] is True
    provenance = {"clip_index": 2, "clip_plan_revision": 1, "generated_by_task_id": tasks[1].id, "result_url": tasks[1].result_url}
    with pytest.raises(ValueError, match="NATIVE_CONTINUITY_OUTPUT_INVALID"):
        video.resolve_extend_previous_av(db_session, novel.id, chapter.id, shot, {**clip, "clip_plan_revision": 1}, provenance)
    queued = []
    monkeypatch.setattr("app.api.shots.enqueue_shot_video_task", lambda *args, **kwargs: queued.append(args))
    response = client.post(f"/api/novels/{novel.id}/chapters/{chapter.id}/shots/{shot.id}/video-director/clips/3/generate",
                           json={"clip_plan_revision": 1, "auto_merge": False})
    assert response.status_code == 400, response.text
    assert "NATIVE_CONTINUITY_OUTPUT_INVALID" in response.text
    assert not queued and db_session.query(Task).count() == 2


def test_bootstrap_bytes_still_probed_at_execution(db_session, approved_chain):
    novel, chapter, shot, plan, tasks, paths = approved_chain
    paths[tasks[0].result_url].write_bytes(b"invalid mp4")
    assert project_clip_execution_readiness(db_session, shot, plan, [])[1]["ready"]
    with pytest.raises(ValueError, match="CLIP_AV_UNREADABLE"):
        video.resolve_extend_previous_av(db_session, novel.id, chapter.id, shot,
            {**plan["clip_plan"][1], "clip_plan_revision": 1},
            {"clip_index": 1, "clip_plan_revision": 1, "generated_by_task_id": tasks[0].id, "result_url": tasks[0].result_url})


def test_approved_artifact_revalidation_remains_strict(db_session, approved_chain):
    novel, chapter, shot, plan, tasks, paths = approved_chain
    paths[tasks[1].result_url].write_bytes(paths[tasks[1].result_url].read_bytes() + b"changed")
    assert ShotRepository(db_session).to_response(shot)["videoDirectorPlan"]["clip_execution_readiness"][-1]["ready"]
    with pytest.raises(ValueError, match="NATIVE_CONTINUITY_OUTPUT_INVALID"):
        video.validate_semantic_clip_artifact(db_session, shot, plan["clip_plan"][1], 1, novel.id, chapter.id)
