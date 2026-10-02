import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import shots as shot_api
from app.models.novel import Chapter, Novel
from app.models.prompt_template import PromptTemplate
from app.models.shot import Shot
from app.repositories.chapter_repository import ChapterRepository
from app.repositories.novel_repository import NovelRepository
from app.repositories.prompt_template import PromptTemplateRepository
from app.repositories.shot_repository import ShotRepository
from app.schemas.shot import PlanVideoKeyframesRequest
from app.services.canonical_visual_speech_authority import (
    CanonicalVisualSpeechAuthorityViolation,
    find_visual_speech_authority,
)


def _state(index, time_seconds, description, role="INTERMEDIATE"):
    return {
        "index": index,
        "time_seconds": time_seconds,
        "role": role,
        "description": description,
        "timed_visual_target": False,
    }


def _shot(description="Scene: hall\nCharacters:\n- 皇帝: 皱眉看向镜子"):
    return SimpleNamespace(
        id="shot-guard",
        index=11,
        description=description,
        video_description="皇帝开口询问，侍从回答",
        characters=json.dumps(["皇帝", "侍从1"], ensure_ascii=False),
        scene="hall",
        props="[]",
        duration=18,
        continuity_mode="NORMAL",
        dialogues=json.dumps([
            {"character_name": "皇帝", "text": "台词正文"},
        ], ensure_ascii=False),
        video_director_plan="{}",
    )


def _payload(content):
    return json.loads(content.split("\n\n", 1)[1])


def _transition_content(description):
    return json.dumps({"transition_description": description}, ensure_ascii=False)


class SequenceLLM:
    def __init__(self, contents):
        self.contents = list(contents)
        self.calls = []

    async def chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        return {"success": True, "content": self.contents.pop(0)}


class FakeDB:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


class FakeTemplateRepo:
    def get_default_system_template(self, _template_type):
        return SimpleNamespace(name="关键帧过渡规划", template="system #10")


@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("皇帝嘴唇微启，处于说话状态", "MOUTH_LIP_SPEECH_STATE"),
        ("侍从1回答皇帝", "SPEAKING_AUTHORITY"),
        ("侍从2接话，身体微微前倾", "SPEAKING_AUTHORITY"),
        ("皇帝听完回答后仍微微皱眉", "LISTENING_AUTHORITY"),
        ("侍从2闭嘴，皇帝开始回答", "MOUTH_LIP_SPEECH_STATE"),
        ("侍从2嘴唇由微启逐渐闭合", "MOUTH_LIP_SPEECH_STATE"),
        ("The emperor starts speaking while the attendant listens", "SPEAKING_AUTHORITY"),
        ("Her lips are closed for the reply", "MOUTH_LIP_SPEECH_STATE"),
    ],
)
def test_detector_rejects_explicit_speech_authority(text, category):
    matches = find_visual_speech_authority(text)
    assert matches
    assert category in {item.category for item in matches}


@pytest.mark.parametrize(
    "text",
    [
        "皇帝皱眉，转头看向侍从1",
        "侍从听到声音后转头看向门口",
        "侍从受到呼喊后回头看向门口",
        "皇帝看到对方动作后皱眉",
        "皇帝微笑，嘴角轻轻上扬",
        "侍从以点头回应皇帝的视线",
        "The emperor raises his hand and looks toward the mirror.",
    ],
)
def test_detector_allows_visual_reaction_and_expression(text):
    assert find_visual_speech_authority(text) == []


def test_clean_canonical_visual_state_normalizes():
    states, _, _ = shot_api._normalize_keyframe_planner_result({"keyframes": [
        _state(1, 0, None, role="START"),
        _state(2, 4, "皇帝皱眉，转头看向侍从1"),
    ]}, None, 8)
    assert states[1]["description"] == "皇帝皱眉，转头看向侍从1"


@pytest.mark.parametrize("description", [
    "皇帝嘴唇微启，处于说话状态",
    "侍从1回答皇帝",
])
def test_canonical_visual_state_rejects_speech_authority(description):
    with pytest.raises(
        CanonicalVisualSpeechAuthorityViolation,
        match=r"VISUAL_STATE_SPEECH_AUTHORITY_VIOLATION.*state_index=2.*description",
    ):
        shot_api._normalize_keyframe_planner_result({"keyframes": [
            _state(1, 0, None, role="START"),
            _state(2, 4, description),
        ]}, None, 8)


def test_transition_payload_excludes_all_dialogue_authority():
    content = shot_api._build_keyframe_transition_user_content(
        _shot(),
        _state(1, 0, "皇帝站在镜前", role="START"),
        _state(2, 4, "皇帝抬起右手"),
        1,
    )
    payload = _payload(content)
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "dialogues" not in payload["shot"]
    assert "dialogue_timeline_source" not in payload
    assert "segment_dialogue_state" not in payload
    assert "description" not in payload["shot"]
    assert "video_description" not in payload["shot"]
    assert "台词正文" not in serialized
    assert "speaker" not in serialized
    assert "start_time" not in serialized
    assert "end_time" not in serialized
    assert payload["from_keyframe"]["description"] == "皇帝站在镜前"
    assert payload["from_keyframe"]["time_seconds"] == 0
    assert payload["to_keyframe"]["time_seconds"] == 4


def test_empty_start_does_not_recover_raw_shot_narrative():
    shot = _shot("皇帝皱眉询问，侍从1与侍从2先后恭敬回答")
    content = shot_api._build_keyframe_transition_user_content(
        shot,
        _state(1, 0, None, role="START"),
        _state(2, 4, "皇帝抬起右手"),
        1,
    )
    payload = _payload(content)
    serialized = json.dumps(payload, ensure_ascii=False)

    assert payload["from_keyframe"] == {
        "index": 1,
        "role": "START",
        "time_seconds": 0,
        "description": "",
    }
    assert payload["to_keyframe"]["description"] == "皇帝抬起右手"
    assert payload["segment_index"] == 1
    assert payload["shot"]["characters"] == ["皇帝", "侍从1"]
    assert payload["shot"]["scene"] == "hall"
    assert payload["shot"]["props"] == []
    assert payload["shot"]["duration"] == 18
    assert payload["shot"]["continuity_mode"] == "NORMAL"
    assert "皇帝皱眉询问，侍从1与侍从2先后恭敬回答" not in serialized
    assert "皇帝开口询问，侍从回答" not in serialized
    assert "询问" not in serialized
    assert "回答" not in serialized


@pytest.mark.parametrize("position", ["from", "to"])
def test_stale_transition_endpoint_is_rejected(position):
    from_state = _state(1, 0, "皇帝站在镜前", role="START")
    to_state = _state(2, 4, "皇帝抬起右手")
    if position == "from":
        from_state["description"] = "皇帝嘴唇微启，处于说话状态"
    else:
        to_state["description"] = "侍从1回答皇帝"
    with pytest.raises(
        CanonicalVisualSpeechAuthorityViolation,
        match=r"VISUAL_STATE_SPEECH_AUTHORITY_VIOLATION",
    ):
        shot_api._build_keyframe_transition_user_content(
            _shot(), from_state, to_state, 1,
        )


@pytest.mark.asyncio
async def test_stale_state_blocks_transition_llm_before_call():
    llm = SequenceLLM([_transition_content("不会被调用")])
    with pytest.raises(HTTPException, match="VISUAL_STATE_SPEECH_AUTHORITY_VIOLATION"):
        await shot_api._plan_keyframe_transitions(
            FakeDB(),
            SimpleNamespace(id="novel", keyframe_transition_prompt_template_id=None),
            SimpleNamespace(id="chapter"),
            _shot(),
            [
                _state(1, 0, "皇帝站在镜前", role="START"),
                _state(2, 4, "皇帝嘴唇微启，处于说话状态"),
            ],
            FakeTemplateRepo(),
            llm,
        )
    assert llm.calls == []


@pytest.mark.asyncio
async def test_transition_output_validation_retries_once_then_accepts(monkeypatch):
    monkeypatch.setattr(shot_api, "get_style", lambda *_args, **_kwargs: ("", None))
    llm = SequenceLLM([
        _transition_content("皇帝嘴唇微启，开始说话"),
        _transition_content("皇帝转向镜子，右手抬至袖口；侍从1向后半步"),
    ])
    shot = _shot()
    transitions = await shot_api._plan_keyframe_transitions(
        FakeDB(),
        SimpleNamespace(id="novel", keyframe_transition_prompt_template_id=None),
        SimpleNamespace(id="chapter"),
        shot,
        [
            _state(1, 0, "皇帝站在镜前", role="START"),
            _state(2, 4, "皇帝抬起右手"),
        ],
        FakeTemplateRepo(),
        llm,
    )
    assert len(llm.calls) == 2
    retry_payload = _payload(llm.calls[1]["user_content"])
    assert retry_payload["previous_validation_failure"]["category"] == "MOUTH_LIP_SPEECH_STATE"
    assert transitions[0]["transition_description"] == "皇帝转向镜子，右手抬至袖口；侍从1向后半步"


@pytest.mark.asyncio
async def test_transition_output_validation_hard_fails_after_one_retry(monkeypatch):
    monkeypatch.setattr(shot_api, "get_style", lambda *_args, **_kwargs: ("", None))
    llm = SequenceLLM([
        _transition_content("皇帝嘴唇微启，开始说话"),
        _transition_content("侍从2闭嘴，皇帝开始回答"),
    ])
    shot = _shot()
    shot.video_director_plan = json.dumps({"transitions": [{"old": True}]})
    with pytest.raises(HTTPException, match="TRANSITION_SPEECH_AUTHORITY_VIOLATION"):
        await shot_api._plan_keyframe_transitions(
            FakeDB(),
            SimpleNamespace(id="novel", keyframe_transition_prompt_template_id=None),
            SimpleNamespace(id="chapter"),
            shot,
            [
                _state(1, 0, "皇帝站在镜前", role="START"),
                _state(2, 4, "皇帝抬起右手"),
            ],
            FakeTemplateRepo(),
            llm,
        )
    assert len(llm.calls) == 2
    assert json.loads(shot.video_director_plan)["transitions"] == [{"old": True}]


@pytest.mark.asyncio
async def test_arbitrary_n_transition_identity_order_and_time_are_preserved(monkeypatch):
    monkeypatch.setattr(shot_api, "get_style", lambda *_args, **_kwargs: ("", None))
    times = [0, 2, 5, 9.5, 14.5, 18]
    keyframes = [
        _state(index, time, f"状态{index}", role="START" if index == 1 else ("END" if index == 6 else "INTERMEDIATE"))
        for index, time in enumerate(times, 1)
    ]
    llm = SequenceLLM([
        _transition_content(f"状态{index}平稳过渡到状态{index + 1}")
        for index in range(1, 6)
    ])
    transitions = await shot_api._plan_keyframe_transitions(
        FakeDB(),
        SimpleNamespace(id="novel", keyframe_transition_prompt_template_id=None),
        SimpleNamespace(id="chapter"),
        _shot(),
        keyframes,
        FakeTemplateRepo(),
        llm,
    )
    assert [
        (item["segment_index"], item["from_keyframe_index"], item["to_keyframe_index"], item["start_time"], item["end_time"])
        for item in transitions
    ] == [
        (index, index, index + 1, times[index - 1], times[index])
        for index in range(1, 6)
    ]


def _planning_fixture(db_session):
    novel = Novel(title="speech boundary")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="test")
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(
        chapter_id=chapter.id,
        index=1,
        description="皇帝站在窗边",
        duration=8,
        characters="[]",
        props="[]",
        dialogues="[]",
        video_director_plan=json.dumps({"existing_marker": True}),
    )
    template = PromptTemplate(
        name="canonical planner",
        type="keyframe_planner",
        template="system #08",
        is_system=True,
    )
    db_session.add_all([shot, template])
    db_session.commit()
    return novel, chapter, shot


def _planner_content(description):
    return json.dumps({"keyframes": [
        _state(1, 0, None, role="START"),
        _state(2, 4, description),
    ]}, ensure_ascii=False)


@pytest.mark.asyncio
async def test_planner_retries_speech_violation_once_then_persists_clean_plan(db_session, monkeypatch):
    novel, chapter, shot = _planning_fixture(db_session)
    monkeypatch.setattr(shot_api, "get_style", lambda *_args, **_kwargs: ("", None))
    llm = SequenceLLM([
        _planner_content("皇帝嘴唇微启，处于说话状态"),
        json.dumps({"keyframes": [_state(1, 0, None, role="START")]}, ensure_ascii=False),
    ])
    result = await shot_api.plan_video_keyframes(
        novel.id,
        chapter.id,
        shot.id,
        PlanVideoKeyframesRequest(force=True),
        db_session,
        NovelRepository(db_session),
        ChapterRepository(db_session),
        ShotRepository(db_session),
        PromptTemplateRepository(db_session),
        llm,
    )
    persisted = json.loads(ShotRepository(db_session).get_by_id(shot.id).video_director_plan)
    assert result["success"] is True
    assert len(llm.calls) == 2
    retry_payload = _payload(llm.calls[1]["user_content"])
    retry_instruction = retry_payload["retry_instruction"]
    assert "violations 是已发现问题" in retry_instruction
    assert "不是完整错误列表" in retry_instruction
    assert "重新审查整个 candidate plan" in retry_instruction
    assert "逐个检查所有 Visual States" in retry_instruction
    assert "未被 previous failure 明确列出" in retry_instruction
    assert "完整、整体重新验证后的 canonical plan" in retry_instruction
    assert len(retry_payload["previous_failed_attempts"]) == 1
    assert persisted["canonical_visual_plan"] is True
    assert persisted["keyframes"] == [_state(1, 0.0, "", role="START")]
    assert "嘴唇微启" not in json.dumps(persisted["keyframes"], ensure_ascii=False)


@pytest.mark.asyncio
async def test_planner_hard_fails_after_second_speech_violation_without_persisting_states(db_session, monkeypatch):
    novel, chapter, shot = _planning_fixture(db_session)
    monkeypatch.setattr(shot_api, "get_style", lambda *_args, **_kwargs: ("", None))
    llm = SequenceLLM([
        _planner_content("皇帝嘴唇微启，处于说话状态"),
        _planner_content("侍从1回答皇帝"),
    ])
    with pytest.raises(HTTPException, match="VISUAL_STATE_SPEECH_AUTHORITY_VIOLATION"):
        await shot_api.plan_video_keyframes(
            novel.id,
            chapter.id,
            shot.id,
            PlanVideoKeyframesRequest(force=True),
            db_session,
            NovelRepository(db_session),
            ChapterRepository(db_session),
            ShotRepository(db_session),
            PromptTemplateRepository(db_session),
            llm,
        )
    persisted = json.loads(ShotRepository(db_session).get_by_id(shot.id).video_director_plan)
    assert len(llm.calls) == 2
    assert persisted["existing_marker"] is True
    assert "canonical_visual_plan" not in persisted
    assert "嘴唇微启" not in json.dumps(persisted.get("keyframes", []), ensure_ascii=False)
