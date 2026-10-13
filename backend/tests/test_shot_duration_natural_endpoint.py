import json
from types import SimpleNamespace

import pytest

from app.api import shots as shot_api
from app.models.novel import Chapter, Novel
from app.models.prompt_template import PromptTemplate
from app.models.shot import Shot
from app.repositories.chapter_repository import ChapterRepository
from app.repositories.novel_repository import NovelRepository
from app.repositories.prompt_template import PromptTemplateRepository
from app.repositories.shot_repository import ShotRepository
from app.schemas.shot import PlanVideoKeyframesRequest
from app.services import clip_planner


def test_only_changed_user_duration_becomes_a_hard_constraint():
    shot = SimpleNamespace(duration=32, video_director_plan='{"visual_intent":"departure"}')
    unchanged = {"duration": 32}
    shot_api._lock_explicit_shot_duration_edit(shot, unchanged)
    assert "video_director_plan" not in unchanged

    edited = {"duration": 28}
    shot_api._lock_explicit_shot_duration_edit(shot, edited)
    assert edited["video_director_plan"]["shot_duration_locked"] is True
    assert edited["video_director_plan"]["visual_intent"] == "departure"


def test_planned_duration_keeps_legacy_and_dialogue_authority():
    resolve = shot_api._resolve_planned_shot_duration
    dialogue = [{"id": "D1", "end_time": 12.3}]
    assert resolve({}, 32, dialogue) == 32
    assert resolve({"shot_duration": 18}, 32, dialogue) == 18
    with pytest.raises(ValueError, match="正式对白"):
        resolve({"shot_duration": 12}, 32, dialogue)
    with pytest.raises(ValueError, match="已锁定"):
        resolve({"shot_duration": 18}, 32, dialogue, can_shorten=False)
    with pytest.raises(ValueError, match="整数秒"):
        resolve({"shot_duration": 18.5}, 32, dialogue)


@pytest.mark.asyncio
async def test_shortened_shot_persists_matching_canonical_endpoint(db_session, monkeypatch):
    novel = Novel(title="natural ending")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="chapter")
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(chapter_id=chapter.id, index=8, duration=32, description="Two people leave.",
                video_description="They exchange a glance and leave.", characters="[]", props="[]",
                dialogues="[]", video_director_plan="{}")
    template = PromptTemplate(name="duration planner", type="keyframe_planner",
                              template="plan", is_system=True, is_active=True)
    db_session.add_all([shot, template])
    db_session.commit()

    async def complete(**kwargs):
        payload = json.loads(kwargs["user_content"].split("\n\n", 1)[1])
        assert payload["shot"]["duration"] == 32
        assert payload["duration_policy"]["can_shorten"] is True
        return {"success": True, "content": json.dumps({
            "shot_duration": 18,
            "keyframes": [
                {"index": 1, "time_seconds": 0, "role": "START", "description": None,
                 "timed_visual_target": False},
                {"index": 2, "time_seconds": 18, "role": "END", "description": "The two people are apart.",
                 "timed_visual_target": False},
            ],
            "visual_attention": {"windows": []},
        })}

    async def transitions(*args, **kwargs):
        planned_shot = kwargs["shot"]
        assert planned_shot.duration == 18
        assert kwargs["keyframes"][-1]["time_seconds"] == 18
        return [{"segment_index": 1, "from_keyframe_index": 1, "to_keyframe_index": 2,
                 "start_time": 0, "end_time": 18, "transition_description": "They part."}]

    monkeypatch.setattr(shot_api, "get_style", lambda *args, **kwargs: ("", None))
    monkeypatch.setattr(shot_api, "_plan_keyframe_transitions", transitions)
    result = await shot_api.plan_video_keyframes(
        novel.id, chapter.id, shot.id, PlanVideoKeyframesRequest(force=True),
        db_session, NovelRepository(db_session), ChapterRepository(db_session),
        ShotRepository(db_session), PromptTemplateRepository(db_session),
        SimpleNamespace(chat_completion=complete),
    )
    db_session.expire_all()
    saved = ShotRepository(db_session).get_by_id(shot.id)
    plan = json.loads(saved.video_director_plan)
    assert result["success"] is True
    assert saved.duration == plan["keyframes"][-1]["time_seconds"] == plan["transitions"][-1]["end_time"] == 18
    assert not plan.get("clip_plan")


@pytest.mark.asyncio
async def test_clip_planner_reports_upstream_empty_tail(monkeypatch):
    shot = SimpleNamespace(id="shot", chapter_id="chapter", duration=32,
                           continuity_mode="NORMAL", characters="[]", scene="", props="[]",
                           dialogues="[]", keyframes="[]", image_url=None, image_path=None,
                           video_director_plan="{}")

    class FakeLLM:
        async def chat_completion(self, **kwargs):
            return {"success": True, "content": json.dumps({
                "duration_replan_required": "16–32s repeats the completed departure",
            })}

    monkeypatch.setattr(clip_planner, "resolve_novel_prompt_template",
                        lambda *args: SimpleNamespace(template="planner", name="planner"))
    monkeypatch.setattr(clip_planner, "LLMService", FakeLLM)
    with pytest.raises(ValueError, match="UPSTREAM_SHOT_DURATION_REPLAN_REQUIRED"):
        await clip_planner.plan_clips(None, SimpleNamespace(id="novel"), shot, [])
