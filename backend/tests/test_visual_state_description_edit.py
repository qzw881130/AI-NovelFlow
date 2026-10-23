import json
from copy import deepcopy

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.shots import UpdateVisualStateDescriptionRequest, update_visual_state_description
from app.models.novel import Novel, Chapter
from app.models.shot import Shot
from app.models.task import Task
from app.repositories import ChapterRepository, ShotRepository
from app.services.shot_keyframe_service import ShotKeyframeService, sync_planned_keyframe_states


@pytest.fixture
def edit_shot(db_session):
    novel = Novel(title="Visual description edit")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="Edit")
    db_session.add(chapter)
    db_session.flush()
    plan = {
        "canonical_visual_plan": True, "clip_plan_revision": 2,
        "keyframes": [
            {"index": 1, "role": "START", "time_seconds": 0, "description": "Initial", "timed_visual_target": False},
            {"index": 10, "role": "INTERMEDIATE", "time_seconds": 7, "description": "The king faces the window.", "timed_visual_target": False, "image_url": "/old.png", "image_task_id": "history", "prompt_text": "old prompt"},
        ],
        "transitions": [{"from_keyframe_index": 1, "to_keyframe_index": 10, "transition_description": "Turns."}],
        "clip_plan": [], "ai_calls": [{"response": "historical"}],
    }
    legacy = [{"frame_index": 0, "plan_keyframe_index": 10, "time_seconds": 7, "description": "The king faces the window.", "image_url": "/old.png", "image_task_id": "history", "prompt_text": "old prompt", "reference_mode": "custom", "reference_image_url": "/ref.png"}]
    shot = Shot(chapter_id=chapter.id, index=1, duration=10, description="Initial", characters="[]", props="[]", dialogues="[]", video_status="completed", video_url="/existing.mp4", keyframes=json.dumps(legacy), video_director_plan=json.dumps(plan))
    db_session.add(shot)
    db_session.commit()
    return novel, chapter, shot, deepcopy(plan), deepcopy(legacy)


def save(db, fixture, *, index=10, description="The king faces the door.", expected="The king faces the window.", revision=2, shot_repo=None):
    novel, chapter, shot, *_ = fixture
    return update_visual_state_description(novel.id, chapter.id, shot.id, index,
        UpdateVisualStateDescriptionRequest(description=description, expected_description=expected, expected_plan_revision=revision),
        db, ChapterRepository(db), shot_repo or ShotRepository(db))


def test_edit_persists_only_selected_state_and_projects_image_description(db_session, edit_shot):
    result = save(db_session, edit_shot)
    shot, before, legacy = edit_shot[2:]
    db_session.expire_all()
    stored = ShotRepository(db_session).get_by_id(shot.id)
    plan, frames = json.loads(stored.video_director_plan), json.loads(stored.keyframes)
    expected = deepcopy(before)
    expected["keyframes"][1].update(description="The king faces the door.", prompt_text="")
    assert plan == expected
    legacy[0].update(description="The king faces the door.", prompt_text="")
    assert frames == legacy
    assert stored.description == "Initial"
    assert stored.video_url == "/existing.mp4"
    assert result["data"]["videoDirectorPlan"]["keyframes"][1]["description"] == "The king faces the door."
    assert "required_execution_images" in result["data"]["videoDirectorPlan"]
    assert not sync_planned_keyframe_states(stored, frames)
    assert ShotKeyframeService._get_reusable_keyframe_prompt(None, db_session, stored.id, 0, frames[0]) == ""


def test_start_edit_updates_the_main_shot_description(db_session, edit_shot):
    result = save(db_session, edit_shot, index=1, description="The king stands by a door.", expected="Initial")
    assert result["data"]["shotDescription"] == "The king stands by a door."
    assert result["data"]["videoDirectorPlan"]["keyframes"][0]["description"] == "The king stands by a door."
    assert result["data"]["keyframes"][0]["description"] == "The king faces the window."


@pytest.mark.parametrize("kwargs, status", [
    ({"description": "  \n "}, 400), ({"expected": "outdated"}, 409),
    ({"revision": 1}, 409), ({"index": 99}, 404),
    ({"description": "The king starts speaking."}, 400),
])
def test_invalid_or_stale_edit_leaves_persisted_data_untouched(db_session, edit_shot, kwargs, status):
    before = edit_shot[2].video_director_plan
    with pytest.raises(HTTPException) as caught:
        save(db_session, edit_shot, **kwargs)
    assert caught.value.status_code == status
    assert edit_shot[2].video_director_plan == before


@pytest.mark.parametrize("kind, task_id", [("shot_video", "active-video"), ("keyframe_image", "history")])
def test_edit_rejects_an_active_video_or_selected_image_task(db_session, edit_shot, kind, task_id):
    novel, chapter, shot, *_ = edit_shot
    db_session.add(Task(id=task_id, type=kind, status="running", name="active", shot_id=shot.id, chapter_id=chapter.id, novel_id=novel.id))
    db_session.commit()
    with pytest.raises(HTTPException) as caught:
        save(db_session, edit_shot)
    assert caught.value.status_code == 409


def test_compare_and_swap_preserves_a_workers_concurrent_update(db_session, edit_shot):
    shot = edit_shot[2]
    original = shot.video_director_plan
    class ConcurrentRepository(ShotRepository):
        def get_by_id(self, shot_id):
            row = super().get_by_id(shot_id)
            newer = json.loads(row.video_director_plan)
            newer["ai_calls"].append({"response": "new worker log"})
            with Session(db_session.bind) as worker:
                worker.query(Shot).filter(Shot.id == shot_id).update({Shot.video_director_plan: json.dumps(newer)}, synchronize_session=False)
                worker.commit()
            return row
    with pytest.raises(HTTPException) as caught:
        save(db_session, edit_shot, shot_repo=ConcurrentRepository(db_session))
    assert caught.value.status_code == 409
    db_session.expire_all()
    assert json.loads(ShotRepository(db_session).get_by_id(shot.id).video_director_plan)["ai_calls"][-1] == {"response": "new worker log"}
    assert json.loads(original)["keyframes"][1]["description"] == "The king faces the window."
