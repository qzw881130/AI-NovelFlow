import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.task import Task
from app.models.workflow import Workflow
from app.repositories.shot_repository import ShotRepository
from app.services.shot_video_service import _save_generated_video, resolve_extend_previous_av
from app.services.comfyui.service import ComfyUIService


def _state(tmp_path):
    novel = Novel(id="extend-novel", title="Extend")
    chapter = Chapter(id="extend-chapter", novel_id=novel.id, number=1, title="Chapter")
    shot = Shot(
        id="extend-shot", chapter_id=chapter.id, index=1, duration=16,
        video_url="/api/files/shot-final.mp4",
        video_director_plan=json.dumps({
            "selected_mode": "MULTI_KEYFRAME",
            "clip_plan_revision": 4,
            "clip_plan": [
                {
                    "clip_index": 1,
                    "start_time": 0,
                    "end_time": 8,
                    "capability": "GENERATE",
                    "execution_status": "APPROVED",
                    "generated_by_task_id": "c1-task-a",
                    "video_url": "/api/files/c1-a.mp4",
                },
                {
                    "clip_index": 2,
                    "start_time": 8,
                    "end_time": 16,
                    "capability": "EXTEND",
                    "continuity_to_previous": "CONTINUOUS",
                    "requires_temporal_control": False,
                    "previous_clip_index": 1,
                },
            ],
        }),
    )
    artifact = tmp_path / "c1-a.mp4"
    artifact.write_bytes(b"approved clip")
    task = Task(
        id="c1-task-a", type="shot_video", status="completed",
        name="C1",
        novel_id=novel.id, chapter_id=chapter.id, shot_id=shot.id,
        result_url="/api/files/c1-a.mp4",
        metadata_json=json.dumps({
            "execution_scope": "CLIP",
            "clip_index": 1,
            "clip_plan_revision": 4,
            "approval_status": "APPROVED",
            "execution_contract": {"artifact_kind": "CLIP_ONLY", "capability": "GENERATE"},
        }),
    )
    return novel, chapter, shot, task, artifact


def test_extend_previous_av_requires_exact_approved_clip(db_session, tmp_path):
    novel, chapter, shot, task, artifact = _state(tmp_path)
    db_session.add_all([novel, chapter, shot, task])
    db_session.commit()
    clip = json.loads(shot.video_director_plan)["clip_plan"][1]
    provenance = {
        "clip_index": 1,
        "clip_plan_revision": 4,
        "generated_by_task_id": task.id,
        "result_url": task.result_url,
    }
    with patch("app.services.shot_video_service.url_to_local_path", return_value=str(artifact)):
        resolved = resolve_extend_previous_av(db_session, novel.id, chapter.id, shot, clip, provenance)
    assert resolved["generated_by_task_id"] == task.id
    assert resolved["result_url"] == task.result_url
    assert resolved["local_path"] == str(artifact)


@pytest.mark.parametrize("change", [
    {"result_url": "/api/files/other.mp4"},
    {"generated_by_task_id": "c1-task-b"},
])
def test_extend_previous_av_never_substitutes_latest_or_shot_video(db_session, tmp_path, change):
    novel, chapter, shot, task, artifact = _state(tmp_path)
    db_session.add_all([novel, chapter, shot, task])
    db_session.commit()
    clip = json.loads(shot.video_director_plan)["clip_plan"][1]
    provenance = {
        "clip_index": 1,
        "clip_plan_revision": 4,
        "generated_by_task_id": task.id,
        "result_url": task.result_url,
        **change,
    }
    with patch("app.services.shot_video_service.url_to_local_path", return_value=str(artifact)):
        with pytest.raises(ValueError, match="PREVIOUS_AV_UNAVAILABLE"):
            resolve_extend_previous_av(db_session, novel.id, chapter.id, shot, clip, provenance)


def test_extend_previous_snapshot_remains_task_a_after_task_b_exists(db_session, tmp_path):
    novel, chapter, shot, task_a, artifact = _state(tmp_path)
    task_b = Task(
        id="c1-task-b", type="shot_video", status="completed",
        name="C1 regenerated",
        novel_id=novel.id, chapter_id=chapter.id, shot_id=shot.id,
        result_url="/api/files/c1-b.mp4",
        metadata_json=json.dumps({
            "execution_scope": "CLIP", "clip_index": 1,
            "clip_plan_revision": 4, "approval_status": "APPROVED",
            "execution_contract": {"artifact_kind": "CLIP_ONLY", "capability": "GENERATE"},
        }),
    )
    db_session.add_all([novel, chapter, shot, task_a, task_b])
    db_session.commit()
    clip = json.loads(shot.video_director_plan)["clip_plan"][1]
    provenance = {
        "clip_index": 1, "clip_plan_revision": 4,
        "generated_by_task_id": task_a.id, "result_url": task_a.result_url,
    }
    with patch("app.services.shot_video_service.url_to_local_path", return_value=str(artifact)):
        resolved = resolve_extend_previous_av(db_session, novel.id, chapter.id, shot, clip, provenance)
    assert resolved["generated_by_task_id"] == task_a.id
    assert resolved["result_url"] == "/api/files/c1-a.mp4"


def test_extend_endpoint_snapshots_previous_contract_and_routes_physical_workflow(client, db_session, tmp_path):
    novel, chapter, shot, task, artifact = _state(tmp_path)
    workflow = Workflow(
        id="6dcdf466-69f1-41e5-9ccf-7a51b0c7de71",
        type="VIDEO_CONTINUATION", name="NovelFlow H3 AV 视频续生成 Minimal V1",
        workflow_json="{}",
        node_mapping=json.dumps({
            "load_video_node_id": "66", "duration_seconds_node_id": "105",
            "prompt_node_id": "107", "video_save_node_id": "65",
            "reference_to_video_node_id": "55",
            **{f"load_image_node_{i}": node for i, node in enumerate(("69", "68", "109", "110", "111", "112", "113", "114", "115"), 1)},
        }),
        is_active=True,
    )
    db_session.add_all([novel, chapter, shot, task, workflow])
    db_session.commit()
    captured = {}

    def enqueue(*args, **kwargs):
        captured["kwargs"] = kwargs

    with patch("app.api.shots.enqueue_shot_video_task", side_effect=enqueue), \
         patch("app.services.shot_video_service.url_to_local_path", return_value=str(artifact)):
        response = client.post(
            f"/api/novels/{novel.id}/chapters/{chapter.id}/shots/{shot.id}/video-director/clips/2/generate",
            json={"clip_plan_revision": 4, "auto_merge": False},
        )
    assert response.status_code == 200
    created = db_session.query(Task).filter(Task.shot_id == shot.id, Task.id != task.id).one()
    metadata = json.loads(created.metadata_json)
    assert created.workflow_id == workflow.id
    assert metadata["capability"] == "EXTEND"
    assert metadata["execution_contract"]["artifact_kind"] == "CLIP_ONLY"
    assert metadata["execution_contract"]["previous_clip"] == {
        "clip_index": 1,
        "clip_plan_revision": 4,
        "generated_by_task_id": task.id,
        "result_url": task.result_url,
    }
    assert captured["kwargs"]["selected_mode"] == "MULTI_KEYFRAME"


@pytest.mark.asyncio
async def test_extend_physical_adapter_binds_previous_duration_prompt_and_refs(db_session, monkeypatch):
    service = ComfyUIService()
    workflow = {
        "66": {"class_type": "VHS_LoadVideoFFmpeg", "inputs": {}},
        "105": {"class_type": "PrimitiveFloat", "inputs": {}},
        "107": {"class_type": "CR Prompt Text", "inputs": {}},
        "55": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {f"ref_images.ref_image_{i}": [node, 0] for i, node in enumerate(("69", "68", "109", "110", "111", "112", "113", "114", "115"))}},
        "65": {"class_type": "MiniMaxH3StreamLiveExtensionAVToVHS", "inputs": {}},
        **{node: {"class_type": "LoadImage", "inputs": {}} for node in ("69", "68", "109", "110", "111", "112", "113", "114", "115")},
    }
    workflow_json = json.dumps(workflow)
    mapping = {
        "load_video_node_id": "66", "duration_seconds_node_id": "105", "prompt_node_id": "107",
        "reference_to_video_node_id": "55", "video_save_node_id": "65",
        **{f"load_image_node_{i}": node for i, node in enumerate(("69", "68", "109", "110", "111", "112", "113", "114", "115"), 1)},
    }
    submitted = {}

    async def upload_video(path): return {"success": True, "filename": "previous-upload.mp4"}
    async def upload_image(path): return {"success": True, "filename": "ref.png"}
    async def queue_prompt(graph): submitted["graph"] = graph; return {"success": True, "prompt_id": "extend-prompt"}
    async def wait_for_result(*args, **kwargs): return {"success": True, "video_url": "raw-extension.mp4"}

    monkeypatch.setattr(service.client, "upload_video", upload_video)
    monkeypatch.setattr(service.client, "upload_image", upload_image)
    monkeypatch.setattr(service.client, "queue_prompt", queue_prompt)
    monkeypatch.setattr(service.client, "wait_for_result", wait_for_result)
    result = await service.generate_video_continuation_with_workflow(
        prompt="current Clip prompt", workflow_json=workflow_json, node_mapping=mapping,
        previous_video_path="/tmp/previous.mp4", duration_seconds=8.0,
        filename_prefix="probe/extend", capability="VIDEO_CONTINUATION",
        reference_image_paths=["/tmp/ref.png"],
    )
    assert result["success"] is True
    graph = submitted["graph"]
    assert graph["66"]["inputs"]["video"] == "previous-upload.mp4"
    assert graph["105"]["inputs"]["value"] == 8.0
    assert graph["107"]["inputs"]["prompt"] == "current Clip prompt"
    assert graph["69"]["inputs"]["image"] == "ref.png"


@pytest.mark.asyncio
async def test_extend_persists_raw_clip_and_preserves_shot_final(db_session, tmp_path, monkeypatch):
    novel = Novel(id="persist-novel", title="Persist")
    chapter = Chapter(id="persist-chapter", novel_id=novel.id, number=1, title="Chapter")
    shot = Shot(
        id="persist-shot", chapter_id=chapter.id, index=2, duration=16,
        video_url="/api/files/existing-final.mp4", video_status="completed",
        video_director_plan=json.dumps({
            "clip_plan_revision": 4,
            "clip_plan": [
                {"clip_index": 1, "execution_status": "APPROVED"},
                {"clip_index": 2, "capability": "EXTEND", "execution_status": "GENERATING"},
            ],
        }),
    )
    metadata = {
        "execution_scope": "CLIP", "clip_index": 2, "clip_plan_revision": 4,
        "capability": "EXTEND", "requested_duration": 8.0,
        "execution_contract": {"capability": "EXTEND", "artifact_kind": "CLIP_ONLY"},
    }
    task = Task(
        id="persist-extend-task", type="shot_video", status="running", name="C2 EXTEND",
        novel_id=novel.id, chapter_id=chapter.id, shot_id=shot.id, metadata_json=json.dumps(metadata),
    )
    db_session.add_all([novel, chapter, shot, task])
    db_session.commit()
    output = tmp_path / "story" / "chapter" / "videos" / "raw-extend.mp4"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"raw extension artifact")

    async def download_video(**kwargs):
        return str(output)

    monkeypatch.setattr("app.services.shot_video_service.file_storage.base_dir", tmp_path)
    monkeypatch.setattr("app.services.shot_video_service.file_storage.download_video", download_video)
    monkeypatch.setattr("app.services.shot_video_service._probe_video_duration", lambda path: 8.0)
    await _save_generated_video(
        {"success": True, "video_url": "http://comfy/raw-extension.mp4"},
        task, novel.id, chapter.id, shot.index, db_session, task.id, ShotRepository(db_session),
        clip_metadata=metadata, update_shot_result=False, artifact_suffix="clip_2_test",
    )

    db_session.refresh(task)
    db_session.refresh(shot)
    expected_url = "/api/files/story/chapter/videos/raw-extend.mp4"
    plan = json.loads(shot.video_director_plan)
    persisted = next(item for item in plan["clip_plan"] if item["clip_index"] == 2)
    task_metadata = json.loads(task.metadata_json)
    assert task.result_url == expected_url
    assert persisted["video_url"] == expected_url
    assert persisted["local_path"] == str(output)
    assert persisted["execution_status"] == "APPROVED"
    assert shot.video_url == "/api/files/existing-final.mp4"
    assert shot.video_status == "completed"
    assert task_metadata["actual_duration"] == 8.0
    assert "assembled_result" not in task_metadata


@pytest.mark.asyncio
async def test_extend_result_does_not_cross_clip_plan_revision(db_session, tmp_path, monkeypatch):
    novel = Novel(id="stale-novel", title="Stale")
    chapter = Chapter(id="stale-chapter", novel_id=novel.id, number=1, title="Chapter")
    shot = Shot(
        id="stale-shot", chapter_id=chapter.id, index=3, duration=16,
        video_url="/api/files/existing-final.mp4", video_status="completed",
        video_director_plan=json.dumps({
            "clip_plan_revision": 5,
            "clip_plan": [{"clip_index": 2, "capability": "EXTEND", "execution_status": "PLANNED"}],
        }),
    )
    metadata = {
        "execution_scope": "CLIP", "clip_index": 2, "clip_plan_revision": 4,
        "capability": "EXTEND", "execution_contract": {"capability": "EXTEND", "artifact_kind": "CLIP_ONLY"},
    }
    task = Task(
        id="stale-task", type="shot_video", status="running", name="Stale C2",
        novel_id=novel.id, chapter_id=chapter.id, shot_id=shot.id, metadata_json=json.dumps(metadata),
    )
    db_session.add_all([novel, chapter, shot, task])
    db_session.commit()
    output = tmp_path / "raw-stale.mp4"
    output.write_bytes(b"stale output")

    async def download_video(**kwargs): return str(output)

    monkeypatch.setattr("app.services.shot_video_service.file_storage.base_dir", tmp_path)
    monkeypatch.setattr("app.services.shot_video_service.file_storage.download_video", download_video)
    await _save_generated_video(
        {"success": True, "video_url": "http://comfy/stale.mp4"}, task, novel.id, chapter.id,
        shot.index, db_session, task.id, ShotRepository(db_session), clip_metadata=metadata, update_shot_result=False,
    )
    db_session.refresh(task)
    db_session.refresh(shot)
    current_clip = json.loads(shot.video_director_plan)["clip_plan"][0]
    assert task.status == "failed"
    assert task.result_url is None
    assert current_clip["execution_status"] == "PLANNED"
    assert "video_url" not in current_clip
    assert shot.video_url == "/api/files/existing-final.mp4"
    assert not output.exists()
