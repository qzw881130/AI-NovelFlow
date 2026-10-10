"""Persisted image selection, real compiler/binder paths; no media generation."""
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.shots import UpdateClipVisualStateReferencesRequest, update_clip_visual_state_references
from app.models.novel import Novel, Chapter
from app.models.shot import Shot
from app.models.task import Task
from app.repositories import ChapterRepository, ShotRepository
from app.services.clip_execution_compiler import (
    compile_generate_clip, compile_temporal_extend_clip, execution_temporal_state_ids, enabled_execution_temporal_state_ids,
    project_canonical_visual_references,
)
from app.services.clip_visual_state_references import disabled_visual_state_ids
from app.services.shot_video_service import clip_prompt_projection_metadata, reusable_clip_prompt
from app.services import h3_execution_optimizer as optimizer
from app.services.video_director_ai import attach_physical_picture_mapping, build_physical_picture_mapping


@pytest.fixture
def saved_clip(db_session):
    novel = Novel(title="Clip reference selection")
    db_session.add(novel); db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="Selection")
    db_session.add(chapter); db_session.flush()
    plan = {"clip_plan_revision": 2, "keyframes": [{"index": 9}, {"index": 10}],
            "clip_plan": [{"clip_index": 6, "visual_state_indexes": [9, 10],
                           "prompt_text": "historical", "video_url": "/original.mp4"},
                          {"clip_index": 7, "visual_state_indexes": []}],
            "ai_calls": [{"response": "historical raw output"}]}
    shot = Shot(chapter_id=chapter.id, index=3, duration=128, characters="[]", props="[]",
                dialogues='[{"speaker":"皇帝","text":"怎么？"}]', keyframes="[]",
                video_url="/original.mp4", video_status="completed", video_director_plan=json.dumps(plan))
    db_session.add(shot); db_session.commit()
    return novel, chapter, shot, plan


def save(db, fixture, ids, *, revision=2, index=6):
    novel, chapter, shot, _ = fixture
    return update_clip_visual_state_references(novel.id, chapter.id, shot.id, index,
        UpdateClipVisualStateReferencesRequest(enabled_state_ids=ids, expected_plan_revision=revision),
        db, ChapterRepository(db), ShotRepository(db))


def test_config_roundtrip_preserves_other_clips_assets_and_canonical(db_session, saved_clip):
    shot, before = saved_clip[2:]
    for ids in (["KF9"], [], ["KF9", "KF10"]):
        result = save(db_session, saved_clip, ids)
        db_session.expire_all()
        stored = db_session.get(Shot, shot.id)
        actual = json.loads(stored.video_director_plan)
        expected = deepcopy(before)
        expected["clip_plan"][0]["visual_state_reference_config"] = {"enabled_state_ids": ids}
        assert actual == expected
        assert result["data"]["videoDirectorPlan"]["clip_plan"][0]["visual_state_reference_config"]["enabled_state_ids"] == ids
        assert stored.video_url == "/original.mp4" and stored.dialogues == shot.dialogues


@pytest.mark.parametrize("ids,revision,index,status", [(["KF999"],2,6,400), (["KF9","KF9"],2,6,400), ([],1,6,409), ([],2,99,404)])
def test_invalid_selection_or_stale_revision_cannot_write(db_session, saved_clip, ids, revision, index, status):
    before = saved_clip[2].video_director_plan
    with pytest.raises(HTTPException) as exc:
        save(db_session, saved_clip, ids, revision=revision, index=index)
    assert exc.value.status_code == status and saved_clip[2].video_director_plan == before


def test_active_generation_freezes_configuration(db_session, saved_clip):
    db_session.add(Task(shot_id=saved_clip[2].id, type="shot_video", status="pending", name="Active video"))
    db_session.commit()
    with pytest.raises(HTTPException) as exc:
        save(db_session, saved_clip, [])
    assert exc.value.status_code == 409


def inputs():
    shot = SimpleNamespace(id="shot", duration=20, image_url="/start.png")
    plan = {"clip_plan_revision":1, "keyframes":[
        {"index":1, "role":"START", "time_seconds":0, "description":"Must stay seated."},
        {"index":2, "role":"END", "time_seconds":8, "description":"Hands remain empty.", "image_url":"/end.png"}]}
    clip = {"clip_index":1, "start_time":0, "end_time":8, "capability":"GENERATE", "visual_state_indexes":[1,2]}
    resources = {"references":[{"kind":kind, "image_url":f"/{kind}.png"} for kind in ("SCENE","CHARACTER_IDENTITY","PROP")]}
    return shot, plan, clip, resources


def test_missing_config_matches_explicit_all_and_none_keeps_text_and_resources():
    shot, plan, clip, resources = inputs()
    before = deepcopy(plan)
    default = project_canonical_visual_references(shot, plan, clip, resource_references=resources)
    clip["visual_state_reference_config"] = {"enabled_state_ids":["KF1","KF2"]}
    assert default == project_canonical_visual_references(shot, plan, clip, resource_references=resources)
    clip["visual_state_reference_config"] = {"enabled_state_ids":[]}
    compiled = compile_generate_clip(shot, plan, clip, 1, resources)
    manifest = compiled["video_reference_manifest"]
    assert [r["kind"] for r in manifest["references"]] == ["SCENE","CHARACTER_IDENTITY","PROP"]
    assert [r["slot"] for r in manifest["references"]] == [1,2,3]
    controls = attach_physical_picture_mapping(plan["keyframes"], build_physical_picture_mapping(manifest))
    assert all(s["physical_reference_status"] == "TEXT_ONLY" and s["physical_picture"] is None for s in controls)
    assert [s["description"] for s in controls] == [s["description"] for s in before["keyframes"]]
    assert plan == before
    shot.image_url = None
    assert compile_generate_clip(shot, plan, clip, 1, resources)["video_reference_manifest"] == manifest


def test_temporal_disabled_image_is_neither_timed_nor_ordinary_but_previous_stays():
    shot, plan, clip, resources = inputs()
    clip.update(clip_index=2, capability="TEMPORAL_EXTEND", continuity_to_previous="CONTINUOUS",
                previous_clip_index=1, requires_temporal_control=True, selected_temporal_target_ids=["KF2"],
                early_composition_state_id="KF1", visual_state_reference_config={"enabled_state_ids":[]})
    previous = {"clip_index":1,"clip_plan_revision":1,"generated_by_task_id":"original","result_url":"/previous.mp4"}
    anchors = [{"anchor_id":"clip-2-KF2","time_seconds":8,"source":{"keyframe_index":2},"image_url":None}]
    result = compile_temporal_extend_clip(shot, plan, clip, 1, previous, anchors, resources)
    assert result["execution_contract"]["temporal_anchor_manifest"]["anchors"] == []
    assert result["execution_contract"]["previous_clip"]["result_url"] == "/previous.mp4"
    assert len(result["video_reference_manifest"]["references"]) == 3
    assert execution_temporal_state_ids(clip) == ["KF2", "KF1"]
    assert enabled_execution_temporal_state_ids(clip) == []


def test_selection_invalidates_cached_prompt_without_overwriting_it():
    _, plan, clip, _ = inputs()
    attention = {"status":"ABSENT"}
    prompt = "original raw prompt"
    metadata = clip_prompt_projection_metadata(plan, clip, attention, prompt)
    assert reusable_clip_prompt(plan, clip, prompt, attention, metadata)
    clip["visual_state_reference_config"] = {"enabled_state_ids":[]}
    assert not reusable_clip_prompt(plan, clip, prompt, attention, metadata)
    new = clip_prompt_projection_metadata(plan, clip, attention, "new prompt")
    assert reusable_clip_prompt(plan, clip, "new prompt", attention, new)
    del clip["visual_state_reference_config"]
    assert not reusable_clip_prompt(plan, clip, "new prompt", attention, new)


def test_explicit_empty_manifest_does_not_resurrect_old_images(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("An explicitly empty manifest must never load fallback images")
    monkeypatch.setattr(optimizer, "vision_proxy", forbidden)
    runtime, images = optimizer.build_runtime_input("subject_definitions:\n<Subject 1> is Mira.", "SINGLE_FRAME",
        {"planned_duration":4}, reference_manifest={"references":[]}, reference_images=[{"url":"/disabled.png"}])
    assert runtime["immutable_authority"]["reference_bindings"] == [] and images == []
