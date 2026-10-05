import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import clip_planner


RAW_DESCRIPTION = "皇帝开口询问，侍从回答后故事继续"
RAW_VIDEO_DESCRIPTION = "两人继续交谈，镜头保持同一房间"
EXACT_DIALOGUE = "城门可曾关闭？"


DIRECTOR_BOUNDARY_CASES = [
    pytest.param("ABC", "AB", "三人沿走廊前行，C正在走向画面边缘。",
                 "A、B继续前行，C已出画；没有新Beat或镜头重建需求。",
                 "C继续走出画面，A、B的步行方向和镜头跟随必须跨边界连续。",
                 "CONTINUOUS", id="T1-exit-C-does-not-force-cut"),
    pytest.param("AB", "A", "A、B前行，B逐渐移向画面边缘。",
                 "A继续向门边前行，B已出画。",
                 "B自然走出画面，A的步行轨迹与相机跟随必须持续。",
                 "CONTINUOUS", id="T2-exit-B-continuing-action"),
    pytest.param("A", "AC", "A单人稳定近景；没有进行中的跨边界动作。",
                 "下一视觉Beat中A、C已在新的双人构图内；不要求展示C入画过程。",
                 "新的A+C双人场面可以独立建立，不要求继承原单人镜头的运动阶段。",
                 "CUT", id="T3-reappearance-without-required-entry"),
    pytest.param("A", "AC", "A在门边等待，门已开始打开，C仍在画外。",
                 "C从门外进入并走向A，门的运动与走入过程必须不间断地延续。",
                 "继续打开门，C从门外走入并走到A身旁；必须从上一状态连续表现。",
                 "CONTINUOUS", id="T4-required-uninterrupted-entry"),
    pytest.param("AC", "ABC", "A、C在稳定构图内；上一动作已结束。",
                 "新视觉Beat重新建立A、B、C三人构图和焦点；B已在场，无须展示入场过程。",
                 "独立建立三人空间关系，没有必须跨边界延续的动作或镜头条件。",
                 "CUT", id="T5-new-cast-composition-beat"),
    pytest.param("ABC", "ABC", "三人沿既定路线走动，摄影机正在连续横移。",
                 "三人继续原动作；站位、物体状态和摄影机运动阶段必须精确延续。",
                 "延续三人动作、相机横移和blocking，不能重置运动阶段。",
                 "CONTINUOUS", id="T6-unchanged-cast-required-continuity"),
    pytest.param("ABC", "ABC", "三人稳定站立，动作结束，无必须继承的运动阶段。",
                 "三人仍可见，新的reaction framing以A的反应为重心，可独立重建构图。",
                 "建立新的反应镜头与视觉焦点，不要求连续相机运动；没有人物增减。",
                 "CUT", id="T7-unchanged-cast-independent-reaction"),
]


def _shot(
    tmp_path,
    *,
    continuity_mode="NORMAL",
    dialogues=None,
    states=None,
    transitions=None,
):
    shot_image = tmp_path / "shot.png"
    shot_image.write_bytes(b"shot")
    states = states or [
        {"index": 1, "role": "START", "time_seconds": 0, "description": None, "timed_visual_target": False},
        {"index": 2, "role": "INTERMEDIATE", "time_seconds": 6, "description": "侍从把奏折递到桌案中央", "timed_visual_target": False},
        {"index": 3, "role": "INTERMEDIATE", "time_seconds": 6.5, "description": "皇帝独立坐在新的正面构图中", "timed_visual_target": False},
        {"index": 4, "role": "END", "time_seconds": 12, "description": "皇帝在当前构图中保持最终姿态", "timed_visual_target": False},
    ]
    transitions = transitions or [
        {"from_keyframe_index": 1, "to_keyframe_index": 2, "start_time": 0, "end_time": 6, "transition_description": "侍从向前移动奏折"},
        {"from_keyframe_index": 2, "to_keyframe_index": 3, "start_time": 6, "end_time": 12, "transition_description": "镜头切到皇帝正面中景"},
    ]
    return SimpleNamespace(
        id="continuity-shot",
        chapter_id="continuity-chapter",
        duration=12,
        continuity_mode=continuity_mode,
        description=RAW_DESCRIPTION,
        video_description=RAW_VIDEO_DESCRIPTION,
        characters=json.dumps(["皇帝", "侍从"], ensure_ascii=False),
        scene="大殿",
        props=json.dumps(["奏折"], ensure_ascii=False),
        dialogues=json.dumps(dialogues or [], ensure_ascii=False),
        image_url=str(shot_image),
        image_path=str(shot_image),
        keyframes="[]",
        video_director_plan=json.dumps({
            "canonical_visual_plan": True,
            "keyframes": states,
            "transitions": transitions,
        }, ensure_ascii=False),
    )


def _composition_response(response, payload):
    """Mock the new director output explicitly; production never auto-upgrades plans."""
    result = json.loads(json.dumps(response))
    for clip in result:
        clip['early_composition_state_id'] = None
        if clip.get('continuity_to_previous') != 'CONTINUOUS' or clip.get('selected_temporal_target_ids'):
            continue
        start, end = clip['start_time'], clip['end_time']
        first_speech = min((max(start, e['start_time']) for e in payload['speech_timing_intervals']
                            if e['end_time'] > start and e['start_time'] < end), default=end)
        early = [v for v in payload['visual_state_candidates'] if start + .05 < v['time_seconds'] < min(end, first_speech)]
        if early:
            clip['early_composition_state_id'] = early[0]['visual_state_id']
    return result


def _fake_planner(monkeypatch, response, captured):
    class FakePromptTemplateService:
        def __init__(self, _db):
            pass

        def get_default_system_template(self, _name):
            return SimpleNamespace(template="planner", name="planner")

    class FakeLLMService:
        async def chat_completion(self, **kwargs):
            captured.update(kwargs)
            return {"success": True, "content": json.dumps({"clips": _composition_response(response, json.loads(kwargs["user_content"]))}, ensure_ascii=False)}

    monkeypatch.setattr(clip_planner, "PromptTemplateService", FakePromptTemplateService)
    monkeypatch.setattr(clip_planner, "LLMService", FakeLLMService)


def test_director_prompt_distinguishes_semantic_reappearance_from_required_entry():
    prompt = (Path(__file__).parents[1] / "prompt_templates" / "10A_NovelFlow_ClipExecutionPlanner_V1.txt").read_text()
    for marker in (
        "Previous AV is continuity conditioning, not a default required resource",
        "CROSS-BOUNDARY ACTION", "SPATIAL / CAMERA CONTINUITY", "CHARACTER SET CHANGE",
        "NATURAL EDIT POINT", "RE-ESTABLISHMENT VALUE",
        "EXIT does not imply CUT. ENTER does not imply CUT either",
        "already present in the next visual beat from a required uninterrupted entry action",
        "inputs do not establish actual visibility in the generated Previous AV tail",
        "Do not assume missing or ambiguous descriptions prove a character absent",
        "speech timing intervals alone cannot supply speaker/focus or continuity authority",
        "never promote a shared-boundary/carry-in state to ownership",
        "ABC -> AB", "AB -> A", "A -> AC", "AC -> ABC", "ABC -> ABC",
    ):
        assert marker in prompt


def test_director_prompt_orders_continuity_before_feasibility_and_reports_conflict():
    prompt = (Path(__file__).parents[1] / "prompt_templates" / "10A_NovelFlow_ClipExecutionPlanner_V1.txt").read_text()
    assert prompt.index("Continuity authority precedes execution feasibility") < prompt.index("3. Early Composition selection")
    assert "must NEVER turn an otherwise CONTINUOUS boundary into CUT" in prompt
    assert "Do not substitute CUT to satisfy coverage" in prompt
    assert "EARLY_COMPOSITION_COVERAGE_INVALID" in prompt
    assert "existing reason" in prompt
    assert "Same-scene genuine" in prompt and "independent edits remain valid" in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("continuity_mode", ["NORMAL", "CONTINUOUS_TAKE"])
@pytest.mark.parametrize("before,after,previous_action,next_action,transition,decision", DIRECTOR_BOUNDARY_CASES)
async def test_director_character_boundary_decisions_preserve_existing_planner_contract(
    tmp_path, monkeypatch, continuity_mode, before, after, previous_action, next_action, transition, decision,
):
    # These are contract regressions with a mocked director, not evidence that a
    # real LLM has learned the decision. No program classifies ENTER/EXIT/CUT.
    def description(characters, action):
        return "Scene: 同一场景\nCharacters:\n" + "\n".join(
            f"- {name}: 在本状态中可见。" for name in characters
        ) + "\nAction: " + action

    state_image = tmp_path / "canonical-state.png"
    state_image.write_bytes(b"test visual asset")
    states = [
        {"index": 1, "role": "START", "time_seconds": 0, "description": None, "timed_visual_target": False},
        {"index": 2, "role": "INTERMEDIATE", "time_seconds": 6,
         "description": description(before, previous_action), "timed_visual_target": False},
        {"index": 3, "role": "INTERMEDIATE", "time_seconds": 6.5,
         "description": description(after, next_action), "timed_visual_target": False, "image_url": str(state_image)},
        {"index": 4, "role": "END", "time_seconds": 12,
         "description": description(after, "保持本视觉Beat的最终可见状态。"), "timed_visual_target": False},
    ]
    transitions = [
        {"from_keyframe_index": 1, "to_keyframe_index": 2, "start_time": 0, "end_time": 6,
         "transition_description": previous_action},
        {"from_keyframe_index": 2, "to_keyframe_index": 3, "start_time": 6, "end_time": 6.5,
         "transition_description": transition},
        {"from_keyframe_index": 3, "to_keyframe_index": 4, "start_time": 6.5, "end_time": 12,
         "transition_description": "保持当前视觉事实，不增添其他人物。"},
    ]
    shot = _shot(tmp_path, continuity_mode=continuity_mode, states=states, transitions=transitions)
    shot.characters = json.dumps(["A", "B", "C"])
    original_plan = shot.video_director_plan
    response = [
        {"clip_index": 1, "start_time": 0, "end_time": 6, "continuity_to_previous": "NONE", "selected_temporal_target_ids": []},
        {"clip_index": 2, "start_time": 6, "end_time": 12, "continuity_to_previous": decision, "selected_temporal_target_ids": [],
         "previous_clip_index": 1 if decision == "CONTINUOUS" else None, "reason": transition},
    ]
    captured = {}
    _fake_planner(monkeypatch, response, captured)
    prompt = (Path(__file__).parents[1] / "prompt_templates" / "10A_NovelFlow_ClipExecutionPlanner_V1.txt").read_text()
    monkeypatch.setattr(clip_planner.PromptTemplateService, "get_default_system_template",
                        lambda _self, _name: SimpleNamespace(template=prompt, name="Clip Execution Planner"))
    anchors = []
    clips, validation = await clip_planner.plan_clips(None, SimpleNamespace(id="novel"), shot, anchors)
    payload = json.loads(captured["user_content"])

    assert validation["passed"] is True, validation
    assert captured["system_prompt"] == prompt
    assert payload["shot"]["characters"] == ["A", "B", "C"]
    assert payload["visual_state_candidates"][1]["description"] == states[1]["description"]
    assert payload["visual_state_candidates"][2]["description"] == states[2]["description"]
    assert payload["transition_context"] == transitions
    assert "character_transition" not in payload and "clip_visible_characters" not in payload
    assert "available_generation_inputs" not in payload
    assert payload["speech_timing_intervals"] == []
    assert clips[1]["continuity_to_previous"] == decision
    assert clips[1]["capability"] == ("TEMPORAL_EXTEND" if decision == "CONTINUOUS" else "GENERATE")
    assert clips[1]["previous_clip_index"] == (1 if decision == "CONTINUOUS" else None)
    assert clips[1]["visual_state_indexes"] == [3, 4]
    assert clips[1]["carry_in_state_index"] == 2
    assert clips[1]["requires_temporal_control"] is (decision == "CONTINUOUS")
    assert clips[1]["reason"] == transition
    assert [a["source"]["id"] for a in anchors] == (["KF3"] if decision == "CONTINUOUS" else [])
    assert shot.video_director_plan == original_plan


async def _plan(monkeypatch, shot, response):
    captured = {}
    _fake_planner(monkeypatch, response, captured)
    temporal_anchors = []
    clips, validation = await clip_planner.plan_clips(
        None,
        SimpleNamespace(id="novel"),
        shot,
        temporal_anchors,
    )
    return clips, validation, temporal_anchors, json.loads(captured["user_content"])


def test_clip_planner_input_projects_only_visual_context_and_speech_intervals(tmp_path):
    dialogues = [{
        "dialogue_id": "D1",
        "character_name": "皇帝",
        "text": EXACT_DIALOGUE,
        "start_time": 1.0,
        "end_time": 4.0,
    }]
    payload = clip_planner.build_clip_planner_input(_shot(tmp_path, dialogues=dialogues), [])
    serialized = json.dumps(payload, ensure_ascii=False)

    assert payload["shot"] == {
        "id": "continuity-shot",
        "duration": 12,
        "continuity_mode": "NORMAL",
        "characters": ["皇帝", "侍从"],
        "scene": "大殿",
        "props": ["奏折"],
    }
    assert payload["speech_timing_intervals"] == [{
        "event_id": "D1",
        "start_time": 1.0,
        "end_time": 4.0,
    }]
    assert len(payload["visual_state_candidates"]) == 4
    assert len(payload["transition_context"]) == 2
    assert "capabilities" not in payload
    assert "official_dialogue_timeline" not in payload
    assert "temporal_anchors" not in payload
    for forbidden in (RAW_DESCRIPTION, RAW_VIDEO_DESCRIPTION, EXACT_DIALOGUE, '"speaker"', '"dialogues"'):
        assert forbidden not in serialized


@pytest.mark.asyncio
async def test_t02_dialogue_boundary_with_object_handoff_preserves_visual_continuous(tmp_path, monkeypatch):
    shot = _shot(tmp_path, dialogues=[{
        "dialogue_id": "D1", "character_name": "皇帝", "text": EXACT_DIALOGUE,
        "start_time": 1.0, "end_time": 6.0,
    }])
    response = [
        {"clip_index": 1, "start_time": 0, "end_time": 6, "continuity_to_previous": "NONE", "selected_temporal_target_ids": [], "reason": "initial visual setup"},
        {"clip_index": 2, "start_time": 6, "end_time": 12, "continuity_to_previous": "CONTINUOUS", "selected_temporal_target_ids": [], "reason": "the object handoff and hand positions continue from the actual prior ending"},
    ]

    clips, validation, _, llm_payload = await _plan(monkeypatch, shot, response)

    assert validation["passed"] is True, validation
    assert clips[1]["continuity_to_previous"] == "CONTINUOUS"
    assert clips[1]["capability"] == "TEMPORAL_EXTEND"
    assert clips[1]["previous_clip_index"] == 1
    assert llm_payload["speech_timing_intervals"][0] == {"event_id": "D1", "start_time": 1.0, "end_time": 6.0}


@pytest.mark.asyncio
async def test_t03_dialogue_end_and_story_continuity_preserve_visual_cut(tmp_path, monkeypatch):
    shot = _shot(tmp_path, dialogues=[{
        "dialogue_id": "D1", "character_name": "皇帝", "text": EXACT_DIALOGUE,
        "start_time": 1.0, "end_time": 6.0,
    }])
    response = [
        {"clip_index": 1, "start_time": 0, "end_time": 6, "continuity_to_previous": "NONE", "selected_temporal_target_ids": []},
        {"clip_index": 2, "start_time": 6, "end_time": 12, "continuity_to_previous": "CUT", "selected_temporal_target_ids": [], "reason": "independently grounded exterior setup"},
    ]

    clips, validation, _, _ = await _plan(monkeypatch, shot, response)

    assert validation["passed"] is True, validation
    assert clips[1]["continuity_to_previous"] == "CUT"
    assert clips[1]["capability"] == "GENERATE"
    assert clips[1]["previous_clip_index"] is None
    assert clips[1]["carry_in_state_index"] == 2


@pytest.mark.asyncio
async def test_t08_no_dialogue_spatial_dependency_preserves_continuous(tmp_path, monkeypatch):
    shot = _shot(tmp_path, dialogues=[], transitions=[
        {"from_keyframe_index": 1, "to_keyframe_index": 2, "start_time": 0, "end_time": 6, "transition_description": "人物从庭院持续走入回廊"},
        {"from_keyframe_index": 2, "to_keyframe_index": 3, "start_time": 6, "end_time": 12, "transition_description": "保持运动方向走到门口"},
    ])
    response = [
        {"clip_index": 1, "start_time": 0, "end_time": 6, "continuity_to_previous": "NONE", "selected_temporal_target_ids": []},
        {"clip_index": 2, "start_time": 6, "end_time": 12, "continuity_to_previous": "CONTINUOUS", "selected_temporal_target_ids": [], "reason": "walking direction and body trajectory depend on the prior ending"},
    ]

    clips, validation, _, llm_payload = await _plan(monkeypatch, shot, response)

    assert validation["passed"] is True, validation
    assert llm_payload["speech_timing_intervals"] == []
    assert clips[1]["continuity_to_previous"] == "CONTINUOUS"
    assert clips[1]["capability"] == "TEMPORAL_EXTEND"


@pytest.mark.asyncio
async def test_t09_no_dialogue_timed_continuous_state_derives_temporal_requirement(tmp_path, monkeypatch):
    timed_image = tmp_path / "timed.png"
    timed_image.write_bytes(b"timed")
    states = [
        {"index": 1, "role": "START", "time_seconds": 0, "description": None, "timed_visual_target": False},
        {"index": 2, "role": "INTERMEDIATE", "time_seconds": 6, "description": "骑者持续前行", "timed_visual_target": False},
        {"index": 3, "role": "INTERMEDIATE", "time_seconds": 9, "description": "骑者回头", "timed_visual_target": True, "image_url": str(timed_image)},
        {"index": 4, "role": "END", "time_seconds": 12, "description": "骑者拔剑", "timed_visual_target": False},
    ]
    shot = _shot(tmp_path, dialogues=[], states=states)
    response = [
        {"clip_index": 1, "start_time": 0, "end_time": 6, "continuity_to_previous": "NONE", "selected_temporal_target_ids": []},
        {"clip_index": 2, "start_time": 6, "end_time": 12, "continuity_to_previous": "CONTINUOUS", "selected_temporal_target_ids": ["KF3"], "reason": "rider motion continues from prior ending"},
    ]

    clips, validation, anchors, _ = await _plan(monkeypatch, shot, response)

    assert validation["passed"] is True, validation
    assert clips[1]["continuity_to_previous"] == "CONTINUOUS"
    assert clips[1]["requires_temporal_control"] is True
    assert clips[1]["capability"] == "TEMPORAL_EXTEND"
    assert clips[1]["selected_temporal_target_ids"] == ["KF3"]
    assert [item["source"]["id"] for item in anchors] == ["KF3"]


@pytest.mark.asyncio
async def test_same_scene_same_people_same_conversation_can_be_cut_under_continuous_take(tmp_path, monkeypatch):
    shot = _shot(tmp_path, continuity_mode="CONTINUOUS_TAKE", dialogues=[{
        "dialogue_id": "D1", "character_name": "皇帝", "text": EXACT_DIALOGUE,
        "start_time": 1.0, "end_time": 10.0,
    }])
    response = [
        {"clip_index": 1, "start_time": 0, "end_time": 6, "continuity_to_previous": "NONE", "selected_temporal_target_ids": []},
        {"clip_index": 2, "start_time": 6, "end_time": 12, "continuity_to_previous": "CUT", "selected_temporal_target_ids": [], "reason": "new independently grounded frontal composition"},
    ]

    clips, validation, _, llm_payload = await _plan(monkeypatch, shot, response)

    assert validation["passed"] is True, validation
    assert llm_payload["shot"]["continuity_mode"] == "CONTINUOUS_TAKE"
    assert clips[1]["continuity_to_previous"] == "CUT"
    assert clips[1]["capability"] == "GENERATE"


@pytest.mark.asyncio
async def test_llm_payload_excludes_physical_and_legacy_execution_authority(tmp_path, monkeypatch):
    shot = _shot(tmp_path)
    response = [{"clip_index": 1, "start_time": 0, "end_time": 12, "continuity_to_previous": "NONE", "selected_temporal_target_ids": []}]

    _, validation, _, llm_payload = await _plan(monkeypatch, shot, response)

    assert validation["passed"] is True, validation
    assert "available_generation_inputs" not in llm_payload
    assert "capabilities" not in llm_payload
    assert "temporal_anchors" not in llm_payload
    serialized = json.dumps(llm_payload, ensure_ascii=False)
    for forbidden in (
        "SINGLE_FRAME", "FIRST_LAST_FRAME", "MULTI_KEYFRAME", "supported_frame_counts",
        "picture_index", "previous_task_id", "workflow_id", "reference_manifest",
    ):
        assert forbidden not in serialized


def _sequence_planner(monkeypatch, responses, calls, before_call=None):
    _fake_planner(monkeypatch, [], {})

    class FakeLLMService:
        async def chat_completion(self, **kwargs):
            if before_call:
                before_call()
            assert len(calls) < len(responses), "unexpected extra planner call"
            response = responses[len(calls)]
            calls.append(json.loads(kwargs["user_content"]))
            return {"success": True, "content": json.dumps({"clips": _composition_response(response, calls[-1])})}

    monkeypatch.setattr(clip_planner, "LLMService", FakeLLMService)


def _two_clips(boundary, continuity, reason="raw KF4 ending -> KF5 first-owned", selected=None):
    return [
        {"clip_index": 1, "start_time": 0, "end_time": boundary, "continuity_to_previous": "NONE", "selected_temporal_target_ids": []},
        {"clip_index": 2, "start_time": boundary, "end_time": 18,
         "continuity_to_previous": continuity, "selected_temporal_target_ids": selected or [], "reason": reason},
    ]


def _shot11(tmp_path, *, timed=False):
    image = tmp_path / "kf4.png"
    image.write_bytes(b"kf4")
    states = [
        {"index": index, "role": "START" if index == 1 else ("END" if index == 6 else "INTERMEDIATE"),
         "time_seconds": time, "description": f"visible state {index}",
         "timed_visual_target": timed and index == 4, "image_url": str(image)}
        for index, time in enumerate([0, 2, 5, 9.5, 14.5, 18], 1)
    ]
    dialogues = [
        {"dialogue_id": f"D{index}", "character_name": "皇帝", "text": EXACT_DIALOGUE,
         "start_time": start, "end_time": end}
        for index, (start, end) in enumerate([(1, 3), (3.2, 6.95), (7.15, 11.9), (12.1, 17.35)], 1)
    ]
    shot = _shot(tmp_path, states=states, dialogues=dialogues)
    shot.duration = 18
    return shot


@pytest.mark.asyncio
@pytest.mark.parametrize("raw_continuity", ["CONTINUOUS", "CUT"])
@pytest.mark.parametrize("retry_continuity,capability", [("CUT", "GENERATE"), ("CONTINUOUS", "EXTEND")])
async def test_shot11_revalidates_both_decisions_against_normalized_structure(
    tmp_path, monkeypatch, raw_continuity, retry_continuity, capability,
):
    shot = _shot11(tmp_path)
    calls = []
    fresh_reason = "KF3 ending -> KF4 visual dependency" if retry_continuity == "CONTINUOUS" else "independent KF4 visual start"
    raw = _two_clips(9.5, raw_continuity)
    _sequence_planner(monkeypatch, [raw, _two_clips(7.15, retry_continuity, fresh_reason)], calls)
    projected_calls = []
    original_projection = clip_planner._project_temporal_targets

    def final_projection(clips, candidates, duration):
        assert len(calls) == 2
        assert all("capability" not in clip for clip in clips)
        projected_calls.append(True)
        original_projection(clips, candidates, duration)

    monkeypatch.setattr(clip_planner, "_project_temporal_targets", final_projection)
    if retry_continuity == "CONTINUOUS":
        with pytest.raises(ValueError, match="EARLY_COMPOSITION_COVERAGE_INVALID"):
            await clip_planner.plan_clips(None, SimpleNamespace(id="novel"), shot, [])
        assert len(calls) == 2 and projected_calls == [True]
        assert calls[1]['continuity_revalidation']['normalized_clips'][1]['start_time'] == 7.15
        return
    clips, validation = await clip_planner.plan_clips(None, SimpleNamespace(id="novel"), shot, [])
    candidates = calls[0]["visual_state_candidates"]
    raw_structure = clip_planner._canonical_continuity_structure(raw, candidates)
    assert raw_structure[1]["previous_ending_state_index"] == 4
    assert raw_structure[1]["first_owned_state_index"] == 5
    assert raw_structure[1]["carry_in_state_index"] == 4
    constraints = calls[1]["continuity_revalidation"]["normalized_clips"]
    assert [(item["start_time"], item["end_time"]) for item in constraints] == [(0, 7.15), (7.15, 18)]
    assert [item["visual_state_indexes"] for item in constraints] == [[1, 2, 3], [4, 5, 6]]
    assert constraints[1]["previous_ending_state_index"] == 3
    assert constraints[1]["first_owned_state_index"] == 4
    assert constraints[1]["carry_in_state_index"] == 3
    assert "continuity_revalidation" not in calls[0]
    assert len(calls) == 2 and projected_calls == [True]
    assert validation["passed"] is True, validation
    assert clips[1]["continuity_to_previous"] == retry_continuity
    assert clips[1]["capability"] == capability
    assert clips[1]["reason"] == fresh_reason
    assert "raw KF4 ending" not in clips[1]["reason"]
    assert [[item["dialogue_id"] for item in clip["dialogue_assignment"]] for clip in clips] == [["D1", "D2"], ["D3", "D4"]]
    serialized = json.dumps(calls[1], ensure_ascii=False)
    for forbidden in (RAW_DESCRIPTION, RAW_VIDEO_DESCRIPTION, EXACT_DIALOGUE, '"speaker"', '"dialogues"'):
        assert forbidden not in serialized
    assert all(set(item) == {"event_id", "start_time", "end_time"} for item in calls[1]["speech_timing_intervals"])


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", [6, 6.0000000001])
async def test_same_premise_and_harmless_rounding_use_one_call(tmp_path, monkeypatch, boundary):
    shot = _shot(tmp_path)
    calls = []
    response = _two_clips(boundary, "CONTINUOUS", "unchanged visual dependency")
    response[1]["end_time"] = 12
    _sequence_planner(monkeypatch, [response], calls)
    clips, validation = await clip_planner.plan_clips(None, SimpleNamespace(id="novel"), shot, [])
    assert len(calls) == 1
    assert validation["passed"] is True, validation
    assert clips[1]["start_time"] == 6
    assert clips[1]["reason"] == "unchanged visual dependency"
    assert clips[1]["capability"] == "TEMPORAL_EXTEND"


@pytest.mark.asyncio
async def test_duration_repair_revalidates_state_identity_not_shot11_special_case(tmp_path, monkeypatch):
    states = [
        {"index": index, "role": "START" if index == 1 else "INTERMEDIATE",
         "time_seconds": time, "description": f"state {index}", "timed_visual_target": False}
        for index, time in enumerate([0, 3.5, 9, 18], 1)
    ]
    shot = _shot(tmp_path, states=states)
    shot.duration = 18
    calls = []
    _sequence_planner(monkeypatch, [_two_clips(3, "CUT"), _two_clips(4, "CONTINUOUS", "KF2 -> KF3 dependency")], calls)
    clips, validation = await clip_planner.plan_clips(None, SimpleNamespace(id="novel"), shot, [])
    assert len(calls) == 2
    assert validation["passed"] is True, validation
    assert [clip["visual_state_indexes"] for clip in clips] == [[1, 2], [3, 4]]
    assert clips[1]["start_time"] == 4
    assert clips[1]["carry_in_state_index"] == 2
    assert clips[1]["capability"] == "TEMPORAL_EXTEND"


@pytest.mark.asyncio
async def test_numeric_boundary_move_with_same_state_premise_does_not_mechanically_retry(tmp_path, monkeypatch):
    states = [
        {"index": index, "role": "START" if index == 1 else "INTERMEDIATE",
         "time_seconds": time, "description": f"state {index}", "timed_visual_target": False}
        for index, time in enumerate([0, 12, 16, 18], 1)
    ]
    shot = _shot(tmp_path, states=states)
    shot.duration = 18
    calls = []
    _sequence_planner(monkeypatch, [_two_clips(15, "CUT", "independent state 3")], calls)
    clips, validation = await clip_planner.plan_clips(None, SimpleNamespace(id="novel"), shot, [])
    assert len(calls) == 1
    assert validation["passed"] is True, validation
    assert clips[1]["start_time"] == 14
    assert clips[1]["visual_state_indexes"] == [3, 4]
    assert clips[1]["carry_in_state_index"] == 2


@pytest.mark.asyncio
async def test_same_identities_with_changed_timed_local_position_require_retry(tmp_path, monkeypatch):
    image = tmp_path / "timed-local.png"
    image.write_bytes(b"timed")
    states = [
        {"index": index, "role": "START" if index == 1 else "INTERMEDIATE",
         "time_seconds": time, "description": f"state {index}",
         "timed_visual_target": index == 3, "image_url": str(image)}
        for index, time in enumerate([0, 12, 16, 18], 1)
    ]
    shot = _shot(tmp_path, states=states)
    shot.duration = 18
    calls, anchors = [], []
    _sequence_planner(monkeypatch, [_two_clips(15, "CONTINUOUS", selected=["KF3"]), _two_clips(14, "CONTINUOUS", "same visual dependency, corrected timed interval", selected=["KF3"])], calls)
    clips, validation = await clip_planner.plan_clips(None, SimpleNamespace(id="novel"), shot, anchors)
    assert validation["passed"] is True, validation
    assert len(calls) == 2
    assert clips[1]["visual_state_indexes"] == [3, 4]
    assert clips[1]["carry_in_state_index"] == 2
    assert clips[1]["capability"] == "TEMPORAL_EXTEND"
    assert anchors[0]["time_seconds"] == 2


@pytest.mark.asyncio
async def test_temporal_projection_uses_validated_retry_boundaries(tmp_path, monkeypatch):
    shot = _shot11(tmp_path, timed=True)
    shot.dialogues = "[]"
    p = json.loads(shot.video_director_plan)
    p["keyframes"][4]["timed_visual_target"] = True
    shot.video_director_plan = json.dumps(p)
    calls, anchors = [], []
    _sequence_planner(monkeypatch, [_two_clips(15, "CONTINUOUS"), _two_clips(14, "CONTINUOUS", "KF4 -> KF5 dependency", selected=["KF5"])], calls)
    clips, validation = await clip_planner.plan_clips(None, SimpleNamespace(id="novel"), shot, anchors)
    assert validation["passed"] is True, validation
    assert len(calls) == 2
    assert clips[1]["capability"] == "TEMPORAL_EXTEND"
    assert clips[1]["selected_temporal_target_ids"] == ["KF5"]
    assert anchors[0]["time_seconds"] == .5
    assert anchors[0]["source"]["id"] == "KF5"


@pytest.mark.asyncio
@pytest.mark.parametrize("retry_boundary", [9.5, 12.1, 8.0])
async def test_second_drift_hard_fails_without_third_call_or_partial_mutation(tmp_path, monkeypatch, retry_boundary):
    shot = _shot11(tmp_path)
    old_plan = shot.video_director_plan
    calls = []
    anchors = [{"anchor_id": "old-anchor"}]
    _sequence_planner(monkeypatch, [_two_clips(9.5, "CONTINUOUS"), _two_clips(retry_boundary, "CUT", "new reason")], calls)
    with pytest.raises(ValueError, match="^CLIP_CONTINUITY_PREMISE_INVALIDATED$"):
        await clip_planner.plan_clips(None, SimpleNamespace(id="novel"), shot, anchors)
    assert len(calls) == 2
    assert shot.video_director_plan == old_plan
    assert anchors == [{"anchor_id": "old-anchor"}]


@pytest.mark.asyncio
async def test_retry_requires_fresh_reason_without_parsing_it(tmp_path, monkeypatch):
    calls = []
    _sequence_planner(monkeypatch, [_two_clips(9.5, "CONTINUOUS"), _two_clips(7.15, "CUT", "")], calls)
    with pytest.raises(ValueError, match="CLIP_CONTINUITY_PREMISE_INVALIDATED: retry reason missing"):
        await clip_planner.plan_clips(None, SimpleNamespace(id="novel"), _shot11(tmp_path), [])
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("retry_succeeds", [True, False])
async def test_normal_persistence_waits_for_validated_whole_plan(
    tmp_path, monkeypatch, db_session, retry_succeeds,
):
    from fastapi import HTTPException
    from app.api.shots import PlanClipsRequest, plan_shot_clips
    from app.models.novel import Novel, Chapter
    from app.models.shot import Shot
    from app.models.task import Task
    from app.repositories import NovelRepository, ShotRepository

    fixture = _shot11(tmp_path)
    old_plan = json.loads(fixture.video_director_plan)
    old_plan.update({"clip_plan_revision": 7, "clip_plan": [{"generated_by_task_id": "old-task", "result_url": "old-clip.mp4"}],
                     "temporal_anchors": [{"anchor_id": "old-anchor"}]})
    serialized_plan = json.dumps(old_plan)
    novel = Novel(id="isolated-novel", title="isolated fixture")
    chapter = Chapter(id=fixture.chapter_id, novel_id=novel.id, number=1, title="isolated chapter")
    shot = Shot(**vars(fixture), index=11, video_url="old-final.mp4", video_status="completed")
    shot.video_director_plan = serialized_plan
    db_session.add_all([novel, chapter, shot])
    db_session.commit()
    calls = []

    def assert_old_authority():
        assert shot.video_director_plan == serialized_plan
        assert shot.video_url == "old-final.mp4"
        assert db_session.query(Task).count() == 0

    retry_boundary = 7.15 if retry_succeeds else 9.5
    _sequence_planner(monkeypatch, [_two_clips(9.5, "CONTINUOUS"), _two_clips(retry_boundary, "CUT", "independent KF4")], calls, assert_old_authority)
    request = PlanClipsRequest(force=True)
    kwargs = dict(novel_id=novel.id, chapter_id=chapter.id, shot_id=shot.id, request=request,
                  db=db_session, novel_repo=NovelRepository(db_session), shot_repo=ShotRepository(db_session))
    if retry_succeeds:
        result = await plan_shot_clips(**kwargs)
        assert result["data"]["revision"] == 8
        assert result["data"]["validation"]["passed"] is True
        current = json.loads(shot.video_director_plan)
        assert current["clip_plan"][1]["capability"] == "GENERATE"
        assert current["clip_plan"][1]["reason"] == "independent KF4"
    else:
        with pytest.raises(HTTPException) as error:
            await plan_shot_clips(**kwargs)
        assert error.value.status_code == 400
        assert error.value.detail == "CLIP_CONTINUITY_PREMISE_INVALIDATED"
        db_session.expire_all()
        assert_old_authority()
    assert len(calls) == 2
    assert db_session.query(Task).count() == 0
