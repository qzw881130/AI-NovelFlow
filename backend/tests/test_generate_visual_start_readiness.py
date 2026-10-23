import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.task import Task
from app.services.clip_execution_compiler import (
    ClipExecutionCompileError,
    compile_generate_clip,
    get_canonical_execution_readiness,
    get_generate_visual_start_readiness,
    project_canonical_visual_references,
)


def _state(index, time, role="INTERMEDIATE", image=None):
    value = {"index": index, "time_seconds": time, "role": role, "timed_visual_target": False}
    if image:
        value["image_url"] = image
    return value


def _clip(index=1, capability="GENERATE", owned=None, carry=None):
    return {
        "clip_index": index,
        "clip_plan_revision": 1,
        "start_time": 0 if index == 1 else 8,
        "end_time": 8 if index == 1 else 16,
        "planned_duration": 8,
        "capability": capability,
        "continuity_to_previous": "CONTINUOUS" if capability != "GENERATE" else "CUT" if index > 1 else "NONE",
        "previous_clip_index": index - 1 if index > 1 else None,
        "visual_state_indexes": list(owned or []),
        "carry_in_state_index": carry,
    }


def _plan(states, clips):
    return {
        "canonical_visual_plan": True,
        "clip_plan_revision": 1,
        "clip_plan_validation": {"passed": True, "temporal_contract": "ELIGIBLE_THEN_SELECTED_V1", "composition_contract": "EARLY_COMPOSITION_V2"},
        "keyframes": states,
        "clip_plan": clips,
    }


def _shot(image_url="/api/files/shot.png"):
    return SimpleNamespace(id="readiness-shot", duration=16, image_url=image_url, image_path=None)


def test_generate_start_uses_own_image_when_present():
    plan = _plan([_state(1, 0, "START", "/api/files/k1.png")], [_clip(owned=[1])])
    readiness = get_generate_visual_start_readiness(_shot(None), plan, plan["clip_plan"][0])
    assert readiness["ready"] is True
    assert readiness["grounding_source"] == "KEYFRAME_IMAGE"


def test_generate_start_preserves_shot_image_fallback():
    plan = _plan([_state(1, 0, "START")], [_clip(owned=[1])])
    readiness = get_generate_visual_start_readiness(_shot(), plan, plan["clip_plan"][0])
    assert readiness["ready"] is True
    assert readiness["grounding_source"] == "SHOT_IMAGE"
    compiled = compile_generate_clip(_shot(), plan, plan["clip_plan"][0], 1)
    assert compiled["video_reference_manifest"]["references"][0]["source_type"] == "SHOT_IMAGE"


def test_generate_non_start_uses_only_its_own_image():
    plan = _plan([_state(4, 9.5, image="/api/files/k4.png")], [_clip(2, owned=[4])])
    readiness = get_generate_visual_start_readiness(_shot(), plan, plan["clip_plan"][0])
    assert readiness["ready"] is True
    assert readiness["visual_state_index"] == 4
    assert readiness["grounding_source"] == "KEYFRAME_IMAGE"


@pytest.mark.parametrize(
    "shot,states,clip",
    [
        (_shot(), [_state(4, 9.5), _state(5, 14.5, image="/api/files/k5.png")], _clip(2, owned=[4, 5])),
        (_shot(), [_state(3, 8, image="/api/files/k3.png"), _state(4, 9.5)], _clip(2, owned=[4], carry=3)),
        (_shot("/api/files/shot.png"), [_state(4, 9.5)], _clip(2, owned=[4])),
    ],
)
def test_generate_non_start_rejects_later_owned_carry_and_shot_fallbacks(shot, states, clip):
    plan = _plan(states, [clip])
    readiness = get_generate_visual_start_readiness(shot, plan, clip)
    assert readiness == {
        "ready": False,
        "applicable": True,
        "code": "GENERATE_VISUAL_START_GROUNDING_MISSING",
        "message": "缺少片段起始视觉图：Clip 2 · 视觉状态 4（9.5s）",
        "clip_index": 2,
        "visual_state_index": 4,
        "time_seconds": 9.5,
        "grounding_source": None,
        "image_url": None,
    }


def test_generate_non_start_does_not_consult_character_scene_or_prop_images():
    shot = _shot()
    shot.merged_character_image = "/api/files/character.png"
    shot.merged_prop_image = "/api/files/prop.png"
    shot.scene_image_url = "/api/files/scene.png"
    plan = _plan([_state(4, 9.5)], [_clip(2, owned=[4])])
    assert get_generate_visual_start_readiness(shot, plan, plan["clip_plan"][0])["ready"] is False


@pytest.mark.parametrize("capability", ["EXTEND", "TEMPORAL_EXTEND"])
def test_continuation_capabilities_are_outside_generate_visual_start_gate(capability):
    plan = _plan([_state(4, 9.5)], [_clip(2, capability, owned=[4], carry=3)])
    readiness = get_generate_visual_start_readiness(_shot(), plan, plan["clip_plan"][0])
    assert readiness["ready"] is True
    assert readiness["applicable"] is False
    assert readiness["code"] == "NOT_APPLICABLE"


def test_compiler_rejects_missing_first_owned_even_when_later_physical_reference_exists():
    clip = _clip(2, owned=[4, 5])
    plan = _plan([_state(4, 9.5), _state(5, 14.5, image="/api/files/k5.png")], [clip])
    manifest = project_canonical_visual_references(_shot(), plan, clip)
    assert [item["source_keyframe_index"] for item in manifest["references"]] == [5]
    with pytest.raises(ClipExecutionCompileError) as exc_info:
        compile_generate_clip(_shot(), plan, clip, 1)
    assert exc_info.value.detail["code"] == "GENERATE_VISUAL_START_GROUNDING_MISSING"
    assert exc_info.value.detail["visual_state_index"] == 4


def _db_fixture(db_session):
    novel = Novel(title="Visual start readiness")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="Chapter")
    db_session.add(chapter)
    db_session.flush()
    clips = [
        _clip(1, owned=[1, 2, 3]),
        _clip(2, owned=[4, 5, 6], carry=3),
    ]
    states = [
        _state(1, 0, "START"),
        _state(2, 4),
        _state(3, 8, image="/api/files/k3.png"),
        _state(4, 9.5),
        _state(5, 14.5),
        _state(6, 16, "END"),
    ]
    shot = Shot(
        chapter_id=chapter.id,
        index=11,
        duration=16,
        image_url="/api/files/shot.png",
        video_director_plan=json.dumps(_plan(states, clips), ensure_ascii=False),
    )
    db_session.add(shot)
    db_session.commit()
    return novel, chapter, shot


def test_single_clip_endpoint_blocks_before_task_creation(client, db_session):
    novel, chapter, shot = _db_fixture(db_session)
    before = db_session.query(Task).count()
    response = client.post(
        f"/api/novels/{novel.id}/chapters/{chapter.id}/shots/{shot.id}/video-director/clips/2/generate",
        json={"clip_plan_revision": 1, "auto_merge": False},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "GENERATE_VISUAL_START_GROUNDING_MISSING"
    assert response.json()["detail"]["visual_state_index"] == 4
    assert db_session.query(Task).count() == before


def test_batch_and_frontend_projection_share_backend_readiness_before_scheduling(client, db_session):
    novel, chapter, shot = _db_fixture(db_session)
    projected = client.get(
        f"/api/novels/{novel.id}/chapters/{chapter.id}/shots/{shot.id}"
    ).json()["data"]["videoDirectorPlan"]["execution_readiness"]
    assert projected["ready"] is False
    assert projected["blocking_clips"][0]["clip_index"] == 2
    assert projected["blocking_clips"][0]["visual_state_index"] == 4
    before = db_session.query(Task).count()
    with patch("app.api.shots.enqueue_shot_video_batch_task") as enqueue:
        response = client.post(
            f"/api/novels/{novel.id}/chapters/{chapter.id}/shot-videos/batch",
            json={"shot_ids": [shot.id]},
        )
    assert response.status_code == 409
    assert response.json()["detail"]["message"] == "缺少片段起始视觉图：Clip 2 · 视觉状态 4（9.5s）"
    assert db_session.query(Task).count() == before
    enqueue.assert_not_called()


def test_plan_level_readiness_reports_only_first_owned_generate_blocker():
    clips = [_clip(1, owned=[1, 2, 3]), _clip(2, owned=[4, 5, 6], carry=3)]
    plan = _plan([
        _state(1, 0, "START"), _state(2, 4), _state(3, 8, image="/api/files/k3.png"),
        _state(4, 9.5), _state(5, 14.5), _state(6, 16, "END"),
    ], clips)
    readiness = get_canonical_execution_readiness(_shot(), plan)
    assert [(item["clip_index"], item["visual_state_index"]) for item in readiness["blocking_clips"]] == [(2, 4)]
