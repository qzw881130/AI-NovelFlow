"""Narrow fake-LLM canonical H3 projection/authority regressions (no media calls)."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from app.models.novel import Novel
from app.models.prompt_template import PromptTemplate
from app.services import video_director_ai as h3
from app.services.clip_execution_compiler import (
    ClipExecutionCompileError, compile_generate_clip, compile_temporal_extend_clip,
)


def state(index, time, role="INTERMEDIATE"):
    return {"index": index, "role": role, "time_seconds": time,
            "description": "微笑，皱眉，嘴角上扬，咬紧牙关，视线变化，身体前倾，转身，抬手。",
            "image_url": "/unexposed.png", "prompt_text": "obsolete image prompt",
            "dialogues": [{"speaker": "wrong", "text": "stale state dialogue"}]}


def dialogue(speaker="Mira", text="请看这里。", event="D1", start=10.5, end=12.0):
    return {"dialogue_id": event, "speaker": speaker, "text": text,
            "start_time": start, "end_time": end, "projection_mode": "intersection"}


def invoke(monkeypatch, *, states=None, capability="EXTEND", images=(), dialogues=(),
           anchors=(), body=None, extra_clip=None, db=None, novel=None,
           shot_characters=None):
    states = states if states is not None else [state(4, 10)]
    refs = [{"slot": slot, "source_keyframe_index": index,
             "source_time_seconds": next(s["time_seconds"] for s in states if s["index"] == index),
             "source_type": "KEYFRAME_IMAGE"} for slot, index in enumerate(images, 1)]
    if body is None:
        pictures = "\n".join(f"{ref['slot']}: <Picture {ref['slot']}> anchors KF{ref['source_keyframe_index']}." for ref in refs)
        body = ("subject_definitions:\n<Subject 1> is Mira, in her current coat.\n"
                "<Subject 2> is Jun, in his current costume.\nkeyframe_timeline:\n" + pictures +
                "\nsummary:\nThe mouth corners of <Subject 1> rise; <Subject 2> clenches his teeth.\n"
                "detailed_description:\nGaze and gestures evolve along the supplied states.\n"
                "overall_soundscape:\nRoom tone, fabric rustle, footsteps and birds outside.")
    calls = []

    class FakeLLM:
        async def chat_completion(self, **kwargs):
            calls.append(kwargs)
            return {"success": True, "content": body}

    monkeypatch.setattr(h3, "LLMService", FakeLLM)
    if novel is None:
        novel = SimpleNamespace(id="fake-novel")
        monkeypatch.setattr(h3, "resolve_prompt_template", lambda *_args: SimpleNamespace(template="override", name="fake override"))
    shot = SimpleNamespace(
        id="fake-shot", index=11, chapter_id="fake-chapter", duration=24,
        description="RAW_DESCRIPTION Mira 低声说话，Jun 回答。",
        video_description="RAW_VIDEO 嘴巴微张，表现低声交谈的视觉状态。",
        dialogues=json.dumps([{"text": "RAW_DIALOGUE", "speaker": "wrong"}]),
        characters=json.dumps(shot_characters or ["Mira", "Jun"], ensure_ascii=False),
        scene="room", props="[]",
        continuity_mode="CONTINUOUS_TAKE", video_director_plan="{}",
    )
    clip = {"clip_index": 2, "start_time": 10, "end_time": 18,
            "visual_state_indexes": [s["index"] for s in states], "carry_in_state_index": 3,
            "capability": capability, "continuity_to_previous": "CUT" if capability == "GENERATE" else "CONTINUOUS",
            "dialogue_assignment": [{"text": "STALE_ASSIGNMENT", "speaker": "wrong"}],
            "execution_contract": {"previous_clip": {"generated_by_task_id": "SECRET_TASK"}},
            **(extra_clip or {})}
    result = asyncio.run(h3.build_h3_video_prompt(
        db=db or SimpleNamespace(commit=lambda: None), novel=novel, shot=shot,
        selected_mode=None, clip=clip, workflow_capability={}, workflow_type="frozen",
        workflow_name="frozen", start_image_url=None, keyframes=states,
        transitions=[{"from_keyframe_index": 3, "to_keyframe_index": states[0]["index"] if states else 4,
                      "transition_description": "抬手，身体前倾，微笑。",
                      "dialogues": [{"text": "STALE_TRANSITION"}]}],
        clip_dialogues=list(dialogues), reference_images=[], temporal_anchors=list(anchors),
        video_reference_manifest={"references": refs},
        previous_av_present=capability != "GENERATE",
    ))
    payload = json.loads(calls[0]["user_content"].split("\n\n", 1)[1])
    return result, payload, calls[0], json.loads(shot.video_director_plan)["ai_calls"][-1]


SHAPES = [
    ([state(4, 10)], "11"),
    ([state(4, 10, "START"), state(5, 18, "END")], "12"),
    ([state(4, 10), state(5, 14), state(6, 18, "END")], "13"),
]


def test_c2_persisted_dialog_box_exclusion_is_not_speech_authority(monkeypatch):
    # Exact failed C2 detailed_description suffix (LLM log e8f9f9c3).
    exclusion = (
        "到达 Clip-local 11.35s 时，让所有微动作自然收束在当前场面的稳定可见状态，不引入后续事件。"
        "画面中不得出现字幕、说明文字、标题、对话框、标志、水印、界面元素或任何其他屏幕文字。"
    )
    body = ("subject_definitions:\n<Subject 1> is Mira.\n<Subject 2> is Jun.\n"
            "summary:\n视线与手势自然变化。\ndetailed_description:\n" + exclusion +
            "\noverall_soundscape:\nRoom tone and fabric rustle.")
    assert h3._canonical_visual_body_speech_issues(body) == []
    prompt, _, _, record = invoke(monkeypatch, states=[], body=body, dialogues=[dialogue()])
    assert exclusion in prompt
    assert record["parsed_result"]["dialogue"]["passed"]
    assert prompt.count("dialogue_timeline:") == 1
    assert "exact_dialogue: 请看这里。" in prompt


@pytest.mark.parametrize("assertion", ["<Subject 2>开始对话。", "<Subject 2>讲话。", "<Subject 2> speaks."])
def test_dialog_box_lexical_boundary_does_not_authorize_actual_speech(monkeypatch, assertion):
    body = ("subject_definitions:\n<Subject 1> is Mira.\n<Subject 2> is Jun.\n"
            "summary:\n画面不得出现字幕、标题、对话框。\ndetailed_description:\n" + assertion +
            "\noverall_soundscape:\nRoom tone.")
    with pytest.raises(RuntimeError, match="CANONICAL_SPEECH_AUTHORITY_OUTSIDE_TIMELINE"):
        invoke(monkeypatch, states=[], body=body, dialogues=[dialogue()])


@pytest.mark.parametrize("states,step", SHAPES)
@pytest.mark.parametrize("capability", ["GENERATE", "EXTEND", "TEMPORAL_EXTEND"])
@pytest.mark.parametrize("has_dialogue", [False, True])
def test_universal_speech_pipeline_all_semantic_shapes_and_capabilities(monkeypatch, states, step, capability, has_dialogue):
    # GENERATE first-owned remains image-backed; continuations can have zero ordinary refs.
    images = (4,) if capability == "GENERATE" else ()
    anchors = [{"anchor_id": "A1", "time_seconds": 0, "source": {"keyframe_index": 4},
                "image_url": "/temporal.png", "frame_position": 1, "slot": 1}] if capability == "TEMPORAL_EXTEND" else []
    prompt, payload, call, record = invoke(monkeypatch, states=states, capability=capability,
                                          images=images, anchors=anchors,
                                          dialogues=[dialogue()] if has_dialogue else [])
    assert record["step"] == step
    assert payload["control_counts"] == {
        "semantic_control_count": len(states), "owned_state_count": len(states),
        "ordinary_reference_count": len(images), "temporal_anchor_count": len(anchors),
        "previous_av_present": capability != "GENERATE",
    }
    assert len(payload["visual_controls"]) == len(states)
    assert payload["visual_controls"][0]["time_seconds"] == 0
    assert prompt.count("dialogue_timeline:") == 1
    assert record["parsed_result"]["dialogue"]["passed"]
    assert record["parsed_result"]["physical_picture"]["passed"]
    assert "Foley" in prompt and "Room tone" in prompt
    assert "CANONICAL SINGLE SPEECH AUTHORITY" in call["system_prompt"]
    for leak in ("RAW_DESCRIPTION", "RAW_VIDEO", "RAW_DIALOGUE", "STALE_ASSIGNMENT",
                 "SECRET_TASK", "STALE_TRANSITION", "stale state dialogue", "obsolete image prompt", "/unexposed.png"):
        assert leak not in call["user_content"]
    assert "description" not in payload["shot"] and "video_description" not in payload["shot"]
    assert "dialogues" not in payload["shot"] and "clip_dialogues" not in payload
    if has_dialogue:
        assert prompt.count("请看这里。") == 1
        assert "D1:\n  speaker: <Subject 1>\n  start_time: 0.5s\n  end_time: 2.0s\n  exact_dialogue: 请看这里。" in prompt
        assert "NO_VOICE:" not in prompt
    else:
        assert "NO_VOICE: no human speech, no human vocalization, no invented dialogue." in prompt
        assert "NO_VOICE is not SILENT_AUDIO" in prompt
    if not images:
        assert "<Picture" not in prompt
        assert all(s["physical_picture"] is None for s in payload["visual_controls"])
    if anchors:
        assert payload["temporal_anchors"] == [{"anchor_id": "A1", "time_seconds": 0,
            "source_keyframe_index": 4, "description": states[0]["description"]}]
        assert "frame_position" not in call["user_content"]
    assert payload["conditioning"]["previous_av_present"] == (capability != "GENERATE")
    assert "shot_continuity_lock:" not in prompt  # Shot guidance cannot override semantic CUT.


@pytest.mark.parametrize("images", [(4,), (5,), (), (4, 5)])
def test_holey_endpoint_mapping(monkeypatch, images):
    prompt, payload, _, record = invoke(monkeypatch, states=SHAPES[1][0], images=images)
    assert record["step"] == "12"
    assert [s["physical_picture_index"] for s in payload["visual_controls"]] == [
        images.index(i) + 1 if i in images else None for i in (4, 5)]
    assert {int(m.group(1)) for m in h3._PICTURE_TOKEN_RE.finditer(prompt)} == set(range(1, len(images) + 1))


def test_t07_holey_multi_controls_and_dense_physical_mapping(monkeypatch):
    states = [state(1, 10, "START"), state(2, 12), state(3, 14), state(4, 18, "END")]
    _, payload, _, record = invoke(monkeypatch, states=states, images=(1, 4))
    assert record["step"] == "13"
    assert [s["physical_picture_index"] for s in payload["visual_controls"]] == [1, None, None, 2]
    assert [s["physical_reference_status"] for s in payload["visual_controls"]] == ["IMAGE_BACKED", "TEXT_ONLY", "TEXT_ONLY", "IMAGE_BACKED"]


def test_temporal_anchor_cannot_turn_one_owned_control_into_multi(monkeypatch):
    anchors = [{"anchor_id": f"A{i}", "time_seconds": i, "source": {"keyframe_index": 4}}
               for i in (1, 2)]
    _, payload, _, record = invoke(monkeypatch, capability="TEMPORAL_EXTEND", anchors=anchors)
    assert record["step"] == "11"
    assert payload["control_counts"]["semantic_control_count"] == 1
    assert payload["control_counts"]["temporal_anchor_count"] == 2


def test_carry_in_and_empty_owned_never_synthesize_raw_control(monkeypatch):
    _, payload, _, _ = invoke(monkeypatch, states=[], extra_clip={"carry_in_state_index": 3})
    assert payload["visual_controls"] == payload["frames"] == payload["keyframes"] == []
    assert payload["control_counts"]["semantic_control_count"] == 0


def test_t05_multiple_speakers_not_assigned_from_picture(monkeypatch):
    lines = [dialogue("Jun", "第一句。", "D1", 10.5, 12), dialogue("Mira", "第二句。", "D2", 13, 15)]
    body = ("subject_definitions:\n<Subject 1> is Mira, the visually prominent figure.\n"
            "<Subject 2> is Jun, further away.\nkeyframe_timeline:\n<Picture 1> anchors KF4.\n"
            "dialogue_timeline:\nD1: speaker: <Subject 1> exact_dialogue: 第一局。\n"
            "summary:\nThe mouth corners of <Subject 1> lift during assigned dialogue D1.\n"
            "detailed_description:\nAssigned event D2 accompanies gaze changes. 第二句。\n"
            "overall_soundscape:\nRoom tone and Foley.")
    prompt, _, _, _ = invoke(monkeypatch, images=(4,), dialogues=lines, body=body)
    assert "D1:\n  speaker: <Subject 2>" in prompt
    assert "D2:\n  speaker: <Subject 1>" in prompt
    assert prompt.count("第一句。") == prompt.count("第二句。") == 1
    assert "第一局。" not in prompt
    assert "exact_dialogue:" not in prompt.split("summary:", 1)[1]


@pytest.mark.parametrize("states,step", SHAPES)
@pytest.mark.parametrize("has_dialogue", [False, True])
def test_canonical_sections_define_subjects_before_deterministic_speech(monkeypatch, states, step, has_dialogue):
    body = ("subject_definitions:\n<Subject 1> is Mira, wearing her current coat.\n"
            "<Subject 2> is Jun, wearing his current costume.\n"
            "official_character_identity_lock:\nKeep both visible identities and costumes stable.\n"
            "keyframe_timeline:\nKF4 starts from <Picture 1>; later states follow the canonical timeline.\n"
            "summary:\nThe two figures hold their positions.\n"
            "detailed_description:\n[Shot 1] Their gaze changes as the camera advances gently.\n"
            "overall_soundscape:\nRoom tone and fabric Foley remain audible.")
    lines = ([dialogue("Jun", "第一句。", "D1", 10.5, 12),
              dialogue("Mira", "第二句。", "D2", 13, 15)] if has_dialogue else [])
    prompt, _, _, record = invoke(monkeypatch, states=states, capability="GENERATE",
                                  images=(4,), dialogues=lines, body=body)
    assert record["step"] == step
    sections = ("subject_definitions:", "official_character_identity_lock:",
                "keyframe_timeline:", "dialogue_timeline:", "summary:",
                "detailed_description:", "overall_soundscape:")
    assert [prompt.index(section) for section in sections] == sorted(prompt.index(section) for section in sections)
    assert record["parsed_result"]["dialogue"]["passed"]
    if has_dialogue:
        assert prompt.index("<Subject 1> is Mira") < prompt.index("D2:\n  speaker: <Subject 1>")
        assert prompt.index("<Subject 2> is Jun") < prompt.index("D1:\n  speaker: <Subject 2>")
        assert prompt.count("第一句。") == prompt.count("第二句。") == 1
        assert "From 2.0s to 3.0s between dialogue events" in prompt
    else:
        assert "NO_VOICE: no human speech, no human vocalization, no invented dialogue." in prompt
    assert "Room tone and fabric Foley remain audible" in prompt


def test_shot_11_shaped_three_semantic_states_keep_one_physical_picture(monkeypatch):
    states = [state(1, 10, "START"), state(2, 12), state(3, 15)]
    body = ("subject_definitions:\n<Subject 1> is 皇帝, facing the mirror.\n"
            "<Subject 2> is 侍从1, standing nearby.\n"
            "official_character_identity_lock:\nKeep their current faces and clothing.\n"
            "keyframe_timeline:\nKF1 at 0s starts from <Picture 1>. KF2 and KF3 are TEXT_ONLY.\n"
            "summary:\nThey stay in the palace dressing room.\n"
            "detailed_description:\n[Shot 1] From 0 to 2s, the emperor inspects a sleeve; "
            "from 2 to 5s, the attendant holds position.\n"
            "overall_soundscape:\nRoom tone and fabric Foley remain audible.")
    lines = [dialogue("皇帝", "袖口是不是太宽了？", "D1", 11, 13),
             dialogue("侍从1", "陛下，这正是今年王城最流行的样式。", "D2", 13.2, 16.95)]
    prompt, payload, _, record = invoke(monkeypatch, states=states, capability="GENERATE",
                                        images=(1,), dialogues=lines, body=body,
                                        shot_characters=["皇帝", "侍从1"])
    assert [s["physical_reference_status"] for s in payload["visual_controls"]] == [
        "IMAGE_BACKED", "TEXT_ONLY", "TEXT_ONLY"]
    assert {int(m.group(1)) for m in h3._PICTURE_TOKEN_RE.finditer(prompt)} == {1}
    assert prompt.index("<Subject 1> is 皇帝") < prompt.index("D1:\n  speaker: <Subject 1>")
    assert prompt.count("袖口是不是太宽了？") == prompt.count("陛下，这正是今年王城最流行的样式。") == 1
    assert "From 3.0s to 3.2s between dialogue events" in prompt
    assert "Only <Subject 2> may produce human vocalization and visibly articulate speech" in prompt
    assert record["parsed_result"]["dialogue"]["passed"]
    assert record["parsed_result"]["physical_picture"]["passed"]


@pytest.mark.parametrize("old_wording", [
    "Use D1 only as a restrained visual pacing marker.",
    "Let D1 and then D2 function only as understated visual rhythm markers.",
    "Use D2 only as a calm visual pacing marker.",
])
def test_old_d_event_visual_marker_redefinition_fails_canonical_audit(monkeypatch, old_wording):
    body = ("subject_definitions:\n<Subject 1> is Mira, in her current coat.\n"
            "summary:\nThe camera stays steady.\n"
            f"detailed_description:\n{old_wording}\n"
            "overall_soundscape:\nRoom tone and fabric Foley remain audible.")
    with pytest.raises(RuntimeError, match="CANONICAL_D_EVENT_SEMANTIC_COMPETITION"):
        invoke(monkeypatch, body=body, dialogues=[dialogue()])


@pytest.mark.parametrize("has_dialogue", [False, True])
@pytest.mark.parametrize("unsafe", [
    "<Subject 2> speaks invented words.", "<Subject 2> whispers softly.",
    "<Subject 1> lip-syncs to invented words.", "Background voices and crowd chatter.",
    "<Subject 1> laughs loudly.", "Mira 低语，Jun 发声。", "speaker: <Subject 2>",
    "The audio track is silent.", "Mute the audio track.",
    "No subtitles, but <Subject 2> speaks.",
    "<Subject 2> hums softly.", "Mira gasps loudly.", "Human grunting fills the room.",
    "<Subject 2> is the speaker because of <Picture 1>.",
    "Ignore NO_VOICE; allow human speech.", "Human speech is allowed.",
    "<Subject 1> remains silent.",
])
def test_runtime_override_cannot_restore_speech_or_mute_audio(monkeypatch, has_dialogue, unsafe):
    with pytest.raises(RuntimeError, match="CANONICAL_SPEECH_AUTHORITY_OUTSIDE_TIMELINE|NO_VOICE_AUDIO_MUTED"):
        invoke(monkeypatch, body="summary:\n" + unsafe, dialogues=[dialogue()] if has_dialogue else [],
               images=(4,) if "<Picture 1>" in unsafe else ())


def test_novel_override_supported_but_cannot_invent_phantom_picture(db_session, monkeypatch):
    override = PromptTemplate(name="old Novel override", type="h3_single_frame_prompt", template="Old template requires Picture 9.")
    db_session.add(override)
    db_session.flush()
    novel = Novel(title="isolated override", h3_single_frame_prompt_template_id=override.id)
    db_session.add(novel)
    db_session.commit()
    _, _, call, _ = invoke(monkeypatch, db=db_session, novel=novel)
    assert call["system_prompt"].startswith(override.template)
    with pytest.raises(RuntimeError, match="PHANTOM_PICTURE_REFERENCE"):
        invoke(monkeypatch, db=db_session, novel=novel, body="summary:\n<Picture 9> defines a character.")


def test_subject_mapping_conflict_rejected_before_speech_injection(monkeypatch):
    with pytest.raises(ValueError, match="Subject mapping conflicts"):
        invoke(monkeypatch, dialogues=[dialogue()], body="subject_definitions:\n<Subject 2> is Mira, visible.")


def test_invalid_positive_dialogue_not_silently_downgraded_to_no_voice(monkeypatch):
    with pytest.raises(ValueError, match="CANONICAL_DIALOGUE_TIMELINE_UNAVAILABLE"):
        invoke(monkeypatch, dialogues=[dialogue(start=0, end=1)])


def test_final_speech_audit_checks_exact_event_subject_and_time():
    item = {"id": "D1", "speaker": "Mira", "text": "一句话。", "start_time": 0.5,
            "end_time": 2.0, "duration_sufficient": True}
    prompt = h3._render_dialogue_timeline_block([item], [], {"Mira": "<Subject 1>"})
    prompt = prompt.replace("speaker: <Subject 1>", "speaker: <Subject 2>")
    audit = h3._audit_final_h3_prompt(prompt, [item], [], {"Mira": "<Subject 1>"}, canonical_visual_body="")
    assert "DIALOGUE_SPEAKER_TIMING_AUTHORITY_INVALID" in audit["blocking_issues"]


def test_single_event_visible_lip_authority_remains_subject_timed_and_exact():
    item = {"id": "D1", "speaker": "Mira", "text": "请看这里。", "start_time": 1.0, "end_time": 3.0}
    prompt = h3._render_dialogue_timeline_block([item], [], {"Mira": "<Subject 1>"})

    assert "D1:\n  speaker: <Subject 1>\n  start_time: 1.0s\n  end_time: 3.0s\n  exact_dialogue: 请看这里。" in prompt
    assert prompt.count("请看这里。") == 1
    assert "All assigned dialogue is Mandarin Chinese only." in prompt
    assert "Only <Subject 1> may produce human vocalization and visibly articulate speech during this event" in prompt
    assert "synchronize this Subject's mouth/lip movement to the exact assigned Mandarin dialogue and event timing" in prompt
    assert "All other Subjects remain non-vocal and must not visibly perform speech-like mouth or lip articulation" in prompt
    assert "Before the first assigned event and after the last, no Subject may visibly perform speech-like mouth or lip articulation" in prompt
    assert "Natural breathing, blinking, facial expression, jaw relaxation and non-speech facial movement remain allowed" in prompt


def test_shot_11_shaped_visible_lip_handoff_and_dialogue_gap():
    events = [
        {"id": "D1", "speaker": "皇帝", "text": "袖口是不是太宽了？", "start_time": 1.0, "end_time": 3.0},
        {"id": "D2", "speaker": "侍从1", "text": "陛下，这正是今年王城最流行的样式。", "start_time": 3.2, "end_time": 6.95},
    ]
    prompt = h3._render_dialogue_timeline_block(
        events, [], {"皇帝": "<Subject 1>", "侍从1": "<Subject 2>"},
    )

    d1 = prompt.split("D1:\n", 1)[1].split("From 3.0s to 3.2s between dialogue events", 1)[0]
    d2 = prompt.split("D2:\n", 1)[1]
    assert "speaker: <Subject 1>\n  start_time: 1.0s\n  end_time: 3.0s" in d1
    assert "Only <Subject 1> may produce human vocalization and visibly articulate speech" in d1
    assert "speaker: <Subject 2>\n  start_time: 3.2s\n  end_time: 6.95s" in d2
    assert "Only <Subject 2> may produce human vocalization and visibly articulate speech" in d2
    assert "From 3.0s to 3.2s between dialogue events, no Subject may visibly perform speech-like mouth or lip articulation." in prompt
    assert prompt.count("袖口是不是太宽了？") == prompt.count("陛下，这正是今年王城最流行的样式。") == 1


def test_zero_dialogue_restricts_visible_speech_without_muting_foley():
    prompt = h3._render_dialogue_timeline_block([], ["Mira"], {"Mira": "<Subject 1>"})

    assert "NO_VOICE: no human speech, no human vocalization, no invented dialogue." in prompt
    assert "No Subject may visibly perform speech-like mouth or lip articulation throughout this clip" in prompt
    assert "natural breathing, blinking, facial expression, jaw relaxation and non-speech facial movement remain allowed" in prompt
    assert "silent_characters: <Subject 1>" in prompt
    assert "NO_VOICE is not SILENT_AUDIO" in prompt
    assert "environmental ambience and synchronized Foley remain audible" in prompt


def test_visual_expressions_and_nonhuman_audio_are_not_speech_authority(monkeypatch):
    prompt, _, _, record = invoke(monkeypatch, body="summary:\n微笑，皱眉，嘴角变化，咬紧牙关，视线变化，身体前倾，转身，姿态，手势。\noverall_soundscape:\nAn engine hums; birds sing; a pig grunts. Wind and cloth Foley remain audible.")
    assert "An engine hums" in prompt
    assert record["parsed_result"]["dialogue"]["passed"]


SAFE_SOUNDSCAPE_REFERENCES = [
    "环境中只有脚步声和衣料摩擦",
    "非人声结构回响",
    "除时间线中的对白外，不得出现其他人声",
    "不得出现背景人声",
    "无额外说话者",
    "对白保持前景清晰，环境声较低",
    "前景人声之外的声响保持与距离、材质和可见动作一致",
    "no extra voices",
    "no background speech",
    "dialogue remains foreground",
    "No background voices",
]

UNSAFE_SPEECH_ASSERTIONS = [
    "背景有人声",
    "远处传来人声",
    "背景有人低声交谈",
    "侍从在远处说话",
    "人群传来交谈声",
    "皇帝继续说话",
    "画外有人回应",
    "前景有人声",
    "背景传来对话",
    "有人低声说话",
    "background chatter",
    "off-screen reply",
    "background voices",
    "没有回答问题，他继续说话",
    "没有背景音乐，但人群继续交谈",
    "禁止音乐，画外有人回应",
    "no music, but background chatter continues",
    "no footsteps; off-screen reply follows",
    "no music and background chatter continues",
    "没有背景音乐并有人说话",
]


@pytest.mark.parametrize("phrase", SAFE_SOUNDSCAPE_REFERENCES)
@pytest.mark.parametrize("has_dialogue", [False, True])
def test_safe_soundscape_reference_is_projected_to_non_speech_audio(monkeypatch, phrase, has_dialogue):
    body = f"summary:\nVisual movement continues.\noverall_soundscape:\n{phrase}；衣料摩擦与脚步声保持可听。"
    prompt, _, _, record = invoke(monkeypatch, body=body, dialogues=[dialogue()] if has_dialogue else [])
    soundscape = prompt.split("overall_soundscape:\n", 1)[1]
    assert "衣料摩擦与脚步声保持可听" in soundscape
    assert not h3._canonical_visual_body_speech_issues(soundscape)
    assert record["parsed_result"]["dialogue"]["passed"]
    if has_dialogue:
        assert prompt.count("请看这里。") == 1
    else:
        assert "NO_VOICE: no human speech, no human vocalization, no invented dialogue." in prompt


@pytest.mark.parametrize("phrase", UNSAFE_SPEECH_ASSERTIONS)
@pytest.mark.parametrize("has_dialogue", [False, True])
def test_assertive_speech_cannot_be_sanitized_into_success(monkeypatch, phrase, has_dialogue):
    body = f"summary:\nVisual movement continues.\noverall_soundscape:\n{phrase}；衣料摩擦与脚步声保持可听。"
    projected = h3._project_canonical_soundscape(body)
    assert phrase in projected  # Do not hide a contract violation by deleting its speech event.
    with pytest.raises(RuntimeError, match="CANONICAL_SPEECH_AUTHORITY_OUTSIDE_TIMELINE"):
        invoke(monkeypatch, body=body, dialogues=[dialogue()] if has_dialogue else [])


def test_shot_11_soundscape_preserves_non_speech_meaning(monkeypatch):
    body = ("summary:\nVisual movement continues.\noverall_soundscape:\n"
            "空间声场随摄影机的轻微推进而自然变化，前景人声之外的声响保持与距离、材质和可见动作一致，"
            "不额外添加音乐或与场景无关的声源。")
    prompt, _, _, record = invoke(monkeypatch, body=body, dialogues=[dialogue()])
    soundscape = prompt.split("overall_soundscape:\n", 1)[1]
    for fragment in ("空间声场", "距离", "材质", "可见动作", "音乐", "无关的声源"):
        assert fragment in soundscape
    assert "前景人声" not in soundscape
    assert record["parsed_result"]["dialogue"]["passed"]


@pytest.mark.parametrize("states,step", SHAPES)
def test_canonical_h3_excludes_explicit_internal_self_check_tail(monkeypatch, states, step):
    body = ("subject_definitions:\n<Subject 1> is Mira, in her current coat.\n"
            "<Subject 2> is Jun, in his current costume.\n"
            "keyframe_timeline:\n<Picture 1> anchors KF4.\n"
            "summary:\nTheir gaze and posture change.\n"
            "detailed_description:\nCamera advances gently.\n"
            "overall_soundscape:\n非人声结构回响，脚步声和衣料摩擦保持可听。\n\n"
            "【输出前内部自检】\n"
            "- 未定义发声、静音或口型规则。\n"
            "- <Picture 9> 是自检说明，不是物理参考。")
    lines = [dialogue("Mira", "请看这里。", "D1", 10.5, 12),
             dialogue("Jun", "第二句。", "D2", 13, 15)]
    prompt, _, _, record = invoke(monkeypatch, states=states, capability="GENERATE",
                                  images=(4,), dialogues=lines, body=body)
    assert record["step"] == step
    assert record["response"] == body  # Raw diagnostic output remains intact.
    assert "【输出前内部自检】" not in prompt
    assert "未定义发声、静音或口型规则" not in prompt
    assert "<Picture 9>" not in prompt
    assert "非人声结构回响" in prompt
    assert prompt.count("请看这里。") == prompt.count("第二句。") == 1
    assert {int(m.group(1)) for m in h3._PICTURE_TOKEN_RE.finditer(prompt)} == {1}
    assert record["parsed_result"]["dialogue"]["passed"]
    assert record["parsed_result"]["physical_picture"]["passed"]


@pytest.mark.parametrize("speech", ["皇帝继续说话", "背景传来对话", "画外有人回应"])
def test_internal_self_check_boundary_does_not_hide_executable_speech(monkeypatch, speech):
    body = (f"summary:\n{speech}。\noverall_soundscape:\n非人声结构回响。\n"
            "【输出前内部自检】\n- 未定义发声、静音或口型规则。")
    with pytest.raises(RuntimeError, match="CANONICAL_SPEECH_AUTHORITY_OUTSIDE_TIMELINE"):
        invoke(monkeypatch, body=body)


@pytest.mark.parametrize("soundscape", [
    "前景人声之外的声响保持与距离一致，画外有人回应。",
    "No background voices; background chatter continues.",
])
def test_safe_reference_cannot_mask_assertive_speech_in_same_soundscape(monkeypatch, soundscape):
    body = "summary:\nVisual movement continues.\noverall_soundscape:\n" + soundscape
    assert h3._project_canonical_soundscape(body) == body
    with pytest.raises(RuntimeError, match="CANONICAL_SPEECH_AUTHORITY_OUTSIDE_TIMELINE"):
        invoke(monkeypatch, body=body, dialogues=[dialogue()])


@pytest.mark.parametrize("states,step", SHAPES)
def test_soundscape_boundary_covers_all_canonical_h3_routes(monkeypatch, states, step):
    body = "summary:\nVisual movement continues.\noverall_soundscape:\n无额外说话者，脚步声可听。"
    prompt, _, _, record = invoke(monkeypatch, states=states, body=body, dialogues=[dialogue()])
    assert record["step"] == step
    assert "脚步声可听" in prompt
    with pytest.raises(RuntimeError, match="CANONICAL_SPEECH_AUTHORITY_OUTSIDE_TIMELINE"):
        invoke(monkeypatch, states=states, body=body.replace("无额外说话者", "画外有人回应"), dialogues=[dialogue()])


def test_soundscape_projection_does_not_hide_visual_section_speech(monkeypatch):
    body = "summary:\n皇帝继续说话。\noverall_soundscape:\n前景人声之外的声响保持与距离一致。"
    with pytest.raises(RuntimeError, match="CANONICAL_SPEECH_AUTHORITY_OUTSIDE_TIMELINE"):
        invoke(monkeypatch, body=body, dialogues=[dialogue()])


def test_visual_response_without_speech_remains_allowed(monkeypatch):
    prompt, _, _, record = invoke(monkeypatch, body="summary:\n<Subject 1> 点头回应他的视线。\noverall_soundscape:\n脚步声和衣料摩擦。")
    assert "点头回应他的视线" in prompt
    assert record["parsed_result"]["dialogue"]["passed"]


@pytest.mark.parametrize("text", [
    "不新增音乐、突发声源或画面外事件",
    "避免突发声源",
    "没有突发声源",
    "环境中不得加入突发声源",
])
def test_sudden_sound_source_is_not_speech_authority(text):
    assert h3._canonical_visual_body_speech_issues(text) == []


@pytest.mark.parametrize("text", [
    "人物发声",
    "骗子1发声",
    "角色突然发声",
    "有人发声",
    "画外人声",
    "新增人声",
    "人物开口说话",
    "角色说道",
    "角色回答",
])
def test_explicit_human_speech_remains_outside_visual_authority(text):
    assert h3._canonical_visual_body_speech_issues(text) == [
        "CANONICAL_SPEECH_AUTHORITY_OUTSIDE_TIMELINE"
    ]


@pytest.mark.parametrize("states,step,template_type,attribute", [
    (SHAPES[0][0], "11", "h3_single_frame_prompt", "h3_single_frame_prompt_template_id"),
    (SHAPES[1][0], "12", "h3_first_last_frame_prompt", "h3_first_last_frame_prompt_template_id"),
    (SHAPES[2][0], "13", "h3_multi_keyframe_prompt", "h3_multi_keyframe_prompt_template_id"),
])
def test_novel_override_still_uses_runtime_soundscape_boundary(db_session, monkeypatch, states, step, template_type, attribute):
    override = PromptTemplate(name="old Novel override", type=template_type,
                              template="Old speech rules allow background chatter.")
    db_session.add(override)
    db_session.flush()
    novel = Novel(title="isolated override", **{attribute: override.id})
    db_session.add(novel)
    db_session.commit()
    prompt, _, call, record = invoke(monkeypatch, db=db_session, novel=novel, states=states,
                                     body="summary:\nVisual movement.\noverall_soundscape:\nNo background voices; footsteps remain audible.")
    assert record["step"] == step
    assert call["system_prompt"].startswith(override.template)
    assert "NO_VOICE: no human speech" in prompt
    assert "footsteps remain audible" in prompt
    meta_body = ("summary:\nVisual movement.\noverall_soundscape:\n非人声结构回响。\n"
                 "【输出前内部自检】\n- 未定义发声、静音或口型规则。")
    prompt, _, call, record = invoke(monkeypatch, db=db_session, novel=novel,
                                     states=states, body=meta_body)
    assert call["system_prompt"].startswith(override.template)
    assert record["response"] == meta_body
    assert "非人声结构回响" in prompt
    assert "【输出前内部自检】" not in prompt
    assert "未定义发声、静音或口型规则" not in prompt
    with pytest.raises(RuntimeError, match="CANONICAL_SPEECH_AUTHORITY_OUTSIDE_TIMELINE"):
        invoke(monkeypatch, db=db_session, novel=novel, states=states,
               body="summary:\nVisual movement.\noverall_soundscape:\nbackground chatter.")
    ordered_body = ("subject_definitions:\n<Subject 1> is Mira, in her current coat.\n"
                    "<Subject 2> is Jun, in his current costume.\n"
                    "keyframe_timeline:\nThe current state develops visually.\n"
                    "summary:\nTheir gaze shifts.\n"
                    "detailed_description:\n[Shot 1] Mira turns toward the mirror.\n"
                    "overall_soundscape:\nFootsteps and fabric Foley remain audible.")
    prompt, _, call, record = invoke(monkeypatch, db=db_session, novel=novel,
                                     states=states, body=ordered_body, dialogues=[dialogue()])
    assert call["system_prompt"].startswith(override.template)
    assert prompt.index("<Subject 1> is Mira") < prompt.index("dialogue_timeline:") < prompt.index("summary:")
    assert record["parsed_result"]["dialogue"]["passed"]
    assert prompt.count("请看这里。") == 1


@pytest.mark.parametrize("missing", ["previous_av", "temporal_anchor"])
def test_f01_f02_canonical_temporal_errors_remain_blocking(missing):
    shot = SimpleNamespace(id="compiler-shot", duration=18, image_url="/shot.png")
    plan = {"canonical_visual_plan": True, "clip_plan_revision": 1, "keyframes": [state(4, 12)]}
    clip = {"clip_index": 2, "start_time": 10, "end_time": 18,
            "visual_state_indexes": [4], "carry_in_state_index": 3,
            "capability": "TEMPORAL_EXTEND", "continuity_to_previous": "CONTINUOUS",
            "requires_temporal_control": True, "previous_clip_index": 1}
    previous = {"clip_index": 1, "clip_plan_revision": 1,
                "generated_by_task_id": "exact-task", "result_url": "/exact-clip.mp4"}
    anchors = [{"anchor_id": "A1", "time_seconds": 2,
                "image_url": "/anchor.png", "source": {"type": "KEYFRAME", "keyframe_index": 4}}]
    code = "PREVIOUS_AV_UNAVAILABLE" if missing == "previous_av" else "TEMPORAL_ANCHOR_UNAVAILABLE"
    with pytest.raises(ClipExecutionCompileError, match=code):
        compile_temporal_extend_clip(shot, plan, clip, 1,
            None if missing == "previous_av" else previous,
            [] if missing == "temporal_anchor" else anchors)


def test_f03_cut_generate_cannot_use_later_image_or_shot_fallback():
    shot = SimpleNamespace(id="compiler-shot", duration=18, image_url="/shot.png")
    plan = {"canonical_visual_plan": True, "clip_plan_revision": 1,
            "keyframes": [{"index": 4, "role": "INTERMEDIATE", "time_seconds": 10}, state(5, 18)]}
    clip = {"clip_index": 2, "start_time": 10, "end_time": 18,
            "capability": "GENERATE", "continuity_to_previous": "CUT", "visual_state_indexes": [4, 5]}
    with pytest.raises(ClipExecutionCompileError) as failure:
        compile_generate_clip(shot, plan, clip, 1)
    assert failure.value.detail["code"] == "GENERATE_VISUAL_START_GROUNDING_MISSING"
    assert failure.value.detail["visual_state_index"] == 4
