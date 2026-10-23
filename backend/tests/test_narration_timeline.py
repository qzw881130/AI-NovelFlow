import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.api import shots as shots_api
from app.models.shot import Shot
from app.schemas.shot import PlanClipsRequest
from app.services.narration_timeline import (
    minimum_shot_duration_for_dialogues,
    segment_oversized_narration,
    split_oversized_narration_records,
)
from app.services.video_director_ai import build_dialogue_timeline, timeline_matches_shot_dialogues


NARRATION = (
    "齐国的变化，渐渐传到了其他诸侯国。\n\n"
    "燕国、赵国、韩国和魏国，都听闻了齐威王广开言路、整顿朝政的事情。\n\n"
    "各国君臣逐渐意识到，齐国正在变得更加强盛。\n\n"
    "过去，一个国家若想战胜其他诸侯，往往需要依靠兵马征伐。\n\n"
    "然而，齐威王并没有因为这次改革而大举兴兵。\n\n"
    "他只是听取臣民的意见，纠正朝政中的过失，使国家治理得更加有序。\n\n"
    "齐国的国力和威望，便因此不断提升。"
)


def make_shot(text=NARRATION, duration=39, **dialogue_fields):
    dialogue = {"order": 1, "character_name": "旁白", "text": text,
                "emotion_prompt": "平稳庄重", **dialogue_fields}
    timeline, _, status = build_dialogue_timeline(
        {"start_time": 0, "end_time": duration}, [dialogue], []
    )
    assert status["status"] == "ok"
    shot = Shot(id="shot", chapter_id="chapter", index=1, duration=duration,
                dialogues=json.dumps([dialogue], ensure_ascii=False), characters="[]",
                video_director_plan=json.dumps({"dialogue_timeline_source": timeline,
                                                "dialogue_timeline_status": status}, ensure_ascii=False))
    return shot, timeline


def test_long_narration_preserves_every_character_and_has_executable_events():
    shot, timeline = make_shot()
    before = shot.dialogues
    repaired = segment_oversized_narration(shot, timeline)
    assert repaired is not None
    dialogues, new_timeline, status = repaired
    assert len(dialogues) == 4
    assert "".join(item["text"] for item in dialogues) == NARRATION
    assert [item["dialogue_id"] for item in dialogues] == [
        "D1__sentence_1", "D1__sentence_2", "D1__sentence_3", "D1__sentence_4"
    ]
    assert all(item["character_name"] == "旁白" for item in dialogues)
    assert all(item["end_time"] - item["start_time"] <= 15 for item in new_timeline)
    assert new_timeline[-1]["end_time"] <= shot.duration
    assert status["status"] == "ok" and timeline_matches_shot_dialogues(new_timeline, dialogues)
    assert shot.dialogues == before
    assert split_oversized_narration_records(dialogues) is None
    assert minimum_shot_duration_for_dialogues(dialogues) <= shot.duration


def test_new_chapter_split_normalizes_narration_before_any_timeline_exists():
    original = [{"order": 0, "character_name": "旁白", "text": NARRATION,
                 "emotion_prompt": "平稳庄重"}]
    parts = split_oversized_narration_records(original)
    assert parts is not None and len(parts) == 4
    assert "".join(item["text"] for item in parts) == NARRATION
    assert minimum_shot_duration_for_dialogues(parts) == 39
    assert original[0]["text"] == NARRATION and len(original) == 1


def test_single_long_sentence_and_existing_audio_are_not_silently_split():
    shot, timeline = make_shot("长" * 84 + "。", duration=24)
    assert segment_oversized_narration(shot, timeline) is None
    shot, timeline = make_shot(audio_url="/api/files/narration.wav")
    assert segment_oversized_narration(shot, timeline) is None


def test_narration_over_fifteen_seconds_splits_to_leave_action_time():
    text = "甲" * 32 + "。" + "乙" * 32 + "。"
    shot, timeline = make_shot(text, duration=19)
    repaired = segment_oversized_narration(shot, timeline)
    assert repaired is not None
    dialogues, new_timeline, _ = repaired
    assert len(dialogues) == 2
    assert "".join(item["text"] for item in dialogues) == text
    assert all(item["end_time"] - item["start_time"] <= 15 for item in new_timeline)


@pytest.mark.asyncio
@pytest.mark.parametrize("valid", [True, False])
async def test_clip_plan_commits_repaired_dialogue_only_with_valid_plan(monkeypatch, valid):
    shot, original_timeline = make_shot()
    original_dialogues = shot.dialogues
    db = SimpleNamespace(commit=Mock())
    novel = SimpleNamespace(id="novel")
    novel_repo = SimpleNamespace(get_by_id=lambda _: novel)
    shot_repo = SimpleNamespace(get_by_id=lambda _: shot)

    async def fake_plan_clips(_db, _novel, planning_shot, _anchors, _policy, *, resolved_dialogue_timeline):
        assert shot.dialogues == original_dialogues
        assert planning_shot is not shot
        assert len(json.loads(planning_shot.dialogues)) == 4
        assert len(resolved_dialogue_timeline) == 4
        return [{"clip_index": 1, "start_time": 0, "end_time": 19}], {
            "passed": valid, "findings": [] if valid else ["TEST_VALIDATION_FAILURE"]
        }

    monkeypatch.setattr(shots_api, "plan_clips", fake_plan_clips)
    monkeypatch.setattr(shots_api, "get_canonical_execution_readiness", lambda *_: {})
    result = await shots_api.plan_shot_clips(
        "novel", "chapter", "shot", PlanClipsRequest(), db, novel_repo, shot_repo
    )
    assert result["success"]
    if valid:
        db.commit.assert_called_once()
        assert len(json.loads(shot.dialogues)) == 4
        assert len(json.loads(shot.video_director_plan)["dialogue_timeline_source"]) == 4
    else:
        db.commit.assert_not_called()
        assert shot.dialogues == original_dialogues
        assert json.loads(shot.video_director_plan)["dialogue_timeline_source"] == original_timeline
