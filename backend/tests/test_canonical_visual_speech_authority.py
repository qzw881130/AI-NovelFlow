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
        return SimpleNamespace(id="system-10", name="关键帧过渡规划", template="system #10")

    def resolve_for_type(self, _selected_id, template_type):
        return self.get_default_system_template(template_type)


def test_clean_canonical_visual_state_normalizes():
    states, _, _ = shot_api._normalize_keyframe_planner_result({"keyframes": [
        _state(1, 0, None, role="START"),
        _state(2, 4, "皇帝皱眉，转头看向侍从1"),
    ]}, None, 8)
    assert states[1]["description"] == "皇帝皱眉，转头看向侍从1"


@pytest.mark.parametrize("description", [
    "皇帝嘴唇微启，处于说话状态",
    "侍从1回答皇帝",
    "禁止新增说话；皇帝没有开口。",
    "皇帝低声说道，宫廷总管望向他。",
])
def test_canonical_visual_state_does_not_block_speech_words(description):
    states, _, validation = shot_api._normalize_keyframe_planner_result({"keyframes": [
        _state(1, 0, None, role="START"),
        _state(2, 4, description),
    ]}, None, 8)
    assert validation["passed"]
    assert states[1]["description"] == description


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


def test_empty_start_resolves_declared_shot_reference_without_dynamic_story():
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
        "description": shot.description,
    }
    assert payload["to_keyframe"]["description"] == "皇帝抬起右手"
    assert payload["segment_index"] == 1
    assert payload["shot"]["characters"] == ["皇帝", "侍从1"]
    assert payload["shot"]["scene"] == "hall"
    assert payload["shot"]["props"] == []
    assert payload["shot"]["duration"] == 18
    assert payload["shot"]["continuity_mode"] == "NORMAL"
    assert payload["start_visual_resolution"][0]["status"] == "RESOLVED"
    assert "皇帝开口询问，侍从回答" not in serialized
    assert "causal_context" not in payload  # Unmarked V1 still excludes Dialogue/story input.


@pytest.mark.parametrize("position", ["from", "to"])
def test_transition_endpoint_speech_words_are_projected_without_blocking(position):
    from_state = _state(1, 0, "皇帝站在镜前", role="START")
    to_state = _state(2, 4, "皇帝抬起右手")
    if position == "from":
        from_state["description"] = "皇帝嘴唇微启，处于说话状态"
    else:
        to_state["description"] = "侍从1回答皇帝"
    payload = _payload(shot_api._build_keyframe_transition_user_content(
        _shot(), from_state, to_state, 1,
    ))
    assert payload["from_keyframe"]["description"] == from_state["description"]
    assert payload["to_keyframe"]["description"] == to_state["description"]


@pytest.mark.asyncio
async def test_transition_llm_receives_visual_state_with_speech_words(monkeypatch):
    monkeypatch.setattr(shot_api, "get_style", lambda *_args, **_kwargs: ("", None))
    llm = SequenceLLM([_transition_content("皇帝低声说道")])
    transitions = await shot_api._plan_keyframe_transitions(
        FakeDB(),
        SimpleNamespace(id="novel", keyframe_transition_prompt_template_id=None),
        SimpleNamespace(id="chapter"),
        _shot(),
        [_state(1, 0, "皇帝站在镜前", role="START"),
         _state(2, 4, "皇帝嘴唇微启，处于说话状态")],
        FakeTemplateRepo(), llm,
    )
    assert len(llm.calls) == 1
    assert transitions[0]["transition_description"] == "皇帝低声说道"


@pytest.mark.asyncio
async def test_transition_output_speech_words_do_not_cause_retry(monkeypatch):
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
    assert len(llm.calls) == 1
    assert transitions[0]["transition_description"] == "皇帝嘴唇微启，开始说话"


@pytest.mark.asyncio
async def test_transition_output_speech_words_do_not_overwrite_existing_plan(monkeypatch):
    monkeypatch.setattr(shot_api, "get_style", lambda *_args, **_kwargs: ("", None))
    llm = SequenceLLM([
        _transition_content("皇帝嘴唇微启，开始说话"),
        _transition_content("侍从2闭嘴，皇帝开始回答"),
    ])
    shot = _shot()
    shot.video_director_plan = json.dumps({"transitions": [{"old": True}]})
    transitions = await shot_api._plan_keyframe_transitions(
        FakeDB(),
        SimpleNamespace(id="novel", keyframe_transition_prompt_template_id=None),
        SimpleNamespace(id="chapter"),
        shot,
        [_state(1, 0, "皇帝站在镜前", role="START"), _state(2, 4, "皇帝抬起右手")],
        FakeTemplateRepo(), llm,
    )
    assert len(llm.calls) == 1
    assert transitions[0]["transition_description"] == "皇帝嘴唇微启，开始说话"
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
async def test_planner_accepts_visual_state_speech_words_without_retry(db_session, monkeypatch):
    novel, chapter, shot = _planning_fixture(db_session)
    monkeypatch.setattr(shot_api, "get_style", lambda *_args, **_kwargs: ("", None))
    async def no_transitions(*_args, **_kwargs):
        return []
    monkeypatch.setattr(shot_api, "_plan_keyframe_transitions", no_transitions)
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
    assert len(llm.calls) == 1
    assert persisted["canonical_visual_plan"] is True
    assert persisted["keyframes"][1]["description"] == "皇帝嘴唇微启，处于说话状态"


@pytest.mark.asyncio
async def test_planner_speech_words_do_not_replace_first_candidate(db_session, monkeypatch):
    novel, chapter, shot = _planning_fixture(db_session)
    monkeypatch.setattr(shot_api, "get_style", lambda *_args, **_kwargs: ("", None))
    async def no_transitions(*_args, **_kwargs):
        return []
    monkeypatch.setattr(shot_api, "_plan_keyframe_transitions", no_transitions)
    llm = SequenceLLM([
        _planner_content("皇帝嘴唇微启，处于说话状态"),
        _planner_content("侍从1回答皇帝"),
    ])
    result = await shot_api.plan_video_keyframes(
        novel.id, chapter.id, shot.id, PlanVideoKeyframesRequest(force=True),
        db_session, NovelRepository(db_session), ChapterRepository(db_session),
        ShotRepository(db_session), PromptTemplateRepository(db_session), llm,
    )
    persisted = json.loads(ShotRepository(db_session).get_by_id(shot.id).video_director_plan)
    assert result["success"] is True
    assert len(llm.calls) == 1
    assert persisted["keyframes"][1]["description"] == "皇帝嘴唇微启，处于说话状态"
