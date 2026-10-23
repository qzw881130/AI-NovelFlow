import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.shot import Shot
from app.models.task import Task
from app.services import shot_video_service
from app.services.file_storage import file_storage
from app.repositories.shot_repository import ShotRepository


@pytest.mark.asyncio
async def test_semantic_clip_assembly_requires_approved_current_revision(db_session, tmp_path, monkeypatch):
    shot = Shot(
        id="assembly-shot",
        chapter_id="chapter-1",
        index=1,
        video_url="/api/files/old.mp4",
        video_status="completed",
        video_director_plan=json.dumps({
            "clip_plan_revision": 2,
            "clip_plan": [
                {"clip_index": 1, "planned_duration": 8},
                {"clip_index": 2, "planned_duration": 8},
            ],
        }),
    )
    db_session.add(shot)
    first = tmp_path / "clip-1.mp4"
    first.write_bytes(b"clip-1")
    db_session.add(Task(
        id="task-1", type="shot_video", status="completed", name="Clip 1",
        shot_id=shot.id, result_url=f"/api/files/{first}",
        metadata_json=json.dumps({"clip_index": 1, "clip_plan_revision": 2, "approval_status": "APPROVED"}),
    ))
    db_session.commit()

    result = await shot_video_service.merge_video_director_clip_videos(
        db_session, shot, ShotRepository(db_session), "novel-1", "chapter-1", 1
    )

    assert result["success"] is False
    assert "C2" in result["message"]
    db_session.refresh(shot)
    assert shot.video_url == "/api/files/old.mp4"


@pytest.mark.asyncio
async def test_semantic_clip_assembly_updates_shot_only_after_merge(db_session, tmp_path, monkeypatch):
    shot = Shot(
        id="assembly-shot-success",
        chapter_id="chapter-1",
        index=2,
        video_url="/api/files/old.mp4",
        video_status="completed",
        video_director_plan=json.dumps({
            "clip_plan_revision": 3,
            "clip_plan": [{"clip_index": 1}, {"clip_index": 2}],
        }),
    )
    db_session.add(shot)
    paths = [tmp_path / "clip-1.mp4", tmp_path / "clip-2.mp4"]
    for path in paths:
        path.write_bytes(b"clip")
    for index, path in enumerate(paths, 1):
        db_session.add(Task(
            id=f"task-{index}", type="shot_video", status="completed", name=f"Clip {index}",
            shot_id=shot.id, result_url=f"/api/files/{path}",
            metadata_json=json.dumps({"clip_index": index, "clip_plan_revision": 3, "approval_status": "APPROVED"}),
        ))
    db_session.commit()

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    monkeypatch.setattr(file_storage, "_get_story_dir", lambda novel_id: output_dir)
    path_map = {f"/api/files/{path}": str(path) for path in paths}
    monkeypatch.setattr(shot_video_service, "url_to_local_path", lambda url: path_map.get(url))
    monkeypatch.setattr(shot_video_service, "_local_url_from_path", lambda path: f"/api/files/{path}")

    async def fake_merge(video_paths, output_path, transition_videos=None):
        Path(output_path).write_bytes(b"assembled")
        return {"success": True, "output_path": output_path}

    monkeypatch.setattr(file_storage, "merge_videos", fake_merge)
    result = await shot_video_service.merge_video_director_clip_videos(
        db_session, shot, ShotRepository(db_session), "novel-1", "chapter-1", 2
    )

    assert result["success"] is True
    db_session.refresh(shot)
    assert shot.video_url == result["video_url"]
    assert shot.video_url != "/api/files/old.mp4"
    assert result["video_url"].endswith(".mp4")


@pytest.mark.asyncio
async def test_semantic_assembly_collapses_base_and_mixed_continuation_chain(db_session, tmp_path, monkeypatch):
    shot = Shot(
        id="assembly-continuation-shot",
        chapter_id="chapter-chain",
        index=3,
        video_director_plan=json.dumps({
            "clip_plan_revision": 4,
            "clip_plan": [
                {"clip_index": 1},
                {"clip_index": 2},
                {"clip_index": 3},
            ],
        }),
    )
    db_session.add(shot)
    paths = [tmp_path / f"chain-{index}.mp4" for index in range(1, 4)]
    for path in paths:
        path.write_bytes(b"clip")
    capabilities = ["SINGLE_FRAME", "VIDEO_CONTINUATION", "TEMPORAL_EXTEND"]
    for index, (path, capability) in enumerate(zip(paths, capabilities), 1):
        db_session.add(Task(
            id=f"chain-task-{index}", type="shot_video", status="completed", name=f"Clip {index}",
            shot_id=shot.id, result_url=f"/api/files/{path}",
            metadata_json=json.dumps({
                "execution_scope": "CLIP", "clip_index": index, "clip_plan_revision": 4,
                "capability": capability, "approval_status": "APPROVED",
            }),
        ))
    db_session.commit()

    output_dir = tmp_path / "chain-output"
    output_dir.mkdir()
    monkeypatch.setattr(file_storage, "_get_story_dir", lambda novel_id: output_dir)
    monkeypatch.setattr(shot_video_service, "url_to_local_path", lambda url: str(url).removeprefix("/api/files/"))
    monkeypatch.setattr(shot_video_service, "_local_url_from_path", lambda path: f"/api/files/{path}")
    merge_inputs = []

    async def fake_merge(video_paths, output_path, transition_videos=None):
        merge_inputs.extend(video_paths)
        Path(output_path).write_bytes(b"assembled")
        return {"success": True, "output_path": output_path}

    monkeypatch.setattr(file_storage, "merge_videos", fake_merge)
    result = await shot_video_service.merge_video_director_clip_videos(
        db_session, shot, ShotRepository(db_session), "novel-chain", "chapter-chain", 3
    )

    assert result["success"] is True
    assert merge_inputs == []
    assert result["video_url"] == f"/api/files/{paths[2]}"
    assert result["plan"]["assembly_mode"] == "CONTINUATION_COLLAPSED"
    assert result["plan"]["assembled_result"]["clip_indexes"] == [3]
    db_session.refresh(shot)
    assert shot.video_url == result["video_url"]
