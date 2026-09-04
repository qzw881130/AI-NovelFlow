import json

import pytest

from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.services.video_director_plan_service import (
    PlanOwnershipError,
    PlanRevisionConflict,
    VideoDirectorPlanService,
)
from app.repositories.shot_repository import ShotRepository


def _create_shot(db_session, plan=None, revision=0):
    novel = Novel(title="Gate D3")
    db_session.add(novel)
    db_session.commit()
    db_session.refresh(novel)

    chapter = Chapter(novel_id=novel.id, number=1, title="Chapter", content="content")
    db_session.add(chapter)
    db_session.commit()
    db_session.refresh(chapter)

    shot = Shot(
        chapter_id=chapter.id,
        index=1,
        description="Shot",
        characters=json.dumps([], ensure_ascii=False),
        scene="",
        props=json.dumps([], ensure_ascii=False),
        duration=4,
        video_director_plan=json.dumps(plan or {}, ensure_ascii=False),
        video_director_plan_revision=revision,
    )
    db_session.add(shot)
    db_session.commit()
    db_session.refresh(shot)
    return novel, chapter, shot


def _plan(shot):
    return json.loads(shot.video_director_plan or "{}")


def test_prompt_patch_after_worker_result_preserves_video_fact(db_session):
    _novel, _chapter, shot = _create_shot(db_session, {
        "clips": [{"clip_index": 1, "prompt_text": "old", "status": "PENDING"}],
    }, revision=10)
    service = VideoDirectorPlanService(db_session)

    service.mutate(shot.id, lambda plan: {
        **plan,
        "clips": [{**plan["clips"][0], "status": "SUCCEEDED", "video_url": "/api/files/new.mp4", "generated_at": "t1"}],
    })
    service.patch_clip_prompt(shot.id, "clips", 1, "new prompt")

    db_session.refresh(shot)
    plan = _plan(shot)
    assert shot.video_director_plan_revision == 12
    assert plan["clips"][0]["prompt_text"] == "new prompt"
    assert plan["clips"][0]["video_url"] == "/api/files/new.mp4"
    assert plan["clips"][0]["status"] == "SUCCEEDED"


def test_two_worker_clip_results_both_survive_field_mutations(db_session):
    _novel, _chapter, shot = _create_shot(db_session, {
        "window_plans": [
            {"window_index": 1, "status": "PENDING"},
            {"window_index": 2, "status": "PENDING"},
        ],
    })
    service = VideoDirectorPlanService(db_session)

    def complete_window(window_index: int, url: str):
        def mutate(plan: dict) -> dict:
            for window in plan["window_plans"]:
                if window["window_index"] == window_index:
                    window.update({"status": "SUCCEEDED", "video_url": url, "generated_at": f"t{window_index}"})
            return plan
        service.mutate(shot.id, mutate)

    complete_window(1, "/api/files/c1.mp4")
    complete_window(2, "/api/files/c2.mp4")

    db_session.refresh(shot)
    windows = _plan(shot)["window_plans"]
    assert shot.video_director_plan_revision == 2
    assert windows[0]["video_url"] == "/api/files/c1.mp4"
    assert windows[1]["video_url"] == "/api/files/c2.mp4"


def test_structural_update_with_old_revision_conflicts_without_write(db_session):
    _novel, _chapter, shot = _create_shot(db_session, {"selected_mode": "SINGLE_FRAME"}, revision=5)
    service = VideoDirectorPlanService(db_session)
    service.mutate(shot.id, lambda plan: {**plan, "merged_video_url": "/api/files/current.mp4"})

    with pytest.raises(PlanRevisionConflict):
        service.replace_structure(shot.id, {"selected_mode": "MULTI_KEYFRAME"}, expected_revision=5)

    db_session.refresh(shot)
    plan = _plan(shot)
    assert shot.video_director_plan_revision == 6
    assert plan["selected_mode"] == "SINGLE_FRAME"
    assert plan["merged_video_url"] == "/api/files/current.mp4"


def test_user_payload_cannot_write_worker_fact_fields():
    with pytest.raises(PlanOwnershipError):
        VideoDirectorPlanService.assert_user_plan_payload_allowed({
            "clips": [{"clip_index": 1, "prompt_text": "ok", "video_url": "/api/files/stale.mp4"}],
        })

    with pytest.raises(PlanOwnershipError):
        VideoDirectorPlanService.assert_user_plan_payload_allowed({"merged_video_url": "/api/files/stale.mp4"})


def test_keyframe_description_patch_preserves_worker_image_url(db_session):
    _novel, _chapter, shot = _create_shot(db_session, {
        "keyframes": [{"index": 2, "description": "old", "image_url": "/api/files/kf.png"}],
    })
    service = VideoDirectorPlanService(db_session)

    service.patch_keyframe_description(shot.id, 2, "new description")

    db_session.refresh(shot)
    keyframe = _plan(shot)["keyframes"][0]
    assert shot.video_director_plan_revision == 1
    assert keyframe["description"] == "new description"
    assert keyframe["image_url"] == "/api/files/kf.png"


def test_batch_update_rejects_full_video_director_plan(client, db_session):
    novel, chapter, shot = _create_shot(db_session, {"clips": [{"clip_index": 1}]})

    response = client.patch(f"/api/novels/{novel.id}/chapters/{chapter.id}/shots/batch", json={
        "shots": [{"id": shot.id, "video_director_plan": {"clips": []}}],
    })

    assert response.status_code == 400
    db_session.refresh(shot)
    assert _plan(shot)["clips"][0]["clip_index"] == 1
    assert shot.video_director_plan_revision == 0


def test_revision_increments_for_each_successful_mutation(db_session):
    _novel, _chapter, shot = _create_shot(db_session, {"clips": [{"clip_index": 1}]})
    service = VideoDirectorPlanService(db_session)

    _plan1, rev1 = service.patch_clip_prompt(shot.id, "clips", 1, "prompt")
    _plan2, rev2 = service.mutate(shot.id, lambda plan: {**plan, "merged_at": "t"})

    assert rev1 == 1
    assert rev2 == 2


def test_shot_repository_plan_update_increments_revision(db_session):
    _novel, _chapter, shot = _create_shot(db_session, {"selected_mode": "SINGLE_FRAME"})

    ShotRepository(db_session).update(shot, video_director_plan={"selected_mode": "MULTI_KEYFRAME"})

    assert shot.video_director_plan_revision == 1
