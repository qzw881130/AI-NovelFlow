import json
from pathlib import Path

import pytest

from app.models.novel import Novel, Chapter
from app.models.shot import Shot
from app.models.task import Task
from app.services import shot_video_service


def _assembly_fixture(db_session, tmp_path, monkeypatch, *, revision=1):
    novel = Novel(id="assembly-novel", title="Assembly")
    chapter = Chapter(id="assembly-chapter", novel_id=novel.id, number=1, title="Chapter")
    shot = Shot(id="assembly-shot", chapter_id=chapter.id, index=1, video_url="/api/files/shot.mp4")
    db_session.add_all([novel, chapter, shot])

    files = {}
    tasks = {}
    clips = []
    for index, capability in ((1, "GENERATE"), (2, "TEMPORAL_EXTEND"), (3, "EXTEND")):
        task_id = f"assembly-task-{index}"
        result_url = f"/api/files/c{index}.mp4"
        path = tmp_path / f"c{index}.mp4"
        path.write_bytes(f"clip-{index}".encode())
        files[result_url] = str(path)
        metadata = {
            "execution_scope": "CLIP",
            "clip_id": f"{shot.id}:clip:{index}",
            "clip_index": index,
            "clip_plan_revision": revision,
            "capability": capability,
            "approval_status": "APPROVED",
            "execution_contract": {
                "capability": capability,
                "artifact_kind": "CLIP_ONLY",
                "clip": {
                    "clip_id": f"{shot.id}:clip:{index}",
                    "clip_index": index,
                    "clip_plan_revision": revision,
                },
            },
        }
        task = Task(
            id=task_id,
            type="shot_video",
            status="completed",
            name=f"C{index}",
            novel_id=novel.id,
            chapter_id=chapter.id,
            shot_id=shot.id,
            result_url=result_url,
            metadata_json=json.dumps(metadata),
        )
        tasks[index] = task
        db_session.add(task)
        clips.append({
            "clip_index": index,
            "capability": capability,
            "generated_by_task_id": task_id,
            "video_url": result_url,
            "execution_status": "APPROVED",
        })

    shot.video_director_plan = json.dumps({"clip_plan_revision": revision, "clip_plan": clips})
    db_session.commit()
    monkeypatch.setattr(shot_video_service, "url_to_local_path", lambda url: files.get(url))
    return novel, chapter, shot, tasks, clips


def _resolve(db_session, shot, novel, chapter):
    plan = json.loads(shot.video_director_plan)
    return shot_video_service._resolve_semantic_clip_assembly_units(
        db_session, shot, plan["clip_plan"], plan["clip_plan_revision"], novel.id, chapter.id,
    )


def test_semantic_assembly_resolves_exact_three_clip_provenance_and_order(db_session, tmp_path, monkeypatch):
    novel, chapter, shot, tasks, clips = _assembly_fixture(db_session, tmp_path, monkeypatch)
    shot.video_director_plan = json.dumps({"clip_plan_revision": 1, "clip_plan": list(reversed(clips))})
    db_session.commit()

    units = _resolve(db_session, shot, novel, chapter)

    assert [task.id for _, task, _, _ in units] == [tasks[1].id, tasks[2].id, tasks[3].id]


@pytest.mark.parametrize("mutate, message", [
    (lambda clips: clips[0].pop("generated_by_task_id"), "冻结执行 provenance"),
    (lambda clips: clips[2].update(generated_by_task_id="assembly-task-2"), "重复使用 Task"),
    (lambda clips: clips[1].update(video_url="/api/files/wrong.mp4"), "provenance 与 semantic Clip 不匹配"),
])
def test_semantic_assembly_rejects_missing_duplicate_or_mismatched_sources(db_session, tmp_path, monkeypatch, mutate, message):
    novel, chapter, shot, _, clips = _assembly_fixture(db_session, tmp_path, monkeypatch)
    mutate(clips)
    shot.video_director_plan = json.dumps({"clip_plan_revision": 1, "clip_plan": clips})
    db_session.commit()

    with pytest.raises(ValueError, match=message):
        _resolve(db_session, shot, novel, chapter)


def test_temporal_extend_is_assembled_as_its_own_clip_only_artifact(db_session, tmp_path, monkeypatch):
    novel, chapter, shot, tasks, clips = _assembly_fixture(db_session, tmp_path, monkeypatch)

    units = _resolve(db_session, shot, novel, chapter)

    temporal = units[1]
    assert temporal[0]["capability"] == "TEMPORAL_EXTEND"
    assert temporal[1].id == tasks[2].id
    assert temporal[1].result_url == "/api/files/c2.mp4"


def test_semantic_assembly_excludes_shot_video_url(db_session, tmp_path, monkeypatch):
    novel, chapter, shot, tasks, _ = _assembly_fixture(db_session, tmp_path, monkeypatch)
    units = _resolve(db_session, shot, novel, chapter)

    assert shot.video_url == "/api/files/shot.mp4"
    assert [task.id for _, task, _, _ in units] == [tasks[1].id, tasks[2].id, tasks[3].id]


def test_semantic_assembly_is_revision_isolated(db_session, tmp_path, monkeypatch):
    novel, chapter, shot, _, clips = _assembly_fixture(db_session, tmp_path, monkeypatch, revision=1)
    shot.video_director_plan = json.dumps({"clip_plan_revision": 2, "clip_plan": clips})
    db_session.commit()

    with pytest.raises(ValueError, match="provenance 与 semantic Clip 不匹配"):
        _resolve(db_session, shot, novel, chapter)


def test_semantic_assembly_rejects_wrong_task_identity(db_session, tmp_path, monkeypatch):
    novel, chapter, shot, tasks, clips = _assembly_fixture(db_session, tmp_path, monkeypatch)
    tasks[2].novel_id = "other-novel"
    db_session.commit()

    with pytest.raises(ValueError, match="provenance 与 semantic Clip 不匹配"):
        _resolve(db_session, shot, novel, chapter)


@pytest.mark.asyncio
async def test_semantic_assembly_merges_exact_order_and_persists_provenance(
    db_session, tmp_path, monkeypatch,
):
    novel, chapter, shot, tasks, clips = _assembly_fixture(db_session, tmp_path, monkeypatch)
    shot.video_director_plan = json.dumps({"clip_plan_revision": 1, "clip_plan": list(reversed(clips))})
    db_session.commit()
    observed = {}

    monkeypatch.setattr(shot_video_service.file_storage, "_get_story_dir", lambda _: tmp_path)

    async def merge(paths, output_path):
        observed["paths"] = list(paths)
        observed["output_path"] = output_path
        Path(output_path).write_bytes(b"assembled")
        return {"success": True}

    monkeypatch.setattr(shot_video_service.file_storage, "merge_videos", merge)
    monkeypatch.setattr(shot_video_service, "_probe_video_duration", lambda _: 25.416667)
    monkeypatch.setattr(shot_video_service, "_local_url_from_path", lambda _: "/api/files/assembled.mp4")

    class Repo:
        def update(self, target, **fields):
            for key, value in fields.items():
                if key == "video_director_plan" and isinstance(value, dict):
                    value = json.dumps(value)
                setattr(target, key, value)
            return target

    result = await shot_video_service.merge_video_director_clip_videos(
        db_session, shot, Repo(), novel.id, chapter.id, shot.index,
    )

    assert result["success"] is True
    assert observed["paths"] == [str(tmp_path / f"c{i}.mp4") for i in (1, 2, 3)]
    persisted = json.loads(shot.video_director_plan)
    assert persisted["assembly_task_ids"] == [tasks[i].id for i in (1, 2, 3)]
    assert persisted["assembly_status"] == "COMPLETED"
    assert shot.video_url == "/api/files/assembled.mp4"
