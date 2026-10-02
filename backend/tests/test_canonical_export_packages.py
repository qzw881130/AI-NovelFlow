import json
import tempfile
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from app.models.novel import Chapter, Character, Novel
from app.models.shot import Shot
from app.models.task import Task


def _configure_storage(monkeypatch, tmp_path, novel_id):
    from app.api import shots as shots_api
    from app.services import canonical_export, shot_video_service

    story_root = tmp_path / f"story_{novel_id[:8]}"
    story_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(canonical_export.file_storage, "base_dir", tmp_path)
    mappings = {}

    def make(name, content=b"asset"):
        path = story_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        url = f"/api/files/{name}"
        mappings[url] = str(path)
        return url, path

    make.mappings = mappings

    resolver = lambda value: mappings.get(value)
    monkeypatch.setattr(canonical_export, "url_to_local_path", resolver)
    monkeypatch.setattr(shot_video_service, "url_to_local_path", resolver)
    monkeypatch.setattr(shots_api, "url_to_local_path", resolver)
    return make, story_root


def _base_records(db_session, title="Canonical export"):
    novel = Novel(title=title)
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=3, title="第三章", content="正文")
    db_session.add(chapter)
    db_session.flush()
    return novel, chapter


def _clip_task(db_session, novel, chapter, shot, clip_index, revision, result_url, **overrides):
    artifact_kind = overrides.pop("artifact_kind", "CLIP_ONLY")
    approval = overrides.pop("approval_status", "APPROVED")
    contract_clip_index = overrides.pop("contract_clip_index", clip_index)
    capability = overrides.pop("capability", "GENERATE")
    contract = {
        "version": 1,
        "artifact_kind": artifact_kind,
        "capability": capability,
        "clip": {
            "clip_id": f"{shot.id}:clip:{contract_clip_index}",
            "clip_index": contract_clip_index,
            "clip_plan_revision": revision,
        },
    }
    contract.update(overrides.pop("contract_extra", {}))
    metadata = {
        "execution_scope": "CLIP",
        "clip_id": f"{shot.id}:clip:{clip_index}",
        "clip_index": clip_index,
        "clip_plan_revision": revision,
        "approval_status": approval,
        "capability": capability,
        "execution_contract": contract,
        "video_reference_manifest": overrides.pop("reference_manifest", {"version": 1, "references": []}),
    }
    metadata.update(overrides.pop("metadata_extra", {}))
    task = Task(
        type="shot_video",
        status=overrides.pop("status", "completed"),
        name=f"C{clip_index}",
        novel_id=novel.id,
        chapter_id=chapter.id,
        shot_id=shot.id,
        result_url=result_url,
        prompt_text=f"prompt C{clip_index}",
        workflow_json=json.dumps({"clip": clip_index, "revision": revision}),
        metadata_json=json.dumps(metadata),
    )
    db_session.add(task)
    db_session.flush()
    return task


def _canonical_clip(shot, task, clip_index, revision, **extra):
    clip = {
        "clip_index": clip_index,
        "start_time": float(clip_index - 1),
        "end_time": float(clip_index),
        "duration": 1.0,
        "continuity_to_previous": "NONE" if clip_index == 1 else "CONTINUOUS",
        "capability": "GENERATE",
        "visual_state_indexes": [clip_index],
        "carry_in_state_index": None,
        "dialogue_assignment": [],
        "generated_by_task_id": task.id,
        "video_url": task.result_url,
        "execution_status": "APPROVED",
        "clip_plan_revision": revision,
    }
    clip.update(extra)
    return clip


def _read_archive(response):
    assert response.status_code == 200, response.text
    archive = ZipFile(BytesIO(response.content))
    return archive, json.loads(archive.read("manifest.json"))


def test_shot_package_exports_arbitrary_n_exact_clip_and_recorded_picture_slots(client, db_session, monkeypatch, tmp_path):
    novel, chapter = _base_records(db_session)
    make, _ = _configure_storage(monkeypatch, tmp_path, novel.id)
    primary_url, _ = make("primary.png")
    state5_url, _ = make("state5.png")
    clip_url, _ = make("clip-current.mp4")
    final_url, _ = make("final-current.mp4")
    shot = Shot(chapter_id=chapter.id, index=1, duration=10, image_url=primary_url, video_director_plan="{}")
    db_session.add(shot)
    db_session.flush()
    references = {
        "version": 1,
        "references": [
            {"slot": 1, "kind": "DIRECTOR_VISUAL_ANCHOR", "source_type": "SHOT_IMAGE", "image_url": primary_url, "source_keyframe_index": 1, "binding": {"workflow_node_id": "12", "uploaded_filename": "start.png"}},
            {"slot": 2, "kind": "DIRECTOR_VISUAL_ANCHOR", "source_type": "KEYFRAME_IMAGE", "image_url": state5_url, "source_keyframe_index": 5, "binding": {"workflow_node_id": "13", "uploaded_filename": "end.png"}},
        ],
    }
    task = _clip_task(db_session, novel, chapter, shot, 1, 4, clip_url, reference_manifest=references)
    decoy_url, _ = make("clip-decoy.mp4")
    _clip_task(db_session, novel, chapter, shot, 1, 4, decoy_url)
    clip = _canonical_clip(shot, task, 1, 4, visual_state_indexes=[1, 5])
    states = [
        {"index": index, "time_seconds": index - 1, "role": "START" if index == 1 else "END" if index == 5 else "INTERMEDIATE", "timed_visual_target": False, "image_url": state5_url if index == 5 else None}
        for index in range(1, 6)
    ]
    shot.video_url = final_url
    shot.video_director_plan = json.dumps({
        "canonical_visual_plan": True,
        "keyframes": states,
        "transitions": [{"from_state_index": 1, "to_state_index": 2}],
        "clip_plan_revision": 4,
        "clip_plan_validation": {"passed": True},
        "clip_plan": [clip],
        "assembly_status": "COMPLETED",
        "assembly_clip_plan_revision": 4,
        "assembly_task_ids": [task.id],
        "merged_video_url": final_url,
        "assembled_result": {"status": "COMPLETED", "url": final_url, "clip_plan_revision": 4, "task_ids": [task.id]},
    })
    db_session.commit()

    response = client.get(f"/api/novels/{novel.id}/chapters/{chapter.id}/shots/{shot.id}/download-video-materials")
    archive, manifest = _read_archive(response)
    names = set(archive.namelist())
    execution = manifest["execution"]["clips"][0]

    assert response.headers["content-disposition"].endswith('filename="shot_001_production.zip"')
    assert manifest["package_type"] == "SHOT_PRODUCTION"
    assert len(manifest["canonical_plan"]["visual_states"]) == 5
    assert manifest["canonical_plan"]["visual_states"][2]["image"]["status"] == "OPTIONAL_MISSING"
    assert execution["artifact"]["generated_by_task_id"] == task.id
    assert execution["artifact"]["artifact_kind"] == "CLIP_ONLY"
    assert [item["physical_slot"] for item in execution["ordinary_references"]["references"]] == [1, 2]
    assert [item["source_keyframe_index"] for item in execution["ordinary_references"]["references"]] == [1, 5]
    assert execution["ordinary_references"]["references"][1]["picture_label"] == "<Picture 2>"
    assert manifest["final_assembly"]["status"] == "CURRENT"
    assert str(tmp_path) not in json.dumps(manifest)
    assert not any("decoy" in name for name in names)
    assert not any("hd" in name.lower() for name in names)


@pytest.mark.parametrize(
    "task_changes,clip_changes",
    [
        ({"revision": 3}, {}),
        ({"contract_clip_index": 2}, {}),
        ({"artifact_kind": "ASSEMBLED"}, {}),
        ({"approval_status": "REVIEW_REQUIRED"}, {}),
        ({}, {"video_url": "/api/files/different.mp4"}),
    ],
)
def test_shot_package_rejects_noncurrent_exact_artifact_without_latest_fallback(
    client, db_session, monkeypatch, tmp_path, task_changes, clip_changes,
):
    novel, chapter = _base_records(db_session)
    make, _ = _configure_storage(monkeypatch, tmp_path, novel.id)
    primary_url, _ = make("primary.png")
    exact_url, _ = make("exact.mp4")
    decoy_url, _ = make("decoy.mp4")
    shot = Shot(chapter_id=chapter.id, index=2, duration=4, image_url=primary_url, video_director_plan="{}")
    db_session.add(shot)
    db_session.flush()
    task_revision = task_changes.pop("revision", 4)
    exact = _clip_task(db_session, novel, chapter, shot, 1, task_revision, exact_url, **task_changes)
    decoy = _clip_task(db_session, novel, chapter, shot, 1, 4, decoy_url)
    clip = _canonical_clip(shot, exact, 1, 4)
    clip.update(clip_changes)
    shot.video_director_plan = json.dumps({
        "canonical_visual_plan": True,
        "keyframes": [{"index": 1, "role": "START", "time_seconds": 0, "timed_visual_target": False}],
        "clip_plan_revision": 4,
        "clip_plan_validation": {"passed": True},
        "clip_plan": [clip],
    })
    db_session.commit()

    response = client.get(f"/api/novels/{novel.id}/chapters/{chapter.id}/shots/{shot.id}/download-video-materials")
    archive, manifest = _read_archive(response)
    execution = manifest["execution"]["clips"][0]

    assert execution["artifact"]["status"] == "CURRENT_ARTIFACT_UNAVAILABLE"
    assert execution["generated_by_task_id"] == exact.id
    assert decoy.id not in json.dumps(manifest)
    assert not any(name.endswith("artifact.mp4") for name in archive.namelist())


def test_shot_package_keeps_temporal_anchors_separate_and_validates_previous_av(client, db_session, monkeypatch, tmp_path):
    novel, chapter = _base_records(db_session)
    make, _ = _configure_storage(monkeypatch, tmp_path, novel.id)
    primary_url, _ = make("primary.png")
    c1_url, _ = make("c1.mp4")
    c2_url, _ = make("c2.mp4")
    anchor_url, _ = make("anchor.png")
    shot = Shot(chapter_id=chapter.id, index=3, duration=8, image_url=primary_url, video_director_plan="{}")
    db_session.add(shot)
    db_session.flush()
    c1_task = _clip_task(db_session, novel, chapter, shot, 1, 2, c1_url)
    previous = {"clip_index": 1, "clip_plan_revision": 2, "generated_by_task_id": c1_task.id, "result_url": c1_url}
    temporal = {"manifest_version": "1.0", "anchors": [{"slot": 1, "anchor_id": "TA-1", "time_seconds": 1.5, "frame_position": 17, "image_url": anchor_url, "source": {"id": "KF4", "keyframe_index": 4}, "binding": {"workflow_node_id": "88", "uploaded_filename": "anchor.png"}}]}
    c2_task = _clip_task(
        db_session, novel, chapter, shot, 2, 2, c2_url,
        capability="TEMPORAL_EXTEND",
        contract_extra={"previous_clip": previous, "temporal_anchor_manifest": temporal},
    )
    c1 = _canonical_clip(shot, c1_task, 1, 2)
    c2 = _canonical_clip(
        shot, c2_task, 2, 2,
        capability="TEMPORAL_EXTEND", previous_clip_index=1,
        carry_in_state_index=2, visual_state_indexes=[3, 4],
        requires_temporal_control=True, temporal_anchor_ids=["TA-1"],
    )
    shot.video_director_plan = json.dumps({
        "canonical_visual_plan": True,
        "keyframes": [{"index": index, "role": "START" if index == 1 else "INTERMEDIATE", "time_seconds": index, "timed_visual_target": index == 4, "image_url": anchor_url if index == 4 else None} for index in range(1, 5)],
        "clip_plan_revision": 2,
        "clip_plan_validation": {"passed": True},
        "clip_plan": [c1, c2],
    })
    db_session.commit()

    response = client.get(f"/api/novels/{novel.id}/chapters/{chapter.id}/shots/{shot.id}/download-video-materials")
    _, manifest = _read_archive(response)
    second = manifest["execution"]["clips"][1]

    assert second["artifact"]["status"] == "CURRENT"
    assert second["previous_av"]["generated_by_task_id"] == c1_task.id
    assert second["previous_av"]["package_artifact_path"] == "execution/clips/C001/artifact.mp4"
    assert second["temporal_anchors"]["anchors"][0]["source"]["keyframe_index"] == 4
    assert second["ordinary_references"]["references"] == []
    assert second["carry_in_state_index"] == 2


def test_shot_package_invalid_previous_av_and_stale_final_are_not_exported(client, db_session, monkeypatch, tmp_path):
    novel, chapter = _base_records(db_session)
    make, _ = _configure_storage(monkeypatch, tmp_path, novel.id)
    primary_url, _ = make("primary.png")
    c1_url, _ = make("c1.mp4")
    c2_url, _ = make("c2.mp4")
    stale_url, _ = make("stale-final.mp4")
    shot = Shot(chapter_id=chapter.id, index=4, duration=8, image_url=primary_url, video_url=stale_url, video_director_plan="{}")
    db_session.add(shot)
    db_session.flush()
    c1_task = _clip_task(db_session, novel, chapter, shot, 1, 2, c1_url)
    invalid_previous = {"clip_index": 1, "clip_plan_revision": 2, "generated_by_task_id": "wrong-task", "result_url": c1_url}
    c2_task = _clip_task(db_session, novel, chapter, shot, 2, 2, c2_url, capability="EXTEND", contract_extra={"previous_clip": invalid_previous})
    c1 = _canonical_clip(shot, c1_task, 1, 2)
    c2 = _canonical_clip(shot, c2_task, 2, 2, capability="EXTEND", previous_clip_index=1)
    shot.video_director_plan = json.dumps({
        "canonical_visual_plan": True,
        "keyframes": [{"index": 1, "role": "START", "time_seconds": 0, "timed_visual_target": False}],
        "clip_plan_revision": 2,
        "clip_plan_validation": {"passed": True},
        "clip_plan": [c1, c2],
        "assembly_status": "COMPLETED",
        "assembly_clip_plan_revision": 2,
        "assembly_task_ids": [c1_task.id, c2_task.id],
        "merged_video_url": stale_url,
        "assembled_result": {"status": "COMPLETED", "url": stale_url, "clip_plan_revision": 2, "task_ids": [c1_task.id, c2_task.id]},
    })
    db_session.commit()

    response = client.get(f"/api/novels/{novel.id}/chapters/{chapter.id}/shots/{shot.id}/download-video-materials")
    archive, manifest = _read_archive(response)

    assert manifest["execution"]["clips"][1]["artifact"]["reason"] == "PREVIOUS_AV_PROVENANCE_INVALID"
    assert manifest["final_assembly"]["status"] == "STALE_NOT_EXPORTED"
    assert not any(name.startswith("final/") for name in archive.namelist())


def test_shot_package_rejects_outside_root_and_symlink_escape_but_succeeds_manifest_only(client, db_session, monkeypatch, tmp_path):
    novel, chapter = _base_records(db_session)
    make, story_root = _configure_storage(monkeypatch, tmp_path, novel.id)
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")
    symlink = story_root / "escape.png"
    symlink.symlink_to(outside)
    from app.services import canonical_export
    monkeypatch.setattr(canonical_export, "url_to_local_path", lambda value: str(symlink) if value == "/api/files/escape.png" else str(outside) if value == "/api/files/outside.png" else None)
    shot = Shot(
        chapter_id=chapter.id, index=5, duration=4, image_url="/api/files/outside.png",
        video_director_plan=json.dumps({
            "canonical_visual_plan": True,
            "keyframes": [{"index": 1, "role": "START", "time_seconds": 0, "timed_visual_target": False, "image_url": "/api/files/escape.png"}],
            "clip_plan_revision": 1,
            "clip_plan_validation": {"passed": True},
            "clip_plan": [],
        }),
    )
    db_session.add(shot)
    db_session.commit()

    response = client.get(f"/api/novels/{novel.id}/chapters/{chapter.id}/shots/{shot.id}/download-video-materials")
    archive, manifest = _read_archive(response)

    assert set(archive.namelist()) == {"manifest.json"}
    assert manifest["shot"]["primary_image"]["path"] is None
    assert manifest["canonical_plan"]["visual_states"][0]["image"]["status"] == "OPTIONAL_MISSING"
    assert any(item["code"] == "OUTSIDE_STORAGE_ROOT" for item in manifest["warnings"])


def test_chapter_archive_is_canonical_scoped_and_temporary(client, db_session, monkeypatch, tmp_path):
    from app.api import shots as shots_api

    novel, chapter = _base_records(db_session)
    make, story_root = _configure_storage(monkeypatch, tmp_path / "storage", novel.id)
    bound_url, _ = make("characters/bound.png")
    unbound_url, _ = make("characters/unbound.png")
    primary_url, _ = make("shots/primary.png")
    clip_url, _ = make("videos/clip.mp4")
    final_url, _ = make("videos/final.mp4")
    stale_url, _ = make("videos/stale.mp4")
    (story_root / "raw-secret.txt").write_text("raw")
    hd_path = story_root / "chapter_hd" / "hd-videos" / "shot.mp4"
    hd_path.parent.mkdir(parents=True)
    hd_path.write_bytes(b"hd")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")
    escape = story_root / "escape.png"
    escape.symlink_to(outside)
    make.mappings["/api/files/escape.png"] = str(escape)
    bound = Character(novel_id=novel.id, name="皇帝", image_url=bound_url)
    unbound = Character(novel_id=novel.id, name="旁人", image_url=unbound_url)
    db_session.add_all([bound, unbound])
    chapter.parsed_data = json.dumps({"characters": ["皇帝"], "scenes": [], "props": []})

    completed = Shot(chapter_id=chapter.id, index=1, duration=4, image_url=primary_url, characters=json.dumps(["皇帝"]), video_director_plan="{}")
    incomplete = Shot(chapter_id=chapter.id, index=2, duration=4, video_url=stale_url, video_director_plan="{}")
    historical = Shot(chapter_id=chapter.id, index=3, duration=4, video_url=stale_url, video_director_plan=json.dumps({"selected_mode": "FIRST_LAST_FRAME", "window_plans": []}))
    missing = Shot(chapter_id=chapter.id, index=4, duration=4, image_url="/api/files/escape.png", video_director_plan="{}")
    db_session.add_all([completed, incomplete, historical, missing])
    db_session.flush()
    task = _clip_task(db_session, novel, chapter, completed, 1, 1, clip_url)
    clip = _canonical_clip(completed, task, 1, 1)
    completed.video_url = final_url
    completed.video_director_plan = json.dumps({
        "canonical_visual_plan": True,
        "keyframes": [{"index": 1, "role": "START", "time_seconds": 0, "timed_visual_target": False}],
        "transitions": [],
        "clip_plan_revision": 1,
        "clip_plan_validation": {"passed": True},
        "clip_plan": [clip],
        "assembly_status": "COMPLETED",
        "assembly_clip_plan_revision": 1,
        "assembly_task_ids": [task.id],
        "merged_video_url": final_url,
        "assembled_result": {"status": "COMPLETED", "url": final_url, "clip_plan_revision": 1, "task_ids": [task.id]},
    })
    incomplete.video_director_plan = json.dumps({
        "canonical_visual_plan": True,
        "keyframes": [{"index": 1, "role": "START", "time_seconds": 0, "timed_visual_target": False}],
        "clip_plan_revision": 2,
        "clip_plan_validation": {"passed": True},
        "clip_plan": [{"clip_index": 1, "capability": "GENERATE", "visual_state_indexes": [1]}],
    })
    db_session.commit()

    temp_paths = []
    real_mkstemp = tempfile.mkstemp

    def tracked_mkstemp(*args, **kwargs):
        kwargs["dir"] = tmp_path
        result = real_mkstemp(*args, **kwargs)
        temp_paths.append(Path(result[1]))
        return result

    monkeypatch.setattr(shots_api.tempfile, "mkstemp", tracked_mkstemp)
    response = client.get(f"/api/novels/{novel.id}/chapters/{chapter.id}/download-materials/")
    archive, manifest = _read_archive(response)
    names = set(archive.namelist())

    assert response.headers["content-disposition"].endswith('filename="chapter_003_archive.zip"')
    assert manifest["package_type"] == "CHAPTER_ARCHIVE"
    assert [item["plan_classification"] for item in manifest["shots"]] == ["CURRENT_CANONICAL", "CURRENT_CANONICAL", "HISTORICAL_PLAN", "MISSING_PLAN"]
    assert manifest["shots"][0]["final_assembly"]["status"] == "CURRENT"
    assert manifest["shots"][1]["final_assembly"]["status"] == "STALE_NOT_EXPORTED"
    assert manifest["shots"][2]["execution_status"] == "HISTORICAL_PLAN_NOT_EXPORTED"
    assert "selected_mode" not in json.dumps(manifest)
    assert "window_plans" not in json.dumps(manifest)
    assert manifest["resources"]["characters"] == [{
        "id": bound.id,
        "name": "皇帝",
        "status": "READY",
        "path": "resources/characters/001_皇帝.png",
    }]
    assert "resources/characters/001_皇帝.png" in names
    assert unbound.id not in json.dumps(manifest)
    assert not any("raw-secret" in name for name in names)
    assert not any("hd" in name.lower() for name in names)
    assert not any("stale" in name for name in names)
    assert not any("escape" in name for name in names)
    assert any(item["code"] == "OUTSIDE_STORAGE_ROOT" for item in manifest["warnings"])
    assert all(not path.exists() for path in temp_paths)
    assert not list(story_root.glob("chapter_*_materials.zip"))


def test_chapter_archive_manifest_only_succeeds(client, db_session, monkeypatch, tmp_path):
    novel, chapter = _base_records(db_session)
    _configure_storage(monkeypatch, tmp_path, novel.id)
    shot = Shot(chapter_id=chapter.id, index=1, duration=4, video_director_plan="{}")
    db_session.add(shot)
    db_session.commit()

    response = client.get(f"/api/novels/{novel.id}/chapters/{chapter.id}/download-materials/")
    archive, manifest = _read_archive(response)

    assert set(archive.namelist()) == {"manifest.json"}
    assert manifest["shots"][0]["plan_classification"] == "MISSING_PLAN"
